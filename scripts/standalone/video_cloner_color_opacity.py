from __future__ import annotations

from typing import Iterable

import cv2
import numpy as np


# The source is 8-bit BT.709. These bounds are expressed in decoded code values:
# eight levels must separate backgrounds; six levels is the authoritative residual.
MIN_BACKGROUND_DELTA = 8.0 / 255.0
AUTHORITATIVE_RESIDUAL = 6.0 / 255.0
PROVISIONAL_RESIDUAL = 12.0 / 255.0


def bt709_to_linear(rgb: np.ndarray) -> np.ndarray:
    value = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    return np.where(value < 0.081, value / 4.5, ((value + 0.099) / 1.099) ** (1.0 / 0.45))


def linear_to_bt709(rgb: np.ndarray) -> np.ndarray:
    value = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    return np.where(value < 0.018, value * 4.5, 1.099 * value**0.45 - 0.099)


def trusted_fill_core(
    fill_mask: np.ndarray,
    foreign_mask: np.ndarray | None = None,
    unknown_mask: np.ndarray | None = None,
) -> np.ndarray:
    fill = np.asarray(fill_mask, dtype=bool)
    foreign = np.zeros_like(fill) if foreign_mask is None else np.asarray(foreign_mask, dtype=bool)
    unknown = np.zeros_like(fill) if unknown_mask is None else np.asarray(unknown_mask, dtype=bool)
    if foreign.shape != fill.shape or unknown.shape != fill.shape:
        raise ValueError("ownership mask shape does not match fill mask")
    owned = fill & ~foreign & ~unknown
    core = cv2.erode(owned.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
    return core if int(core.sum()) >= 12 else np.zeros_like(fill)


def sample_fill_observation(
    crop_bgr: np.ndarray,
    fill_mask: np.ndarray,
    *,
    foreign_mask: np.ndarray | None = None,
    unknown_mask: np.ndarray | None = None,
    stroke_width_px: float = 0.0,
) -> dict[str, object]:
    image = np.asarray(crop_bgr, dtype=np.uint8)
    fill = np.asarray(fill_mask, dtype=bool)
    foreign = np.zeros_like(fill) if foreign_mask is None else np.asarray(foreign_mask, dtype=bool)
    unknown = np.zeros_like(fill) if unknown_mask is None else np.asarray(unknown_mask, dtype=bool)
    if image.shape[:2] != fill.shape or foreign.shape != fill.shape or unknown.shape != fill.shape:
        raise ValueError("image and masks must share crop dimensions")
    core = trusted_fill_core(fill, foreign, unknown)
    if int(core.sum()) < 12:
        return {"accepted": False, "reason": "insufficient_trusted_interior_pixels"}
    fill_pixels = image[core][:, ::-1].astype(np.float64) / 255.0
    fill_rgb = np.median(fill_pixels, axis=0)
    fill_result = {
        "accepted": True,
        "fill_rgb": [round(float(value), 8) for value in fill_rgb],
        "trusted_fill_pixel_count": int(core.sum()),
        "trusted_fill_mask": core,
    }
    distance = cv2.distanceTransform((~fill).astype(np.uint8), cv2.DIST_L2, 5)
    inner = max(2.0, float(stroke_width_px) + 1.0)
    background = (distance > inner) & (distance <= inner + 6.0) & ~foreign & ~unknown
    if int(background.sum()) < 24:
        return {**fill_result, "background_accepted": False, "background_rgb": None, "trusted_background_pixel_count": int(background.sum()), "trusted_background_mask": background, "reason": "insufficient_trusted_background_pixels"}
    background_pixels = image[background][:, ::-1].astype(np.float64) / 255.0
    background_rgb = np.median(background_pixels, axis=0)
    background_mad = float(np.median(np.linalg.norm(background_pixels - background_rgb, axis=1)))
    if background_mad > PROVISIONAL_RESIDUAL:
        return {
            **fill_result,
            "background_accepted": False,
            "background_rgb": [round(float(value), 8) for value in background_rgb],
            "trusted_background_pixel_count": int(background.sum()),
            "trusted_background_mask": background,
            "background_mad_code": round(background_mad, 8),
            "reason": "local_background_not_uniform_enough",
        }
    return {
        **fill_result,
        "background_accepted": True,
        "reason": None,
        "background_rgb": [round(float(value), 8) for value in background_rgb],
        "trusted_background_pixel_count": int(background.sum()),
        "background_mad_code": round(background_mad, 8),
        "trusted_background_mask": background,
    }


def infer_fill_color_opacity(observations: Iterable[dict[str, object]]) -> dict[str, object]:
    rows = [row for row in observations if row.get("accepted")]
    base = {
        "supporting_frame_count": len(rows),
        "supporting_pixel_count": sum(int(row.get("trusted_fill_pixel_count", 0)) for row in rows),
        "color_space": "BT.709 encoded output; linear-light BT.709 fit",
    }
    if not rows:
        return {
            **base,
            "fill": {"status": "NO_AUTHORITATIVE_FILL_COLOR", "color_rgb": None, "color_hex": None, "reason": "no_trusted_fill_observations"},
            "opacity": {"status": "NO_AUTHORITATIVE_OPACITY", "opacity": None, "reason": "no_trusted_fill_observations"},
            "temporal_consistency": None,
        }
    observed = np.asarray([row["fill_rgb"] for row in rows], dtype=np.float64)
    observed_median = np.median(observed, axis=0)
    spread = float(np.max(np.linalg.norm(observed - observed_median, axis=1)))
    provisional_rgb = np.clip(np.rint(observed_median * 255.0), 0, 255).astype(int)
    provisional_hex = "#" + "".join(f"{value:02x}" for value in provisional_rgb)
    provisional_fill = {
        "status": "PROVISIONAL_FILL_COLOR",
        "color_rgb": provisional_rgb.tolist(),
        "color_hex": provisional_hex,
        "representation": "observed_composite_color_not_unblended",
        "reason": "opacity_not_identifiable",
    }
    compositing_rows = [row for row in rows if row.get("background_accepted", row.get("background_rgb") is not None)]
    if len(compositing_rows) < 2:
        return {
            **base,
            "fill": provisional_fill,
            "opacity": {"status": "NO_AUTHORITATIVE_OPACITY", "opacity": None, "reason": "insufficient_independent_background_variation"},
            "temporal_consistency": round(spread, 8),
            "background_variation_code": None,
        }
    observed = np.asarray([row["fill_rgb"] for row in compositing_rows], dtype=np.float64)
    backgrounds = np.asarray([row["background_rgb"] for row in compositing_rows], dtype=np.float64)
    background_delta = float(np.max(np.linalg.norm(backgrounds - np.median(backgrounds, axis=0), axis=1)))
    if background_delta < MIN_BACKGROUND_DELTA:
        return {
            **base,
            "fill": provisional_fill,
            "opacity": {"status": "NO_AUTHORITATIVE_OPACITY", "opacity": None, "reason": "insufficient_independent_background_variation"},
            "temporal_consistency": round(spread, 8),
            "background_variation_code": round(background_delta, 8),
        }
    observed_linear = bt709_to_linear(observed)
    background_linear = bt709_to_linear(backgrounds)
    centered_background = background_linear - background_linear.mean(axis=0)
    centered_observed = observed_linear - observed_linear.mean(axis=0)
    denominator = float(np.sum(centered_background**2))
    beta = float(np.sum(centered_background * centered_observed) / denominator) if denominator > 1e-12 else float("nan")
    alpha = 1.0 - beta
    if not np.isfinite(alpha) or alpha < 0.05 or alpha > 1.05:
        return {
            **base,
            "fill": provisional_fill,
            "opacity": {"status": "NO_AUTHORITATIVE_OPACITY", "opacity": None, "reason": "physical_alpha_solution_not_found"},
            "temporal_consistency": round(spread, 8),
            "background_variation_code": round(background_delta, 8),
        }
    alpha = min(1.0, alpha)
    foreground_linear = np.mean(observed_linear - (1.0 - alpha) * background_linear, axis=0) / alpha
    if np.any(foreground_linear < -1e-6) or np.any(foreground_linear > 1.000001):
        return {
            **base,
            "fill": provisional_fill,
            "opacity": {"status": "NO_AUTHORITATIVE_OPACITY", "opacity": None, "reason": "foreground_solution_outside_display_gamut"},
            "temporal_consistency": round(spread, 8),
            "background_variation_code": round(background_delta, 8),
        }
    predicted_linear = alpha * foreground_linear + (1.0 - alpha) * background_linear
    residual = float(np.sqrt(np.mean((linear_to_bt709(predicted_linear) - observed) ** 2)))
    channel_alphas = []
    for channel in range(3):
        channel_denominator = float(np.sum(centered_background[:, channel] ** 2))
        if channel_denominator >= (MIN_BACKGROUND_DELTA**2):
            channel_beta = float(np.sum(centered_background[:, channel] * centered_observed[:, channel]) / channel_denominator)
            channel_alphas.append(1.0 - channel_beta)
    alpha_spread = float(np.max(np.abs(np.asarray(channel_alphas) - alpha))) if channel_alphas else 0.0
    if residual > PROVISIONAL_RESIDUAL or alpha_spread > 0.15:
        opacity_status = "NO_AUTHORITATIVE_OPACITY"
        opacity_value = None
        opacity_reason = "inconsistent_compositing_solution"
        fill = provisional_fill
    else:
        authoritative = len(rows) >= 3 and residual <= AUTHORITATIVE_RESIDUAL and alpha_spread <= 0.08
        opacity_status = "AUTHORITATIVE_OPACITY" if authoritative else "PROVISIONAL_OPACITY"
        opacity_value = round(alpha, 6)
        opacity_reason = None if authoritative else "identifiable_but_evidence_below_authoritative_bound"
        encoded = linear_to_bt709(foreground_linear)
        rgb = np.clip(np.rint(encoded * 255.0), 0, 255).astype(int)
        fill = {
            "status": "AUTHORITATIVE_FILL_COLOR" if authoritative else "PROVISIONAL_FILL_COLOR",
            "color_rgb": rgb.tolist(),
            "color_hex": "#" + "".join(f"{value:02x}" for value in rgb),
            "representation": "unblended_bt709_rgb",
            "reason": opacity_reason,
        }
    return {
        **base,
        "fill": fill,
        "opacity": {"status": opacity_status, "opacity": opacity_value, "reason": opacity_reason},
        "temporal_consistency": round(spread, 8),
        "background_variation_code": round(background_delta, 8),
        "fit_residual_code_rms": round(residual, 8),
        "channel_alpha_spread": round(alpha_spread, 8),
    }


def infer_stroke_color(
    observations: Iterable[dict[str, object]],
    *,
    upstream_status: str,
    upstream_present: bool | None,
) -> dict[str, object]:
    if upstream_present is False:
        return {"status": "NOT_APPLICABLE", "color_rgb": None, "color_hex": None, "reason": "frozen_step2c_no_stroke"}
    if upstream_present is not True:
        return {"status": "NO_AUTHORITATIVE_STROKE_COLOR", "color_rgb": None, "color_hex": None, "reason": "frozen_step2c_stroke_unresolved"}
    rows = [row for row in observations if row.get("accepted") and row.get("stroke_rgb") is not None]
    if not rows:
        return {"status": "NO_AUTHORITATIVE_STROKE_COLOR", "color_rgb": None, "color_hex": None, "reason": "no_trusted_stroke_pixels"}
    colors = np.asarray([row["stroke_rgb"] for row in rows], dtype=np.float64)
    median = np.median(colors, axis=0)
    spread = float(np.max(np.linalg.norm(colors - median, axis=1)))
    if spread > PROVISIONAL_RESIDUAL:
        return {
            "status": "NO_AUTHORITATIVE_STROKE_COLOR", "color_rgb": None, "color_hex": None,
            "supporting_frame_count": len(rows), "temporal_consistency": round(spread, 8),
            "reason": "stroke_color_not_temporally_consistent",
        }
    rgb = np.clip(np.rint(median * 255.0), 0, 255).astype(int)
    authoritative_upstream = upstream_status.startswith("AUTHORITATIVE_")
    return {
        "status": "AUTHORITATIVE_STROKE_COLOR" if authoritative_upstream else "PROVISIONAL_STROKE_COLOR",
        "color_rgb": rgb.tolist(), "color_hex": "#" + "".join(f"{value:02x}" for value in rgb),
        "supporting_frame_count": len(rows),
        "supporting_pixel_count": sum(int(row.get("stroke_pixel_count", 0)) for row in rows),
        "temporal_consistency": round(spread, 8),
        "upstream_step2c_status": upstream_status,
        "reason": None if authoritative_upstream else "authority_capped_by_frozen_step2c",
    }
