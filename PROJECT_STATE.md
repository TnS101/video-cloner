# PROJECT_STATE.md — Video Cloner Current Operational Reality

> Concise evolving state. GitHub `main` + direct evidence are stronger authority. Cleanup-era history remains in `docs/CANONICAL_PROJECT_STATE.md` and `docs/VIDEO_CLONER_FINAL_HANDOFF.md`.

## Project

- PROJECT NAME: Video Cloner
- STATUS: ACTIVE
- LAST UPDATED: 2026-10-08
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
- P001 is BLOCKED/CLOSED: one authorized live import created/found the exact commanded target, then machine validation failed with `ValueError: target_title`.
- Persistence, protected-state preservation, second-run/idempotency behavior, and visual acceptance remain unproven.
- Advanced caption/font/opacity/stroke/camera/Flash/occlusion sources are indexed as deferred, not active operator paths.

## Current Constraint

- MAIN BOTTLENECK: Resolve title readback/validation boundary.
- WHY: the canonical live import created/found the exact target, but current machine validation stopped at `ValueError: target_title` before persistence, protected-state, idempotency, or visual acceptance could be proven.
- NEXT TECHNICAL MOVE: UNDEFINED; only a fresh Browser Architect chat may define the next bounded Plan.

## Architecture State

- ARCHITECTURE STATUS: APPROVED
- ARCHITECTURE FILE: `ARCHITECTURE.md`
- MATERIAL HUMAN APPROVAL: APPROVED

## Current Plan Partition

- CURRENT PLAN ID: `P001_LIVE_RESOLVE_ACCEPTANCE`
- PLAN STATUS: `BLOCKED / CLOSED`
- BROWSER SESSION: `BROW-P001_LIVE_RESOLVE_ACCEPTANCE` (this browser chat)
- CODEX SESSION: `CODEX-P001_LIVE_RESOLVE_ACCEPTANCE`
- ARCHIVED PLAN: `docs/plans/archive/P001_LIVE_RESOLVE_ACCEPTANCE.md`
- CURRENT REPORT: `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T002/REPORT.md`
- FURTHER RESOLVE ACTION UNDER P001: NOT AUTHORIZED

## Next Plan Partition

- NEXT PLAN ID: UNDEFINED
- NEXT PLAN PURPOSE: determined only by a fresh Browser Architect chat from the closed P001 evidence
- MAY BE CREATED NOW: YES — fresh Browser Architect chat only

## Critical Path

1. P001 isolated the live failure to the Resolve title readback/validation boundary.
2. A fresh Browser Architect chat reviews the closed evidence and defines the next bounded Plan.
3. Persistence, protected-state, idempotency, and visual acceptance remain future gates.

CURRENT CRITICAL MOVE: UNDEFINED — no active Plan after P001 closure

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
- P001 run `20261007T173351920Z_b031b0693f6f4c7d8f8d17c6d718ce41` called `ImportTimelineFromFile` once and created/found target `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`.
- The matching bridge result was `BLOCKED_LIVE_ACCEPTANCE` with `ValueError: target_title`; T003 was not executed.

### INFERRED

- The most likely failure boundary is Resolve title-item readback versus the current validator's expected title representation; exact mismatch values were not recorded.

### ASSUMED

- NONE for closed P001.

### UNKNOWN

- The exact observed title value/media-path condition that triggered `target_title`.
- Whether the created target persists across save/reopen.
- Whether protected state remained unchanged.
- Second-run/idempotency behavior and visual acceptance.

## Main Risks / SPOFs

- Conflating the created target with machine acceptance, persistence, protected-state proof, or visual fidelity.
- Retrying or patching the closed acceptance Plan instead of isolating root cause in a new bounded Plan.
- Treating flattened source reconstruction as raw style-transfer proof.

## Human Action Queue

NONE under P001. No further Resolve action is authorized by the closed Plan.

## Latest Consequential Decision

- DECISION: isolate live Resolve acceptance from repair work.
- WHY: P001 produced an attributable `target_title` failure without retrying or patching inside acceptance; root cause belongs to a new bounded Plan.
- STATUS: VALIDATED BY P001 CLOSURE
- DETAILS: `docs/DECISIONS.md`
