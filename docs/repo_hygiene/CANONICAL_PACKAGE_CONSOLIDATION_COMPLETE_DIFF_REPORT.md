# Video Cloner — Canonical Package Consolidation Complete Diff Report

Date: 2026-10-07  
Branch: `repo-hygiene/canonical-consolidation-20261007`  
Step: `3/5 — CANONICAL PACKAGE CONSOLIDATION`  
Result: **PASS**  
Final implementation commit before this report: `499a829379bca0b4eb95fbb3690d8b10b4e59b1a`

## Scope and baselines

The Step 3 task named `3399e9bfa4376fb0a59ded4867ed4d5ca4d0d4e1` as its pre-step commit. A complete pre-consolidation report was committed immediately afterward, so implementation began from `d802ce3`. This report uses:

- implementation diff: `d802ce3..499a829`
- immutable recovery point: `f728d4ae1073a2b37f58e5b06a77ed6b97ca0605`
- recovery tag: `video-cloner-pre-hygiene-snapshot-20261007`
- retained fresh Reel: `DZatr0EJt4B`
- canonical regression boundary: 115 passed, 0 failed, 0 errors, 1 deselected

No broad deletion was performed. Existing production algorithms were moved intact into package owners and historical paths became compatibility wrappers.

## Diff summary

```text
65 files changed, 26059 insertions(+), 25297 deletions(-)
```

Most apparent churn is source relocation: large implementations moved from `scripts/` into `video_cloner/`, while the old paths were reduced to thin import/CLI delegates. Git's line-based summary does not classify these edited-wrapper moves as renames.

### Added files

```text
.github/workflows/offline-core.yml
docs/repo_hygiene/DEPENDENCY_STRATEGY.md
pyproject.toml
tests/test_video_cloner_config_contracts.py
tests/test_video_cloner_pipeline_cli.py
video_cloner/__init__.py
video_cloner/analysis/__init__.py
video_cloner/analysis/caption_occlusion.py
video_cloner/analysis/caption_style.py
video_cloner/analysis/cuts.py
video_cloner/analysis/motion.py
video_cloner/analysis/pipeline.py
video_cloner/analysis/rhythm.py
video_cloner/analysis/transcription.py
video_cloner/analysis/transitions.py
video_cloner/camera.py
video_cloner/caption_grammar.py
video_cloner/captions/__init__.py
video_cloner/captions/fcpxml.py
video_cloner/captions/lifecycle.py
video_cloner/captions/textplus.py
video_cloner/cli.py
video_cloner/config.py
video_cloner/contracts.py
video_cloner/ingestion/__init__.py
video_cloner/ingestion/media.py
video_cloner/pipeline.py
video_cloner/planning/__init__.py
video_cloner/planning/compile.py
video_cloner/planning/merge.py
video_cloner/planning/pipeline.py
video_cloner/planning/plan.py
video_cloner/planning/validate.py
video_cloner/profile_comparison.py
video_cloner/profiles.py
video_cloner/resolve/__init__.py
video_cloner/resolve/fcpxml.py
video_cloner/resolve/queue.py
video_cloner/transition_policy.py
```

### Modified files

```text
scripts/analysis/build_camera_style_profile.py
scripts/analysis/build_caption_style_grammar_generic.py
scripts/analysis/build_style_profile_mvp_generic.py
scripts/analysis/compare_style_profiles_mvp.py
scripts/analysis/detect_caption_occlusion.py
scripts/analysis/detect_caption_style.py
scripts/analysis/detect_cuts.py
scripts/analysis/detect_motion_speed.py
scripts/analysis/detect_rhythm_beats.py
scripts/analysis/detect_transitions_proxy.py
scripts/analysis/transcribe.py
scripts/davinci/compile_davinci_textplus_fcpxml.py
scripts/davinci/prepare_video_cloner_fresh_mvp_timeline.py
scripts/planning/compile_generic_edit.py
scripts/planning/merge_analysis.py
scripts/planning/plan_edit.py
scripts/planning/validate_edit_plan.py
scripts/standalone/video_cloner_analysis.py
scripts/standalone/video_cloner_caption_lifecycle.py
scripts/standalone/video_cloner_fcpxml.py
scripts/standalone/video_cloner_media_prep.py
scripts/standalone/video_cloner_mvp_transition_filter.py
scripts/standalone/video_cloner_plan.py
scripts/standalone/video_cloner_textplus.py
tests/test_standalone_analysis.py
tests/test_standalone_plan.py
```

