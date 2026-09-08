#!/usr/bin/env python3
"""Build source-grounded caption visual-fidelity authority V2.

This is an offline analysis boundary. It does not touch Resolve.

Generic corrections:
- strict semantic re-anchoring for ambiguous short OCR tokens;
- exact adjacent compound-OCR decomposition for merged visual words;
- semantic-anchor + source-template continuity for visual timing and geometry;
- static-by-default motion with strong coherent-motion/exit gates;
- dual-axis Resolve font calibration (source width + height) with weak-family fallback;
- source-case preservation from exact OCR tokens;
- source-glyph interior fill sampling;
- same-line/group topology metadata from source geometry;
- explicit occlusion/foreground asset carry-forward.

Transcript timing is never authority. Detector score never becomes opacity. No cue,
word, video-ID, or screenshot-specific production branch exists.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2"
UNIVERSAL = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/universal_visual_repair_authority_v1.json")
SEMANTIC = Path("artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_v1.json")
POST_METRICS = Path("artifacts/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/post_visual_metrics_polish_v1.json")
V4 = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json")
WORD_TRACKS = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json")
OCCLUSION = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_occlusion.json")
FOREGROUND = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_foreground_assets.json")
OCR_MODULE = Path("scripts/davinci/redetect_caption_word_instances_step_3B_6.py")
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json")

EXPECTED_TOTAL = 117
EXPECTED_PROTECTED = 17
EXPECTED_EXISTING_CONFIRMED = 47
EXPECTED_NEW_CONFIRMED = 27
EXPECTED_REPAIR = 74
EXPECTED_UNRESOLVED = 23
EXPECTED_REMOVED = 3
EXPECTED_PHYSICAL = 114
REF_WIDTH = 540
REF_HEIGHT = 960
TIMELINE_FPS = 24.0
MIN_FAMILY_CALIBRATION_SAMPLES = 3


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
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def token_units(value: Any) -> float:
    text = str(value or "")
    units = 0.0
    for ch in text:
        if ch.isspace():
            units += 0.32
        elif ch in "ilI1|!.,:'`;":
            units += 0.34
        elif ch in "mwMW@%&":
            units += 0.88
        elif ch.isdigit():
            units += 0.58
        else:
            units += 0.60
    return max(0.5, units)


def median(values: Sequence[float], default: float = 0.0) -> float:
    return float(statistics.median(values)) if values else float(default)


def mad(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    center = median(values)
    return median([abs(float(v) - center) for v in values])


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float]:
    require(len(xs) == len(ys) and bool(xs), "linear_fit")
    if len(xs) == 1:
        return 0.0, float(ys[0]), 1.0
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom <= 1e-12:
        return 0.0, my, 1.0
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    intercept = my - slope * mx
    fitted = [slope * x + intercept for x in xs]
    ss_res = sum((y - f) ** 2 for y, f in zip(ys, fitted))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 1.0
    return float(slope), float(intercept), float(r2)


def bbox_center(box: Sequence[float]) -> tuple[float, float]:
    return (float(box[0]) + float(box[2])) * 0.5, (float(box[1]) + float(box[3])) * 0.5


def bbox_size(box: Sequence[float]) -> tuple[float, float]:
    return max(1.0, float(box[2]) - float(box[0])), max(1.0, float(box[3]) - float(box[1]))


def normalized_bbox(box: Sequence[float], width: float, height: float) -> list[float]:
    return [
        round(float(box[0]) / width, 8),
        round(float(box[1]) / height, 8),
        round(float(box[2]) / width, 8),
        round(float(box[3]) / height, 8),
    ]


def font_key(row: Mapping[str, Any]) -> tuple[str, str]:
    font = row.get("font") if isinstance(row.get("font"), Mapping) else row.get("style")
    font = font if isinstance(font, Mapping) else {}
    return str(font.get("font_family") or ""), str(font.get("font_style") or "")


def flatten_v4(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group in document.get("groups") or []:
        if not isinstance(group, Mapping):
            continue
        for token in group.get("tokens") or []:
            if isinstance(token, Mapping):
                row = dict(token)
                row["group_id"] = str(group.get("group_id") or "")
                result.append(row)
    return result


def build_render_calibration(v4_tokens: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for token in v4_tokens:
        role = (str(token.get("role") or "") + " " + str(token.get("visual_kind") or "")).lower()
        if "decorative" in role or "script" in role:
            continue
        anchor = token.get("source_pixel_anchor") if isinstance(token.get("source_pixel_anchor"), Mapping) else {}
        generated_h = float(anchor.get("generated_height_px") or 0.0)
        generated_w = float(anchor.get("generated_width_px") or 0.0)
        base = float(token.get("application_base_size_candidate") or 0.0)
        text = str(token.get("display_text") or "")
        if generated_h <= 0 or generated_w <= 0 or base <= 0 or not text:
            continue
        family, style = font_key(token)
        samples.append({
            "instance_id": str(token.get("visual_token_id") or ""),
            "font_family": family,
            "font_style": style,
            "height_px_per_size": generated_h / base,
            "width_px_per_size_unit": generated_w / (base * token_units(text)),
        })
    require(len(samples) >= 8, "render_calibration_samples")
    global_h = median([r["height_px_per_size"] for r in samples])
    global_w = median([r["width_px_per_size_unit"] for r in samples])
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in samples:
        grouped[(row["font_family"], row["font_style"])].append(row)
    families = []
    for key, rows in sorted(grouped.items()):
        family_direct = len(rows) >= MIN_FAMILY_CALIBRATION_SAMPLES
        families.append({
            "font_family": key[0],
            "font_style": key[1],
            "sample_count": len(rows),
            "model_source": "family_robust_median" if family_direct else "global_fallback_weak_family",
            "height_px_per_size": round(median([r["height_px_per_size"] for r in rows]) if family_direct else global_h, 8),
            "width_px_per_size_unit": round(median([r["width_px_per_size_unit"] for r in rows]) if family_direct else global_w, 8),
            "evidence_ids": [r["instance_id"] for r in rows],
        })
    return {
        "global": {
            "sample_count": len(samples),
            "height_px_per_size": round(global_h, 8),
            "width_px_per_size_unit": round(global_w, 8),
        },
        "families": families,
    }


def calibration_for(row: Mapping[str, Any], calibration: Mapping[str, Any]) -> Mapping[str, Any]:
    key = font_key(row)
    for family in calibration.get("families") or []:
        if (str(family.get("font_family") or ""), str(family.get("font_style") or "")) == key:
            return family
    return {**dict(calibration["global"]), "model_source": "global_fallback_unmeasured_family"}


def source_size_to_application(text: str, width_px: float, height_px: float, model: Mapping[str, Any]) -> dict[str, Any]:
    hpps = float(model.get("height_px_per_size") or 0.0)
    wpps = float(model.get("width_px_per_size_unit") or 0.0)
    require(hpps > 0 and wpps > 0, "font_model")
    height_size = float(height_px) / hpps
    width_size = float(width_px) / (wpps * token_units(text))
    # Width acts as a hard anti-overflow constraint. Height still matters, but
    # a single weak family sample can no longer inflate a word beyond its source box.
    width_cap = width_size * 1.05
    target = min(height_size, width_cap)
    if min(height_size, width_size) / max(height_size, width_size) >= 0.72:
        target = math.sqrt(height_size * width_size)
    target = clamp(target, 0.018, 0.32)
    return {
        "target_size": round(target, 12),
        "height_size": round(height_size, 12),
        "width_size": round(width_size, 12),
        "width_capped": bool(width_cap < height_size),
        "model_source": str(model.get("model_source") or "global"),
    }


def exact_source_token(source_text: Any, canonical: str) -> str | None:
    target = compact_text(canonical)
    if not target:
        return None
    for token in re.findall(r"[A-Za-z0-9']+", str(source_text or "")):
        if compact_text(token) == target:
            return token
    return None


def source_case_consensus(canonical: str, observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    votes: list[tuple[str, float]] = []
    for row in observations:
        token = exact_source_token(row.get("ocr_source_text"), canonical)
        if token is None:
            continue
        weight = max(0.01, float(row.get("ocr_confidence") or 0.0))
        votes.append((token, weight))
    if not votes:
        return {"text": canonical, "apply": False, "support": 0, "basis": "no_exact_source_case"}
    totals: dict[str, float] = defaultdict(float)
    counts: Counter[str] = Counter()
    for token, weight in votes:
        totals[token] += weight
        counts[token] += 1
    best = sorted(totals, key=lambda text: (totals[text], counts[text], text), reverse=True)[0]
    same_semantics = compact_text(best) == compact_text(canonical)
    return {
        "text": best if same_semantics else canonical,
        "apply": bool(same_semantics and best != canonical),
        "support": int(counts[best]),
        "basis": "exact_source_ocr_case_consensus",
    }


def track_observations(track: Mapping[str, Any], canonical: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in track.get("frame_observations") or []:
        if not isinstance(row, Mapping) or str(row.get("method") or "") != "ocr":
            continue
        bbox = row.get("normalized_bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        result.append({
            "timeline_frame": int(row.get("timeline_frame")),
            "source_frame": int(row.get("source_frame") or -1),
            "normalized_bbox": [float(v) for v in bbox],
            "ocr_text": str(row.get("ocr_text") or ""),
            "ocr_source_text": str(row.get("ocr_source_text") or ""),
            "ocr_confidence": float(row.get("ocr_confidence") or 0.0),
            "text_similarity": float(row.get("text_similarity") or 0.0),
            "semantic_score": float(row.get("assignment_score") or row.get("score") or 0.0),
            "candidate_kind": str(row.get("candidate_kind") or "ocr"),
            "exact_token": compact_text(row.get("ocr_text")) == compact_text(canonical),
        })
    return result


def ocr_confusable_skeleton(value: Any) -> str:
    """Return a conservative visual-confusion skeleton for OCR identity checks.

    This is intentionally narrower than general fuzzy matching. It only folds
    glyphs that are routinely indistinguishable to OCR at reel resolution.
    Production semantic identity still requires equal compact length, a single
    character difference, and high OCR confidence.
    """
    text = compact_text(value)
    table = str.maketrans({
        "i": "l",
        "1": "l",
        "o": "0",
    })
    return text.translate(table)


def single_substitution_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right))


def strict_ocr_semantic_match(canonical: str, ocr_text: Any, confidence: float) -> bool:
    """Accept exact OCR or one high-confidence OCR-confusable substitution.

    Short tokens remain exact-only because collapsing visually similar glyphs is
    too ambiguous for 1-3 character captions such as ``at``. This gate is only
    semantic; geometry/proximity never turns a non-match into a caption.
    """
    target = compact_text(canonical)
    candidate = compact_text(ocr_text)
    if not target or not candidate:
        return False
    if candidate == target:
        return True
    if len(target) <= 3 or len(candidate) != len(target):
        return False
    if float(confidence or 0.0) < 0.85:
        return False
    if single_substitution_distance(target, candidate) != 1:
        return False
    return ocr_confusable_skeleton(target) == ocr_confusable_skeleton(candidate)


def source_compact_preserve_case(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or ""))


def adjacent_compound_sequences(
    target_id: str,
    ordered_ids: Sequence[str],
    canonical_by_id: Mapping[str, str],
    max_members: int = 3,
) -> list[dict[str, Any]]:
    """Return contiguous canonical-token sequences containing ``target_id``.

    OCR engines commonly merge visually adjacent words into one line token. We
    only consider exact compact concatenations of immediate structural neighbors;
    no timing, geometry, or fuzzy text score may create semantic identity here.
    """
    if target_id not in ordered_ids:
        return []
    position = ordered_ids.index(target_id)
    result: list[dict[str, Any]] = []
    for count in range(2, max(2, int(max_members)) + 1):
        first = max(0, position - count + 1)
        last = min(position, len(ordered_ids) - count)
        for start in range(first, last + 1):
            members = list(ordered_ids[start : start + count])
            texts = [str(canonical_by_id.get(member) or "") for member in members]
            compact = [compact_text(text) for text in texts]
            if any(not text for text in compact):
                continue
            result.append({
                "member_ids": members,
                "member_texts": texts,
                "target_index": members.index(target_id),
                "compact_concat": "".join(compact),
            })
    return result


def split_compound_bbox(
    bbox: Sequence[float],
    member_texts: Sequence[str],
    target_index: int,
    inter_token_gap_units: float = 0.32,
) -> list[float]:
    """Split a horizontal OCR line bbox into a source-grounded member segment.

    The OCR bbox remains the pixel authority. Canonical token widths are only a
    proportional partitioning model inside that already-semantic line; they do
    not establish timing or presence.
    """
    require(len(bbox) == 4, "compound_bbox")
    require(0 <= int(target_index) < len(member_texts), "compound_target_index")
    weights = [token_units(text) for text in member_texts]
    gap = max(0.0, float(inter_token_gap_units))
    total = sum(weights) + gap * max(0, len(weights) - 1)
    require(total > 0.0, "compound_units")
    index = int(target_index)
    start_units = sum(weights[:index]) + gap * index
    end_units = start_units + weights[index]
    x0, y0, x1, y1 = [float(value) for value in bbox]
    width = x1 - x0
    require(width > 0 and y1 > y0, "compound_bbox_geometry")
    return [
        round(x0 + width * (start_units / total), 8),
        round(y0, 8),
        round(x0 + width * (end_units / total), 8),
        round(y1, 8),
    ]


def compound_ocr_decompose_observations(
    target_id: str,
    observations: Sequence[Mapping[str, Any]],
    ordered_ids: Sequence[str],
    canonical_by_id: Mapping[str, str],
    min_confidence: float = 0.85,
    min_distinct_frames: int = 2,
    max_members: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recover a token from an exact merged OCR token of adjacent captions.

    Example class: OCR returns ``Iwas`` while structural captions are ``I`` and
    ``was``. The merged OCR token is accepted only when it exactly equals a
    contiguous canonical concatenation on multiple source frames. The target bbox
    is then split proportionally inside the observed OCR bbox, avoiding use of the
    full merged-line geometry for one member.
    """
    canonical = str(canonical_by_id.get(target_id) or "")
    sequences = adjacent_compound_sequences(target_id, ordered_ids, canonical_by_id, max_members=max_members)
    if not canonical or not sequences:
        return [dict(row) for row in observations], {"applied": False, "reason": "no_adjacent_sequence"}

    matches: list[tuple[tuple[int, float, int], dict[str, Any], list[dict[str, Any]]]] = []
    for sequence in sequences:
        rows = [
            dict(row)
            for row in observations
            if float(row.get("ocr_confidence") or 0.0) >= float(min_confidence)
            and compact_text(row.get("ocr_source_text") or row.get("ocr_text")) == sequence["compact_concat"]
        ]
        frames = {int(row.get("timeline_frame")) for row in rows if row.get("timeline_frame") is not None}
        if len(frames) < int(min_distinct_frames):
            continue
        median_conf = median([float(row.get("ocr_confidence") or 0.0) for row in rows])
        # Prefer more source frames, then higher confidence, then fewer members.
        score = (len(frames), median_conf, -len(sequence["member_ids"]))
        matches.append((score, sequence, rows))

    if not matches:
        return [dict(row) for row in observations], {"applied": False, "reason": "no_exact_compound_consensus"}

    matches.sort(key=lambda item: item[0], reverse=True)
    _, sequence, rows = matches[0]
    target_index = int(sequence["target_index"])
    member_compacts = [compact_text(text) for text in sequence["member_texts"]]
    source_start = sum(len(text) for text in member_compacts[:target_index])
    source_end = source_start + len(member_compacts[target_index])
    decomposed: list[dict[str, Any]] = []
    for source in rows:
        original_source = str(source.get("ocr_source_text") or source.get("ocr_text") or "")
        source_compact = source_compact_preserve_case(original_source)
        source_segment = source_compact[source_start:source_end] if len(source_compact) >= source_end else canonical
        row = dict(source)
        row.update({
            "normalized_bbox": split_compound_bbox(row["normalized_bbox"], sequence["member_texts"], target_index),
            "ocr_text": canonical,
            "ocr_source_text": source_segment or canonical,
            "text_similarity": 1.0,
            "semantic_score": max(0.99, float(row.get("semantic_score") or 0.0)),
            "candidate_kind": "ocr_compound_segment",
            "exact_token": True,
            "method": "strict_adjacent_compound_ocr_decomposition",
            "compound_decomposition": {
                "source_ocr_text": original_source,
                "member_ids": list(sequence["member_ids"]),
                "member_texts": list(sequence["member_texts"]),
                "target_index": target_index,
                "identity_rule": "exact_compact_adjacent_concatenation",
            },
        })
        decomposed.append(row)

    return [dict(row) for row in observations] + decomposed, {
        "applied": True,
        "member_ids": list(sequence["member_ids"]),
        "member_texts": list(sequence["member_texts"]),
        "target_index": target_index,
        "source_frames": sorted({int(row["timeline_frame"]) for row in rows}),
        "source_ocr_texts": sorted({str(row.get("ocr_source_text") or row.get("ocr_text") or "") for row in rows}),
        "identity_rule": "exact_compact_adjacent_concatenation",
    }


