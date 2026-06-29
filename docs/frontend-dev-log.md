<!-- SCOPE BANNER — read first -->
> **SCOPE — FRONTEND ONLY.** Chronological build log for the **Frontend SPA** (`frontend/`), the
> platform's fifth independent deployable. Plans/checklist live in `docs/frontend-build-plan.md`;
> cross-cutting rationale in `docs/design-decisions.md` (DD-19). Backend changes are logged in the
> Core API docs, not here.

# Enterprise AI Platform — Frontend — Dev Log

## Session F1 — Scaffold + auth shell + API/SSE layer (2026-06-29)

Brought the `frontend/` deployable from `.gitkeep` to a building SPA scaffold. Everything in the F1
checklist is done; the app builds green and is ready for F2 (conversation shell + chat mode).

### What landed
- **Toolchain / project:** Vite 6 + React 18 + TS (strict, `@/*` path alias), Tailwind 3 with a
  CSS-variable token layer, ESLint 9 (flat config) + Prettier. Node 22 / npm.
- **Theming:** `src/theme/themes.css` defines both locked themes — `dark` (pitch black / cool silver /
  JetBrains Mono) and `typer` (cream paper / warm ink / Courier Prime + Special Elite) — as HSL
  CSS-variable sets selected by a class on `<html>`. `ThemeProvider` toggles + persists; the blinking
  block caret is a shared `.block-caret` utility. shadcn-style `Button`/`Input` are themed purely off
  these variables, so the theme swap touches zero component code.
- **Routing + guard:** code-based TanStack Router tree (`src/router.tsx`). A pathless `authed` layout
  route runs the guard in `beforeLoad` (no valid token → `redirect` to `/login?redirect=…`) and renders
  the `RootShell` (nav, theme toggle, tenant badge, sign-out). `/login` sits outside the guard. The
  router is held behind an `AppGate` until `AuthProvider.restore()` settles, so there's no login-flash
  on reload and the guard reads a deterministic auth state.
- **Auth seam (DD-19):** one `AuthProviderAdapter` interface, two impls. **dev-mint** signs an HS256 JWT
  in-browser via `jose` with exactly the claims the backend reads (`tenant_id`, `permissions[]`, `sub`,
  `iss`, `aud`, `exp`) against the shared dev secret — verified to match `config/settings.py` defaults
  (`core-api` issuer, `core-api-clients` audience). **cognito** is stubbed: config-gated, `signIn`
  throws a clear "designed not wired" error. Token + decoded claims live in a Zustand store
  (`store/auth.ts`, localStorage-persisted, expiry-checked); `useScope` exposes `has/hasAny/hasAll`
  for UX-only conditional rendering.
- **API layer:** `api/client.ts` is the single JSON fetch wrapper — injects the Bearer, maps 401→clear
  token + `UnauthorizedError`, 403→`ForbiddenError`, parses `{detail}`. `api/endpoints.ts` are typed
  wrappers over every non-SSE route. `api/sse.ts` handles **both** stream shapes over POST via
  `@microsoft/fetch-event-source`: chat (bare `data:` tokens → `[DONE]`, `event: error`) and agent
  (named events with JSON payloads), with abort/disconnect handling and the lib's auto-retry disabled
  (our streams are finite).
- **Generated types:** dumped the live OpenAPI offline (`uv run python -c "...create_app().openapi()..."`
  → `frontend/openapi.json`, 15 paths) and generated `src/api/generated/types.ts` via
  `openapi-typescript` (`npm run gen:api`). The committed `openapi.json` is the regeneration source.
- **Dev proxy:** `vite.config.ts` proxies every Core API route prefix to `localhost:8000` (the backend
  has no CORS middleware — it only verifies a bearer), keeping dev same-origin; SSE responses pass
  through unbuffered. `.env.example` documents API base, the dev JWT secret/issuer/audience, the auth
  provider switch, and Cognito placeholders.

