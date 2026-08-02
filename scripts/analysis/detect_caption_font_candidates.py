#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import cv2
    import numpy as np
except Exception as exc:
    raise SystemExit(
        "OpenCV and NumPy are required. Run this script with the Video Cloner OCR venv. "
        f"Import error: {exc}"
    )

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:
    raise SystemExit(f"Pillow is required: {exc}")

try:
    from fontTools.ttLib import TTCollection, TTFont
except Exception as exc:
    raise SystemExit(
        "fontTools is required. Install it in venv_ocr with: pip install fonttools\n"
        f"Import error: {exc}"
    )


VERSION = "caption_font_detector_v1_0_1_safe_glyph_rendering"
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}
WINDOWS_FONT_ROOTS = {
    str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts").lower(),
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts").lower(),
}


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def parse_hex_color(value: Any) -> Optional[Tuple[int, int, int]]:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        return None
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))


def normalize_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalized_token(value: Any) -> str:
    return "".join(ch.lower() for ch in normalize_text(value) if ch.isalnum())


def safe_name(record: Any) -> Optional[str]:
    try:
        value = record.toUnicode()
    except Exception:
        try:
            value = record.string.decode(record.getEncoding(), errors="ignore")
        except Exception:
            return None
    value = " ".join(str(value).split()).strip()
    return value or None


def best_name(font: TTFont, ids: Sequence[int]) -> Optional[str]:
    table = font.get("name")
    if table is None:
        return None
    candidates: List[Tuple[int, str]] = []
    for record in table.names:
        if record.nameID not in ids:
            continue
        value = safe_name(record)
        if not value:
            continue
        priority = 0
        if record.platformID == 3:
            priority += 20
        if record.langID in (0x409, 0):
            priority += 10
        priority += max(0, 5 - ids.index(record.nameID))
        candidates.append((priority, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], len(item[1]), item[1].lower()))
    return candidates[0][1]


def is_path_installed(path: Path) -> bool:
    lower = str(path.resolve()).lower()
    for root in WINDOWS_FONT_ROOTS:
        if root and lower.startswith(root):
            return True
    return False


def font_faces_from_path(path: Path) -> List[Dict[str, Any]]:
    faces: List[Dict[str, Any]] = []
    suffix = path.suffix.lower()
    count = 1
    if suffix in {".ttc", ".otc"}:
        try:
            collection = TTCollection(str(path), lazy=True)
            count = len(collection.fonts)
            collection.close()
        except Exception:
            count = 1

    for index in range(count):
        try:
            font = TTFont(
                str(path),
                fontNumber=index if suffix in {".ttc", ".otc"} else 0,
                lazy=True,
                recalcBBoxes=False,
                recalcTimestamp=False,
            )
            family = best_name(font, (16, 1)) or path.stem
            face = best_name(font, (17, 2)) or "Regular"
            full_name = best_name(font, (4,)) or f"{family} {face}".strip()
            postscript = best_name(font, (6,))
            weight = 400
            italic = False
            os2 = font.get("OS/2")
            if os2 is not None:
                weight = int(getattr(os2, "usWeightClass", 400) or 400)
                fs_selection = int(getattr(os2, "fsSelection", 0) or 0)
                italic = bool(fs_selection & 0x01)
            post = font.get("post")
            if post is not None:
                italic = italic or abs(float(getattr(post, "italicAngle", 0.0) or 0.0)) > 0.01
            variable_axes = []
            fvar = font.get("fvar")
            if fvar is not None:
                for axis in fvar.axes:
                    variable_axes.append({
                        "tag": str(axis.axisTag),
                        "min": float(axis.minValue),
                        "default": float(axis.defaultValue),
                        "max": float(axis.maxValue),
                    })
            font.close()
            faces.append({
                "path": str(path),
                "index": index,
                "family": family,
                "face": face,
                "full_name": full_name,
                "postscript_name": postscript,
                "weight_class": weight,
                "italic": italic,
                "installed_on_windows": is_path_installed(path),
                "variable_axes": variable_axes,
                "file_name": path.name,
            })
        except Exception:
            continue
    return faces


