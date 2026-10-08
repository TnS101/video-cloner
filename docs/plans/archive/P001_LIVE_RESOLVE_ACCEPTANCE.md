# plan.md — CURRENT PLAN PARTITION

- PLAN ID: `P001_LIVE_RESOLVE_ACCEPTANCE`
- PLAN NAME: Controlled Live Resolve Machine Acceptance
- STATUS: `BLOCKED`
- PHASE: `PH1`
- BROWSER SESSION: `BROW-P001_LIVE_RESOLVE_ACCEPTANCE`
- CODEX SESSION: `CODEX-P001_LIVE_RESOLVE_ACCEPTANCE`
- CREATED: 2026-10-07 Europe/Sofia
- BASELINE BRANCH: `main`
- BASELINE ACCEPTED PRODUCT COMMIT: `4516da32e6780a574e7d3904782bb1007def05e7`
- BASELINE TAG: `video-cloner-canonical-cleanup-20261007`
- ARCHITECTURE VERSION: `A001`

> One Plan = one bounded result. This Plan is ACCEPTANCE ONLY. Do not repair product behavior inside it. A product defect becomes the next root-cause Plan.

## Closure Summary

- CLOSED: 2026-10-08 Europe/Sofia
- RESULT: `BLOCKED`
- T001: `PASS` — preparation and safety boundary complete.
- T002: `BLOCKED_LIVE_ACCEPTANCE` — one authorized execution called `ImportTimelineFromFile` once and created/found the exact commanded target, then machine validation failed with `ValueError: target_title`.
- T003: `NOT_EXECUTED`.
- NOT PROVEN: persistence, protected-state preservation, second-run/idempotency behavior, and visual acceptance.
- NO SECOND RUN IS AUTHORIZED UNDER P001.

## 1. Objective — One Observable Result

Prove or falsify the CURRENT canonical Resolve application boundary in the real installed environment using one matching run identity: first live application, target persistence/readback, declared second-run/idempotency behavior, protected-state checks, and human visual decision.

## 2. Why This Is the Current Move

- CURRENT BOTTLENECK: live Resolve machine acceptance is still NOT ACCEPTED.
- WHY THIS PLAN ATTACKS IT: offline generation and queue publication are already accepted; more coding before testing the live boundary would optimize behind the unresolved SPOF.
- WHY NOW: repository/API cleanup is complete and launcher wiring is verified.

## 3. Prerequisites / Gates

- [x] `ARCHITECTURE.md` is APPROVED and compatible.
- [x] `PROJECT_STATE.md` current Plan ID matches.
- [x] `PROJECT_TRACKER.xlsx` contains this partition.
- [x] GitHub `main` + cleanup tag identify accepted product baseline.
- [x] No new research/reuse decision is required for this acceptance Plan.
- [x] No new dependency is authorized or required.
- [ ] Fresh Codex session verifies local Git HEAD/status and installed/runtime preconditions.
- [ ] Codex confirms exact current Phase 6 expected first-run and second-run/idempotency semantics from current code/tests BEFORE live mutation.
- [ ] Codex chooses/validates a NEW target timeline identity that is absent and is not any protected/accepted timeline.

If any unchecked runtime gate cannot be proven: STOP — BLOCKED.

## 4. IN Scope

- Read-only preflight of current repository, local queue state, launcher/bridge identity, relevant current tests/contracts.
- Use existing local fresh source/artifacts when available; avoid network re-download if unnecessary.
- Create one canonical run / bounded pending Resolve command using public API/CLI.
- Verify command/run/target/protected identities before human execution.
- Request the human to execute Resolve Workspace action exactly when ready.
- Validate matching bridge report + target persistence/readback after first execution.
- Request a second controlled Workspace action only after first-pass validation, to prove the CURRENT declared idempotency/fail-closed behavior.
- Capture human visual APPROVE / REJECT separately from machine acceptance.
- Write reports/evidence under `.project_ops`.

## 5. OUT of Scope

- Any redesign of `video_cloner/` architecture.
- Product-code fixes to Phase 6, captions, camera, Flash, transitions, occlusion, fonts, opacity, stroke/shadow.
- New dependencies or OSS integration.
- HyperFrames, Remotion, rough-cut engines, multi-editor adapters.
- Mutating Reel #2 GOLD/protected timeline.
- Claiming raw-footage/style-transfer generalization from the flattened fresh Reel.
- Repeated trial-and-error live executions.

## 6. Preserve / Regression Guard

- Protected Reel #2 GOLD identity/timeline/artifacts unchanged.
- Frozen launcher/bridge/application hashes unchanged unless this Plan explicitly proves they differ before execution; if they differ, STOP.
- Public queue operation remains bounded; no arbitrary module input.
- Canonical regression remains green if any tracked non-report file changes (ideally none).
- No stale or unrelated pending/running Resolve commands are consumed.

## 7. Worker Decision Boundary

Codex MAY decide locally:

- exact read-only inspection commands;
- disposable evidence/report locations;
- whether an existing fresh-run artifact can be safely reused versus generating a new canonical run;
- a NEW target timeline name, provided it is proven absent and non-protected;
- how to normalize non-behavioral timestamps/paths in evidence comparison.

Codex MUST STOP / escalate for:

- any product-code change;
- bridge/application logic change;
- architecture/scope expansion;
- new dependency;
- stale/ambiguous queue state that cannot be safely isolated;
- target/protected identity ambiguity;
- first-run validation failure;
- persistence/readback mismatch;
- any unexpected mutation;
- visual/subjective acceptance;
- destructive cleanup/rollback action.

## 8. Tasks

### TASK T001 — Prepare Acceptance Run

