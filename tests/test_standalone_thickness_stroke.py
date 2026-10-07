from pathlib import Path

import cv2
import numpy as np

from scripts.standalone import video_cloner_font_inference as fonts
from scripts.standalone import video_cloner_thickness_stroke as inference


FONTS = Path(r"C:\Windows\Fonts")


def test_thickness_responds_to_controlled_width_and_real_bold_weight():
    thin = np.zeros((40, 40), dtype=bool)
    thick = np.zeros_like(thin)
    thin[5:35, 18:21] = True
    thick[5:35, 16:23] = True

    assert inference.measure_glyph_thickness(thick)["median_px"] > inference.measure_glyph_thickness(thin)["median_px"]
    regular = fonts.render_text_mask("sample", FONTS / "arial.ttf")
    bold = fonts.render_text_mask("sample", FONTS / "arialbd.ttf")
    assert inference.measure_glyph_thickness(bold)["median_px"] > inference.measure_glyph_thickness(regular)["median_px"]


def test_controlled_outline_is_detected_and_uniform_background_is_not():
    fill = np.zeros((90, 180), dtype=bool)
    fill[25:65, 55:125] = True
    background = np.full((90, 180, 3), (110, 120, 130), np.uint8)
    no_stroke = background.copy()
    no_stroke[fill] = (245, 245, 245)
    ring = cv2.dilate(fill.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & ~fill
    stroked = background.copy()
    stroked[ring] = (12, 20, 28)
    stroked[fill] = (245, 245, 245)

    detected = inference.detect_outline_observation(stroked, fill)
    absent = inference.detect_outline_observation(no_stroke, fill)

    assert detected["present"] is True
    assert 2 <= detected["width_px"] <= 5
    assert absent["present"] is False


def test_single_pixel_antialias_ring_is_not_promoted_to_stroke():
    fill = np.zeros((90, 180), dtype=bool)
    fill[25:65, 55:125] = True
    frame = np.full((90, 180, 3), (110, 120, 130), np.uint8)
    antialias = cv2.dilate(fill.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~fill
    frame[antialias] = (180, 185, 190)
    frame[fill] = (245, 245, 245)

    result = inference.detect_outline_observation(frame, fill)

    assert result["width_px"] == 1
    assert result["present"] is None
    assert result["reason"] == "anti_aliasing_background_or_shadow_ambiguity"


def test_unknown_pixels_never_create_positive_stroke_evidence():
    fill = np.zeros((90, 180), dtype=bool)
    fill[25:65, 55:125] = True
    frame = np.full((90, 180, 3), (110, 120, 130), np.uint8)
    ring = cv2.dilate(fill.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & ~fill
    frame[ring] = (12, 20, 28)
    frame[fill] = (245, 245, 245)

    result = inference.detect_outline_observation(frame, fill, unknown_mask=ring)

    assert result["present"] is not True
    assert result.get("unknown_edge_pixel_count", int(ring.sum())) > 0


def test_foreign_identity_projection_removes_false_stroke_authority():
    fill = np.zeros((90, 180), dtype=bool)
    fill[25:65, 55:125] = True
    frame = np.full((90, 180, 3), (110, 120, 130), np.uint8)
    foreign = cv2.dilate(fill.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & ~fill
    frame[foreign] = (245, 245, 245)
    frame[fill] = (20, 30, 40)
    projected = inference.project_bbox_to_crop((100, 200, 280, 290), (150, 220, 230, 270), fill.shape)
    ownership = inference.build_crop_ownership(fill, [foreign], [projected])

    raw = inference.detect_outline_observation(frame, fill)
    filtered = inference.detect_outline_observation(
        frame, fill, ownership["FOREIGN_IDENTITY"] | ownership["UNKNOWN_OR_OCCLUDED"],
    )

    assert raw["present"] is True
    assert filtered["present"] is not True
    assert not np.any(ownership["FOREIGN_IDENTITY"] & ownership["TARGET_OWNED"])
    assert not np.any(ownership["UNKNOWN_OR_OCCLUDED"] & ownership["TARGET_OWNED"])
    assert np.all(
        ownership["TARGET_OWNED"]
        | ownership["FOREIGN_IDENTITY"]
        | ownership["UNKNOWN_OR_OCCLUDED"]
        | ownership["USABLE_BACKGROUND"]
    )


def test_missing_structure_fails_closed():
    empty = np.zeros((20, 40), dtype=bool)

    result = inference.infer_thickness(
        empty, empty, "Regular", font_authority="NO_AUTHORITATIVE_FONT_RANKING",
        evidence_classification="INSUFFICIENT_EVIDENCE", mask_confidence=0.0,
    )

    assert result["status"] == "NO_AUTHORITATIVE_THICKNESS_INFERENCE"
    assert result["observed_visual_weight_category"] is None
    assert inference.aggregate_outline_observations([])["status"] == "NO_AUTHORITATIVE_STROKE_INFERENCE"
