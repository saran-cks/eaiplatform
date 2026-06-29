import { useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type Mode = "chat" | "agent";

interface ComposerProps {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onSubmit: (text: string) => void;
  onStop: () => void;
  isStreaming: boolean;
}

const MODES: { value: Mode; label: string }[] = [
  { value: "chat", label: "chat" },
  { value: "agent", label: "agent" },
];

/** Query box + chat/agent mode toggle. Agent mode is gated until F3. */
export function Composer({ mode, onModeChange, onSubmit, onStop, isStreaming }: ComposerProps) {
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  const agentDisabled = mode === "agent";
  const canSend = text.trim().length > 0 && !isStreaming && !agentDisabled;

  const submit = () => {
    if (!canSend) return;
    onSubmit(text.trim());
    setText("");
    taRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-border bg-surface">
      <div className="mx-auto w-full max-w-3xl px-4 py-3">
        <div className="mb-2 flex items-center gap-1">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => onModeChange(m.value)}
              className={cn(
                "rounded-md px-2 py-0.5 font-accent text-xs lowercase transition-colors",
                m.value === mode
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {m.label}
            </button>
          ))}
          {agentDisabled && (
            <span className="ml-1 text-xs text-muted-foreground">
              agent mode lands in F3
            </span>
          )}
        </div>
        <div className="flex items-end gap-2">
          <textarea
            ref={taRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder={
              agentDisabled ? "agent mode coming soon…" : "ask anything — Enter to send, Shift+Enter for newline"
            }
            disabled={agentDisabled}
            className="max-h-40 min-h-9 flex-1 resize-y rounded-md border border-border bg-background px-3 py-2 font-body text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          />
          {isStreaming ? (
            <Button variant="destructive" onClick={onStop}>
              stop
            </Button>
          ) : (
            <Button onClick={submit} disabled={!canSend}>
              send
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
