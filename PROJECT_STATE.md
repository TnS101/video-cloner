# PROJECT_STATE.md — Video Cloner Current Operational Reality

> Concise evolving state. GitHub `main` + direct evidence are stronger authority. Cleanup-era history remains in `docs/CANONICAL_PROJECT_STATE.md` and `docs/VIDEO_CLONER_FINAL_HANDOFF.md`.

## Project

- PROJECT NAME: Video Cloner
- STATUS: ACTIVE
- LAST UPDATED: 2026-10-09
- PLAN-CREATION REPOSITORY HEAD: `a102a94b34431bcc609ed5cfc4e048cfc6b3fa0a`
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

- Canonical GitHub `main` is `a102a94b34431bcc609ed5cfc4e048cfc6b3fa0a`. Historical P003 baseline facts remain preserved below as predecessor evidence.
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
- P003 T002 is `PASS / COMMAND PREPARED`: exactly one attributable save-capable finalizer command was published for run `20261008T120754374Z_11c3411415444aa2a83b816bf7bacb88` with command SHA-256 `c9d1acf2adf64d2e798b3a70a5614ef94ccbad5cc81d4cd2edda57cfb045869a`.
- P003 is terminal `BLOCKED / CLOSED` at T003 with `BLOCKED_T003_FINALIZER_GIT_EXECUTABLE_NOT_FOUND_BEFORE_SAVE`.
- The Resolve-hosted Python process could not locate `git` at the first repository identity check. Status/report/log SHA-256 are `b4d0dc5f86e6e10e53d213555eef53b66778133cca698b8ad2503ddbcf66e139`, `2d6e3c4e84a65441a5c52e6c52334a62bf9348d03b6a2901e9e730d0a0f1aa6c`, and `830752423d9e5f4585dce47fe0e199b50c9c175c91442ea2daa670f0a722f15b`.
- Exactly one P003 finalizer invocation and one terminal failed result exist. No retry, replacement, or T004 command exists.
- `SaveProject` was not called; `saves=0` and every other mutation counter was zero. Live project/target state was not reached or observed.
- Current timeline, all 46 timelines, 45 protected/non-target timelines, and all 55 media-pool items were unchanged; all P002 mutation counters were zero.
- Exact current target: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`, UID `4aaa91c0-c434-4439-a15a-92ce86e80256`.
- Reel #2 GOLD remains exact: timeline `DcJRJtUKScu_offline_timeline_v1`, UID `4ad2a3c3-031c-464d-96aa-76a045608ad6`, DRT SHA-256 `99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e`.
- The Reel #2 advanced-caption lifecycle and human-cleaned GOLD are retained baseline evidence to REUSE/ADAPT, not rebuild.
- P004 T001 is `PASS / ACCEPTED — OFFLINE` at commit `da1d62833f1ec32ba40396a267640aa239ba7046`: focused `46 passed`, bounded affected regression `57 passed`, no command publication/queue processing/Resolve invocation/`SaveProject` occurred.
- Persistence across save/reopen, the declared same-target second-run behavior, and human visual acceptance remain unproven.

## P004 Sequencing Override — 2026-10-09

- CURRENT P004: `P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK` — `READY_FOR_CODEX`; T001 accepted OFFLINE, T002 authorized for command preparation/publication only on branch `architect/p004-persistence-unblock-draft`.
- Selected mechanism: command-bound canonical absolute Git executable plus SHA-256, checked within Resolve before either finalizer or read-only verifier Git call; original HEAD/branch checks remain mandatory.
- New immediate Win Condition: existing Reel #3 target saved exactly once and surviving one read-only close/reopen persistence cycle unchanged.
- PH2 is released immediately on `P004_PERSISTENCE_UNBLOCKED`; no intermediate acceptance Plan.
- Same-target replay/idempotency acceptance, formal pre-PH2-target human visual acceptance, and full PH1/ship certification are `PRE-SHIP DEFERRED`, not abandoned.
- P003 remains BLOCKED/CLOSED with no retry. P004 T001 is accepted. T002 may prepare and publish exactly one fresh pending finalizer command; queue processing, Resolve invocation, `SaveProject`, T003/T004, and PH2 implementation remain unauthorized.

## Current Constraint

- Resolve-hosted repository identity authentication currently depends on ambient Git executable discovery and fails when Git is absent from the Resolve process `PATH`.
- P004 draft selects Route A — authenticated absolute `git.exe` binding with executable SHA-256 plus the existing repository HEAD/branch checks.
- Route A T001 implementation is accepted at `da1d62833f1ec32ba40396a267640aa239ba7046`. Current task is T002 command preparation/publication only; P003 must not be repaired or retried and no live Resolve execution is authorized.
- PH1 remains not accepted: persistence, same-target replay, and human visual acceptance are unproven. PH2 is blocked only by exact save/reopen persistence, not full PH1 acceptance.

## Architecture State

- ARCHITECTURE STATUS: APPROVED / UNCHANGED
- ARCHITECTURE FILE: `ARCHITECTURE.md`
- ARCHITECTURE VERSION: `A001`
- MATERIAL HUMAN APPROVAL: APPROVED

## Current Plan Partition

- CURRENT PLAN ID: `P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK`
- PLAN STATUS: `READY_FOR_CODEX`
- CURRENT AUTHORIZATION: `T002 ONLY — PREPARE/PUBLISH EXACTLY ONE FRESH PENDING FINALIZER COMMAND; NO QUEUE PROCESSING; NO RESOLVE INVOCATION; NO SaveProject`
- T001 STATUS: `PASS / ACCEPTED — OFFLINE` — commit `da1d62833f1ec32ba40396a267640aa239ba7046`
- T002 STATUS: `AUTHORIZED — PREPARATION/PUBLICATION ONLY`
- T003 STATUS: `NOT_STARTED / NOT_AUTHORIZED`
- T004 STATUS: `NOT_STARTED / NOT_AUTHORIZED`
- PLAN FILE: `plan.md`
- PREDECESSOR: `P003_FALLBACK_PERSISTENCE_ACCEPTANCE` — `BLOCKED / CLOSED`
- PREDECESSOR ARCHIVE: `docs/plans/archive/P003_FALLBACK_PERSISTENCE_ACCEPTANCE.md`
- REQUIRED REPORT ROOT: `.project_ops/reports/P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK/`

## Resolve Live-State Hold

- KEEP Resolve open and `New Project 1` unchanged.
- DO NOT save, close, reopen, switch, rename, delete, modify, import, export, render, run a Workspace script, repair, retry, or publish another command under P003.
- No further P003 human gate is active. T004–T007 were cancelled by the terminal block. P004 T002 may publish exactly one pending command, but it must not be processed and Resolve must not be invoked.

## Critical Path

1. T001: `PASS / ACCEPTED — OFFLINE` at `da1d62833f1ec32ba40396a267640aa239ba7046`.
2. T002: prepare/publish exactly one fresh pending command — CURRENT.
3. T003: one live save attempt — NOT AUTHORIZED.
4. T004: one persistence cycle — NOT AUTHORIZED.
5. PASS → PH2 immediately.

CURRENT CRITICAL CONSTRAINT: complete T002 attribution/binding and publish exactly one pending finalizer command, then STOP for Browser Architect review. Do not process the queue, invoke Resolve, call `SaveProject`, start T003/T004, or begin PH2.

## Dependencies / Constraints

- Preserve `video_cloner.pipeline`, `video-cloner run`, the frozen importer/bridge/launcher, bounded queue publication, run/manifest provenance, and Reel #2 GOLD.
- Reuse `validate_target(..., require_title_text=False)`, snapshots/inventories, P002 evidence, and `PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1`.
- Do not weaken strict validation globally or reinterpret unobservable title text as directly verified text.
- The declared second run remains fail closed: same target + `require_target_absent=true` → `ValueError: target_already_exists` before import.
- `.agent` remains ignored Resolve runtime state; project reports belong under `.project_ops`.
- No new dependency or OSS research is authorized in P003.
- PH2 may start immediately after P004 proves one exact save plus close/reopen persistence; full PH1 acceptance is PRE-SHIP, not a PH2 prerequisite.

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

1. Preserve Resolve, project, and target open and unchanged.
2. During authorized P004 T002, take no human Resolve action and do not process the pending command after Codex publishes it.

## Latest Consequential Decision

- DECISION: accept P004 T001 at `da1d62833f1ec32ba40396a267640aa239ba7046` and authorize T002 only.
- STATUS: P004 `READY_FOR_CODEX`; T001 `PASS / ACCEPTED — OFFLINE`; T002 `AUTHORIZED — PREPARATION/PUBLICATION ONLY`; T003/T004 `NOT_STARTED / NOT_AUTHORIZED`.
- HARD BOUNDARY: T002 may prepare and publish exactly one fresh pending finalizer command. No queue processing, Resolve invocation, `SaveProject`, T003/T004, or PH2 implementation. STOP after T002 report for Browser Architect review.
- PREDECESSOR: P003 remains `BLOCKED / CLOSED` with no retry.
- DETAILS: `docs/DECISIONS.md` D012 and `plan.md`.
