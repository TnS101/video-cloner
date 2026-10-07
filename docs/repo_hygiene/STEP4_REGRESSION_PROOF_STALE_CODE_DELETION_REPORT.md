# Video Cloner Repository Hygiene — Step 4 Complete Report

Date: 2026-10-07  
Step: 4/5 — Regression proof, stale-code deletion, and Git cleanup  
Branch: `repo-hygiene/canonical-consolidation-20261007`  
Evidence baseline after implementation/deletion commits: `2f7d0c1f75d122dbb0195d62704afac4b30eff66`

## Result

PASS. The repository has one public full-workflow command and Python API, canonical runs have immutable run IDs and manifests, a fresh isolated `DZatr0EJt4B` run completed through bounded queue publication, current-path regression has no deselections, compatibility wrappers and an additional repository-wide stale-source wave were deleted, deferred capability sources were retained, the frozen Resolve boundary was unchanged, and the final tracked working tree is clean after this report commit.

Live Resolve application was deliberately not executed. Step 4 proves the offline product path and command publication, not machine acceptance of a Resolve timeline.

## Git truth

- Step 3 start used for the commit-range check: `d802ce3`.
- Step 3 completion/report commit: `9457568e9c1b1bd8083a9d24eaab7d5db1907537`.
- `git rev-list --count d802ce3..9457568` returned `12`.
- The apparent 11-versus-12 discrepancy is factual, not lost history: Step 3 had 11 implementation/CI commits plus the committed final report commit.
- `docs/repo_hygiene/CANONICAL_PACKAGE_CONSOLIDATION_COMPLETE_DIFF_REPORT.md` is tracked and committed.
- History was not rewritten. The immutable recovery point remains `f728d4ae1073a2b37f58e5b06a77ed6b97ca0605` / `video-cloner-pre-hygiene-snapshot-20261007`.

Step 4 commits through the evidence baseline:

| Commit | Purpose |
| --- | --- |
| `c7a6d61` | Add identified one-command workflow and bounded public publication API. |
| `740e387` | Replace the private `.agent` preflight dependency with a self-contained safety fixture. |
| `5157b7d` | Apply transition policy before planning; fixes the first fresh-E2E failure at the shared orchestration boundary. |
| `73d5b97` | Add lightweight Python 3.10 compatibility CI. |
| `0df40d1` | Retarget tests and remove canonical compatibility wrappers. |
| `2f7d0c1` | Remove a second wave of superseded forensic/probe launchers and generated-package noise. |

## One-entry pipeline

Public Python API:

```python
video_cloner.pipeline.run(source, config, project=..., target_timeline=...)
```

Public CLI:

```text
video-cloner run --project-root . --local-video <path> --project VideoCloner --target-timeline VIDEO_CLONER_DZatr0EJt4B_MVP_V1
```

The single orchestration flow is:

```text
ingest/reuse
-> analysis
-> transition policy
-> planning
-> camera/caption/style profiles
-> FCPXML compile
-> bounded Resolve queue publication
```

`run_offline()` reuses the same implementation through compilation and intentionally omits publication. No manual PowerShell or BAT chain is required for normal operation. Neither entry point launches or mutates Resolve.

## Run identity and manifest

Every canonical full run receives a generated run ID when the caller omits one. The successful fresh run was:

- Run ID: `DZatr0EJt4B-20261007T084921050672Z-a5b35ef930c2`
- Manifest: `.pytest-tmp-step4-e2e-2/state/runs/DZatr0EJt4B-20261007T084921050672Z-a5b35ef930c2/manifest.json`
- Manifest SHA-256: `c3c8a5183c707231fff06060c52fb66b05039719915c8f5b1a11d31192c5ef92`
- Schema: `video_cloner.canonical_run.v1`
- Result: `success`
- Source SHA-256: `e0b60e0cfd647894033c8daa5d1b285d4b3d0d22f83a9ccc80a0ebbe99817911`
- Configuration identity: `9e9e1d8ac4812bc675078640f650f00a522b2d2b5d18e8a12e05ab3a32736ce7`
- Hashed artifact records: 1,354
- Started: `2026-10-07T08:49:21.051194Z`
- Finished: `2026-10-07T08:53:13.404531Z`

