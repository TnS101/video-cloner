# plan.md — CURRENT PLAN PARTITION

- PLAN ID: `P003_FALLBACK_PERSISTENCE_ACCEPTANCE`
- PLAN NAME: Evidence-Bound Fallback, Persistence, and PH1 Acceptance
- STATUS: `READY_FOR_CODEX`
- INITIAL AUTHORIZATION: `T001 ONLY — OFFLINE IMPLEMENTATION / TESTS; NO COMMAND PUBLICATION; NO RESOLVE ACTION`
- CURRENT CHECKPOINT: `T001 PASS / ACCEPTED — OFFLINE`
- NEXT TASK: `T002 — NEXT / NOT YET AUTHORIZED`
- PHASE: `PH1`
- BROWSER SESSION: `BROW-P003_FALLBACK_PERSISTENCE_ACCEPTANCE`
- CODEX SESSION: `CODEX-P003_FALLBACK_PERSISTENCE_ACCEPTANCE` (fresh session required)
- CREATED: 2026-10-08 Europe/Sofia
- BASELINE BRANCH: `main`
- BASELINE REPOSITORY HEAD: `397148c02e05e803225dec8f2723e6702ce7355f`
- BASELINE ACCEPTED PRODUCT COMMIT: `4516da32e6780a574e7d3904782bb1007def05e7`
- BASELINE TAG: `video-cloner-canonical-cleanup-20261007`
- ARCHITECTURE VERSION: `A001`
- PREDECESSOR: `P002_LIVE_TARGET_FORENSIC_READBACK` — `ACCEPTED / CLOSED`

> One Plan = one observable result: decide PH1 acceptance for the exact existing P001 target by operationalizing the accepted structural/provenance fallback, proving one project save plus reopen persistence, exercising the already-declared fail-closed second-run behavior, preserving protected state, and recording a human visual APPROVE/REJECT.

> P003 architecture and T001 offline implementation are accepted. T002 is next but is **not yet authorized**. Browser Architect authorization is still required before T002 may publish a finalizer command. No command publication, Resolve action, save, close, reopen, or visual gate is authorized by this checkpoint.

> CURRENT CRITICAL MOVE: after the accepted T001 checkpoint is pushed and independently verified, T002 authenticates the committed P003 implementation/evidence/runtime identities and prepares/publishes exactly one save-capable finalizer command. Resolve remains open and unchanged; PH2 remains blocked.

## 1. Objective — One Observable Result

For the exact existing target `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B` in project `New Project 1`, produce one attributable PH1 acceptance result:

- `PH1_ACCEPTED` only if the accepted P002 fallback is applied without semantic or structural contradiction, `SaveProject` succeeds exactly once, the exact target and all protected state survive close/reopen, the canonical same-target second run fails closed exactly as already declared with zero mutation, and the human returns visual `APPROVE`;
- `PH1_VISUAL_REJECTED` if all machine gates pass but the human returns visual `REJECT`;
- otherwise stop at the first failed gate with a precise `BLOCKED_*` result and no retry.

Machine acceptance and human visual acceptance remain separate evidence fields. Fallback eligibility alone is not product acceptance.

## 2. Main Constraint / Why Now

- P002 removed the only causal ambiguity: direct Resolve title-text readback is unobservable for all 112 overlays, while exact overlay geometry, title media-path emptiness, structural validation, artifact identity, and one-import provenance are valid.
- The remaining PH1 blocker is not title diagnosis. It is that the eligible fallback is not yet bound to the current P001 evidence shape and used by the save-capable acceptance adapter.
- Persistence across save/reopen, protected-state preservation through that boundary, the declared same-target second-run behavior, and human visual fidelity are still unproven.
- PH2, OSS research, caption enhancement, and broader product work remain blocked until this PH1 acceptance decision exists.

## 3. Existing-Mechanism Decision — REUSE / ADAPT

### Reuse

