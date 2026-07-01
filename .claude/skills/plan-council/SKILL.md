---
name: plan-council
description: >-
  Rigorous adversarial review of a plan, design, architecture, or set of claims.
  Fans out three fully isolated subagents (optimist, contrarian, first-principles),
  each scoring its findings, then synthesizes a single decision as chairman.
  ONLY runs when the user explicitly invokes it (e.g. "/plan-council" or
  "run the plan council on X"). It must NEVER trigger automatically.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash, Agent, TodoWrite
---

# Plan Council

A structured "steelman + red-team + first-principles" review. You (the main agent)
act as **Chairman**: you gather context, dispatch three isolated worker subagents,
wait for all three, then cross-correlate and deliver one decision.

This skill only runs when the user asks for it. Do not invoke it on your own.

---

## STEP 0 — Mandatory context gate (do this before anything else)

Do **not** spawn any subagent until you have all of the following. If any item is
missing, STOP and ask the user for it. Ask in a single message, then wait.

Required context:
1. **What are we reviewing?** The plan / design / PR / architecture / specific
   claims. Get the actual text or file paths, not a summary.
2. **What is the goal / definition of success?** What must this achieve to count
   as correct or good?
3. **Project tier & tradeoffs.** How big/critical is this? (e.g. weekend
   prototype, internal tool, funded startup MVP, high-scale production system.)
   This calibrates severity — a solo side project is NOT judged by the standards
   of a system serving millions. Record this as the `TIER` and pass it to every
   agent.
4. **Constraints.** Deadline, team size, budget, stack lock-ins, non-negotiables.
5. **Codebase scope (optional).** Which directories/files are in play, if the
   agents should search the code.

If the user invoked the skill with all of this already, acknowledge it and skip
straight to Step 1. Otherwise, ask. Do not guess the tier — an ungrounded tier
poisons every downstream score.

---

## STEP 1 — Fan out three ISOLATED agents (in parallel)

Spawn all three subagents in a **single batch** so they run concurrently and can
never see each other's work. Each starts from a blank context, so you must paste
the full shared brief into every spawn prompt.

Use the Agent tool three times in one turn, targeting:
- `optimist-scout`
- `contrarian-breaker`
- `first-principles-architect`

Into EACH spawn prompt, embed the identical **Shared Brief** below, then append
that agent's one-line mandate. Do not tell any agent what the others were asked —
isolation is the point.

### Shared Brief template (paste into all three)

```
## Subject under review
<full plan text OR file paths + the specific claims to evaluate>

## Goal / success criteria
<from Step 0 item 2>

## Project TIER (calibrate all severity to this)
<from Step 0 item 3 — e.g. "internal tool, 2 engineers, ship in 3 weeks">

## Constraints
<from Step 0 item 4>

## Codebase scope
<paths to search, or "no codebase — evaluate the plan as written">

## Scoring rubric (use EXACTLY this — do not change the weights)
For every finding you raise, score four axes 1–5:
  I = Impact       (effect on the goal if this is true / realized)
  C = Confidence   (how sure you are, given evidence you actually gathered)
  V = Evidence     (5 = observed directly in code/tests/docs; 3 = strong
                    inference; 1 = speculation)
  E = Effort       (cost to capture[optimist] / mitigate[contrarian] /
                    build correctly[first-principles]; 1 = trivial, 5 = major)

Per-finding Priority score P (0–100), rounded to whole number:
  In = I/5 ; Cn = C/5 ; Vn = V/5 ; Ee = 1 - (E-1)/4
  P = 100 * (0.35*In + 0.30*Cn + 0.20*Vn + 0.15*Ee)

Also give ONE overall Stance score (0–100) = your confidence in your thesis
after doing the work.

## TIER discipline (mandatory)
Every finding must be justified at the stated TIER. If a concern only matters at
a higher tier than this project is, say so explicitly and down-score it — do not
smuggle in "best practice for Netflix" objections against a weekend app.

## Required output format
Return ONLY this, nothing else:

STANCE: <0-100> — <one sentence thesis>

FINDINGS (ranked by P, highest first):
1. <title>
   - Claim/observation: <what, grounded in the subject or code>
   - Evidence: <file:line, quote, or "inference: ...">
   - I=_ C=_ V=_ E=_  → P=__
   - Tier note: <why this matters at THIS tier, or why you down-scored it>
2. ...

COMPOSITE: <mean of the P scores of your top 5 findings>
BLIND SPOTS: <what you could not verify and would need to be sure>
```

### Per-agent mandate (append the matching line)

- optimist-scout → `MANDATE: Build the strongest honest case FOR this plan. Find real upside, leverage, and things already working in the codebase. No hollow cheerleading — every upside needs evidence and a P score.`
- contrarian-breaker → `MANDATE: Find what will fail, with as much certainty as the evidence allows, calibrated to the TIER. Concrete failure modes, not vibes. If you cannot ground a failure, mark its Evidence low.`
- first-principles-architect → `MANDATE: Strip every assumption baked into the plan and the question itself. Rebuild the problem from scratch as an ideal system designer would, then compare that to the plan. Surface both what the plan gets right and where a from-scratch design diverges. Correctness over convenience.`

Wait for all three to return before continuing. Do not start synthesis early.

---

## STEP 2 — Chairman synthesis

By default, YOU synthesize (you are the chairman). Only spawn the
`chairman-synthesizer` subagent instead if the three reports are very long and
you're worried about context budget — if so, paste all three verbatim into its
prompt.

Cross-correlate the three reports and produce:

1. **Consensus** — points two or three agents independently land on. Combine
   their scores; these are your highest-trust conclusions.
2. **Conflicts / decision points** — where the optimist's upside and the
   contrarian's failure attach to the *same* component. Name the tradeoff, show
   both P scores, and state what tips the decision each way.
3. **Reframes** — where the first-principles agent changes the frame such that a
   disagreement dissolves or the plan's premise itself is questionable.
4. **Ranked action list** — concrete next steps, each with a combined composite
   (0–100) and a short "do / defer / drop" call, all calibrated to the TIER.
5. **Verdict** — GO / GO-WITH-CONDITIONS / NO-GO, with a single confidence number
   (0–100) and the top 2 conditions if conditional.
6. **Falsifiers** — the specific evidence that would flip the verdict. This keeps
   the review honest.

Present the three raw stance scores and composites side by side first, then your
synthesis. Do not silently overrule an agent — if you discount a finding, say why.

---

## Notes
- Keep the agents read-only (they analyze, they don't edit).
- If the user re-runs after changes, note what moved between runs.
- If the "claims" being reviewed are factual/empirical, instruct agents to verify
  against the codebase/docs rather than assert from memory, and to mark
  unverifiable claims as low Evidence.