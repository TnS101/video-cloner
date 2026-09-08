from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "analysis" / "build_step_3E_unresolved_source_classification_v1.py"
VALIDATOR = ROOT / "scripts" / "analysis" / "validate_step_3E_unresolved_source_classification_v1.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


b = load(BUILDER, "test_unresolved_source_classification_builder")
v = load(VALIDATOR, "test_unresolved_source_classification_validator")


def test_compact_text_is_case_and_punctuation_insensitive():
    assert b.compact_text("DON'T.") == "dont"
    assert b.compact_text("to.") == "to"


def test_exact_anchor_candidates_are_strict_for_short_tokens():
    row = {
        "canonical_text": "at",
        "high_confidence_ocr_candidates": [
            {"timeline_frame": 1, "text": "at", "confidence": 0.94, "normalized_bbox": [0, 0, 1, 1]},
            {"timeline_frame": 2, "text": "at", "confidence": 0.96, "normalized_bbox": [0, 0, 1, 1]},
            {"timeline_frame": 3, "text": "dt", "confidence": 0.99, "normalized_bbox": [0, 0, 1, 1]},
        ],
    }
    out = b.exact_anchor_candidates(row)
    assert [(x["timeline_frame"], x["text"]) for x in out] == [(2, "at")]


def test_exact_anchor_candidates_accept_long_exact_identity_without_fuzzy_matching():
    row = {
        "canonical_text": "before",
        "high_confidence_ocr_candidates": [
            {"timeline_frame": 1, "text": "before", "confidence": 0.91, "normalized_bbox": [0, 0, 1, 1]},
            {"timeline_frame": 2, "text": "bef0re", "confidence": 0.99, "normalized_bbox": [0, 0, 1, 1]},
        ],
    }
    assert [x["timeline_frame"] for x in b.exact_anchor_candidates(row)] == [1]


def test_strongest_run_must_contain_semantic_anchor():
    rows = [
        {"timeline_frame": 1, "score": 0.9},
        {"timeline_frame": 2, "score": 0.9},
        {"timeline_frame": 4, "score": 0.95},
        {"timeline_frame": 5, "score": 0.95},
    ]
    assert [x["timeline_frame"] for x in b.strongest_consecutive_run_containing_anchor(rows, 5, 0.78)] == [4, 5]
    assert b.strongest_consecutive_run_containing_anchor(rows, 3, 0.78) == []


def test_absence_gate_requires_all_independent_signals():
    good = {
        "full_window_semantic_scan": True,
        "neighbor_sequence_closed": True,
        "unexplained_text_components": 0,
        "semantic_hits": 0,
    }
    assert b.absence_gate(good) is True
    for key in list(good):
        bad = dict(good)
        if key in ("full_window_semantic_scan", "neighbor_sequence_closed"):
            bad[key] = False
        else:
            bad[key] = 1
        assert b.absence_gate(bad) is False


def test_absence_gate_rejects_bool_as_integer_evidence():
    assert b.absence_gate({
        "full_window_semantic_scan": True,
        "neighbor_sequence_closed": True,
        "unexplained_text_components": False,
        "semantic_hits": 0,
    }) is False


def test_compound_membership_uses_accepted_exact_decomposition_only():
    vf = {"compound_ocr_decompositions": {
        "sub_b": {
            "applied": True,
            "identity_rule": "exact_compact_adjacent_concatenation",
            "member_ids": ["sub_a", "sub_b"],
            "member_texts": ["I", "was"],
            "source_frames": [10, 11],
            "source_ocr_texts": ["Iwas"],
        }
    }}
    out = b.compound_membership(vf, "sub_a")
    assert out["authority_instance_id"] == "sub_b"
    assert out["member_index"] == 0
    assert out["source_frames"] == [10, 11]


def test_validator_requires_exact_zero_absence_claims():
    summary = {"source_absent_claims": 0}
    v.exact_int(summary, "source_absent_claims", 0, "summary_absent")
    for bad in ({}, {"source_absent_claims": False}, {"source_absent_claims": "0"}, {"source_absent_claims": 1}):
        with pytest.raises(v.ValidationError, match="summary_absent"):
            v.exact_int(bad, "source_absent_claims", 0, "summary_absent")


def test_validator_rejects_absence_without_full_window_multisignal_evidence():
    row = {
        "instance_id": "sub_x",
        "canonical_text": "x",
        "classification": "source_not_materialized",
        "source_materialized": False,
        "transcript_timing_authority": False,
        "geometry_only_semantic_promotion": False,
        "negative_ocr_promoted_to_absence": False,
        "resolve_application_authorized": False,
        "absence_evidence": {
            "full_window_semantic_scan": False,
            "neighbor_sequence_closed": True,
            "unexplained_text_components": 0,
            "semantic_hits": 0,
        },
    }
    authority = {
        "task_id": v.TASK_ID,
        "ok": True,
        "policy": {
            "transcript_timing_authority": False,
            "geometry_only_semantic_promotion": False,
            "negative_ocr_promoted_to_absence": False,
            "sampled_negative_ocr_can_prove_absence": False,
            "source_not_materialized_requires_full_window_multi_signal_absence_gate": True,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "classifications": [row] * 22,
        "summary": {},
    }
    with pytest.raises(v.ValidationError, match="classification_ids|absence_full_scan"):
        v.validate(authority)


def test_real_accepted_inputs_classify_positive_source_evidence_when_available():
    recovery = ROOT / b.RECOVERY
    validation = ROOT / b.RECOVERY_VALIDATION
    vf_path = ROOT / b.VF
    video = ROOT / "input" / "DZsqH7auhjt.mp4"
    if not all(x.is_file() for x in (recovery, validation, vf_path, video)):
        pytest.skip("real integration inputs not available")
    out = ROOT / "artifacts" / "_test_unresolved_source_classification_v1.json"
    try:
        result = b.build(ROOT, out)
        assert result["summary"]["evaluated_remaining"] == 22
        assert result["summary"]["source_absent_claims"] == 0
        assert result["summary"]["source_semantic_track_recovered"] >= 1
        assert result["summary"]["source_compound_member_represented"] >= 1
        assert result["summary"]["source_still_unresolved"] < 22
        assert result["policy"]["transcript_timing_authority"] is False
        assert result["policy"]["negative_ocr_promoted_to_absence"] is False
        checks = v.validate(result)
        assert all(checks.values())
    finally:
        if out.exists():
            out.unlink()
