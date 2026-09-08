#!/usr/bin/env python3
"""Recover unresolved caption visual layers from accepted source evidence.

Offline-only authority stage. It never touches Resolve.

Recovery is deliberately conservative and generic:
1. strict source OCR semantics with multi-frame support;
2. exact adjacent compound-OCR decomposition with partitioned geometry;
3. source-template transfer from an already accepted V4 visual-only text
   prototype having the same compact display text.

Negative OCR never proves source absence. Geometry alone never promotes a
semantic caption. Remaining rows stay unresolved with probe evidence for the
next omission/non-caption classification boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1"
VF = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json")
SEMANTIC = Path("artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_v1.json")
UNIVERSAL = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/universal_visual_repair_authority_v1.json")
V4 = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json")
V2_BUILDER = Path("scripts/analysis/build_step_3E_visual_fidelity_authority_v2.py")
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_v1.json")
ACCEPTED_VF_SHA256 = "6f7cdf265dcb18611e7f6326d7d12de7a3dade7b2a7b6d33e1d406d5645ca6f5"
EXPECTED_UNRESOLVED = 23
EXPECTED_STRUCTURAL = 117
EXPECTED_PHYSICAL = 114
TIMELINE_FPS = 24.0
REF_WIDTH = 540
REF_HEIGHT = 960
PROTOTYPE_STRONG_SCORE = 0.60
PROTOTYPE_PEAK_SCORE = 0.70
PROTOTYPE_SELF_SCORE = 0.80
PROTOTYPE_MIN_SUPPORT = 3
OCR_MIN_CONFIDENCE = 0.22
OCR_RECOVERY_MIN_SUPPORT = 2
OCR_EXACT_RECOVERY_MIN_CONFIDENCE = 0.50


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
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def median(values: Sequence[float], default: float = 0.0) -> float:
    return float(statistics.median(values)) if values else float(default)


def load_module(path: Path, name: str):
    require(path.is_file(), f"module_missing:{path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module_spec:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalized_path(value: Any) -> Path:
    return Path(str(value or "").replace("\\", "/"))


def flatten_v4(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in value.get("groups") or []:
        if not isinstance(group, Mapping):
            continue
        for token in group.get("tokens") or []:
            if isinstance(token, Mapping):
                rows.append(dict(token))
    return rows


def accepted_visual_prototypes(v4: Mapping[str, Any], v2: Any) -> list[dict[str, Any]]:
    result = []
    for token in flatten_v4(v4):
        if str(token.get("visual_kind") or "") != "visual_only_text_decoration":
            continue
        display = str(token.get("display_text") or "")
        anchor = token.get("source_pixel_anchor") if isinstance(token.get("source_pixel_anchor"), Mapping) else {}
        bbox = anchor.get("source_bbox_px_540x960")
        frame = anchor.get("reference_frame")
        if not v2.compact_text(display) or not isinstance(bbox, list) or len(bbox) != 4 or frame is None:
            continue
        result.append({
            "prototype_id": str(token.get("visual_token_id") or ""),
            "display_text": display,
            "compact_text": v2.compact_text(display),
            "reference_frame": int(frame),
            "source_bbox_ref": [int(round(float(v))) for v in bbox],
            "font": dict(token.get("font") or {}),
            "style_lock": dict(token.get("style_lock") or {}),
            "role": str(token.get("role") or ""),
            "visual_kind": str(token.get("visual_kind") or ""),
        })
    return result


def v2_input_entry(vf: Mapping[str, Any], suffix: str) -> Mapping[str, Any]:
    for key, row in (vf.get("inputs") or {}).items():
        if str(key).replace("\\", "/").endswith(suffix.replace("\\", "/")) and isinstance(row, Mapping):
            return row
    raise BuildError(f"vf_input_missing:{suffix}")


def verify_lineage(repo_root: Path, vf: Mapping[str, Any]) -> tuple[Path, Path]:
    require(sha256(repo_root / VF) == ACCEPTED_VF_SHA256, "accepted_vf_sha256")
    require(vf.get("ok") is True, "vf_ok")
    require((vf.get("policy") or {}).get("transcript_timing_authority") is False, "vf_transcript")
    require((vf.get("policy") or {}).get("geometry_only_semantic_promotion") is False, "vf_geometry_promotion")
    require(int((vf.get("summary") or {}).get("unresolved_preserved") or 0) == EXPECTED_UNRESOLVED, "vf_unresolved")
    require(int((vf.get("summary") or {}).get("structural_total") or 0) == EXPECTED_STRUCTURAL, "vf_structural")
    require(int((vf.get("summary") or {}).get("physical_textplus") or 0) == EXPECTED_PHYSICAL, "vf_physical")

    source = v2_input_entry(vf, "source_video")
    source_path = repo_root / normalized_path(source.get("path"))
    require(source_path.is_file(), f"source_video:{source_path}")
    require(sha256(source_path) == str(source.get("sha256") or ""), "source_video_sha256")

    ocr = v2_input_entry(vf, "scripts/davinci/redetect_caption_word_instances_step_3B_6.py")
    ocr_path = repo_root / normalized_path(ocr.get("path"))
    require(ocr_path.is_file(), f"ocr_module:{ocr_path}")
    require(sha256(ocr_path) == str(ocr.get("sha256") or ""), "ocr_module_sha256")
    return source_path, ocr_path


def candidate_dict(candidate: Any, timeline_frame: int, source_frame: int, width: int, height: int, v2: Any) -> dict[str, Any]:
    bbox = [float(v) for v in getattr(candidate, "bbox", [0, 0, 1, 1])]
    return {
        "timeline_frame": int(timeline_frame),
        "source_frame": int(source_frame),
        "ocr_text": str(getattr(candidate, "text", "")),
        "ocr_source_text": str(getattr(candidate, "source_text", "")),
        "ocr_confidence": round(float(getattr(candidate, "confidence", 0.0)), 6),
        "candidate_kind": str(getattr(candidate, "source_kind", "")),
        "normalized_bbox": v2.normalized_bbox(bbox, width, height),
    }


def scan_ocr_frames(
    source_path: Path,
    ocr_module: Any,
    frames: Sequence[int],
    lang: str,
    device: str,
    gpu_id: int,
    min_confidence: float,
) -> tuple[dict[int, list[dict[str, Any]]], Mapping[str, Any]]:
    engine, info = ocr_module.create_ocr(lang, device, gpu_id)
    cap = cv2.VideoCapture(str(source_path))
    require(cap.isOpened(), f"video_open:{source_path}")
    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    source_count = int(round(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
    width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0))
    height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
    require(source_fps > 0 and source_count > 0 and width > 0 and height > 0, "video_meta")
    result: dict[int, list[dict[str, Any]]] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="vc_unresolved_ocr_") as temp_name:
            temp_dir = Path(temp_name)
            for index, timeline_frame in enumerate(sorted(set(int(v) for v in frames)), start=1):
                source_frame = max(0, min(source_count - 1, int(round(timeline_frame * source_fps / TIMELINE_FPS))))
                cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
                ok, frame = cap.read()
                require(ok and frame is not None, f"ocr_frame:{timeline_frame}")
                ocr_frame, scale_x, scale_y = ocr_module.resize_for_ocr(frame, 1440)
                parsed = ocr_module.parse_paddle_result(ocr_module.run_ocr(engine, ocr_frame, temp_dir, f"unresolved_{timeline_frame}"))
                candidates = ocr_module.build_candidates(parsed, scale_x, scale_y, width, height, min_confidence)
                result[timeline_frame] = [candidate_dict(c, timeline_frame, source_frame, width, height, load_v2_cached) for c in candidates]
                if index % 25 == 0 or index == len(set(frames)):
                    print(f"[unresolved-recovery] OCR {index}/{len(set(frames))}", flush=True)
    finally:
        cap.release()
    return result, info


# Assigned after V2 module loading. Keeping it module-global avoids repeatedly
# threading a helper-only dependency through Paddle candidate conversion.
load_v2_cached: Any = None


def member_spans(instance_id: str, ordered_ids: Sequence[str], canonical_by_id: Mapping[str, str], v2: Any) -> list[dict[str, Any]]:
    try:
        index = list(ordered_ids).index(instance_id)
    except ValueError:
        return []
    spans = []
    for length in (2, 3):
        for start in range(max(0, index - length + 1), min(index + 1, len(ordered_ids) - length + 1)):
            ids = list(ordered_ids[start:start + length])
            if instance_id not in ids:
                continue
            compacts = [v2.compact_text(canonical_by_id.get(i, "")) for i in ids]
            if all(compacts):
                spans.append({"member_instance_ids": ids, "compact_concat": "".join(compacts)})
    return spans


def partition_bbox_for_member(
    bbox: Sequence[float],
    member_ids: Sequence[str],
    target_id: str,
    canonical_by_id: Mapping[str, str],
    v2: Any,
) -> list[float]:
    require(target_id in member_ids, "partition_member")
    units = [float(v2.token_units(canonical_by_id[i])) for i in member_ids]
    total = max(1e-6, sum(units))
    x0, y0, x1, y1 = [float(v) for v in bbox]
    width = x1 - x0
    before = sum(units[:member_ids.index(target_id)]) / total
    through = sum(units[:member_ids.index(target_id) + 1]) / total
    return [x0 + width * before, y0, x0 + width * through, y1]


def semantic_recovery(
    instance_id: str,
    canonical: str,
    candidate_rows: Sequence[Mapping[str, Any]],
    ordered_ids: Sequence[str],
    canonical_by_id: Mapping[str, str],
    v2: Any,
) -> dict[str, Any] | None:
    strict = [
        dict(row) for row in candidate_rows
        if float(row.get("ocr_confidence") or 0.0) >= OCR_EXACT_RECOVERY_MIN_CONFIDENCE
        and v2.strict_ocr_semantic_match(canonical, row.get("ocr_text"), float(row.get("ocr_confidence") or 0.0))
    ]
    strict_frames = sorted({int(row["timeline_frame"]) for row in strict})
    if len(strict_frames) >= OCR_RECOVERY_MIN_SUPPORT:
        strict.sort(key=lambda r: (float(r.get("ocr_confidence") or 0.0), v2.compact_text(r.get("ocr_text")) == v2.compact_text(canonical)), reverse=True)
        return {
            "classification": "source_semantic_recovered",
            "basis": "strict_source_ocr_multiframe",
            "support_frames": strict_frames,
            "support": len(strict_frames),
            "observations": strict,
            "display_text": str(strict[0].get("ocr_text") or canonical),
            "geometry_partitioned_from_compound": False,
        }

    spans = member_spans(instance_id, ordered_ids, canonical_by_id, v2)
    for span in spans:
        matched = [dict(row) for row in candidate_rows if v2.compact_text(row.get("ocr_text")) == span["compact_concat"] and float(row.get("ocr_confidence") or 0.0) >= 0.85]
        frames = sorted({int(row["timeline_frame"]) for row in matched})
        if len(frames) < OCR_RECOVERY_MIN_SUPPORT:
            continue
        observations = []
        for row in matched:
            item = dict(row)
            item["full_compound_normalized_bbox"] = list(item["normalized_bbox"])
            item["normalized_bbox"] = partition_bbox_for_member(item["normalized_bbox"], span["member_instance_ids"], instance_id, canonical_by_id, v2)
            observations.append(item)
        return {
            "classification": "source_compound_semantic_recovered",
            "basis": "exact_adjacent_compound_ocr_multiframe_partition",
            "member_instance_ids": span["member_instance_ids"],
            "compact_concat": span["compact_concat"],
            "support_frames": frames,
            "support": len(frames),
            "observations": observations,
            "display_text": canonical,
            "geometry_partitioned_from_compound": True,
        }
    return None


class VideoSource:
    def __init__(self, path: Path):
        self.cap = cv2.VideoCapture(str(path))
        require(self.cap.isOpened(), f"video_open:{path}")
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.count = int(round(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        require(self.fps > 0 and self.count > 0, "video_meta")

    def read_ref(self, timeline_frame: int) -> np.ndarray:
        source_frame = max(0, min(self.count - 1, int(round(int(timeline_frame) * self.fps / TIMELINE_FPS))))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
        ok, frame = self.cap.read()
        require(ok and frame is not None, f"video_frame:{timeline_frame}")
        if frame.shape[1] == REF_WIDTH and frame.shape[0] == REF_HEIGHT:
            return frame
        return cv2.resize(frame, (REF_WIDTH, REF_HEIGHT), interpolation=cv2.INTER_AREA)

    def close(self) -> None:
        self.cap.release()


def highpass(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (0, 0), 2.0)
    value = cv2.absdiff(gray, blur)
    return cv2.normalize(value, None, 0, 255, cv2.NORM_MINMAX)


def representative_bbox(row: Mapping[str, Any]) -> list[int] | None:
    box = row.get("median_source_bbox_ref")
    if isinstance(box, list) and len(box) == 4:
        return [int(round(float(v))) for v in box]
    path = [p for p in row.get("frame_path") or [] if isinstance(p, Mapping) and isinstance(p.get("source_bbox_ref"), list)]
    if path:
        boxes = [p["source_bbox_ref"] for p in path]
        return [int(round(median([float(b[i]) for b in boxes]))) for i in range(4)]
    return None


def nearest_anchor_context(instance_id: str, ordered_ids: Sequence[str], repairs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    index = list(ordered_ids).index(instance_id)
    choices = []
    for direction in (-1, 1):
        pos = index + direction
        while 0 <= pos < len(ordered_ids):
            rid = ordered_ids[pos]
            row = repairs.get(rid)
            if row is not None and isinstance(row.get("visual_window"), list):
                box = representative_bbox(row)
                if box is not None:
                    choices.append((abs(pos - index), 0 if direction < 0 else 1, rid, row, box))
                break
            pos += direction
    choices.sort(key=lambda x: (x[0], x[1]))
    if not choices:
        return {"anchor_instance_id": None, "anchor_visual_window": None, "anchor_bbox_ref": None}
    _, _, rid, row, box = choices[0]
    return {"anchor_instance_id": rid, "anchor_visual_window": list(row["visual_window"]), "anchor_bbox_ref": box}


def prototype_search_roi(anchor_bbox: Sequence[int] | None) -> list[int]:
    if anchor_bbox is None:
        return [20, 100, REF_WIDTH - 20, int(REF_HEIGHT * 0.68)]
    x0, y0, x1, y1 = [int(v) for v in anchor_bbox]
    w, h = max(8, x1 - x0), max(8, y1 - y0)
    return [
        max(0, int(round(x0 - 0.75 * w))),
        max(0, int(round(y0 - 2.6 * h))),
        min(REF_WIDTH, int(round(x1 + 0.75 * w))),
        min(REF_HEIGHT, int(round(y1 + 1.6 * h))),
    ]


def cross_template_rows(video: VideoSource, prototype: Mapping[str, Any], frames: Sequence[int], roi_box: Sequence[int]) -> tuple[list[dict[str, Any]], float]:
    px0, py0, px1, py1 = [int(v) for v in prototype["source_bbox_ref"]]
    anchor = video.read_ref(int(prototype["reference_frame"]))
    anchor_filtered = highpass(cv2.cvtColor(anchor, cv2.COLOR_BGR2GRAY))
    template = anchor_filtered[py0:py1, px0:px1].copy()
    require(template.shape[0] >= 4 and template.shape[1] >= 4, "prototype_template_bbox")

    # Self-consistency is mandatory before a V4 source crop can become a style
    # prototype. This guards stale/misaligned prototype geometry.
    self_roi = anchor_filtered[max(0, py0 - 30):min(REF_HEIGHT, py1 + 30), max(0, px0 - 30):min(REF_WIDTH, px1 + 30)]
    self_response = cv2.matchTemplate(self_roi, template, cv2.TM_CCOEFF_NORMED)
    _, self_score, _, _ = cv2.minMaxLoc(self_response)
    require(float(self_score) >= PROTOTYPE_SELF_SCORE, f"prototype_self_score:{prototype['prototype_id']}:{self_score}")

    x0, y0, x1, y1 = [int(v) for v in roi_box]
    rows = []
    scales = [0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.30, 1.40, 1.50]
    base_h, base_w = template.shape[:2]
    for timeline_frame in sorted(set(int(v) for v in frames)):
        image = video.read_ref(timeline_frame)
        filtered = highpass(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        roi = filtered[y0:y1, x0:x1]
        best = None
        for scale in scales:
            tw, th = max(4, int(round(base_w * scale))), max(4, int(round(base_h * scale)))
            if tw >= roi.shape[1] or th >= roi.shape[0]:
                continue
            resized = cv2.resize(template, (tw, th), interpolation=cv2.INTER_LINEAR)
            response = cv2.matchTemplate(roi, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(response)
            adjusted = float(score) - 0.025 * abs(math.log(scale))
            bbox = [x0 + location[0], y0 + location[1], x0 + location[0] + tw, y0 + location[1] + th]
            candidate = (adjusted, scale, bbox)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is not None:
            rows.append({
                "timeline_frame": timeline_frame,
                "score": round(float(best[0]), 6),
                "scale": round(float(best[1]), 6),
                "bbox_ref": [int(v) for v in best[2]],
            })
    return rows, round(float(self_score), 6)


def strongest_consecutive_run(rows: Sequence[Mapping[str, Any]], threshold: float) -> list[dict[str, Any]]:
    strong = {int(row["timeline_frame"]): dict(row) for row in rows if float(row.get("score") or 0.0) >= threshold}
    if not strong:
        return []
    best: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    last = None
    for frame in sorted(strong):
        if last is None or frame == last + 1:
            current.append(strong[frame])
        else:
            if len(current) > len(best):
                best = current
            current = [strong[frame]]
        last = frame
    if len(current) > len(best):
        best = current
    return best


def prototype_recovery(
    instance_id: str,
    canonical: str,
    prototypes: Sequence[Mapping[str, Any]],
    search_frames: Sequence[int],
    anchor_context: Mapping[str, Any],
    video: VideoSource,
    v2: Any,
) -> dict[str, Any] | None:
    matching = [row for row in prototypes if row.get("compact_text") == v2.compact_text(canonical)]
    if not matching:
        return None
    roi = prototype_search_roi(anchor_context.get("anchor_bbox_ref"))
    passed = []
    for prototype in matching:
        rows, self_score = cross_template_rows(video, prototype, search_frames, roi)
        run = strongest_consecutive_run(rows, PROTOTYPE_STRONG_SCORE)
        if len(run) < PROTOTYPE_MIN_SUPPORT:
            continue
        peak = max(float(row["score"]) for row in run)
        if peak < PROTOTYPE_PEAK_SCORE:
            continue
        centers = [((r["bbox_ref"][0] + r["bbox_ref"][2]) * 0.5, (r["bbox_ref"][1] + r["bbox_ref"][3]) * 0.5) for r in run]
        steps = [math.hypot(centers[i][0] - centers[i-1][0], centers[i][1] - centers[i-1][1]) for i in range(1, len(centers))]
        heights = [float(r["bbox_ref"][3] - r["bbox_ref"][1]) for r in run]
        max_step = max(steps) if steps else 0.0
        if max_step > max(18.0, median(heights) * 0.55):
            continue
        passed.append((median([float(r["score"]) for r in run]), peak, prototype, run, self_score))
    if not passed:
        return None
    passed.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if len(passed) > 1 and passed[0][0] - passed[1][0] < 0.08:
        return None
    med, peak, prototype, run, self_score = passed[0]
    return {
        "classification": "source_visual_companion_recovered",
        "basis": "accepted_v4_visual_only_source_template_multiframe",
        "prototype_id": prototype["prototype_id"],
        "prototype_display_text": prototype["display_text"],
        "prototype_self_score": self_score,
        "support": len(run),
        "support_frames": [int(r["timeline_frame"]) for r in run],
        "median_match_score": round(float(med), 6),
        "peak_match_score": round(float(peak), 6),
        "visual_window": [int(run[0]["timeline_frame"]), int(run[-1]["timeline_frame"]) + 1],
        "frame_path": [dict(r) for r in run],
        "display_text": prototype["display_text"],
        "font": dict(prototype["font"]),
        "style_lock": dict(prototype["style_lock"]),
        "visual_kind": prototype["visual_kind"],
        "role": prototype["role"],
        "neighbor_context": dict(anchor_context),
        "search_roi_ref": roi,
        "semantic_promotion": False,
    }


def build(repo_root: Path, output_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    global load_v2_cached
    for rel in (VF, SEMANTIC, UNIVERSAL, V4, V2_BUILDER):
        require((repo_root / rel).is_file(), f"missing_input:{rel}")
    vf = load_json(repo_root / VF)
    semantic = load_json(repo_root / SEMANTIC)
    universal = load_json(repo_root / UNIVERSAL)
    v4 = load_json(repo_root / V4)
    source_path, ocr_path = verify_lineage(repo_root, vf)
    v2 = load_module(repo_root / V2_BUILDER, "vc_visual_fidelity_v2_recovery_dependency")
    load_v2_cached = v2
    ocr_module = load_module(ocr_path, "vc_unresolved_recovery_ocr")

    require((semantic.get("policy") or {}).get("transcript_timing_authority") is False, "semantic_transcript")
    unresolved_rows = [dict(row) for row in semantic.get("coverage") or [] if isinstance(row, Mapping) and row.get("coverage_status") == "source_unresolved"]
    require(len(unresolved_rows) == EXPECTED_UNRESOLVED, "unresolved_count")

    universal_rows = [dict(row) for row in universal.get("instances") or [] if isinstance(row, Mapping)]
    ordered_ids = [str(row.get("instance_id") or "") for row in universal_rows]
    canonical_by_id = {str(row.get("instance_id") or ""): str(row.get("canonical_text") or "") for row in universal_rows}
    repairs = {str(row.get("instance_id") or ""): row for row in vf.get("repair_instances") or [] if isinstance(row, Mapping)}
    prototypes = accepted_visual_prototypes(v4, v2)
    require(bool(prototypes), "visual_prototypes_empty")

    frames_needed = []
    row_frames: dict[str, list[int]] = {}
    row_template_frames: dict[str, list[int]] = {}
    for row in unresolved_rows:
        instance_id = str(row.get("instance_id") or "")
        prior = row.get("search_prior") if isinstance(row.get("search_prior"), Mapping) else {}
        selected = [int(v) for v in prior.get("probe_frames") or []]
        search = prior.get("source_pixel_search_window")
        if isinstance(search, list) and len(search) == 2:
            # OCR stays sampled for cost, while accepted visual-prototype
            # matching scans the complete source-pixel search interval because
            # template transfer is cheap and a short companion can sit between
            # OCR sample frames.
            start, end = int(search[0]), int(search[1])
            selected.extend([start, max(start, (start + end - 1) // 2), max(start, end - 1)])
            row_template_frames[instance_id] = list(range(max(0, start), max(0, end)))
        else:
            row_template_frames[instance_id] = list(selected)
        selected = sorted(set(v for v in selected if v >= 0))
        require(bool(selected), f"probe_frames:{instance_id}")
        row_frames[instance_id] = selected
        frames_needed.extend(selected)

    print(f"[unresolved-recovery] scanning {len(set(frames_needed))} unique OCR frames for {EXPECTED_UNRESOLVED} unresolved rows", flush=True)
    candidate_by_frame, ocr_info = scan_ocr_frames(source_path, ocr_module, frames_needed, args.ocr_lang, args.ocr_device, args.ocr_gpu_id, args.min_ocr_confidence)

    video = VideoSource(source_path)
    classifications = []
    try:
        for index, semantic_row in enumerate(unresolved_rows, start=1):
            instance_id = str(semantic_row.get("instance_id") or "")
            canonical = str(semantic_row.get("canonical_text") or canonical_by_id.get(instance_id) or "")
            require(canonical, f"canonical:{instance_id}")
            frames = row_frames[instance_id]
            candidates = [dict(c) for frame in frames for c in candidate_by_frame.get(frame, [])]
            recovered = semantic_recovery(instance_id, canonical, candidates, ordered_ids, canonical_by_id, v2)
            anchor_context = nearest_anchor_context(instance_id, ordered_ids, repairs)
            if recovered is None:
                recovered = prototype_recovery(instance_id, canonical, prototypes, row_template_frames[instance_id], anchor_context, video, v2)
            compact_candidates = []
            for row in candidates:
                if float(row.get("ocr_confidence") or 0.0) < 0.50:
                    continue
                compact_candidates.append({
                    "timeline_frame": int(row["timeline_frame"]),
                    "text": str(row.get("ocr_text") or ""),
                    "confidence": round(float(row.get("ocr_confidence") or 0.0), 6),
                    "normalized_bbox": list(row.get("normalized_bbox") or []),
                })
            compact_candidates.sort(key=lambda r: (r["timeline_frame"], -r["confidence"], r["text"]))
            base = {
                "instance_id": instance_id,
                "canonical_text": canonical,
                "input_coverage_status": "source_unresolved",
                "source_pixel_search_prior": dict(semantic_row.get("search_prior") or {}),
                "probe_frames_scanned": frames,
                "high_confidence_ocr_candidates": compact_candidates,
                "neighbor_context": anchor_context,
                "transcript_timing_authority": False,
                "resolve_application_authorized": False,
            }
            if recovered is None:
                base.update({
                    "classification": "source_unresolved_after_recovery",
                    "basis": "no_safe_semantic_compound_or_accepted_visual_prototype_recovery",
                    "semantic_promotion": False,
                    "negative_ocr_promoted_to_absence": False,
                })
            else:
                base.update(recovered)
            classifications.append(base)
            print(f"[unresolved-recovery] {index}/{EXPECTED_UNRESOLVED} {instance_id} -> {base['classification']}", flush=True)
    finally:
        video.close()

    counts = defaultdict(int)
    for row in classifications:
        counts[str(row["classification"])] += 1
    require(sum(counts.values()) == EXPECTED_UNRESOLVED, "classification_total")
    require(counts["source_visual_companion_recovered"] >= 1, "visual_companion_recovery_missing")

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "primary_authority": "accepted_visual_fidelity_v2_plus_source_pixels",
            "transcript_timing_authority": False,
            "per_cue_hardcoded_overrides": False,
            "screenshot_specific_overrides": False,
            "geometry_only_semantic_promotion": False,
            "negative_ocr_promoted_to_absence": False,
            "semantic_recovery_requires_multiframe_source_ocr": True,
            "compound_recovery_requires_exact_adjacent_concat": True,
            "visual_companion_requires_accepted_v4_source_prototype": True,
            "visual_companion_semantic_promotion": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "inputs": {
            str(VF): {"path": str(VF), "sha256": sha256(repo_root / VF)},
            str(SEMANTIC): {"path": str(SEMANTIC), "sha256": sha256(repo_root / SEMANTIC)},
            str(UNIVERSAL): {"path": str(UNIVERSAL), "sha256": sha256(repo_root / UNIVERSAL)},
            str(V4): {"path": str(V4), "sha256": sha256(repo_root / V4)},
            "source_video": {"path": str(source_path.relative_to(repo_root)), "sha256": sha256(source_path)},
            "ocr_module": {"path": str(ocr_path.relative_to(repo_root)), "sha256": sha256(ocr_path)},
        },
        "configuration": {
            "ocr_lang": args.ocr_lang,
            "ocr_device": ocr_info.get("selected_device"),
            "min_ocr_confidence": args.min_ocr_confidence,
            "ocr_recovery_min_support": OCR_RECOVERY_MIN_SUPPORT,
            "ocr_exact_recovery_min_confidence": OCR_EXACT_RECOVERY_MIN_CONFIDENCE,
            "prototype_strong_score": PROTOTYPE_STRONG_SCORE,
            "prototype_peak_score": PROTOTYPE_PEAK_SCORE,
            "prototype_self_score": PROTOTYPE_SELF_SCORE,
            "prototype_min_support": PROTOTYPE_MIN_SUPPORT,
        },
        "accepted_vf_sha256": ACCEPTED_VF_SHA256,
        "visual_prototypes": prototypes,
        "classifications": classifications,
        "summary": {
            "evaluated_unresolved": len(classifications),
            "source_semantic_recovered": counts["source_semantic_recovered"],
            "source_compound_semantic_recovered": counts["source_compound_semantic_recovered"],
            "source_visual_companion_recovered": counts["source_visual_companion_recovered"],
            "source_unresolved_after_recovery": counts["source_unresolved_after_recovery"],
            "source_absent_claims": 0,
            "structural_total": EXPECTED_STRUCTURAL,
            "physical_textplus_before_merge": EXPECTED_PHYSICAL,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "next_boundary": "STEP_3E_CLASSIFY_REMAINING_SOURCE_OMISSIONS_AND_NONCAPTION_GRAPHICS_BEFORE_RESOLVE_ROLLOUT",
        "semantic_sha256": "",
    }
    result["semantic_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "semantic_sha256"})
    write_json(output_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--ocr-lang", default="en")
    parser.add_argument("--ocr-device", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--ocr-gpu-id", type=int, default=0)
    parser.add_argument("--min-ocr-confidence", type=float, default=OCR_MIN_CONFIDENCE)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    output = (args.output or (root / DEFAULT_OUTPUT)).resolve()
    result = build(root, output, args)
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
