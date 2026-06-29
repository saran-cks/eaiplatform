import {
  EventStreamContentType,
  fetchEventSource,
} from "@microsoft/fetch-event-source";

import { authHeader, apiUrl, ForbiddenError, UnauthorizedError } from "./client";
import { useAuthStore } from "@/store/auth";

/**
 * SSE primitive for the Core API streams. Native EventSource is GET-only, but
 * both chat and agent streams are POST — hence @microsoft/fetch-event-source
 * (DD-19, non-negotiable). Two stream *shapes* are handled here:
 *   - chat  : bare `data: <token>` … terminated by `data: [DONE]`; errors via
 *             `event: error`.
 *   - agent : named events (thought/worker_start/worker_done/synthesis/output/
 *             error/done) each carrying a JSON `data` payload.
 */

const DONE_SENTINEL = "[DONE]";

/** Stop the lib's auto-retry: any error thrown from a callback aborts the stream. */
class FatalStreamError extends Error {}

interface BaseStreamOptions {
  signal?: AbortSignal;
  onError?: (error: Error) => void;
}

function mapHttpError(status: number, detail: string): Error {
  if (status === 401) {
    useAuthStore.getState().clear();
    return new UnauthorizedError(detail);
  }
  if (status === 403) return new ForbiddenError(detail);
  return new FatalStreamError(`SSE ${status}: ${detail}`);
}

async function openStream(
  path: string,
  body: unknown,
  handlers: {
    onMessage: (event: string, data: string) => void;
    signal?: AbortSignal;
    onError?: (error: Error) => void;
  },
): Promise<void> {
  try {
    await fetchEventSource(apiUrl(path), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeader() },
      body: JSON.stringify(body),
      signal: handlers.signal,
      // Don't reconnect when the tab is backgrounded — our streams are finite.
      openWhenHidden: true,
      async onopen(res) {
        const ct = res.headers.get("content-type") ?? "";
        if (res.ok && ct.includes(EventStreamContentType)) return;
        let detail = res.statusText;
        try {
          const parsed = (await res.json()) as { detail?: string };
          if (parsed.detail) detail = parsed.detail;
        } catch {
          // keep statusText
        }
        throw mapHttpError(res.status, detail);
      },
      onmessage(msg) {
        handlers.onMessage(msg.event || "message", msg.data);
      },
      onclose() {
        // Server closed the stream cleanly; stop (don't let the lib reconnect).
        throw new FatalStreamError("__closed__");
      },
      onerror(err) {
        // Rethrow to abort; returning would trigger the default retry loop.
        throw err;
      },
    });
  } catch (err) {
    if (err instanceof FatalStreamError) return; // clean termination
    if (err instanceof DOMException && err.name === "AbortError") return;
    const error = err instanceof Error ? err : new Error(String(err));
    if (handlers.onError) handlers.onError(error);
    else throw error;
  }
}

// ---------------------------------------------------------------------------
// Chat: bare-token stream
// ---------------------------------------------------------------------------
/** Sidecar metadata on the chat stream (`event: meta`) — carries the turn's span id. */
export interface ChatMeta {
  span_id?: string;
}

export interface ChatStreamOptions extends BaseStreamOptions {
  sessionId: string;
  query: string;
  title?: string;
  onToken: (token: string) => void;
  onMeta?: (meta: ChatMeta) => void;
  onDone?: () => void;
}

export async function streamChat({
  sessionId,
  query,
  title,
  onToken,
  onMeta,
  onDone,
  onError,
  signal,
}: ChatStreamOptions): Promise<void> {
  let doneSeen = false;
  await openStream(
    `/chat/${encodeURIComponent(sessionId)}/message`,
    { query, title },
    {
      signal,
      onError,
      onMessage(event, data) {
        if (event === "error") {
          throw new FatalStreamError(data || "chat stream error");
        }
        if (event === "meta") {
          try {
            onMeta?.(JSON.parse(data) as ChatMeta);
          } catch {
            // ignore malformed meta — it never affects the token stream
          }
          return;
        }
        if (data === DONE_SENTINEL) {
          doneSeen = true;
          onDone?.();
          throw new FatalStreamError("__done__");
        }
        onToken(data);
      },
    },
  );
  if (!doneSeen) onDone?.();
}

// ---------------------------------------------------------------------------
// Agent: named-event stream
// ---------------------------------------------------------------------------
export type AgentEventName =
  | "thought"
  | "worker_start"
  | "worker_done"
  | "synthesis"
  | "output"
  | "error"
  | "done";

export interface AgentEvent {
  event: AgentEventName | string;
  data: Record<string, unknown>;
}

export interface AgentStreamOptions extends BaseStreamOptions {
  sessionId: string;
  prompt: string;
  peerAgentIds?: string[];
  onEvent: (event: AgentEvent) => void;
}

export async function streamAgent({
  sessionId,
  prompt,
  peerAgentIds,
  onEvent,
  onError,
  signal,
}: AgentStreamOptions): Promise<void> {
  await openStream(
    `/agent/${encodeURIComponent(sessionId)}/run`,
    { prompt, peer_agent_ids: peerAgentIds ?? [] },
    {
      signal,
      onError,
      onMessage(event, data) {
        let payload: Record<string, unknown> = {};
        if (data) {
          try {
            payload = JSON.parse(data) as Record<string, unknown>;
          } catch {
            payload = { raw: data };
          }
        }
        onEvent({ event, data: payload });
        if (event === "done") throw new FatalStreamError("__done__");
      },
    },
  );
}
