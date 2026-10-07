from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.standalone.video_cloner_analysis import ANALYZERS, AnalysisOrchestrator, AnalysisRunError
from scripts.standalone.video_cloner_media_prep import InputSpec, RuntimeConfig, build_run_context


def make_context(tmp_path: Path, *, wav: bool = True, proxy: bool = True):
    project = tmp_path / "project"
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source-v1")
    config = RuntimeConfig.load(project, environ={}, overrides={"python_default": "py-default", "python_audio": "py-audio", "python_ocr": "py-ocr"})
    context = build_run_context(InputSpec.from_local(video), config)
    context.initialize_directories()
    if wav:
        context.wav_path.write_bytes(b"wav-v1")
    if proxy:
        context.proxy_path.write_bytes(b"proxy-v1")
    for spec in ANALYZERS:
        script = project / spec.script
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(f"# {spec.name}\n", encoding="utf-8")
    return context


def fake_scene_result():
    return {"ok": True, "cuts": [{"scene_index": 1, "start_seconds": 0.0, "end_seconds": 1.0, "duration_seconds": 1.0, "start_frame": 0, "end_frame": 24}]}


class FakeRunner:
    def __init__(self, fail: str | None = None):
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, argv):
        call = list(argv); self.calls.append(call)
        name = Path(call[1]).name
        if self.fail and self.fail in name:
            return subprocess.CompletedProcess(call, 9, "", "SECRET stderr must not serialize")
        if name == "cuts.py":
            return subprocess.CompletedProcess(call, 0, json.dumps(fake_scene_result()), "")
        output = Path(call[call.index("--output") + 1])
        payload = {"success": True, "analysis_version": f"mock_{name}", "observations": []}
        if name == "caption_occlusion.py":
            root = output.parent / "foreground_masks"
            event_dir = root / "0001_mock"
            event_dir.mkdir(parents=True, exist_ok=True)
            pattern = event_dir / "mask_%06d.png"
            for frame in range(10, 12):
                Path(str(pattern) % frame).write_bytes(f"mask-{frame}".encode("ascii"))
            asset = {
                "requested": True,
                "mask_root": str(root),
                "event_dir": str(event_dir),
                "mask_pattern": str(pattern),
                "source_frame_start": 10,
                "source_frame_end_exclusive": 12,
                "frame_count_expected": 2,
                "frame_count_written": 2,
                "complete": True,
                "errors": [],
            }
            manifest = event_dir / "manifest.json"
            asset["manifest"] = str(manifest)
            manifest.write_text(json.dumps(asset), encoding="utf-8")
            debug = output.parent / "debug_caption_occlusion" / "optional.jpg"
            debug.parent.mkdir(parents=True, exist_ok=True)
            debug.write_bytes(b"optional-debug")
            payload.update({
                "mask_assets": {"enabled": True, "root": str(root), "frames_written": 2, "events_requested": 1, "events_complete": 1, "events_incomplete": 0, "ready": True},
                "occlusion_events": [{"id": "mock", "mask_asset": asset}],
                "debug_artifacts": {"files": [str(debug)]},
            })
        output.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(call, 0, json.dumps({"success": True}), "")


class ZeroMaskOcclusionRunner(FakeRunner):
    def __call__(self, argv):
        call = list(argv)
        name = Path(call[1]).name
        if name != "caption_occlusion.py":
            return super().__call__(argv)
        self.calls.append(call)
        output = Path(call[call.index("--output") + 1])
        payload = {
            "success": True,
            "analysis_version": "mock_caption_occlusion.py",
            "observations": [],
            "mask_assets": {
                "enabled": True,
                "root": str(output.parent / "foreground_masks"),
                "frames_written": 0,
                "events_requested": 0,
                "events_complete": 0,
                "events_incomplete": 0,
                "ready": False,
            },
            "occlusion_events": [],
        }
        output.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(call, 0, json.dumps({"success": True}), "")


def status_map(report):
    return {record["analyzer"]: record["status"] for record in report["analyzers"]}


def test_phase1_run_context_integrates_and_uses_canonical_paths(tmp_path: Path):
    context = make_context(tmp_path)
    orchestrator = AnalysisOrchestrator(context, FakeRunner())
    contract = orchestrator.canonical_contract()
    assert contract["video_id"] == context.video_id
    assert Path(contract["analysis_dir"]) == context.analysis_dir
    assert orchestrator.artifacts["transcript"] == context.analysis_dir / f"{context.video_id}_transcript.json"
    assert orchestrator.artifacts["caption_occlusion"] == context.analysis_dir / f"{context.video_id}_caption_occlusion.json"
    assert orchestrator.report_path.parent == context.analysis_dir


