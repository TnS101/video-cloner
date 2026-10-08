# plan.md — CURRENT PLAN PARTITION

- PLAN ID: `P002_LIVE_TARGET_FORENSIC_READBACK`
- PLAN NAME: Read-Only P001 Live Target Forensic Classification
- STATUS: `READY_FOR_CODEX`
- PHASE: `PH1`
- BROWSER SESSION: `BROW-P002_LIVE_TARGET_FORENSIC_READBACK`
- CODEX SESSION: `NOT_STARTED`
- CREATED: 2026-10-08 Europe/Sofia
- BASELINE BRANCH: `main`
- BASELINE REPOSITORY HEAD: `41ff2537c8de610df71b502f071c00d919bf43b0`
- BASELINE ACCEPTED PRODUCT COMMIT: `4516da32e6780a574e7d3904782bb1007def05e7`
- BASELINE TAG: `video-cloner-canonical-cleanup-20261007`
- ARCHITECTURE VERSION: `A001`
- PREDECESSOR: `P001_LIVE_RESOLVE_ACCEPTANCE` — `BLOCKED / CLOSED`

> One Plan = one bounded result. P002 is DIAGNOSIS ONLY. It must classify the existing P001 live target without saving it, importing again, repairing it, or proving persistence/idempotency/visual acceptance.

## 1. Objective — One Observable Result

Produce one attributable, zero-mutation forensic report for the **existing live P001 target** that distinguishes the `ValueError: target_title` failure into one of these evidence-backed classes:

1. `DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID` — strict title text readback is unavailable, while target structure/timing/media/title-lane geometry remains compatible with the canonical contract and no contradictory direct evidence exists;
2. `DIRECT_TITLE_TEXT_MISMATCH` — Resolve exposes title text and at least one observed value contradicts the canonical expected text;
3. `TITLE_MEDIA_PATH_CONTAMINATION` — at least one title item exposes a non-empty media path, which independently triggers the current `target_title` guard;
4. `STRUCTURAL_TARGET_MISMATCH` — `require_title_text=False` still fails a structural/timing/media/lane invariant;
5. `FORENSIC_EVIDENCE_INSUFFICIENT` — the target/provenance/state cannot be attributed safely enough to classify without mutation.

The Plan succeeds when the exact class, supporting per-item evidence, target identity, and zero-mutation state evidence are captured durably. It does **not** make the product PASS.

## 2. Current Bottleneck / Why Now

- MAIN BOTTLENECK: missing attributable read-only evidence from the unsaved live P001 target.
- WHY: P001 proved one import occurred and the exact commanded target was created/found, but the frozen importer aborted at strict `target_title` validation before recording the observed title value/media-path condition, target UID, post-import inventory, or protected-state comparison.
- CURRENT UNCERTAINTY: the same generic exception is consistent with materially different causes: unavailable TextPlus readback, genuine text mismatch, non-empty title media path, or a downstream structural contradiction not yet captured.
- WHY NOW: persistence/save, second-run/idempotency, visual review, and any repair all depend on knowing which failure class is real. Re-running import or saving first would alter the evidence boundary.

## 3. Existing-Mechanism Decision — REUSE / ADAPT, Not Reinvention

Existing repository mechanisms were inspected before selecting this Plan:

### Frozen Phase 6 base importer

`resolve_workspace/modules/video_cloner_phase6_textplus_application.py`

- `_title_text(item)` already performs the intended read-only title/TextPlus lookup through item properties and existing Fusion compositions/tools.
- `validate_target(..., require_title_text=False)` already preserves target name/timebase, track counts, lane placement, timing, V1/A1 media identity, no-extra-track, overlap, and duration guards while relaxing only direct title-text equality.
- `_validate_item(..., title=True)` still rejects a non-empty title `media_path` even when title text is not required.
- Its current `run()` is **not** suitable for P002 because strict validation happens immediately after import and the failure result discards the exact title evidence needed here.

