# Target Architecture

The target is one obvious package with one CLI, one application/pipeline API, and one Resolve bridge route. File count is a soft outcome of cohesive ownership, not a compression target. A clean 20–30-module runtime package is preferable to a few multi-thousand-line god-files.

```text
video_cloner/
  __init__.py
  config.py             # validated runtime inputs and paths
  contracts.py          # schemas, manifests, artifact identity, validation
  pipeline.py           # public application API; no Resolve import
  cli.py                # one discoverable CLI over pipeline.py

  ingestion/
    pipeline.py
    media.py

  analysis/
    pipeline.py         # seven-analyzer DAG
    cuts.py
    transcription.py
    rhythm.py
    caption_style.py
    motion.py
    transitions.py
    caption_occlusion.py

  planning/
    pipeline.py
    merge.py
    plan.py
    validate.py
    compile.py

  captions/
    grammar.py
    lifecycle.py
    textplus.py
    style.py

  camera.py
  transition_policy.py
  profiles.py

  resolve/
    fcpxml.py
    queue.py

resolve_workspace/
  VC_Run_Agent_Task.py   # installed compatibility launcher only
  VC_Agent_Bridge.py     # one queue/dispatch route
  modules/
    timeline_import.py   # one generic import/validate implementation
```

Exact boundaries should follow real cohesion during migration. Algorithmically distinct cuts, transcription, rhythm, caption CV, motion, transition detection, and caption occlusion remain separate internal modules. Caption grammar, lifecycle, Text+, and style likewise remain separable rather than accumulating in one giant `captions.py`. Do not create empty scaffolding ahead of migrated behavior.

## Public boundaries

| Consumer | Supported entry point |
| --- | --- |
| Operator / automation | `video_cloner.cli` |
| Python caller and future local web app | `video_cloner.pipeline` application service |
| Resolve | `VC_Agent_Bridge.py` -> allowlisted `modules/timeline_import.py` operation |

The future web boundary is `UI -> video_cloner.pipeline -> capability modules`. It must not become `UI -> PowerShell -> BAT -> arbitrary standalone scripts`. CLI and UI are thin adapters over the same Python API.

## Ownership

| Question | One future owner |
| --- | --- |
| Runtime inputs, roots, tools, and model selection | `video_cloner.config` |
| Schemas, manifests, and artifact identity | `video_cloner.contracts` |
| End-to-end desired-state orchestration | `video_cloner.pipeline` |
| Media acquisition, WAV, and proxy | `video_cloner.ingestion` |
| Analyzer DAG and analyzer capabilities | `video_cloner.analysis` |
| Merge, plan, validate, and generic commands | `video_cloner.planning` |
| Caption grammar/lifecycle/style/Text+ | `video_cloner.captions` |
| Camera profile | `video_cloner.camera` |
| Transition observation and execution policy | `video_cloner.transition_policy` |
| Style profiles and comparison | `video_cloner.profiles` |
| Offline FCPXML | `video_cloner.resolve.fcpxml` |
| Queue publication | `video_cloner.resolve.queue` |
| Live Resolve mutation | bridge -> `modules/timeline_import.py` |

## Configuration boundary

The Resolve project name, target/protected timeline name or identity, Reel ID, repository/input/media/data/state roots, model names, service endpoints, and runtime executables are validated configuration or invocation inputs. `New Project 1`, machine-local `C:/Users/...` paths, and historical timeline IDs may remain in tests and recovery scripts, but cannot become production constants.

Step 3 should introduce one configuration model consumed by both CLI and pipeline API. Compatibility adapters may translate existing environment variables and runtime JSON into that model. Queue/report state roots must also become configuration rather than making ignored `.agent` history a prerequisite.

## Constraints

- New commands use an explicit operation registry or bounded command type; arbitrary filename dispatch remains compatibility-only.
- The bridge owns claim/move/status/report behavior; the Resolve module owns authenticated timeline work only.
- Profiles use immutable/hash-addressed inputs; no artifact is silently overwritten beneath a recorded hash.
- Historical scripts/configs are evidence, not imports of the production package.
- Unsupported transitions remain explicit observations or placeholders.
- Resolve consolidation waits for the current validation failure and external-fixture safety contract to be closed.

## Migration mapping

- Media prep -> `config.py` plus `ingestion/`.
- Analysis orchestrator plus seven analyzers -> `analysis/pipeline.py` plus cohesive analyzer modules.
- Planning orchestrator plus four stages -> `planning/`.
- Generic profiles/filtering -> `camera.py`, `captions/`, `transition_policy.py`, and `profiles.py`.
- FCPXML compiler -> `resolve/fcpxml.py`; fresh timeline publisher -> `resolve/queue.py`.
- Phase 6 implementation -> one allowlisted `modules/timeline_import.py` only after its failure semantics are resolved.
