# Video Cloner Operating Model v2

## Core loop

```text
Human sets objective / Reel / priority
 -> Browser Architect frames one meaningful production stage
 -> one Codex session works through the stage
 -> focused tests + real artifacts + local repairs
 -> HUMAN_REVIEW only when real judgment/action is needed
 -> stage exit review
 -> one checkpoint + state/tracker update
 -> next human-set stage
```

No new Plan/session after every microtask.

## Current authority

Read first:

1. `PROJECT_STATE.md`
2. `plan.md`
3. `ARCHITECT_RULES.md`
4. `ARCHITECTURE.md`

Use `PROJECT_TRACKER.xlsx` for roadmap/backlog/priority context, especially at stage boundaries. It is not a per-task gate.

## Normal R1 feature work

Codex:

- inspects Git once;
- implements;
- runs focused tests;
- generates/uses real artifacts;
- may perform up to 3 focused repair cycles;
- continues to the next stage step when no human gate is pending;
- returns a short result instead of a full report.

## R2 / R3

Use stronger evidence only for:

- live Resolve/project mutation;
- destructive/external action;
- credentials/permissions;
- architecture/dependency/security change;
- release/hardening.

## Blocked

Block only when safe progress is impossible.

Harmless `.project_ops` residue, Excel lock files, tracker lag, archived plans or a safely fast-forwardable branch are not blockers.

## Human role

The human sets production direction and judges visible output. The human should not relay routine AI process messages.
