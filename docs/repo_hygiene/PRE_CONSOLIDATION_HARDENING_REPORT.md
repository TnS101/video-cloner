# Video Cloner — Pre-Consolidation Hardening Report

## Result

**PASS — PRE-CONSOLIDATION HARDENING COMPLETE**

- Current step: **2.5/5 — Pre-Consolidation Hardening**
- Repository: `C:\Users\User\Downloads\Projects\Video Cloner`
- Working branch: `repo-hygiene/canonical-consolidation-20261007`
- Hardening implementation commit: `3399e9bfa4376fb0a59ded4867ed4d5ca4d0d4e1`
- Recovery snapshot commit: `f728d4ae1073a2b37f58e5b06a77ed6b97ca0605`
- Recovery tag: `video-cloner-pre-hygiene-snapshot-20261007`
- Date: 2026-10-07

This report is the consolidated handoff for Step 2.5. It does not declare the runtime production-accepted and does not begin package consolidation.

## 1. Recovery integrity and branch isolation

The recovery branch was not used for continued development. The annotated recovery tag and recovery branch both still dereference to the exact preserved snapshot:

```text
repo-hygiene/pre-cleanup-snapshot-20261007
  -> f728d4ae1073a2b37f58e5b06a77ed6b97ca0605

video-cloner-pre-hygiene-snapshot-20261007^{}
  -> f728d4ae1073a2b37f58e5b06a77ed6b97ca0605
```

The new working branch was created from that exact commit:

```text
repo-hygiene/canonical-consolidation-20261007
```

No amend, rebase, tag movement, or history rewrite was performed on the recovery point.

## 2. Reviewed upstream merge

The upstream branch `origin/migration/autonomy-baseline-20260908` was merged normally with merge commit:

```text
7a2f91be195d8423be96002190b8b1af8a51f46b
merge: reviewed upstream migration documentation
```

The merge changed exactly eight reviewed documentation, instruction, and classification files:

```text
.agent/README.md
AGENTS.md
docs/migration/CANONICAL_PIPELINE.md
docs/migration/MIGRATION_SEQUENCE.md
docs/migration/MIGRATION_STATUS.md
docs/migration/SCRIPT_CLASSIFICATION.csv
docs/migration/SCRIPT_CLASSIFICATION.json
docs/migration/WORKSPACE_AUDIT.md
```

No runtime file changed in the merge. The upstream commits were:

- `923a18b5a21b20c9942e4d1bbf53aab66dac661a` — migration baseline corrections and classification updates.
- `f2d1837faae5c3f6c7d0e87dd1634e4899f11c20` — PR review status correction in the workspace audit.

## 3. Generated usage-dump cleanup