### Verification
- `npm run build` (= `tsc -b && vite build`) green — 264 modules, no type errors.
- `npm run lint` — 0 errors, 4 `react-refresh/only-export-components` warnings (expected for the context
  providers + the cva `buttonVariants` export; left as-is).
- No live backend run yet — wiring real chat/agent streams against a running Core API is an F2/F3 task
  (and a smoke test, ST-F1, to record in `docs/smoke-tests.md` when run).

### Intentional deviations from the build-plan wording (all noted in the plan)
1. **Code-based router**, not the file-based codegen plugin — equivalent type-safety without a generated
   `routeTree.gen.ts` build step; route components still live under `src/routes/`.
2. **shadcn primitives hand-authored** (no `shadcn` CLI init) — the CLI is interactive and network-bound;
   we own the `cn()` util + token layer + `Button`/`Input` in shadcn style and can run the CLI later
   against the same CSS variables to add more primitives.
3. **npm**, not pnpm — pnpm wasn't installed; npm is present and the lockfile is committed. Switchable later.

### Toolchain hiccup worth remembering
A `cd frontend` left the Bash/PowerShell persistent cwd inside `frontend/`, which broke the repo's
PreToolUse/PostToolUse hooks (`check_commit_oneline.py`, `ruff_check.py`) because they're invoked by a
path relative to the repo root. Fix: always `cd` back to the repo root within the same command
(`cd frontend && … ; cd ..`), or drive npm from root. Not a code issue — a shell-state gotcha.

### Next (F2)
ThemeProvider is already in; F2 is the conversation surface: `HistorySidebar` (GET/POST `/chat`,
`GET /chat/{id}/history`), `Composer` with the chat/agent mode toggle, chat-mode bare-token streaming
via `streamChat`, a parallel `GET /search` sources panel, and markdown rendering.

## Session F2 — Conversation shell + chat mode (2026-06-29)

Brought the conversation surface to life: the placeholder `conversation` route is now a real three-column
chat client streaming against the Core API. Builds green; chat mode is fully wired, agent mode is gated to
F3 behind the same composer toggle.

### What landed
- **Feature module `src/features/conversation/`** — all chat UI + state isolated from the route, which now
  just renders `<ConversationView/>`.
- **`useConversation` hook** — single owner of chat-mode state: the session list (`listSessions` via
  TanStack Query), the active session's `messages`, the live stream, and the parallel sources lookup.
  Exposes `send`/`stop`/`selectSession`/`newConversation`. Streaming appends tokens to the in-flight
  assistant message by id; an `AbortController` is held in a ref and torn down on `stop` and on unmount.
- **Implicit session creation** — on the first message of a new conversation the client generates the
  `session_id` (`crypto.randomUUID()`) and posts straight to `POST /chat/{id}/message`; the backend
  `get_or_create`s the session and takes the title from the request body, so there's **no separate
  `POST /chat`** round-trip. After the stream finishes, the sessions query is invalidated so the new
  conversation appears in the rail (with its derived title).
- **`HistorySidebar`** — new-conversation button + the tenant/subject's sessions (`GET /chat`), active
  highlight, history hydrate on select (`GET /chat/{id}/history`, role-mapped to user/assistant).
- **`Composer`** — auto-growing textarea, Enter-to-send / Shift+Enter-newline, and the **chat/agent mode
  toggle**. Agent mode is selectable but disabled (clear "lands in F3" hint) until the named-event stream
  is wired; the send button flips to a **stop** control while streaming.
- **`MessageList`** — user/assistant bubbles, assistant output through the markdown renderer, a blinking
  block caret on the streaming message, per-message error state, and bottom-stick auto-scroll.
- **`SourcesPanel`** — right rail showing the chunks `GET /search` returned for the last query (fusion +
  reranked badges, score, doc title/id, snippet). Runs concurrently with the token stream and never blocks
  it; stands in for structured citations until the chat stream emits them (DD-19).
