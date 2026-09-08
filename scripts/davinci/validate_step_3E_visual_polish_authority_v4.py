#!/usr/bin/env python3
"""Validate the offline Step 3E temporal re-detection and V4 authority lock."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3E_TEMPORAL_VISUAL_AUTHORITY_V4"
AUTHORITY = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
MEASUREMENTS = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_temporal_redetection_v4.json"
BUILDER = "scripts/davinci/build_step_3E_visual_polish_authority_v4.py"
EXPECTED_TOKENS = 17
EXPECTED_GROUPS = 7
EXPECTED_FRAME_ROWS = 397


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_builder(root: Path):
    path = root / BUILDER
    spec = importlib.util.spec_from_file_location("step3e_v4_builder_for_validation", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    authority = load_json(root / AUTHORITY)
    measurements = load_json(root / MEASUREMENTS)
    builder = load_builder(root)
    rebuilt = builder.build_authority(root)

    tokens = [token for group in authority.get("groups", []) for token in group.get("tokens", [])]
    by_id = {row["visual_token_id"]: row for row in tokens}
    measured = {row["visual_token_id"]: row for row in measurements.get("tokens", [])}
    evidence_hashes_ok = True
    evidence_results: Dict[str, bool] = {}
    for name, row in measurements.get("evidence", {}).items():
        path = row.get("path") if isinstance(row, dict) else None
        expected = row.get("sha256") if isinstance(row, dict) else None
        if not path or not expected:
            continue
        actual_path = root / str(path)
        ok = actual_path.is_file() and raw_sha256(actual_path) == expected
        evidence_results[name] = ok
        evidence_hashes_ok = evidence_hashes_ok and ok

    frame_coverage_ok = True
    for token in tokens:
        start, end = token["visual_window"]
        frames = [int(row["timeline_frame"]) for row in token["frame_path"]]
        if frames != list(range(int(start), int(end))):
            frame_coverage_ok = False
            break
        if any(len(row.get("position_top_origin", [])) != 2 or len(row.get("position_fusion", [])) != 2 for row in token["frame_path"]):
            frame_coverage_ok = False
            break

    g02_primary = by_id.get("vf_02_already", {})
    g02_script = by_id.get("vf_02_decorative_glyph", {})
    primary_positions = [row["position_top_origin"] for row in g02_primary.get("frame_path", [])]
    script_positions = [row["position_top_origin"] for row in g02_script.get("frame_path", [])]
    g02_x_static = bool(primary_positions and script_positions) and max(abs(row[0] - primary_positions[-1][0]) for row in primary_positions) <= 1e-9 and max(abs(row[0] - script_positions[-1][0]) for row in script_positions) <= 1e-9
    g02_hold = bool(primary_positions and script_positions) and all(row == primary_positions[-1] for row in primary_positions[10:]) and all(row == script_positions[-1] for row in script_positions[10:])

    semantic = authority.get("semantic_sha256")
    without_semantic = dict(authority)
    without_semantic.pop("semantic_sha256", None)
    semantic_ok = semantic == builder.canonical_sha256(without_semantic)

    checks = {
        "authority_identity": authority.get("task_id") == TASK_ID and authority.get("ok") is True,
        "measurement_identity": measurements.get("task_id") == TASK_ID and measurements.get("ok") is True,
        "deterministic_rebuild": rebuilt == authority,
        "semantic_sha256": semantic_ok,
        "evidence_hashes": evidence_hashes_ok and len(evidence_results) >= 5,
        "group_count": authority.get("summary", {}).get("group_count") == EXPECTED_GROUPS,
        "token_count": authority.get("summary", {}).get("visual_token_count") == EXPECTED_TOKENS and len(by_id) == EXPECTED_TOKENS and len(measured) == EXPECTED_TOKENS,
        "explicit_frame_rows": authority.get("summary", {}).get("explicit_frame_row_count") == EXPECTED_FRAME_ROWS and sum(len(row["frame_path"]) for row in tokens) == EXPECTED_FRAME_ROWS,
        "frame_coverage": frame_coverage_ok,
        "source_pixel_anchors": all(row.get("source_pixel_anchor", {}).get("source_bbox_px_540x960") for row in tokens),
        "generated_pixel_anchors": all(row.get("source_pixel_anchor", {}).get("generated_bbox_px_540x960") for row in tokens),
        "transcript_not_timing_authority": authority.get("authority_policy", {}).get("transcript_timing_authority") is False and all(row.get("transcript_timing_promoted_to_authority") is False for row in tokens),
        "resolve_unmodified": authority.get("authority_policy", {}).get("resolve_modified") is False and authority.get("summary", {}).get("resolve_modified") is False,
        "full_rollout_not_authorized": authority.get("authority_policy", {}).get("full_rollout_authorized") is False and authority.get("next_boundary", {}).get("remaining_100_rollout_allowed") is False,
        "next_boundary_is_3E3": authority.get("next_boundary", {}).get("full_baseline_polish_patch_allowed") is True and authority.get("next_boundary", {}).get("scope") == "17_visual_first_tokens_only",
        "group02_visual_window_extended_to_cut": g02_primary.get("visual_window") == [245, 270] and g02_script.get("visual_window") == [245, 270],
        "group02_vertical_only": g02_x_static and g02_primary.get("motion_summary", {}).get("axis") == "vertical" and g02_script.get("motion_summary", {}).get("axis") == "vertical",
        "group02_hold_to_cut": g02_hold and g02_primary.get("frame_path", [])[-1]["timeline_frame"] == 269 and g02_script.get("frame_path", [])[-1]["timeline_frame"] == 269,
        "group02_fonts": (g02_primary.get("font", {}).get("font_family"), g02_primary.get("font", {}).get("font_style")) == ("Verdana", "Bold") and (g02_script.get("font", {}).get("font_family"), g02_script.get("font", {}).get("font_style")) == ("Segoe Script", "Regular"),
        "group02_sizes": abs(float(g02_primary.get("application_base_size_candidate", 0.0)) - 0.158) < 1e-12 and abs(float(g02_script.get("application_base_size_candidate", 0.0)) - 0.162) < 1e-12,
        "group04_source_reanchored": by_id.get("vf_04_that", {}).get("source_pixel_anchor", {}).get("source_bbox_center_normalized_top_origin") == [0.323148, 0.270833] and by_id.get("vf_04_knows", {}).get("source_pixel_anchor", {}).get("source_bbox_center_normalized_top_origin") == [0.472222, 0.326042],
        "group05_source_reanchored": by_id.get("vf_05_know", {}).get("source_pixel_anchor", {}).get("source_bbox_center_normalized_top_origin") == [0.440741, 0.360417],
    }
    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "checks": checks,
        "evidence_hash_checks": evidence_results,
        "counts": {"groups": len(authority.get("groups", [])), "tokens": len(tokens), "explicit_frame_rows": sum(len(row["frame_path"]) for row in tokens)},
        "semantic_sha256": semantic,
        "resolve_modified": False,
        "full_rollout_authorized": False,
        "next_boundary": authority.get("next_boundary"),
        "ok": all(checks.values()),
    }
    if not result["ok"]:
        raise ValueError("validation_failed:" + ",".join(name for name, ok in checks.items() if not ok))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        result = validate(args.root)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
