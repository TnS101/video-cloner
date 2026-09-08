from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_SEMANTIC_SKY_PLATE_PROOF_V1"
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
FRAME_COUNT = SOURCE_FRAME_END - SOURCE_FRAME_START + 1
FPS = 24
PERSON_LABEL = 1
PERSON_SCORE_MIN = 0.75
PERSON_MASK_THRESHOLD = 0.50
PERSON_GUARD_DILATION = 4
SEMANTIC_AUTHORITY_DILATION = 3
MAX_DYNAMIC_RIGHT_GUARD_PIXELS = 180
MIN_SCORE_MASK_COVERAGE = 0.92
MIN_PERSON_MASK_AREA = 90_000
MAX_PERSON_MASK_AREA = 650_000
MIN_PERSON_ROI_OVERLAP = 40_000
MIN_REMOVAL_PIXELS = 15_000
SKY_MIN_GRAY = 145
SKY_MAX_SATURATION = 105
SKY_MIN_SAMPLES_PER_SIDE = 8
SKY_SMOOTH_RADIUS = 3
FEATHER_RADIUS = 3.0
MASKRCNN_WEIGHT_FILE = "maskrcnn_resnet50_fpn_v2_coco-73cbd019.pth"
MASKRCNN_WEIGHT_ENUM = "MaskRCNN_ResNet50_FPN_V2_Weights.COCO_V1"
MASKRCNN_MODEL = "torchvision.models.detection.maskrcnn_resnet50_fpn_v2"


class ProofError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_repo_root(value: str | None) -> Path:
    root = Path(value).resolve() if value else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        raise ProofError(f"repository root not found: {root}")
    return root


def load_v5_authority(repo_root: Path):
    path = repo_root / "scripts" / "analysis" / "run_baked_caption_video_inpaint_proof_v1.py"
    if not path.is_file():
        raise ProofError(f"V5 proof authority is missing: {path}")
    spec = importlib.util.spec_from_file_location("vc_baked_caption_v5_authority", path)
    if spec is None or spec.loader is None:
        raise ProofError(f"cannot load V5 proof authority: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_contact_sheet(rows: list[tuple[str, Any]], path: Path) -> None:
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
    if not cv2.imwrite(str(path), np.concatenate(normalized, axis=1)):
        raise ProofError(f"failed to write contact sheet: {path}")


def choose_person_instance(
    labels,
    scores,
    boxes,
    masks,
    *,
    frame_shape: tuple[int, int],
) -> dict[str, Any]:
    import numpy as np

    height, width = frame_shape
    roi_x1 = max(0, int(round(width * 0.30)))
    roi_x2 = min(width, int(round(width * 0.70)))
    roi_y1 = max(0, int(round(height * 0.32)))
    roi_y2 = min(height, int(round(height * 0.96)))
    candidates: list[dict[str, Any]] = []
    for index in range(len(labels)):
        label = int(labels[index])
        score = float(scores[index])
        if label != PERSON_LABEL or score < PERSON_SCORE_MIN:
            continue
        probability = np.asarray(masks[index], dtype=np.float32)
        if probability.ndim == 3 and probability.shape[0] == 1:
            probability = probability[0]
        if probability.shape != (height, width):
            raise ProofError(f"unexpected Mask R-CNN mask dimensions: {probability.shape}")
        binary = probability >= PERSON_MASK_THRESHOLD
        area = int(np.count_nonzero(binary))
        overlap = int(np.count_nonzero(binary[roi_y1:roi_y2, roi_x1:roi_x2]))
        box = [float(value) for value in boxes[index]]
        box_height = max(0.0, box[3] - box[1])
        box_width = max(0.0, box[2] - box[0])
        if area < MIN_PERSON_MASK_AREA or area > MAX_PERSON_MASK_AREA:
            continue
        if overlap < MIN_PERSON_ROI_OVERLAP:
            continue
        if box_height < height * 0.45 or box_width < width * 0.12:
            continue
        candidates.append(
            {
                "index": index,
                "score": score,
                "box": box,
                "mask": binary,
                "mask_area": area,
                "roi_overlap": overlap,
                "rank": overlap * score,
            }
        )
    if not candidates:
        raise ProofError("Mask R-CNN did not produce a valid central person instance")
    return max(candidates, key=lambda row: (row["rank"], row["score"]))


def build_person_guard(mask, box: list[float]):
    import cv2
    import numpy as np

    binary = np.asarray(mask, dtype=np.uint8)
    height, width = binary.shape
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    x1 = max(0, x1 - 12)
    y1 = max(0, y1 - 12)
    x2 = min(width, x2 + 12)
    y2 = min(height, y2 + 12)
    bounded = np.zeros_like(binary)
    bounded[y1:y2, x1:x2] = binary[y1:y2, x1:x2]
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    bounded = cv2.morphologyEx(bounded, cv2.MORPH_CLOSE, close_kernel)
    dilate_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (2 * PERSON_GUARD_DILATION + 1, 2 * PERSON_GUARD_DILATION + 1),
    )
    return cv2.dilate(bounded, dilate_kernel) > 0


