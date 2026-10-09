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
- STATUS: VALIDATED
- DECISION: preserve the live P001 target and use exactly one bounded read-only forensic capture before repair or persistence. P002 accepted classification `DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID`: 112/112 overlays mapped exactly, every direct title read was `null`, every title media path was empty, strict validation failed `ValueError: target_title`, and tolerant structural validation passed with all protected state unchanged and all mutation counters zero.
- WHY: P002 removed the ambiguity without mutating Resolve. Existing structural/provenance evidence makes fallback evaluation eligible, while persistence, idempotency, visual acceptance, and product acceptance remain separate unproven gates.
- REVISIT IF: a future approved Plan explicitly evaluates the eligible fallback or decides the live-state/save/close policy.

## D010 — Retain Reel #2 advanced-caption lifecycle and human-cleaned GOLD

- DATE: 2026-10-08
- PLAN: P002_LIVE_TARGET_FORENSIC_READBACK
- STATUS: VALIDATED
- DECISION: retain the Reel #2 advanced-caption lifecycle and human-cleaned GOLD as baseline evidence to verify, reuse, adapt, and improve—not rebuild. The exact protected identity is timeline `DcJRJtUKScu_offline_timeline_v1`, UID `4ad2a3c3-031c-464d-96aa-76a045608ad6`, frozen DRT SHA-256 `99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e`.
- WHY: P002's unchanged full inventory independently retained the historical Resolve identity, and repository GOLD provenance matches the same name, UID, and DRT hash.
- REVISIT IF: direct evidence proves the retained GOLD identity is corrupted or superseded by an explicitly human-accepted replacement.

## D011 — Operationalize the accepted fallback without changing importer semantics

- DATE: 2026-10-08
- PLAN: P003_FALLBACK_PERSISTENCE_ACCEPTANCE
- STATUS: TERMINAL — P003 BLOCKED / CLOSED AT T003
- DECISION: adapt the existing Phase 6 save-capable acceptance support to consume the exact P001/P002 evidence and `PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1`; keep the frozen importer, public API/CLI, bridge, launcher, strict validator, and canonical same-target second-run behavior unchanged.
- WHY: P002 proved direct title text is unobservable while exact structure, artifact provenance, per-overlay expected-text binding, empty title media paths, and zero-mutation state are valid. The smallest next move is to bind that accepted evidence to the existing fallback/save boundary, not redesign title validation or import again.
- LIVE POLICY: after offline proof and explicit task gates, permit exactly one project save, one canonical same-target replay expected to fail `target_already_exists` before import, one human close/reopen, one read-only persistence verification, and one human visual APPROVE/REJECT. No retry or repair occurs inside P003.
- PRE-SAVE BOUNDARY: T002 authenticates repository/evidence/artifact/queue/runtime identities and may publish one attributable save-capable finalizer command, but it does not directly observe current Resolve state. The finalizer re-reads and compares the exact live target, protected timelines, current timeline, and media pool to the accepted P002 baseline immediately before `SaveProject`; the single save is permitted only if that validation passes. Pre-save validation and `SaveProject` deliberately share one finalizer invocation.
- TERMINAL OUTCOME: T001 passed and was accepted offline. T002 passed and prepared exactly one finalizer command. The single authorized T003 invocation, run `20261008T120754374Z_11c3411415444aa2a83b816bf7bacb88`, terminated `P003_FALLBACK_SAVE_BLOCKED` because the Resolve-hosted Python process could not locate `git` at the first repository identity check. `SaveProject` was not called; `saves=0` and every other mutation counter was zero. Live project/target state was not reached or observed.
- TERMINAL EVIDENCE: command/status/report/log SHA-256 are `c9d1acf2adf64d2e798b3a70a5614ef94ccbad5cc81d4cd2edda57cfb045869a`, `b4d0dc5f86e6e10e53d213555eef53b66778133cca698b8ad2503ddbcf66e139`, `2d6e3c4e84a65441a5c52e6c52334a62bf9348d03b6a2901e9e730d0a0f1aa6c`, and `830752423d9e5f4585dce47fe0e199b50c9c175c91442ea2daa670f0a722f15b`.
- CLOSEOUT: P003 is `BLOCKED / CLOSED`. T004–T007 were not executed and are cancelled by the terminal block. Persistence, same-target replay, and human visual acceptance remain unproven; PH1 is not accepted and PH2 remains blocked. Resolve must remain open and unchanged.
- NEXT CONSTRAINT: Resolve-hosted repository identity authentication currently depends on ambient Git executable discovery and fails when Git is absent from the Resolve process `PATH`. A fresh Browser Architect must compare an authenticated absolute Git binding, an existing repository/runtime identity mechanism, and a dependency-free HEAD verification mechanism only if safer/smaller. This decision does not select or authorize an implementation.
- ACCEPTANCE BOUNDARY: fallback eligibility is not product acceptance. `PH1_ACCEPTED` requires exact save/reopen persistence, protected/media preservation, declared zero-mutation second-run behavior, and human visual `APPROVE`.
- REVISIT IF: a fresh Browser Architect authorizes a bounded Plan that removes the ambient-`PATH` dependency without weakening repository identity authentication.

