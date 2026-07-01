---
name: doc-driven-dev
description: >
  The doc-driven coding workflow for this repo (Core API + sidecars + ingestion worker).
  Use for ANY non-trivial code change here: it enforces the loop check/update the build
  plan → code to the hexagonal invariants → record the work + any issues in the dev log →
  add a design decision only if a real architectural choice was made → write/verify a smoke
  test when behavior depends on live services. Invoke when asked to build, implement, add,
  wire, fix, or extend a feature in this codebase.
---

# Doc-driven development

This repo is documentation-driven. Four doc families carry state across sessions; keep them
honest as you code. **Match the existing file's tone and format — append, don't restructure.**

| Doc family | Files | What it holds |
|---|---|---|
| Build plan | `docs/<deployable>-build-plan.md` | The task checklist + locked decisions. Source of *what to do next*. |
| Dev log | `docs/<deployable>-dev-log.md` | Chronological session log: what was built + **issues faced & resolved**. |
| Design decisions | `docs/design-decisions.md` | Cross-cutting **why** (DD-N). Append-only, newest at bottom. |
| Smoke tests | `docs/smoke-tests.md` | Deferred **live/E2E** checks (ST-N) that unit tests can't cover. |

`<deployable>` is one of: `core-api` (`src/`), `ingestion-worker` (`ingestion_worker/`),
`embedding-sidecar` (`sidecars/model_server/`), `prompt-guard-sidecar` (`sidecars/prompt_guard/`).
Read `CLAUDE.md` for the architecture invariants and commands.

## The loop — follow in order, every change

### 1. Check / write the plan (before coding)
- Open the relevant `docs/<deployable>-build-plan.md`. Find the task; if it isn't there and
  the work is non-trivial, **add it as a checklist item first** (under the right session/phase).
- Honor the "Locked decisions" and "Architecture invariants" sections — if your change would
  violate one, stop and go to step 4 (it needs a design decision, not a silent break).
- Do not collapse layers or build everything at once; follow the plan's ordering.

### 2. Code it
- Hold the hexagonal invariants (enforced by `src/tests/test_architecture.py`): `core/use_cases`
  depends only on `core/ports` + `core/domain`; adapters never import each other; `config/di.py`
  is the only wiring point; `PermissionScope` flows top-down, never derived in an adapter/use-case.
- New external dependency ⇒ extend a port → write an adapter → bind it in `di.py`. Never I/O from a use-case.
- Everything async, typed (mypy strict), ruff-clean. Mark deferred work `# FUTURE EXTENSION`, no placeholder comments.
- Write/extend unit tests alongside the code (mock transports). Run the relevant suite + lint + mypy
  (see `CLAUDE.md` "Commands") and get them green before moving on.

### 3. Record it in the dev log (always)
Append to `docs/<deployable>-dev-log.md`. Either a new `## Session N:` block or extend the current one,
matching the existing structure:
- **Completed**: date (`2026-06-29`) · **Target**: one line · **Steps Completed**: bullets of what landed.
- **Issues Faced & Resolved**: list every non-obvious problem and its fix (the convention is explicit
  here — Windows encoding quirks, library shape surprises, timeouts, etc.). If nothing went wrong, omit it.
- Tick the matching boxes in the build plan (`[ ]` → `[x]`) and add a next-step note if you stopped mid-task.

### 4. Add a design decision — ONLY if one was actually made
Append a new `## DD-N` to `docs/design-decisions.md` (next number, newest at bottom) **only** when you
made a real, cross-cutting architectural choice: a trade-off, a rejected alternative, a security-model
stance, an invariant. Capture the *why* and an **Enforcement check** line (the test that holds it), per
the existing DD-8…DD-17 style. **Do NOT** add a DD for routine implementation that just follows existing
decisions — that belongs in the dev log. When unsure, it's probably a dev-log entry, not a DD.It is not a DD if it is just a local implementation choice, or if it is a decision that only affects one
adapter or use-case. It is a DD if it is a decision that affects the architecture,
the security model, or the invariants of the system. If you are unsure, err on the side of not creating a DD. It is better to have a dev log entry than to create.

### 5. Smoke test — write and/or verify when required
A change "requires" a smoke test when correctness depends on a **real service** (sidecar, DB, network,
live MCP/Bedrock/Phoenix) that unit tests mock. In that case:
- Add a new `## ST-N: … — added <date> — **PENDING**` to `docs/smoke-tests.md` (newest at bottom): prereqs,
  numbered steps with expected results, and a "Record outcome here" checkbox — match the ST-1…ST-4 format.
- **Verify only when the live services are actually available** in this session. If they are, run it and
  record the outcome (date + PASS/FAIL + any fixes found). If not, leave it **PENDING** — do not fabricate a
  run. (Per repo convention, deferred live checks are written down, not run inline.)

## Before you finish
Confirm: build-plan boxes ticked · dev-log entry appended (with issues if any) · DD added *iff* a real
decision was made · smoke test added/verified *iff* live-service behavior is involved · unit tests + ruff +
mypy green. Commit messages stay **single-line** — the detail lives in these docs, not the commit body.