def test_canonical_analyzer_map_and_interpreters_are_exact(tmp_path: Path):
    orchestrator = AnalysisOrchestrator(make_context(tmp_path), FakeRunner())
    specs = {spec.name: spec for spec in ANALYZERS}
    assert list(specs) == ["cuts", "transcript", "rhythm", "caption_style", "motion", "transitions", "caption_occlusion"]
    assert specs["transitions"].script == "video_cloner/analysis/transitions.py"
    assert specs["transcript"].interpreter == specs["rhythm"].interpreter == "python_audio"
    assert specs["caption_style"].interpreter == specs["caption_occlusion"].interpreter == "python_ocr"
    assert specs["cuts"].interpreter == specs["motion"].interpreter == specs["transitions"].interpreter == "python_default"
    assert orchestrator._interpreter(specs["cuts"]) == "py-default"
    assert orchestrator._interpreter(specs["transcript"]) == "py-audio"
    assert orchestrator._interpreter(specs["caption_style"]) == "py-ocr"


def test_exact_dependency_graph_uses_actual_caption_inputs():
    specs = {spec.name: spec for spec in ANALYZERS}
    assert specs["cuts"].inputs == ("proxy",)
    assert specs["transcript"].inputs == specs["rhythm"].inputs == ("wav",)
    assert specs["caption_style"].inputs == ("source_video", "transcript")
    assert specs["motion"].inputs == specs["transitions"].inputs == ("proxy", "shots")
    assert specs["caption_occlusion"].inputs == ("proxy", "caption_style", "transcript")


def test_commands_preserve_n8n_parameters_and_runtime_roles(tmp_path: Path):
    orchestrator = AnalysisOrchestrator(make_context(tmp_path), FakeRunner())
    commands = {spec.name: orchestrator._command(spec) for spec in ANALYZERS}
    assert commands["cuts"][0] == "py-default" and commands["cuts"][-1] == "23"
    assert commands["transcript"][0] == "py-audio" and commands["transcript"][commands["transcript"].index("--model") + 1] == "medium"
    assert "--caption-mode" in commands["transcript"] and "word" in commands["transcript"]
    assert commands["rhythm"][0] == "py-audio" and "--approximate-downbeats" in commands["rhythm"]
    assert commands["caption_style"][0] == "py-ocr" and "viral_transcript_aware" in commands["caption_style"]
    assert commands["motion"][0] == commands["transitions"][0] == "py-default"
    assert commands["caption_occlusion"][0] == "py-ocr" and "paddle_humanseg" in commands["caption_occlusion"]


def test_missing_wav_blocks_wav_consumers_but_preserves_independent_proxy_branch(tmp_path: Path):
    runner = FakeRunner(); orchestrator = AnalysisOrchestrator(make_context(tmp_path, wav=False), runner)
    with pytest.raises(AnalysisRunError) as caught:
        orchestrator.run()
    states = status_map(caught.value.report)
    assert states["transcript"] == states["rhythm"] == "blocked"
    assert states["caption_style"] == states["caption_occlusion"] == "blocked"
    assert states["cuts"] == states["motion"] == states["transitions"] == "generated"
    assert all("transcription.py" not in call[1] and "rhythm.py" not in call[1] for call in runner.calls)


def test_missing_proxy_blocks_proxy_consumers_but_allows_wav_branch(tmp_path: Path):
    runner = FakeRunner(); orchestrator = AnalysisOrchestrator(make_context(tmp_path, proxy=False), runner)
    with pytest.raises(AnalysisRunError) as caught:
        orchestrator.run()
    states = status_map(caught.value.report)
    assert states["cuts"] == states["motion"] == states["transitions"] == states["caption_occlusion"] == "blocked"
    assert states["transcript"] == states["rhythm"] == states["caption_style"] == "generated"


def test_transitions_and_caption_occlusion_readiness_require_nonempty_inputs(tmp_path: Path):
    orchestrator = AnalysisOrchestrator(make_context(tmp_path), FakeRunner())
    assert orchestrator.readiness("transitions") == {"analyzer": "transitions", "ready": False, "missing": ["shots"]}
    assert orchestrator.readiness("caption_occlusion") == {"analyzer": "caption_occlusion", "ready": False, "missing": ["caption_style", "transcript"]}
    orchestrator.artifacts["shots"].write_text("[]", encoding="utf-8")
    orchestrator.artifacts["transcript"].write_text("{}", encoding="utf-8")
    orchestrator.artifacts["caption_style"].write_text("{}", encoding="utf-8")
    assert orchestrator.readiness("transitions")["ready"] is True
    assert orchestrator.readiness("caption_occlusion")["ready"] is True


def test_independent_branches_execute_in_deterministic_topological_order(tmp_path: Path):
    runner = FakeRunner(); report = AnalysisOrchestrator(make_context(tmp_path), runner).run()
    assert [Path(call[1]).name for call in runner.calls] == ["cuts.py", "transcription.py", "rhythm.py", "caption_style.py", "motion.py", "transitions.py", "caption_occlusion.py"]
    assert [record["analyzer"] for record in report["analyzers"]] == [spec.name for spec in ANALYZERS]
    assert report["summary"] == {"generated": 7, "reused": 0, "failed": 0, "blocked": 0}


