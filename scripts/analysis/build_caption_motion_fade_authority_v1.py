#!/usr/bin/env python3
"""Build the bounded caption motion/fade authority for the accepted V4 timeline.

Only two source-backed authority families are promoted:
1. Center trajectories from the later Visual Fidelity V2 source-pixel review,
   and only for repair rows classified dynamic plus protected rows classified
   as real exits.
2. Opacity factors for the 17 protected visual-first captions from the accepted
   V4 source-pixel authority.

Detector/template confidence never becomes opacity. Size, static style, text,
clip lifecycle, tracks and occlusion are outside this authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_CAPTION_MOTION_FADE_APPLICATION_V1"
SOURCE_TIMELINE = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4"
VF = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json")
VF_NORMALIZED_SHA256 = "6f7cdf265dcb18611e7f6326d7d12de7a3dade7b2a7b6d33e1d406d5645ca6f5"
V4 = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json")
PROTECTED = Path(
    ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/"
    "20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json"
)
B33 = Path(
    "artifacts/DZSQH7AUHJT_STEP_3B3_OUTLINE_SHADOW_AUTHORITY_RECONCILIATION_V2/"
    "effective_authority_validation.json"
)
V4_REPORT = Path(
    ".agent/reports/DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4/"
    "20260812T174800495896Z_07d0e09144764182a5c4b1ec41ca6952/report.json"
)
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_CAPTION_MOTION_FADE_APPLICATION_V1/caption_motion_fade_authority_v1.json")

EXPECTED_PHYSICAL = 114
EXPECTED_REPAIR = 74
EXPECTED_PROTECTED = 17
EXPECTED_DYNAMIC_REPAIR = 4
EXPECTED_PROTECTED_EXITS = 3
EXPECTED_TOTAL_EXITS = 4


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def protected_map(persistent: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = persistent.get("rows")
    require(persistent.get("ok") is True and isinstance(rows, list) and len(rows) == EXPECTED_PROTECTED, "protected_persistent")
    result: Dict[str, Dict[str, Any]] = {}
    for raw in rows:
        require(isinstance(raw, Mapping), "protected_row")
        token = str(raw.get("visual_token_id") or "")
        name = str(raw.get("target_name") or "")
        summary = raw.get("summary") if isinstance(raw.get("summary"), Mapping) else {}
        start = int(summary.get("start") or -1)
        end = int(summary.get("end") or -1)
        require(token and name and start >= 0 and end > start, f"protected_identity:{token}")
        require(token not in result, f"protected_duplicate:{token}")
        result[token] = {"target_name": name, "range": [start, end]}
    return result


def build(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    paths = [VF, V4, PROTECTED, B33, V4_REPORT]
    for relative in paths:
        require((root / relative).is_file(), f"missing:{relative}")
    require(normalized_sha256(root / VF) == VF_NORMALIZED_SHA256, "vf_hash")

    vf = load_json(root / VF)
    v4 = load_json(root / V4)
    persistent = load_json(root / PROTECTED)
    b33 = load_json(root / B33)
    v4_report = load_json(root / V4_REPORT)

    vf_summary = vf.get("summary") if isinstance(vf.get("summary"), Mapping) else {}
    vf_policy = vf.get("policy") if isinstance(vf.get("policy"), Mapping) else {}
    require(vf.get("ok") is True, "vf_not_ok")
    require(vf_summary.get("physical_textplus") == EXPECTED_PHYSICAL, "vf_physical")
    require(vf_summary.get("repair_instances") == EXPECTED_REPAIR, "vf_repair")
    require(vf_summary.get("protected_instances") == EXPECTED_PROTECTED, "vf_protected")
    require(vf_summary.get("dynamic_position_instances") == EXPECTED_DYNAMIC_REPAIR, "vf_dynamic")
    require(vf_summary.get("detected_exit_motion_instances") == EXPECTED_TOTAL_EXITS, "vf_exit_total")
    require(vf_policy.get("detector_score_controls_opacity") is False, "vf_detector_alpha")
    require(vf_policy.get("transcript_timing_authority") is False, "vf_transcript")
    require(vf_policy.get("static_motion_is_default") is True, "vf_static_default")

    require(v4.get("ok") is True, "v4_authority")
    v4_summary = v4.get("summary") if isinstance(v4.get("summary"), Mapping) else {}
    require(v4_summary.get("visual_token_count") == EXPECTED_PROTECTED, "v4_token_count")
    require(v4_summary.get("explicit_frame_row_count") == 397, "v4_frame_rows")

    decision = b33.get("decision") if isinstance(b33.get("decision"), Mapping) else {}
    require(b33.get("ok") is True and b33.get("textplus_count") == EXPECTED_PHYSICAL, "b33")
    require(decision.get("accepted_timeline_remains") == SOURCE_TIMELINE, "b33_timeline")
    require(decision.get("step_3B3_status") == "complete_no_mutation_required", "b33_status")

    require(v4_report.get("ok") is True, "v4_report")
    require(v4_report.get("target_timeline_name") == SOURCE_TIMELINE, "v4_report_timeline")
    require(v4_report.get("final_textplus_count") == EXPECTED_PHYSICAL, "v4_report_count")
    require(v4_report.get("caption_mutation_count") == 0, "v4_report_caption_mutation")
    require(v4_report.get("persistent_readback_ok") is True and v4_report.get("idempotency_ok") is True, "v4_report_contract")

    pmap = protected_map(persistent)

    repair_center = []
    repair_exit_count = 0
    repair_rows = vf.get("repair_instances")
    require(isinstance(repair_rows, list) and len(repair_rows) == EXPECTED_REPAIR, "repair_rows")
    for raw in repair_rows:
        require(isinstance(raw, Mapping), "repair_row")
        motion = raw.get("motion") if isinstance(raw.get("motion"), Mapping) else {}
        if motion.get("position_model") == "source_static_hold":
            continue
        path = raw.get("frame_path")
        require(isinstance(path, list) and path, f"repair_path:{raw.get('instance_id')}")
        keys = []
        for frame in path:
            require(isinstance(frame, Mapping), "repair_frame")
            value = frame.get("position_fusion")
            require(isinstance(value, list) and len(value) == 2, "repair_position")
            keys.append({"timeline_frame": int(frame["timeline_frame"]), "value": [float(value[0]), float(value[1])]})
        repair_center.append({
            "authority_kind": "visual_fidelity_v2_repair_dynamic_center",
            "instance_id": str(raw.get("instance_id") or ""),
            "target_name": str(raw.get("target_name") or ""),
            "source_detected_range": [keys[0]["timeline_frame"], keys[-1]["timeline_frame"] + 1],
            "position_model": str(motion.get("position_model") or ""),
            "exit_motion": bool(motion.get("exit_motion")),
            "exit_axis": motion.get("exit_axis"),
            "exit_direction_top_origin": motion.get("exit_direction_top_origin"),
            "position_keys": keys,
        })
        repair_exit_count += int(bool(motion.get("exit_motion")))
    require(len(repair_center) == EXPECTED_DYNAMIC_REPAIR, f"repair_center_count:{len(repair_center)}")

    protected_exit = []
    protected_motion = vf.get("protected_motion_review")
    require(isinstance(protected_motion, list) and len(protected_motion) == EXPECTED_PROTECTED, "protected_motion")
    for raw in protected_motion:
        require(isinstance(raw, Mapping), "protected_motion_row")
        motion = raw.get("motion") if isinstance(raw.get("motion"), Mapping) else {}
        if not motion.get("exit_motion"):
            continue
        token = str(raw.get("instance_id") or "")
        mapped = pmap.get(token)
        require(mapped is not None, f"protected_map:{token}")
        start, end = mapped["range"]
        path = []
        for frame in raw.get("frame_path") or []:
            timeline_frame = int(frame.get("timeline_frame") or -1)
            if not start <= timeline_frame < end:
                continue
            value = frame.get("position_fusion")
            require(isinstance(value, list) and len(value) == 2, f"protected_position:{token}:{timeline_frame}")
            path.append({"timeline_frame": timeline_frame, "value": [float(value[0]), float(value[1])]})
        require(path, f"protected_exit_path:{token}")
        protected_exit.append({
            "authority_kind": "visual_fidelity_v2_protected_real_exit_center",
            "visual_token_id": token,
            "target_name": mapped["target_name"],
            "target_range": [start, end],
            "source_detected_range": [int((raw.get("frame_path") or [])[0]["timeline_frame"]), int((raw.get("frame_path") or [])[-1]["timeline_frame"]) + 1],
            "position_model": str(motion.get("position_model") or ""),
            "exit_axis": motion.get("exit_axis"),
            "exit_direction_top_origin": motion.get("exit_direction_top_origin"),
            "position_keys": path,
        })
    require(len(protected_exit) == EXPECTED_PROTECTED_EXITS, f"protected_exit_count:{len(protected_exit)}")
    require(repair_exit_count + len(protected_exit) == EXPECTED_TOTAL_EXITS, "exit_partition")

    v4_tokens: Dict[str, Mapping[str, Any]] = {}
    for group in v4.get("groups") or []:
        require(isinstance(group, Mapping), "v4_group")
        for token in group.get("tokens") or []:
            require(isinstance(token, Mapping), "v4_token")
            token_id = str(token.get("visual_token_id") or "")
            require(token_id and token_id not in v4_tokens, f"v4_token_id:{token_id}")
            v4_tokens[token_id] = token
    require(set(v4_tokens) == set(pmap), "protected_token_set")

    protected_opacity = []
    explicit_opacity_rows = 0
    for token_id in sorted(v4_tokens, key=lambda key: pmap[key]["target_name"]):
        token = v4_tokens[token_id]
        mapped = pmap[token_id]
        start, end = mapped["range"]
        require(list(token.get("visual_window") or []) == [start, end], f"v4_window:{token_id}")
        frame_path = token.get("frame_path")
        require(isinstance(frame_path, list) and len(frame_path) == end - start, f"v4_dense:{token_id}")
        factors = []
        for expected_frame, raw in zip(range(start, end), frame_path):
            require(int(raw.get("timeline_frame") or -1) == expected_frame, f"v4_frame:{token_id}:{expected_frame}")
            factor = float(raw.get("opacity_factor"))
            require(0.0 <= factor <= 1.0, f"v4_opacity:{token_id}:{expected_frame}")
            factors.append({"timeline_frame": expected_frame, "factor": factor})
        explicit_opacity_rows += len(factors)
        protected_opacity.append({
            "authority_kind": "accepted_v4_source_pixel_opacity_factor",
            "visual_token_id": token_id,
            "target_name": mapped["target_name"],
            "target_range": [start, end],
            "opacity_factors": factors,
        })
    require(len(protected_opacity) == EXPECTED_PROTECTED, "protected_opacity_count")
    require(explicit_opacity_rows == 397, f"opacity_rows:{explicit_opacity_rows}")

    center_names = [row["target_name"] for row in repair_center + protected_exit]
    opacity_names = [row["target_name"] for row in protected_opacity]
    require(all(center_names) and len(center_names) == len(set(center_names)), "center_target_duplicates")
    require(all(opacity_names) and len(opacity_names) == len(set(opacity_names)), "opacity_target_duplicates")

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "accepted_source_timeline": SOURCE_TIMELINE,
        "policy": {
            "monotonic_non_regression": True,
            "source_pixel_authority_only": True,
            "detector_score_controls_opacity": False,
            "transcript_timing_authority": False,
            "static_motion_is_default": True,
            "caption_recreation_authorized": False,
            "size_mutation_authorized": False,
            "style_mutation_authorized": False,
            "timing_or_track_mutation_authorized": False,
            "occlusion_mutation_authorized": False,
            "center_mutation_scope": "four_dynamic_repair_tracks_plus_three_protected_real_exits_only",
            "opacity_mutation_scope": "seventeen_accepted_v4_source_pixel_factor_tracks_only",
            "repair_caption_opacity_mutation_authorized": False,
            "visual_approval_required": True,
            "further_rollout_authorized": False,
        },
        "inputs": {str(path): {"normalized_sha256": normalized_sha256(root / path)} for path in paths},
        "repair_center_updates": repair_center,
        "protected_exit_center_updates": protected_exit,
        "protected_opacity_updates": protected_opacity,
        "summary": {
            "physical_textplus": EXPECTED_PHYSICAL,
            "repair_center_target_count": len(repair_center),
            "protected_exit_center_target_count": len(protected_exit),
            "unique_center_target_count": len(center_names),
            "protected_opacity_target_count": len(protected_opacity),
            "explicit_opacity_frame_rows": explicit_opacity_rows,
            "repair_exit_count": repair_exit_count,
            "protected_exit_count": len(protected_exit),
            "total_source_detected_exit_count": repair_exit_count + len(protected_exit),
        },
        "next_boundary": "ISOLATED_RESOLVE_MOTION_FADE_APPLICATION_WITH_FROZEN_NON_TARGET_PROPERTIES",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = build(args.root)
        output = args.output if args.output.is_absolute() else args.root / args.output
        write_json(output, result)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "output": str(output), "summary": result["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
