import { listArtifacts, type ArtifactOut } from "@/api/endpoints";
import { mockListArtifacts } from "@/api/mockArtifacts";
import { env } from "@/lib/env";

/**
 * Fetch an agent run's artifacts, choosing the mock seam or the live endpoint by
 * `env.mockAgent`. Shared by the ConversationView existence-gate (whether to show
 * the `⌗ artifacts` affordance) and the ArtifactViewer itself, so both hit the
 * same TanStack Query key (`queryKeys.artifacts`) — the viewer opens on a cache hit.
 */
export function fetchArtifacts(
  agentSessionId: string,
  signal?: AbortSignal,
): Promise<ArtifactOut[]> {
  return env.mockAgent ? mockListArtifacts() : listArtifacts(agentSessionId, signal);
}
