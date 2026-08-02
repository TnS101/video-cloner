#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np


BUILDER_VERSION = "caption_foreground_rgba_v1_2_local_caption_occlusion_patch"


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean, got: {value!r}")


def load_json(path: Path, encoding: str) -> Dict[str, Any]:
    with path.open("r", encoding=encoding) as f:
        return json.load(f)


def write_json(path: Path, payload: Dict[str, Any], encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def odd_kernel_from_radius(radius: float) -> int:
    if radius <= 0:
        return 0
    return max(3, int(round(radius * 2.0)) * 2 + 1)


def morphology(binary: np.ndarray, open_px: int, close_px: int) -> np.ndarray:
    result = binary
    if close_px > 0:
        k = max(1, int(close_px)) * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        result = cv2.morphologyEx(result, cv2.MORPH_CLOSE, kernel)
    if open_px > 0:
        k = max(1, int(open_px)) * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        result = cv2.morphologyEx(result, cv2.MORPH_OPEN, kernel)
    return result


def refine_alpha(
    small_mask: np.ndarray,
    frame_bgr: np.ndarray,
    threshold: int,
    mode: str,
    grabcut_iterations: int,
    erode_px: int,
    dilate_px: int,
    open_px: int,
    close_px: int,
    feather_radius_px: float,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    height, width = frame_bgr.shape[:2]
    binary_small = np.where(small_mask >= threshold, 255, 0).astype(np.uint8)
    upscaled = cv2.resize(binary_small, (width, height), interpolation=cv2.INTER_NEAREST)
    upscaled = morphology(upscaled, open_px=open_px, close_px=close_px)

    metadata: Dict[str, Any] = {
        "mode_requested": mode,
        "mode_used": mode,
        "grabcut_ok": None,
        "fallback_reason": None,
    }

    refined = upscaled
    if mode == "trimap_grabcut":
        try:
            erode_kernel_size = max(1, int(erode_px)) * 2 + 1
            dilate_kernel_size = max(1, int(dilate_px)) * 2 + 1
            erode_kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (erode_kernel_size, erode_kernel_size)
            )
            dilate_kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (dilate_kernel_size, dilate_kernel_size)
            )
            sure_fg = cv2.erode(upscaled, erode_kernel)
            possible_fg = cv2.dilate(upscaled, dilate_kernel)

            if int(np.count_nonzero(sure_fg)) == 0:
                raise RuntimeError("trimap has no sure foreground")
            if int(np.count_nonzero(possible_fg == 0)) == 0:
                raise RuntimeError("trimap has no sure background")

            gc_mask = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
            gc_mask[possible_fg > 0] = cv2.GC_PR_FGD
            gc_mask[sure_fg > 0] = cv2.GC_FGD

            bg_model = np.zeros((1, 65), np.float64)
            fg_model = np.zeros((1, 65), np.float64)
            cv2.grabCut(
                frame_bgr,
                gc_mask,
                None,
                bg_model,
                fg_model,
                max(1, int(grabcut_iterations)),
                cv2.GC_INIT_WITH_MASK,
            )
            refined = np.where(
                (gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD),
                255,
                0,
            ).astype(np.uint8)

            # Prevent GrabCut from growing far outside the canonical mask envelope.
            refined[possible_fg == 0] = 0
            refined = morphology(refined, open_px=open_px, close_px=close_px)
            metadata["grabcut_ok"] = True
        except Exception as exc:
            refined = upscaled
            metadata["mode_used"] = "resize_feather_fallback"
            metadata["grabcut_ok"] = False
            metadata["fallback_reason"] = str(exc)
    elif mode != "resize_feather":
        raise ValueError(f"Unsupported refine mode: {mode}")

    blur_kernel = odd_kernel_from_radius(feather_radius_px)
    if blur_kernel > 0:
        alpha = cv2.GaussianBlur(refined, (blur_kernel, blur_kernel), 0)
    else:
        alpha = refined

    alpha = np.clip(alpha, 0, 255).astype(np.uint8)
    return alpha, metadata


