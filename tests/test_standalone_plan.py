from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.standalone.video_cloner_media_prep import InputSpec, RuntimeConfig, build_run_context
from scripts.standalone.video_cloner_plan import STAGES, PlanningOrchestrator, PlanningRunError


def transition_payload(*, video_id: str | None = None):
    rows = []
    for frame in (158, 526, 556, 833):
        rows.append({"cut_frame": frame, "transition_type": "whip_pan_candidate", "editor_actionable": False, "duration_frames": 0, "duration_seconds": 0.0, "scores": {"directional_context": {"outgoing": {"p90_magnitude": 1.0}, "incoming": {"p90_magnitude": 1.0}}}})
    for frame in (492, 587, 618):
        rows.append({"cut_frame": frame, "transition_type": "slide_transition_candidate", "editor_actionable": False, "duration_frames": 0, "duration_seconds": 0.0, "scores": {"directional_context": {"outgoing": {"p90_magnitude": 1.0}, "incoming": {"p90_magnitude": 1.0}}}})
    rows.append({"cut_frame": 96, "transition_type": "flash_cut", "editor_actionable": True, "duration_frames": 4, "duration_seconds": 0.1667})
    payload = {"ok": True, "success": True, "schema": "video_cloner_transitions", "analysis_version": "transition_proxy_detector_v2_rich_editor_contract", "transitions": rows}
    if video_id is not None:
        payload["video_id"] = video_id
    return payload


def make_context(tmp_path: Path):
    project = tmp_path / "project"
    source = tmp_path / "fixture.mp4"
    source.write_bytes(b"source")
    config = RuntimeConfig.load(project, environ={}, overrides={"python_default": "py-default", "ollama_model": "llama3.1"})
    context = build_run_context(InputSpec.from_local(source), config)
    context.initialize_directories()
    for stage in STAGES:
        script = project / stage.script
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(f"# {stage.name}\n", encoding="utf-8")
    analysis = context.analysis_dir
    (analysis / "fixture_shots.json").write_text(json.dumps([{"shot_id": 1, "start_frame": 0, "end_frame": 24}]), encoding="utf-8")
    (analysis / "fixture_beatmap.json").write_text(json.dumps({"success": True, "analysis_version": "mock"}), encoding="utf-8")
    (analysis / "fixture_motion.json").write_text(json.dumps({"success": True, "analysis_version": "mock"}), encoding="utf-8")
    for suffix in ("transcript", "caption_style", "caption_occlusion"):
        (analysis / f"fixture_{suffix}.json").write_text(json.dumps({"success": True, "analysis_version": f"mock_{suffix}"}), encoding="utf-8")
    authority = tmp_path / "transition_authority.json"
    authority.write_text(json.dumps(transition_payload()), encoding="utf-8")
    return context, authority


class FakeRunner:
    def __init__(self, fail: str | None = None):
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, argv):
        call = list(argv)
        self.calls.append(call)
        name = Path(call[1]).name
        if self.fail == name:
            return subprocess.CompletedProcess(call, 7, "", "SECRET stderr")
        output = Path(call[call.index("--output") + 1])
        if name == "merge_analysis.py":
            transitions = json.loads(Path(call[call.index("--transitions") + 1]).read_text(encoding="utf-8"))
            payload = {
                "success": True,
                "analysis_version": "merge_analysis_v2_2_caption_foreground_assets_ready",
                "schema_version": "2.1",
                "job": {"job_id": call[call.index("--job-id") + 1], "fps": 24.0},
                "summary": {"shot_count": 1},
                "timeline": {"shots": [{"shot_id": index + 1, "transition_to_next": row} for index, row in enumerate(transitions["transitions"])]},
                "planner_ready": {"ready": True},
            }
        elif name == "plan_edit.py":
            analysis = json.loads(Path(call[call.index("--analysis") + 1]).read_text(encoding="utf-8"))
            payload = {"version": "1.0", "video_id": analysis["job"]["job_id"], "global_style": {}, "caption_plan": {}, "timeline": [{"shot_id": 1, "actions": [{"type": "cut"}]}], "_meta": {"planner_version": "mock", "skip_llm": True, "sanitized": True}}
        elif name == "validate_edit_plan.py":
            plan = json.loads(Path(call[call.index("--edit-plan") + 1]).read_text(encoding="utf-8"))
            payload = {"success": True, "validation_version": "mock", "video_id": plan["video_id"], "analysis_video_id": plan["video_id"], "errors_count": 0, "errors": [], "edit_plan": plan, "_meta": {"ready_for_compile_generic_edit_v2": True}}
        elif name == "compile_generic_edit.py":
            analysis = json.loads(Path(call[call.index("--analysis") + 1]).read_text(encoding="utf-8"))
            operations = [{"operation": "cut", "parameters": {}}]
            for shot in analysis["timeline"]["shots"]:
                transition = shot.get("transition_to_next") or {}
                if transition.get("transition_type") == "flash_cut" and transition.get("editor_actionable") is True:
                    operations.append({"operation": "transition_hint", "parameters": {"transition_type": "flash_cut"}})
            payload = {"success": True, "compiler_version": "mock", "schema": "generic_edit_commands", "schema_version": "2.0", "video_id": analysis["job"]["job_id"], "summary": {"commands_count": 1}, "timeline": [{"source_start_frame": 0, "source_end_frame": 24, "source_duration_frames": 24, "timeline_start_frame": 0, "timeline_end_frame": 24, "timeline_duration_frames": 24, "operations": operations}]}
        else:
            raise AssertionError(name)
        output.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(call, 0, json.dumps({"ok": True}), "")


