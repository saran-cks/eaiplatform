import type { SessionOut } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface HistorySidebarProps {
  sessions: SessionOut[];
  isLoading: boolean;
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  collapsed: boolean;
  onToggle: () => void;
}

function sessionLabel(s: SessionOut): string {
  const title = s.title?.trim();
  if (title) return title;
  return `session ${s.session_id.slice(0, 8)}`;
}

/** Left rail: collapse toggle + new-chat action + the tenant/subject's session
 *  list. Collapses to a thin strip with a single expand button on the far left. */
export function HistorySidebar({
  sessions,
  isLoading,
  activeId,
  onSelect,
  onNew,
  collapsed,
  onToggle,
}: HistorySidebarProps) {
  if (collapsed) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center border-r border-border bg-surface py-2">
        <button
          type="button"
          onClick={onToggle}
          aria-label="expand sidebar"
          title="expand sidebar"
          className="rounded-md px-2 py-1.5 font-accent text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {"»"}
        </button>
      </aside>
    );
  }

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center gap-1 p-2">
        <button
          type="button"
          onClick={onToggle}
          aria-label="collapse sidebar"
          title="collapse sidebar"
          className="shrink-0 rounded-md px-2 py-1.5 font-accent text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {"«"}
        </button>
        <Button variant="outline" size="sm" className="flex-1" onClick={onNew}>
          + new chat
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isLoading && (
          <p className="px-2 py-1 text-xs text-muted-foreground">loading…</p>
        )}
        {!isLoading && sessions.length === 0 && (
          <p className="px-2 py-1 text-xs text-muted-foreground">no conversations yet</p>
        )}
        <ul className="flex flex-col gap-0.5">
          {sessions.map((s) => (
            <li key={s.session_id}>
              <button
                type="button"
                onClick={() => onSelect(s.session_id)}
                className={cn(
                  "w-full truncate rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  s.session_id === activeId
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                title={sessionLabel(s)}
              >
                {sessionLabel(s)}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
