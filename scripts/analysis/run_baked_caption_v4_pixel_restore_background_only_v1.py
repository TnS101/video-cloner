from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path, PurePath

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_baked_caption_video_inpaint_proof_v1 as legacy

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_V4_PIXEL_RESTORE_BACKGROUND_ONLY_V1"
EXPECTED_LEGACY_TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_VIDEO_INPAINT_PROOF_V9"
ARCHITECTURE_FAMILY = "accepted_v4_full_foreground_veto_background_only_propainter_v1"
CLOSED_FAMILIES = (
    "propainter_semantic_split_person_repair_v1",
    "stabilized_source_backed_person_then_background_v1",
)
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
FRAME_COUNT = SOURCE_FRAME_END - SOURCE_FRAME_START + 1
FPS = 24
MIN_RGBA_GLYPH_PERSON_COVERAGE = 0.985
MIN_RGBA_ALPHA_PIXELS = 1500
MIN_SAFE_GLYPH_SCORE_PIXELS = 4000
HOLD_SENTINELS = (434, 438, 443, 448)
SENTINELS = (429, 431, 434, 438, 443, 448, 452)
TAIL_BACKGROUND_START_FRAME = 451
TAIL_CLOSE_WIDTH = 31
TAIL_CLOSE_HEIGHT = 9
TAIL_DILATION_PIXELS = 5
TAIL_FEATHER_SIGMA = 2.0
COMPOSITE_ALPHA_MIN = 1


class ProofError(RuntimeError):
    pass


