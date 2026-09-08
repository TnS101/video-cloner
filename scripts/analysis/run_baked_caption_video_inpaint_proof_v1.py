from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_VIDEO_INPAINT_PROOF_V9"
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
FRAME_COUNT = SOURCE_FRAME_END - SOURCE_FRAME_START + 1
CONTEXT_SOURCE_FRAME_COUNT = 0
INFERENCE_FRAME_COUNT = FRAME_COUNT
PROCESS_WIDTH = 540
PROCESS_HEIGHT = 960
FPS = 24
MASK_PRE_DILATION = 6
PROPAINTER_MASK_DILATION = 2
COMPACT_HULL_MIN_COMPONENT_AREA = 50
COMPACT_HULL_CLOSE_WIDTH = 9
COMPACT_HULL_CLOSE_HEIGHT = 5
COMPACT_HULL_DILATION = 2
COMPACT_INFERENCE_DILATION = 6
COMPACT_VERTICAL_MARGIN = 3
RIGHT_EXTENSION_MIN_COMPONENT_AREA = 18
RIGHT_EXTENSION_MIN_COMPONENT_WIDTH = 3
LEGACY_SOLID_REFERENCE_MIN_RIGHT_GUARD_PIXELS = 56
MAX_COMPOSITE_RIGHT_GLYPH_GUARD_PIXELS = 180
RIGHT_GLYPH_PROBE_INSIDE_PIXELS = 80
RIGHT_GLYPH_DARK_THRESHOLD = 140
RIGHT_GLYPH_DISCOVERY_THRESHOLD = 185
MAX_COMPACT_VS_LEGACY_SOLID_RATIO = 0.90
MIN_SCORE_MASK_COVERAGE = 0.84
MIN_INFERENCE_BRIDGE_ADDED_PIXELS = 2000
MIN_INFERENCE_BRIDGE_ROWS = 80
INPAINT_MASK_STRATEGY = "row_filled_background_plus_source_glyph_person_repair_v1"
COMPOSITE_MASK_STRATEGY = "semantic_split_person_repair_tail_feather_v1"
GLYPH_SCORE_MASK_STRATEGY = "transformed_v3_glyph_clipped_to_source_bbox_v1"
TEMPORAL_CONTEXT_STRATEGY = "target_only_no_clean_same_shot_context_v1"
FOREGROUND_PERSON_AUTHORITY_STRATEGY = "accepted_v4_person_masks_canonical_humanseg_plus_global_affine_v1"
PERSON_REPAIR_DILATION_PIXELS = 3
PERSON_REPAIR_FEATHER_SIGMA = 1.5
MAX_PERSON_REPAIR_AUTHORITY_RATIO = 0.05
MIN_PERSON_GLYPH_SEED_PIXELS = 4000
TAIL_BACKGROUND_START_FRAME = 451
TAIL_BACKGROUND_CLOSE_WIDTH = 81
TAIL_BACKGROUND_CLOSE_HEIGHT = 7
TAIL_BACKGROUND_DILATION_PIXELS = 4
TAIL_BACKGROUND_FEATHER_SIGMA = 3.0
COMPOSITE_ALPHA_MIN = 8
SOURCE_TRACK_REL = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json")
LIFECYCLE_REL = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json")
EXPECTED_SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
EXPECTED_SOURCE_VIDEO_FPS = 30.0
EXPECTED_SOURCE_VIDEO_FRAME_COUNT = 1206
EXPECTED_SOURCE_VIDEO_SIZE = (1080, 1920)
EXPECTED_COME_SOURCE_VISIBLE_RANGE = (537, 564)
V2_FAILED_RUN_REL = Path(
    ".agent/reports/DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_COME_ONLY_V2/"
    "20260814T103405587845Z_f95e3445b2e34b888c3a0ab6b67c466a"
)
V3_GEOMETRY_RUN_REL = Path(
    ".agent/reports/DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3/"
    "20260812T160055844261Z_f292f909ae7d40358098157428affd43"
)
STYLE_REL = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_style.json")
EXPECTED_STYLE_ANCHORS = {
    429: [264, 661, 687, 775],
    445: [334, 660, 746, 764],
    448: [339, 662, 758, 768],
}
SENTINELS = [429, 431, 434, 438, 443, 448, 452]
HOLD_SENTINELS = frozenset({434, 438, 443, 448})
RIGHT_GLYPH_MIN_SOURCE_DARK_PIXELS = 3000


class ProofError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def resolve_repo_root(value: str | None) -> Path:
    root = Path(value).resolve() if value else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        raise ProofError(f"repository root not found: {root}")
    return root


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_come_lifecycle(lifecycle_payload: dict) -> dict:
    layers = lifecycle_payload.get("layers")
    if not isinstance(layers, list):
        raise ProofError("caption lifecycle authority has no layers list")
    for row in layers:
        if isinstance(row, dict) and row.get("cue_id") == "sub_052" and str(row.get("text", "")).upper() == "COME":
            return row
    raise ProofError("sub_052 / COME lifecycle authority is missing")


def verify_source_context_authority(track_payload: dict, lifecycle_payload: dict, repo_root: Path) -> dict:
    source_video = repo_root / "input" / "DZsqH7auhjt.mp4"
    source_info = track_payload.get("source_video_info") or {}
    if track_payload.get("source_video_sha256") != EXPECTED_SOURCE_VIDEO_SHA256:
        raise ProofError("source video SHA authority changed")
    if float(source_info.get("fps", 0.0)) != EXPECTED_SOURCE_VIDEO_FPS:
        raise ProofError(f"unexpected source video fps authority: {source_info.get('fps')}")
    if int(source_info.get("frame_count", 0)) != EXPECTED_SOURCE_VIDEO_FRAME_COUNT:
        raise ProofError(f"unexpected source video frame count authority: {source_info.get('frame_count')}")
    if (int(source_info.get("width", 0)), int(source_info.get("height", 0))) != EXPECTED_SOURCE_VIDEO_SIZE:
        raise ProofError(f"unexpected source video size authority: {source_info}")
    if source_info.get("is_proxy") is not False:
        raise ProofError("source video authority unexpectedly references a proxy")
    if not source_video.is_file():
        raise ProofError(f"source video is missing: {source_video}")
    if sha256_file(source_video) != EXPECTED_SOURCE_VIDEO_SHA256:
        raise ProofError("source video bytes do not match canonical SHA-256 authority")

    lifecycle = find_come_lifecycle(lifecycle_payload)
    tracking = ((lifecycle.get("targeted_redetection") or {}).get("tracking") or {})
    first_visible = int(tracking.get("first_visible_source_frame", -1))
    last_visible = int(tracking.get("last_visible_source_frame", -1))
    if (first_visible, last_visible) != EXPECTED_COME_SOURCE_VISIBLE_RANGE:
        raise ProofError(
            f"COME native-source visible range changed: expected {EXPECTED_COME_SOURCE_VISIBLE_RANGE}, "
            f"got {(first_visible, last_visible)}"
        )
    return {
        "source_video": source_video,
        "first_visible_source_frame": first_visible,
        "last_visible_source_frame": last_visible,
        "pre_context_source_frames": [],
        "post_context_source_frames": [],
    }


def extract_native_source_frames(source_video: Path, frame_indices: list[int]) -> dict[int, object]:
    import cv2

    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        raise ProofError(f"could not open canonical source video: {source_video}")
    frames: dict[int, object] = {}
    try:
        for frame_index in frame_indices:
            if frame_index < 0:
                raise ProofError(f"negative source frame index: {frame_index}")
            if not cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_index)):
                raise ProofError(f"could not seek canonical source video to frame {frame_index}")
            ok, frame = cap.read()
            if not ok or frame is None:
                raise ProofError(f"could not decode canonical source frame {frame_index}")
            if frame.shape[:2] != (EXPECTED_SOURCE_VIDEO_SIZE[1], EXPECTED_SOURCE_VIDEO_SIZE[0]):
                raise ProofError(f"unexpected canonical source frame dimensions at {frame_index}: {frame.shape}")
            frames[frame_index] = frame
    finally:
        cap.release()
    return frames


