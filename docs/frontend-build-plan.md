<!-- SCOPE BANNER — read first -->
> **SCOPE — FRONTEND ONLY.** This is the build plan / session checklist for the **Frontend SPA**
> (`frontend/`) — the platform's UI and its **fifth independent deployable**. It shares **no code**
> with the Core API, the sidecars, or the ingestion worker; it is coupled to them only over the wire
> (the **Core API's HTTP + SSE surface**). Backend route/schema changes are tracked in
> `docs/core-api-build-plan.md`, not here. Stack/auth rationale lives in **DD-19**
> (`docs/design-decisions.md`).

# Enterprise AI Platform — Frontend — Build Plan

A static **React + Vite + TypeScript SPA** that is a pure client of the Core API: permission-scoped
chat (RAG), the autonomous agent surface (live ReAct trace + Monaco artifacts), retrieval search,
and an observability/ops surface. No SSR, no BFF — builds to static assets, deploys behind a CDN or
the API's static mount. See **DD-19** for why SPA-not-SSR and the full rationale.

> **Status:** PLANNING ONLY (this session). No app code yet — `frontend/` is still just `.gitkeep`.
> The **visual design** section (palette, typography, theming) is a deliberate **TBD** pending the
> palette/style the user will provide; everything above it is the technical plan.

## Locked decisions (DD-19)
- **Static SPA, not SSR/Next.js** — every surface is behind auth over a pure JSON/SSE API; SSR buys
  nothing here and adds a Node runtime to operate. Build → static assets.
- **Stack:** Vite + React + TypeScript · **TanStack Router** (type-safe protected routes) ·
  **TanStack Query** (server-state cache/retries) · **`@microsoft/fetch-event-source`** (POST SSE) ·
  **shadcn/ui** (Radix + Tailwind — we own the component source) · **Zustand** (auth/client state).
- **SSE primitive is `fetch-event-source`, not native `EventSource`** — the chat and agent streams are
  **POST**, and native `EventSource` is GET-only. Non-negotiable.
- **Two stream shapes, both handled:** chat = bare `data: <token>` … `data: [DONE]`; agent = named
  events (`thought`/`worker_start`/`worker_done`/`synthesis`/`output`/`error`/`done`) with JSON data.
- **Auth has a dev-mint path and a prod Cognito path behind one `AuthProvider` seam** (swap = config).
  The Core API has **no login route** and never will — it only *verifies* a bearer JWT. Prod auth
  (Cognito OIDC + claim mapping + backend RS256/JWKS swap) is **designed now, not wired yet**.
- **Permission-scoped rendering is UX defense-in-depth only** — the server re-enforces every scope.
- **TypeScript types are generated from the backend OpenAPI** (`/openapi.json`) — single source of
  truth, no hand-maintained request/response types that can drift from the API.

## The Core API surface this SPA consumes (verified against `src/api/routes/`)
| Method & path | Shape | Notes |
|---|---|---|
| `POST /chat` | → `SessionOut` | Create a chat session. |
| `GET /chat` | → `SessionOut[]` | List sessions for the JWT tenant/subject. |
| `GET /chat/{id}/history` | → `HistoryOut` | Up to 20 recent messages. |
| `POST /chat/{id}/message` | body `{query, title?}` → **SSE** | Bare-token stream, ends `data: [DONE]`. |
| `GET /search` | `?query&limit` → `SearchResponse` | Hybrid retrieval; scope-filtered chunks + scores. |
| `POST /agent/{id}/run` | body `{prompt, peer_agent_ids?}` → **SSE** | Named-event ReAct stream. |
| `POST /agent/{id}/interrupt` | → `{status}` | Cooperative cancel. |
| `GET /agent/{id}/artifacts` | → `ArtifactOut[]` | Monaco-ready files (`name`/`content`/`language`). |
| `GET /agent/artifacts/{file_id}` | → `ArtifactOut` | Single artifact. |
| `GET /observability/traces` | `?limit&session_id?` → `ListOut` | Live. |
| `GET /observability/evals` | `?limit` → `ListOut` | Live. |
| `GET /observability/datasets` | → `ListOut` | Live. |
| `GET /observability/drift` | → `DriftOut` | Per-tenant embedding drift. |
| `POST /feedback` | body `{span_id, name, label, score?, explanation?}` → `FeedbackAck` | Human annotation. |
| `GET /health`, `/ready` | public | No auth. |
| `POST /dashboard` *(SSE)* | — | **NOT built server-side yet** (core-api Session 9 + ML pipeline). |

All non-public calls require `Authorization: Bearer <jwt>`. A 401 → bounce to login; a 403 → "you
lack permission X" (the scope check failed server-side).

## Planned `frontend/` structure
```
frontend/
  index.html
  vite.config.ts            # dev proxy → Core API (avoids CORS in dev)
  tailwind.config.ts
  package.json
  src/
    main.tsx                # Router + QueryClient + AuthProvider providers
    routes/                 # TanStack Router tree (file/route-based)
      __root.tsx            #   app shell (nav, auth guard)
      login.tsx             #   dev-mint login (prod: Cognito redirect)
      conversation/         #   UNIFIED chat+agent surface — mode toggle by composer
      search/               #   retrieval explorer
      observability/        #   traces / evals / datasets / drift / feedback
      dashboard/            #   PLACEHOLDER — pending /dashboard route
    auth/
      AuthProvider.tsx      # one interface; dev-mint + Cognito-OIDC adapters
      devMint.ts            # dev-only token helper / paste
      cognito.ts            # OIDC PKCE redirect (designed, wired later)
      useScope.ts           # decode permissions[] for conditional rendering
    api/
      client.ts             # fetch wrapper: injects Bearer, handles 401/403
      sse.ts                # fetch-event-source helpers (chat + agent shapes)
      generated/            # types generated from /openapi.json (do not edit)
    components/ui/          # shadcn-generated primitives (owned source)
    components/
      HistorySidebar.tsx    #   left rail — conversation history (ChatGPT/Claude style)
      Composer.tsx          #   query box + chat/agent mode toggle
      MessageList.tsx       #   streamed conversation turns
      ActionStream.tsx      #   ephemeral live action ticker → fades + collapses under ">"
      ArtifactViewer.tsx    #   Monaco editor (agent artifacts)
    theme/
      ThemeProvider.tsx     #   "typer" | "dark" toggle (CSS-variable themes)
    lib/                    # query keys, formatters, constants
    store/                  # Zustand stores (auth/session)
```

---

## Task checklist

### Session F1 — Scaffold + auth shell + API/SSE layer  ← NEXT (no infra needed)
- [ ] Vite + React + TS project in `frontend/`; Tailwind + shadcn init; ESLint/Prettier.
- [ ] TanStack Router tree with `__root` app shell + a protected-route guard.
- [ ] TanStack Query client; `api/client.ts` (Bearer injection, 401→login, 403 surface).
- [ ] `auth/AuthProvider` interface + **dev-mint adapter** (paste/generate HS256 token) + login page.
- [ ] **Cognito OIDC adapter stubbed** behind the same interface (PKCE flow shape, config-gated, not wired).
- [ ] `useScope` — decode `permissions[]`/`tenant_id` for conditional rendering.
- [ ] `api/sse.ts` — `fetch-event-source` helpers for **both** stream shapes (bare-token + named-event).
- [ ] Generate `api/generated/` types from the backend `/openapi.json`.
- [ ] Vite dev proxy to the Core API; `.env.example` (API base URL, dev secret, Cognito placeholders).

### Session F2 — Conversation shell + chat mode
- [ ] `ThemeProvider` — `typer`/`dark` CSS-variable themes + toggle; fonts loaded (Courier Prime / Special
      Elite; JetBrains Mono or IBM Plex Mono). Blinking block caret.
- [ ] `HistorySidebar` (left rail): list (`GET /chat`), create (`POST /chat`), select; history hydrate
      (`GET /chat/{id}/history`).
- [ ] `Composer` — query box with the **chat/agent mode toggle** beside it.
- [ ] **Chat mode**: `POST /chat/{id}/message`, render the **bare-token SSE** incrementally; handle
      `event: error` and `[DONE]`; cancel on unmount. (No action ticker in chat — see FUTURE note.)
- [ ] Sources panel via a parallel `GET /search` (until structured citations exist — flagged in DD-19).
- [ ] Empty/loading/error states; markdown rendering of assistant output.

### Session F3 — Agent mode + ephemeral action ticker + Monaco
- [ ] **Agent mode** via the toggle: `POST /agent/{id}/run` consuming the **named-event SSE**.
- [ ] `ActionStream` — live ephemeral ticker fed by `worker_start`/`worker_done`/`thought`/`synthesis`
      (e.g. `pulled git repo`, `searched ServiceNow ticket…`); on completion **fade opacity + collapse
      under a `>` drilldown** the user can re-expand. Themed per mode (typewriter keys / CLI log lines).
- [ ] Stream `output` tokens into the answer; terminal `done`/`truncated` handling.
- [ ] Interrupt button (`POST /agent/{id}/interrupt`) + disconnect-cancel.
- [ ] **Monaco editor** (`ArtifactViewer`) for artifacts (`GET /agent/{id}/artifacts`,
      `/artifacts/{file_id}`) — language-aware, read-only.
- [ ] (Future) approval/PDP-prompt handling when the backend surfaces require-approval events.

> **FUTURE EXTENSION — chat-mode action ticker.** Reusing `ActionStream` for chat (`searching / found /
> rewriting`) needs the Core API to emit **intermediate step events** on `POST /chat/{id}/message` (it
> streams bare tokens only today). **Deferred — not needed now.** When that backend addition lands, chat
> plugs the same component into those events; no FE redesign required.

### Session F4 — Search + Observability/ops surface
- [ ] Search explorer over `GET /search` (query, limit, fusion/reranked indicators, scored chunks).
- [ ] Observability views: traces (filter by session), evals, datasets, per-tenant drift.
- [ ] `POST /feedback` (human annotation) from a trace/eval row.

### Session F5 — Dashboard (BLOCKED) + polish
- [ ] Dashboard surface — **blocked** on the server-side `/dashboard` SSE route (core-api Session 9)
      and the ML pipeline that feeds it. Placeholder route only until then.
- [ ] Accessibility pass, responsive layout, error boundaries, build/deploy as static assets.

### Prod auth — wire when infra is ready (BLOCKED on backend)
- [ ] Stand up the Cognito user pool + app client; map profile/group attrs → `permissions`/`tenant_id`.
- [ ] Backend: swap the HS256 verifier for **RS256/JWKS** (core-api note) — coordinate, not a FE-only change.
- [ ] Flip the `AuthProvider` config from dev-mint to Cognito-OIDC; no feature-surface change expected.

---

## Visual design — locked (2026-06-29)

Two named themes, toggled by the user, both **monospace-led** so the product reads as one coherent
"machine." Implemented as CSS-variable theme sets behind `ThemeProvider` (`typer` | `dark`); shadcn is
themed off these variables.

### Theme: `typer` (light) — *vintage type machine*
- **Background:** cream / sepia-toned paper, warm and easy on the eyes (~`#F4ECD8`; surfaces a touch
  lighter, e.g. `#FAF4E6`).
- **Text:** ink black, slightly warm (~`#1C1B19`); secondary ink at reduced opacity.
- **Font:** typewriter face — **Courier Prime** for body (readable, not distressed); **Special Elite**
  reserved for accents/headings to push the vintage vibe without hurting legibility.
- **Vibe:** paper feel, ink-weight text, **blinking block caret**, optional faint paper grain. Keys-being-
  typed motion on the action ticker. No heavy chrome.

### Theme: `dark` — *CLI tool, Interstellar feel*
- **Background:** pitch black (~`#050505`); surfaces barely lifted (`#0C0C0D`).
- **Text:** cool **silver** (~`#C0C4CC`); dim silver for secondary.
- **Font:** clean Codex-style monospace — **JetBrains Mono** or **IBM Plex Mono** (crisp, modern).
- **Vibe:** sparse, precise, lots of black; **faint text glow**, terminal-log cadence, minimal accents.
  Think a spacecraft readout — quiet until it speaks.

### Shared interaction model
- **One conversation surface, not two pages.** Chat and Agent are a **mode toggle next to the query box**
  (`Composer`). Same window, same history.
- **Left rail = conversation history** (ChatGPT/Claude style): list, select, new conversation.
- **Streaming responses** render token-by-token in both modes.
- **Ephemeral action ticker (`ActionStream`)** — the signature interaction. While the system works, steps
  appear **live and transient** (typer: keys typing `> searching corpus…`; dark: CLI lines
  `[search] qdrant → 5 hits`). They **must not persist**: once the action completes and the answer lands,
  the ticker **drops opacity and collapses under a `>` drilldown** the user can expand to re-read the trace.
  - **Agent mode (now):** driven by the live named events (`worker_start`/`worker_done`/`thought`/
    `synthesis`) — e.g. `pulled git repo`, `searched ServiceNow ticket…`. Built this milestone.
  - **Chat mode (FUTURE):** the same component, but chat step events (`searching / found / rewriting`)
    require a backend addition the Core API does not have yet — see the gap note below. **Deferred**;
    chat simply streams the answer for now.

### Tokens to formalize at scaffold time
Color (bg/surface/text/secondary/accent/border per theme), typography scale, spacing/radius (slightly
tighter, terminal-like), motion (caret blink, ticker fade/collapse, stream cadence), focus rings. All as
CSS variables so `typer`/`dark` swap with zero component changes.

## What YOU need to do before Session F1
1. Confirm Node toolchain (Node 20 LTS + a package manager — npm/pnpm; pnpm recommended for the lockfile).
2. Provide a **dev JWT or the shared secret** so the dev-mint path can produce valid tokens
   (`JWT_SECRET`, plus the `audience`/`issuer` the backend's `AuthMiddleware` requires).
3. Decide the dev API base URL (default assume Core API at `http://localhost:8000`).
4. Hand over the **palette + UI style** to unblock the Visual design section.
