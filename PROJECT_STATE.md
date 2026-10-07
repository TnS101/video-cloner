# PROJECT_STATE.md — Video Cloner Current Operational Reality

> Concise evolving state. GitHub `main` + direct evidence are stronger authority. Cleanup-era history remains in `docs/CANONICAL_PROJECT_STATE.md` and `docs/VIDEO_CLONER_FINAL_HANDOFF.md`.

## Project

- PROJECT NAME: Video Cloner
- STATUS: ACTIVE
- LAST UPDATED: 2026-10-07
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

- GitHub `main` is canonical repository/software authority.
- Repository cleanup and source-control reconciliation are complete.
- Normal entry points are `video-cloner run` and `video_cloner.pipeline.run()`.
- Canonical offline generation + bounded queue publication are accepted.
- Canonical regression: 116 passed; CI-equivalent core: 64 passed.
- Resolve launcher wiring is ready and points to the canonical repository.
- Live Resolve machine acceptance is NOT ACCEPTED.
- Advanced caption/font/opacity/stroke/camera/Flash/occlusion sources are indexed as deferred, not active operator paths.

## Current Constraint

- MAIN BOTTLENECK: live Resolve machine acceptance.
- WHY: until the published canonical command is proven to apply, persist, read back with correct target identity, and satisfy declared second-run behavior, downstream visual/product work rests on an untrusted execution boundary.
- LIKELY NEXT BOTTLENECK: visual fidelity / missing deferred capabilities, determined only after P001 evidence.

## Architecture State

- ARCHITECTURE STATUS: APPROVED
- ARCHITECTURE FILE: `ARCHITECTURE.md`
- MATERIAL HUMAN APPROVAL: APPROVED

## Current Plan Partition

- CURRENT PLAN ID: `P001_LIVE_RESOLVE_ACCEPTANCE`
- PLAN STATUS: `READY_FOR_CODEX`
- BROWSER SESSION: `BROW-P001_LIVE_RESOLVE_ACCEPTANCE` (this browser chat)
- CODEX SESSION: `CODEX-P001_LIVE_RESOLVE_ACCEPTANCE`
- CURRENT `plan.md`: `/plan.md`
- CURRENT REPORT: NONE

## Next Plan Partition

- NEXT PLAN ID: UNDEFINED
- NEXT PLAN PURPOSE: determined only after P001 closes from evidence
- MAY BE CREATED NOW: NO

## Critical Path

1. Prove controlled live Resolve apply + persistence/identity.
2. Prove declared second-run/idempotency behavior + human visual gate.
3. Use evidence to choose the next smallest product blocker (likely visual fidelity/deferred capability canonicalization).
4. Prove real style transfer on clean/raw footage before claiming generalization.
5. Only then expand adapters/content-ecosystem integrations.

CURRENT CRITICAL MOVE: `P001_LIVE_RESOLVE_ACCEPTANCE`

## Dependencies / Constraints

- Preserve clean canonical package/API architecture.
- `.agent` is reserved for Resolve runtime state; project ops use `.project_ops`.
- Multi-runtime Python environments remain valid architecture until evidence justifies consolidation.
- Prefer local/FOSS/free mechanisms; paid dependencies require explicit human approval.
- Flattened finished Reel reconstruction is not sufficient final proof of style transfer.

## Reuse / Research State

- RESEARCH GATE FOR P001: NOT_APPLICABLE
- REASON: P001 validates already-approved mechanisms; no new dependency/architecture choice is being made.
- FUTURE RULE: targeted OSS scan is required when selecting/changing a renderer, rough-cut engine, editor adapter, or other material mechanism.
- RESEARCH FILE: `docs/RESEARCH_BASELINE.md`

## Evidence

### KNOWN

- Cleanup authority tag and GitHub main establish the clean baseline.
- Canonical E2E offline run and bounded publication passed.
- Installed Resolve launcher/bridge hashes were verified against repository state.
- Previous live Resolve bridge transactions were machine-unaccepted after validation.

### INFERRED

- The next highest-value test is the live boundary itself, not more repository work.

### ASSUMED

- Current installed Resolve environment remains materially the same as the Step 5 launcher verification until P001 preflight proves otherwise.

### UNKNOWN

- Whether the next controlled live application persists the intended target with correct readback.
- Whether declared second-run behavior is safe/idempotent in the real Resolve environment.
- Whether the resulting timeline is visually acceptable to the human.

## Main Risks / SPOFs

- Conflating timeline creation with machine acceptance or visual fidelity.
- Mutating a protected/incorrect timeline.
- Debugging/fixing inside an acceptance Plan and recreating patch loops.
- Treating flattened source reconstruction as raw style-transfer proof.

## Human Action Queue

P001 will require explicit Resolve Workspace execution and human visual approval. Codex must stop and request each action with exact run/target evidence.

## Latest Consequential Decision

- DECISION: isolate live Resolve acceptance from repair work.
- WHY: one clean acceptance boundary makes failures attributable; defects become a separate investigation Plan.
- STATUS: OPEN UNTIL P001 CLOSES
- DETAILS: `docs/DECISIONS.md`