The manifest records source/configuration/runtime identity, per-stage status, artifacts and hashes, timestamps, final result, and published command identity. It is written atomically under `state/runs/<run_id>/manifest.json`. Existing mutable compatibility paths were not misrepresented as immutable provenance.

## Fresh-Reel canonical E2E

The canonical public CLI was executed once against existing local media, with isolated input, media, data, output, and state roots. The successful run executed all seven stages:

| Stage | Result |
| --- | --- |
| ingest | success |
| analysis | success |
| transition policy | success |
| planning | success |
| profile | success |
| compile | success |
| publish | success |

It published exactly one disposable pending command:

- Command: `.pytest-tmp-step4-e2e-2/state/commands/pending/VIDEO_CLONER_PHASE6_TEXTPLUS_APPLICATION_V1_20261007T085312209Z_8d0d29d665e54ce699b07e8f655e0ef4.json`
- Command SHA-256: `f5bf4c6ae3014b6b902ae58c106e5f2a925571fa08fe116659d638709baa22f2`
- Queue run ID: `20261007T085312209Z_8d0d29d665e54ce699b07e8f655e0ef4`
- Pending queue count: `1`
- Resolve launched: no

The first clean attempt failed closed during planning because raw observations contained executable `whip_pan`. No publication or Resolve mutation occurred. The shared orchestration order was corrected so the canonical transition policy runs before planning. The second fresh invocation succeeded.

## Fresh-versus-accepted parity

Normalization was restricted to run IDs, timestamps, elapsed/runtime fields, disposable paths, and the hashes/identities necessarily derived from those paths. Behavioral values were not normalized.

| Artifact family | Comparison result |
| --- | --- |
| Shots | Exact SHA-256 match. |
| Transcript | Semantic match; only runtime and input/output paths differed. |
| Beat map | Semantic match; output path differed. |
| Motion | Semantic match; timestamps, paths, and runtime differed. |
| Raw transitions | Semantic match; timestamps, paths, and runtime differed. |
| Caption occlusion | All 724 raw differences were path/timing metadata; summary and events matched exactly. |
| Caption style | All 162 style events, five profiles, and event diagnostics matched exactly. Of 444 subtitle groups, 97 non-consumed `candidate_reason` diagnostic labels varied; resolved authority and downstream behavior were unchanged. |
| Merged analysis | Match after allowed path/time normalization except the same 97 non-consumed diagnostic labels. |
| Edit plan | Exact after allowed normalization. |
| Validated edit plan | Exact after allowed normalization. |
| Generic commands | Exact after allowed normalization. |
| Camera profile | Exact. |
| Caption grammar | Only source path differed. |
| Style profile | Behavioral content matched; source artifact paths/hashes reflected the isolated root. |
| Transition policy | Exact after allowed normalization. |
| FCPXML | Structural match; only asset UID/source values derived from disposable paths differed. Accepted size: 73,779 bytes; fresh size: 73,967 bytes. |
| Timeline manifest | Schema, contract, nodes, and producer matched; path/hash-derived identities differed. |
| Queue payload | Safety policy and operation matched after run/path/hash normalization. |

No substantive analysis, planning, camera, grammar, profile, transition, FCPXML, manifest, or queue-policy delta was found.

## Package and runtime smoke

Minimal editable installation was tested in an isolated Python 3.14 virtual environment with `pip install --no-deps -e .`. From outside the repository:

- `import video_cloner` succeeded.
- `video-cloner --help` succeeded.
- Paddle, Whisper models, GPU, Resolve, Ollama, and private media were not required for package/CLI startup.

Python 3.10.11 worker checks succeeded in the existing configured environments:

- Audio worker: `video_cloner`, transcription, and rhythm imports.
- OCR worker: `video_cloner`, caption-style, and caption-occlusion imports.
- The OCR environment emitted only its existing optional `ccache` warning.

