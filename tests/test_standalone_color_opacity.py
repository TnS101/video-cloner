import cv2
import numpy as np

from scripts.standalone import video_cloner_color_opacity as inference


def _observation(foreground, alpha, background):
    foreground = np.asarray(foreground, dtype=float) / 255.0
    background = np.asarray(background, dtype=float) / 255.0
    observed = inference.linear_to_bt709(
        alpha * inference.bt709_to_linear(foreground)
        + (1.0 - alpha) * inference.bt709_to_linear(background)
    )
    return {
        "accepted": True,
        "fill_rgb": observed.tolist(),
        "background_rgb": background.tolist(),
        "trusted_fill_pixel_count": 100,
    }


def test_opaque_and_semitransparent_colors_are_recovered_in_linear_light():
    backgrounds = ([20, 40, 60], [90, 30, 120], [180, 150, 40], [30, 170, 150])
    foreground = [224, 92, 38]
    opaque = inference.infer_fill_color_opacity(_observation(foreground, 1.0, bg) for bg in backgrounds)
    translucent = inference.infer_fill_color_opacity(_observation(foreground, 0.7, bg) for bg in backgrounds)

    assert opaque["fill"]["status"] == "AUTHORITATIVE_FILL_COLOR"
    assert max(abs(a - b) for a, b in zip(opaque["fill"]["color_rgb"], foreground)) <= 1
    assert abs(opaque["opacity"]["opacity"] - 1.0) <= 0.01
    assert max(abs(a - b) for a, b in zip(translucent["fill"]["color_rgb"], foreground)) <= 1
    assert abs(translucent["opacity"]["opacity"] - 0.7) <= 0.01


def test_antialiased_boundary_does_not_reduce_opaque_style_opacity():
    mask = np.zeros((50, 90), np.uint8)
    mask[10:40, 25:65] = 1
    boundary = cv2.dilate(mask, np.ones((3, 3), np.uint8)).astype(bool) & ~mask.astype(bool)
    rows = []
    for background in ((20, 40, 60), (100, 20, 90), (180, 130, 20)):
        crop = np.full((50, 90, 3), background[::-1], np.uint8)
        crop[boundary] = np.rint((np.asarray(background[::-1]) + np.asarray((240, 240, 240))) / 2).astype(np.uint8)
        crop[mask.astype(bool)] = (240, 240, 240)
        rows.append(inference.sample_fill_observation(crop, mask))
    result = inference.infer_fill_color_opacity(rows)

    assert result["opacity"]["status"] == "AUTHORITATIVE_OPACITY"
    assert result["opacity"]["opacity"] >= 0.99


def test_foreign_and_unknown_pixels_are_excluded_from_fill_authority():
    mask = np.zeros((40, 80), bool)
    mask[8:32, 20:60] = True
    foreign = np.zeros_like(mask)
    foreign[8:32, 20:40] = True
    unknown = np.zeros_like(mask)
    unknown[8:32, 40:48] = True
    crop = np.full((40, 80, 3), (30, 30, 30), np.uint8)
    crop[mask] = (220, 220, 220)
    crop[foreign] = (0, 0, 255)
    crop[unknown] = (0, 255, 0)

    sample = inference.sample_fill_observation(crop, mask, foreign_mask=foreign, unknown_mask=unknown)

    assert sample["accepted"] is True
    assert sample["fill_rgb"] == [round(220 / 255, 8)] * 3
    assert sample["trusted_fill_pixel_count"] < int(mask.sum())


def test_single_background_is_explicitly_underdetermined():
    result = inference.infer_fill_color_opacity([_observation([240, 240, 240], 0.5, [30, 40, 50])])

    assert result["fill"]["status"] == "PROVISIONAL_FILL_COLOR"
    assert result["opacity"] == {
        "status": "NO_AUTHORITATIVE_OPACITY",
        "opacity": None,
        "reason": "insufficient_independent_background_variation",
    }


def test_stroke_color_respects_frozen_step2c_authority_ceiling():
    rows = [
        {"accepted": True, "stroke_rgb": [0.1, 0.2, 0.3], "stroke_pixel_count": 20},
        {"accepted": True, "stroke_rgb": [0.1, 0.2, 0.3], "stroke_pixel_count": 22},
    ]

    result = inference.infer_stroke_color(
        rows, upstream_status="PROVISIONAL_STROKE_INFERENCE", upstream_present=True,
    )

    assert result["status"] == "PROVISIONAL_STROKE_COLOR"
    assert result["color_rgb"] == [26, 51, 76]
    assert inference.infer_stroke_color([], upstream_status="PROVISIONAL_NO_STROKE_INFERENCE", upstream_present=False)["status"] == "NOT_APPLICABLE"
