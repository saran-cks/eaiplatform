import type { SessionOut } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface HistorySidebarProps {
  sessions: SessionOut[];
  isLoading: boolean;
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

function sessionLabel(s: SessionOut): string {
  const title = s.title?.trim();
  if (title) return title;
  return `session ${s.session_id.slice(0, 8)}`;
}

/** Left rail: new-conversation action + the tenant/subject's session list. */
export function HistorySidebar({
  sessions,
  isLoading,
  activeId,
  onSelect,
  onNew,
}: HistorySidebarProps) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface">
      <div className="p-2">
        <Button variant="outline" size="sm" className="w-full" onClick={onNew}>
          + new conversation
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