CI now keeps one Python 3.14 focused core job and one Python 3.10 lightweight import job; no broad matrix was added.

## Public queue safety

Arbitrary module selection is not exposed by `video_cloner.pipeline.run()`, the CLI `run` command, or the public publisher. There is no public `module` parameter. The bounded timeline-import publisher internally selects:

```text
resolve_workspace/modules/video_cloner_phase6_textplus_application.py
```

An offline regression proves module-path injection is unavailable. The generated command also preserved fail-closed policies: target timeline must be absent; import is enabled; replacement, save, deletion, relink, and metadata mutation are disabled.

## Deselected safety test

The excluded historical test protected four properties: report SHA-256 integrity, repository containment, required absence of the target timeline before import, and zero mutation during preflight. These properties were moved into a self-contained temporary fixture with no private `.agent` dependency. The canonical current-path suite now reports 116 passed and zero deselections.

## Caller graph and exhaustive classification rules

`docs/repo_hygiene/CURRENT_PIPELINE_GRAPH.md` now describes the post-deletion graph. Caller inspection covered Python imports, subprocess strings, CLI commands, BAT/PowerShell, tests, GitHub workflow, config, current command documentation, dynamic module strings, queue directories, and installed bridge configuration.

The following ordered rules classify every tracked runtime source. The first matching rule wins; `UNKNOWN` is retained:

| Rule | Classification | Scope / reason |
| --- | --- | --- |
| 1 | `CANONICAL` | All `video_cloner/**/*.py`; public behavior is owned here. |
| 2 | `COMPATIBILITY_REQUIRED` | `scripts/install_vc_agent_live.py`, the three remaining root BAT infrastructure launchers, `resolve_workspace/VC_Run_Agent_Task.py`, `resolve_workspace/VC_Agent_Bridge.py`, and the frozen Phase 6 application module. |
| 3 | `DEFERRED_CAPABILITY_SOURCE` | Retained caption animation/font/opacity/stroke-shadow/lifecycle/occlusion, camera-transform, transition/Flash, and related Resolve sources whose complete accepted capability is not yet canonical. |
| 4 | `HISTORICAL_EVIDENCE_ONLY` | Reports, migration inventories, accepted artifacts, and tests that encode safety or behavioral knowledge but are not operator entry points. |
| 5 | `SUPERSEDED` | Deleted wrapper paths and the deleted superseded ownership/legacy-studio sources listed below. |
| 6 | `REPAIR_ONLY` | One-off repair/probe/diagnostic launchers with no current caller and with source behavior retained elsewhere; deleted in Wave 2. |
| 7 | `FAILED_EXPERIMENT` | Rejected probe launchers with no current caller; deleted in Wave 2. |
| 8 | `GENERATED` | `__pycache__`, pytest/benchmark scratch, browser evidence, and egg-info; ignored and physically removed when safe. |
| 9 | `UNKNOWN` | Any remaining `scripts/**` or non-frozen `resolve_workspace/**` file not matched above. It is intentionally not deleted without a future capability/caller proof. |

Important retained deferred sources include:

- Caption animation/lifecycle: `scripts/davinci/caption_animation_step_3C.py`, `scripts/davinci/caption_lifecycle_authority_step_3D.py`, and corresponding Resolve modules.
- Font/opacity/stroke-shadow: `scripts/standalone/video_cloner_font_inference.py`, `video_cloner_color_opacity.py`, `video_cloner_thickness_stroke.py`, font calibration/detection sources, and the Step 3B/3E Resolve sources.
- Camera transforms: motion/animation authority and current camera-profile coverage not yet proven equivalent to all historical live experiments.
- Transition/Flash: `advanced_transition_flash_*`, Phase 4C/5/6A modules, latest prepare/validate sources, and their tests.
- Occlusion/compositing: current analysis plus final-composition and baked-caption recovery sources whose live composition behavior is not in the canonical offline importer.

