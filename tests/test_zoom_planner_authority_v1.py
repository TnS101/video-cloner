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


PLAN = load_module("vc_plan_edit_zoom_authority", "scripts/planning/plan_edit.py")
VALIDATE = load_module("vc_validate_edit_zoom_authority", "scripts/planning/validate_edit_plan.py")
COMPILE = load_module("vc_compile_generic_zoom_authority", "scripts/planning/compile_generic_edit.py")


def slim_zoom_shot(**overrides):
    shot = {
        "shot_id": 1,
        "duration_frames": 48,
        "motion_type": "push_in",
        "motion_family": "push_in",
        "motion_intensity": "medium",
        "motion_confidence": "high",
        "speed_ramp_candidate": False,
        "zoom_candidate": True,
        "zoom_direction": "in",
        "zoom_confidence": "high",
        "zoom_affine_scale_delta": 0.0125,
        "cut_priority_score": 0.4,
        "beats_in_shot_count": 0,
        "downbeats_in_shot_count": 0,
    }
    shot.update(overrides)
    return shot


def analysis_zoom_shot(**overrides):
    shot = {
        "shot_id": 1,
        "start_frame": 0,
        "end_frame": 48,
        "duration_frames": 48,
        "start_seconds": 0.0,
        "end_seconds": 2.0,
        "duration_seconds": 2.0,
        "motion": {
            "motion_type": "push_in",
            "motion_family": "push_in",
            "motion_intensity": "medium",
            "confidence": "high",
            "zoom_candidate": True,
            "zoom_direction": "in",
            "camera_motion": {"avg_scale_delta": 0.0125},
            "motion_based_zoom": {
                "candidate": True,
                "direction": "in",
                "confidence": "high",
            },
        },
        "edit_signals": {
            "speed_ramp_candidate": False,
            "cut_priority_score": 0.4,
            "beats_in_shot_count": 0,
            "downbeats_in_shot_count": 0,
        },
    }
    for key, value in overrides.items():
        if key in {"motion", "edit_signals"}:
            shot[key].update(value)
        else:
            shot[key] = value
    return shot


def expected_observation():
    return {
        "candidate": True,
        "actionable": False,
        "authority": "motion_heuristic_only",
        "source": "motion_affine_scale_delta",
        "direction": "in",
        "confidence": "high",
        "motion_family": "push_in",
        "motion_type": "push_in",
        "motion_intensity": "medium",
        "avg_scale_delta": 0.0125,
        "reason": (
            "affine scale motion marked a zoom candidate; editable zoom authority "
            "requires separate source-backed transform evidence"
        ),
    }


def test_planner_demotes_zoom_candidate_to_source_preserving_cut():
    shot = slim_zoom_shot()
    action = PLAN.expected_action_for_shot(shot)
    observation = PLAN.build_zoom_observation(shot)

    assert action["type"] == "cut"
    assert action["rule_id"] == "R5_CUT"
    assert action["reason"] == (
        "zoom_candidate retained as non-actionable motion observation; preserve source geometry"
    )
    assert all(op["operation"] != "transform_zoom" for op in action["operation_hints"])
    assert observation == expected_observation()


def test_sanitizer_preserves_zoom_metadata_without_transform_zoom():
    slim = {
        "video_id": "fixture",
        "caption_plan": {"enabled": False},
        "shots": [slim_zoom_shot()],
    }
    raw = {
        "global_style": {"pace": "medium", "music_sync": True, "caption_style": "none"},
        "timeline": [{"shot_id": 1, "actions": [{"type": "zoom_in", "reason": "heuristic"}]}],
    }
    cleaned, corrections = PLAN.sanitize_edit_plan(raw, slim)
    item = cleaned["timeline"][0]

    assert corrections
    assert item["actions"][0]["type"] == "cut"
    assert item["observations"]["zoom_candidate"] == expected_observation()

    encoded = json.dumps(item)
    assert '"type": "zoom_in"' not in encoded
    assert '"type": "zoom_out"' not in encoded
    assert '"operation": "transform_zoom"' not in encoded
    assert '"start_scale"' not in encoded
    assert '"end_scale"' not in encoded


@pytest.mark.parametrize("action_type", ["zoom_in", "zoom_out"])
def test_validator_rejects_explicit_legacy_zoom_even_without_expected_action_enforcement(action_type):
    shot = analysis_zoom_shot()
    explicit = {
        "type": action_type,
        "rule_id": "R3_ZOOM_IN" if action_type == "zoom_in" else "R4_ZOOM_OUT",
        "confidence": "high",
        "priority_score": 0.72,
        "intent": "enhance_existing_push_in" if action_type == "zoom_in" else "enhance_existing_pull_out",
        "compiler_hints": {
            "strength": "medium",
            "sync_to_beat": False,
            "preferred_timing": "full_shot",
            "direction": "in" if action_type == "zoom_in" else "out",
        },
    }
    errors, _warnings = VALIDATE.validate_action_against_analysis(
        explicit,
        shot,
        strict=True,
        enforce_expected_action=False,
    )
    assert any("motion heuristic is not editable zoom authority" in row["message"] for row in errors)


