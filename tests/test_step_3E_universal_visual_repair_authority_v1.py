from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "analysis" / "visual_caption_repair_core.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_step_3E_universal_visual_repair_authority_v1.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = load(CORE_PATH, "visual_repair_core_test")
v = load(VALIDATOR_PATH, "visual_repair_validator_test")


def test_core_contains_no_reel_or_cue_identity():
    source = CORE_PATH.read_text(encoding="utf-8")
    assert "DZsqH7auhjt" not in source
    assert "sub_" not in source
    assert "graduated" not in source.lower()
    assert "already" not in source.lower()


def test_bbox_iou():
    assert c.bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert c.bbox_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def text_frame_two_words():
    frame = np.full((240, 360, 3), 90, dtype=np.uint8)
    # short left word
    for x in (70, 82):
        cv2.rectangle(frame, (x, 100), (x + 7, 126), (245, 245, 245), -1)
    # longer right word
    for x in (145, 157, 169, 181, 193, 205):
        cv2.rectangle(frame, (x, 100), (x + 7, 126), (245, 245, 245), -1)
    return frame


def test_text_geometry_repairs_phrase_sized_seed_for_single_glyph():
    geometry = c.normalise_text_geometry("Q", 316.0, 49.0)
    assert geometry["width_source"] == "text_height_aspect_repair"
    assert 12.0 <= geometry["expected_width_px"] <= 45.0
    assert geometry["expected_width_px"] < geometry["historic_width_px"] * 0.2


def test_text_geometry_keeps_compatible_historic_word_width():
    height = 32.0
    prior = c.text_width_prior_px("caption", height)
    geometry = c.normalise_text_geometry("caption", prior * 1.15, height)
    assert geometry["width_source"] == "historic_bbox_compatible"
    assert geometry["expected_width_px"] == pytest.approx(prior * 1.15, abs=1e-4)


def test_repaired_single_glyph_geometry_produces_source_candidates():
    frame = np.full((240, 360, 3), 75, dtype=np.uint8)
    cv2.putText(frame, "Q", (166, 126), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (245, 245, 245), 3, cv2.LINE_AA)
    geometry = c.normalise_text_geometry("Q", 300.0, 36.0)
    rows = c.frame_candidates(
        frame,
        [0.50, 0.46],
        geometry["expected_width_px"],
        geometry["expected_height_px"],
    )
    assert rows
    best = rows[0]["bbox"]
    assert best[2] - best[0] < 80


def test_frame_candidates_use_expected_width_to_separate_neighbour_words():
    frame = text_frame_two_words()
    short = c.frame_candidates(frame, [0.23, 0.47], 25, 28)
    long = c.frame_candidates(frame, [0.50, 0.47], 75, 28)
    assert short and long
    sw = short[0]["bbox"][2] - short[0]["bbox"][0]
    lw = long[0]["bbox"][2] - long[0]["bbox"][0]
    assert lw > sw


def test_tracking_prefers_same_region_over_neighbour_jump():
    rows = {
        10: [{"bbox": [10, 10, 40, 30], "base_score": 0.8}],
        11: [
            {"bbox": [100, 10, 130, 30], "base_score": 0.82},
            {"bbox": [11, 10, 41, 30], "base_score": 0.76},
        ],
        12: [{"bbox": [12, 10, 42, 30], "base_score": 0.74}],
    }
    tracked = c.track_candidate_series(rows, [10, 13])
    assert tracked[11]["bbox"][0] == 11


def test_visibility_rejects_single_early_noise_before_real_run():
    tracked = {
        1: {"base_score": 0.75, "bbox": [0, 0, 10, 10]},
        2: None,
        3: None,
        4: {"base_score": 0.62, "bbox": [0, 0, 10, 10]},
        5: {"base_score": 0.68, "bbox": [0, 0, 10, 10]},
        6: {"base_score": 0.64, "bbox": [0, 0, 10, 10]},
    }
    result = c.derive_visibility_window(tracked, [4, 7])
    assert result["ok"] is True
    assert result["window"] == [4, 7]


def test_static_jitter_collapses_to_exact_hold():
    tracked = {}
    for frame, dx, dy, dh in [(10, 0, 0, 0), (11, 1, -1, 1), (12, -1, 1, -1), (13, 0, 0, 0)]:
        tracked[frame] = {"bbox": [100 + dx, 80 + dy, 180 + dx, 110 + dy + dh], "base_score": 0.8}
    calibration = {"global_ratio": 0.0025, "font_ratios": {}}
    path, motion = c.stabilise_path(tracked, [10, 14], 360, 240, "Font", calibration)
    assert motion["position_model"] == "source_static_hold"
    assert motion["size_model"] == "source_static_hold"
    assert len({tuple(row["position_fusion"]) for row in path}) == 1
    assert len({row["application_size_candidate"] for row in path}) == 1
    assert {row["opacity_factor"] for row in path} == {1.0}