def enumerate_font_files(font_dirs: Sequence[Path], max_files: int) -> Tuple[List[Path], List[str]]:
    files: List[Path] = []
    warnings: List[str] = []
    seen = set()
    for root in font_dirs:
        if not root.exists():
            warnings.append(f"font_dir_missing:{root}")
            continue
        iterator: Iterable[Path]
        if root.is_file():
            iterator = [root]
        else:
            iterator = root.rglob("*")
        for path in iterator:
            if not path.is_file() or path.suffix.lower() not in FONT_EXTENSIONS:
                continue
            try:
                key = str(path.resolve()).lower()
            except Exception:
                key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            files.append(path)
            if max_files > 0 and len(files) >= max_files:
                warnings.append(f"font_file_limit_reached:{max_files}")
                return files, warnings
    return files, warnings


def event_confidence(event: Dict[str, Any]) -> float:
    value = event.get("confidence")
    if isinstance(value, dict):
        value = value.get("score")
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def choose_event_text(event: Dict[str, Any]) -> str:
    observed = normalize_text(event.get("observed_text") or event.get("text"))
    cue = normalize_text((event.get("match") or {}).get("cue_text"))
    similarity = float((event.get("match") or {}).get("text_similarity") or 0.0)
    if cue and similarity >= 0.75 and normalized_token(cue) == normalized_token(observed):
        return cue
    return observed


def valid_bbox(value: Any, width: int, height: int) -> Optional[List[int]]:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(v))) for v in value]
    except Exception:
        return None
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return [x1, y1, x2, y2]


def select_samples(
    style_report: Dict[str, Any],
    samples_per_profile: int,
    min_confidence: float,
    min_chars: int,
    max_chars: int,
) -> Dict[str, List[Dict[str, Any]]]:
    info = style_report.get("video_info") or {}
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    events = style_report.get("caption_style_events") or style_report.get("style_events") or []
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for event in events:
        if not isinstance(event, dict):
            continue
        profile = str(event.get("style_profile_id") or "unassigned")
        text = choose_event_text(event)
        token = normalized_token(text)
        if len(token) < min_chars or len(token) > max_chars:
            continue
        if event_confidence(event) < min_confidence:
            continue
        placement = event.get("placement") or {}
        bbox = valid_bbox(placement.get("bbox"), width, height)
        if not bbox:
            continue

        observations = event.get("observations") or []
        observation = None
        if observations:
            target_mid = float(event.get("mid") or 0.0)
            candidates = [o for o in observations if isinstance(o, dict) and o.get("timestamp") is not None]
            if candidates:
                observation = min(candidates, key=lambda o: abs(float(o.get("timestamp") or 0.0) - target_mid))

        timestamp = float(
            (observation or {}).get("timestamp")
            or event.get("mid")
            or ((float(event.get("start") or 0.0) + float(event.get("end") or 0.0)) / 2.0)
        )
        if observation and valid_bbox(observation.get("bbox"), width, height):
            bbox = valid_bbox(observation.get("bbox"), width, height) or bbox

        typography = event.get("typography") or {}
        stroke = event.get("stroke") or {}
        grouped[profile].append({
            "event_id": event.get("event_id"),
            "cue_id": event.get("cue_id"),
            "profile_id": profile,
            "text": text,
            "timestamp": timestamp,
            "bbox": bbox,
            "font_height_px": int(typography.get("font_height_px") or max(10, bbox[3] - bbox[1])),
            "font_weight_hint": str(typography.get("font_weight") or "unknown"),
            "font_style_hint": str(typography.get("font_style") or "normal_or_unknown"),
            "fill_rgb": parse_hex_color((event.get("colors") or {}).get("fill")),
            "stroke_rgb": parse_hex_color((event.get("colors") or {}).get("stroke")),
            "shadow_rgb": parse_hex_color((event.get("colors") or {}).get("shadow")),
            "stroke_width_px": int(stroke.get("width_px_estimate") or 0),
            "confidence": event_confidence(event),
            "match_score": float((event.get("match") or {}).get("score") or 0.0),
            "text_similarity": float((event.get("match") or {}).get("text_similarity") or 0.0),
        })

    selected: Dict[str, List[Dict[str, Any]]] = {}
    for profile, rows in grouped.items():
        rows.sort(
            key=lambda row: (
                -float(row["text_similarity"]),
                -float(row["confidence"]),
                -len(normalized_token(row["text"])),
                float(row["timestamp"]),
            )
        )
        distinct: List[Dict[str, Any]] = []
        seen_texts = set()
        for row in rows:
            token = normalized_token(row["text"])
            if token in seen_texts:
                continue
            seen_texts.add(token)
            distinct.append(row)
            if len(distinct) >= samples_per_profile:
                break
        if distinct:
            selected[profile] = distinct
    return selected


