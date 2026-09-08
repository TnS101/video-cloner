from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_PRECAPTION_SOURCE_TRANSPORT_V1"
ARCHITECTURE_FAMILY = "pre_caption_clean_donor_source_transport_v1"
ARCHITECTURE_ATTEMPT = 1
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
FRAME_COUNT = 24
FPS = 24
REFERENCE_FRAME = 429
PRECAPTION_CLEAN_FRAME = 533
PRECAPTION_SHARP_FRAME = 534
REFERENCE_SOURCE_FRAME = 536
EXPECTED_SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
EXPECTED_DIFF_HELPER_SHA256 = "ca95ccfa9e9070a8b4f4ade24afd89d441d016eb931476b4e0d30fffd5a7817d"
EXPECTED_FOREGROUND_MANIFEST_SHA256 = "7b2cd599494c06f12cc22af5f7cb4fd8226f8a8e8a15ffdaac498cf0576e00c6"
EXPECTED_SOURCE_MAPPING = {
    429: 536, 430: 538, 431: 539, 432: 540, 433: 541, 434: 542,
    435: 544, 436: 545, 437: 546, 438: 548, 439: 549, 440: 550,
    441: 551, 442: 552, 443: 554, 444: 555, 445: 556, 446: 558,
    447: 559, 448: 560, 449: 561, 450: 562, 451: 564, 452: 565,
}
CLOSED_ARCHITECTURE_FAMILIES = (
    "propainter_semantic_split_person_repair_v1",
    "stabilized_source_backed_person_then_background_v1",
    "propainter_v4_foreground_veto_background_only_v1",
    "diffueraser_roi_source_authority_semantic_composite_v1",
    "lama_highres_roi_source_authority_semantic_composite_v1",
    "masked_generative_inpainting_without_reliable_source_correspondence",
)

PAIRWISE_SCALE = 0.5
PAIRWISE_MIN_INLIERS = 40
PAIRWISE_MAX_MEDIAN_ERROR = 1.25
PAIRWISE_MIN_SCALE = 0.97
PAIRWISE_MAX_SCALE = 1.03
PAIRWISE_MAX_ROTATION_DEGREES = 2.0
DENSE_BRIDGE_SCALE = 0.5
DENSE_BRIDGE_FB_MAX_PROCESS_PIXELS = 3.0
DENSE_BRIDGE_MIN_SUPPORT_PIXELS = 15000
DENSE_BRIDGE_MIN_FB_VALID_FRACTION = 0.95
DENSE_BRIDGE_MAX_MEDIAN_FB_ERROR = 0.50
DENSE_BRIDGE_MAX_PHOTOMETRIC_MAE = 25.0
DENSE_BRIDGE_GRID_STEP = 2
DENSE_BRIDGE_MIN_SAMPLED_CORRESPONDENCES = 4000
DENSE_BRIDGE_MIN_RANSAC_INLIERS = 2500
DENSE_BRIDGE_MAX_MEDIAN_RANSAC_ERROR = 1.10
DENSE_BRIDGE_MAX_P95_RANSAC_ERROR = 1.70
PRECAPTION_BRIDGE_METHOD = "farneback_dense_to_similarity"
MIN_COMBINED_SOURCE_BACKED_COVERAGE = 0.83
MIN_PRECAPTION_VALID_COVERAGE = 0.98
MIN_SOURCE_GLYPH_REDUCTION = 0.70
MIN_RIGHT_GLYPH_REMOVAL = 0.75
MAX_NEW_DARK_ARTIFACT_RATIO = 0.03
MAX_NEW_BRIGHT_ARTIFACT_RATIO = 0.03
MAX_BOUNDARY_RING_MAE = 30.0
MIN_SAFE_GLYPH_PIXELS = 4000
SENTINELS = (429, 431, 434, 438, 443, 448, 452)
HOLD_SENTINELS = (434, 438, 443, 448)


