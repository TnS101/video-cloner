# PROJECT_STATE.md — Video Cloner Current Operational Reality

> Concise evolving state. GitHub `main` + direct evidence are stronger authority. Cleanup-era history remains in `docs/CANONICAL_PROJECT_STATE.md` and `docs/VIDEO_CLONER_FINAL_HANDOFF.md`.

## Project

- PROJECT NAME: Video Cloner
- STATUS: ACTIVE
- LAST UPDATED: 2026-10-08
- PLAN-CREATION REPOSITORY HEAD: `41ff2537c8de610df71b502f071c00d919bf43b0`
- LAST ACCEPTED PRODUCT COMMIT: `4516da32e6780a574e7d3904782bb1007def05e7`
- CLEANUP AUTHORITY TAG: `video-cloner-canonical-cleanup-20261007`
- RECOVERY TAG: `video-cloner-pre-hygiene-snapshot-20261007`

## Real Objective

Build and ship a deterministic editing-style engine that analyzes editing/style evidence and applies an edit reproducibly through a standalone Python API/CLI, beginning with DaVinci Resolve and remaining adapter-ready for future editors/services.

## Win Condition

A clean/raw target can be processed through the canonical pipeline and produce a persistent, idempotent, human-approved edited timeline whose execution does not depend on an AI agent improvising editor actions. Resolve is the first accepted adapter; additional editors are not required for the immediate ship gate.

## Urgency

Deadline has already passed. Optimize for the shortest critical path to a trustworthy product result. Avoid infrastructure/research side quests unless they remove the current bottleneck.

## Known True Now

- GitHub `main` at P002 creation is `41ff2537c8de610df71b502f071c00d919bf43b0`.
- Repository cleanup and source-control reconciliation are complete.
- Normal entry points are `video-cloner run` and `video_cloner.pipeline.run()`.
- Canonical offline generation + bounded queue publication are accepted.
- Canonical regression: 116 passed; CI-equivalent core: 64 passed.
- Resolve launcher wiring is ready and points to the canonical repository.
- Live Resolve machine acceptance is NOT ACCEPTED.
- P001 is BLOCKED/CLOSED: one authorized live import called `ImportTimelineFromFile` exactly once, created/found the exact commanded target, then strict machine validation failed with `ValueError: target_title`.
- P001 did not record the exact observed title text/media-path condition, target UID, post-import protected-state comparison, or persistence evidence because the frozen importer aborted during strict title validation.
- No second P001 Resolve execution is authorized.
- Resolve is still open with the live P001 target left untouched.
- Existing Phase 6 code already supports title/TextPlus readback, `require_title_text=False` structural validation, and a tested provenance/structural semantic fallback for proven direct-readback unavailability.
- The existing live-application regression-support `run()` is not directly applicable to the P001 evidence: it requires prerequisite forensic/provenance reports with a different historical result schema and performs `SaveProject`.
- Persistence, protected-state preservation, second-run/idempotency behavior, and visual acceptance remain unproven.

## Current Constraint

- MAIN BOTTLENECK: missing attributable read-only forensic evidence from the existing unsaved P001 target.
- WHY: `target_title` can currently mean direct TextPlus/title text is unobservable, actual text mismatch, non-empty title media path, or another title-side contradiction. P001's failure path discarded the exact observed values needed to distinguish them.
- CURRENT CRITICAL MOVE: execute P002 as a zero-mutation forensic classification Plan before any save, close, second import, repair, idempotency check, or visual acceptance.
- LIKELY NEXT BOTTLENECK: operationalizing the correct validation/fallback path if direct title text is proven unobservable; otherwise repairing the first concrete semantic/structural mismatch found.

## Architecture State

- ARCHITECTURE STATUS: APPROVED
- ARCHITECTURE FILE: `ARCHITECTURE.md`
- MATERIAL HUMAN APPROVAL: APPROVED

## Current Plan Partition

- CURRENT PLAN ID: `P002_LIVE_TARGET_FORENSIC_READBACK`
- PLAN STATUS: `READY_FOR_CODEX`
- BROWSER SESSION: `BROW-P002_LIVE_TARGET_FORENSIC_READBACK`
- CODEX SESSION: `NOT_STARTED`
- CURRENT PLAN FILE: `plan.md`
- PREDECESSOR: `P001_LIVE_RESOLVE_ACCEPTANCE` — `BLOCKED / CLOSED`
- PREDECESSOR ARCHIVE: `docs/plans/archive/P001_LIVE_RESOLVE_ACCEPTANCE.md`
- PREDECESSOR REPORT: `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T002/REPORT.md`

## Resolve Live-State Hold

Until P002 T003 forensic capture completes:

- KEEP Resolve open and keep the current project open;
- DO NOT save, close, revert, switch timelines, rename/delete/modify the target, import again, or run unrelated Resolve commands;
- P002 plan creation by itself does NOT authorize a Resolve action;
- exactly one P002 read-only Workspace invocation may be authorized only after T001 + T002 prove the diagnostic module/command is zero-mutation and exact-identity bound;
- after capture, closing/saving/discarding remains an explicit Browser Architect + human decision. Do not assume behavior.