The following root files were generated grep/usage evidence, not source:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `keyframe_api_usage.txt` | 937 | `fd565ff40ac74038c1d712fec963363ed883208795b55ade3a14dfe4088484c6` |
| `latest_accepted_usage.txt` | 440 | `4d2613ba3fd98b7de71f4a89734e1133d48ab90a6b022cb07db32e353918daff` |
| `step_3B_6E_usage.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

Their hashes and full non-empty contents were verified against `PRE_HYGIENE_SNAPSHOT_COMPLETE_DIFF_REPORT.md` before removal. No broad `*_usage.txt` ignore rule was added, so future accidental root dumps remain visible.

## 4. Manifest semantics

`PRE_HYGIENE_SOURCE_MANIFEST.json` is explicitly the **PRE-COMMIT WORKING-TREE MANIFEST**. Its `tracked` and `modified` fields describe the repository before snapshot commit `f728d4a`. A file recorded there as `tracked: false` may therefore be tracked by the resulting snapshot commit.

`SNAPSHOT_COMMIT_MANIFEST.json` is the authority for the actual committed tree. It was generated from Git tree and blob objects at the immutable snapshot commit, not from the current worktree.

### Snapshot commit manifest verification

| Field | Value |
| --- | --- |
| Path | `docs/repo_hygiene/SNAPSHOT_COMMIT_MANIFEST.json` |
| Schema | `video_cloner.snapshot_commit_manifest.v1` |
| Snapshot commit | `f728d4ae1073a2b37f58e5b06a77ed6b97ca0605` |
| Snapshot tag | `video-cloner-pre-hygiene-snapshot-20261007` |
| Entries | 622 |
| SHA-256 mismatches | 0 |
| Git object-ID mismatches | 0 |

Each record contains:

- repository-relative path;
- Git blob/object ID;
- SHA-256 of exact committed bytes;
- byte count;
- source, test, documentation, or configuration classification.

The scope includes `scripts/`, `resolve_workspace/`, `tests/`, `docs/`, `config/`, relevant root source/configuration files, root BAT/PowerShell launchers, `.gitignore`, and `AGENTS.md`.

## 5. Environment and dependency baseline

The audit was read-only. It records the machine that produced and verified the baseline; it is not a final dependency lock.

### Platform

| Component | Detected value |
| --- | --- |
| OS | Windows 11, build `10.0.26200`, AMD64 |
| GPU | NVIDIA GeForce RTX 5070 |
| NVIDIA driver | 596.36 |
| GPU memory | 12227 MiB |
| Compute capability | 12.0 |

### Python environments

| Role | Python | pip | Executable |
| --- | --- | --- | --- |
| Canonical regression | 3.14.5 | 26.2 | `C:\Python314\python.exe` |
| Default analysis | 3.14.5 | 26.1.2 | `Virtual Environments\venv\Scripts\python.exe` |
| Audio analysis | 3.10.11 | 26.1.2 | `Virtual Environments\venv_audio\Scripts\python.exe` |
| OCR/segmentation | 3.10.11 | 26.1.2 | `Virtual Environments\venv_ocr\Scripts\python.exe` |

### Relevant installed packages

| Capability | Packages and versions |
| --- | --- |
| Regression | pytest 9.1.1; NumPy 2.4.4; opencv-contrib-python 4.13.0.92 |
| Default analysis | NumPy 2.4.6; opencv-python 4.13.0.92; PySceneDetect 0.7 |
| Transcription/audio | faster-whisper 1.2.1; CTranslate2 4.8.0; librosa 0.10.1; NumPy 1.23.5 |
| Audio CUDA libraries | nvidia-cublas-cu12 12.9.2.10; nvidia-cudnn-cu12 9.23.1.3 |
| OCR/segmentation | PaddleOCR 2.7.3; PaddlePaddle GPU distribution 3.0.0.dev20250717, runtime 3.0.0; PaddleHub 2.4.0; NumPy 1.23.5; OpenCV 4.6.0.66 |

CTranslate2 detected one CUDA device. Paddle reported CUDA compilation enabled and selected `gpu:0`.

### External tools

| Tool | Status |
| --- | --- |
| ffmpeg | `2026-05-25-git-34dfa8bf2b-essentials_build-www.gyan.dev`; available at `C:\ffmpeg\bin\ffmpeg.exe` |
| yt-dlp | `2026.08.30.232658`; installed in the Python 3.14 user scripts directory |
| Ollama | 0.35.1; service reachable; `llama3.1:latest`, model ID `46e0c10c039e`, present |
| DaVinci Resolve | 21.0.1.11 portable executable detected |
| Resolve scripting API | `DaVinciResolveScript.py` found under ProgramData |

Ollama is conditionally required by the current planner only when `plan_edit.py` runs without a supplied `--llm-response`.

### Dependency-definition gap

No project-owned `pyproject.toml`, `requirements*.txt`, Python lock file, Pipfile, or Conda environment file exists outside ignored local virtual environments. The current route therefore relies on three separately provisioned runtime interpreters and external executables. Step 3 must introduce the canonical dependency declaration after package boundaries are established.

Machine-readable evidence is in `ENVIRONMENT_BASELINE.json`; the readable audit is in `ENVIRONMENT_BASELINE.md`. The cookies environment value was deliberately excluded.

## 6. Historical and external provenance

The committed inventory searched source, configuration, tests, documentation, root BAT files, and root PowerShell files for:

- `C:/Users/` and `C:\Users\`;
- `.agent/` and `.agent\`;
- `DcJRJtUKScu`;
- `.drt` paths.

### Inventory result

| Classification | Match lines |
| --- | ---: |
| `PRODUCTION_DEPENDENCY` | 3 |
| `TEST_FIXTURE_DEPENDENCY` | 96 |
| `HISTORICAL_REFERENCE_ONLY` | 481 |
| `DOCUMENTATION_ONLY` | 25 |
| `UNKNOWN` | 0 |
| **Total** | **605 across 221 files** |

The three production match lines are:

```text
resolve_workspace/VC_Agent_Bridge.py:60
resolve_workspace/VC_Agent_Bridge.py:61
scripts/davinci/prepare_video_cloner_fresh_mvp_timeline.py:195
```

They reference `.agent` only as an operational command queue/report-state location. No current fresh-Reel source reads a pre-existing ignored `.agent` report/task, machine-local absolute path, Reel #2 input media, or external DRT as an input.

Consequently there is no missing historical-input blocker for Step 3. The operational state root must nevertheless become configurable so the final package does not require a hard-coded ignored `.agent` location.

Accepted Reel #2 configurations were not cosmetically rewritten. Large media, DRT files, and ignored report trees were not copied into Git. If later regression work needs historical evidence, only the smallest bounded datum should be promoted into `tests/fixtures/` with provenance.

The complete 605-line occurrence inventory and classification is in `HISTORICAL_EVIDENCE_DEPENDENCIES.md`.

## 7. Target architecture

The target is defined by public entry points and cohesive ownership, not minimum file count.

### Public routes

```text
Operator / automation
  -> video_cloner.cli
  -> video_cloner.pipeline
  -> internal capability modules

