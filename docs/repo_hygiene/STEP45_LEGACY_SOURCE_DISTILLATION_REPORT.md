# Video Cloner Repository Hygiene — Step 4.5 Report

Date: 2026-10-07
Step: 4.5/5 — Legacy source distillation and deferred-capability indexing
Branch: `repo-hygiene/canonical-consolidation-20261007`

## Result

PASS. The noncanonical runtime tree was reduced to the smallest retained compatibility and deferred-capability closure. Every retained runtime/source file has an explicit classification and owner; `UNKNOWN` is zero. The canonical package and frozen Resolve boundary were not rewritten.

## Before/after inventory

| Tracked area | Step 4 baseline | Step 4.5 result | Change |
|---|---:|---:|---:|
| `video_cloner/` | 34 | 34 | 0 |
| `scripts/` | 281 | 16 | -265 |
| `resolve_workspace/` | 91 | 24 | -67 |
| root runtime BAT helpers | 3 | 2 | -1 |
| `tests/` | 176 | 176 | 0 |
| retained runtime/source total above | 375 | 42 | -333 |

The deleted wave is 333 tracked files: 265 under `scripts/`, 67 under `resolve_workspace/`, and the obsolete root `run_bridge_smoke_test.bat`. `run_agent_task.bat` and `run_install_VC_AGENT_BRIDGE.bat` remain install/bridge helpers; normal operation is still `video-cloner run`.

## Directory-size audit

The post-cleanup top-level audit is dominated by intentionally external/evidence data, not retained source. Sizes are physical bytes and include ignored files:

| Directory | Bytes |
|---|---:|
| `Virtual Environments/` | 10,627,773,620 |
| `.agent/` | 2,112,525,797 |
| `data/` | 496,350,898 |
| `.pytest-tmp-step4-e2e-2/` (accepted evidence) | 335,460,967 |
| `.git/` | 112,984,476 |
| `input/` | 53,338,559 |
| `media/` | 15,091,649 |
| `docs/` | 3,075,561 |
| `tests/` | 1,653,953 |
| `resolve_workspace/` | 1,373,213 |

The current `scripts/` footprint is 405,955 bytes; generated Step 4.5 scratch directories and source bytecode caches were removed.

## Classification

See [`DEFERRED_CAPABILITIES_INDEX.md`](DEFERRED_CAPABILITIES_INDEX.md) for the complete path-level index. The exact post-cleanup counts are:

| Class | Count |
|---|---:|
| `CANONICAL` | 0 |
| `COMPATIBILITY_REQUIRED` | 11 |
| `DEFERRED_CAPABILITY_SOURCE` | 31 |
| `HISTORICAL_EVIDENCE_ONLY` | 0 |
| `SUPERSEDED` | 0 |
| `REPAIR_ONLY` | 0 |
| `FAILED_EXPERIMENT` | 0 |
| `GENERATED` | 0 |
| `UNKNOWN` | 0 |

## Dependency closure retained

Only seven explicitly requested deferred domains remain: caption animation/lifecycle, font inference/application, opacity, stroke/shadow, camera editor transforms, transition/Flash execution, and occlusion/compositing. The retained Resolve closures are the smallest imports needed for those domains: Flash V1→V2→V4, final occlusion V1→V2→V3→V4 plus its Step 3E repair chain, and the Step 3D lifecycle/TextPlus probe chain. All prepare/validate/monitor launchers outside the indexed closure were deleted.

## Verification

- Canonical regression: 116 passed in 6.05s; the one Windows transient PermissionError observed during an earlier isolated run was retried independently and passed.
- CI-equivalent core selection: 64 passed in 3.68s.
- Python 3.10 audio/OCR worker imports: both passed on Python 3.10.11.
- Public import and `python -m video_cloner.cli --help`: passed; this checkout has no installed `video-cloner` console shim on PATH, so the module entry point was used for the equivalent check.
- Dynamic caller audit: only the three retained lifecycle imports and frozen queue module remain executable references; deleted basenames appear only in a historical comment or evidence metadata.
- `git diff --cached --check`: passed.
- The two files initially found to be current regression dependencies were restored and retained: `scripts/davinci/validate_caption_lifecycle_fcpxml_step_3D.py` and `resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py`.
- Frozen hashes remained unchanged from Step 4: `VC_Run_Agent_Task.py` `873ada0103990254232e16bfdb4e6590a2d91f24`, `VC_Agent_Bridge.py` `19b1c048ea8992bae419ad60abc826e339fd6032`, and `video_cloner_phase6_textplus_application.py` `4ec39183aee74d1478ec811946e21b0137098644`.
- Generated scratch directories and Python bytecode caches created during this step were removed. The accepted fresh E2E evidence directory `.pytest-tmp-step4-e2e-2` remains intentionally retained.

## Step 5 boundary

This step proves repository ownership and source hygiene only. It does not launch Resolve or claim a live timeline application. Step 5 must still perform the explicit live Resolve gate with the frozen bridge, matching run ID, and machine acceptance evidence.

Final token: `PASS_LEGACY_SOURCE_DISTILLATION_READY_FOR_FINAL_AUTHORITY`
