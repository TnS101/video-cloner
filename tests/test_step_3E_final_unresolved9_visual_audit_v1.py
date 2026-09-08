from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "analysis" / "build_step_3E_final_unresolved9_visual_audit_v1.py"
VALIDATOR = ROOT / "scripts" / "analysis" / "validate_step_3E_final_unresolved9_visual_audit_v1.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


b = load(BUILDER, "test_final_unresolved9_builder")
v = load(VALIDATOR, "test_final_unresolved9_validator")


def test_adjacent_compounds_are_structural_and_generic():
    rows = [
        {"instance_id": "a", "canonical_text": "I"},
        {"instance_id": "b", "canonical_text": "was"},
        {"instance_id": "c", "canonical_text": "there"},
    ]
    spans = b.adjacent_compounds(rows, "b")
    assert {x["compact_text"] for x in spans} == {"iwas", "wasthere", "iwasthere"}
    assert all("sub_" not in json.dumps(x) for x in spans)


def test_compound_observations_require_exact_concatenation_and_confidence():
    spans = [{"member_ids": ["a", "b"], "member_texts": ["I", "was"], "compact_text": "iwas", "member_index": 1}]
    rows = [
        {"timeline_frame": 1, "text": "I was", "confidence": 0.99},
        {"timeline_frame": 2, "text": "I waz", "confidence": 0.99},
        {"timeline_frame": 3, "text": "I was", "confidence": 0.70},
    ]
    out = b.compound_observations(spans, rows)
    assert [x["timeline_frame"] for x in out] == [1]


def test_quarantine_is_generic_sparse_low_confidence_short_anchor_gate():
    vf = {"repair_instances": [
        {
            "instance_id": "x1", "canonical_text": "at", "tracking_basis": "sparse_semantic_anchor_plus_source_template_continuity",
            "source_anchor": {"method": "strict_exact_short_token_reanchor", "ocr_confidence": 0.74, "timeline_frame": 10},
            "visual_window": [8, 15],
        },
        {
            "instance_id": "x2", "canonical_text": "the", "tracking_basis": "source_semantic_ocr_temporal_consensus",
            "source_anchor": {"method": "strict_exact_short_token_reanchor", "ocr_confidence": 0.74, "timeline_frame": 20},
            "visual_window": [19, 22],
        },
        {
            "instance_id": "x3", "canonical_text": "to", "tracking_basis": "sparse_semantic_anchor_plus_source_template_continuity",
            "source_anchor": {"method": "strict_exact_short_token_reanchor", "ocr_confidence": 0.95, "timeline_frame": 30},
            "visual_window": [30, 32],
        },
        {
            "instance_id": "x4", "canonical_text": "word", "tracking_basis": "sparse_semantic_anchor_plus_source_template_continuity",
            "source_anchor": {"method": "strict_exact_short_token_reanchor", "ocr_confidence": 0.50, "timeline_frame": 40},
            "visual_window": [40, 45],
        },
    ]}
    out = b.sparse_short_anchor_quarantines(vf)
    assert [x["instance_id"] for x in out] == ["x1"]
    assert out[0]["cue_specific_rule"] is False


def test_negative_full_scan_never_becomes_source_absence():
    source = BUILDER.read_text(encoding="utf-8")
    assert '"source_absence_claimed": False' in source
    assert '"source_absence_claims_allowed": False' in source
    assert "source_not_materialized" not in source


def test_semantic_recovery_requires_pixel_tracking_support():
    source = BUILDER.read_text(encoding="utf-8")
    assert "track_exact_anchor" in source
    assert "strong_support" in source
    assert "SEMANTIC_MIN_SUPPORT" in source


