#!/usr/bin/env python3
"""Build a COME-only sparse baked-caption restore from exact Resolve base renders.

This proof intentionally handles only source-occluded `sub_052` (COME). The
source reel already proves that the woman is in front of COME, therefore the
restore mask is forbidden from touching the protected HumanSeg silhouette.
Only dark/gray COME glyph pixels inside the source-backed cue box and outside a
protected person margin are spatially inpainted from the same Resolve-rendered
frame. No temporal donor pixels and no foreground reconstruction are allowed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_COME_ONLY_V2"
SCHEMA = "video_cloner_baked_original_caption_removal_come_only_v2"
SCHEMA_VERSION = 1
EXPECTED_FPS = 24.0
CONTEXT_RANGE = (429, 453)
CLEAN_RANGE = (429, 453)
TARGET_CUE = "sub_052"
PERSON_PROTECTION_DILATION = 11
INPAINT_RADIUS = 5.0
MAX_MASK_AREA_RATIO = 0.025
MIN_MASKED_FRAME_RATIO = 0.70
MIN_MEDIAN_DARK_REDUCTION = 0.30


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
BASE = _load("vc_remove_baked_base_for_come_v2", HERE / "remove_baked_captions_window.py")


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise BuildError(f"render_frame_set:missing={sorted(expected-set(rows))}:extra={sorted(set(rows)-expected)}")
    return rows


def _palette_values(
    cue_id: str,
    style_map: Mapping[str, Mapping[str, Any]],
    profile_map: Mapping[str, Mapping[str, Any]],
    track_map: Mapping[str, Mapping[str, Any]],
) -> list[Tuple[int, int, int]]:
    event = style_map.get(cue_id) or {}
    track = track_map.get(cue_id) or {}
    profile_id = str(event.get("style_profile_id") or track.get("style_profile_id") or "")
    colors: list[Tuple[int, int, int]] = []
    for source in (event, profile_map.get(profile_id) or {}):
        color_map = source.get("colors") if isinstance(source.get("colors"), Mapping) else {}
        for key in ("fill", "stroke", "shadow"):
            rgb = BASE.parse_hex_rgb(color_map.get(key))
            if rgb is None:
                continue
            bgr = BASE.rgb_to_bgr(rgb)
            if bgr not in colors:
                colors.append(bgr)
    return colors


def _palette_candidate(crop: np.ndarray, palette: Sequence[Tuple[int, int, int]], threshold: float = 55.0) -> np.ndarray:
    if not palette:
        return np.zeros(crop.shape[:2], dtype=bool)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    result = np.zeros(crop.shape[:2], dtype=bool)
    for color in palette:
        swatch = cv2.cvtColor(np.uint8([[list(color)]]), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
        result |= np.linalg.norm(lab - swatch, axis=2) <= float(threshold)
    return result


def come_background_mask(
    frame: np.ndarray,
    bbox: Sequence[float],
    protected_person: np.ndarray,
    palette: Sequence[Tuple[int, int, int]],
) -> tuple[np.ndarray, Dict[str, Any]]:
    """Detect baked COME glyphs while hard-vetoing the person after morphology."""
    if protected_person.shape != frame.shape[:2]:
        raise BuildError("foreground_shape")
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = BASE.normalized_bbox_to_pixels(
        bbox, width, height, pad_x_ratio=0.035, pad_y_ratio=0.10
    )
    crop = frame[y1:y2, x1:x2]
    person = protected_person[y1:y2, x1:x2] > 0
    if crop.size == 0:
        raise BuildError("empty_crop")

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    contrast = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 2.0))
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]

    dark_neutral = (value <= 190) & (saturation <= 105) & (contrast >= 2)
    palette_match = _palette_candidate(crop, palette) & (contrast >= 1)
    candidate = (dark_neutral | palette_match) & ~person

    mask_crop = candidate.astype(np.uint8) * 255
    mask_crop = cv2.morphologyEx(mask_crop, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    mask_crop = cv2.dilate(mask_crop, np.ones((3, 3), np.uint8), iterations=1)
    mask_crop[person] = 0

    components, labels, stats, _ = cv2.connectedComponentsWithStats((mask_crop > 0).astype(np.uint8), 8)
    filtered = np.zeros_like(mask_crop)
    crop_area = max(1, mask_crop.size)
    for component in range(1, components):
        area = int(stats[component, cv2.CC_STAT_AREA])
        cw = int(stats[component, cv2.CC_STAT_WIDTH])
        ch = int(stats[component, cv2.CC_STAT_HEIGHT])
        if 8 <= area <= int(crop_area * 0.36) and cw >= 3 and ch >= 3:
            filtered[labels == component] = 255
    filtered[person] = 0

    result = np.zeros((height, width), dtype=np.uint8)
    result[y1:y2, x1:x2] = filtered
    overlap = int(np.count_nonzero((result > 0) & (protected_person > 0)))
    if overlap:
        raise BuildError(f"person_mask_overlap:{overlap}")
    return result, {
        "crop": [x1, y1, x2, y2],
        "mask_pixels": int(np.count_nonzero(result)),
        "person_overlap_pixels": overlap,
    }


def dark_glyph_score(frame: np.ndarray, bbox_pixels: Sequence[int], protected_person: np.ndarray) -> int:
    x1, y1, x2, y2 = [int(v) for v in bbox_pixels]
    crop = frame[y1:y2, x1:x2]
    person = protected_person[y1:y2, x1:x2] > 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    contrast = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 2.0))
    glyph = (hsv[:, :, 2] <= 190) & (hsv[:, :, 1] <= 105) & (contrast >= 2) & ~person
    return int(np.count_nonzero(glyph))


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
    for directory in (rgba_dir, cleaned_dir, mask_dir, foreground_dir):
        directory.mkdir()

    render_rows = indexed_pngs(base_dir, CONTEXT_RANGE)
    frames = []
    for number in range(*CONTEXT_RANGE):
        image = cv2.imread(str(render_rows[number]), cv2.IMREAD_COLOR)
        if image is None:
            raise BuildError(f"decode:{number}")
        if image.shape[:2] != (1920, 1080):
            raise BuildError(f"render_dimensions:{number}:{image.shape}")
        frames.append(image)

    style = BASE.load_json(Path(args.caption_style).resolve())
    lifecycle = BASE.load_json(Path(args.lifecycle).resolve())
    tracks = BASE.load_json(Path(args.tracks).resolve())
    style_map, profile_map, lifecycle_map, track_map = BASE.build_contract_maps(style, lifecycle, tracks)
    if TARGET_CUE not in lifecycle_map:
        raise BuildError("authority_missing:sub_052")
    palette = _palette_values(TARGET_CUE, style_map, profile_map, track_map)

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
        protected = BASE.protect_foreground(raw, PERSON_PROTECTION_DILATION)
        foreground_masks.append(protected)
        segmentation_rows.append({
            "frame": timeline_frame,
            "backend": backend,
            "device": device,
            "foreground_pixels": int(np.count_nonzero(protected)),
        })

    rows = []
    before_after = []
    mask_images = []
    labels = []
    mask_labels = []
    masked_frames = 0
    reductions = []
    distinct_rgba = set()
    sentinels = {429, 431, 434, 438, 443, 448, 452}

    for offset, (frame, protected) in enumerate(zip(frames, foreground_masks)):
        timeline_frame = CONTEXT_RANGE[0] + offset
        bbox = BASE.cue_bbox(TARGET_CUE, timeline_frame, style_map, lifecycle_map, track_map)
        if bbox is None:
            raise BuildError(f"bbox:{timeline_frame}")
        mask, meta = come_background_mask(frame, bbox, protected, palette)
        mask_pixels = int(np.count_nonzero(mask))
        if mask_pixels:
            masked_frames += 1
        mask_ratio = mask_pixels / float(mask.size)
        if mask_ratio > MAX_MASK_AREA_RATIO:
            raise BuildError(f"mask_area:{timeline_frame}:{mask_ratio:.6f}")

        cleaned = BASE.inpaint_caption_pixels(frame, mask, INPAINT_RADIUS)
        person_pixels = protected > 0
        cleaned[person_pixels] = frame[person_pixels]
        outside = mask == 0
        outside_mae = float(np.mean(np.abs(cleaned[outside].astype(np.int16) - frame[outside].astype(np.int16)))) if np.any(outside) else 0.0
        person_mae = float(np.mean(np.abs(cleaned[person_pixels].astype(np.int16) - frame[person_pixels].astype(np.int16)))) if np.any(person_pixels) else 0.0
        if outside_mae != 0.0 or person_mae != 0.0:
            raise BuildError(f"outside_or_person_changed:{timeline_frame}:{outside_mae}:{person_mae}")

        before_score = dark_glyph_score(frame, meta["crop"], protected)
        after_score = dark_glyph_score(cleaned, meta["crop"], protected)
        reduction = 0.0 if before_score <= 0 else max(0.0, (before_score - after_score) / float(before_score))
        if mask_pixels:
            reductions.append(reduction)

        cleaned_path = cleaned_dir / f"cleaned_{timeline_frame:06d}.png"
        mask_path = mask_dir / f"mask_{timeline_frame:06d}.png"
        foreground_path = foreground_dir / f"foreground_{timeline_frame:06d}.png"
        rgba_path = rgba_dir / f"rgba_{timeline_frame:06d}.png"
        for path, image in ((cleaned_path, cleaned), (mask_path, mask), (foreground_path, protected)):
            if not cv2.imwrite(str(path), image):
                raise BuildError(f"write:{path}")
        rgba = cv2.cvtColor(cleaned, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = mask
        if not cv2.imwrite(str(rgba_path), rgba):
            raise BuildError(f"write:{rgba_path}")
        if mask_pixels:
            distinct_rgba.add(sha256_file(rgba_path))

        rows.append({
            "frame": timeline_frame,
            "mask_pixels": mask_pixels,
            "mask_area_ratio": round(mask_ratio, 6),
            "person_overlap_pixels": int(np.count_nonzero((mask > 0) & person_pixels)),
            "outside_mean_abs_diff": round(outside_mae, 6),
            "person_mean_abs_diff": round(person_mae, 6),
            "dark_glyph_score_before": before_score,
            "dark_glyph_score_after": after_score,
            "dark_glyph_reduction": round(reduction, 6),
            "bbox_pixels": meta["crop"],
            "mask_sha256": sha256_file(mask_path),
            "cleaned_sha256": sha256_file(cleaned_path),
            "rgba_sha256": sha256_file(rgba_path),
        })
        if timeline_frame in sentinels:
            overlay = frame.copy()
            overlay[mask > 0] = (0, 0, 255)
            before_after.extend([frame, cleaned])
            mask_images.append(overlay)
            labels.extend([f"{timeline_frame} BEFORE", f"{timeline_frame} CLEANED"])
            mask_labels.append(f"{timeline_frame} MASK")

    masked_ratio = masked_frames / float(CLEAN_RANGE[1] - CLEAN_RANGE[0])
    median_reduction = float(np.median(reductions)) if reductions else 0.0
    before_after_sheet = output / "before_after_contact_sheet.jpg"
    mask_sheet = output / "mask_contact_sheet.jpg"
    _make_sheet(before_after, labels, before_after_sheet, columns=2)
    _make_sheet(mask_images, mask_labels, mask_sheet, columns=4)

    checks = {
        "target_cue_exact": True,
        "paddle_gpu_every_frame": len(segmentation_rows) == len(frames) and all(r["backend"] == "paddle_humanseg" and r["device"].startswith("gpu") for r in segmentation_rows),
        "person_overlap_zero_all_frames": all(int(r["person_overlap_pixels"]) == 0 for r in rows),
        "person_pixels_exact_all_frames": all(float(r["person_mean_abs_diff"]) == 0.0 for r in rows),
        "outside_mask_exact_all_frames": all(float(r["outside_mean_abs_diff"]) == 0.0 for r in rows),
        "mask_area_bounded": max(float(r["mask_area_ratio"]) for r in rows) <= MAX_MASK_AREA_RATIO,
        "masked_frame_coverage": masked_ratio >= MIN_MASKED_FRAME_RATIO,
        "dark_glyph_reduction": median_reduction >= MIN_MEDIAN_DARK_REDUCTION,
        "sequence_not_frozen": len(distinct_rgba) >= 3,
        "artifacts_exist": before_after_sheet.is_file() and mask_sheet.is_file(),
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "schema": SCHEMA,
        "task_id": TASK_ID,
        "ok": all(checks.values()),
        "context_range": list(CONTEXT_RANGE),
        "clean_range": list(CLEAN_RANGE),
        "target_cues": [TARGET_CUE],
        "mask_authority": "source_backed_sub_052_bbox_plus_dark_neutral_palette_hard_person_veto",
        "rgb_authority": "same_frame_exact_resolve_base_spatial_telea_background_only",
        "foreground_policy": "restore_alpha_intersection_with_protected_person_must_be_zero",
        "temporal_donor_reconstruction_used": False,
        "foreground_reconstruction_used": False,
        "thresholds": {
            "person_protection_dilation": PERSON_PROTECTION_DILATION,
            "inpaint_radius": INPAINT_RADIUS,
            "max_mask_area_ratio": MAX_MASK_AREA_RATIO,
            "min_masked_frame_ratio": MIN_MASKED_FRAME_RATIO,
            "min_median_dark_reduction": MIN_MEDIAN_DARK_REDUCTION,
        },
        "metrics": {
            "masked_frame_ratio": round(masked_ratio, 6),
            "median_dark_glyph_reduction": round(median_reduction, 6),
            "distinct_nonzero_rgba_hashes": len(distinct_rgba),
        },
        "checks": checks,
        "segmentation": segmentation_rows,
        "frames": rows,
        "artifacts": {
            "rgba_dir": str(rgba_dir),
            "cleaned_dir": str(cleaned_dir),
            "mask_dir": str(mask_dir),
            "foreground_dir": str(foreground_dir),
            "before_after_contact_sheet": str(before_after_sheet),
            "mask_contact_sheet": str(mask_sheet),
        },
        "visual_approval_required": True,
        "further_rollout_authorized": False,
    }
    write_json(output / "manifest.json", result)
    if not result["ok"]:
        raise BuildError("checks:" + ",".join(k for k, v in checks.items() if not v))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-render-dir", required=True, type=Path)
    parser.add_argument("--caption-style", required=True, type=Path)
    parser.add_argument("--lifecycle", required=True, type=Path)
    parser.add_argument("--tracks", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--paddle-hub-module", default="humanseg_lite")
    parser.add_argument("--segmentation-max-side", type=int, default=960)
    args = parser.parse_args()
    try:
        result = run(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "task_id": TASK_ID, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "task_id": TASK_ID, "masked_frame_ratio": result["metrics"]["masked_frame_ratio"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