def test_real_linear_motion_is_preserved_without_raw_jitter():
    tracked = {}
    for frame in range(10, 16):
        x = 90 + (frame - 10) * 6
        tracked[frame] = {"bbox": [x, 80, x + 60, 110], "base_score": 0.8}
    calibration = {"global_ratio": 0.0025, "font_ratios": {}}
    path, motion = c.stabilise_path(tracked, [10, 16], 360, 240, "Font", calibration)
    assert motion["position_model"] == "source_linear_motion"
    assert path[-1]["position_fusion"][0] > path[0]["position_fusion"][0]
    assert motion["size_model"] == "source_static_hold"


def test_size_calibration_ignores_single_extreme_cue():
    seeds = [
        {"font_family": "A", "base_size": 0.08, "expected_height_px": 40},
        {"font_family": "A", "base_size": 0.082, "expected_height_px": 41},
        {"font_family": "A", "base_size": 0.079, "expected_height_px": 39},
        {"font_family": "Odd", "base_size": 0.32, "expected_height_px": 40},
    ]
    cal = c.build_size_calibration(seeds)
    size = c.calibrated_application_size("Odd", 40, cal)
    assert 0.06 < size < 0.11


def test_source_fill_sampling_uses_glyph_colour_not_border_background():
    frame = np.full((120, 180, 3), (180, 150, 120), dtype=np.uint8)
    cv2.putText(frame, "TEST", (35, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 220, 250), 3, cv2.LINE_AA)
    value, confidence = c.sample_fill_hex(frame, [28, 42, 150, 84])
    assert value
    assert confidence > 0.0
    # sampled colour must not collapse to the flat background colour
    assert value.lower() != "#7896b4"


def test_unmapped_script_text_uses_nearby_sequence_not_blocked_sibling():
    token = {
        "role": "decorative_script_layer",
        "visual_kind": "script",
        "font": {"font_family": "Some Script"},
        "style_lock": {"font_class": "high_contrast_script"},
        "visual_window": [50, 70],
        "source_pixel_anchor": {"source_bbox_px_540x960": [100, 100, 268, 200]},
        "display_text": "Sibling",
    }
    neighbours = [
        {"instance_id": "a", "canonical_text": "I", "visual_window": [40, 44]},
        {"instance_id": "b", "canonical_text": "was", "visual_window": [45, 52]},
        {"instance_id": "c", "canonical_text": "Sibling", "visual_window": [50, 65]},
    ]
    result = c.reconcile_unmapped_script_text(token, neighbours, blocked_texts=["Sibling"])
    assert result["ok"] is True
    assert result["text"] == "I was"
    assert result["source_instance_ids"] == ["a", "b"]


def test_non_script_unmapped_layer_is_not_guessed():
    token = {"role": "icon", "visual_kind": "glyph", "font": {}, "style_lock": {}, "display_text": "x"}
    result = c.reconcile_unmapped_script_text(token, [])
    assert result["ok"] is False
    assert result["method"] == "not_script_layer"


def test_validator_accepts_static_hold_semantics():
    row = {
        "instance_id": "x",
        "visual_window": [1, 3],
        "motion": {"position_model": "source_static_hold", "size_model": "source_static_hold", "opacity_model": "hold_no_synthetic_flicker"},
        "source_pixel_evidence": {"peak_bbox": [1, 1, 10, 10], "peak_score": 0.8},
        "frame_path": [
            {"timeline_frame": 1, "position_fusion": [0.5, 0.5], "application_size_candidate": 0.08, "opacity_factor": 1.0},
            {"timeline_frame": 2, "position_fusion": [0.5, 0.5], "application_size_candidate": 0.08, "opacity_factor": 1.0},
        ],
    }
    assert v.validate_frame_path(row) == 2


def test_validator_rejects_static_bounce():
    row = {
        "instance_id": "x",
        "visual_window": [1, 3],
        "motion": {"position_model": "source_static_hold", "size_model": "source_static_hold", "opacity_model": "hold_no_synthetic_flicker"},
        "source_pixel_evidence": {"peak_bbox": [1, 1, 10, 10], "peak_score": 0.8},
        "frame_path": [
            {"timeline_frame": 1, "position_fusion": [0.5, 0.5], "application_size_candidate": 0.08, "opacity_factor": 1.0},
            {"timeline_frame": 2, "position_fusion": [0.51, 0.5], "application_size_candidate": 0.08, "opacity_factor": 1.0},
        ],
    }
    with pytest.raises(v.ValidationError):
        v.validate_frame_path(row)


