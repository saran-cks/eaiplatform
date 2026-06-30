import { useMemo, useState } from "react";
import Editor from "@monaco-editor/react";
import { useQuery } from "@tanstack/react-query";

import type { ArtifactOut } from "@/api/endpoints";
import { configureMonaco } from "@/lib/monaco";
import { queryKeys } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { useTheme } from "@/theme/ThemeProvider";

import { fetchArtifacts } from "./artifacts";

// Point @monaco-editor/react at the bundled monaco before any <Editor/> mounts.
configureMonaco();

// Map a file extension to a Monaco language id when the artifact omits one.
const EXT_LANG: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  py: "python",
  json: "json",
  md: "markdown",
  markdown: "markdown",
  yaml: "yaml",
  yml: "yaml",
  sql: "sql",
  sh: "shell",
  bash: "shell",
  html: "html",
  css: "css",
  java: "java",
  go: "go",
  rs: "rust",
  toml: "ini",
  ini: "ini",
  xml: "xml",
  txt: "plaintext",
};

function languageFor(a: ArtifactOut): string {
  if (a.language) return a.language;
  const ext = a.name.split(".").pop()?.toLowerCase() ?? "";
  return EXT_LANG[ext] ?? "plaintext";
}

interface ArtifactViewerProps {
  /** Agent session whose artifacts to show (`GET /agent/{id}/artifacts`). */
  agentSessionId: string;
  onClose: () => void;
}

/**
 * Read-only Monaco viewer for an agent run's artifacts (F3). A right-docked
 * drawer: a file list on the left, the selected file in the editor on the right.
 * Lazy-loaded by ConversationView so the heavy editor chunk is only fetched when
 * a user opens it. Locally the files come from the mock seam (`env.mockAgent`).
 */
export function ArtifactViewer({ agentSessionId, onClose }: ArtifactViewerProps) {
  const { theme } = useTheme();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.artifacts(agentSessionId),
    queryFn: ({ signal }) => fetchArtifacts(agentSessionId, signal),
  });

  const artifacts = useMemo(() => data ?? [], [data]);
  const selected =
    artifacts.find((a) => a.file_id === selectedId) ?? artifacts[0] ?? null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      {/* Backdrop — click to dismiss. */}
      <button
        type="button"
        aria-label="close artifacts"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <aside className="relative flex h-full w-[min(720px,92vw)] flex-col border-l border-border bg-background shadow-xl">
        <header className="flex items-center justify-between border-b border-border px-3 py-2">
          <h3 className="font-accent text-xs uppercase tracking-wider text-muted-foreground">
            artifacts
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="hide artifacts"
            title="hide artifacts"
            className="rounded-md px-1.5 font-accent text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            ✕
          </button>
        </header>

        <div className="flex min-h-0 flex-1">
          {/* File list. */}
          <ul className="w-48 shrink-0 overflow-y-auto border-r border-border p-1">
            {isLoading && (
              <li className="px-2 py-1 text-xs text-muted-foreground">loading…</li>
            )}
            {isError && (
              <li className="px-2 py-1 text-xs text-destructive">
                {error instanceof Error ? error.message : "failed to load artifacts"}
              </li>
            )}
            {!isLoading && !isError && artifacts.length === 0 && (
              <li className="px-2 py-1 text-xs text-muted-foreground">
                this run produced no artifacts.
              </li>
            )}
            {artifacts.map((a) => (
              <li key={a.file_id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(a.file_id)}
                  title={a.name}
                  className={cn(
                    "w-full truncate rounded px-2 py-1 text-left font-accent text-xs transition-colors",
                    selected?.file_id === a.file_id
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {a.name}
                </button>
              </li>
            ))}
          </ul>

          {/* Editor. */}
          <div className="min-w-0 flex-1">
            {selected ? (
              <Editor
                key={selected.file_id}
                height="100%"
                path={selected.name}
                language={languageFor(selected)}
                value={selected.content}
                theme={theme === "dark" ? "vs-dark" : "light"}
                loading={
                  <span className="px-3 py-2 text-xs text-muted-foreground">
                    loading editor…
                  </span>
                }
                options={{
                  readOnly: true,
                  domReadOnly: true,
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: "on",
                  scrollBeyondLastLine: false,
                  renderWhitespace: "none",
                  wordWrap: "on",
                  automaticLayout: true,
                }}
              />
            ) : (
              <div className="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
                select a file to view it.
              </div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
