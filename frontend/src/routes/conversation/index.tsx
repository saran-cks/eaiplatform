/**
 * Unified chat + agent surface (mode toggle by the composer). Built in F2 (chat
 * mode) and F3 (agent mode + ActionStream + Monaco). Scaffold placeholder.
 */
export function ConversationPage() {
  return (
    <div className="flex h-full">
      <aside className="w-64 shrink-0 border-r border-border bg-surface p-3">
        <p className="text-xs text-muted-foreground">history rail — F2</p>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col items-center justify-center gap-2 p-6">
        <h2 className="font-accent text-base">conversation</h2>
        <p className="text-sm text-muted-foreground">
          chat + agent surface — wired in F2/F3
        </p>
        <span className="block-caret text-muted-foreground" />
      </section>
    </div>
  );
}