### Current Phase 6 live-application regression support

`resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py`

- already contains readback/protected-state comparison logic and `PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1`;
- its tests explicitly prove that direct title text can be unavailable while `require_title_text=False` structural validation still passes;
- its fallback fails closed on direct semantic contradiction, export contradiction, second-import provenance, canonical hash mismatch, and structural mismatch.

Its current `run()` must **not** be executed against the P001 state because it requires forensic/direct/export prerequisite reports not produced by P001 and it performs `SaveProject`. Its import-provenance loader also expects a different historical report schema (`ownership_classification` + `mutation_counts.timeline_imports`) than the frozen P001 importer result (`import_call_count`).

### Decision

- `REUSE`: existing `_title_text`, `timeline_snapshot`, inventory helpers, `validate_target(..., require_title_text=False)`, and relevant fail-closed test semantics.
- `ADAPT`: add only the minimum dedicated **read-only diagnostic support** needed to bind those mechanisms to the existing P001 target and emit the missing evidence.
- `DO NOT MODIFY`: frozen Phase 6 importer, frozen bridge, public `video_cloner` API/CLI, canonical FCPXML/compiler behavior.
- RESEARCH GATE: `NOT_APPLICABLE`; this is diagnosis using already-approved repository mechanisms, not a new renderer/dependency/adapter decision.

## 4. Live Resolve Preservation Decision

The current Resolve process and project state are evidence. Until T003 captures the forensic report:

- KEEP Resolve open;
- KEEP the current project open;
- DO NOT save;
- DO NOT close/revert the project or Resolve;
- DO NOT switch the current timeline;
- DO NOT rename/delete/modify the P001 target;
- DO NOT import again;
- DO NOT run any other queued Resolve command.

Reason: current save/discard/autosave state is not proven, and P001 did not prove persistence. Closing or saving before read-only capture can destroy or change the evidence we are trying to classify.

**After P002 evidence is durably captured:** P002 still does not decide save/discard implicitly. Browser Architect + human must make an explicit closure decision from the report. No worker may assume that closing is safe or that Save/Discard preserves the required evidence.

## 5. Accepted Baseline / P001 Evidence Binding

The diagnostic must bind to all of the following before any live action:

- repository `main` plan baseline: `41ff2537c8de610df71b502f071c00d919bf43b0`;
- accepted product baseline: `4516da32e6780a574e7d3904782bb1007def05e7`;
- P001 run ID: `20261007T173351920Z_b031b0693f6f4c7d8f8d17c6d718ce41`;
- expected project: `New Project 1`;
- exact P001 target: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`;
- P001 T002 report: `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T002/REPORT.md`;
- P001 command/report/status evidence identified by exact path + SHA-256 in the P002 report before publication;
- canonical Phase 5/6 artifact identities loaded from the current accepted manifest, not copied by hand.

If any binding is ambiguous or contradictory: STOP `BLOCKED_FORENSIC_IDENTITY` before Resolve execution.

## 6. IN Scope

- Read current repository/code/tests and closed P001 evidence.
- Add the minimum dedicated read-only Resolve diagnostic support module necessary to inspect the existing P001 target.
- Add focused offline tests for that diagnostic support.
- Reuse frozen Phase 6 readback/validation helpers instead of duplicating their semantics.
- Prepare exactly one bounded P002 diagnostic command only after offline verification passes.
- Human executes Workspace → `VC_Run_Agent_Task` at most once under P002 after explicit READY gate.
- Capture exact project/target identity, target UID, item-level title readback, structural validation, timeline/media inventories, current-timeline identity, and before/after zero-mutation evidence.
- Classify the failure into the Objective taxonomy.
- Record whether existing provenance/structural semantic fallback is **eligible for a future Plan**; do not execute persistence/save acceptance in P002.

## 7. OUT of Scope

- Modifying `resolve_workspace/modules/video_cloner_phase6_textplus_application.py`.
- Modifying `resolve_workspace/VC_Agent_Bridge.py` or launcher copies/config.
- Modifying `video_cloner/`, public CLI/API, compiler, FCPXML, captions, transition policy, profiles, or analysis behavior.
- `SaveProject` or any persistence proof.
- `ImportTimelineFromFile`, media import, export, render, relink, replace, delete, rename, title write, Fusion write, metadata write, or timeline selection change.
- A second P002 diagnostic retry after any live invocation.
- P001 second-run/idempotency acceptance.
- Human visual acceptance.
- Product repair, validator weakening, or accepting semantic mismatch by policy change.
- New dependencies / OSS research.

## 8. Preserve / Regression Guard

Must remain unchanged:

- P001 live target content/state during diagnosis;
- current timeline selection;
- every non-target timeline and its observable signature;
- media-pool inventory;
- project persistence state — no explicit save;
- canonical artifact identities;
- frozen launcher, bridge, and `video_cloner_phase6_textplus_application.py` hashes;
- public API/CLI behavior;
- P001 evidence files.

The diagnostic module must be observational only. Any detected before/after inventory or current-timeline drift is a hard failure even if the intended title evidence was captured.

## 9. Worker Decision Boundary

Codex MAY decide locally:

- exact name/shape of the new diagnostic support module and focused test file, provided it remains dedicated, read-only, repository-relative, and outside the public product API;
- exact `.project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/...` evidence layout;
- how to normalize path case/separators for comparison without weakening identity;
- how to format item-level forensic rows for clarity;
- whether to import existing helper functions from the frozen base or regression-support module, provided no frozen file is modified.

Codex MUST STOP / escalate for:

- any need to change product behavior or frozen files;
- any requirement to save, import, export, render, select/switch timeline, or mutate Resolve;
- inability to bind the live target to exact P001 provenance;
- stale/ambiguous pending/running queue state;
- more than one exact target match;
- unexpected project/timeline identity;
- any offline test indicating the diagnostic can call a mutation API;
- live diagnostic failure or any observed state drift;
- a need for a second live diagnostic invocation;
- architecture/scope/dependency expansion.

## 10. Tasks

### TASK T001 — Build + Prove the Read-Only Forensic Surface

**Status:** `NOT_STARTED`

**Objective:** create the smallest diagnostic adapter that exposes the evidence P001 discarded while statically and behaviorally proving it cannot mutate Resolve.

**Allowed tracked changes:**

- one dedicated diagnostic module under `resolve_workspace/modules/`;
- one focused test file under `tests/`;
- P002 project-op reports/artifact references only.

**Required behavior:**

1. validate command identity and require explicit read-only/zero-mutation flags;
2. verify exact project identity and exactly one target with the P001 target name;
3. capture current timeline identity without changing it;
4. capture full timeline + media-pool inventories before inspection;
5. capture target UID and `timeline_snapshot`;
6. map expected overlay rows to actual title items by lane/track + timing/duration, not by display name alone;
7. record for each overlay: expected text, observed `title_text`, observed `media_path`, name, track, start, end, duration;
8. run strict `validate_target(...)` and record the exact pass/failure;
9. independently run `validate_target(..., require_title_text=False)` and record the exact pass/failure;
10. derive the Objective classification fail-closed;
11. recapture current timeline, timelines, and media inventory after inspection and prove equality;
12. report explicit zero mutation counters/claims for all prohibited operation classes.

**Test requirements:**

- direct TextPlus/property readback PASS;
- all-title direct readback unavailable + structural PASS → `DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID`;
- observed wrong text → `DIRECT_TITLE_TEXT_MISMATCH`;
- non-empty title media path → `TITLE_MEDIA_PATH_CONTAMINATION`;
- structural timing/lane/count/media mismatch → `STRUCTURAL_TARGET_MISMATCH`;
- partial/ambiguous title observability fails closed, never silently becomes fallback eligibility;
- duplicate/wrong target/project fails closed;
- current timeline and inventories unchanged;
- static call-surface test rejects prohibited mutation APIs including `ImportTimelineFromFile`, `SaveProject`, `SetCurrentTimeline`, `DeleteTimelines`, `AppendToTimeline`, title/Fusion writes, relink/replace/import/export/render calls.

**Acceptance criteria:**

- focused tests green;
- `git diff --check` green;
- no dependency change;
- only allowed files changed;
- frozen base/bridge hashes unchanged;
- diagnostic code contains no mutation path.

**Required report:** `.project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/T001/REPORT.md`

### TASK T002 — Prepare One Attributable Diagnostic Command

**Status:** `NOT_STARTED`

**Objective:** prove one exact read-only command is safe and ready for human execution against the still-open P001 state.

**Required checks:**

1. repository branch/HEAD/status recorded;
2. exact P001 T002 command/report/status paths + SHA-256 recorded;
3. canonical artifact/manifest identities verified;
4. installed launcher/bridge repository identity still matches expected frozen authority;
5. queue has no stale/ambiguous pending/running command;
6. command binds exact project, exact existing target, exact P001 run evidence, exact diagnostic module, unique P002 run ID;
7. every mutation permission is explicitly false;
8. no live action has occurred yet.

**Acceptance criteria:**

- one and only one intended pending P002 command exists;
- command/report/status destinations are unambiguous and repository-contained;
- human receives exact Workspace action and the warning not to save/close/switch/modify Resolve before the action.

**Required report:** `.project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/T002/REPORT.md`

**HUMAN GATE:** only after T001 + T002 are PASS may the human run Resolve → Workspace → Scripts → `VC_Run_Agent_Task` **exactly once**. Plan creation alone does not authorize this action.

### TASK T003 — Capture + Classify the Existing P001 Target

**Status:** `NOT_STARTED`

**Objective:** consume the single diagnostic result and close P002 with an evidence-backed failure class.

**Acceptance criteria:**

1. P002 bridge/report/run ID matches the exact T002 command;
2. diagnostic reports exactly one P001 target and target UID;
3. exact per-overlay title evidence is present;
4. strict and structural validation outcomes are both recorded;
5. before/after current timeline, non-target timeline inventory, and media inventory are unchanged;
6. no prohibited mutation occurred;
7. one Objective classification is selected with concrete evidence;
8. fallback eligibility is reported separately from product acceptance;
9. no second live invocation occurs.

**P002 PASS means:** `PASS_FORENSIC_CLASSIFICATION_READY` — diagnosis is sufficient to choose the next Plan. It does **not** mean live Resolve acceptance passed.

**Required report:** `.project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/T003/REPORT.md`

## 11. Classification / Next-Plan Routing

P002 itself does not create the next Plan. Its report must expose the routing evidence:

- `DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID` → next Browser Architect evaluates operationalizing the already-tested provenance/structural semantic fallback for this current importer evidence shape, then a separate persistence acceptance Plan.
- `DIRECT_TITLE_TEXT_MISMATCH` → next Plan isolates whether compiler/import semantics or readback normalization is wrong; do not weaken validation.
- `TITLE_MEDIA_PATH_CONTAMINATION` → next Plan isolates why the imported title item is media-backed under current contract.
- `STRUCTURAL_TARGET_MISMATCH` → next Plan repairs the earliest violated structural invariant.
- `FORENSIC_EVIDENCE_INSUFFICIENT` → next Plan improves observation/provenance only; no repair guess.

## 12. Verification

Before publishing any P002 live command:

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
python -m pytest --basetemp=.pytest-tmp-p002-readback -q tests/test_video_cloner_phase6_offline_timeline_live_application.py <P002_DIAGNOSTIC_TEST_FILE>
git diff --check
```