class ProofError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_safe(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def resolve_repo_root(value: str | None) -> Path:
    root = Path(value).resolve() if value else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        raise ProofError(f"repository root not found: {root}")
    return root


def load_diff_helper(repo_root: Path):
    path = repo_root / "scripts" / "analysis" / "run_baked_caption_diffueraser_roi_proof_v1.py"
    if not path.is_file():
        raise ProofError(f"authority helper missing: {path}")
    actual = sha256_file(path)
    if actual != EXPECTED_DIFF_HELPER_SHA256:
        raise ProofError(
            f"authority helper hash mismatch: expected {EXPECTED_DIFF_HELPER_SHA256}, got {actual}"
        )
    spec = importlib.util.spec_from_file_location("video_cloner_diff_authority", path)
    if spec is None or spec.loader is None:
        raise ProofError("could not load authority helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = (
        "load_v9_authority_module", "build_final_alpha", "visual_artifact_metrics",
        "relative_reduction", "create_contact_sheet",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise ProofError(f"authority helper contract missing: {missing}")
    return module


def _to_homogeneous(matrix):
    import numpy as np
    out = np.eye(3, dtype=np.float64)
    out[:2, :] = matrix
    return out


def _matrix_scale_rotation(matrix) -> tuple[float, float]:
    a = float(matrix[0, 0])
    b = float(matrix[0, 1])
    scale = math.sqrt(a * a + b * b)
    rotation = math.degrees(math.atan2(-b, a))
    return scale, rotation


def estimate_pairwise_person_affine(
    donor_image,
    target_image,
    donor_person_mask,
    target_person_mask,
    donor_score_mask,
    target_score_mask,
):
    """Estimate donor->target person similarity from caption-safe visible context."""
    import cv2
    import numpy as np

    height, width = donor_image.shape[:2]
    if target_image.shape[:2] != (height, width):
        raise ProofError("pairwise frame shape mismatch")
    process_width = int(round(width * PAIRWISE_SCALE))
    process_height = int(round(height * PAIRWISE_SCALE))
    donor_gray = cv2.resize(
        cv2.cvtColor(donor_image, cv2.COLOR_BGR2GRAY),
        (process_width, process_height), interpolation=cv2.INTER_AREA,
    )
    target_gray = cv2.resize(
        cv2.cvtColor(target_image, cv2.COLOR_BGR2GRAY),
        (process_width, process_height), interpolation=cv2.INTER_AREA,
    )
    donor_person = cv2.resize(
        (donor_person_mask > 0).astype(np.uint8),
        (process_width, process_height), interpolation=cv2.INTER_NEAREST,
    ) > 0
    target_person = cv2.resize(
        (target_person_mask > 0).astype(np.uint8),
        (process_width, process_height), interpolation=cv2.INTER_NEAREST,
    ) > 0
    donor_score = cv2.resize(
        (donor_score_mask > 0).astype(np.uint8),
        (process_width, process_height), interpolation=cv2.INTER_NEAREST,
    ) > 0
    target_score = cv2.resize(
        (target_score_mask > 0).astype(np.uint8),
        (process_width, process_height), interpolation=cv2.INTER_NEAREST,
    ) > 0

    y_grid = np.arange(process_height)[:, None]
    caption_buffer = cv2.dilate(
        donor_score.astype(np.uint8), np.ones((11, 11), dtype=np.uint8), iterations=1
    ) > 0
    support = donor_person & ~caption_buffer
    support &= y_grid >= int(round(640 * PAIRWISE_SCALE))
    support &= y_grid <= int(round(1150 * PAIRWISE_SCALE))
    points = cv2.goodFeaturesToTrack(
        donor_gray, maxCorners=600, qualityLevel=0.005, minDistance=4,
        blockSize=7, mask=support.astype(np.uint8) * 255,
    )
    if points is None or len(points) < 20:
        raise ProofError(f"pairwise alignment has too few donor features: {0 if points is None else len(points)}")

    tracked, status, _ = cv2.calcOpticalFlowPyrLK(
        donor_gray, target_gray, points, None, winSize=(41, 41), maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 0.005),
    )
    backward, backward_status, _ = cv2.calcOpticalFlowPyrLK(
        target_gray, donor_gray, tracked, None, winSize=(41, 41), maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 0.005),
    )
    good = (status[:, 0] > 0) & (backward_status[:, 0] > 0)
    fb_error = np.linalg.norm(backward[:, 0] - points[:, 0], axis=1)
    good &= fb_error < 1.2
    donor_points = points[:, 0][good]
    target_points = tracked[:, 0][good]
    if len(donor_points) < PAIRWISE_MIN_INLIERS:
        raise ProofError(f"pairwise alignment has too few forward/backward points: {len(donor_points)}")

    xy = np.rint(target_points).astype(np.int32)
    valid = (
        (xy[:, 0] >= 0) & (xy[:, 0] < process_width)
        & (xy[:, 1] >= 0) & (xy[:, 1] < process_height)
    )
    target_caption_buffer = cv2.dilate(
        target_score.astype(np.uint8), np.ones((11, 11), dtype=np.uint8), iterations=1
    ) > 0
    endpoint_ok = np.zeros(len(valid), dtype=bool)
    vi = np.where(valid)[0]
    endpoint_ok[vi] = (
        target_person[xy[vi, 1], xy[vi, 0]]
        & ~target_caption_buffer[xy[vi, 1], xy[vi, 0]]
    )
    donor_points = donor_points[endpoint_ok]
    target_points = target_points[endpoint_ok]
    if len(donor_points) < PAIRWISE_MIN_INLIERS:
        raise ProofError(f"pairwise alignment has too few caption-safe points: {len(donor_points)}")

    matrix, inliers = cv2.estimateAffinePartial2D(
        donor_points, target_points, method=cv2.RANSAC, ransacReprojThreshold=1.5,
        maxIters=3000, confidence=0.995, refineIters=20,
    )
    if matrix is None or inliers is None:
        raise ProofError("pairwise alignment RANSAC failed")
    inlier_mask = inliers[:, 0] > 0
    count = int(np.count_nonzero(inlier_mask))
    if count < PAIRWISE_MIN_INLIERS:
        raise ProofError(f"pairwise alignment RANSAC inliers too small: {count}")
    predicted = donor_points @ matrix[:, :2].T + matrix[:, 2]
    errors = np.linalg.norm(predicted - target_points, axis=1)
    median_error = float(np.median(errors[inlier_mask]))
    full = matrix.astype(np.float64).copy()
    full[:, 2] /= PAIRWISE_SCALE
    scale, rotation = _matrix_scale_rotation(full)
    if median_error > PAIRWISE_MAX_MEDIAN_ERROR:
        raise ProofError(f"pairwise alignment median error too high: {median_error:.6f}")
    if not (PAIRWISE_MIN_SCALE <= scale <= PAIRWISE_MAX_SCALE):
        raise ProofError(f"pairwise alignment scale escaped bound: {scale:.6f}")
    if abs(rotation) > PAIRWISE_MAX_ROTATION_DEGREES:
        raise ProofError(f"pairwise alignment rotation escaped bound: {rotation:.6f}")
    return full, {
        "inliers": count,
        "median_reprojection_error_process_pixels": median_error,
        "scale": scale,
        "rotation_degrees": rotation,
    }


