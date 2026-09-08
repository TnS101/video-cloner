#!/usr/bin/env python3
"""Build the Step 3E V4 visual authority without modifying Resolve."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3E_TEMPORAL_VISUAL_AUTHORITY_V4"
VIDEO_ID = "DZsqH7auhjt"
V3 = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3/visual_authority_script_renderability_v3.json"
PILOT_PLAN = ".agent/reports/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_RESOLVE_PILOT_V1/20260810T011342949336Z_f12b698b68724d27abf91e56be55988f/authority_plan.json"
MEASUREMENTS = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_temporal_redetection_v4.json"
G02_MOTION = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_vertical_motion_v1.json"
G02_FONT = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_font_metrics_v1.json"
OUTPUT = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
EXPECTED_GROUPS = 7
EXPECTED_TOKENS = 17
G02_IDS = {"vf_02_already", "vf_02_decorative_glyph"}


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def round_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [round_value(item) for item in value]
    return round(float(value), 6)


def interpolate(rows: Sequence[Mapping[str, Any]], frame: int, value_key: str = "value") -> Any:
    points: List[Tuple[int, Any]] = sorted((int(row["timeline_frame"]), row[value_key]) for row in rows)
    if not points:
        raise ValueError("empty_path")
    if frame <= points[0][0]:
        return round_value(points[0][1])
    if frame >= points[-1][0]:
        return round_value(points[-1][1])
    for (f0, v0), (f1, v1) in zip(points, points[1:]):
        if f0 <= frame <= f1:
            alpha = (frame - f0) / float(f1 - f0)
            if isinstance(v0, (list, tuple)):
                return [round(float(a) + (float(b) - float(a)) * alpha, 6) for a, b in zip(v0, v1)]
            return round(float(v0) + (float(v1) - float(v0)) * alpha, 6)
    raise AssertionError("unreachable")


def shifted_position_rows(rows: Sequence[Mapping[str, Any]], shift: Sequence[float]) -> List[Dict[str, Any]]:
    result = []
    for row in rows:
        value = row["value"]
        result.append({
            "timeline_frame": int(row["timeline_frame"]),
            "value": [round(float(value[0]) + float(shift[0]), 6), round(float(value[1]) + float(shift[1]), 6)],
        })
    return result


def motion_axis(first: Sequence[float], last: Sequence[float]) -> Dict[str, Any]:
    dx = round(float(last[0]) - float(first[0]), 6)
    dy = round(float(last[1]) - float(first[1]), 6)
    ax, ay = abs(dx), abs(dy)
    if max(ax, ay) < 0.002:
        axis, direction = "static", "none"
    elif ay > ax * 1.5:
        axis, direction = "vertical", "down" if dy > 0 else "up"
    elif ax > ay * 1.5:
        axis, direction = "horizontal", "right" if dx > 0 else "left"
    else:
        axis = "mixed"
        direction = ("right" if dx > 0 else "left") + "+" + ("down" if dy > 0 else "up")
    return {"axis": axis, "direction_top_origin": direction, "delta_normalized": [dx, dy]}


def token_maps(v3: Mapping[str, Any], pilot: Mapping[str, Any], measurements: Mapping[str, Any], g02_font: Mapping[str, Any]):
    v3_tokens = {token["visual_token_id"]: (group, token) for group in v3["groups"] for token in group["tokens"]}
    pilot_tokens = {row["visual_token_id"]: row for row in pilot["instances"]}
    measured = {row["visual_token_id"]: row for row in measurements["tokens"]}
    g02 = {row["visual_token_id"]: row for row in g02_font["plans"]}
    expected = set(v3_tokens)
    if len(expected) != EXPECTED_TOKENS or set(pilot_tokens) != expected or set(measured) != expected or set(g02) != G02_IDS:
        raise ValueError("token_inventory")
    return v3_tokens, pilot_tokens, measured, g02


def build_token(v3_token: Mapping[str, Any], pilot_row: Mapping[str, Any], measurement: Mapping[str, Any], g02_row: Mapping[str, Any] | None) -> Dict[str, Any]:
    token_id = str(v3_token["visual_token_id"])
    if g02_row is not None:
        visual_window = [int(x) for x in g02_row["visual_window"]]
        position_rows = [
            {"timeline_frame": int(row["timeline_frame"]), "value": round_value(row["source_top_origin_value"])}
            for row in g02_row["position_keys"]
        ]
        size_rows = [{"timeline_frame": int(row["timeline_frame"]), "value": float(row["scale"])} for row in g02_row["size_keys"]]
        opacity_rows = [{"timeline_frame": int(row["timeline_frame"]), "value": float(row["factor"])} for row in g02_row["opacity_keys"]]
        base_size = float(g02_row["base_size"])
        font = dict(g02_row["font"])
        style_lock = dict(g02_row["style_lock"])
        phases = dict(g02_row["animation_phases"])
        position_basis = "accepted_group02_source_pixel_motion_contract"
        metrics_status = "accepted_group02_font_metrics_pilot"
    else:
        visual_window = [int(x) for x in v3_token["visual_window"]]
        shift = measurement["v4_center_shift_from_v3_normalized"]
        position_rows = shifted_position_rows(v3_token["position_path"], shift)
        size_rows = [{"timeline_frame": int(row["timeline_frame"]), "value": float(row["value"])} for row in v3_token["size_path"]]
        opacity_rows = [{"timeline_frame": int(row["timeline_frame"]), "value": float(row["value"])} for row in v3_token["opacity_path"]]
        base_size = float(pilot_row["base_size"])
        font = dict(pilot_row["font"])
        style_lock = dict(v3_token["style_lock"])
        phases = dict(v3_token["animation_phases"])
        position_basis = "v3_source_reviewed_motion_shifted_to_v4_source_pixel_anchor"
        metrics_status = "source_pixel_bbox_locked_application_size_pending_3E3"

    start, end = visual_window
    if end <= start:
        raise ValueError(f"visual_window:{token_id}")
    frame_path = []
    for frame in range(start, end):
        top = interpolate(position_rows, frame)
        scale = float(interpolate(size_rows, frame))
        opacity = float(interpolate(opacity_rows, frame))
        frame_path.append({
            "timeline_frame": frame,
            "position_top_origin": top,
            "position_fusion": [round(float(top[0]), 6), round(1.0 - float(top[1]), 6)],
            "size_scale": round(scale, 6),
            "application_size_candidate": round(base_size * scale, 12),
            "opacity_factor": round(opacity, 6),
        })

    entrance = phases.get("entrance_window") if isinstance(phases.get("entrance_window"), list) else [start, start]
    entrance_start = max(start, int(entrance[0]))
    entrance_end = min(end - 1, int(entrance[1]))
    first = next(row["position_top_origin"] for row in frame_path if row["timeline_frame"] == entrance_start)
    last = next(row["position_top_origin"] for row in frame_path if row["timeline_frame"] == entrance_end)
    motion = motion_axis(first, last)
    motion.update({
        "entrance_window": [int(x) for x in entrance],
        "hold_window": [int(x) for x in phases.get("hold_window", [])],
        "exit_window": [int(x) for x in phases.get("exit_window", [])],
        "classification": str(phases.get("classification") or ""),
        "horizontal_motion_allowed": phases.get("horizontal_motion_allowed"),
        "exit_motion_allowed": phases.get("exit_motion_allowed"),
    })

    return {
        "visual_token_id": token_id,
        "display_text": str(v3_token["display_text"]),
        "role": str(v3_token.get("role") or ""),
        "visual_kind": str(v3_token.get("visual_kind") or "text"),
        "z_order": int(v3_token.get("z_order") or 0),
        "source_cue_id": pilot_row.get("source_cue_id"),
        "text_authority": str(v3_token.get("text_authority") or "source_video_pixels"),
        "transcript_timing_promoted_to_authority": False,
        "visual_window": visual_window,
        "position_basis": position_basis,
        "application_base_size_candidate": round(base_size, 12),
        "font": font,
        "font_metrics_status": metrics_status,
        "style_lock": style_lock,
        "source_pixel_anchor": {
            key: measurement[key]
            for key in (
                "reference_frame", "source_bbox_px_540x960", "generated_bbox_px_540x960",
                "source_bbox_center_normalized_top_origin", "source_width_px", "source_height_px",
                "generated_width_px", "generated_height_px", "width_ratio_source_over_generated",
                "height_ratio_source_over_generated", "v4_center_shift_from_v3_normalized",
            )
        },
        "animation_phases": phases,
        "motion_summary": motion,
        "frame_path": frame_path,
    }


def build_authority(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    v3 = load_json(root / V3)
    pilot = load_json(root / PILOT_PLAN)
    measurements = load_json(root / MEASUREMENTS)
    g02_motion = load_json(root / G02_MOTION)
    g02_font = load_json(root / G02_FONT)

    if v3.get("ok") is not True or measurements.get("ok") is not True or pilot.get("ok") is not True:
        raise ValueError("input_not_ok")
    if measurements.get("task_id") != TASK_ID or measurements.get("policy", {}).get("transcript_timing_authority") is not False:
        raise ValueError("measurement_identity")
    if g02_motion.get("ok") is not True or g02_font.get("ok") is not True:
        raise ValueError("group02_contract")
    if g02_font.get("source_motion_contract") != G02_MOTION:
        raise ValueError("group02_contract_chain")

    v3_tokens, pilot_tokens, measured, g02 = token_maps(v3, pilot, measurements, g02_font)
    groups = []
    total_frame_rows = 0
    for source_group in v3["groups"]:
        group_id = str(source_group["group_id"])
        tokens = []
        for source_token in sorted(source_group["tokens"], key=lambda row: (int(row.get("z_order") or 0), str(row["visual_token_id"]))):
            token_id = str(source_token["visual_token_id"])
            row = build_token(source_token, pilot_tokens[token_id], measured[token_id], g02.get(token_id))
            tokens.append(row)
            total_frame_rows += len(row["frame_path"])
        windows = [row["visual_window"] for row in tokens]
        groups.append({
            "group_id": group_id,
            "label": str(source_group.get("label") or ""),
            "composition_type": str(source_group.get("composition_type") or ""),
            "group_window": [min(row[0] for row in windows), max(row[1] for row in windows)],
            "assembly_order": [str(value) for value in source_group.get("assembly_order", [])],
            "tokens": tokens,
        })

    document: Dict[str, Any] = {
        "schema": "video_cloner_visual_polish_authority_v4",
        "schema_version": 1,
        "task_id": TASK_ID,
        "video_id": VIDEO_ID,
        "inputs": {
            "v3_authority": V3,
            "pilot_authority_plan": PILOT_PLAN,
            "temporal_redetection_measurements": MEASUREMENTS,
            "group02_motion_contract": G02_MOTION,
            "group02_font_metrics_contract": G02_FONT,
        },
        "authority_policy": {
            "primary_authority": "source_video_pixels",
            "transcript_timing_authority": False,
            "transcript_use": "canonical_text_alias_only",
            "explicit_frame_paths_required": True,
            "resolve_modified": False,
            "full_rollout_authorized": False,
            "visual_approval_required_before_remaining_100": True,
        },
        "groups": groups,
        "summary": {
            "group_count": len(groups),
            "visual_token_count": sum(len(group["tokens"]) for group in groups),
            "explicit_frame_row_count": total_frame_rows,
            "source_pixel_anchor_count": len(measured),
            "group02_corrected_token_count": len(G02_IDS),
            "transcript_timing_promoted_count": 0,
            "resolve_modified": False,
            "full_rollout_authorized": False,
        },
        "next_boundary": {
            "step": "3E.3_full_baseline_polish_patch",
            "full_baseline_polish_patch_allowed": True,
            "scope": "17_visual_first_tokens_only",
            "protected_source_timeline_must_remain_immutable": True,
            "remaining_100_rollout_allowed": False,
            "visual_acceptance_required_after_patch": True,
        },
        "ok": True,
    }
    document["semantic_sha256"] = canonical_sha256(document)
    if document["summary"]["group_count"] != EXPECTED_GROUPS or document["summary"]["visual_token_count"] != EXPECTED_TOKENS:
        raise ValueError("summary_counts")
    return document


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        built = build_authority(args.root)
        output = args.root.resolve() / OUTPUT
        if args.check:
            if not output.is_file() or load_json(output) != built:
                raise ValueError("authority_out_of_date")
        else:
            write_json(output, built)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "task_id": TASK_ID, "output": OUTPUT, "semantic_sha256": built["semantic_sha256"], "summary": built["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
