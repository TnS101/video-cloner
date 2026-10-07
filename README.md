# Video Cloner

Video Cloner is an offline-first video analysis and timeline-generation package. It analyzes a local video or URL, builds a deterministic edit plan and caption/style profiles, compiles FCPXML, and publishes one bounded Resolve command when a Resolve project/timeline identity is supplied.

## Current status

The canonical offline workflow and public Python API are implemented and regression-tested. Queue publication is proven. Live DaVinci Resolve machine acceptance is **not** accepted: the frozen bridge has previously created/inspected timelines but failed post-import identity validation. That is the next product-development gate, not a repository-hygiene failure.

## Installation

From a fresh checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

The supported command is installed by the `project.scripts` entry point in `pyproject.toml`. Optional worker environments may be configured for audio, OCR, rhythm, FFmpeg, and `yt-dlp` through `RuntimeConfig` or `VIDEO_CLONER_*` variables.

## One-command operation

```powershell
video-cloner run `
  --project-root . `
  --local-video .\input\source.mp4 `
  --project VideoCloner `
  --target-timeline VIDEO_CLONER_SOURCE_MVP_V1
```

The command runs ingest, analysis, transition policy, planning, profiling, FCPXML compilation, and one bounded queue publication. It does not launch Resolve itself.

Use `video-cloner run --help` for all options. Use `video-cloner run-offline` to stop after compilation without queue publication.

## Python API

```python
from pathlib import Path

from video_cloner.config import RuntimeConfig
from video_cloner.pipeline import run

config = RuntimeConfig.load(".")
result = run(
    Path("input/source.mp4"),
    config,
    project="VideoCloner",
    target_timeline="VIDEO_CLONER_SOURCE_MVP_V1",
)
```

The canonical package starts in `video_cloner.pipeline`; `video_cloner.cli` is only the console adapter.

## Current pipeline

```text
ingest/reuse
  → analyze
  → transition policy
  → plan
  → profile
  → compile FCPXML
  → publish one bounded Resolve command
  → state/runs/<run_id>/manifest.json
```

Every run has a run ID, configuration/runtime identity, stage statuses, artifact hashes, and an atomic manifest. `run_offline()` uses the same flow through compilation and omits publication.

## Resolve workspace step

Resolve is an external boundary. The installed Workspace launcher loads the repository bridge from the configured repository root:

```text
installed VC_Run_Agent_Task.py
  → resolve_workspace/VC_Run_Agent_Task.py
  → resolve_workspace/VC_Agent_Bridge.py
  → frozen Phase 6 application module
```

The launcher and bridge are frozen compatibility files. Do not edit timelines, projects, caption behavior, or the Phase 6 implementation as part of repository cleanup.

## Supported now

- deterministic local/URL ingest and reusable run context;
- audio/OCR/motion/caption/transition analysis through configured workers;
- canonical planning, profiling, FCPXML compilation, and bounded queue publication;
- run manifests and artifact hashes;
- Python 3.10 worker import compatibility;
- public CLI and Python API.

## Known limitations

- live Resolve import/persistence/idempotency and visual fidelity are not accepted;
- a flattened source cannot prove every editor transform or occlusion cause;
- the public pipeline intentionally does not launch Resolve;
- optional external tools and worker environments must be installed/configured by the operator.

## Deferred capabilities

Advanced caption lifecycle/animation, font application, opacity, stroke/shadow, camera editor transforms, Flash execution, and occlusion/compositing sources remain explicitly indexed as deferred material. See [`docs/repo_hygiene/DEFERRED_CAPABILITIES_INDEX.md`](docs/repo_hygiene/DEFERRED_CAPABILITIES_INDEX.md). Retention does not make those sources current entry points.

## Development and tests

```powershell
python -m pytest -q `
  tests/test_video_cloner_config_contracts.py `
  tests/test_video_cloner_pipeline_cli.py `
  tests/test_standalone_media_prep.py `
  tests/test_standalone_analysis.py `
  tests/test_standalone_plan.py
```

The full canonical regression selection is recorded in [`docs/repo_hygiene/CANONICAL_REGRESSION_BASELINE.md`](docs/repo_hygiene/CANONICAL_REGRESSION_BASELINE.md). CI authority is [`.github/workflows/offline-core.yml`](.github/workflows/offline-core.yml).

## Architecture pointers

- [`video_cloner/pipeline.py`](video_cloner/pipeline.py) — orchestration and manifests
- [`video_cloner/config.py`](video_cloner/config.py) — configuration and worker paths
- [`video_cloner/analysis/`](video_cloner/analysis/) — analysis capabilities
- [`video_cloner/planning/`](video_cloner/planning/) — plan construction
- [`video_cloner/resolve/`](video_cloner/resolve/) — FCPXML and queue boundary
- [`docs/repo_hygiene/CURRENT_PIPELINE_GRAPH.md`](docs/repo_hygiene/CURRENT_PIPELINE_GRAPH.md) — ownership graph
- [`docs/CANONICAL_PROJECT_STATE.md`](docs/CANONICAL_PROJECT_STATE.md) — onboarding authority map
- [`docs/VIDEO_CLONER_FINAL_HANDOFF.md`](docs/VIDEO_CLONER_FINAL_HANDOFF.md) — decision-ready handoff
