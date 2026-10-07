# Video Cloner Project Operating Model

## Core loop

```text
Browser Architect
 -> plan.md
 -> fresh Codex session
 -> bounded execution/evidence
 -> REPORT.md
 -> same Browser Architect review
 -> ACCEPT / BLOCK / REJECT
 -> synchronize state/tracker + archive Plan
 -> fresh Browser chat for next independent Plan
```

## Context

GitHub `main` is primary context. A browser-context ZIP is fallback only.

Read first:

- `ARCHITECT_RULES.md`
- `PROJECT_STATE.md`
- `ARCHITECTURE.md`
- `PROJECT_TRACKER.xlsx`
- `plan.md`

Use `docs/RESEARCH_BASELINE.md`, `docs/DECISIONS.md`, `docs/TEST_STRATEGY.md`, reports, screenshots, or logs only when decision-relevant.

## Boundaries

- Codex is worker, not architect.
- No current `plan.md` = no product implementation.
- No evidence = not done.
- Human owns visual/subjective acceptance and external mutable Resolve UI actions.
- `.agent` is Resolve runtime state. Project operations use `.project_ops`.
- Do not resurrect deleted historical code merely because old reports mention it.
- Research/reuse scan is triggered by a NEW material mechanism/dependency decision, not every Plan.

## Normal Plan start

Start a fresh Codex session in the repository and paste:

> Read `AGENTS.md` and the current `plan.md` completely before acting. Read `ARCHITECTURE.md` and `PROJECT_STATE.md`, verify Git branch/HEAD/status, then execute ONLY the current Plan ID. Do not expand scope, redesign architecture, choose the next Plan, or continue beyond this Plan. Write the required `.project_ops/reports/.../REPORT.md` and evidence, then STOP or request the exact human intervention required by the Plan.

## Current partition

`P001_LIVE_RESOLVE_ACCEPTANCE` is the first Plan under this operating model.