def checkerboard(width: int, height: int, cell: int = 20) -> np.ndarray:
    yy, xx = np.indices((height, width))
    pattern = ((xx // cell + yy // cell) % 2).astype(np.uint8)
    light = np.full((height, width, 3), 210, dtype=np.uint8)
    dark = np.full((height, width, 3), 150, dtype=np.uint8)
    return np.where(pattern[..., None] == 0, light, dark)


def composite_on_checker(frame_bgr: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    board = checkerboard(w, h)
    a = alpha.astype(np.float32)[..., None] / 255.0
    return np.clip(frame_bgr.astype(np.float32) * a + board.astype(np.float32) * (1.0 - a), 0, 255).astype(np.uint8)


def contact_sheet(rows: List[Tuple[int, np.ndarray, np.ndarray]], path: Path) -> None:
    if not rows:
        return
    preview_width = 240
    cells: List[np.ndarray] = []
    for frame_index, frame_bgr, alpha in rows:
        h, w = frame_bgr.shape[:2]
        preview_height = max(1, int(round(h * (preview_width / float(w)))))
        source_preview = cv2.resize(frame_bgr, (preview_width, preview_height), interpolation=cv2.INTER_AREA)
        alpha_preview = cv2.resize(alpha, (preview_width, preview_height), interpolation=cv2.INTER_AREA)
        alpha_bgr = cv2.cvtColor(alpha_preview, cv2.COLOR_GRAY2BGR)
        composite_preview = cv2.resize(
            composite_on_checker(frame_bgr, alpha),
            (preview_width, preview_height),
            interpolation=cv2.INTER_AREA,
        )
        strip = np.hstack([source_preview, alpha_bgr, composite_preview])
        cv2.putText(
            strip,
            f"frame {frame_index} | source | alpha | RGBA preview",
            (10, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cells.append(strip)
    sheet = np.vstack(cells)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), sheet):
        raise RuntimeError(f"Failed to write contact sheet: {path}")


def resolve_mask_path(
    span: Dict[str, Any],
    frame_index: int,
    mask_root_override: Optional[Path],
) -> Path:
    span_id = str(span["span_id"])
    if mask_root_override:
        candidate = mask_root_override / span_id / f"mask_{frame_index:06d}.png"
        if candidate.is_file():
            return candidate

    mask_asset = span.get("mask_asset") or {}
    pattern = str(mask_asset.get("mask_pattern") or "")
    if pattern:
        try:
            candidate = Path(pattern % frame_index)
            if candidate.is_file():
                return candidate
        except TypeError:
            pass

    event_dir = mask_asset.get("event_dir")
    if event_dir:
        candidate = Path(str(event_dir)) / f"mask_{frame_index:06d}.png"
        if candidate.is_file():
            return candidate

    relative = str(mask_asset.get("relative_mask_pattern") or "")
    if mask_root_override and relative:
        relative = relative.replace("\\", os.sep).replace("/", os.sep)
        try:
            candidate = mask_root_override / Path(relative % frame_index)
            if candidate.is_file():
                return candidate
        except TypeError:
            pass

    raise FileNotFoundError(
        f"Could not resolve mask for {span_id} frame {frame_index}. "
        "Use --mask-root when the contract was moved."
    )


def frame_iou(alpha_a: np.ndarray, alpha_b: np.ndarray, threshold: int = 127) -> float:
    a = alpha_a >= threshold
    b = alpha_b >= threshold
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return 1.0
    inter = int(np.count_nonzero(a & b))
    return inter / float(union)



def load_caption_regions(
    occlusion_path: Path,
    spans: List[Dict[str, Any]],
    encoding: str,
) -> Dict[str, Dict[str, Any]]:
    report = load_json(occlusion_path, encoding)
    events = report.get("occlusion_events") or []
    by_index: Dict[int, Dict[str, Any]] = {}
    by_cue: Dict[str, Dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            by_index[int(event.get("index"))] = event
        except Exception:
            pass
        cue_id = str(event.get("cue_id") or "")
        if cue_id:
            by_cue[cue_id] = event

    result: Dict[str, Dict[str, Any]] = {}
    for span in spans:
        span_id = str(span.get("span_id") or "")
        matched: List[Dict[str, Any]] = []

        for idx in span.get("source_event_indexes") or []:
            try:
                event = by_index.get(int(idx))
            except Exception:
                event = None
            if event:
                matched.append(event)

        for cue_id in span.get("affected_cue_ids") or []:
            event = by_cue.get(str(cue_id))
            if event and event not in matched:
                matched.append(event)

        boxes: List[List[float]] = []
        event_ids: List[str] = []
        for event in matched:
            bbox = event.get("normalized_bbox")
            if (
                isinstance(bbox, list)
                and len(bbox) == 4
                and all(isinstance(v, (int, float)) for v in bbox)
            ):
                x1, y1, x2, y2 = [float(v) for v in bbox]
                if 0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0:
                    boxes.append([x1, y1, x2, y2])
                    event_ids.append(str(event.get("id") or event.get("caption_event_id") or ""))

        if boxes:
            result[span_id] = {
                "normalized_bbox": [
                    min(b[0] for b in boxes),
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                ],
                "source_event_ids": event_ids,
                "matched_event_count": len(boxes),
            }
    return result


def build_local_occlusion_region(
    normalized_bbox: List[float],
    width: int,
    height: int,
    padding_x_ratio: float,
    padding_y_ratio: float,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    x1, y1, x2, y2 = [float(v) for v in normalized_bbox]
    box_w = max(1.0 / width, x2 - x1)
    box_h = max(1.0 / height, y2 - y1)

    px = box_w * max(0.0, padding_x_ratio)
    py = box_h * max(0.0, padding_y_ratio)

    ex1 = max(0.0, x1 - px)
    ey1 = max(0.0, y1 - py)
    ex2 = min(1.0, x2 + px)
    ey2 = min(1.0, y2 + py)

    ix1 = max(0, min(width - 1, int(math.floor(ex1 * width))))
    iy1 = max(0, min(height - 1, int(math.floor(ey1 * height))))
    ix2 = max(ix1 + 1, min(width, int(math.ceil(ex2 * width))))
    iy2 = max(iy1 + 1, min(height, int(math.ceil(ey2 * height))))

    region = np.zeros((height, width), dtype=np.uint8)
    region[iy1:iy2, ix1:ix2] = 255
    return region, {
        "source_normalized_bbox": [x1, y1, x2, y2],
        "expanded_normalized_bbox": [ex1, ey1, ex2, ey2],
        "expanded_pixel_bbox": [ix1, iy1, ix2, iy2],
        "padding_x_ratio_of_caption_width": padding_x_ratio,
        "padding_y_ratio_of_caption_height": padding_y_ratio,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build full-resolution straight-alpha RGBA foreground assets from a matte-span contract."
    )
    parser.add_argument("--video", required=True, help="Original/full-resolution source video.")
    parser.add_argument("--contract", required=True, help="Step 2C caption matte contract JSON.")
    parser.add_argument("--caption-occlusion", required=True, help="v1.9 caption occlusion JSON used to resolve the target caption bbox.")
    parser.add_argument("--output-root", required=True, help="Output root for per-span RGBA PNG sequences.")
    parser.add_argument("--output-contract", required=True, help="Output foreground-asset contract JSON.")
    parser.add_argument("--mask-root", default="", help="Optional override for foreground_matte_spans root.")
    parser.add_argument("--clear-output", type=parse_bool, default=True)
    parser.add_argument("--require-full-resolution", type=parse_bool, default=True)
    parser.add_argument("--fps-tolerance", type=float, default=0.05, help="Only used to decide whether remapping is reported as active.")
    parser.add_argument("--duration-tolerance-sec", type=float, default=0.12)
    parser.add_argument("--timebase-policy", choices=["remap_by_timestamp", "require_equal"], default="remap_by_timestamp")
    parser.add_argument("--refine-mode", choices=["trimap_grabcut", "resize_feather"], default="trimap_grabcut")
    parser.add_argument("--grabcut-iterations", type=int, default=2)
    parser.add_argument("--trimap-erode-px", type=int, default=3)
    parser.add_argument("--trimap-dilate-px", type=int, default=10)
    parser.add_argument("--morph-open-px", type=int, default=0)
    parser.add_argument("--morph-close-px", type=int, default=2)
    parser.add_argument("--feather-radius-px", type=float, default=1.5)
    parser.add_argument("--mask-threshold", type=int, default=127)
    parser.add_argument("--clip-to-caption-region", type=parse_bool, default=True)
    parser.add_argument("--caption-padding-x-ratio", type=float, default=0.18)
    parser.add_argument("--caption-padding-y-ratio", type=float, default=0.42)
    parser.add_argument("--write-contact-sheet", type=parse_bool, default=True)
    parser.add_argument("--encoding", choices=["utf-8", "utf-8-sig"], default="utf-8")
    args = parser.parse_args()

    started = time.time()
    video_path = Path(args.video)
    contract_path = Path(args.contract)
    caption_occlusion_path = Path(args.caption_occlusion)
    output_root = Path(args.output_root)
    output_contract_path = Path(args.output_contract)
    mask_root_override = Path(args.mask_root) if args.mask_root else None

    failures: List[str] = []
    warnings: List[str] = []

    if not video_path.is_file():
        raise FileNotFoundError(f"Source video not found: {video_path}")
    if not contract_path.is_file():
        raise FileNotFoundError(f"Matte contract not found: {contract_path}")

    contract = load_json(contract_path, args.encoding)
    if not contract.get("success") or not contract.get("ok"):
        raise RuntimeError("Step 2C contract is not successful/ok")
    if not (contract.get("summary") or {}).get("ready_for_matte_asset_build"):
        raise RuntimeError("Step 2C contract is not ready_for_matte_asset_build")

    spans = [s for s in (contract.get("matte_spans") or []) if s.get("complete")]
    if not spans:
        raise RuntimeError("No complete matte spans found")

    if not caption_occlusion_path.is_file():
        raise FileNotFoundError(f"Caption occlusion JSON not found: {caption_occlusion_path}")

    caption_regions = load_caption_regions(
        caption_occlusion_path,
        spans,
        args.encoding,
    )
    if args.clip_to_caption_region:
        for span in spans:
            span_id = str(span.get("span_id") or "")
            if span_id not in caption_regions:
                raise RuntimeError(
                    f"No valid normalized caption bbox found for {span_id}. "
                    "Refusing to build a full-body V4 overlay."
                )

    if args.clear_output and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source video: {video_path}")

    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    source_frame_count = int(round(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
    source_width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0))
    source_height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))

    contract_fps = float((contract.get("video_info") or {}).get("fps") or spans[0].get("fps") or 0.0)
    mask_width = int(((spans[0].get("mask_asset") or {}).get("width") or 0))
    mask_height = int(((spans[0].get("mask_asset") or {}).get("height") or 0))

    if source_fps <= 0:
        failures.append("source_video_invalid_fps")
    if contract_fps <= 0:
        failures.append("contract_invalid_fps")

    timebase_remap_applied = (
        source_fps > 0
        and contract_fps > 0
        and abs(source_fps - contract_fps) > args.fps_tolerance
    )
    if timebase_remap_applied and args.timebase_policy == "require_equal":
        failures.append(
            f"fps_mismatch: source={source_fps:.6f}, contract={contract_fps:.6f}, "
            f"policy={args.timebase_policy}"
        )
    elif timebase_remap_applied:
        warnings.append(
            f"timebase_remap_active: contract={contract_fps:.6f}fps -> source={source_fps:.6f}fps"
        )

    source_duration_seconds = (
        source_frame_count / source_fps if source_fps > 0 and source_frame_count > 0 else 0.0
    )
    contract_frame_count = int((contract.get("video_info") or {}).get("frame_count") or 0)
    contract_duration_seconds = (
        contract_frame_count / contract_fps
        if contract_fps > 0 and contract_frame_count > 0
        else 0.0
    )
    duration_delta_seconds = (
        abs(source_duration_seconds - contract_duration_seconds)
        if source_duration_seconds > 0 and contract_duration_seconds > 0
        else None
    )
    if (
        duration_delta_seconds is not None
        and duration_delta_seconds > args.duration_tolerance_sec
    ):
        failures.append(
            f"duration_mismatch: source={source_duration_seconds:.6f}s, "
            f"contract={contract_duration_seconds:.6f}s, "
            f"delta={duration_delta_seconds:.6f}s, "
            f"tolerance={args.duration_tolerance_sec:.6f}s"
        )

    if source_width <= 0 or source_height <= 0:
        failures.append("source_video_invalid_dimensions")
    if args.require_full_resolution and source_width <= mask_width and source_height <= mask_height:
        failures.append(
            f"source_video_not_higher_resolution: source={source_width}x{source_height}, mask={mask_width}x{mask_height}"
        )

    # Step 2C frame numbers belong to the contract/proxy/timeline timebase.
    # The original source may use another FPS. Map each contract frame by timestamp
    # to the nearest decodable source frame, while keeping output PNG names in the
    # contract/timeline frame domain.
    requested_source_frames: Dict[int, List[Dict[str, Any]]] = {}
    requested_contract_frame_count = 0
    source_mapping_records: List[Dict[str, Any]] = []
    max_requested_source_frame = -1

    for span in spans:
        contract_start = int(span["source_frame_start"])
        contract_end = int(span["source_frame_end_exclusive"])
        timeline_start = int(span.get("timeline_frame_start", contract_start))
        timeline_offset = timeline_start - contract_start

        if contract_end <= contract_start:
            failures.append(f"{span.get('span_id')}: invalid_frame_interval")
            continue

        for contract_frame in range(contract_start, contract_end):
            contract_timestamp = contract_frame / contract_fps
            unclamped_source_frame = int(round(contract_timestamp * source_fps))
            source_frame = unclamped_source_frame

            if source_frame_count > 0:
                source_frame = max(0, min(source_frame, source_frame_count - 1))

            timeline_frame = contract_frame + timeline_offset
            source_timestamp = source_frame / source_fps
            timing_error_seconds = source_timestamp - contract_timestamp

            job = {
                "span": span,
                "contract_frame": contract_frame,
                "timeline_frame": timeline_frame,
                "source_frame": source_frame,
                "contract_timestamp": contract_timestamp,
                "source_timestamp": source_timestamp,
                "timing_error_seconds": timing_error_seconds,
                "source_frame_was_clamped": source_frame != unclamped_source_frame,
            }
            requested_source_frames.setdefault(source_frame, []).append(job)
            requested_contract_frame_count += 1
            max_requested_source_frame = max(max_requested_source_frame, source_frame)
            source_mapping_records.append({
                "span_id": str(span.get("span_id")),
                "contract_frame": contract_frame,
                "timeline_frame": timeline_frame,
                "source_video_frame": source_frame,
                "contract_timestamp": round(contract_timestamp, 9),
                "source_timestamp": round(source_timestamp, 9),
                "timing_error_seconds": round(timing_error_seconds, 9),
                "source_frame_was_clamped": source_frame != unclamped_source_frame,
            })

    max_abs_timing_error = max(
        (abs(float(row["timing_error_seconds"])) for row in source_mapping_records),
        default=0.0,
    )
    nearest_frame_error_limit = (0.5 / source_fps) + 1e-6 if source_fps > 0 else 0.0
    if max_abs_timing_error > nearest_frame_error_limit:
        failures.append(
            f"timebase_mapping_error_too_large: max={max_abs_timing_error:.9f}s, "
            f"limit={nearest_frame_error_limit:.9f}s"
        )

    if failures:
        cap.release()
        payload = {
            "success": False,
            "ok": False,
            "schema": "video_cloner_caption_foreground_assets",
            "schema_version": "1.1",
            "builder_version": BUILDER_VERSION,
            "inputs": {"video": str(video_path), "contract": str(contract_path)},
            "timebase": {
                "policy": args.timebase_policy,
                "contract_fps": contract_fps,
                "source_fps": source_fps,
                "remap_applied": timebase_remap_applied,
                "source_duration_seconds": source_duration_seconds,
                "contract_duration_seconds": contract_duration_seconds,
                "duration_delta_seconds": duration_delta_seconds,
            },
            "failures": failures,
            "warnings": warnings,
        }
        write_json(output_contract_path, payload, args.encoding)
        print(json.dumps(payload, ensure_ascii=False))
        return 1

    span_state: Dict[str, Dict[str, Any]] = {}
    for span in spans:
        span_id = str(span["span_id"])
        span_dir = output_root / span_id
        span_dir.mkdir(parents=True, exist_ok=True)
        span_state[span_id] = {
            "span": span,
            "dir": span_dir,
            "frames": [],
            "contact_rows": [],
            "previous_alpha": None,
            "adjacent_ious": [],
            "grabcut_fallback_count": 0,
            "caption_region": caption_regions.get(span_id),
            "caption_region_runtime": None,
            "alpha_pixels_removed_outside_caption_region": 0,
            "errors": [],
        }

    source_frame_index = 0
    decoded_requested = 0
    while source_frame_index <= max_requested_source_frame:
        ok, frame_bgr = cap.read()
        if not ok or frame_bgr is None:
            failures.append(f"source_frame_read_failed:{source_frame_index}")
            break

        jobs = requested_source_frames.get(source_frame_index, [])
        for job in jobs:
            span = job["span"]
            span_id = str(span["span_id"])
            state = span_state[span_id]
            contract_frame = int(job["contract_frame"])
            timeline_frame = int(job["timeline_frame"])

            try:
                mask_path = resolve_mask_path(span, contract_frame, mask_root_override)
                small_mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
                if small_mask is None:
                    raise RuntimeError(f"Unreadable mask: {mask_path}")

                alpha, refine_meta = refine_alpha(
                    small_mask=small_mask,
                    frame_bgr=frame_bgr,
                    threshold=args.mask_threshold,
                    mode=args.refine_mode,
                    grabcut_iterations=args.grabcut_iterations,
                    erode_px=args.trimap_erode_px,
                    dilate_px=args.trimap_dilate_px,
                    open_px=args.morph_open_px,
                    close_px=args.morph_close_px,
                    feather_radius_px=args.feather_radius_px,
                )
                if refine_meta.get("grabcut_ok") is False:
                    state["grabcut_fallback_count"] += 1

                if args.clip_to_caption_region:
                    region_info = state.get("caption_region") or {}
                    normalized_bbox = region_info.get("normalized_bbox")
                    if not normalized_bbox:
                        raise RuntimeError("caption region is missing")
                    region_mask, region_runtime = build_local_occlusion_region(
                        normalized_bbox=normalized_bbox,
                        width=source_width,
                        height=source_height,
                        padding_x_ratio=args.caption_padding_x_ratio,
                        padding_y_ratio=args.caption_padding_y_ratio,
                    )
                    before_nonzero = int(np.count_nonzero(alpha))
                    alpha = cv2.bitwise_and(alpha, region_mask)
                    after_nonzero = int(np.count_nonzero(alpha))
                    state["alpha_pixels_removed_outside_caption_region"] += max(
                        0, before_nonzero - after_nonzero
                    )
                    state["caption_region_runtime"] = region_runtime
                    if after_nonzero == 0:
                        raise RuntimeError(
                            "local caption-region clipping removed the entire foreground"
                        )

                rgba = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)
                rgba[:, :, 3] = alpha

                # Output names stay in timeline/contract frame space. This gives the
                # downstream editor a five-frame 24fps sequence even though RGB pixels
                # were sampled from the matching 30fps source timestamps.
                rgba_path = state["dir"] / f"rgba_{timeline_frame:06d}.png"
                alpha_path = state["dir"] / f"alpha_fullres_{timeline_frame:06d}.png"
                if not cv2.imwrite(str(rgba_path), rgba):
                    raise RuntimeError(f"Failed to write RGBA: {rgba_path}")
                if not cv2.imwrite(str(alpha_path), alpha):
                    raise RuntimeError(f"Failed to write alpha: {alpha_path}")

                previous_alpha = state["previous_alpha"]
                if previous_alpha is not None:
                    state["adjacent_ious"].append(frame_iou(previous_alpha, alpha))
                state["previous_alpha"] = alpha.copy()

                alpha_nonzero = int(np.count_nonzero(alpha))
                alpha_opaque = int(np.count_nonzero(alpha == 255))
                total_pixels = int(alpha.size)
                state["frames"].append({
                    "contract_frame": contract_frame,
                    "timeline_frame": timeline_frame,
                    "source_video_frame": source_frame_index,
                    "contract_timestamp": round(float(job["contract_timestamp"]), 9),
                    "source_timestamp": round(float(job["source_timestamp"]), 9),
                    "timing_error_seconds": round(float(job["timing_error_seconds"]), 9),
                    "source_frame_was_clamped": bool(job["source_frame_was_clamped"]),
                    "rgba_path": str(rgba_path),
                    "rgba_sha256": sha256_file(rgba_path),
                    "alpha_path": str(alpha_path),
                    "alpha_sha256": sha256_file(alpha_path),
                    "source_mask_path": str(mask_path),
                    "source_mask_sha256": sha256_file(mask_path),
                    "width": source_width,
                    "height": source_height,
                    "channels": 4,
                    "alpha_nonzero_ratio": round(alpha_nonzero / float(total_pixels), 6),
                    "alpha_opaque_ratio": round(alpha_opaque / float(total_pixels), 6),
                    "alpha_min": int(alpha.min()),
                    "alpha_max": int(alpha.max()),
                    "refinement": refine_meta,
                    "local_occlusion_region": state.get("caption_region_runtime"),
                })
                state["contact_rows"].append((timeline_frame, frame_bgr.copy(), alpha.copy()))
                decoded_requested += 1
            except Exception as exc:
                state["errors"].append(
                    f"timeline frame {timeline_frame} / source frame {source_frame_index}: {exc}"
                )
                failures.append(
                    f"{span_id}: timeline frame {timeline_frame} / "
                    f"source frame {source_frame_index}: {exc}"
                )

        source_frame_index += 1

    cap.release()

    asset_spans: List[Dict[str, Any]] = []
    total_rgba_frames = 0
    total_fallbacks = 0
    for span_id, state in span_state.items():
        span = state["span"]
        expected = int(span["duration_frames"])
        written = len(state["frames"])
        total_rgba_frames += written
        total_fallbacks += int(state["grabcut_fallback_count"])
        complete = written == expected and not state["errors"]
        contact_path = state["dir"] / "contact_sheet.jpg"
        if args.write_contact_sheet and state["contact_rows"]:
            try:
                contact_sheet(state["contact_rows"], contact_path)
            except Exception as exc:
                state["errors"].append(f"contact_sheet: {exc}")
                failures.append(f"{span_id}: contact_sheet: {exc}")
                complete = False

        adjacent_ious = state["adjacent_ious"]
        manifest = {
            "schema": "video_cloner_caption_foreground_rgba_span",
            "schema_version": "1.1",
            "builder_version": BUILDER_VERSION,
            "span_id": span_id,
            "complete": complete,
            "source_video": str(video_path),
            "contract_frame_start": int(span["source_frame_start"]),
            "contract_frame_end_exclusive": int(span["source_frame_end_exclusive"]),
            "source_frame_start": int(span["source_frame_start"]),
            "source_frame_end_exclusive": int(span["source_frame_end_exclusive"]),
            "timeline_frame_start": int(span["timeline_frame_start"]),
            "timeline_frame_end_exclusive": int(span["timeline_frame_end_exclusive"]),
            "duration_frames": expected,
            "source_video_frame_start": min((f["source_video_frame"] for f in state["frames"]), default=None),
            "source_video_frame_end_exclusive": (max((f["source_video_frame"] for f in state["frames"]), default=-1) + 1) if state["frames"] else None,
            "timeline_fps": contract_fps,
            "source_video_fps": source_fps,
            "timebase_remap_applied": timebase_remap_applied,
            "width": source_width,
            "height": source_height,
            "pixel_format": "RGBA8",
            "alpha_mode": "straight_unassociated",
            "rgba_pattern": str(state["dir"] / "rgba_%06d.png"),
            "alpha_pattern": str(state["dir"] / "alpha_fullres_%06d.png"),
            "contact_sheet": str(contact_path) if contact_path.is_file() else None,
            "affected_cue_ids": span.get("affected_cue_ids") or [],
            "affected_texts": span.get("affected_texts") or [],
            "mask_source_resolution": {"width": mask_width, "height": mask_height},
            "output_resolution": {"width": source_width, "height": source_height},
            "upscale_ratio": {
                "x": round(source_width / float(mask_width), 6) if mask_width else None,
                "y": round(source_height / float(mask_height), 6) if mask_height else None,
            },
            "asset_scope": "local_foreground_patch_intersecting_caption_region",
            "caption_region": {
                "enabled": bool(args.clip_to_caption_region),
                "source": state.get("caption_region"),
                "runtime": state.get("caption_region_runtime"),
                "alpha_pixels_removed_outside_region": int(
                    state.get("alpha_pixels_removed_outside_caption_region") or 0
                ),
            },
            "refinement_config": {
                "mode": args.refine_mode,
                "grabcut_iterations": args.grabcut_iterations,
                "trimap_erode_px": args.trimap_erode_px,
                "trimap_dilate_px": args.trimap_dilate_px,
                "morph_open_px": args.morph_open_px,
                "morph_close_px": args.morph_close_px,
                "feather_radius_px": args.feather_radius_px,
                "mask_threshold": args.mask_threshold,
            },
            "quality": {
                "grabcut_fallback_count": int(state["grabcut_fallback_count"]),
                "adjacent_alpha_iou_min": round(min(adjacent_ious), 6) if adjacent_ious else None,
                "adjacent_alpha_iou_median": round(float(np.median(adjacent_ious)), 6) if adjacent_ious else None,
            },
            "frame_count_expected": expected,
            "frame_count_written": written,
            "frames": state["frames"],
            "errors": state["errors"],
        }
        manifest_path = state["dir"] / "manifest.json"
        write_json(manifest_path, manifest, args.encoding)
        asset_spans.append({
            "span_id": span_id,
            "complete": complete,
            "source_frame_start": int(span["source_frame_start"]),
            "source_frame_end_exclusive": int(span["source_frame_end_exclusive"]),
            "timeline_frame_start": int(span["timeline_frame_start"]),
            "timeline_frame_end_exclusive": int(span["timeline_frame_end_exclusive"]),
            "duration_frames": expected,
            "contract_fps": contract_fps,
            "source_video_fps": source_fps,
            "timebase_remap_applied": timebase_remap_applied,
            "source_video_frame_start": min((f["source_video_frame"] for f in state["frames"]), default=None),
            "source_video_frame_end_exclusive": (max((f["source_video_frame"] for f in state["frames"]), default=-1) + 1) if state["frames"] else None,
            "affected_cue_ids": span.get("affected_cue_ids") or [],
            "asset_scope": "local_foreground_patch_intersecting_caption_region",
            "caption_region": {
                "source": state.get("caption_region"),
                "runtime": state.get("caption_region_runtime"),
            },
            "rgba_asset": {
                "asset_type": "png_sequence_rgba8_straight_alpha",
                "event_dir": str(state["dir"]),
                "rgba_pattern": str(state["dir"] / "rgba_%06d.png"),
                "alpha_pattern": str(state["dir"] / "alpha_fullres_%06d.png"),
                "manifest": str(manifest_path),
                "contact_sheet": str(contact_path) if contact_path.is_file() else None,
                "frame_count_expected": expected,
                "frame_count_written": written,
                "width": source_width,
                "height": source_height,
                "complete": complete,
            },
            "quality": manifest["quality"],
            "errors": state["errors"],
        })

    complete_count = sum(1 for span in asset_spans if span["complete"])
    success = not failures and complete_count == len(asset_spans)
    payload = {
        "success": success,
        "ok": success,
        "schema": "video_cloner_caption_foreground_assets",
        "schema_version": "1.1",
        "builder_version": BUILDER_VERSION,
        "created_at_unix": time.time(),
        "elapsed_seconds": round(time.time() - started, 4),
        "inputs": {
            "source_video": str(video_path),
            "matte_contract": str(contract_path),
            "caption_occlusion": str(caption_occlusion_path),
            "mask_root_override": str(mask_root_override) if mask_root_override else None,
        },
        "outputs": {
            "asset_contract": str(output_contract_path),
            "rgba_root": str(output_root),
        },
        "timebase": {
            "policy": args.timebase_policy,
            "contract_fps": contract_fps,
            "source_video_fps": source_fps,
            "remap_applied": timebase_remap_applied,
            "mapping_method": "nearest_source_frame_by_contract_timestamp",
            "source_duration_seconds": round(source_duration_seconds, 9),
            "contract_duration_seconds": round(contract_duration_seconds, 9),
            "duration_delta_seconds": round(duration_delta_seconds, 9) if duration_delta_seconds is not None else None,
            "max_abs_timing_error_seconds": round(max_abs_timing_error, 9),
            "nearest_frame_error_limit_seconds": round(nearest_frame_error_limit, 9),
            "frame_mappings": source_mapping_records,
        },
        "local_occlusion_patch_config": {
            "clip_to_caption_region": bool(args.clip_to_caption_region),
            "caption_padding_x_ratio": args.caption_padding_x_ratio,
            "caption_padding_y_ratio": args.caption_padding_y_ratio,
            "policy": "foreground_alpha_intersection_with_expanded_target_caption_bbox",
        },
        "source_video_info": {
            "fps": source_fps,
            "frame_count": source_frame_count,
            "width": source_width,
            "height": source_height,
            "duration_seconds": round(source_frame_count / source_fps, 6) if source_fps > 0 else None,
        },
        "summary": {
            "input_span_count": len(spans),
            "complete_asset_span_count": complete_count,
            "incomplete_asset_span_count": len(spans) - complete_count,
            "requested_contract_frame_count": requested_contract_frame_count,
            "unique_source_video_frame_count": len(requested_source_frames),
            "decoded_requested_frame_writes": decoded_requested,
            "rgba_frames_written": total_rgba_frames,
            "grabcut_fallback_count": total_fallbacks,
            "local_caption_region_span_count": sum(
                1 for span in asset_spans
                if span.get("asset_scope") == "local_foreground_patch_intersecting_caption_region"
            ),
            "ready_for_merge_analysis": success,
            "ready_for_editor_compilers": success,
            "ready_for_v4_import": success,
        },
        "asset_spans": asset_spans,
        "failures": failures,
        "warnings": warnings,
    }
    write_json(output_contract_path, payload, args.encoding)
    print(json.dumps({
        "success": success,
        "output_contract": str(output_contract_path),
        "rgba_root": str(output_root),
        "complete_asset_span_count": complete_count,
        "rgba_frames_written": total_rgba_frames,
        "grabcut_fallback_count": total_fallbacks,
        "failures": failures,
    }, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