def transform_glyph_mask_raw(mask, target_bbox: tuple[int, int, int, int]):
    import cv2
    import numpy as np

    binary = (mask > 0).astype(np.uint8) * 255
    ys, xs = np.where(binary > 0)
    if xs.size == 0:
        raise ProofError("empty glyph mask")
    sx1, sy1, sx2, sy2 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    tx1, ty1, tx2, ty2 = target_bbox
    if tx2 <= tx1 or ty2 <= ty1:
        raise ProofError(f"invalid target bbox: {target_bbox}")
    scale_x = (tx2 - tx1) / float(sx2 - sx1)
    scale_y = (ty2 - ty1) / float(sy2 - sy1)
    matrix = np.asarray(
        [[scale_x, 0.0, tx1 - scale_x * sx1], [0.0, scale_y, ty1 - scale_y * sy1]],
        dtype=np.float32,
    )
    return cv2.warpAffine(
        binary,
        matrix,
        (binary.shape[1], binary.shape[0]),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def fill_component_hulls(mask):
    import cv2
    import numpy as np

    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    filled = np.zeros_like(mask, dtype=np.uint8)
    kept = 0
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < COMPACT_HULL_MIN_COMPONENT_AREA:
            continue
        ys, xs = np.where(labels == label)
        hull = cv2.convexHull(np.stack([xs, ys], axis=1).astype(np.int32))
        cv2.fillConvexPoly(filled, hull, 255)
        kept += 1
    if kept == 0:
        raise ProofError("no glyph components survived compact hull filtering")
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (COMPACT_HULL_CLOSE_WIDTH, COMPACT_HULL_CLOSE_HEIGHT),
    )
    filled = cv2.morphologyEx(filled, cv2.MORPH_CLOSE, close_kernel)
    dilate_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (2 * COMPACT_HULL_DILATION + 1, 2 * COMPACT_HULL_DILATION + 1),
    )
    return cv2.dilate(filled, dilate_kernel), kept


def build_source_dark_right_extension_mask(
    image,
    target_bbox: tuple[int, int, int, int],
):
    import cv2
    import numpy as np

    x1, y1, x2, y2 = target_bbox
    height, width = image.shape[:2]
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ProofError(f"invalid source bbox for compact right extension: {target_bbox}")
    search_x2 = min(width, x2 + MAX_COMPOSITE_RIGHT_GLYPH_GUARD_PIXELS)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    roi = (gray[y1:y2, x2:search_x2] < RIGHT_GLYPH_DISCOVERY_THRESHOLD).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(roi, connectivity=8)
    extension = np.zeros_like(gray, dtype=np.uint8)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        component_width = int(stats[label, cv2.CC_STAT_WIDTH])
        if area < RIGHT_EXTENSION_MIN_COMPONENT_AREA or component_width < RIGHT_EXTENSION_MIN_COMPONENT_WIDTH:
            continue
        ys, xs = np.where(labels == label)
        points = np.stack([xs + x2, ys + y1], axis=1).astype(np.int32)
        hull = cv2.convexHull(points)
        cv2.fillConvexPoly(extension, hull, 255)
    if np.any(extension):
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (2 * COMPACT_HULL_DILATION + 1, 2 * COMPACT_HULL_DILATION + 1),
        )
        extension = cv2.dilate(extension, kernel)
        extension[:, search_x2:] = 0
    return extension


def build_row_filled_inference_seed(composite_mask):
    import numpy as np

    source = composite_mask > 0
    row_filled = np.zeros_like(composite_mask, dtype=np.uint8)
    active_rows = 0
    for y in np.where(np.any(source, axis=1))[0]:
        xs = np.where(source[y])[0]
        if xs.size == 0:
            continue
        row_filled[y, int(xs.min()): int(xs.max()) + 1] = 255
        active_rows += 1
    if active_rows == 0:
        raise ProofError("row-filled inference seed is empty")
    if not np.all((composite_mask == 0) | (row_filled > 0)):
        raise ProofError("row-filled inference seed does not contain compact composite authority")
    added_pixels = int(np.count_nonzero((row_filled > 0) & ~source))
    return row_filled, added_pixels, active_rows


def build_compact_caption_masks(
    image,
    glyph,
    target_bbox: tuple[int, int, int, int],
):
    import cv2
    import numpy as np

    raw = clip_mask_to_bbox(transform_glyph_mask_raw(glyph, target_bbox), target_bbox)
    hull_mask, component_count = fill_component_hulls(raw)
    right_extension = build_source_dark_right_extension_mask(image, target_bbox)
    composite = cv2.max(hull_mask, right_extension)

    x1, y1, x2, y2 = target_bbox
    clamped = np.zeros_like(composite, dtype=np.uint8)
    cy1 = max(0, y1 - COMPACT_VERTICAL_MARGIN)
    cy2 = min(composite.shape[0], y2 + COMPACT_VERTICAL_MARGIN)
    clamped[cy1:cy2, :] = composite[cy1:cy2, :]
    composite = clamped

    ys, xs = np.where(composite > 0)
    if xs.size == 0:
        raise ProofError("compact caption mask is empty")
    dynamic_right_guard_pixels = max(0, int(xs.max()) + 1 - x2)
    if dynamic_right_guard_pixels > MAX_COMPOSITE_RIGHT_GLYPH_GUARD_PIXELS:
        raise ProofError(f"compact right extension escaped bound: {dynamic_right_guard_pixels}")

    # V5 proved that compact letter-shaped inference topology can preserve/recreate
    # dark C/O/M/E structure even when most source-backed glyph pixels are masked.
    # Break that conditioning only for inference by horizontally bridging every
    # active caption row. Keep the final composite authority compact and unchanged.
    inference_seed, inference_bridge_added_pixels, inference_bridge_rows = build_row_filled_inference_seed(composite)
    inference_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (2 * COMPACT_INFERENCE_DILATION + 1, 2 * COMPACT_INFERENCE_DILATION + 1),
    )
    inpaint = cv2.dilate(inference_seed, inference_kernel)

    legacy_right_guard = max(
        LEGACY_SOLID_REFERENCE_MIN_RIGHT_GUARD_PIXELS,
        dynamic_right_guard_pixels,
    )
    legacy_right = min(image.shape[1], x2 + legacy_right_guard)
    legacy_solid_pixels = (legacy_right - x1) * (y2 - y1)
    composite_pixels = int(np.count_nonzero(composite))
    compact_ratio = composite_pixels / float(legacy_solid_pixels)
    return {
        "composite_mask": composite,
        "inpaint_mask": inpaint,
        "dynamic_right_guard_pixels": dynamic_right_guard_pixels,
        "legacy_solid_reference_pixels": legacy_solid_pixels,
        "compact_vs_legacy_solid_ratio": compact_ratio,
        "component_count": component_count,
        "inference_seed_pixels": int(np.count_nonzero(inference_seed)),
        "inference_bridge_added_pixels": inference_bridge_added_pixels,
        "inference_bridge_rows": inference_bridge_rows,
    }


