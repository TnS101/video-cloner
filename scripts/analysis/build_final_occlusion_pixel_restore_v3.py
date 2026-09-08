#!/usr/bin/env python3
"""Build a sparse caption-occlusion pixel-restore sequence.

Authority is deliberately split:
- person geometry: the five clean HumanSeg masks, extended only by global affine
  tracking (never GrabCut, dense flow, or local mask growth);
- caption pixels: exact difference between two Resolve renders of one disposable
  timeline, with only the target COME Text+ clip toggled off for the second render;
- RGB: exact pixels from the Resolve render with COME disabled.

The output therefore restores pixels only where the editable COME glyph overlaps
an independently tracked person silhouette. It never copies RGB from the raw
source video and can never learn caption glyphs into the person mask.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

import cv2  # type: ignore
import numpy as np  # type: ignore

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3"
FRAME_IN = 426
FRAME_OUT_EXCLUSIVE = 454
TIMELINE_FPS = 24.0
SOURCE_FPS = 30.0
SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
ANCHOR_FRAMES = (429, 430, 431, 432, 433)
ANCHOR_HASHES = {
    429: "fbea2275e7f1edb16e1e3c2130c587a5948968e1af847d7abb36d41a3cf9a971",
    430: "72f4f8cd0e7ecae13c8d28f3d1e44a77c890a730f591668430e0c613d84287b9",
    431: "b1d5a8e481d2370355d82dc2d8e9ad7bb9bf0b4e5e9e162e97561fafd15f3d03",
    432: "8f07161e5e1d0f597f9268efa851f700452ebd0d89858aa40721f1ef96979883",
    433: "5831a4d86ba3b4bc0fd50908f46a4d8ecadfb9f7d304ecaac2d921ecf53ea74f",
}
SMALL_SIZE = (304, 540)  # width, height
FULL_SIZE = (1080, 1920)
SENTINEL_FRAMES = (429, 431, 434, 438, 443, 448, 452, 453)


def raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def timeline_to_source_frame(frame: int) -> int:
    return int(round(float(frame) * SOURCE_FPS / TIMELINE_FPS))


def parse_render_frame(path: Path) -> int:
    stem = path.stem
    digits = ""
    for char in reversed(stem):
        if char.isdigit():
            digits = char + digits
        elif digits:
            break
    if not digits:
        raise ValueError(f"render_frame_name:{path.name}")
    return int(digits)


def indexed_pngs(directory: Path) -> Dict[int, Path]:
    rows: Dict[int, Path] = {}
    for path in sorted(directory.glob("*.png")):
        frame = parse_render_frame(path)
        if frame in rows:
            raise ValueError(f"render_frame_duplicate:{frame}")
        rows[frame] = path
    expected = set(range(FRAME_IN, FRAME_OUT_EXCLUSIVE))
    if set(rows) != expected:
        raise ValueError(f"render_frames:{sorted(rows)}")
    return rows


def load_gray(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"image_read:{path}")
    return image


def load_bgr(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"image_read:{path}")
    return image


def _matrix_metrics(matrix: np.ndarray) -> Dict[str, float]:
    a, b, tx = [float(value) for value in matrix[0]]
    c, d, ty = [float(value) for value in matrix[1]]
    scale = math.sqrt(max(0.0, a * a + c * c))
    rotation = math.degrees(math.atan2(c, a))
    return {
        "scale": scale,
        "rotation_degrees": rotation,
        "tx": tx,
        "ty": ty,
    }


def validate_affine(matrix: np.ndarray, inliers: int, tracked: int) -> Dict[str, Any]:
    metrics = _matrix_metrics(matrix)
    checks = {
        "tracked_min": tracked >= 12,
        "inliers_min": inliers >= 6,
        "scale": 0.94 <= metrics["scale"] <= 1.06,
        "rotation": abs(metrics["rotation_degrees"]) <= 8.0,
        "tx": abs(metrics["tx"]) <= 40.0,
        "ty": abs(metrics["ty"]) <= 50.0,
    }
    return {"metrics": metrics, "tracked": tracked, "inliers": inliers, "checks": checks, "ok": all(checks.values())}


def estimate_affine(previous_bgr: np.ndarray, current_bgr: np.ndarray, previous_mask: np.ndarray) -> tuple[np.ndarray, Dict[str, Any]]:
    prev_gray = cv2.cvtColor(previous_bgr, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(current_bgr, cv2.COLOR_BGR2GRAY)
    binary = np.where(previous_mask >= 128, 255, 0).astype(np.uint8)
    eroded = cv2.erode(binary, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)), iterations=1)
    points = cv2.goodFeaturesToTrack(
        prev_gray,
        maxCorners=250,
        qualityLevel=0.01,
        minDistance=4,
        mask=eroded,
        blockSize=5,
    )
    if points is None or len(points) < 12:
        raise ValueError(f"affine_features:{0 if points is None else len(points)}")
    next_points, status, _error = cv2.calcOpticalFlowPyrLK(
        prev_gray,
        curr_gray,
        points,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if next_points is None or status is None:
        raise ValueError("affine_lk")
    valid = status.reshape(-1).astype(bool)
    src = points.reshape(-1, 2)[valid]
    dst = next_points.reshape(-1, 2)[valid]
    if len(src) < 12:
        raise ValueError(f"affine_tracks:{len(src)}")
    matrix, inlier_mask = cv2.estimateAffinePartial2D(
        src,
        dst,
        method=cv2.RANSAC,
        ransacReprojThreshold=2.0,
        maxIters=2000,
        confidence=0.99,
        refineIters=10,
    )
    if matrix is None or matrix.shape != (2, 3):
        raise ValueError("affine_matrix")
    inliers = int(np.count_nonzero(inlier_mask)) if inlier_mask is not None else 0
    validation = validate_affine(matrix, inliers, len(src))
    if not validation["ok"]:
        raise ValueError(f"affine_bounds:{json.dumps(validation, sort_keys=True)}")
    return matrix.astype(np.float64), validation


def warp_mask(previous_mask: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    height, width = previous_mask.shape
    return cv2.warpAffine(
        previous_mask,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def caption_glyph_mask(with_bgr: np.ndarray, without_bgr: np.ndarray) -> tuple[np.ndarray, Dict[str, Any]]:
    if with_bgr.shape != without_bgr.shape:
        raise ValueError("glyph_dimensions")
    delta = cv2.absdiff(with_bgr, without_bgr)
    peak = np.max(delta, axis=2)
    strong = peak >= 8
    weak = peak >= 1
    near_strong = cv2.dilate(strong.astype(np.uint8) * 255, np.ones((5, 5), dtype=np.uint8), iterations=1) > 0
    glyph = (weak & near_strong).astype(np.uint8) * 255
    count = int(np.count_nonzero(glyph))
    strong_count = int(np.count_nonzero(strong))
    ys, xs = np.where(glyph > 0)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if count else None
    return glyph, {"glyph_pixels": count, "strong_pixels": strong_count, "bbox": bbox}


def build_restore_bgra(with_bgr: np.ndarray, without_bgr: np.ndarray, person_small: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any]]:
    if with_bgr.shape[:2] != (FULL_SIZE[1], FULL_SIZE[0]) or without_bgr.shape != with_bgr.shape:
        raise ValueError(f"render_dimensions:{with_bgr.shape}:{without_bgr.shape}")
    if person_small.shape != (SMALL_SIZE[1], SMALL_SIZE[0]):
        raise ValueError(f"person_dimensions:{person_small.shape}")
    glyph, glyph_info = caption_glyph_mask(with_bgr, without_bgr)
    person_full = cv2.resize(person_small, FULL_SIZE, interpolation=cv2.INTER_LINEAR)
    alpha = np.where(glyph > 0, person_full, 0).astype(np.uint8)
    bgra = np.zeros((FULL_SIZE[1], FULL_SIZE[0], 4), dtype=np.uint8)
    bgra[:, :, 3] = alpha
    active = alpha > 0
    bgra[:, :, :3][active] = without_bgr[active]
    alpha_pixels = int(np.count_nonzero(active))
    core_pixels = int(np.count_nonzero(alpha >= 250))
    person_pixels = int(np.count_nonzero(person_full >= 128))
    intersection_ratio = float(alpha_pixels / max(1, glyph_info["glyph_pixels"]))
    return bgra, glyph, person_full, {
        **glyph_info,
        "person_pixels_full": person_pixels,
        "alpha_pixels": alpha_pixels,
        "alpha_core_pixels": core_pixels,
        "glyph_person_intersection_ratio": round(intersection_ratio, 9),
    }


def _read_source_small_frames(video_path: Path) -> Dict[int, np.ndarray]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("source_video_open")
    rows: Dict[int, np.ndarray] = {}
    try:
        for timeline_frame in range(FRAME_IN, FRAME_OUT_EXCLUSIVE):
            source_frame = timeline_to_source_frame(timeline_frame)
            cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
            ok, image = cap.read()
            if not ok or image is None:
                raise ValueError(f"source_decode:{source_frame}")
            rows[timeline_frame] = cv2.resize(image, SMALL_SIZE, interpolation=cv2.INTER_AREA)
    finally:
        cap.release()
    return rows


def build_person_masks(video_path: Path, anchor_dir: Path, output_dir: Path) -> tuple[Dict[int, np.ndarray], Dict[int, Dict[str, Any]]]:
    source = _read_source_small_frames(video_path)
    masks: Dict[int, np.ndarray] = {}
    evidence: Dict[int, Dict[str, Any]] = {}
    for frame in ANCHOR_FRAMES:
        path = anchor_dir / f"mask_{frame:06d}.png"
        if not path.is_file() or raw_sha256(path) != ANCHOR_HASHES[frame]:
            raise ValueError(f"anchor_hash:{frame}")
        mask = load_gray(path)
        if mask.shape != (SMALL_SIZE[1], SMALL_SIZE[0]):
            raise ValueError(f"anchor_dimensions:{frame}:{mask.shape}")
        masks[frame] = mask
        evidence[frame] = {"mode": "canonical_humanseg_anchor", "source_video_frame": timeline_to_source_frame(frame), "anchor_sha256": ANCHOR_HASHES[frame], "ok": True}

    for frame in range(428, FRAME_IN - 1, -1):
        previous = frame + 1
        matrix, validation = estimate_affine(source[previous], source[frame], masks[previous])
        masks[frame] = warp_mask(masks[previous], matrix)
        evidence[frame] = {"mode": "global_affine_from_next", "from_timeline_frame": previous, "source_video_frame": timeline_to_source_frame(frame), "matrix": matrix.tolist(), **validation}

    for frame in range(434, FRAME_OUT_EXCLUSIVE):
        previous = frame - 1
        matrix, validation = estimate_affine(source[previous], source[frame], masks[previous])
        masks[frame] = warp_mask(masks[previous], matrix)
        evidence[frame] = {"mode": "global_affine_from_previous", "from_timeline_frame": previous, "source_video_frame": timeline_to_source_frame(frame), "matrix": matrix.tolist(), **validation}

    output_dir.mkdir(parents=True, exist_ok=False)
    for frame in range(FRAME_IN, FRAME_OUT_EXCLUSIVE):
        path = output_dir / f"person_{frame:06d}.png"
        if not cv2.imwrite(str(path), masks[frame]):
            raise ValueError(f"person_write:{frame}")
        evidence[frame]["person_mask_sha256"] = raw_sha256(path)
        evidence[frame]["person_mask_size"] = path.stat().st_size
    return masks, evidence


def build(args: argparse.Namespace) -> Dict[str, Any]:
    source_video = args.source_video.resolve()
    with_dir = args.with_come_dir.resolve()
    without_dir = args.without_come_dir.resolve()
    anchor_dir = args.anchor_mask_dir.resolve()
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise ValueError(f"output_exists:{output_root}")
    if not source_video.is_file() or raw_sha256(source_video) != SOURCE_VIDEO_SHA256:
        raise ValueError("source_video_hash")
    with_rows = indexed_pngs(with_dir)
    without_rows = indexed_pngs(without_dir)
    output_root.mkdir(parents=True)
    person_dir = output_root / "person_masks"
    rgba_dir = output_root / "rgba"
    glyph_dir = output_root / "glyph_masks"
    person_masks, person_evidence = build_person_masks(source_video, anchor_dir, person_dir)
    rgba_dir.mkdir()
    glyph_dir.mkdir()

    frame_rows = []
    sentinel_nonzero = 0
    for frame in range(FRAME_IN, FRAME_OUT_EXCLUSIVE):
        with_bgr = load_bgr(with_rows[frame])
        without_bgr = load_bgr(without_rows[frame])
        bgra, glyph, person_full, stats = build_restore_bgra(with_bgr, without_bgr, person_masks[frame])
        rgba_path = rgba_dir / f"rgba_{frame:06d}.png"
        glyph_path = glyph_dir / f"glyph_{frame:06d}.png"
        if not cv2.imwrite(str(rgba_path), bgra) or not cv2.imwrite(str(glyph_path), glyph):
            raise ValueError(f"output_write:{frame}")
        if frame in SENTINEL_FRAMES and stats["alpha_pixels"] >= 20:
            sentinel_nonzero += 1
        frame_rows.append(
            {
                "timeline_frame": frame,
                "source_video_frame": timeline_to_source_frame(frame),
                "with_come_render": with_rows[frame].name,
                "without_come_render": without_rows[frame].name,
                "with_come_sha256": raw_sha256(with_rows[frame]),
                "without_come_sha256": raw_sha256(without_rows[frame]),
                "person": person_evidence[frame],
                "person_mask": str((person_dir / f"person_{frame:06d}.png").relative_to(output_root)).replace("\\", "/"),
                "glyph_mask": str(glyph_path.relative_to(output_root)).replace("\\", "/"),
                "glyph_mask_sha256": raw_sha256(glyph_path),
                "rgba": str(rgba_path.relative_to(output_root)).replace("\\", "/"),
                "rgba_sha256": raw_sha256(rgba_path),
                "rgba_size": rgba_path.stat().st_size,
                "stats": stats,
            }
        )

    if sentinel_nonzero < 6:
        raise ValueError(f"sentinel_overlap:{sentinel_nonzero}")
    alpha_total = sum(int(row["stats"]["alpha_pixels"]) for row in frame_rows)
    if alpha_total < 500:
        raise ValueError(f"alpha_total:{alpha_total}")

    manifest = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "backend": "resolve_caption_difference_intersect_clean_person_affine",
        "timeline_range_half_open": [FRAME_IN, FRAME_OUT_EXCLUSIVE],
        "duration_frames": FRAME_OUT_EXCLUSIVE - FRAME_IN,
        "source_video_sha256": SOURCE_VIDEO_SHA256,
        "timeline_fps": TIMELINE_FPS,
        "source_fps": SOURCE_FPS,
        "rgb_authority": "resolve_render_with_target_come_disabled",
        "glyph_authority": "exact_resolve_with_come_minus_without_come_render_difference",
        "person_authority": "canonical_humanseg_anchors_plus_global_affine_only",
        "forbidden_mask_growth": ["grabcut", "dense_optical_flow", "local_segmentation_growth"],
        "sentinel_frames": list(SENTINEL_FRAMES),
        "sentinel_nonzero_count": sentinel_nonzero,
        "alpha_pixels_total": alpha_total,
        "frames": frame_rows,
        "ok": True,
    }
    write_json(output_root / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--with-come-dir", type=Path, required=True)
    parser.add_argument("--without-come-dir", type=Path, required=True)
    parser.add_argument("--anchor-mask-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "manifest": str((args.output_root / "manifest.json").resolve()), "alpha_pixels_total": result["alpha_pixels_total"], "sentinel_nonzero_count": result["sentinel_nonzero_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
