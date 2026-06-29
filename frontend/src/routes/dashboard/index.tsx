/**
 * Dashboard surface — BLOCKED on the server-side POST /dashboard SSE route
 * (core-api Session 9) and the ML pipeline that feeds it. Placeholder until then.
 */
export function DashboardPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6">
      <h2 className="font-accent text-base">dashboard</h2>
      <p className="text-sm text-muted-foreground">
        blocked — pending the backend /dashboard route + ML pipeline
      </p>
    </div>
  );
}