def test_validator_rejects_detector_score_as_flickering_alpha():
    row = {
        "instance_id": "x",
        "visual_window": [1, 2],
        "motion": {"position_model": "source_static_hold", "size_model": "source_static_hold", "opacity_model": "hold_no_synthetic_flicker"},
        "source_pixel_evidence": {"peak_bbox": [1, 1, 10, 10], "peak_score": 0.8},
        "frame_path": [{"timeline_frame": 1, "position_fusion": [0.5, 0.5], "application_size_candidate": 0.08, "opacity_factor": 0.7}],
    }
    with pytest.raises(v.ValidationError):
        v.validate_frame_path(row)


def test_ocr_source_presence_uses_observed_frames_not_cue_window_coverage():
    track = {
        "cue_id": "cue_a",
        "accepted_source_instance": False,
        "confidence": {
            "direct_ocr_frame_count": 3,
            "dense_observation_count": 3,
            "cue_window_coverage": 0.10,
            "median_text_similarity": 0.91,
            "median_ocr_confidence": 0.96,
        },
        "fallback_reasons": ["cue_window_coverage_below_0_45"],
        "frame_observations": [
            {"timeline_frame": 30, "normalized_bbox": [0.20, 0.30, 0.50, 0.36], "assignment_score": 0.84, "method": "ocr"},
            {"timeline_frame": 31, "normalized_bbox": [0.21, 0.31, 0.51, 0.37], "assignment_score": 0.91, "method": "ocr"},
            {"timeline_frame": 32, "normalized_bbox": [0.22, 0.32, 0.52, 0.38], "assignment_score": 0.88, "method": "ocr"},
        ],
    }
    result = c.ocr_source_presence(["cue_a"], {"cue_a": track}, 540, 960)
    assert result["status"] == "confirmed"
    assert result["window"] == [30, 33]
    assert result["selected_frames"] == [30, 31, 32]
    assert result["peak_frame"] == 31
    assert result["cue_window_coverage_used_as_authority"] is False


def test_ocr_source_presence_keeps_no_ocr_track_unresolved():
    track = {
        "cue_id": "cue_a",
        "confidence": {
            "direct_ocr_frame_count": 0,
            "dense_observation_count": 0,
            "cue_window_coverage": 0.0,
            "median_text_similarity": 0.0,
            "median_ocr_confidence": 0.0,
        },
        "fallback_reasons": ["no_direct_ocr_seed"],
        "frame_observations": [],
    }
    result = c.ocr_source_presence(["cue_a"], {"cue_a": track}, 540, 960)
    assert result["status"] == "unresolved"
    assert "no_direct_ocr_seed" in result["reasons"]
    assert "tracked" not in result


def test_ocr_source_presence_does_not_invent_semantics_for_uncovered_geometry():
    result = c.ocr_source_presence(["cue_a"], {}, 540, 960)
    assert result == {
        "status": "not_evaluated",
        "source_track_ids": [],
        "reasons": ["no_semantic_source_track"],
        "cue_window_coverage_used_as_authority": False,
    }


def test_validator_accepts_unresolved_only_when_excluded_from_repair():
    row = {
        "instance_id": "x",
        "presence_status": "source_unresolved",
        "repair_action": "exclude_from_repair",
        "transcript_timing_authority": False,
        "visual_timing_authority": "unresolved_source_presence",
        "visual_window": None,
        "source_pixel_evidence": {
            "evidence_kind": "semantic_presence_gate",
            "semantic_presence": {
                "status": "unresolved",
                "cue_window_coverage_used_as_authority": False,
            },
            "reasons": ["no_direct_ocr_seed"],
        },
        "frame_path": [],
    }
    status, repair_rows = v.validate_instance_row(row)
    assert status == "source_unresolved"
    assert repair_rows == 0


def test_validator_rejects_unresolved_row_if_it_gets_repair_path():
    row = {
        "instance_id": "x",
        "presence_status": "source_unresolved",
        "repair_action": "exclude_from_repair",
        "transcript_timing_authority": False,
        "visual_timing_authority": "unresolved_source_presence",
        "visual_window": None,
        "source_pixel_evidence": {
            "evidence_kind": "semantic_presence_gate",
            "semantic_presence": {
                "status": "unresolved",
                "cue_window_coverage_used_as_authority": False,
            },
            "reasons": ["no_direct_ocr_seed"],
        },
        "frame_path": [{"timeline_frame": 10}],
    }
    with pytest.raises(v.ValidationError):
        v.validate_instance_row(row)