def read_frame(cap: Any, frame_index: int) -> Optional[np.ndarray]:
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_index))
        ok, frame = cap.read()
        if ok and frame is not None:
            return frame
    except Exception:
        return None
    return None


def crop_with_padding(frame: np.ndarray, bbox: Sequence[int], padding_ratio: float) -> Tuple[np.ndarray, List[int]]:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    px = int(round(bw * padding_ratio))
    py = int(round(bh * padding_ratio))
    cx1 = max(0, x1 - px)
    cy1 = max(0, y1 - py)
    cx2 = min(width, x2 + px)
    cy2 = min(height, y2 + py)
    return frame[cy1:cy2, cx1:cx2].copy(), [cx1, cy1, cx2, cy2]


def color_distance_mask(crop_bgr: np.ndarray, colors_rgb: Sequence[Optional[Tuple[int, int, int]]], threshold: float) -> np.ndarray:
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
    masks = []
    for color in colors_rgb:
        if color is None:
            continue
        target = np.array(color, dtype=np.float32).reshape(1, 1, 3)
        distance = np.linalg.norm(rgb - target, axis=2)
        masks.append((distance <= threshold).astype(np.uint8) * 255)
    if not masks:
        return np.zeros(crop_bgr.shape[:2], dtype=np.uint8)
    combined = masks[0]
    for mask in masks[1:]:
        combined = cv2.bitwise_or(combined, mask)
    return combined


def largest_reasonable_components(mask: np.ndarray) -> np.ndarray:
    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if count <= 1:
        return mask
    total = mask.shape[0] * mask.shape[1]
    output = np.zeros_like(mask)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        if area < max(3, total * 0.00025):
            continue
        if w > mask.shape[1] * 0.98 and h > mask.shape[0] * 0.98:
            continue
        output[labels == label] = 255
    return output


def observed_text_mask(crop_bgr: np.ndarray, sample: Dict[str, Any], color_threshold: float) -> np.ndarray:
    # Fill colors can tolerate a wider RGB distance. Dark stroke/shadow colors
    # need a tighter threshold or ordinary dark background pixels contaminate
    # the glyph mask and make serif fonts look falsely similar.
    fill_mask = color_distance_mask(
        crop_bgr,
        [sample.get("fill_rgb")],
        color_threshold,
    )
    stroke_mask = color_distance_mask(
        crop_bgr,
        [sample.get("stroke_rgb")],
        min(38.0, color_threshold * 0.55),
    )
    shadow_mask = color_distance_mask(
        crop_bgr,
        [sample.get("shadow_rgb")],
        min(26.0, color_threshold * 0.38),
    )
    mask = cv2.bitwise_or(fill_mask, stroke_mask)
    mask = cv2.bitwise_or(mask, shadow_mask)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = largest_reasonable_components(mask)

    ratio = float(np.count_nonzero(mask)) / float(mask.size or 1)
    if ratio < 0.004 or ratio > 0.62:
        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blur, 50, 150)
        mask = cv2.dilate(edges, kernel, iterations=1)
        mask = largest_reasonable_components(mask)
    return mask


def mask_bbox(mask: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def target_weight(sample: Dict[str, Any]) -> int:
    hint = str(sample.get("font_weight_hint") or "").lower()
    if "black" in hint or "heavy" in hint:
        return 900
    if "extra" in hint and "bold" in hint:
        return 800
    if "bold" in hint:
        return 700
    if "semi" in hint or "demi" in hint:
        return 600
    if "medium" in hint:
        return 500
    if "light" in hint:
        return 300
    return 400


def _safe_font_bbox(
    font: ImageFont.FreeTypeFont,
    text: str,
    stroke_width: int,
    max_glyph_side_px: int,
    max_glyph_pixels: int,
) -> Optional[Tuple[int, int, int, int]]:
    """Return a sane glyph bbox or None for malformed/pathological fonts."""
    try:
        with warnings.catch_warnings():
            # Some malformed fonts request enormous internal glyph masks.
            # Convert Pillow's warning to an exception before allocation.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            left, top, right, bottom = font.getbbox(
                text,
                stroke_width=max(0, int(stroke_width)),
            )
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None
    except (MemoryError, OverflowError, OSError, ValueError):
        return None
    except Exception:
        return None

    try:
        values = [int(left), int(top), int(right), int(bottom)]
    except Exception:
        return None

    left, top, right, bottom = values
    glyph_w = right - left
    glyph_h = bottom - top
    if glyph_w <= 0 or glyph_h <= 0:
        return None

    if glyph_w > max_glyph_side_px or glyph_h > max_glyph_side_px:
        return None
    if glyph_w * glyph_h > max_glyph_pixels:
        return None

    # Extreme origin offsets are another sign of broken font metrics.
    max_offset = max_glyph_side_px * 4
    if any(abs(value) > max_offset for value in values):
        return None
    return left, top, right, bottom