Also record SHA-256 / Git blob identity for:

- `resolve_workspace/VC_Run_Agent_Task.py`;
- `resolve_workspace/VC_Agent_Bridge.py`;
- `resolve_workspace/modules/video_cloner_phase6_textplus_application.py`;
- `resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py`;
- the new P002 diagnostic module.

Run broader canonical regression only if the bounded diagnostic change touches a shared helper or focused evidence indicates regression risk. Any requested change to frozen/shared product behavior is a STOP, not a reason to broaden P002.

## 13. Evidence Required

- T001/T002/T003 `REPORT.md` files under `.project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/`.
- exact Git baseline/diff.
- focused test output.
- original P001 command/report/status path + SHA-256 binding.
- exact P002 command/run ID + completed/failed bridge evidence.
- target UID + target snapshot.
- per-overlay expected vs observed title text/media-path geometry.
- strict validator result.
- `require_title_text=False` structural validator result.
- before/after current timeline + timeline inventory + media inventory comparison.
- explicit zero-mutation evidence.
- final classification + next-plan routing evidence.

Heavy machine-local evidence may remain under `.project_ops/artifacts/` when ignored; the reports must contain enough hashes/paths to make it attributable.

## 14. Repair Limit

- PRODUCT-CODE REPAIR ATTEMPTS: `0`.
- DIAGNOSTIC-SUPPORT REPAIR ATTEMPTS BEFORE LIVE EXECUTION: `1` bounded correction if T001 offline tests expose an implementation defect in the new diagnostic adapter itself.
- AFTER ANY P002 LIVE INVOCATION: `0` retries / `0` repairs / `0` second executions under this Plan.

