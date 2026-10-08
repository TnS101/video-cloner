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
- P001 is BLOCKED/CLOSED after one import created the exact commanded target and strict validation failed `ValueError: target_title`.
- P002 is ACCEPTED/CLOSED with exactly one read-only live execution and classification `DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID`.
- P002 mapped 112/112 overlays exactly; every direct title readback was `null`, every title media path was empty, strict validation failed `ValueError: target_title`, and `require_title_text=False` structural validation passed.
- P002 fallback eligibility is `true`; this is not product acceptance.
- Current timeline, all 46 timelines, 45 protected/non-target timelines, and all 55 media-pool items were unchanged; all mutation counters were zero.
- Reel #2 GOLD is retained exactly as timeline `DcJRJtUKScu_offline_timeline_v1`, UID `4ad2a3c3-031c-464d-96aa-76a045608ad6`, DRT SHA-256 `99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e`.
- The Reel #2 advanced-caption lifecycle and human-cleaned GOLD remain baseline evidence to REUSE/ADAPT, not rebuild.
- Persistence, save/reopen, second-run/idempotency behavior, and human visual acceptance remain unproven.

## Current Constraint

- P002 removed the forensic ambiguity: direct imported-title text is unobservable while structural identity is valid.
- No new active Plan exists. The Browser Architect must explicitly choose any future work and the live-state/save/close policy.
- Product acceptance remains blocked on unproven persistence, idempotency, and human visual acceptance.

## Architecture State

- ARCHITECTURE STATUS: APPROVED
- ARCHITECTURE FILE: `ARCHITECTURE.md`
- MATERIAL HUMAN APPROVAL: APPROVED

## Current Plan Partition

- CURRENT PLAN ID: `NONE`
- PLAN STATUS: `NO_ACTIVE_PLAN`
- MOST RECENT CLOSED PLAN: `P002_LIVE_TARGET_FORENSIC_READBACK` — `ACCEPTED / CLOSED`
- CLOSED PLAN FILE: `docs/plans/archive/P002_LIVE_TARGET_FORENSIC_READBACK.md`
- PREDECESSOR: `P001_LIVE_RESOLVE_ACCEPTANCE` — `BLOCKED / CLOSED`
- PREDECESSOR ARCHIVE: `docs/plans/archive/P001_LIVE_RESOLVE_ACCEPTANCE.md`
- P002 REPORTS: `.project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/{T001,T002,T003}/REPORT.md`

## Resolve Live-State Hold

- KEEP Resolve open and the current project/target unchanged.
- DO NOT save, close, revert, switch, rename, delete, modify, import, or run another P002 command.
- P002 authorized exactly one live read-only execution; it is complete and no further P002 execution is authorized.
- Save/discard/close requires an explicit future Browser Architect Plan and human instruction.

## Critical Path

1. P002 forensic diagnosis is complete and accepted.
2. Browser Architect review selects the next bounded Plan, if any.
3. Until then, preserve the live Resolve state unchanged.

CURRENT CRITICAL MOVE: none authorized; no active Plan exists.

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

- P002 research gate: `NOT_APPLICABLE`; accepted mechanism decision: `REUSE / ADAPT`.
- Phase 6 `_title_text`, snapshots/inventories, tolerant structural validation, and provenance/structural fallback semantics were reused without changing frozen code.
- Reel #2 advanced-caption lifecycle and human-cleaned GOLD remain retained baseline evidence to verify, reuse, and improve rather than rebuild.

## Evidence

### KNOWN

- P002 run `20261008T071035670Z_46adb9a1733448e3b6ff82b42b2e7de2` inspected the exact existing P001 target once, read-only.
- Target UID is `4aaa91c0-c434-4439-a15a-92ce86e80256`.
- 112/112 overlay geometry matched; title text was unobservable for every row and no title exposed a media path.
- Strict validation failed `ValueError: target_title`; tolerant structural validation passed.
- Fallback eligibility is true and product acceptance remains false.
- Reel #2 GOLD name/UID/DRT hash are retained and exact.

### INFERRED

- A future Plan may evaluate the already-tested structural/provenance fallback, but P002 does not authorize it.

### ASSUMED

- Resolve remains open and unchanged after the accepted capture until explicitly directed otherwise.

### UNKNOWN

- Persistence across save/reopen.
- Second-run/idempotency behavior and visual acceptance.

## Main Risks / SPOFs

- Treating fallback eligibility as product acceptance.
- Saving/closing/modifying Resolve before a future Plan explicitly decides the live-state policy.
- Rebuilding accepted Reel #2 lifecycle/GOLD evidence instead of reusing its proven baseline.

## Human Action Queue

1. Leave Resolve/project/target open and untouched.
2. Do not run another P002 command.
3. Wait for an explicit future Browser Architect Plan before save/close/discard or further live action.

## Latest Consequential Decision

- DECISION: P002 is accepted/closed; direct title readback is unobservable while exact structural/provenance evidence makes fallback evaluation eligible but does not establish product acceptance.
- STATUS: VALIDATED.
- DETAILS: `docs/DECISIONS.md` D009–D010.