### Deleted files

None.

## Substep status

| Substep | Status | Result |
|---|---|---|
| 3A — config/contracts | PASS | Central config, run/artifact contracts, dependency metadata |
| 3B — ingestion | PASS | Media preparation moved to `video_cloner.ingestion.media` |
| 3C — analysis | PASS | Orchestrator and seven analyzers moved; canonical subprocess paths active |
| 3D — planning | PASS | Orchestrator and four deterministic stages moved |
| 3E — profiles | PASS | Camera, caption grammar, style, comparison, transition policy moved |
| 3F — captions/FCPXML | PASS | Offline caption and compiler owners moved intact |
| 3G — queue | PASS | Offline package/queue publication moved; live bridge contract preserved |
| 3H — API/CLI | PASS | One pipeline API and one `video-cloner` CLI added |
| 3I — wrappers | PASS | Required old paths are thin delegates with removal gates |
| 3J — parity/regression | PASS | Fresh-Reel parity, 115-test regression, and lightweight CI green |

## Canonical package

The package contains 34 tracked Python modules. The public orchestration surface is `video_cloner.pipeline`:

```text
context(...)
ingest(...)
analyze(...)
plan(...)
profile(...)
compile(...)
publish(...)
run_offline(...)
```

`pipeline.py` contains orchestration only. Algorithms remain in cohesive capability modules.

The installed console entry point is:

```text
video-cloner ingest ...
video-cloner analyze ...
video-cloner plan ...
video-cloner profile ...
video-cloner compile ...
video-cloner publish ...
video-cloner run-offline ...
```

Both CLI and future application callers route through `video_cloner.pipeline`; the CLI does not invoke BAT, PowerShell, or arbitrary standalone scripts.

## Configuration and contracts

`video_cloner.config.RuntimeConfig` is the canonical authority for:

- repository, input, media, data, and state roots;
- default/core, audio, OCR, rhythm, and Resolve Python executables;
- ffmpeg and yt-dlp executables;
- Ollama endpoint/model;
- Resolve installation paths, project name, and target timeline;
- optional cookies path.

Configuration loads from defaults, an optional JSON file, `VIDEO_CLONER_*` environment variables, and explicit overrides. Sensitive URL query/fragment data is excluded from public runtime identity.

`video_cloner.contracts` adds:

- `InputSpec`
- `RunContext`
- `ArtifactIdentity`
- `StageResult`
- canonical URL/video identity helpers
- optional immutable `run_id`
- media dependency DAG and public run-context contract

The optional `run_id` preserves old public contracts while allowing new callers to establish immutable run identity. Existing mutable artifact locations remain for compatibility and are not represented as immutable solely because they have a path.

## Dependency strategy

`pyproject.toml` declares:

- supported Python: `>=3.10,<3.15`
- core package dependencies: none
- test extra: pytest
- default-analysis extra: NumPy, OpenCV, PySceneDetect
- audio extra: the separately provisioned NumPy/librosa/faster-whisper stack
- OCR extra: the separately provisioned compatible NumPy/OpenCV/Paddle stack

`docs/repo_hygiene/DEPENDENCY_STRATEGY.md` explicitly documents that Paddle GPU support remains separately provisioned and that the current multi-runtime system must not be falsely locked into one environment.

## Capability migration map

