import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getHistory, listSessions, search, type SearchResponse } from "@/api/endpoints";
import { streamChat } from "@/api/sse";
import { queryKeys } from "@/lib/queryKeys";

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

  const abortRef = useRef<AbortController | null>(null);

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
    abort();
    setStreaming(false);
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
  }, [abort]);

  const selectSession = useCallback(
    async (id: string) => {
      if (id === activeId) return;
      abort();
      setStreaming(false);
      setActiveId(id);
      setMessages([]);
      setSources({ status: "idle" });
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

  const send = useCallback(
    async (query: string) => {
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

      // Sources lookup runs in parallel with the token stream — never blocks it.
      runSourcesSearch(text, controller.signal);

      const appendToken = (token: string) =>
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + token } : m,
          ),
        );

      try {
        await streamChat({
          sessionId,
          query: text,
          title: isNew ? deriveTitle(text) : undefined,
          signal: controller.signal,
          onToken: appendToken,
          onError: (err) =>
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, status: "error", error: err.message }
                  : m,
              ),
            ),
        });
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
        if (isNew) void qc.invalidateQueries({ queryKey: queryKeys.sessions });
      }
    },
    [activeId, isStreaming, qc, runSourcesSearch],
  );

  return {
    sessions: sessionsQuery.data ?? [],
    sessionsLoading: sessionsQuery.isLoading,
    activeId,
    messages,
    isStreaming,
    loadingHistory,
    sources,
    send,
    stop,
    selectSession,
    newConversation,
  };
}