def names(runner: FakeRunner):
    return [Path(call[1]).name for call in runner.calls]


def statuses(report):
    return {record["stage"]: record["status"] for record in report["stages"]}


def test_contract_uses_exact_stage_order_default_runtime_and_offline_planner(tmp_path: Path):
    context, authority = make_context(tmp_path)
    orchestrator = PlanningOrchestrator(context, authority, FakeRunner())
    assert [stage.name for stage in STAGES] == ["merge", "plan", "validate", "compile"]
    commands = {stage.name: orchestrator._command(stage) for stage in STAGES}
    assert all(command[0] == "py-default" for command in commands.values())
    assert "--skip-llm" in commands["plan"] and "--ollama-url" not in commands["plan"]
    assert commands["compile"][-2:] == ["--subtitle-source", "words"]
    assert str(authority.resolve()) in commands["merge"]


def test_successful_end_to_end_run_preserves_authority(tmp_path: Path):
    context, authority = make_context(tmp_path)
    runner = FakeRunner(); orchestrator = PlanningOrchestrator(context, authority, runner)
    report = orchestrator.run()
    assert names(runner) == ["merge_analysis.py", "plan_edit.py", "validate_edit_plan.py", "compile_generic_edit.py"]
    assert report["summary"] == {"generated": 4, "reused": 0, "failed": 0}
    assert report["authority"]["speed_operations"] == report["authority"]["zoom_operations"] == 0
    assert report["authority"]["generated_blur_operations"] == report["authority"]["rejected_transition_operations"] == 0
    assert report["authority"]["whip_candidate_count"] == 4
    assert report["authority"]["whip_candidate_frames"] == [158, 526, 556, 833]
    assert report["authority"]["slide_candidate_count"] == 3
    assert report["authority"]["slide_candidate_frames"] == [492, 587, 618]
    assert report["authority"]["flash_transition_hints"] == 1
    assert orchestrator.artifacts["generic_edit_commands"].stat().st_size > 0


def test_identical_second_run_reuses_all_stages_without_subprocesses(tmp_path: Path):
    context, authority = make_context(tmp_path)
    PlanningOrchestrator(context, authority, FakeRunner()).run()
    second = FakeRunner(); report = PlanningOrchestrator(context, authority, second).run()
    assert second.calls == []
    assert report["summary"] == {"generated": 0, "reused": 4, "failed": 0}


@pytest.mark.parametrize("mode", ["missing", "empty", "malformed"])
def test_nonempty_valid_json_prerequisite_gate(mode: str, tmp_path: Path):
    context, authority = make_context(tmp_path)
    beatmap = context.analysis_dir / "fixture_beatmap.json"
    if mode == "missing":
        beatmap.unlink()
    elif mode == "empty":
        beatmap.write_bytes(b"")
    else:
        beatmap.write_text("not-json", encoding="utf-8")
    runner = FakeRunner()
    with pytest.raises(PlanningRunError) as caught:
        PlanningOrchestrator(context, authority, runner).run()
    assert caught.value.report["first_failure"]["stage"] == "merge"
    assert runner.calls == []


def test_video_identity_mismatch_blocks_merge(tmp_path: Path):
    context, authority = make_context(tmp_path)
    authority.write_text(json.dumps(transition_payload(video_id="other")), encoding="utf-8")
    runner = FakeRunner()
    with pytest.raises(PlanningRunError, match="video identity mismatch"):
        PlanningOrchestrator(context, authority, runner).run()
    assert runner.calls == []


def test_stale_actionable_whip_authority_is_rejected(tmp_path: Path):
    context, authority = make_context(tmp_path)
    payload = transition_payload(); payload["transitions"][0].update({"transition_type": "whip_pan", "editor_actionable": True, "duration_frames": 8, "duration_seconds": 0.3333})
    authority.write_text(json.dumps(payload), encoding="utf-8")
    runner = FakeRunner()
    with pytest.raises(PlanningRunError, match="executable rejected transition"):
        PlanningOrchestrator(context, authority, runner).run()
    assert runner.calls == []