def test_failed_cuts_blocks_dependents_but_independent_branches_complete(tmp_path: Path):
    runner = FakeRunner(fail="cuts.py"); orchestrator = AnalysisOrchestrator(make_context(tmp_path), runner)
    with pytest.raises(AnalysisRunError) as caught:
        orchestrator.run()
    states = status_map(caught.value.report)
    assert states["cuts"] == "failed"
    assert states["motion"] == states["transitions"] == "blocked"
    assert states["transcript"] == states["rhythm"] == states["caption_style"] == states["caption_occlusion"] == "generated"
    assert caught.value.report["first_failure"]["analyzer"] == "cuts"


def test_second_run_reuses_all_valid_outputs_without_external_calls(tmp_path: Path):
    context = make_context(tmp_path); first = FakeRunner(); AnalysisOrchestrator(context, first).run()
    second = FakeRunner(); report = AnalysisOrchestrator(context, second).run()
    assert second.calls == []
    assert report["summary"] == {"generated": 0, "reused": 7, "failed": 0, "blocked": 0}


def test_force_selected_analyzer_reruns_only_requested_scope_when_output_is_identical(tmp_path: Path):
    context = make_context(tmp_path); AnalysisOrchestrator(context, FakeRunner()).run()
    runner = FakeRunner(); report = AnalysisOrchestrator(context, runner).run(force_analyzers={"transitions"})
    assert [Path(call[1]).name for call in runner.calls] == ["transitions.py"]
    assert status_map(report)["transitions"] == "generated"
    assert sum(value == "reused" for value in status_map(report).values()) == 6


def test_force_all_reruns_all_analyzers(tmp_path: Path):
    context = make_context(tmp_path); AnalysisOrchestrator(context, FakeRunner()).run()
    runner = FakeRunner(); report = AnalysisOrchestrator(context, runner).run(force=True)
    assert len(runner.calls) == 7
    assert report["summary"]["generated"] == 7


def test_changed_proxy_invalidates_only_relevant_reuse(tmp_path: Path):
    context = make_context(tmp_path); AnalysisOrchestrator(context, FakeRunner()).run()
    context.proxy_path.write_bytes(b"proxy-v2")
    runner = FakeRunner(); report = AnalysisOrchestrator(context, runner).run()
    called = [Path(call[1]).name for call in runner.calls]
    assert called == ["cuts.py", "motion.py", "transitions.py", "caption_occlusion.py"]
    states = status_map(report)
    assert states["transcript"] == states["rhythm"] == states["caption_style"] == "reused"


def test_changed_transcript_invalidates_caption_dependents(tmp_path: Path):
    context = make_context(tmp_path); AnalysisOrchestrator(context, FakeRunner()).run()

    class ChangedTranscriptRunner(FakeRunner):
        def __call__(self, argv):
            result = super().__call__(argv)
            call = list(argv)
            if Path(call[1]).name == "transcription.py":
                output = Path(call[call.index("--output") + 1])
                output.write_text(json.dumps({"success": True, "analysis_version": "changed"}), encoding="utf-8")
            return result

    runner = ChangedTranscriptRunner()
    report = AnalysisOrchestrator(context, runner).run(force_analyzers={"transcript"})
    called = [Path(call[1]).name for call in runner.calls]
    assert called == ["transcription.py", "caption_style.py", "caption_occlusion.py"]
    assert status_map(report)["transcript"] == status_map(report)["caption_style"] == status_map(report)["caption_occlusion"] == "generated"


def test_changed_ocr_runtime_invalidates_only_ocr_analyzers(tmp_path: Path):
    context = make_context(tmp_path); AnalysisOrchestrator(context, FakeRunner()).run()
    changed = replace(context, config=replace(context.config, python_ocr="py-ocr-v2"))
    runner = FakeRunner(); report = AnalysisOrchestrator(changed, runner).run()
    assert [Path(call[1]).name for call in runner.calls] == ["caption_style.py", "caption_occlusion.py"]
    assert status_map(report)["caption_style"] == status_map(report)["caption_occlusion"] == "generated"
    assert status_map(report)["cuts"] == status_map(report)["transcript"] == status_map(report)["rhythm"] == "reused"


def test_zero_requested_occlusion_masks_are_valid_and_reusable(tmp_path: Path):
    context = make_context(tmp_path)
    first_runner = ZeroMaskOcclusionRunner()
    first = AnalysisOrchestrator(context, first_runner).run()
    assert status_map(first)["caption_occlusion"] == "generated"
    assert not (context.analysis_dir / "foreground_masks").exists()

    second_runner = ZeroMaskOcclusionRunner()
    second = AnalysisOrchestrator(context, second_runner).run()
    assert second_runner.calls == []
    assert status_map(second)["caption_occlusion"] == "reused"


