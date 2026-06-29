import { useState } from "react";

import { postFeedback } from "@/api/endpoints";
import { cn } from "@/lib/utils";

type Vote = "up" | "down";

// Thumb glyph + U+FE0E variation selector: forces text-style (monochrome)
// rendering so the emoji inherits the theme text color, never the OS color
// palette.
const GLYPH: Record<Vote, string> = {
  up: "\u{1F44D}︎",
  down: "\u{1F44E}︎",
};

/**
 * Thumbs up/down on an assistant reply, attached to the turn's LLM span via
 * `POST /feedback` (annotator=HUMAN). The span id is surfaced on the chat SSE as
 * an `event: meta` line (#4); replies without one (e.g. cache hits) render no
 * controls.
 */
export function Feedback({ spanId }: { spanId: string }) {
  const [vote, setVote] = useState<Vote | null>(null);
  const [pending, setPending] = useState(false);

  const send = (v: Vote) => {
    if (pending || vote === v) return;
    setPending(true);
    setVote(v);
    void postFeedback({
      span_id: spanId,
      name: "User Feedback",
      label: v === "up" ? "thumbs_up" : "thumbs_down",
      score: v === "up" ? 1 : 0,
    })
      .catch(() => setVote(null))
      .finally(() => setPending(false));
  };

  return (
    <div className="mt-1 flex items-center gap-0.5">
      {(["up", "down"] as const).map((v) => (
        <button
          key={v}
          type="button"
          disabled={pending}
          onClick={() => send(v)}
          aria-label={v === "up" ? "thumbs up" : "thumbs down"}
          aria-pressed={vote === v}
          className={cn(
            "rounded px-1 text-sm leading-none transition-colors hover:text-foreground disabled:cursor-default",
            vote === v ? "text-foreground" : "text-muted-foreground/70",
          )}
        >
          {GLYPH[v]}
        </button>
      ))}
    </div>
  );
}
