from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN = load_module("vc_plan_edit_speed_authority", "video_cloner/planning/plan.py")
VALIDATE = load_module("vc_validate_edit_speed_authority", "video_cloner/planning/validate.py")
COMPILE = load_module("vc_compile_generic_speed_authority", "video_cloner/planning/compile.py")


def slim_candidate_shot(**overrides):
    shot = {
        "shot_id": 1,
        "duration_frames": 48,
        "motion_type": "pan",
        "motion_family": "pan",
        "motion_intensity": "high",
        "motion_confidence": "high",
        "speed_ramp_candidate": True,
        "cut_priority_score": 0.8,
        "beats_in_shot_count": 2,
        "downbeats_in_shot_count": 1,
    }
    shot.update(overrides)
    return shot


def analysis_candidate_shot(**overrides):
    shot = {
        "shot_id": 1,
        "start_frame": 0,
        "end_frame": 48,
        "duration_frames": 48,
        "start_seconds": 0.0,
        "end_seconds": 2.0,
        "duration_seconds": 2.0,
        "motion": {
            "motion_type": "pan",
            "motion_family": "pan",
            "motion_intensity": "high",
            "confidence": "high",
        },
        "edit_signals": {
            "speed_ramp_candidate": True,
            "cut_priority_score": 0.8,
            "beats_in_shot_count": 2,
            "downbeats_in_shot_count": 1,
        },
    }
    for key, value in overrides.items():
        if key in {"motion", "edit_signals"}:
            shot[key].update(value)
        else:
            shot[key] = value
    return shot


def test_planner_demotes_speed_candidate_to_source_preserving_cut():
    shot = slim_candidate_shot()
    action = PLAN.expected_action_for_shot(shot)
    observation = PLAN.build_speed_ramp_observation(shot)

    assert action["type"] == "cut"
    assert action["rule_id"] == "R5_CUT"
    assert action["reason"] == (
        "speed_ramp_candidate retained as non-actionable motion observation; preserve source timing"
    )
    assert all(op["operation"] != "speed_ramp" for op in action["operation_hints"])

    assert observation == {
        "candidate": True,
        "actionable": False,
        "authority": "motion_heuristic_only",
        "motion_intensity": "high",
        "motion_confidence": "high",
        "reason": (
            "motion analysis marked a speed-ramp candidate; exact retime authority "
            "requires separate source-backed evidence"
        ),
    }


def test_sanitizer_preserves_candidate_metadata_without_speed_parameters():
    slim = {
        "video_id": "fixture",
        "caption_plan": {"enabled": False},
        "shots": [slim_candidate_shot()],
    }
    raw = {
        "global_style": {"pace": "medium", "music_sync": True, "caption_style": "none"},
        "timeline": [{"shot_id": 1, "actions": [{"type": "speed_ramp", "reason": "heuristic"}]}],
    }
    cleaned, corrections = PLAN.sanitize_edit_plan(raw, slim)
    item = cleaned["timeline"][0]

    assert corrections
    assert item["actions"][0]["type"] == "cut"
    assert item["observations"]["speed_ramp_candidate"]["candidate"] is True
    assert item["observations"]["speed_ramp_candidate"]["actionable"] is False

    encoded = json.dumps(item)
    assert '"type": "speed_ramp"' not in encoded
    assert '"operation": "speed_ramp"' not in encoded
    assert "speed_multiplier" not in encoded
    assert "speed_percent" not in encoded


def test_validator_demotes_motion_heuristic_and_rejects_explicit_speed_action():
    shot = analysis_candidate_shot()

    assert VALIDATE.expected_action_type_for_shot(shot) == "cut"
    assert VALIDATE.valid_speed_ramp(shot) is False

    explicit = {
        "type": "speed_ramp",
        "rule_id": "R1_SPEED_RAMP",
        "confidence": "high",
        "priority_score": 0.88,
        "intent": "emphasize_motion_speed_change",
        "compiler_hints": {
            "strength": "strong",
            "sync_to_beat": True,
            "preferred_timing": "within_shot",
            "ramp_style": "smooth",
        },
    }
    errors, _warnings = VALIDATE.validate_action_against_analysis(
        explicit,
        shot,
        strict=True,
        enforce_expected_action=False,
    )
    assert any("motion heuristic is not retime authority" in row["message"] for row in errors)


def test_validator_requires_exact_non_actionable_observation():
    shot = analysis_candidate_shot()
    expected = VALIDATE.expected_speed_ramp_observation(shot)
    item = {"observations": {"speed_ramp_candidate": expected}}

    assert VALIDATE.validate_speed_ramp_observation(item, shot) == []

    bad = json.loads(json.dumps(item))
    bad["observations"]["speed_ramp_candidate"]["actionable"] = True
    errors = VALIDATE.validate_speed_ramp_observation(bad, shot)
    assert len(errors) == 1
    assert errors[0]["message"] == "speed_ramp_candidate observation mismatch"


def test_compiler_fails_closed_on_legacy_speed_action():
    action = {"type": "speed_ramp", "compiler_hints": {"strength": "strong"}}
    ctx = {
        "duration_frames": 48,
        "fps": 24.0,
        "timeline_start_frame": 0,
        "source_clip": {"source_start_frame": 0},
    }
    with pytest.raises(RuntimeError, match="no source-backed retime authority"):
        COMPILE.compile_main_operation(action, {}, ctx)


