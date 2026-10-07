# Historical Script Classification — Step 1 Snapshot

> Historical evidence only. The wrapper paths described here were the pre-consolidation graph and are not current operator recommendations. Use `CURRENT_PIPELINE_GRAPH.md` and `STEP4_REGRESSION_PROOF_STALE_CODE_DELETION_REPORT.md` for the post-Step-4 authority.

Audit snapshot date: 2026-10-07. Inventory at that point: 414 `.py`/`.ps1`/`.bat` files under `scripts/` and `resolve_workspace/`, 169 Python tests, and four root BAT launchers. Of the runtime/operations scripts, 329 were tracked and 85 were untracked.

This document is deliberately conservative. `UNKNOWN` means preserve until a caller/provenance check is completed.

## Then-proven path (superseded by the canonical package)

| Path | Classification | Current caller | Current callees | Current test coverage | Last proven use | Reel-specific | Safe to remove eventually | Why |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `run_video_cloner_media_prep.bat` | KEEP_CANONICAL | operator | media-prep CLI | `test_standalone_media_prep.py` | 2026-10-06 | no | no | Recorded fresh-Reel entry command. |
| `scripts/standalone/video_cloner_media_prep.py` | KEEP_CANONICAL | root BAT/operator | yt-dlp, ffmpeg | current regression | 2026-10-06 | no | no | Owns input identity, paths, WAV, proxy. |
| `scripts/standalone/video_cloner_analysis.py` | KEEP_CANONICAL | operator | seven analyzer CLIs | `test_standalone_analysis.py` | 2026-10-06 | no | no | Analysis run manifest names all callees and hashes. |
| `scripts/analysis/detect_cuts.py` | KEEP_CANONICAL | analysis orchestrator | OpenCV/data helpers | orchestrator + direct tests | 2026-10-06 | no | no | Generated fresh shots artifact. |
| `scripts/analysis/transcribe.py` | KEEP_CANONICAL | analysis orchestrator | Whisper runtime | orchestrator tests | 2026-10-06 | no | no | Generated fresh transcript. |
| `scripts/analysis/detect_rhythm_beats.py` | KEEP_CANONICAL | analysis orchestrator | audio libraries | orchestrator tests | 2026-10-06 | no | no | Generated fresh beatmap. |
| `scripts/analysis/detect_caption_style.py` | KEEP_CANONICAL | analysis orchestrator | OCR/CV helpers | multiple current classifier/authority tests | 2026-10-06 | no | no | Generated fresh caption-style authority. |
| `scripts/analysis/detect_motion_speed.py` | KEEP_CANONICAL | analysis orchestrator | CV helpers | orchestrator tests | 2026-10-06 | no | no | Generated fresh motion analysis. |
| `scripts/analysis/detect_transitions_proxy.py` | KEEP_CANONICAL | analysis orchestrator | CV helpers | orchestrator tests | 2026-10-06 | no | no | Generated raw transition observations. |
| `scripts/analysis/detect_caption_occlusion.py` | KEEP_CANONICAL | analysis orchestrator | OCR/CV/mask generation | orchestrator tests | 2026-10-06 | no | no | Generated fresh occlusion bundle. |
| `scripts/standalone/video_cloner_plan.py` | KEEP_CANONICAL | operator | four planning CLIs | `test_standalone_plan.py` | 2026-10-06 | no | no | Planning run manifest proves all four stages. |
| `scripts/planning/merge_analysis.py` | KEEP_CANONICAL | planning orchestrator | JSON inputs | current planning tests | 2026-10-06 | no | no | Generated merged analysis. |
| `scripts/planning/plan_edit.py` | KEEP_CANONICAL | planning orchestrator | merged analysis | current planning tests | 2026-10-06 | no | no | Generated edit plan. |
| `scripts/planning/validate_edit_plan.py` | KEEP_CANONICAL | planning orchestrator | analysis + plan | current planning tests | 2026-10-06 | no | no | Generated validated plan. |
| `scripts/planning/compile_generic_edit.py` | KEEP_CANONICAL | planning orchestrator | analysis + validated plan | current planning/speed/zoom tests | 2026-10-06 | no | no | Generated generic commands. |
| `scripts/analysis/build_camera_style_profile.py` | MERGE_CANDIDATE | operator | motion + video | `test_build_camera_style_profile.py` | 2026-10-06 | no | no | Current useful sidecar, not wired into pipeline. Owner: `video_cloner/profiles.py`. |
| `scripts/analysis/build_caption_style_grammar_generic.py` | MERGE_CANDIDATE | operator | caption-style JSON | current direct test | 2026-10-06 | no | no | Generic sidecar. Owner: `video_cloner/captions.py`. |
| `scripts/analysis/build_style_profile_mvp_generic.py` | MERGE_CANDIDATE | operator | five profile/planning artifacts | current comparison test | 2026-10-06 | no | no | Generic aggregator, currently stale-hash prone. Owner: `video_cloner/profiles.py`. |
| `scripts/analysis/compare_style_profiles_mvp.py` | MERGE_CANDIDATE | operator | two style profiles | current comparison test | 2026-10-06 | no | yes, after API migration | Evaluation/reporting, not runtime timeline input. Owner: `video_cloner/profiles.py`. |
| `scripts/standalone/video_cloner_mvp_transition_filter.py` | MERGE_CANDIDATE | operator | transition JSON | direct current test | 2026-10-06 | no | no | Compatibility policy belongs with transitions/planning. |
| `scripts/davinci/compile_davinci_textplus_fcpxml.py` | KEEP_CANONICAL | operator; three wrappers | FCPXML | current compiler and wrapper tests | 2026-10-06 | no | no | Exact version in fresh compiler report. |
| `scripts/davinci/prepare_video_cloner_fresh_mvp_timeline.py` | MERGE_CANDIDATE | operator | Phase 6 contract loader; command queue | indirect Phase 6 tests | 2026-10-07 | no | no | Queue publishing should move behind one pipeline CLI. |
| `resolve_workspace/VC_Run_Agent_Task.py` | COMPATIBILITY_WRAPPER | Resolve Workspace | repository bridge via importlib | bridge tests | 2026-10-07 | no | no | Required permanent installed entry point. |
| `resolve_workspace/VC_Agent_Bridge.py` | KEEP_CANONICAL | Workspace launcher / BAT | command-selected module via importlib | `test_vc_agent_bridge.py` | 2026-10-07 | no | no | Single queue/dispatch authority. |
| `resolve_workspace/modules/video_cloner_phase6_textplus_application.py` | MERGE_CANDIDATE | bridge command payload | Resolve API + FCPXML contract | Phase 6 offline tests | 2026-10-07 (failed validation) | no | no | Current Resolve implementation to keep for migration; both fresh bridge transactions are machine-unaccepted. |

