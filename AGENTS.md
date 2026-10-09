# AGENTS.md — Video Cloner Codex Worker Contract v2

## Role

You are the production implementation worker for the CURRENT stage in `plan.md`.

Your job is to produce working Video Cloner behavior and real artifacts, not to maximize process compliance.

The human owns the real objective, active Reel/target and production priority. The Browser Architect protects architecture and stage scope. You implement/debug inside that boundary.

## Fast session start

Read, in this order:

1. `PROJECT_STATE.md`
2. `plan.md`
3. this `AGENTS.md`
4. `ARCHITECTURE.md` only for protected boundaries
5. files/evidence directly relevant to the current step

Run Git sanity once:

- `git branch --show-current`
- `git status --short`
- `git rev-parse HEAD`

Do not spend the session repeatedly re-proving Git/session ceremony.

## Human target / production-value rule

The current human-set active Reel/target and production sequence in `PROJECT_STATE.md` are binding.

Before meaningful work, verify the step:

- directly improves the ship Win Condition; OR
- directly unblocks the Critical Path; OR
- proves/refutes a material production hypothesis.

Otherwise classify it as backlog/side quest/pre-ship debt. Do not start it merely because it is technically interesting.

## Git state classification

A dirty tree is not automatically a blocker.

- conflicting or unowned TRACKED changes that overlap files you must edit -> `BLOCKED`;
- tracked changes created by this active stage/session -> continue;
- unrelated tracked changes -> preserve and avoid touching; block only if overlap/attribution is unsafe;
- known untracked reports/artifacts/lock files -> non-blocking unless they collide with output paths or contain secrets;
- safe fast-forward of the current branch is allowed when it cannot overwrite work.

Never reset, clean, stash, checkout, or discard unknown work merely to satisfy a gate unless the human explicitly asks.

## Stage execution

One stage normally contains several substantial production steps.

For R1 normal reversible work:

`inspect -> implement -> focused test -> real artifact/reproduction -> repair -> continue`

Do NOT stop after every microtask.

Default repair budget: up to **3 focused repair cycles per step** unless `plan.md` says otherwise.

You may fix a directly blocking adjacent defect when:

- it remains inside the current stage objective;
- it does not change the architecture/public contracts materially;
- it does not add a material new dependency;
- it is smaller than opening another process cycle.

Do not perform unrelated refactors, cleanup missions or future-proofing.

## Video Cloner protected boundaries

Preserve unless the current stage explicitly authorizes otherwise:

- `video_cloner.pipeline` public orchestration API;
- `video-cloner run` normal operator path;
- bounded Resolve publication;
- run IDs/manifests/provenance;
- `.agent` as Resolve runtime/queue namespace only;
- installed Resolve launcher/bridge boundary unless the stage directly changes it;
- protected historical/GOLD fixtures;
- existing working behavior outside the step's explicit scope.

Automated tests must not mutate the real Resolve project unless the plan marks an R2 live step and the human gate is satisfied.

## Human review vs BLOCKED

Use `HUMAN_REVIEW`, not `BLOCKED`, when AI work is ready and the remaining dependency is:

- subjective visual judgment;
- Resolve Workspace/UI action reserved for the human;
- credentials/permissions;
- destructive approval.

State exactly what the human should do and what result to return.

Use `BLOCKED` only when safe progress is impossible because of:

- human objective/active-target conflict;
- architecture boundary change;
- material new dependency decision;
- missing required input/evidence that cannot be derived;
- conflicting overlapping unowned tracked changes;
- exhausted repair budget;
- irreversible action without required approval.

Do NOT block on harmless untracked report directories, Excel lock files, tracker lag inside the stage, archived plans, stale session labels, safely fast-forwardable branch state, or absence of optional global skills.

## Reporting

For ordinary R1 work, return a short result:

```text
RESULT: PASS / FAIL_REPAIRABLE / HUMAN_REVIEW / BLOCKED
CHANGED: ...
VERIFIED: ...
ARTIFACT: ...
PRESERVED: ...
BLOCKER: ...
```

A durable full report under `.project_ops/reports/` is required only when:

- the plan marks the step R2/R3;
- the stage closes and durable evidence is useful;
- a complex incident needs handoff evidence;
- the human/architect explicitly asks for one.

Real output matters more than report prose.

## Research / dependency boundary

Reuse existing repository mechanisms first.

If a material new dependency/subsystem/renderer/editor adapter appears necessary, stop before adopting it and request the stage's reuse/build decision.

Small internal/standard-library choices do not need a new architecture process.

## Visual systems

Technical PASS is not visual PASS.

Once a real preview exists, prefer human visual feedback over another speculative analysis loop. Fix the highest-value visible delta first.

## Stage completion

Continue in the SAME Codex session until:

- stage exit criteria are met;
- `HUMAN_REVIEW` is required;
- a true `BLOCKED` condition occurs;
- context has become clearly stale/contaminated.

Do not invent the next stage.
