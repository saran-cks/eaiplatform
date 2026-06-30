/** Centralized TanStack Query keys — keep cache invalidation consistent. */

export const queryKeys = {
  sessions: ["sessions"] as const,
  history: (sessionId: string) => ["history", sessionId] as const,
  search: (query: string, limit: number) => ["search", query, limit] as const,
  artifacts: (agentSessionId: string) => ["artifacts", agentSessionId] as const,
  artifact: (fileId: string) => ["artifact", fileId] as const,
  traces: (limit: number, sessionId?: string) =>
    ["traces", limit, sessionId ?? null] as const,
  evals: (limit: number) => ["evals", limit] as const,
  datasets: ["datasets"] as const,
  drift: ["drift"] as const,
};
