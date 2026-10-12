import argparse
import base64
import json
import math
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np


ANALYSIS_VERSION = "motion_speed_v4_rich_editor_contract"
SCHEMA = "video_cloner_motion_speed"
SCHEMA_VERSION = "2.0"


# -----------------------------
# Small utilities
# -----------------------------

def rf(value, digits=4):
    try:
        if value is None:
            return None
        return round(float(value), digits)
    except Exception:
        return None


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=None):
    try:
        if value is None:
            return default
        return int(round(float(value)))
    except Exception:
        return default


def clamp(value, min_value=0.0, max_value=1.0):
    try:
        value = float(value)
    except Exception:
        value = min_value
    return max(min_value, min(max_value, value))


def bool_arg(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    value = str(value).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Boolean expected, got: {value}")


def ensure_dir_for_file(path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def json_error(message, output_json=None, extra=None):
    payload = {
        "success": False,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "error": str(message),
        "errors": [str(message)],
    }
    if extra:
        payload.update(extra)
    if output_json:
        try:
            ensure_dir_for_file(output_json)
            with open(output_json, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    print(json.dumps(payload, ensure_ascii=False), flush=True)


# -----------------------------
# Shots input handling
# -----------------------------

def normalize_shot(raw, index, fps=None):
    shot_id = raw.get("shot_id", raw.get("scene_index", raw.get("index", index + 1)))
    start = safe_float(raw.get("start_seconds", raw.get("start_time", raw.get("start", 0.0))), 0.0)
    end = safe_float(raw.get("end_seconds", raw.get("end_time", raw.get("end", start))), start)

    if end < start:
        start, end = end, start

    duration = max(0.0, safe_float(raw.get("duration_seconds", raw.get("duration", end - start)), end - start))

    start_frame = safe_int(raw.get("start_frame"), None)
    end_frame = safe_int(raw.get("end_frame"), None)

    if fps and fps > 0:
        if start_frame is None:
            start_frame = int(round(start * fps))
        if end_frame is None:
            end_frame = int(round(end * fps))

    return {
        "shot_id": safe_int(shot_id, index + 1),
        "index": index,
        "start_seconds": rf(start, 6),
        "end_seconds": rf(end, 6),
        "duration_seconds": rf(duration, 6),
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration_frames": max(1, (end_frame - start_frame) if start_frame is not None and end_frame is not None else safe_int(duration * fps, None) if fps else None),
    }


def load_shots_from_arg(shots_arg, fps=None):
    """
    Supports:
    - path to JSON file
    - raw JSON string
    - base64 encoded JSON prefixed by base64:

    In n8n/Windows, passing large JSON inline through CMD is fragile.
    File path is the recommended production method.
    """
    if not shots_arg:
        return []

    data = None
    shots_arg = str(shots_arg).strip()

    if shots_arg.lower().startswith("base64:"):
        decoded = base64.b64decode(shots_arg.split(":", 1)[1]).decode("utf-8")
        data = json.loads(decoded)
    elif os.path.exists(shots_arg):
        with open(shots_arg, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.loads(shots_arg)

    if isinstance(data, dict):
        if "shots" in data:
            data = data["shots"]
        elif "cuts" in data:
            data = data["cuts"]
        elif "scenes" in data:
            data = data["scenes"]
        elif isinstance(data.get("timeline"), dict) and isinstance(data["timeline"].get("shots"), list):
            data = data["timeline"]["shots"]
        else:
            data = []

    if not isinstance(data, list):
        return []

    return [normalize_shot(s, i, fps=fps) for i, s in enumerate(data) if isinstance(s, dict)]


# -----------------------------
# Video helpers
# -----------------------------

def get_video_info(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = frame_count / fps if fps > 0 else 0.0
    cap.release()

    orientation = "vertical" if height > width else "horizontal" if width > height else "square"

    return {
        "fps": rf(fps, 3),
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": rf(duration, 3),
        "orientation": orientation,
    }


def read_frame_at(cap, time_sec):
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frame_idx = int(max(0, round(time_sec * fps)))
    if frame_count > 0:
        frame_idx = min(frame_idx, max(0, frame_count - 1))

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    if not ok or frame is None:
        return None
    return frame


def preprocess_gray(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Small blur reduces compression/caption edge noise on low-res proxy.
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return gray


def build_feature_mask(gray, top_mask_end_y=0.06, bottom_mask_start_y=0.62, use_caption_mask=True):
    """
    Masks out subtitle and UI bands so camera motion estimation does not follow
    burned-in captions, UI overlays, or black bars.
    """
    h, w = gray.shape[:2]
    mask = np.ones((h, w), dtype=np.uint8) * 255

    if use_caption_mask:
        mask[int(h * bottom_mask_start_y):h, :] = 0
    mask[:int(h * top_mask_end_y), :] = 0

    return mask


# -----------------------------
# Classification thresholds
# Tuned for 480p/540p vertical social video proxy.
# -----------------------------

DIRECTION_THRESHOLD = 0.0045
ZOOM_THRESHOLD = 0.0055
SUBTLE_ZOOM_THRESHOLD = 0.0025
SUBTLE_MOVE_THRESHOLD = 0.0028
OBJECT_MOTION_THRESHOLD = 0.006
MEDIUM_MOTION_THRESHOLD = 0.010
HIGH_MOTION_THRESHOLD = 0.022
SHAKE_RESIDUAL_THRESHOLD = 0.030
STATIC_MAG_THRESHOLD = 0.0015
SUBTLE_MAG_THRESHOLD = 0.0040

SPEED_RAMP_ALLOWED_INTENSITIES = {"medium", "high", "very_high"}
SPEED_RAMP_ALLOWED_FAMILIES = {"push_in", "pull_out", "pan_tilt", "shaky"}
SPEED_RAMP_MIN_P75_MAG = OBJECT_MOTION_THRESHOLD
SPEED_RAMP_MIN_DURATION = 0.80
SPEED_RAMP_MIN_VALID_SAMPLES = 5


# -----------------------------
# Motion classification
# -----------------------------

def direction_label(tx_norm, ty_norm, threshold=DIRECTION_THRESHOLD):
    horizontal = None
    vertical = None

    if tx_norm > threshold:
        horizontal = "pan_right"
    elif tx_norm < -threshold:
        horizontal = "pan_left"

    if ty_norm > threshold:
        vertical = "tilt_down"
    elif ty_norm < -threshold:
        vertical = "tilt_up"

    if horizontal and vertical:
        return f"{horizontal}_{vertical}"
    return horizontal or vertical or "none"


def intensity_label(mag):
    mag = safe_float(mag, 0.0)
    if mag < STATIC_MAG_THRESHOLD:
        return "static"
    if mag < SUBTLE_MAG_THRESHOLD:
        return "subtle"
    if mag < MEDIUM_MOTION_THRESHOLD:
        return "medium"
    if mag < HIGH_MOTION_THRESHOLD:
        return "high"
    return "very_high"


def classify_motion_type(scale_delta, tx_norm, ty_norm, residual_norm, magnitude_norm, inlier_ratio):
    scale_delta = safe_float(scale_delta, 0.0)
    tx_norm = safe_float(tx_norm, 0.0)
    ty_norm = safe_float(ty_norm, 0.0)
    residual_norm = safe_float(residual_norm, 0.0)
    magnitude_norm = safe_float(magnitude_norm, 0.0)
    inlier_ratio = safe_float(inlier_ratio, 0.0)

    direction = direction_label(tx_norm, ty_norm)

    if residual_norm > SHAKE_RESIDUAL_THRESHOLD and magnitude_norm > MEDIUM_MOTION_THRESHOLD:
        return "handheld_or_shaky"

    if scale_delta > ZOOM_THRESHOLD:
        return f"push_in_with_{direction}" if direction != "none" else "push_in"
    if scale_delta < -ZOOM_THRESHOLD:
        return f"pull_out_with_{direction}" if direction != "none" else "pull_out"

    if abs(tx_norm) > DIRECTION_THRESHOLD or abs(ty_norm) > DIRECTION_THRESHOLD:
        return direction

    if abs(scale_delta) > SUBTLE_ZOOM_THRESHOLD:
        return "subtle_push_in" if scale_delta > 0 else "subtle_pull_out"
    if abs(tx_norm) > SUBTLE_MOVE_THRESHOLD or abs(ty_norm) > SUBTLE_MOVE_THRESHOLD:
        subtle_direction = direction_label(tx_norm, ty_norm, threshold=SUBTLE_MOVE_THRESHOLD)
        return f"subtle_{subtle_direction}" if subtle_direction != "none" else "subtle_camera_drift"

    if magnitude_norm > OBJECT_MOTION_THRESHOLD:
        return "object_or_local_motion"

    if magnitude_norm > STATIC_MAG_THRESHOLD:
        return "subtle_motion"

    return "static"


def motion_family(motion_type):
    if not motion_type:
        return "unknown"
    motion_type = str(motion_type).lower()
    if motion_type == "static":
        return "static"
    if motion_type.startswith("subtle_push_in"):
        return "push_in"
    if motion_type.startswith("subtle_pull_out"):
        return "pull_out"
    if motion_type.startswith("subtle"):
        return "subtle"
    if "push_in" in motion_type:
        return "push_in"
    if "pull_out" in motion_type:
        return "pull_out"
    if "pan_" in motion_type or "tilt_" in motion_type:
        return "pan_tilt"
    if "shaky" in motion_type or "handheld" in motion_type:
        return "shaky"
    if "object_or_local" in motion_type:
        return "local_motion"
    return "other"


def estimate_pair_motion(prev_gray, next_gray, top_mask_end_y=0.06, bottom_mask_start_y=0.62, use_caption_mask=True):
    h, w = prev_gray.shape[:2]
    mask = build_feature_mask(
        prev_gray,
        top_mask_end_y=top_mask_end_y,
        bottom_mask_start_y=bottom_mask_start_y,
        use_caption_mask=use_caption_mask,
    )

    max_corners = 500
    min_distance = max(5, int(min(w, h) * 0.010))

    p0 = cv2.goodFeaturesToTrack(
        prev_gray,
        maxCorners=max_corners,
        qualityLevel=0.008,
        minDistance=min_distance,
        blockSize=7,
        mask=mask,
    )

    if p0 is None or len(p0) < 10:
        return {
            "valid": False,
            "reason": "not_enough_features",
            "feature_count": 0,
        }

    p1, status, _ = cv2.calcOpticalFlowPyrLK(
        prev_gray,
        next_gray,
        p0,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )

    if p1 is None or status is None:
        return {
            "valid": False,
            "reason": "optical_flow_failed",
            "feature_count": int(len(p0)),
        }

    good_old = p0[status.flatten() == 1]
    good_new = p1[status.flatten() == 1]

    if len(good_old) < 10:
        return {
            "valid": False,
            "reason": "not_enough_tracked_features",
            "feature_count": int(len(good_old)),
        }

    old_pts = good_old.reshape(-1, 2)
    new_pts = good_new.reshape(-1, 2)

    flow = new_pts - old_pts
    magnitudes = np.linalg.norm(flow, axis=1)
    median_mag = float(np.median(magnitudes))
    p75_mag = float(np.percentile(magnitudes, 75))
    p90_mag = float(np.percentile(magnitudes, 90))
    mean_mag = float(np.mean(magnitudes))
    magnitude_norm = median_mag / max(w, h)
    p75_magnitude_norm = p75_mag / max(w, h)
    p90_magnitude_norm = p90_mag / max(w, h)

    matrix, inliers = cv2.estimateAffinePartial2D(
        old_pts,
        new_pts,
        method=cv2.RANSAC,
        ransacReprojThreshold=2.8,
        maxIters=3000,
        confidence=0.985,
    )

    if matrix is None:
        return {
            "valid": True,
            "feature_count": int(len(old_pts)),
            "inlier_ratio": 0.0,
            "tx_norm": 0.0,
            "ty_norm": 0.0,
            "scale": 1.0,
            "scale_delta": 0.0,
            "rotation_deg": 0.0,
            "median_flow_px": rf(median_mag),
            "p75_flow_px": rf(p75_mag),
            "p90_flow_px": rf(p90_mag),
            "mean_flow_px": rf(mean_mag),
            "magnitude_norm": rf(magnitude_norm, 6),
            "p75_magnitude_norm": rf(p75_magnitude_norm, 6),
            "p90_magnitude_norm": rf(p90_magnitude_norm, 6),
            "residual_norm": 1.0,
            "motion_type": "object_or_local_motion" if magnitude_norm > OBJECT_MOTION_THRESHOLD else "subtle_motion",
            "intensity": intensity_label(magnitude_norm),
            "confidence": "low",
            "global_model_available": False,
        }

    a, b, tx = matrix[0]
    c, d, ty = matrix[1]

    scale = math.sqrt(a * a + c * c)
    rotation = math.degrees(math.atan2(c, a))

    predicted = cv2.transform(old_pts.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    residuals = np.linalg.norm(predicted - new_pts, axis=1)
    residual_norm = float(np.median(residuals)) / max(w, h)

    inlier_ratio = float(np.sum(inliers)) / max(1, len(inliers)) if inliers is not None else 0.0
    tx_norm = float(tx) / max(w, 1)
    ty_norm = float(ty) / max(h, 1)
    scale_delta = float(scale) - 1.0

    motion_type = classify_motion_type(
        scale_delta=scale_delta,
        tx_norm=tx_norm,
        ty_norm=ty_norm,
        residual_norm=residual_norm,
        magnitude_norm=magnitude_norm,
        inlier_ratio=inlier_ratio,
    )

    confidence = "high"
    if len(old_pts) < 18 or inlier_ratio < 0.30:
        confidence = "low"
    elif inlier_ratio < 0.50:
        confidence = "medium"

    return {
        "valid": True,
        "feature_count": int(len(old_pts)),
        "inlier_ratio": rf(inlier_ratio),
        "tx_norm": rf(tx_norm, 6),
        "ty_norm": rf(ty_norm, 6),
        "scale": rf(scale, 6),
        "scale_delta": rf(scale_delta, 6),
        "rotation_deg": rf(rotation, 4),
        "median_flow_px": rf(median_mag),
        "p75_flow_px": rf(p75_mag),
        "p90_flow_px": rf(p90_mag),
        "mean_flow_px": rf(mean_mag),
        "magnitude_norm": rf(magnitude_norm, 6),
        "p75_magnitude_norm": rf(p75_magnitude_norm, 6),
        "p90_magnitude_norm": rf(p90_magnitude_norm, 6),
        "residual_norm": rf(residual_norm, 6),
        "motion_type": motion_type,
        "intensity": intensity_label(magnitude_norm),
        "confidence": confidence,
        "global_model_available": True,
    }


# -----------------------------
# Shot sampling and aggregation
# -----------------------------

def sample_times_for_shot(start, end, samples_per_shot):
    duration = end - start
    if duration <= 0.18:
        return []

    safe_margin = min(0.08, duration * 0.12)
    safe_start = start + safe_margin
    safe_end = end - safe_margin
    if safe_end <= safe_start:
        return []

    count = min(samples_per_shot, max(2, int(duration / 0.22)))
    count = max(1, count)

    if count == 1:
        return [(safe_start + safe_end) / 2]

    return [float(t) for t in np.linspace(safe_start, safe_end, count)]


def mean_or_zero(values):
    clean = [safe_float(v, None) for v in values]
    clean = [v for v in clean if v is not None]
    return float(np.mean(clean)) if clean else 0.0


def median_or_zero(values):
    clean = [safe_float(v, None) for v in values]
    clean = [v for v in clean if v is not None]
    return float(np.median(clean)) if clean else 0.0


def percentile_or_zero(values, percentile=75):
    clean = [safe_float(v, None) for v in values]
    clean = [v for v in clean if v is not None]
    return float(np.percentile(clean, percentile)) if clean else 0.0


def longest_monotonic_run(values, direction="up"):
    if len(values) < 2:
        return 0
    best = 1
    current = 1
    for i in range(1, len(values)):
        if direction == "up":
            ok = values[i] >= values[i - 1]
        else:
            ok = values[i] <= values[i - 1]
        if ok:
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


def aggregate_shot_motion(pair_results):
    valid = [r for r in pair_results if r and r.get("valid")]
    invalid_count = len([r for r in pair_results if r and not r.get("valid")])

    if not valid:
        return {
            "motion_type": "unknown",
            "motion_intensity": "static",
            "confidence": "low",
            "avg_scale_delta": 0.0,
            "avg_tx_norm": 0.0,
            "avg_ty_norm": 0.0,
            "avg_magnitude_norm": 0.0,
            "avg_p75_magnitude_norm": 0.0,
            "avg_p90_magnitude_norm": 0.0,
            "avg_rotation_deg": 0.0,
            "avg_inlier_ratio": 0.0,
            "avg_residual_norm": 0.0,
            "invalid_samples": invalid_count,
        }

    avg_scale_delta = median_or_zero([r.get("scale_delta") for r in valid])
    avg_tx = median_or_zero([r.get("tx_norm") for r in valid])
    avg_ty = median_or_zero([r.get("ty_norm") for r in valid])
    avg_mag = median_or_zero([r.get("magnitude_norm") for r in valid])
    avg_p75_mag = median_or_zero([r.get("p75_magnitude_norm") for r in valid])
    avg_p90_mag = median_or_zero([r.get("p90_magnitude_norm") for r in valid])
    avg_rot = median_or_zero([r.get("rotation_deg") for r in valid])
    avg_residual = median_or_zero([r.get("residual_norm") for r in valid])
    avg_inlier = median_or_zero([r.get("inlier_ratio") for r in valid])

    motion_type = classify_motion_type(
        scale_delta=avg_scale_delta,
        tx_norm=avg_tx,
        ty_norm=avg_ty,
        residual_norm=avg_residual,
        magnitude_norm=avg_mag,
        inlier_ratio=avg_inlier,
    )

    high_conf = len([r for r in valid if r.get("confidence") == "high"])
    med_conf = len([r for r in valid if r.get("confidence") == "medium"])
    total = max(1, len(valid))

    if high_conf / total >= 0.45 and avg_inlier >= 0.50:
        confidence = "high"
    elif (high_conf + med_conf) / total >= 0.45 and avg_inlier >= 0.30:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "motion_type": motion_type,
        "motion_intensity": intensity_label(avg_mag),
        "confidence": confidence,
        "avg_scale_delta": rf(avg_scale_delta, 6),
        "avg_tx_norm": rf(avg_tx, 6),
        "avg_ty_norm": rf(avg_ty, 6),
        "avg_magnitude_norm": rf(avg_mag, 6),
        "avg_p75_magnitude_norm": rf(avg_p75_mag, 6),
        "avg_p90_magnitude_norm": rf(avg_p90_mag, 6),
        "avg_rotation_deg": rf(avg_rot, 4),
        "avg_inlier_ratio": rf(avg_inlier, 4),
        "avg_residual_norm": rf(avg_residual, 6),
        "valid_samples": len(valid),
        "invalid_samples": invalid_count,
    }


def detect_speed_change(pair_results):
    valid = [r for r in pair_results if r and r.get("valid")]

    if len(valid) < 5:
        return {
            "speed_change": "constant_or_unknown",
            "speed_change_confidence": "low",
            "reason": "not_enough_samples",
            "speed_curve": [],
            "score": 0.0,
        }

    mags = np.array([safe_float(r.get("p75_magnitude_norm", r.get("magnitude_norm", 0.0)), 0.0) for r in valid], dtype=float)
    median_mag = float(np.median(mags))

    curve = []
    max_mag = max(float(np.max(mags)), 1e-6)
    for i, r in enumerate(valid):
        curve.append({
            "index": i,
            "time": r.get("time"),
            "relative_position": rf(i / max(1, len(valid) - 1), 4),
            "motion": rf(mags[i], 6),
            "normalized_motion": rf(float(mags[i]) / max_mag, 4),
        })

    if median_mag < SUBTLE_MAG_THRESHOLD:
        return {
            "speed_change": "constant",
            "speed_change_confidence": "medium",
            "reason": "too_little_motion_for_speed_ramp",
            "median_motion": rf(median_mag, 6),
            "speed_curve": curve,
            "score": 0.0,
        }

    n = len(mags)
    third = max(1, n // 3)
    first = float(np.mean(mags[:third]))
    middle = float(np.mean(mags[third: -third])) if n > 2 * third else float(np.mean(mags))
    last = float(np.mean(mags[-third:]))

    diff = last - first
    ratio = (last + 1e-6) / (first + 1e-6)

    monotonic_up = longest_monotonic_run(list(mags), "up") / max(1, n)
    monotonic_down = longest_monotonic_run(list(mags), "down") / max(1, n)

    abs_threshold = 0.008
    rel_threshold_up = 1.65
    rel_threshold_down = 0.60

    if diff > abs_threshold and ratio >= rel_threshold_up:
        score = clamp(0.45 + min(0.35, (ratio - rel_threshold_up) * 0.16) + monotonic_up * 0.20)
        conf = "high" if score >= 0.72 else "medium"
        return {
            "speed_change": "speed_up_candidate",
            "speed_change_confidence": conf,
            "first_motion": rf(first, 6),
            "middle_motion": rf(middle, 6),
            "last_motion": rf(last, 6),
            "ratio": rf(ratio, 4),
            "diff": rf(diff, 6),
            "monotonicity": rf(monotonic_up, 4),
            "speed_curve": curve,
            "score": rf(score, 4),
        }

    if diff < -abs_threshold and ratio <= rel_threshold_down:
        score = clamp(0.45 + min(0.35, (rel_threshold_down - ratio) * 0.75) + monotonic_down * 0.20)
        conf = "high" if score >= 0.72 else "medium"
        return {
            "speed_change": "slow_down_candidate",
            "speed_change_confidence": conf,
            "first_motion": rf(first, 6),
            "middle_motion": rf(middle, 6),
            "last_motion": rf(last, 6),
            "ratio": rf(ratio, 4),
            "diff": rf(diff, 6),
            "monotonicity": rf(monotonic_down, 4),
            "speed_curve": curve,
            "score": rf(score, 4),
        }

    return {
        "speed_change": "constant",
        "speed_change_confidence": "medium",
        "first_motion": rf(first, 6),
        "middle_motion": rf(middle, 6),
        "last_motion": rf(last, 6),
        "ratio": rf(ratio, 4),
        "diff": rf(diff, 6),
        "monotonicity": rf(max(monotonic_up, monotonic_down), 4),
        "speed_curve": curve,
        "score": 0.0,
    }


# -----------------------------
# Editor-contract helpers
# -----------------------------

def zoom_scale_for_intensity(intensity, subtle_scale=1.06, medium_scale=1.12, strong_scale=1.18):
    if intensity in {"high", "very_high"}:
        return strong_scale
    if intensity == "medium":
        return medium_scale
    return subtle_scale


def build_zoom_profile(segment, fps, subtle_scale=1.06, medium_scale=1.12, strong_scale=1.18):
    family = segment.get("motion_family")
    intensity = segment.get("motion_intensity")
    duration_frames = safe_int(segment.get("duration_frames"), 1) or 1
    last_frame = max(1, duration_frames - 1)

    if family not in {"push_in", "pull_out"}:
        return {
            "candidate": False,
            "reason": f"motion_family_not_zoomable:{family}",
        }

    scale = round(zoom_scale_for_intensity(intensity, subtle_scale, medium_scale, strong_scale), 4)
    direction = "in" if family == "push_in" else "out"

    if direction == "in":
        start_scale = 1.0
        end_scale = scale
    else:
        start_scale = scale
        end_scale = 1.0

    return {
        "candidate": True,
        "operation": "transform_zoom",
        "direction": direction,
        "confidence": segment.get("confidence"),
        "strength": "strong" if intensity in {"high", "very_high"} else "medium" if intensity == "medium" else "subtle",
        "start_scale": round(start_scale, 4),
        "end_scale": round(end_scale, 4),
        "easing": "ease_in_out",
        "preferred_timing": "full_shot",
        "keyframes": [
            {
                "relative_frame": 0,
                "time_offset": 0.0,
                "scale": round(start_scale, 4),
                "zoom": round(start_scale, 4),
            },
            {
                "relative_frame": last_frame,
                "time_offset": rf(last_frame / max(fps, 1e-6), 4),
                "scale": round(end_scale, 4),
                "zoom": round(end_scale, 4),
            },
        ],
        "source": "motion_affine_scale_delta",
    }


def validate_speed_ramp_candidate(segment, speed, min_score=0.45):
    change = speed.get("speed_change")
    if change not in {"speed_up_candidate", "slow_down_candidate"}:
        return False, "not_a_speed_ramp_label"

    if speed.get("speed_change_confidence") == "low":
        return False, "low_speed_change_confidence"

    if safe_float(segment.get("duration_seconds"), 0.0) < SPEED_RAMP_MIN_DURATION:
        return False, "shot_too_short"

    if safe_int(segment.get("samples_analyzed"), 0) < SPEED_RAMP_MIN_VALID_SAMPLES:
        return False, "not_enough_valid_samples"

    intensity = segment.get("motion_intensity")
    if intensity not in SPEED_RAMP_ALLOWED_INTENSITIES:
        return False, f"motion_intensity_not_allowed:{intensity}"

    family = segment.get("motion_family")
    if family not in SPEED_RAMP_ALLOWED_FAMILIES:
        return False, f"motion_family_not_allowed:{family}"

    camera_motion = segment.get("camera_motion", {}) or {}
    p75_mag = safe_float(camera_motion.get("avg_p75_magnitude_norm"), 0.0)
    if p75_mag < SPEED_RAMP_MIN_P75_MAG:
        return False, f"p75_motion_too_low:{rf(p75_mag, 6)}"

    if safe_float(speed.get("score"), 0.0) < min_score:
        return False, f"speed_ramp_score_too_low:{rf(speed.get('score'), 4)}"

    return True, "accepted"


def build_speed_ramp_profile(segment, speed, fps, min_score=0.45):
    is_ramp, reason = validate_speed_ramp_candidate(segment, speed, min_score=min_score)

    profile = {
        "candidate": bool(is_ramp),
        "actionable": False,
        "authority": "motion_heuristic_only",
        "source": "optical_flow_p75_motion_curve",
        "speed_change": speed.get("speed_change"),
        "confidence": speed.get("speed_change_confidence"),
        "score": safe_float(speed.get("score"), 0.0),
        "filter_reason": reason,
        "speed_curve": speed.get("speed_curve", []),
        "missing_authority": "source-backed time mapping or original pre-retime footage",
        "reason": (
            "optical-flow motion change is not a measured playback-speed change; "
            "source-backed time mapping or original pre-retime footage is missing"
        ),
    }

    if not is_ramp:
        profile["degraded_to"] = "normal_speed"

    return profile


def build_editor_contract(segment, zoom_profile, speed_ramp_profile):
    speed_ramp_actionable = bool(speed_ramp_profile.get("actionable"))
    return {
        "motion_layer_ready": True,
        "zoom_candidate": bool(zoom_profile.get("candidate")),
        "speed_ramp_candidate": bool(speed_ramp_profile.get("candidate")),
        "recommended_operations": [
            op for op in [
                "transform_zoom" if zoom_profile.get("candidate") else None,
                "speed_ramp" if speed_ramp_actionable else None,
            ] if op
        ],
        "resolve_controller": {
            "animated_zoom_ready": bool(zoom_profile.get("candidate")),
            "speed_ramp_ready": speed_ramp_actionable,
            "speed_ramp_note": "Motion evidence is non-actionable without source-backed retime authority.",
        },
        "generic_compiler": {
            "can_emit_transform_zoom_keyframes": bool(zoom_profile.get("candidate")),
            "can_emit_speed_ramp_segments": speed_ramp_actionable,
        },
    }


# -----------------------------
# Main motion analysis
# -----------------------------

def analyze_motion(
    video_path,
    shots,
    samples_per_shot,
    pair_delta,
    min_shot_duration,
    include_pair_samples=False,
    top_mask_end_y=0.06,
    bottom_mask_start_y=0.62,
    use_caption_mask=True,
    speed_ramp_min_score=0.45,
    subtle_zoom_scale=1.06,
    medium_zoom_scale=1.12,
    strong_zoom_scale=1.18,
):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    info = get_video_info(video_path)
    fps = safe_float(info.get("fps"), 24.0)
    duration = safe_float(info.get("duration"), 0.0)

    if not shots:
        shots = [{
            "shot_id": 1,
            "index": 0,
            "start_seconds": 0.0,
            "end_seconds": duration,
            "duration_seconds": duration,
            "start_frame": 0,
            "end_frame": safe_int(duration * fps, None),
            "duration_frames": safe_int(duration * fps, None),
        }]

    segments = []
    speed_change_candidates = []
    zoom_candidates = []

    for shot in shots:
        shot_id = shot.get("shot_id") or shot.get("scene_index")
        start = safe_float(shot.get("start_seconds", 0.0), 0.0)
        end = safe_float(shot.get("end_seconds", start), start)
        start = max(0.0, min(start, duration))
        end = max(start, min(end, duration))
        shot_duration = max(0.0, end - start)

        start_frame = safe_int(shot.get("start_frame"), int(round(start * fps)))
        end_frame = safe_int(shot.get("end_frame"), int(round(end * fps)))
        duration_frames = max(1, safe_int(shot.get("duration_frames"), end_frame - start_frame))

        pair_results = []

        if shot_duration >= min_shot_duration:
            times = sample_times_for_shot(start, end, samples_per_shot)
            for sample_index, t in enumerate(times):
                local_delta = min(pair_delta, max(0.06, (end - t) * 0.75))
                t2 = min(t + local_delta, end - 0.015)
                if t2 <= t:
                    continue

                frame1 = read_frame_at(cap, t)
                frame2 = read_frame_at(cap, t2)
                if frame1 is None or frame2 is None:
                    pair_results.append({
                        "valid": False,
                        "reason": "frame_read_failed",
                        "sample_index": sample_index,
                        "time": rf(t),
                        "next_time": rf(t2),
                    })
                    continue

                gray1 = preprocess_gray(frame1)
                gray2 = preprocess_gray(frame2)
                result = estimate_pair_motion(
                    gray1,
                    gray2,
                    top_mask_end_y=top_mask_end_y,
                    bottom_mask_start_y=bottom_mask_start_y,
                    use_caption_mask=use_caption_mask,
                )
                result["sample_index"] = sample_index
                result["time"] = rf(t)
                result["next_time"] = rf(t2)
                result["relative_time"] = rf(max(0.0, t - start), 4)
                result["relative_position"] = rf((t - start) / shot_duration if shot_duration > 0 else 0.0, 4)
                result["source_frame"] = int(round(t * fps))
                result["relative_frame"] = max(0, int(round((t - start) * fps)))
                pair_results.append(result)

        aggregated = aggregate_shot_motion(pair_results)
        speed = detect_speed_change(pair_results)

        base_segment = {
            "shot_id": safe_int(shot_id),
            "index": shot.get("index"),
            "start_seconds": rf(start),
            "end_seconds": rf(end),
            "duration_seconds": rf(shot_duration),
            "start_frame": start_frame,
            "end_frame": end_frame,
            "duration_frames": duration_frames,
            "source_start_frame": start_frame,
            "source_end_frame": end_frame,
            "source_duration_frames": duration_frames,
            "timeline_start_frame": start_frame,
            "timeline_end_frame": end_frame,
            "timeline_duration_frames": duration_frames,
            "motion_type": aggregated["motion_type"],
            "motion_family": motion_family(aggregated["motion_type"]),
            "motion_intensity": aggregated["motion_intensity"],
            "confidence": aggregated["confidence"],
            "camera_motion": {
                "avg_scale_delta": aggregated["avg_scale_delta"],
                "avg_tx_norm": aggregated["avg_tx_norm"],
                "avg_ty_norm": aggregated["avg_ty_norm"],
                "avg_rotation_deg": aggregated["avg_rotation_deg"],
                "avg_magnitude_norm": aggregated["avg_magnitude_norm"],
                "avg_p75_magnitude_norm": aggregated.get("avg_p75_magnitude_norm"),
                "avg_p90_magnitude_norm": aggregated.get("avg_p90_magnitude_norm"),
                "avg_inlier_ratio": aggregated.get("avg_inlier_ratio"),
                "avg_residual_norm": aggregated.get("avg_residual_norm"),
            },
            "global_motion": {
                "translation": {
                    "x_norm": aggregated["avg_tx_norm"],
                    "y_norm": aggregated["avg_ty_norm"],
                    "direction": direction_label(
                        safe_float(aggregated["avg_tx_norm"], 0.0),
                        safe_float(aggregated["avg_ty_norm"], 0.0),
                    ),
                },
                "scale_delta": aggregated["avg_scale_delta"],
                "rotation_deg": aggregated["avg_rotation_deg"],
                "inlier_ratio": aggregated.get("avg_inlier_ratio"),
                "residual_norm": aggregated.get("avg_residual_norm"),
            },
            "local_motion": {
                "magnitude_norm": aggregated["avg_magnitude_norm"],
                "p75_magnitude_norm": aggregated.get("avg_p75_magnitude_norm"),
                "p90_magnitude_norm": aggregated.get("avg_p90_magnitude_norm"),
            },
            "speed_change": speed["speed_change"],
            "speed_change_confidence": speed["speed_change_confidence"],
            "speed_change_score": speed.get("score", 0.0),
            "samples_analyzed": len([r for r in pair_results if r and r.get("valid")]),
            "invalid_samples": aggregated.get("invalid_samples", 0),
        }

        zoom_profile = build_zoom_profile(
            base_segment,
            fps=fps,
            subtle_scale=subtle_zoom_scale,
            medium_scale=medium_zoom_scale,
            strong_scale=strong_zoom_scale,
        )
        speed_ramp_profile = build_speed_ramp_profile(
            base_segment,
            speed,
            fps=fps,
            min_score=speed_ramp_min_score,
        )

        is_ramp = bool(speed_ramp_profile.get("candidate"))
        ramp_reason = speed_ramp_profile.get("filter_reason")

        segment = {
            **base_segment,
            "motion_profile": {
                "family": base_segment["motion_family"],
                "type": base_segment["motion_type"],
                "intensity": base_segment["motion_intensity"],
                "confidence": base_segment["confidence"],
                "camera_motion": base_segment["camera_motion"],
                "global_motion": base_segment["global_motion"],
                "local_motion": base_segment["local_motion"],
            },
            "motion_based_zoom": zoom_profile,
            "zoom_profile": zoom_profile,
            "zoom_candidate": bool(zoom_profile.get("candidate")),
            "speed_ramp_profile": speed_ramp_profile,
            "speed_ramp_candidate": bool(is_ramp),
            "speed_ramp_filter_reason": ramp_reason,
            "editor_contract": None,
        }

        segment["editor_contract"] = build_editor_contract(segment, zoom_profile, speed_ramp_profile)

        if not is_ramp and segment["speed_change"] in {"speed_up_candidate", "slow_down_candidate"}:
            segment["raw_speed_change"] = segment["speed_change"]
            segment["raw_speed_change_profile"] = {
                "speed_change": speed.get("speed_change"),
                "confidence": speed.get("speed_change_confidence"),
                "score": speed.get("score"),
                "reason": ramp_reason,
                "speed_curve": speed.get("speed_curve", []),
            }
            segment["speed_change"] = "constant"
            segment["speed_change_confidence"] = "medium"

        if include_pair_samples:
            segment["pair_samples"] = pair_results

        segments.append(segment)

        if zoom_profile.get("candidate"):
            zoom_candidates.append({
                "shot_id": segment["shot_id"],
                "start_seconds": segment["start_seconds"],
                "end_seconds": segment["end_seconds"],
                "start_frame": segment["start_frame"],
                "end_frame": segment["end_frame"],
                "direction": zoom_profile.get("direction"),
                "confidence": zoom_profile.get("confidence"),
                "strength": zoom_profile.get("strength"),
                "start_scale": zoom_profile.get("start_scale"),
                "end_scale": zoom_profile.get("end_scale"),
                "keyframes": zoom_profile.get("keyframes"),
                "motion_type": segment["motion_type"],
                "motion_intensity": segment["motion_intensity"],
            })

        if is_ramp:
            speed_change_candidates.append({
                "shot_id": segment["shot_id"],
                "start_seconds": segment["start_seconds"],
                "end_seconds": segment["end_seconds"],
                "start_frame": segment["start_frame"],
                "end_frame": segment["end_frame"],
                "type": speed.get("speed_change"),
                "confidence": speed.get("speed_change_confidence"),
                "score": speed.get("score"),
                "motion_intensity": segment["motion_intensity"],
                "motion_family": segment["motion_family"],
                "motion_type": segment["motion_type"],
                "avg_p75_magnitude_norm": segment["camera_motion"].get("avg_p75_magnitude_norm"),
                "filter_reason": ramp_reason,
                "profile": speed_ramp_profile,
            })

    cap.release()
    return info, segments, speed_change_candidates, zoom_candidates


# -----------------------------
# Summary
# -----------------------------

def build_summary(segments):
    usable = [s for s in segments if s.get("motion_type") != "unknown"]
    if not usable:
        return {
            "dominant_motion_type": "unknown",
            "dominant_non_static_motion_type": "unknown",
            "dominant_motion_family": "unknown",
            "average_motion_intensity": "static",
            "has_speed_ramps": False,
            "camera_movement_confidence": "low",
            "segments_count": len(segments),
            "zoom_candidates_count": 0,
            "speed_ramp_candidates_count": 0,
        }

    counts = {}
    non_static_counts = {}
    family_counts = {}
    for s in usable:
        mt = s.get("motion_type", "unknown")
        fam = s.get("motion_family", motion_family(mt))
        counts[mt] = counts.get(mt, 0) + 1
        family_counts[fam] = family_counts.get(fam, 0) + 1
        if mt not in {"static", "subtle_motion"} and not str(mt).startswith("subtle_"):
            non_static_counts[mt] = non_static_counts.get(mt, 0) + 1

    dominant = max(counts, key=counts.get)
    dominant_non_static = max(non_static_counts, key=non_static_counts.get) if non_static_counts else "none"
    dominant_family = max(family_counts, key=family_counts.get)

    rank = {"static": 0, "subtle": 1, "low": 1, "medium": 2, "high": 3, "very_high": 4}
    avg_rank = float(np.mean([rank.get(s.get("motion_intensity"), 0) for s in usable]))
    if avg_rank < 0.5:
        avg_intensity = "static"
    elif avg_rank < 1.5:
        avg_intensity = "subtle"
    elif avg_rank < 2.5:
        avg_intensity = "medium"
    elif avg_rank < 3.5:
        avg_intensity = "high"
    else:
        avg_intensity = "very_high"

    conf_rank = {"low": 1, "medium": 2, "high": 3}
    avg_conf = float(np.mean([conf_rank.get(s.get("confidence"), 1) for s in usable]))
    conf = "high" if avg_conf >= 2.4 else "medium" if avg_conf >= 1.6 else "low"

    speed_ramp_candidates = [s for s in usable if s.get("speed_ramp_candidate") is True]
    zoom_candidates = [s for s in usable if s.get("zoom_candidate") is True]

    return {
        "dominant_motion_type": dominant,
        "dominant_non_static_motion_type": dominant_non_static,
        "dominant_motion_family": dominant_family,
        "average_motion_intensity": avg_intensity,
        "has_speed_ramps": False,
        "speed_ramp_candidates_count": len(speed_ramp_candidates),
        "zoom_candidates_count": len(zoom_candidates),
        "camera_movement_confidence": conf,
        "segments_count": len(segments),
        "motion_type_counts": counts,
        "motion_family_counts": family_counts,
        "editor_contract": {
            "motion_layer_ready": True,
            "transform_zoom_profiles_ready": len(zoom_candidates) > 0,
            "speed_ramp_profiles_ready": False,
            "note": "Animated zoom is controller-ready. Speed-change candidates are non-actionable motion evidence without source-backed retime authority.",
        },
    }


def compact_segment(segment):
    out = dict(segment)
    out.pop("pair_samples", None)
    return out


def compact_output(output):
    return {
        "success": output["success"],
        "schema": output["schema"],
        "schema_version": output["schema_version"],
        "analysis_version": output["analysis_version"],
        "created_at_unix": output["created_at_unix"],
        "video_path": output["video_path"],
        "video_info": output["video_info"],
        "motion_summary": output["motion_summary"],
        "segments": [compact_segment(s) for s in output["segments"]],
        "speed_change_candidates": output["speed_change_candidates"],
        "zoom_candidates": output["zoom_candidates"],
        "debug": output["debug"],
        "errors": output["errors"],
    }


def run(
    video_path,
    shots_json,
    output_json,
    output_mode,
    samples_per_shot,
    pair_delta,
    min_shot_duration,
    include_pair_samples=False,
    top_mask_end_y=0.06,
    bottom_mask_start_y=0.62,
    use_caption_mask=True,
    speed_ramp_min_score=0.45,
    subtle_zoom_scale=1.06,
    medium_zoom_scale=1.12,
    strong_zoom_scale=1.18,
):
    started = time.monotonic()
    errors = []

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    ensure_dir_for_file(output_json)

    video_info_probe = get_video_info(video_path)
    fps = safe_float(video_info_probe.get("fps"), 24.0)

    try:
        shots = load_shots_from_arg(shots_json, fps=fps)
    except Exception as e:
        raise ValueError(f"Could not load shots JSON/path: {e}")

    video_info, segments, speed_change_candidates, zoom_candidates = analyze_motion(
        video_path=video_path,
        shots=shots,
        samples_per_shot=samples_per_shot,
        pair_delta=pair_delta,
        min_shot_duration=min_shot_duration,
        include_pair_samples=include_pair_samples or output_mode == "full",
        top_mask_end_y=top_mask_end_y,
        bottom_mask_start_y=bottom_mask_start_y,
        use_caption_mask=use_caption_mask,
        speed_ramp_min_score=speed_ramp_min_score,
        subtle_zoom_scale=subtle_zoom_scale,
        medium_zoom_scale=medium_zoom_scale,
        strong_zoom_scale=strong_zoom_scale,
    )

    output = {
        "success": True,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "created_at_unix": round(time.time(), 3),
        "video_path": video_path,
        "video_info": video_info,
        "motion_summary": build_summary(segments),
        "segments": segments,
        "speed_change_candidates": speed_change_candidates,
        "zoom_candidates": zoom_candidates,
        "editor_contract": {
            "provides_motion_based_zoom": True,
            "provides_speed_ramp_profiles": False,
            "provides_frame_accurate_ranges": True,
            "consumer_layers": [
                "merge_analysis.py",
                "plan_edit.py",
                "compile_generic_edit.py",
                "resolve_apply_video_cloner_metadata.py",
            ],
        },
        "debug": {
            "output_mode": output_mode,
            "shots_input_count": len(shots),
            "samples_per_shot": samples_per_shot,
            "pair_delta": pair_delta,
            "min_shot_duration": min_shot_duration,
            "include_pair_samples": include_pair_samples,
            "feature_mask": {
                "enabled": bool(use_caption_mask),
                "top_mask_end_y": top_mask_end_y,
                "bottom_mask_start_y": bottom_mask_start_y,
                "description": "top UI band and lower caption band removed from optical-flow feature detection",
            },
            "thresholds": {
                "static_mag_threshold": STATIC_MAG_THRESHOLD,
                "subtle_mag_threshold": SUBTLE_MAG_THRESHOLD,
                "direction_threshold": DIRECTION_THRESHOLD,
                "zoom_threshold": ZOOM_THRESHOLD,
                "object_motion_threshold": OBJECT_MOTION_THRESHOLD,
                "speed_ramp_allowed_intensities": sorted(SPEED_RAMP_ALLOWED_INTENSITIES),
                "speed_ramp_allowed_families": sorted(SPEED_RAMP_ALLOWED_FAMILIES),
                "speed_ramp_min_p75_mag": SPEED_RAMP_MIN_P75_MAG,
                "speed_ramp_min_duration": SPEED_RAMP_MIN_DURATION,
                "speed_ramp_min_valid_samples": SPEED_RAMP_MIN_VALID_SAMPLES,
                "speed_ramp_min_score": speed_ramp_min_score,
                "zoom_scales": {
                    "subtle": subtle_zoom_scale,
                    "medium": medium_zoom_scale,
                    "strong": strong_zoom_scale,
                },
            },
            "runtime_sec": round(time.monotonic() - started, 4),
        },
        "errors": errors,
    }

    if output_mode == "compact":
        final_output = compact_output(output)
    elif output_mode == "full":
        final_output = output
    else:
        final_output = compact_output(output)
        full_debug_path = output_json.replace(".json", "_full_debug.json")
        with open(full_debug_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        final_output["debug"]["full_debug_json"] = full_debug_path

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    summary = output["motion_summary"]
    print(json.dumps({
        "success": True,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "output_json": output_json,
        "video_duration": video_info.get("duration"),
        "segments_count": len(segments),
        "dominant_motion_type": summary.get("dominant_motion_type"),
        "dominant_non_static_motion_type": summary.get("dominant_non_static_motion_type"),
        "dominant_motion_family": summary.get("dominant_motion_family"),
        "average_motion_intensity": summary.get("average_motion_intensity"),
        "zoom_candidates_count": summary.get("zoom_candidates_count"),
        "has_speed_ramps": summary.get("has_speed_ramps"),
        "speed_ramp_candidates_count": summary.get("speed_ramp_candidates_count"),
        "camera_movement_confidence": summary.get("camera_movement_confidence"),
        "errors_count": len(errors),
        "output_mode": output_mode,
        "runtime_sec": output["debug"]["runtime_sec"],
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect camera motion and speed-ramp candidates from a proxy video.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--shots", required=False, default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--output-mode", choices=["compact", "full", "both"], default="compact")
    parser.add_argument("--samples-per-shot", type=int, default=7)
    parser.add_argument("--pair-delta", type=float, default=0.18)
    parser.add_argument("--min-shot-duration", type=float, default=0.35)

    parser.add_argument("--include-pair-samples", type=bool_arg, default=False)
    parser.add_argument("--use-caption-mask", type=bool_arg, default=True)
    parser.add_argument("--top-mask-end-y", type=float, default=0.06)
    parser.add_argument("--bottom-mask-start-y", type=float, default=0.62)

    parser.add_argument("--speed-ramp-min-score", type=float, default=0.45)
    parser.add_argument("--subtle-zoom-scale", type=float, default=1.06)
    parser.add_argument("--medium-zoom-scale", type=float, default=1.12)
    parser.add_argument("--strong-zoom-scale", type=float, default=1.18)

    args = parser.parse_args()

    try:
        run(
            video_path=args.video,
            shots_json=args.shots,
            output_json=args.output,
            output_mode=args.output_mode,
            samples_per_shot=max(2, args.samples_per_shot),
            pair_delta=max(0.04, args.pair_delta),
            min_shot_duration=max(0.10, args.min_shot_duration),
            include_pair_samples=args.include_pair_samples,
            top_mask_end_y=clamp(args.top_mask_end_y, 0.0, 0.35),
            bottom_mask_start_y=clamp(args.bottom_mask_start_y, 0.45, 0.95),
            use_caption_mask=args.use_caption_mask,
            speed_ramp_min_score=clamp(args.speed_ramp_min_score, 0.0, 1.0),
            subtle_zoom_scale=max(1.0, args.subtle_zoom_scale),
            medium_zoom_scale=max(1.0, args.medium_zoom_scale),
            strong_zoom_scale=max(1.0, args.strong_zoom_scale),
        )
    except Exception as e:
        json_error(e, output_json=args.output if "args" in locals() else None)
        sys.exit(1)