## D012 — Persistence-only production unblock; defer full PH1 acceptance until pre-ship

- DATE: 2026-10-09
- PLAN: `P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK`
- STATUS: APPROVED — P004 READY_FOR_CODEX; T001 ACCEPTED; T002 PREPARATION/PUBLICATION ONLY
- DECISION: Route A: resolve the exact absolute Git executable during offline command preparation, authenticate its canonical path and executable SHA-256, bind both into each command, and verify them inside Resolve before executing HEAD/branch checks. Apply to both the finalizer and read-only post-reopen verifier. Do not use ambient PATH or alter expected HEAD/branch enforcement. No new dependency or bridge/launcher modification.
- WHY: both P003 finalizer and verifier execute bare Git, while existing runtime repository-root binding does not provide Git HEAD/branch verification. This is an environment discovery defect, not a caption defect.
- SEQUENCING: P004 success proves one attributable save plus one close/reopen persistence readback for current Reel #3. Then PH2 caption production begins immediately, without full PH1 acceptance as an intermediate gate. Same-target replay/idempotency, formal full-target visual APPROVE/REJECT, and remaining PH1/ship checks become mandatory PRE-SHIP deferred work.
- HARD LIMIT: one identity mechanism decision, one bounded patch, one focused offline verification batch, one newly attributable save attempt, one close/reopen persistence verification; no P004 subdivisions or retries. On another pre-save environment/tooling failure, stop and present manual controlled save/reopen versus one authorized targeted automation repair; default manual unless product correctness risk. On actual target/protected/media corruption or persistence drift, stop PH2.
- PRESERVE: P003 terminal failure is closed, never retried. Existing semantic/provenance fallback, strict validation behavior, target UID, protected Reel #2 GOLD, queue/bridge/launcher, and all blocked mutation authorities remain untouched.


## D013 — Speedrun: PH2 caption production starts now; persistence moves to PRE-SHIP

- DATE: 2026-10-09
- PLAN: `P005_PH2_ADVANCED_TEXTPLUS_CAPTION_FIDELITY`
- STATUS: APPROVED / ACTIVE
- DECISION: supersede P004 as the current Critical Path and defer its remaining save/reopen + live repository-identity proof to PRE-SHIP. Start PH2 caption production immediately from the retained Reel #2 GOLD/accepted caption authorities.
- WHY: the end-of-week ship deadline makes visible feature output the binding constraint. The tracker explicitly defines PH2 as Retain / Reuse / Improve and says not to rebuild the retained Reel #2 caption baseline. P004 T002 published nothing, so deferral creates no ambiguous live state.
- PRESERVE: P004 T001 accepted repair remains in source; full persistence/idempotency/final human acceptance remain mandatory before release.
- SPEEDRUN RULE: no further Git/persistence ceremony while it does not block caption feature production.


## D014 — Integrated production slice replaces caption-only blocker loop

- DATE: 2026-10-09
- STATUS: APPROVED / ACTIVE
- PLAN: `P005_PRODUCTION_VERTICAL_SLICE_SPEEDRUN`
- DECISION: treat the Reel #2 caption identity mismatch as a bounded fidelity sub-fix, not as a global blocker. Generate one integrated production slice covering cuts, supported transitions, captions, and detection manifests for ramps/zoom/whip-slide/animation combos.
- RULE: unresolved optional identity-bound caption authority may be omitted and reported for the preview if core semantic/timing validity remains intact; mappings must never be guessed.
- NEXT: visual evidence selects the single highest-ROI production repair.


## D015 — Correct active target: Reel #3 advanced production

- DATE: 2026-10-09
- STATUS: APPROVED / ACTIVE
- DECISION: Reel #3 (`DZatr0EJt4B`) is the active production target. Reel #2 remains reference/reuse evidence only.
- CORRECTION: supersede the Reel #2 integrated-preview detour. Do not regenerate basic captions; Reel #3 already has applied captions and structural overlay validation.
- CURRENT MOVE: advanced caption animations on the existing Reel #3 target, followed immediately by Reel #3 transitions/VFX.


## D016 — Human-directed speedrun sequence and mandatory OSS reuse milestone

- DATE: 2026-10-09
- STATUS: APPROVED / HARD DIRECTIVE
- DECISION: explicit human commands are the highest product-direction authority. The active target is Reel #3 `DZatr0EJt4B`; reference reels must not be promoted to active work without explicit authorization.
- WIN CONDITION: ship a working Video Cloner by end of week that can analyze a Reel and recreate the core/basic principles of that editor's style.
- REQUIRED SEQUENCE: finish the active Reel #3 baseline for captions/advanced animation, cuts, transitions, and core motion/VFX first. After that baseline, the `PROJECT_TRACKER.xlsx` OSS research/reuse backlog layer is mandatory before broader ecosystem/functionality expansion.
- OSS RULE: research and reuse/adapt proven open-source mechanisms before custom-building equivalents; prefer `REUSE > ADAPT > COMBINE > BUILD`.
- FAILURE PREVENTION: no silent reel/phase/target pivot. If human command, tracker, state, and Plan disagree materially, stop and surface the conflict.