| Capability | Historical owner | Canonical owner | Compatibility result |
|---|---|---|---|
| Media prep | `scripts/standalone/video_cloner_media_prep.py` | `video_cloner/ingestion/media.py` | historical CLI delegates |
| Analysis orchestration | `scripts/standalone/video_cloner_analysis.py` | `video_cloner/analysis/pipeline.py` | historical CLI delegates |
| Cuts | `scripts/analysis/detect_cuts.py` | `video_cloner/analysis/cuts.py` | wrapper delegates |
| Transcription | `scripts/analysis/transcribe.py` | `video_cloner/analysis/transcription.py` | wrapper delegates |
| Rhythm | `scripts/analysis/detect_rhythm_beats.py` | `video_cloner/analysis/rhythm.py` | wrapper delegates |
| Caption style | `scripts/analysis/detect_caption_style.py` | `video_cloner/analysis/caption_style.py` | wrapper delegates |
| Motion | `scripts/analysis/detect_motion_speed.py` | `video_cloner/analysis/motion.py` | wrapper delegates |
| Transitions | `scripts/analysis/detect_transitions_proxy.py` | `video_cloner/analysis/transitions.py` | wrapper delegates; monkeypatch compatibility retained |
| Caption occlusion | `scripts/analysis/detect_caption_occlusion.py` | `video_cloner/analysis/caption_occlusion.py` | wrapper delegates |
| Planning orchestration | `scripts/standalone/video_cloner_plan.py` | `video_cloner/planning/pipeline.py` | historical CLI delegates |
| Planning merge | `scripts/planning/merge_analysis.py` | `video_cloner/planning/merge.py` | wrapper delegates |
| Edit planning | `scripts/planning/plan_edit.py` | `video_cloner/planning/plan.py` | wrapper delegates |
| Plan validation | `scripts/planning/validate_edit_plan.py` | `video_cloner/planning/validate.py` | wrapper delegates |
| Generic command compile | `scripts/planning/compile_generic_edit.py` | `video_cloner/planning/compile.py` | wrapper delegates |
| Camera profile | `scripts/analysis/build_camera_style_profile.py` | `video_cloner/camera.py` | wrapper delegates |
| Caption grammar | `scripts/analysis/build_caption_style_grammar_generic.py` | `video_cloner/caption_grammar.py` | wrapper delegates |
| Style profile | `scripts/analysis/build_style_profile_mvp_generic.py` | `video_cloner/profiles.py` | wrapper delegates |
| Profile comparison | `scripts/analysis/compare_style_profiles_mvp.py` | `video_cloner/profile_comparison.py` | wrapper delegates |
| Transition policy | `scripts/standalone/video_cloner_mvp_transition_filter.py` | `video_cloner/transition_policy.py` | wrapper delegates |
| Caption lifecycle | `scripts/standalone/video_cloner_caption_lifecycle.py` | `video_cloner/captions/lifecycle.py` | import alias retained |
| Caption Text+ | `scripts/standalone/video_cloner_textplus.py` | `video_cloner/captions/textplus.py` | import alias retained |
| Caption FCPXML | `scripts/standalone/video_cloner_fcpxml.py` | `video_cloner/captions/fcpxml.py` | import alias retained |
| Offline compiler | `scripts/davinci/compile_davinci_textplus_fcpxml.py` | `video_cloner/resolve/fcpxml.py` | module/CLI alias retained |
| Queue publisher | `scripts/davinci/prepare_video_cloner_fresh_mvp_timeline.py` | `video_cloner/resolve/queue.py` | module/CLI alias retained |

## Fresh-Reel offline parity

### Retained artifact hashes

All 23 source/media/analysis/planning/profile/compiler/manifest artifacts recorded in `DZatr0EJt4B_CANONICAL_RUN_MANIFEST.json` still match exactly after consolidation:

```text
MATCH=23 MISMATCH=0 TOTAL=23
```

This includes the media-prep artifacts, seven analysis artifacts plus analysis run report, four planning outputs plus planning run report, camera/grammar/style/transition artifacts, FCPXML, compiler report, and timeline manifest.

### Generated old-versus-new comparisons