Future local web UI
  -> video_cloner.pipeline
  -> the same internal capability modules

Resolve
  -> VC_Agent_Bridge.py
  -> allowlisted modules/timeline_import.py operation
```

The future web application must not invoke PowerShell, BAT files, or arbitrary standalone Python scripts as its application boundary.

### Internal module strategy

The estimated healthy runtime package is 20–30 modules. Algorithmically distinct analyzers remain separate:

- cuts;
- transcription;
- rhythm;
- caption style/CV;
- motion;
- transition detection;
- caption occlusion.

Planning retains separate merge, plan, validate, and compile capabilities. Caption grammar, lifecycle, Text+, and style remain cohesive internal modules rather than becoming one multi-thousand-line file.

Primary shared owners are:

- `config.py` — validated runtime inputs, roots, executables, services, and models;
- `contracts.py` — schemas, manifests, artifact identity, and validation;
- `pipeline.py` — public desired-state application API;
- `cli.py` — one thin command surface;
- `resolve/queue.py` and `resolve/fcpxml.py` — offline Resolve-facing artifacts and publication;
- `VC_Agent_Bridge.py` plus one allowlisted import module — live mutation boundary.

No empty architecture scaffolding was created in Step 2.5.

## 8. Configuration boundary

The new canonical package must receive these values as validated configuration or invocation inputs:

- Resolve project name;
- target/protected timeline identity;
- Reel ID;
- repository, input, media, data, and state roots;
- model names and service endpoints;
- Python and external runtime executables.

`New Project 1`, historical timeline IDs, Reel-specific IDs, and `C:/Users/...` paths may remain in historical tests and recovery scripts but cannot become canonical production constants.

Step 3 should create one configuration model shared by the CLI and pipeline API. Compatibility adapters may translate the existing environment variables and runtime JSON into that model. Historical scripts are not to be rewritten wholesale.

## 9. Canonical regression

The exact baseline command was rerun after branch creation, upstream merge, and all hardening documentation/manifest changes:

```powershell
python -m pytest --basetemp=.pytest-tmp-repo-hygiene -q tests/test_standalone_media_prep.py tests/test_standalone_analysis.py tests/test_standalone_plan.py tests/test_build_camera_style_profile.py tests/test_build_caption_style_grammar_generic.py tests/test_style_profile_mvp_generic_comparison.py tests/test_video_cloner_mvp_transition_filter.py tests/test_compile_davinci_textplus_fcpxml_lifecycle.py tests/test_prepare_video_cloner_fresh_mvp_timeline.py tests/test_vc_agent_bridge.py tests/test_video_cloner_phase6_offline_timeline_live_application.py -k "not actual_step7b_preflight_report_validates_without_mutation"
```

Result:

```text
115 passed
0 failed
0 errors
1 deselected
6.95 seconds
```

The repository-local `--basetemp` avoids the previously diagnosed global temporary-directory permission problem.

The deselection remains a temporary boundary. Before Resolve consolidation or deletion in Step 4, the safety property represented by every external-fixture exclusion must either:

1. have a self-contained replacement fixture/test; or
2. be formally proven legacy-only and irrelevant to the canonical route.

## 10. Files changed by hardening

The coherent hardening commit changed only documentation and manifests:

```text
docs/repo_hygiene/CANONICAL_REGRESSION_BASELINE.md
docs/repo_hygiene/ENVIRONMENT_BASELINE.json
docs/repo_hygiene/ENVIRONMENT_BASELINE.md
docs/repo_hygiene/GIT_HEALTH_AUDIT.md
docs/repo_hygiene/HISTORICAL_EVIDENCE_DEPENDENCIES.md
docs/repo_hygiene/PRE_HYGIENE_SNAPSHOT_COMPLETE_DIFF_REPORT.md
docs/repo_hygiene/SNAPSHOT_COMMIT_MANIFEST.json
docs/repo_hygiene/TARGET_ARCHITECTURE.md
```

No production algorithm, production source file, historical accepted configuration, or recovery ref was changed by the hardening commit.

## 11. Evidence index

| Artifact | Purpose |
| --- | --- |
| `PRE_HYGIENE_SOURCE_MANIFEST.json` | Pre-commit working-tree tracking and byte state |
| `SNAPSHOT_COMMIT_MANIFEST.json` | Exact snapshot Git tree/blob identity |
| `PRE_HYGIENE_SNAPSHOT_COMPLETE_DIFF_REPORT.md` | Complete 187-file snapshot unified diff and preserved usage dumps |
| `DZatr0EJt4B_CANONICAL_RUN_MANIFEST.json` | Fresh-Reel source, artifact, and runtime provenance |
| `CANONICAL_REGRESSION_BASELINE.md` | Exact bounded regression command and results |
| `ENVIRONMENT_BASELINE.md` / `.json` | Human-readable and machine-readable runtime environment |
| `HISTORICAL_EVIDENCE_DEPENDENCIES.md` | Complete historical/external path occurrence inventory |
| `TARGET_ARCHITECTURE.md` | Package, public API, configuration, Resolve, and web boundaries |
| `GIT_HEALTH_AUDIT.md` | Git risks and manifest-semantics correction |

## 12. Unresolved risks

1. Resolve application remains machine-unaccepted because the observed bridge transactions ended in validation failure even though a reviewable timeline may exist.
2. The current Resolve implementation must not replace or delete older modules until controlled application, persistent readback, and idempotency pass.
3. The external-fixture/deselected safety contract must be replaced or formally retired before Step 4 deletion.
4. The canonical dependency declaration and lock strategy do not yet exist.
5. Three current production lines still hard-code `.agent` as operational state; Step 3 must put the state root behind configuration.

None of these risks blocks beginning bounded package consolidation. They remain explicit gates before destructive cleanup or production acceptance.

## 13. Next action

**BEGIN STEP 3/5 — CANONICAL PACKAGE CONSOLIDATION**

`PASS_PRE_CONSOLIDATION_HARDENING`
