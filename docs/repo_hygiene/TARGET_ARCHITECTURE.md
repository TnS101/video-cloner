# Target Architecture

The target should be one package plus two thin entry points. Do not merge behavior merely to hit a file count.

```text
video_cloner/
  __init__.py
  config.py          # runtime configuration, RunContext, paths, identities
  contracts.py       # schemas, manifests, artifact identity and validation
  ingestion.py       # URL/local acquisition, WAV, proxy
  analysis.py        # seven-analyzer DAG and contracts
  planning.py        # merge -> plan -> validate -> generic commands
  captions.py        # text authority, lifecycle, style grammar, lane/style normalization
  camera.py          # camera profile
  transitions.py     # observations, MVP compatibility, executable authority
  profiles.py        # style profile build + comparison/reporting
  fcpxml.py          # one compiler and validation contract
  pipeline.py        # desired-state orchestration; no Resolve import
  cli.py             # one discoverable command surface

resolve_workspace/
  VC_Run_Agent_Task.py       # installed compatibility launcher only
  VC_Agent_Bridge.py         # queue ownership and dynamic dispatch only
  modules/
    timeline_import.py       # one generic import/validate implementation
```

Estimated primary runtime source count: roughly 15 files, not a hard target. Keep capability boundaries cohesive; do not create god-files to reach a count. Optional reporting commands should call package functions, not form separate production pipelines.

## Ownership

| Question | One future owner |
| --- | --- |
| Where does Video Cloner start? | `video_cloner.cli` |
| What imports a Reel? | `video_cloner.ingestion` |
| What runs analysis? | `video_cloner.analysis` |
| What defines cuts and edit commands? | `video_cloner.planning` |
| What defines transitions? | `video_cloner.transitions` |
| What defines camera behavior? | `video_cloner.camera` |
| What defines captions? | `video_cloner.captions` |
| What builds/compares style profiles? | `video_cloner.profiles` |
| What builds the offline timeline? | `video_cloner.fcpxml` |
| Who owns schemas/manifests/artifact identity? | `video_cloner.contracts` |
| What runs inside Resolve? | `VC_Agent_Bridge.py` -> `modules/timeline_import.py` |

## Constraints

- Resolve receives a repository-relative allowlisted module path through the existing queue protocol.
- New production commands should use an explicit operation registry or bounded command type; arbitrary filename-based dispatch remains compatibility-only.
- The bridge owns claim/move/status/report behavior; the Resolve module owns only authenticated timeline work.
- Profiles are generated before consumers and use immutable/hash-addressed inputs; no artifact is silently overwritten beneath a recorded hash.
- Reel IDs, project names, timeline names, and fixture counts are inputs, never module constants.
- Historical scripts and reports cannot be imported by the production package.
- Unsupported transitions remain explicit observations or placeholders; they are not silently promoted.

## Migration mapping

- `video_cloner_media_prep.py` -> `config.py` + `ingestion.py`.
- `video_cloner_analysis.py` and seven analyzers -> `analysis.py` with analyzer functions retained behind one DAG.
- `video_cloner_plan.py` and four planning scripts -> `planning.py`.
- generic profile/filter scripts -> `camera.py`, `captions.py`, `transitions.py`, `profiles.py`.
- compiler plus standalone wrappers -> `fcpxml.py` and `captions.py`.
- fresh timeline prepare script -> `pipeline.py` queue-publish step.
- Phase 6 module -> `modules/timeline_import.py` only after current failure semantics are resolved.
