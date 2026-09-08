from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import time
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_LAMA_ROI_PROOF_V1"
ARCHITECTURE_FAMILY = "lama_highres_roi_source_authority_semantic_composite_v1"
ARCHITECTURE_ATTEMPT = 1
PARENT_TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_DIFFUERASER_ROI_PROOF_V1"
PARENT_RUN_ID = "20260816T111310504Z"
PARENT_FAILURE_CLASS = "G_VISUAL"
PARENT_FAILURE_SIGNATURE = "post_inference_visual+persistent_dark_glyph_like_topology_and_pale_rectangular_remnants+technical_pass"
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
FRAME_COUNT = 24
FPS = 24
SENTINELS = (429, 431, 434, 438, 443, 448, 452)
HOLD_SENTINELS = (434, 438, 443, 448)
EXPECTED_DIFFUERASER_HELPER_SHA256 = "ca95ccfa9e9070a8b4f4ade24afd89d441d016eb931476b4e0d30fffd5a7817d"
EXPECTED_MODEL_SHA256 = "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"
EXPECTED_FOREGROUND_MANIFEST_SHA256 = "7b2cd599494c06f12cc22af5f7cb4fd8226f8a8e8a15ffdaac498cf0576e00c6"
MIN_SOURCE_GLYPH_REDUCTION = 0.70
MIN_RIGHT_GLYPH_REMOVAL = 0.75
MAX_NEW_DARK_ARTIFACT_RATIO = 0.03
MAX_NEW_BRIGHT_ARTIFACT_RATIO = 0.03
MAX_BOUNDARY_RING_MAE = 30.0
MIN_SAFE_GLYPH_PIXELS = 4000
CLOSED_ARCHITECTURE_FAMILIES = (
    "propainter_semantic_split_person_repair_v1",
    "stabilized_source_backed_person_then_background_v1",
    "propainter_v4_foreground_veto_background_only_v1",
    "same_frame_rowwise_sky_interpolation_inside_come_authority_minus_semantic_person_v1",
)


class ProofError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_path_default(value: object) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def resolve_repo_root(value: str | None) -> Path:
    root = Path(value).resolve() if value else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        raise ProofError(f"repository root not found: {root}")
    return root