| Stage | Comparison | Result |
|---|---|---|
| Media-prep contract | historical CLI vs canonical CLI, no-force reuse | semantic exact; zero artifacts regenerated on either path |
| Camera profile | historical wrapper vs package CLI | exact SHA-256 `e312441f3ad083a5c5b5475c05bfab217fb4f97e25a18cb08cd1e474b3356fab` |
| Caption grammar | historical wrapper vs package CLI | exact SHA-256 `7aab5c89045d972207f9b8d9362960e765035c596b3d22027144a7618cf35fae` |
| Style profile | historical wrapper vs package CLI | normalized exact; only generated camera/grammar path strings differed |
| Transition filter | historical wrapper vs package CLI | exact SHA-256 `8f788e405db512ebebed8d6b5179dfc6544787655f2ce77168326a4a92590dc2` |
| FCPXML compiler | historical wrapper vs canonical `video-cloner compile` | exact SHA-256 `681048a9840ae8939d9ccc48446afbe9660e8af63576a19133ee3fab51145eaa` |
| Compiler report | historical wrapper vs canonical API | normalized exact; ignored only `started_at_unix` and `runtime_sec` |
| Queue publication | historical wrapper vs canonical `video-cloner publish` in disposable queue | normalized command exact; ignored only run ID and run-derived status/log/report paths |

Analysis and planning artifacts did not require expensive model re-execution: every retained generated artifact remained byte-identical to the accepted pre-migration manifest, and the migrated orchestrators now point at the package modules whose algorithms were moved intact.

No validation was weakened. No Resolve process was started.

## Regression and CI

Canonical regression command:

```powershell
python -m pytest --basetemp=.pytest-tmp-repo-hygiene-step3 -q tests/test_standalone_media_prep.py tests/test_standalone_analysis.py tests/test_standalone_plan.py tests/test_build_camera_style_profile.py tests/test_build_caption_style_grammar_generic.py tests/test_style_profile_mvp_generic_comparison.py tests/test_video_cloner_mvp_transition_filter.py tests/test_compile_davinci_textplus_fcpxml_lifecycle.py tests/test_prepare_video_cloner_fresh_mvp_timeline.py tests/test_vc_agent_bridge.py tests/test_video_cloner_phase6_offline_timeline_live_application.py -k "not actual_step7b_preflight_report_validates_without_mutation"
```

Result:

```text
115 passed, 0 failed, 0 errors, 1 deselected in 5.56s
```

New lightweight CI gate local proof:

```text
63 passed in 3.30s
```

The workflow runs package/config/API tests plus media, analysis, and planning orchestration tests on Windows/Python 3.14. It does not require Resolve, GPU, private media, `.agent` history, OCR downloads, or audio models.

## Resolve safety

Live Resolve runtime changed: **NO**  
Queue command schema changed: **NO**  
Queue default path changed: **NO**  
Resolve launched: **NO**  
Resolve project/timeline mutated: **NO**  
Machine acceptance status: **still not accepted**, unchanged from the pre-step evidence.

Frozen file hashes remain:

```text
resolve_workspace/VC_Run_Agent_Task.py
ce39ebd249963b67450e79d67435f6a9618eeaacc8700e9ed9d5fa2e35c98013

resolve_workspace/VC_Agent_Bridge.py
c5d342d1b735a9e7862bf60aedb38c3bade391324d57e518d68b3b3b8578c85e

resolve_workspace/modules/video_cloner_phase6_textplus_application.py
14fa8307716708f19116b86fbddf208a5a000e4b7494d39327c330a93a31a859
```

The canonical configuration can represent an alternate `state_root`, but publication intentionally continues to use the frozen bridge's `.agent/commands` contract. Redirecting the live bridge queue is deferred until a separately accepted Resolve-boundary change; silently changing it here would have violated the stop condition.

## Commits produced