def load_v4_foreground_authority(authority_dir: Path, expected_frames: list[int] | None = None) -> dict[int, Path]:
    expected = expected_frames or list(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1))
    manifest_path = authority_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ProofError(f"missing V4 foreground authority manifest: {manifest_path}")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("ok") is not True:
        raise ProofError("V4 foreground authority manifest is not PASS evidence")
    if manifest.get("task_id") != "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3":
        raise ProofError("unexpected V4 foreground authority task id")
    if manifest.get("timeline_range_half_open") != [426, 454]:
        raise ProofError("unexpected V4 foreground authority timeline range")
    if manifest.get("person_authority") != "canonical_humanseg_anchors_plus_global_affine_only":
        raise ProofError("unexpected V4 foreground person authority")
    if manifest.get("source_video_sha256") != EXPECTED_SOURCE_VIDEO_SHA256:
        raise ProofError("V4 foreground authority source SHA changed")
    rows = manifest.get("frames")
    if not isinstance(rows, list):
        raise ProofError("V4 foreground authority frame rows are missing")
    by_frame = {
        int(row["timeline_frame"]): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("timeline_frame"), int)
    }
    result: dict[int, Path] = {}
    for frame in expected:
        row = by_frame.get(frame)
        if not isinstance(row, dict):
            raise ProofError(f"V4 foreground authority missing frame {frame}")
        rel = row.get("person_mask")
        person = row.get("person") or {}
        expected_hash = person.get("person_mask_sha256")
        if not isinstance(rel, str) or not isinstance(expected_hash, str):
            raise ProofError(f"V4 foreground authority metadata incomplete at frame {frame}")
        path = authority_dir / Path(rel)
        if not path.is_file():
            raise ProofError(f"V4 foreground person mask missing at frame {frame}: {path}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ProofError(
                f"V4 foreground person mask hash mismatch at frame {frame}: expected {expected_hash}, got {actual_hash}"
            )
        result[frame] = path
    return result


def load_full_resolution_person_mask(path: Path, target_shape: tuple[int, int]):
    import cv2
    import numpy as np

    source = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if source is None:
        raise ProofError(f"could not read V4 foreground person mask: {path}")
    if source.shape != (540, 304):
        raise ProofError(f"unexpected V4 foreground person-mask dimensions: {source.shape}")
    height, width = int(target_shape[0]), int(target_shape[1])
    resized = cv2.resize(source, (width, height), interpolation=cv2.INTER_NEAREST)
    binary = (resized > 0).astype(np.uint8) * 255
    pixels = int(np.count_nonzero(binary))
    if pixels < 150000:
        raise ProofError(f"V4 foreground person mask unexpectedly small after resize: {pixels}")
    return binary


def build_semantic_split_inference_mask(
    frame: int,
    row_filled_mask,
    score_mask,
    person_mask,
):
    import cv2
    import numpy as np

    row_filled = row_filled_mask > 0
    score = score_mask > 0
    person = person_mask > 0
    if row_filled.shape != score.shape or row_filled.shape != person.shape:
        raise ProofError(f"V9 semantic-split inference shape mismatch at frame {frame}")

    person_glyph_seed = score & person
    seed_pixels = int(np.count_nonzero(person_glyph_seed))
    if seed_pixels < MIN_PERSON_GLYPH_SEED_PIXELS:
        raise ProofError(f"V9 person/glyph source seed unexpectedly small at frame {frame}: {seed_pixels}")

    repair_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (2 * PERSON_REPAIR_DILATION_PIXELS + 1, 2 * PERSON_REPAIR_DILATION_PIXELS + 1),
    )
    person_repair = cv2.dilate(person_glyph_seed.astype(np.uint8) * 255, repair_kernel) > 0
    person_repair &= person

    person_pixels = int(np.count_nonzero(person))
    repair_pixels = int(np.count_nonzero(person_repair))
    repair_ratio = repair_pixels / float(person_pixels) if person_pixels else 0.0
    if repair_ratio <= 0.0 or repair_ratio > MAX_PERSON_REPAIR_AUTHORITY_RATIO:
        raise ProofError(f"V9 person inference repair escaped bound at frame {frame}: {repair_ratio:.6f}")

    background_rowfill = row_filled & ~person
    hybrid = background_rowfill | person_repair
    if np.any(hybrid & person & ~person_repair):
        raise ProofError(f"V9 inference mask escaped bounded person repair at frame {frame}")
    if not np.all(~person_glyph_seed | hybrid):
        raise ProofError(f"V9 source-backed person/glyph pixels escaped inference repair at frame {frame}")

    return {
        "inpaint_mask": hybrid.astype(np.uint8) * 255,
        "person_glyph_seed": person_glyph_seed.astype(np.uint8) * 255,
        "person_repair_mask": person_repair.astype(np.uint8) * 255,
        "pre_split_row_filled_mask_pixels": int(np.count_nonzero(row_filled)),
        "background_rowfill_pixels": int(np.count_nonzero(background_rowfill)),
        "person_glyph_seed_pixels": seed_pixels,
        "person_repair_inference_pixels": repair_pixels,
        "person_repair_inference_ratio": repair_ratio,
        "person_mask_pixels": person_pixels,
    }


def build_semantic_split_composite_alpha(
    frame: int,
    inpaint_mask,
    compact_source_mask,
    person_mask,
    person_glyph_seed,
    person_repair_mask,
):
    import cv2
    import numpy as np

    inpaint = inpaint_mask > 0
    compact = compact_source_mask > 0
    person = person_mask > 0
    person_seed = person_glyph_seed > 0
    person_repair = person_repair_mask > 0
    if not (inpaint.shape == compact.shape == person.shape == person_seed.shape == person_repair.shape):
        raise ProofError(f"V9 semantic-split composite shape mismatch at frame {frame}")
    if np.any(inpaint & person & ~person_repair):
        raise ProofError(f"V9 inference repaints person outside source-glyph repair at frame {frame}")
    if not np.all(~person_seed | person_repair):
        raise ProofError(f"V9 person/glyph seed escaped bounded repair at frame {frame}")

    if frame < TAIL_BACKGROUND_START_FRAME:
        background_mode = "row_filled_background_plus_person_glyph_repair"
        background_alpha = (inpaint & ~person).astype(np.float32) * 255.0
    else:
        background_mode = "tail_closed_background_plus_person_glyph_repair"
        compact_binary = compact.astype(np.uint8) * 255
        close_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (TAIL_BACKGROUND_CLOSE_WIDTH, TAIL_BACKGROUND_CLOSE_HEIGHT),
        )
        background_core = cv2.morphologyEx(compact_binary, cv2.MORPH_CLOSE, close_kernel)
        tail_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (2 * TAIL_BACKGROUND_DILATION_PIXELS + 1, 2 * TAIL_BACKGROUND_DILATION_PIXELS + 1),
        )
        background_core = cv2.dilate(background_core, tail_kernel)
        background_alpha = cv2.GaussianBlur(
            background_core,
            (0, 0),
            TAIL_BACKGROUND_FEATHER_SIGMA,
        ).astype(np.float32)
        background_alpha *= (inpaint & ~person).astype(np.float32)
        background_alpha[(background_core > 0) & inpaint & ~person] = 255.0

    person_seed_u8 = person_seed.astype(np.uint8) * 255
    person_alpha = cv2.GaussianBlur(person_seed_u8, (0, 0), PERSON_REPAIR_FEATHER_SIGMA).astype(np.float32)
    person_alpha *= person_repair.astype(np.float32)
    person_alpha[person_seed] = 255.0

    alpha = np.maximum(background_alpha, person_alpha)
    alpha[~inpaint] = 0.0
    alpha[alpha < float(COMPOSITE_ALPHA_MIN)] = 0.0
    alpha = np.rint(alpha).clip(0, 255).astype(np.uint8)

    seed_full_alpha_pixels = int(np.count_nonzero(person_seed & (alpha == 255)))
    seed_pixels = int(np.count_nonzero(person_seed))
    if seed_full_alpha_pixels != seed_pixels:
        raise ProofError(f"V9 person/glyph source seed is not fully composited at frame {frame}")
    if np.any(person & ~person_repair & (alpha > 0)):
        raise ProofError(f"V9 final alpha escaped bounded person repair at frame {frame}")

    background_compact = compact & ~person
    background_compact_covered = int(np.count_nonzero(background_compact & (alpha > 0)))
    background_compact_pixels = int(np.count_nonzero(background_compact))
    if frame < TAIL_BACKGROUND_START_FRAME and background_compact_covered != background_compact_pixels:
        raise ProofError(f"V9 background compact authority is not fully composited at frame {frame}")

    return {
        "alpha": alpha,
        "background_mode": background_mode,
        "background_compact_pixels": background_compact_pixels,
        "background_compact_covered_pixels": background_compact_covered,
        "person_glyph_seed_full_alpha_pixels": seed_full_alpha_pixels,
    }

