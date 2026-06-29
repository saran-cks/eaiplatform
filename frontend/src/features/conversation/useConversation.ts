import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { apiUrl, authHeader } from "@/api/client";
import { getHistory, listSessions, search, type SearchResponse } from "@/api/endpoints";
import { mockAgentStream } from "@/api/mockAgent";
import { streamAgent, streamChat, type AgentEvent } from "@/api/sse";
import { queryKeys } from "@/lib/queryKeys";

import type { Mode } from "./Composer";

// Agent backend isn't runnable locally yet — mock unless explicitly disabled.
const MOCK_AGENT = (import.meta.env.VITE_MOCK_AGENT ?? "1") !== "0";

/**
 * Owns the whole chat-mode conversation: the session list, the active session's
 * message log, the live token stream, and the parallel `/search` sources lookup.
 * Agent mode (F3) is intentionally not handled here — the composer gates it.
 */

export type Role = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  status: "done" | "streaming" | "error";
  error?: string;
  /** LLM span id surfaced on the chat SSE (`event: meta`); enables feedback. */
  spanId?: string;
}

export interface ActionStep {
  id: string;
  kind: "thought" | "worker" | "synthesis";
  label: string;
  detail?: string;
  status: "active" | "done";
}

export type SourceChunk = SearchResponse["chunks"][number];

export type SourcesState =
  | { status: "idle" }
  | { status: "loading"; query: string }
  | { status: "ready"; query: string; chunks: SourceChunk[]; fusion: string; reranked: boolean }
  | { status: "error"; query: string; message: string };

function deriveTitle(query: string): string {
  const t = query.trim().replace(/\s+/g, " ");
  return t.length > 60 ? `${t.slice(0, 60)}…` : t;
}

function newId(): string {
  return crypto.randomUUID();
}

