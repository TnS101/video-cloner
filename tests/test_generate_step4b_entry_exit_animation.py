import json
from pathlib import Path

from scripts.analysis.generate_step4b_entry_exit_animation import classify_boundary, generate


def point(frame, center=(0.5, 0.5), scale=100.0):
    return {"frame": frame, "center": list(center), "scale": scale, "source_frame": frame, "crop_sha256": str(frame)}


def test_boundary_taxonomy_is_fail_closed_and_boundary_local():
    stable_geometry = classify_boundary([point(10), point(12), point(14)], 10, 30, "entry")
    assert stable_geometry["type"] == "unresolved"
    assert stable_geometry["authority"] == "UNRESOLVED"
    assert stable_geometry["confidence"] == "low"
    assert stable_geometry["reason"] == "abrupt_visibility_transition_not_proven"

    slide = classify_boundary([
        point(10, (0.45, 0.5)), point(12, (0.5, 0.5)), point(14, (0.5, 0.5))
    ], 10, 30, "entry")
    assert slide["type"] == "slide"
    assert slide["parameters"]["property"] == "Center"

    scale = classify_boundary([
        point(10, scale=70), point(12, scale=100), point(14, scale=100)
    ], 10, 30, "entry")
    assert scale["type"] == "scale"
    assert scale["parameters"]["property"] == "Size"

    mixed = classify_boundary([
        point(10, (0.45, 0.5), 70), point(12), point(14)
    ], 10, 30, "entry")
    assert mixed["type"] == "unresolved"
    assert mixed["reason"] == "mixed_scale_and_slide_boundary_evidence"

    ongoing = classify_boundary([
        point(10, (0.45, 0.5)), point(12, (0.48, 0.5)), point(14, (0.5, 0.5))
    ], 10, 30, "entry")
    assert ongoing["type"] == "unresolved"
    assert ongoing["reason"] == "motion_not_localized_to_boundary"

    short = classify_boundary([point(10), point(11)], 10, 14, "entry")
    assert short["type"] == "unresolved"
    assert short["reason"] == "entry_exit_windows_overlap"


def test_actual_generation_accounts_for_all_identities_and_is_deterministic(tmp_path):
    output = tmp_path / "step4b"
    result = generate(output)
    contract = json.loads((output / "step4b_entry_exit_animation_contract.json").read_text())
    validation = json.loads((output / "step4b_entry_exit_validation.json").read_text())
    proof = json.loads((output / "determinism_proof.json").read_text())

    assert result["result"] == "PASS_STEP_4B_ENTRY_EXIT_ANIMATION_READY_FOR_HUMAN_REVIEW"
    assert len(contract["identities"]) == 113
    assert all("entry" in row and "exit" in row for row in contract["identities"])
    assert validation["identity_accounting"] == {"expected": 113, "produced": 113, "missing": [], "duplicates": 0}
    assert validation["boundary_timing"]["inside_frozen_intervals"] is True
    assert validation["static_artifacts_changed"] is False
    assert validation["step4a_timing_artifacts_changed"] is False
    assert validation["step4c_started"] is False
    assert validation["step4d_started"] is False
    assert validation["resolve_mutated"] is False
    assert validation["entry_results"]["abrupt"] == validation["exit_results"]["abrupt"] == 0
    assert validation["abrupt_evidence_correction"] == {
        "before": 25,
        "after": 0,
        "downgraded": 25,
        "entry_downgraded": 17,
        "exit_downgraded": 8,
        "surviving_abrupt_evidence": [],
    }
    assert proof["rerun_byte_identical"] is True
    assert (output / "step4b_entry_exit_review_diagnostic.jpg").stat().st_size > 0
