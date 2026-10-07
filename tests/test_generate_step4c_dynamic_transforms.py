import importlib.util
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/analysis/generate_step4c_dynamic_transforms.py"
SPEC=importlib.util.spec_from_file_location("step4c_dynamic",SCRIPT)
MODULE=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)


def test_channel_status_and_rotation_authority_are_fail_closed():
    samples=[{"frame":i,"position":{"x":.5+i*.003,"y":.5},"scale":None,"relative_visibility":None} for i in range(5)]
    row={"samples":samples,"channel_authority":{"position":"SOURCE_TEMPLATE_TRACK","scale":"UNRESOLVED","relative_visibility":"UNRESOLVED","rotation":"UNSUPPORTED"}}
    assert MODULE.channel_status(row,"position")=="DYNAMIC_SUPPORTED"
    assert MODULE.channel_status(row,"scale")=="UNRESOLVED"
    assert MODULE.feasibility.classify_rotation({"sample_count":4,"span_degrees":2.0,"correlation":.9,"linear_rmse_degrees":.5})=="DYNAMIC_ROTATION_SUPPORTED"
    assert MODULE.feasibility.classify_rotation({"sample_count":4,"span_degrees":.75,"correlation":.99,"linear_rmse_degrees":.01})=="STATIC_TILT_ONLY"


def test_generated_whole_reel_contract(tmp_path):
    output=tmp_path/"step4c"
    result=MODULE.generate(output)
    contract=json.loads((output/"step4c_dynamic_transform_contract.json").read_text())
    validation=json.loads((output/"step4c_dynamic_transform_validation.json").read_text())
    rotation=json.loads((output/"step4c_rotation_audit.json").read_text())
    adjudication=json.loads((output/"step4c_6000_rotation_adjudication.json").read_text())
    manifest=json.loads((output/"step4c_dynamic_transform_review_manifest.json").read_text())
    proof=json.loads((output/"determinism_proof.json").read_text())
    assert result["result"]=="PASS_STEP_4C_DYNAMIC_TRANSFORMS_READY_FOR_HUMAN_REVIEW"
    assert len(contract["records"])==113
    assert validation["summary"]["identity_accounting"]=={"expected":113,"produced":113,"missing":[],"duplicates":0}
    assert validation["summary"]["continuations"]["total"]==27
    assert validation["step4b_4c_continuity"]["ok"] is True
    assert validation["keyframes_inside_step4a_intervals"] is True
    assert validation["scale_gate"].startswith("UNCHANGED_CORROBORATED")
    assert validation["relative_visibility_semantics"].endswith("NOT_ABSOLUTE_ALPHA")
    assert validation["resolve_mutated"] is validation["step4d_started"] is False
    assert adjudication["regression_status"]=="PASS_STATIC_TILT_ONLY_PRESERVED"
    assert adjudication["dynamic_rotation_keyframes"]==[]
    assert rotation["gate"]=={"maximum_background_contamination":.20,"maximum_linear_rmse_degrees":.50,"minimum_absolute_frame_angle_correlation":.90,"minimum_samples":4,"minimum_angle_span_degrees":2.0}
    assert 10<=manifest["case_count"]<=15
    assert proof["rerun_byte_identical"] is True
    assert any(len(row["editor_neutral_keyframes"][channel]) for row in contract["records"] for channel in ("position","scale","rotation","relative_visibility"))
    for row in contract["records"]:
        start,end=row["visibility_interval"]
        assert all(start<=key["frame"]<end for values in row["editor_neutral_keyframes"].values() for key in values)
        if row["rotation"]["detector_verdict"]=="STATIC_TILT_ONLY": assert not row["editor_neutral_keyframes"]["rotation"]
    assert not re.search(r"\b(?:F\d+|caption_tracklet_\d+|continuous_visual_identity_\d+)\b",SCRIPT.read_text(encoding="utf-8"))
