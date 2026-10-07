# Canonical Project State

Updated: 2026-10-07 (Step 5/5)

## Objective

Turn a source video into a reproducible analysis, edit plan, caption/style profile, FCPXML timeline, and bounded Resolve import command while preserving run identity and artifact provenance.

## Current win condition

The current repository is the canonical software authority for offline generation and queue publication. The working tree is clean, the canonical test gates are green, and deferred capabilities are indexed. Live Resolve acceptance remains a separate product-development gate.

## Canonical entry point

- CLI: `video-cloner run`
- Python: `from video_cloner.pipeline import run`
- Package owner: `video_cloner/`
- Install metadata: `pyproject.toml` (`video-cloner = video_cloner.cli:main`)

Normal operation does not require BAT files, PowerShell orchestration, N8N, historical Step/Phase launchers, or arbitrary module filenames.

## Canonical package map

| Concern | Owner |
|---|---|
| Configuration and identities | `video_cloner.config`, `video_cloner.contracts` |
| Ingest/media preparation | `video_cloner.ingestion` |
| Analysis | `video_cloner.analysis` |
| Transition policy | `video_cloner.transition_policy` |
| Planning | `video_cloner.planning` |
| Camera/caption/style profiles | `video_cloner.camera`, `video_cloner.caption_grammar`, `video_cloner.profiles` |
| FCPXML | `video_cloner.resolve.fcpxml` |
| Queue publication | `video_cloner.resolve.queue` |
| Full workflow and manifests | `video_cloner.pipeline` |

## Configuration model

`RuntimeConfig.load(project_root, config_path=None)` starts from repository-relative `data/`, `input/`, `media/`, and `.agent/` roots, then applies JSON config, `VIDEO_CLONER_*` environment variables, and explicit overrides. Public runtime identity redacts endpoint credentials and reports only whether cookies are configured.

## Multi-runtime model

The core package runs on Python 3.10–3.14. `RuntimeConfig` can point audio, OCR, rhythm, Resolve, FFmpeg, and `yt-dlp` to separate workers/tools. Python 3.10 audio and OCR import smokes pass. No virtual environment is committed.

## Run and manifest model

`pipeline.run()` creates a run ID, executes ingest → analysis → transition policy → planning → profile → compile, publishes one bounded command, and atomically writes `state/runs/<run_id>/manifest.json`. `run_offline()` stops before publication. A zero exit code is not the acceptance criterion by itself; stage statuses, artifacts, hashes, and the manifest are the evidence.

## Resolve boundary

The repository owns command construction and the frozen bridge contract. Installed Workspace launchers in the portable Resolve tree and `%APPDATA%` both point to this repository root and match the frozen launcher/bridge hashes. `RESOLVE_LAUNCHER_READY = YES`.

Live machine acceptance is **NOT ACCEPTED**: previous bridge runs failed post-import identity/target-title validation. Do not infer timeline persistence or visual fidelity from a created timeline.

## Test and CI authority

- canonical regression: 116 passed;
- CI-equivalent core selection: 64 passed;
- Python 3.10 worker imports: passed;
- clean disposable package install, public import, `video-cloner --help`, and `video-cloner run --help`: passed;
- `git diff --check`: passed.

The workflow authority is [`.github/workflows/offline-core.yml`](../.github/workflows/offline-core.yml).

## Deferred capabilities

The exact retained noncanonical closure is [`repo_hygiene/DEFERRED_CAPABILITIES_INDEX.md`](repo_hygiene/DEFERRED_CAPABILITIES_INDEX.md). It covers advanced caption animation/lifecycle, font inference/application, opacity, stroke/shadow, camera transforms, Flash transitions, and occlusion/compositing. These are future source/evidence, not current entry points.

## Known product failures / unresolved work

The next unresolved product issue is live Resolve application acceptance: prove correct target identity, persistent readback, idempotency, and human visual fidelity using one matching run ID. Do not rewrite the bridge or canonical pipeline as a cleanup response.

## Dead/deleted path policy

Deleted Step/Phase scripts are historical. Do not recreate them because an old report, manifest, or test name mentions them. Git history and the recovery tag are the archive. Only the explicitly indexed deferred closure and compatibility files remain in the working tree.

## Recovery tag

`video-cloner-pre-hygiene-snapshot-20261007` is an annotated immutable recovery tag pointing to commit `f728d4ae1073a2b37f58e5b06a77ed6b97ca0605`. It is the pre-hygiene archive, not the current authority.

## Current next move

Resolve the remote authority divergence through normal repository policy, then perform the live Resolve product gate. The canonical cleanup tag must point at the final clean authority commit; it must never be presented as proof that all video-cloning capabilities are complete.