def _json_safe(value):
    """Convert the runtime result to strict JSON-compatible primitives.

    Path objects are expected in source-context evidence on Windows. Unknown
    object types are rejected instead of being silently stringified.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise ProofError(f"runtime result contains unsupported JSON value: {type(value).__name__}")


def _validate_reused_generated_dir(path: Path) -> Path:
    path = path.resolve()
    if not path.is_dir():
        raise ProofError(f"reused ProPainter frame directory is missing: {path}")
    expected = [path / f"{index:04d}.png" for index in range(FRAME_COUNT)]
    missing = [item.name for item in expected if not item.is_file()]
    if missing:
        raise ProofError(f"reused ProPainter frames are incomplete: {missing}")
    pngs = sorted(path.glob("*.png"))
    if len(pngs) != FRAME_COUNT:
        raise ProofError(f"reused ProPainter frame count mismatch: {len(pngs)}")
    return path


def _require_legacy_contract() -> None:
    if getattr(legacy, "TASK_ID", None) != EXPECTED_LEGACY_TASK_ID:
        raise ProofError(
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
        "load_full_resolution_person_mask",
        "require_right_glyph_probe_population",
        "run_command",
    )
    missing = [name for name in required if not hasattr(legacy, name)]
    if missing:
        raise ProofError(f"legacy helper contract missing symbols: {missing}")


def _load_v4_authority(authority_dir: Path) -> tuple[dict[int, dict], dict]:
    manifest_path = authority_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ProofError(f"missing packaged V4 pixel-restore manifest: {manifest_path}")
    manifest = legacy.load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ProofError("V4 pixel-restore manifest is not an object")
    required_root = {
        "ok": True,
        "task_id": "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3",
        "backend": "resolve_caption_difference_intersect_clean_person_affine",
        "timeline_range_half_open": [426, 454],
        "glyph_authority": "exact_resolve_with_come_minus_without_come_render_difference",
        "person_authority": "canonical_humanseg_anchors_plus_global_affine_only",
        "rgb_authority": "resolve_render_with_target_come_disabled",
    }
    for key, expected in required_root.items():
        if manifest.get(key) != expected:
            raise ProofError(f"unexpected V4 pixel-restore authority {key}: {manifest.get(key)!r}")
    rows = manifest.get("frames")
    if not isinstance(rows, list):
        raise ProofError("V4 pixel-restore frame rows are missing")
    by_frame = {
        int(row["timeline_frame"]): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("timeline_frame"), int)
    }
    expected_frames = set(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1))
    if not expected_frames.issubset(by_frame):
        missing = sorted(expected_frames - set(by_frame))
        raise ProofError(f"V4 pixel-restore authority missing target frames: {missing}")
    return by_frame, manifest


def _read_authority_assets(authority_dir: Path, row: dict, frame: int, target_shape: tuple[int, int]):
    import cv2
    import numpy as np

    person_rel = row.get("person_mask")
    rgba_rel = row.get("rgba")
    person_meta = row.get("person") or {}
    if not isinstance(person_rel, str) or not isinstance(rgba_rel, str):
        raise ProofError(f"V4 authority paths missing at frame {frame}")
    person_path = authority_dir / person_rel
    rgba_path = authority_dir / rgba_rel
    if not person_path.is_file() or not rgba_path.is_file():
        raise ProofError(f"V4 authority asset missing at frame {frame}")
    expected_person_hash = person_meta.get("person_mask_sha256")
    expected_rgba_hash = row.get("rgba_sha256")
    if not isinstance(expected_person_hash, str) or not isinstance(expected_rgba_hash, str):
        raise ProofError(f"V4 authority hashes missing at frame {frame}")
    if legacy.sha256_file(person_path) != expected_person_hash:
        raise ProofError(f"V4 person-mask hash mismatch at frame {frame}")
    if legacy.sha256_file(rgba_path) != expected_rgba_hash:
        raise ProofError(f"V4 RGBA hash mismatch at frame {frame}")

    person = legacy.load_full_resolution_person_mask(person_path, target_shape)
    rgba = cv2.imread(str(rgba_path), cv2.IMREAD_UNCHANGED)
    if rgba is None or rgba.shape != (target_shape[0], target_shape[1], 4):
        raise ProofError(f"unexpected V4 RGBA dimensions at frame {frame}: {None if rgba is None else rgba.shape}")
    alpha = rgba[:, :, 3]
    alpha_pixels = int(np.count_nonzero(alpha))
    if alpha_pixels < MIN_RGBA_ALPHA_PIXELS:
        raise ProofError(f"V4 RGBA alpha unexpectedly small at frame {frame}: {alpha_pixels}")
    return person, rgba


def _run_propainter(
    *,
    python_exe: str,
    propainter_source: Path,
    video_dir: Path,
    mask_dir: Path,
    output_dir: Path,
    log_path: Path,
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
        "540",
        "--height",
        "960",
        "--mask_dilation",
        "0",
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
    valid = [p for p in candidates if p.is_dir() and len(list(p.glob("*.png"))) == FRAME_COUNT]
    if len(valid) != 1:
        raise ProofError(f"expected one ProPainter output frame directory, got: {valid}")
    return valid[0]


def _build_background_alpha(frame: int, inference_mask, compact_source_mask):
    import cv2
    import numpy as np

    inference = inference_mask > 0
    compact = compact_source_mask > 0
    if frame < TAIL_BACKGROUND_START_FRAME:
        alpha = inference.astype(np.uint8) * 255
        mode = "row_filled_background_only"
    else:
        compact_u8 = compact.astype(np.uint8) * 255
        close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (TAIL_CLOSE_WIDTH, TAIL_CLOSE_HEIGHT))
        core = cv2.morphologyEx(compact_u8, cv2.MORPH_CLOSE, close_kernel)
        dilate_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (2 * TAIL_DILATION_PIXELS + 1, 2 * TAIL_DILATION_PIXELS + 1),
        )
        core = cv2.dilate(core, dilate_kernel)
        alpha = cv2.GaussianBlur(core, (0, 0), TAIL_FEATHER_SIGMA).astype(np.float32)
        alpha *= inference.astype(np.float32)
        alpha[(core > 0) & inference] = 255.0
        alpha[~inference] = 0.0
        alpha[alpha < COMPOSITE_ALPHA_MIN] = 0.0
        alpha = np.rint(alpha).clip(0, 255).astype(np.uint8)
        mode = "tail_closed_compact_background_only"
    return alpha, mode


def _alpha_composite(base, overlay_bgr, alpha_u8):
    import numpy as np

    a = alpha_u8.astype(np.float32) / 255.0
    return np.rint(
        base.astype(np.float32) * (1.0 - a[..., None])
        + overlay_bgr.astype(np.float32) * a[..., None]
    ).clip(0, 255).astype(np.uint8)


def _build_foreground_preserve(person_mask, rgba_alpha):
    """Return the full foreground region that ProPainter may never modify.

    The accepted V4 person mask is the primary authority.  The V4 pixel-restore
    alpha is unioned only to retain its finer anti-aliased foreground edge.
    RGB is intentionally *not* taken from the V4 RGBA artifact because that
    artifact was produced from the baked source render; the original source
    pixels are the preservation authority.
    """

    import numpy as np

    person = person_mask > 0
    alpha = rgba_alpha > 0
    preserve = person | alpha
    if not np.any(preserve):
        raise ProofError("empty accepted foreground preserve mask")
    return preserve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--propainter-source", required=True)
    parser.add_argument("--pixel-restore-authority-dir", required=True)
    parser.add_argument(
        "--reuse-generated-dir",
        help="Reuse an already-completed 24-frame ProPainter output directory and skip inference.",
    )
    args = parser.parse_args()

    import cv2
    import imageio.v2 as imageio
    import numpy as np

    _require_legacy_contract()
    repo_root = legacy.resolve_repo_root(args.repo_root)
    artifact_dir = Path(args.artifact_dir).resolve()
    propainter_source = Path(args.propainter_source).resolve()
    authority_dir = Path(args.pixel_restore_authority_dir).resolve()
    reuse_generated_dir = (
        _validate_reused_generated_dir(Path(args.reuse_generated_dir))
        if args.reuse_generated_dir
        else None
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if not (propainter_source / "inference_propainter.py").is_file():
        raise ProofError(f"invalid ProPainter source: {propainter_source}")

    v4_rows, v4_manifest = _load_v4_authority(authority_dir)
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
            raise ProofError(f"missing proof authority file: {path}")

    base_authority = legacy.load_json(failed_run / "base_render_authority.json")
    if not isinstance(base_authority, dict) or base_authority.get("ok") is not True:
        raise ProofError("base render authority is not PASS")
    if base_authority.get("dimensions") != {"frame_rate": 24.0, "height": 1920, "width": 1080}:
        raise ProofError(f"unexpected base render dimensions: {base_authority.get('dimensions')}")
    v3_manifest = legacy.load_json(geometry_run / "generated_pixel_restore_v3" / "manifest.json")
    if not isinstance(v3_manifest, dict) or v3_manifest.get("ok") is not True:
        raise ProofError("unexpected V3 glyph authority")
    v3_by_frame = {
        int(row["timeline_frame"]): row
        for row in (v3_manifest.get("frames") or [])
        if isinstance(row, dict) and isinstance(row.get("timeline_frame"), int)
    }

    anchors = legacy.verify_style_anchors(legacy.load_json(repo_root / legacy.STYLE_REL))
    source_context = legacy.verify_source_context_authority(
        legacy.load_json(repo_root / legacy.SOURCE_TRACK_REL),
        legacy.load_json(repo_root / legacy.LIFECYCLE_REL),
        repo_root,
    )

    input_dir = artifact_dir / "input_frames"
    mask_dir = artifact_dir / "background_masks"
    output_dir = artifact_dir / "propainter_background_output"
    final_dir = artifact_dir / "inpainted_frames"
    reset_directories = [input_dir, mask_dir, final_dir]
    if reuse_generated_dir is None:
        reset_directories.append(output_dir)
    for directory in reset_directories:
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    base_images = {}
    score_masks = {}
    compact_masks = {}
    inference_masks = {}
    person_masks = {}
    rgba_assets = {}
    foreground_preserve_masks = {}
    input_rows = []

    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        base_path = base_dir / f"base_baked_{frame:08d}.png"
        glyph_path = glyph_dir / f"glyph_{frame:06d}.png"
        if not base_path.is_file() or not glyph_path.is_file():
            raise ProofError(f"missing proof input at frame {frame}")
        image = cv2.imread(str(base_path), cv2.IMREAD_COLOR)
        glyph = cv2.imread(str(glyph_path), cv2.IMREAD_GRAYSCALE)
        if image is None or glyph is None or image.shape[:2] != (1920, 1080) or glyph.shape != (1920, 1080):
            raise ProofError(f"invalid proof input dimensions at frame {frame}")
        v3_row = v3_by_frame.get(frame)
        if not isinstance(v3_row, dict):
            raise ProofError(f"missing V3 glyph metadata at frame {frame}")
        expected_glyph_hash = v3_row.get("glyph_mask_sha256")
        if not isinstance(expected_glyph_hash, str) or legacy.sha256_file(glyph_path) != expected_glyph_hash:
            raise ProofError(f"V3 glyph hash mismatch at frame {frame}")
        v4_row = v4_rows[frame]
        if v4_row.get("glyph_mask_sha256") != expected_glyph_hash:
            raise ProofError(f"V4/V3 glyph authority mismatch at frame {frame}")

        target_bbox = legacy.interpolate_bbox(frame, anchors)
        score = legacy.clip_mask_to_bbox(legacy.transform_glyph_mask(glyph, target_bbox), target_bbox)
        compact = legacy.build_compact_caption_masks(image, glyph, target_bbox)
        person, rgba = _read_authority_assets(authority_dir, v4_row, frame, image.shape[:2])

        glyph_core = glyph > 0
        person_core = person > 0
        rgba_alpha = rgba[:, :, 3] > 0
        glyph_person = glyph_core & person_core
        glyph_person_pixels = int(np.count_nonzero(glyph_person))
        if glyph_person_pixels < 1500:
            raise ProofError(f"V4 glyph/person intersection unexpectedly small at frame {frame}: {glyph_person_pixels}")
        rgba_coverage = int(np.count_nonzero(rgba_alpha & glyph_person)) / float(glyph_person_pixels)
        if rgba_coverage < MIN_RGBA_GLYPH_PERSON_COVERAGE:
            raise ProofError(
                f"accepted V4 RGBA coverage too small at frame {frame}: {rgba_coverage:.6f}"
            )

        # Critical architecture boundary: the full accepted foreground is never
        # given to ProPainter, including the COME/person geometric intersection.
        # The baked COME is visually behind the accepted foreground.  Preserve
        # the original source person exactly; use V4 RGBA alpha only to extend
        # the fine foreground edge, never as replacement RGB.
        foreground_preserve = _build_foreground_preserve(person, rgba[:, :, 3])
        row_filled = compact["inpaint_mask"] > 0
        inference = row_filled & ~foreground_preserve
        if not np.any(inference):
            raise ProofError(f"background-only inference mask is empty at frame {frame}")
        if np.any(inference & foreground_preserve):
            raise ProofError(f"background-only inference escaped foreground preserve authority at frame {frame}")

        base_images[frame] = image
        score_masks[frame] = score
        compact_masks[frame] = compact["composite_mask"]
        inference_masks[frame] = inference.astype(np.uint8) * 255
        person_masks[frame] = person
        rgba_assets[frame] = rgba
        foreground_preserve_masks[frame] = foreground_preserve
        sequential = f"{index:04d}.png"
        if not cv2.imwrite(str(input_dir / sequential), image):
            raise ProofError(f"failed to write ProPainter input at frame {frame}")
        if not cv2.imwrite(str(mask_dir / sequential), inference_masks[frame]):
            raise ProofError(f"failed to write ProPainter mask at frame {frame}")
        input_rows.append(
            {
                "timeline_frame": frame,
                "base_sha256": legacy.sha256_file(base_path),
                "glyph_sha256": expected_glyph_hash,
                "person_mask_sha256": (v4_row.get("person") or {}).get("person_mask_sha256"),
                "rgba_sha256": v4_row.get("rgba_sha256"),
                "rgba_alpha_pixels": int(np.count_nonzero(rgba_alpha)),
                "glyph_person_pixels": glyph_person_pixels,
                "rgba_glyph_person_coverage": rgba_coverage,
                "row_filled_mask_pixels": int(np.count_nonzero(row_filled)),
                "background_inference_mask_pixels": int(np.count_nonzero(inference)),
                "foreground_preserve_pixels": int(np.count_nonzero(foreground_preserve)),
                "person_pixels": int(np.count_nonzero(person_core)),
                "inference_person_overlap_pixels": int(np.count_nonzero(inference & person_core)),
                "inference_foreground_preserve_overlap_pixels": int(np.count_nonzero(inference & foreground_preserve)),
                "compact_source_mask_pixels": int(np.count_nonzero(compact["composite_mask"])),
                "dynamic_right_guard_pixels": int(compact["dynamic_right_guard_pixels"]),
            }
        )

    if reuse_generated_dir is not None:
        generated_dir = reuse_generated_dir
        background_generation_mode = "reused_existing_propainter_frames"
        propainter_inference_rerun = 0
    else:
        generated_dir = _run_propainter(
            python_exe=sys.executable,
            propainter_source=propainter_source,
            video_dir=input_dir,
            mask_dir=mask_dir,
            output_dir=output_dir,
            log_path=artifact_dir / "PROPAINTER_BACKGROUND_RUN.log",
        )
        background_generation_mode = "fresh_propainter_inference"
        propainter_inference_rerun = 1

    composite_rows = []
    video_frames = []
    after_images = {}
    for index, frame in enumerate(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        before = base_images[frame]
        generated = cv2.imread(str(generated_dir / f"{index:04d}.png"), cv2.IMREAD_COLOR)
        if generated is None:
            raise ProofError(f"missing ProPainter background output at frame {frame}")
        if generated.shape[:2] != before.shape[:2]:
            generated = cv2.resize(generated, (before.shape[1], before.shape[0]), interpolation=cv2.INTER_CUBIC)

        background_alpha, background_mode = _build_background_alpha(
            frame,
            inference_masks[frame],
            compact_masks[frame],
        )
        final = _alpha_composite(before, generated, background_alpha)

        # Foreground is source-exact.  Do not composite V4 RGBA RGB here: V4
        # supplies mask/alpha authority, while the original frame supplies the
        # accepted person pixels.
        rgba = rgba_assets[frame]
        foreground_preserve = foreground_preserve_masks[frame]
        final[foreground_preserve] = before[foreground_preserve]
        person_context = person_masks[frame] > 0

        final_path = final_dir / f"frame_{frame:06d}.png"
        if not cv2.imwrite(str(final_path), final):
            raise ProofError(f"failed to write final frame {frame}")
        after_images[frame] = final

        delta = cv2.absdiff(before, final)
        final_authority = background_alpha > 0
        outside_changed = int(np.count_nonzero(np.any(delta[~final_authority] != 0, axis=1)))
        if outside_changed != 0:
            raise ProofError(f"outside-authority preservation failed at frame {frame}: {outside_changed}")
        person_context_changed = int(np.count_nonzero(np.any(delta[person_context] != 0, axis=1)))
        if person_context_changed != 0:
            raise ProofError(f"protected person context changed at frame {frame}: {person_context_changed}")
        foreground_preserve_changed = int(
            np.count_nonzero(np.any(delta[foreground_preserve] != 0, axis=1))
        )
        if foreground_preserve_changed != 0:
            raise ProofError(
                f"accepted V4 foreground preserve changed at frame {frame}: {foreground_preserve_changed}"
            )

        gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        gray_after = cv2.cvtColor(final, cv2.COLOR_BGR2GRAY)
        score = score_masks[frame] > 0
        rgba_alpha = rgba[:, :, 3] > 0
        safe_score = score & ~foreground_preserve
        x1, y1, x2, y2 = legacy.interpolate_bbox(frame, anchors)
        width = max(1, x2 - x1)
        safe_score[:, int(x1 + 0.42 * width): int(x1 + 0.78 * width)] = False
        safe_score_pixels = int(np.count_nonzero(safe_score))
        if safe_score_pixels < MIN_SAFE_GLYPH_SCORE_PIXELS:
            raise ProofError(f"background glyph score region unexpectedly small at frame {frame}: {safe_score_pixels}")
        before_dark = float(np.mean(gray_before[safe_score] < 140))
        after_dark = float(np.mean(gray_after[safe_score] < 140))

        probe_x1 = max(x1, x2 - legacy.RIGHT_GLYPH_PROBE_INSIDE_PIXELS)
        authority_xs = np.where(final_authority)[1]
        probe_x2 = max(x2, int(authority_xs.max()) + 1)
        right_probe = np.zeros_like(gray_before, dtype=bool)
        right_probe[y1:y2, probe_x1:probe_x2] = True
        right_source_dark = right_probe & (gray_before < legacy.RIGHT_GLYPH_DARK_THRESHOLD) & ~foreground_preserve
        right_source_dark_pixels = int(np.count_nonzero(right_source_dark))
        legacy.require_right_glyph_probe_population(frame, right_source_dark_pixels)
        right_dark_survival = (
            float(np.mean(gray_after[right_source_dark] < legacy.RIGHT_GLYPH_DARK_THRESHOLD))
            if right_source_dark_pixels > 0
            else 0.0
        )
        composite_rows.append(
            {
                "timeline_frame": frame,
                "background_mode": background_mode,
                "outside_authority_changed_pixels": outside_changed,
                "protected_person_context_changed_pixels": person_context_changed,
                "foreground_preserve_changed_pixels": foreground_preserve_changed,
                "rgba_glyph_person_coverage": input_rows[index]["rgba_glyph_person_coverage"],
                "safe_glyph_score_pixels": safe_score_pixels,
                "safe_glyph_dark_ratio_lt140_before": before_dark,
                "safe_glyph_dark_ratio_lt140_after": after_dark,
                "safe_glyph_dark_reduction": before_dark - after_dark,
                "right_source_dark_pixels": right_source_dark_pixels,
                "right_source_dark_removal": 1.0 - right_dark_survival,
                "final_sha256": legacy.sha256_file(final_path),
            }
        )

        before_small = cv2.resize(before, (432, 768), interpolation=cv2.INTER_AREA)
        after_small = cv2.resize(final, (432, 768), interpolation=cv2.INTER_AREA)
        cv2.putText(before_small, f"BEFORE frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(after_small, f"AFTER frame {frame}", (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
        video_frames.append(cv2.cvtColor(np.concatenate([before_small, after_small], axis=1), cv2.COLOR_BGR2RGB))

    imageio.mimwrite(
        str(artifact_dir / "COME_BEFORE_AFTER_V4_PIXEL_RESTORE_BACKGROUND_ONLY_V1.mp4"),
        video_frames,
        fps=FPS,
        quality=8,
    )

    # Compact sentinel contact sheets.
    before_after_tiles = []
    mask_tiles = []
    for frame in SENTINELS:
        before = base_images[frame]
        after = after_images[frame]
        inf = inference_masks[frame] > 0
        foreground_preserve = foreground_preserve_masks[frame]
        ys, xs = np.where(inf | foreground_preserve)
        cx1, cx2 = max(0, int(xs.min()) - 80), min(before.shape[1], int(xs.max()) + 81)
        cy1, cy2 = max(0, int(ys.min()) - 90), min(before.shape[0], int(ys.max()) + 91)
        for label, image in (("BEFORE", before), ("AFTER", after)):
            crop = image[cy1:cy2, cx1:cx2].copy()
            crop = cv2.resize(crop, (280, 180), interpolation=cv2.INTER_AREA)
            cv2.putText(crop, f"{label} {frame}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
            before_after_tiles.append(crop)
        overlay = before[cy1:cy2, cx1:cx2].copy()
        inf_crop = inf[cy1:cy2, cx1:cx2]
        preserve_crop = foreground_preserve[cy1:cy2, cx1:cx2]
        overlay[inf_crop] = (0, 255, 0)
        overlay[preserve_crop] = (255, 0, 255)
        overlay = cv2.resize(overlay, (280, 180), interpolation=cv2.INTER_NEAREST)
        cv2.putText(overlay, f"MASK {frame}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        mask_tiles.append(overlay)

    # 14 before/after tiles => two rows of 7 pairs.
    ba_row1 = np.concatenate(before_after_tiles[:8], axis=1)
    ba_row2 = np.concatenate(before_after_tiles[8:], axis=1)
    if ba_row2.shape[1] < ba_row1.shape[1]:
        pad = np.zeros((ba_row2.shape[0], ba_row1.shape[1] - ba_row2.shape[1], 3), dtype=np.uint8)
        ba_row2 = np.concatenate([ba_row2, pad], axis=1)
    cv2.imwrite(str(artifact_dir / "BEFORE_AFTER_CONTACT_SHEET.png"), np.concatenate([ba_row1, ba_row2], axis=0))
    cv2.imwrite(str(artifact_dir / "MASK_CONTACT_SHEET.png"), np.concatenate(mask_tiles, axis=1))

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "status": "runtime_complete_pending_validator",
        "architecture": {
            "family": ARCHITECTURE_FAMILY,
            "background_generation_mode": background_generation_mode,
            "closed_families": list(CLOSED_FAMILIES),
            "foreground_rule": "full accepted V4 person mask plus V4 RGBA alpha edge are never inferred; original source RGB is preserved exactly",
            "background_rule": "ProPainter receives only row-filled background pixels outside the full accepted V4 foreground preserve mask",
            "min_rgba_glyph_person_coverage": MIN_RGBA_GLYPH_PERSON_COVERAGE,
        },
        "source_context": source_context,
        "v4_manifest_sha256": legacy.sha256_file(authority_dir / "manifest.json"),
        "input_rows": input_rows,
        "composite_rows": composite_rows,
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
        "propainter_inference_rerun": propainter_inference_rerun,
    }
    json_result = _json_safe(result)
    (artifact_dir / "PROOF_RUN_RESULT.json").write_text(
        json.dumps(json_result, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
