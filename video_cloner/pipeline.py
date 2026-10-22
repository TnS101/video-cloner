"""Canonical orchestration API for the offline Video Cloner pipeline."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .analysis.pipeline import AnalysisOrchestrator
from .config import RuntimeConfig, build_run_context
from .contracts import ArtifactIdentity, InputSpec, RunContext, new_run_id
from .ingestion.media import ingest as _ingest
from .planning.pipeline import PlanningOrchestrator


def context(source: str | Path | InputSpec, config: RuntimeConfig, run_id: str | None = None) -> RunContext:
    spec = source if isinstance(source, InputSpec) else InputSpec.from_url(source) if str(source).startswith(("http://", "https://")) else InputSpec.from_local(source)
    return build_run_context(spec, config, run_id=run_id)


def ingest(source: str | Path | InputSpec, config: RuntimeConfig, *, force: bool = False, run_id: str | None = None) -> dict[str, object]:
    spec = source if isinstance(source, InputSpec) else context(source, config, run_id).input_spec
    return _ingest(spec, config, force=force, run_id=run_id)


def analyze(run: RunContext, *, force: bool = False, force_analyzers: Iterable[str] = ()) -> dict[str, object]:
    return AnalysisOrchestrator(run).run(force=force, force_analyzers=force_analyzers)


def plan(run: RunContext, transition_authority: str | Path, *, force: bool = False, force_stages: Iterable[str] = ()) -> dict[str, object]:
    return PlanningOrchestrator(run, transition_authority).run(force=force, force_stages=force_stages)


def filter_transitions(run: RunContext) -> str:
    """Apply the canonical bounded transition policy required by planning."""
    from .transition_policy import filter_mvp_transitions

    source = run.analysis_dir / f"{run.video_id}_transitions.json"
    output = run.analysis_dir / f"{run.video_id}_transitions_mvp_resolve.json"
    filtered = filter_mvp_transitions(json.loads(source.read_text(encoding="utf-8-sig")))
    output.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(output)


def profile(run: RunContext, *, samples_per_shot: int = 5) -> dict[str, str]:
    """Build the current camera, caption, style, and transition profile artifacts."""
    from .camera import build_camera_style_profile, collect_face_observations
    from .caption_grammar import build_grammar
    from .profiles import build_profile

    reel = run.video_id
    analysis = run.analysis_dir
    planning = run.planning_dir
    paths = {
        "camera": analysis / f"{reel}_camera_style_profile.json",
        "caption_grammar": analysis / f"{reel}_caption_style_grammar.json",
        "font_candidates": analysis / f"{reel}_font_candidates.json",
        "style_profile": analysis / f"{reel}_style_profile_mvp.json",
        "transitions": analysis / f"{reel}_transitions_mvp_resolve.json",
    }
    motion_path = analysis / f"{reel}_motion.json"
    transition_path = analysis / f"{reel}_transitions.json"
    motion = json.loads(motion_path.read_text(encoding="utf-8-sig"))
    segments = motion.get("segments") if isinstance(motion.get("segments"), list) else []
    camera = build_camera_style_profile(motion, collect_face_observations(run.source_video_path, segments, max(1, samples_per_shot)))
    paths["camera"].write_text(json.dumps(camera, indent=2) + "\n", encoding="utf-8")
    grammar = build_grammar(analysis / f"{reel}_caption_style.json", reel)
    paths["caption_grammar"].write_text(json.dumps(grammar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    style = build_profile(
        analysis / f"{reel}_analysis.json",
        planning / f"{reel}_edit_plan.json",
        transition_path,
        paths["camera"],
        paths["caption_grammar"],
        reel,
    )
    paths["style_profile"].write_text(json.dumps(style, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["transitions"] = Path(filter_transitions(run))
    return {name: str(path) for name, path in paths.items()}


def compile(
    generic: str | Path,
    caption_style: str | Path,
    output_fcpxml: str | Path,
    report: str | Path,
    *,
    options: Mapping[str, Any] | None = None,
) -> int:
    """Compile FCPXML through the proven compiler without importing Resolve."""
    selected = dict(options or {})
    lifecycle = selected.get("caption_lifecycle_plan")
    if lifecycle is not None:
        from .captions.fcpxml import compile_fcpxml

        compile_fcpxml(
            generic_path=generic,
            output_fcpxml=output_fcpxml,
            report_path=report,
            video_path=selected.get("video"),
            timeline_name=selected.get("timeline_name"),
            caption_style_path=caption_style,
            caption_lifecycle_path=lifecycle,
            audio_path=selected.get("audio"),
        )
        return 0

    from .resolve.fcpxml import main

    argv = ["--generic", str(generic), "--caption-style", str(caption_style), "--output-fcpxml", str(output_fcpxml), "--report", str(report)]
    for name, value in selected.items():
        if value is None:
            continue
        argv.extend((f"--{name.replace('_', '-')}", str(value).lower() if isinstance(value, bool) else str(value)))
    return main(argv)


def publish(
    config: RuntimeConfig,
    *,
    generic: str | Path,
    proxy: str | Path,
    caption_style: str | Path,
    audio: str | Path,
    fcpxml: str | Path,
    compiler_report: str | Path,
    editing_dna: str | Path | None = None,
    project: str | None = None,
    target_timeline: str | None = None,
) -> dict[str, Any]:
    """Publish one command to the frozen Resolve bridge queue contract."""
    from .resolve.queue import build_package, publish as publish_command

    project_name = project or config.resolve_project_name
    target = target_timeline or config.target_timeline
    if not project_name or not target:
        raise ValueError("Resolve project and target timeline identities are required")
    manifest, contract = build_package(
        config.project_root, Path(generic), Path(proxy), Path(caption_style), Path(audio), Path(fcpxml), Path(compiler_report), target,
        Path(editing_dna) if editing_dna else None,
    )
    return publish_command(config.project_root, manifest, contract, project_name, target, config.state_root)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _artifact_inventory(run: RunContext) -> list[dict[str, object]]:
    paths = {run.source_video_path, run.wav_path, run.proxy_path}
    if run.video_data_root.is_dir():
        paths.update(path for path in run.video_data_root.rglob("*") if path.is_file())
    return [ArtifactIdentity.from_path(path).as_dict() for path in sorted(paths) if path.is_file()]


def _write_manifest(run: RunContext, result: Mapping[str, object]) -> Path:
    assert run.run_id is not None
    path = run.config.state_root / "runs" / run.run_id / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def run_offline(
    run: RunContext,
    transition_authority: str | Path | None = None,
    *,
    force: bool = False,
    samples_per_shot: int = 5,
    target_timeline: str | None = None,
) -> dict[str, object]:
    """Run ingestion through offline FCPXML compilation without publishing."""
    if run.run_id is None:
        run = replace(run, run_id=new_run_id(run.video_id))
    started = _utc_now()
    reel = run.video_id
    transitions = Path(transition_authority) if transition_authority else run.analysis_dir / f"{reel}_transitions_mvp_resolve.json"
    timeline = target_timeline or run.config.target_timeline or f"VIDEO_CLONER_{reel}_MVP_V1"
    fcpxml = run.davinci_dir / f"{reel}_mvp_timeline.fcpxml"
    compiler_report = run.davinci_dir / f"{reel}_mvp_timeline_report.json"
    stages: dict[str, object] = {}
    result: dict[str, object] = {
        "schema": "video_cloner.canonical_run.v1",
        "run_id": run.run_id,
        "video_id": reel,
        "started_at_utc": started,
        "configuration_identity": run.config.identity(),
        "runtime_identity": run.config.public_runtime(),
        "stages": stages,
        "status": "running",
    }
    try:
        try:
            ingestion = ingest(run.input_spec, run.config, force=force, run_id=run.run_id)
        except Exception as error:
            stages["ingest"] = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
            raise
        stages["ingest"] = {"status": "success", "result": ingestion}
        result["source"] = ArtifactIdentity.from_path(run.source_video_path).as_dict()
        stages["analysis"] = {"status": "success", "result": analyze(run, force=force)}
        stages["transition_policy"] = {"status": "success", "output": filter_transitions(run)}
        stages["planning"] = {"status": "success", "result": plan(run, transitions, force=force)}
        stages["profile"] = {"status": "success", "result": profile(run, samples_per_shot=samples_per_shot)}
        code = compile(
            run.planning_dir / f"{reel}_generic_edit_commands.json",
            run.analysis_dir / f"{reel}_caption_style.json",
            fcpxml,
            compiler_report,
            options={
                "source": "subtitle_clips",
                "timeline_name": timeline,
                "timeline_mode": "full_timeline",
                "video": run.proxy_path,
                "audio": run.wav_path,
                "include_transitions": False,
                "transition_mode": "none",
                "position_mode": "detected_fcpx",
                "caption_lifecycle_plan": run.analysis_dir / f"{reel}_caption_lifecycle_authority.json",
            },
        )
        if code:
            raise RuntimeError(f"FCPXML compiler exited with code {code}")
        stages["compile"] = {"status": "success", "fcpxml": str(fcpxml), "report": str(compiler_report)}
        result.update(status="success", finished_at_utc=_utc_now(), artifacts=_artifact_inventory(run))
    except Exception as error:
        result.update(status="failed", finished_at_utc=_utc_now(), error=f"{type(error).__name__}: {error}", artifacts=_artifact_inventory(run))
        result["manifest_path"] = str(_write_manifest(run, result))
        raise
    result["manifest_path"] = str(_write_manifest(run, result))
    return result


def run(
    source: str | Path | InputSpec,
    config: RuntimeConfig,
    *,
    run_id: str | None = None,
    force: bool = False,
    samples_per_shot: int = 5,
    project: str | None = None,
    target_timeline: str | None = None,
) -> dict[str, object]:
    """Run the full canonical workflow and publish one bounded Resolve import command."""
    spec = source if isinstance(source, InputSpec) else InputSpec.from_url(source) if str(source).startswith(("http://", "https://")) else InputSpec.from_local(source)
    run_context = context(spec, config, run_id or new_run_id(spec.video_id))
    result = run_offline(run_context, force=force, samples_per_shot=samples_per_shot, target_timeline=target_timeline)
    reel = run_context.video_id
    stages = result["stages"]
    assert isinstance(stages, dict)
    try:
        receipt = publish(
            config,
            generic=run_context.planning_dir / f"{reel}_generic_edit_commands.json",
            proxy=run_context.proxy_path,
            caption_style=run_context.analysis_dir / f"{reel}_caption_style.json",
            audio=run_context.wav_path,
            fcpxml=run_context.davinci_dir / f"{reel}_mvp_timeline.fcpxml",
            compiler_report=run_context.davinci_dir / f"{reel}_mvp_timeline_report.json",
            editing_dna=run_context.analysis_dir / f"{reel}_editing_dna.json",
            project=project,
            target_timeline=target_timeline,
        )
    except Exception as error:
        stages["publish"] = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
        result.update(status="failed", finished_at_utc=_utc_now(), artifacts=_artifact_inventory(run_context))
        result["manifest_path"] = str(_write_manifest(run_context, result))
        raise
    stages["publish"] = {"status": "success", "receipt": receipt}
    result["publish_command"] = receipt
    result["resolve_status"] = "ready_for_resolve"
    result["resolve_action"] = "Workspace -> Scripts -> VC_Run_Agent_Task"
    result["artifacts"] = _artifact_inventory(run_context)
    result["finished_at_utc"] = _utc_now()
    result["manifest_path"] = str(_write_manifest(run_context, result))
    return result
