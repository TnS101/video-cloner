#!/usr/bin/env python3
"""Remove baked caption pixels from one bounded proxy-video window.

This is an offline capability proof. It does not modify DaVinci Resolve, the
accepted Text+ rollout, or the protected source timeline.

The script uses the existing Paddle HumanSeg backend to protect the foreground
subject, builds caption-pixel masks from the accepted lifecycle/style/tracking
contracts, inpaints only non-foreground caption pixels, and writes lossless
review artifacts for frames 420-462.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3D_CAPTION_REMOVAL_WINDOW_PROBE_V1"
SCHEMA = "video_cloner_baked_caption_removal_window_probe"
SCHEMA_VERSION = 1
DEFAULT_TARGET_CUES = ("sub_051", "sub_052", "sub_053", "sub_054", "sub_055", "sub_056")


class ProbeError(RuntimeError):
    pass


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ProbeError(f"json_root_not_object:{path}")
    return data


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_cue_id(value: Any) -> str:
    match = re.search(r"(\d+)\s*$", str(value or ""))
    if not match:
        return str(value or "").strip()
    return f"sub_{int(match.group(1)):03d}"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def parse_hex_rgb(value: Any) -> Optional[Tuple[int, int, int]]:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return None
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def rgb_to_bgr(rgb: Sequence[int]) -> Tuple[int, int, int]:
    return int(rgb[2]), int(rgb[1]), int(rgb[0])


def read_video_window(video_path: Path, frame_start: int, frame_end_exclusive: int) -> Tuple[List[np.ndarray], float]:
    if frame_start < 0 or frame_end_exclusive <= frame_start:
        raise ProbeError("invalid_frame_window")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ProbeError(f"video_open_failed:{video_path}")
    fps = safe_float(capture.get(cv2.CAP_PROP_FPS), 0.0)
    if fps <= 0:
        capture.release()
        raise ProbeError("video_fps_invalid")
    capture.set(cv2.CAP_PROP_POS_FRAMES, float(frame_start))
    frames: List[np.ndarray] = []
    for frame_number in range(frame_start, frame_end_exclusive):
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            raise ProbeError(f"video_frame_read_failed:{frame_number}")
        frames.append(frame)
    capture.release()
    return frames, fps


def build_contract_maps(
    style_contract: Mapping[str, Any],
    lifecycle_contract: Mapping[str, Any],
    track_contract: Mapping[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    style_events = style_contract.get("caption_style_events") or style_contract.get("style_events") or []
    style_map = {
        normalize_cue_id(event.get("cue_id")): event
        for event in style_events
        if isinstance(event, dict) and event.get("cue_id") is not None
    }
    profile_items = style_contract.get("caption_style_profiles") or style_contract.get("style_profiles") or []
    profile_map = {
        str(profile.get("style_id") or profile.get("style_profile_id") or ""): profile
        for profile in profile_items
        if isinstance(profile, dict)
    }
    lifecycle_map = {
        normalize_cue_id(layer.get("cue_id")): layer
        for layer in lifecycle_contract.get("layers", [])
        if isinstance(layer, dict) and layer.get("cue_id") is not None
    }
    track_map = {
        normalize_cue_id(track.get("cue_id")): track
        for track in track_contract.get("tracks", [])
        if isinstance(track, dict) and track.get("cue_id") is not None
    }
    return style_map, profile_map, lifecycle_map, track_map


def _observation_bbox(track: Mapping[str, Any], frame_number: int) -> Optional[List[float]]:
    observations = [
        item
        for item in track.get("frame_observations", [])
        if isinstance(item, dict) and isinstance(item.get("normalized_bbox"), (list, tuple))
    ]
    observations.sort(key=lambda item: int(item.get("timeline_frame", -1)))
    if not observations:
        return None
    for item in observations:
        if int(item.get("timeline_frame", -1)) == frame_number:
            return [safe_float(value) for value in item["normalized_bbox"]]
    before = [item for item in observations if int(item.get("timeline_frame", -1)) < frame_number]
    after = [item for item in observations if int(item.get("timeline_frame", -1)) > frame_number]
    if before and after:
        left, right = before[-1], after[0]
        left_frame = int(left["timeline_frame"])
        right_frame = int(right["timeline_frame"])
        if 0 < right_frame - left_frame <= 5:
            ratio = (frame_number - left_frame) / float(right_frame - left_frame)
            return [
                (1.0 - ratio) * safe_float(a) + ratio * safe_float(b)
                for a, b in zip(left["normalized_bbox"], right["normalized_bbox"])
            ]
    nearest = min(observations, key=lambda item: abs(int(item.get("timeline_frame", -1)) - frame_number))
    if abs(int(nearest.get("timeline_frame", -1)) - frame_number) <= 3:
        return [safe_float(value) for value in nearest["normalized_bbox"]]
    return None


def cue_bbox(
    cue_id: str,
    frame_number: int,
    style_map: Mapping[str, Mapping[str, Any]],
    lifecycle_map: Mapping[str, Mapping[str, Any]],
    track_map: Mapping[str, Mapping[str, Any]],
) -> Optional[List[float]]:
    track = track_map.get(cue_id)
    if track:
        observed = _observation_bbox(track, frame_number)
        if observed:
            return observed
    event = style_map.get(cue_id) or {}
    placement = event.get("placement") if isinstance(event.get("placement"), dict) else {}
    normalized = placement.get("normalized_bbox")
    if isinstance(normalized, (list, tuple)) and len(normalized) == 4:
        return [safe_float(value) for value in normalized]
    layer = lifecycle_map.get(cue_id) or {}
    targeted = layer.get("targeted_redetection") if isinstance(layer.get("targeted_redetection"), dict) else {}
    seed = targeted.get("source_seed") if isinstance(targeted.get("source_seed"), dict) else {}
    source_bbox = seed.get("source_bbox")
    if isinstance(source_bbox, (list, tuple)) and len(source_bbox) == 4:
        return [safe_float(value) for value in source_bbox]
    return None


def removal_window(
    cue_id: str,
    fps: float,
    style_map: Mapping[str, Mapping[str, Any]],
    lifecycle_map: Mapping[str, Mapping[str, Any]],
    track_map: Mapping[str, Mapping[str, Any]],
    lead_margin: int = 2,
    tail_margin: int = 1,
) -> Tuple[int, int]:
    starts: List[int] = []
    ends: List[int] = []
    layer = lifecycle_map.get(cue_id) or {}
    lifecycle = layer.get("lifecycle_window")
    if isinstance(lifecycle, (list, tuple)) and len(lifecycle) == 2:
        starts.append(int(lifecycle[0]))
        ends.append(int(lifecycle[1]))
    track = track_map.get(cue_id) or {}
    geometry = track.get("geometry") if isinstance(track.get("geometry"), dict) else {}
    first_visible = geometry.get("first_visible_frame")
    last_visible = geometry.get("last_visible_frame")
    if first_visible is not None:
        starts.append(int(first_visible))
    if last_visible is not None:
        ends.append(int(last_visible) + 1)
    event = style_map.get(cue_id) or {}
    if event.get("start") is not None:
        starts.append(int(math.floor(safe_float(event.get("start")) * fps)))
    if event.get("end") is not None:
        ends.append(int(math.ceil(safe_float(event.get("end")) * fps)))
    for observation in event.get("observations", []):
        if not isinstance(observation, dict) or observation.get("timestamp") is None:
            continue
        observation_frame = safe_float(observation.get("timestamp")) * fps
        starts.append(int(math.floor(observation_frame)))
        ends.append(int(math.ceil(observation_frame)) + 1)
    if not starts or not ends:
        raise ProbeError(f"removal_window_missing:{cue_id}")
    return min(starts) - int(lead_margin), max(ends) + int(tail_margin)


def normalized_bbox_to_pixels(
    bbox: Sequence[float],
    width: int,
    height: int,
    pad_x_ratio: float = 0.12,
    pad_y_ratio: float = 0.32,
) -> Tuple[int, int, int, int]:
    if len(bbox) != 4:
        raise ProbeError("bbox_malformed")
    x1, y1, x2, y2 = [safe_float(value) for value in bbox]
    if x2 <= x1 or y2 <= y1:
        raise ProbeError("bbox_invalid")
    box_width = x2 - x1
    box_height = y2 - y1
    x1 -= box_width * pad_x_ratio
    x2 += box_width * pad_x_ratio
    y1 -= box_height * pad_y_ratio
    y2 += box_height * pad_y_ratio
    return (
        max(0, min(width - 1, int(round(x1 * width)))),
        max(0, min(height - 1, int(round(y1 * height)))),
        max(1, min(width, int(round(x2 * width)))),
        max(1, min(height, int(round(y2 * height)))),
    )


def _palette_for_cue(
    cue_id: str,
    style_map: Mapping[str, Mapping[str, Any]],
    profile_map: Mapping[str, Mapping[str, Any]],
    track_map: Mapping[str, Mapping[str, Any]],
) -> List[Tuple[int, int, int]]:
    event = style_map.get(cue_id) or {}
    track = track_map.get(cue_id) or {}
    profile_id = str(event.get("style_profile_id") or track.get("style_profile_id") or "")
    sources = [event, profile_map.get(profile_id) or {}]
    colors: List[Tuple[int, int, int]] = []
    for source in sources:
        color_map = source.get("colors") if isinstance(source.get("colors"), dict) else {}
        for key in ("fill", "stroke", "shadow"):
            rgb = parse_hex_rgb(color_map.get(key))
            if rgb is not None:
                bgr = rgb_to_bgr(rgb)
                if bgr not in colors:
                    colors.append(bgr)
    return colors


def caption_pixel_mask(
    frame: np.ndarray,
    bbox: Sequence[float],
    foreground_mask: np.ndarray,
    palette_bgr: Sequence[Tuple[int, int, int]],
) -> np.ndarray:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = normalized_bbox_to_pixels(bbox, width, height)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return np.zeros((height, width), dtype=np.uint8)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]
    blurred = cv2.GaussianBlur(gray, (0, 0), 2.0)
    local_contrast = cv2.absdiff(gray, blurred)

    bright = (value >= 150) & (saturation <= 155) & (local_contrast >= 2)
    dark = (value <= 165) & (local_contrast >= 3)
    colored = (saturation >= 45) & (local_contrast >= 3)
    candidate = bright | dark | colored

    if palette_bgr:
        crop_lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.int16)
        palette_candidate = np.zeros(candidate.shape, dtype=bool)
        for color in palette_bgr:
            swatch = np.uint8([[list(color)]])
            swatch_lab = cv2.cvtColor(swatch, cv2.COLOR_BGR2LAB).astype(np.int16)[0, 0]
            distance = np.sqrt(np.sum((crop_lab - swatch_lab) ** 2, axis=2))
            palette_candidate |= distance <= 52.0
        candidate |= palette_candidate & (local_contrast >= 1)

    mask_crop = candidate.astype(np.uint8) * 255
    mask_crop = cv2.morphologyEx(mask_crop, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    mask_crop = cv2.dilate(mask_crop, np.ones((5, 5), np.uint8), iterations=1)

    foreground_crop = foreground_mask[y1:y2, x1:x2]
    mask_crop[foreground_crop > 0] = 0

    components, labels, stats, _ = cv2.connectedComponentsWithStats((mask_crop > 0).astype(np.uint8), 8)
    filtered = np.zeros_like(mask_crop)
    crop_area = max(1, mask_crop.shape[0] * mask_crop.shape[1])
    for component in range(1, components):
        area = int(stats[component, cv2.CC_STAT_AREA])
        component_width = int(stats[component, cv2.CC_STAT_WIDTH])
        component_height = int(stats[component, cv2.CC_STAT_HEIGHT])
        if 3 <= area <= int(crop_area * 0.60) and max(component_width, component_height) >= 2:
            filtered[labels == component] = 255

    result = np.zeros((height, width), dtype=np.uint8)
    result[y1:y2, x1:x2] = filtered
    return result


def protect_foreground(mask: np.ndarray, dilation: int = 5) -> np.ndarray:
    binary = (mask > 0).astype(np.uint8) * 255
    if dilation > 0:
        kernel_size = max(1, int(dilation))
        if kernel_size % 2 == 0:
            kernel_size += 1
        binary = cv2.dilate(binary, np.ones((kernel_size, kernel_size), np.uint8), iterations=1)
    return binary


def inpaint_caption_pixels(frame: np.ndarray, mask: np.ndarray, radius: float = 4.0) -> np.ndarray:
    if mask.shape != frame.shape[:2]:
        raise ProbeError("mask_shape_mismatch")
    if int(np.count_nonzero(mask)) == 0:
        return frame.copy()
    return cv2.inpaint(frame, mask, float(radius), cv2.INPAINT_TELEA)


def local_contrast_score(frame: np.ndarray, mask: np.ndarray) -> float:
    if int(np.count_nonzero(mask)) == 0:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (0, 0), 2.0)
    contrast = cv2.absdiff(gray, blurred)
    return float(np.mean(contrast[mask > 0]))


def make_contact_sheet(
    images: Sequence[np.ndarray],
    labels: Sequence[str],
    destination: Path,
    columns: int = 4,
    thumbnail_width: int = 304,
) -> None:
    if len(images) != len(labels) or not images:
        raise ProbeError("contact_sheet_inputs_invalid")
    thumbnail_height = int(round(images[0].shape[0] * thumbnail_width / images[0].shape[1]))
    label_height = 26
    rows = int(math.ceil(len(images) / float(columns)))
    sheet = np.full((rows * (thumbnail_height + label_height), columns * thumbnail_width, 3), 235, dtype=np.uint8)
    for index, (image, label) in enumerate(zip(images, labels)):
        resized = cv2.resize(image, (thumbnail_width, thumbnail_height), interpolation=cv2.INTER_AREA)
        row, column = divmod(index, columns)
        y = row * (thumbnail_height + label_height)
        x = column * thumbnail_width
        sheet[y : y + thumbnail_height, x : x + thumbnail_width] = resized
        cv2.putText(
            sheet,
            str(label),
            (x + 6, y + thumbnail_height + 19),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (25, 25, 25),
            1,
            cv2.LINE_AA,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), sheet):
        raise ProbeError(f"contact_sheet_write_failed:{destination}")


def encode_ffv1(frame_dir: Path, frame_start: int, fps: float, destination: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ProbeError("ffmpeg_not_found")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-framerate",
        f"{fps:.8f}",
        "-start_number",
        str(frame_start),
        "-i",
        str(frame_dir / "frame_%06d.png"),
        "-an",
        "-c:v",
        "ffv1",
        "-level",
        "3",
        str(destination),
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.returncode != 0 or not destination.is_file() or destination.stat().st_size <= 0:
        raise ProbeError(f"ffmpeg_encode_failed:{completed.returncode}:{completed.stderr.strip()}")


def run_probe(args: argparse.Namespace) -> Dict[str, Any]:
    video_path = Path(args.video).resolve()
    style_path = Path(args.caption_style).resolve()
    lifecycle_path = Path(args.lifecycle).resolve()
    tracks_path = Path(args.tracks).resolve()
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        raise ProbeError(f"output_dir_already_exists:{output_dir}")
    output_dir.mkdir(parents=True)
    frames_dir = output_dir / "frames"
    masks_dir = output_dir / "masks"
    foreground_dir = output_dir / "foreground_masks"
    frames_dir.mkdir()
    masks_dir.mkdir()
    foreground_dir.mkdir()

    frames, fps = read_video_window(video_path, args.frame_start, args.frame_end_exclusive)
    style_contract = load_json(style_path)
    lifecycle_contract = load_json(lifecycle_path)
    track_contract = load_json(tracks_path)
    style_map, profile_map, lifecycle_map, track_map = build_contract_maps(
        style_contract, lifecycle_contract, track_contract
    )
    target_cues = tuple(normalize_cue_id(value) for value in args.target_cues.split(",") if value.strip())
    if not target_cues:
        raise ProbeError("target_cues_empty")
    missing = [cue for cue in target_cues if cue not in lifecycle_map]
    if missing:
        raise ProbeError(f"target_cues_missing_from_lifecycle:{','.join(missing)}")

    removal_windows = {
        cue: removal_window(cue, fps, style_map, lifecycle_map, track_map)
        for cue in target_cues
    }

    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
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

    output_frames: List[np.ndarray] = []
    output_masks: List[np.ndarray] = []
    frame_rows: List[Dict[str, Any]] = []
    backend_counts: Dict[str, int] = {}

    for offset, frame in enumerate(frames):
        frame_number = args.frame_start + offset
        foreground_raw, segmentation = segmenter.segment(frame)
        backend = str(segmentation.get("backend") or "unknown")
        backend_counts[backend] = backend_counts.get(backend, 0) + 1
        if args.require_paddle_gpu:
            device = str(segmentation.get("device_selected") or segmentation.get("runtime", {}).get("device_selected") or "")
            if not segmentation.get("ok") or backend != "paddle_humanseg" or not device.startswith("gpu"):
                raise ProbeError(f"paddle_gpu_segmentation_required:{frame_number}:{backend}:{device}")
        foreground = protect_foreground(foreground_raw, args.foreground_dilation)
        active_cues: List[str] = []
        caption_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        if args.clean_start <= frame_number < args.clean_end_exclusive:
            for cue in target_cues:
                start, end = removal_windows[cue]
                if not (start <= frame_number < end):
                    continue
                bbox = cue_bbox(cue, frame_number, style_map, lifecycle_map, track_map)
                if bbox is None:
                    raise ProbeError(f"cue_bbox_missing:{cue}:{frame_number}")
                palette = _palette_for_cue(cue, style_map, profile_map, track_map)
                cue_mask = caption_pixel_mask(frame, bbox, foreground, palette)
                caption_mask = cv2.bitwise_or(caption_mask, cue_mask)
                active_cues.append(cue)
        caption_mask[foreground > 0] = 0
        cleaned = inpaint_caption_pixels(frame, caption_mask, args.inpaint_radius)

        outside = caption_mask == 0
        foreground_pixels = foreground > 0
        outside_diff = float(np.mean(np.abs(cleaned[outside].astype(np.int16) - frame[outside].astype(np.int16)))) if np.any(outside) else 0.0
        foreground_diff = float(np.mean(np.abs(cleaned[foreground_pixels].astype(np.int16) - frame[foreground_pixels].astype(np.int16)))) if np.any(foreground_pixels) else 0.0
        before_contrast = local_contrast_score(frame, caption_mask)
        after_contrast = local_contrast_score(cleaned, caption_mask)
        ratio = (after_contrast / before_contrast) if before_contrast > 1e-6 else 0.0

        frame_path = frames_dir / f"frame_{frame_number:06d}.png"
        mask_path = masks_dir / f"mask_{frame_number:06d}.png"
        foreground_path = foreground_dir / f"foreground_{frame_number:06d}.png"
        if not cv2.imwrite(str(frame_path), cleaned):
            raise ProbeError(f"frame_write_failed:{frame_number}")
        if not cv2.imwrite(str(mask_path), caption_mask):
            raise ProbeError(f"mask_write_failed:{frame_number}")
        if not cv2.imwrite(str(foreground_path), foreground):
            raise ProbeError(f"foreground_write_failed:{frame_number}")

        output_frames.append(cleaned)
        output_masks.append(caption_mask)
        frame_rows.append(
            {
                "frame": frame_number,
                "active_cues": active_cues,
                "mask_pixels": int(np.count_nonzero(caption_mask)),
                "foreground_pixels": int(np.count_nonzero(foreground)),
                "outside_mask_mean_abs_diff": round(outside_diff, 6),
                "protected_foreground_mean_abs_diff": round(foreground_diff, 6),
                "masked_local_contrast_before": round(before_contrast, 6),
                "masked_local_contrast_after": round(after_contrast, 6),
                "masked_local_contrast_ratio": round(ratio, 6),
                "segmentation_backend": backend,
                "segmentation_device": segmentation.get("device_selected") or segmentation.get("runtime", {}).get("device_selected"),
            }
        )

    sampled_numbers = sorted(set([args.clean_start, args.clean_start + 2, args.clean_start + 5, args.clean_start + 8, args.clean_start + 12, args.clean_start + 16, args.clean_end_exclusive - 2, args.clean_end_exclusive - 1]))
    before_after: List[np.ndarray] = []
    mask_previews: List[np.ndarray] = []
    labels: List[str] = []
    for frame_number in sampled_numbers:
        index = frame_number - args.frame_start
        if not (0 <= index < len(frames)):
            continue
        before_after.append(np.concatenate([frames[index], output_frames[index]], axis=1))
        mask_preview = cv2.cvtColor(output_masks[index], cv2.COLOR_GRAY2BGR)
        mask_previews.append(mask_preview)
        labels.append(str(frame_number))
    before_after_sheet = output_dir / "before_after_contact_sheet.jpg"
    mask_sheet = output_dir / "mask_contact_sheet.jpg"
    make_contact_sheet(before_after, labels, before_after_sheet, columns=2, thumbnail_width=608)
    make_contact_sheet(mask_previews, labels, mask_sheet, columns=4, thumbnail_width=304)

    video_output = output_dir / "cleaned_frames_420_462_ffv1.mkv"
    encode_ffv1(frames_dir, args.frame_start, fps, video_output)

    target_rows = [
        row for row in frame_rows if args.clean_start <= int(row["frame"]) < args.clean_end_exclusive
    ]
    nonzero_rows = [row for row in target_rows if int(row["mask_pixels"]) > 0]
    contrast_ratios = [safe_float(row["masked_local_contrast_ratio"]) for row in nonzero_rows]
    median_ratio = float(np.median(contrast_ratios)) if contrast_ratios else 999.0
    max_outside_diff = max((safe_float(row["outside_mask_mean_abs_diff"]) for row in frame_rows), default=0.0)
    max_foreground_diff = max((safe_float(row["protected_foreground_mean_abs_diff"]) for row in frame_rows), default=0.0)
    minimum_nonzero = max(1, int(math.ceil(len(target_rows) * args.minimum_masked_frame_ratio)))

    checks = {
        "frame_count_exact": len(frames) == args.frame_end_exclusive - args.frame_start,
        "target_frame_count_exact": len(target_rows) == args.clean_end_exclusive - args.clean_start,
        "masked_target_frames_sufficient": len(nonzero_rows) >= minimum_nonzero,
        "outside_mask_unchanged": max_outside_diff <= 0.0,
        "protected_foreground_unchanged": max_foreground_diff <= 0.0,
        "masked_contrast_reduced": median_ratio < 1.0,
        "paddle_gpu_only": (not args.require_paddle_gpu) or set(backend_counts) == {"paddle_humanseg"},
        "artifacts_exist": all(path.is_file() and path.stat().st_size > 0 for path in (video_output, before_after_sheet, mask_sheet)),
    }
    ok = all(checks.values())
    report = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "ok": ok,
        "video": str(video_path),
        "video_sha256": sha256_file(video_path),
        "fps": fps,
        "frame_window": [args.frame_start, args.frame_end_exclusive],
        "clean_window": [args.clean_start, args.clean_end_exclusive],
        "target_cues": list(target_cues),
        "removal_windows": {key: list(value) for key, value in removal_windows.items()},
        "segmentation_backend_counts": backend_counts,
        "frame_count": len(frames),
        "target_frame_count": len(target_rows),
        "masked_target_frame_count": len(nonzero_rows),
        "minimum_masked_target_frame_count": minimum_nonzero,
        "median_masked_local_contrast_ratio": round(median_ratio, 6),
        "max_outside_mask_mean_abs_diff": round(max_outside_diff, 6),
        "max_protected_foreground_mean_abs_diff": round(max_foreground_diff, 6),
        "checks": checks,
        "artifacts": {
            "cleaned_video": str(video_output),
            "before_after_contact_sheet": str(before_after_sheet),
            "mask_contact_sheet": str(mask_sheet),
            "cleaned_frames": str(frames_dir),
            "caption_masks": str(masks_dir),
            "foreground_masks": str(foreground_dir),
        },
        "frames": frame_rows,
        "visual_approval_required": True,
        "visual_review": "Review before_after_contact_sheet.jpg and cleaned_frames_420_462_ffv1.mkv. Accept only if baked words are removed without visible damage to the woman, sky, skyline, cuts, or motion.",
    }
    write_json(output_dir / "report.json", report)
    if not ok:
        failed = [name for name, passed in checks.items() if not passed]
        raise ProbeError(f"probe_checks_failed:{','.join(failed)}")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--caption-style", required=True)
    parser.add_argument("--lifecycle", required=True)
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--frame-start", type=int, default=420)
    parser.add_argument("--frame-end-exclusive", type=int, default=463)
    parser.add_argument("--clean-start", type=int, default=428)
    parser.add_argument("--clean-end-exclusive", type=int, default=452)
    parser.add_argument("--target-cues", default=",".join(DEFAULT_TARGET_CUES))
    parser.add_argument("--backend", default="paddle_humanseg")
    parser.add_argument("--segmentation-device", default="gpu")
    parser.add_argument("--paddle-gpu-id", type=int, default=0)
    parser.add_argument("--paddle-hub-module", default="humanseg_lite")
    parser.add_argument("--paddle-seg-threshold", type=float, default=0.50)
    parser.add_argument("--segmentation-max-side", type=int, default=720)
    parser.add_argument("--foreground-dilation", type=int, default=5)
    parser.add_argument("--inpaint-radius", type=float, default=4.0)
    parser.add_argument("--minimum-masked-frame-ratio", type=float, default=0.75)
    parser.add_argument("--require-paddle-gpu", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = run_probe(args)
    except Exception as exc:
        print(f"FAIL {TASK_ID}: {exc}", file=sys.stderr)
        return 1
    print(f"PASS {TASK_ID}")
    print(f"Output: {args.output_dir}")
    print(f"Masked target frames: {report['masked_target_frame_count']} / {report['target_frame_count']}")
    print(f"Median contrast ratio: {report['median_masked_local_contrast_ratio']}")
    print("Visual approval remains required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
