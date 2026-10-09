# PROJECT_STATE.md — Video Cloner Current Operational Reality

## Project

- STATUS: ACTIVE — SPEEDRUN
- DEADLINE: ship usable Video Cloner by end of week
- CURRENT PLAN: `P005_PH2_ADVANCED_TEXTPLUS_CAPTION_FIDELITY`
- CURRENT PHASE: PH2 — FEATURE / PRODUCTION
- CURRENT MOVE: build a real Reel #2 caption production preview package from retained accepted authorities

## Real Objective / Win Condition

Ship a deterministic Video Cloner that can produce a visually strong, editable video result. This week, visible caption fidelity is the highest-value feature bottleneck.

## Known Working / Reuse Assets

- Public pipeline/API architecture remains accepted and unchanged.
- Reel #2 GOLD remains retained baseline evidence: timeline `DcJRJtUKScu_offline_timeline_v1`, UID `4ad2a3c3-031c-464d-96aa-76a045608ad6`, DRT SHA-256 `99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e`.
- Tracker PH2 explicitly says **Retain / Reuse / Improve** and **do not rebuild from scratch**.
- Accepted Reel #2 authorities exist for static style, font choices, position, opacity/gradient examples, lifecycle correction and motion.
- Canonical caption modules already exist under `video_cloner/captions`; Step 3C/3D mechanisms and focused caption tests survived cleanup.
- P004 T001 Git executable repair passed offline at `da1d62833f1ec32ba40396a267640aa239ba7046`.
- P004 T002 published nothing; no queue command, Resolve invocation or SaveProject occurred.

## Current Constraint

**Production caption fidelity / visual proof.** We have substantial caption machinery and accepted evidence, but need one real canonical caption package and a visual production preview instead of more infrastructure ceremony.

## Critical Path

1. P005 T001 — generate/validate real retained-baseline caption package.
2. P005 T002 — one Resolve visual caption preview + human APPROVE/REJECT.
3. If rejected: one bounded visual fidelity repair; if approved: freeze caption baseline and continue next production feature.

## Current Plan Partition

- PLAN: `P005_PH2_ADVANCED_TEXTPLUS_CAPTION_FIDELITY`
- STATUS: `READY_FOR_CODEX`
- T001: `AUTHORIZED — FEATURE/PRODUCTION OFFLINE PACKAGE`
- T002: `NOT_STARTED / NOT_AUTHORIZED`
- T003: `CONDITIONAL / NOT_AUTHORIZED`
- PREDECESSOR: `P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK` — `SUPERSEDED / PRE-SHIP DEFERRED`
- P004 ARCHIVE: `docs/plans/archive/P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK.md`

## PRE-SHIP Debt — Deferred, Not Forgotten

- save/reopen persistence;
- live repository identity proof;
- same-target replay/idempotency;
- final full-target human acceptance / ship certification.

Do not work these while captions are the bottleneck.

## Speedrun Guardrails

- No new Git/process micro-plan unless it directly blocks product work.
- No caption rebuild; reuse accepted Reel #2 assets.
- No generic refactor without a visible production payoff.
- Prefer a real output artifact over another diagnostic report.
- After a real visual preview, fix only material visible deltas.
