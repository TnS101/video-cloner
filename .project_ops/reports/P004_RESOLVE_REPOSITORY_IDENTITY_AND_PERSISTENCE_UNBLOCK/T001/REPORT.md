# REPORT.md — Video Cloner Worker Evidence

- PLAN ID: `P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK`
- TASK ID: `T001`
- CODEX SESSION: `CODEX-P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK`
- RESULT: PASS — PENDING ARCHITECT REVIEW
- EXTERNAL SKILLS: VERIFIED — `ponytail` (full)

## Baseline

- repository: `TnS101/video-cloner` (`origin` = `https://github.com/TnS101/video-cloner.git`)
- branch: `architect/p004-persistence-unblock-draft`
- HEAD: `b3659692f8cdea2418ea25fce41f9f56ff130eaa`
- canonical main base: `a102a94b34431bcc609ed5cfc4e048cfc6b3fa0a`
- accepted product baseline: `4516da32e6780a574e7d3904782bb1007def05e7`
- initial `git status --short`: clean (no output)
- plan gate: `READY_FOR_CODEX`; authorization limited to T001 offline only
- repair limit: one bounded T001 correction before live execution; no live action authorized

## Objective

Remove ambient PATH dependence from both existing Git identity callers by authenticating a command-bound absolute Git executable path and SHA-256, while preserving repository branch/HEAD checks, all accepted P003 fallback/save semantics, finalizer pre-save fail-closed ordering, and verifier read-only behavior.

## Approach

Added the same small in-place executable identity check to the finalizer and verifier. Each caller now requires `git_executable_path` and `git_executable_sha256`, rejects a non-absolute/missing/non-file/hash-mismatched binding, canonicalizes the path, and invokes only that resolved path with the existing explicit repository `cwd`. No shared helper was introduced because two local ten-line checks were smaller than adding another runtime module/import boundary.

## Files Changed

| File | Why |
|---|---|
| `resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py` | Authenticate command-bound Git path/hash and use only that path before repository checks and `SaveProject`. |
| `resolve_workspace/modules/video_cloner_p003_post_reopen_verification.py` | Apply the same authenticated Git binding while retaining the read-only verifier surface. |
| `tests/test_video_cloner_p003_fallback_persistence_acceptance.py` | Prove valid binding and fail-closed path/hash/process/repository cases, pre-save ordering, read-only behavior, and absence of bare Git fallback. |
| `.project_ops/reports/P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK/T001/REPORT.md` | Required T001 evidence report. |

## Commands / Tests Run

```text
python -m pytest tests/test_video_cloner_p003_fallback_persistence_acceptance.py -q
RESULT: 32 passed, 14 setup errors — pytest default Windows temp root was inaccessible; no test assertion failed.

python -m pytest tests/test_video_cloner_p003_fallback_persistence_acceptance.py -q --basetemp=.project_ops/artifacts/P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK/T001/pytest
RESULT: 46 passed in 0.34s

python -m pytest tests/test_video_cloner_p002_live_target_forensic_readback.py tests/test_video_cloner_phase6_offline_timeline_live_application.py tests/test_prepare_video_cloner_fresh_mvp_timeline.py tests/test_vc_agent_bridge.py -q --basetemp=.project_ops/artifacts/P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK/T001/pytest-regression
RESULT: 57 passed in 1.12s

git diff --check
RESULT: PASS; no whitespace errors (LF-to-CRLF working-copy warnings only).

git diff --stat
RESULT:
 .../video_cloner_p003_post_reopen_verification.py  |  17 +++-
 ...ner_phase6_offline_timeline_live_application.py |  17 +++-
 ..._cloner_p003_fallback_persistence_acceptance.py | 106 +++++++++++++++++++--
 3 files changed, 128 insertions(+), 12 deletions(-)
```

## Key Evidence / Artifacts

- Ambient PATH removal: neither identity module contains a subprocess argv beginning with bare `"git"`; the invoked argv begins with the authenticated resolved path.
- Executable authentication: absolute path, existing regular file, canonical resolution, and exact command-bound SHA-256 are required in both callers.
- Repository authentication preserved: both calls still execute `branch --show-current` and `rev-parse HEAD` with explicit `cwd=root`, and reject non-zero Git exits, a non-`main` branch, wrong HEAD, or wrong repository root.
- Finalizer ordering: repository root, executable path/hash, branch, and HEAD checks occur before Resolve manager access and before `SaveProject`; focused tests prove executable/root/branch/HEAD rejection leaves save count zero.
- Verifier remains read-only: its prohibited-mutation AST check passes and its mutation counters remain all zero in accepted/rejected state tests.
- Test artifacts: `.project_ops/artifacts/P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK/T001/` (ignored/local).

## Acceptance Criteria

| Criterion | Result | Evidence |
|---|---|---|
| command-bound absolute Git path required in both callers | PASS | Valid absolute binding succeeds; relative, missing, and path-only bindings fail. |
| executable SHA-256 authenticated | PASS | Correct digest succeeds; wrong digest and swapped executable fail. |
| only authenticated executable invoked; no PATH fallback | PASS | Subprocess argv assertion and AST no-bare-`git` checks pass for both modules. |
| branch/HEAD/root/non-zero failures fail closed | PASS | Focused wrong branch, wrong HEAD, wrong root, and non-zero process tests pass. |
| `SaveProject` unreachable until identity acceptance | PASS | Failure-path save count remains zero; accepted baseline saves exactly once. |
| P003 fallback/save semantics preserved | PASS | Entire focused P003 file passes: 46 tests. |
| post-reopen verifier remains read-only | PASS | Accepted/drift tests and prohibited mutation call-surface test pass. |
| bounded affected regression | PASS | Exact plan-listed P002/Phase 6/preparation/bridge set: 57 passed. |
| scope limited to authorized files/report | PASS | Final status/stat/diff inspection; no helper, dependency, launcher, bridge, API/CLI, validator, Plan, state, or architecture change. |

## Deviations / Remaining Risk

- Warning: pytest's default temp root was inaccessible; the identical focused suite passed using the Plan-authorized local artifact directory.
- Warning: Git reports LF-to-CRLF working-copy conversion warnings for the three modified Python files; `git diff --check` reports no whitespace error.
- Remaining uncertainty: no real Git executable or Resolve-hosted process was exercised because T001 is offline/mock-only. Command preparation and all live persistence evidence remain outside this authorization.

## Human Intervention

- REQUIRED: NO
- ACTION: Browser Architect reviews this T001 diff and evidence.
- WHY: T001 authorization ends at offline evidence/report.
- RETURN REQUIRED: T001 acceptance or a bounded correction decision; this report does not authorize T002/T003/T004 or PH2.

## Safety Confirmations

- NO COMMAND PUBLICATION
- NO QUEUE PROCESSING
- NO RESOLVE INVOCATION
- NO `SaveProject` CALL
- NO T002/T003/T004 STARTED
- NO PH2 STARTED

## Final Git Status

```text
 M resolve_workspace/modules/video_cloner_p003_post_reopen_verification.py
 M resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py
 M tests/test_video_cloner_p003_fallback_persistence_acceptance.py
?? .project_ops/reports/P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK/
```

## Stop

T001 implementation is complete pending Browser Architect review. No further P004 task is authorized in this session.