def test_missing_required_occlusion_mask_invalidates_bundle_reuse(tmp_path: Path):
    context = make_context(tmp_path); orchestrator = AnalysisOrchestrator(context, FakeRunner()); orchestrator.run()
    (context.analysis_dir / "foreground_masks" / "0001_mock" / "mask_000010.png").unlink()
    runner = FakeRunner(); report = AnalysisOrchestrator(context, runner).run()
    assert [Path(call[1]).name for call in runner.calls] == ["caption_occlusion.py"]
    assert status_map(report)["caption_occlusion"] == "generated"


def test_modified_required_occlusion_mask_invalidates_bundle_reuse(tmp_path: Path):
    context = make_context(tmp_path); orchestrator = AnalysisOrchestrator(context, FakeRunner()); orchestrator.run()
    (context.analysis_dir / "foreground_masks" / "0001_mock" / "mask_000011.png").write_bytes(b"changed-mask")
    runner = FakeRunner(); report = AnalysisOrchestrator(context, runner).run()
    assert [Path(call[1]).name for call in runner.calls] == ["caption_occlusion.py"]
    assert status_map(report)["caption_occlusion"] == "generated"


def test_missing_optional_occlusion_debug_artifact_does_not_invalidate_reuse(tmp_path: Path):
    context = make_context(tmp_path); AnalysisOrchestrator(context, FakeRunner()).run()
    (context.analysis_dir / "debug_caption_occlusion" / "optional.jpg").unlink()
    runner = FakeRunner(); report = AnalysisOrchestrator(context, runner).run()
    assert runner.calls == []
    assert status_map(report)["caption_occlusion"] == "reused"


def test_nonempty_output_without_matching_manifest_is_not_reused(tmp_path: Path):
    context = make_context(tmp_path); orchestrator = AnalysisOrchestrator(context, FakeRunner())
    for key in ("shots", "transcript", "beatmap", "caption_style", "motion", "transitions", "caption_occlusion"):
        orchestrator.artifacts[key].write_text("[]" if key == "shots" else '{"success":true}', encoding="utf-8")
    runner = FakeRunner(); report = AnalysisOrchestrator(context, runner).run()
    assert len(runner.calls) == 7 and report["summary"]["generated"] == 7


def test_invalid_cached_json_is_regenerated(tmp_path: Path):
    context = make_context(tmp_path); first = AnalysisOrchestrator(context, FakeRunner()); first.run()
    first.artifacts["beatmap"].write_text("not-json", encoding="utf-8")
    runner = FakeRunner(); report = AnalysisOrchestrator(context, runner).run()
    assert [Path(call[1]).name for call in runner.calls] == ["rhythm.py"]
    assert status_map(report)["rhythm"] == "generated"


def test_failure_report_is_sanitized_and_persisted(tmp_path: Path):
    context = make_context(tmp_path); orchestrator = AnalysisOrchestrator(context, FakeRunner(fail="transcription.py"))
    with pytest.raises(AnalysisRunError) as caught:
        orchestrator.run()
    serialized = json.dumps(caught.value.report)
    assert "SECRET stderr" not in serialized
    assert "cookies" not in serialized.lower()
    persisted = json.loads(orchestrator.report_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "failed" and persisted["first_failure"]["analyzer"] == "transcript"


def test_report_records_hashes_versions_runtime_and_observation_only_boundary(tmp_path: Path):
    report = AnalysisOrchestrator(make_context(tmp_path), FakeRunner()).run()
    for record in report["analyzers"]:
        assert record["status"] == "generated"
        assert len(record["script_sha256"]) == len(record["output_sha256"]) == 64
        assert len(record["interpreter_identity_sha256"]) == len(record["command_profile_sha256"]) == 64
        assert len(record["output_bundle_fingerprint"]) == 64
        assert record["analyzer_version"].startswith(("mock_", "script_sha256:"))
        assert record["runtime_sec"] >= 0
    serialized = json.dumps(report)
    assert report["planner_invoked"] is report["resolve_invoked"] is False
    assert "executable_authority" not in serialized and "transform_zoom" not in serialized and "speed_multiplier" not in serialized


def test_source_contains_no_network_resolve_planner_or_hardcoded_reel_defaults():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "standalone" / "video_cloner_analysis.py").read_text(encoding="utf-8")
    for forbidden in ("DaVinciResolveScript", "merge_analysis.py", "plan_edit.py", "compile_generic_edit.py", "DS5AyItD8DV", "DZsqH7auhjt", "--apply-zoom", "--animated-zoom"):
        assert forbidden not in source
    assert "requests." not in source and "urlopen(" not in source