def test_validator_rejects_absence_claim_and_missing_full_scan():
    row = {
        "instance_id": "x", "canonical_text": "x", "classification": "unresolved_after_full_visual_audit",
        "full_window_ocr_scan": True, "audit_window": [1, 3], "frames_scanned": 2,
        "transcript_timing_authority": False, "geometry_only_semantic_promotion": False,
        "negative_ocr_promoted_to_absence": False, "source_absence_claimed": True,
        "resolve_application_authorized": False, "source_materialized": None, "timing_status": "unresolved",
        "audit_evidence": {"negative_scan_is_not_absence": True},
    }
    authority = {
        "task_id": v.TASK_ID, "ok": True,
        "policy": {
            "all_residual_rows_receive_full_window_ocr_scan": True, "negative_ocr_promoted_to_absence": False,
            "source_absence_claims_allowed": False, "geometry_only_semantic_promotion": False,
            "transcript_timing_authority": False, "semantic_recovery_requires_source_pixel_continuity": True,
            "sparse_low_confidence_short_semantic_anchors_are_quarantined": True,
            "per_cue_hardcoded_overrides": False, "screenshot_specific_overrides": False,
            "resolve_modified": False, "repair_rollout_authorized": False, "offline_recovery_stops_after_this_boundary": True,
        },
        "audits": [dict(row, instance_id=f"x{i}") for i in range(9)],
        "repair_authority_quarantine": [{
            "instance_id": "q", "anchor_confidence": 0.7,
            "reason": "short_exact_identity_has_only_sparse_low_confidence_ocr_anchor", "cue_specific_rule": False,
            "final_rollout_action": "remove_or_do_not_materialize_semantic_textplus_until_multiframe_semantics_exist",
        }],
        "summary": {},
    }
    with pytest.raises(v.ValidationError, match="row_absence"):
        v.validate(authority)


def test_validator_accepts_zero_absence_as_integer_not_truthiness():
    summary = {"source_absent_claims": 0}
    v.exact_int(summary, "source_absent_claims", 0, "absence")
    for bad in ({}, {"source_absent_claims": False}, {"source_absent_claims": "0"}, {"source_absent_claims": 1}):
        with pytest.raises(v.ValidationError, match="absence"):
            v.exact_int(bad, "source_absent_claims", 0, "absence")


def test_real_accepted_inputs_have_exact_nine_residual_and_one_generic_quarantine():
    classification = ROOT / b.CLASSIFICATION
    vf_path = ROOT / b.VF
    if not classification.is_file() or not vf_path.is_file():
        pytest.skip("real accepted inputs unavailable")
    c = json.loads(classification.read_text(encoding="utf-8-sig"))
    vf = json.loads(vf_path.read_text(encoding="utf-8-sig"))
    residual = [x for x in c.get("classifications") or [] if x.get("classification") == "source_still_unresolved"]
    assert len(residual) == 9
    q = b.sparse_short_anchor_quarantines(vf)
    assert len(q) == 1
    assert q[0]["anchor_confidence"] < b.SHORT_ANCHOR_QUARANTINE_CONFIDENCE
    assert q[0]["cue_specific_rule"] is False


def test_production_code_has_no_residual_id_or_word_special_cases():
    source = BUILDER.read_text(encoding="utf-8")
    forbidden = ["sub_003", "sub_004", "sub_020", "sub_021", "sub_061", "sub_064", "sub_090", "sub_106", "sub_115"]
    assert not any(token in source for token in forbidden)


def test_real_input_hash_contract_is_current_and_source_video_present():
    required = [ROOT / b.CLASSIFICATION, ROOT / b.CLASSIFICATION_VALIDATION, ROOT / b.RECOVERY, ROOT / b.RECOVERY_VALIDATION, ROOT / b.VF, ROOT / b.VF_VALIDATION, ROOT / b.UNIVERSAL, ROOT / b.OCR_MODULE, ROOT / "input" / "DZsqH7auhjt.mp4"]
    if not all(x.is_file() for x in required):
        pytest.skip("real accepted inputs unavailable")
    c = b.load_json(ROOT / b.CLASSIFICATION)
    cv = b.load_json(ROOT / b.CLASSIFICATION_VALIDATION)
    r = b.load_json(ROOT / b.RECOVERY)
    rv = b.load_json(ROOT / b.RECOVERY_VALIDATION)
    vf = b.load_json(ROOT / b.VF)
    vfv = b.load_json(ROOT / b.VF_VALIDATION)
    u = b.load_json(ROOT / b.UNIVERSAL)
    source = b.verify_inputs(ROOT, c, cv, r, rv, vf, vfv, u)
    assert source.is_file()
    assert b.sha256(source) == b.EXPECTED_SOURCE_SHA256
