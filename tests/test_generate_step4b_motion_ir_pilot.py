import json

from scripts.analysis.generate_step4b_motion_ir_pilot import derive_features, generate, scale_gate


def sample(frame, x, y, scale=None, visibility=None):
    return {"frame": frame, "position": {"x": x, "y": y}, "scale": {"value": scale} if scale is not None else None, "relative_visibility": {"value": visibility} if visibility is not None else None}


def test_generic_features_keep_channels_and_trajectory_shape():
    rows = [sample(0, 0.0, 0.0, 1.0, 0.2), sample(1, 0.1, 0.0, 1.3, 0.7), sample(2, 0.1, 0.0, 1.0, 1.0), sample(3, 0.05, 0.0, 1.0, 1.0)]
    features = derive_features(rows)
    assert features["overshoot"] is True
    assert features["hold_intervals"]
    assert features["direction_changes"] >= 1


def test_scale_requires_corroboration_and_rejects_bbox_only_change():
    glyph = {"mask_confidence": 0.8}
    observations = [
        {"timestamp": frame / 24, "bbox": [0, 0, size, size], "background_contamination": 0.01}
        for frame, size in [(1, 100), (2, 120), (3, 95)]
    ]
    rejected = scale_gate(glyph, observations, {1: 1.0, 2: 1.0, 3: 1.0}, 10000)
    assert rejected["supported"] is False
    accepted = scale_gate(glyph, observations, {1: 1.0, 2: 1.2, 3: 0.95}, 10000)
    assert accepted["supported"] is True


def test_actual_bounded_pilot_is_deterministic_and_preserves_freezes(tmp_path):
    output = tmp_path / "pilot"
    result = generate(__import__("pathlib").Path("tests/fixtures/step4b_motion_ir_controls.json"), output)
    pilot = json.loads((output / "step4b_motion_ir_pilot.json").read_text())
    validation = json.loads((output / "step4b_motion_ir_pilot_validation.json").read_text())
    proof = json.loads((output / "determinism_proof.json").read_text())
    assert result["result"] == "PASS_STEP_4B_BOUNDARY_LOCAL_MOTION_IR_PILOT_READY_FOR_HUMAN_REVIEW"
    assert validation["ok"] is True
    assert validation["identity_graph_count"] == 113
    assert validation["production_hardcoding"] == []
    assert validation["step4c_started"] is False
    assert validation["resolve_mutated"] is False
    assert proof["rerun_byte_identical"] is True
    assert all(sample["rotation"] is None for row in pilot["controls"] for sample in row.get("samples", []))