def render_mask(
    face: Dict[str, Any],
    text: str,
    canvas_size: Tuple[int, int],
    target_height: int,
    observed_bbox: Optional[Tuple[int, int, int, int]],
    stroke_width: int,
    max_render_font_size_px: int = 512,
    max_glyph_side_px: int = 8192,
    max_glyph_pixels: int = 16_000_000,
) -> Optional[np.ndarray]:
    """
    Render one candidate safely.

    A single corrupt or pathological font must never terminate the whole scan.
    Pillow can raise DecompressionBombError while rasterising a glyph even when
    the output canvas itself is small. This function rejects that face instead.
    """
    width, height = canvas_size
    if width <= 2 or height <= 2:
        return None

    text = normalize_text(text)
    if not text:
        return None

    max_render_font_size_px = max(16, min(int(max_render_font_size_px), 2048))
    max_glyph_side_px = max(512, min(int(max_glyph_side_px), 32768))
    max_glyph_pixels = max(1_000_000, min(int(max_glyph_pixels), 64_000_000))

    # A detected text height should not require a font size dozens of times
    # larger than the crop itself. Clamp bad style metadata before loading fonts.
    target_height = max(4, int(target_height))
    target_height = min(
        target_height,
        max(16, height * 2),
        max_render_font_size_px,
    )
    stroke_width = max(0, min(int(stroke_width), max(1, target_height // 3)))

    def load(size: int) -> Optional[ImageFont.FreeTypeFont]:
        try:
            return ImageFont.truetype(
                face["path"],
                size=max(4, min(int(size), max_render_font_size_px)),
                index=int(face.get("index") or 0),
            )
        except (MemoryError, OverflowError, OSError, ValueError):
            return None
        except Exception:
            return None

    lo = 4
    hi = min(
        max_render_font_size_px,
        max(12, int(target_height * 3.0)),
    )
    best_font: Optional[ImageFont.FreeTypeFont] = None
    best_bbox: Optional[Tuple[int, int, int, int]] = None
    best_error = float("inf")

    for _ in range(12):
        if lo > hi:
            break
        mid = max(4, (lo + hi) // 2)
        font = load(mid)
        if font is None:
            return None

        bbox = _safe_font_bbox(
            font,
            text,
            stroke_width,
            max_glyph_side_px,
            max_glyph_pixels,
        )
        if bbox is None:
            # Large sizes may be unsafe while smaller sizes remain valid.
            hi = mid - 1
            continue

        left, top, right, bottom = bbox
        glyph_h = max(1, bottom - top)
        error = abs(glyph_h - target_height)
        if error < best_error:
            best_error = error
            best_font = font
            best_bbox = bbox

        if glyph_h < target_height:
            lo = mid + 1
        else:
            hi = mid - 1

    if best_font is None or best_bbox is None:
        return None

    left, top, right, bottom = best_bbox
    glyph_w = max(1, right - left)
    glyph_h = max(1, bottom - top)

    # Do not let a candidate render a glyph that is wildly larger than the
    # observed crop. Normal long words can exceed the crop slightly, so the
    # limit is intentionally generous.
    crop_relative_side_limit = max(width, height) * 8
    if glyph_w > crop_relative_side_limit or glyph_h > crop_relative_side_limit:
        return None

    if observed_bbox:
        ox1, oy1, ox2, oy2 = observed_bbox
        center_x = (ox1 + ox2) / 2.0
        center_y = (oy1 + oy2) / 2.0
    else:
        center_x = width / 2.0
        center_y = height / 2.0

    x = int(round(center_x - glyph_w / 2.0 - left))
    y = int(round(center_y - glyph_h / 2.0 - top))

    try:
        image = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(image)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            draw.text(
                (x, y),
                text,
                font=best_font,
                fill=255,
                stroke_width=stroke_width,
                stroke_fill=255,
            )
        rendered = np.asarray(image, dtype=np.uint8)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None
    except (MemoryError, OverflowError, OSError, ValueError):
        return None
    except Exception:
        return None

    if rendered.shape != (height, width):
        return None
    return rendered


def mask_score(observed: np.ndarray, rendered: np.ndarray) -> Dict[str, float]:
    if observed.shape != rendered.shape:
        return {"score": 0.0}
    obs = observed > 0
    ren = rendered > 0
    if not obs.any() or not ren.any():
        return {"score": 0.0}

    kernel = np.ones((3, 3), np.uint8)
    obs_d = cv2.dilate(obs.astype(np.uint8), kernel, iterations=1) > 0
    ren_d = cv2.dilate(ren.astype(np.uint8), kernel, iterations=1) > 0
    intersection = float(np.logical_and(obs_d, ren_d).sum())
    union = float(np.logical_or(obs_d, ren_d).sum())
    iou = intersection / union if union else 0.0

    obs_edges = cv2.Canny((obs.astype(np.uint8) * 255), 50, 150)
    ren_edges = cv2.Canny((ren.astype(np.uint8) * 255), 50, 150)
    inv_obs = np.where(obs_edges > 0, 0, 255).astype(np.uint8)
    inv_ren = np.where(ren_edges > 0, 0, 255).astype(np.uint8)
    dist_obs = cv2.distanceTransform(inv_obs, cv2.DIST_L2, 3)
    dist_ren = cv2.distanceTransform(inv_ren, cv2.DIST_L2, 3)
    ren_points = ren_edges > 0
    obs_points = obs_edges > 0
    diag = math.hypot(observed.shape[0], observed.shape[1]) or 1.0
    d1 = float(dist_obs[ren_points].mean()) / diag if ren_points.any() else 1.0
    d2 = float(dist_ren[obs_points].mean()) / diag if obs_points.any() else 1.0
    chamfer_similarity = max(0.0, 1.0 - min(1.0, (d1 + d2) * 5.0))

    ob = mask_bbox(observed)
    rb = mask_bbox(rendered)
    width_similarity = 0.0
    height_similarity = 0.0
    if ob and rb:
        ow, oh = max(1, ob[2] - ob[0]), max(1, ob[3] - ob[1])
        rw, rh = max(1, rb[2] - rb[0]), max(1, rb[3] - rb[1])
        width_similarity = math.exp(-abs(math.log(rw / ow)))
        height_similarity = math.exp(-abs(math.log(rh / oh)))

    obs_density = float(obs.sum()) / float(obs.size)
    ren_density = float(ren.sum()) / float(ren.size)
    density_similarity = math.exp(-abs(obs_density - ren_density) * 8.0)

    score = (
        0.42 * iou
        + 0.25 * chamfer_similarity
        + 0.18 * width_similarity
        + 0.10 * height_similarity
        + 0.05 * density_similarity
    )
    return {
        "score": round(float(score), 6),
        "iou": round(iou, 6),
        "chamfer_similarity": round(chamfer_similarity, 6),
        "width_similarity": round(width_similarity, 6),
        "height_similarity": round(height_similarity, 6),
        "density_similarity": round(density_similarity, 6),
    }


def face_hint_penalty(face: Dict[str, Any], samples: Sequence[Dict[str, Any]]) -> float:
    if not samples:
        return 0.0
    target = int(round(sum(target_weight(s) for s in samples) / len(samples)))
    weight = int(face.get("weight_class") or 400)
    penalty = min(0.18, abs(weight - target) / 3000.0)
    style_hint = " ".join(str(s.get("font_style_hint") or "") for s in samples).lower()
    wants_italic = "italic" in style_hint or "oblique" in style_hint
    if bool(face.get("italic")) != wants_italic:
        penalty += 0.06
    return penalty


def evaluate_face(
    face: Dict[str, Any],
    prepared_samples: Sequence[Dict[str, Any]],
    max_render_font_size_px: int = 512,
    max_glyph_side_px: int = 8192,
    max_glyph_pixels: int = 16_000_000,
) -> Dict[str, Any]:
    sample_results: List[Dict[str, Any]] = []
    render_rejected_count = 0

    try:
        for prepared in prepared_samples:
            observed = prepared["mask"]
            sample = prepared["sample"]
            bbox = mask_bbox(observed)
            try:
                rendered = render_mask(
                    face=face,
                    text=sample["text"],
                    canvas_size=(observed.shape[1], observed.shape[0]),
                    target_height=max(8, int(sample["font_height_px"])),
                    observed_bbox=bbox,
                    stroke_width=max(0, int(sample.get("stroke_width_px") or 0)),
                    max_render_font_size_px=max_render_font_size_px,
                    max_glyph_side_px=max_glyph_side_px,
                    max_glyph_pixels=max_glyph_pixels,
                )
            except Exception:
                # A font-specific failure is a rejected candidate, not a fatal run.
                rendered = None

            if rendered is None:
                render_rejected_count += 1
                continue

            result = mask_score(observed, rendered)
            result.update({
                "event_id": sample.get("event_id"),
                "cue_id": sample.get("cue_id"),
                "text": sample.get("text"),
                "timestamp": sample.get("timestamp"),
            })
            sample_results.append(result)
    except Exception as exc:
        return {
            **face,
            "visual_score": 0.0,
            "samples_scored": 0,
            "sample_scores": [],
            "render_rejected_count": len(prepared_samples),
            "evaluation_error": f"{type(exc).__name__}: {exc}",
        }

    if not sample_results:
        return {
            **face,
            "visual_score": 0.0,
            "samples_scored": 0,
            "sample_scores": [],
            "render_rejected_count": render_rejected_count,
            "evaluation_error": "all_sample_renders_rejected",
        }

    raw = sum(float(row["score"]) for row in sample_results) / len(sample_results)
    penalty = face_hint_penalty(face, [p["sample"] for p in prepared_samples])
    final = max(0.0, raw - penalty)
    return {
        **face,
        "visual_score": round(final, 6),
        "raw_shape_score": round(raw, 6),
        "hint_penalty": round(penalty, 6),
        "samples_scored": len(sample_results),
        "sample_scores": sample_results,
        "render_rejected_count": render_rejected_count,
        "evaluation_error": None,
    }


def candidate_key(row: Dict[str, Any]) -> Tuple[str, str]:
    return (
        normalized_token(row.get("family")),
        normalized_token(row.get("face") or "Regular"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank real font files against caption pixels and emit Resolve probe candidates."
    )
    parser.add_argument("--video", required=True)
    parser.add_argument("--caption-style", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--debug-dir", default="")
    parser.add_argument("--font-dir", action="append", default=[])
    parser.add_argument("--samples-per-profile", type=int, default=5)
    parser.add_argument("--min-event-confidence", type=float, default=0.48)
    parser.add_argument("--min-text-chars", type=int, default=3)
    parser.add_argument("--max-text-chars", type=int, default=14)
    parser.add_argument("--max-font-files", type=int, default=2500)
    parser.add_argument("--max-font-faces", type=int, default=3000)
    parser.add_argument("--coarse-samples", type=int, default=2)
    parser.add_argument("--coarse-top-k", type=int, default=45)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--resolve-probe-limit", type=int, default=24)
    parser.add_argument("--crop-padding-ratio", type=float, default=0.14)
    parser.add_argument("--color-distance", type=float, default=72.0)
    parser.add_argument(
        "--max-render-font-size-px",
        type=int,
        default=512,
        help="Hard safety cap for candidate font rasterisation. Default: 512.",
    )
    parser.add_argument(
        "--max-glyph-side-px",
        type=int,
        default=8192,
        help="Reject candidate glyph metrics exceeding this side length. Default: 8192.",
    )
    parser.add_argument(
        "--max-glyph-pixels",
        type=int,
        default=16000000,
        help="Reject candidate glyph masks exceeding this pixel count. Default: 16000000.",
    )
    args = parser.parse_args()

    started = time.time()
    video_path = Path(args.video)
    style_path = Path(args.caption_style)
    output_path = Path(args.output)
    debug_dir = Path(args.debug_dir) if args.debug_dir else output_path.parent / "debug_caption_font"

    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    if not style_path.is_file():
        raise FileNotFoundError(style_path)

    style_report = load_json(style_path)
    video_info = style_report.get("video_info") or {}
    fps = float(video_info.get("fps") or 0.0)
    width = int(video_info.get("width") or 0)
    height = int(video_info.get("height") or 0)
    if fps <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("caption-style video_info is incomplete")

    font_dirs = [Path(value) for value in args.font_dir if str(value).strip()]
    if not font_dirs:
        font_dirs = [
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
            Path(os.environ.get("USERPROFILE", "")) / "Downloads",
        ]

    font_files, warnings = enumerate_font_files(font_dirs, args.max_font_files)
    faces: List[Dict[str, Any]] = []
    for path in font_files:
        faces.extend(font_faces_from_path(path))
        if args.max_font_faces > 0 and len(faces) >= args.max_font_faces:
            faces = faces[:args.max_font_faces]
            warnings.append(f"font_face_limit_reached:{args.max_font_faces}")
            break
    if not faces:
        raise RuntimeError("No readable TTF/OTF/TTC font faces were found")

    samples_by_profile = select_samples(
        style_report,
        samples_per_profile=max(1, args.samples_per_profile),
        min_confidence=args.min_event_confidence,
        min_chars=max(1, args.min_text_chars),
        max_chars=max(args.min_text_chars, args.max_text_chars),
    )
    if not samples_by_profile:
        raise RuntimeError("No reliable caption samples were found in caption_style_events")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    debug_dir.mkdir(parents=True, exist_ok=True)
    prepared_by_profile: Dict[str, List[Dict[str, Any]]] = {}
    sample_failures: List[str] = []
    for profile, samples in samples_by_profile.items():
        prepared = []
        profile_dir = debug_dir / profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        for index, sample in enumerate(samples, start=1):
            source_frame = int(round(float(sample["timestamp"]) * fps))
            frame = read_frame(cap, source_frame)
            if frame is None:
                sample_failures.append(f"{profile}:{sample.get('event_id')}:frame_read_failed")
                continue
            crop, crop_bbox = crop_with_padding(frame, sample["bbox"], args.crop_padding_ratio)
            mask = observed_text_mask(crop, sample, args.color_distance)
            if np.count_nonzero(mask) < 8:
                sample_failures.append(f"{profile}:{sample.get('event_id')}:text_mask_empty")
                continue
            crop_path = profile_dir / f"sample_{index:02d}_{source_frame:06d}_crop.jpg"
            mask_path = profile_dir / f"sample_{index:02d}_{source_frame:06d}_mask.png"
            cv2.imwrite(str(crop_path), crop)
            cv2.imwrite(str(mask_path), mask)
            prepared.append({
                "sample": {
                    **sample,
                    "source_frame": source_frame,
                    "crop_bbox": crop_bbox,
                    "crop_path": str(crop_path),
                    "mask_path": str(mask_path),
                },
                "mask": mask,
            })
        if prepared:
            prepared_by_profile[profile] = prepared
    cap.release()

    if not prepared_by_profile:
        raise RuntimeError("All caption sample masks failed")

    profile_results: List[Dict[str, Any]] = []
    for profile, prepared in prepared_by_profile.items():
        coarse_prepared = prepared[:max(1, args.coarse_samples)]
        coarse = [
            evaluate_face(
                face,
                coarse_prepared,
                max_render_font_size_px=args.max_render_font_size_px,
                max_glyph_side_px=args.max_glyph_side_px,
                max_glyph_pixels=args.max_glyph_pixels,
            )
            for face in faces
        ]
        coarse.sort(key=lambda row: float(row.get("visual_score") or 0.0), reverse=True)
        finalists = coarse[:max(args.top_k, args.coarse_top_k)]
        full = []
        for row in finalists:
            base_face = {key: row[key] for key in (
                "path", "index", "family", "face", "full_name", "postscript_name",
                "weight_class", "italic", "installed_on_windows", "variable_axes", "file_name"
            )}
            full.append(
                evaluate_face(
                    base_face,
                    prepared,
                    max_render_font_size_px=args.max_render_font_size_px,
                    max_glyph_side_px=args.max_glyph_side_px,
                    max_glyph_pixels=args.max_glyph_pixels,
                )
            )
        full.sort(key=lambda row: float(row.get("visual_score") or 0.0), reverse=True)
        top = full[:max(1, args.top_k)]

        top_score = float(top[0].get("visual_score") or 0.0) if top else 0.0
        second_score = float(top[1].get("visual_score") or 0.0) if len(top) > 1 else 0.0
        margin = top_score - second_score
        if len(prepared) < 2:
            status = "insufficient_samples"
        elif top_score >= 0.56 and margin >= 0.035:
            status = "strong_visual_candidate"
        elif top_score >= 0.42:
            status = "ambiguous_visual_candidates"
        else:
            status = "weak_visual_match"

        installed_top = [row for row in top if row.get("installed_on_windows")]
        profile_results.append({
            "style_profile_id": profile,
            "sample_count": len(prepared),
            "samples": [row["sample"] for row in prepared],
            "selection_status": status,
            "top_score": round(top_score, 6),
            "top_two_margin": round(margin, 6),
            "visual_best_candidate": top[0] if top else None,
            "best_installed_candidate": installed_top[0] if installed_top else None,
            "requires_font_installation": bool(top and not top[0].get("installed_on_windows")),
            "candidates": top,
        })

    profiles_lookup = {
        str(row.get("style_id")): row
        for row in (style_report.get("caption_style_profiles") or style_report.get("style_profiles") or [])
        if isinstance(row, dict)
    }
    primary_style_id = str(
        (style_report.get("caption_style_resolved") or {}).get("primary_style_id")
        or ""
    )
    for result in profile_results:
        result["profile_role"] = (profiles_lookup.get(result["style_profile_id"]) or {}).get("role")
        result["is_primary_style"] = result["style_profile_id"] == primary_style_id

    consensus: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for result in profile_results:
        for rank, candidate in enumerate(result["candidates"][:5], start=1):
            key = candidate_key(candidate)
            if not all(key):
                continue
            row = consensus.setdefault(key, {
                "family": candidate["family"],
                "face": candidate["face"],
                "installed_on_windows": bool(candidate.get("installed_on_windows")),
                "paths": [],
                "profile_votes": 0,
                "weighted_score_sum": 0.0,
                "profiles": [],
            })
            row["profile_votes"] += 1
            row["weighted_score_sum"] += float(candidate.get("visual_score") or 0.0) / rank
            row["profiles"].append(result["style_profile_id"])
            if candidate["path"] not in row["paths"]:
                row["paths"].append(candidate["path"])
    consensus_rows = list(consensus.values())
    for row in consensus_rows:
        row["consensus_score"] = round(
            row["weighted_score_sum"] / max(1, row["profile_votes"]),
            6,
        )
        del row["weighted_score_sum"]
    consensus_rows.sort(
        key=lambda row: (
            -int(row["installed_on_windows"]),
            -int(row["profile_votes"]),
            -float(row["consensus_score"]),
        )
    )

    resolve_candidates: List[Dict[str, Any]] = []
    seen = set()
    for result in profile_results:
        for candidate in result["candidates"]:
            if not candidate.get("installed_on_windows"):
                continue
            key = candidate_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            resolve_candidates.append({
                "family": candidate["family"],
                "face": candidate["face"] or "Regular",
                "font_file": candidate["path"],
                "font_index": candidate["index"],
                "visual_score": candidate["visual_score"],
                "style_profile_ids": [result["style_profile_id"]],
                "source": "visual_font_detector",
            })
    resolve_candidates.sort(key=lambda row: float(row["visual_score"]), reverse=True)
    resolve_candidates = resolve_candidates[:max(1, args.resolve_probe_limit)]

    payload = {
        "success": True,
        "schema": "video_cloner_caption_font_candidates",
        "schema_version": "1.0",
        "analysis_version": VERSION,
        "inputs": {
            "video": str(video_path),
            "caption_style": str(style_path),
            "font_dirs": [str(path) for path in font_dirs],
        },
        "video_info": {
            "fps": fps,
            "width": width,
            "height": height,
        },
        "inventory": {
            "font_file_count": len(font_files),
            "font_face_count": len(faces),
            "installed_face_count": sum(1 for face in faces if face.get("installed_on_windows")),
            "downloaded_or_uninstalled_face_count": sum(1 for face in faces if not face.get("installed_on_windows")),
        },
        "render_safety": {
            "max_render_font_size_px": int(args.max_render_font_size_px),
            "max_glyph_side_px": int(args.max_glyph_side_px),
            "max_glyph_pixels": int(args.max_glyph_pixels),
            "coarse_faces_rejected_for_all_samples": sum(
                1
                for result in profile_results
                for candidate in result.get("candidates", [])
                if candidate.get("evaluation_error") == "all_sample_renders_rejected"
            ),
            "policy": "reject_pathological_font_face_and_continue",
        },
        "primary_style_id": primary_style_id or None,
        "profiles": profile_results,
        "global_consensus": consensus_rows[:20],
        "resolve_probe_candidates": resolve_candidates,
        "policy": {
            "visual_detection_is_not_resolve_verification": True,
            "downloaded_uninstalled_fonts_are_candidate_only": True,
            "resolve_probe_required_before_automatic_textplus_write": True,
            "font_weight_hint_is_not_treated_as_a_real_face_name": True,
        },
        "debug_dir": str(debug_dir),
        "sample_failures": sample_failures,
        "warnings": warnings,
        "runtime_seconds": round(time.time() - started, 3),
    }
    write_json(output_path, payload)
    print(json.dumps({
        "success": True,
        "output": str(output_path),
        "profiles": len(profile_results),
        "font_faces": len(faces),
        "resolve_probe_candidates": len(resolve_candidates),
        "primary_style_id": primary_style_id or None,
        "runtime_seconds": payload["runtime_seconds"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
