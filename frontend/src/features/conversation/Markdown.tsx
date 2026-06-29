import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/**
 * Themed markdown renderer for assistant output. No `@tailwindcss/typography`
 * dependency — element styles map onto the theme tokens directly so both the
 * `dark` and `typer` palettes render coherently. GFM (tables, strikethrough,
 * task lists) is enabled.
 *
 * Note: the chat SSE collapses newlines inside each token (backend SSE framing),
 * so streamed answers arrive largely single-line — inline formatting (bold,
 * code, links) still renders; block structure is fuller for persisted history.
 */

// react-markdown passes an internal `node` prop we must not spread onto the DOM.
function clean<T extends { node?: unknown }>(props: T): Omit<T, "node"> {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { node, ...rest } = props;
  return rest;
}

const components: Components = {
  p: (props) => <p className="mb-2 leading-relaxed last:mb-0" {...clean(props)} />,
  ul: (props) => <ul className="mb-2 list-disc pl-5 last:mb-0" {...clean(props)} />,
  ol: (props) => <ol className="mb-2 list-decimal pl-5 last:mb-0" {...clean(props)} />,
  li: (props) => <li className="mb-1" {...clean(props)} />,
  h1: (props) => <h1 className="mb-2 font-accent text-lg" {...clean(props)} />,
  h2: (props) => <h2 className="mb-2 font-accent text-base" {...clean(props)} />,
  h3: (props) => <h3 className="mb-1 font-accent text-sm" {...clean(props)} />,
  a: (props) => (
    <a
      className="text-foreground underline underline-offset-2 hover:opacity-80"
      target="_blank"
      rel="noreferrer"
      {...clean(props)}
    />
  ),
  blockquote: (props) => (
    <blockquote
      className="mb-2 border-l-2 border-border pl-3 text-muted-foreground"
      {...clean(props)}
    />
  ),
  pre: (props) => (
    <pre
      className="mb-2 overflow-x-auto rounded-md border border-border bg-muted p-3 text-xs [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-inherit"
      {...clean(props)}
    />
  ),
  code: ({ className, children }) => {
    const isBlock = className?.includes("language-");
    return isBlock ? (
      <code className={cn("font-body", className)}>{children}</code>
    ) : (
      <code className="rounded bg-muted px-1 py-0.5 font-body text-[0.85em]">{children}</code>
    );
  },
  table: (props) => (
    <div className="mb-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs" {...clean(props)} />
    </div>
  ),
  th: (props) => (
    <th className="border border-border px-2 py-1 text-left font-medium" {...clean(props)} />
  ),
  td: (props) => <td className="border border-border px-2 py-1" {...clean(props)} />,
};

export function Markdown({ content }: { content: string }) {
  return (
    <div className="text-sm [overflow-wrap:anywhere]">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
