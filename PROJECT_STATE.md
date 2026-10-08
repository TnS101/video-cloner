# PROJECT_STATE.md — Video Cloner Current Operational Reality

> Concise evolving state. GitHub `main` + direct evidence are stronger authority. Cleanup-era history remains in `docs/CANONICAL_PROJECT_STATE.md` and `docs/VIDEO_CLONER_FINAL_HANDOFF.md`.

## Project

- PROJECT NAME: Video Cloner
- STATUS: ACTIVE
- LAST UPDATED: 2026-10-08
- PLAN-CREATION REPOSITORY HEAD: `397148c02e05e803225dec8f2723e6702ce7355f`
- LAST ACCEPTED PRODUCT COMMIT: `4516da32e6780a574e7d3904782bb1007def05e7`
- CLEANUP AUTHORITY TAG: `video-cloner-canonical-cleanup-20261007`
- RECOVERY TAG: `video-cloner-pre-hygiene-snapshot-20261007`

## Real Objective

Build and ship a deterministic editing-style engine that analyzes editing/style evidence and applies an edit reproducibly through a standalone Python API/CLI, beginning with DaVinci Resolve and remaining adapter-ready for future editors/services.

## Win Condition

A clean/raw target can be processed through the canonical pipeline and produce a persistent, safely repeatable, human-approved edited timeline whose execution does not depend on an AI agent improvising editor actions. Resolve is the first accepted adapter; additional editors are not required for the immediate ship gate.

## Urgency

Deadline has passed. Optimize for the shortest critical path to a trustworthy product result. Avoid infrastructure, research, cleanup, and dataset side quests unless they remove the current bottleneck.

## Known True Now

