from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "analysis" / "build_step_3E_unresolved_visual_layer_recovery_v1.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_step_3E_unresolved_visual_layer_recovery_v1.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


b = load_module(BUILDER_PATH, "test_unresolved_recovery_builder")
v = load_module(VALIDATOR_PATH, "test_unresolved_recovery_validator")


def test_member_spans_are_adjacent_only():
    class V2:
        compact_text = staticmethod(lambda x: "".join(ch for ch in str(x).lower() if ch.isalnum()))
    ids = ["a", "b", "c", "d"]
    canonical = {"a": "closing", "b": "deals", "c": "I", "d": "built"}
    spans = b.member_spans("b", ids, canonical, V2)
    assert {tuple(row["member_instance_ids"]) for row in spans} == {("a", "b"), ("b", "c"), ("a", "b", "c"), ("b", "c", "d")}


def test_partition_bbox_uses_member_width_units():
    class V2:
        token_units = staticmethod(lambda x: 1.0 if x == "I" else 3.0)
    box = b.partition_bbox_for_member([0.1, 0.2, 0.9, 0.4], ["a", "b"], "a", {"a": "I", "b": "built"}, V2)
    assert box == pytest.approx([0.1, 0.2, 0.3, 0.4])


def test_semantic_recovery_requires_two_frames():
    class V2:
        strict_ocr_semantic_match = staticmethod(lambda c, o, conf: str(c).lower() == str(o).lower() and conf >= 0.8)
        compact_text = staticmethod(lambda x: str(x).lower())
        token_units = staticmethod(lambda x: 1.0)
    one = [{"timeline_frame": 1, "ocr_text": "word", "ocr_confidence": 0.9, "normalized_bbox": [0, 0, 1, 1]}]
    assert b.semantic_recovery("b", "word", one, ["a", "b", "c"], {"a": "x", "b": "word", "c": "y"}, V2) is None
    two = one + [{"timeline_frame": 2, "ocr_text": "word", "ocr_confidence": 0.91, "normalized_bbox": [0, 0, 1, 1]}]
    out = b.semantic_recovery("b", "word", two, ["a", "b", "c"], {"a": "x", "b": "word", "c": "y"}, V2)
    assert out["classification"] == "source_semantic_recovered"
    assert out["support"] == 2


def test_compound_recovery_requires_exact_concat_and_partitions():
    class V2:
        strict_ocr_semantic_match = staticmethod(lambda c, o, conf: False)
        compact_text = staticmethod(lambda x: "".join(ch for ch in str(x).lower() if ch.isalnum()))
        token_units = staticmethod(lambda x: float(len(str(x))))
    rows = [
        {"timeline_frame": 10, "ocr_text": "closing deals", "ocr_confidence": 0.94, "normalized_bbox": [0.1, 0.2, 0.9, 0.3]},
        {"timeline_frame": 11, "ocr_text": "closing deals", "ocr_confidence": 0.95, "normalized_bbox": [0.1, 0.2, 0.9, 0.3]},
    ]
    out = b.semantic_recovery("b", "deals", rows, ["a", "b", "c"], {"a": "closing", "b": "deals", "c": "I"}, V2)
    assert out["classification"] == "source_compound_semantic_recovered"
    assert out["member_instance_ids"] == ["a", "b"]
    assert all(row["normalized_bbox"] != row["full_compound_normalized_bbox"] for row in out["observations"])


def test_compound_recovery_rejects_one_frame():
    class V2:
        strict_ocr_semantic_match = staticmethod(lambda c, o, conf: False)
        compact_text = staticmethod(lambda x: "".join(ch for ch in str(x).lower() if ch.isalnum()))
        token_units = staticmethod(lambda x: 1.0)
    rows = [{"timeline_frame": 10, "ocr_text": "closing deals", "ocr_confidence": 0.99, "normalized_bbox": [0, 0, 1, 1]}]
    assert b.semantic_recovery("b", "deals", rows, ["a", "b"], {"a": "closing", "b": "deals"}, V2) is None


def test_prototype_library_only_accepts_visual_only_text_decorations():
    class V2:
        compact_text = staticmethod(lambda x: str(x).lower())
    v4 = {"groups": [{"tokens": [
        {"visual_token_id": "p1", "display_text": "I", "visual_kind": "visual_only_text_decoration", "role": "decorative_script_layer", "source_pixel_anchor": {"reference_frame": 10, "source_bbox_px_540x960": [1, 2, 11, 22]}, "font": {"font_family": "Example"}, "style_lock": {"fill": "#fff"}},
        {"visual_token_id": "p2", "display_text": "word", "visual_kind": "caption", "source_pixel_anchor": {"reference_frame": 10, "source_bbox_px_540x960": [1, 2, 11, 22]}},
    ]}]}
    rows = b.accepted_visual_prototypes(v4, V2)
    assert [row["prototype_id"] for row in rows] == ["p1"]


def test_strongest_consecutive_run_does_not_bridge_gaps():
    rows = [
        {"timeline_frame": 1, "score": 0.7},
        {"timeline_frame": 2, "score": 0.7},
        {"timeline_frame": 4, "score": 0.9},
        {"timeline_frame": 5, "score": 0.9},
        {"timeline_frame": 6, "score": 0.9},
    ]
    out = b.strongest_consecutive_run(rows, 0.6)
    assert [row["timeline_frame"] for row in out] == [4, 5, 6]


