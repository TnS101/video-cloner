# Current Pipeline Graph

Updated: 2026-10-07 after Step 4 wrapper retirement.

## Canonical operator path

```text
video-cloner run --local-video <path> --project <Resolve project> --target-timeline <timeline>
  -> video_cloner.cli.main()
  -> video_cloner.pipeline.run()
     -> ingest/reuse
     -> AnalysisOrchestrator.run()
     -> filter_transitions()
     -> PlanningOrchestrator.run()
     -> profile()
     -> compile() -> FCPXML + compiler report
     -> publish() -> one bounded pending Resolve command
  -> state/runs/<run_id>/manifest.json

Resolve Workspace action, only when live application is desired
  -> installed VC_Run_Agent_Task.py
  -> repository resolve_workspace/VC_Run_Agent_Task.py
  -> resolve_workspace/VC_Agent_Bridge.py
  -> resolve_workspace/modules/video_cloner_phase6_textplus_application.py
```

`video_cloner.pipeline.run_offline()` is the same flow through compilation without queue publication. Neither public entry point launches Resolve.

## Ownership

| Behavior | Canonical owner |
| --- | --- |
| Configuration, input identity, run identity | `video_cloner.config`, `video_cloner.contracts` |
| Media preparation | `video_cloner.ingestion.media` |
| Analysis | `video_cloner.analysis.*` |
| Transition policy | `video_cloner.transition_policy` |
| Planning | `video_cloner.planning.*` |
| Camera/caption/style profiles | `video_cloner.camera`, `video_cloner.caption_grammar`, `video_cloner.profiles` |
| FCPXML compilation | `video_cloner.resolve.fcpxml` |
| Bounded queue publication | `video_cloner.resolve.queue` |
| Full orchestration and run manifest | `video_cloner.pipeline` |

The retired `scripts/analysis`, `scripts/planning`, `scripts/standalone`, compiler, media BAT, and queue-preparation wrappers are not current entry points.

## Queue boundary

The public API exposes a timeline-import operation, not a module filename. The queue publisher maps internally to the frozen module `resolve_workspace/modules/video_cloner_phase6_textplus_application.py`. Pending/running queues were empty before stale deletion. Completed and failed command records remain evidence, not current callers.

## Deferred capability boundary

Historical caption animation, font, opacity, stroke/shadow, lifecycle, camera-transform, transition/Flash, and occlusion sources remain outside the canonical operator graph. They are intentionally retained as `DEFERRED_CAPABILITY_SOURCE` until equivalent canonical behavior and tests exist. Their prepare/probe launchers are not automatically active merely because the source remains.

## Machine-acceptance boundary

Step 4 proves generation and safe queue publication only. It does not claim a successful live Resolve application. Live application remains an explicit Workspace action and must be accepted using a matching bridge run ID and report.
