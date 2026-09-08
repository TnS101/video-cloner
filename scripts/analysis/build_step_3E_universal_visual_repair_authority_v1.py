#!/usr/bin/env python3
"""Build a source-pixel repair authority for all current editable captions.

The adapter is reel-specific only in its input artifact paths.  Detection,
tracking, motion stabilisation, fill sampling, size calibration and decorative
text reconciliation live in visual_caption_repair_core.py and contain no cue or
video-specific rules.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

import cv2

TASK_ID = "DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1"
EXPECTED_TOTAL = 117
EXPECTED_REMAINING = 100
EXPECTED_V4 = 17
SEARCH_PAD = 12
REMAINING_AUTHORITY = Path("artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/remaining100_visual_authority_v1.json")
V4_AUTHORITY = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json")
V4_READBACK = Path(
    ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/"
    "20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json"
)
WORD_TRACKS = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json")
DEFAULT_OUTPUT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/"
    "universal_visual_repair_authority_v1.json"
)


class BuildError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BuildError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_core(repo_root: Path):
    path = repo_root / "scripts/analysis/visual_caption_repair_core.py"
    spec = importlib.util.spec_from_file_location("visual_caption_repair_core_runtime", path)
    require(spec is not None and spec.loader is not None, f"core_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VideoSource:
    def __init__(self, path: Path, timeline_fps: float, analysis_dimensions: list[int]):
        self.cap = cv2.VideoCapture(str(path))
        require(self.cap.isOpened(), f"video_open:{path}")
        self.source_fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.source_count = int(round(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        self.timeline_fps = float(timeline_fps)
        self.target_width, self.target_height = [int(v) for v in analysis_dimensions]
        require(self.source_fps > 0 and self.source_count > 0, "video_metadata")
        require(self.target_width > 0 and self.target_height > 0, "analysis_dimensions")
        self.cache: dict[int, Any] = {}

    def source_index(self, timeline_frame: int) -> int:
        index = int(round(float(timeline_frame) * self.source_fps / self.timeline_fps))
        return max(0, min(self.source_count - 1, index))

    def read(self, timeline_frame: int):
        index = self.source_index(timeline_frame)
        if index in self.cache:
            return self.cache[index]
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.cap.read()
        require(ok and frame is not None, f"frame_read:{timeline_frame}:{index}")
        if frame.shape[1] != self.target_width or frame.shape[0] != self.target_height:
            frame = cv2.resize(frame, (self.target_width, self.target_height), interpolation=cv2.INTER_AREA)
        self.cache[index] = frame
        if len(self.cache) > 72:
            self.cache.pop(next(iter(self.cache)))
        return frame

    def close(self) -> None:
        self.cap.release()
        self.cache.clear()


def remaining_seed(row: Mapping[str, Any]) -> dict[str, Any]:
    geometry = row.get("source_pixel_seed") if isinstance(row.get("source_pixel_seed"), Mapping) else {}
    style = row.get("style") if isinstance(row.get("style"), Mapping) else {}
    font = style.get("font") if isinstance(style.get("font"), Mapping) else {}
    window = [int(v) for v in row.get("visual_window") or []]
    require(len(window) == 2 and window[1] > window[0], f"remaining_window:{row.get('instance_id')}")
    return {
        "authority_source": "remaining100_v1",
        "instance_id": str(row.get("instance_id") or ""),
        "target_name": str(row.get("target_name") or ""),
        "canonical_text": str(row.get("canonical_text") or ""),
        "source_cue_ids": [str(v) for v in row.get("source_cue_ids") or []],
        "visual_window": window,
        "center_top_origin": [float(v) for v in geometry.get("center_top_origin") or [0.5, 0.48]],
        "expected_width_px": float(geometry.get("expected_width_px") or 80.0),
        "expected_height_px": float(geometry.get("expected_height_px") or 28.0),
        "seed_fill_hex": str(style.get("fill_hex") or ""),
        "font_family": str(font.get("font_family") or "Verdana"),
        "font_style": str(font.get("font_style") or "Bold"),
        "base_size": float(style.get("base_application_size") or 0.08),
        "text_resolution": {"method": "direct_canonical_instance", "source_instance_ids": [str(row.get("instance_id") or "")]},
    }


def v4_seed(token: Mapping[str, Any], target_name: str) -> dict[str, Any]:
    anchor = token.get("source_pixel_anchor") if isinstance(token.get("source_pixel_anchor"), Mapping) else {}
    bbox = anchor.get("source_bbox_px_540x960")
    if isinstance(bbox, list) and len(bbox) == 4:
        width = max(10.0, float(bbox[2]) - float(bbox[0]))
        height = max(8.0, float(bbox[3]) - float(bbox[1]))
        center = [((float(bbox[0]) + float(bbox[2])) * 0.5) / 540.0, ((float(bbox[1]) + float(bbox[3])) * 0.5) / 960.0]
    else:
        path = token.get("frame_path") or []
        first = path[0] if path else {}
        center = [float(v) for v in first.get("position_top_origin") or [0.5, 0.48]]
        width, height = 90.0, 32.0
    style_lock = token.get("style_lock") if isinstance(token.get("style_lock"), Mapping) else {}
    font = token.get("font") if isinstance(token.get("font"), Mapping) else {}
    window = [int(v) for v in token.get("visual_window") or []]
    require(len(window) == 2 and window[1] > window[0], f"v4_window:{token.get('visual_token_id')}")
    return {
        "authority_source": "v4",
        "instance_id": str(token.get("visual_token_id") or ""),
        "target_name": target_name,
        "canonical_text": str(token.get("display_text") or ""),
        "source_cue_ids": [str(token.get("source_cue_id"))] if token.get("source_cue_id") else [],
        "visual_window": window,
        "center_top_origin": center,
        "expected_width_px": width,
        "expected_height_px": height,
        "seed_fill_hex": str(style_lock.get("fill") or ""),
        "font_family": str(font.get("font_family") or "Verdana"),
        "font_style": str(font.get("font_style") or "Regular"),
        "base_size": float(token.get("application_base_size_candidate") or 0.08),
        "role": str(token.get("role") or ""),
        "visual_kind": str(token.get("visual_kind") or ""),
        "style_lock": dict(style_lock),
        "source_pixel_anchor": dict(anchor),
        "text_resolution": {"method": "direct_v4_source_cue" if token.get("source_cue_id") else "unresolved_visual_layer", "source_instance_ids": []},
        "_source_token": dict(token),
    }


def source_video_path(repo_root: Path, remaining: Mapping[str, Any]) -> Path:
    inputs = remaining.get("inputs") if isinstance(remaining.get("inputs"), Mapping) else {}
    source = inputs.get("source_video") if isinstance(inputs.get("source_video"), Mapping) else {}
    raw = str(source.get("path") or "input/DZsqH7auhjt.mp4")
    path = repo_root / Path(raw)
    require(path.is_file(), f"source_video:{path}")
    expected = str(source.get("sha256") or (remaining.get("source_video") or {}).get("sha256") or "")
    if expected:
        require(sha256(path) == expected, "source_video_sha256")
    return path


def build(repo_root: Path, output_path: Path) -> dict[str, Any]:
    core = load_core(repo_root)
    remaining_path = repo_root / REMAINING_AUTHORITY
    v4_path = repo_root / V4_AUTHORITY
    readback_path = repo_root / V4_READBACK
    word_tracks_path = repo_root / WORD_TRACKS
    for path in (remaining_path, v4_path, readback_path, word_tracks_path):
        require(path.is_file(), f"missing_input:{path}")
    remaining = load_json(remaining_path)
    v4 = load_json(v4_path)
    readback = load_json(readback_path)
    word_tracks = load_json(word_tracks_path)
    remaining_rows = remaining.get("instances") or []
    require(len(remaining_rows) == EXPECTED_REMAINING, f"remaining_count:{len(remaining_rows)}")
    v4_tokens = [token for group in v4.get("groups") or [] for token in group.get("tokens") or [] if isinstance(token, Mapping)]
    require(len(v4_tokens) == EXPECTED_V4, f"v4_count:{len(v4_tokens)}")
    readback_map = {str(row.get("visual_token_id") or ""): str(row.get("target_name") or "") for row in readback.get("rows") or [] if isinstance(row, Mapping)}
    require(len(readback_map) == EXPECTED_V4, f"v4_readback_count:{len(readback_map)}")
    source_tracks = {
        str(row.get("cue_id") or ""): row
        for row in word_tracks.get("tracks") or []
        if isinstance(row, Mapping) and row.get("cue_id")
    }
    require(source_tracks, "word_tracks_empty")

    seeds = [remaining_seed(row) for row in remaining_rows]
    v4_seeds = [v4_seed(token, readback_map.get(str(token.get("visual_token_id") or ""), "")) for token in v4_tokens]
    require(all(seed["target_name"] for seed in seeds + v4_seeds), "target_name")

    # Reconcile only genuinely unmapped decorative script layers. This is text
    # association, not source-presence promotion, and does not authorize repair.
    sibling_texts = {str(seed["canonical_text"]).strip() for seed in v4_seeds if seed["source_cue_ids"]}
    composite_reconciled = 0
    for seed in v4_seeds:
        if seed["source_cue_ids"]:
            continue
        token = seed.get("_source_token") or {}
        resolved = core.reconcile_unmapped_script_text(token, remaining_rows, blocked_texts=sorted(sibling_texts))
        seed["text_resolution"] = resolved
        if resolved.get("ok"):
            seed["canonical_text"] = str(resolved.get("text") or seed["canonical_text"])
            composite_reconciled += 1

    all_seeds = seeds + v4_seeds
    require(len(all_seeds) == EXPECTED_TOTAL, "seed_total")
    calibration = core.build_size_calibration(all_seeds)

    source_path = source_video_path(repo_root, remaining)
    source_meta = remaining.get("source_video") if isinstance(remaining.get("source_video"), Mapping) else {}
    analysis_dimensions = [int(v) for v in source_meta.get("analysis_dimensions") or [540, 960]]
    timeline_fps = float(source_meta.get("timeline_fps") or 24.0)
    video = VideoSource(source_path, timeline_fps, analysis_dimensions)
    instances: list[dict[str, Any]] = []
    try:
        for seed in all_seeds:
            base_style = {
                "font_family": seed["font_family"],
                "font_style": seed["font_style"],
                "historic_fill_seed_hex": seed["seed_fill_hex"],
                "application_size_basis": "robust_reel_font_height_calibration",
            }

            # The human-accepted V4 authority is protected. Structural rows are
            # still counted, but this repair stage cannot rewrite those tokens.
            if seed["authority_source"] == "v4":
                token = seed.get("_source_token") or {}
                anchor = token.get("source_pixel_anchor") if isinstance(token.get("source_pixel_anchor"), Mapping) else {}
                instances.append(
                    {
                        "instance_id": seed["instance_id"],
                        "target_name": seed["target_name"],
                        "authority_source": seed["authority_source"],
                        "canonical_text": seed["canonical_text"],
                        "source_cue_ids": seed["source_cue_ids"],
                        "text_resolution": seed["text_resolution"],
                        "presence_status": "protected_existing",
                        "repair_action": "preserve_existing",
                        "transcript_timing_authority": False,
                        "visual_timing_authority": "approved_source_visual_authority_v4",
                        "seed_window_only": seed["visual_window"],
                        "visual_window": seed["visual_window"],
                        "source_pixel_evidence": {
                            "evidence_kind": "approved_v4_source_visual_authority",
                            "source_pixel_anchor": dict(anchor),
                            "visual_token_id": seed["instance_id"],
                            "source_locked": bool((seed.get("style_lock") or {}).get("source_locked")),
                        },
                        "style": {**base_style, "source_sampled_fill_hex": seed["seed_fill_hex"], "source_sampled_fill_confidence": 1.0},
                        "motion": {
                            "position_model": "preserve_existing",
                            "size_model": "preserve_existing",
                            "opacity_model": "preserve_existing",
                        },
                        "frame_path": [],
                        "explicit_frame_row_count": 0,
                    }
                )
                continue

            semantic = core.ocr_source_presence(
                seed["source_cue_ids"],
                source_tracks,
                analysis_dimensions[0],
                analysis_dimensions[1],
            )
            semantic_public = {key: value for key, value in semantic.items() if key != "tracked"}
            if semantic.get("status") == "confirmed":
                tracked = semantic["tracked"]
                window = [int(v) for v in semantic["window"]]
                frame_path, motion = core.stabilise_path(
                    tracked,
                    window,
                    analysis_dimensions[0],
                    analysis_dimensions[1],
                    seed["font_family"],
                    calibration,
                )
                peak_frame = int(semantic["peak_frame"])
                peak_row = tracked.get(peak_frame) or {}
                fill_hex, fill_conf = core.sample_fill_hex(video.read(peak_frame), peak_row.get("bbox") or [])
                instances.append(
                    {
                        "instance_id": seed["instance_id"],
                        "target_name": seed["target_name"],
                        "authority_source": seed["authority_source"],
                        "canonical_text": seed["canonical_text"],
                        "source_cue_ids": seed["source_cue_ids"],
                        "text_resolution": seed["text_resolution"],
                        "presence_status": "source_confirmed",
                        "repair_action": "repair_from_source_evidence",
                        "transcript_timing_authority": False,
                        "visual_timing_authority": "source_ocr_continuity_observations",
                        "seed_window_only": seed["visual_window"],
                        "visual_window": window,
                        "source_pixel_evidence": {
                            "evidence_kind": "ocr_continuity",
                            **semantic_public,
                            "peak_bbox": peak_row.get("bbox"),
                        },
                        "style": {
                            **base_style,
                            "source_sampled_fill_hex": fill_hex or seed["seed_fill_hex"],
                            "source_sampled_fill_confidence": fill_conf,
                        },
                        "motion": motion,
                        "frame_path": frame_path,
                        "explicit_frame_row_count": len(frame_path),
                    }
                )
                continue

            # A structural Text+ row is not proof that a distinct visual token
            # exists. Geometry-only matching was the source of the prior false
            # positives, so unconfirmed rows stay excluded until semantic source
            # coverage is expanded in a separate detector boundary.
            status = "source_unresolved" if semantic.get("status") == "unresolved" else "source_not_evaluated"
            instances.append(
                {
                    "instance_id": seed["instance_id"],
                    "target_name": seed["target_name"],
                    "authority_source": seed["authority_source"],
                    "canonical_text": seed["canonical_text"],
                    "source_cue_ids": seed["source_cue_ids"],
                    "text_resolution": seed["text_resolution"],
                    "presence_status": status,
                    "repair_action": "exclude_from_repair",
                    "transcript_timing_authority": False,
                    "visual_timing_authority": "unresolved_source_presence",
                    "seed_window_only": seed["visual_window"],
                    "visual_window": None,
                    "source_pixel_evidence": {
                        "evidence_kind": "semantic_presence_gate",
                        "semantic_presence": semantic_public,
                        "reasons": list(semantic_public.get("reasons") or []),
                    },
                    "style": {**base_style, "source_sampled_fill_hex": seed["seed_fill_hex"], "source_sampled_fill_confidence": 0.0},
                    "motion": {
                        "position_model": "not_authorized",
                        "size_model": "not_authorized",
                        "opacity_model": "not_authorized",
                    },
                    "frame_path": [],
                    "explicit_frame_row_count": 0,
                }
            )
    finally:
        video.close()

    target_names = [row["target_name"] for row in instances]
    require(len(target_names) == len(set(target_names)) == EXPECTED_TOTAL, "target_identity")
    statuses = {name: sum(1 for row in instances if row["presence_status"] == name) for name in (
        "protected_existing",
        "source_confirmed",
        "source_unresolved",
        "source_not_evaluated",
    )}
    confirmed_rows = [row for row in instances if row["presence_status"] == "source_confirmed"]
    static_position = sum(1 for row in confirmed_rows if row["motion"]["position_model"] == "source_static_hold")
    static_size = sum(1 for row in confirmed_rows if row["motion"]["size_model"] == "source_static_hold")
    unresolved_script = sum(
        1
        for seed in v4_seeds
        if not seed["source_cue_ids"] and "script" in (str(seed.get("role") or "") + str(seed.get("visual_kind") or "") + str(seed.get("font_family") or "")).lower()
        and not seed["text_resolution"].get("ok")
    )
    result = {
        "schema_version": 2,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "core_is_reel_agnostic": True,
            "primary_authority": "source_video_pixels",
            "transcript_timing_authority": False,
            "raw_detector_score_controls_opacity": False,
            "static_source_motion_collapses_to_hold": True,
            "per_cue_hardcoded_overrides": False,
            "structural_caption_count_requires_positive_visual_presence": False,
            "unresolved_source_presence_is_valid": True,
            "geometry_only_cannot_authorize_repair": True,
            "approved_v4_authority_is_preserved": True,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
            "fade_polish_deferred": True,
        },
        "inputs": {
            "remaining_authority": {"path": str(REMAINING_AUTHORITY), "sha256": sha256(remaining_path)},
            "v4_authority": {"path": str(V4_AUTHORITY), "sha256": sha256(v4_path)},
            "v4_readback": {"path": str(V4_READBACK), "sha256": sha256(readback_path)},
            "word_tracks": {"path": str(WORD_TRACKS), "sha256": sha256(word_tracks_path)},
            "source_video": {"path": str(source_path.relative_to(repo_root)), "sha256": sha256(source_path)},
        },
        "calibration": calibration,
        "summary": {
            "total_instances": len(instances),
            "remaining_instances": EXPECTED_REMAINING,
            "v4_instances": EXPECTED_V4,
            "protected_existing_instances": statuses["protected_existing"],
            "source_confirmed_repair_instances": statuses["source_confirmed"],
            "source_unresolved_instances": statuses["source_unresolved"],
            "source_not_evaluated_instances": statuses["source_not_evaluated"],
            "repair_ready_instances": statuses["source_confirmed"],
            "static_position_instances": static_position,
            "dynamic_position_instances": len(confirmed_rows) - static_position,
            "static_size_instances": static_size,
            "dynamic_size_instances": len(confirmed_rows) - static_size,
            "hold_opacity_instances": len(confirmed_rows),
            "composite_text_reconciled_count": composite_reconciled,
            "unresolved_script_layer_count": unresolved_script,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "instances": instances,
        "semantic_sha256": "",
        "next_boundary": "STEP_3E_EXPAND_SOURCE_SEMANTIC_COVERAGE_BEFORE_REPAIR_ROLLOUT",
    }
    result["semantic_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "semantic_sha256"})
    write_json(output_path, result)
    return result

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / DEFAULT_OUTPUT
    try:
        result = build(root, output)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    summary = result["summary"]
    print(
        f"PASS {TASK_ID}: total={summary['total_instances']} static_position={summary['static_position_instances']} "
        f"static_size={summary['static_size_instances']} composite_reconciled={summary['composite_text_reconciled_count']}"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
