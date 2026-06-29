import { useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { search, type SearchResponse } from "@/api/endpoints";
import { cn } from "@/lib/utils";

type SearchChunk = SearchResponse["chunks"][number];

type State =
  | { status: "idle" }
  | { status: "loading"; query: string }
  | { status: "ready"; query: string; result: SearchResponse }
  | { status: "error"; query: string; message: string };

const LIMITS = [5, 10, 20] as const;

function scorePct(score: number): string {
  // Scores come back as RRF/rerank floats; show a compact fixed view.
  return score.toFixed(4);
}

function ChunkCard({ chunk, rank }: { chunk: SearchChunk; rank: number }) {
  return (
    <li className="rounded-md border border-border bg-surface/60 p-3">
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <span className="font-accent text-xs text-muted-foreground">
          [{rank}] doc:{chunk.document_id}
        </span>
        <span className="shrink-0 font-accent text-xs text-foreground">
          score {scorePct(chunk.score)}
        </span>
      </div>
      <p className="whitespace-pre-wrap break-words text-sm text-foreground [overflow-wrap:anywhere]">
        {chunk.text}
      </p>
      <p className="mt-1 font-accent text-[0.65rem] text-muted-foreground">
        chunk:{chunk.chunk_id}
      </p>
    </li>
  );
}

/**
 * Retrieval explorer over `GET /search` (F4). Runs the identical scope-filtered
 * hybrid retrieval the chat pipeline uses (pre-LLM), so it doubles as a way to
 * inspect exactly what the model would have seen for a query. Fusion method and
 * the rerank flag are surfaced as indicators.
 */
export function SearchPage() {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState<number>(10);
  const [state, setState] = useState<State>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  const run = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q || state.status === "loading") return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "loading", query: q });

    search(q, limit, controller.signal)
      .then((result) => setState({ status: "ready", query: q, result }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : "search failed";
        setState({ status: "error", query: q, message });
      });
  };

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-4 p-6">
      <div>
        <h2 className="font-accent text-base text-foreground">search</h2>
        <p className="text-sm text-muted-foreground">
          scope-filtered hybrid retrieval — the same chunks chat would retrieve
        </p>
      </div>

      <form onSubmit={run} className="flex items-center gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="query the knowledge base…"
          className="flex-1"
        />
        <div className="flex items-center gap-1">
          {LIMITS.map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setLimit(n)}
              className={cn(
                "rounded-md px-2 py-1 font-accent text-xs transition-colors",
                n === limit
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {n}
            </button>
          ))}
        </div>
        <Button type="submit" disabled={!query.trim() || state.status === "loading"}>
          {state.status === "loading" ? "…" : "search"}
        </Button>
      </form>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {state.status === "idle" && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            enter a query to explore retrieval.
          </p>
        )}
        {state.status === "loading" && (
          <p className="py-8 text-center text-sm text-muted-foreground">searching…</p>
        )}
        {state.status === "error" && (
          <p className="py-8 text-center text-sm text-destructive">
            search failed: {state.message}
          </p>
        )}
        {state.status === "ready" && (
          <>
            <div className="mb-3 flex items-center gap-2 text-xs">
              <span className="rounded-md bg-muted px-2 py-0.5 font-accent text-foreground">
                fusion: {state.result.fusion}
              </span>
              <span
                className={cn(
                  "rounded-md px-2 py-0.5 font-accent",
                  state.result.reranked
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground",
                )}
              >
                {state.result.reranked ? "reranked" : "not reranked"}
              </span>
              <span className="text-muted-foreground">
                {state.result.chunks.length} chunk
                {state.result.chunks.length === 1 ? "" : "s"}
              </span>
            </div>
            {state.result.chunks.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                no chunks matched within your permission scope.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {state.result.chunks.map((c, i) => (
                  <ChunkCard key={c.chunk_id} chunk={c} rank={i + 1} />
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}