def expected_style_event(style_payload: dict) -> dict:
    candidates = []
    for key in ("style_events", "caption_style_events"):
        value = style_payload.get(key)
        if isinstance(value, list):
            candidates.extend(row for row in value if isinstance(row, dict))
    for row in candidates:
        if row.get("event_id") == "style_event_sub_0052" and str(row.get("observed_text", "")).upper() == "COME":
            return row
    raise ProofError("style_event_sub_0052 / COME authority is missing")


def verify_style_anchors(style_payload: dict) -> dict[int, list[int]]:
    event = expected_style_event(style_payload)
    observations = event.get("observations")
    if not isinstance(observations, list):
        raise ProofError("COME style observations are missing")
    anchors: dict[int, list[int]] = {}
    for row in observations:
        if not isinstance(row, dict):
            continue
        timestamp = row.get("timestamp")
        bbox = row.get("bbox")
        if not isinstance(timestamp, (int, float)) or not isinstance(bbox, list) or len(bbox) != 4:
            continue
        timeline_frame = int(round(float(timestamp) * FPS))
        anchors[timeline_frame] = [int(round(float(v))) for v in bbox]
    for frame, expected in EXPECTED_STYLE_ANCHORS.items():
        actual = anchors.get(frame)
        if actual != expected:
            raise ProofError(f"COME source bbox authority mismatch at frame {frame}: expected {expected}, got {actual}")
    return {frame: EXPECTED_STYLE_ANCHORS[frame][:] for frame in sorted(EXPECTED_STYLE_ANCHORS)}


def interpolate_bbox(frame: int, anchors: dict[int, list[int]]) -> tuple[int, int, int, int]:
    import numpy as np

    if frame <= 445:
        a, b = 429, 445
        ratio = (frame - a) / float(b - a)
        value = np.asarray(anchors[a], dtype=np.float64) * (1.0 - ratio) + np.asarray(anchors[b], dtype=np.float64) * ratio
    elif frame <= 448:
        a, b = 445, 448
        ratio = (frame - a) / float(b - a)
        value = np.asarray(anchors[a], dtype=np.float64) * (1.0 - ratio) + np.asarray(anchors[b], dtype=np.float64) * ratio
    else:
        velocity = (np.asarray(anchors[448], dtype=np.float64) - np.asarray(anchors[445], dtype=np.float64)) / 3.0
        value = np.asarray(anchors[448], dtype=np.float64) + velocity * float(frame - 448)
    return tuple(int(round(v)) for v in value)


