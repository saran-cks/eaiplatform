import { Suspense, lazy, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/lib/queryKeys";

import { ActionStream } from "./ActionStream";
import { fetchArtifacts } from "./artifacts";
import { Composer, type Mode } from "./Composer";
import { HistorySidebar } from "./HistorySidebar";
import { MessageList } from "./MessageList";
import { SourcesPanel } from "./SourcesPanel";
import { useConversation } from "./useConversation";

// The Monaco editor is heavy — split it into its own chunk, only fetched when a
// user actually opens the artifacts of an agent run.
const ArtifactViewer = lazy(() =>
  import("./ArtifactViewer").then((m) => ({ default: m.ArtifactViewer })),
);

/**
 * Unified conversation surface (F2: chat mode). Three columns — history rail,
 * transcript + composer, sources panel. The composer's mode toggle exposes
 * agent mode but it stays gated until F3 (named-event stream + ActionStream).
 */
export function ConversationView() {
  const [mode, setMode] = useState<Mode>("chat");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [artifactsOpen, setArtifactsOpen] = useState(false);
  const {
    sessions,
    sessionsLoading,
    activeId,
    messages,
    isStreaming,
    loadingHistory,
    sources,
    actionSteps,
    agentSessionId,
    send,
    stop,
    selectSession,
    newConversation,
  } = useConversation();

  // Only surface the artifacts affordance when the run actually produced files.
  // Runs once the stream finishes; shares the viewer's query key (cache hit on open).
  const { data: artifacts } = useQuery({
    queryKey: queryKeys.artifacts(agentSessionId ?? "none"),
    queryFn: ({ signal }) => fetchArtifacts(agentSessionId as string, signal),
    enabled: Boolean(agentSessionId) && !isStreaming,
  });
  const hasArtifacts = (artifacts?.length ?? 0) > 0;

  return (
    <div className="flex h-full min-h-0">
      <HistorySidebar
        sessions={sessions}
        isLoading={sessionsLoading}
        activeId={activeId}
        onSelect={(id) => void selectSession(id)}
        onNew={newConversation}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((v) => !v)}
      />
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            loadingHistory={loadingHistory}
          />
        </div>
        <ActionStream steps={actionSteps} active={isStreaming && mode === "agent"} />
        {agentSessionId && hasArtifacts && (
          <div className="mx-auto w-full max-w-3xl px-4 pb-1">
            <button
              type="button"
              onClick={() => setArtifactsOpen(true)}
              className="font-accent text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              ⌗ artifacts
            </button>
          </div>
        )}
        <Composer
          mode={mode}
          onModeChange={setMode}
          onSubmit={(text) => void send(text, mode)}
          onStop={stop}
          isStreaming={isStreaming}
        />
      </section>
      <SourcesPanel
        sources={sources}
        open={sourcesOpen}
        onToggle={() => setSourcesOpen((v) => !v)}
      />
      {artifactsOpen && agentSessionId && (
        <Suspense fallback={null}>
          <ArtifactViewer
            agentSessionId={agentSessionId}
            onClose={() => setArtifactsOpen(false)}
          />
        </Suspense>
      )}
    </div>
  );
}
