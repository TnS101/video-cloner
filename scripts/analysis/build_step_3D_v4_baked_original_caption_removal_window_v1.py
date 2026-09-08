#!/usr/bin/env python3
"""Build one sparse baked-caption removal restore from exact Resolve base renders.

The input render is produced from a disposable duplicate of the accepted
Resolve timeline with all editable Text+ captions and the accepted foreground
occlusion overlay disabled.  Therefore frame numbers, cuts, transforms and
color processing are already in the exact timeline coordinate system.

This helper only reconstructs source-baked caption pixels for one bounded
window.  It never edits Resolve.  HumanSeg separates foreground/background for
temporal donor selection; caption masks combine accepted tracked source boxes,
source color authority and the HumanSeg silhouette.  `sub_052` (COME) is a
source-proven foreground-occluded cue, so foreground pixels are explicitly
excluded from its removal mask.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_WINDOW_V1"
SCHEMA = "video_cloner_baked_original_caption_removal_window_v1"
SCHEMA_VERSION = 1
EXPECTED_FPS = 24.0
CONTEXT_RANGE = (400, 480)
CLEAN_RANGE = (426, 455)
TARGET_CUES = tuple(f"sub_{value:03d}" for value in range(51, 57))
SOURCE_OCCLUDED_CUES = frozenset({"sub_052"})
DONOR_RADIUS = 24
DONOR_STRIDE = 3
FLOW_MAX_SIDE = 640
FLOW_CONSISTENCY_THRESHOLD = 3.5
TEMPORAL_PENALTY = 0.25
MAX_MASK_AREA_RATIO = 0.075
MIN_CUE_MASK_COVERAGE_RATIO = 0.45
MIN_MEDIAN_DONOR_COVERAGE = 0.15
MAX_UNRESOLVED_RATIO = 0.95


class BuildError(RuntimeError):
    pass


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
BASE = _load("vc_remove_baked_base_for_step3dv4", HERE / "remove_baked_captions_window.py")
TEMP = _load("vc_remove_baked_temporal_for_step3dv4", HERE / "remove_baked_captions_window_temporal.py")


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def frame_number(path: Path) -> int:
    match = re.search(r"(\d+)\s*$", path.stem)
    if not match:
        raise BuildError(f"render_frame_number:{path.name}")
    return int(match.group(1))


def indexed_pngs(directory: Path, expected_range: Tuple[int, int]) -> Dict[int, Path]:
    if not directory.is_dir():
        raise BuildError(f"render_dir_missing:{directory}")
    rows: Dict[int, Path] = {}
    for path in sorted(directory.glob("*.png")):
        number = frame_number(path)
        if number in rows:
            raise BuildError(f"duplicate_render_frame:{number}")
        rows[number] = path
    expected = set(range(*expected_range))
    if set(rows) != expected:
        missing = sorted(expected - set(rows))
        extra = sorted(set(rows) - expected)
        raise BuildError(f"render_frame_set:missing={missing}:extra={extra}")
    if any(path.stat().st_size <= 0 for path in rows.values()):
        raise BuildError("render_empty_file")
    return rows


def _palette_values(
    cue_id: str,
    style_map: Mapping[str, Mapping[str, Any]],
    profile_map: Mapping[str, Mapping[str, Any]],
    track_map: Mapping[str, Mapping[str, Any]],
    keys: Iterable[str],
) -> list[Tuple[int, int, int]]:
    event = style_map.get(cue_id) or {}
    track = track_map.get(cue_id) or {}
    profile_id = str(event.get("style_profile_id") or track.get("style_profile_id") or "")
    colors: list[Tuple[int, int, int]] = []
    for source in (event, profile_map.get(profile_id) or {}):
        color_map = source.get("colors") if isinstance(source.get("colors"), Mapping) else {}
        for key in keys:
            rgb = BASE.parse_hex_rgb(color_map.get(key))
            if rgb is None:
                continue
            bgr = BASE.rgb_to_bgr(rgb)
            if bgr not in colors:
                colors.append(bgr)
    return colors


def _palette_candidate(crop: np.ndarray, local_contrast: np.ndarray, palette: Sequence[Tuple[int, int, int]], threshold: float) -> np.ndarray:
    if not palette:
        return np.zeros(crop.shape[:2], dtype=bool)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    result = np.zeros(crop.shape[:2], dtype=bool)
    for color in palette:
        swatch = cv2.cvtColor(np.uint8([[list(color)]]), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
        distance = np.linalg.norm(lab - swatch, axis=2)
        result |= (distance <= float(threshold)) & (local_contrast >= 1)
    return result


def caption_pixel_mask_v2(
    frame: np.ndarray,
    bbox: Sequence[float],
    foreground_mask: np.ndarray,
    background_palette: Sequence[Tuple[int, int, int]],
    foreground_palette: Sequence[Tuple[int, int, int]],
    *,
    allow_foreground: bool,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Return a tight caption-pixel mask, not a whole tracked rectangle.

    Generic high-contrast selection is allowed only on background.  On the
    human foreground, only source fill/stroke palette pixels are accepted and
    slightly expanded to cover anti-alias/shadow edges.  This prevents dark
    hair/clothing from becoming a removal mask merely because the cue itself is
    dark.  Source-proven occluded cues can forbid foreground pixels entirely.
    """
    if foreground_mask.shape != frame.shape[:2]:
        raise BuildError("foreground_shape")
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = BASE.normalized_bbox_to_pixels(
        bbox, width, height, pad_x_ratio=0.07, pad_y_ratio=0.20
    )
    crop = frame[y1:y2, x1:x2]
    fg_crop = foreground_mask[y1:y2, x1:x2] > 0
    if crop.size == 0:
        return np.zeros((height, width), np.uint8), {"crop": [x1, y1, x2, y2], "pixels": 0}

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (0, 0), 2.0)
    contrast = cv2.absdiff(gray, blurred)
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]

    generic = (
        ((value >= 145) & (saturation <= 175) & (contrast >= 2))
        | ((value <= 175) & (contrast >= 3))
        | ((saturation >= 50) & (contrast >= 3))
    )
    palette_bg = _palette_candidate(crop, contrast, background_palette, 50.0)
    background_candidate = (generic | palette_bg) & ~fg_crop

    if allow_foreground:
        palette_fg = _palette_candidate(crop, contrast, foreground_palette, 42.0)
        # The foreground mask intentionally starts from fill/stroke colors only.
        # A small dilation restores antialias/shadow pixels without selecting the
        # person's dark clothing/hair as generic caption pixels.
        foreground_candidate = palette_fg & fg_crop
        foreground_candidate = cv2.dilate(
            foreground_candidate.astype(np.uint8) * 255,
            np.ones((5, 5), np.uint8),
            iterations=1,
        ) > 0
        foreground_candidate &= fg_crop
    else:
        foreground_candidate = np.zeros_like(background_candidate)

    candidate = background_candidate | foreground_candidate
    mask_crop = candidate.astype(np.uint8) * 255
    mask_crop = cv2.morphologyEx(mask_crop, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    mask_crop = cv2.dilate(mask_crop, np.ones((3, 3), np.uint8), iterations=1)

    components, labels, stats, _ = cv2.connectedComponentsWithStats((mask_crop > 0).astype(np.uint8), 8)
    filtered = np.zeros_like(mask_crop)
    crop_area = max(1, mask_crop.size)
    for component in range(1, components):
        area = int(stats[component, cv2.CC_STAT_AREA])
        component_width = int(stats[component, cv2.CC_STAT_WIDTH])
        component_height = int(stats[component, cv2.CC_STAT_HEIGHT])
        if 3 <= area <= int(crop_area * 0.78) and max(component_width, component_height) >= 2:
            filtered[labels == component] = 255

    if not allow_foreground:
        filtered[fg_crop] = 0

    result = np.zeros((height, width), dtype=np.uint8)
    result[y1:y2, x1:x2] = filtered
    fg_pixels = int(np.count_nonzero((result > 0) & (foreground_mask > 0)))
    return result, {
        "crop": [x1, y1, x2, y2],
        "pixels": int(np.count_nonzero(result)),
        "foreground_pixels": fg_pixels,
        "allow_foreground": bool(allow_foreground),
    }


def _make_sheet(images: Sequence[np.ndarray], labels: Sequence[str], destination: Path, columns: int = 4) -> None:
    BASE.make_contact_sheet(images, labels, destination, columns=columns, thumbnail_width=304)


def run(args: argparse.Namespace) -> Dict[str, Any]:
    base_dir = Path(args.base_render_dir).resolve()
    output = Path(args.output_root).resolve()
    if output.exists():
        raise BuildError(f"output_exists:{output}")
    output.mkdir(parents=True)
    rgba_dir = output / "rgba"
    cleaned_dir = output / "cleaned"
    mask_dir = output / "masks"
    foreground_dir = output / "foreground"
    coverage_dir = output / "coverage"
    for directory in (rgba_dir, cleaned_dir, mask_dir, foreground_dir, coverage_dir):
        directory.mkdir()

    render_rows = indexed_pngs(base_dir, CONTEXT_RANGE)
    frames = []
    shape = None
    for number in range(*CONTEXT_RANGE):
        image = cv2.imread(str(render_rows[number]), cv2.IMREAD_COLOR)
        if image is None:
            raise BuildError(f"decode:{number}")
        if shape is None:
            shape = image.shape
        if image.shape != shape:
            raise BuildError(f"shape:{number}:{image.shape}:{shape}")
        frames.append(image)
    if shape is None or shape[:2] != (1920, 1080):
        raise BuildError(f"render_dimensions:{shape}")

    style = BASE.load_json(Path(args.caption_style).resolve())
    lifecycle = BASE.load_json(Path(args.lifecycle).resolve())
    tracks = BASE.load_json(Path(args.tracks).resolve())
    style_map, profile_map, lifecycle_map, track_map = BASE.build_contract_maps(style, lifecycle, tracks)
    # Some accepted cues (notably sub_052/sub_053) have no dedicated
    # word-instance track, but do have stronger style/lifecycle geometry.
    # Require lifecycle plus an actual resolvable bbox; do not invent a track.
    missing = []
    for cue in TARGET_CUES:
        if cue not in lifecycle_map:
            missing.append(cue)
            continue
        start, end = BASE.removal_window(
            cue, EXPECTED_FPS, style_map, lifecycle_map, track_map, lead_margin=2, tail_margin=1
        )
        probe_frames = range(max(CONTEXT_RANGE[0], start), min(CONTEXT_RANGE[1], end))
        if not any(BASE.cue_bbox(cue, frame_no, style_map, lifecycle_map, track_map) is not None for frame_no in probe_frames):
            missing.append(cue)
    if missing:
        raise BuildError(f"authority_missing:{','.join(missing)}")
    removal_windows = {
        cue: BASE.removal_window(cue, EXPECTED_FPS, style_map, lifecycle_map, track_map, lead_margin=2, tail_margin=1)
        for cue in TARGET_CUES
    }

    from detect_caption_occlusion import ForegroundSegmenter  # pylint: disable=import-outside-toplevel

    segmenter = ForegroundSegmenter(
        backend="paddle_humanseg",
        max_side=int(args.segmentation_max_side),
        segmentation_device="gpu:0",
        paddle_gpu_id=0,
        paddle_hub_module=str(args.paddle_hub_module),
        paddle_seg_threshold=0.5,
        enable_grabcut_fallback=False,
    )
    foreground_masks: list[np.ndarray] = []
    segmentation_rows = []
    for offset, frame in enumerate(frames):
        timeline_frame = CONTEXT_RANGE[0] + offset
        raw, info = segmenter.segment(frame)
        backend = str(info.get("backend") or "")
        device = str(info.get("device_selected") or (info.get("runtime") or {}).get("device_selected") or "")
        if info.get("ok") is not True or backend != "paddle_humanseg" or not device.startswith("gpu"):
            raise BuildError(f"humanseg:{timeline_frame}:{backend}:{device}:{info.get('reason')}")
        protected = BASE.protect_foreground(raw, 3)
        foreground_masks.append(protected)
        segmentation_rows.append({
            "frame": timeline_frame,
            "backend": backend,
            "device": device,
            "foreground_pixels": int(np.count_nonzero(protected)),
        })

    combined_masks: list[np.ndarray] = []
    active_by_frame: list[list[str]] = []
    cue_stats: Dict[str, Dict[str, Any]] = {
        cue: {"active_frames": 0, "masked_frames": 0, "mask_pixels": 0, "foreground_mask_pixels": 0}
        for cue in TARGET_CUES
    }
    mask_details: Dict[str, list[Dict[str, Any]]] = {cue: [] for cue in TARGET_CUES}

    for offset, (frame, foreground) in enumerate(zip(frames, foreground_masks)):
        timeline_frame = CONTEXT_RANGE[0] + offset
        combined = np.zeros(frame.shape[:2], np.uint8)
        active: list[str] = []
        for cue in TARGET_CUES:
            start, end = removal_windows[cue]
            if not (start <= timeline_frame < end):
                continue
            bbox = BASE.cue_bbox(cue, timeline_frame, style_map, lifecycle_map, track_map)
            if bbox is None:
                raise BuildError(f"bbox:{cue}:{timeline_frame}")
            background_palette = _palette_values(cue, style_map, profile_map, track_map, ("fill", "stroke", "shadow"))
            foreground_palette = _palette_values(cue, style_map, profile_map, track_map, ("fill", "stroke"))
            mask, meta = caption_pixel_mask_v2(
                frame,
                bbox,
                foreground,
                background_palette,
                foreground_palette,
                allow_foreground=cue not in SOURCE_OCCLUDED_CUES,
            )
            pixels = int(np.count_nonzero(mask))
            stats = cue_stats[cue]
            stats["active_frames"] += 1
            stats["mask_pixels"] += pixels
            stats["foreground_mask_pixels"] += int(meta["foreground_pixels"])
            if pixels > 0:
                stats["masked_frames"] += 1
            mask_details[cue].append({"frame": timeline_frame, **meta})
            combined = cv2.bitwise_or(combined, mask)
            active.append(cue)
        combined_masks.append(combined)
        active_by_frame.append(active)

    cue_checks = {}
    for cue, stats in cue_stats.items():
        active_frames = int(stats["active_frames"])
        masked_frames = int(stats["masked_frames"])
        ratio = (masked_frames / float(active_frames)) if active_frames else 0.0
        stats["masked_frame_ratio"] = round(ratio, 6)
        cue_checks[f"{cue}_coverage"] = active_frames > 0 and ratio >= MIN_CUE_MASK_COVERAGE_RATIO
        if cue in SOURCE_OCCLUDED_CUES:
            cue_checks[f"{cue}_foreground_excluded"] = int(stats["foreground_mask_pixels"]) == 0

    offsets = TEMP.donor_offsets(DONOR_RADIUS, DONOR_STRIDE)
    frame_rows = []
    nonzero_hashes = set()
    before_after_images = []
    mask_images = []
    labels = []
    sampled = {426, 428, 431, 434, 438, 443, 448, 451, 454}

    for timeline_frame in range(*CLEAN_RANGE):
        index = timeline_frame - CONTEXT_RANGE[0]
        original = frames[index]
        mask = combined_masks[index]
        if np.count_nonzero(mask):
            cleaned, coverage, meta = TEMP.reconstruct_frame(
                index,
                frames,
                combined_masks,
                foreground_masks,
                offsets,
                FLOW_MAX_SIDE,
                FLOW_CONSISTENCY_THRESHOLD,
                TEMPORAL_PENALTY,
            )
        else:
            cleaned = original.copy()
            coverage = np.zeros_like(mask)
            meta = {"donor_count": 0, "coverage_ratio": 1.0, "unresolved_ratio": 0.0, "donor_frames": []}

        outside = mask == 0
        inside = mask > 0
        outside_mae = float(np.mean(np.abs(cleaned[outside].astype(np.int16) - original[outside].astype(np.int16)))) if np.any(outside) else 0.0
        inside_mae = float(np.mean(np.abs(cleaned[inside].astype(np.int16) - original[inside].astype(np.int16)))) if np.any(inside) else 0.0
        mask_ratio = float(np.count_nonzero(mask)) / float(mask.size)
        if mask_ratio > MAX_MASK_AREA_RATIO:
            raise BuildError(f"mask_area:{timeline_frame}:{mask_ratio:.6f}")
        if outside_mae != 0.0:
            raise BuildError(f"outside_changed:{timeline_frame}:{outside_mae}")

        cleaned_path = cleaned_dir / f"cleaned_{timeline_frame:06d}.png"
        mask_path = mask_dir / f"mask_{timeline_frame:06d}.png"
        foreground_path = foreground_dir / f"foreground_{timeline_frame:06d}.png"
        coverage_path = coverage_dir / f"coverage_{timeline_frame:06d}.png"
        rgba_path = rgba_dir / f"rgba_{timeline_frame:06d}.png"
        for path, image in (
            (cleaned_path, cleaned),
            (mask_path, mask),
            (foreground_path, foreground_masks[index]),
            (coverage_path, coverage),
        ):
            if not cv2.imwrite(str(path), image):
                raise BuildError(f"write:{path}")
        rgba = cv2.cvtColor(cleaned, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = mask
        if not cv2.imwrite(str(rgba_path), rgba):
            raise BuildError(f"write:{rgba_path}")
        if np.count_nonzero(mask):
            nonzero_hashes.add(sha256_file(rgba_path))

        row = {
            "frame": timeline_frame,
            "active_cues": active_by_frame[index],
            "mask_pixels": int(np.count_nonzero(mask)),
            "mask_area_ratio": round(mask_ratio, 6),
            "foreground_mask_pixels": int(np.count_nonzero((mask > 0) & (foreground_masks[index] > 0))),
            "inside_mask_mean_abs_diff": round(inside_mae, 6),
            "outside_mask_mean_abs_diff": round(outside_mae, 6),
            "donor_count": int(meta["donor_count"]),
            "donor_coverage_ratio": round(float(meta["coverage_ratio"]), 6),
            "unresolved_ratio": round(float(meta["unresolved_ratio"]), 6),
            "donor_frames": [CONTEXT_RANGE[0] + int(value) for value in meta["donor_frames"]],
            "rgba_sha256": sha256_file(rgba_path),
            "mask_sha256": sha256_file(mask_path),
            "cleaned_sha256": sha256_file(cleaned_path),
        }
        frame_rows.append(row)

        if timeline_frame in sampled:
            before_after_images.append(np.concatenate([original, cleaned], axis=1))
            mask_images.append(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR))
            labels.append(str(timeline_frame))

    if not frame_rows:
        raise BuildError("no_frames")
    nonzero_rows = [row for row in frame_rows if int(row["mask_pixels"]) > 0]
    if not nonzero_rows:
        raise BuildError("no_masks")
    coverage_values = [safe_float(row["donor_coverage_ratio"]) for row in nonzero_rows]
    unresolved_values = [safe_float(row["unresolved_ratio"], 1.0) for row in nonzero_rows]
    inside_values = [safe_float(row["inside_mask_mean_abs_diff"]) for row in nonzero_rows]
    max_mask_area = max(safe_float(row["mask_area_ratio"]) for row in frame_rows)
    median_coverage = float(np.median(coverage_values))
    max_unresolved = max(unresolved_values)
    median_inside = float(np.median(inside_values))

    before_after_sheet = output / "before_after_contact_sheet.jpg"
    mask_sheet = output / "mask_contact_sheet.jpg"
    _make_sheet(before_after_images, labels, before_after_sheet, columns=2)
    _make_sheet(mask_images, labels, mask_sheet, columns=4)

    checks = {
        "context_frame_count_exact": len(frames) == CONTEXT_RANGE[1] - CONTEXT_RANGE[0],
        "clean_frame_count_exact": len(frame_rows) == CLEAN_RANGE[1] - CLEAN_RANGE[0],
        "all_cue_mask_coverage": all(cue_checks.values()),
        "mask_area_bounded": max_mask_area <= MAX_MASK_AREA_RATIO,
        "outside_mask_unchanged": all(row["outside_mask_mean_abs_diff"] == 0.0 for row in frame_rows),
        "masked_pixels_modified": median_inside >= 1.0,
        "donor_coverage_sufficient": median_coverage >= MIN_MEDIAN_DONOR_COVERAGE,
        "unresolved_ratio_bounded": max_unresolved <= MAX_UNRESOLVED_RATIO,
        "sequence_not_frozen": len(nonzero_hashes) >= 3,
        "paddle_gpu_every_context_frame": len(segmentation_rows) == len(frames) and all(row["backend"] == "paddle_humanseg" and str(row["device"]).startswith("gpu") for row in segmentation_rows),
        "artifacts_exist": before_after_sheet.is_file() and mask_sheet.is_file(),
    }
    ok = all(checks.values())
    manifest = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "ok": ok,
        "context_range": list(CONTEXT_RANGE),
        "clean_range": list(CLEAN_RANGE),
        "fps": EXPECTED_FPS,
        "target_cues": list(TARGET_CUES),
        "source_occluded_cues": sorted(SOURCE_OCCLUDED_CUES),
        "removal_windows": {cue: list(removal_windows[cue]) for cue in TARGET_CUES},
        "mask_authority": "accepted_tracked_bbox_plus_source_fill_stroke_palette_plus_paddle_humanseg",
        "rgb_authority": "exact_resolve_base_render_temporal_donor_reconstruction",
        "overlay_policy": "sparse_rgba_only_where_source_baked_caption_mask_is_nonzero",
        "donor_radius": DONOR_RADIUS,
        "donor_stride": DONOR_STRIDE,
        "cue_stats": cue_stats,
        "cue_checks": cue_checks,
        "segmentation": segmentation_rows,
        "frames": frame_rows,
        "summary": {
            "nonzero_frame_count": len(nonzero_rows),
            "max_mask_area_ratio": round(max_mask_area, 6),
            "median_inside_mask_mean_abs_diff": round(median_inside, 6),
            "median_donor_coverage_ratio": round(median_coverage, 6),
            "max_unresolved_ratio": round(max_unresolved, 6),
            "distinct_nonzero_rgba_hashes": len(nonzero_hashes),
        },
        "checks": checks,
        "artifacts": {
            "rgba_dir": str(rgba_dir),
            "cleaned_dir": str(cleaned_dir),
            "mask_dir": str(mask_dir),
            "foreground_dir": str(foreground_dir),
            "coverage_dir": str(coverage_dir),
            "before_after_contact_sheet": str(before_after_sheet),
            "mask_contact_sheet": str(mask_sheet),
            "first_rgba_file": str(rgba_dir / f"rgba_{CLEAN_RANGE[0]:06d}.png"),
        },
        "forbidden": [
            "raw_source_rgb_overlay",
            "whole_frame_replacement",
            "caption_recreation",
            "accepted_caption_property_mutation",
            "v4_occlusion_mutation",
            "grabcut_fallback",
        ],
        "visual_approval_required": True,
        "further_rollout_authorized": False,
    }
    write_json(output / "manifest.json", manifest)
    if not ok:
        failed = ",".join(key for key, value in checks.items() if not value)
        raise BuildError(f"checks:{failed}")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-render-dir", required=True)
    parser.add_argument("--caption-style", required=True)
    parser.add_argument("--lifecycle", required=True)
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--segmentation-max-side", type=int, default=960)
    parser.add_argument("--paddle-hub-module", default="humanseg_lite")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = run(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "task_id": TASK_ID, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({
        "ok": True,
        "task_id": TASK_ID,
        "clean_range": manifest["clean_range"],
        "nonzero_frames": manifest["summary"]["nonzero_frame_count"],
        "median_donor_coverage_ratio": manifest["summary"]["median_donor_coverage_ratio"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