def build_semantic_authority(v5, image, glyph, target_bbox: tuple[int, int, int, int]):
    import cv2
    import numpy as np

    compact = v5.build_compact_caption_masks(image, glyph, target_bbox)
    base = (compact["composite_mask"] > 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (2 * SEMANTIC_AUTHORITY_DILATION + 1, 2 * SEMANTIC_AUTHORITY_DILATION + 1),
    )
    authority = cv2.dilate(base, kernel) > 0
    x1, y1, x2, y2 = target_bbox
    clamped = np.zeros_like(authority)
    left = max(0, x1 - 8)
    right = min(authority.shape[1], x2 + MAX_DYNAMIC_RIGHT_GUARD_PIXELS)
    clamped[y1:y2, left:right] = authority[y1:y2, left:right]
    authority = clamped
    ys, xs = np.where(authority)
    if xs.size == 0:
        raise ProofError("semantic caption authority is empty")
    dynamic_right_guard_pixels = max(0, int(xs.max()) + 1 - x2)
    if dynamic_right_guard_pixels > MAX_DYNAMIC_RIGHT_GUARD_PIXELS:
        raise ProofError(f"semantic caption authority escaped right bound: {dynamic_right_guard_pixels}")
    return {
        "authority": authority,
        "dynamic_right_guard_pixels": dynamic_right_guard_pixels,
        "legacy_compact_pixels": int(np.count_nonzero(base)),
        "semantic_authority_pixels": int(np.count_nonzero(authority)),
    }