def transform_glyph_mask(mask, target_bbox: tuple[int, int, int, int]):
    import cv2
    import numpy as np

    binary = (mask > 0).astype(np.uint8) * 255
    ys, xs = np.where(binary > 0)
    if xs.size == 0:
        raise ProofError("empty glyph mask")
    sx1, sy1, sx2, sy2 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    tx1, ty1, tx2, ty2 = target_bbox
    if tx2 <= tx1 or ty2 <= ty1:
        raise ProofError(f"invalid target bbox: {target_bbox}")
    scale_x = (tx2 - tx1) / float(sx2 - sx1)
    scale_y = (ty2 - ty1) / float(sy2 - sy1)
    matrix = np.asarray(
        [[scale_x, 0.0, tx1 - scale_x * sx1], [0.0, scale_y, ty1 - scale_y * sy1]],
        dtype=np.float32,
    )
    warped = cv2.warpAffine(
        binary,
        matrix,
        (binary.shape[1], binary.shape[0]),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    kernel = np.ones((2 * MASK_PRE_DILATION + 1, 2 * MASK_PRE_DILATION + 1), dtype=np.uint8)
    return cv2.dilate((warped > 0).astype(np.uint8) * 255, kernel, iterations=1)


def clip_mask_to_bbox(mask, target_bbox: tuple[int, int, int, int]):
    import numpy as np

    x1, y1, x2, y2 = target_bbox
    clipped = np.zeros_like(mask, dtype=np.uint8)
    clipped[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
    return clipped


def build_solid_bbox_mask(shape: tuple[int, int], target_bbox: tuple[int, int, int, int]):
    import numpy as np

    height, width = int(shape[0]), int(shape[1])
    x1, y1, x2, y2 = target_bbox
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ProofError(f"source bbox escaped frame: {target_bbox} for {(width, height)}")
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[y1:y2, x1:x2] = 255
    return mask


def require_right_glyph_probe_population(frame: int, source_dark_pixels: int) -> None:
    """Require a populated right-glyph probe only on validator hold sentinels.

    Fade/transition frames such as 429 may legitimately contain fewer dark source
    pixels and are not part of the technical right-glyph acceptance gate.
    """
    if frame in HOLD_SENTINELS and source_dark_pixels < RIGHT_GLYPH_MIN_SOURCE_DARK_PIXELS:
        raise ProofError(f"right-side source glyph probe unexpectedly small at hold sentinel {frame}: {source_dark_pixels}")


def run_command(args: list[str], *, cwd: Path, log_path: Path) -> None:
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            [str(value) for value in args],
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        code = proc.wait()
    if code != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
        raise ProofError(f"ProPainter inference failed with code {code}:\n{tail}")


def find_propainter_result_frames(output_root: Path) -> Path:
    candidates = sorted(output_root.glob("*/frames"))
    valid = [path for path in candidates if path.is_dir() and len(list(path.glob("*.png"))) == INFERENCE_FRAME_COUNT]
    if len(valid) != 1:
        raise ProofError(f"expected exactly one ProPainter frame directory with {INFERENCE_FRAME_COUNT} frames, got {valid}")
    return valid[0]


def create_contact_sheet(rows: list[tuple[str, object]], path: Path) -> None:
    import cv2
    import numpy as np

    rendered = []
    for label, image in rows:
        image = image.copy()
        cv2.rectangle(image, (0, 0), (image.shape[1], 54), (0, 0, 0), -1)
        cv2.putText(image, label, (12, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2, cv2.LINE_AA)
        rendered.append(image)
    max_h = max(image.shape[0] for image in rendered)
    max_w = max(image.shape[1] for image in rendered)
    normalized = []
    for image in rendered:
        canvas = np.zeros((max_h, max_w, 3), dtype=np.uint8)
        canvas[: image.shape[0], : image.shape[1]] = image
        normalized.append(canvas)
    sheet = np.concatenate(normalized, axis=1)
    cv2.imwrite(str(path), sheet)


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

    repo_root = resolve_repo_root(args.repo_root)
    artifact_dir = Path(args.artifact_dir).resolve()
    propainter_source = Path(args.propainter_source).resolve()
    foreground_authority_dir = Path(args.foreground_authority_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    failed_run = repo_root / V2_FAILED_RUN_REL
    geometry_run = repo_root / V3_GEOMETRY_RUN_REL
    base_dir = failed_run / "render_base_baked"
    glyph_dir = geometry_run / "generated_pixel_restore_v3" / "glyph_masks"
    style_path = repo_root / STYLE_REL
    source_track_path = repo_root / SOURCE_TRACK_REL
    lifecycle_path = repo_root / LIFECYCLE_REL
    for required in (
        failed_run / "report.json",
        failed_run / "base_render_authority.json",
        geometry_run / "generated_pixel_restore_v3" / "manifest.json",
        style_path,
        source_track_path,
        lifecycle_path,
    ):
        if not required.is_file():
            raise ProofError(f"missing proof authority file: {required}")
    if not (propainter_source / "inference_propainter.py").is_file():
        raise ProofError(f"invalid ProPainter source: {propainter_source}")

    failed_report = load_json(failed_run / "report.json")
    if not isinstance(failed_report, dict):
        raise ProofError("unexpected COME-only V2 failed-run report payload")
    if failed_report.get("task_id") != "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_COME_ONLY_V2":
        raise ProofError("unexpected COME-only V2 failed-run task id")
    if failed_report.get("ok") is not False or failed_report.get("failed_target_retained") is not False:
        raise ProofError("COME-only V2 evidence is not the expected clean failed run")
    v3_manifest = load_json(geometry_run / "generated_pixel_restore_v3" / "manifest.json")
    if not isinstance(v3_manifest, dict) or v3_manifest.get("ok") is not True:
        raise ProofError("V3 glyph geometry manifest is not PASS evidence")
    if v3_manifest.get("task_id") != "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3":
        raise ProofError("unexpected V3 glyph geometry task id")
    if v3_manifest.get("timeline_range_half_open") != [426, 454]:
        raise ProofError("unexpected V3 glyph geometry timeline range")
    v3_rows = v3_manifest.get("frames")
    if not isinstance(v3_rows, list):
        raise ProofError("V3 glyph geometry frame rows are missing")
    v3_by_frame = {
        int(row["timeline_frame"]): row
        for row in v3_rows
        if isinstance(row, dict) and isinstance(row.get("timeline_frame"), int)
    }
    base_authority = load_json(failed_run / "base_render_authority.json")
    if not isinstance(base_authority, dict) or base_authority.get("ok") is not True:
        raise ProofError("base render authority is not PASS")
    dimensions = base_authority.get("dimensions") or {}
    if dimensions != {"frame_rate": 24.0, "height": 1920, "width": 1080}:
        raise ProofError(f"unexpected base render dimensions: {dimensions}")

    anchors = verify_style_anchors(load_json(style_path))
    source_context = verify_source_context_authority(
        load_json(source_track_path),
        load_json(lifecycle_path),
        repo_root,
    )

    foreground_authority_paths = load_v4_foreground_authority(foreground_authority_dir)
    foreground_manifest_sha256 = sha256_file(foreground_authority_dir / "manifest.json")

    inputs_dir = artifact_dir / "input_frames"
    masks_dir = artifact_dir / "masks"
    final_dir = artifact_dir / "inpainted_frames"
    propainter_output = artifact_dir / "propainter_output"
    for directory in (inputs_dir, masks_dir, final_dir, propainter_output):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    frame_rows = []
    context_rows = []
    inpaint_masks: dict[int, object] = {}
    compact_source_masks: dict[int, object] = {}
    composite_masks: dict[int, object] = {}
    composite_alphas: dict[int, object] = {}
    person_masks: dict[int, object] = {}
    composite_authority_rows: dict[int, dict[str, object]] = {}
    score_masks: dict[int, object] = {}
    base_images: dict[int, object] = {}

    # The native-source audit found no clean same-shot reference frame:
    # 500-503 are a different pose/shot with baked text, 504-531 are another shot,
    # 532 is a transition, 533 already contains "use", 534-536 contain COME, and
    # 565+ is after the cut. Do not poison inference with those frames. Instead,
    # keep target-only temporal ordering and minimize unknown pixels using filled
    # per-component glyph hulls plus a bounded source-dark right extension.
    for target_index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        index = target_index
        base_path = base_dir / f"base_baked_{frame:08d}.png"
        glyph_path = glyph_dir / f"glyph_{frame:06d}.png"
        if not base_path.is_file() or not glyph_path.is_file():
            raise ProofError(f"missing proof frame authority at timeline frame {frame}")
        v3_row = v3_by_frame.get(frame)
        if not isinstance(v3_row, dict):
            raise ProofError(f"V3 manifest has no glyph authority row for frame {frame}")
        expected_glyph_rel = f"glyph_masks/glyph_{frame:06d}.png"
        if v3_row.get("glyph_mask") != expected_glyph_rel:
            raise ProofError(f"V3 glyph path mismatch at frame {frame}")
        expected_glyph_sha = v3_row.get("glyph_mask_sha256")
        if not isinstance(expected_glyph_sha, str) or sha256_file(glyph_path) != expected_glyph_sha:
            raise ProofError(f"V3 glyph hash mismatch at frame {frame}")
        image = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
        glyph = cv2.imread(str(glyph_path), cv2.IMREAD_GRAYSCALE)
        if image is None or glyph is None or image.shape[:2] != (1920, 1080) or glyph.shape != (1920, 1080):
            raise ProofError(f"invalid proof input at timeline frame {frame}")
        target_bbox = interpolate_bbox(frame, anchors)
        score_mask = clip_mask_to_bbox(transform_glyph_mask(glyph, target_bbox), target_bbox)
        compact = build_compact_caption_masks(image, glyph, target_bbox)
        row_filled_mask = compact["inpaint_mask"]
        compact_source_mask = compact["composite_mask"]
        person_mask = load_full_resolution_person_mask(
            foreground_authority_paths[frame],
            image.shape[:2],
        )
        inference_authority = build_semantic_split_inference_mask(
            frame,
            row_filled_mask,
            score_mask,
            person_mask,
        )
        inpaint_mask = inference_authority["inpaint_mask"]
        person_glyph_seed = inference_authority["person_glyph_seed"]
        person_repair_mask = inference_authority["person_repair_mask"]
        composite_authority = build_semantic_split_composite_alpha(
            frame,
            inpaint_mask,
            compact_source_mask,
            person_mask,
            person_glyph_seed,
            person_repair_mask,
        )
        composite_alpha = composite_authority["alpha"]
        composite_mask = (composite_alpha > 0).astype(np.uint8) * 255
        dynamic_guard_pixels = int(compact["dynamic_right_guard_pixels"])
        compact_ratio = float(compact["compact_vs_legacy_solid_ratio"])
        legacy_solid_reference_pixels = int(compact["legacy_solid_reference_pixels"])
        component_count = int(compact["component_count"])
        inference_seed_pixels = int(compact["inference_seed_pixels"])
        inference_bridge_added_pixels = int(compact["inference_bridge_added_pixels"])
        inference_bridge_rows = int(compact["inference_bridge_rows"])
        if int(np.count_nonzero(score_mask)) < 15000:
            raise ProofError(f"transformed COME score mask unexpectedly small at frame {frame}")
        if int(np.count_nonzero(compact_source_mask)) < 25000:
            raise ProofError(f"compact source mask unexpectedly small at frame {frame}")
        background_compact = (compact_source_mask > 0) & ~(person_mask > 0)
        if frame < TAIL_BACKGROUND_START_FRAME and not np.all(~background_compact | (inpaint_mask > 0)):
            raise ProofError(f"V9 background compact authority escaped semantic-split inference at frame {frame}")
        if not np.all((person_glyph_seed == 0) | (inpaint_mask > 0)):
            raise ProofError(f"V9 person/glyph seed escaped semantic-split inference at frame {frame}")
        if not np.all((person_glyph_seed == 0) | (composite_alpha == 255)):
            raise ProofError(f"V9 person/glyph seed is not fully replaced at frame {frame}")
        if not np.all((composite_mask == 0) | (inpaint_mask > 0)):
            raise ProofError(f"V9 final authority escaped semantic-split inference at frame {frame}")
        if np.any((person_mask > 0) & (person_repair_mask == 0) & (inpaint_mask > 0)):
            raise ProofError(f"V9 inference repaints protected person context at frame {frame}")
        if np.any((person_mask > 0) & (person_repair_mask == 0) & (composite_alpha > 0)):
            raise ProofError(f"V9 final alpha repaints protected person context at frame {frame}")
        if inference_bridge_added_pixels < MIN_INFERENCE_BRIDGE_ADDED_PIXELS:
            raise ProofError(
                f"row-filled inference topology did not add enough non-glyph background context at frame {frame}: "
                f"{inference_bridge_added_pixels}"
            )
        if inference_bridge_rows < MIN_INFERENCE_BRIDGE_ROWS:
            raise ProofError(f"row-filled inference topology is too sparse at frame {frame}: {inference_bridge_rows} rows")
        if compact_ratio > MAX_COMPACT_VS_LEGACY_SOLID_RATIO:
            raise ProofError(
                f"compact mask is not meaningfully smaller than legacy solid authority at frame {frame}: {compact_ratio:.6f}"
            )
        x1, y1, x2, y2 = target_bbox
        ys, xs = np.where(score_mask > 0)
        if xs.min() < x1 or xs.max() >= x2 or ys.min() < y1 or ys.max() >= y2:
            raise ProofError(f"COME score mask escaped source bbox at frame {frame}")
        score_core = score_mask > 0
        score_coverage = float(np.count_nonzero(score_core & (compact_source_mask > 0))) / float(np.count_nonzero(score_core))
        if score_coverage < MIN_SCORE_MASK_COVERAGE:
            raise ProofError(f"compact mask under-covered source-backed COME score pixels at frame {frame}: {score_coverage:.6f}")
        sequential = f"{index:04d}.png"
        shutil.copy2(base_path, inputs_dir / sequential)
        if not cv2.imwrite(str(masks_dir / sequential), inpaint_mask):
            raise ProofError(f"failed to write proof mask at frame {frame}")
        inpaint_masks[frame] = inpaint_mask
        compact_source_masks[frame] = compact_source_mask
        composite_masks[frame] = composite_mask
        composite_alphas[frame] = composite_alpha
        person_masks[frame] = person_mask
        composite_authority_rows[frame] = {
            **composite_authority,
            **inference_authority,
        }
        score_masks[frame] = score_mask
        base_images[frame] = image
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        score_core = score_mask > 0
        frame_rows.append(
            {
                "timeline_frame": frame,
                "sequence_index": index,
                "base_file": str(base_path.relative_to(repo_root)).replace("\\", "/"),
                "base_sha256": sha256_file(base_path),
                "glyph_file": str(glyph_path.relative_to(repo_root)).replace("\\", "/"),
                "glyph_sha256": sha256_file(glyph_path),
                "source_bbox": list(target_bbox),
                "dynamic_right_guard_pixels": dynamic_guard_pixels,
                "pre_split_row_filled_mask_pixels": inference_authority["pre_split_row_filled_mask_pixels"],
                "background_rowfill_pixels": inference_authority["background_rowfill_pixels"],
                "inpaint_mask_pixels": int(np.count_nonzero(inpaint_mask)),
                "compact_source_mask_pixels": int(np.count_nonzero(compact_source_mask)),
                "composite_mask_pixels": int(np.count_nonzero(composite_mask)),
                "composite_alpha_sum": int(np.sum(composite_alpha, dtype=np.int64)),
                "foreground_background_mode": composite_authority["background_mode"],
                "person_mask_pixels": inference_authority["person_mask_pixels"],
                "person_glyph_seed_pixels": inference_authority["person_glyph_seed_pixels"],
                "person_repair_inference_pixels": inference_authority["person_repair_inference_pixels"],
                "person_repair_inference_ratio": inference_authority["person_repair_inference_ratio"],
                "person_glyph_seed_full_alpha_pixels": composite_authority["person_glyph_seed_full_alpha_pixels"],
                "background_compact_pixels": composite_authority["background_compact_pixels"],
                "background_compact_covered_pixels": composite_authority["background_compact_covered_pixels"],
                "legacy_solid_reference_pixels": legacy_solid_reference_pixels,
                "compact_vs_legacy_solid_ratio": compact_ratio,
                "filled_component_count": component_count,
                "inference_seed_pixels": inference_seed_pixels,
                "inference_bridge_added_pixels": inference_bridge_added_pixels,
                "inference_bridge_rows": inference_bridge_rows,
                "score_mask_pixels": int(np.count_nonzero(score_core)),
                "score_mask_coverage": score_coverage,
                "score_mask_dark_ratio_lt140_before": float(np.mean(gray[score_core] < 140)),
            }
        )

    if len(list(inputs_dir.glob("*.png"))) != INFERENCE_FRAME_COUNT:
        raise ProofError("target-only inference input frame count mismatch")
    if len(list(masks_dir.glob("*.png"))) != INFERENCE_FRAME_COUNT:
        raise ProofError("target-only inference mask count mismatch")

    # Mask contact sheet: translucent red = V9 semantic-split ProPainter inference authority;
    # blue = final composite authority; yellow = accepted V4 person matte; magenta = the
    # only person pixels ProPainter may infer; green = source-backed transformed V3 glyph score.
    contact_rows = []
    for frame in SENTINELS:
        image = base_images[frame]
        inpaint = inpaint_masks[frame] > 0
        compact_source = compact_source_masks[frame] > 0
        composite = composite_masks[frame] > 0
        person = person_masks[frame] > 0
        score = score_masks[frame] > 0
        person_repair = composite_authority_rows[frame]["person_repair_mask"] > 0
        ys, xs = np.where(inpaint)
        x1, x2 = max(0, int(xs.min()) - 70), min(image.shape[1], int(xs.max()) + 71)
        y1, y2 = max(0, int(ys.min()) - 80), min(image.shape[0], int(ys.max()) + 81)
        crop = image[y1:y2, x1:x2].copy()
        inpaint_crop = inpaint[y1:y2, x1:x2]
        compact_source_crop = compact_source[y1:y2, x1:x2]
        composite_crop = composite[y1:y2, x1:x2]
        person_crop = person[y1:y2, x1:x2]
        score_crop = score[y1:y2, x1:x2]
        person_repair_crop = person_repair[y1:y2, x1:x2]
        overlay = crop.copy()
        overlay[inpaint_crop] = (0.78 * overlay[inpaint_crop] + 0.22 * np.asarray([0, 0, 255])).astype(np.uint8)
        overlay[person_crop] = (0.84 * overlay[person_crop] + 0.16 * np.asarray([0, 255, 255])).astype(np.uint8)
        overlay[person_repair_crop] = (0.42 * overlay[person_repair_crop] + 0.58 * np.asarray([255, 0, 255])).astype(np.uint8)
        overlay[composite_crop] = (0.72 * overlay[composite_crop] + 0.28 * np.asarray([255, 0, 0])).astype(np.uint8)
        overlay[score_crop] = (0.35 * overlay[score_crop] + 0.65 * np.asarray([0, 255, 0])).astype(np.uint8)
        contact_rows.append((f"frame {frame} V9 semantic split / final / person / repair / glyph", overlay))
    create_contact_sheet(contact_rows, artifact_dir / "MASK_CONTACT_SHEET.png")

    command = [
        sys.executable,
        str(propainter_source / "inference_propainter.py"),
        "--video",
        str(inputs_dir),
        "--mask",
        str(masks_dir),
        "--output",
        str(propainter_output),
        "--width",
        str(PROCESS_WIDTH),
        "--height",
        str(PROCESS_HEIGHT),
        "--mask_dilation",
        str(PROPAINTER_MASK_DILATION),
        "--neighbor_length",
        "6",
        "--ref_stride",
        "6",
        "--subvideo_length",
        str(INFERENCE_FRAME_COUNT),
        "--save_fps",
        str(FPS),
        "--save_frames",
        "--fp16",
    ]
    run_command(command, cwd=propainter_source, log_path=artifact_dir / "PROPAINTER_RUN.log")
    result_frames = find_propainter_result_frames(propainter_output)

    after_images: dict[int, object] = {}
    composite_rows = []
    video_frames = []
    for target_index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        generated_index = target_index
        generated_path = result_frames / f"{generated_index:04d}.png"
        generated = cv2.imread(str(generated_path), cv2.IMREAD_COLOR)
        before = base_images[frame]
        if generated is None:
            raise ProofError(f"missing ProPainter output for timeline frame {frame}")
        if generated.shape != before.shape:
            generated = cv2.resize(generated, (before.shape[1], before.shape[0]), interpolation=cv2.INTER_CUBIC)
        # V9 fixes the V8 failure before inference. ProPainter sees the row-filled mask
        # only on background pixels. Inside the accepted V4 person matte, it sees only a
        # three-pixel expansion of source-backed COME glyph pixels. The rest of the woman
        # remains visible temporal context, preventing whole-head/face hallucination.
        composite_mask = composite_masks[frame] > 0
        composite_alpha = composite_alphas[frame].astype(np.float32) / 255.0
        final = np.rint(
            before.astype(np.float32) * (1.0 - composite_alpha[..., None])
            + generated.astype(np.float32) * composite_alpha[..., None]
        ).clip(0, 255).astype(np.uint8)
        final_path = final_dir / f"frame_{frame:06d}.png"
        if not cv2.imwrite(str(final_path), final):
            raise ProofError(f"failed to write final proof frame {frame}")
        after_images[frame] = final
        delta = cv2.absdiff(before, final)
        outside = ~composite_mask
        outside_changed = int(np.count_nonzero(np.any(delta[outside] != 0, axis=1)))
        if outside_changed != 0:
            raise ProofError(f"outside-mask preservation failed at frame {frame}: {outside_changed} pixels")
        person_mask = person_masks[frame] > 0
        person_repair_mask = composite_authority_rows[frame]["person_repair_mask"] > 0
        person_glyph_seed = composite_authority_rows[frame]["person_glyph_seed"] > 0
        protected_person_context = person_mask & ~person_repair_mask
        person_context_changed = int(
            np.count_nonzero(np.any(delta[protected_person_context] != 0, axis=1))
        )
        if person_context_changed != 0:
            raise ProofError(
                f"V9 protected person context changed outside source-glyph repair at frame {frame}: "
                f"{person_context_changed} pixels"
            )
        person_repair_changed = int(np.count_nonzero(np.any(delta[person_repair_mask] != 0, axis=1)))
        person_glyph_delta_mae = float(np.mean(delta[person_glyph_seed])) if np.any(person_glyph_seed) else 0.0
        gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        gray_after = cv2.cvtColor(final, cv2.COLOR_BGR2GRAY)
        x1, y1, x2, y2 = interpolate_bbox(frame, anchors)
        width = max(1, x2 - x1)
        # Keep the established background-heavy glyph reduction metric for direct V5-V8
        # comparability. Person-overlap glyphs have a separate replacement-activity gate
        # because legitimate hair is dark and cannot be judged by a simple darkness ratio.
        safe_score = (score_masks[frame] > 0).copy()
        safe_score[:, int(x1 + 0.42 * width): int(x1 + 0.78 * width)] = False
        safe_score_pixels = int(np.count_nonzero(safe_score))
        if safe_score_pixels < 4000:
            raise ProofError(f"source-backed glyph score region unexpectedly small at frame {frame}")
        before_dark = float(np.mean(gray_before[safe_score] < 140))
        after_dark = float(np.mean(gray_after[safe_score] < 140))

        # Independently score the right side of COME, where the failed proof visibly
        # retained the three E bars outside the original style bbox. The probe uses only
        # source pixels that were dark before removal and stays away from the person.
        probe_x1 = max(x1, x2 - RIGHT_GLYPH_PROBE_INSIDE_PIXELS)
        composite_xs = np.where(composite_mask)[1]
        probe_x2 = max(x2, int(composite_xs.max()) + 1)
        right_probe = np.zeros_like(gray_before, dtype=bool)
        right_probe[y1:y2, probe_x1:probe_x2] = True
        right_source_dark = right_probe & (gray_before < RIGHT_GLYPH_DARK_THRESHOLD)
        right_source_dark_pixels = int(np.count_nonzero(right_source_dark))
        require_right_glyph_probe_population(frame, right_source_dark_pixels)
        right_dark_survival = (
            float(np.mean(gray_after[right_source_dark] < RIGHT_GLYPH_DARK_THRESHOLD))
            if right_source_dark_pixels > 0
            else 0.0
        )
        composite_rows.append(
            {
                "timeline_frame": frame,
                "outside_changed_pixels": outside_changed,
                "dynamic_right_guard_pixels": frame_rows[target_index]["dynamic_right_guard_pixels"],
                "inpaint_mask_pixels": frame_rows[target_index]["inpaint_mask_pixels"],
                "inference_seed_pixels": frame_rows[target_index]["inference_seed_pixels"],
                "inference_bridge_added_pixels": frame_rows[target_index]["inference_bridge_added_pixels"],
                "inference_bridge_rows": frame_rows[target_index]["inference_bridge_rows"],
                "compact_source_mask_pixels": frame_rows[target_index]["compact_source_mask_pixels"],
                "composite_mask_pixels": frame_rows[target_index]["composite_mask_pixels"],
                "composite_alpha_sum": frame_rows[target_index]["composite_alpha_sum"],
                "foreground_background_mode": frame_rows[target_index]["foreground_background_mode"],
                "pre_split_row_filled_mask_pixels": frame_rows[target_index]["pre_split_row_filled_mask_pixels"],
                "background_rowfill_pixels": frame_rows[target_index]["background_rowfill_pixels"],
                "person_mask_pixels": frame_rows[target_index]["person_mask_pixels"],
                "person_glyph_seed_pixels": frame_rows[target_index]["person_glyph_seed_pixels"],
                "person_repair_inference_pixels": frame_rows[target_index]["person_repair_inference_pixels"],
                "person_repair_inference_ratio": frame_rows[target_index]["person_repair_inference_ratio"],
                "person_glyph_seed_full_alpha_pixels": frame_rows[target_index]["person_glyph_seed_full_alpha_pixels"],
                "background_compact_pixels": frame_rows[target_index]["background_compact_pixels"],
                "background_compact_covered_pixels": frame_rows[target_index]["background_compact_covered_pixels"],
                "person_context_changed_pixels": person_context_changed,
                "person_repair_changed_pixels": person_repair_changed,
                "person_glyph_delta_mae": person_glyph_delta_mae,
                "legacy_solid_reference_pixels": frame_rows[target_index]["legacy_solid_reference_pixels"],
                "compact_vs_legacy_solid_ratio": frame_rows[target_index]["compact_vs_legacy_solid_ratio"],
                "score_mask_coverage": frame_rows[target_index]["score_mask_coverage"],
                "safe_glyph_score_pixels": safe_score_pixels,
                "safe_glyph_dark_ratio_lt140_before": before_dark,
                "safe_glyph_dark_ratio_lt140_after": after_dark,
                "safe_glyph_dark_reduction": before_dark - after_dark,
                "right_source_dark_pixels": right_source_dark_pixels,
                "right_source_dark_survival_lt140": right_dark_survival,
                "right_source_dark_removal": 1.0 - right_dark_survival,
                "masked_mae": float(np.mean(delta[composite_mask])) if np.any(composite_mask) else 0.0,
                "final_sha256": sha256_file(final_path),
            }
        )
        # Side-by-side video with compact labels.
        before_small = cv2.resize(before, (432, 768), interpolation=cv2.INTER_AREA)
        after_small = cv2.resize(final, (432, 768), interpolation=cv2.INTER_AREA)
        cv2.putText(before_small, f"BEFORE frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(after_small, f"PROPAINTER frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
        video_frames.append(cv2.cvtColor(np.concatenate([before_small, after_small], axis=1), cv2.COLOR_BGR2RGB))

    imageio.mimwrite(str(artifact_dir / "COME_BEFORE_AFTER_PROOF_V9.mp4"), video_frames, fps=FPS, quality=8)

    # Sentinel contact sheet with before / after pairs.
    pair_rows = []
    for frame in SENTINELS:
        before = base_images[frame]
        after = after_images[frame]
        mask = composite_masks[frame] > 0
        ys, xs = np.where(mask)
        x1, x2 = max(0, int(xs.min()) - 80), min(before.shape[1], int(xs.max()) + 81)
        y1, y2 = max(0, int(ys.min()) - 90), min(before.shape[0], int(ys.max()) + 91)
        pair_rows.append((f"BEFORE {frame}", before[y1:y2, x1:x2]))
        pair_rows.append((f"AFTER {frame}", after[y1:y2, x1:x2]))
    create_contact_sheet(pair_rows, artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png")

    weights = []
    weights_dir = propainter_source / "weights"
    if weights_dir.is_dir():
        for weight in sorted(weights_dir.iterdir()):
            if weight.is_file() and weight.suffix.lower() in {".pth", ".pt"}:
                weights.append({"name": weight.name, "sha256": sha256_file(weight), "bytes": weight.stat().st_size})

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "mode": "offline_video_inpainting_proof_only",
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
        "source_window": [SOURCE_FRAME_START, SOURCE_FRAME_END + 1],
        "frame_count": FRAME_COUNT,
        "inference_frame_count": INFERENCE_FRAME_COUNT,
        "processing_resolution": [PROCESS_WIDTH, PROCESS_HEIGHT],
        "output_resolution": [1080, 1920],
        "temporal_context": {
            "strategy": TEMPORAL_CONTEXT_STRATEGY,
            "source_video": str(Path("input/DZsqH7auhjt.mp4").as_posix()),
            "source_video_sha256": EXPECTED_SOURCE_VIDEO_SHA256,
            "source_video_fps": EXPECTED_SOURCE_VIDEO_FPS,
            "source_visible_range": [
                source_context["first_visible_source_frame"],
                source_context["last_visible_source_frame"],
            ],
            "pre_context_source_frames": [],
            "post_context_source_frames": [],
            "context_mask_pixels": 0,
            "rows": [],
            "rejection_reason": "No clean same-shot native source reference exists in the audited pre-window; post-564 is after the cut.",
        },
        "mask_authority": {
            "glyph_source": str((V3_GEOMETRY_RUN_REL / "generated_pixel_restore_v3/glyph_masks").as_posix()),
            "source_bbox_authority": str(STYLE_REL.as_posix()),
            "source_bbox_anchors": {str(k): v for k, v in anchors.items()},
            "pre_dilation_pixels": MASK_PRE_DILATION,
            "propainter_mask_dilation_pixels": PROPAINTER_MASK_DILATION,
            "final_composite_mask_dilation_pixels": 0,
            "max_composite_right_glyph_guard_pixels": MAX_COMPOSITE_RIGHT_GLYPH_GUARD_PIXELS,
            "compact_hull_min_component_area": COMPACT_HULL_MIN_COMPONENT_AREA,
            "compact_hull_close_kernel": [COMPACT_HULL_CLOSE_WIDTH, COMPACT_HULL_CLOSE_HEIGHT],
            "compact_hull_dilation_pixels": COMPACT_HULL_DILATION,
            "compact_inference_dilation_pixels": COMPACT_INFERENCE_DILATION,
            "min_inference_bridge_added_pixels": MIN_INFERENCE_BRIDGE_ADDED_PIXELS,
            "min_inference_bridge_rows": MIN_INFERENCE_BRIDGE_ROWS,
            "right_glyph_discovery_threshold": RIGHT_GLYPH_DISCOVERY_THRESHOLD,
            "right_glyph_probe_inside_pixels": RIGHT_GLYPH_PROBE_INSIDE_PIXELS,
            "max_compact_vs_legacy_solid_ratio": MAX_COMPACT_VS_LEGACY_SOLID_RATIO,
            "min_score_mask_coverage": MIN_SCORE_MASK_COVERAGE,
            "inpaint_mask_strategy": INPAINT_MASK_STRATEGY,
            "composite_mask_strategy": COMPOSITE_MASK_STRATEGY,
            "glyph_score_mask_strategy": GLYPH_SCORE_MASK_STRATEGY,
            "inference_person_veto": True,
            "person_inference_mode": "veto_except_source_glyph_repair",
            "final_person_veto": True,
            "foreground_person_authority_strategy": FOREGROUND_PERSON_AUTHORITY_STRATEGY,
            "foreground_manifest_sha256": foreground_manifest_sha256,
            "person_repair_dilation_pixels": PERSON_REPAIR_DILATION_PIXELS,
            "person_repair_feather_sigma": PERSON_REPAIR_FEATHER_SIGMA,
            "max_person_repair_authority_ratio": MAX_PERSON_REPAIR_AUTHORITY_RATIO,
            "min_person_glyph_seed_pixels": MIN_PERSON_GLYPH_SEED_PIXELS,
            "tail_background_start_frame": TAIL_BACKGROUND_START_FRAME,
            "tail_background_close_kernel": [TAIL_BACKGROUND_CLOSE_WIDTH, TAIL_BACKGROUND_CLOSE_HEIGHT],
            "tail_background_dilation_pixels": TAIL_BACKGROUND_DILATION_PIXELS,
            "tail_background_feather_sigma": TAIL_BACKGROUND_FEATHER_SIGMA,
            "composite_alpha_min": COMPOSITE_ALPHA_MIN,
            "reason": "V8 failed visually because ProPainter had already masked and hallucinated the whole person band before final compositing. V9 moves the protection to inference: background remains row-filled, while accepted V4 person pixels are masked only where source-backed COME glyph pixels actually overlap the person, with a three-pixel repair margin.",
        },
        "iteration_guard": {
            "architecture_family": "propainter_semantic_split_person_repair_v1",
            "same_family_visual_retry_allowed": False,
            "technical_integration_fix_allowed": True,
            "on_visual_fail": "stop_architecture_family_no_v10_mask_dilation_feather_threshold_retry",
        },
        "input_frames": frame_rows,
        "frame_metrics": composite_rows,
        "weights": weights,
        "artifacts": {
            "mask_contact_sheet": "MASK_CONTACT_SHEET.png",
            "before_after_contact_sheet": "BEFORE_AFTER_CONTACT_SHEET.png",
            "comparison_video": "COME_BEFORE_AFTER_PROOF_V9.mp4",
            "final_frames": "inpainted_frames",
            "propainter_log": "PROPAINTER_RUN.log",
        },
        "visual_approval_required": True,
    }
    (artifact_dir / "PROOF_RUN_RESULT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "artifact_dir": str(artifact_dir), "frame_count": FRAME_COUNT}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