## Step 1 logic not yet on one production path

| Path | Classification | Caller/callees | Test coverage | Reel-specific | Removal | Why / intended owner |
| --- | --- | --- | --- | --- | --- | --- |
| `scripts/standalone/video_cloner_textplus.py` | MERGE_CANDIDATE | imported by FCPXML/lifecycle wrappers; calls canonical compiler helpers | current standalone tests | no | no | Caption authority logic -> `video_cloner/captions.py`. |
| `scripts/standalone/video_cloner_caption_lifecycle.py` | MERGE_CANDIDATE | operator; imports Text+ and compiler | current lifecycle tests | no | no | Lifecycle logic -> `video_cloner/captions.py`. |
| `scripts/standalone/video_cloner_fcpxml.py` | COMPATIBILITY_WRAPPER | operator; imports Text+ and compiler | current standalone tests | no | yes after CLI migration | Transitional validated frontend to canonical compiler. |
| `scripts/standalone/video_cloner_transition_authority.py` | MERGE_CANDIDATE | operator/tests | direct tests | no | no | Transition contract -> `video_cloner/transitions.py`. |
| `scripts/davinci/caption_animation_step_3C.py` | MERGE_CANDIDATE | Text+ wrapper/tests | current tests | no | no | Normalization helper -> captions module. |
| `scripts/install_vc_agent_live.py` | KEEP_CANONICAL | `run_install_VC_AGENT_BRIDGE.bat` | installer/bridge evidence | no | no | Installs the Workspace launcher/config. |
| `run_install_VC_AGENT_BRIDGE.bat` | COMPATIBILITY_WRAPPER | operator | installer script | no | yes after unified CLI | Root installer entry point. |
| `run_agent_task.bat` | COMPATIBILITY_WRAPPER | operator/tests | bridge tests | no | no until semantics clarified | Runs the repository bridge in ordinary Python; it is not the Resolve Workspace launcher and does not supply Resolve's embedded API context. |
| `run_bridge_smoke_test.bat` and `resolve_workspace/modules/bridge_smoke_test.py` | EXPERIMENTAL | operator -> queued dynamic module | bridge tests | no | yes after installer acceptance | Infrastructure smoke probe, not video production. |

## Exhaustive ordered classification rules for remaining scripts

Apply these rules top-to-bottom; the explicit tables above win. This assigns exactly one class to every remaining runtime/operations file without pretending unsupported provenance.

