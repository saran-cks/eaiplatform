import { loader } from "@monaco-editor/react";
import type { Environment } from "monaco-editor";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

/**
 * Self-host Monaco from the bundled `monaco-editor` package instead of letting
 * `@monaco-editor/react` fetch the editor from a CDN, so the SPA works offline
 * and in a locked-down static deploy. The ArtifactViewer is **read-only**, so
 * only the base editor worker is wired up — the language-service workers
 * (ts/json/css/html) power IntelliSense/diagnostics we don't use, while Monarch
 * syntax highlighting runs without them. Keeping it to one worker also trims the
 * lazy chunk the viewer pulls in.
 *
 * Call once before the first <Editor/> mounts; subsequent calls are no-ops.
 */
let configured = false;

export function configureMonaco(): void {
  if (configured) return;
  configured = true;
  const environment: Environment = { getWorker: () => new EditorWorker() };
  self.MonacoEnvironment = environment;
  loader.config({ monaco });
}
