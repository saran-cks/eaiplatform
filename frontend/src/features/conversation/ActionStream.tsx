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
 * Ephemeral agent activity ticker. While the run is live it shows each step;
 * once the run completes it fades and collapses under a `›` drilldown so the
 * transcript stays clean but the trace is one click away (DD-19 / F3).
 */
export function ActionStream({ steps, active }: { steps: ActionStep[]; active: boolean }) {
  const [open, setOpen] = useState(false);
  if (steps.length === 0) return null;

  if (!active) {
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

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-2">
      <ul className="rounded-md border border-border bg-surface/60 px-3 py-2">
        {steps.map((s) => (
          <StepRow key={s.id} step={s} />
        ))}
      </ul>
    </div>
  );
}
