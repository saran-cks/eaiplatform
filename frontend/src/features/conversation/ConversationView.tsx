import { useState } from "react";

import { Composer, type Mode } from "./Composer";
import { HistorySidebar } from "./HistorySidebar";
import { MessageList } from "./MessageList";
import { SourcesPanel } from "./SourcesPanel";
import { useConversation } from "./useConversation";

/**
 * Unified conversation surface (F2: chat mode). Three columns — history rail,
 * transcript + composer, sources panel. The composer's mode toggle exposes
 * agent mode but it stays gated until F3 (named-event stream + ActionStream).
 */
export function ConversationView() {
  const [mode, setMode] = useState<Mode>("chat");
  const {
    sessions,
    sessionsLoading,
    activeId,
    messages,
    isStreaming,
    loadingHistory,
    sources,
    send,
    stop,
    selectSession,
    newConversation,
  } = useConversation();

  return (
    <div className="flex h-full min-h-0">
      <HistorySidebar
        sessions={sessions}
        isLoading={sessionsLoading}
        activeId={activeId}
        onSelect={(id) => void selectSession(id)}
        onNew={newConversation}
      />
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            loadingHistory={loadingHistory}
          />
        </div>
        <Composer
          mode={mode}
          onModeChange={setMode}
          onSubmit={(text) => void send(text)}
          onStop={stop}
          isStreaming={isStreaming}
        />
      </section>
      <SourcesPanel sources={sources} />
    </div>
  );
}
