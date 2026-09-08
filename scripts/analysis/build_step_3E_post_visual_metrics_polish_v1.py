#!/usr/bin/env python3
"""Build generic post-visual Text+ metrics corrections from source/render evidence.

This stage consumes the visually reviewed confirmed-74 authority, the protected
V4 source/generated bbox anchors, and semantic composite reconciliation. It does
not use cue IDs, words, screenshots, or transcript timing as special cases.

Two generic corrections are allowed:
1. Text+ Size calibration from measured source-glyph height versus measured
   generated-glyph height for the same font/style.
2. Protected composite text reconciliation from semantic coverage when a
   structural sequence was already proven to be represented by that composite.

Center and opacity are deliberately preserved. The current source timeline still
contains the baked reference captions, so fade appearance cannot be judged from
those pixels; existing protected opacity keys are treated as evidence to preserve,
not rewritten by this stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1"
CONFIRMED = Path("artifacts/DZSQH7AUHJT_STEP_3E_CONFIRMED74_REPAIR_AUTHORITY_V1/confirmed74_repair_authority_v1.json")
V4 = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json")
SEMANTIC = Path("artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_v1.json")
OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/post_visual_metrics_polish_v1.json")
EXPECTED_PHYSICAL = 114
EXPECTED_REPAIR = 74
EXPECTED_PROTECTED = 17
EXPECTED_UNRESOLVED = 23
EXPECTED_REMOVED_COMPOSITE = 3
FRAME_HEIGHT = 960
MIN_RATIO = 0.45
MAX_RATIO = 4.50
MIN_SIZE = 0.012
MAX_SIZE = 0.60


def require(value: bool, code: str) -> None:
    if not value:
        raise ValueError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def flatten_v4(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in document.get("groups") or []:
        if not isinstance(group, Mapping):
            continue
        for token in group.get("tokens") or []:
            if isinstance(token, Mapping):
                row = dict(token)
                row["group_id"] = str(group.get("group_id") or "")
                rows.append(row)
    return rows


def font_key(row: Mapping[str, Any]) -> tuple[str, str]:
    font = row.get("font") if isinstance(row.get("font"), Mapping) else {}
    return str(font.get("font_family") or ""), str(font.get("font_style") or "")


def direct_anchor_calibration(token: Mapping[str, Any]) -> dict[str, Any] | None:
    anchor = token.get("source_pixel_anchor") if isinstance(token.get("source_pixel_anchor"), Mapping) else {}
    source_h = float(anchor.get("source_height_px") or 0.0)
    generated_h = float(anchor.get("generated_height_px") or 0.0)
    base_size = float(token.get("application_base_size_candidate") or 0.0)
    if source_h <= 0 or generated_h <= 0 or base_size <= 0:
        return None
    factor = source_h / generated_h
    if not MIN_RATIO <= factor <= MAX_RATIO:
        return None
    rendered_size_per_source_px = base_size * factor / source_h
    return {
        "font_family": font_key(token)[0],
        "font_style": font_key(token)[1],
        "source_height_px": source_h,
        "generated_height_px": generated_h,
        "direct_size_factor": factor,
        "rendered_size_per_source_px": rendered_size_per_source_px,
    }


def robust_family_calibration(tokens: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    evidence: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for token in tokens:
        direct = direct_anchor_calibration(token)
        if not direct:
            continue
        key = (direct["font_family"], direct["font_style"])
        if not all(key):
            continue
        grouped[key].append(float(direct["rendered_size_per_source_px"]))
        evidence[key].append({
            "visual_token_id": str(token.get("visual_token_id") or ""),
            "source_height_px": direct["source_height_px"],
            "generated_height_px": direct["generated_height_px"],
            "rendered_size_per_source_px": round(float(direct["rendered_size_per_source_px"]), 12),
        })
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, values in grouped.items():
        center = float(statistics.median(values))
        deviations = [abs(value - center) for value in values]
        mad = float(statistics.median(deviations)) if deviations else 0.0
        clean = [value for value in values if mad <= 1e-12 or abs(value - center) <= max(mad * 3.5, center * 0.38)]
        if not clean:
            clean = list(values)
        ratio = float(statistics.median(clean))
        result[key] = {
            "font_family": key[0],
            "font_style": key[1],
            "sample_count": len(values),
            "clean_sample_count": len(clean),
            "rendered_size_per_source_px": round(ratio, 12),
            "evidence": evidence[key],
        }
    return result


def protected_size_update(token: Mapping[str, Any]) -> dict[str, Any] | None:
    direct = direct_anchor_calibration(token)
    if not direct:
        return None
    factor = float(direct["direct_size_factor"])
    frame_path = [row for row in token.get("frame_path") or [] if isinstance(row, Mapping)]
    window = [int(v) for v in token.get("visual_window") or []]
    require(len(window) == 2 and window[1] > window[0], f"protected_window:{token.get('visual_token_id')}")
    require([int(row["timeline_frame"]) for row in frame_path] == list(range(window[0], window[1])), f"protected_dense:{token.get('visual_token_id')}")
    size_keys = []
    for row in frame_path:
        timeline_frame = int(row["timeline_frame"])
        value = clamp(float(row["application_size_candidate"]) * factor, MIN_SIZE, MAX_SIZE)
        size_keys.append({"timeline_frame": timeline_frame, "local_frame": timeline_frame - window[0], "value": round(value, 12)})
    return {
        "instance_id": str(token.get("visual_token_id") or ""),
        "target_name": str(token.get("target_name") or ""),
        "display_text": str(token.get("display_text") or ""),
        "font": {"font_family": font_key(token)[0], "font_style": font_key(token)[1]},
        "target_range": window,
        "size_keys": size_keys,
        "direct_size_factor": round(factor, 8),
        "source_height_px": int(round(float(direct["source_height_px"]))),
        "generated_height_px": int(round(float(direct["generated_height_px"]))),
        "basis": "direct_source_vs_generated_glyph_height",
    }


def source_height_px(repair: Mapping[str, Any]) -> float:
    motion = repair.get("motion") if isinstance(repair.get("motion"), Mapping) else {}
    if motion.get("median_bbox_height_px") is not None:
        return float(motion.get("median_bbox_height_px") or 0.0)
    if motion.get("median_bbox_height_norm") is not None:
        return float(motion.get("median_bbox_height_norm") or 0.0) * FRAME_HEIGHT
    return 0.0


def repair_size_update(repair: Mapping[str, Any], calibration: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any] | None:
    key = font_key(repair)
    family = calibration.get(key)
    if not family:
        return None
    height = source_height_px(repair)
    if height <= 0:
        return None
    frame_path = [row for row in repair.get("frame_path") or [] if isinstance(row, Mapping)]
    window = [int(v) for v in repair.get("visual_window") or []]
    require(len(window) == 2 and window[1] > window[0], f"repair_window:{repair.get('instance_id')}")
    require([int(row["timeline_frame"]) for row in frame_path] == list(range(window[0], window[1])), f"repair_dense:{repair.get('instance_id')}")
    old_sizes = [float(row.get("application_size_candidate") or 0.0) for row in frame_path]
    require(all(value > 0 for value in old_sizes), f"repair_size:{repair.get('instance_id')}")
    old_center = float(statistics.median(old_sizes))
    target_center = clamp(height * float(family["rendered_size_per_source_px"]), MIN_SIZE, MAX_SIZE)
    factor = target_center / old_center
    if not MIN_RATIO <= factor <= MAX_RATIO:
        return None
    size_keys = []
    for row in frame_path:
        timeline_frame = int(row["timeline_frame"])
        value = clamp(float(row["application_size_candidate"]) * factor, MIN_SIZE, MAX_SIZE)
        size_keys.append({"timeline_frame": timeline_frame, "local_frame": timeline_frame - window[0], "value": round(value, 12)})
    return {
        "instance_id": str(repair.get("instance_id") or ""),
        "target_name": str(repair.get("target_name") or ""),
        "canonical_text": str(repair.get("canonical_text") or ""),
        "font": {"font_family": key[0], "font_style": key[1]},
        "target_range": window,
        "size_keys": size_keys,
        "source_height_px": round(height, 6),
        "old_median_size": round(old_center, 12),
        "target_median_size": round(target_center, 12),
        "size_factor": round(factor, 8),
        "calibration_sample_count": int(family["sample_count"]),
        "basis": "source_bbox_height_times_empirical_resolve_font_render_ratio",
    }


def protected_text_reconciliation(semantic: Mapping[str, Any], v4_tokens: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    v4_by_id = {str(row.get("visual_token_id") or ""): row for row in v4_tokens}
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in semantic.get("coverage") or []:
        if not isinstance(row, Mapping) or row.get("coverage_status") != "source_absent_or_nonsemantic":
            continue
        composite = row.get("protected_composite") if isinstance(row.get("protected_composite"), Mapping) else {}
        protected_id = str(composite.get("protected_instance_id") or "")
        protected_text = str(composite.get("protected_text") or "").strip()
        if protected_id and protected_text:
            grouped[protected_id].append(row)
    updates = []
    for protected_id, rows in sorted(grouped.items()):
        token = v4_by_id.get(protected_id)
        require(token is not None, f"composite_protected_missing:{protected_id}")
        texts = {str((row.get("protected_composite") or {}).get("protected_text") or "").strip() for row in rows}
        require(len(texts) == 1, f"composite_text_disagreement:{protected_id}")
        text = next(iter(texts))
        current = str(token.get("display_text") or "")
        if text == current:
            continue
        updates.append({
            "instance_id": protected_id,
            "target_name": str((rows[0].get("protected_composite") or {}).get("protected_target_name") or ""),
            "target_range": [int(v) for v in token.get("visual_window") or []],
            "old_text": current,
            "new_text": text,
            "source_instance_ids": sorted({str(v) for row in rows for v in ((row.get("protected_composite") or {}).get("source_instance_ids") or [])}),
            "resolution_methods": sorted({str((row.get("protected_composite") or {}).get("resolution_method") or "") for row in rows}),
            "basis": "semantic_coverage_protected_composite_reconciliation",
        })
    return updates


def protected_fade_evidence(tokens: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for token in tokens:
        frame_path = [row for row in token.get("frame_path") or [] if isinstance(row, Mapping)]
        if not frame_path:
            continue
        factors = [float(row.get("opacity_factor") or 0.0) for row in frame_path]
        if max(factors) - min(factors) <= 1e-6:
            continue
        phases = token.get("animation_phases") if isinstance(token.get("animation_phases"), Mapping) else {}
        exit_window = [int(v) for v in phases.get("exit_window") or []]
        exit_factors = [float(row.get("opacity_factor") or 0.0) for row in frame_path if len(exit_window) == 2 and exit_window[0] <= int(row["timeline_frame"]) < exit_window[1]]
        rows.append({
            "instance_id": str(token.get("visual_token_id") or ""),
            "target_name": str(token.get("target_name") or ""),
            "nontrivial_opacity": True,
            "exit_window": exit_window,
            "exit_min_factor": round(min(exit_factors), 6) if exit_factors else None,
            "action": "preserve_existing_opacity_keys",
        })
    return rows


def validate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    summary = document.get("summary") if isinstance(document.get("summary"), Mapping) else {}
    protected = [row for row in document.get("protected_size_updates") or [] if isinstance(row, Mapping)]
    repair = [row for row in document.get("repair_size_updates") or [] if isinstance(row, Mapping)]
    text = [row for row in document.get("protected_text_updates") or [] if isinstance(row, Mapping)]
    cal = [row for row in document.get("font_render_calibration") or [] if isinstance(row, Mapping)]
    all_names = [str(row.get("target_name") or "") for row in protected + repair]
    checks = {
        "task": document.get("task_id") == TASK_ID,
        "physical_count": summary.get("expected_physical_textplus_count") == EXPECTED_PHYSICAL,
        "repair_source_count": summary.get("confirmed74_repair_instances") == EXPECTED_REPAIR,
        "protected_source_count": summary.get("protected_v4_instances") == EXPECTED_PROTECTED,
        "unresolved_count": summary.get("unresolved_preserved") == EXPECTED_UNRESOLVED,
        "composite_removed_count": summary.get("composite_structural_removed") == EXPECTED_REMOVED_COMPOSITE,
        "protected_partition": len(protected) + len(text) == EXPECTED_PROTECTED,
        "repair_updates_nonempty": bool(repair),
        "size_targets_unique": len(all_names) == len(set(all_names)) and all(all_names),
        "text_targets_unique": len({str(row.get("target_name") or "") for row in text}) == len(text),
        "calibration_nonempty": bool(cal),
        "position_preserved": document.get("policy", {}).get("position_mutation_authorized") is False,
        "opacity_preserved": document.get("policy", {}).get("opacity_mutation_authorized") is False,
        "transcript_false": document.get("policy", {}).get("transcript_timing_authority") is False,
        "no_cue_overrides": document.get("policy", {}).get("per_cue_hardcoded_overrides") is False,
        "resolve_unmodified": document.get("policy", {}).get("resolve_modified") is False,
        "rollout_locked": document.get("policy", {}).get("runtime_authorized") is False,
    }
    return {"checks": checks, "ok": all(checks.values())}


def build(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    confirmed_path, v4_path, semantic_path = root / CONFIRMED, root / V4, root / SEMANTIC
    for path in (confirmed_path, v4_path, semantic_path):
        require(path.is_file(), f"missing:{path}")
    confirmed = load_json(confirmed_path)
    v4 = load_json(v4_path)
    semantic = load_json(semantic_path)
    require(confirmed.get("ok") is True, "confirmed_not_ok")
    require(confirmed.get("policy", {}).get("transcript_timing_authority") is False, "confirmed_transcript")
    require(semantic.get("ok") is True and semantic.get("policy", {}).get("transcript_timing_authority") is False, "semantic_not_ok")
    require((confirmed.get("summary") or {}).get("repair_instances") == EXPECTED_REPAIR, "confirmed_repair_count")
    require((confirmed.get("summary") or {}).get("protected_v4") == EXPECTED_PROTECTED, "confirmed_protected_count")
    require((confirmed.get("summary") or {}).get("preserve_unresolved") == EXPECTED_UNRESOLVED, "confirmed_unresolved")
    require((confirmed.get("summary") or {}).get("remove_composite_structural") == EXPECTED_REMOVED_COMPOSITE, "confirmed_composite")
    require((confirmed.get("summary") or {}).get("expected_physical_textplus_count") == EXPECTED_PHYSICAL, "confirmed_physical")

    tokens = flatten_v4(v4)
    protected_map = {str(row.get("instance_id") or ""): str(row.get("target_name") or "") for row in confirmed.get("protected_v4") or []}
    v4_tokens = []
    for row in tokens:
        instance_id = str(row.get("visual_token_id") or "")
        target_name = protected_map.get(instance_id)
        if target_name:
            item = dict(row)
            item["target_name"] = target_name
            v4_tokens.append(item)
    require(len(v4_tokens) == EXPECTED_PROTECTED, f"v4_protected:{len(v4_tokens)}")

    text_updates = protected_text_reconciliation(semantic, v4_tokens)
    text_update_ids = {str(row.get("instance_id") or "") for row in text_updates}
    metric_tokens = [row for row in v4_tokens if str(row.get("visual_token_id") or "") not in text_update_ids]
    calibration = robust_family_calibration(metric_tokens)
    protected_updates = [row for token in metric_tokens if (row := protected_size_update(token)) is not None]
    require(len(protected_updates) + len(text_updates) == EXPECTED_PROTECTED, f"protected_evidence_partition:{len(protected_updates)}:{len(text_updates)}")

    repair_updates = []
    for repair in confirmed.get("repair_instances") or []:
        if isinstance(repair, Mapping):
            update = repair_size_update(repair, calibration)
            if update is not None:
                repair_updates.append(update)
    fade_evidence = protected_fade_evidence(v4_tokens)
    calibration_rows = [dict(value) for _, value in sorted(calibration.items())]

    document: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "primary_authority": "source_pixels_plus_measured_resolve_generated_glyphs",
            "transcript_timing_authority": False,
            "per_cue_hardcoded_overrides": False,
            "screenshot_specific_overrides": False,
            "position_mutation_authorized": False,
            "opacity_mutation_authorized": False,
            "fade_appearance_reassessment_deferred_until_baked_original_is_removed": True,
            "protected_composite_text_reconciliation_requires_semantic_coverage": True,
            "unresolved_rows_mutated": False,
            "resolve_modified": False,
            "runtime_authorized": False,
        },
        "inputs": {
            "confirmed74_authority": {"path": str(CONFIRMED), "sha256": sha256(confirmed_path), "semantic_sha256": confirmed.get("semantic_sha256")},
            "protected_v4_authority": {"path": str(V4), "sha256": sha256(v4_path), "semantic_sha256": v4.get("semantic_sha256")},
            "semantic_coverage": {"path": str(SEMANTIC), "sha256": sha256(semantic_path), "semantic_sha256": semantic.get("semantic_sha256")},
        },
        "font_render_calibration": calibration_rows,
        "protected_size_updates": sorted(protected_updates, key=lambda row: row["target_name"]),
        "repair_size_updates": sorted(repair_updates, key=lambda row: row["target_name"]),
        "protected_text_updates": sorted(text_updates, key=lambda row: row["target_name"]),
        "protected_fade_evidence": sorted(fade_evidence, key=lambda row: row["target_name"]),
        "summary": {
            "confirmed74_repair_instances": EXPECTED_REPAIR,
            "protected_v4_instances": EXPECTED_PROTECTED,
            "unresolved_preserved": EXPECTED_UNRESOLVED,
            "composite_structural_removed": EXPECTED_REMOVED_COMPOSITE,
            "expected_physical_textplus_count": EXPECTED_PHYSICAL,
            "protected_size_updates": len(protected_updates),
            "repair_size_updates": len(repair_updates),
            "protected_text_updates": len(text_updates),
            "font_calibration_profiles": len(calibration_rows),
            "protected_nontrivial_opacity_rows": len(fade_evidence),
            "position_updates": 0,
            "opacity_updates": 0,
            "resolve_modified": False,
            "runtime_authorized": False,
        },
        "semantic_sha256": "",
        "next_boundary": "STEP_3E_POST_VISUAL_METRICS_POLISH_RUNTIME_AFTER_AUTHORITY_VALIDATION",
    }
    validation = validate_document(document)
    require(validation["ok"], "document:" + ",".join(key for key, ok in validation["checks"].items() if not ok))
    document["semantic_sha256"] = canonical_sha256({key: value for key, value in document.items() if key != "semantic_sha256"})
    write_json(output, document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / OUTPUT
    try:
        doc = build(root, output)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "path": str(output), "semantic_sha256": doc["semantic_sha256"], "summary": doc["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
