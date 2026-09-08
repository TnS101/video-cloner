from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_baked_caption_video_inpaint_proof_v1 as legacy

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_SOURCE_BACKED_TEMPORAL_RECOVERY_V1"
EXPECTED_LEGACY_TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_VIDEO_INPAINT_PROOF_V9"
ARCHITECTURE_FAMILY = "stabilized_source_backed_person_then_background_v1"
CLOSED_ARCHITECTURE_FAMILY = "propainter_semantic_split_person_repair_v1"
VISUAL_FAIL_STOP = "stop_current_family_no_mask_parameter_retry"
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
FRAME_COUNT = SOURCE_FRAME_END - SOURCE_FRAME_START + 1
REFERENCE_FRAME = 443
STABILIZED_CROP = (284, 620, 796, 940)  # x1, y1, x2, y2 => 512x320
STABILIZED_WIDTH = 512
STABILIZED_HEIGHT = 320
PAIRWISE_SCALE = 0.5
PAIRWISE_MIN_INLIERS = 40
PAIRWISE_MAX_MEDIAN_ERROR = 1.25
PAIRWISE_MIN_SCALE = 0.97
PAIRWISE_MAX_SCALE = 1.03
PAIRWISE_MAX_ROTATION_DEGREES = 2.0
SOURCE_BACKED_MIN_ANY_COVERAGE = 0.83
SOURCE_BACKED_MIN_TWO_OBSERVATION_COVERAGE = 0.75
SOURCE_BACKED_KNOWN_MIN_OBSERVATIONS = 2
PERSON_REPAIR_DILATION_PIXELS = 2
PERSON_REPAIR_FEATHER_SIGMA = 1.0
BACKGROUND_FEATHER_SIGMA = 3.0
BACKGROUND_MASK_DILATION = 0
PERSON_PASS_MASK_DILATION = 0
FPS = 24
HOLD_SENTINELS = (434, 438, 443, 448)
SENTINELS = (429, 431, 434, 438, 443, 448, 452)


class RecoveryError(RuntimeError):
    pass


def _require_legacy_contract() -> None:
    if getattr(legacy, "TASK_ID", None) != EXPECTED_LEGACY_TASK_ID:
        raise RecoveryError(
            f"unexpected legacy proof helper task id: {getattr(legacy, 'TASK_ID', None)!r}"
        )
    required = (
        "resolve_repo_root",
        "load_json",
        "sha256_file",
        "verify_style_anchors",
        "verify_source_context_authority",
        "interpolate_bbox",
        "transform_glyph_mask",
        "clip_mask_to_bbox",
        "build_compact_caption_masks",
        "load_v4_foreground_authority",
        "load_full_resolution_person_mask",
        "require_right_glyph_probe_population",
        "create_contact_sheet",
        "run_command",
    )
    missing = [name for name in required if not hasattr(legacy, name)]
    if missing:
        raise RecoveryError(f"legacy helper contract missing symbols: {missing}")


