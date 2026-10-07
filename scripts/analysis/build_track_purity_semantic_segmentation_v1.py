#!/usr/bin/env python3
"""Derive generic track-purity and semantic-segmentation authority."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import re
import sys
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np


CLASSES = {
    "PURE_SINGLE_OBJECT", "FRAGMENT_TRACK", "MULTI_OBJECT_CROP",
    "TRACK_SWITCH", "NON_CAPTION_TRACK", "UNRESOLVED_TRACK",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", str(value or "").lower()))


def compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def similarity(a: Any, b: Any) -> float:
    aa, bb = compact(a), compact(b)
    return round(SequenceMatcher(None, aa, bb).ratio(), 6) if aa and bb else 0.0


def containment(a: Any, b: Any) -> float:
    aa, bb = compact(a), compact(b)
    if not aa or not bb or (aa not in bb and bb not in aa):
        return 0.0
    return round(min(len(aa), len(bb)) / max(len(aa), len(bb)), 6)


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = max(1.0, (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)
    return round(inter / union, 6)


def overlap(a: Sequence[int], b: Sequence[int], margin: int = 0) -> bool:
    return int(a[0]) <= int(b[1]) + margin and int(b[0]) <= int(a[1]) + margin


def sampled_frames(start: int, end: int, limit: int = 7) -> list[int]:
    values = list(range(int(start), int(end) + 1))
    if len(values) <= limit:
        return values
    return sorted({values[round(i * (len(values) - 1) / (limit - 1))] for i in range(limit)})


def load_ocr_module(path: Path):
    spec = importlib.util.spec_from_file_location("vc_track_purity_ocr", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"ocr_module_load_failed:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def crop_for_bbox(frame: np.ndarray, bbox: Sequence[float]) -> np.ndarray:
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    px, py = max(30, (x2-x1)//3), max(24, (y2-y1)//2)
    return frame[max(0, y1-py):min(frame.shape[0], y2+py), max(0, x1-px):min(frame.shape[1], x2+px)]


def component_count(crop: np.ndarray) -> int:
    if crop.size == 0:
        return 0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary)
    minimum = max(12, crop.shape[0] * crop.shape[1] // 3000)
    return sum(1 for i in range(1, count) if int(stats[i, cv2.CC_STAT_AREA]) >= minimum)


def ocr_text(module: Any, engine: Any, crop: np.ndarray, temp: Path, token: str) -> tuple[str, list[dict[str, Any]]]:
    result = module.run_ocr(engine, crop, temp, token)
    parsed = module.parse_paddle_result(result)
    lines = []
    for box, text, confidence in parsed:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        lines.append({"text": str(text), "confidence": round(float(confidence), 6), "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    lines.sort(key=lambda x: ((x["bbox"][1]+x["bbox"][3])/2, (x["bbox"][0]+x["bbox"][2])/2))
    return " ".join(x["text"] for x in lines).strip(), lines


def geometry_features(style: Mapping[str, Any]) -> dict[str, Any]:
    observations = sorted(style["geometry"].get("accepted_source_observations") or [], key=lambda x: int(x["source_frame"]))
    ious, center_steps, size_steps = [], [], []
    for left, right in zip(observations, observations[1:]):
        a, b = left["bbox"], right["bbox"]
        ious.append(bbox_iou(a, b))
        ac, bc = ((a[0]+a[2])/2, (a[1]+a[3])/2), ((b[0]+b[2])/2, (b[1]+b[3])/2)
        center_steps.append(math.hypot(bc[0]-ac[0], bc[1]-ac[1]))
        aw, ah, bw, bh = max(1, a[2]-a[0]), max(1, a[3]-a[1]), max(1, b[2]-b[0]), max(1, b[3]-b[1])
        size_steps.append(abs(math.log(bw/aw)) + abs(math.log(bh/ah)))
    return {
        "accepted_observation_count": len(observations),
        "adjacent_iou_median": round(float(np.median(ious)), 6) if ious else None,
        "center_step_median_px": round(float(np.median(center_steps)), 6) if center_steps else None,
        "size_log_step_median": round(float(np.median(size_steps)), 6) if size_steps else None,
    }


def extract_features(source: Mapping[str, Any], linkage: Mapping[str, Any], style: Mapping[str, Any], composition: Mapping[str, Any], video: Path, ocr_module: Path) -> list[dict[str, Any]]:
    source_rows = {x["mapped_visual_identity"]: x for x in source["objects"] if x.get("status") == "MATCHED"}
    link_rows = {x["identity"]: x for x in linkage["identities"]}
    style_rows = {x["identity"]["stable_identity_id"]: x for x in style["identities"]}
    identities = sorted(source_rows)
    if len(identities) != 113 or set(identities) != set(link_rows) or set(identities) != set(style_rows):
        raise ValueError("identity_accounting_mismatch")
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"video_open_failed:{video}")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    module = load_ocr_module(ocr_module)
    engine, runtime = module.create_ocr("en", "cpu", 0)
    features = []
    with tempfile.TemporaryDirectory(prefix="vc_track_purity_") as temporary:
        temp = Path(temporary)
        for index, identity in enumerate(identities):
            source_row, link, static = source_rows[identity], link_rows[identity], style_rows[identity]
            frame_range = [int(source_row["first_visible_frame"]), int(source_row["last_visible_frame"])]
            frames = []
            for frame_number in sampled_frames(*frame_range):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ok, frame = cap.read()
                if not ok:
                    frames.append({"source_frame": frame_number, "ocr_text": "", "ocr_lines": [], "component_count": 0, "visible": False})
                    continue
                crop = crop_for_bbox(frame, source_row["bbox"])
                text, lines = ocr_text(module, engine, crop, temp, f"{index}_{frame_number}")
                frames.append({"source_frame": frame_number, "ocr_text": text, "normalized_text": norm(text), "ocr_lines": lines, "component_count": component_count(crop), "visible": bool(lines)})
            features.append({
                "identity": identity, "source_frame_range": frame_range, "representative_bbox": source_row["bbox"],
                "normalized_bbox": source_row["normalized_bbox"], "accepted_observed_text": source_row["observed_text"],
                "contract_text_diagnostic": link["contract_text"], "glyph_candidate_text": link["glyph_artifact_text"],
                "text_mask_relationship": link["text_mask_relationship"],
                "composition_memberships": static["identity"].get("composition_memberships") or [],
                "geometry": geometry_features(static), "frame_samples": frames,
                "style_support": {"font_status": static["typography"]["font"]["authority"]["status"], "fill_status": static["fill"]["authority"]["status"]},
            })
    cap.release()
    by_id = {x["identity"]: x for x in features}
    for row in features:
        neighbors = []
        for other in features:
            if other["identity"] == row["identity"] or not overlap(row["source_frame_range"], other["source_frame_range"], 4):
                continue
            spatial = bbox_iou(row["representative_bbox"], other["representative_bbox"])
            if spatial <= 0.02 and not set(row["composition_memberships"]) & set(other["composition_memberships"]):
                continue
            neighbors.append({"identity": other["identity"], "source_frame_range": other["source_frame_range"], "observed_text": other["accepted_observed_text"], "contract_text": other["contract_text_diagnostic"], "bbox_iou": spatial, "shared_composition": sorted(set(row["composition_memberships"]) & set(other["composition_memberships"]))})
        row["neighbors"] = sorted(neighbors, key=lambda x: x["identity"])
    return features


def text_clusters(samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for sample in samples:
        value = norm(sample.get("ocr_text"))
        if not value:
            continue
        confidence = max((float(x.get("confidence") or 0.0) for x in sample.get("ocr_lines") or []), default=0.0)
        if clusters and (similarity(value, clusters[-1]["representative_text"]) >= 0.62 or containment(value, clusters[-1]["representative_text"]) >= 0.5):
            cluster = clusters[-1]
            cluster["frames"].append(int(sample["source_frame"]))
            cluster["texts"].append(value)
            cluster["confidences"].append(confidence)
            cluster["representative_text"] = max(cluster["texts"], key=lambda x: (len(compact(x)), x))
        else:
            clusters.append({"frames": [int(sample["source_frame"])], "texts": [value], "confidences": [confidence], "representative_text": value})
    return clusters


def fragment_parent(row: Mapping[str, Any]) -> dict[str, Any] | None:
    candidates = [norm(row.get("accepted_observed_text")), *[norm(x.get("ocr_text")) for x in row["frame_samples"]]]
    candidates = [x for x in candidates if len(compact(x)) >= 2]
    best = None
    for neighbor in row["neighbors"]:
        for child in candidates:
            for parent in (neighbor.get("observed_text"), neighbor.get("contract_text")):
                ratio = containment(child, parent)
                length_ratio = len(compact(child)) / max(1, len(compact(parent)))
                fuzzy_fragment = length_ratio <= 0.83 and similarity(child, parent) >= 0.68 and neighbor["bbox_iou"] >= 0.15
                if (0.2 <= ratio < 0.86 and compact(child) in compact(parent)) or fuzzy_fragment:
                    item = {"fragment_text": child, "parent_text": norm(parent), "parent_identity": neighbor["identity"], "containment_ratio": ratio, "bbox_iou": neighbor["bbox_iou"]}
                    if best is None or (item["containment_ratio"], item["bbox_iou"]) > (best["containment_ratio"], best["bbox_iou"]):
                        best = item
    return best


def component_phrase_fragment(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if int(row["geometry"]["accepted_observation_count"]) != 0:
        return None
    candidates = [norm(row.get("accepted_observed_text")), *[norm(x.get("ocr_text")) for x in row["frame_samples"]]]
    for candidate in sorted({x for x in candidates if x}, key=lambda x: (-len(compact(x)), x)):
        supported = []
        for neighbor in row["neighbors"]:
            values = [norm(neighbor.get("observed_text")), norm(neighbor.get("contract_text"))]
            if any(value and (compact(value) in compact(candidate) or similarity(value, candidate) >= 0.68) for value in values):
                supported.append(neighbor["identity"])
        if len(set(supported)) >= 2:
            return {"fragment_text": candidate, "component_identities": sorted(set(supported)), "rule": "multiple_neighbor_components_inside_one_partial_phrase_crop"}
    return None


def infer_track(row: Mapping[str, Any], frame_height: int) -> dict[str, Any]:
    clusters = text_clusters(row["frame_samples"])
    nonempty = [x for x in row["frame_samples"] if norm(x.get("ocr_text"))]
    pair_scores = [similarity(a["representative_text"], b["representative_text"]) for a, b in zip(clusters, clusters[1:])]
    strong_switch = len(clusters) >= 3 and sum(x <= 0.45 for x in pair_scores) >= 2
    if len(clusters) == 2:
        repeated = sorted(len(x["frames"]) for x in clusters)
        boundary_single = repeated[0] == 1 and max(max(x["confidences"]) for x in clusters if len(x["frames"]) == 1) >= 0.8
        strong_switch = pair_scores[0] <= 0.32 and (
            repeated[0] >= 2
            or (row["source_frame_range"][1]-row["source_frame_range"][0] <= 4 and repeated[1] >= 2)
            or (pair_scores[0] <= 0.2 and boundary_single and repeated[1] >= 2 and row["source_frame_range"][1]-row["source_frame_range"][0] >= 10)
        )
    multi_lines = [x for x in nonempty if len(x.get("ocr_lines") or []) >= 2]
    multi_neighbor_support = any(x["shared_composition"] and x["bbox_iou"] > 0.08 for x in row["neighbors"])
    fragment = fragment_parent(row)
    phrase_fragment = component_phrase_fragment(row)
    source_contract_score = similarity(row["accepted_observed_text"], row["contract_text_diagnostic"])
    animation_consensus = (
        len(clusters) == 1
        and len(nonempty) >= 2
        and source_contract_score >= 0.85
        and (similarity(clusters[0]["representative_text"], row["contract_text_diagnostic"]) >= 0.7 or containment(clusters[0]["representative_text"], row["contract_text_diagnostic"]) >= 0.7)
    )
    bottom_region = float(row["normalized_bbox"][1]) >= 0.64
    watermark_like = bottom_region and source_contract_score < 0.35 and len(row["neighbors"]) >= 1

    if watermark_like:
        purity, confidence, reason = "NON_CAPTION_TRACK", 0.93, "bottom_region_static_visual_cluster_without_caption_text_agreement"
    elif len(multi_lines) >= max(2, len(nonempty)//2) and multi_neighbor_support:
        purity, confidence, reason = "MULTI_OBJECT_CROP", 0.9, "multiple_ocr_components_plus_co_visible_neighbor_geometry"
    elif strong_switch:
        purity, confidence, reason = "TRACK_SWITCH", 0.94, "multiple_dissimilar_temporally_ordered_multi_frame_text_clusters"
    elif animation_consensus:
        purity, confidence, reason = "PURE_SINGLE_OBJECT", 0.94, "stable_multi_frame_semantic_consensus_overrides_partial_animation_glyphs"
    elif fragment is not None or phrase_fragment is not None or row["text_mask_relationship"] == "ACCEPTED_PHYSICAL_WORD_FRAGMENT":
        purity, confidence, reason = "FRAGMENT_TRACK", 0.9, "strict_spatial_text_subset_of_temporally_adjacent_or_overlapping_source_object"
    elif nonempty or norm(row["accepted_observed_text"]):
        purity, confidence, reason = "PURE_SINGLE_OBJECT", 0.82, "single_semantic_trajectory_after_containment_based_animation_normalization"
    else:
        purity, confidence, reason = "UNRESOLVED_TRACK", 0.0, "no_stable_source_text_evidence"
    return {
        "identity": row["identity"], "purity_class": purity, "confidence": confidence, "reason": reason,
        "features": {
            "temporal_text_clusters": clusters, "adjacent_cluster_similarity": pair_scores,
            "nonempty_ocr_samples": len(nonempty), "multi_line_samples": len(multi_lines),
            "fragment_parent": fragment, "component_phrase_fragment": phrase_fragment, "source_contract_similarity": source_contract_score,
            "geometry": row["geometry"], "composition_memberships": row["composition_memberships"],
            "neighbor_count": len(row["neighbors"]), "bottom_region": bottom_region,
            "animation_consensus": animation_consensus,
            "style_support_only": row["style_support"],
        },
    }


def segment_track(row: Mapping[str, Any], decision: Mapping[str, Any]) -> list[dict[str, Any]]:
    purity = decision["purity_class"]
    if purity == "NON_CAPTION_TRACK":
        return []
    clusters = decision["features"]["temporal_text_clusters"]
    start, end = row["source_frame_range"]
    if purity == "TRACK_SWITCH" and clusters:
        boundaries = []
        for index, cluster in enumerate(clusters):
            left = start if index == 0 else (clusters[index-1]["frames"][-1] + cluster["frames"][0] + 1)//2
            right = end if index == len(clusters)-1 else (cluster["frames"][-1] + clusters[index+1]["frames"][0])//2
            boundaries.append((left, max(left, right), cluster["representative_text"]))
    elif purity == "MULTI_OBJECT_CROP" and clusters:
        tokens = sorted({token for cluster in clusters for token in norm(cluster["representative_text"]).split() if token})
        boundaries = [(start, end, token) for token in tokens]
    else:
        choices = [x["representative_text"] for x in clusters] + [norm(row["accepted_observed_text"]), norm(row["contract_text_diagnostic"])]
        text = max((x for x in choices if x), key=lambda x: (sum(similarity(x, y) for y in choices), len(compact(x)), x), default="")
        boundaries = [(start, end, text)]
    return [{
        "parent_track_identity": row["identity"],
        "semantic_segment_id": f"{row['identity']}::semantic_segment_{index:03d}",
        "source_frame_start": left, "source_frame_end": right,
        "representative_bbox_trajectory": [row["representative_bbox"]],
        "candidate_visible_text": text, "normalized_text": norm(text),
        "source_evidence": {"sampled_frames": [x["source_frame"] for x in row["frame_samples"]], "accepted_observed_text": row["accepted_observed_text"], "ocr_clusters": clusters},
        "confidence": decision["confidence"], "segmentation_reason": decision["reason"],
        "segment_role": "FRAGMENT" if purity == "FRAGMENT_TRACK" else "UNRESOLVED" if purity == "UNRESOLVED_TRACK" else "SOURCE_OBJECT",
    } for index, (left, right, text) in enumerate(boundaries, 1)]


def production_branch_audit(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in {"extract_features", "text_clusters", "fragment_parent", "component_phrase_fragment", "infer_track", "segment_track"}]
    counts = {"literal": 0, "identity": 0, "composition_id": 0, "frame_range": 0, "reel": 0}
    matches = []
    allowed = CLASSES | {"ACCEPTED_PHYSICAL_WORD_FRAGMENT", "MATCHED"}
    for root in roots:
        for node in ast.walk(root):
            if not isinstance(node, ast.Compare):
                continue
            values = [x.value for x in [node.left, *node.comparators] if isinstance(x, ast.Constant) and isinstance(x.value, str)]
            names = {x.id.lower() for x in ast.walk(node) if isinstance(x, ast.Name)}
            for value in values:
                low = value.lower()
                category = None
                if any(token in low for token in ("caption_tracklet_", "continuous_visual_identity_", "source_visible_recovery_")):
                    category = "identity"
                elif "composition_" in low:
                    category = "composition_id"
                elif re.fullmatch(r"[a-z0-9]{11}", low) and any(x.isalpha() for x in low) and any(x.isdigit() for x in low):
                    category = "reel"
                elif value not in allowed and names & {"text", "observed", "contract", "identity", "composition_id", "frame", "source_frame"}:
                    category = "literal"
                if category:
                    counts[category] += 1
                    matches.append({"function": root.name, "line": node.lineno, "category": category, "value": value})
    return {"counts": counts, "matches": matches, "human_ground_truth_readers": ["evaluate_human_ground_truth"], "production_functions": [x.name for x in roots]}


def evaluate_human_ground_truth(authority: Mapping[str, Any], segments: Mapping[str, Any], ground_truth_path: Path) -> dict[str, Any]:
    truth = load(ground_truth_path)
    predicted = {x["identity"]: x for x in authority["tracks"]}
    segment_rows: dict[str, list[dict[str, Any]]] = {}
    for segment in segments["segments"]:
        segment_rows.setdefault(segment["parent_track_identity"], []).append(segment)
    class_map = {"CLEAN_OBJECT": "PURE_SINGLE_OBJECT", "FRAGMENT": "FRAGMENT_TRACK", "MULTI_OBJECT_CROP": "MULTI_OBJECT_CROP", "TRACK_SWITCH": "TRACK_SWITCH", "NON_CAPTION": "NON_CAPTION_TRACK"}
    rows = []
    for item in truth["rows"]:
        prediction = predicted[item["identity"]]
        expected = class_map.get(item["human_class"])
        agreement = expected is not None and prediction["purity_class"] == expected
        rows.append({**item, "predicted_class": prediction["purity_class"], "agreement": agreement if expected is not None else None, "predicted_segments": segment_rows.get(item["identity"], []), "discrepancy": None if agreement or expected is None else f"expected {expected}; predicted {prediction['purity_class']}"})
    strict = [x for x in rows if x["agreement"] is not None]
    def recall(label: str) -> float:
        selected = [x for x in rows if x["human_class"] == label]
        return round(sum(x["agreement"] is True for x in selected) / len(selected), 6) if selected else 1.0
    return {
        "schema": "video_cloner_track_purity_human_ground_truth_evaluation_v1", "schema_version": 1,
        "ground_truth_path": str(ground_truth_path), "ground_truth_sha256": sha256(ground_truth_path), "production_consumes_ground_truth": False,
        "evaluated_rows": len(rows), "strict_rows": len(strict), "exact_class_agreements": sum(x["agreement"] is True for x in strict),
        "disagreement_count": sum(x["agreement"] is False for x in strict),
        "track_switch_recall": recall("TRACK_SWITCH"), "fragment_recall": recall("FRAGMENT"), "non_caption_recall": recall("NON_CAPTION"),
        "false_track_switches_on_clean_controls": sum(x["human_class"] == "CLEAN_OBJECT" and x["predicted_class"] == "TRACK_SWITCH" for x in rows),
        "invalid_classes_on_clean_controls": sum(x["human_class"] == "CLEAN_OBJECT" and x["predicted_class"] in {"FRAGMENT_TRACK", "NON_CAPTION_TRACK", "TRACK_SWITCH"} for x in rows),
        "rows": rows,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    paths = {name: Path(getattr(args, name)).resolve() for name in ("source", "linkage", "style", "composition", "video", "ocr_module", "ground_truth")}
    source, linkage, style, composition = (load(paths[x]) for x in ("source", "linkage", "style", "composition"))
    features = extract_features(source, linkage, style, composition, paths["video"], paths["ocr_module"])
    first = [infer_track(row, 1920) for row in features]
    second = [infer_track(row, 1920) for row in features]
    segments_first = [segment for row, decision in zip(features, first) for segment in segment_track(row, decision)]
    segments_second = [segment for row, decision in zip(features, second) for segment in segment_track(row, decision)]
    first_hash, second_hash = canonical_sha256({"tracks": first, "segments": segments_first}), canonical_sha256({"tracks": second, "segments": segments_second})
    deterministic = first_hash == second_hash
    out = Path(args.output).resolve()
    inputs = {name: {"path": str(path), "sha256": sha256(path)} for name, path in paths.items() if name != "ground_truth"}
    purity_counts = Counter(x["purity_class"] for x in first)
    authority = {"schema": "video_cloner_track_purity_authority_v1", "schema_version": 1, "inputs": inputs, "track_count": len(first), "counts": dict(purity_counts), "tracks": first}
    segments = {"schema": "video_cloner_semantic_segments_v1", "schema_version": 1, "track_count": len(first), "segment_count": len(segments_first), "segments": segments_first}
    evaluation = evaluate_human_ground_truth(authority, segments, paths["ground_truth"])
    audit = production_branch_audit(Path(__file__))
    unresolved = [x for x in first if x["purity_class"] == "UNRESOLVED_TRACK"]
    human_gate = evaluation["track_switch_recall"] == 1.0 and evaluation["fragment_recall"] == 1.0 and evaluation["non_caption_recall"] == 1.0 and evaluation["invalid_classes_on_clean_controls"] == 0
    architecture_ok = not any(audit["counts"].values())
    status = "READY_FOR_SOURCE_AUTHORITY_V3" if deterministic and architecture_ok and human_gate and not unresolved else "BLOCKED_ARCHITECTURE" if not architecture_ok else "BLOCKED_TRACK_EVIDENCE"
    authority["status"] = segments["status"] = status
    reports = {
        "track_switch_report.json": [x for x in first if x["purity_class"] == "TRACK_SWITCH"],
        "fragment_track_report.json": [x for x in first if x["purity_class"] == "FRAGMENT_TRACK"],
        "multi_object_crop_report.json": [x for x in first if x["purity_class"] == "MULTI_OBJECT_CROP"],
        "non_caption_track_report.json": [x for x in first if x["purity_class"] == "NON_CAPTION_TRACK"],
        "unresolved_track_report.json": unresolved,
    }
    write(out / "track_purity_authority_v1.json", authority)
    write(out / "semantic_segments_v1.json", segments)
    for name, rows in reports.items():
        write(out / name, {"schema": name.removesuffix(".json"), "schema_version": 1, "status": status, "count": len(rows), "tracks": rows})
    write(out / "human_ground_truth_evaluation.json", evaluation)
    write(out / "production_branch_audit.json", {"schema": "video_cloner_track_purity_production_branch_audit_v1", "schema_version": 1, **audit})
    write(out / "determinism_report.json", {"schema": "video_cloner_track_purity_determinism_v1", "schema_version": 1, "identical": deterministic, "first_hash": first_hash, "second_hash": second_hash, "purity_equal": first == second, "segments_equal": segments_first == segments_second})
    return {"status": status, "output": str(out), "tracks": len(first), "purity": dict(purity_counts), "segments": len(segments_first), "split_tracks": sum(len([s for s in segments_first if s["parent_track_identity"] == x["identity"]]) > 1 for x in first), "evaluation": {k: evaluation[k] for k in ("evaluated_rows", "exact_class_agreements", "disagreement_count", "track_switch_recall", "fragment_recall", "non_caption_recall", "false_track_switches_on_clean_controls", "invalid_classes_on_clean_controls")}, "branch_audit": audit["counts"], "deterministic": deterministic}


def self_test() -> None:
    assert norm("You're!") == "you're"
    assert similarity("launcn", "launch") > 0.8
    assert containment("vest", "invest") > 0.66
    assert bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert sampled_frames(1, 3) == [1, 2, 3]
    print("SELF_TEST_PASS")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    for name in ("source", "linkage", "style", "composition", "video", "ocr-module", "ground-truth", "output"):
        value.add_argument(f"--{name}", required=True)
    value.add_argument("--self-test", action="store_true")
    return value


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
