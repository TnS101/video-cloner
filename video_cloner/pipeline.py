"""Canonical orchestration API for the offline Video Cloner pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .analysis.pipeline import AnalysisOrchestrator
from .config import RuntimeConfig, build_run_context
from .contracts import InputSpec, RunContext
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


def profile(run: RunContext, *, samples_per_shot: int = 5) -> dict[str, str]:
    """Build the current camera, caption, style, and transition profile artifacts."""
    from .camera import build_camera_style_profile, collect_face_observations
    from .caption_grammar import build_grammar
    from .profiles import build_profile
    from .transition_policy import filter_mvp_transitions

    reel = run.video_id
    analysis = run.analysis_dir
    planning = run.planning_dir
    paths = {
        "camera": analysis / f"{reel}_camera_style_profile.json",
        "caption_grammar": analysis / f"{reel}_caption_style_grammar.json",
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
    filtered = filter_mvp_transitions(json.loads(transition_path.read_text(encoding="utf-8-sig")))
    paths["transitions"].write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
    from .resolve.fcpxml import main

    argv = ["--generic", str(generic), "--caption-style", str(caption_style), "--output-fcpxml", str(output_fcpxml), "--report", str(report)]
    for name, value in (options or {}).items():
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
        config.project_root, Path(generic), Path(proxy), Path(caption_style), Path(audio), Path(fcpxml), Path(compiler_report), target
    )
    return publish_command(config.project_root, manifest, contract, project_name, target)


def run_offline(run: RunContext, transition_authority: str | Path, *, force: bool = False, samples_per_shot: int = 5) -> dict[str, object]:
    """Run analysis, planning, and profiles after media ingestion."""
    return {
        "analysis": analyze(run, force=force),
        "planning": plan(run, transition_authority, force=force),
        "profiles": profile(run, samples_per_shot=samples_per_shot),
    }