def _to_homogeneous(matrix):
    import numpy as np

    result = np.eye(3, dtype=np.float64)
    result[:2, :] = matrix
    return result


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
    """Estimate donor->target upper-body similarity using only visible person context.

    The baked COME region is explicitly excluded from both feature selection and
    endpoint validation. The forward/backward LK check plus RANSAC keeps this a
    deterministic geometry step rather than an image-synthesis step.
    """

    import cv2
    import numpy as np

    height, width = donor_image.shape[:2]
    if target_image.shape[:2] != (height, width):
        raise RecoveryError("pairwise frame shape mismatch")
    process_width = int(round(width * PAIRWISE_SCALE))
    process_height = int(round(height * PAIRWISE_SCALE))
    donor_gray = cv2.resize(
        cv2.cvtColor(donor_image, cv2.COLOR_BGR2GRAY),
        (process_width, process_height),
        interpolation=cv2.INTER_AREA,
    )
    target_gray = cv2.resize(
        cv2.cvtColor(target_image, cv2.COLOR_BGR2GRAY),
        (process_width, process_height),
        interpolation=cv2.INTER_AREA,
    )
    donor_person = cv2.resize(
        (donor_person_mask > 0).astype(np.uint8),
        (process_width, process_height),
        interpolation=cv2.INTER_NEAREST,
    ) > 0
    target_person = cv2.resize(
        (target_person_mask > 0).astype(np.uint8),
        (process_width, process_height),
        interpolation=cv2.INTER_NEAREST,
    ) > 0
    donor_score = cv2.resize(
        (donor_score_mask > 0).astype(np.uint8),
        (process_width, process_height),
        interpolation=cv2.INTER_NEAREST,
    ) > 0
    target_score = cv2.resize(
        (target_score_mask > 0).astype(np.uint8),
        (process_width, process_height),
        interpolation=cv2.INTER_NEAREST,
    ) > 0

    y_grid = np.arange(process_height)[:, None]
    donor_caption_buffer = cv2.dilate(
        donor_score.astype(np.uint8),
        np.ones((11, 11), dtype=np.uint8),
        iterations=1,
    ) > 0
    support = donor_person & ~donor_caption_buffer
    support &= (y_grid >= int(round(640 * PAIRWISE_SCALE)))
    support &= (y_grid <= int(round(1150 * PAIRWISE_SCALE)))

    points = cv2.goodFeaturesToTrack(
        donor_gray,
        maxCorners=600,
        qualityLevel=0.005,
        minDistance=4,
        blockSize=7,
        mask=support.astype(np.uint8) * 255,
    )
    if points is None or len(points) < 20:
        raise RecoveryError(f"pairwise stabilization has too few donor features: {0 if points is None else len(points)}")

    tracked, status, _ = cv2.calcOpticalFlowPyrLK(
        donor_gray,
        target_gray,
        points,
        None,
        winSize=(41, 41),
        maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 0.005),
    )
    backward, backward_status, _ = cv2.calcOpticalFlowPyrLK(
        target_gray,
        donor_gray,
        tracked,
        None,
        winSize=(41, 41),
        maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 0.005),
    )
    good = (status[:, 0] > 0) & (backward_status[:, 0] > 0)
    fb_error = np.linalg.norm(backward[:, 0] - points[:, 0], axis=1)
    good &= fb_error < 1.2
    donor_points = points[:, 0][good]
    target_points = tracked[:, 0][good]
    if len(donor_points) < PAIRWISE_MIN_INLIERS:
        raise RecoveryError(f"pairwise stabilization has too few forward/backward points: {len(donor_points)}")

    target_xy = np.rint(target_points).astype(np.int32)
    valid = (
        (target_xy[:, 0] >= 0)
        & (target_xy[:, 0] < process_width)
        & (target_xy[:, 1] >= 0)
        & (target_xy[:, 1] < process_height)
    )
    target_caption_buffer = cv2.dilate(
        target_score.astype(np.uint8),
        np.ones((11, 11), dtype=np.uint8),
        iterations=1,
    ) > 0
    endpoint_ok = np.zeros(len(valid), dtype=bool)
    valid_indices = np.where(valid)[0]
    endpoint_ok[valid_indices] = (
        target_person[target_xy[valid_indices, 1], target_xy[valid_indices, 0]]
        & ~target_caption_buffer[target_xy[valid_indices, 1], target_xy[valid_indices, 0]]
    )
    donor_points = donor_points[endpoint_ok]
    target_points = target_points[endpoint_ok]
    if len(donor_points) < PAIRWISE_MIN_INLIERS:
        raise RecoveryError(f"pairwise stabilization has too few caption-safe points: {len(donor_points)}")

    matrix, inliers = cv2.estimateAffinePartial2D(
        donor_points,
        target_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=1.5,
        maxIters=3000,
        confidence=0.995,
        refineIters=20,
    )
    if matrix is None or inliers is None:
        raise RecoveryError("pairwise stabilization RANSAC failed")
    inlier_mask = inliers[:, 0] > 0
    inlier_count = int(np.count_nonzero(inlier_mask))
    if inlier_count < PAIRWISE_MIN_INLIERS:
        raise RecoveryError(f"pairwise stabilization RANSAC inliers too small: {inlier_count}")
    predicted = donor_points @ matrix[:, :2].T + matrix[:, 2]
    errors = np.linalg.norm(predicted - target_points, axis=1)
    median_error = float(np.median(errors[inlier_mask]))

    full_matrix = matrix.astype(np.float64).copy()
    full_matrix[:, 2] /= PAIRWISE_SCALE
    scale, rotation = _matrix_scale_rotation(full_matrix)
    if median_error > PAIRWISE_MAX_MEDIAN_ERROR:
        raise RecoveryError(f"pairwise stabilization median error too high: {median_error:.6f}")
    if not (PAIRWISE_MIN_SCALE <= scale <= PAIRWISE_MAX_SCALE):
        raise RecoveryError(f"pairwise stabilization scale escaped bound: {scale:.6f}")
    if abs(rotation) > PAIRWISE_MAX_ROTATION_DEGREES:
        raise RecoveryError(f"pairwise stabilization rotation escaped bound: {rotation:.6f}")
    return full_matrix, {
        "inliers": inlier_count,
        "median_reprojection_error_process_pixels": median_error,
        "scale": scale,
        "rotation_degrees": rotation,
    }


def compose_transforms_to_reference(pairwise: dict[tuple[int, int], object], reference_frame: int):
    import numpy as np

    transforms: dict[int, object] = {}
    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1):
        transform = np.eye(3, dtype=np.float64)
        if frame < reference_frame:
            for cursor in range(frame, reference_frame):
                transform = _to_homogeneous(pairwise[(cursor, cursor + 1)]) @ transform
        elif frame > reference_frame:
            for cursor in range(frame - 1, reference_frame - 1, -1):
                transform = np.linalg.inv(_to_homogeneous(pairwise[(cursor, cursor + 1)])) @ transform
        transforms[frame] = transform
    return transforms


