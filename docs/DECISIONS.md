# DECISIONS.md — Consequential Video Cloner Decisions

Only decisions that materially constrain future work belong here.

## D001 — Canonical software authority

- DATE: 2026-10-07
- STATUS: VALIDATED
- DECISION: GitHub `main` and annotated tag `video-cloner-canonical-cleanup-20261007` are the canonical software authority. Git history/recovery tag are the archive.
- WHY: repository cleanup reconciled stale history without reintroducing deleted runtime source.
- REVISIT IF: GitHub authority diverges or repository policy changes materially.

## D002 — Standalone application boundary

- DATE: 2026-10-07
- STATUS: VALIDATED
- DECISION: normal operation goes through `video-cloner run` / `video_cloner.pipeline`, not BAT/PowerShell/N8N chains.
- WHY: one decoupled orchestration layer is required for future UI/service/editor adapters.
- REVISIT IF: evidence proves the public API cannot express a required workflow safely.

## D003 — Resolve is an explicit live boundary

- DATE: 2026-10-07
- STATUS: VALIDATED
- DECISION: public pipeline publishes a bounded command; Resolve mutation occurs only through explicit Workspace launcher/bridge action.
- WHY: deterministic execution, provenance, fail-closed safety, and human control.
- REVISIT IF: a future editor adapter exposes a safer deterministic transaction mechanism.

## D004 — Project-ops namespace

- DATE: 2026-10-07
- STATUS: VALIDATED
- DECISION: bootstrap/project-management files use `.project_ops`; `.agent` remains reserved for Resolve runtime/queue state.
- WHY: avoid semantic collision and ignored-file loss.

## D005 — GitHub-first browser context

- DATE: 2026-10-07
- STATUS: VALIDATED
- DECISION: new Browser Architect chats read canonical files directly from GitHub. Context ZIP is fallback only.
- WHY: clean GitHub authority now exists; repeated ZIP handoffs create stale-context risk and manual friction.

## D006 — Conditional research gate

- DATE: 2026-10-07
- STATUS: VALIDATED
- DECISION: 5–10+ OSS/existing-solution research is mandatory when choosing/changing a material mechanism/dependency/adapter, not before every late-stage acceptance/debug Plan.
- WHY: preserve reuse discipline without delaying the current critical path.

## D007 — External skills are not a universal blocker

- DATE: 2026-10-07
- STATUS: VALIDATED
- DECISION: Codex should use relevant globally installed skills when present, but missing Ponytail/global skills block only when the current Plan explicitly requires one.
- WHY: unknown external installation state must not become an artificial SPOF.

## D008 — P001 isolates acceptance from repair

- DATE: 2026-10-08
- PLAN: P001_LIVE_RESOLVE_ACCEPTANCE
- STATUS: VALIDATED
- DECISION: do not retry or patch inside P001. P001 closes BLOCKED after `ValueError: target_title`; root-cause work becomes a new bounded Plan created by a fresh Browser Architect chat.
- WHY: P001 proved the acceptance-vs-repair boundary works: one controlled execution produced attributable live evidence without starting a patch loop or authorizing a second Resolve run.

## D009 — Preserve P001 live state and diagnose read-only before repair/persistence

- DATE: 2026-10-08
- PLAN: P002_LIVE_TARGET_FORENSIC_READBACK
- STATUS: ACTIVE
- DECISION: keep Resolve and the current project open with the P001 target untouched until one bounded read-only forensic capture classifies `target_title`. Do not save, close/revert, switch timeline, rename/delete/modify the target, import again, or run unrelated Resolve commands before capture. After capture, save/discard/close remains an explicit Browser Architect + human decision.
- WHY: P001 aborted before recording the exact title text/media-path condition, target UID, and post-import inventories. Existing code already proves a tolerant structural/provenance route can be valid when direct title readback is genuinely unavailable, but the current save-capable regression-support runner requires prerequisite evidence P001 did not produce and is not safe as the first diagnostic action. The live unsaved target is therefore the highest-value evidence and must not be contaminated before zero-mutation inspection.
- REVISIT IF: P002 T003 captures sufficient attributable evidence to retire the live state safely, or if independent evidence proves the live state was already saved/closed/modified.