def strict_anchor_ok(canonical: str, observations: Sequence[Mapping[str, Any]]) -> bool:
    target = compact_text(canonical)
    if not target:
        return False
    exact = [row for row in observations if compact_text(row.get("ocr_text")) == target]
    if len(target) <= 3:
        return bool(exact)
    if exact:
        return True
    if any(
        strict_ocr_semantic_match(
            canonical,
            row.get("ocr_text"),
            float(row.get("ocr_confidence") or 0.0),
        )
        for row in observations
    ):
        return True
    return any(float(row.get("text_similarity") or 0.0) >= 0.82 and float(row.get("ocr_confidence") or 0.0) >= 0.70 for row in observations)


def best_anchor(canonical: str, observations: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not observations:
        return None
    target = compact_text(canonical)
    scored = []
    for row in observations:
        exact = compact_text(row.get("ocr_text")) == target
        score = (2.0 if exact else 0.0) + float(row.get("semantic_score") or 0.0) + 0.25 * float(row.get("ocr_confidence") or 0.0)
        scored.append((score, dict(row)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def semantic_observation_run(
    canonical: str,
    observations: Sequence[Mapping[str, Any]],
    anchor_frame: int,
    max_frame_gap: int = 10,
) -> list[dict[str, Any]]:
    """Return the source-semantic observation component containing the anchor.

    OCR is sampled rather than guaranteed every timeline frame. We therefore join
    nearby source-pixel observations, but never bridge a large gap just because
    transcript tokens are adjacent. Short tokens remain exact-only.
    """
    target = compact_text(canonical)
    accepted: list[dict[str, Any]] = []
    for source in observations:
        row = dict(source)
        exact = compact_text(row.get("ocr_text")) == target
        strict_equivalent = strict_ocr_semantic_match(
            canonical,
            row.get("ocr_text"),
            float(row.get("ocr_confidence") or 0.0),
        )
        if len(target) <= 3:
            keep = exact
        else:
            keep = strict_equivalent or (
                float(row.get("text_similarity") or 0.0) >= 0.82
                and float(row.get("ocr_confidence") or 0.0) >= 0.70
            )
        if keep:
            accepted.append(row)
    if not accepted:
        return []

    # Keep only the best semantic candidate per sampled timeline frame.
    by_frame: dict[int, dict[str, Any]] = {}
    for row in accepted:
        frame = int(row["timeline_frame"])
        exact = compact_text(row.get("ocr_text")) == target
        score = (
            (2.0 if exact else 0.0)
            + float(row.get("semantic_score") or 0.0)
            + 0.25 * float(row.get("ocr_confidence") or 0.0)
        )
        current = by_frame.get(frame)
        if current is None or score > float(current["_selection_score"]):
            by_frame[frame] = {**row, "_selection_score": score}

    ordered = [by_frame[frame] for frame in sorted(by_frame)]
    components: list[list[dict[str, Any]]] = []
    for row in ordered:
        if not components or int(row["timeline_frame"]) - int(components[-1][-1]["timeline_frame"]) > max_frame_gap:
            components.append([row])
        else:
            components[-1].append(row)

    component = min(
        components,
        key=lambda rows: min(abs(int(row["timeline_frame"]) - int(anchor_frame)) for row in rows),
    )
    return [{k: v for k, v in row.items() if k != "_selection_score"} for row in component]


def dense_track_from_observations(observations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Interpolate a dense source geometry path between sampled OCR observations."""
    require(bool(observations), "semantic_observation_track_empty")
    rows = sorted((dict(row) for row in observations), key=lambda row: int(row["timeline_frame"]))
    require(all(isinstance(row.get("normalized_bbox"), list) and len(row["normalized_bbox"]) == 4 for row in rows), "semantic_observation_bbox")
    if len(rows) == 1:
        row = rows[0]
        box = [
            int(round(float(row["normalized_bbox"][0]) * REF_WIDTH)),
            int(round(float(row["normalized_bbox"][1]) * REF_HEIGHT)),
            int(round(float(row["normalized_bbox"][2]) * REF_WIDTH)),
            int(round(float(row["normalized_bbox"][3]) * REF_HEIGHT)),
        ]
        return [{"timeline_frame": int(row["timeline_frame"]), "score": 1.0, "scale": 1.0, "bbox_ref": box, "bbox_normalized": normalized_bbox(box, REF_WIDTH, REF_HEIGHT)}]

    by_frame = {int(row["timeline_frame"]): row for row in rows}
    frames = sorted(by_frame)
    dense: list[dict[str, Any]] = []
    for frame in range(frames[0], frames[-1] + 1):
        if frame in by_frame:
            box_norm = [float(v) for v in by_frame[frame]["normalized_bbox"]]
        else:
            left = max(value for value in frames if value < frame)
            right = min(value for value in frames if value > frame)
            alpha = (frame - left) / max(1, right - left)
            lbox = [float(v) for v in by_frame[left]["normalized_bbox"]]
            rbox = [float(v) for v in by_frame[right]["normalized_bbox"]]
            box_norm = [l + (r - l) * alpha for l, r in zip(lbox, rbox)]
        box = [
            int(round(box_norm[0] * REF_WIDTH)),
            int(round(box_norm[1] * REF_HEIGHT)),
            int(round(box_norm[2] * REF_WIDTH)),
            int(round(box_norm[3] * REF_HEIGHT)),
        ]
        dense.append({
            "timeline_frame": frame,
            "score": 1.0,
            "scale": 1.0,
            "bbox_ref": box,
            "bbox_normalized": normalized_bbox(box, REF_WIDTH, REF_HEIGHT),
        })
    return dense


def load_ocr_module(repo_root: Path):
    path = repo_root / OCR_MODULE
    require(path.is_file(), f"ocr_module:{path}")
    spec = importlib.util.spec_from_file_location("vc_visual_fidelity_v2_ocr", path)
    require(spec is not None and spec.loader is not None, "ocr_spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def strict_reanchor_search_window(universal_row: Mapping[str, Any]) -> list[int]:
    window = universal_row.get("visual_window") or universal_row.get("seed_window_only")
    require(isinstance(window, list) and len(window) == 2, f"reanchor_window:{universal_row.get('instance_id')}")
    start, end = int(window[0]), int(window[1])
    return [max(0, start - 2), end + 2]


def reanchor_short_tokens(
    repo_root: Path,
    rows: Sequence[Mapping[str, Any]],
    source_path: Path,
    ocr_lang: str,
    ocr_device: str,
    ocr_gpu_id: int,
    min_ocr_confidence: float,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Strictly re-anchor short tokens whose old OCR identity was only fuzzy.

    Exact split-token semantics are mandatory. Spatial proximity is only a tie
    breaker, so a nearby logo glyph cannot impersonate a short caption token.
    """
    if not rows:
        return {}, {"required": 0, "reanchored": 0, "failures": []}
    ocr = load_ocr_module(repo_root)
    engine, info = ocr.create_ocr(ocr_lang, ocr_device, ocr_gpu_id)
    cap = cv2.VideoCapture(str(source_path))
    require(cap.isOpened(), f"video_open:{source_path}")
    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    source_count = int(round(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
    width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0))
    height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
    require(source_fps > 0 and source_count > 0 and width > 0 and height > 0, "video_meta")
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failures: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="vc_vf2_reanchor_") as temp_name:
            temp_dir = Path(temp_name)
            for index, row in enumerate(rows, start=1):
                instance_id = str(row.get("instance_id") or "")
                canonical = str(row.get("canonical_text") or "")
                window = strict_reanchor_search_window(row)
                print(f"[visual-fidelity-v2] strict reanchor {index}/{len(rows)} {instance_id} frames={window}", flush=True)
                for timeline_frame in range(window[0], window[1]):
                    source_frame = max(0, min(source_count - 1, int(round(timeline_frame * source_fps / TIMELINE_FPS))))
                    cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
                    ok, frame = cap.read()
                    require(ok and frame is not None, f"reanchor_frame:{instance_id}:{timeline_frame}")
                    ocr_frame, scale_x, scale_y = ocr.resize_for_ocr(frame, 1440)
                    parsed = ocr.parse_paddle_result(ocr.run_ocr(engine, ocr_frame, temp_dir, f"reanchor_{instance_id}_{timeline_frame}"))
                    candidates = ocr.build_candidates(parsed, scale_x, scale_y, width, height, min_ocr_confidence)
                    semantic = [
                        cand
                        for cand in candidates
                        if strict_ocr_semantic_match(
                            canonical,
                            getattr(cand, "text", ""),
                            float(getattr(cand, "confidence", 0.0)),
                        )
                    ]
                    if not semantic:
                        continue
                    semantic.sort(
                        key=lambda cand: (
                            compact_text(getattr(cand, "text", "")) == compact_text(canonical),
                            float(getattr(cand, "confidence", 0.0)),
                            -float(bbox_size(getattr(cand, "bbox", [0, 0, 1, 1]))[1]),
                        ),
                        reverse=True,
                    )
                    cand = semantic[0]
                    exact_token = compact_text(getattr(cand, "text", "")) == compact_text(canonical)
                    result[instance_id].append({
                        "timeline_frame": timeline_frame,
                        "source_frame": source_frame,
                        "normalized_bbox": normalized_bbox(cand.bbox, width, height),
                        "ocr_text": str(getattr(cand, "text", "")),
                        "ocr_source_text": str(getattr(cand, "source_text", "")),
                        "ocr_confidence": round(float(getattr(cand, "confidence", 0.0)), 6),
                        "text_similarity": 1.0 if exact_token else 0.99,
                        "semantic_score": 1.0 if exact_token else 0.99,
                        "candidate_kind": str(getattr(cand, "source_kind", "")),
                        "exact_token": exact_token,
                        "strict_ocr_equivalent": not exact_token,
                        "method": "strict_exact_short_token_reanchor" if exact_token else "strict_ocr_confusable_reanchor",
                    })
                if not result[instance_id]:
                    failures.append(instance_id)
    finally:
        cap.release()
    return dict(result), {
        "required": len(rows),
        "reanchored": len(rows) - len(failures),
        "failures": failures,
        "ocr_engine": info.get("engine"),
        "ocr_device": info.get("selected_device"),
    }


class VideoSource:
    def __init__(self, path: Path):
        self.cap = cv2.VideoCapture(str(path))
        require(self.cap.isOpened(), f"video_open:{path}")
        self.source_fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.source_count = int(round(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        self.source_width = int(round(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0))
        self.source_height = int(round(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
        require(self.source_fps > 0 and self.source_count > 0 and self.source_width > 0 and self.source_height > 0, "video_meta")

    def read_ref(self, timeline_frame: int) -> np.ndarray:
        source_frame = max(0, min(self.source_count - 1, int(round(timeline_frame * self.source_fps / TIMELINE_FPS))))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
        ok, frame = self.cap.read()
        require(ok and frame is not None, f"frame_read:{timeline_frame}:{source_frame}")
        return cv2.resize(frame, (REF_WIDTH, REF_HEIGHT), interpolation=cv2.INTER_AREA)

    def close(self) -> None:
        self.cap.release()


def highpass(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (0, 0), 2.0)
    value = cv2.absdiff(gray, blur)
    return cv2.normalize(value, None, 0, 255, cv2.NORM_MINMAX)


def template_track(
    video: VideoSource,
    anchor_frame: int,
    anchor_bbox_norm: Sequence[float],
    search_window: Sequence[int],
) -> dict[str, Any]:
    anchor_image = video.read_ref(anchor_frame)
    box = [
        int(round(float(anchor_bbox_norm[0]) * REF_WIDTH)),
        int(round(float(anchor_bbox_norm[1]) * REF_HEIGHT)),
        int(round(float(anchor_bbox_norm[2]) * REF_WIDTH)),
        int(round(float(anchor_bbox_norm[3]) * REF_HEIGHT)),
    ]
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(REF_WIDTH, x1), min(REF_HEIGHT, y1)
    require(x1 - x0 >= 4 and y1 - y0 >= 4, "template_bbox")
    # Build the anchor template in the same preprocessing context used for
    # every search frame. High-pass filtering a tight crop creates artificial
    # boundary responses that are absent when the full search frame is filtered,
    # so the anchor can fail to match itself even though its source bbox is valid.
    # Filtering the full anchor frame first makes the anchor score a true
    # self-consistency check instead of a crop-boundary artifact.
    anchor_filtered = highpass(cv2.cvtColor(anchor_image, cv2.COLOR_BGR2GRAY))
    template = anchor_filtered[y0:y1, x0:x1].copy()
    base_w, base_h = x1 - x0, y1 - y0
    cx0, cy0 = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    scales = [0.88, 0.94, 1.0, 1.06, 1.12]
    rows: list[dict[str, Any]] = []
    for timeline_frame in range(int(search_window[0]), int(search_window[1])):
        image = video.read_ref(timeline_frame)
        gray = highpass(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        half_w = max(24, int(round(base_w * 0.42)))
        half_h = max(28, int(round(base_h * 2.30)))
        rx0 = max(0, int(round(cx0 - base_w * 0.5)) - half_w)
        rx1 = min(REF_WIDTH, int(round(cx0 + base_w * 0.5)) + half_w)
        ry0 = max(0, int(round(cy0 - base_h * 0.5)) - half_h)
        ry1 = min(REF_HEIGHT, int(round(cy0 + base_h * 0.5)) + half_h)
        roi = gray[ry0:ry1, rx0:rx1]
        best: tuple[float, float, list[int]] | None = None
        for scale in scales:
            tw, th = max(4, int(round(base_w * scale))), max(4, int(round(base_h * scale)))
            if tw >= roi.shape[1] or th >= roi.shape[0]:
                continue
            resized = cv2.resize(template, (tw, th), interpolation=cv2.INTER_LINEAR)
            response = cv2.matchTemplate(roi, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(response)
            adjusted = float(score) - 0.025 * abs(math.log(scale))
            bbox = [rx0 + location[0], ry0 + location[1], rx0 + location[0] + tw, ry0 + location[1] + th]
            candidate = (adjusted, float(scale), bbox)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            continue
        score, scale, bbox = best
        rows.append({
            "timeline_frame": timeline_frame,
            "score": round(clamp(score, -1.0, 1.0), 6),
            "scale": round(scale, 6),
            "bbox_ref": bbox,
            "bbox_normalized": normalized_bbox(bbox, REF_WIDTH, REF_HEIGHT),
        })
    require(any(r["timeline_frame"] == anchor_frame for r in rows), "template_anchor_missing")
    anchor_score = max(float(r["score"]) for r in rows if r["timeline_frame"] == anchor_frame)
    require(anchor_score >= 0.80, f"template_anchor_score:{anchor_score}")
    return {"rows": rows, "anchor_score": round(anchor_score, 6)}


def active_template_run(track: Mapping[str, Any], anchor_frame: int) -> list[dict[str, Any]]:
    rows = [dict(row) for row in track.get("rows") or []]
    by_frame = {int(row["timeline_frame"]): row for row in rows}
    strong = {frame for frame, row in by_frame.items() if float(row["score"]) >= 0.46}
    require(anchor_frame in strong, "template_anchor_not_active")
    start = end = int(anchor_frame)
    while start - 1 in by_frame and (start - 1 in strong or (float(by_frame[start - 1]["score"]) >= 0.30 and start in strong)):
        start -= 1
    while end + 1 in by_frame and (end + 1 in strong or (float(by_frame[end + 1]["score"]) >= 0.30 and end in strong)):
        end += 1

    # Preserve one geometrically coherent low-score tail sample. Real roll/fall
    # exits often lose template confidence exactly because the glyph is leaving
    # the frame/ROI. A background jump is rejected by center/size continuity.
    next_frame = end + 1
    if next_frame in by_frame and float(by_frame[next_frame]["score"]) >= 0.24:
        prev = by_frame[end]
        nxt = by_frame[next_frame]
        pcx, pcy = bbox_center(prev["bbox_ref"])
        ncx, ncy = bbox_center(nxt["bbox_ref"])
        pw, ph = bbox_size(prev["bbox_ref"])
        nw, nh = bbox_size(nxt["bbox_ref"])
        step = math.hypot(ncx - pcx, ncy - pcy)
        size_ratio = max(nw / max(1.0, pw), nh / max(1.0, ph), pw / max(1.0, nw), ph / max(1.0, nh))
        if step <= max(14.0, ph * 0.55) and size_ratio <= 1.28:
            end = next_frame

    active = [by_frame[frame] for frame in range(start, end + 1) if frame in by_frame]
    require(bool(active), "template_active_empty")
    return active

def smooth(values: Sequence[float]) -> list[float]:
    result = []
    for index in range(len(values)):
        lo, hi = max(0, index - 1), min(len(values), index + 2)
        result.append(median([float(v) for v in values[lo:hi]]))
    return result


def classify_motion(active: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    frames = [int(row["timeline_frame"]) for row in active]
    boxes = [row["bbox_ref"] for row in active]
    centers = [bbox_center(box) for box in boxes]
    widths_heights = [bbox_size(box) for box in boxes]
    xs = smooth([c[0] for c in centers])
    ys = smooth([c[1] for c in centers])
    hs = smooth([s[1] for s in widths_heights])
    median_h = median(hs)
    _, _, r2x = linear_fit(frames, xs)
    _, _, r2y = linear_fit(frames, ys)
    _, _, r2h = linear_fit(frames, hs)
    displacement = math.hypot(xs[-1] - xs[0], ys[-1] - ys[0]) if len(xs) > 1 else 0.0
    size_change = abs(hs[-1] - hs[0]) if len(hs) > 1 else 0.0
    step = [math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]) for i in range(1, len(xs))]
    jitter = mad(step)

    scores = [float(row.get("score") or 0.0) for row in active]
    peak_score = max(scores) if scores else 0.0
    plateau_threshold = max(0.60, peak_score - 0.15)
    plateau = [i for i, score in enumerate(scores) if score >= plateau_threshold]
    if not plateau:
        plateau = list(range(max(1, len(active) // 2)))
    base_x = median([xs[i] for i in plateau])
    base_y = median([ys[i] for i in plateau])

    tail_count = max(3, len(active) // 5)
    tail = list(range(max(0, len(active) - tail_count), len(active)))
    tail_dy = [ys[i] - base_y for i in tail]
    tail_dx = [xs[i] - base_x for i in tail]
    y_extent = max([abs(v) for v in tail_dy] or [0.0])
    x_extent = max([abs(v) for v in tail_dx] or [0.0])
    plateau_score = median([scores[i] for i in plateau], peak_score)
    final_score = median(scores[-min(3, len(scores)):], peak_score) if scores else 0.0
    score_drop = max(0.0, plateau_score - final_score)

    exit_axis = None
    exit_extent = 0.0
    exit_signed = 0.0
    if y_extent >= max(12.0, median_h * 0.45):
        exit_axis = "y"
        exit_signed = ys[-1] - base_y
        exit_extent = abs(exit_signed)
    elif x_extent >= max(16.0, median_h * 0.60):
        exit_axis = "x"
        exit_signed = xs[-1] - base_x
        exit_extent = abs(exit_signed)
    exit_motion = bool(exit_axis is not None and score_drop >= 0.08)

    coherent_motion = bool(
        len(active) >= 5
        and displacement >= max(8.0, median_h * 0.35)
        and max(r2x, r2y) >= 0.82
        and displacement >= max(4.0, jitter * 4.0)
    )
    size_dynamic = bool(
        len(active) >= 5
        and size_change >= max(4.0, median_h * 0.30)
        and r2h >= 0.88
    )
    direction = None
    if exit_motion:
        if exit_axis == "y":
            direction = "down" if exit_signed > 0 else "up"
        else:
            direction = "right" if exit_signed > 0 else "left"
    return {
        "position_model": "source_exit_trajectory" if exit_motion else ("source_coherent_motion" if coherent_motion else "source_static_hold"),
        "size_model": "source_coherent_scale" if size_dynamic else "source_static_hold",
        "opacity_model": "preserve_or_hold_no_detector_alpha",
        "median_bbox_height_ref_px": round(median_h, 4),
        "median_bbox_width_ref_px": round(median([s[0] for s in widths_heights]), 4),
        "displacement_ref_px": round(displacement, 4),
        "size_change_ref_px": round(size_change, 4),
        "position_r2": [round(r2x, 6), round(r2y, 6)],
        "size_r2": round(r2h, 6),
        "step_jitter_mad_px": round(jitter, 4),
        "exit_motion": exit_motion,
        "exit_axis": exit_axis,
        "exit_direction_top_origin": direction,
        "exit_extent_ref_px": round(exit_extent, 4),
        "template_score_drop": round(score_drop, 6),
        "smoothed_centers_ref": [[round(x, 4), round(y, 4)] for x, y in zip(xs, ys)],
        "smoothed_heights_ref": [round(v, 4) for v in hs],
    }

def motion_frame_path(active: Sequence[Mapping[str, Any]], metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    centers = metrics.get("smoothed_centers_ref") or []
    heights = metrics.get("smoothed_heights_ref") or []
    median_center = [median([float(v[0]) for v in centers]), median([float(v[1]) for v in centers])]
    median_h = median([float(v) for v in heights])
    rows = []
    for index, source in enumerate(active):
        if metrics["position_model"] == "source_static_hold":
            cx, cy = median_center
        else:
            cx, cy = [float(v) for v in centers[index]]
        h = float(heights[index]) if metrics["size_model"] == "source_coherent_scale" else median_h
        bbox = source["bbox_ref"]
        w = float(bbox[2]) - float(bbox[0])
        rows.append({
            "timeline_frame": int(source["timeline_frame"]),
            "position_top_origin": [round(cx / REF_WIDTH, 6), round(cy / REF_HEIGHT, 6)],
            "position_fusion": [round(cx / REF_WIDTH, 6), round(1.0 - cy / REF_HEIGHT, 6)],
            "source_width_ref_px": round(w, 4),
            "source_height_ref_px": round(h, 4),
            "template_score": round(float(source.get("score") or 0.0), 6),
        })
    return rows


def current_size_map(post: Mapping[str, Any], universal: Mapping[str, Any], v4_tokens: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for section in ("repair_size_updates", "protected_size_updates"):
        for row in post.get(section) or []:
            values = [float(item.get("value") or 0.0) for item in row.get("size_keys") or [] if float(item.get("value") or 0.0) > 0]
            if values:
                result[str(row.get("instance_id") or "")] = median(values)
    for row in universal.get("instances") or []:
        instance_id = str(row.get("instance_id") or "")
        if instance_id in result:
            continue
        values = [float(item.get("application_size_candidate") or 0.0) for item in row.get("frame_path") or [] if float(item.get("application_size_candidate") or 0.0) > 0]
        if values:
            result[instance_id] = median(values)
    for token in v4_tokens:
        instance_id = str(token.get("visual_token_id") or "")
        if instance_id in result:
            continue
        values = [float(item.get("application_size_candidate") or 0.0) for item in token.get("frame_path") or [] if float(item.get("application_size_candidate") or 0.0) > 0]
        if values:
            result[instance_id] = median(values)
    return result


def border_background(frame: np.ndarray, bbox: Sequence[int]) -> np.ndarray:
    x0, y0, x1, y1 = [int(v) for v in bbox]
    pad = max(3, int(round((y1 - y0) * 0.35)))
    ax0, ay0 = max(0, x0 - pad), max(0, y0 - pad)
    ax1, ay1 = min(frame.shape[1], x1 + pad), min(frame.shape[0], y1 + pad)
    around = frame[ay0:ay1, ax0:ax1]
    if around.size == 0:
        return np.array([127.0, 127.0, 127.0], dtype=np.float32)
    k = max(1, min(pad // 2, max(1, around.shape[0] // 4), max(1, around.shape[1] // 4)))
    border = np.concatenate([
        around[:k].reshape(-1, 3), around[-k:].reshape(-1, 3), around[:, :k].reshape(-1, 3), around[:, -k:].reshape(-1, 3)
    ], axis=0)
    return np.median(border.astype(np.float32), axis=0)


def sample_interior_fill(frame: np.ndarray, bbox: Sequence[int]) -> tuple[str, float]:
    x0, y0, x1, y1 = [int(round(v)) for v in bbox]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(frame.shape[1], x1), min(frame.shape[0], y1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return "", 0.0
    crop = frame[y0:y1, x0:x1]
    bg = border_background(frame, [x0, y0, x1, y1])
    delta = np.linalg.norm(crop.astype(np.float32) - bg.reshape(1, 1, 3), axis=2)
    threshold = max(18.0, float(np.percentile(delta, 55.0)))
    mask = (delta >= threshold).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), dtype=np.uint8))
    if int(mask.sum()) < 8:
        return "", 0.0
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    values = distance[mask > 0]
    interior_threshold = max(0.8, float(np.percentile(values, 60.0))) if len(values) else 0.8
    interior = (mask > 0) & (distance >= interior_threshold)
    pixels = crop[interior] if int(interior.sum()) >= 8 else crop[mask > 0]
    if len(pixels) < 8:
        return "", 0.0
    quant = (pixels.astype(np.int16) // 16) * 16 + 8
    quant = np.clip(quant, 0, 255).astype(np.uint8)
    bins, counts = np.unique(quant.reshape(-1, 3), axis=0, return_counts=True)
    best = int(np.argmax(counts))
    b, g, r = [int(v) for v in bins[best]]
    confidence = float(counts[best]) / max(1, int(counts.sum()))
    return f"#{r:02x}{g:02x}{b:02x}", round(confidence, 6)


def robust_fill(video: VideoSource, path: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not path:
        return {"apply": False, "fill_hex": "", "confidence": 0.0, "support": 0}
    indices = sorted(set([0, len(path) // 4, len(path) // 2, (3 * len(path)) // 4, len(path) - 1]))
    samples = []
    for index in indices:
        row = path[index]
        frame = video.read_ref(int(row["timeline_frame"]))
        bbox = row.get("source_bbox_ref") or None
        if bbox is None:
            cx = float(row["position_top_origin"][0]) * REF_WIDTH
            cy = float(row["position_top_origin"][1]) * REF_HEIGHT
            w = float(row.get("source_width_ref_px") or 1.0)
            h = float(row.get("source_height_ref_px") or 1.0)
            bbox = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
        value, confidence = sample_interior_fill(frame, bbox)
        if value and confidence > 0:
            samples.append((value, confidence))
    if not samples:
        return {"apply": False, "fill_hex": "", "confidence": 0.0, "support": 0}
    groups: dict[str, list[float]] = defaultdict(list)
    for value, confidence in samples:
        groups[value].append(confidence)
    best = sorted(groups, key=lambda value: (len(groups[value]), median(groups[value])), reverse=True)[0]
    support = len(groups[best])
    consistency = support / len(samples)
    confidence = median(groups[best])
    return {
        "apply": bool(support >= 2 and consistency >= 0.50 and confidence >= 0.20),
        "fill_hex": best,
        "confidence": round(confidence, 6),
        "support": support,
        "sample_count": len(samples),
        "consistency": round(consistency, 6),
        "basis": "source_glyph_interior_multiframe_consensus",
    }


def line_groups(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates = [row for row in rows if row.get("authorized") and row.get("visual_window") and row.get("median_source_bbox_ref")]
    edges: dict[str, set[str]] = defaultdict(set)
    by_id = {str(row["instance_id"]): row for row in candidates}
    ids = sorted(by_id)
    for i, left_id in enumerate(ids):
        left = by_id[left_id]
        lw = left["visual_window"]
        lb = left["median_source_bbox_ref"]
        lcx, lcy = bbox_center(lb)
        _, lh = bbox_size(lb)
        for right_id in ids[i + 1:]:
            right = by_id[right_id]
            rw = right["visual_window"]
            overlap = min(int(lw[1]), int(rw[1])) - max(int(lw[0]), int(rw[0]))
            if overlap < 2:
                continue
            rb = right["median_source_bbox_ref"]
            rcx, rcy = bbox_center(rb)
            _, rh = bbox_size(rb)
            same_line = abs(lcy - rcy) <= max(7.0, 0.55 * max(lh, rh))
            horizontal_distance = abs(lcx - rcx)
            if same_line and horizontal_distance <= REF_WIDTH * 0.48:
                edges[left_id].add(right_id)
                edges[right_id].add(left_id)
    seen: set[str] = set()
    groups = []
    for instance_id in ids:
        if instance_id in seen or not edges.get(instance_id):
            continue
        stack = [instance_id]
        members = []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            members.append(cur)
            stack.extend(sorted(edges.get(cur, set()) - seen))
        if len(members) < 2:
            continue
        members.sort(key=lambda item: bbox_center(by_id[item]["median_source_bbox_ref"])[0])
        groups.append({
            "group_id": f"line_group_{len(groups)+1:03d}",
            "member_instance_ids": members,
            "source_order": members,
            "basis": "overlapping_source_windows_same_line_geometry",
            "transcript_timing_authority": False,
        })
    return groups


def validate_occlusion(occlusion: Mapping[str, Any], foreground: Mapping[str, Any]) -> dict[str, Any]:
    require(occlusion.get("ok") is True, "occlusion_not_ok")
    require(foreground.get("ok") is True, "foreground_not_ok")
    summary = foreground.get("summary") if isinstance(foreground.get("summary"), Mapping) else {}
    spans = [row for row in foreground.get("asset_spans") or [] if isinstance(row, Mapping)]
    require(bool(summary.get("ready_for_v4_import")), "foreground_not_ready")
    require(all(row.get("complete") is True for row in spans), "foreground_incomplete")
    return {
        "enabled": bool(spans),
        "asset_span_count": len(spans),
        "complete_asset_span_count": sum(1 for row in spans if row.get("complete") is True),
        "affected_cue_ids": sorted({str(cue) for row in spans for cue in row.get("affected_cue_ids") or []}),
        "required_layer_order": "foreground_rgba_above_textplus",
        "must_survive_caption_mutation": True,
        "persistent_readback_required": True,
    }


def build(repo_root: Path, output_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    paths = [UNIVERSAL, SEMANTIC, POST_METRICS, V4, WORD_TRACKS, OCCLUSION, FOREGROUND, OCR_MODULE]
    for rel in paths:
        require((repo_root / rel).is_file(), f"missing_input:{rel}")
    universal = load_json(repo_root / UNIVERSAL)
    semantic = load_json(repo_root / SEMANTIC)
    post = load_json(repo_root / POST_METRICS)
    v4 = load_json(repo_root / V4)
    word_tracks = load_json(repo_root / WORD_TRACKS)
    occlusion = load_json(repo_root / OCCLUSION)
    foreground = load_json(repo_root / FOREGROUND)

    summary = universal.get("summary") or {}
    require(int(summary.get("total_instances") or 0) == EXPECTED_TOTAL, "total")
    require(int(summary.get("protected_existing_instances") or 0) == EXPECTED_PROTECTED, "protected")
    require(int(summary.get("source_confirmed_repair_instances") or 0) == EXPECTED_EXISTING_CONFIRMED, "existing_confirmed")
    require(universal.get("policy", {}).get("transcript_timing_authority") is False, "universal_transcript")
    require(semantic.get("policy", {}).get("transcript_timing_authority") is False, "semantic_transcript")
    require(post.get("policy", {}).get("transcript_timing_authority") is False, "post_transcript")

    source_info = (universal.get("inputs") or {}).get("source_video") or {}
    source_rel = Path(str(source_info.get("path") or "input/DZsqH7auhjt.mp4").replace("\\", "/"))
    source_path = repo_root / source_rel
    require(source_path.is_file(), f"source_video:{source_path}")
    if source_info.get("sha256"):
        require(sha256(source_path) == str(source_info["sha256"]), "source_video_sha256")

    universal_rows = {str(row.get("instance_id") or ""): row for row in universal.get("instances") or [] if isinstance(row, Mapping)}
    semantic_rows = {str(row.get("instance_id") or ""): row for row in semantic.get("coverage") or [] if isinstance(row, Mapping)}
    tracks = {str(row.get("cue_id") or ""): row for row in word_tracks.get("tracks") or [] if isinstance(row, Mapping)}
    v4_tokens = flatten_v4(v4)
    v4_map = {str(row.get("visual_token_id") or ""): row for row in v4_tokens}

    existing_ids = sorted(instance_id for instance_id, row in universal_rows.items() if row.get("presence_status") == "source_confirmed")
    protected_ids = sorted(instance_id for instance_id, row in universal_rows.items() if row.get("presence_status") == "protected_existing")
    new_ids = sorted(instance_id for instance_id, row in semantic_rows.items() if row.get("coverage_status") == "source_confirmed")
    unresolved_ids = sorted(instance_id for instance_id, row in semantic_rows.items() if row.get("coverage_status") == "source_unresolved")
    removed_ids = sorted(instance_id for instance_id, row in semantic_rows.items() if row.get("coverage_status") == "source_absent_or_nonsemantic")
    require(len(existing_ids) == EXPECTED_EXISTING_CONFIRMED, "existing_count")
    require(len(new_ids) == EXPECTED_NEW_CONFIRMED, "new_count")
    require(len(set(existing_ids + new_ids)) == EXPECTED_REPAIR, "repair_count")
    require(len(unresolved_ids) == EXPECTED_UNRESOLVED, "unresolved_count")
    require(len(removed_ids) == EXPECTED_REMOVED, "removed_count")
    require(len(protected_ids) == EXPECTED_PROTECTED, "protected_count")

    ordered_ids = [str(row.get("instance_id") or "") for row in universal.get("instances") or [] if isinstance(row, Mapping) and str(row.get("instance_id") or "")]
    canonical_by_id = {
        instance_id: str(universal_rows.get(instance_id, {}).get("canonical_text") or semantic_rows.get(instance_id, {}).get("canonical_text") or "")
        for instance_id in ordered_ids
    }

    observations_by_id: dict[str, list[dict[str, Any]]] = {}
    for instance_id in existing_ids:
        row = universal_rows[instance_id]
        observations_by_id[instance_id] = track_observations(tracks.get(instance_id, {}), str(row.get("canonical_text") or ""))
    for instance_id in new_ids:
        observations_by_id[instance_id] = [dict(row) for row in semantic_rows[instance_id].get("semantic_observations") or [] if isinstance(row, Mapping)]

    compound_decompositions: dict[str, dict[str, Any]] = {}
    for instance_id in existing_ids + new_ids:
        canonical = canonical_by_id.get(instance_id, "")
        if strict_anchor_ok(canonical, observations_by_id[instance_id]):
            continue
        enriched, evidence = compound_ocr_decompose_observations(
            instance_id,
            observations_by_id[instance_id],
            ordered_ids,
            canonical_by_id,
        )
        if evidence.get("applied"):
            observations_by_id[instance_id] = enriched
            compound_decompositions[instance_id] = evidence

    suspicious = []
    for instance_id in existing_ids:
        row = universal_rows[instance_id]
        canonical = str(row.get("canonical_text") or "")
        if not strict_anchor_ok(canonical, observations_by_id[instance_id]):
            suspicious.append(row)
    reanchors, reanchor_summary = reanchor_short_tokens(
        repo_root, suspicious, source_path, args.ocr_lang, args.ocr_device, args.ocr_gpu_id, args.min_ocr_confidence
    )
    require(not reanchor_summary["failures"], f"strict_reanchor_failures:{','.join(reanchor_summary['failures'])}")
    for instance_id, rows in reanchors.items():
        observations_by_id[instance_id] = rows

    calibration = build_render_calibration(v4_tokens)
    current_sizes = current_size_map(post, universal, v4_tokens)
    video = VideoSource(source_path)
    correction_rows: list[dict[str, Any]] = []
    try:
        for index, instance_id in enumerate(existing_ids + new_ids, start=1):
            source_row = universal_rows[instance_id]
            canonical = str(source_row.get("canonical_text") or semantic_rows.get(instance_id, {}).get("canonical_text") or "")
            observations = observations_by_id[instance_id]
            require(strict_anchor_ok(canonical, observations), f"strict_anchor:{instance_id}")
            anchor = best_anchor(canonical, observations)
            require(anchor is not None, f"anchor:{instance_id}")
            anchor_frame = int(anchor["timeline_frame"])
            anchor_bbox = [float(v) for v in anchor["normalized_bbox"]]
            if instance_id in semantic_rows and semantic_rows[instance_id].get("coverage_status") == "source_confirmed":
                search = (semantic_rows[instance_id].get("search_prior") or {}).get("source_pixel_search_window")
            else:
                search = source_row.get("visual_window") or source_row.get("seed_window_only")
            require(isinstance(search, list) and len(search) == 2, f"search:{instance_id}")
            search_window = [max(0, int(search[0]) - 2), int(search[1]) + 2]
            semantic_run = semantic_observation_run(canonical, observations, anchor_frame)
            if len({int(row["timeline_frame"]) for row in semantic_run}) >= 2:
                active = dense_track_from_observations(semantic_run)
                tracking_basis = "source_semantic_ocr_temporal_consensus"
                print(f"[visual-fidelity-v2] semantic track {index}/{EXPECTED_REPAIR} {instance_id} frames={[active[0]['timeline_frame'], active[-1]['timeline_frame'] + 1]}", flush=True)
            else:
                print(f"[visual-fidelity-v2] template {index}/{EXPECTED_REPAIR} {instance_id} anchor={anchor_frame} search={search_window}", flush=True)
                tracked = template_track(video, anchor_frame, anchor_bbox, search_window)
                active = active_template_run(tracked, anchor_frame)
                tracking_basis = "sparse_semantic_anchor_plus_source_template_continuity"
            metrics = classify_motion(active)
            path = motion_frame_path(active, metrics)
            for path_row, source_track in zip(path, active):
                path_row["source_bbox_ref"] = [int(v) for v in source_track["bbox_ref"]]
            widths = [float(row["source_width_ref_px"]) for row in path]
            heights = [float(row["source_height_ref_px"]) for row in path]
            median_bbox = [
                median([float(row["source_bbox_ref"][0]) for row in path]),
                median([float(row["source_bbox_ref"][1]) for row in path]),
                median([float(row["source_bbox_ref"][2]) for row in path]),
                median([float(row["source_bbox_ref"][3]) for row in path]),
            ]
            model = calibration_for(source_row, calibration)
            size = source_size_to_application(canonical, median(widths), median(heights), model)
            current_size = float(current_sizes.get(instance_id) or 0.0)
            size_apply = bool(current_size > 0 and abs(size["target_size"] / current_size - 1.0) >= 0.07)
            case = source_case_consensus(canonical, observations)
            fill = robust_fill(video, path)
            correction_rows.append({
                "instance_id": instance_id,
                "target_name": str(source_row.get("target_name") or ""),
                "canonical_text": canonical,
                "identity_status": "strict_source_semantic_confirmed",
                "identity_basis": "strict_exact_or_high_confidence_source_ocr_anchor",
                "tracking_basis": tracking_basis,
                "reanchored": instance_id in reanchors,
                "compound_ocr_decomposition": compound_decompositions.get(instance_id),
                "authorized": True,
                "visual_window": [int(path[0]["timeline_frame"]), int(path[-1]["timeline_frame"]) + 1],
                "source_anchor": anchor,
                "frame_path": path,
                "motion": {k: v for k, v in metrics.items() if k not in {"smoothed_centers_ref", "smoothed_heights_ref"}},
                "median_source_bbox_ref": [round(v, 4) for v in median_bbox],
                "size": {
                    **size,
                    "current_size": round(current_size, 12),
                    "apply": size_apply,
                    "font_family": font_key(source_row)[0],
                    "font_style": font_key(source_row)[1],
                },
                "text_case": case,
                "fill": fill,
                "opacity_action": "preserve_existing_or_hold; detector_score_not_alpha",
                "transcript_timing_authority": False,
            })

        # Protected visual layers keep semantic identity but receive source-template
        # motion review. This is what allows real exit trajectories to survive.
        protected_motion = []
        for instance_id in protected_ids:
            token = v4_map.get(instance_id)
            require(token is not None, f"protected_token:{instance_id}")
            anchor = token.get("source_pixel_anchor") or {}
            bbox = anchor.get("source_bbox_px_540x960")
            window = token.get("visual_window")
            if not isinstance(bbox, list) or len(bbox) != 4 or not isinstance(window, list) or len(window) != 2:
                protected_motion.append({"instance_id": instance_id, "authorized": False, "reason": "missing_source_anchor"})
                continue
            bbox_norm = normalized_bbox(bbox, REF_WIDTH, REF_HEIGHT)
            ref_frame = int(anchor.get("reference_frame") or ((int(window[0]) + int(window[1]) - 1) // 2))
            tracked = template_track(video, ref_frame, bbox_norm, [int(window[0]), int(window[1]) + 2])
            active = active_template_run(tracked, ref_frame)
            metrics = classify_motion(active)
            path = motion_frame_path(active, metrics)
            protected_motion.append({
                "instance_id": instance_id,
                "target_name": str(token.get("target_name") or ""),
                "authorized": True,
                "visual_window": [int(path[0]["timeline_frame"]), int(path[-1]["timeline_frame"]) + 1],
                "frame_path": path,
                "motion": {k: v for k, v in metrics.items() if k not in {"smoothed_centers_ref", "smoothed_heights_ref"}},
                "opacity_action": "preserve_existing_opacity_keys",
                "transcript_timing_authority": False,
            })
    finally:
        video.close()

    layout_groups = line_groups(correction_rows)
    occlusion_contract = validate_occlusion(occlusion, foreground)
    position_dynamic = sum(1 for row in correction_rows if row["motion"]["position_model"] != "source_static_hold")
    size_dynamic = sum(1 for row in correction_rows if row["motion"]["size_model"] != "source_static_hold")
    exit_count = sum(1 for row in correction_rows if row["motion"]["exit_motion"]) + sum(1 for row in protected_motion if row.get("authorized") and row["motion"]["exit_motion"])
    size_updates = sum(1 for row in correction_rows if row["size"]["apply"])
    fill_updates = sum(1 for row in correction_rows if row["fill"]["apply"])
    case_updates = sum(1 for row in correction_rows if row["text_case"]["apply"])

    result = {
        "schema_version": 2,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "primary_authority": "source_video_pixels_plus_strict_semantic_anchor_plus_visual_continuity",
            "transcript_timing_authority": False,
            "per_cue_hardcoded_overrides": False,
            "screenshot_specific_overrides": False,
            "geometry_only_semantic_promotion": False,
            "short_tokens_require_exact_semantic_anchor": True,
            "compound_ocr_decomposition_requires_exact_adjacent_concat": True,
            "compound_ocr_decomposition_requires_multi_frame_consensus": True,
            "static_motion_is_default": True,
            "detector_score_controls_opacity": False,
            "weak_family_font_calibration_must_fallback": True,
            "source_case_is_visual_style": True,
            "occlusion_foreground_must_survive_caption_mutation": True,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "inputs": {
            str(rel): {"path": str(rel), "sha256": sha256(repo_root / rel)} for rel in paths
        } | {"source_video": {"path": str(source_rel), "sha256": sha256(source_path)}},
        "configuration": {
            "ocr_lang": args.ocr_lang,
            "ocr_device": reanchor_summary.get("ocr_device"),
            "min_ocr_confidence": args.min_ocr_confidence,
            "template_active_threshold": 0.46,
            "static_motion_displacement_threshold": "max(8px,0.35*glyph_height)",
            "dynamic_size_threshold": "max(4px,0.30*glyph_height)",
            "family_calibration_min_samples": MIN_FAMILY_CALIBRATION_SAMPLES,
        },
        "inventory": {
            "structural_total": EXPECTED_TOTAL,
            "physical_textplus": EXPECTED_PHYSICAL,
            "protected": protected_ids,
            "repair_ready": existing_ids + new_ids,
            "unresolved_preserved": unresolved_ids,
            "composite_structural_removed": removed_ids,
        },
        "strict_reanchor": reanchor_summary,
        "compound_ocr_decompositions": compound_decompositions,
        "font_render_calibration_v2": calibration,
        "repair_instances": correction_rows,
        "protected_motion_review": protected_motion,
        "layout_groups": layout_groups,
        "occlusion_contract": occlusion_contract,
        "summary": {
            "structural_total": EXPECTED_TOTAL,
            "physical_textplus": EXPECTED_PHYSICAL,
            "repair_instances": len(correction_rows),
            "protected_instances": len(protected_motion),
            "unresolved_preserved": len(unresolved_ids),
            "composite_structural_removed": len(removed_ids),
            "strict_reanchor_required": int(reanchor_summary["required"]),
            "strict_reanchor_failures": len(reanchor_summary["failures"]),
            "compound_ocr_decompositions": len(compound_decompositions),
            "size_updates": size_updates,
            "fill_updates": fill_updates,
            "case_updates": case_updates,
            "dynamic_position_instances": position_dynamic,
            "dynamic_size_instances": size_dynamic,
            "detected_exit_motion_instances": exit_count,
            "layout_group_count": len(layout_groups),
            "occlusion_asset_spans": int(occlusion_contract["asset_span_count"]),
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "semantic_sha256": "",
        "next_boundary": "STEP_3E_VISUAL_FIDELITY_V2_ISOLATED_RESOLVE_APPLICATION_AFTER_AUTHORITY_VALIDATION",
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
    parser.add_argument("--min-ocr-confidence", type=float, default=0.22)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    output = (root / DEFAULT_OUTPUT) if args.output is None else args.output.resolve()
    result = build(root, output, args)
    print(json.dumps({"ok": result["ok"], "task_id": TASK_ID, "summary": result["summary"], "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
