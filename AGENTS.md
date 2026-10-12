# AGENTS.md — VIDEO CLONER PRODUCT-ONLY CONTRACT

## Mission

Implement only the user's current requested Video Cloner product behavior as directly and quickly as possible.

The product is the code and visible/editable output. Process is not the product.

## Authority

1. The user's current message and explicit next step.
2. Real Resolve/output behavior.
3. Current code and source evidence.
4. `PROJECT_TRACKER.xlsx` only as high-level project memory/reference.

`PROJECT_TRACKER.xlsx` is NOT an autonomous task queue. The human chooses the next step after every completed step and will provide the detailed next request.

## Project tracker

The tracker is the one allowed project-management artifact because it preserves vital project memory: steps, OSS choices, progress, current results and deferred work.

Rules:
- read it for context when relevant;
- never infer permission to start the next row;
- never expand it into plans, reports, architecture or stage machinery;
- update it only when the user explicitly asks, normally after a meaningful milestone;
- do not block product implementation because the tracker is stale.

## Absolute prohibitions unless the user explicitly asks

Do **not** create or expand:

- architecture work or architecture documents;
- infrastructure/framework work not strictly required by the requested feature;
- plans, decision logs, stage machinery, reports, handoff packs or process docs;
- manifests/checkpoint/snapshot/preservation systems for agent workflow;
- validation/safety frameworks, graph validators, rollback frameworks or generalized guardrails;
- new test suites, test harnesses or CI work;
- generalized abstractions, refactors, cleanup projects or future-proofing;
- broad research surveys or benchmark frameworks.

Do not update documentation just because code changed. Do not create new project-state/process files.

## Tests and checks

Default: **do not write new tests**.

Run an existing fast test only if it directly answers whether the requested feature works. Add a tiny test only if the user explicitly asks or reproducing one concrete bug is faster than direct/live verification.

Never build validation infrastructure around a feature. Real visible/editable product output is the acceptance authority.

## OSS / reuse

Reuse an obvious existing mechanism when it is already known or already in the repository.

The existing proven-code research file may be consulted only as a lookup table:

`docs/research/OSS_PROVEN_CODE_RESEARCH_20261009.md`

Do not perform open-ended research. Search externally only when direct implementation is blocked by a missing mechanism. Compare at most two serious candidates and stop as soon as one usable route is found.

## Execution loop

Use only:

`inspect relevant code/evidence -> implement smallest direct change -> run it -> inspect real output`

If it works: stop and report to the human.

If it fails: fix the concrete defect. Maximum two direct repair attempts on the same route. If it still fails, bypass/defer that piece and continue unless it is truly critical.

If ~10 minutes pass without executable or user-visible progress, stop that approach and choose a simpler route. Never spend 30+ minutes designing support machinery.

## Live Resolve work

Prefer a disposable timeline/project derivative when mutation could damage accepted work. Do not build a rollback/snapshot framework around it.

Do not control a GUI/desktop as the product mechanism. Build deterministic scripts/commands that detect/apply the behavior; the human runs or reviews them. Use GUI/computer control only when the human explicitly requests a one-off exploratory action.

Never destroy unknown user work.

## Scope discipline

Do not:
- refactor unrelated code;
- solve future Auto Editing problems inside Video Cloner;
- clean technical debt unless it blocks the current feature;
- improve architecture/code quality for its own sake;
- turn an edge case into a subsystem;
- reopen accepted captions/transitions/cuts without new user-visible evidence.

A 4/5 working batch is better than a perfect framework that never reaches Resolve.

## Human-controlled sequencing

When the requested step is complete or reaches human review:
- STOP;
- summarize the real result;
- do not begin the next tracker step;
- do not invent the next stage.

The human will decide what happens next and provide more detailed direction. Advice is welcome; autonomous roadmap execution is not.

## Output

Keep the result short:

- what changed;
- what now works;
- exact command/action for the user, if any;
- one real blocker only if progress is genuinely impossible.

No process report. No ceremony.
