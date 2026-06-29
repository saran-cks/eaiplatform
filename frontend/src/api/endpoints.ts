import type { components } from "./generated/types";
import { apiFetch } from "./client";

/**
 * Typed wrappers over the non-SSE Core API surface. Request/response types come
 * straight from the backend OpenAPI (`./generated/types.ts`, regenerated via
 * `npm run gen:api`) so they can never drift from the server. The two SSE
 * endpoints live in `./sse.ts`, not here.
 */

type Schemas = components["schemas"];

export type SessionOut = Schemas["SessionOut"];
export type HistoryOut = Schemas["HistoryOut"];
export type SearchResponse = Schemas["SearchResponse"];
export type ArtifactOut = Schemas["ArtifactOut"];
export type ListOut = Schemas["ListOut"];
export type DriftOut = Schemas["DriftOut"];
export type FeedbackRequest = Schemas["FeedbackRequest"];
export type FeedbackAck = Schemas["FeedbackAck"];

// --- Chat sessions ---------------------------------------------------------
export const createSession = (signal?: AbortSignal) =>
  apiFetch<SessionOut>("/chat", { method: "POST", signal });

export const listSessions = (signal?: AbortSignal) =>
  apiFetch<SessionOut[]>("/chat", { signal });

export const getHistory = (sessionId: string, signal?: AbortSignal) =>
  apiFetch<HistoryOut>(`/chat/${encodeURIComponent(sessionId)}/history`, { signal });

// --- Search ----------------------------------------------------------------
export const search = (query: string, limit = 5, signal?: AbortSignal) =>
  apiFetch<SearchResponse>("/search", { query: { query, limit }, signal });

// --- Agent artifacts -------------------------------------------------------
export const listArtifacts = (agentSessionId: string, signal?: AbortSignal) =>
  apiFetch<ArtifactOut[]>(
    `/agent/${encodeURIComponent(agentSessionId)}/artifacts`,
    { signal },
  );

export const getArtifact = (fileId: string, signal?: AbortSignal) =>
  apiFetch<ArtifactOut>(`/agent/artifacts/${encodeURIComponent(fileId)}`, { signal });

export const interruptAgent = (agentSessionId: string, signal?: AbortSignal) =>
  apiFetch<{ status: string }>(
    `/agent/${encodeURIComponent(agentSessionId)}/interrupt`,
    { method: "POST", signal },
  );

// --- Observability + feedback ---------------------------------------------
export const getTraces = (limit = 50, sessionId?: string, signal?: AbortSignal) =>
  apiFetch<ListOut>("/observability/traces", {
    query: { limit, session_id: sessionId },
    signal,
  });

export const getEvals = (limit = 50, signal?: AbortSignal) =>
  apiFetch<ListOut>("/observability/evals", { query: { limit }, signal });

export const getDatasets = (signal?: AbortSignal) =>
  apiFetch<ListOut>("/observability/datasets", { signal });

export const getDrift = (signal?: AbortSignal) =>
  apiFetch<DriftOut>("/observability/drift", { signal });

export const postFeedback = (body: FeedbackRequest, signal?: AbortSignal) =>
  apiFetch<FeedbackAck>("/feedback", { method: "POST", body, signal });