- **`Markdown`** — `react-markdown` + `remark-gfm`, every element themed off the CSS-variable token layer
  (no `@tailwindcss/typography`), so it reads correctly in both `dark` and `typer`.

### Verification
- `npm run build` (`tsc -b && vite build`) green — 530 modules, 0 type errors.
- `npm run lint` — 0 errors, the same 4 pre-existing `react-refresh/only-export-components` warnings from
  F1 (none from the new files).
- Not yet run against a live Core API — that's smoke test **ST-F2** (`docs/smoke-tests.md`).

### Known limitations / deferred
- **Markdown block structure is degraded while streaming.** The chat SSE replaces newlines inside each
  token with spaces (backend SSE framing in `api/routes/chat.py`), so streamed answers arrive largely
  single-line — inline formatting (bold, inline code, links) still renders; paragraph/list structure is
  only full for persisted history. Not worth a backend change now; noted.
- **Feedback (👍/👎) not built.** `POST /feedback` requires the turn's `span_id`; the chat stream doesn't
  surface one. Deferred to a small backend addition (emit the span id on the stream), then it drops in next
  to each reply per the DD-19 addendum.
- **Titles** rely on the first message: `get_or_create` sets the title from the first send; existing
  sessions with no title fall back to `session <id8>` in the rail.

### Dependencies added
`react-markdown ^9` + `remark-gfm ^4` (assistant output rendering). Lockfile updated.

### Next (F3)
Agent mode through the same composer toggle: `streamAgent` against `POST /agent/{id}/run`, the ephemeral
`ActionStream` ticker fed by `worker_start`/`worker_done`/`thought`/`synthesis` (fade + collapse under a
`>` drilldown on completion), `output` tokens into the answer, an interrupt button
(`POST /agent/{id}/interrupt`), and the Monaco `ArtifactViewer` for `GET /agent/{id}/artifacts`.

## Session F3 — Agent mode + ephemeral ActionStream (2026-06-29)

Ungated the composer's **agent** toggle and wired the named-event agent stream end-to-end. Because the
LangGraph agent runtime isn't runnable on this laptop, the surface is driven by a **mock stream** by default
so it's fully demoable now and flips to the real backend with one env flag. Builds green; the Monaco
artifact viewer is the one F3 item left.

### What landed
- **Mode-aware send.** `send(text, mode)` branches: chat keeps the bare-token path; agent calls the
  named-event stream. `useConversation` now also owns `actionSteps` and an `agentRunRef`.
- **Mock agent stream** (`api/mockAgent.ts`) — emits the exact event shapes `streamAgent`/`sse.ts` parse
  (`thought` → `worker_start` → `worker_done` → `synthesis` → `output…` → `done`) on abortable timers.
  Selected by `MOCK_AGENT = (VITE_MOCK_AGENT ?? "1") !== "0"` — **on by default**; set `VITE_MOCK_AGENT=0`
  to hit the live `POST /agent/{id}/run`. Dev-only seam, marked FUTURE-delete.
- **Event folding.** `handleAgentEvent` maps events to UI: `thought`→a done step; `worker_start`→an active
  step keyed `w:{worker_id}`; `worker_done`→that step flips to done + gets a `summary` detail;
  `synthesis`→an active step; `output`→tokens appended to the in-flight answer; `error`→message error.
- **`ActionStream`** (`features/conversation/ActionStream.tsx`) — live ticker while running (active row gets
  the accent glyph + block caret); on completion it **fades to 70% and collapses under a `› N agent steps`
  drilldown** the user can re-expand. Renders nothing when there are no steps (so chat mode is unaffected).
- **Interrupt.** The streaming **stop** button aborts the stream; for a real (non-mock) run it also fires
  `POST /agent/{id}/interrupt` (best-effort) to tear the session down server-side. Unmount still cancels.