def _row_sky_sample(image, person_guard, y: int, x_start: int, x_end: int):
    import cv2
    import numpy as np

    x_start = max(0, x_start)
    x_end = min(image.shape[1], x_end)
    if x_end <= x_start:
        return None
    pixels = image[y, x_start:x_end]
    if pixels.size == 0:
        return None
    gray = cv2.cvtColor(pixels.reshape(1, -1, 3), cv2.COLOR_BGR2GRAY).reshape(-1)
    hsv = cv2.cvtColor(pixels.reshape(1, -1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    allowed = (~person_guard[y, x_start:x_end]) & (gray >= SKY_MIN_GRAY) & (hsv[:, 1] <= SKY_MAX_SATURATION)
    if int(np.count_nonzero(allowed)) < SKY_MIN_SAMPLES_PER_SIDE:
        return None
    return np.median(pixels[allowed], axis=0).astype(np.float32)


def estimate_sky_rows(image, person_guard, target_bbox: tuple[int, int, int, int], authority):
    import numpy as np

    x1, y1, x2, y2 = target_bbox
    ys, xs = np.where(authority)
    if xs.size == 0:
        raise ProofError("cannot estimate sky for empty authority")
    authority_left = int(xs.min())
    authority_right = int(xs.max()) + 1
    left_rows: dict[int, np.ndarray] = {}
    right_rows: dict[int, np.ndarray] = {}
    for y in range(y1, y2):
        left = _row_sky_sample(image, person_guard, y, authority_left - 170, authority_left - 14)
        right = _row_sky_sample(image, person_guard, y, authority_right + 14, authority_right + 190)
        if left is None and right is None:
            raise ProofError(f"insufficient clean sky samples at row {y}")
        if left is None:
            left = right.copy()
        if right is None:
            right = left.copy()
        left_rows[y] = left
        right_rows[y] = right

    def smooth(rows: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
        smoothed: dict[int, np.ndarray] = {}
        keys = sorted(rows)
        for y in keys:
            values = [rows[yy] for yy in keys if abs(yy - y) <= SKY_SMOOTH_RADIUS]
            smoothed[y] = np.median(np.stack(values, axis=0), axis=0).astype(np.float32)
        return smoothed

    return smooth(left_rows), smooth(right_rows), authority_left, authority_right


def apply_semantic_sky_plate(
    image,
    authority,
    person_guard,
    target_bbox: tuple[int, int, int, int],
    score_mask,
):
    import cv2
    import numpy as np

    removal = authority & ~person_guard
    if int(np.count_nonzero(removal)) < MIN_REMOVAL_PIXELS:
        raise ProofError("semantic removal region unexpectedly small")
    left_rows, right_rows, authority_left, authority_right = estimate_sky_rows(
        image,
        person_guard,
        target_bbox,
        authority,
    )
    fill = image.astype(np.float32).copy()
    for y in range(target_bbox[1], target_bbox[3]):
        xs = np.where(removal[y])[0]
        if xs.size == 0:
            continue
        denom = max(1, authority_right - 1 - authority_left)
        t = np.clip((xs - authority_left) / float(denom), 0.0, 1.0)
        values = left_rows[y][None, :] * (1.0 - t[:, None]) + right_rows[y][None, :] * t[:, None]
        fill[y, xs] = values

    distance = cv2.distanceTransform(removal.astype(np.uint8), cv2.DIST_L2, 3)
    alpha = np.clip(distance / FEATHER_RADIUS, 0.0, 1.0).astype(np.float32)
    critical = (score_mask > 0) & removal
    alpha[critical] = 1.0
    alpha[person_guard] = 0.0
    final = image.astype(np.float32) * (1.0 - alpha[..., None]) + fill * alpha[..., None]
    final = np.clip(final, 0, 255).astype(np.uint8)
    return final, removal, alpha


def _maskrcnn_model(runtime_root: Path):
    import torch
    import torchvision
    from torchvision.models.detection import MaskRCNN_ResNet50_FPN_V2_Weights, maskrcnn_resnet50_fpn_v2

    if not torch.cuda.is_available():
        raise ProofError("CUDA is required for semantic person segmentation")
    torch_home = runtime_root / "torch_home"
    torch_home.mkdir(parents=True, exist_ok=True)
    os.environ["TORCH_HOME"] = str(torch_home)
    weights = MaskRCNN_ResNet50_FPN_V2_Weights.COCO_V1
    model = maskrcnn_resnet50_fpn_v2(weights=weights)
    device = torch.device("cuda:0")
    model.to(device)
    model.eval()
    return model, device, torch, torchvision, torch_home


def _segment_person(model, device, torch, image):
    import cv2

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    tensor = torch.from_numpy(rgb).permute(2, 0, 1).contiguous().float().div_(255.0).to(device)
    with torch.inference_mode():
        prediction = model([tensor])[0]
    labels = prediction["labels"].detach().cpu().numpy()
    scores = prediction["scores"].detach().cpu().numpy()
    boxes = prediction["boxes"].detach().cpu().numpy()
    masks = prediction["masks"].detach().cpu().numpy()
    return choose_person_instance(labels, scores, boxes, masks, frame_shape=image.shape[:2])


def _weight_info(torch_home: Path) -> dict[str, Any]:
    path = torch_home / "hub" / "checkpoints" / MASKRCNN_WEIGHT_FILE
    if not path.is_file():
        raise ProofError(f"Mask R-CNN weight file is missing after model initialization: {path}")
    if path.stat().st_size < 150_000_000:
        raise ProofError(f"Mask R-CNN weight file is unexpectedly small: {path.stat().st_size}")
    return {
        "filename": path.name,
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--runtime-source", required=True)
    args = parser.parse_args()

    import cv2
    import imageio.v2 as imageio
    import numpy as np

    repo_root = resolve_repo_root(args.repo_root)
    artifact_dir = Path(args.artifact_dir).resolve()
    runtime_source = Path(args.runtime_source).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if not (runtime_source / "inference_propainter.py").is_file():
        raise ProofError(f"verified isolated runtime source is missing: {runtime_source}")

    v5 = load_v5_authority(repo_root)
    failed_run = repo_root / v5.V2_FAILED_RUN_REL
    geometry_run = repo_root / v5.V3_GEOMETRY_RUN_REL
    base_dir = failed_run / "render_base_baked"
    glyph_dir = geometry_run / "generated_pixel_restore_v3" / "glyph_masks"
    style_path = repo_root / v5.STYLE_REL
    source_track_path = repo_root / v5.SOURCE_TRACK_REL
    lifecycle_path = repo_root / v5.LIFECYCLE_REL
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

    failed_report = load_json(failed_run / "report.json")
    if not isinstance(failed_report, dict) or failed_report.get("ok") is not False or failed_report.get("failed_target_retained") is not False:
        raise ProofError("COME-only V2 evidence is not the expected clean failed run")
    v3_manifest = load_json(geometry_run / "generated_pixel_restore_v3" / "manifest.json")
    if not isinstance(v3_manifest, dict) or v3_manifest.get("ok") is not True:
        raise ProofError("V3 glyph geometry manifest is not PASS evidence")
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
    if base_authority.get("dimensions") != {"frame_rate": 24.0, "height": 1920, "width": 1080}:
        raise ProofError("unexpected base render dimensions")
    base_render = base_authority.get("render") or {}
    base_hashes = base_render.get("file_hashes")
    if base_render.get("ok") is not True or not isinstance(base_hashes, dict) or len(base_hashes) != FRAME_COUNT:
        raise ProofError("base render authority does not contain the exact 24-frame hash contract")
    anchors = v5.verify_style_anchors(load_json(style_path))
    source_context = v5.verify_source_context_authority(
        load_json(source_track_path),
        load_json(lifecycle_path),
        repo_root,
    )

    outputs_dir = artifact_dir / "semantic_sky_frames"
    person_dir = artifact_dir / "person_masks"
    authority_dir = artifact_dir / "semantic_authority_masks"
    for directory in (outputs_dir, person_dir, authority_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    model, device, torch, torchvision, torch_home = _maskrcnn_model(runtime_source.parent)
    weight_info = _weight_info(torch_home)
    frame_metrics: list[dict[str, Any]] = []
    before_images: dict[int, Any] = {}
    after_images: dict[int, Any] = {}
    person_masks: dict[int, Any] = {}
    authority_masks: dict[int, Any] = {}
    video_frames = []

    for frame in range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1):
        base_path = base_dir / f"base_baked_{frame:08d}.png"
        glyph_path = glyph_dir / f"glyph_{frame:06d}.png"
        if not base_path.is_file() or not glyph_path.is_file():
            raise ProofError(f"missing proof authority at frame {frame}")
        row = v3_by_frame.get(frame)
        if not isinstance(row, dict):
            raise ProofError(f"V3 geometry has no row for frame {frame}")
        expected_base_sha = base_hashes.get(base_path.name)
        if not isinstance(expected_base_sha, str) or sha256_file(base_path) != expected_base_sha:
            raise ProofError(f"base render hash mismatch at frame {frame}")
        expected_glyph_sha = row.get("glyph_mask_sha256")
        if not isinstance(expected_glyph_sha, str) or sha256_file(glyph_path) != expected_glyph_sha:
            raise ProofError(f"V3 glyph hash mismatch at frame {frame}")
        image = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
        glyph = cv2.imread(str(glyph_path), cv2.IMREAD_GRAYSCALE)
        if image is None or glyph is None or image.shape[:2] != (1920, 1080) or glyph.shape != (1920, 1080):
            raise ProofError(f"invalid proof input at frame {frame}")
        target_bbox = v5.interpolate_bbox(frame, anchors)
        score_mask = v5.clip_mask_to_bbox(v5.transform_glyph_mask(glyph, target_bbox), target_bbox)
        semantic = build_semantic_authority(v5, image, glyph, target_bbox)
        authority = semantic["authority"]
        score_core = score_mask > 0
        score_coverage = float(np.count_nonzero(score_core & authority)) / float(np.count_nonzero(score_core))
        if score_coverage < MIN_SCORE_MASK_COVERAGE:
            raise ProofError(f"semantic authority under-covered COME score mask at frame {frame}: {score_coverage:.6f}")

        person = _segment_person(model, device, torch, image)
        person_guard = build_person_guard(person["mask"], person["box"])
        person_pixels = int(np.count_nonzero(person_guard))
        if person_pixels < MIN_PERSON_MASK_AREA or person_pixels > MAX_PERSON_MASK_AREA + 80_000:
            raise ProofError(f"semantic person guard area out of bounds at frame {frame}: {person_pixels}")
        final, removal, alpha = apply_semantic_sky_plate(image, authority, person_guard, target_bbox, score_mask)
        delta = cv2.absdiff(image, final)
        outside_changed = int(np.count_nonzero(np.any(delta[~authority] != 0, axis=1)))
        person_changed = int(np.count_nonzero(np.any(delta[person_guard] != 0, axis=1)))
        if outside_changed != 0:
            raise ProofError(f"outside semantic authority changed at frame {frame}: {outside_changed}")
        if person_changed != 0:
            raise ProofError(f"semantic person guard changed at frame {frame}: {person_changed}")

        gray_before = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray_after = cv2.cvtColor(final, cv2.COLOR_BGR2GRAY)
        safe_score = score_core & ~person_guard
        safe_score_pixels = int(np.count_nonzero(safe_score))
        if safe_score_pixels < 3500:
            raise ProofError(f"person-excluded COME score region unexpectedly small at frame {frame}: {safe_score_pixels}")
        before_dark = float(np.mean(gray_before[safe_score] < 140))
        after_dark = float(np.mean(gray_after[safe_score] < 140))

        x1, y1, x2, y2 = target_bbox
        authority_xs = np.where(authority)[1]
        probe_x1 = max(x1, x2 - v5.RIGHT_GLYPH_PROBE_INSIDE_PIXELS)
        probe_x2 = max(x2, int(authority_xs.max()) + 1)
        right_probe = np.zeros_like(gray_before, dtype=bool)
        right_probe[y1:y2, probe_x1:probe_x2] = True
        right_source_dark = right_probe & ~person_guard & (gray_before < v5.RIGHT_GLYPH_DARK_THRESHOLD)
        right_source_dark_pixels = int(np.count_nonzero(right_source_dark))
        if frame in v5.HOLD_SENTINELS and right_source_dark_pixels < 2500:
            raise ProofError(f"person-excluded right-glyph probe unexpectedly small at frame {frame}: {right_source_dark_pixels}")
        right_survival = (
            float(np.mean(gray_after[right_source_dark] < v5.RIGHT_GLYPH_DARK_THRESHOLD))
            if right_source_dark_pixels
            else 0.0
        )

        person_path = person_dir / f"person_{frame:06d}.png"
        authority_path = authority_dir / f"authority_{frame:06d}.png"
        final_path = outputs_dir / f"frame_{frame:06d}.png"
        if not cv2.imwrite(str(person_path), person_guard.astype(np.uint8) * 255):
            raise ProofError(f"failed to write person mask at frame {frame}")
        if not cv2.imwrite(str(authority_path), authority.astype(np.uint8) * 255):
            raise ProofError(f"failed to write semantic authority at frame {frame}")
        if not cv2.imwrite(str(final_path), final):
            raise ProofError(f"failed to write semantic sky plate at frame {frame}")

        before_images[frame] = image
        after_images[frame] = final
        person_masks[frame] = person_guard
        authority_masks[frame] = authority
        frame_metrics.append(
            {
                "timeline_frame": frame,
                "source_bbox": list(target_bbox),
                "dynamic_right_guard_pixels": int(semantic["dynamic_right_guard_pixels"]),
                "legacy_compact_pixels": int(semantic["legacy_compact_pixels"]),
                "semantic_authority_pixels": int(semantic["semantic_authority_pixels"]),
                "score_mask_coverage": score_coverage,
                "person_score": float(person["score"]),
                "person_box": [float(value) for value in person["box"]],
                "person_mask_area": int(person["mask_area"]),
                "person_guard_pixels": person_pixels,
                "person_roi_overlap": int(person["roi_overlap"]),
                "person_changed_pixels": person_changed,
                "outside_changed_pixels": outside_changed,
                "removal_pixels": int(np.count_nonzero(removal)),
                "safe_glyph_score_pixels": safe_score_pixels,
                "safe_glyph_dark_ratio_lt140_before": before_dark,
                "safe_glyph_dark_ratio_lt140_after": after_dark,
                "right_source_dark_pixels": right_source_dark_pixels,
                "right_source_dark_survival_lt140": right_survival,
                "final_sha256": sha256_file(final_path),
                "person_mask_sha256": sha256_file(person_path),
                "authority_sha256": sha256_file(authority_path),
            }
        )

        before_small = cv2.resize(image, (432, 768), interpolation=cv2.INTER_AREA)
        after_small = cv2.resize(final, (432, 768), interpolation=cv2.INTER_AREA)
        cv2.putText(before_small, f"BEFORE frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(after_small, f"SEMANTIC SKY frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
        video_frames.append(cv2.cvtColor(np.concatenate([before_small, after_small], axis=1), cv2.COLOR_BGR2RGB))
        torch.cuda.empty_cache()

    imageio.mimwrite(str(artifact_dir / "COME_BEFORE_AFTER_PROOF_V6.mp4"), video_frames, fps=FPS, quality=8)

    sentinels = list(v5.SENTINELS)
    before_after_rows = []
    mask_rows = []
    person_rows = []
    for frame in sentinels:
        before = before_images[frame]
        after = after_images[frame]
        authority = authority_masks[frame]
        person = person_masks[frame]
        ys, xs = np.where(authority)
        x1 = max(0, int(xs.min()) - 80)
        x2 = min(before.shape[1], int(xs.max()) + 81)
        y1 = max(0, int(ys.min()) - 90)
        y2 = min(before.shape[0], int(ys.max()) + 91)
        before_after_rows.append((f"BEFORE {frame}", before[y1:y2, x1:x2]))
        before_after_rows.append((f"AFTER {frame}", after[y1:y2, x1:x2]))
        overlay = before.copy()
        overlay[authority] = (0.45 * overlay[authority] + 0.55 * np.array([0, 0, 255])).astype(np.uint8)
        overlay[person] = (0.35 * overlay[person] + 0.65 * np.array([0, 255, 0])).astype(np.uint8)
        mask_rows.append((f"authority red / person green {frame}", overlay[y1:y2, x1:x2]))
        person_preview = before.copy()
        person_preview[~person] = (person_preview[~person] * 0.22).astype(np.uint8)
        person_rows.append((f"Mask R-CNN person {frame}", person_preview[y1:y2, x1:x2]))
    create_contact_sheet(before_after_rows, artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png")
    create_contact_sheet(mask_rows, artifact_dir / "MASK_CONTACT_SHEET.png")
    create_contact_sheet(person_rows, artifact_dir / "PERSON_MASK_CONTACT_SHEET.png")

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "mode": "offline_semantic_person_sky_plate_proof_only",
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
        "source_window": [SOURCE_FRAME_START, SOURCE_FRAME_END + 1],
        "frame_count": FRAME_COUNT,
        "source_video": {
            "path": "input/DZsqH7auhjt.mp4",
            "sha256": v5.EXPECTED_SOURCE_VIDEO_SHA256,
            "fps": v5.EXPECTED_SOURCE_VIDEO_FPS,
            "visible_range": [source_context["first_visible_source_frame"], source_context["last_visible_source_frame"]],
        },
        "semantic_person_model": {
            "model": MASKRCNN_MODEL,
            "weights": MASKRCNN_WEIGHT_ENUM,
            "person_label": PERSON_LABEL,
            "score_min": PERSON_SCORE_MIN,
            "mask_threshold": PERSON_MASK_THRESHOLD,
            "guard_dilation_pixels": PERSON_GUARD_DILATION,
            "weight_file": weight_info,
            "torch": torch.__version__,
            "torchvision": torchvision.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
        },
        "sky_plate": {
            "strategy": "same_frame_rowwise_sky_interpolation_inside_come_authority_minus_semantic_person_v1",
            "semantic_authority_source": "V5 filled component hulls plus source-dark right extension, dilated 3px and clamped to COME vertical bbox",
            "semantic_authority_dilation_pixels": SEMANTIC_AUTHORITY_DILATION,
            "max_dynamic_right_guard_pixels": MAX_DYNAMIC_RIGHT_GUARD_PIXELS,
            "min_score_mask_coverage": MIN_SCORE_MASK_COVERAGE,
            "sky_min_gray": SKY_MIN_GRAY,
            "sky_max_saturation": SKY_MAX_SATURATION,
            "sky_smooth_radius": SKY_SMOOTH_RADIUS,
            "feather_radius": FEATHER_RADIUS,
            "person_pixels_are_exact_source": True,
            "outside_authority_pixels_are_exact_source": True,
        },
        "frame_metrics": frame_metrics,
        "artifacts": {
            "comparison_video": "COME_BEFORE_AFTER_PROOF_V6.mp4",
            "before_after_contact_sheet": "BEFORE_AFTER_CONTACT_SHEET.png",
            "mask_contact_sheet": "MASK_CONTACT_SHEET.png",
            "person_mask_contact_sheet": "PERSON_MASK_CONTACT_SHEET.png",
            "final_frames": "semantic_sky_frames",
            "person_masks": "person_masks",
            "authority_masks": "semantic_authority_masks",
        },
        "visual_approval_required": True,
    }
    (artifact_dir / "SEMANTIC_SKY_PROOF_RESULT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "artifact_dir": str(artifact_dir), "frame_count": FRAME_COUNT}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
