# Current Pipeline Graph

Audit date: 2026-10-07. Mode: read-only. Production code was not changed.

## Authority boundary

The fresh `DZatr0EJt4B` run proves the offline pipeline through FCPXML, manifest, and queue publication. It does **not** prove a clean Resolve application: the two bridge reports at `20261006T054753181Z_...` and `20261007T050028174Z_...` both have `ok: false` (`import_returned_identity` and `target_title`). A timeline may have been created before validation failed, but that is not a successful bridge result.

## Execution graph

```text
ENTRY
run_video_cloner_media_prep.bat
  -> scripts/standalone/video_cloner_media_prep.py
  -> yt-dlp / ffmpeg [subprocess]
  -> input/DZatr0EJt4B.mp4
  -> media/DZatr0EJt4B.wav
  -> media/DZatr0EJt4B_proxy.mp4

ANALYSIS
scripts/standalone/video_cloner_analysis.py
  => scripts/analysis/detect_cuts.py [fixed filename, subprocess]
  => scripts/analysis/transcribe.py [fixed filename, subprocess]
  => scripts/analysis/detect_rhythm_beats.py [fixed filename, subprocess]
  => scripts/analysis/detect_caption_style.py [fixed filename, subprocess]
  => scripts/analysis/detect_motion_speed.py [fixed filename, subprocess]
  => scripts/analysis/detect_transitions_proxy.py [fixed filename, subprocess]
  => scripts/analysis/detect_caption_occlusion.py [fixed filename, subprocess]
  -> data/DZatr0EJt4B/analysis/DZatr0EJt4B_{shots,transcript,beatmap,
     caption_style,motion,transitions,caption_occlusion}.json
  -> data/DZatr0EJt4B/analysis/DZatr0EJt4B_analysis_run.json

PLANNING
scripts/standalone/video_cloner_plan.py
  => scripts/planning/merge_analysis.py [fixed filename, subprocess]
  => scripts/planning/plan_edit.py [fixed filename, subprocess]
  => scripts/planning/validate_edit_plan.py [fixed filename, subprocess]
  => scripts/planning/compile_generic_edit.py [fixed filename, subprocess]
  -> data/DZatr0EJt4B/analysis/DZatr0EJt4B_analysis.json
  -> data/DZatr0EJt4B/planning/DZatr0EJt4B_edit_plan.json
  -> data/DZatr0EJt4B/planning/DZatr0EJt4B_validated_edit_plan.json
  -> data/DZatr0EJt4B/planning/DZatr0EJt4B_generic_edit_commands.json
  -> data/DZatr0EJt4B/planning/DZatr0EJt4B_planning_run.json

PROFILE SIDECARS (manual CLIs; not called by the planning orchestrator)
scripts/analysis/build_camera_style_profile.py
  -> DZatr0EJt4B_camera_style_profile.json
scripts/analysis/build_caption_style_grammar_generic.py
  -> DZatr0EJt4B_caption_style_grammar.json
scripts/analysis/build_style_profile_mvp_generic.py
  -> DZatr0EJt4B_style_profile_mvp.json
scripts/analysis/compare_style_profiles_mvp.py
  -> DZatr0EJt4B_vs_DcJRJtUKScu_style_comparison.{json,md}

TRANSITION COMPATIBILITY
scripts/standalone/video_cloner_mvp_transition_filter.py [manual CLI]
  -> DZatr0EJt4B_transitions_mvp_resolve.json
  -> consumed by the subsequent planning run as its transition authority

TIMELINE COMPILATION
scripts/davinci/compile_davinci_textplus_fcpxml.py [direct CLI]
  -> DZatr0EJt4B_mvp_timeline.fcpxml
  -> DZatr0EJt4B_mvp_timeline_report.json

QUEUE PUBLICATION
scripts/davinci/prepare_video_cloner_fresh_mvp_timeline.py
  -> validates compiler report and artifacts
  -> DZatr0EJt4B_mvp_timeline_import_report.json
  -> DZatr0EJt4B_mvp_timeline_manifest.json
  -> .agent/reports/<task>/<run>/import_command.json
  -> .agent/commands/pending/<task>_<run>.json

RESOLVE
installed VC_Run_Agent_Task.py
  => repository resolve_workspace/VC_Run_Agent_Task.py [installed launcher copy]
  => resolve_workspace/VC_Agent_Bridge.py [importlib dynamic load]
  => command["module"] [validated repository-relative path, importlib dynamic load]
  => resolve_workspace/modules/video_cloner_phase6_textplus_application.py
  => Resolve ImportTimelineFromFile / timeline inspection
  -> .agent/commands/{completed|failed}/...
  -> .agent/reports/<task>/<run>/{status,report,run}.json/log
```

`=>` marks an executable edge. The Resolve command-to-module edge is dynamic and is the main deletion hazard.

## Proven artifact facts

- Analysis report: `status: success`, seven analyzers generated, zero failed/blocked.
- Planning report: `status: success`, four stages generated; `resolve_invoked: false` and `timeline_mutated: false`.
- Compiler report: `success: true`, version `davinci_textplus_fcpxml_compiler_v1_6_visual_lifecycle`.
- MVP manifest: valid `video_cloner.standalone_phase5_manifest.v1` artifact set.
- Resolve bridge: two terminal failed commands. No completed Phase 6 command for `DZatr0EJt4B` was found. The timeline may exist because import/mutation preceded post-import validation, but the machine transaction is unaccepted.

## Provenance warning

`DZatr0EJt4B_style_profile_mvp.json` records hashes for an earlier `analysis.json` and `edit_plan.json`; both files were later overwritten by the successful planning run. The profile is useful evidence but is not currently reproducible from the files at those paths without re-running it. The profile sidecars are also not consumed by the current timeline compiler path.

## Actual entry points

- Import/media preparation: `run_video_cloner_media_prep.bat`.
- Analysis: `python -m scripts.standalone.video_cloner_analysis` (no root launcher).
- Planning: `python -m scripts.standalone.video_cloner_plan` (no root launcher).
- Profiles/filter/compiler/queue publisher: separate direct Python CLIs.
- Resolve: Workspace launcher `VC_Run_Agent_Task.py`; `run_agent_task.bat` executes the bridge outside Resolve and is not equivalent to the Workspace launcher.