def test_validator_rejects_negative_ocr_as_absence():
    authority = {
        "task_id": v.TASK_ID,
        "ok": True,
        "policy": {
            "transcript_timing_authority": False,
            "geometry_only_semantic_promotion": False,
            "negative_ocr_promoted_to_absence": True,
            "per_cue_hardcoded_overrides": False,
            "screenshot_specific_overrides": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
    }
    with pytest.raises(v.ValidationError, match="negative_absence"):
        v.validate(authority)


def test_validator_rejects_weak_visual_companion():
    rows = []
    for i in range(23):
        row = {
            "instance_id": f"sub_{i:03d}",
            "canonical_text": "x",
            "transcript_timing_authority": False,
            "resolve_application_authorized": False,
            "classification": "source_unresolved_after_recovery",
            "negative_ocr_promoted_to_absence": False,
            "semantic_promotion": False,
        }
        rows.append(row)
    rows[0] = {
        "instance_id": "sub_000",
        "canonical_text": "I",
        "transcript_timing_authority": False,
        "resolve_application_authorized": False,
        "classification": "source_visual_companion_recovered",
        "basis": "accepted_v4_visual_only_source_template_multiframe",
        "semantic_promotion": False,
        "support": 3,
        "peak_match_score": 0.69,
        "prototype_self_score": 1.0,
        "prototype_id": "p",
        "frame_path": [{}, {}, {}],
    }
    authority = {
        "task_id": v.TASK_ID,
        "ok": True,
        "policy": {
            "transcript_timing_authority": False,
            "geometry_only_semantic_promotion": False,
            "negative_ocr_promoted_to_absence": False,
            "per_cue_hardcoded_overrides": False,
            "screenshot_specific_overrides": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "classifications": rows,
        "summary": {"evaluated_unresolved": 23, "source_visual_companion_recovered": 1, "source_absent_claims": 0, "structural_total": 117, "physical_textplus_before_merge": 114, "resolve_modified": False, "repair_rollout_authorized": False},
        "semantic_sha256": "0" * 64,
    }
    with pytest.raises(v.ValidationError, match="companion_peak"):
        v.validate(authority)


def test_exact_zero_summary_field_is_valid():
    v.require_exact_int_field({"source_absent_claims": 0}, "source_absent_claims", 0, "summary_absent")


def test_exact_zero_summary_field_rejects_missing_bool_string_and_nonzero():
    for summary in ({}, {"source_absent_claims": False}, {"source_absent_claims": "0"}, {"source_absent_claims": 1}):
        with pytest.raises(v.ValidationError, match="summary_absent"):
            v.require_exact_int_field(summary, "source_absent_claims", 0, "summary_absent")

def test_real_source_prototype_transfer_recovers_only_one_unresolved_i_when_inputs_available():
    vf_path = ROOT / b.VF
    sem_path = ROOT / b.SEMANTIC
    uni_path = ROOT / b.UNIVERSAL
    v4_path = ROOT / b.V4
    video_path = ROOT / "input" / "DZsqH7auhjt.mp4"
    v2_path = ROOT / b.V2_BUILDER
    if not all(p.is_file() for p in (vf_path, sem_path, uni_path, v4_path, video_path, v2_path)):
        pytest.skip("real source integration inputs not present")
    vf = json.loads(vf_path.read_text(encoding="utf-8-sig"))
    sem = json.loads(sem_path.read_text(encoding="utf-8-sig"))
    uni = json.loads(uni_path.read_text(encoding="utf-8-sig"))
    v4 = json.loads(v4_path.read_text(encoding="utf-8-sig"))
    v2 = load_module(v2_path, "test_recovery_v2_dependency")
    prototypes = b.accepted_visual_prototypes(v4, v2)
    repairs = {r["instance_id"]: r for r in vf["repair_instances"]}
    ordered = [r["instance_id"] for r in uni["instances"]]
    unresolved_i = [r for r in sem["coverage"] if r.get("coverage_status") == "source_unresolved" and v2.compact_text(r.get("canonical_text")) == "i"]
    video = b.VideoSource(video_path)
    recovered = []
    try:
        for row in unresolved_i:
            prior = row.get("search_prior") or {}
            window = prior.get("source_pixel_search_window")
            frames = list(range(int(window[0]), int(window[1]))) if isinstance(window, list) and len(window) == 2 else sorted(set(int(x) for x in prior.get("probe_frames") or []))
            ctx = b.nearest_anchor_context(row["instance_id"], ordered, repairs)
            out = b.prototype_recovery(row["instance_id"], row["canonical_text"], prototypes, frames, ctx, video, v2)
            if out is not None:
                recovered.append((row["instance_id"], out))
    finally:
        video.close()
    assert len(recovered) == 1
    assert recovered[0][1]["support"] >= 3
    assert recovered[0][1]["peak_match_score"] >= 0.70
    assert recovered[0][1]["semantic_promotion"] is False
