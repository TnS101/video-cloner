from __future__ import annotations

import argparse
import contextlib
import gc
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_DIFFUERASER_ROI_PROOF_V1"
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
FRAME_COUNT = 24
FPS = 24
SENTINELS = (429, 431, 434, 438, 443, 448, 452)
HOLD_SENTINELS = (434, 438, 443, 448)
MAX_MODEL_EDGE = 576
MODEL_SEED = 20260816
ROI_HORIZONTAL_MARGIN = 120
ROI_TOP_MARGIN = 120
ROI_BOTTOM_MARGIN = 180
MIN_ROI_WIDTH = 700
MIN_ROI_HEIGHT = 360
FINAL_BACKGROUND_FEATHER_PIXELS = 8
FINAL_PERSON_REPAIR_DILATION_PIXELS = 3
FINAL_PERSON_FEATHER_PIXELS = 3
MIN_SAFE_GLYPH_PIXELS = 4000
MIN_SOURCE_GLYPH_REDUCTION = 0.70
MIN_RIGHT_GLYPH_REMOVAL = 0.75
NEW_DARK_THRESHOLD_BEFORE = 170
NEW_DARK_THRESHOLD_AFTER = 110
NEW_BRIGHT_THRESHOLD_BEFORE = 170
NEW_BRIGHT_THRESHOLD_AFTER = 235
MAX_NEW_DARK_ARTIFACT_RATIO = 0.03
MAX_NEW_BRIGHT_ARTIFACT_RATIO = 0.03
MAX_BOUNDARY_RING_MAE = 30.0
MIN_ARTIFACT_CONTEXT_PIXELS = 1000
ARCHITECTURE_FAMILY = "diffueraser_roi_source_authority_semantic_composite_v1"
CLOSED_ARCHITECTURE_FAMILIES = (
    "propainter_semantic_split_person_repair_v1",
    "stabilized_source_backed_person_then_background_v1",
    "propainter_v4_foreground_veto_background_only_v1",
)
EXPECTED_DIFFUERASER_COMMIT = "8e6f279ac7531e27ad1849c6f8dab5372a8597e7"
EXPECTED_V9_SHA256 = "297ce12a8edd0fbb875f95ce4ba9817de8e80b0cce0027a21510d3e82fa45825"


class ProofError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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


