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