If the first live diagnostic cannot classify safely, close P002 BLOCKED with the evidence obtained.

## 15. Human Gate

Human intervention is required once, conditionally:

- PRE-GATE: keep Resolve/project/target open and untouched.
- ACTION: only after T001 + T002 explicitly say READY, run Workspace → Scripts → `VC_Run_Agent_Task` exactly once.
- RETURN: no manual interpretation is required for machine classification; report the visible launcher outcome only if it differs from captured bridge evidence.
- AFTER ACTION: do not save/close/revert/delete/rename/switch until Browser Architect reviews T003 and explicitly decides how the live state may be retired.

## 16. Rollback

- Repository diagnostic changes are reversible with Git and do not alter accepted product behavior.
- Live rollback is **not applicable** because P002 authorizes no mutation. If any mutation is observed, STOP and preserve the state/evidence; do not attempt cleanup.
- Do not delete or alter the P001 target as “cleanup” under P002.

## 17. Stop Conditions

STOP instead of improvising when:

- baseline Git/provenance identity is not exact;
- Resolve/project/target identity is ambiguous;
- Resolve was saved/closed/reverted/modified before capture and persistence/state cannot be proven;
- queue state is ambiguous;
- diagnostic support requires product/frozen-file change;
- any prohibited mutation call exists or occurs;
- current timeline changes;
- protected/non-target timeline or media inventory changes;
- live diagnostic errors before sufficient evidence is captured;
- classification remains ambiguous;
- a second live invocation appears useful;
- save/persistence/idempotency/visual review becomes tempting inside P002.

## 18. Partition Close Procedure

After Codex finishes or blocks:

1. return T001/T002/T003 reports + exact Git diff/evidence to this Browser Architect partition;
2. Browser Architect reviews actual code/evidence, not `PASS` alone;
3. record the exact forensic classification and fallback eligibility;
4. explicitly decide whether the now-captured live Resolve state can be closed and under which save/discard instruction;
5. synchronize `PROJECT_STATE.md`, `PROJECT_TRACKER.xlsx`, and `docs/DECISIONS.md` if warranted;
6. archive P002 only after ACCEPTED/BLOCKED review;
7. next Plan is created only in a fresh Browser Architect chat + fresh Codex session.