## Critical Path

1. P002 T001: reuse/adapt existing Phase 6 readback + structural validation into a minimal dedicated zero-mutation forensic adapter; prove it offline.
2. P002 T002: bind one command to exact P001 run/target/artifact evidence and prove queue/runtime safety.
3. Human gate: one read-only Workspace invocation only if T001 + T002 are READY.
4. P002 T003: classify the actual live target and prove before/after state unchanged.
5. Fresh Browser Architect selects the next Plan from the observed class; persistence/idempotency/visual acceptance remain separate gates.

CURRENT CRITICAL MOVE: P002 T001 — build/prove the bounded read-only forensic surface; do not run Resolve yet.

## Dependencies / Constraints

- Preserve clean canonical package/API architecture.
- `.agent` is reserved for Resolve runtime state; project ops use `.project_ops`.
- Frozen bridge and frozen `video_cloner_phase6_textplus_application.py` remain unchanged in P002.
- P002 may add only minimal diagnostic support + focused tests; product behavior changes are out of scope.
- No save/import/export/render/timeline-selection/mutation operation is permitted in the P002 diagnostic.
- Multi-runtime Python environments remain valid architecture until evidence justifies consolidation.
- Prefer local/FOSS/free mechanisms; paid dependencies require explicit human approval.
- Flattened finished Reel reconstruction is not sufficient final proof of style transfer.

## Reuse / Research State

- RESEARCH GATE FOR P002: `NOT_APPLICABLE`.
- EXISTING MECHANISM DECISION: `REUSE / ADAPT`.
- REUSED: Phase 6 `_title_text`, snapshots/inventories, `validate_target(..., require_title_text=False)`, and existing provenance/structural semantic fallback semantics/tests.
- NOT DIRECTLY RUNNABLE: current live-application regression-support `run()` because it saves and expects provenance/forensic inputs P001 did not produce.
- NEW WORK JUSTIFICATION: a thin read-only diagnostic surface is required to expose the P001 live evidence without changing the frozen importer or saving/re-importing.

## Evidence

### KNOWN

- Cleanup authority tag and GitHub main establish the clean baseline.
- Canonical E2E offline run and bounded publication passed.
- P001 run `20261007T173351920Z_b031b0693f6f4c7d8f8d17c6d718ce41` called `ImportTimelineFromFile` once and created/found target `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B` in project `New Project 1`.
- The matching bridge result failed with `ValueError: target_title`; P001 T003 was not executed.
- Frozen validator raises `target_title` when strict title text differs from expected OR a title item reports a media path.
- The same validator can retain structural/timing/media/lane guards with `require_title_text=False`.
- Existing tests prove a provenance/structural semantic fallback may be valid only when direct title text is genuinely unobservable and no contradictory evidence exists.

### INFERRED

- A single read-only live inspection can remove the current ambiguity with substantially lower risk than re-importing, saving, or patching first.

### ASSUMED

- Resolve remains open and the live P001 target remains untouched until P002 diagnostic execution. T002 must verify live identity rather than trust this assumption.

### UNKNOWN

- Exact title item(s) that triggered `target_title`.
- Exact observed title text for each overlay.
- Whether any title item exposes a non-empty media path.
- Exact live target UID and post-import full inventory.
- Whether direct TextPlus readback is fully unavailable, partially available, or contradictory.
- Persistence across save/reopen.
- Protected-state preservation from the original P001 mutation.
- Second-run/idempotency behavior and visual acceptance.

## Main Risks / SPOFs

- Closing or saving Resolve before read-only capture, losing/altering the only live P001 target evidence.
- Treating `require_title_text=False` as permission to ignore real semantic mismatch; P002 must distinguish unobservable from contradictory data.
- Reusing the existing save-capable live-application `run()` against incompatible P001 provenance and accidentally mutating the project.
- A diagnostic adapter that accidentally calls a mutation API; static + behavioral zero-mutation tests are mandatory before publication.
- Retrying live diagnostics after one P002 execution and creating another attribution problem.

## Human Action Queue

1. NOW: leave Resolve/project/target open and untouched. Do not save/close/revert/switch/rename/delete/import/run scripts.
2. LATER: only after P002 T001 + T002 explicitly report READY, run Workspace → Scripts → `VC_Run_Agent_Task` exactly once.
3. AFTER CAPTURE: do not close/save/discard until Browser Architect reviews T003 and gives an explicit closure instruction.

## Latest Consequential Decision

- DECISION: preserve the live P001 target and use one bounded zero-mutation forensic Plan before any repair or persistence action.
- WHY: existing code already contains the relevant tolerant structural/fallback mechanisms, but P001 did not capture the inputs needed to decide whether they apply. Saving, closing, re-importing, or patching first would contaminate the critical evidence.
- STATUS: ACTIVE — P002
- DETAILS: `docs/DECISIONS.md` D009.