- **Composer** — agent mode is no longer disabled; the hint now reads "multi-step agent · streams its
  actions above".

### Also in this session (conversation polish)
- **Empty state** reworked to a user-facing welcome ("Welcome! Curious Mind!" + a three-line couplet),
  dropping the dev-facing "scoped retrieval" copy.
- **Sources panel collapsed by default** — a slim always-present `› sources` tab on the far right (with a
  result-count badge) opens the 72-wide panel; a `›` in the header closes it. `sourcesOpen` lives in
  `ConversationView`.
- **Composer floats + auto-grows** — it's now a centered rounded card lifted off the bottom edge; the
  textarea grows to fit its content (`useLayoutEffect` measuring `scrollHeight`, capped at 240px).
- **Translucent scrollbars globally** — a `*` rule in `theme/themes.css` styles every scrollbar off
  `--border` at 50% opacity (→80% hover), transparent track, rounded thumb; Firefox + WebKit. Adapts to
  both themes. Replaces the chunky default OS bar in the transcript, rails, and composer.

### Verification
- `npm run build` (`tsc -b && vite build`) green — 532 modules, 0 type errors.
- `npm run lint` — 0 errors, same 4 pre-existing `react-refresh` warnings from F1 (none new).
- Agent mode exercised via the mock (no backend); live agent run is smoke test **ST-F3** (`docs/smoke-tests.md`).

### Known limitations / deferred
- **Monaco `ArtifactViewer` not built** — skipped the heavy `@monaco-editor/react` install in this quick
  pass; `GET /agent/{id}/artifacts` rendering is the one remaining F3 bullet.
- **Mock event vocabulary is a subset** — covers the happy path; no `require-approval`/`truncated`/PDP-deny
  events yet (those wire when the live agent surfaces them).

### Next
F4 (Search explorer + permission-gated "Open Phoenix ↗" launcher), or close out F3 by adding the Monaco
artifact viewer. Feedback 👍/👎 still waits on the backend emitting a `span_id` on the stream.

## Session F4: Search + observability launcher + feedback (with the backend span_id), plus conversation-surface polish — 2026-06-29

