from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/analysis/build_step_3E_visual_fidelity_authority_v2.py"
VALIDATOR = ROOT / "scripts/analysis/validate_step_3E_visual_fidelity_authority_v2.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


b = load(BUILDER, "visual_fidelity_v2_builder_test")
v = load(VALIDATOR, "visual_fidelity_v2_validator_test")


def obs(frame, text, source=None, conf=0.95, sim=1.0, bbox=(0.4, 0.4, 0.6, 0.45)):
    return {
        "timeline_frame": frame,
        "source_frame": frame,
        "normalized_bbox": list(bbox),
        "ocr_text": text,
        "ocr_source_text": source or text,
        "ocr_confidence": conf,
        "text_similarity": sim,
        "semantic_score": 0.9,
    }


def test_short_token_rejects_partial_semantic_match():
    rows = [obs(1, "t", source="T", sim=2 / 3)]
    assert not b.strict_anchor_ok("at", rows)
    rows.append(obs(2, "at", source="at"))
    assert b.strict_anchor_ok("at", rows)




def test_high_confidence_single_ocr_confusion_is_strict_semantic_match():
    assert b.strict_ocr_semantic_match("While", "Whlle", 0.923194)
    assert b.strict_anchor_ok("While", [obs(197, "whlle", source="Whlle", conf=0.923194, sim=0.8)])


def test_ocr_confusion_gate_does_not_relax_short_token_or_unrelated_word_identity():
    assert not b.strict_ocr_semantic_match("at", "a1", 0.99)
    assert not b.strict_ocr_semantic_match("While", "whole", 0.99)
    assert not b.strict_ocr_semantic_match("While", "Whlle", 0.70)


def test_real_sub007_prior_ocr_typo_is_semantically_accepted_when_inputs_are_available():
    tracks_path = ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json"
    if not tracks_path.is_file():
        pytest.skip("word-track integration input not present")
    import json
    doc = json.loads(tracks_path.read_text(encoding="utf-8-sig"))
    row = next(row for row in doc["tracks"] if row.get("cue_id") == "sub_007")
    observations = b.track_observations(row, "While")
    assert any(o.get("ocr_text") == "whlle" for o in observations)
    assert b.strict_anchor_ok("While", observations)


def test_source_case_consensus_preserves_visual_case_without_semantic_change():
    rows = [
        obs(1, "error", source="ERRON", conf=0.8, sim=0.8),
        obs(2, "error", source="ERROR", conf=0.95),
        obs(3, "error", source="ERROR", conf=0.94),
    ]
    result = b.source_case_consensus("error", rows)
    assert result["apply"] is True
    assert result["text"] == "ERROR"
    assert b.compact_text(result["text"]) == b.compact_text("error")


def test_weak_single_sample_font_family_falls_back_to_global_model():
    tokens = []
    for index in range(7):
        tokens.append({
            "visual_token_id": f"strong_{index}",
            "display_text": "sample",
            "role": "text",
            "visual_kind": "text",
            "font": {"font_family": "Strong", "font_style": "Bold"},
            "application_base_size_candidate": 0.1,
            "source_pixel_anchor": {"generated_height_px": 30, "generated_width_px": 110},
        })
    tokens.append({
        "visual_token_id": "weak",
        "display_text": "sample",
        "role": "text",
        "visual_kind": "text",
        "font": {"font_family": "Weak", "font_style": "Bold"},
        "application_base_size_candidate": 0.2,
        "source_pixel_anchor": {"generated_height_px": 20, "generated_width_px": 70},
    })
    model = b.build_render_calibration(tokens)
    weak = next(x for x in model["families"] if x["font_family"] == "Weak")
    assert weak["sample_count"] == 1
    assert weak["model_source"] == "global_fallback_weak_family"
    assert weak["height_px_per_size"] == pytest.approx(model["global"]["height_px_per_size"])


def test_dual_axis_size_caps_height_only_blowup():
    model = {"height_px_per_size": 260.0, "width_px_per_size_unit": 340.0, "model_source": "global"}
    result = b.source_size_to_application("margin", width_px=248, height_px=72, model=model)
    assert result["width_capped"] is True
    assert result["target_size"] < result["height_size"]
    assert result["target_size"] < 0.24


def synthetic_track(y_values, scores=None, height=30, x=200):
    scores = scores or [0.9] * len(y_values)
    rows = []
    for frame, (y, score) in enumerate(zip(y_values, scores), start=10):
        rows.append({
            "timeline_frame": frame,
            "score": score,
            "bbox_ref": [x - 50, y - height / 2, x + 50, y + height / 2],
        })
    return rows


def test_small_detector_drift_is_static_not_popup_motion():
    active = synthetic_track([200, 201, 200, 202, 201, 203, 202, 203, 204])
    result = b.classify_motion(active)
    assert result["position_model"] == "source_static_hold"
    assert result["size_model"] == "source_static_hold"