def test_validator_requires_exact_nonactionable_zoom_observation():
    shot = analysis_zoom_shot()
    expected = VALIDATE.expected_zoom_observation(shot)
    assert expected == expected_observation()

    item = {"observations": {"zoom_candidate": expected}}
    assert VALIDATE.validate_zoom_observation(item, shot) == []

    bad = json.loads(json.dumps(item))
    bad["observations"]["zoom_candidate"]["actionable"] = True
    errors = VALIDATE.validate_zoom_observation(bad, shot)
    assert len(errors) == 1
    assert errors[0]["message"] == "zoom_candidate observation mismatch"


@pytest.mark.parametrize("action_type", ["zoom_in", "zoom_out"])
def test_compiler_fails_closed_on_legacy_zoom_action(action_type):
    action = {"type": action_type, "compiler_hints": {"strength": "medium"}}
    ctx = {
        "duration_frames": 48,
        "fps": 24.0,
        "timeline_start_frame": 0,
        "source_clip": {"source_start_frame": 0},
    }
    with pytest.raises(RuntimeError, match="no source-backed editable zoom authority"):
        COMPILE.compile_main_operation(action, {}, ctx)


def test_compiler_propagates_zoom_observation_as_metadata_not_operation():
    analysis = {
        "job": {"job_id": "fixture", "fps": 24.0, "frame_count": 48},
        "summary": {"duration_seconds": 2.0},
        "timeline": {"shots": [analysis_zoom_shot()]},
    }
    zoom_observation = VALIDATE.expected_zoom_observation(analysis["timeline"]["shots"][0])
    speed_observation = VALIDATE.expected_speed_ramp_observation(analysis["timeline"]["shots"][0])
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
                "confidence": "medium",
                "priority_score": 0.57,
                "intent": "safe_cut_or_pacing_cut",
                "reason": "zoom candidate is metadata only",
                "compiler_hints": {
                    "strength": "normal",
                    "sync_to_beat": False,
                    "preferred_timing": "shot_boundary",
                },
            }],
            "observations": {
                "speed_ramp_candidate": speed_observation,
                "zoom_candidate": zoom_observation,
            },
        }],
    }
    validated = {"success": True, "edit_plan": edit_plan}
    commands = COMPILE.compile_timeline(validated, analysis)

    assert len(commands) == 1
    assert commands[0]["observations"]["zoom_candidate"] == zoom_observation
    assert commands[0]["action"]["type"] == "cut"
    assert all(op["operation"] != "transform_zoom" for op in commands[0]["operations"])


def test_reel1_cli_pipeline_emits_15_nonactionable_zoom_candidates_and_zero_zoom_ops(tmp_path: Path):
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
            str(ROOT / "scripts/planning/plan_edit.py"),
            "--analysis", str(analysis),
            "--output", str(plan_out),
            "--skip-llm",
        ],
        [
            sys.executable,
            str(ROOT / "scripts/planning/validate_edit_plan.py"),
            "--analysis", str(analysis),
            "--edit-plan", str(plan_out),
            "--output", str(validated_out),
        ],
        [
            sys.executable,
            str(ROOT / "scripts/planning/compile_generic_edit.py"),
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
        if item["observations"]["zoom_candidate"]["candidate"] is True
    ]
    assert len(plan["timeline"]) == 22
    assert len(candidates) == 15
    assert {item["shot_id"] for item in candidates} == {2,3,6,8,9,10,11,12,14,17,18,19,20,21,22}
    assert all(item["observations"]["zoom_candidate"]["actionable"] is False for item in candidates)
    assert all(item["observations"]["zoom_candidate"]["authority"] == "motion_heuristic_only" for item in candidates)
    assert all(item["observations"]["zoom_candidate"]["source"] == "motion_affine_scale_delta" for item in candidates)
    assert all(item["actions"][0]["type"] not in {"zoom_in", "zoom_out"} for item in plan["timeline"])

    assert validated["success"] is True
    counts = validated["timeline_stats"]["primary_action_counts"]
    assert counts.get("zoom_in", 0) == 0
    assert counts.get("zoom_out", 0) == 0
    assert counts.get("speed_ramp", 0) == 0

    zoom_ops = [
        op for command in generic["timeline"]
        for op in command.get("operations", [])
        if op.get("operation") == "transform_zoom"
    ]
    speed_ops = [
        op for command in generic["timeline"]
        for op in command.get("operations", [])
        if op.get("operation") == "speed_ramp"
    ]
    assert zoom_ops == []
    assert speed_ops == []
    assert sum(
        1 for command in generic["timeline"]
        if ((command.get("observations") or {}).get("zoom_candidate") or {}).get("candidate") is True
    ) == 15
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
    assert '"operation": "transform_zoom"' not in encoded
    assert '"operation": "speed_ramp"' not in encoded
    assert '"start_scale"' not in encoded
    assert '"end_scale"' not in encoded
    assert '"speed_multiplier"' not in encoded
    assert '"speed_percent"' not in encoded


def test_speed_candidate_precedence_and_observation_are_preserved():
    shot = slim_zoom_shot(
        speed_ramp_candidate=True,
        motion_intensity="high",
        cut_priority_score=0.8,
        beats_in_shot_count=2,
    )
    action = PLAN.expected_action_for_shot(shot)
    assert action["type"] == "cut"
    assert action["reason"] == (
        "speed_ramp_candidate retained as non-actionable motion observation; preserve source timing"
    )
    assert PLAN.build_speed_ramp_observation(shot)["actionable"] is False
    assert PLAN.build_zoom_observation(shot)["actionable"] is False
