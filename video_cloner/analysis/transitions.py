#!/usr/bin/env python3
"""
detect_transitions_proxy.py

Video Cloner transition analyzer for proxy video + shot boundaries.

Purpose:
    Detect high-confidence visual transition signatures around shot boundaries and
    emit a richer, editor-agnostic transition contract for downstream layers:

        detect_transitions_proxy.py
        -> merge_analysis.py
        -> plan_edit.py / validate_edit_plan.py
        -> compile_generic_edit.py
        -> compile_davinci_otio.py / Resolve controller

Important architecture rule:
    This analyzer does NOT insert transitions and does NOT make DaVinci-specific
    choices. It only classifies visual evidence and prepares safe metadata:
        - transition_type
        - confidence
        - cut_time / cut_frame
        - duration_frames / duration_seconds
        - placement / side
        - handle_check
        - editor_actionable
        - scores / reasons

Notes:
    - Native Resolve transition insertion is handled later, and may remain marker/
      FCPXML/OTIO-controller based depending on Resolve API reliability.
    - Hard cuts and unknown/simple cuts are intentionally marked non-actionable.
    - Candidate transition types are also non-actionable unless another layer opts in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

VERSION = "transition_proxy_detector_v2_rich_editor_contract"
SCHEMA = "video_cloner_transitions"
SCHEMA_VERSION = "2.0"

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
NON_ACTIONABLE_TYPES = {"hard_cut", "unknown_or_simple_cut", "none", "unknown"}
CANDIDATE_SUFFIX = "candidate"


# -------------------------
# IO / primitives
# -------------------------


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def roundf(value: Any, digits: int = 4, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return round(float(value), digits)
    except Exception:
        return default


def parse_time_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", ".")
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        pass

    parts = text.split(":")
    try:
        parts_f = [float(p) for p in parts]
    except ValueError:
        return None

    if len(parts_f) == 3:
        h, m, s = parts_f
        return h * 3600.0 + m * 60.0 + s
    if len(parts_f) == 2:
        m, s = parts_f
        return m * 60.0 + s
    return None


def get_num(obj: Dict[str, Any], keys: Iterable[str], default: Optional[float] = None) -> Optional[float]:
    for key in keys:
        if key in obj and obj[key] is not None:
            parsed = parse_time_value(obj[key])
            if parsed is not None:
                return parsed
    return default


def get_int(obj: Dict[str, Any], keys: Iterable[str], default: Optional[int] = None) -> Optional[int]:
    for key in keys:
        if key in obj and obj[key] is not None:
            try:
                return int(round(float(obj[key])))
            except Exception:
                pass
    return default


def get_shots(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("shots", "cuts", "scenes"):
            if isinstance(data.get(key), list):
                return data[key]
        timeline = data.get("timeline")
        if isinstance(timeline, dict) and isinstance(timeline.get("shots"), list):
            return timeline["shots"]
    if isinstance(data, list):
        return data
    raise ValueError("Could not find shots/cuts/scenes list in shots.json")


def shot_id(shot: Dict[str, Any], fallback: int) -> int:
    value = shot.get("shot_id", shot.get("scene_index", shot.get("index", fallback)))
    try:
        return int(value)
    except Exception:
        return int(fallback)


def shot_start_time(shot: Dict[str, Any], fps: float, fallback: Optional[float] = None) -> Optional[float]:
    value = get_num(shot, ["start_seconds", "start_time", "start", "start_sec"], None)
    if value is not None:
        return value
    frame = get_int(shot, ["start_frame", "startFrame"], None)
    if frame is not None and fps > 0:
        return frame / fps
    return fallback


def shot_end_time(shot: Dict[str, Any], fps: float, fallback: Optional[float] = None) -> Optional[float]:
    value = get_num(shot, ["end_seconds", "end_time", "end", "end_sec"], None)
    if value is not None:
        return value
    frame = get_int(shot, ["end_frame", "endFrame"], None)
    if frame is not None and fps > 0:
        return frame / fps
    return fallback


def shot_start_frame(shot: Dict[str, Any], fps: float, fallback: int = 0) -> int:
    frame = get_int(shot, ["start_frame", "startFrame"], None)
    if frame is not None:
        return max(0, frame)
    ts = shot_start_time(shot, fps, None)
    if ts is not None:
        return max(0, int(round(ts * fps)))
    return fallback


def shot_end_frame(shot: Dict[str, Any], fps: float, fallback: int = 0) -> int:
    frame = get_int(shot, ["end_frame", "endFrame"], None)
    if frame is not None:
        return max(0, frame)
    ts = shot_end_time(shot, fps, None)
    if ts is not None:
        return max(0, int(round(ts * fps)))
    return fallback


def shot_duration_frames(shot: Dict[str, Any], fps: float) -> int:
    start_f = shot_start_frame(shot, fps, 0)
    end_f = shot_end_frame(shot, fps, start_f)
    if end_f > start_f:
        return max(1, end_f - start_f)
    duration = get_num(shot, ["duration_seconds", "duration", "duration_sec"], None)
    if duration is not None and fps > 0:
        return max(1, int(round(duration * fps)))
    return 1


def frames_to_seconds(frames: int, fps: float) -> float:
    if fps <= 0:
        fps = 24.0
    return round(float(frames) / float(fps), 4)


# -------------------------
# Image metrics
# -------------------------


def resize(frame: np.ndarray, width: int = 220) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= width:
        return frame
    scale = width / float(w)
    return cv2.resize(frame, (width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)


def gray(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def luma(frame: np.ndarray) -> float:
    return float(np.mean(gray(frame))) / 255.0


def black_ratio(frame: np.ndarray) -> float:
    return float(np.mean(gray(frame) < 25))


def white_ratio(frame: np.ndarray) -> float:
    return float(np.mean(gray(frame) > 235))


def blur_score(frame: np.ndarray) -> float:
    return float(cv2.Laplacian(gray(resize(frame, 220)), cv2.CV_64F).var())


def hist_delta(a: np.ndarray, b: np.ndarray) -> float:
    a_hsv = cv2.cvtColor(resize(a, 220), cv2.COLOR_BGR2HSV)
    b_hsv = cv2.cvtColor(resize(b, 220), cv2.COLOR_BGR2HSV)

    hist_a = cv2.calcHist([a_hsv], [0, 1], None, [20, 20], [0, 180, 0, 256])
    hist_b = cv2.calcHist([b_hsv], [0, 1], None, [20, 20], [0, 180, 0, 256])

    cv2.normalize(hist_a, hist_a, 0, 1, cv2.NORM_MINMAX)
    cv2.normalize(hist_b, hist_b, 0, 1, cv2.NORM_MINMAX)

    corr = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
    return float(max(0.0, min(1.0, 1.0 - corr)))


def adjacent_hist_deltas(frames: List[np.ndarray]) -> List[float]:
    if len(frames) < 2:
        return []
    out = []
    for i in range(len(frames) - 1):
        try:
            out.append(hist_delta(frames[i], frames[i + 1]))
        except Exception:
            pass
    return out


def flow_stats(a: np.ndarray, b: np.ndarray) -> Dict[str, Any]:
    a_small = resize(a, 160)
    b_small = resize(b, 160)

    ga = gray(a_small)
    gb = gray(b_small)

    flow = cv2.calcOpticalFlowFarneback(
        ga,
        gb,
        None,
        0.5,
        2,
        9,
        2,
        5,
        1.1,
        0,
    )

    fx = flow[..., 0]
    fy = flow[..., 1]
    mag, _ = cv2.cartToPolar(fx, fy, angleInDegrees=True)

    mean_x = float(np.mean(fx))
    mean_y = float(np.mean(fy))
    mean_mag = float(np.mean(mag))
    p90_mag = float(np.percentile(mag, 90))

    if abs(mean_x) > abs(mean_y) * 1.35:
        direction = "horizontal"
    elif abs(mean_y) > abs(mean_x) * 1.35:
        direction = "vertical"
    else:
        direction = "mixed"

    coherent_motion = float(np.sqrt(mean_x * mean_x + mean_y * mean_y))
    directional_coherence = coherent_motion / max(mean_mag, 1e-6)

    # Radial component: useful for rough zoom/push-style transition signatures.
    h, w = ga.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx = (w - 1) / 2.0
    cy = (h - 1) / 2.0
    rx = xx - cx
    ry = yy - cy
    rnorm = np.sqrt(rx * rx + ry * ry) + 1e-6
    rx /= rnorm
    ry /= rnorm
    radial = (fx * rx + fy * ry)
    radial_score = float(np.mean(radial) / max(mean_mag, 1e-6)) if mean_mag > 0 else 0.0
    zoom_score = clamp(abs(radial_score), 0.0, 1.0)

    return {
        "mean_magnitude": mean_mag,
        "p90_magnitude": p90_mag,
        "mean_x": mean_x,
        "mean_y": mean_y,
        "direction": direction,
        "directional_coherence": directional_coherence,
        "radial_score": radial_score,
        "zoom_score": zoom_score,
    }


def directional_context_stats(frames: List[np.ndarray]) -> Dict[str, Any]:
    """Measure real motion on each side of a cut without crossing the cut.

    Cross-cut optical flow between unrelated shots can produce a large coherent
    vector even when the edit is just a hard cut.  A whip-pan promotion therefore
    requires directional motion inside at least one adjacent shot as well.
    """
    if len(frames) < 4:
        empty = {
            "pair_count": 0,
            "p90_magnitude": 0.0,
            "mean_x": 0.0,
            "mean_y": 0.0,
            "direction": "mixed",
            "directional_coherence": 0.0,
        }
        return {"outgoing": dict(empty), "incoming": dict(empty)}

    center = len(frames) // 2
    outgoing_frames = frames[:center]
    incoming_frames = frames[center:]

    def summarize(side_frames: List[np.ndarray]) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for index in range(len(side_frames) - 1):
            try:
                rows.append(flow_stats(side_frames[index], side_frames[index + 1]))
            except Exception:
                pass

        if not rows:
            return {
                "pair_count": 0,
                "p90_magnitude": 0.0,
                "mean_x": 0.0,
                "mean_y": 0.0,
                "direction": "mixed",
                "directional_coherence": 0.0,
            }

        best = max(rows, key=lambda row: float(row.get("p90_magnitude", 0.0) or 0.0))
        return {
            "pair_count": len(rows),
            "p90_magnitude": float(best.get("p90_magnitude", 0.0) or 0.0),
            "mean_x": float(best.get("mean_x", 0.0) or 0.0),
            "mean_y": float(best.get("mean_y", 0.0) or 0.0),
            "direction": str(best.get("direction") or "mixed"),
            "directional_coherence": float(best.get("directional_coherence", 0.0) or 0.0),
        }

    return {
        "outgoing": summarize(outgoing_frames),
        "incoming": summarize(incoming_frames),
    }


# -------------------------
# Transition classification
# -------------------------


def transition_strength_score(metrics: Dict[str, Any]) -> float:
    hist = float(metrics.get("hist_delta", 0.0) or 0.0)
    lum = float(metrics.get("luma_delta", 0.0) or 0.0)
    black = float(metrics.get("black_ratio_max", 0.0) or 0.0)
    white = float(metrics.get("white_ratio_max", 0.0) or 0.0)
    blur_drop = float(metrics.get("blur_drop", 0.0) or 0.0)
    flow = metrics.get("flow") or {}
    flow_p90 = float(flow.get("p90_magnitude", 0.0) or 0.0)
    coherence = float(flow.get("directional_coherence", 0.0) or 0.0)
    zoom_score = float(metrics.get("zoom_score", 0.0) or 0.0)
    gradual = float(metrics.get("gradual_change_score", 0.0) or 0.0)

    score = (
        min(hist / 0.75, 1.0) * 0.26
        + min(lum / 0.35, 1.0) * 0.16
        + max(black, white) * 0.16
        + min(flow_p90 / 18.0, 1.0) * 0.16
        + min(coherence / 0.55, 1.0) * 0.08
        + min(blur_drop / 0.75, 1.0) * 0.08
        + min(zoom_score / 0.8, 1.0) * 0.04
        + min(gradual / 0.8, 1.0) * 0.06
    )
    return round(clamp(score, 0.0, 1.0), 4)


def classify_transition(metrics: Dict[str, Any], args: argparse.Namespace) -> Tuple[str, str, List[str]]:
    hist = float(metrics["hist_delta"])
    lum = float(metrics["luma_delta"])
    black = float(metrics["black_ratio_max"])
    white = float(metrics["white_ratio_max"])
    flow = metrics["flow"]
    flow_p90 = float(flow["p90_magnitude"])
    direction = str(flow["direction"])
    coherence = float(flow.get("directional_coherence", 0.0) or 0.0)
    blur_drop = float(metrics["blur_drop"])
    gradual = float(metrics.get("gradual_change_score", 0.0) or 0.0)
    strength = float(metrics.get("transition_strength", 0.0) or 0.0)
    zoom_score = float(metrics.get("zoom_score", 0.0) or 0.0)

    if black >= args.dip_black_ratio and lum >= args.dip_luma_delta:
        confidence = "high" if black >= 0.65 or strength >= 0.62 else "medium"
        return "dip_to_black", confidence, ["black-frame/luma spike near boundary"]

    if white >= args.flash_white_ratio and lum >= args.flash_luma_delta:
        confidence = "high" if white >= 0.55 or strength >= 0.62 else "medium"
        return "flash_cut", confidence, ["white-frame/luma spike near boundary"]

    if (
        flow_p90 >= args.directional_flow_p90
        and hist >= args.directional_hist_delta
        and coherence >= args.directional_coherence
        and direction in {"horizontal", "vertical"}
    ):
        if direction == "horizontal":
            context = metrics.get("directional_context") or {}
            context_rows = [context.get("outgoing") or {}, context.get("incoming") or {}]
            supported_rows = [
                row
                for row in context_rows
                if str(row.get("direction") or "") == "horizontal"
                and float(row.get("p90_magnitude", 0.0) or 0.0) >= args.whip_context_flow_p90
                and float(row.get("directional_coherence", 0.0) or 0.0) >= args.whip_context_coherence
            ]
            if not supported_rows:
                return "whip_pan_candidate", "medium", [
                    "cross-cut horizontal flow lacks within-shot horizontal support",
                    "direction=horizontal",
                ]

            confidence = "high" if flow_p90 >= args.directional_high_flow_p90 and strength >= 0.52 else "medium"
            return "whip_pan", confidence, [
                "horizontal optical-flow spike with within-shot support",
                "direction=horizontal",
            ]

        context = metrics.get("directional_context") or {}
        context_rows = [context.get("outgoing") or {}, context.get("incoming") or {}]
        supported_rows = [
            row
            for row in context_rows
            if str(row.get("direction") or "") == "vertical"
            and float(row.get("p90_magnitude", 0.0) or 0.0) >= args.slide_context_flow_p90
            and float(row.get("directional_coherence", 0.0) or 0.0) >= args.slide_context_coherence
        ]
        if not supported_rows:
            return "slide_transition_candidate", "medium", [
                "cross-cut vertical flow lacks within-shot vertical support",
                "direction=vertical",
            ]

        confidence = "high" if flow_p90 >= args.directional_high_flow_p90 and strength >= 0.52 else "medium"
        return "slide_transition_candidate", confidence, [
            "vertical optical-flow spike with within-shot support",
            "direction=vertical",
        ]

    if blur_drop >= args.blur_drop and flow_p90 >= args.blur_flow_p90:
        confidence = "high" if strength >= 0.65 else "medium"
        return "blur_transition", confidence, ["blur drop/spike near boundary"]

    if zoom_score >= args.zoom_score and hist >= 0.20 and flow_p90 >= 3.0:
        confidence = "high" if zoom_score >= 0.65 and strength >= 0.58 else "medium"
        return "zoom_transition", confidence, ["radial optical-flow pattern near boundary"]

    if gradual >= args.crossfade_gradual_score and hist >= args.crossfade_hist_delta and flow_p90 <= args.crossfade_max_flow_p90:
        if strength >= 0.58:
            return "crossfade", "high", ["gradual histogram change with low directional flow"]
        return "crossfade_candidate", "medium", ["probable gradual transition, but confidence below high threshold"]

    if hist >= args.hard_cut_hist_delta or lum >= args.hard_cut_luma_delta:
        return "hard_cut", "medium", ["visual discontinuity, but no reliable stylized transition signature"]

    return "unknown_or_simple_cut", "low", ["weak transition signature"]


def analyze_boundary_frames(before: np.ndarray, after: np.ndarray, near_frames: List[np.ndarray], args: argparse.Namespace) -> Tuple[str, str, List[str], Dict[str, Any]]:
    hist = hist_delta(before, after)
    lum = abs(luma(before) - luma(after))
    black = max(black_ratio(f) for f in near_frames)
    white = max(white_ratio(f) for f in near_frames)

    blur_values = [blur_score(f) for f in near_frames]
    blur_min = min(blur_values)
    blur_median = float(np.median(blur_values))
    blur_drop = 0.0 if blur_median <= 1 else max(0.0, (blur_median - blur_min) / blur_median)

    flow = flow_stats(before, after)
    directional_context = directional_context_stats(near_frames)
    adjacent = adjacent_hist_deltas(near_frames)
    adjacent_mean = float(np.mean(adjacent)) if adjacent else 0.0
    adjacent_max = float(np.max(adjacent)) if adjacent else 0.0

    # A gradual transition changes over a few frames rather than only at one hard boundary.
    gradual_change_score = 0.0
    if hist > 0.0:
        gradual_change_score = clamp((hist - adjacent_mean * 0.45) / max(hist, 1e-6), 0.0, 1.0)
        if adjacent_mean > hist * 0.95:
            gradual_change_score *= 0.6

    metrics: Dict[str, Any] = {
        "hist_delta": round(hist, 4),
        "luma_delta": round(lum, 4),
        "black_ratio_max": round(black, 4),
        "white_ratio_max": round(white, 4),
        "blur_min": round(blur_min, 2),
        "blur_median": round(blur_median, 2),
        "blur_drop": round(blur_drop, 4),
        "adjacent_hist_delta_mean": round(adjacent_mean, 4),
        "adjacent_hist_delta_max": round(adjacent_max, 4),
        "gradual_change_score": round(gradual_change_score, 4),
        "zoom_score": round(float(flow.get("zoom_score", 0.0) or 0.0), 4),
        "flow": {
            "mean_magnitude": round(float(flow["mean_magnitude"]), 4),
            "p90_magnitude": round(float(flow["p90_magnitude"]), 4),
            "mean_x": round(float(flow["mean_x"]), 4),
            "mean_y": round(float(flow["mean_y"]), 4),
            "direction": flow["direction"],
            "directional_coherence": round(float(flow.get("directional_coherence", 0.0) or 0.0), 4),
            "radial_score": round(float(flow.get("radial_score", 0.0) or 0.0), 4),
        },
        "directional_context": {
            side: {
                key: (
                    round(float(value), 4)
                    if key in {"p90_magnitude", "mean_x", "mean_y", "directional_coherence"}
                    else value
                )
                for key, value in row.items()
            }
            for side, row in directional_context.items()
        },
    }
    metrics["transition_strength"] = transition_strength_score(metrics)

    transition_type, confidence, reasons = classify_transition(metrics, args)
    return transition_type, confidence, reasons, metrics


# -------------------------
# Editor contract helpers
# -------------------------


def transition_base_duration_frames(transition_type: str, fps: float, args: argparse.Namespace) -> int:
    t = str(transition_type or "").lower()

    if t in NON_ACTIONABLE_TYPES or CANDIDATE_SUFFIX in t:
        return 0

    if t == "flash_cut":
        seconds = 0.18
    elif t == "whip_pan":
        seconds = 0.35
    elif t in {"slide_transition", "blur_transition", "zoom_transition"}:
        seconds = 0.45
    elif t in {"dip_to_black", "crossfade"}:
        seconds = 0.50
    else:
        seconds = float(args.default_transition_seconds)

    frames = int(round(seconds * fps))
    return max(args.min_transition_frames, min(args.max_transition_frames, frames))


def transition_side_and_placement(transition_type: str, confidence: str) -> Tuple[str, str]:
    t = str(transition_type or "").lower()
    if t in NON_ACTIONABLE_TYPES or CANDIDATE_SUFFIX in t:
        return "none", "cut"
    if t == "flash_cut":
        return "center", "at_cut"
    if t in {"dip_to_black", "crossfade", "blur_transition", "zoom_transition", "whip_pan", "slide_transition"}:
        return "both", "centered_on_cut"
    if confidence == "high":
        return "both", "centered_on_cut"
    return "none", "marker_only"


def transition_kind_for_otio(transition_type: str) -> str:
    t = str(transition_type or "").lower()
    if t in {"crossfade", "dip_to_black", "blur_transition"}:
        return "SMPTE_Dissolve"
    return "Custom"


def recommended_backend(transition_type: str, actionable: bool) -> Dict[str, Any]:
    t = str(transition_type or "").lower()
    if not actionable:
        return {
            "preferred": "marker_only",
            "resolve": "debug_marker_or_report_only",
            "otio": "marker_only",
            "fcpxml": "not_recommended",
        }

    if t in {"crossfade", "dip_to_black", "blur_transition"}:
        return {
            "preferred": "fcpxml_or_otio_experiment",
            "resolve": "marker_or_ui_automation_or_preset_transition",
            "otio": "optional_basic_transition_experiment",
            "fcpxml": "recommended_for_native_transition",
        }

    return {
        "preferred": "preset_or_adjustment_clip",
        "resolve": "controller_marker_then_manual_or_ui_automation",
        "otio": "marker_only_by_default",
        "fcpxml": "possible_custom_effect_if_supported",
    }


def handle_contract(
    from_shot: Dict[str, Any],
    to_shot: Dict[str, Any],
    fps: float,
    duration_frames: int,
) -> Dict[str, Any]:
    if duration_frames <= 0:
        return {
            "ok": False,
            "reason": "non_actionable_or_zero_duration",
            "required_outgoing_frames": 0,
            "required_incoming_frames": 0,
            "available_outgoing_frames": shot_duration_frames(from_shot, fps),
            "available_incoming_frames": shot_duration_frames(to_shot, fps),
        }

    out_required = max(1, duration_frames // 2)
    in_required = max(1, duration_frames - out_required)
    out_available = max(0, shot_duration_frames(from_shot, fps) - 1)
    in_available = max(0, shot_duration_frames(to_shot, fps) - 1)

    ok = out_available >= out_required and in_available >= in_required
    return {
        "ok": bool(ok),
        "reason": "ok" if ok else "insufficient_neighbor_shot_duration_for_transition_handles",
        "required_outgoing_frames": out_required,
        "required_incoming_frames": in_required,
        "available_outgoing_frames": out_available,
        "available_incoming_frames": in_available,
    }


def is_editor_actionable(transition_type: str, confidence: str, handle_check: Dict[str, Any], args: argparse.Namespace) -> Tuple[bool, str]:
    t = str(transition_type or "").lower()
    if t in NON_ACTIONABLE_TYPES:
        return False, f"non_actionable_transition_type:{t}"
    if CANDIDATE_SUFFIX in t:
        return False, f"candidate_transition_type:{t}"
    if args.actionable_requires_high_confidence and confidence != "high":
        return False, f"confidence_not_high:{confidence}"
    if handle_check.get("ok") is False:
        return False, "handle_check_failed"
    return True, "ok"


def build_transition_contract(
    transition_type: str,
    confidence: str,
    boundary: Dict[str, Any],
    from_shot: Dict[str, Any],
    to_shot: Dict[str, Any],
    fps: float,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    duration_frames = transition_base_duration_frames(transition_type, fps, args)
    side, placement = transition_side_and_placement(transition_type, confidence)
    handle_check = handle_contract(from_shot, to_shot, fps, duration_frames)
    actionable, reason = is_editor_actionable(transition_type, confidence, handle_check, args)

    outgoing_frames = handle_check.get("required_outgoing_frames", 0)
    incoming_frames = handle_check.get("required_incoming_frames", 0)

    return {
        "duration_frames": int(duration_frames),
        "duration_seconds": frames_to_seconds(duration_frames, fps),
        "side": side,
        "placement": placement,
        "timeline_cut_frame": int(boundary["cut_frame"]),
        "timeline_cut_time": roundf(boundary["cut_time"], 4, 0.0),
        "outgoing_frames": int(outgoing_frames or 0),
        "incoming_frames": int(incoming_frames or 0),
        "handle_check": handle_check,
        "editor_actionable": bool(actionable),
        "actionability_reason": reason,
        "recommended_backend": recommended_backend(transition_type, actionable),
        "otio_transition_kind": transition_kind_for_otio(transition_type),
    }


# -------------------------
# Frame loading
# -------------------------


def build_boundary_requests(
    shots: List[Dict[str, Any]],
    fps: float,
    frame_count: int,
    window_frames: int,
    max_boundaries: int,
) -> Tuple[List[Dict[str, Any]], List[int], int]:
    total_boundaries = max(0, len(shots) - 1)
    limit = min(total_boundaries, max_boundaries)

    boundaries: List[Dict[str, Any]] = []
    needed_frames = set()

    for i in range(limit):
        shot = shots[i]
        next_shot = shots[i + 1]

        end_frame = shot_end_frame(shot, fps, 0)
        end_time = shot_end_time(shot, fps, end_frame / fps if fps > 0 else None)

        if frame_count > 0:
            end_frame = max(2, min(frame_count - 3, end_frame))

        before_idx = end_frame - 1
        after_idx = end_frame + 1
        near_indexes = list(range(end_frame - window_frames, end_frame + window_frames + 1))

        boundary = {
            "index": i,
            "from_shot_id": shot_id(shot, i + 1),
            "to_shot_id": shot_id(next_shot, i + 2),
            "shot": shot,
            "next_shot": next_shot,
            "cut_frame": int(end_frame),
            "cut_time": float(end_time if end_time is not None else end_frame / fps),
            "next_start_time": shot_start_time(next_shot, fps, None),
            "before_idx": int(before_idx),
            "after_idx": int(after_idx),
            "near_indexes": [int(x) for x in near_indexes],
        }
        boundaries.append(boundary)

        needed_frames.add(before_idx)
        needed_frames.add(after_idx)
        for idx in near_indexes:
            if idx >= 0:
                needed_frames.add(idx)

    return boundaries, sorted(needed_frames), total_boundaries


def load_frames_sequential(
    video_path: str,
    needed_indexes: List[int],
    max_runtime_sec: float,
    start_time: float,
) -> Dict[int, np.ndarray]:
    if not needed_indexes:
        return {}

    needed = sorted(set(int(i) for i in needed_indexes if i >= 0))
    frames: Dict[int, np.ndarray] = {}

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    target_pos = 0
    current_idx = 0
    max_needed = needed[-1]

    while current_idx <= max_needed:
        if time.monotonic() - start_time > max_runtime_sec:
            cap.release()
            raise TimeoutError(f"Frame loading exceeded {max_runtime_sec}s")

        ok, frame = cap.read()
        if not ok or frame is None:
            break

        while target_pos < len(needed) and needed[target_pos] < current_idx:
            target_pos += 1

        if target_pos < len(needed) and needed[target_pos] == current_idx:
            frames[current_idx] = frame.copy()
            target_pos += 1
            if target_pos >= len(needed):
                break

        current_idx += 1

    cap.release()
    return frames


# -------------------------
# Summary / main
# -------------------------


def count_by_key(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in items:
        value = item.get(key)
        if value is None:
            continue
        out[str(value)] = out.get(str(value), 0) + 1
    return out


def build_summary(transitions: List[Dict[str, Any]], boundaries_total: int, skipped: List[Dict[str, Any]]) -> Dict[str, Any]:
    actionable = [t for t in transitions if t.get("editor_actionable")]
    high_conf = [t for t in transitions if t.get("confidence") == "high"]
    stylized = [
        t for t in transitions
        if str(t.get("transition_type") or "").lower() not in NON_ACTIONABLE_TYPES
    ]
    candidates = [
        t for t in transitions
        if CANDIDATE_SUFFIX in str(t.get("transition_type") or "").lower()
    ]

    return {
        "boundaries_total": boundaries_total,
        "transition_count": len(transitions),
        "high_confidence_count": len(high_conf),
        "stylized_transition_count": len(stylized),
        "candidate_transition_count": len(candidates),
        "editor_actionable_count": len(actionable),
        "type_counts": count_by_key(transitions, "transition_type"),
        "confidence_counts": count_by_key(transitions, "confidence"),
        "skipped_count": len(skipped),
        "ready_for_merge_analysis": True,
        "ready_for_generic_compiler": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect transition signatures at proxy-video shot boundaries and emit rich transition metadata."
    )
    parser.add_argument("--video", required=True, help="Path to proxy.mp4")
    parser.add_argument("--shots", required=True, help="Path to shots.json")
    parser.add_argument("--output", required=True, help="Path to transitions.json")
    parser.add_argument("--window-frames", type=int, default=3, help="Frames before/after cut used for local transition analysis. Default: 3")
    parser.add_argument("--min-confidence", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--max-runtime-sec", type=float, default=45.0)
    parser.add_argument("--max-boundaries", type=int, default=300)
    parser.add_argument("--output-mode", choices=["compact", "full"], default="compact")

    # Editor-contract duration defaults.
    parser.add_argument("--default-transition-seconds", type=float, default=0.45)
    parser.add_argument("--min-transition-frames", type=int, default=4)
    parser.add_argument("--max-transition-frames", type=int, default=18)
    parser.add_argument(
        "--actionable-requires-high-confidence",
        action="store_true",
        help="Only mark stylized transitions editor_actionable when confidence is high. Default: false; handle/type checks still apply.",
    )

    # Classification thresholds. Defaults are intentionally conservative.
    parser.add_argument("--dip-black-ratio", type=float, default=0.55)
    parser.add_argument("--dip-luma-delta", type=float, default=0.14)
    parser.add_argument("--flash-white-ratio", type=float, default=0.45)
    parser.add_argument("--flash-luma-delta", type=float, default=0.16)
    parser.add_argument("--directional-flow-p90", type=float, default=9.0)
    parser.add_argument("--directional-high-flow-p90", type=float, default=13.0)
    parser.add_argument("--directional-hist-delta", type=float, default=0.30)
    parser.add_argument("--directional-coherence", type=float, default=0.10)
    parser.add_argument(
        "--whip-context-flow-p90",
        type=float,
        default=4.5,
        help="Minimum within-shot horizontal p90 flow required for whip-pan promotion. Default: 4.5",
    )
    parser.add_argument(
        "--whip-context-coherence",
        type=float,
        default=0.25,
        help="Minimum within-shot horizontal coherence required for whip-pan promotion. Default: 0.25",
    )
    parser.add_argument(
        "--slide-context-flow-p90",
        type=float,
        default=4.5,
        help="Minimum within-shot vertical p90 flow required for slide-transition promotion. Default: 4.5",
    )
    parser.add_argument(
        "--slide-context-coherence",
        type=float,
        default=0.25,
        help="Minimum within-shot vertical coherence required for slide-transition promotion. Default: 0.25",
    )
    parser.add_argument("--blur-drop", type=float, default=0.45)
    parser.add_argument("--blur-flow-p90", type=float, default=3.0)
    parser.add_argument("--zoom-score", type=float, default=0.55)
    parser.add_argument("--crossfade-gradual-score", type=float, default=0.58)
    parser.add_argument("--crossfade-hist-delta", type=float, default=0.20)
    parser.add_argument("--crossfade-max-flow-p90", type=float, default=8.0)
    parser.add_argument("--hard-cut-hist-delta", type=float, default=0.35)
    parser.add_argument("--hard-cut-luma-delta", type=float, default=0.22)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    started = time.monotonic()

    if not os.path.exists(args.video):
        raise FileNotFoundError(f"Video not found: {args.video}")
    if not os.path.exists(args.shots):
        raise FileNotFoundError(f"Shots JSON not found: {args.shots}")

    shots = get_shots(load_json(args.shots))

    probe = cv2.VideoCapture(args.video)
    if not probe.isOpened():
        raise RuntimeError(f"Could not open video probe: {args.video}")

    fps = float(probe.get(cv2.CAP_PROP_FPS) or 24.0)
    frame_count = int(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration_seconds = frame_count / fps if fps > 0 and frame_count > 0 else None
    probe.release()

    boundaries, needed_frames, boundaries_total = build_boundary_requests(
        shots=shots,
        fps=fps,
        frame_count=frame_count,
        window_frames=max(1, int(args.window_frames)),
        max_boundaries=max(1, int(args.max_boundaries)),
    )

    frames = load_frames_sequential(
        video_path=args.video,
        needed_indexes=needed_frames,
        max_runtime_sec=float(args.max_runtime_sec),
        start_time=started,
    )

    min_rank = CONFIDENCE_RANK[args.min_confidence]
    transitions: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    boundary_debug: List[Dict[str, Any]] = []

    for b in boundaries:
        if time.monotonic() - started > args.max_runtime_sec:
            skipped.append({"boundary_index": b["index"], "reason": "max_runtime_reached"})
            break

        before = frames.get(b["before_idx"])
        after = frames.get(b["after_idx"])
        near = [frames[idx] for idx in b["near_indexes"] if idx in frames]

        if before is None or after is None or not near:
            skipped.append({
                "boundary_index": b["index"],
                "from_shot": b.get("from_shot_id"),
                "to_shot": b.get("to_shot_id"),
                "reason": "missing_required_frames",
                "before_idx": b["before_idx"],
                "after_idx": b["after_idx"],
                "loaded_near_count": len(near),
            })
            continue

        try:
            transition_type, confidence, reasons, scores = analyze_boundary_frames(before, after, near, args)
        except Exception as exc:
            skipped.append({
                "boundary_index": b["index"],
                "from_shot": b.get("from_shot_id"),
                "to_shot": b.get("to_shot_id"),
                "reason": "analysis_error",
                "error": str(exc),
            })
            continue

        debug_item = {
            "boundary_index": b["index"],
            "from_shot": b.get("from_shot_id"),
            "to_shot": b.get("to_shot_id"),
            "cut_frame": b.get("cut_frame"),
            "cut_time": roundf(b.get("cut_time"), 4, 0.0),
            "transition_type": transition_type,
            "confidence": confidence,
            "scores": scores,
            "reasons": reasons,
        }
        boundary_debug.append(debug_item)

        if CONFIDENCE_RANK.get(confidence, 0) < min_rank:
            continue

        from_shot = b["shot"]
        to_shot = b["next_shot"]
        contract = build_transition_contract(
            transition_type=transition_type,
            confidence=confidence,
            boundary=b,
            from_shot=from_shot,
            to_shot=to_shot,
            fps=fps,
            args=args,
        )

        transition_strength = roundf(scores.get("transition_strength"), 4, 0.0)

        transitions.append({
            "from_shot": int(shot_id(from_shot, b["index"] + 1)),
            "to_shot": int(shot_id(to_shot, b["index"] + 2)),
            "from_shot_array_index": int(b["index"]),
            "to_shot_array_index": int(b["index"] + 1),
            "cut_time": round(float(b["cut_time"]), 4),
            "cut_frame": int(b["cut_frame"]),
            "next_start_time": round(float(b["next_start_time"]), 4) if b.get("next_start_time") is not None else None,
            "transition_type": transition_type,
            "confidence": confidence,
            "transition_strength": transition_strength,
            "duration_frames": contract["duration_frames"],
            "duration_seconds": contract["duration_seconds"],
            "side": contract["side"],
            "placement": contract["placement"],
            "timeline_cut_frame": contract["timeline_cut_frame"],
            "timeline_cut_time": contract["timeline_cut_time"],
            "outgoing_frames": contract["outgoing_frames"],
            "incoming_frames": contract["incoming_frames"],
            "handle_check": contract["handle_check"],
            "editor_actionable": contract["editor_actionable"],
            "actionability_reason": contract["actionability_reason"],
            "recommended_backend": contract["recommended_backend"],
            "otio_transition_kind": contract["otio_transition_kind"],
            "scores": scores,
            "reasons": reasons,
        })

    summary = build_summary(transitions, boundaries_total, skipped)
    runtime_sec = round(time.monotonic() - started, 3)

    output: Dict[str, Any] = {
        "success": True,
        "ok": True,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "analysis_version": VERSION,
        "source_video": os.path.abspath(args.video),
        "source_shots": os.path.abspath(args.shots),
        "fps": round(float(fps), 4),
        "frame_count": frame_count,
        "video_info": {
            "width": width,
            "height": height,
            "fps": round(float(fps), 4),
            "frame_count": frame_count,
            "duration_seconds": roundf(duration_seconds, 4, None),
            "orientation": "vertical" if height > width else "horizontal" if width > height else "square",
        },
        "shot_count": len(shots),
        "boundaries_total": boundaries_total,
        "boundaries_attempted": len(boundaries),
        "runtime_sec": runtime_sec,
        "transition_count": len(transitions),
        # Backward-compatible summary alias: transition_type -> count.
        "summary": summary["type_counts"],
        "transition_summary": summary,
        "detector_config": {
            "window_frames": args.window_frames,
            "min_confidence": args.min_confidence,
            "max_runtime_sec": args.max_runtime_sec,
            "max_boundaries": args.max_boundaries,
            "output_mode": args.output_mode,
            "default_transition_seconds": args.default_transition_seconds,
            "min_transition_frames": args.min_transition_frames,
            "max_transition_frames": args.max_transition_frames,
            "actionable_requires_high_confidence": args.actionable_requires_high_confidence,
        },
        "skipped": skipped,
        "transitions": transitions,
        "quality_flags": [],
        "planner_ready": {
            "transition_fields": [
                "transition_type",
                "confidence",
                "transition_strength",
                "cut_time",
                "cut_frame",
                "duration_frames",
                "duration_seconds",
                "side",
                "placement",
                "handle_check",
                "editor_actionable",
            ],
            "notes": [
                "Only editor_actionable=true transitions should be considered for native transition experiments.",
                "hard_cut and unknown_or_simple_cut should remain cuts or markers, not native transitions.",
                "candidate transition types are retained for analysis but marked non-actionable by default.",
            ],
        },
        "_meta": {
            "created_at_unix": round(time.time(), 3),
            "editor_agnostic": True,
            "safe_for_merge_analysis": True,
            "safe_for_generic_compiler": True,
        },
    }

    if args.output_mode == "full":
        output["boundary_debug"] = boundary_debug
        output["needed_frames_count"] = len(needed_frames)
        output["loaded_frames_count"] = len(frames)

    if len(boundaries) < boundaries_total:
        output["quality_flags"].append({
            "type": "partial_boundary_analysis",
            "message": "Not all boundaries were attempted because max_boundaries limited the run.",
            "boundaries_total": boundaries_total,
            "boundaries_attempted": len(boundaries),
        })

    if skipped:
        output["quality_flags"].append({
            "type": "skipped_boundaries",
            "message": "Some boundaries were skipped.",
            "skipped_count": len(skipped),
        })

    save_json(args.output, output)

    print(json.dumps({
        "ok": True,
        "success": True,
        "version": VERSION,
        "schema": SCHEMA,
        "output": os.path.abspath(args.output),
        "runtime_sec": runtime_sec,
        "transition_count": len(transitions),
        "editor_actionable_count": summary["editor_actionable_count"],
        "summary": summary["type_counts"],
        "confidence_counts": summary["confidence_counts"],
        "skipped_count": len(skipped),
        "quality_flags_count": len(output["quality_flags"]),
    }, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "success": False,
            "version": VERSION,
            "error": str(e),
            "error_type": type(e).__name__,
        }), file=sys.stderr, flush=True)
        raise