| Path set | Classification | Caller | Callees | Coverage / last use | Reel-specific | Safe to remove eventually | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `scripts/davinci/archive(for studio)/*` (2 files) | N8N_LEGACY | no current caller found | legacy compiler/adapter | historical only | mixed | yes, after archival snapshot | Directory and n8n-era architecture are explicit. |
| `scripts/analysis/repair_*.py` (5 files) | REPAIR_ONLY | reports/tests or operator | bounded repair logic | associated focused tests; no fresh pipeline edge | mostly | yes, after evidence preservation | One-off repair naming and no canonical caller. |
| `scripts/**/__pycache__/*`, `resolve_workspace/**/__pycache__/*` | GENERATED | Python | none | none | no | yes now, but not in this task | Ignored cache, not source. |
| `scripts/analysis/build_caption_style_grammar.py`, `scripts/analysis/build_style_profile_mvp.py` | REEL_SPECIFIC_REFERENCE | operator/tests | hard-coded reference inputs | direct tests/historical evidence | yes (`DcJRJtUKScu`) | yes after generic parity | Generic variants produced the fresh artifacts. |
| `resolve_workspace/resolve_apply_video_cloner_metadata.py`, `scripts/davinci/resolve_apply_video_cloner_metadata.py` | SUPERSEDED | legacy launch paths/comments | large direct Resolve controllers | historical tests/reports | mixed | yes after dispatcher inventory | Near-copy pair (38 insertions/33 deletions), replaced in current run by bridge/module architecture. |
| `resolve_workspace/modules/*v1.py` where a `v2`/`v3`/`v4` dynamically imports it | UNKNOWN | newer module via importlib | Resolve/API helpers | historical accepted reports | mixed | no | Intermediate version is a runtime dependency despite its name. |
| other `resolve_workspace/modules/*.py` | UNKNOWN | command JSON may select by filename | Resolve API and dynamic parents | mixed accepted/failed reports | mixed | no | Command queues and ignored reports are not fully tracked; deletion is unsafe. |
| other `resolve_workspace/resolve_*.py` | UNKNOWN | legacy direct Workspace launch or no caller | Resolve API | historical reports | mixed | no | Must compare installed Scripts/Edit inventory before deletion. |
| other `scripts/davinci/prepare_*.py`, `validate_*.py`, `monitor_*.ps1` | UNKNOWN | operator/task packages | command JSON, reports, Resolve modules | historical task evidence | mostly | no | Operational scripts may be required to reproduce accepted/failed state. |
| other `scripts/analysis/{build,compile,generate,investigate,adjudicate,calibrate,close,run,validate,remove,provision}_*.py` | UNKNOWN | operator/reports/tests | JSON/artifact transforms | mixed | mostly | no | Mostly Step/Phase experiments, but evidence is insufficient for safe removal. |
| all other runtime/operations scripts | UNKNOWN | insufficient evidence | insufficient evidence | insufficient evidence | unknown | no | Preserve by safety rule. |

## Test classification

| Test set | Classification | Reason |
| --- | --- | --- |
| `test_standalone_media_prep.py`, `test_standalone_analysis.py`, `test_standalone_plan.py`, `test_build_camera_style_profile.py`, `test_build_caption_style_grammar_generic.py`, `test_style_profile_mvp_generic_comparison.py`, `test_video_cloner_mvp_transition_filter.py`, `test_compile_davinci_textplus_fcpxml_lifecycle.py`, `test_vc_agent_bridge.py`, and current standalone caption/FCPXML tests | CURRENT_REGRESSION | Directly exercises the proven or target canonical path. |
| Step/Phase and Resolve tests with preserved fixtures/reports | LEGACY_BUT_VALUABLE | They encode bug and safety regressions; retain until replacement coverage maps each contract. |
| Exact duplicate tests | REDUNDANT | No byte-identical runtime scripts were found; no test deletion is authorized without semantic comparison. |
| `test_video_cloner_phase6_offline_timeline_authority.py` | LEGACY_BUT_VALUABLE / LEGACY_EXTERNAL_FIXTURE | Requires ignored, absent `data/DcJRJtUKScu/davinci/offline_timeline_v1` fixtures. It remains deliberately runnable when that fixture package is supplied, but is excluded from the canonical default suite. |

## Verification snapshot

A focused run collected 98 tests: 36 passed, two failed, and 60 errored. Most errors came from an inaccessible global pytest temp directory; the two failures and eight fixture errors in the Phase 6 authority file came from the missing ignored Reel-1 package. This is not a canonical regression PASS.
