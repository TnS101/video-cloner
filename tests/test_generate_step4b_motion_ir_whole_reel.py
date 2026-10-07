import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/generate_step4b_motion_ir_whole_reel.py"
SPEC = importlib.util.spec_from_file_location("step4b_whole", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)


def test_generic_safety_helpers():
    assert MODULE.boundary_intervals(10, 30) == {"entry": [10, 16], "exit": [23, 29]}
    assert MODULE.boundary_intervals(10, 13) == {"entry": [10, 10], "exit": [12, 12]}
    assert MODULE.merge_holds([[3, 5], [4, 6], [9, 10]]) == [[3, 6], [9, 10]]
    source = SCRIPT.read_text(encoding="utf-8")
    assert not __import__("re").search(r"\b(?:F\d+|caption_tracklet_\d+|continuous_visual_identity_\d+)\b", source)
    assert '"derived_label": "ABRUPT"' not in source


def test_weak_tracker_oscillation_cannot_become_authoritative_label():
    samples = []
    xs = [0.1, 0.14, 0.1, 0.14, 0.1, 0.14, 0.1]
    scores = [0.92, 0.25, 0.94, 0.25, 0.95, 0.96, 0.95]
    for frame, (x, score) in enumerate(zip(xs, scores)):
        samples.append({"frame": frame, "source_frame": frame, "position": {"x": x, "y": 0.5, "authority": "SOURCE_TEMPLATE_TRACK"}, "match_score": score, "relative_visibility": None, "scale": None, "rotation": None})
    row = {"control_id": "generic:entry", "identity": "generic", "boundary": "entry", "interval": [0, 7], "samples": samples, "features": MODULE.pilot.derive_features(samples), "channel_authority": {"position": "SOURCE_TEMPLATE_TRACK", "relative_visibility": "UNRESOLVED", "scale": "UNRESOLVED", "rotation": "UNSUPPORTED"}, "scale_gate": {"supported": False}}
    result = MODULE.normalize("generic", "", row)
    assert result["features"]["raw_oscillation_candidate"] is True
    assert result["features"]["semantic_oscillation_confidence"] == "LOW"
    assert result["derived_label"] != "CUSTOM_OSCILLATION"


def test_generated_whole_reel_contract(tmp_path):
    output = tmp_path / "whole"
    result = MODULE.generate(output)
    contract = json.loads((output / "step4b_whole_reel_motion_ir.json").read_text())
    validation = json.loads((output / "step4b_whole_reel_motion_ir_validation.json").read_text())
    summary = json.loads((output / "step4b_whole_reel_motion_ir_summary.json").read_text())
    diagnostic = json.loads((output / "step4b_whole_reel_review_sample.json").read_text())
    proof = json.loads((output / "determinism_proof.json").read_text())
    assert result["result"] == "PASS_STEP_4B_WHOLE_REEL_MOTION_IR_READY_FOR_HUMAN_REVIEW"
    assert len(contract["records"]) == 226
    assert summary["identity_accounting"] == {"duplicates": 0, "expected": 113, "missing": [], "produced": 113}
    assert summary["entry_exit_accounting"]["entry"] == summary["entry_exit_accounting"]["exit"] == 113
    assert all(row["reproduction_authority"] is False for row in contract["records"])
    assert all(set(row["channel_authority"]) == {"position", "relative_visibility", "scale", "rotation"} for row in contract["records"])
    assert all(row["interval"][0] >= next(t["source"]["visibility_intervals"][0][0] for t in MODULE.load(MODULE.TIMING_CONTRACT)["identities"] if t["identity"] == row["identity"]) for row in contract["records"])
    assert all(not (row["features"]["semantic_oscillation_confidence"] == "LOW" and row["derived_label"] == "CUSTOM_OSCILLATION") for row in contract["records"])
    assert all(row["derived_label"] is None for row in contract["records"] if row["static_no_motion"])
    assert validation["false_scale_gate"].startswith("PASS")
    assert validation["abrupt_regression_gate"].startswith("PASS")
    assert len(diagnostic["pilot_regression"]["controls"]) == 13
    assert all(row["match"] in {"YES", "PARTIAL"} for row in diagnostic["pilot_regression"]["controls"])
    assert validation["step4c_started"] is validation["resolve_mutated"] is False
    assert proof["rerun_byte_identical"] is True