- Canonical GitHub `main` is `397148c02e05e803225dec8f2723e6702ce7355f`; local `main` matches and is clean at P003 creation.
- Repository cleanup and source-control reconciliation are complete.
- Normal entry points are `video-cloner run` and `video_cloner.pipeline.run()`.
- Canonical offline generation + bounded queue publication are accepted.
- Canonical bootstrap regression authority remains 116 tests; CI-equivalent core remains 64 tests. P003 defines narrower affected verification before any live gate.
- Resolve launcher wiring points to the canonical repository.
- P001 is BLOCKED/CLOSED after one import created the exact commanded target and strict validation failed `ValueError: target_title`.
- P002 is ACCEPTED/CLOSED after exactly one read-only live execution classified `DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID`.
- P002 mapped 112/112 overlays exactly; every direct title read was `null`, every title media path was empty, strict validation failed only `ValueError: target_title`, and `require_title_text=False` structural validation passed.
- P002 fallback eligibility is `true`; this is not product acceptance.
- P003 T001 is `PASS / ACCEPTED — OFFLINE`: the evidence-bound finalizer, dedicated read-only reopen verifier, focused tests, and report passed Browser Architect review.
- Accepted T001 SHA-256: finalizer `79d1a8cafecc28eb791fbfa453df80ad02be70a432e861c84500f21b8ec28c4c`; verifier `f4493d0bab98f97fc39db4b4f2bb38427d7372a1dbac7db73e9bd9af02fd767c`; focused test `153d9ec232787be430e752b8a2f7a111487859df54f6b4c5428b0430faf29f38`.
- T001 verification: focused tests `26 passed`; required affected regression `83 passed`; no queue publication or Resolve/live action occurred.
- Current timeline, all 46 timelines, 45 protected/non-target timelines, and all 55 media-pool items were unchanged; all P002 mutation counters were zero.
- Exact current target: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`, UID `4aaa91c0-c434-4439-a15a-92ce86e80256`.
- Reel #2 GOLD remains exact: timeline `DcJRJtUKScu_offline_timeline_v1`, UID `4ad2a3c3-031c-464d-96aa-76a045608ad6`, DRT SHA-256 `99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e`.
- The Reel #2 advanced-caption lifecycle and human-cleaned GOLD are retained baseline evidence to REUSE/ADAPT, not rebuild.
- Persistence across save/reopen, the declared same-target second-run behavior, and human visual acceptance remain unproven.

## Current Constraint

- The accepted fallback exists in Phase 6 regression support but is not bound to the exact P001/P002 evidence shape in the save-capable acceptance path.
- The existing live target is still unsaved and Resolve remains open.
- PH1 acceptance is blocked on one evidence-bound save, exact fail-closed same-target replay, reopen persistence/protected-state proof, and human visual decision.

## Architecture State

- ARCHITECTURE STATUS: APPROVED / UNCHANGED
- ARCHITECTURE FILE: `ARCHITECTURE.md`
- ARCHITECTURE VERSION: `A001`
- MATERIAL HUMAN APPROVAL: APPROVED

## Current Plan Partition

- CURRENT PLAN ID: `P003_FALLBACK_PERSISTENCE_ACCEPTANCE`
- PLAN STATUS: `READY_FOR_CODEX`
- INITIAL AUTHORIZATION: `T001 ONLY — OFFLINE IMPLEMENTATION / TESTS; NO COMMAND PUBLICATION; NO RESOLVE ACTION`
- T001 STATUS: `PASS / ACCEPTED — OFFLINE`
- T002 STATUS: `NEXT — NOT YET AUTHORIZED`
- T003–T007 STATUS: `NOT_STARTED — NOT AUTHORIZED`
- T002 AUTHORIZATION: Browser Architect authorization is still required before T002 may publish a finalizer command.
- PLAN FILE: `plan.md`
- PREDECESSOR: `P002_LIVE_TARGET_FORENSIC_READBACK` — `ACCEPTED / CLOSED`
- PREDECESSOR ARCHIVE: `docs/plans/archive/P002_LIVE_TARGET_FORENSIC_READBACK.md`
- REQUIRED REPORT ROOT: `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/`

## Resolve Live-State Hold

- KEEP Resolve open and `New Project 1` unchanged until a later explicit human gate.
- DO NOT save, close, reopen, switch, rename, delete, modify, import, export, render, or run a Workspace script merely because P003 exists.
- P003 live actions are sequential human gates. Each requires the preceding task report to PASS and explicit progression authorization.
- If a Save/Discard prompt appears during the later authorized close after the P003 save, cancel and report it.

## Critical Path

1. T001: `PASS / ACCEPTED — OFFLINE`; evidence-bound fallback/save boundary and dedicated read-only reopen verifier are checkpoint-ready.
2. T002–T003: one attributable finalizer invocation; accept the existing target under the evidence-backed fallback and save exactly once.
3. T004–T005: exercise the already-declared same-target `target_already_exists` fail-closed behavior with zero mutation.
4. T005–T006: human close/reopen, then one read-only persistence/protected-state verification.
5. T006–T007: human visual APPROVE/REJECT and evidence closure.

CURRENT CRITICAL MOVE: after the accepted T001 checkpoint is pushed and independently verified, execute T002 to authenticate the committed P003 implementation/evidence/runtime identities and prepare/publish exactly one save-capable finalizer command. T002 is next but not yet authorized. No command publication, Resolve/live action, save, close, or reopen is authorized by this checkpoint.

## Dependencies / Constraints

- Preserve `video_cloner.pipeline`, `video-cloner run`, the frozen importer/bridge/launcher, bounded queue publication, run/manifest provenance, and Reel #2 GOLD.
- Reuse `validate_target(..., require_title_text=False)`, snapshots/inventories, P002 evidence, and `PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1`.
- Do not weaken strict validation globally or reinterpret unobservable title text as directly verified text.
- The declared second run remains fail closed: same target + `require_target_absent=true` → `ValueError: target_already_exists` before import.
- `.agent` remains ignored Resolve runtime state; project reports belong under `.project_ops`.
- No new dependency or OSS research is authorized in P003.
- PH2 remains blocked until P003 closes with the PH1 result.

## Reuse / Research State

- P003 research gate: `NOT_APPLICABLE`.
- Decision: `REUSE / ADAPT` the existing Phase 6 semantic-provenance fallback and save-capable acceptance support.
- Reel #2 caption lifecycle/GOLD remains retained PH2 baseline evidence only; no PH2 implementation is in P003.

## Evidence

### KNOWN

- P001 import run: `20261007T173351920Z_b031b0693f6f4c7d8f8d17c6d718ce41`.
- P002 read-only run: `20261008T071035670Z_46adb9a1733448e3b6ff82b42b2e7de2`.
- Exact target UID: `4aaa91c0-c434-4439-a15a-92ce86e80256`.
- 112/112 overlay geometry and canonical expected text bindings are recorded; direct readback is unavailable and no title media path exists.
- Structural validation, target/protected/media inventories, and zero-mutation evidence pass.
- Canonical second-run contract is fail closed on an existing exact target.

### INFERRED

- The existing Phase 6 fallback/save adapter can likely be adapted without changing frozen/public code because it already owns the relevant semantic, protected-state, and save mechanisms.

### ASSUMED

- Resolve, project, target, and queue state are assumed unchanged after P002. T002 authenticates repository/evidence/artifact/queue/runtime identities but does not directly observe current Resolve state. The finalizer must re-read and compare the exact live target/protected/current-timeline/media state to the accepted P002 baseline immediately before `SaveProject`, which is permitted only if that in-invocation validation passes.

### UNKNOWN

- Whether `SaveProject` succeeds for the current target and preserves its exact state.
- Whether the saved target survives close/reopen with the same UID/signature.
- Whether the live second run returns the exact declared fail-closed result with no state change.
- Whether the human visually approves the target.

## Main Risks / SPOFs

- Confusing fallback eligibility with accepted semantic readback.
- Saving from drifted or ambiguously attributed live state.
- Treating immediate post-save readback as close/reopen persistence.
- Redefining idempotency instead of testing the existing fail-closed second-run contract.
- Allowing a save/discard prompt or visual inspection to introduce untracked state changes.

## Human Action Queue

1. Before T002 authorization: leave Resolve/project/target open and untouched; run nothing.
2. Later gates, only when explicitly authorized: one finalizer Workspace action; one fail-closed second-run Workspace action; close/reopen without accepting any prompt; one read-only verifier Workspace action; visual APPROVE/REJECT with notes.

## Latest Consequential Decision

- DECISION: P003 will adapt the existing evidence-backed Phase 6 fallback/save support, preserve the frozen importer and its declared fail-closed second-run contract, and cross save/reopen/protected-state/visual gates in strict sequence.
- STATUS: P003 remains READY_FOR_CODEX; T001 PASS / ACCEPTED — OFFLINE; T002 NEXT / NOT YET AUTHORIZED; T003–T007 NOT STARTED / NOT AUTHORIZED.
- DETAILS: `docs/DECISIONS.md` D011 and `plan.md`.