@pytest.mark.parametrize("failed,expected", [
    ("merge_analysis.py", ["merge_analysis.py"]),
    ("plan_edit.py", ["merge_analysis.py", "plan_edit.py"]),
    ("validate_edit_plan.py", ["merge_analysis.py", "plan_edit.py", "validate_edit_plan.py"]),
    ("compile_generic_edit.py", ["merge_analysis.py", "plan_edit.py", "validate_edit_plan.py", "compile_generic_edit.py"]),
])
def test_failure_isolation_stops_at_first_failed_stage(failed: str, expected: list[str], tmp_path: Path):
    context, authority = make_context(tmp_path)
    runner = FakeRunner(fail=failed)
    with pytest.raises(PlanningRunError) as caught:
        PlanningOrchestrator(context, authority, runner).run()
    assert names(runner) == expected
    assert caught.value.report["first_failure"]["stage"] == {"merge_analysis.py": "merge", "plan_edit.py": "plan", "validate_edit_plan.py": "validate", "compile_generic_edit.py": "compile"}[failed]
    assert "SECRET" not in json.dumps(caught.value.report)


def test_changed_transition_authority_invalidates_merge_and_downstream(tmp_path: Path):
    context, authority = make_context(tmp_path)
    PlanningOrchestrator(context, authority, FakeRunner()).run()
    payload = transition_payload(); payload["transitions"].append({"cut_frame": 120, "transition_type": "hard_cut", "editor_actionable": False, "duration_frames": 0, "duration_seconds": 0.0})
    authority.write_text(json.dumps(payload), encoding="utf-8")
    runner = FakeRunner(); report = PlanningOrchestrator(context, authority, runner).run()
    assert names(runner) == ["merge_analysis.py", "plan_edit.py", "validate_edit_plan.py", "compile_generic_edit.py"]
    assert all(value == "generated" for value in statuses(report).values())


def test_changed_planner_script_invalidates_only_plan_when_output_is_identical(tmp_path: Path):
    context, authority = make_context(tmp_path)
    PlanningOrchestrator(context, authority, FakeRunner()).run()
    planner = context.config.project_root / "scripts/planning/plan_edit.py"
    planner.write_text("# plan changed\n", encoding="utf-8")
    runner = FakeRunner(); report = PlanningOrchestrator(context, authority, runner).run()
    assert names(runner) == ["plan_edit.py"]
    assert statuses(report) == {"merge": "reused", "plan": "generated", "validate": "reused", "compile": "reused"}


def test_default_runtime_identity_change_invalidates_all_default_runtime_stages(tmp_path: Path):
    context, authority = make_context(tmp_path)
    PlanningOrchestrator(context, authority, FakeRunner()).run()
    changed = replace(context, config=replace(context.config, python_default="py-default-v2"))
    runner = FakeRunner(); report = PlanningOrchestrator(changed, authority, runner).run()
    assert names(runner) == ["merge_analysis.py", "plan_edit.py", "validate_edit_plan.py", "compile_generic_edit.py"]
    assert report["summary"]["generated"] == 4


def test_selective_force_and_force_all(tmp_path: Path):
    context, authority = make_context(tmp_path)
    PlanningOrchestrator(context, authority, FakeRunner()).run()
    selective = FakeRunner(); report = PlanningOrchestrator(context, authority, selective).run(force_stages={"compile"})
    assert names(selective) == ["compile_generic_edit.py"]
    assert statuses(report)["compile"] == "generated"
    all_runner = FakeRunner(); all_report = PlanningOrchestrator(context, authority, all_runner).run(force=True)
    assert len(all_runner.calls) == 4 and all_report["summary"]["generated"] == 4


def test_report_records_runtime_command_and_output_identities_without_secrets(tmp_path: Path):
    context, authority = make_context(tmp_path)
    report = PlanningOrchestrator(context, authority, FakeRunner()).run()
    for record in report["stages"]:
        assert len(record["script_sha256"]) == len(record["interpreter_identity_sha256"]) == 64
        assert len(record["command_profile_sha256"]) == len(record["input_fingerprint"]) == len(record["output_sha256"]) == 64
    encoded = json.dumps(report)
    assert "SECRET" not in encoded and "cookies" not in encoded.lower()
    assert report["phase2_analyzers_invoked"] is report["fcpxml_invoked"] is report["resolve_invoked"] is False


def test_source_has_no_phase2_analyzer_fcpxml_resolve_network_or_hardcoded_reel_calls():
    source = (Path(__file__).resolve().parents[1] / "scripts/standalone/video_cloner_plan.py").read_text(encoding="utf-8")
    for forbidden in ("detect_transitions_proxy.py", "detect_motion_speed.py", "detect_caption_style.py", "compile_davinci", "DaVinciResolveScript", "SaveProject", "DZsqH7auhjt", "requests.", "urlopen("):
        assert forbidden not in source
    assert "--skip-llm" in source