- `resolve_workspace/modules/video_cloner_phase6_textplus_application.py` remains the frozen import/structural authority.
- `validate_target(..., require_title_text=False)`, snapshots, inventories, artifact loading, run IDs, manifests, queue publication, and the bridge contract remain authoritative.
- `resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py` already owns the save-capable readback/protected-state boundary and `PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1` semantics.
- P002's completed command/report/status/log provide the accepted direct-readback limitation, exact target UID, per-overlay evidence, and zero-mutation baseline.
- The canonical importer's declared same-target second run remains: `require_target_absent=true` fails closed with `ValueError: target_already_exists`, zero import, and no duplicate.

### Adapt

Adapt only the existing Phase 6 live-application acceptance support needed to consume the exact P001/P002 evidence schemas and current 112-title contract. Add the smallest read-only post-reopen verifier needed to compare the reopened state with the accepted pre-save/saved baseline.

### Do not redesign

- Do not weaken strict `validate_target(...)` or claim direct title text became observable.
- Do not change the frozen importer, launcher, bridge, public `video_cloner.pipeline` API, normal `video-cloner run` flow, compiler, or FCPXML.
- Do not invent a successful reuse/no-op second-run contract. P003 must test the already-declared fail-closed contract.
- RESEARCH GATE: `NOT_APPLICABLE`; no new mechanism, dependency, renderer, or adapter is being selected.

## 4. Accepted Baseline and Exact Evidence Binding

P003 must bind before any live publication:

