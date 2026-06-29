import { cn } from "@/lib/utils";

import type { SourceChunk, SourcesState } from "./useConversation";

function ChunkCard({ chunk, index }: { chunk: SourceChunk; index: number }) {
  const title =
    (typeof chunk.metadata?.title === "string" && chunk.metadata.title) ||
    chunk.document_id;
  return (
    <li className="rounded-md border border-border bg-surface p-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="truncate font-accent text-[0.7rem] text-foreground" title={title}>
          [{index + 1}] {title}
        </span>
        <span className="shrink-0 text-[0.65rem] text-muted-foreground">
          {chunk.score.toFixed(3)}
        </span>
      </div>
      <p className="line-clamp-4 text-xs text-muted-foreground">{chunk.text}</p>
    </li>
  );
}

/** Number of chunks to badge on the collapsed tab, when a search has resolved. */
function sourceCount(sources: SourcesState): number | null {
  return sources.status === "ready" ? sources.chunks.length : null;
}

interface SourcesPanelProps {
  sources: SourcesState;
  open: boolean;
  onToggle: () => void;
}

/** Right rail: the chunks `/search` returned for the last query (DD-19: stands in
 *  for structured citations until the chat stream emits them). Collapsed by
 *  default — a thin tab on the far right opens it. */
export function SourcesPanel({ sources, open, onToggle }: SourcesPanelProps) {
  const count = sourceCount(sources);

  // Collapsed: a slim always-present tab on the extreme right.
  if (!open) {
    return (
      <button
        type="button"
        onClick={onToggle}
        title="show sources"
        className="hidden shrink-0 flex-col items-center gap-2 border-l border-border bg-background px-2 py-3 text-muted-foreground transition-colors hover:text-foreground lg:flex"
      >
        <span className="font-accent text-xs">›</span>
        <span className="font-accent text-[0.65rem] uppercase tracking-wider [writing-mode:vertical-rl]">
          sources
        </span>
        {count !== null && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[0.6rem] text-foreground">
            {count}
          </span>
        )}
      </button>
    );
  }

  return (
    <aside className="hidden w-72 shrink-0 flex-col border-l border-border bg-background lg:flex">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h3 className="font-accent text-xs uppercase tracking-wider text-muted-foreground">
          sources
        </h3>
        <button
          type="button"
          onClick={onToggle}
          title="hide sources"
          className={cn(
            "rounded-md px-1.5 font-accent text-sm text-muted-foreground",
            "transition-colors hover:text-foreground",
          )}
        >
          ›
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {sources.status === "idle" && (
          <p className="px-1 py-1 text-xs text-muted-foreground">
            retrieved chunks for your query appear here.
          </p>
        )}
        {sources.status === "loading" && (
          <p className="px-1 py-1 text-xs text-muted-foreground">searching…</p>
        )}
        {sources.status === "error" && (
          <p className="px-1 py-1 text-xs text-destructive">
            sources unavailable: {sources.message}
          </p>
        )}
        {sources.status === "ready" && (
          <>
            <p className="mb-2 px-1 text-[0.65rem] text-muted-foreground">
              {sources.chunks.length} chunk{sources.chunks.length === 1 ? "" : "s"} ·{" "}
              {sources.fusion}
              {sources.reranked ? " · reranked" : ""}
            </p>
            {sources.chunks.length === 0 ? (
              <p className="px-1 text-xs text-muted-foreground">no matching chunks.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {sources.chunks.map((c, i) => (
                  <ChunkCard key={c.chunk_id} chunk={c} index={i} />
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