export function useConversation() {
  const qc = useQueryClient();

  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setStreaming] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sources, setSources] = useState<SourcesState>({ status: "idle" });
  const [actionSteps, setActionSteps] = useState<ActionStep[]>([]);

  const abortRef = useRef<AbortController | null>(null);
  const agentRunRef = useRef<{ sessionId: string } | null>(null);

  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions,
    queryFn: ({ signal }) => listSessions(signal),
  });

  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  // Abort any in-flight stream when the surface unmounts.
  useEffect(() => abort, [abort]);

  const stop = useCallback(() => {
    // For a live agent run, also tell the server to tear the session down.
    const run = agentRunRef.current;
    if (run && !MOCK_AGENT) {
      void fetch(apiUrl(`/agent/${encodeURIComponent(run.sessionId)}/interrupt`), {
        method: "POST",
        headers: authHeader(),
      }).catch(() => undefined);
    }
    agentRunRef.current = null;
    abort();
    setStreaming(false);
    setActionSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
    setMessages((prev) =>
      prev.map((m) => (m.status === "streaming" ? { ...m, status: "done" } : m)),
    );
  }, [abort]);

  const newConversation = useCallback(() => {
    abort();
    setStreaming(false);
    setActiveId(null);
    setMessages([]);
    setSources({ status: "idle" });
    setActionSteps([]);
  }, [abort]);

  const selectSession = useCallback(
    async (id: string) => {
      if (id === activeId) return;
      abort();
      setStreaming(false);
      setActiveId(id);
      setMessages([]);
      setSources({ status: "idle" });
      setActionSteps([]);
      setLoadingHistory(true);
      try {
        const history = await getHistory(id);
        setMessages(
          history.messages.map((m) => ({
            id: m.message_id,
            role: m.role === "assistant" ? "assistant" : "user",
            content: m.content,
            status: "done",
          })),
        );
      } catch {
        setMessages([]);
      } finally {
        setLoadingHistory(false);
      }
    },
    [abort, activeId],
  );

  const runSourcesSearch = useCallback((query: string, signal: AbortSignal) => {
    setSources({ status: "loading", query });
    search(query, 6, signal)
      .then((res) =>
        setSources({
          status: "ready",
          query,
          chunks: res.chunks,
          fusion: res.fusion,
          reranked: res.reranked,
        }),
      )
      .catch((err: unknown) => {
        if (signal.aborted) return;
        const message = err instanceof Error ? err.message : "search failed";
        setSources({ status: "error", query, message });
      });
  }, []);

  const appendTokenTo = useCallback(
    (assistantId: string, token: string) =>
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: m.content + token } : m,
        ),
      ),
    [],
  );

  const setSpanId = useCallback(
    (assistantId: string, spanId: string) =>
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, spanId } : m)),
      ),
    [],
  );

  const markError = useCallback(
    (assistantId: string, message: string) =>
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, status: "error", error: message } : m,
        ),
      ),
    [],
  );

  // Fold one agent event into the action-step list / answer.
  const handleAgentEvent = useCallback(
    (ev: AgentEvent, assistantId: string) => {
      const d = ev.data as Record<string, unknown>;
      const str = (k: string, fallback = "") =>
        typeof d[k] === "string" ? (d[k] as string) : fallback;
      switch (ev.event) {
        case "thought":
          setActionSteps((p) => [
            ...p,
            { id: newId(), kind: "thought", label: str("text", "thinking…"), status: "done" },
          ]);
          break;
        case "worker_start": {
          const sid = `w:${str("worker_id", newId())}`;
          const label = [str("role", "worker"), str("task")].filter(Boolean).join(" · ");
          setActionSteps((p) => [...p, { id: sid, kind: "worker", label, status: "active" }]);
          break;
        }
        case "worker_done": {
          const sid = `w:${str("worker_id")}`;
          setActionSteps((p) =>
            p.map((s) =>
              s.id === sid ? { ...s, status: "done", detail: str("summary") || s.detail } : s,
            ),
          );
          break;
        }
        case "synthesis":
          setActionSteps((p) => [
            ...p,
            { id: newId(), kind: "synthesis", label: str("text", "synthesizing…"), status: "active" },
          ]);
          break;
        case "output":
          appendTokenTo(assistantId, str("text") || str("token") || str("raw"));
          break;
        case "error":
          markError(assistantId, str("message") || str("raw") || "agent error");
          break;
      }
    },
    [appendTokenTo, markError],
  );

  const send = useCallback(
    async (query: string, mode: Mode = "chat") => {
      const text = query.trim();
      if (!text || isStreaming) return;

      const isNew = activeId === null;
      const sessionId = activeId ?? newId();
      if (isNew) setActiveId(sessionId);

      const assistantId = newId();
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "user", content: text, status: "done" },
        { id: assistantId, role: "assistant", content: "", status: "streaming" },
      ]);

      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(true);

      const onError = (err: Error) => markError(assistantId, err.message);

      try {
        if (mode === "agent") {
          setActionSteps([]);
          agentRunRef.current = { sessionId };
          const run = MOCK_AGENT ? mockAgentStream : streamAgent;
          await run({
            sessionId,
            prompt: text,
            signal: controller.signal,
            onError,
            onEvent: (ev) => handleAgentEvent(ev, assistantId),
          });
        } else {
          // Sources lookup runs in parallel with the token stream — never blocks it.
          runSourcesSearch(text, controller.signal);
          await streamChat({
            sessionId,
            query: text,
            title: isNew ? deriveTitle(text) : undefined,
            signal: controller.signal,
            onToken: (t) => appendTokenTo(assistantId, t),
            onMeta: (meta) => {
              if (meta.span_id) setSpanId(assistantId, meta.span_id);
            },
            onError,
          });
        }
        setActionSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId && m.status === "streaming"
              ? { ...m, status: "done" }
              : m,
          ),
        );
      } finally {
        setStreaming(false);
        abortRef.current = null;
        agentRunRef.current = null;
        if (isNew) void qc.invalidateQueries({ queryKey: queryKeys.sessions });
      }
    },
    [
      activeId,
      isStreaming,
      qc,
      runSourcesSearch,
      appendTokenTo,
      setSpanId,
      markError,
      handleAgentEvent,
    ],
  );

  return {
    sessions: sessionsQuery.data ?? [],
    sessionsLoading: sessionsQuery.isLoading,
    activeId,
    messages,
    isStreaming,
    loadingHistory,
    sources,
    actionSteps,
    send,
    stop,
    selectSession,
    newConversation,
  };
}