def load_v9_authority_module(repo_root: Path):
    path = repo_root / "scripts" / "analysis" / "run_baked_caption_video_inpaint_proof_v1.py"
    if not path.is_file():
        raise ProofError(f"V9 authority runner missing: {path}")
    actual = sha256_file(path)
    if actual != EXPECTED_V9_SHA256:
        raise ProofError(f"V9 authority hash mismatch: expected {EXPECTED_V9_SHA256}, got {actual}")
    spec = importlib.util.spec_from_file_location("video_cloner_v9_authority", path)
    if spec is None or spec.loader is None:
        raise ProofError("could not load V9 authority module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def centered_interval(lo: int, hi: int, minimum: int, limit: int) -> tuple[int, int]:
    size = hi - lo
    if size >= minimum:
        return max(0, lo), min(limit, hi)
    need = minimum - size
    left = need // 2
    right = need - left
    lo -= left
    hi += right
    if lo < 0:
        hi = min(limit, hi - lo)
        lo = 0
    if hi > limit:
        lo = max(0, lo - (hi - limit))
        hi = limit
    return lo, hi


def derive_roi(masks: list[object], frame_shape: tuple[int, int]) -> tuple[int, int, int, int]:
    import numpy as np

    height, width = frame_shape
    union = np.zeros((height, width), dtype=np.uint8)
    for mask in masks:
        if getattr(mask, "shape", None) != (height, width):
            raise ProofError("ROI authority mask shape mismatch")
        union |= (mask > 0).astype(np.uint8)
    ys, xs = np.where(union > 0)
    if xs.size == 0:
        raise ProofError("ROI authority is empty")
    x1 = max(0, int(xs.min()) - ROI_HORIZONTAL_MARGIN)
    x2 = min(width, int(xs.max()) + 1 + ROI_HORIZONTAL_MARGIN)
    y1 = max(0, int(ys.min()) - ROI_TOP_MARGIN)
    y2 = min(height, int(ys.max()) + 1 + ROI_BOTTOM_MARGIN)
    x1, x2 = centered_interval(x1, x2, MIN_ROI_WIDTH, width)
    y1, y2 = centered_interval(y1, y2, MIN_ROI_HEIGHT, height)
    if x2 <= x1 or y2 <= y1:
        raise ProofError("derived ROI is invalid")
    # This proof intentionally keeps a wide, caption-centered crop so a 576px max
    # edge stays close to the official 640x360 memory envelope instead of feeding
    # the 1080x1920 portrait frame to the diffusion model.
    if (y2 - y1) / float(x2 - x1) > 0.78:
        raise ProofError(f"derived ROI is too tall for the bounded 12GB proof: {(x1, y1, x2, y2)}")
    return x1, y1, x2, y2


def inward_feather(mask, pixels: int):
    import cv2
    import numpy as np

    binary = (mask > 0).astype(np.uint8)
    if not np.any(binary):
        return np.zeros_like(binary, dtype=np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    alpha = np.clip(distance / float(max(1, pixels)), 0.0, 1.0)
    return np.rint(alpha * 255.0).astype(np.uint8)


def build_final_alpha(row_filled_mask, compact_source_mask, score_mask, person_mask):
    import cv2
    import numpy as np

    row = row_filled_mask > 0
    compact = compact_source_mask > 0
    score = score_mask > 0
    person = person_mask > 0
    # Compact authority includes source-dark right-tail discovery. That is useful on
    # background but can legitimately include dark hair. Never treat those discovered
    # dark person pixels as caption authority. On the accepted person matte, only the
    # source-backed transformed V3 glyph score is allowed to open a repair region.
    background_source_caption = (compact | score) & ~person
    person_seed = score & person
    source_caption = background_source_caption | person_seed

    background_authority = row & ~person
    background_alpha = inward_feather(background_authority.astype(np.uint8) * 255, FINAL_BACKGROUND_FEATHER_PIXELS)

    kernel_size = 2 * FINAL_PERSON_REPAIR_DILATION_PIXELS + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    person_repair = cv2.dilate(person_seed.astype(np.uint8), kernel) > 0
    person_repair &= person
    person_alpha = inward_feather(person_repair.astype(np.uint8) * 255, FINAL_PERSON_FEATHER_PIXELS)

    alpha = np.maximum(background_alpha, person_alpha)
    # Every source-backed caption pixel gets full replacement authority. Feathering
    # is only allowed on the outside transition ring, never across the baked glyph.
    alpha[source_caption] = 255
    final_authority = alpha > 0
    protected_person = person & ~person_repair
    if np.any(protected_person & final_authority):
        raise ProofError("final alpha escaped protected person context")
    if np.any(source_caption & (alpha < 255)):
        raise ProofError("source caption is not fully covered by final alpha")
    return {
        "alpha": alpha,
        "source_caption": source_caption,
        "background_authority": background_authority,
        "person_seed": person_seed,
        "person_repair": person_repair,
        "protected_person": protected_person,
        "final_authority": final_authority,
    }


def visual_artifact_metrics(before, after, alpha, source_caption, person_mask):
    import cv2
    import numpy as np

    gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    authority = alpha > 0
    person = person_mask > 0
    caption = source_caption > 0
    context = authority & ~person & ~caption
    context_pixels = int(np.count_nonzero(context))
    if context_pixels < MIN_ARTIFACT_CONTEXT_PIXELS:
        raise ProofError(f"artifact context unexpectedly small: {context_pixels}")
    new_dark = context & (gray_before >= NEW_DARK_THRESHOLD_BEFORE) & (gray_after <= NEW_DARK_THRESHOLD_AFTER)
    new_bright = context & (gray_before <= NEW_BRIGHT_THRESHOLD_BEFORE) & (gray_after >= NEW_BRIGHT_THRESHOLD_AFTER)
    boundary = (alpha > 0) & (alpha < 255) & ~caption & ~person
    delta = cv2.absdiff(before, after)
    boundary_mae = float(np.mean(delta[boundary])) if np.any(boundary) else 0.0
    return {
        "artifact_context_pixels": context_pixels,
        "new_dark_artifact_pixels": int(np.count_nonzero(new_dark)),
        "new_dark_artifact_ratio": float(np.mean(new_dark[context])),
        "new_bright_artifact_pixels": int(np.count_nonzero(new_bright)),
        "new_bright_artifact_ratio": float(np.mean(new_bright[context])),
        "boundary_ring_pixels": int(np.count_nonzero(boundary)),
        "boundary_ring_mae": boundary_mae,
    }


def relative_reduction(before_ratio: float, after_ratio: float) -> float:
    if before_ratio <= 0.0:
        return 0.0
    return max(0.0, min(1.0, (before_ratio - after_ratio) / before_ratio))


def read_mp4_frames(path: Path) -> list[object]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ProofError(f"could not open generated video: {path}")
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames


def install_exact_directory_readers(diffueraser_module, *, fps: int) -> None:
    import cv2
    import numpy as np
    from PIL import Image

    def read_video_dir(validation_image, video_length, nframes, max_img_size):
        root = Path(validation_image)
        if not root.is_dir():
            return diffueraser_module._video_cloner_original_read_video(validation_image, video_length, nframes, max_img_size)
        names = sorted(root.glob("*.png"))
        n_total_frames = min(len(names), int(round(float(video_length) * fps)))
        frames = [Image.open(name).convert("RGB") for name in names[:n_total_frames]]
        if not frames:
            raise ValueError("exact-directory video input is empty")
        max_size = max(frames[0].size)
        if max_size < 256 or max_size > 4096:
            raise ValueError(f"unsupported ROI input size: {frames[0].size}")
        if max_size > max_img_size:
            ratio = max_size / float(max_img_size)
            ratio_size = (int(frames[0].size[0] / ratio), int(frames[0].size[1] / ratio))
            img_size = (ratio_size[0] - ratio_size[0] % 8, ratio_size[1] - ratio_size[1] % 8)
            frames = diffueraser_module.resize_frames(frames, img_size)
        else:
            img_size = (frames[0].size[0] - frames[0].size[0] % 8, frames[0].size[1] - frames[0].size[1] % 8)
            frames = diffueraser_module.resize_frames(frames, img_size)
        n_clip = int(math.ceil(n_total_frames / float(nframes)))
        return frames, float(fps), frames[0].size, n_clip, n_total_frames

    def read_mask_dir(validation_mask, actual_fps, n_total_frames, img_size, mask_dilation_iter, frames):
        root = Path(validation_mask)
        if not root.is_dir():
            return diffueraser_module._video_cloner_original_read_mask(
                validation_mask, actual_fps, n_total_frames, img_size, mask_dilation_iter, frames
            )
        names = sorted(root.glob("*.png"))[:n_total_frames]
        if len(names) != n_total_frames:
            raise ValueError(f"exact-directory mask count mismatch: {len(names)} != {n_total_frames}")
        masks, masked_images = [], []
        for index, name in enumerate(names):
            mask_img = Image.open(name).convert("L")
            if mask_img.size != img_size:
                mask_img = mask_img.resize(img_size, Image.NEAREST)
            binary = (np.asarray(mask_img) > 127).astype(np.uint8) * 255
            mask = Image.fromarray(binary)
            masks.append(mask)
            frame = np.asarray(frames[index]).astype(np.uint8)
            masked = frame * (1 - (binary[:, :, None].astype(np.float32) / 255.0))
            masked_images.append(Image.fromarray(masked.astype(np.uint8)))
        return masks, masked_images

    diffueraser_module._video_cloner_original_read_video = diffueraser_module.read_video
    diffueraser_module._video_cloner_original_read_mask = diffueraser_module.read_mask
    diffueraser_module.read_video = read_video_dir
    diffueraser_module.read_mask = read_mask_dir


def run_diffueraser(source: Path, input_dir: Path, mask_dir: Path, artifact_dir: Path) -> dict[str, object]:
    import torch

    if not torch.cuda.is_available():
        raise ProofError("DiffuEraser proof requires CUDA")
    if source.name != f"DiffuEraser_checkout_{EXPECTED_DIFFUERASER_COMMIT[:12]}":
        raise ProofError(f"unexpected DiffuEraser checkout path: {source}")
    if not (source / ".git").is_dir():
        raise ProofError(f"DiffuEraser checkout is not a git clone: {source}")

    import subprocess
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(source), text=True).strip()
    if commit != EXPECTED_DIFFUERASER_COMMIT:
        raise ProofError(f"DiffuEraser commit mismatch: {commit}")

    sys.path.insert(0, str(source))
    old_cwd = Path.cwd()
    prior_work = artifact_dir / "PROPAINTER_PRIOR_WORK.mp4"
    prior_preserved = artifact_dir / "PROPAINTER_PRIOR_PRESERVED.mp4"
    output_video = artifact_dir / "DIFFUERASER_ROI_OUTPUT.mp4"
    log_path = artifact_dir / "DIFFUERASER_RUN.log"
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    try:
        os.chdir(source)
        from propainter.inference import Propainter
        import diffueraser.diffueraser as diffueraser_module
        from diffueraser.diffueraser import DiffuEraser

        install_exact_directory_readers(diffueraser_module, fps=FPS)
        device = torch.device("cuda")
        with log_path.open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            print(f"task_id={TASK_ID}")
            print(f"diffueraser_commit={commit}")
            print(f"device={torch.cuda.get_device_name(0)}")
            print(f"max_model_edge={MAX_MODEL_EDGE}")
            print("stage=propainter_prior")
            prior_model = Propainter(str(source / "weights" / "propainter"), device)
            prior_model.forward(
                str(input_dir),
                str(mask_dir),
                str(prior_work),
                resize_ratio=1.0,
                video_length=1.0,
                mask_dilation=1,
                ref_stride=10,
                neighbor_length=10,
                subvideo_length=50,
                raft_iter=20,
                save_fps=FPS,
                save_frames=False,
                fp16=True,
            )
            if not prior_work.is_file() or prior_work.stat().st_size <= 0:
                raise ProofError("ProPainter prior was not produced")
            shutil.copy2(prior_work, prior_preserved)
            del prior_model
            gc.collect()
            torch.cuda.empty_cache()

            print("stage=diffueraser")
            model = DiffuEraser(
                device=device,
                base_model_path=str(source / "weights" / "stable-diffusion-v1-5"),
                vae_path=str(source / "weights" / "sd-vae-ft-mse"),
                diffueraser_path=str(source / "weights" / "diffuEraser"),
                ckpt="2-Step",
                mode="sd15",
            )
            model.forward(
                str(input_dir),
                str(mask_dir),
                str(prior_work),
                str(output_video),
                max_img_size=MAX_MODEL_EDGE,
                video_length=1.0,
                mask_dilation_iter=0,
                nframes=22,
                seed=MODEL_SEED,
                guidance_scale=None,
                blended=False,
            )
            del model
            gc.collect()
            torch.cuda.empty_cache()
            print("stage=complete")
    finally:
        os.chdir(old_cwd)
        try:
            sys.path.remove(str(source))
        except ValueError:
            pass

    if not output_video.is_file() or output_video.stat().st_size <= 0:
        raise ProofError("DiffuEraser output video is missing")
    frames = read_mp4_frames(output_video)
    if len(frames) != FRAME_COUNT:
        raise ProofError(f"DiffuEraser output frame count mismatch: {len(frames)} != {FRAME_COUNT}")
    return {
        "diffueraser_commit": commit,
        "output_video": str(output_video),
        "output_sha256": sha256_file(output_video),
        "prior_preserved": str(prior_preserved),
        "prior_sha256": sha256_file(prior_preserved),
        "log": str(log_path),
        "log_sha256": sha256_file(log_path),
        "output_frame_count": len(frames),
        "device_name": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
    }


def create_contact_sheet(v9, rows: list[tuple[str, object]], path: Path) -> None:
    v9.create_contact_sheet(rows, path)


def main() -> int:
    import cv2
    import imageio.v2 as imageio
    import numpy as np

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--diffueraser-source", required=True)
    parser.add_argument("--foreground-authority-dir", required=True)
    args = parser.parse_args()

    repo_root = resolve_repo_root(args.repo_root)
    artifact_dir = Path(args.artifact_dir).resolve()
    source = Path(args.diffueraser_source).resolve()
    foreground_dir = Path(args.foreground_authority_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    v9 = load_v9_authority_module(repo_root)

    failed_run = repo_root / v9.V2_FAILED_RUN_REL
    geometry_run = repo_root / v9.V3_GEOMETRY_RUN_REL
    base_dir = failed_run / "render_base_baked"
    glyph_dir = geometry_run / "generated_pixel_restore_v3" / "glyph_masks"
    style_path = repo_root / v9.STYLE_REL
    source_track_path = repo_root / v9.SOURCE_TRACK_REL
    lifecycle_path = repo_root / v9.LIFECYCLE_REL
    required = [
        failed_run / "report.json",
        failed_run / "base_render_authority.json",
        geometry_run / "generated_pixel_restore_v3" / "manifest.json",
        style_path,
        source_track_path,
        lifecycle_path,
        foreground_dir / "manifest.json",
    ]
    for path in required:
        if not path.is_file():
            raise ProofError(f"missing authority file: {path}")

    base_authority = v9.load_json(failed_run / "base_render_authority.json")
    if not isinstance(base_authority, dict) or base_authority.get("ok") is not True:
        raise ProofError("base render authority is not PASS")
    if base_authority.get("dimensions") != {"frame_rate": 24.0, "height": 1920, "width": 1080}:
        raise ProofError(f"unexpected base dimensions: {base_authority.get('dimensions')}")
    anchors = v9.verify_style_anchors(v9.load_json(style_path))
    source_context = v9.verify_source_context_authority(
        v9.load_json(source_track_path), v9.load_json(lifecycle_path), repo_root
    )
    foreground_paths = v9.load_v4_foreground_authority(foreground_dir)

    frames: dict[int, object] = {}
    row_masks: dict[int, object] = {}
    compact_masks: dict[int, object] = {}
    score_masks: dict[int, object] = {}
    person_masks: dict[int, object] = {}
    target_bboxes: dict[int, tuple[int, int, int, int]] = {}
    frame_pre_rows = []

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
        row = compact["inpaint_mask"]
        compact_source = compact["composite_mask"]
        person = v9.load_full_resolution_person_mask(foreground_paths[frame], before.shape[:2])
        if int(np.count_nonzero(score)) < 15000:
            raise ProofError(f"score mask unexpectedly small at frame {frame}")
        frames[frame] = before
        row_masks[frame] = row
        compact_masks[frame] = compact_source
        score_masks[frame] = score
        person_masks[frame] = person
        target_bboxes[frame] = bbox
        frame_pre_rows.append({
            "timeline_frame": frame,
            "row_filled_mask_pixels": int(np.count_nonzero(row)),
            "compact_source_mask_pixels": int(np.count_nonzero(compact_source)),
            "score_mask_pixels": int(np.count_nonzero(score)),
            "person_mask_pixels": int(np.count_nonzero(person)),
            "dynamic_right_guard_pixels": int(compact["dynamic_right_guard_pixels"]),
        })

    roi = derive_roi(list(row_masks.values()), (1920, 1080))
    rx1, ry1, rx2, ry2 = roi
    roi_w, roi_h = rx2 - rx1, ry2 - ry1
    input_dir = artifact_dir / "roi_input_frames"
    mask_dir = artifact_dir / "roi_inference_masks"
    final_dir = artifact_dir / "inpainted_frames"
    generated_dir = artifact_dir / "diffueraser_generated_roi_frames"
    for directory in (input_dir, mask_dir, final_dir, generated_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        crop = frames[frame][ry1:ry2, rx1:rx2]
        mask_crop = row_masks[frame][ry1:ry2, rx1:rx2]
        if not cv2.imwrite(str(input_dir / f"{index:04d}.png"), crop):
            raise ProofError(f"could not write ROI input frame {frame}")
        if not cv2.imwrite(str(mask_dir / f"{index:04d}.png"), mask_crop):
            raise ProofError(f"could not write ROI mask frame {frame}")

    roi_payload = {
        "task_id": TASK_ID,
        "architecture_family": ARCHITECTURE_FAMILY,
        "closed_architecture_families": list(CLOSED_ARCHITECTURE_FAMILIES),
        "roi_xyxy": list(roi),
        "roi_size": [roi_w, roi_h],
        "roi_aspect_height_over_width": roi_h / float(roi_w),
        "max_model_edge": MAX_MODEL_EDGE,
        "model_seed": MODEL_SEED,
        "frame_count": FRAME_COUNT,
    }
    (artifact_dir / "ROI_AUTHORITY.json").write_text(json.dumps(roi_payload, indent=2, sort_keys=True), encoding="utf-8")

    model_run = run_diffueraser(source, input_dir, mask_dir, artifact_dir)
    generated_roi_frames = read_mp4_frames(Path(model_run["output_video"]))

    after_images: dict[int, object] = {}
    frame_metrics = []
    video_frames = []
    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        before = frames[frame]
        generated_roi = generated_roi_frames[index]
        if generated_roi.shape[1] != roi_w or generated_roi.shape[0] != roi_h:
            generated_roi = cv2.resize(generated_roi, (roi_w, roi_h), interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(str(generated_dir / f"frame_{frame:06d}.png"), generated_roi)
        generated = before.copy()
        generated[ry1:ry2, rx1:rx2] = generated_roi

        authority = build_final_alpha(
            row_masks[frame], compact_masks[frame], score_masks[frame], person_masks[frame]
        )
        alpha = authority["alpha"].astype(np.float32) / 255.0
        final = np.rint(
            before.astype(np.float32) * (1.0 - alpha[:, :, None])
            + generated.astype(np.float32) * alpha[:, :, None]
        ).clip(0, 255).astype(np.uint8)
        final_path = final_dir / f"frame_{frame:06d}.png"
        if not cv2.imwrite(str(final_path), final):
            raise ProofError(f"could not write final frame {frame}")
        after_images[frame] = final

        delta = cv2.absdiff(before, final)
        outside = ~authority["final_authority"]
        outside_changed = int(np.count_nonzero(np.any(delta[outside] != 0, axis=1)))
        protected_person_changed = int(
            np.count_nonzero(np.any(delta[authority["protected_person"]] != 0, axis=1))
        )
        if outside_changed != 0:
            raise ProofError(f"outside-authority pixels changed at frame {frame}: {outside_changed}")
        if protected_person_changed != 0:
            raise ProofError(f"protected person pixels changed at frame {frame}: {protected_person_changed}")

        gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        gray_after = cv2.cvtColor(final, cv2.COLOR_BGR2GRAY)
        x1, y1, x2, y2 = target_bboxes[frame]
        width = max(1, x2 - x1)
        safe_score = (score_masks[frame] > 0).copy()
        safe_score[:, int(x1 + 0.42 * width): int(x1 + 0.78 * width)] = False
        safe_pixels = int(np.count_nonzero(safe_score))
        if safe_pixels < MIN_SAFE_GLYPH_PIXELS:
            raise ProofError(f"safe glyph score unexpectedly small at frame {frame}: {safe_pixels}")
        before_dark = float(np.mean(gray_before[safe_score] < v9.RIGHT_GLYPH_DARK_THRESHOLD))
        after_dark = float(np.mean(gray_after[safe_score] < v9.RIGHT_GLYPH_DARK_THRESHOLD))
        reduction = relative_reduction(before_dark, after_dark)

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
        artifact = visual_artifact_metrics(
            before, final, authority["alpha"], authority["source_caption"], person_masks[frame]
        )
        row = {
            "timeline_frame": frame,
            "outside_authority_changed_pixels": outside_changed,
            "protected_person_changed_pixels": protected_person_changed,
            "final_authority_pixels": int(np.count_nonzero(authority["final_authority"])),
            "person_repair_pixels": int(np.count_nonzero(authority["person_repair"])),
            "source_caption_full_alpha_pixels": int(np.count_nonzero(authority["source_caption"])),
            "safe_glyph_score_pixels": safe_pixels,
            "safe_glyph_dark_ratio_lt140_before": before_dark,
            "safe_glyph_dark_ratio_lt140_after": after_dark,
            "safe_glyph_dark_reduction": reduction,
            "right_source_dark_pixels": right_source_dark_pixels,
            "right_source_dark_survival_lt140": right_survival,
            "right_source_dark_removal": 1.0 - right_survival,
            **artifact,
            "final_sha256": sha256_file(final_path),
        }
        frame_metrics.append(row)

        before_small = cv2.resize(before, (432, 768), interpolation=cv2.INTER_AREA)
        after_small = cv2.resize(final, (432, 768), interpolation=cv2.INTER_AREA)
        cv2.putText(before_small, f"BEFORE frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255,255,255), 2, cv2.LINE_AA)
        cv2.putText(after_small, f"DIFFUERASER frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255,255,255), 2, cv2.LINE_AA)
        video_frames.append(cv2.cvtColor(np.concatenate([before_small, after_small], axis=1), cv2.COLOR_BGR2RGB))

    compare_video = artifact_dir / "COME_BEFORE_AFTER_DIFFUERASER_ROI_V1.mp4"
    imageio.mimwrite(str(compare_video), video_frames, fps=FPS, quality=8)

    sheet_rows = []
    mask_rows = []
    for frame in SENTINELS:
        authority = build_final_alpha(row_masks[frame], compact_masks[frame], score_masks[frame], person_masks[frame])
        mask = authority["final_authority"]
        ys, xs = np.where(mask)
        x1, x2 = max(0, int(xs.min()) - 80), min(1080, int(xs.max()) + 81)
        y1, y2 = max(0, int(ys.min()) - 90), min(1920, int(ys.max()) + 91)
        sheet_rows.append((f"BEFORE {frame}", frames[frame][y1:y2, x1:x2]))
        sheet_rows.append((f"AFTER {frame}", after_images[frame][y1:y2, x1:x2]))
        mask_vis = np.zeros_like(frames[frame])
        mask_vis[:, :, 0] = row_masks[frame]
        mask_vis[:, :, 1] = authority["alpha"]
        mask_vis[:, :, 2] = person_masks[frame]
        mask_rows.append((f"MASK {frame} B=row G=alpha R=person", mask_vis[y1:y2, x1:x2]))
    create_contact_sheet(v9, sheet_rows, artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png")
    create_contact_sheet(v9, mask_rows, artifact_dir / "MASK_CONTACT_SHEET.png")

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "status": "proof_completed_validation_required",
        "architecture": {
            "family": ARCHITECTURE_FAMILY,
            "closed_families": list(CLOSED_ARCHITECTURE_FAMILIES),
            "inference": "official_diffueraser_roi_with_propainter_prior_exact_png_authority_v1",
            "final_composite": "rowfilled_background_plus_source_caption_person_repair_inward_feather_v1",
            "max_model_edge": MAX_MODEL_EDGE,
            "seed": MODEL_SEED,
            "blended": False,
        },
        "source_context": source_context,
        "roi": roi_payload,
        "model_run": model_run,
        "authority": {
            "v9_runner_sha256": EXPECTED_V9_SHA256,
            "foreground_manifest_sha256": sha256_file(foreground_dir / "manifest.json"),
            "frame_range_half_open": [SOURCE_FRAME_START, SOURCE_FRAME_END + 1],
        },
        "thresholds": {
            "min_source_glyph_reduction": MIN_SOURCE_GLYPH_REDUCTION,
            "min_right_glyph_removal": MIN_RIGHT_GLYPH_REMOVAL,
            "max_new_dark_artifact_ratio": MAX_NEW_DARK_ARTIFACT_RATIO,
            "max_new_bright_artifact_ratio": MAX_NEW_BRIGHT_ARTIFACT_RATIO,
            "max_boundary_ring_mae": MAX_BOUNDARY_RING_MAE,
        },
        "input_frames": frame_pre_rows,
        "frame_metrics": frame_metrics,
        "artifacts": {
            "comparison_video": str(compare_video),
            "before_after_contact_sheet": str(artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png"),
            "mask_contact_sheet": str(artifact_dir / "MASK_CONTACT_SHEET.png"),
            "roi_authority": str(artifact_dir / "ROI_AUTHORITY.json"),
            "prior_video": model_run["prior_preserved"],
            "diffueraser_output": model_run["output_video"],
            "diffueraser_log": model_run["log"],
            "final_dir": str(final_dir),
        },
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
    }
    (artifact_dir / "PROOF_RUN_RESULT.json").write_text(
        json.dumps(json_safe(result), indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({"task_id": TASK_ID, "status": result["status"], "artifact_dir": str(artifact_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
