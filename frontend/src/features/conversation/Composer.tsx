import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

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

/** Tallest the box grows before it starts scrolling internally (px). */
const MAX_HEIGHT = 240;

/** Query box + chat/agent mode toggle. The textarea auto-grows with its content
 *  so the whole draft stays visible; the circular `>>` button sends. In agent
 *  mode the live actions stream on a single line above the composer (ActionStream). */
export function Composer({ mode, onModeChange, onSubmit, onStop, isStreaming }: ComposerProps) {
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  const canSend = text.trim().length > 0 && !isStreaming;

  // Grow the textarea to fit its content (capped at MAX_HEIGHT, then it scrolls).
  useLayoutEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

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
    <div className="px-4 pb-4 pt-2">
      <div className="mx-auto w-full max-w-3xl rounded-2xl border border-border bg-surface shadow-lg">
        <div className="px-3 pt-2">
          <div className="flex items-center gap-1">
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
          </div>
        </div>
        <div className="flex items-end gap-2 px-3 pb-3 pt-2">
          <textarea
            ref={taRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="ask anything — Enter to send, Shift+Enter for newline"
            className="min-h-9 flex-1 resize-none overflow-y-auto bg-transparent px-1 py-2 font-body text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 [scrollbar-color:hsl(var(--border))_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-border/40 [&::-webkit-scrollbar-track]:bg-transparent"
          />
          {isStreaming ? (
            <Button
              variant="destructive"
              size="icon"
              onClick={onStop}
              aria-label="stop"
              className="shrink-0 rounded-full"
            >
              <span className="text-xs leading-none">{"■"}</span>
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={submit}
              disabled={!canSend}
              aria-label="send"
              className="shrink-0 rounded-full font-accent"
            >
              <span className="leading-none tracking-tighter">{">>"}</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