def test_coherent_late_drop_is_real_exit_motion():
    active = synthetic_track(
        [200, 200, 201, 200, 201, 202, 210, 225, 245, 270],
        scores=[0.95, 0.94, 0.95, 0.94, 0.93, 0.91, 0.82, 0.72, 0.58, 0.35],
        height=45,
    )
    result = b.classify_motion(active)
    assert result["exit_motion"] is True
    assert result["exit_axis"] == "y"
    assert result["position_model"] == "source_exit_trajectory"


def test_static_motion_path_collapses_source_jitter_to_hold():
    active = synthetic_track([200, 201, 200, 202, 201])
    metrics = b.classify_motion(active)
    path = b.motion_frame_path(active, metrics)
    ys = {row["position_top_origin"][1] for row in path}
    assert metrics["position_model"] == "source_static_hold"
    assert len(ys) == 1


def test_line_groups_require_real_temporal_overlap_and_same_source_line():
    rows = [
        {"instance_id": "a", "authorized": True, "visual_window": [10, 20], "median_source_bbox_ref": [100, 100, 160, 130]},
        {"instance_id": "b", "authorized": True, "visual_window": [12, 19], "median_source_bbox_ref": [170, 102, 230, 132]},
        {"instance_id": "c", "authorized": True, "visual_window": [21, 30], "median_source_bbox_ref": [170, 102, 230, 132]},
        {"instance_id": "d", "authorized": True, "visual_window": [12, 19], "median_source_bbox_ref": [170, 220, 230, 250]},
    ]
    groups = b.line_groups(rows)
    assert len(groups) == 1
    assert groups[0]["member_instance_ids"] == ["a", "b"]


def test_source_interior_fill_prefers_glyph_interior_over_outline():
    image = np.full((100, 200, 3), 140, dtype=np.uint8)
    # orange glyph with a dark outline
    image[35:65, 50:150] = (10, 10, 10)
    image[40:60, 58:142] = (80, 170, 250)  # BGR -> warm orange
    value, confidence = b.sample_interior_fill(image, [45, 30, 155, 70])
    assert value
    assert confidence > 0.15
    r = int(value[1:3], 16)
    assert r > 150


def test_occlusion_contract_requires_complete_foreground_assets():
    occlusion = {"ok": True}
    foreground = {
        "ok": True,
        "summary": {"ready_for_v4_import": True},
        "asset_spans": [{"complete": True, "affected_cue_ids": ["sub_x"]}],
    }
    result = b.validate_occlusion(occlusion, foreground)
    assert result["enabled"] is True
    assert result["required_layer_order"] == "foreground_rgba_above_textplus"
    assert result["persistent_readback_required"] is True


def test_case_update_never_changes_semantic_text():
    result = b.source_case_consensus("Follow", [obs(1, "follow", source="FOLLOW")])
    assert b.compact_text(result["text"]) == b.compact_text("Follow")



def test_template_anchor_uses_same_full_frame_preprocessing_context():
    image = np.full((b.REF_HEIGHT, b.REF_WIDTH, 3), 130, dtype=np.uint8)
    x0, y0, x1, y1 = 220, 400, 320, 450
    cv2.rectangle(image, (x0, y0), (x1 - 1, y1 - 1), (245, 245, 245), -1)
    cv2.line(image, (x0, y0), (x1 - 1, y1 - 1), (20, 20, 20), 4)

    class StaticVideo:
        def read_ref(self, timeline_frame):
            return image.copy()

    bbox = [x0 / b.REF_WIDTH, y0 / b.REF_HEIGHT, x1 / b.REF_WIDTH, y1 / b.REF_HEIGHT]
    track = b.template_track(StaticVideo(), 10, bbox, [10, 11])
    assert track["anchor_score"] >= 0.999


def test_real_sub007_template_anchor_self_matches_when_inputs_are_available():
    video_path = ROOT / "input/DZsqH7auhjt.mp4"
    tracks_path = ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json"
    if not video_path.is_file() or not tracks_path.is_file():
        pytest.skip("source integration inputs not present")
    import json
    doc = json.loads(tracks_path.read_text(encoding="utf-8-sig"))
    row = next(row for row in doc["tracks"] if row.get("cue_id") == "sub_007")
    observations = b.track_observations(row, "While")
    anchor = b.best_anchor("While", observations)
    assert anchor is not None
    video = b.VideoSource(video_path)
    try:
        track = b.template_track(
            video,
            int(anchor["timeline_frame"]),
            anchor["normalized_bbox"],
            [int(anchor["timeline_frame"]), int(anchor["timeline_frame"]) + 1],
        )
    finally:
        video.close()
    assert track["anchor_score"] >= 0.999