```text
dc5290a refactor(core): introduce canonical config and contracts
3b06a8d refactor(ingestion): migrate media preparation
0a8eaf1 refactor(analysis): migrate canonical analyzers
7e904d1 refactor(analysis): route orchestrator through package modules
f7308db refactor(planning): migrate planning pipeline
9fc1cad refactor(profiles): consolidate generic style capabilities
8acf12c refactor(resolve-offline): migrate caption and FCPXML owners
27a6116 refactor(resolve-offline): migrate queue publication
89b6913 feat(cli): expose canonical video-cloner command
d5d1801 ci(core): verify canonical offline package
499a829 fix(cli): keep profile arguments minimal
```

## Step 4 deletion candidates

No candidate should be deleted until its listed gate is proven.

| Candidate family | Exact files | Remaining callers/evidence | Deletion gate |
|---|---|---|---|
| Analyzer wrappers | `scripts/analysis/detect_cuts.py`, `transcribe.py`, `detect_rhythm_beats.py`, `detect_caption_style.py`, `detect_motion_speed.py`, `detect_transitions_proxy.py`, `detect_caption_occlusion.py` | historical N8N node map, direct compatibility tests, operator commands | prove no active N8N/operator/subprocess caller uses historical paths; update retained maps/tests |
| Analysis CLI | `scripts/standalone/video_cloner_analysis.py` | historical operator CLI/tests | migrate all callers to `video-cloner analyze` and preserve contract coverage |
| Planning wrappers | `scripts/planning/merge_analysis.py`, `plan_edit.py`, `validate_edit_plan.py`, `compile_generic_edit.py` | compatibility tests/operator history | prove canonical orchestrator is sole runtime caller; retarget tests |
| Planning CLI | `scripts/standalone/video_cloner_plan.py` | historical operator CLI/tests | migrate callers to `video-cloner plan` |
| Profile wrappers | four `scripts/analysis/build_*profile*.py`/`compare_style_profiles_mvp.py` files | current direct tests and documented operator commands | retarget tests/operators to package API/CLI |
| Transition wrapper | `scripts/standalone/video_cloner_mvp_transition_filter.py` | current direct test/operator compatibility | retarget to package API |
| Caption wrappers | `scripts/standalone/video_cloner_caption_lifecycle.py`, `video_cloner_textplus.py`, `video_cloner_fcpxml.py` | import compatibility tests and historical imports | prove no remaining import identity caller depends on old module names |
| Compiler wrapper | `scripts/davinci/compile_davinci_textplus_fcpxml.py` | N8N map, historical scripts, compiler tests | migrate every caller to `video-cloner compile` or `video_cloner.resolve.fcpxml` |
| Media wrapper | `scripts/standalone/video_cloner_media_prep.py` | root BAT/operator callers | migrate root launchers/operators to `video-cloner ingest` |
| Queue wrapper | `scripts/davinci/prepare_video_cloner_fresh_mvp_timeline.py` | operator path and queue tests | migrate operators/tests to `video-cloner publish`; re-prove frozen bridge command compatibility |

The three frozen live Resolve files are **not** Step 4 deletion candidates.

## Known constraints and risks

1. The live Resolve transaction remains unaccepted. Step 3 deliberately proves only offline consolidation and queue-contract parity.
2. Alternate `state_root` values are represented centrally but are not applied to the frozen live bridge queue.
3. Several large algorithm modules remain large because this was a behavior-preserving move. Splitting them during Step 3 would have mixed structural migration with algorithm risk.
4. The one deselected test still depends on a large ignored historical `.agent` report. Its safety property must be replaced with a self-contained fixture or formally retired before relevant Step 4 deletion.
5. OCR/audio environments remain separate. This is documented architecture, not an unresolved attempt at one universal environment.

## Git state

Before adding this report, the working tree was clean. All implementation changes are in coherent bounded commits. This report is the only final documentation artifact added after the verified implementation commit.

## Next action

Begin Step 4 with caller inventory and deletion proof for the lowest-risk wrapper family. Do not touch the frozen live Resolve boundary until its own machine-acceptance task exists.

## Final token

`PASS_CANONICAL_PACKAGE_CONSOLIDATION`