**Status:** `PASS` — preparation and safety boundary complete.

**Objective:** produce one provenance-backed canonical command and prove it is safe to execute.

**Allowed components:**
- read canonical package/tests/config/docs;
- public `video-cloner` CLI / `video_cloner.pipeline`;
- local ignored input/media/data/state;
- `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T001/`;
- `.project_ops/artifacts/P001_LIVE_RESOLVE_ACCEPTANCE/T001/`.

**Acceptance criteria:**
1. exact Git/runtime baseline recorded;
2. current first-run/second-run semantics summarized from code/tests;
3. queue is safe/isolated; no unintended pending/running command;
4. generated command has matching non-empty run ID and NEW absent target identity;
5. protected target identities explicitly checked;
6. no Resolve mutation yet;
7. human receives exact Workspace action + exact evidence to return.

**Required report:** `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T001/REPORT.md`

### TASK T002 — First Live Apply + Persistence Readback

**Status:** `BLOCKED_LIVE_ACCEPTANCE` — `ValueError: target_title` after one import; see the required T002 report.

**Objective:** after the human executes the exact Workspace action once, validate the resulting live state.

**Acceptance criteria:**
1. bridge report/run ID matches T001 command;
2. operation reports machine success under CURRENT validators;
3. expected target timeline identity is present after execution and survives readback;
4. protected timeline(s) remain unchanged;
5. no unrelated timeline/project mutation is detected;
6. evidence is sufficient to authorize the second-run check.

If any criterion fails: `BLOCKED_LIVE_ACCEPTANCE` and STOP. No fix in this Plan.

**Required report:** `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T002/REPORT.md`

### TASK T003 — Declared Second-Run Behavior + Human Visual Gate

**Status:** `NOT_EXECUTED` — first-run validation failure prohibited further Resolve execution.

**Objective:** prove the current declared second-run/idempotency/fail-closed behavior and capture human visual decision.

Before execution, state the exact expected second-run behavior derived from current code/tests. Do not invent a new definition of idempotency.

**Acceptance criteria:**
1. second Workspace execution behaves exactly as the current contract declares;
2. no duplicate/corrupt/unintended target is created;
3. protected state remains unchanged;
4. persistent target state remains internally consistent;
5. human returns `APPROVE` or `REJECT` for visual review with concise notes;
6. machine acceptance and visual acceptance are reported separately.

**Required report:** `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T003/REPORT.md`

## 9. Verification

Before any live execution:

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
python -m pytest --basetemp=.pytest-tmp-p001-preflight -q tests/test_vc_agent_bridge.py tests/test_video_cloner_phase6_offline_timeline_live_application.py tests/test_prepare_video_cloner_fresh_mvp_timeline.py
```

Also inspect the current canonical regression authority in:

`docs/repo_hygiene/CANONICAL_REGRESSION_BASELINE.md`

Run the full 116-test canonical suite only if tracked runtime/product code changes unexpectedly (which should cause STOP anyway) or if focused evidence indicates regression risk.

Live evidence must include exact command/run ID, bridge report, target identity/readback, and protected-state result.

## 10. Evidence Required

- T001/T002/T003 `REPORT.md` files under `.project_ops/reports/...`.
- canonical run manifest / command identity or hashes.
- matching bridge report/run ID.
- readback evidence for target identity/persistence.
- protected-state check.
- second-run result.
- human visual `APPROVE` / `REJECT` + notes.

Heavy screenshots/logs remain local under `.project_ops/artifacts/...` unless a small artifact must be promoted deliberately.

## 11. Repair Limit

- PRODUCT-CODE REPAIR ATTEMPTS: 0.
- A trivial local operational correction is allowed only BEFORE live mutation if it does not change tracked product behavior (for example, creating an empty disposable evidence directory).
- Any real acceptance failure closes the Plan as BLOCKED and becomes a new architect-selected investigation Plan.

## 12. Human Gate

- HUMAN INTERVENTION REQUIRED: YES.
- ACTION 1: when T001 says READY, run Resolve → Workspace → Scripts → `VC_Run_Agent_Task` exactly once.
- RETURN 1: exact observed result plus the requested bridge/report evidence.
- ACTION 2: NOT AUTHORIZED — T002 failed machine validation; no second Workspace execution is permitted under P001.
- RETURN 2: second observed result/report.
- ACTION 3: visually inspect the target timeline and return `APPROVE` or `REJECT` + concise notes.

## 13. Rollback

This Plan should create a NEW target timeline and must not mutate protected timelines. If unexpected mutation occurs, STOP immediately and report exact state. Do not perform ad-hoc cleanup/rollback without a new explicit human-approved action.

Repository rollback authority remains GitHub `main` / cleanup tag; this Plan should not need product-code rollback.

## 14. Stop Conditions

Stop instead of improvising when:

- Git/runtime baseline is unsafe or differs materially from accepted authority;
- launcher/bridge/application hashes differ unexpectedly;
- target identity is not proven absent/non-protected;
- queue contains ambiguous/stale executable commands;
- live first run fails any validator;
- persistence/readback does not match;
- protected state changes;
- second-run expectation is ambiguous;
- product code would need modification;
- human action/visual review is required.

## 15. Partition Close Procedure

After Codex finishes or blocks:

1. return all P001 reports/evidence to THIS browser chat;
2. Browser Architect reviews actual Git/evidence, not `PASS` alone;
3. human visual result is recorded;
4. if accepted, synchronize project state/tracker and archive this Plan;
5. if blocked, synchronize state/tracker and archive this Plan as BLOCKED;
6. only then create the next Plan in a fresh browser chat + fresh Codex session.