def test_template_active_run_uses_hysteresis_around_anchor():
    track = {
        "rows": [
            {"timeline_frame": 8, "score": 0.2},
            {"timeline_frame": 9, "score": 0.33},
            {"timeline_frame": 10, "score": 1.0},
            {"timeline_frame": 11, "score": 0.8},
            {"timeline_frame": 12, "score": 0.5},
            {"timeline_frame": 13, "score": 0.31},
            {"timeline_frame": 14, "score": 0.1},
        ]
    }
    active = b.active_template_run(track, 10)
    assert [row["timeline_frame"] for row in active] == [9, 10, 11, 12, 13]




def test_compound_ocr_decomposition_recovers_short_member_from_exact_adjacent_merge():
    ordered = ["sub_a", "sub_b", "sub_c"]
    canonical = {"sub_a": "I", "sub_b": "was", "sub_c": "ready"}
    rows = [
        obs(10, "iwas", source="Iwas", conf=0.99, sim=0.85, bbox=(0.30, 0.40, 0.70, 0.46)),
        obs(11, "iwas", source="Iwas", conf=0.98, sim=0.85, bbox=(0.30, 0.40, 0.70, 0.46)),
    ]
    assert not b.strict_anchor_ok("was", rows)
    enriched, evidence = b.compound_ocr_decompose_observations("sub_b", rows, ordered, canonical)
    assert evidence["applied"] is True
    assert evidence["member_ids"] == ["sub_a", "sub_b"]
    assert b.strict_anchor_ok("was", enriched)
    segments = [row for row in enriched if row.get("candidate_kind") == "ocr_compound_segment"]
    assert len(segments) == 2
    assert all(row["ocr_text"] == "was" for row in segments)
    assert all(row["ocr_source_text"] == "was" for row in segments)
    assert all(row["normalized_bbox"][0] > 0.30 for row in segments)
    assert all(row["normalized_bbox"][2] == pytest.approx(0.70) for row in segments)


def test_compound_ocr_decomposition_requires_exact_concat_and_multi_frame_source_consensus():
    ordered = ["left", "target"]
    canonical = {"left": "I", "target": "was"}
    one_frame = [obs(10, "iwas", source="Iwas", conf=0.99, sim=0.85)]
    enriched, evidence = b.compound_ocr_decompose_observations("target", one_frame, ordered, canonical)
    assert evidence["applied"] is False
    assert not b.strict_anchor_ok("was", enriched)

    unrelated = [
        obs(10, "logoat", source="logoat", conf=0.99, sim=0.85),
        obs(11, "logoat", source="logoat", conf=0.99, sim=0.85),
    ]
    enriched, evidence = b.compound_ocr_decompose_observations("target", unrelated, ordered, canonical)
    assert evidence["applied"] is False
    assert not b.strict_anchor_ok("was", enriched)


def test_real_sub100_iwas_compound_source_observations_are_decomposed_when_inputs_are_available():
    semantic_path = ROOT / "artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_v1.json"
    universal_path = ROOT / "artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/universal_visual_repair_authority_v1.json"
    if not semantic_path.is_file() or not universal_path.is_file():
        pytest.skip("semantic integration inputs not present")
    import json
    semantic = json.loads(semantic_path.read_text(encoding="utf-8-sig"))
    universal = json.loads(universal_path.read_text(encoding="utf-8-sig"))
    coverage = {row["instance_id"]: row for row in semantic["coverage"]}
    ordered = [row["instance_id"] for row in universal["instances"]]
    canonical = {
        row["instance_id"]: str(row.get("canonical_text") or coverage.get(row["instance_id"], {}).get("canonical_text") or "")
        for row in universal["instances"]
    }
    rows = coverage["sub_100"]["semantic_observations"]
    assert {b.compact_text(row["ocr_source_text"]) for row in rows} == {"iwas"}
    assert not b.strict_anchor_ok("was", rows)
    enriched, evidence = b.compound_ocr_decompose_observations("sub_100", rows, ordered, canonical)
    assert evidence["applied"] is True
    assert evidence["member_ids"] == ["sub_099", "sub_100"]
    assert b.strict_anchor_ok("was", enriched)
    segments = [row for row in enriched if row.get("candidate_kind") == "ocr_compound_segment"]
    assert len(segments) == 2
    assert all(row["normalized_bbox"][0] > 0.38888889 for row in segments)
    assert all(row["normalized_bbox"][2] == pytest.approx(0.60888889) for row in segments)


def test_validator_policy_requires_rollout_lock_and_source_only_timing():
    # This is a contract smoke test; the full artifact is produced by Luna with PaddleOCR.
    assert v.TASK_ID == b.TASK_ID
    assert v.EXPECTED_REPAIR == 74
    assert v.EXPECTED_PHYSICAL == 114



