# REPORT.md — Video Cloner Worker Evidence

- PLAN ID: `P001_LIVE_RESOLVE_ACCEPTANCE`
- TASK ID: `T001`
- CODEX SESSION: `CODEX-P001_LIVE_RESOLVE_ACCEPTANCE` (continuation)
- RESULT: `HUMAN_INTERVENTION_REQUIRED`
- EXTERNAL SKILLS: VERIFIED — `ponytail` (full)

## Baseline

- branch: `main`
- HEAD: `6b713b24ace1b148284f3722098da6faee03917f`
- accepted product baseline: `4516da32e6780a574e7d3904782bb1007def05e7` / `video-cloner-canonical-cleanup-20261007`
- accepted product baseline is an ancestor of HEAD.
- initial `git status --short`:

```text
[clean]
```

## Objective

Produce one provenance-backed canonical command and prove it is safe to execute.

## Approach

Read the current installer contract, corrected the prior `%APPDATA%` assumption, verified the installer-selected single canonical launcher/config and empty active queue, ran the narrow installer contract tests, compiled a fresh collision-resistant target, and published exactly one new bounded command. No Resolve action was executed.

## Installer Contract Reconciliation

`scripts/install_vc_agent_live.py` requires exactly one discovered launcher and one adjacent config at the installer-selected canonical `Scripts/Edit` directory. It prefers `%APPDATA%` only when that directory is an anchored candidate; it does not require a second `%APPDATA%` copy. The portable directory selected and recorded by the approved installer is the current authority.

## Files Changed

| File | Why |
|---|---|
| `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T001/REPORT.md` | Required T001 continuation report. |
| `.project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T001/PREFLIGHT_EVIDENCE.json` | Updated machine-readable preflight and fresh command identity. |
| `.project_ops/artifacts/P001_LIVE_RESOLVE_ACCEPTANCE/T001/P001_acceptance_fresh_4CE37F9BC61B*` | Fresh ignored FCPXML/package evidence. |

Tracked product files: NONE.

## Commands / Tests Run

```text
git status --short
git branch --show-current
git rev-parse HEAD
python -m pytest --basetemp=.pytest-tmp-p001-installer -q tests/test_vc_bridge_installer.py
read-only installer discovery/state/hash/process verification
read-only pending/running queue inventory
python -m video_cloner.cli compile ... --timeline-name VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B --timeline-mode full_timeline ...
python -m video_cloner.cli publish ... --project "New Project 1" --target-timeline VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B
```

- installer contract tests: `8 passed in 0.18s`.
- immediately prior focused contract preflight: `46 passed in 0.65s`; not repeated because no tracked runtime/product code changed.

## Current Contract Semantics

- First run: one pending command is claimed; the application requires project `New Project 1` and an absent target, imports once, validates target/protected/media state, restores the prior current timeline, and does not save, replace, delete, relink, or invoke metadata control.
- Declared second run: only after T002 authorization, republishing for the same target creates a new run ID and must fail closed with `target_already_exists`; no duplicate is created. Invoking Workspace with no pending command is a no-op.

## Key Evidence / Artifacts

- canonical Scripts/Edit: portable installer-selected directory recorded in `PREFLIGHT_EVIDENCE.json`.
- repository/installed launcher SHA-256: `ce39ebd249963b67450e79d67435f6a9618eeaacc8700e9ed9d5fa2e35c98013` (match).
- installed config SHA-256: `da85e6d7bb9eaf9fc6448feb142234c599705011e1f6739f3cf01398d9ab08e0`.
- repository bridge SHA-256: `c5d342d1b735a9e7862bf60aedb38c3bade391324d57e518d68b3b3b8578c85e`.
- previous quarantined command: not reused.
- fresh run ID: `20261007T173351920Z_b031b0693f6f4c7d8f8d17c6d718ce41`.
- fresh target: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`.
- protected target: `DcJRJtUKScu_offline_timeline_v1` (distinct).
- command SHA-256: `3f8f78df42275aa2ec57a2ea67e3f7bd8676c0a62e1ab5fb055c363dfabfd492`.
- manifest SHA-256: `38e57cfd57eafb4956f7a54ea86b8f3819d3ba5b1ab3b8b7d47d0d37fe38a615`.
- FCPXML SHA-256: `d9d5c5c695e29e8ea82e7e1f6488f19deb95e9328c7e2c0f89a7370ed2cf8b62`.
- queue after publication: pending `1`, running `0`.
- Resolve mutation: NONE.

## Acceptance Criteria

| Criterion | Result | Evidence |
|---|---|---|
| exact Git/runtime baseline recorded | PASS | Clean initial Git state; baseline and canonical installer state recorded. |
| current first/second-run semantics summarized | PASS | Current contract above and focused test evidence. |
| queue safe/isolated | PASS | `0/0` before publication; exactly one owned pending command afterward. |
| matching non-empty run ID and NEW absent target | PASS | Fresh identities above; target absent from local evidence before creation and live application independently requires absence. |
| protected identities checked | PASS | Fresh target differs from protected Reel #2 GOLD identity; replacement/deletion/relink/save are false. |
| no Resolve mutation yet | PASS | No Workspace action occurred. |
| exact Workspace action supplied | PASS | Human action below. |

## Deviations / Remaining Risk

- The earlier requirement for an additional `%APPDATA%` launcher was a worker assumption contradicted by the current installer. It is withdrawn.
- Live target absence and protected-state preservation remain subject to the application's fail-closed Resolve readback during the authorized first execution.

## Human Intervention

- REQUIRED: YES
- ACTION: Launch the canonical portable DaVinci Resolve, open project `New Project 1`, and confirm no timeline named `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B` is present. If absent, click `Workspace` → `Scripts` → `VC_Run_Agent_Task` exactly once. Do not invoke it a second time and do not save/delete/rename any timeline.
- WHY: Resolve Workspace execution is the explicit live mutation boundary and must be performed by the human.
- RETURN REQUIRED: confirm the script was clicked exactly once; report any visible error/dialog/console text verbatim; state whether the target timeline appeared; leave Resolve/project state unchanged afterward. The worker will inspect the matching bridge report/status/log, target readback, and protected-state evidence before authorizing anything else.

## Final Git Status

```text
 M .project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T001/PREFLIGHT_EVIDENCE.json
 M .project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T001/REPORT.md
```

## Stop

Stop at the first Resolve human gate. No second Workspace action is authorized.