These retained files are recovery sources, not current operator commands. Keeping them prevents deletion of the Reel 2 learning while avoiding an in-tree archive copy.

## Source cleanup

Tracked source counts use `git ls-files` by major directory.

| Directory | Before | After | Delta |
| --- | ---: | ---: | ---: |
| `video_cloner/` | 34 | 34 | 0 |
| `scripts/` | 323 | 281 | -42 |
| `resolve_workspace/` | 91 | 91 | 0 |
| `tests/` | 172 | 176 | +4 |
| root runtime scripts | 4 | 3 | -1 |

Wave 1 deleted 25 files: one obsolete root media BAT and 24 analysis/planning/standalone/compiler/queue compatibility wrappers. Thirty-two tests were retargeted to canonical modules or public APIs.

Wave 2 deleted 18 additional stale runtime/operations files (5,740 lines), including:

- the two-file `scripts/davinci/archive(for studio)` legacy implementation;
- superseded source-text ownership v2 and its orphaned audit;
- an orphaned Step 5A diagnostic;
- obsolete caption geometry/fidelity audit and monitor tools;
- obsolete caption fill/position/source-geometry probe launchers;
- obsolete glyph-mask, read-only preflight, Flash-location, rollback, combined-validation, and idempotency prepare launchers.

Git history and the immutable recovery tag are the archive. No replacement archive directory was created.

Physical cleanup removed 49 top-level pytest/benchmark/browser/package-build scratch directories and 22 source-tree `__pycache__` directories. The successful isolated E2E directory was intentionally retained as bounded execution evidence. `*.egg-info/` was added to `.gitignore`.

## Resolve boundary

The following frozen files retained their pre-Step-4 Git object hashes and were not modified or deleted:

| File | Git object hash |
| --- | --- |
| `resolve_workspace/VC_Run_Agent_Task.py` | `873ada0103990254232e16bfdb4e6590a2d91f24` |
| `resolve_workspace/VC_Agent_Bridge.py` | `19b1c048ea8992bae419ad60abc826e339fd6032` |
| `resolve_workspace/modules/video_cloner_phase6_textplus_application.py` | `4ec39183aee74d1478ec811946e21b0137098644` |

Before deletion, `.agent/commands/pending` and `.agent/commands/running` contained zero active real commands. The installed bridge config lookup under the Blackmagic Design Workspace path returned not found, so no external installed launcher was inferred as a caller. No Resolve process was launched.

No Resolve modules were deleted in this step because several contain deferred capability or dynamic-import dependencies. This is intentional fail-closed behavior, not an unclassified deletion gap.

## Regression and CI evidence

- Canonical current-path regression after wrapper and stale-source deletion: `116 passed in 5.89s`; zero failures, errors, or deselections.
- GitHub Python 3.14 core-equivalent selection: `64 passed in 3.52s`.
- Python 3.10.11 audio and OCR worker import smokes: passed.
- Public pipeline/CLI tests cover generated run identity, manifest recording, full stage ordering, failure manifest behavior, isolated queue publication, and the absence of module injection.
- `git diff --check`: passed before commits.
- Dynamic caller audit found no executable current caller for the deleted Wave 2 files; active queue count was zero. Remaining basename mentions are historical schema/provenance labels, comments, or negative tests rather than import/subprocess/CLI edges.

A broader historical 345-test diagnostic was not used as the release gate: its failures were confined to absent ignored Reel 1/Reel 2 external evidence packages and historical suites outside the canonical product path. The current-path and CI-equivalent suites are self-contained and green.

## Remaining risk

The only material boundary is live Resolve machine acceptance. The published command was not executed, so timeline persistence, idempotency, and visual fidelity are not claimed. Those belong to the explicit Step 5 authority/handoff workflow and must use the frozen Workspace bridge with matching run evidence.

## Next action

Begin Step 5/5: clean GitHub authority and complete project handoff, while treating live Resolve application as a separately authorized machine-acceptance operation.

`PASS_REPOSITORY_CLEANUP_READY_FOR_FINAL_AUTHORITY`