**Target**: land Session F4 (retrieval explorer, the `obs:admin`-gated Phoenix launcher, and feedback wired
into the conversation) — and fold in the backend gap F2/F3 were blocked on (the chat stream now carries the
turn's `span_id`). Also a batch of conversation-surface fixes the user asked for.

### Conversation-surface fixes
- **Assistant turns are no longer boxed.** `MessageList` renders the assistant answer as plain full-width
  markdown — no border, no surface fill, **no "assistant" label**. Only the user turn keeps a label ("you").
- **User bubble is borderless with a soft fade.** New `.bubble-user` component class in `theme/themes.css`
  paints a radial wash of `--muted` (fullest behind the text, → transparent at the edges) so the message
  reads as lifted-off-paper and **mixes into the page background** instead of sitting in a bordered box.
- **Long lines wrap.** Added `break-words` + `[overflow-wrap:anywhere]` to the user paragraph and the
  Markdown wrapper, and `min-w-0` on the flex columns, so unbroken tokens/URLs never push the layout sideways
  past the viewport.
- **Agent actions stream on one line.** `ActionStream`'s **active** state is now a single transient line
  above the composer (current step: glyph + label + optional detail + caret) instead of a multi-row bordered
  box; on completion it still fades and collapses under the `› N agent steps` drilldown. Removed the
  composer's "multi-step agent · streams its actions above" hint.
- **Send is a circular `>>` button.** The composer's send/stop controls became `size="icon"` + `rounded-full`
  (send shows `>>`, stop shows `■`).
- **History rail collapses.** A toggle on the rail's far-left edge collapses `HistorySidebar` to a thin
  strip (a single `»` expand button); `«` collapses it again. `sidebarCollapsed` lives in `ConversationView`.
  Also renamed the rail's action **"new conversation" → "new chat"**.

### Feedback 👍/👎 — unblocked by the backend (#4)
- **Backend now surfaces the span id.** `POST /chat/{id}/message` emits a one-shot **`event: meta`** line
  (`data: {"span_id": …}`) right before the first token (core-api Session 19). It rides a distinct event
  name, so the bare-token stream contract the FE depends on is unchanged.
- **`sse.ts`**: `streamChat` gained an `onMeta` callback; the `meta` event is parsed and never treated as a
  token (malformed meta is swallowed — it can't corrupt the answer).
- **`useConversation`**: `ChatMessage` carries an optional `spanId`; `onMeta` stamps it on the in-flight
  assistant message.
- **`Feedback.tsx`**: thumbs up/down under each *done* assistant reply that has a `spanId`; posts to
  `/feedback` (`label: thumbs_up|thumbs_down`, `score: 1|0`, `annotator=HUMAN` server-side). The glyphs carry
  a **U+FE0E** variation selector to force **text-style (monochrome)** rendering so they inherit the theme
  text color rather than the OS color-emoji palette (per the request that the emojis match the text color).

### Search explorer (`routes/search/index.tsx`)
- Query box + a 5/10/20 limit toggle over `GET /search`. Shows **fusion** method and a **reranked / not
  reranked** indicator as chips, the chunk count, and each scored chunk (rank, `document_id`, score, text,
  `chunk_id`). Aborts the prior request on resubmit. Same scope-filtered retrieval chat uses, so it doubles
  as a "what would the model have seen" inspector.

### Observability launcher (`routes/observability/index.tsx`)
- **"Open Phoenix ↗"** link gated on `useScope().has("obs:admin")` — non-admins see a "you lack obs:admin"
  note. Native scoped trace/eval/dataset/drift views stay deferred (DD-19 addendum). Added
  `env.phoenixUrl` (`VITE_PHOENIX_URL`, default `http://localhost:6006`) + `.env.example` entry.

### Issues faced & resolved
- **Stuck shell cwd broke the repo hooks.** A `cd frontend` in the Bash tool persisted as the session
  working directory, after which the repo's `PreToolUse` (commit-oneline) and `PostToolUse` (ruff_check)
  hooks — both configured with **relative** script paths — failed with "can't open file …\frontend\.claude
  \hooks\…". Reset the cwd to repo root and **anchored both hook commands to `$CLAUDE_PROJECT_DIR`**
  (`.claude/settings.json` + `.claude/settings.local.json`) so they're cwd-independent going forward.
- **Color emoji vs. monochrome.** Plain 👍/👎 render in the OS emoji color palette and ignore CSS `color`.
  Appending the **U+FE0E** text-presentation variation selector makes them inherit `currentColor` — the
  requested "same color as the text" behavior — with no icon-font dependency.

### Verification
- `npm run build` (`tsc -b && vite build`) green — 533 modules, 0 type errors.
- `npm run lint` — 0 errors, same 4 pre-existing `react-refresh` warnings (none new).
- Backend (#4): `uv run pytest src/tests -q` → **108 passed**; touched files ruff-clean. New unit tests assert
  `on_span` reports the LLM span id exactly once (token stream unchanged) and is **not** called on a cache hit.
- End-to-end feedback round-trip + search + the live Phoenix launcher are smoke test **ST-F4**
  (`docs/smoke-tests.md`, PENDING — needs a running Core API + Phoenix).

### Known limitations / deferred
- **Monaco `ArtifactViewer` still not built** — the one remaining F3 bullet (heavy dep).
- **Feedback only on fresh (non-cached) chat turns** — cache hits open no LLM span, so no `span_id`, so no
  thumbs. Agent-mode replies have no `span_id` yet either. Acceptable; revisit if needed.

### Next
Close out F3 (Monaco artifact viewer), or F5 polish (a11y/responsive/error boundaries). Dashboard stays
blocked on the server-side `/dashboard` SSE route.
