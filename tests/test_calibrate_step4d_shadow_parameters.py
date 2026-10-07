import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/calibrate_step4d_shadow_parameters.py"
SPEC = importlib.util.spec_from_file_location("step4d_shadow_parameters", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_shadow_parameter_calibration_is_bounded_deconfounded_and_fail_closed():
    artifacts = MODULE.build()
    calibrated = json.loads(artifacts["step4d_shadow_ir_calibrated.json"])
    fit = json.loads(artifacts["step4d_shadow_parameter_fit.json"])
    validation = json.loads(artifacts["step4d_shadow_parameter_validation.json"])
    review = json.loads(artifacts["step4d_shadow_parameter_human_review_data.json"])
    by_id = {row["source_identity"]: row for row in calibrated["shadows"]}

    assert validation["result"] == "PASS_STEP_4D_SHADOW_PARAMETER_FIDELITY_READY_FOR_HUMAN_REVIEW"
    assert validation["freeze_integrity"]["status"] == "PASS"
    assert validation["shadow_presence_authority_changed"] is False
    assert validation["positive_presence_unchanged"] is validation["negative_controls_unchanged"] is True
    assert validation["negative_control_parameter_authority_count"] == 0
    assert validation["font_geometry_deconfounded"] is validation["source_domain_fit_improved"] is True
    assert fit["method"]["font_renderer_used"] is False
    assert "unknown_contaminated_pixels" in fit["method"]["excluded"]
    positive = next(row for row in calibrated["shadows"] if row["presence_authority"] == "SOURCE_REQUIRED_SHADOW")
    assert positive["offset"]["authority"] == "BOUNDED_RANGE_ONLY"
    assert positive["offset"]["y_range_px"][0] > 5
    assert positive["softness"]["authority"] == "BOUNDED_RANGE_ONLY"
    assert positive["strength"]["alpha"] is None
    assert positive["color"]["isolated_color_authority"] == "UNRESOLVED"
    assert all(row["parameter_authority"] == "NONE_UPSTREAM_PRESENCE_GATE_FAILED" for row in calibrated["shadows"] if row is not positive)
    assert any(frame["excluded_unknown_pixel_count"] > 0 for case in fit["cases"] for frame in case["frame_fits"])
    assert validation["global_shadow_propagation"] is validation["general_mask_repair_added"] is validation["segmentation_system_added"] is False
    assert validation["production_hardcoded_identities"] == []
    assert validation["upstream_artifacts_changed"] is validation["resolve_mutated"] is validation["occlusion_started"] is validation["step5_started"] is validation["step6_started"] is False
    assert review["human_review_status"] == "PENDING"
    assert review["review_order"][0] == "DECONFOUNDED_SOURCE_GLYPH_SHADOW"
    placed = MODULE.place_mask(np.ones((3, 5), bool), (20, 30), np.pad(np.ones((8, 12), bool), ((6, 6), (9, 9))))
    assert placed.max() == 255 and np.count_nonzero(placed) > 0