def load_diffueraser_authority_helper(repo_root: Path):
    path = repo_root / "scripts" / "analysis" / "run_baked_caption_diffueraser_roi_proof_v1.py"
    if not path.is_file():
        raise ProofError(f"accepted DiffuEraser authority helper missing: {path}")
    actual = sha256_file(path)
    if actual != EXPECTED_DIFFUERASER_HELPER_SHA256:
        raise ProofError(
            f"DiffuEraser authority helper hash mismatch: expected {EXPECTED_DIFFUERASER_HELPER_SHA256}, got {actual}"
        )
    spec = importlib.util.spec_from_file_location("video_cloner_diffueraser_authority_helper", path)
    if spec is None or spec.loader is None:
        raise ProofError("could not load DiffuEraser authority helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_foreground_authority_dir(repo_root: Path) -> Path:
    roots = [repo_root / "artifacts", repo_root / ".agent" / "reports", repo_root / "data"]
    matches: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("manifest.json"):
            try:
                if sha256_file(path) == EXPECTED_FOREGROUND_MANIFEST_SHA256:
                    matches.append(path.parent.resolve())
            except OSError:
                continue
    unique = sorted(set(matches))
    if len(unique) != 1:
        raise ProofError(
            f"expected exactly one V4 foreground authority manifest {EXPECTED_FOREGROUND_MANIFEST_SHA256}, found {len(unique)}: {unique}"
        )
    return unique[0]


def ceil_modulo(value: int, modulo: int = 8) -> int:
    if modulo <= 0:
        raise ValueError("modulo must be positive")
    return value if value % modulo == 0 else ((value // modulo) + 1) * modulo


def prepare_lama_arrays(image_bgr, mask_gray):
    import numpy as np

    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ProofError(f"LaMa image must be HxWx3 BGR, got {image_bgr.shape}")
    if mask_gray.ndim != 2 or mask_gray.shape != image_bgr.shape[:2]:
        raise ProofError(f"LaMa mask shape mismatch: image={image_bgr.shape}, mask={mask_gray.shape}")
    height, width = image_bgr.shape[:2]
    padded_h = ceil_modulo(height, 8)
    padded_w = ceil_modulo(width, 8)
    rgb = image_bgr[:, :, ::-1].astype(np.float32) / 255.0
    chw = np.transpose(rgb, (2, 0, 1))
    mask = (mask_gray > 0).astype(np.float32)[None, :, :]
    pad_h = padded_h - height
    pad_w = padded_w - width
    chw = np.pad(chw, ((0, 0), (0, pad_h), (0, pad_w)), mode="symmetric")
    mask = np.pad(mask, ((0, 0), (0, pad_h), (0, pad_w)), mode="symmetric")
    mask = (mask > 0).astype(np.float32)
    return chw, mask, (height, width)


def run_lama_inference(model_path: Path, inputs: list[object], masks: list[object], log_path: Path):
    import numpy as np
    import torch

    if sha256_file(model_path) != EXPECTED_MODEL_SHA256:
        raise ProofError("LaMa model SHA-256 mismatch before inference")
    if not torch.cuda.is_available():
        raise ProofError("CUDA unavailable for LaMa proof")
    device = torch.device("cuda:0")
    model = torch.jit.load(str(model_path), map_location=device)
    model.eval().to(device)
    outputs = []
    rows = []
    started = time.perf_counter()
    try:
        for index, (image, mask) in enumerate(zip(inputs, masks, strict=True)):
            chw, mask_chw, original_size = prepare_lama_arrays(image, mask)
            image_tensor = torch.from_numpy(chw).unsqueeze(0).to(device)
            mask_tensor = (torch.from_numpy(mask_chw).unsqueeze(0).to(device) > 0) * 1
            frame_started = time.perf_counter()
            with torch.inference_mode():
                generated = model(image_tensor, mask_tensor)
            torch.cuda.synchronize()
            if list(generated.shape[:2]) != [1, 3]:
                raise ProofError(f"unexpected LaMa output shape at index {index}: {list(generated.shape)}")
            h, w = original_size
            rgb = generated[0, :, :h, :w].permute(1, 2, 0).detach().float().cpu().numpy()
            rgb = np.clip(rgb * 255.0, 0.0, 255.0).astype(np.uint8)
            bgr = rgb[:, :, ::-1].copy()
            if bgr.shape != image.shape:
                raise ProofError(f"LaMa output size mismatch at index {index}: {bgr.shape} vs {image.shape}")
            outputs.append(bgr)
            rows.append({
                "index": index,
                "seconds": time.perf_counter() - frame_started,
                "input_size": [int(image.shape[1]), int(image.shape[0])],
                "padded_size": [int(chw.shape[2]), int(chw.shape[1])],
                "mask_pixels": int(np.count_nonzero(mask)),
            })
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    payload = {
        "task_id": TASK_ID,
        "architecture_family": ARCHITECTURE_FAMILY,
        "model_sha256": EXPECTED_MODEL_SHA256,
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "frame_count": len(outputs),
        "total_seconds": time.perf_counter() - started,
        "frames": rows,
    }
    log_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return outputs, payload


def residual_topology_diagnostic(gray_before, gray_after, safe_score, dark_threshold: int):
    import cv2
    import numpy as np

    region = safe_score > 0
    before_dark = region & (gray_before < dark_threshold)
    after_dark = region & (gray_after < dark_threshold)
    components = []
    binary = after_dark.astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area > 0:
            components.append(area)
    components.sort(reverse=True)
    overlap = int(np.count_nonzero(before_dark & after_dark))
    return {
        "residual_dark_pixels": int(np.count_nonzero(after_dark)),
        "residual_dark_components": len(components),
        "largest_residual_dark_component_pixels": components[0] if components else 0,
        "top5_residual_dark_component_pixels": components[:5],
        "source_dark_overlap_pixels": overlap,
    }


def main() -> int:
    import cv2
    import imageio.v2 as imageio
    import numpy as np

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--lama-model", required=True)
    args = parser.parse_args()

    repo_root = resolve_repo_root(args.repo_root)
    artifact_dir = Path(args.artifact_dir).resolve()
    model_path = Path(args.lama_model).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    helper = load_diffueraser_authority_helper(repo_root)
    v9 = helper.load_v9_authority_module(repo_root)
    foreground_dir = find_foreground_authority_dir(repo_root)

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
        model_path,
    ]
    for path in required:
        if not path.is_file():
            raise ProofError(f"missing authority/runtime file: {path}")

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

    roi = helper.derive_roi(list(row_masks.values()), (1920, 1080))
    rx1, ry1, rx2, ry2 = roi
    roi_w, roi_h = rx2 - rx1, ry2 - ry1
    input_dir = artifact_dir / "roi_input_frames"
    mask_dir = artifact_dir / "roi_inference_masks"
    generated_dir = artifact_dir / "lama_generated_roi_frames"
    final_dir = artifact_dir / "inpainted_frames"
    for directory in (input_dir, mask_dir, generated_dir, final_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    inputs = []
    masks = []
    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        crop = frames[frame][ry1:ry2, rx1:rx2]
        mask_crop = row_masks[frame][ry1:ry2, rx1:rx2]
        inputs.append(crop)
        masks.append(mask_crop)
        if not cv2.imwrite(str(input_dir / f"{index:04d}.png"), crop):
            raise ProofError(f"could not write ROI input frame {frame}")
        if not cv2.imwrite(str(mask_dir / f"{index:04d}.png"), mask_crop):
            raise ProofError(f"could not write ROI mask frame {frame}")

    roi_payload = {
        "task_id": TASK_ID,
        "architecture_family": ARCHITECTURE_FAMILY,
        "architecture_attempt": ARCHITECTURE_ATTEMPT,
        "closed_architecture_families": list(CLOSED_ARCHITECTURE_FAMILIES),
        "roi_xyxy": list(roi),
        "roi_size": [roi_w, roi_h],
        "model_input_policy": "native_roi_padded_to_modulo_8_no_downscale",
        "frame_count": FRAME_COUNT,
    }
    (artifact_dir / "ROI_AUTHORITY.json").write_text(json.dumps(roi_payload, indent=2, sort_keys=True), encoding="utf-8")

    generated_roi_frames, model_run = run_lama_inference(
        model_path, inputs, masks, artifact_dir / "LAMA_RUN.log"
    )
    if len(generated_roi_frames) != FRAME_COUNT:
        raise ProofError(f"LaMa produced {len(generated_roi_frames)} frames, expected {FRAME_COUNT}")

    after_images: dict[int, object] = {}
    frame_metrics = []
    video_frames = []
    raw_video_frames = []
    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        before = frames[frame]
        generated_roi = generated_roi_frames[index]
        generated_path = generated_dir / f"frame_{frame:06d}.png"
        if not cv2.imwrite(str(generated_path), generated_roi):
            raise ProofError(f"could not write generated ROI frame {frame}")
        generated = before.copy()
        generated[ry1:ry2, rx1:rx2] = generated_roi

        authority = helper.build_final_alpha(
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
        reduction = helper.relative_reduction(before_dark, after_dark)

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
        artifact = helper.visual_artifact_metrics(
            before, final, authority["alpha"], authority["source_caption"], person_masks[frame]
        )
        topology = residual_topology_diagnostic(
            gray_before, gray_after, safe_score, v9.RIGHT_GLYPH_DARK_THRESHOLD
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
            **topology,
            "generated_roi_sha256": sha256_file(generated_path),
            "final_sha256": sha256_file(final_path),
        }
        frame_metrics.append(row)

        before_small = cv2.resize(before, (432, 768), interpolation=cv2.INTER_AREA)
        after_small = cv2.resize(final, (432, 768), interpolation=cv2.INTER_AREA)
        cv2.putText(before_small, f"BEFORE frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255,255,255), 2, cv2.LINE_AA)
        cv2.putText(after_small, f"LAMA frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255,255,255), 2, cv2.LINE_AA)
        video_frames.append(cv2.cvtColor(np.concatenate([before_small, after_small], axis=1), cv2.COLOR_BGR2RGB))
        raw_video_frames.append(cv2.cvtColor(generated_roi, cv2.COLOR_BGR2RGB))

    compare_video = artifact_dir / "COME_BEFORE_AFTER_LAMA_ROI_V1.mp4"
    raw_video = artifact_dir / "LAMA_ROI_OUTPUT.mp4"
    imageio.mimwrite(str(compare_video), video_frames, fps=FPS, quality=8)
    imageio.mimwrite(str(raw_video), raw_video_frames, fps=FPS, quality=8)

    sheet_rows = []
    mask_rows = []
    for frame in SENTINELS:
        authority = helper.build_final_alpha(row_masks[frame], compact_masks[frame], score_masks[frame], person_masks[frame])
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
    v9.create_contact_sheet(sheet_rows, artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png")
    v9.create_contact_sheet(mask_rows, artifact_dir / "MASK_CONTACT_SHEET.png")

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "status": "proof_completed_validation_required",
        "architecture": {
            "family": ARCHITECTURE_FAMILY,
            "attempt": ARCHITECTURE_ATTEMPT,
            "inference": "big_lama_torchscript_native_roi_per_frame_cuda_v1",
            "conditioning": "same_frame_source_plus_row_filled_caption_mask_no_propainter_prior",
            "model_input_policy": "native_roi_padded_to_modulo_8_no_downscale",
            "final_composite": "accepted_diffueraser_v1_source_person_authority_helper_exact_hash",
            "closed_families": list(CLOSED_ARCHITECTURE_FAMILIES),
            "parent_failure_class": PARENT_FAILURE_CLASS,
            "parent_failure_signature": PARENT_FAILURE_SIGNATURE,
        },
        "source_context": source_context,
        "roi": roi_payload,
        "model_run": model_run,
        "authority": {
            "diffueraser_helper_sha256": EXPECTED_DIFFUERASER_HELPER_SHA256,
            "foreground_authority_dir": str(foreground_dir),
            "foreground_manifest_sha256": EXPECTED_FOREGROUND_MANIFEST_SHA256,
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
            "raw_lama_video": str(raw_video),
            "before_after_contact_sheet": str(artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png"),
            "mask_contact_sheet": str(artifact_dir / "MASK_CONTACT_SHEET.png"),
            "roi_authority": str(artifact_dir / "ROI_AUTHORITY.json"),
            "lama_log": str(artifact_dir / "LAMA_RUN.log"),
            "generated_dir": str(generated_dir),
            "final_dir": str(final_dir),
        },
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
    }
    (artifact_dir / "PROOF_RUN_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=json_path_default), encoding="utf-8"
    )
    print(json.dumps({"task_id": TASK_ID, "status": result["status"], "artifact_dir": str(artifact_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