def test_compiler_propagates_observation_as_metadata_not_operation():
    analysis = {
        "job": {"job_id": "fixture", "fps": 24.0, "frame_count": 48},
        "summary": {"duration_seconds": 2.0},
        "timeline": {"shots": [analysis_candidate_shot()]},
    }
    observation = VALIDATE.expected_speed_ramp_observation(analysis["timeline"]["shots"][0])
    edit_plan = {
        "version": "1.0",
        "video_id": "fixture",
        "global_style": {"pace": "medium", "music_sync": True, "caption_style": "none"},
        "caption_plan": {"enabled": False},
        "timeline": [{
            "shot_id": 1,
            "actions": [{
                "type": "cut",
                "rule_id": "R5_CUT",
                "confidence": "high",
                "priority_score": 0.79,
                "intent": "safe_cut_or_pacing_cut",
                "reason": "speed candidate is metadata only",
                "compiler_hints": {
                    "strength": "normal",
                    "sync_to_beat": True,
                    "preferred_timing": "shot_boundary",
                },
            }],
            "observations": {"speed_ramp_candidate": observation},
        }],
    }
    validated = {"success": True, "edit_plan": edit_plan}
    commands = COMPILE.compile_timeline(validated, analysis)

    assert len(commands) == 1
    assert commands[0]["observations"]["speed_ramp_candidate"] == observation
    assert commands[0]["action"]["type"] == "cut"
    assert all(op["operation"] != "speed_ramp" for op in commands[0]["operations"])


def test_reel1_cli_pipeline_emits_16_nonactionable_candidates_and_zero_speed_ops(tmp_path: Path):
    source_analysis = ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_analysis.json"
    analysis_data = json.loads(source_analysis.read_text(encoding="utf-8-sig"))
    for shot in analysis_data["timeline"]["shots"]:
        shot.pop("transition_to_next", None)
    analysis = tmp_path / "analysis_without_transition_authority.json"
    analysis.write_text(json.dumps(analysis_data), encoding="utf-8")
    plan_out = tmp_path / "edit_plan.json"
    validated_out = tmp_path / "validated.json"
    generic_out = tmp_path / "generic.json"

    commands = [
        [
            sys.executable,
            str(ROOT / "video_cloner/planning/plan.py"),
            "--analysis", str(analysis),
            "--output", str(plan_out),
            "--skip-llm",
        ],
        [
            sys.executable,
            str(ROOT / "video_cloner/planning/validate.py"),
            "--analysis", str(analysis),
            "--edit-plan", str(plan_out),
            "--output", str(validated_out),
        ],
        [
            sys.executable,
            str(ROOT / "video_cloner/planning/compile.py"),
            "--analysis", str(analysis),
            "--validated-edit-plan", str(validated_out),
            "--output", str(generic_out),
        ],
    ]
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert completed.returncode == 0, completed.stdout + completed.stderr

    plan = json.loads(plan_out.read_text(encoding="utf-8"))
    validated = json.loads(validated_out.read_text(encoding="utf-8"))
    generic = json.loads(generic_out.read_text(encoding="utf-8"))

    candidates = [
        item for item in plan["timeline"]
        if item["observations"]["speed_ramp_candidate"]["candidate"] is True
    ]
    assert len(plan["timeline"]) == 22
    assert len(candidates) == 16
    assert {item["actions"][0]["type"] for item in candidates} == {"cut"}
    assert all(item["observations"]["speed_ramp_candidate"]["actionable"] is False for item in candidates)
    assert all(item["observations"]["speed_ramp_candidate"]["authority"] == "motion_heuristic_only" for item in candidates)

    assert validated["success"] is True
    assert validated["timeline_stats"]["primary_action_counts"].get("speed_ramp", 0) == 0

    speed_ops = [
        op for command in generic["timeline"]
        for op in command.get("operations", [])
        if op.get("operation") == "speed_ramp"
    ]
    assert speed_ops == []
    assert sum(
        1 for command in generic["timeline"]
        if ((command.get("observations") or {}).get("speed_ramp_candidate") or {}).get("candidate") is True
    ) == 16
    assert all(
        command["source_start_frame"] == command["timeline_start_frame"]
        and command["source_end_frame"] == command["timeline_end_frame"]
        and command["source_duration_frames"] == command["timeline_duration_frames"]
        for command in generic["timeline"]
    )

    encoded = generic_out.read_text(encoding="utf-8")
    assert '"operation": "speed_ramp"' not in encoded
    assert '"speed_multiplier"' not in encoded
    assert '"speed_percent"' not in encoded


def test_reel1_candidate_primary_actions_are_monotonic_source_preserving(tmp_path: Path):
    analysis = json.loads(
        (ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_analysis.json").read_text(encoding="utf-8")
    )
    slim = PLAN.slim_analysis(analysis)
    cleaned, _corrections = PLAN.sanitize_edit_plan(
        {
            "version": "1.0",
            "video_id": slim["video_id"],
            "global_style": {"pace": "medium", "music_sync": True, "caption_style": "none"},
            "timeline": [],
        },
        slim,
    )
    candidates = [
        item for item in cleaned["timeline"]
        if item["observations"]["speed_ramp_candidate"]["candidate"]
    ]
    assert len(candidates) == 16
    assert all(item["actions"][0]["type"] == "cut" for item in candidates)
    assert all(
        item["actions"][0]["operation_hints"][0]["parameters"]["preferred_timing"] == "shot_boundary"
        for item in candidates
    )