def warp_binary(mask, transform, width: int, height: int):
    import cv2
    import numpy as np

    return cv2.warpPerspective(
        (mask > 0).astype(np.uint8) * 255,
        transform,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def build_source_backed_clean_plate(stabilized_images, stabilized_person_masks, stabilized_score_masks):
    import numpy as np

    image_stack = np.stack(stabilized_images, axis=0)
    person_stack = np.stack([mask > 0 for mask in stabilized_person_masks], axis=0)
    score_stack = np.stack([mask > 0 for mask in stabilized_score_masks], axis=0)
    clean_stack = person_stack & ~score_stack
    clean_count = np.sum(clean_stack, axis=0).astype(np.uint8)
    plate = np.zeros(image_stack.shape[1:], dtype=np.uint8)
    for channel in range(3):
        values = image_stack[..., channel].astype(np.float32)
        values[~clean_stack] = np.nan
        with np.errstate(all="ignore"):
            median = np.nanmedian(values, axis=0)
        median = np.nan_to_num(median, nan=0.0)
        plate[..., channel] = np.rint(median).clip(0, 255).astype(np.uint8)
    return plate, clean_count


def build_inward_alpha(core_mask, sigma: float, full_alpha_mask=None):
    import cv2
    import numpy as np

    core = core_mask > 0
    if not np.any(core):
        raise RecoveryError("empty composite core mask")
    blurred = cv2.GaussianBlur(core.astype(np.uint8) * 255, (0, 0), sigma).astype(np.float32) / 255.0
    alpha = blurred * core.astype(np.float32)
    if full_alpha_mask is not None:
        alpha[full_alpha_mask > 0] = 1.0
    alpha[~core] = 0.0
    return alpha


def run_propainter_pass(
    *,
    python_exe: str,
    propainter_source: Path,
    video_dir: Path,
    mask_dir: Path,
    output_dir: Path,
    width: int,
    height: int,
    log_path: Path,
    mask_dilation: int,
):
    command = [
        python_exe,
        str(propainter_source / "inference_propainter.py"),
        "--video",
        str(video_dir),
        "--mask",
        str(mask_dir),
        "--output",
        str(output_dir),
        "--width",
        str(width),
        "--height",
        str(height),
        "--mask_dilation",
        str(mask_dilation),
        "--neighbor_length",
        "6",
        "--ref_stride",
        "6",
        "--subvideo_length",
        str(FRAME_COUNT),
        "--save_fps",
        str(FPS),
        "--save_frames",
        "--fp16",
    ]
    legacy.run_command(command, cwd=propainter_source, log_path=log_path)
    candidates = sorted(output_dir.glob("*/frames"))
    valid = [path for path in candidates if path.is_dir() and len(list(path.glob("*.png"))) == FRAME_COUNT]
    if len(valid) != 1:
        raise RecoveryError(f"expected one ProPainter frame directory with {FRAME_COUNT} frames, got {valid}")
    return valid[0]


def _write_png(path: Path, image) -> None:
    import cv2

    if not cv2.imwrite(str(path), image):
        raise RecoveryError(f"failed to write image: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--propainter-source", required=True)
    parser.add_argument("--foreground-authority-dir", required=True)
    args = parser.parse_args()

    import cv2
    import imageio.v2 as imageio
    import numpy as np

    _require_legacy_contract()
    repo_root = legacy.resolve_repo_root(args.repo_root)
    artifact_dir = Path(args.artifact_dir).resolve()
    propainter_source = Path(args.propainter_source).resolve()
    foreground_authority_dir = Path(args.foreground_authority_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if not (propainter_source / "inference_propainter.py").is_file():
        raise RecoveryError(f"invalid ProPainter source: {propainter_source}")

    failed_run = repo_root / legacy.V2_FAILED_RUN_REL
    geometry_run = repo_root / legacy.V3_GEOMETRY_RUN_REL
    base_dir = failed_run / "render_base_baked"
    glyph_dir = geometry_run / "generated_pixel_restore_v3" / "glyph_masks"
    required_paths = (
        failed_run / "report.json",
        failed_run / "base_render_authority.json",
        geometry_run / "generated_pixel_restore_v3" / "manifest.json",
        repo_root / legacy.STYLE_REL,
        repo_root / legacy.SOURCE_TRACK_REL,
        repo_root / legacy.LIFECYCLE_REL,
    )
    for path in required_paths:
        if not path.is_file():
            raise RecoveryError(f"missing proof authority file: {path}")

    failed_report = legacy.load_json(failed_run / "report.json")
    if (
        not isinstance(failed_report, dict)
        or failed_report.get("task_id")
        != "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_COME_ONLY_V2"
        or failed_report.get("ok") is not False
        or failed_report.get("failed_target_retained") is not False
    ):
        raise RecoveryError("unexpected COME-only V2 failed-run authority")
    v3_manifest = legacy.load_json(geometry_run / "generated_pixel_restore_v3" / "manifest.json")
    if (
        not isinstance(v3_manifest, dict)
        or v3_manifest.get("ok") is not True
        or v3_manifest.get("task_id") != "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3"
        or v3_manifest.get("timeline_range_half_open") != [426, 454]
    ):
        raise RecoveryError("unexpected V3 glyph authority")
    v3_rows = v3_manifest.get("frames")
    if not isinstance(v3_rows, list):
        raise RecoveryError("V3 glyph frame rows missing")
    v3_by_frame = {
        int(row["timeline_frame"]): row
        for row in v3_rows
        if isinstance(row, dict) and isinstance(row.get("timeline_frame"), int)
    }
    base_authority = legacy.load_json(failed_run / "base_render_authority.json")
    if not isinstance(base_authority, dict) or base_authority.get("ok") is not True:
        raise RecoveryError("base render authority is not PASS")
    if base_authority.get("dimensions") != {"frame_rate": 24.0, "height": 1920, "width": 1080}:
        raise RecoveryError(f"unexpected base render dimensions: {base_authority.get('dimensions')}")

    anchors = legacy.verify_style_anchors(legacy.load_json(repo_root / legacy.STYLE_REL))
    source_context = legacy.verify_source_context_authority(
        legacy.load_json(repo_root / legacy.SOURCE_TRACK_REL),
        legacy.load_json(repo_root / legacy.LIFECYCLE_REL),
        repo_root,
    )
    foreground_paths = legacy.load_v4_foreground_authority(foreground_authority_dir)
    foreground_manifest_sha256 = legacy.sha256_file(foreground_authority_dir / "manifest.json")

    base_images: dict[int, object] = {}
    glyph_masks: dict[int, object] = {}
    score_masks: dict[int, object] = {}
    compact_masks: dict[int, object] = {}
    row_filled_masks: dict[int, object] = {}
    person_masks: dict[int, object] = {}
    input_rows: list[dict[str, object]] = []

    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1):
        base_path = base_dir / f"base_baked_{frame:08d}.png"
        glyph_path = glyph_dir / f"glyph_{frame:06d}.png"
        if not base_path.is_file() or not glyph_path.is_file():
            raise RecoveryError(f"missing proof input at frame {frame}")
        v3_row = v3_by_frame.get(frame)
        expected_rel = f"glyph_masks/glyph_{frame:06d}.png"
        if not isinstance(v3_row, dict) or v3_row.get("glyph_mask") != expected_rel:
            raise RecoveryError(f"V3 glyph metadata mismatch at frame {frame}")
        expected_hash = v3_row.get("glyph_mask_sha256")
        if not isinstance(expected_hash, str) or legacy.sha256_file(glyph_path) != expected_hash:
            raise RecoveryError(f"V3 glyph hash mismatch at frame {frame}")
        image = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
        glyph = cv2.imread(str(glyph_path), cv2.IMREAD_GRAYSCALE)
        if image is None or glyph is None or image.shape[:2] != (1920, 1080) or glyph.shape != (1920, 1080):
            raise RecoveryError(f"invalid proof input dimensions at frame {frame}")
        target_bbox = legacy.interpolate_bbox(frame, anchors)
        score = legacy.clip_mask_to_bbox(legacy.transform_glyph_mask(glyph, target_bbox), target_bbox)
        compact = legacy.build_compact_caption_masks(image, glyph, target_bbox)
        person = legacy.load_full_resolution_person_mask(foreground_paths[frame], image.shape[:2])
        score_core = score > 0
        compact_core = compact["composite_mask"] > 0
        person_core = person > 0
        person_seed = score_core & person_core
        if int(np.count_nonzero(person_seed)) < 2500:
            raise RecoveryError(f"source-backed person/glyph seed unexpectedly small at frame {frame}")
        score_coverage = int(np.count_nonzero(score_core & compact_core)) / float(np.count_nonzero(score_core))
        if score_coverage < legacy.MIN_SCORE_MASK_COVERAGE:
            raise RecoveryError(f"score/compact coverage regressed at frame {frame}: {score_coverage:.6f}")
        base_images[frame] = image
        glyph_masks[frame] = glyph
        score_masks[frame] = score
        compact_masks[frame] = compact["composite_mask"]
        row_filled_masks[frame] = compact["inpaint_mask"]
        person_masks[frame] = person
        input_rows.append(
            {
                "timeline_frame": frame,
                "base_file": str(base_path.relative_to(repo_root).as_posix()),
                "base_sha256": legacy.sha256_file(base_path),
                "glyph_file": str(glyph_path.relative_to(repo_root).as_posix()),
                "glyph_sha256": expected_hash,
                "source_bbox": list(target_bbox),
                "score_mask_pixels": int(np.count_nonzero(score_core)),
                "person_glyph_seed_pixels": int(np.count_nonzero(person_seed)),
                "compact_source_mask_pixels": int(np.count_nonzero(compact_core)),
                "row_filled_mask_pixels": int(np.count_nonzero(compact["inpaint_mask"])),
                "dynamic_right_guard_pixels": int(compact["dynamic_right_guard_pixels"]),
                "compact_vs_legacy_solid_ratio": float(compact["compact_vs_legacy_solid_ratio"]),
                "score_mask_coverage": score_coverage,
            }
        )

    pairwise: dict[tuple[int, int], object] = {}
    alignment_rows: list[dict[str, object]] = []
    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END):
        matrix, metrics = estimate_pairwise_person_affine(
            base_images[frame],
            base_images[frame + 1],
            person_masks[frame],
            person_masks[frame + 1],
            score_masks[frame],
            score_masks[frame + 1],
        )
        pairwise[(frame, frame + 1)] = matrix
        alignment_rows.append(
            {
                "from_frame": frame,
                "to_frame": frame + 1,
                "matrix": [[float(value) for value in row] for row in matrix.tolist()],
                **metrics,
            }
        )
    transforms = compose_transforms_to_reference(pairwise, REFERENCE_FRAME)

    person_inputs = artifact_dir / "person_stabilized_input_frames"
    person_masks_dir = artifact_dir / "person_stabilized_masks"
    person_output = artifact_dir / "person_propainter_output"
    background_inputs = artifact_dir / "background_input_frames"
    background_masks_dir = artifact_dir / "background_masks"
    background_output = artifact_dir / "background_propainter_output"
    final_dir = artifact_dir / "inpainted_frames"
    for directory in (
        person_inputs,
        person_masks_dir,
        person_output,
        background_inputs,
        background_masks_dir,
        background_output,
        final_dir,
    ):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    x1, y1, x2, y2 = STABILIZED_CROP
    stabilized_images = []
    stabilized_person_masks = []
    stabilized_score_masks = []
    stabilized_row_filled_masks = []
    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1):
        transform = transforms[frame]
        stabilized = cv2.warpPerspective(
            base_images[frame],
            transform,
            (1080, 1920),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
        stabilized_person = warp_binary(person_masks[frame], transform, 1080, 1920)
        stabilized_score = warp_binary(score_masks[frame], transform, 1080, 1920)
        stabilized_row_filled = warp_binary(row_filled_masks[frame], transform, 1080, 1920)
        stabilized_images.append(stabilized[y1:y2, x1:x2].copy())
        stabilized_person_masks.append(stabilized_person[y1:y2, x1:x2].copy())
        stabilized_score_masks.append(stabilized_score[y1:y2, x1:x2].copy())
        stabilized_row_filled_masks.append(stabilized_row_filled[y1:y2, x1:x2].copy())

    clean_plate, clean_count = build_source_backed_clean_plate(
        stabilized_images,
        stabilized_person_masks,
        stabilized_score_masks,
    )
    _write_png(artifact_dir / "STABILIZED_SOURCE_BACKED_PERSON_PLATE.png", clean_plate)

    coverage_rows: list[dict[str, object]] = []
    known_masks: dict[int, object] = {}
    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        person = stabilized_person_masks[index] > 0
        score = stabilized_score_masks[index] > 0
        seed = person & score
        any_known = seed & (clean_count >= 1)
        two_known = seed & (clean_count >= SOURCE_BACKED_KNOWN_MIN_OBSERVATIONS)
        seed_pixels = int(np.count_nonzero(seed))
        any_fraction = int(np.count_nonzero(any_known)) / float(seed_pixels)
        two_fraction = int(np.count_nonzero(two_known)) / float(seed_pixels)
        if any_fraction < SOURCE_BACKED_MIN_ANY_COVERAGE:
            raise RecoveryError(f"stabilized source-backed coverage too small at frame {frame}: {any_fraction:.6f}")
        if two_fraction < SOURCE_BACKED_MIN_TWO_OBSERVATION_COVERAGE:
            raise RecoveryError(
                f"stabilized two-observation source-backed coverage too small at frame {frame}: {two_fraction:.6f}"
            )
        known_masks[frame] = two_known.astype(np.uint8) * 255
        coverage_rows.append(
            {
                "timeline_frame": frame,
                "person_glyph_seed_pixels_stabilized": seed_pixels,
                "source_backed_any_pixels": int(np.count_nonzero(any_known)),
                "source_backed_any_fraction": any_fraction,
                "source_backed_two_observation_pixels": int(np.count_nonzero(two_known)),
                "source_backed_two_observation_fraction": two_fraction,
                "model_unresolved_fraction": 1.0 - two_fraction,
            }
        )
        input_image = stabilized_images[index].copy()
        input_image[two_known] = clean_plate[two_known]
        inference_mask = stabilized_row_filled_masks[index] > 0
        inference_mask[two_known] = False
        sequential = f"{index:04d}.png"
        _write_png(person_inputs / sequential, input_image)
        _write_png(person_masks_dir / sequential, inference_mask.astype(np.uint8) * 255)

    person_result_frames = run_propainter_pass(
        python_exe=sys.executable,
        propainter_source=propainter_source,
        video_dir=person_inputs,
        mask_dir=person_masks_dir,
        output_dir=person_output,
        width=STABILIZED_WIDTH,
        height=STABILIZED_HEIGHT,
        log_path=artifact_dir / "PROPAINTER_PERSON_RUN.log",
        mask_dilation=PERSON_PASS_MASK_DILATION,
    )

    precleaned_images: dict[int, object] = {}
    person_alpha_masks: dict[int, object] = {}
    person_pass_rows: list[dict[str, object]] = []
    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        generated_crop = cv2.imread(str(person_result_frames / f"{index:04d}.png"), cv2.IMREAD_COLOR)
        if generated_crop is None:
            raise RecoveryError(f"missing stabilized person ProPainter output at frame {frame}")
        if generated_crop.shape[:2] != (STABILIZED_HEIGHT, STABILIZED_WIDTH):
            generated_crop = cv2.resize(
                generated_crop,
                (STABILIZED_WIDTH, STABILIZED_HEIGHT),
                interpolation=cv2.INTER_CUBIC,
            )
        known = known_masks[frame] > 0
        generated_crop[known] = clean_plate[known]
        reference_canvas = np.zeros((1920, 1080, 3), dtype=np.uint8)
        reference_valid = np.zeros((1920, 1080), dtype=np.uint8)
        reference_canvas[y1:y2, x1:x2] = generated_crop
        reference_valid[y1:y2, x1:x2] = 255
        inverse = np.linalg.inv(transforms[frame])
        generated_target = cv2.warpPerspective(
            reference_canvas,
            inverse,
            (1080, 1920),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        valid_target = cv2.warpPerspective(
            reference_valid,
            inverse,
            (1080, 1920),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        ) > 0
        person_seed = (score_masks[frame] > 0) & (person_masks[frame] > 0)
        repair_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (2 * PERSON_REPAIR_DILATION_PIXELS + 1, 2 * PERSON_REPAIR_DILATION_PIXELS + 1),
        )
        repair_core = cv2.dilate(person_seed.astype(np.uint8) * 255, repair_kernel) > 0
        repair_core &= (person_masks[frame] > 0) & valid_target
        person_alpha = build_inward_alpha(
            repair_core,
            PERSON_REPAIR_FEATHER_SIGMA,
            full_alpha_mask=person_seed,
        )
        before = base_images[frame]
        precleaned = np.rint(
            before.astype(np.float32) * (1.0 - person_alpha[..., None])
            + generated_target.astype(np.float32) * person_alpha[..., None]
        ).clip(0, 255).astype(np.uint8)
        precleaned_images[frame] = precleaned
        person_alpha_masks[frame] = person_alpha
        _write_png(background_inputs / f"{index:04d}.png", precleaned)
        background_mask = (row_filled_masks[frame] > 0) & ~(person_masks[frame] > 0)
        _write_png(background_masks_dir / f"{index:04d}.png", background_mask.astype(np.uint8) * 255)
        person_delta = cv2.absdiff(before, precleaned)
        protected_person = (person_masks[frame] > 0) & ~(repair_core)
        protected_changed = int(np.count_nonzero(np.any(person_delta[protected_person] != 0, axis=1)))
        if protected_changed != 0:
            raise RecoveryError(f"person preclean changed protected context at frame {frame}: {protected_changed}")
        person_pass_rows.append(
            {
                "timeline_frame": frame,
                "person_repair_pixels": int(np.count_nonzero(repair_core)),
                "person_seed_pixels": int(np.count_nonzero(person_seed)),
                "protected_person_context_changed_pixels": protected_changed,
                "person_seed_delta_mae": float(np.mean(person_delta[person_seed])) if np.any(person_seed) else 0.0,
            }
        )

    background_result_frames = run_propainter_pass(
        python_exe=sys.executable,
        propainter_source=propainter_source,
        video_dir=background_inputs,
        mask_dir=background_masks_dir,
        output_dir=background_output,
        width=legacy.PROCESS_WIDTH,
        height=legacy.PROCESS_HEIGHT,
        log_path=artifact_dir / "PROPAINTER_BACKGROUND_RUN.log",
        mask_dilation=BACKGROUND_MASK_DILATION,
    )

    after_images: dict[int, object] = {}
    metric_rows: list[dict[str, object]] = []
    video_frames = []
    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        generated_background = cv2.imread(str(background_result_frames / f"{index:04d}.png"), cv2.IMREAD_COLOR)
        if generated_background is None:
            raise RecoveryError(f"missing background ProPainter output at frame {frame}")
        before = base_images[frame]
        if generated_background.shape != before.shape:
            generated_background = cv2.resize(
                generated_background,
                (before.shape[1], before.shape[0]),
                interpolation=cv2.INTER_CUBIC,
            )
        person = person_masks[frame] > 0
        background_core = (row_filled_masks[frame] > 0) & ~person
        compact_background = (compact_masks[frame] > 0) & ~person
        background_alpha = build_inward_alpha(
            background_core,
            BACKGROUND_FEATHER_SIGMA,
            full_alpha_mask=compact_background,
        )
        person_alpha = person_alpha_masks[frame]
        precleaned = precleaned_images[frame]
        final = np.rint(
            precleaned.astype(np.float32) * (1.0 - background_alpha[..., None])
            + generated_background.astype(np.float32) * background_alpha[..., None]
        ).clip(0, 255).astype(np.uint8)
        final_path = final_dir / f"frame_{frame:06d}.png"
        _write_png(final_path, final)
        after_images[frame] = final

        authority = (background_alpha > 0.0) | (person_alpha > 0.0)
        delta = cv2.absdiff(before, final)
        outside_changed = int(np.count_nonzero(np.any(delta[~authority] != 0, axis=1)))
        if outside_changed != 0:
            raise RecoveryError(f"outside-authority preservation failed at frame {frame}: {outside_changed}")
        protected_person = person & ~(person_alpha > 0.0)
        person_context_changed = int(np.count_nonzero(np.any(delta[protected_person] != 0, axis=1)))
        if person_context_changed != 0:
            raise RecoveryError(f"protected person context changed at frame {frame}: {person_context_changed}")

        gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        gray_after = cv2.cvtColor(final, cv2.COLOR_BGR2GRAY)
        bx1, by1, bx2, by2 = legacy.interpolate_bbox(frame, anchors)
        bbox_width = max(1, bx2 - bx1)
        safe_score = (score_masks[frame] > 0).copy()
        safe_score[:, int(bx1 + 0.42 * bbox_width): int(bx1 + 0.78 * bbox_width)] = False
        safe_score_pixels = int(np.count_nonzero(safe_score))
        if safe_score_pixels < 4000:
            raise RecoveryError(f"safe source-glyph score unexpectedly small at frame {frame}")
        before_dark = float(np.mean(gray_before[safe_score] < 140))
        after_dark = float(np.mean(gray_after[safe_score] < 140))

        probe_x1 = max(bx1, bx2 - legacy.RIGHT_GLYPH_PROBE_INSIDE_PIXELS)
        authority_xs = np.where(authority)[1]
        probe_x2 = max(bx2, int(authority_xs.max()) + 1)
        right_probe = np.zeros_like(gray_before, dtype=bool)
        right_probe[by1:by2, probe_x1:probe_x2] = True
        right_source_dark = right_probe & (gray_before < legacy.RIGHT_GLYPH_DARK_THRESHOLD)
        right_source_dark_pixels = int(np.count_nonzero(right_source_dark))
        legacy.require_right_glyph_probe_population(frame, right_source_dark_pixels)
        right_survival = (
            float(np.mean(gray_after[right_source_dark] < legacy.RIGHT_GLYPH_DARK_THRESHOLD))
            if right_source_dark_pixels > 0
            else 0.0
        )
        coverage = coverage_rows[index]
        person_pass = person_pass_rows[index]
        metric_rows.append(
            {
                "timeline_frame": frame,
                "outside_changed_pixels": outside_changed,
                "person_context_changed_pixels": person_context_changed,
                "person_seed_delta_mae": person_pass["person_seed_delta_mae"],
                "person_repair_pixels": person_pass["person_repair_pixels"],
                "source_backed_any_fraction": coverage["source_backed_any_fraction"],
                "source_backed_two_observation_fraction": coverage["source_backed_two_observation_fraction"],
                "model_unresolved_fraction": coverage["model_unresolved_fraction"],
                "safe_glyph_score_pixels": safe_score_pixels,
                "safe_glyph_dark_ratio_lt140_before": before_dark,
                "safe_glyph_dark_ratio_lt140_after": after_dark,
                "safe_glyph_dark_reduction": before_dark - after_dark,
                "right_source_dark_pixels": right_source_dark_pixels,
                "right_source_dark_survival_lt140": right_survival,
                "right_source_dark_removal": 1.0 - right_survival,
                "masked_mae": float(np.mean(delta[authority])) if np.any(authority) else 0.0,
                "final_sha256": legacy.sha256_file(final_path),
            }
        )
        before_small = cv2.resize(before, (432, 768), interpolation=cv2.INTER_AREA)
        after_small = cv2.resize(final, (432, 768), interpolation=cv2.INTER_AREA)
        cv2.putText(before_small, f"BEFORE frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(after_small, f"RECOVERED frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
        video_frames.append(cv2.cvtColor(np.concatenate([before_small, after_small], axis=1), cv2.COLOR_BGR2RGB))

    imageio.mimwrite(
        str(artifact_dir / "COME_BEFORE_AFTER_SOURCE_BACKED_TEMPORAL_V1.mp4"),
        video_frames,
        fps=FPS,
        quality=8,
    )

    pair_rows = []
    for frame in SENTINELS:
        before = base_images[frame]
        after = after_images[frame]
        mask = (score_masks[frame] > 0) | (row_filled_masks[frame] > 0)
        ys, xs = np.where(mask)
        cx1 = max(0, int(xs.min()) - 80)
        cx2 = min(before.shape[1], int(xs.max()) + 81)
        cy1 = max(0, int(ys.min()) - 90)
        cy2 = min(before.shape[0], int(ys.max()) + 91)
        pair_rows.append((f"BEFORE {frame}", before[cy1:cy2, cx1:cx2]))
        pair_rows.append((f"AFTER {frame}", after[cy1:cy2, cx1:cx2]))
    legacy.create_contact_sheet(pair_rows, artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png")

    stabilization_rows = []
    for index, frame in enumerate(SENTINELS):
        source_index = frame - SOURCE_FRAME_START
        image = stabilized_images[source_index].copy()
        known = known_masks[frame] > 0
        score = stabilized_score_masks[source_index] > 0
        overlay = image.copy()
        overlay[score] = (0.55 * overlay[score] + 0.45 * np.asarray([0, 0, 255])).astype(np.uint8)
        overlay[known] = (0.25 * overlay[known] + 0.75 * np.asarray([0, 255, 0])).astype(np.uint8)
        stabilization_rows.append((f"STABILIZED {frame} red=COME green=real donor", overlay))
    legacy.create_contact_sheet(stabilization_rows, artifact_dir / "STABILIZATION_CONTACT_SHEET.png")

    weights = []
    weights_dir = propainter_source / "weights"
    if weights_dir.is_dir():
        for weight in sorted(weights_dir.iterdir()):
            if weight.is_file() and weight.suffix.lower() in {".pth", ".pt"}:
                weights.append(
                    {
                        "name": weight.name,
                        "sha256": legacy.sha256_file(weight),
                        "bytes": weight.stat().st_size,
                    }
                )

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "mode": "offline_source_backed_temporal_recovery_proof_only",
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
        "source_window": [SOURCE_FRAME_START, SOURCE_FRAME_END + 1],
        "frame_count": FRAME_COUNT,
        "reference_frame": REFERENCE_FRAME,
        "iteration_guard": {
            "closed_architecture_family": CLOSED_ARCHITECTURE_FAMILY,
            "closed_reason": "V9 technical PASS received human visual FAIL",
            "current_architecture_family": ARCHITECTURE_FAMILY,
            "reopens_closed_family": False,
            "same_family_visual_retry_allowed": False,
            "on_visual_fail": VISUAL_FAIL_STOP,
        },
        "architecture": {
            "family": ARCHITECTURE_FAMILY,
            "person_recovery": "pairwise_lk_ransac_stabilization_plus_real_temporal_pixel_plate_then_propainter_residual",
            "background_recovery": "second_propainter_pass_after_person_cleanup",
            "same_family_mask_tuning_retry": False,
            "stabilized_crop": list(STABILIZED_CROP),
            "source_backed_known_min_observations": SOURCE_BACKED_KNOWN_MIN_OBSERVATIONS,
            "min_any_source_backed_coverage": SOURCE_BACKED_MIN_ANY_COVERAGE,
            "min_two_observation_source_backed_coverage": SOURCE_BACKED_MIN_TWO_OBSERVATION_COVERAGE,
            "person_repair_dilation_pixels": PERSON_REPAIR_DILATION_PIXELS,
            "person_repair_feather_sigma": PERSON_REPAIR_FEATHER_SIGMA,
            "background_feather_sigma": BACKGROUND_FEATHER_SIGMA,
        },
        "source_authority": {
            "source_video": "input/DZsqH7auhjt.mp4",
            "source_video_sha256": legacy.EXPECTED_SOURCE_VIDEO_SHA256,
            "source_video_fps": legacy.EXPECTED_SOURCE_VIDEO_FPS,
            "source_visible_range": [
                source_context["first_visible_source_frame"],
                source_context["last_visible_source_frame"],
            ],
            "foreground_manifest_sha256": foreground_manifest_sha256,
        },
        "alignment_rows": alignment_rows,
        "coverage_rows": coverage_rows,
        "input_frames": input_rows,
        "person_pass_rows": person_pass_rows,
        "frame_metrics": metric_rows,
        "weights": weights,
        "artifacts": {
            "comparison_video": "COME_BEFORE_AFTER_SOURCE_BACKED_TEMPORAL_V1.mp4",
            "before_after_contact_sheet": "BEFORE_AFTER_CONTACT_SHEET.png",
            "stabilization_contact_sheet": "STABILIZATION_CONTACT_SHEET.png",
            "source_backed_person_plate": "STABILIZED_SOURCE_BACKED_PERSON_PLATE.png",
            "person_log": "PROPAINTER_PERSON_RUN.log",
            "background_log": "PROPAINTER_BACKGROUND_RUN.log",
            "final_frames": "inpainted_frames",
        },
        "visual_approval_required": True,
    }
    (artifact_dir / "PROOF_RUN_RESULT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