- repository `main`: `397148c02e05e803225dec8f2723e6702ce7355f`;
- P001 run ID: `20261007T173351920Z_b031b0693f6f4c7d8f8d17c6d718ce41`;
- P002 run ID: `20261008T071035670Z_46adb9a1733448e3b6ff82b42b2e7de2`;
- project: `New Project 1`;
- target: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`;
- target UID: `4aaa91c0-c434-4439-a15a-92ce86e80256`;
- classification: `DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID`;
- fallback eligibility: `true`;
- P001 T002 and P002 T001/T002/T003 reports;
- exact completed P001/P002 command/report/status/log identities recorded in those reports;
- canonical manifest and artifact identities recorded by P002 T002;
- P002 baseline: 46 timelines, 45 protected timelines, 55 media items, all inventories unchanged, all mutation counters zero;
- protected Reel #2 GOLD: `DcJRJtUKScu_offline_timeline_v1`, UID `4ad2a3c3-031c-464d-96aa-76a045608ad6`, DRT SHA-256 `99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e`.

Any missing, changed, ambiguous, stale, or contradictory identity is a STOP before publication.

## 5. Live-State Policy

Until T002 explicitly reaches its human gate:

- keep Resolve and `New Project 1` open;
- keep the target and current timeline unchanged;
- do not save, close, reopen, switch, rename, delete, edit, import, export, render, or run a Workspace script.

P003 may later authorize only these state transitions, in order:

1. one evidence-bound `SaveProject` call by the P003 finalizer;
2. one canonical same-target second-run invocation expected to fail before import with `target_already_exists`;
3. after both reports pass, one human close/reopen of Resolve/project for persistence proof;
4. one read-only post-reopen verification invocation;
5. after machine acceptance, human timeline selection/playback solely for visual review, with no edit or save.

If Resolve presents a save/discard prompt during the authorized close after the successful P003 save, the human must cancel the close and report the prompt. Do not choose Save or Discard.

## 6. IN Scope

- Minimal adaptation of the current Phase 6 save-capable acceptance module to the exact P001/P002 evidence shape.
- One minimal read-only post-reopen verifier, reusing existing snapshot/inventory/structural/fallback mechanisms.
- Focused offline tests and the affected Phase 6/bridge/queue regressions.
- Exact queue/provenance/frozen-identity gates before every live command.
- One save-capable finalization invocation.
- One canonical same-target fail-closed second-run invocation.
- One read-only post-reopen verification invocation.
- Human close/reopen and final visual APPROVE/REJECT only at explicit gates.
- Required P003 reports under `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/`.

## 7. OUT of Scope

- A second import, duplicate target, replacement, deletion, rename, relink, media import, title/Fusion write, metadata write, export, render, or repair.
- Changing the frozen importer, launcher, bridge, public API/CLI, compiler, FCPXML, analysis, planning, profiles, captions, transitions, fonts, animation, or Reel #2 GOLD.
- Redefining the same-target second-run contract.
- PH2 work, caption lifecycle changes, font/animation improvement, OSS research, benchmarks, datasets, or future Plan creation.
- Visual self-approval by Codex.
- Retrying any live action after its first invocation.

## 8. Preserve / Regression Guard

Must remain unchanged except for the single authorized project save:

- exact target name, UID, signature, 8 video clips, 1 audio clip, 112 overlays, 673-frame duration, overlay geometry, and empty title media paths;
- all 45 non-target/protected timeline identities and observable signatures;
- full 46-timeline inventory count;
- all 55 media-pool items;
- Reel #2 GOLD name and UID;
- current timeline through machine tasks unless Resolve itself restores a different selection after reopen; selection variance must be recorded separately and may not hide content drift;
- canonical artifacts, P001/P002 evidence, frozen importer, launcher, bridge, public queue contract, and repository architecture.

## 9. Worker Decision Boundary

Codex MAY decide locally:

- the smallest compatible field-normalization needed to bind P001/P002 reports without weakening identity;
- whether the post-reopen verifier is a small dedicated module or a strictly read-only mode in the adapted acceptance module, whichever yields the smaller auditable call surface;
- exact P003 report/artifact filenames under the required namespaces;
- path separator/case normalization that preserves exact file identity.

Codex MUST STOP / escalate for:

- any need to change frozen/public product code or architecture;
- any direct semantic contradiction, partial title observability, non-empty title media path, structural mismatch, target UID change, artifact hash change, or inventory drift;
- any save count other than exactly one in the finalizer;
- any active/stale/ambiguous queue state;
- any second-run result other than the exact declared fail-closed result;
- a save/discard prompt during close, reopen ambiguity, missing project/target after reopen, or protected/media drift;
- any live retry, cleanup, rollback, or product repair;
- human visual `REJECT` or required subjective judgment.

## 10. Tasks

### T001 — Adapt and Prove the Evidence-Bound Acceptance Surface

**Status:** `PASS / ACCEPTED — OFFLINE`

**Objective:** make the smallest offline-proven adapter change that consumes the exact accepted P001/P002 evidence, applies the existing structural/provenance fallback, allows exactly one save, and supports zero-mutation post-reopen verification.

**Allowed tracked changes:**

- `resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py`;
- at most one small dedicated P003 read-only verifier module if materially simpler than a second mode;
- focused corresponding tests;
- P003 `T001/REPORT.md`.

**Required behavior:**

1. authenticate exact repository, project, target, UID, manifest/artifact, P001 import, P002 classification, completed command/report/status/log, and file hashes;
2. require P002 `fallback_eligible=true`, exact 112/112 overlay mapping, every expected text matching the canonical contract, every observed title text `null`, every title media path empty, strict failure exactly `ValueError: target_title`, structural validation PASS, and every P002 mutation counter zero;
3. re-read the live target structurally before save and compare current timeline, target, protected timelines, and media pool to the P002 baseline;
4. reuse `PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1` semantics without requiring irrelevant historical Reel #2 report schemas;
5. permit only one `SaveProject`; all other mutation capabilities remain explicitly false;
6. verify target/protected/media/current state immediately after save;
7. provide a read-only post-reopen path that verifies the exact saved target and full protected/media state without selecting or mutating a timeline;
8. fail closed on any contradiction or incomplete evidence.

**Offline tests:** accepted P001/P002 schema passes; wrong run/hash/UID/classification/fallback flag/overlay text/geometry/media path/validation result/counter fails; pre-save drift fails before save; save false fails; post-save drift fails; save count exactly one; post-reopen verifier has a prohibited-mutation static call-surface test and rejects persistence/protected/media drift.

**Verification:** focused P003 tests, `tests/test_video_cloner_p002_live_target_forensic_readback.py`, `tests/test_video_cloner_phase6_offline_timeline_live_application.py`, `tests/test_prepare_video_cloner_fresh_mvp_timeline.py`, `tests/test_vc_agent_bridge.py`, and `git diff --check`.

**Required report:** `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/T001/REPORT.md`

**STOP:** return T001 evidence for Browser Architect/user progression approval. Do not publish a command.

**Accepted checkpoint evidence:** finalizer SHA-256 `79d1a8cafecc28eb791fbfa453df80ad02be70a432e861c84500f21b8ec28c4c`; verifier SHA-256 `f4493d0bab98f97fc39db4b4f2bb38427d7372a1dbac7db73e9bd9af02fd767c`; focused test SHA-256 `153d9ec232787be430e752b8a2f7a111487859df54f6b4c5428b0430faf29f38`; focused tests `26 passed`; required affected regression `83 passed`; no live action or queue publication occurred.

### T002 — Prepare One Save-Capable Finalization Command

**Status:** `NEXT — NOT YET AUTHORIZED`

Browser Architect authorization is still required before T002 may publish a finalizer command.

**Objective:** authenticate the exact repository, evidence, artifact, queue, and runtime identities and publish one attributable save-capable P003 finalizer command. T002 does not claim to directly observe current Resolve state.

**Requirements:** clean/explained Git state; exact baseline/evidence hashes; frozen launcher/bridge/importer identity; empty pending/running queue; exact installed repository identity; focused regressions repeated; one unique run ID; `SaveProject=true`; import/delete/replace/relink/media/title/Fusion/metadata/export/render/timeline-selection permissions false; retry false. The finalizer itself must re-read and compare the exact current live target, protected-timeline, current-timeline, and media-pool state to the accepted P002 baseline immediately before `SaveProject`. `SaveProject` is permitted only if that in-invocation pre-save validation passes. Pre-save validation and the single `SaveProject` deliberately remain within one finalizer invocation; no separate pre-save live invocation is authorized.

**Required report:** `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/T002/REPORT.md`

**HUMAN GATE 1:** only after T001 and T002 PASS, run Resolve → Workspace → Scripts → `VC_Run_Agent_Task` exactly once. Do not close/reopen or visually edit yet.

### T003 — Verify Fallback Finalization and One Save

**Status:** `NOT_STARTED — NOT AUTHORIZED`

**Objective:** consume the first P003 result without another live call.

**PASS requires:** exact command/run binding; fallback policy accepted; pre-save and immediate post-save target signature exact; exact UID; 46 timelines / 45 protected / 55 media items unchanged; `saves=1`; every other mutation counter zero; `SaveProject` succeeded; no second finalizer exists.

**Required report:** `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/T003/REPORT.md`

**STOP:** no T004 publication without explicit progression approval.

### T004 — Prepare the Declared Same-Target Second Run

**Status:** `NOT_STARTED — NOT AUTHORIZED`

**Objective:** publish one new-run-ID canonical import command for the same exact target to test the already-declared fail-closed contract.

**Expected behavior:** because the exact target already exists and `require_target_absent=true`, the frozen importer returns `ValueError: target_already_exists` before `ImportTimelineFromFile`; import/save/delete/relink/metadata counts remain zero and no duplicate is created.

**Required report:** `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/T004/REPORT.md`

**HUMAN GATE 2:** only after T004 PASS, run `VC_Run_Agent_Task` exactly once. The visible failure is expected; do not retry.

### T005 — Verify Fail-Closed Second Run and Prepare Reopen Readback

**Status:** `NOT_STARTED — NOT AUTHORIZED`

**Objective:** bind the exact expected failed command/result and, only if exact, publish one read-only post-reopen verifier command.

**PASS requires:** `ValueError: target_already_exists`; import/save/delete/relink/metadata counters all zero; one target only; no retry/duplicate; clean pending/running queue before publishing exactly one read-only verifier; every verifier mutation permission false.

**Required report:** `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/T005/REPORT.md`

**HUMAN GATE 3:** after T005 PASS, close Resolve. If any Save/Discard prompt appears, cancel and report it. Otherwise reopen Resolve, open `New Project 1` if needed, make no edits or timeline selection changes, then run `VC_Run_Agent_Task` exactly once for the pending read-only verifier.

### T006 — Verify Save/Reopen Persistence and Protected State

**Status:** `NOT_STARTED — NOT AUTHORIZED`

**Objective:** consume the post-reopen read-only report and decide machine acceptance.

**PASS requires:** exact project, target name, UID, signature, structure, 112 overlay geometry, empty title media paths, 46 timelines, 45 protected signatures including Reel #2 GOLD, and 55 media items match the accepted saved baseline; all verifier mutation counters zero; exactly one verifier invocation; no unexpected state drift.

**Required report:** `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/T006/REPORT.md`

**HUMAN GATE 4 — VISUAL:** only after T006 PASS, the human may select/open the target for inspection without editing or saving and return exactly `APPROVE` or `REJECT` plus concise notes on cuts, audio, captions/text, timing, framing, and obvious corruption.

### T007 — Record Human Decision and Close P003 Evidence

**Status:** `NOT_STARTED — NOT AUTHORIZED`

**Objective:** record the human decision only; no live call and no product change.

- `APPROVE` plus all machine gates PASS → `PH1_ACCEPTED`.
- `REJECT` plus all machine gates PASS → `PH1_VISUAL_REJECTED`; do not repair in P003.

**Required report:** `.project_ops/reports/P003_FALLBACK_PERSISTENCE_ACCEPTANCE/T007/REPORT.md`

**STOP:** Browser Architect reviews and closes/archives P003. Codex does not create the next Plan.

## 11. Acceptance Criteria

| Criterion | Required evidence |
|---|---|
| fallback operationalized | exact P001/P002 evidence accepted under `PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1`; no semantic contradiction |
| target identity | exact name + UID + canonical artifact binding |
| save | exactly one successful `SaveProject`; no other mutation in finalizer |
| persistence | exact target survives human close/reopen and read-only verification |
| protected state | all 45 protected timelines, Reel #2 GOLD, and 55 media items unchanged |
| second run | canonical same-target replay fails `target_already_exists` before import; zero mutation; one target remains |
| visual | explicit human `APPROVE` or `REJECT` recorded separately |
| product acceptance | only `APPROVE` plus every machine gate PASS yields `PH1_ACCEPTED` |

## 12. Repair Limit

- Before any P003 live invocation: one bounded T001 correction is allowed if focused offline evidence exposes a defect in the new/adapted P003 support only.
- After the first P003 live invocation: zero product repairs, zero retries, zero replacement commands for a failed gate.
- The expected T004 fail-closed result is not a retry or defect; any other result is a stop.
- Visual rejection closes P003 as `PH1_VISUAL_REJECTED`; it does not authorize repair.

## 13. Rollback

- Repository changes are Git-reversible.
- The single project save is an intentional one-way external-state transition. Do not attempt ad hoc discard, delete, restore, or project-backup manipulation under P003.
- If a post-save gate fails, preserve the exact state/evidence and stop. Never delete or replace the target or mutate Reel #2 GOLD.

## 14. Stop Conditions

Stop immediately on unexplained Git state, stale/ambiguous queue state, identity/hash mismatch, title contradiction, structural mismatch, target/protected/media drift, unauthorized mutation, save count mismatch, unexpected second-run result, close prompt, reopen ambiguity, persistence failure, human visual rejection, need for retry/repair, or scope/architecture/dependency expansion.

## 15. Partition Close Procedure

After T007 or the first blocked gate:

1. Browser Architect reviews actual diffs and all P003 reports/live artifacts;
2. synchronize `PROJECT_STATE.md`, `PROJECT_TRACKER.xlsx`, and `docs/DECISIONS.md` to the evidence;
3. archive this Plan to `docs/plans/archive/P003_FALLBACK_PERSISTENCE_ACCEPTANCE.md`;
4. commit accepted closeout if authorized;
5. end this partition;
6. create no next Plan in this Codex session.
