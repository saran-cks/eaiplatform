import { useState } from "react";

import { cn } from "@/lib/utils";

import type { ActionStep } from "./useConversation";

const KIND_GLYPH: Record<ActionStep["kind"], string> = {
  thought: "·",
  worker: "▸",
  synthesis: "∴",
};

function StepRow({ step }: { step: ActionStep }) {
  const active = step.status === "active";
  return (
    <li className="flex items-baseline gap-2 py-0.5">
      <span className={cn("font-accent text-xs", active ? "text-accent" : "text-muted-foreground")}>
        {KIND_GLYPH[step.kind]}
      </span>
      <span className="text-xs text-foreground">{step.label}</span>
      {step.detail && (
        <span className="text-[0.7rem] text-muted-foreground">— {step.detail}</span>
      )}
      {active && <span className="block-caret text-muted-foreground" />}
    </li>
  );
}

/**
 * Ephemeral agent activity ticker. While the run is live it streams the *current*
 * action on a single transient line just above the composer (no multi-step box);
 * once the run completes the line fades and collapses under a `›` drilldown that
 * re-expands the full trace, so the transcript stays clean (DD-19 / F3).
 */
export function ActionStream({ steps, active }: { steps: ActionStep[]; active: boolean }) {
  const [open, setOpen] = useState(false);
  if (steps.length === 0) return null;

  if (active) {
    // The action in flight: the latest still-active step, else the most recent.
    const current =
      [...steps].reverse().find((s) => s.status === "active") ?? steps[steps.length - 1];
    return (
      <div className="mx-auto flex w-full max-w-3xl items-baseline gap-2 px-4 py-1">
        <span className="font-accent text-xs text-accent">{KIND_GLYPH[current.kind]}</span>
        <span className="min-w-0 truncate text-xs text-foreground">{current.label}</span>
        {current.detail && (
          <span className="min-w-0 truncate text-[0.7rem] text-muted-foreground">
            — {current.detail}
          </span>
        )}
        <span className="block-caret text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-1 opacity-70 transition-opacity hover:opacity-100">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="font-accent text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        {open ? "▾" : "›"} {steps.length} agent step{steps.length === 1 ? "" : "s"}
      </button>
      {open && (
        <ul className="mt-1 border-l border-border pl-3">
          {steps.map((s) => (
            <StepRow key={s.id} step={s} />
          ))}
        </ul>
      )}
    </div>
  );
}