def test_semantic_observation_run_keeps_adjacent_words_separate():
    follow = [obs(874, "follow", source="Follow"), obs(876, "follow", source="Follow"), obs(878, "follow", source="Follow"), obs(880, "follow", source="Follow"), obs(882, "follow", source="Follow")]
    along = [obs(883, "along"), obs(885, "along"), obs(886, "along")]
    follow_run = b.semantic_observation_run("Follow", follow, 880)
    along_run = b.semantic_observation_run("along", along, 885)
    follow_dense = b.dense_track_from_observations(follow_run)
    along_dense = b.dense_track_from_observations(along_run)
    assert follow_dense[-1]["timeline_frame"] < along_dense[0]["timeline_frame"]


def test_real_source_protected_something_exit_is_detected_when_inputs_are_available():
    video_path = ROOT / "input/DZsqH7auhjt.mp4"
    v4_path = ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
    if not video_path.is_file() or not v4_path.is_file():
        pytest.skip("source integration inputs not present")
    import json
    doc = json.loads(v4_path.read_text(encoding="utf-8-sig"))
    token = next(token for group in doc["groups"] for token in group["tokens"] if token.get("visual_token_id") == "vf_07_something")
    anchor = token["source_pixel_anchor"]
    video = b.VideoSource(video_path)
    try:
        track = b.template_track(
            video,
            int(anchor["reference_frame"]),
            b.normalized_bbox(anchor["source_bbox_px_540x960"], b.REF_WIDTH, b.REF_HEIGHT),
            [int(token["visual_window"][0]), int(token["visual_window"][1]) + 2],
        )
        active = b.active_template_run(track, int(anchor["reference_frame"]))
        motion = b.classify_motion(active)
    finally:
        video.close()
    assert motion["exit_motion"] is True
    assert motion["exit_axis"] == "y"
    assert motion["exit_direction_top_origin"] == "down"
    assert motion["position_model"] == "source_exit_trajectory"


def test_real_semantic_follow_and_along_source_windows_do_not_overlap_when_inputs_are_available():
    semantic_path = ROOT / "artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_v1.json"
    if not semantic_path.is_file():
        pytest.skip("semantic integration input not present")
    import json
    doc = json.loads(semantic_path.read_text(encoding="utf-8-sig"))
    by_id = {row["instance_id"]: row for row in doc["coverage"]}
    follow = by_id["sub_112"]
    along = by_id["sub_113"]
    follow_anchor = b.best_anchor(follow["canonical_text"], follow["semantic_observations"])
    along_anchor = b.best_anchor(along["canonical_text"], along["semantic_observations"])
    follow_run = b.semantic_observation_run(follow["canonical_text"], follow["semantic_observations"], follow_anchor["timeline_frame"])
    along_run = b.semantic_observation_run(along["canonical_text"], along["semantic_observations"], along_anchor["timeline_frame"])
    assert max(int(row["timeline_frame"]) for row in follow_run) < min(int(row["timeline_frame"]) for row in along_run)



def test_semantic_observation_run_bridges_sparse_source_ocr_gap_without_transcript_timing():
    rows = [
        obs(147, "graduated", source="graduated"),
        obs(150, "graduated", source="graduated"),
        obs(158, "graduated", source="gradated", sim=0.94),
        obs(168, "graduated", source="gradated", sim=0.94),
    ]
    run = b.semantic_observation_run("graduated", rows, 147)
    assert [row["timeline_frame"] for row in run] == [147, 150, 158, 168]


def test_real_sparse_development_anchor_extends_by_source_template_when_inputs_are_available():
    video_path = ROOT / "input/DZsqH7auhjt.mp4"
    semantic_path = ROOT / "artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_v1.json"
    if not video_path.is_file() or not semantic_path.is_file():
        pytest.skip("source integration inputs not present")
    import json
    doc = json.loads(semantic_path.read_text(encoding="utf-8-sig"))
    row = next(row for row in doc["coverage"] if row.get("instance_id") == "sub_029")
    anchor = b.best_anchor(row["canonical_text"], row["semantic_observations"])
    semantic_run = b.semantic_observation_run(row["canonical_text"], row["semantic_observations"], int(anchor["timeline_frame"]))
    assert len(semantic_run) == 1
    search = row["search_prior"]["source_pixel_search_window"]
    video = b.VideoSource(video_path)
    try:
        track = b.template_track(video, int(anchor["timeline_frame"]), anchor["normalized_bbox"], [int(search[0]) - 2, int(search[1]) + 2])
        active = b.active_template_run(track, int(anchor["timeline_frame"]))
    finally:
        video.close()
    assert active[0]["timeline_frame"] < int(anchor["timeline_frame"])
    assert active[-1]["timeline_frame"] > int(anchor["timeline_frame"])
    assert len(active) >= 8
