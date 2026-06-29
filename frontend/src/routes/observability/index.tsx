import { useScope } from "@/auth/useScope";
import { env } from "@/lib/env";

/**
 * Observability surface (F4). Native scoped trace/eval/dataset/drift views are
 * deferred (DD-19 addendum) until multi-tenant prod needs them; for now this is
 * an **"Open Phoenix ↗"** launcher, gated on the `obs:admin` claim so it never
 * shows for non-dev users. The server still re-enforces scope — hiding it here
 * is UX defense-in-depth only.
 */
export function ObservabilityPage() {
  const { has } = useScope();
  const canViewObs = has("obs:admin");

  if (!canViewObs) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <h2 className="font-accent text-base text-foreground">observability</h2>
        <p className="max-w-sm text-sm text-muted-foreground">
          you lack the <code className="font-accent">obs:admin</code> permission required to
          view tracing.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
      <div>
        <h2 className="font-accent text-base text-foreground">observability</h2>
        <p className="max-w-md text-sm text-muted-foreground">
          traces, evals, datasets, and embedding drift live in Phoenix. Native scoped views
          are deferred — open the Phoenix UI for the full surface.
        </p>
      </div>
      <a
        href={env.phoenixUrl}
        target="_blank"
        rel="noreferrer"
        className="rounded-md border border-border bg-surface px-4 py-2 font-accent text-sm text-foreground transition-colors hover:bg-muted"
      >
        Open Phoenix ↗
      </a>
      <p className="font-accent text-[0.65rem] text-muted-foreground">{env.phoenixUrl}</p>
    </div>
  );
}
