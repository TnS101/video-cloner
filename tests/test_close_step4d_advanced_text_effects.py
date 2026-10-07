import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/close_step4d_advanced_text_effects.py"
SPEC = importlib.util.spec_from_file_location("close_step4d", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_step4d_closure_pins_corrected_bookkeeping_without_runtime_changes():
    output = ROOT / ".pytest-tmp-step4d-freeze/unit"
    first = MODULE.build(output, "2026-09-28T18:30:00+03:00")
    assert first == MODULE.build(output, "2026-09-28T18:30:00+03:00")
    matrix = json.loads(first["step4d_effect_class_final_matrix.json"])
    capabilities = json.loads(first["step4d_deferred_required_capabilities.json"])
    validation = json.loads(first["step4d_final_closure_validation.json"])
    acceptance = json.loads(first["step4d_human_acceptance.json"])
    freeze = json.loads(first["__freeze_state__"])

    by_id = {row["id"]: row for row in capabilities["capabilities"]}
    required = {"CAPTION_CLIPPING_DETECTION_V2", "CAPTION_OCCLUSION_DETECTION_V2"}
    assert set(by_id) == required
    assert all(row["status"] == "DEFERRED_REQUIRED_CAPABILITY" for row in by_id.values())
    assert all(row["required_before"] == "FINAL_PARITY / RELEASE ACCEPTANCE" for row in by_id.values())
    assert matrix["classes"]["clipping"]["status"] == "UNSUPPORTED_WITH_CURRENT_EVIDENCE"
    assert matrix["classes"]["caption_occlusion"]["status"] == "UNSUPPORTED_WITH_CURRENT_EVIDENCE"
    assert set(matrix["long_term_product_capability_status"]) == required
    assert acceptance["human_decision"] == acceptance["step_4d_current_version_decision"] == "ACCEPT"
    assert freeze["step4d_final_status"] == "COMPLETE_HUMAN_ACCEPTED_FROZEN_CURRENT_VERSION"
    assert freeze["deferred_required_capabilities"] == ["CAPTION_CLIPPING_DETECTION_V2", "CAPTION_OCCLUSION_DETECTION_V2"]
    assert freeze["reopen_allowed_now"] is False
    assert validation["production_runtime_changed"] is validation["upstream_artifacts_changed"] is validation["resolve_mutated"] is False
    assert validation["step5_status"] == "UNBLOCKED_NOT_STARTED" and validation["step6_started"] is False
    assert validation["production_hardcoded_identities"] == []
