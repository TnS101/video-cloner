#!/usr/bin/env python3
"""Motion-compensated temporal removal of baked captions in one bounded window.

This is an offline capability probe. It does not modify DaVinci Resolve or the
accepted Text+ timeline. Unlike the foreground-protected OpenCV probe, this
probe reconstructs caption-covered foreground and background pixels from
nearby frames using bidirectionally checked optical flow. Caption regions are
rasterized from the accepted tracked boxes so active frames cannot collapse to
empty masks because of scene-color heuristics.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import remove_baked_captions_window as base  # noqa: E402

TASK_ID = "DZSQH7AUHJT_STEP_3D_CAPTION_REMOVAL_TEMPORAL_WINDOW_PROBE_V1"
SCHEMA = "video_cloner_baked_caption_removal_temporal_window_probe"
SCHEMA_VERSION = 1
DEFAULT_TARGET_CUES = base.DEFAULT_TARGET_CUES
TEMPORAL_MASK_PAD_X_RATIO = 0.02
TEMPORAL_MASK_PAD_Y_RATIO = 0.08
MINIMUM_TARGET_MASK_AREA_RATIO = 0.01
MAXIMUM_TARGET_MASK_AREA_RATIO = 0.10


class TemporalProbeError(RuntimeError):
    pass


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def read_video_range(video_path: Path, start: int, end_exclusive: int) -> Tuple[List[np.ndarray], float]:
    return base.read_video_window(video_path, start, end_exclusive)


def caption_region_mask(
    frame_shape: Sequence[int],
    bbox: Sequence[float],
    pad_x_ratio: float = TEMPORAL_MASK_PAD_X_RATIO,
    pad_y_ratio: float = TEMPORAL_MASK_PAD_Y_RATIO,
) -> np.ndarray:
    """Rasterize the complete tracked caption box.

    The V1 palette detector selected broad scene regions and then dropped the
    resulting connected component when it exceeded 60% of the crop. That
    produced empty masks on active caption frames. Temporal reconstruction
    needs a deterministic region contract, not a color guess, so R2 uses the
    accepted tracked caption box directly.
    """
    height, width = int(frame_shape[0]), int(frame_shape[1])
    x1, y1, x2, y2 = base.normalized_bbox_to_pixels(
        bbox,
        width,
        height,
        pad_x_ratio=float(pad_x_ratio),
        pad_y_ratio=float(pad_y_ratio),
    )
    if x2 <= x1 or y2 <= y1:
        raise TemporalProbeError("caption_region_empty")
    result = np.zeros((height, width), dtype=np.uint8)
    result[y1:y2, x1:x2] = 255
    return result


def build_full_caption_masks(
    frames: Sequence[np.ndarray],
    frame_start: int,
    fps: float,
    target_cues: Sequence[str],
    style_map: Mapping[str, Mapping[str, Any]],
    profile_map: Mapping[str, Mapping[str, Any]],
    lifecycle_map: Mapping[str, Mapping[str, Any]],
    track_map: Mapping[str, Mapping[str, Any]],
    removal_windows: Mapping[str, Tuple[int, int]],
) -> Tuple[List[np.ndarray], List[List[str]]]:
    del fps, profile_map  # kept in the signature for the existing call contract
    masks: List[np.ndarray] = []
    active_rows: List[List[str]] = []
    for offset, frame in enumerate(frames):
        frame_number = frame_start + offset
        combined = np.zeros(frame.shape[:2], dtype=np.uint8)
        active: List[str] = []
        for cue_id in target_cues:
            window = removal_windows.get(cue_id)
            if not window or not (window[0] <= frame_number < window[1]):
                continue
            bbox = base.cue_bbox(cue_id, frame_number, style_map, lifecycle_map, track_map)
            if bbox is None:
                raise TemporalProbeError(f"cue_bbox_missing:{cue_id}:{frame_number}")
            cue_mask = caption_region_mask(frame.shape, bbox)
            combined = cv2.bitwise_or(combined, cue_mask)
            active.append(cue_id)
        masks.append(combined)
        active_rows.append(active)
    return masks, active_rows


def prepare_flow_image(frame: np.ndarray, caption_mask: np.ndarray, max_side: int) -> Tuple[np.ndarray, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if np.count_nonzero(caption_mask):
        gray = cv2.inpaint(gray, caption_mask, 7.0, cv2.INPAINT_TELEA)
    height, width = gray.shape
    scale = min(1.0, float(max_side) / float(max(height, width)))
    if scale < 1.0:
        gray = cv2.resize(gray, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA)
    return gray, scale


def calculate_flow(source_gray: np.ndarray, destination_gray: np.ndarray) -> np.ndarray:
    return cv2.calcOpticalFlowFarneback(
        source_gray,
        destination_gray,
        None,
        pyr_scale=0.5,
        levels=5,
        winsize=25,
        iterations=4,
        poly_n=7,
        poly_sigma=1.5,
        flags=cv2.OPTFLOW_FARNEBACK_GAUSSIAN,
    )


def upscale_flow(flow: np.ndarray, width: int, height: int, scale: float) -> np.ndarray:
    if flow.shape[:2] == (height, width):
        return flow.astype(np.float32, copy=False)
    resized = cv2.resize(flow, (width, height), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    if scale <= 0:
        raise TemporalProbeError("flow_scale_invalid")
    resized[..., 0] /= scale
    resized[..., 1] /= scale
    return resized


def remap_with_flow(image: np.ndarray, target_to_source_flow: np.ndarray, interpolation: int) -> np.ndarray:
    height, width = image.shape[:2]
    grid_x, grid_y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    map_x = grid_x + target_to_source_flow[..., 0]
    map_y = grid_y + target_to_source_flow[..., 1]
    return cv2.remap(
        image,
        map_x,
        map_y,
        interpolation,
        borderMode=cv2.BORDER_REFLECT101,
    )


def flow_pair(
    target: np.ndarray,
    donor: np.ndarray,
    target_mask: np.ndarray,
    donor_mask: np.ndarray,
    max_side: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    target_gray, target_scale = prepare_flow_image(target, target_mask, max_side)
    donor_gray, donor_scale = prepare_flow_image(donor, donor_mask, max_side)
    if target_gray.shape != donor_gray.shape:
        raise TemporalProbeError("flow_shape_mismatch")
    if abs(target_scale - donor_scale) > 1e-6:
        raise TemporalProbeError("flow_scale_mismatch")

    target_to_donor_small = calculate_flow(target_gray, donor_gray)
    donor_to_target_small = calculate_flow(donor_gray, target_gray)
    height, width = target.shape[:2]
    target_to_donor = upscale_flow(target_to_donor_small, width, height, target_scale)
    donor_to_target = upscale_flow(donor_to_target_small, width, height, target_scale)

    warped_donor = remap_with_flow(donor, target_to_donor, cv2.INTER_LINEAR)
    warped_backward = remap_with_flow(donor_to_target, target_to_donor, cv2.INTER_LINEAR)
    consistency = np.linalg.norm(target_to_donor + warped_backward, axis=2)
    return warped_donor, target_to_donor, consistency


def donor_offsets(radius: int, stride: int) -> Tuple[int, ...]:
    if radius <= 0 or stride <= 0:
        raise TemporalProbeError("donor_window_invalid")
    values = list(range(-radius, 0, stride)) + list(range(stride, radius + 1, stride))
    return tuple(values)


def ring_mask(mask: np.ndarray, radius: int = 9) -> np.ndarray:
    if np.count_nonzero(mask) == 0:
        return np.zeros_like(mask)
    outer = cv2.dilate(mask, np.ones((radius, radius), np.uint8), iterations=1)
    inner = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    return cv2.subtract(outer, inner)


def reconstruct_frame(
    target_index: int,
    frames: Sequence[np.ndarray],
    masks: Sequence[np.ndarray],
    foreground_masks: Sequence[np.ndarray],
    offsets: Sequence[int],
    flow_max_side: int,
    consistency_threshold: float,
    temporal_penalty: float,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    target = frames[target_index]
    target_mask = masks[target_index]
    if np.count_nonzero(target_mask) == 0:
        return target.copy(), np.zeros_like(target_mask), {
            "donor_count": 0,
            "coverage_ratio": 1.0,
            "unresolved_ratio": 0.0,
            "donor_frames": [],
        }

    target_fg = foreground_masks[target_index] > 0
    target_gray_flow, _ = prepare_flow_image(target, target_mask, flow_max_side)
    if target_gray_flow.shape != target.shape[:2]:
        target_gray_flow = cv2.resize(target_gray_flow, (target.shape[1], target.shape[0]), interpolation=cv2.INTER_LINEAR)
    context_ring = ring_mask(target_mask) > 0

    donor_images: List[np.ndarray] = []
    donor_validity: List[np.ndarray] = []
    donor_costs: List[np.ndarray] = []
    donor_frames_used: List[int] = []

    for offset in offsets:
        donor_index = target_index + int(offset)
        if donor_index < 0 or donor_index >= len(frames):
            continue
        donor = frames[donor_index]
        donor_mask = masks[donor_index]
        warped, flow, consistency = flow_pair(
            target,
            donor,
            target_mask,
            donor_mask,
            flow_max_side,
        )
        warped_donor_mask = remap_with_flow(donor_mask, flow, cv2.INTER_NEAREST)
        warped_donor_fg = remap_with_flow(foreground_masks[donor_index], flow, cv2.INTER_NEAREST) > 0

        valid = warped_donor_mask < 64
        valid &= consistency <= float(consistency_threshold)
        # Do not transplant background into the person or vice versa.
        valid &= warped_donor_fg == target_fg

        warped_flow_gray, _ = prepare_flow_image(warped, np.zeros_like(target_mask), max(target.shape))
        if warped_flow_gray.shape != target.shape[:2]:
            warped_flow_gray = cv2.resize(warped_flow_gray, (target.shape[1], target.shape[0]), interpolation=cv2.INTER_LINEAR)
        photometric = cv2.absdiff(target_gray_flow, warped_flow_gray).astype(np.float32)
        photometric = cv2.GaussianBlur(photometric, (0, 0), 2.0)
        ring_values = photometric[context_ring & valid]
        ring_cost = float(np.median(ring_values)) if ring_values.size else 255.0
        cost = photometric + ring_cost + abs(offset) * float(temporal_penalty)
        cost[~valid] = np.inf

        donor_images.append(warped)
        donor_validity.append(valid)
        donor_costs.append(cost)
        donor_frames_used.append(donor_index)

    if not donor_images:
        fallback = cv2.inpaint(target, target_mask, 5.0, cv2.INPAINT_TELEA)
        return fallback, np.zeros_like(target_mask), {
            "donor_count": 0,
            "coverage_ratio": 0.0,
            "unresolved_ratio": 1.0,
            "donor_frames": [],
        }

    images = np.stack(donor_images, axis=0)
    validity = np.stack(donor_validity, axis=0)
    costs = np.stack(donor_costs, axis=0)
    best = np.argmin(costs, axis=0)
    has_donor = np.any(validity, axis=0)

    height, width = target_mask.shape
    yy, xx = np.indices((height, width))
    selected = images[best, yy, xx]
    reconstructed = target.copy()
    replace = (target_mask > 0) & has_donor
    reconstructed[replace] = selected[replace]

    unresolved = (target_mask > 0) & ~has_donor
    if np.any(unresolved):
        fallback_mask = unresolved.astype(np.uint8) * 255
        fallback = cv2.inpaint(reconstructed, fallback_mask, 5.0, cv2.INPAINT_TELEA)
        reconstructed[unresolved] = fallback[unresolved]

    mask_pixels = max(1, int(np.count_nonzero(target_mask)))
    coverage_map = (has_donor.astype(np.uint8) * 255)
    return reconstructed, coverage_map, {
        "donor_count": len(donor_images),
        "coverage_ratio": float(np.count_nonzero(replace)) / float(mask_pixels),
        "unresolved_ratio": float(np.count_nonzero(unresolved)) / float(mask_pixels),
        "donor_frames": donor_frames_used,
    }


def local_contrast(frame: np.ndarray, mask: np.ndarray) -> float:
    return base.local_contrast_score(frame, mask)


def palette_residual_ratio(
    frame: np.ndarray,
    mask: np.ndarray,
    palettes: Sequence[Tuple[int, int, int]],
    threshold: float = 42.0,
) -> float:
    pixels = frame[mask > 0].astype(np.float32)
    if pixels.size == 0 or not palettes:
        return 0.0
    palette = np.array(palettes, dtype=np.float32).reshape((-1, 1, 3))
    distances = np.linalg.norm(palette - pixels.reshape((1, -1, 3)), axis=2)
    return float(np.mean(np.min(distances, axis=0) <= float(threshold)))


def make_before_after_sheet(
    originals: Sequence[np.ndarray],
    cleaned: Sequence[np.ndarray],
    frame_start: int,
    sampled_numbers: Sequence[int],
    destination: Path,
) -> None:
    images: List[np.ndarray] = []
    labels: List[str] = []
    for frame_number in sampled_numbers:
        index = frame_number - frame_start
        if 0 <= index < len(originals):
            images.append(np.concatenate([originals[index], cleaned[index]], axis=1))
            labels.append(str(frame_number))
    base.make_contact_sheet(images, labels, destination, columns=2, thumbnail_width=608)


def encode_video(frame_dir: Path, frame_start: int, fps: float, destination: Path) -> None:
    base.encode_ffv1(frame_dir, frame_start, fps, destination)


def run_probe(args: argparse.Namespace) -> Dict[str, Any]:
    video_path = Path(args.video).resolve()
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        raise TemporalProbeError(f"output_dir_already_exists:{output_dir}")
    output_dir.mkdir(parents=True)
    frames_dir = output_dir / "frames"
    masks_dir = output_dir / "masks"
    foreground_dir = output_dir / "foreground_masks"
    coverage_dir = output_dir / "donor_coverage"
    for directory in (frames_dir, masks_dir, foreground_dir, coverage_dir):
        directory.mkdir()

    context_frames, fps = read_video_range(video_path, args.context_start, args.context_end_exclusive)
    style_contract = base.load_json(Path(args.caption_style).resolve())
    lifecycle_contract = base.load_json(Path(args.lifecycle).resolve())
    track_contract = base.load_json(Path(args.tracks).resolve())
    style_map, profile_map, lifecycle_map, track_map = base.build_contract_maps(
        style_contract,
        lifecycle_contract,
        track_contract,
    )
    target_cues = tuple(base.normalize_cue_id(value) for value in args.target_cues.split(",") if value.strip())
    if not target_cues:
        raise TemporalProbeError("target_cues_empty")
    missing = [cue for cue in target_cues if cue not in lifecycle_map]
    if missing:
        raise TemporalProbeError(f"target_cues_missing:{','.join(missing)}")
    removal_windows = {
        cue: base.removal_window(cue, fps, style_map, lifecycle_map, track_map)
        for cue in target_cues
    }

    full_masks, active_cues = build_full_caption_masks(
        context_frames,
        args.context_start,
        fps,
        target_cues,
        style_map,
        profile_map,
        lifecycle_map,
        track_map,
        removal_windows,
    )

    from detect_caption_occlusion import ForegroundSegmenter  # pylint: disable=import-outside-toplevel

    segmenter = ForegroundSegmenter(
        backend=args.backend,
        max_side=args.segmentation_max_side,
        segmentation_device=args.segmentation_device,
        paddle_gpu_id=args.paddle_gpu_id,
        paddle_hub_module=args.paddle_hub_module,
        paddle_seg_threshold=args.paddle_seg_threshold,
        enable_grabcut_fallback=False,
    )
    foreground_masks: List[np.ndarray] = []
    backend_counts: Dict[str, int] = {}
    for offset, frame in enumerate(context_frames):
        frame_number = args.context_start + offset
        foreground_raw, segmentation = segmenter.segment(frame)
        backend = str(segmentation.get("backend") or "unknown")
        backend_counts[backend] = backend_counts.get(backend, 0) + 1
        device = str(segmentation.get("device_selected") or segmentation.get("runtime", {}).get("device_selected") or "")
        if args.require_paddle_gpu and (
            not segmentation.get("ok")
            or backend != "paddle_humanseg"
            or not device.startswith("gpu")
        ):
            raise TemporalProbeError(f"paddle_gpu_required:{frame_number}:{backend}:{device}")
        foreground_masks.append(base.protect_foreground(foreground_raw, args.foreground_dilation))

    offsets = donor_offsets(args.donor_radius, args.donor_stride)
    cleaned_context = [frame.copy() for frame in context_frames]
    coverage_context = [np.zeros(frame.shape[:2], np.uint8) for frame in context_frames]
    rows: List[Dict[str, Any]] = []

    # Palette list is used only as a diagnostic residual metric.
    palette_values: List[Tuple[int, int, int]] = []
    for cue in target_cues:
        palette_values.extend(base._palette_for_cue(cue, style_map, profile_map, track_map))
    palette_values = sorted(set(tuple(int(v) for v in color) for color in palette_values))

    for frame_number in range(args.output_start, args.output_end_exclusive):
        index = frame_number - args.context_start
        frame = context_frames[index]
        mask = full_masks[index]
        if args.clean_start <= frame_number < args.clean_end_exclusive:
            cleaned, coverage, meta = reconstruct_frame(
                index,
                context_frames,
                full_masks,
                foreground_masks,
                offsets,
                args.flow_max_side,
                args.flow_consistency_threshold,
                args.temporal_penalty,
            )
        else:
            cleaned = frame.copy()
            coverage = np.zeros_like(mask)
            meta = {
                "donor_count": 0,
                "coverage_ratio": 1.0,
                "unresolved_ratio": 0.0,
                "donor_frames": [],
            }
        cleaned_context[index] = cleaned
        coverage_context[index] = coverage

        outside = mask == 0
        inside = mask > 0
        outside_diff = float(np.mean(np.abs(cleaned[outside].astype(np.int16) - frame[outside].astype(np.int16)))) if np.any(outside) else 0.0
        inside_diff = float(np.mean(np.abs(cleaned[inside].astype(np.int16) - frame[inside].astype(np.int16)))) if np.any(inside) else 0.0
        mask_area_ratio = float(np.count_nonzero(mask)) / float(mask.size)
        before_contrast = local_contrast(frame, mask)
        after_contrast = local_contrast(cleaned, mask)
        contrast_ratio = after_contrast / before_contrast if before_contrast > 1e-6 else 0.0
        before_palette = palette_residual_ratio(frame, mask, palette_values)
        after_palette = palette_residual_ratio(cleaned, mask, palette_values)
        palette_ratio = after_palette / before_palette if before_palette > 1e-6 else 0.0

        if not cv2.imwrite(str(frames_dir / f"frame_{frame_number:06d}.png"), cleaned):
            raise TemporalProbeError(f"frame_write_failed:{frame_number}")
        if not cv2.imwrite(str(masks_dir / f"mask_{frame_number:06d}.png"), mask):
            raise TemporalProbeError(f"mask_write_failed:{frame_number}")
        if not cv2.imwrite(str(foreground_dir / f"foreground_{frame_number:06d}.png"), foreground_masks[index]):
            raise TemporalProbeError(f"foreground_write_failed:{frame_number}")
        if not cv2.imwrite(str(coverage_dir / f"coverage_{frame_number:06d}.png"), coverage):
            raise TemporalProbeError(f"coverage_write_failed:{frame_number}")

        rows.append(
            {
                "frame": frame_number,
                "active_cues": active_cues[index],
                "mask_pixels": int(np.count_nonzero(mask)),
                "mask_area_ratio": round(mask_area_ratio, 6),
                "inside_mask_mean_abs_diff": round(inside_diff, 6),
                "donor_count": int(meta["donor_count"]),
                "donor_frames": [args.context_start + int(value) for value in meta["donor_frames"]],
                "donor_coverage_ratio": round(float(meta["coverage_ratio"]), 6),
                "unresolved_ratio": round(float(meta["unresolved_ratio"]), 6),
                "outside_mask_mean_abs_diff": round(outside_diff, 6),
                "masked_local_contrast_before": round(before_contrast, 6),
                "masked_local_contrast_after": round(after_contrast, 6),
                "masked_local_contrast_ratio": round(contrast_ratio, 6),
                "palette_residual_before": round(before_palette, 6),
                "palette_residual_after": round(after_palette, 6),
                "palette_residual_ratio": round(palette_ratio, 6),
            }
        )

    output_frames = [cleaned_context[number - args.context_start] for number in range(args.output_start, args.output_end_exclusive)]
    original_output_frames = [context_frames[number - args.context_start] for number in range(args.output_start, args.output_end_exclusive)]
    sampled_numbers = sorted(set([
        args.clean_start,
        args.clean_start + 2,
        args.clean_start + 5,
        args.clean_start + 8,
        args.clean_start + 12,
        args.clean_start + 16,
        args.clean_end_exclusive - 2,
        args.clean_end_exclusive - 1,
    ]))
    before_after = output_dir / "before_after_contact_sheet.jpg"
    make_before_after_sheet(original_output_frames, output_frames, args.output_start, sampled_numbers, before_after)

    mask_previews = [full_masks[number - args.context_start] for number in sampled_numbers]
    coverage_previews = [coverage_context[number - args.context_start] for number in sampled_numbers]
    labels = [str(number) for number in sampled_numbers]
    mask_sheet = output_dir / "mask_contact_sheet.jpg"
    coverage_sheet = output_dir / "donor_coverage_contact_sheet.jpg"
    base.make_contact_sheet([cv2.cvtColor(value, cv2.COLOR_GRAY2BGR) for value in mask_previews], labels, mask_sheet, columns=4, thumbnail_width=304)
    base.make_contact_sheet([cv2.cvtColor(value, cv2.COLOR_GRAY2BGR) for value in coverage_previews], labels, coverage_sheet, columns=4, thumbnail_width=304)

    video_output = output_dir / "cleaned_frames_420_462_temporal_ffv1.mkv"
    encode_video(frames_dir, args.output_start, fps, video_output)

    target_rows = [row for row in rows if args.clean_start <= int(row["frame"]) < args.clean_end_exclusive]
    coverage_values = [safe_float(row["donor_coverage_ratio"]) for row in target_rows if int(row["mask_pixels"]) > 0]
    unresolved_values = [safe_float(row["unresolved_ratio"]) for row in target_rows if int(row["mask_pixels"]) > 0]
    contrast_values = [safe_float(row["masked_local_contrast_ratio"], 999.0) for row in target_rows if int(row["mask_pixels"]) > 0]
    palette_values_metric = [safe_float(row["palette_residual_ratio"], 999.0) for row in target_rows if int(row["mask_pixels"]) > 0]
    mask_area_values = [safe_float(row["mask_area_ratio"], 0.0) for row in target_rows]
    inside_diff_values = [safe_float(row["inside_mask_mean_abs_diff"], 0.0) for row in target_rows]
    max_outside = max((safe_float(row["outside_mask_mean_abs_diff"], 999.0) for row in rows), default=999.0)

    median_coverage = float(np.median(coverage_values)) if coverage_values else 0.0
    max_unresolved = max(unresolved_values, default=1.0)
    median_contrast = float(np.median(contrast_values)) if contrast_values else 999.0
    median_palette = float(np.median(palette_values_metric)) if palette_values_metric else 999.0
    minimum_mask_area = min(mask_area_values, default=0.0)
    maximum_mask_area = max(mask_area_values, default=1.0)
    median_inside_diff = float(np.median(inside_diff_values)) if inside_diff_values else 0.0

    checks = {
        "output_frame_count_exact": len(rows) == args.output_end_exclusive - args.output_start,
        "target_frame_count_exact": len(target_rows) == args.clean_end_exclusive - args.clean_start,
        "target_masks_nonempty": all(int(row["mask_pixels"]) > 0 for row in target_rows),
        "target_mask_area_bounded": (
            minimum_mask_area >= MINIMUM_TARGET_MASK_AREA_RATIO
            and maximum_mask_area <= MAXIMUM_TARGET_MASK_AREA_RATIO
        ),
        "target_regions_modified": median_inside_diff >= 1.0,
        "outside_mask_unchanged": max_outside == 0.0,
        "donor_coverage_sufficient": median_coverage >= args.minimum_median_donor_coverage,
        "unresolved_ratio_bounded": max_unresolved <= args.maximum_unresolved_ratio,
        "contrast_reduced": median_contrast < 1.0,
        "paddle_gpu_only": backend_counts == {"paddle_humanseg": len(context_frames)},
        "artifacts_exist": all(path.is_file() and path.stat().st_size > 0 for path in (video_output, before_after, mask_sheet, coverage_sheet)),
    }
    ok = all(checks.values())
    report = {
        "task_id": TASK_ID,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "video": str(video_path),
        "context_window": [args.context_start, args.context_end_exclusive],
        "output_window": [args.output_start, args.output_end_exclusive],
        "clean_window": [args.clean_start, args.clean_end_exclusive],
        "output_frame_count": len(rows),
        "target_frame_count": len(target_rows),
        "target_cues": list(target_cues),
        "removal_windows": {key: list(value) for key, value in removal_windows.items()},
        "segmentation_backend_counts": backend_counts,
        "donor_offsets": list(offsets),
        "median_donor_coverage_ratio": round(median_coverage, 6),
        "max_unresolved_ratio": round(max_unresolved, 6),
        "median_masked_local_contrast_ratio": round(median_contrast, 6),
        "median_palette_residual_ratio": round(median_palette, 6),
        "palette_residual_metric_role": "diagnostic_only",
        "minimum_target_mask_area_ratio": round(minimum_mask_area, 6),
        "maximum_target_mask_area_ratio": round(maximum_mask_area, 6),
        "median_inside_mask_mean_abs_diff": round(median_inside_diff, 6),
        "max_outside_mask_mean_abs_diff": round(max_outside, 6),
        "checks": checks,
        "frames": rows,
        "artifacts": {
            "cleaned_video": str(video_output),
            "cleaned_frames": str(frames_dir),
            "caption_masks": str(masks_dir),
            "foreground_masks": str(foreground_dir),
            "donor_coverage": str(coverage_dir),
            "before_after_contact_sheet": str(before_after),
            "mask_contact_sheet": str(mask_sheet),
            "donor_coverage_contact_sheet": str(coverage_sheet),
        },
        "visual_approval_required": True,
        "visual_review": "Reject if any baked word remains readable, if facial/body reconstruction is distorted, or if temporal shimmer is visible.",
    }
    write_json(output_dir / "report.json", report)
    if not ok:
        failed = ",".join(name for name, passed in checks.items() if not passed)
        raise TemporalProbeError(f"technical_checks_failed:{failed}")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--caption-style", required=True)
    parser.add_argument("--lifecycle", required=True)
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-cues", default=",".join(DEFAULT_TARGET_CUES))
    parser.add_argument("--context-start", type=int, default=416)
    parser.add_argument("--context-end-exclusive", type=int, default=468)
    parser.add_argument("--output-start", type=int, default=420)
    parser.add_argument("--output-end-exclusive", type=int, default=463)
    parser.add_argument("--clean-start", type=int, default=428)
    parser.add_argument("--clean-end-exclusive", type=int, default=452)
    parser.add_argument("--donor-radius", type=int, default=12)
    parser.add_argument("--donor-stride", type=int, default=3)
    parser.add_argument("--flow-max-side", type=int, default=640)
    parser.add_argument("--flow-consistency-threshold", type=float, default=3.5)
    parser.add_argument("--temporal-penalty", type=float, default=0.35)
    parser.add_argument("--minimum-median-donor-coverage", type=float, default=0.25)
    parser.add_argument("--maximum-unresolved-ratio", type=float, default=0.90)
    parser.add_argument("--backend", default="paddle_humanseg")
    parser.add_argument("--segmentation-max-side", type=int, default=960)
    parser.add_argument("--segmentation-device", default="gpu:0")
    parser.add_argument("--paddle-gpu-id", type=int, default=0)
    parser.add_argument("--paddle-hub-module", default="deeplabv3p_xception65_humanseg")
    parser.add_argument("--paddle-seg-threshold", type=float, default=0.5)
    parser.add_argument("--foreground-dilation", type=int, default=3)
    parser.add_argument("--require-paddle-gpu", action="store_true", default=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = run_probe(args)
    except Exception as exc:  # bounded CLI failure reporting
        print(f"FAIL {TASK_ID}: {exc}", file=sys.stderr)
        return 1
    print(f"PASS {TASK_ID}")
    print(f"Frames: {report['output_frame_count']}")
    print(f"Median donor coverage: {report['median_donor_coverage_ratio']}")
    print(f"Max unresolved ratio: {report['max_unresolved_ratio']}")
    print(f"Review: {report['artifacts']['before_after_contact_sheet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