def _authority_child(root: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ProofError(f"{label} path is missing from foreground manifest")
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ProofError(f"{label} escaped foreground authority root: {relative}") from exc
    if not candidate.is_file():
        raise ProofError(f"{label} authority file missing: {candidate}")
    return candidate


def resolve_manifest_frame_authority(
    foreground_dir: Path,
    foreground_manifest: dict,
    timeline_frame: int,
    expected_source_frame: int,
    frame_shape: tuple[int, int],
    v9,
):
    """Resolve one V4 authority frame directly from its verified manifest.

    This intentionally does not depend on the target-only mapping returned by
    ``load_v4_foreground_authority``.  Bridge frame 427 is valid V4 authority
    even though it lies outside the 429-452 proof target interval.
    """
    import cv2
    import numpy as np

    rows = [
        row for row in foreground_manifest.get("frames", [])
        if isinstance(row, dict) and row.get("timeline_frame") == timeline_frame
    ]
    if len(rows) != 1:
        raise ProofError(
            f"foreground manifest expected exactly one row for frame {timeline_frame}, got {len(rows)}"
        )
    row = rows[0]
    actual_source = row.get("source_video_frame")
    if not isinstance(actual_source, int) or actual_source != expected_source_frame:
        raise ProofError(
            f"foreground bridge source mapping mismatch at frame {timeline_frame}: {actual_source}"
        )
    person_info = row.get("person")
    if not isinstance(person_info, dict) or person_info.get("ok") is not True:
        raise ProofError(f"foreground bridge person authority is not PASS at frame {timeline_frame}")

    person_path = _authority_child(foreground_dir, row.get("person_mask"), "person mask")
    expected_person_sha = person_info.get("person_mask_sha256")
    if not isinstance(expected_person_sha, str) or sha256_file(person_path) != expected_person_sha:
        raise ProofError(f"foreground bridge person-mask hash mismatch at frame {timeline_frame}")
    expected_person_size = person_info.get("person_mask_size")
    if isinstance(expected_person_size, int) and person_path.stat().st_size != expected_person_size:
        raise ProofError(f"foreground bridge person-mask size mismatch at frame {timeline_frame}")
    person_mask = v9.load_full_resolution_person_mask(person_path, frame_shape)
    if getattr(person_mask, "shape", None) != frame_shape or not np.any(person_mask > 0):
        raise ProofError(f"foreground bridge person mask is invalid at frame {timeline_frame}")

    glyph_path = _authority_child(foreground_dir, row.get("glyph_mask"), "glyph mask")
    expected_glyph_sha = row.get("glyph_mask_sha256")
    if not isinstance(expected_glyph_sha, str) or sha256_file(glyph_path) != expected_glyph_sha:
        raise ProofError(f"foreground bridge glyph-mask hash mismatch at frame {timeline_frame}")
    glyph_mask = cv2.imread(str(glyph_path), cv2.IMREAD_GRAYSCALE)
    if glyph_mask is None or glyph_mask.shape != frame_shape:
        raise ProofError(f"foreground bridge glyph mask is invalid at frame {timeline_frame}")

    return {
        "timeline_frame": timeline_frame,
        "source_video_frame": actual_source,
        "person_mask": person_mask,
        "glyph_mask": glyph_mask,
        "person_mask_path": person_path,
        "glyph_mask_path": glyph_path,
        "person_mask_sha256": expected_person_sha,
        "glyph_mask_sha256": expected_glyph_sha,
    }


def estimate_precaption_dense_bridge_affine(
    sharp_image,
    clean_image,
    sharp_person_mask,
    sharp_score_mask,
):
    """Estimate 534->533 geometry from dense, caption-safe real-source flow.

    The previous sparse LK bridge found only 33 RANSAC inliers on the supplied
    534->533 blur transition.  This bridge adds genuinely new correspondence
    information: dense Farneback flow over the accepted frame-534 person matte,
    forward/backward consistency, then a RANSAC similarity fit from thousands
    of real source correspondences.  No generated pixels enter authority.
    """
    import cv2
    import numpy as np

    height, width = sharp_image.shape[:2]
    if clean_image.shape[:2] != (height, width):
        raise ProofError("pre-caption dense bridge frame shape mismatch")
    process_width = int(round(width * DENSE_BRIDGE_SCALE))
    process_height = int(round(height * DENSE_BRIDGE_SCALE))
    sharp_gray = cv2.resize(
        cv2.cvtColor(sharp_image, cv2.COLOR_BGR2GRAY),
        (process_width, process_height), interpolation=cv2.INTER_AREA,
    )
    clean_gray = cv2.resize(
        cv2.cvtColor(clean_image, cv2.COLOR_BGR2GRAY),
        (process_width, process_height), interpolation=cv2.INTER_AREA,
    )
    person = cv2.resize(
        (sharp_person_mask > 0).astype(np.uint8),
        (process_width, process_height), interpolation=cv2.INTER_NEAREST,
    ) > 0
    score = cv2.resize(
        (sharp_score_mask > 0).astype(np.uint8),
        (process_width, process_height), interpolation=cv2.INTER_NEAREST,
    ) > 0
    score_buffer = cv2.dilate(
        score.astype(np.uint8), np.ones((11, 11), dtype=np.uint8), iterations=1
    ) > 0
    y_grid = np.arange(process_height)[:, None]
    support = person & ~score_buffer
    support &= y_grid >= int(round(640 * DENSE_BRIDGE_SCALE))
    support &= y_grid <= int(round(1150 * DENSE_BRIDGE_SCALE))
    support_pixels = int(np.count_nonzero(support))
    if support_pixels < DENSE_BRIDGE_MIN_SUPPORT_PIXELS:
        raise ProofError(f"pre-caption dense bridge support too small: {support_pixels}")

    # OpenCV Farneback is part of the already-required cv2 runtime and avoids a
    # new optional dependency.  Direction is sharp(534) -> clean(533).
    backward = cv2.calcOpticalFlowFarneback(
        sharp_gray, clean_gray, None,
        0.5, 5, 31, 5, 7, 1.5, 0,
    )
    forward = cv2.calcOpticalFlowFarneback(
        clean_gray, sharp_gray, None,
        0.5, 5, 31, 5, 7, 1.5, 0,
    )
    yy, xx = np.mgrid[0:process_height, 0:process_width].astype(np.float32)
    source_x = xx + backward[..., 0]
    source_y = yy + backward[..., 1]
    forward_x = cv2.remap(
        forward[..., 0], source_x, source_y, cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan,
    )
    forward_y = cv2.remap(
        forward[..., 1], source_x, source_y, cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan,
    )
    fb_error = np.sqrt(
        (backward[..., 0] + forward_x) ** 2
        + (backward[..., 1] + forward_y) ** 2
    )
    inside = (
        (source_x >= 0.0) & (source_x < process_width)
        & (source_y >= 0.0) & (source_y < process_height)
        & np.isfinite(fb_error)
    )
    valid = support & inside & (fb_error <= DENSE_BRIDGE_FB_MAX_PROCESS_PIXELS)
    valid_pixels = int(np.count_nonzero(valid))
    valid_fraction = valid_pixels / float(support_pixels)
    if valid_fraction < DENSE_BRIDGE_MIN_FB_VALID_FRACTION:
        raise ProofError(
            f"pre-caption dense bridge FB-valid fraction too small: {valid_fraction:.6f}"
        )
    median_fb = float(np.median(fb_error[support & inside]))
    if median_fb > DENSE_BRIDGE_MAX_MEDIAN_FB_ERROR:
        raise ProofError(f"pre-caption dense bridge median FB error too high: {median_fb:.6f}")

    clean_small = cv2.resize(clean_image, (process_width, process_height), interpolation=cv2.INTER_AREA)
    sharp_small = cv2.resize(sharp_image, (process_width, process_height), interpolation=cv2.INTER_AREA)
    dense_warp = cv2.remap(
        clean_small, source_x, source_y, cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    dense_photo = fit_channel_affine(
        dense_warp, sharp_small, valid.astype(np.uint8) * 255
    )
    dense_matched = apply_channel_affine(dense_warp, dense_photo)
    photometric_mae = float(np.mean(
        np.abs(dense_matched.astype(np.float32) - sharp_small.astype(np.float32))[valid]
    ))
    if photometric_mae > DENSE_BRIDGE_MAX_PHOTOMETRIC_MAE:
        raise ProofError(
            f"pre-caption dense bridge photometric MAE too high: {photometric_mae:.6f}"
        )

    grid_y, grid_x = np.indices((process_height, process_width))
    sampled = valid & ((grid_y % DENSE_BRIDGE_GRID_STEP) == 0) & ((grid_x % DENSE_BRIDGE_GRID_STEP) == 0)
    donor_points = np.stack([xx[sampled], yy[sampled]], axis=1)
    clean_points = np.stack([source_x[sampled], source_y[sampled]], axis=1)
    sampled_count = int(len(donor_points))
    if sampled_count < DENSE_BRIDGE_MIN_SAMPLED_CORRESPONDENCES:
        raise ProofError(
            f"pre-caption dense bridge sampled correspondences too small: {sampled_count}"
        )
    matrix, inliers = cv2.estimateAffinePartial2D(
        donor_points, clean_points, method=cv2.RANSAC, ransacReprojThreshold=1.5,
        maxIters=3000, confidence=0.995, refineIters=20,
    )
    if matrix is None or inliers is None:
        raise ProofError("pre-caption dense bridge RANSAC failed")
    inlier_mask = inliers[:, 0] > 0
    inlier_count = int(np.count_nonzero(inlier_mask))
    if inlier_count < DENSE_BRIDGE_MIN_RANSAC_INLIERS:
        raise ProofError(f"pre-caption dense bridge RANSAC inliers too small: {inlier_count}")
    predicted = donor_points @ matrix[:, :2].T + matrix[:, 2]
    errors = np.linalg.norm(predicted - clean_points, axis=1)
    median_ransac = float(np.median(errors[inlier_mask]))
    p95_ransac = float(np.percentile(errors[inlier_mask], 95))
    if median_ransac > DENSE_BRIDGE_MAX_MEDIAN_RANSAC_ERROR:
        raise ProofError(
            f"pre-caption dense bridge median RANSAC error too high: {median_ransac:.6f}"
        )
    if p95_ransac > DENSE_BRIDGE_MAX_P95_RANSAC_ERROR:
        raise ProofError(
            f"pre-caption dense bridge p95 RANSAC error too high: {p95_ransac:.6f}"
        )

    full = matrix.astype(np.float64).copy()
    full[:, 2] /= DENSE_BRIDGE_SCALE
    scale, rotation = _matrix_scale_rotation(full)
    if not (PAIRWISE_MIN_SCALE <= scale <= PAIRWISE_MAX_SCALE):
        raise ProofError(f"pre-caption dense bridge scale escaped bound: {scale:.6f}")
    if abs(rotation) > PAIRWISE_MAX_ROTATION_DEGREES:
        raise ProofError(f"pre-caption dense bridge rotation escaped bound: {rotation:.6f}")
    return full, {
        "method": PRECAPTION_BRIDGE_METHOD,
        "support_pixels": support_pixels,
        "fb_valid_pixels": valid_pixels,
        "fb_valid_fraction": valid_fraction,
        "median_fb_error_process_pixels": median_fb,
        "photometric_mae_process_pixels": photometric_mae,
        "photometric_channel_affine": dense_photo,
        "sampled_correspondences": sampled_count,
        "ransac_inliers": inlier_count,
        "median_ransac_error_process_pixels": median_ransac,
        "p95_ransac_error_process_pixels": p95_ransac,
        "scale": scale,
        "rotation_degrees": rotation,
    }

def compose_to_reference(pairwise: dict[tuple[int, int], object], reference_frame: int = REFERENCE_FRAME):
    import numpy as np
    out = {}
    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1):
        transform = np.eye(3, dtype=np.float64)
        if frame < reference_frame:
            for cursor in range(frame, reference_frame):
                transform = _to_homogeneous(pairwise[(cursor, cursor + 1)]) @ transform
        elif frame > reference_frame:
            for cursor in range(frame - 1, reference_frame - 1, -1):
                transform = np.linalg.inv(_to_homogeneous(pairwise[(cursor, cursor + 1)])) @ transform
        out[frame] = transform
    return out


def warp_binary(mask, transform, width: int, height: int):
    import cv2
    import numpy as np
    return cv2.warpPerspective(
        (mask > 0).astype(np.uint8) * 255, transform, (width, height),
        flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    )


def build_temporal_person_plate(stabilized_images, stabilized_person_masks, stabilized_score_masks):
    import warnings
    import numpy as np
    image_stack = np.stack(stabilized_images, axis=0)
    person_stack = np.stack([m > 0 for m in stabilized_person_masks], axis=0)
    score_stack = np.stack([m > 0 for m in stabilized_score_masks], axis=0)
    clean = person_stack & ~score_stack
    count = np.sum(clean, axis=0).astype(np.uint8)
    plate = np.zeros(image_stack.shape[1:], dtype=np.uint8)
    for channel in range(3):
        values = image_stack[..., channel].astype(np.float32)
        values[~clean] = np.nan
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice encountered", category=RuntimeWarning)
            median = np.nanmedian(values, axis=0)
        plate[..., channel] = np.rint(np.nan_to_num(median, nan=0.0)).clip(0, 255).astype(np.uint8)
    return plate, count


def fit_channel_affine(source, target, support):
    """Robust source->target per-channel gain/bias; geometry remains source-backed."""
    import numpy as np
    support = support > 0
    if int(np.count_nonzero(support)) < 500:
        raise ProofError("photometric support unexpectedly small")
    out = []
    for channel in range(3):
        x = source[..., channel][support].astype(np.float64)
        y = target[..., channel][support].astype(np.float64)
        keep = (
            (x >= np.percentile(x, 5)) & (x <= np.percentile(x, 95))
            & (y >= np.percentile(y, 5)) & (y <= np.percentile(y, 95))
        )
        x, y = x[keep], y[keep]
        if len(x) < 250:
            raise ProofError("photometric fit has too few robust samples")
        A = np.stack([x, np.ones_like(x)], axis=1)
        gain, bias = np.linalg.lstsq(A, y, rcond=None)[0]
        gain = float(np.clip(gain, 0.65, 1.35))
        bias = float(np.clip(bias, -55.0, 55.0))
        out.append((gain, bias))
    return out


def apply_channel_affine(image, params):
    import numpy as np
    result = image.astype(np.float32).copy()
    for channel, (gain, bias) in enumerate(params):
        result[..., channel] = result[..., channel] * float(gain) + float(bias)
    return np.rint(result).clip(0, 255).astype(np.uint8)


def decode_source_frames(video_path: Path, indices: set[int]):
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ProofError(f"could not open source video: {video_path}")
    frames = {}
    cursor = 0
    wanted = sorted(indices)
    want_set = set(wanted)
    max_index = wanted[-1]
    while cursor <= max_index:
        ok, frame = cap.read()
        if not ok:
            break
        if cursor in want_set:
            frames[cursor] = frame
        cursor += 1
    cap.release()
    missing = sorted(want_set - set(frames))
    if missing:
        raise ProofError(f"source video missing required frames: {missing}")
    return frames


def build_precaption_reference_plate(
    frame533, frame534, transform_533_to_ref, transform_534_to_ref,
    contamination_mask_ref, person_mask_ref,
):
    """Fuse sharp 534 with clean 533 only where 534 carries the nascent COME overlay."""
    import cv2
    import numpy as np
    h, w = frame534.shape[:2]
    donor534 = cv2.warpPerspective(
        frame534, transform_534_to_ref, (w, h), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    donor533 = cv2.warpPerspective(
        frame533, transform_533_to_ref, (w, h), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    valid533 = cv2.warpPerspective(
        np.full((h, w), 255, dtype=np.uint8), transform_533_to_ref, (w, h),
        flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    ) > 0
    contamination = contamination_mask_ref > 0
    # Fit exposure/transition correction on nearby clean person+background context,
    # excluding the known COME authority itself.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (81, 81))
    near = cv2.dilate(contamination.astype(np.uint8), kernel) > 0
    support = near & ~contamination & valid533
    params = fit_channel_affine(donor533, donor534, support)
    matched533 = apply_channel_affine(donor533, params)
    plate = donor534.copy()
    plate[contamination] = matched533[contamination]
    provenance = np.full((h, w), PRECAPTION_SHARP_FRAME, dtype=np.uint16)
    provenance[contamination] = PRECAPTION_CLEAN_FRAME
    valid = np.ones((h, w), dtype=np.uint8) * 255
    valid[contamination & ~valid533] = 0
    return plate, provenance, valid, params


def write_png(path: Path, image):
    import cv2
    if not cv2.imwrite(str(path), image):
        raise ProofError(f"could not write image: {path}")


def write_rgb_mp4(path: Path, frames, fps: float) -> dict[str, object]:
    """Write RGB uint8 frames to MP4 using already-required OpenCV only.

    Try common MP4 codecs, then reopen and count decoded frames so a missing
    encoder cannot masquerade as a successful visual artifact.
    """
    import cv2
    import numpy as np

    if not frames:
        raise ProofError("comparison video has no frames")
    first = np.asarray(frames[0])
    if first.ndim != 3 or first.shape[2] != 3 or first.dtype != np.uint8:
        raise ProofError(f"invalid comparison frame shape/dtype: {first.shape}/{first.dtype}")
    height, width = first.shape[:2]
    codecs = ("mp4v", "avc1", "H264")
    errors = []
    path.parent.mkdir(parents=True, exist_ok=True)

    for codec in codecs:
        path.unlink(missing_ok=True)
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*codec), float(fps), (width, height)
        )
        if not writer.isOpened():
            writer.release()
            errors.append(f"{codec}:open_failed")
            continue
        try:
            for index, frame in enumerate(frames):
                arr = np.asarray(frame)
                if arr.shape != first.shape or arr.dtype != np.uint8:
                    raise ProofError(
                        f"comparison frame {index} shape/dtype mismatch: {arr.shape}/{arr.dtype}"
                    )
                writer.write(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
        finally:
            writer.release()

        if not path.is_file() or path.stat().st_size <= 0:
            errors.append(f"{codec}:empty_output")
            continue
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            errors.append(f"{codec}:readback_open_failed")
            continue
        decoded = 0
        try:
            while True:
                ok, decoded_frame = capture.read()
                if not ok:
                    break
                if decoded_frame is None or decoded_frame.shape[:2] != (height, width):
                    raise ProofError(f"comparison video readback frame {decoded} is invalid")
                decoded += 1
        finally:
            capture.release()
        if decoded != len(frames):
            errors.append(f"{codec}:decoded_{decoded}_expected_{len(frames)}")
            continue
        return {
            "backend": "opencv",
            "codec": codec,
            "frame_count": decoded,
            "width": width,
            "height": height,
            "fps": float(fps),
            "bytes": path.stat().st_size,
        }

    path.unlink(missing_ok=True)
    raise ProofError("OpenCV MP4 encoder unavailable or invalid: " + "; ".join(errors))


def main() -> int:
    import cv2
    import numpy as np

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--foreground-authority-dir", required=True)
    parser.add_argument("--geometry-preflight-only", action="store_true")
    args = parser.parse_args()

    repo_root = resolve_repo_root(args.repo_root)
    artifact_dir = Path(args.artifact_dir).resolve()
    foreground_dir = Path(args.foreground_authority_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    diff = load_diff_helper(repo_root)
    v9 = diff.load_v9_authority_module(repo_root)
    failed_run = repo_root / v9.V2_FAILED_RUN_REL
    geometry_run = repo_root / v9.V3_GEOMETRY_RUN_REL
    base_dir = failed_run / "render_base_baked"
    glyph_dir = geometry_run / "generated_pixel_restore_v3" / "glyph_masks"
    source_video = repo_root / "input" / "DZsqH7auhjt.mp4"
    required = (
        failed_run / "base_render_authority.json",
        geometry_run / "generated_pixel_restore_v3" / "manifest.json",
        repo_root / v9.STYLE_REL,
        repo_root / v9.SOURCE_TRACK_REL,
        repo_root / v9.LIFECYCLE_REL,
        foreground_dir / "manifest.json",
        source_video,
    )
    for path in required:
        if not path.is_file():
            raise ProofError(f"missing authority file: {path}")
    if sha256_file(source_video) != EXPECTED_SOURCE_VIDEO_SHA256:
        raise ProofError("source video hash mismatch")
    fg_hash = sha256_file(foreground_dir / "manifest.json")
    if fg_hash != EXPECTED_FOREGROUND_MANIFEST_SHA256:
        raise ProofError(f"foreground manifest hash mismatch: {fg_hash}")

    base_authority = v9.load_json(failed_run / "base_render_authority.json")
    if not isinstance(base_authority, dict) or base_authority.get("ok") is not True:
        raise ProofError("base render authority is not PASS")
    if base_authority.get("dimensions") != {"frame_rate": 24.0, "height": 1920, "width": 1080}:
        raise ProofError(f"unexpected base dimensions: {base_authority.get('dimensions')}")
    anchors = v9.verify_style_anchors(v9.load_json(repo_root / v9.STYLE_REL))
    source_context = v9.verify_source_context_authority(
        v9.load_json(repo_root / v9.SOURCE_TRACK_REL),
        v9.load_json(repo_root / v9.LIFECYCLE_REL),
        repo_root,
    )
    foreground_paths = v9.load_v4_foreground_authority(foreground_dir)
    fg_manifest = v9.load_json(foreground_dir / "manifest.json")
    fg_rows = {
        int(row["timeline_frame"]): row
        for row in fg_manifest.get("frames", [])
        if isinstance(row, dict) and isinstance(row.get("timeline_frame"), int)
    }
    actual_mapping = {
        frame: int(fg_rows[frame]["source_video_frame"])
        for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)
    }
    if actual_mapping != EXPECTED_SOURCE_MAPPING:
        raise ProofError(f"timeline/source mapping mismatch: {actual_mapping}")

    frames, row_masks, compact_masks, score_masks, person_masks, bboxes = {}, {}, {}, {}, {}, {}
    input_rows = []
    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1):
        base_path = base_dir / f"base_baked_{frame:08d}.png"
        glyph_path = glyph_dir / f"glyph_{frame:06d}.png"
        before = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
        glyph = cv2.imread(str(glyph_path), cv2.IMREAD_GRAYSCALE)
        if before is None or glyph is None or before.shape[:2] != (1920, 1080):
            raise ProofError(f"invalid source authority frame {frame}")
        bbox = v9.interpolate_bbox(frame, anchors)
        score = v9.clip_mask_to_bbox(v9.transform_glyph_mask(glyph, bbox), bbox)
        compact = v9.build_compact_caption_masks(before, glyph, bbox)
        person = v9.load_full_resolution_person_mask(foreground_paths[frame], before.shape[:2])
        frames[frame] = before
        row_masks[frame] = compact["inpaint_mask"]
        compact_masks[frame] = compact["composite_mask"]
        score_masks[frame] = score
        person_masks[frame] = person
        bboxes[frame] = bbox
        input_rows.append({
            "timeline_frame": frame,
            "source_video_frame": actual_mapping[frame],
            "base_sha256": sha256_file(base_path),
            "glyph_sha256": sha256_file(glyph_path),
        })

    # Reuse the proven caption-safe target-person stabilization geometry, but not
    # the closed ProPainter residual. The reference is frame 429 so the clean
    # pre-caption donor can bridge directly into this geometry.
    pairwise = {}
    alignment_rows = []
    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END):
        matrix, metrics = estimate_pairwise_person_affine(
            frames[frame], frames[frame + 1],
            person_masks[frame], person_masks[frame + 1],
            score_masks[frame], score_masks[frame + 1],
        )
        pairwise[(frame, frame + 1)] = matrix
        alignment_rows.append({
            "kind": "target_pairwise",
            "from_timeline_frame": frame,
            "to_timeline_frame": frame + 1,
            "matrix": matrix.tolist(),
            **metrics,
        })
    transforms_to_ref = compose_to_reference(pairwise, REFERENCE_FRAME)

    stabilized_images, stabilized_person, stabilized_score = [], [], []
    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1):
        t = transforms_to_ref[frame]
        stabilized_images.append(cv2.warpPerspective(
            frames[frame], t, (1080, 1920), flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        ))
        stabilized_person.append(warp_binary(person_masks[frame], t, 1080, 1920))
        stabilized_score.append(warp_binary(score_masks[frame], t, 1080, 1920))
    temporal_plate, temporal_count = build_temporal_person_plate(
        stabilized_images, stabilized_person, stabilized_score
    )

    source_frames = decode_source_frames(
        source_video, {PRECAPTION_CLEAN_FRAME, PRECAPTION_SHARP_FRAME, REFERENCE_SOURCE_FRAME}
    )
    raw536 = source_frames[REFERENCE_SOURCE_FRAME]
    # Frame 427 is valid accepted V4 authority but lies outside the target-only
    # 429-452 mapping returned by load_v4_foreground_authority. Resolve it
    # directly from the already-hashed foreground manifest instead.
    bridge_timeline_frame = 427
    bridge_authority = resolve_manifest_frame_authority(
        foreground_dir, fg_manifest, bridge_timeline_frame, PRECAPTION_SHARP_FRAME,
        raw536.shape[:2], v9,
    )
    bridge_person_534 = bridge_authority["person_mask"]
    bridge_glyph = bridge_authority["glyph_mask"]
    bridge_bbox = v9.interpolate_bbox(bridge_timeline_frame, anchors)
    bridge_score_534 = v9.clip_mask_to_bbox(
        v9.transform_glyph_mask(bridge_glyph, bridge_bbox), bridge_bbox
    )

    # Bridge source 536 -> 534 with the accepted V4 mattes at both instants.
    matrix_536_to_534, bridge_metrics = estimate_pairwise_person_affine(
        raw536, source_frames[PRECAPTION_SHARP_FRAME],
        person_masks[REFERENCE_FRAME], bridge_person_534,
        score_masks[REFERENCE_FRAME], bridge_score_534,
    )
    transform_534_to_ref = np.linalg.inv(_to_homogeneous(matrix_536_to_534))
    alignment_rows.append({
        "kind": "precaption_sharp_bridge",
        "from_source_frame": PRECAPTION_SHARP_FRAME,
        "to_source_frame": REFERENCE_SOURCE_FRAME,
        "matrix": transform_534_to_ref.tolist(),
        **bridge_metrics,
    })

    # The old sparse 534->533 bridge failed on the real blur transition with 33
    # RANSAC inliers.  Use dense caption-safe real-source correspondences instead
    # of lowering that sparse threshold.
    person534 = bridge_person_534
    score534 = bridge_score_534
    matrix_534_to_533, bridge533_metrics = estimate_precaption_dense_bridge_affine(
        source_frames[PRECAPTION_SHARP_FRAME], source_frames[PRECAPTION_CLEAN_FRAME],
        person534, score534,
    )
    transform_533_to_ref = transform_534_to_ref @ np.linalg.inv(_to_homogeneous(matrix_534_to_533))
    alignment_rows.append({
        "kind": "precaption_clean_dense_bridge",
        "from_source_frame": PRECAPTION_CLEAN_FRAME,
        "via_source_frame": PRECAPTION_SHARP_FRAME,
        "to_source_frame": REFERENCE_SOURCE_FRAME,
        "matrix": transform_533_to_ref.tolist(),
        **bridge533_metrics,
    })

    ref_authority = diff.build_final_alpha(
        row_masks[REFERENCE_FRAME], compact_masks[REFERENCE_FRAME],
        score_masks[REFERENCE_FRAME], person_masks[REFERENCE_FRAME],
    )
    donor_contamination = (
        ref_authority["source_caption"] | ref_authority["person_repair"]
    ).astype(np.uint8) * 255
    # Two source-backed donor plates are required because the camera/background is
    # screen-static while the person moves. Never apply the person affine to background.
    identity = np.eye(3, dtype=np.float64)
    precaption_background_plate, background_provenance, background_valid, background_photo = (
        build_precaption_reference_plate(
            source_frames[PRECAPTION_CLEAN_FRAME],
            source_frames[PRECAPTION_SHARP_FRAME],
            identity,
            identity,
            donor_contamination,
            bridge_person_534,
        )
    )
    precaption_person_plate_ref, person_provenance, precaption_valid, person_photo = (
        build_precaption_reference_plate(
            source_frames[PRECAPTION_CLEAN_FRAME],
            source_frames[PRECAPTION_SHARP_FRAME],
            transform_533_to_ref,
            transform_534_to_ref,
            donor_contamination,
            person_masks[REFERENCE_FRAME],
        )
    )

    geometry_preflight = {
        "task_id": TASK_ID,
        "ok": True,
        "architecture_family": ARCHITECTURE_FAMILY,
        "architecture_attempt": ARCHITECTURE_ATTEMPT,
        "target_pairwise_count": len(pairwise),
        "target_pairwise_min_inliers": min(int(row["inliers"]) for row in alignment_rows if row["kind"] == "target_pairwise"),
        "target_pairwise_max_median_error": max(float(row["median_reprojection_error_process_pixels"]) for row in alignment_rows if row["kind"] == "target_pairwise"),
        "bridge_timeline_frame": bridge_timeline_frame,
        "bridge_source_frame": bridge_authority["source_video_frame"],
        "bridge_person_mask_sha256": bridge_authority["person_mask_sha256"],
        "bridge_glyph_mask_sha256": bridge_authority["glyph_mask_sha256"],
        "sharp_536_to_534": bridge_metrics,
        "dense_534_to_533": bridge533_metrics,
        "background_photometric": background_photo,
        "person_photometric": person_photo,
    }
    if args.geometry_preflight_only:
        preflight_path = artifact_dir / "GEOMETRY_PREFLIGHT.json"
        preflight_path.write_text(
            json.dumps(json_safe(geometry_preflight), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "task_id": TASK_ID,
            "status": "geometry_preflight_pass",
            "artifact": str(preflight_path),
        }, sort_keys=True))
        return 0

    final_dir = artifact_dir / "inpainted_frames"
    for directory in (final_dir,):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    write_png(artifact_dir / "PRECLEAN_BACKGROUND_DONOR_PLATE.png", precaption_background_plate)
    write_png(artifact_dir / "PRECLEAN_PERSON_DONOR_PLATE_REF.png", precaption_person_plate_ref)
    write_png(artifact_dir / "TEMPORAL_PERSON_PLATE.png", temporal_plate)
    prov_vis = np.zeros((1920, 1080, 3), dtype=np.uint8)
    prov_vis[person_provenance == PRECAPTION_CLEAN_FRAME] = (0, 255, 255)
    prov_vis[person_provenance == PRECAPTION_SHARP_FRAME] = (255, 0, 0)
    write_png(artifact_dir / "DONOR_PROVENANCE.png", prov_vis)

    after_images = {}
    frame_metrics = []
    video_frames = []
    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        before = frames[frame]
        t_to_ref = transforms_to_ref[frame]
        inverse = np.linalg.inv(t_to_ref)

        # In reference geometry, prefer real temporal observations; use the clean
        # pre-caption donor only where the old 24-frame temporal set has no clean observation.
        person_ref = precaption_person_plate_ref.copy()
        any_temporal = temporal_count >= 1
        person_ref[any_temporal] = temporal_plate[any_temporal]
        person_valid_ref = (precaption_valid > 0) | any_temporal
        transported_person = cv2.warpPerspective(
            person_ref, inverse, (1080, 1920), flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
        transported_valid = cv2.warpPerspective(
            person_valid_ref.astype(np.uint8) * 255, inverse, (1080, 1920),
            flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
        ) > 0

        candidate = precaption_background_plate.copy()  # background remains in screen coordinates
        authority = diff.build_final_alpha(
            row_masks[frame], compact_masks[frame], score_masks[frame], person_masks[frame]
        )
        candidate[authority["person_repair"]] = transported_person[authority["person_repair"]]

        person_seed_ref = (stabilized_score[index] > 0) & (stabilized_person[index] > 0)
        seed_pixels = int(np.count_nonzero(person_seed_ref))
        temporal_any = person_seed_ref & (temporal_count >= 1)
        temporal_two = person_seed_ref & (temporal_count >= 2)
        combined_valid_ref = person_seed_ref & ((temporal_count >= 1) | (precaption_valid > 0))
        any_fraction = int(np.count_nonzero(temporal_any)) / float(seed_pixels)
        two_fraction = int(np.count_nonzero(temporal_two)) / float(seed_pixels)
        combined_fraction = int(np.count_nonzero(combined_valid_ref)) / float(seed_pixels)
        if combined_fraction < MIN_COMBINED_SOURCE_BACKED_COVERAGE:
            raise ProofError(
                f"combined real-source coverage too small at frame {frame}: {combined_fraction:.6f}"
            )
        repair_pixels = int(np.count_nonzero(authority["person_repair"]))
        transported_valid_fraction = (
            float(np.mean(transported_valid[authority["person_repair"]])) if repair_pixels else 1.0
        )
        if transported_valid_fraction < MIN_PRECAPTION_VALID_COVERAGE:
            raise ProofError(
                f"pre-caption transported validity too small at frame {frame}: "
                f"{transported_valid_fraction:.6f}"
            )

        alpha = authority["alpha"].astype(np.float32) / 255.0
        final = np.rint(
            before.astype(np.float32) * (1.0 - alpha[:, :, None])
            + candidate.astype(np.float32) * alpha[:, :, None]
        ).clip(0, 255).astype(np.uint8)
        final_path = final_dir / f"frame_{frame:06d}.png"
        write_png(final_path, final)
        after_images[frame] = final

        delta = cv2.absdiff(before, final)
        outside = ~authority["final_authority"]
        outside_changed = int(np.count_nonzero(np.any(delta[outside] != 0, axis=1)))
        protected_changed = int(
            np.count_nonzero(np.any(delta[authority["protected_person"]] != 0, axis=1))
        )
        if outside_changed != 0:
            raise ProofError(f"outside-authority pixels changed at frame {frame}: {outside_changed}")
        if protected_changed != 0:
            raise ProofError(f"protected-person pixels changed at frame {frame}: {protected_changed}")

        gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        gray_after = cv2.cvtColor(final, cv2.COLOR_BGR2GRAY)
        x1, y1, x2, y2 = bboxes[frame]
        width = max(1, x2 - x1)
        safe_score = (score_masks[frame] > 0).copy()
        safe_score[:, int(x1 + 0.42 * width): int(x1 + 0.78 * width)] = False
        safe_pixels = int(np.count_nonzero(safe_score))
        if safe_pixels < MIN_SAFE_GLYPH_PIXELS:
            raise ProofError(f"safe glyph score unexpectedly small at frame {frame}: {safe_pixels}")
        before_dark = float(np.mean(gray_before[safe_score] < v9.RIGHT_GLYPH_DARK_THRESHOLD))
        after_dark = float(np.mean(gray_after[safe_score] < v9.RIGHT_GLYPH_DARK_THRESHOLD))
        reduction = diff.relative_reduction(before_dark, after_dark)

        probe_x1 = max(x1, x2 - v9.RIGHT_GLYPH_PROBE_INSIDE_PIXELS)
        authority_xs = np.where(authority["final_authority"])[1]
        probe_x2 = max(x2, int(authority_xs.max()) + 1)
        right_probe = np.zeros_like(gray_before, dtype=bool)
        right_probe[y1:y2, probe_x1:probe_x2] = True
        right_source_dark = right_probe & (gray_before < v9.RIGHT_GLYPH_DARK_THRESHOLD)
        right_source_dark_pixels = int(np.count_nonzero(right_source_dark))
        v9.require_right_glyph_probe_population(frame, right_source_dark_pixels)
        right_survival = (
            float(np.mean(gray_after[right_source_dark] < v9.RIGHT_GLYPH_DARK_THRESHOLD))
            if right_source_dark_pixels else 0.0
        )
        artifact = diff.visual_artifact_metrics(
            before, final, authority["alpha"], authority["source_caption"], person_masks[frame]
        )
        frame_metrics.append({
            "timeline_frame": frame,
            "source_video_frame": actual_mapping[frame],
            "outside_authority_changed_pixels": outside_changed,
            "protected_person_changed_pixels": protected_changed,
            "source_backed_temporal_any_fraction": any_fraction,
            "source_backed_temporal_two_fraction": two_fraction,
            "source_backed_combined_fraction": combined_fraction,
            "transported_person_valid_fraction": transported_valid_fraction,
            "safe_glyph_score_pixels": safe_pixels,
            "safe_glyph_dark_ratio_lt140_before": before_dark,
            "safe_glyph_dark_ratio_lt140_after": after_dark,
            "safe_glyph_dark_reduction": reduction,
            "right_source_dark_pixels": right_source_dark_pixels,
            "right_source_dark_survival_lt140": right_survival,
            "right_source_dark_removal": 1.0 - right_survival,
            **artifact,
            "final_sha256": sha256_file(final_path),
        })
        before_small = cv2.resize(before, (432, 768), interpolation=cv2.INTER_AREA)
        after_small = cv2.resize(final, (432, 768), interpolation=cv2.INTER_AREA)
        cv2.putText(before_small, f"BEFORE {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, .85, (255,255,255), 2, cv2.LINE_AA)
        cv2.putText(after_small, f"SOURCE TRANSPORT {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, .75, (255,255,255), 2, cv2.LINE_AA)
        video_frames.append(cv2.cvtColor(np.concatenate([before_small, after_small], axis=1), cv2.COLOR_BGR2RGB))

    comparison_video = artifact_dir / "COME_BEFORE_AFTER_PRECAPTION_SOURCE_TRANSPORT_V1.mp4"
    comparison_video_writer = write_rgb_mp4(comparison_video, video_frames, FPS)

    pairs, masks = [], []
    for frame in SENTINELS:
        authority = diff.build_final_alpha(
            row_masks[frame], compact_masks[frame], score_masks[frame], person_masks[frame]
        )
        ys, xs = np.where(authority["final_authority"])
        cx1, cx2 = max(0, int(xs.min()) - 80), min(1080, int(xs.max()) + 81)
        cy1, cy2 = max(0, int(ys.min()) - 90), min(1920, int(ys.max()) + 91)
        pairs.append((f"BEFORE {frame}", frames[frame][cy1:cy2, cx1:cx2]))
        pairs.append((f"AFTER {frame}", after_images[frame][cy1:cy2, cx1:cx2]))
        mask_vis = np.zeros_like(frames[frame])
        mask_vis[:, :, 0] = row_masks[frame]
        mask_vis[:, :, 1] = authority["alpha"]
        mask_vis[:, :, 2] = person_masks[frame]
        masks.append((f"MASK {frame}", mask_vis[cy1:cy2, cx1:cx2]))
    diff.create_contact_sheet(v9, pairs, artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png")
    diff.create_contact_sheet(v9, masks, artifact_dir / "MASK_CONTACT_SHEET.png")

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "status": "proof_completed_validation_required",
        "architecture": {
            "family": ARCHITECTURE_FAMILY,
            "attempt_number": ARCHITECTURE_ATTEMPT,
            "mechanism_failed_before": "masked_generative_reconstruction_hallucinated_structure",
            "why_new_design_avoids_it": "repair authority is derived only from observed source frames; no neural/generated reconstruction is accepted",
            "genuinely_new_capability": "clean same-shot frame 533 plus dense caption-safe Farneback correspondences across the 534->533 blur transition fill the old temporal donor coverage deficit without lowering sparse thresholds",
            "closed_families": list(CLOSED_ARCHITECTURE_FAMILIES),
            "generative_inference_calls": 0,
        },
        "source_authority": {
            "source_video": "input/DZsqH7auhjt.mp4",
            "source_video_sha256": EXPECTED_SOURCE_VIDEO_SHA256,
            "foreground_manifest_sha256": EXPECTED_FOREGROUND_MANIFEST_SHA256,
            "diffueraser_authority_helper_sha256": EXPECTED_DIFF_HELPER_SHA256,
            "precaption_clean_source_frame": PRECAPTION_CLEAN_FRAME,
            "precaption_sharp_source_frame": PRECAPTION_SHARP_FRAME,
            "target_reference_source_frame": REFERENCE_SOURCE_FRAME,
            "bridge_timeline_frame": bridge_timeline_frame,
            "bridge_person_mask_sha256": bridge_authority["person_mask_sha256"],
            "bridge_glyph_mask_sha256": bridge_authority["glyph_mask_sha256"],
            "precaption_bridge_method": PRECAPTION_BRIDGE_METHOD,
            "timeline_to_source": actual_mapping,
            "source_context": source_context,
        },
        "thresholds": {
            "min_combined_source_backed_coverage": MIN_COMBINED_SOURCE_BACKED_COVERAGE,
            "min_precaption_valid_coverage": MIN_PRECAPTION_VALID_COVERAGE,
            "min_source_glyph_reduction": MIN_SOURCE_GLYPH_REDUCTION,
            "min_right_glyph_removal": MIN_RIGHT_GLYPH_REMOVAL,
            "max_new_dark_artifact_ratio": MAX_NEW_DARK_ARTIFACT_RATIO,
            "max_new_bright_artifact_ratio": MAX_NEW_BRIGHT_ARTIFACT_RATIO,
            "max_boundary_ring_mae": MAX_BOUNDARY_RING_MAE,
            "dense_bridge_min_support_pixels": DENSE_BRIDGE_MIN_SUPPORT_PIXELS,
            "dense_bridge_min_fb_valid_fraction": DENSE_BRIDGE_MIN_FB_VALID_FRACTION,
            "dense_bridge_max_median_fb_error": DENSE_BRIDGE_MAX_MEDIAN_FB_ERROR,
            "dense_bridge_max_photometric_mae": DENSE_BRIDGE_MAX_PHOTOMETRIC_MAE,
            "dense_bridge_min_sampled_correspondences": DENSE_BRIDGE_MIN_SAMPLED_CORRESPONDENCES,
            "dense_bridge_min_ransac_inliers": DENSE_BRIDGE_MIN_RANSAC_INLIERS,
            "dense_bridge_max_median_ransac_error": DENSE_BRIDGE_MAX_MEDIAN_RANSAC_ERROR,
            "dense_bridge_max_p95_ransac_error": DENSE_BRIDGE_MAX_P95_RANSAC_ERROR,
        },
        "precaption_dense_bridge": bridge533_metrics,
        "geometry_preflight": geometry_preflight,
        "photometric_source533_to_534": {
            "background_screen_static": background_photo,
            "person_reference_geometry": person_photo,
        },
        "alignment_rows": alignment_rows,
        "input_frames": input_rows,
        "frame_metrics": frame_metrics,
        "artifacts": {
            "comparison_video": str(comparison_video),
            "comparison_video_writer": comparison_video_writer,
            "before_after_contact_sheet": str(artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png"),
            "mask_contact_sheet": str(artifact_dir / "MASK_CONTACT_SHEET.png"),
            "precaption_background_donor_plate": str(artifact_dir / "PRECLEAN_BACKGROUND_DONOR_PLATE.png"),
            "precaption_person_donor_plate_ref": str(artifact_dir / "PRECLEAN_PERSON_DONOR_PLATE_REF.png"),
            "temporal_person_plate": str(artifact_dir / "TEMPORAL_PERSON_PLATE.png"),
            "donor_provenance": str(artifact_dir / "DONOR_PROVENANCE.png"),
            "final_dir": str(final_dir),
        },
        "resolve_invocations": 0,
        "timeline_mutations": 0,
        "save_project_calls": 0,
        "visual_approval_required": True,
    }
    (artifact_dir / "PROOF_RUN_RESULT.json").write_text(
        json.dumps(json_safe(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"task_id": TASK_ID, "status": result["status"], "artifact_dir": str(artifact_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
