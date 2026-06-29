import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

import { Markdown } from "./Markdown";
import type { ChatMessage } from "./useConversation";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  loadingHistory: boolean;
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
      <h2 className="font-accent text-base text-foreground">Welcome! Curious Mind!</h2>
      <p className="max-w-sm whitespace-pre-line text-sm text-muted-foreground">
        {"You're early and most people are still searching.\nThe room gets quiet when you have the answer.\nAnd even quieter when you've already acted on it."}
      </p>
      <span className="block-caret text-muted-foreground" />
    </div>
  );
}

/** Scrolling transcript. Auto-sticks to the bottom as tokens arrive. */
export function MessageList({ messages, isStreaming, loadingHistory }: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  if (loadingHistory) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">loading history…</p>
      </div>
    );
  }

  if (messages.length === 0) return <EmptyState />;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6">
      {messages.map((m) => {
        const isUser = m.role === "user";
        const isStreamingThis = m.status === "streaming";
        return (
          <div
            key={m.id}
            className={cn("flex flex-col gap-1", isUser ? "items-end" : "items-start")}
          >
            <span className="font-accent text-[0.65rem] uppercase tracking-wider text-muted-foreground">
              {isUser ? "you" : "assistant"}
            </span>
            <div
              className={cn(
                "max-w-full rounded-md px-3 py-2",
                isUser
                  ? "bg-muted text-foreground"
                  : "border border-border bg-surface text-foreground",
                m.status === "error" && "border-destructive",
              )}
            >
              {isUser ? (
                <p className="whitespace-pre-wrap text-sm">{m.content}</p>
              ) : (
                <>
                  {m.content ? (
                    <Markdown content={m.content} />
                  ) : (
                    isStreamingThis && (
                      <span className="block-caret text-muted-foreground" />
                    )
                  )}
                  {m.content && isStreamingThis && (
                    <span className="block-caret" />
                  )}
                  {m.status === "error" && (
                    <p className="mt-1 text-xs text-destructive">
                      stream error: {m.error}
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}
      {/* keep a stable anchor so the streaming caret stays in view */}
      <div ref={endRef} aria-hidden className={cn(isStreaming && "h-2")} />
    </div>
  );
}
