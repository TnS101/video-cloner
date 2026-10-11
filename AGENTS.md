# AGENTS.md — VIDEO CLONER PRODUCT-ONLY CONTRACT

## Mission

Implement the user's current Video Cloner product behavior as directly and quickly as possible.

The product is the code and visible/editable output. Process is not the product.

## Authority

1. The user's current request.
2. Real Resolve/output behavior.
3. Current code and source evidence.
4. `PROJECT_STATE.md` for minimal continuity.

Everything else is historical/reference material unless the user explicitly asks for it.

## Absolute prohibitions unless the user explicitly asks

Do **not** create or expand:

- architecture work or architecture documents;
- infrastructure/framework work not strictly required by the requested feature;
- project-management systems, plans, trackers, decision logs, stage machinery, reports or handoff packs;
- manifests/checkpoint/snapshot/preservation systems for agent workflow;
- validation/safety frameworks, graph validators, rollback frameworks or generalized guardrails;
- new test suites, test harnesses or CI work;
- generalized abstractions, refactors, cleanup projects or future-proofing;
- broad OSS surveys or benchmark frameworks.

Do not update documentation just because code changed. Do not synchronize multiple state files. Do not create new state files.

## Tests and checks

Default: **do not write new tests**.

You may run an existing fast test if it directly answers whether the current feature works. Add a tiny test only if the user explicitly asks or reproducing one concrete bug is faster than manual/live verification.

Never build validation infrastructure around a feature. Real visible/editable product output is the acceptance authority.

## OSS / reuse

Reuse an obvious existing mechanism when it is already known or already in the repository.

Do not perform open-ended research. Search externally only when direct implementation is blocked by a missing mechanism. Compare at most two serious candidates and stop as soon as one usable route is found.

The existing proven-code research file may be consulted as a lookup table, not as a task or research queue:

`docs/research/OSS_PROVEN_CODE_RESEARCH_20261009.md`

## Execution loop

Use only:

`inspect relevant code/evidence -> implement smallest direct change -> run -> inspect real output`

If it works: stop.

If it fails: fix the concrete defect. Maximum two direct repair attempts on the same route. If it still fails, bypass/defer that piece and continue unless it is truly critical to the current product milestone.

If ~10 minutes pass without executable or user-visible progress, stop the approach immediately and choose a simpler route. Never spend the next 30+ minutes designing support machinery.

## Live Resolve work

Prefer a disposable timeline/project derivative when mutation could damage accepted work. That is the default safety mechanism.

Do not build rollback/snapshot/validation infrastructure around the derivative.

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

## Output

Keep the result short:

- what changed;
- what now works;
- exact command/action for the user, if any;
- one real blocker only if progress is genuinely impossible.

No process report. No ceremony.
