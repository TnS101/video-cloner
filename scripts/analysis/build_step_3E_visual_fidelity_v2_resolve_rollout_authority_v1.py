#!/usr/bin/env python3
"""Build the final Step 3E Visual Fidelity V2 Resolve rollout authority.

Consumes only accepted offline authorities. It merges the safe Visual Fidelity V2
repair subset, positive unresolved-row recoveries, one accepted visual companion,
explicit residual preservation, sparse-short-anchor quarantine, protected source
exit trajectories, and the validated foreground RGBA occlusion contract.

No Resolve API is used here. Transcript timing is never authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1"
VF = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json")
VF_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_validation.json")
RECOVERY = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_v1.json")
RECOVERY_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_validation.json")
CLASSIFICATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_v1.json")
CLASSIFICATION_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_validation.json")
FINAL_AUDIT = Path("artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_v1.json")
FINAL_AUDIT_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_validation.json")
UNIVERSAL = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/universal_visual_repair_authority_v1.json")
FOREGROUND = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_foreground_assets.json")
FOREGROUND_VALIDATION = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_foreground_assets_validation.json")
MATTE_CONTRACT = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_matte_contract.json")
PROTECTED_PERSISTENT = Path(".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json")
FINAL_AUDIT_SOURCE_CONTRACTS = {
    Path("scripts/analysis/build_step_3E_final_unresolved9_visual_audit_v1.py"): "3d5ff1e3124dad95e260ac4e444fd464dcd27b4fcb13ba84b31b73ec2438b31e",
    Path("scripts/analysis/validate_step_3E_final_unresolved9_visual_audit_v1.py"): "3ac073b6b82bde0433a3d9393a71b6dae709323da5f9f5b34daac71f8dbc2864",
    Path("tests/test_step_3E_final_unresolved9_visual_audit_v1.py"): "b58326c978c5080dbef84b90d5a6c0d2d8afa16f3f25fdca8846dfbffea5b6ba",
}
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1/visual_fidelity_v2_resolve_rollout_authority_v1.json")

EXPECTED_HASHES = {
    VF: "6f7cdf265dcb18611e7f6326d7d12de7a3dade7b2a7b6d33e1d406d5645ca6f5",
    VF_VALIDATION: "4ec072bce20b2881403ec9468a3d1e7cacb4f26a2f1b1cc0483b0ce7670e7f1a",
    RECOVERY: "bb4fab45389dbb10d58970955c6194e3f4d8e7351d79f397074bfb15b2fb8e5d",
    RECOVERY_VALIDATION: "7339bf038feafce8eaefdf3702e1457e67a7fcbc034a34eddf7183b2f7a6b1c7",
    CLASSIFICATION: "b0d390a54e9a73c05059b2725a5ff28aeab1d7ff233d14376507cb82bba77a87",
    CLASSIFICATION_VALIDATION: "7e4bca4b115e5e82c0f0ae25e274843f0fa33a23b559865395ed40f78042ca14",
    UNIVERSAL: "5fda48532c96ad6452a3c194671dde82e67839b05f70ae45d38615255545b670",
    FOREGROUND: "7b54d72ce22746c60cfad5955aa82c577d246bf04aa0470e469b2afb04b35554",
    FOREGROUND_VALIDATION: "9b96fda7c428307100cabdca2718e9ab3b336c0e48a2fec2000a294d82f93d6c",
    MATTE_CONTRACT: "2d24522d99d7ba0fd9250cdd7d43b49cc59085f8df079615b81117c68ced6b6b",
}
EXPECTED_PROTECTED_PERSISTENT_SEMANTIC_SHA256 = "922edc3abe59b6c27ca3ff33541986e17c91b50127b4ce212a221b00c8fbb7b0"
EXPECTED_STRUCTURAL = 117
EXPECTED_SOURCE_PHYSICAL = 114
EXPECTED_V2_REPAIR = 74
EXPECTED_QUARANTINE = 1
EXPECTED_V2_RECREATE = 73
EXPECTED_CLASSIFIER_RECOVERED = 11
EXPECTED_FINAL_RECOVERED = 2
EXPECTED_SEMANTIC_RECREATE = 13
EXPECTED_VISUAL_COMPANION = 1
EXPECTED_PRESERVED = 9
EXPECTED_PROTECTED = 17
EXPECTED_PROTECTED_EXITS = 3
EXPECTED_COMPOSITE_ABSENT = 3
EXPECTED_TARGET_PHYSICAL = 113
REF_WIDTH = 1080.0
REF_HEIGHT = 1920.0

class BuildError(RuntimeError):
    pass

def require(condition: bool, code: str) -> None:
    if not condition:
        raise BuildError(code)


def protected_persistent_semantic_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable accepted-state portion of the historical persistent readback.

    `reacquire_calls` contains Resolve PyRemoteObject repr strings with process-local
    memory addresses. Those values are runtime diagnostics, not accepted visual state,
    and make a raw-file SHA brittle. Every other field remains in the semantic
    projection so protected Text+ identity, ranges, style/readback rows, save result,
    checks, task/run identity, and rollout locks stay byte-independent but exact.
    """
    return {str(key): value for key, value in payload.items() if str(key) != "reacquire_calls"}


def protected_persistent_semantic_sha256(payload: Mapping[str, Any]) -> str:
    return canonical_sha256(protected_persistent_semantic_projection(payload))

def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def normalized_text_sha256(path: Path) -> str:
    """Hash UTF-8 text independent of BOM and Windows/Unix line endings."""
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)

def target_map(universal: Mapping[str, Any]) -> dict[str, str]:
    result = {}
    for row in universal.get("instances") or []:
        if isinstance(row, Mapping):
            iid = str(row.get("instance_id") or "")
            name = str(row.get("target_name") or "")
            if iid and name:
                result[iid] = name
    require(len(result) == EXPECTED_STRUCTURAL, "universal_target_map")
    return result

def bbox_center_fusion(bbox: Sequence[float]) -> list[float]:
    require(len(bbox) == 4, "bbox")
    x0, y0, x1, y1 = [float(v) for v in bbox]
    require(x1 > x0 and y1 > y0, "bbox_geometry")
    return [round(((x0 + x1) * 0.5) / REF_WIDTH, 6), round(1.0 - (((y0 + y1) * 0.5) / REF_HEIGHT), 6)]

def dense_position_path(rows: Sequence[Mapping[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    by_frame = {int(row["timeline_frame"]): row for row in rows}
    require(sorted(by_frame) == list(range(start, end)), f"dense_tracking:{start}:{end}")
    centers = [bbox_center_fusion(by_frame[frame].get("source_bbox_ref") or by_frame[frame].get("bbox_ref") or []) for frame in range(start, end)]
    # Recovered sparse rows are source template tracks. Tiny bbox jitter is not animation.
    median_x = sorted(v[0] for v in centers)[len(centers)//2]
    median_y = sorted(v[1] for v in centers)[len(centers)//2]
    displacement = math.hypot((centers[-1][0]-centers[0][0])*REF_WIDTH, (centers[-1][1]-centers[0][1])*REF_HEIGHT) if len(centers) > 1 else 0.0
    static = displacement < 10.0
    result = []
    for index, frame in enumerate(range(start, end)):
        value = [round(median_x, 6), round(median_y, 6)] if static else centers[index]
        result.append({"timeline_frame": frame, "local_frame": frame-start, "value": value})
    return result

def v2_plan(row: Mapping[str, Any]) -> dict[str, Any]:
    window = [int(v) for v in row.get("visual_window") or []]
    require(len(window) == 2 and window[1] > window[0], f"v2_window:{row.get('instance_id')}")
    frame_path = [dict(v) for v in row.get("frame_path") or []]
    require([int(v["timeline_frame"]) for v in frame_path] == list(range(window[0], window[1])), f"v2_dense:{row.get('instance_id')}")
    motion = row.get("motion") or {}
    size = row.get("size") or {}
    fill = row.get("fill") or {}
    case = row.get("text_case") or {}
    return {
        "instance_id": str(row["instance_id"]),
        "target_name": str(row["target_name"]),
        "kind": "v2_repair",
        "canonical_text": str(row.get("canonical_text") or ""),
        "display_text": str(case.get("text") if case.get("apply") is True else row.get("canonical_text") or ""),
        "target_range": window,
        "position_keys": [{"timeline_frame": int(v["timeline_frame"]), "local_frame": int(v["timeline_frame"])-window[0], "value": [float(x) for x in v["position_fusion"]]} for v in frame_path],
        "size_action": "source_target" if size.get("apply") is True else "preserve_source_static",
        "target_size": float(size.get("target_size") or 0.0) if size.get("apply") is True else None,
        "fill_action": "source_override" if fill.get("apply") is True else "preserve_source_static",
        "fill_hex": str(fill.get("fill_hex") or "") if fill.get("apply") is True else None,
        "case_action": "source_override" if case.get("apply") is True else "preserve_source_static",
        "position_model": str(motion.get("position_model") or ""),
        "exit_motion": bool(motion.get("exit_motion")),
        "opacity_action": "hold_source_layer_opacity_fade_deferred",
    }

def recovered_plan(row: Mapping[str, Any], targets: Mapping[str, str], kind: str) -> dict[str, Any]:
    iid = str(row.get("instance_id") or "")
    target = targets.get(iid, "")
    require(iid and target, f"recovered_target:{iid}")
    window = [int(v) for v in row.get("visual_window") or []]
    tracking = row.get("source_pixel_tracking") or {}
    strong = [dict(v) for v in tracking.get("strong_run") or [] if isinstance(v, Mapping)]
    require(len(window) == 2 and window[1] > window[0], f"recovered_window:{iid}")
    require([int(v["timeline_frame"]) for v in strong] == list(range(window[0], window[1])), f"recovered_dense:{iid}")
    return {
        "instance_id": iid,
        "target_name": target,
        "kind": kind,
        "canonical_text": str(row.get("canonical_text") or ""),
        "display_text": str(row.get("canonical_text") or ""),
        "target_range": window,
        "position_keys": dense_position_path(strong, window[0], window[1]),
        "size_action": "preserve_source_static",
        "target_size": None,
        "fill_action": "preserve_source_static",
        "fill_hex": None,
        "case_action": "preserve_source_static",
        "position_model": "source_recovered_pixel_track",
        "exit_motion": False,
        "opacity_action": "hold_source_layer_opacity_fade_deferred",
    }

def companion_plan(row: Mapping[str, Any], targets: Mapping[str, str], global_model: Mapping[str, Any]) -> dict[str, Any]:
    iid = str(row.get("instance_id") or "")
    target = targets.get(iid, "")
    require(iid and target, "companion_target")
    window = [int(v) for v in row.get("visual_window") or []]
    path = [dict(v) for v in row.get("frame_path") or [] if isinstance(v, Mapping)]
    require([int(v["timeline_frame"]) for v in path] == list(range(window[0], window[1])), "companion_dense")
    heights = [float(v["bbox_ref"][3]) - float(v["bbox_ref"][1]) for v in path]
    hpps = float(global_model.get("height_px_per_size") or 0.0)
    require(hpps > 0 and heights, "companion_calibration")
    target_size = max(0.018, min(0.32, sorted(heights)[len(heights)//2] / hpps))
    style = row.get("style_lock") or {}
    font = row.get("font") or {}
    return {
        "instance_id": iid,
        "target_name": target,
        "kind": "visual_companion_recovered",
        "canonical_text": str(row.get("canonical_text") or ""),
        "display_text": str(row.get("display_text") or row.get("canonical_text") or ""),
        "target_range": window,
        "position_keys": dense_position_path(path, window[0], window[1]),
        "size_action": "source_target",
        "target_size": round(target_size, 12),
        "fill_action": "source_override",
        "fill_hex": str(style.get("fill") or style.get("fill_hex") or "#F6F3EF"),
        "case_action": "source_override",
        "font_override": {"font_family": str(font.get("font_family") or ""), "font_style": str(font.get("font_style") or "")},
        "style_lock": dict(style),
        "position_model": "source_visual_companion_track",
        "exit_motion": False,
        "opacity_action": "hold_source_layer_opacity_fade_deferred",
    }

def build(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    for rel, digest in EXPECTED_HASHES.items():
        require((root/rel).is_file() and sha256(root/rel) == digest, f"input_sha256:{rel}")
    for rel, digest in FINAL_AUDIT_SOURCE_CONTRACTS.items():
        require(
            (root/rel).is_file() and normalized_text_sha256(root/rel) == digest,
            f"input_normalized_text_sha256:{rel}",
        )
    require((root/PROTECTED_PERSISTENT).is_file(), "protected_persistent_missing")
    for rel in (FINAL_AUDIT, FINAL_AUDIT_VALIDATION):
        require((root/rel).is_file(), f"final_audit_missing:{rel}")

    vf = load_json(root/VF); vfv = load_json(root/VF_VALIDATION)
    recovery = load_json(root/RECOVERY); recoveryv = load_json(root/RECOVERY_VALIDATION)
    classification = load_json(root/CLASSIFICATION); classificationv = load_json(root/CLASSIFICATION_VALIDATION)
    audit = load_json(root/FINAL_AUDIT); auditv = load_json(root/FINAL_AUDIT_VALIDATION)
    universal = load_json(root/UNIVERSAL); foreground = load_json(root/FOREGROUND); foregroundv = load_json(root/FOREGROUND_VALIDATION); matte = load_json(root/MATTE_CONTRACT)
    persistent = load_json(root/PROTECTED_PERSISTENT)
    require(
        protected_persistent_semantic_sha256(persistent) == EXPECTED_PROTECTED_PERSISTENT_SEMANTIC_SHA256,
        "protected_persistent_semantic_sha256",
    )
    require(all(x.get("ok") is True for x in (vf, vfv, recovery, recoveryv, classification, classificationv, audit, auditv)), "accepted_inputs")
    require((auditv.get("summary") or {}) == (audit.get("summary") or {}), "audit_validation_summary")
    asum = audit.get("summary") or {}
    expected_audit = {"evaluated_residual":9, "recovered_semantic":2, "recovered_visual_companion":0, "represented_by_existing_visual_layer":0, "unresolved_after_full_visual_audit":7, "source_absent_claims":0, "sparse_short_anchor_quarantines":1}
    for key, value in expected_audit.items(): require(asum.get(key) == value, f"audit_summary:{key}")
    require((audit.get("policy") or {}).get("offline_recovery_stops_after_this_boundary") is True, "audit_stop_policy")
    require((audit.get("policy") or {}).get("transcript_timing_authority") is False, "audit_transcript")
    require((audit.get("policy") or {}).get("geometry_only_semantic_promotion") is False, "audit_geometry")
    require((vf.get("summary") or {}).get("repair_instances") == EXPECTED_V2_REPAIR, "vf_repair_count")
    require((vf.get("summary") or {}).get("protected_instances") == EXPECTED_PROTECTED, "vf_protected")
    require((vf.get("summary") or {}).get("physical_textplus") == EXPECTED_SOURCE_PHYSICAL, "vf_physical")
    require((vf.get("occlusion_contract") or {}).get("required_layer_order") == "foreground_rgba_above_textplus", "occlusion_policy")
    require(foreground.get("ok") is True and foregroundv.get("ok") is True and (foreground.get("summary") or {}).get("complete_asset_span_count") == 1, "foreground_input")
    require(matte.get("ok") is True and (matte.get("summary") or {}).get("complete_span_count") == 1, "matte_input")
    require(persistent.get("ok") is True and len(persistent.get("rows") or []) == EXPECTED_PROTECTED, "protected_persistent")

    targets = target_map(universal)
    quarantine = [dict(x) for x in audit.get("repair_authority_quarantine") or [] if isinstance(x, Mapping)]
    require(len(quarantine) == EXPECTED_QUARANTINE, "quarantine_count")
    qids = {str(x.get("instance_id") or "") for x in quarantine}
    v2_rows = [dict(x) for x in vf.get("repair_instances") or [] if isinstance(x, Mapping)]
    safe_v2 = [x for x in v2_rows if str(x.get("instance_id") or "") not in qids]
    require(len(safe_v2) == EXPECTED_V2_RECREATE, "safe_v2_count")
    v2_plans = [v2_plan(x) for x in safe_v2]

    class_recovered = [dict(x) for x in classification.get("classifications") or [] if isinstance(x, Mapping) and x.get("classification") == "source_semantic_track_recovered"]
    audit_recovered = [dict(x) for x in audit.get("audits") or [] if isinstance(x, Mapping) and x.get("classification") == "recovered_semantic"]
    require(len(class_recovered) == EXPECTED_CLASSIFIER_RECOVERED and len(audit_recovered) == EXPECTED_FINAL_RECOVERED, "semantic_recovery_counts")
    semantic_plans = [recovered_plan(x, targets, "semantic_recovered_classification") for x in class_recovered] + [recovered_plan(x, targets, "semantic_recovered_final_audit") for x in audit_recovered]
    require(len(semantic_plans) == EXPECTED_SEMANTIC_RECREATE, "semantic_plan_count")

    companions = [dict(x) for x in recovery.get("classifications") or [] if isinstance(x, Mapping) and x.get("classification") == "source_visual_companion_recovered"]
    require(len(companions) == EXPECTED_VISUAL_COMPANION, "companion_count")
    companion_plans = [companion_plan(companions[0], targets, (vf.get("font_render_calibration_v2") or {}).get("global") or {})]

    final_unresolved_ids = {str(x.get("instance_id") or "") for x in audit.get("audits") or [] if isinstance(x, Mapping) and x.get("classification") == "unresolved_after_full_visual_audit"}
    anchor_ids = {str(x.get("instance_id") or "") for x in classification.get("classifications") or [] if isinstance(x, Mapping) and x.get("classification") == "source_semantic_anchor_only"}
    compound_ids = {str(x.get("instance_id") or "") for x in classification.get("classifications") or [] if isinstance(x, Mapping) and x.get("classification") == "source_compound_member_represented"}
    preserved_ids = final_unresolved_ids | anchor_ids | compound_ids
    require(len(preserved_ids) == EXPECTED_PRESERVED, f"preserved_count:{len(preserved_ids)}")
    preserved = [{"instance_id": iid, "target_name": targets[iid], "action": "preserve_source_item_untouched"} for iid in sorted(preserved_ids)]

    protected_rows = {str(x.get("visual_token_id") or ""): dict(x) for x in persistent.get("rows") or [] if isinstance(x, Mapping)}
    protected_map = {token: str(row.get("target_name") or "") for token, row in protected_rows.items()}
    protected_exit = []
    for row in vf.get("protected_motion_review") or []:
        if not isinstance(row, Mapping) or not (row.get("motion") or {}).get("exit_motion"):
            continue
        token = str(row.get("instance_id") or "")
        name = protected_map.get(token, "")
        require(name, f"protected_target:{token}")
        persistent_row = protected_rows.get(token) or {}
        item_summary = persistent_row.get("summary") if isinstance(persistent_row.get("summary"), Mapping) else {}
        clip_start = int(item_summary.get("start") or -1)
        clip_end = int(item_summary.get("end") or -1)
        require(clip_start >= 0 and clip_end > clip_start, f"protected_clip_range:{token}")
        path = [dict(v) for v in row.get("frame_path") or [] if clip_start <= int(v.get("timeline_frame") or -1) < clip_end]
        require(path, f"protected_path:{token}")
        protected_exit.append({
            "visual_token_id": token,
            "target_name": name,
            "target_range": [clip_start, clip_end],
            "position_keys": [{"timeline_frame": int(v["timeline_frame"]), "local_frame": int(v["timeline_frame"])-clip_start, "value": [float(x) for x in v["position_fusion"]]} for v in path],
            "source_detected_range": [int((row.get("frame_path") or [])[0]["timeline_frame"]), int((row.get("frame_path") or [])[-1]["timeline_frame"])+1],
            "clipped_to_existing_protected_item": len(path) != len(row.get("frame_path") or []),
            "exit_axis": (row.get("motion") or {}).get("exit_axis"),
            "exit_direction_top_origin": (row.get("motion") or {}).get("exit_direction_top_origin"),
            "action": "center_only_source_exit_trajectory_within_existing_item_range",
        })
    require(len(protected_exit) == EXPECTED_PROTECTED_EXITS, f"protected_exit_count:{len(protected_exit)}")

    recreate = v2_plans + semantic_plans + companion_plans
    require(len(recreate) == 87 and len({x["target_name"] for x in recreate}) == 87, "recreate_scope")
    quarantine_rows = []
    for row in quarantine:
        iid = str(row["instance_id"]); match = next((x for x in v2_rows if str(x.get("instance_id")) == iid), None)
        require(match is not None, f"quarantine_v2:{iid}")
        quarantine_rows.append({"instance_id": iid, "target_name": str(match["target_name"]), "reason": str(row.get("reason") or ""), "action": str(row.get("final_rollout_action") or "")})
    require(not ({x["target_name"] for x in recreate} & {x["target_name"] for x in preserved}), "recreate_preserve_overlap")

    span = (foreground.get("asset_spans") or [None])[0]
    require(isinstance(span, Mapping), "foreground_span")
    affected = [str(x) for x in span.get("affected_cue_ids") or []]
    require(len(affected) == 1, "foreground_affected")
    matte_name = f"VC_OCCLUSION_RGBA_{span.get('span_id')}_{affected[0]}"
    occlusion = {
        "item_name": matte_name,
        "source_record_range": [int(span["timeline_frame_start"]), int(span["timeline_frame_end_exclusive"])],
        "duration_frames": int(span["duration_frames"]),
        "required_layer_order": "foreground_rgba_above_textplus",
        "target_track_policy": "max_physical_textplus_track_plus_one",
        "persistent_readback_required": True,
    }

    size_updates = sum(1 for row in recreate if row.get("size_action") == "source_target")
    fill_updates = sum(1 for row in recreate if row.get("fill_action") == "source_override")
    case_updates = sum(1 for row in recreate if row.get("case_action") == "source_override")
    dynamic_position = sum(1 for row in recreate if row.get("position_model") not in {"source_static_hold", "source_recovered_pixel_track"})
    explicit_position_rows = sum(len(row.get("position_keys") or []) for row in recreate)
    require(all(str(row.get("action") or "").startswith("remove_or_do_not_materialize") for row in quarantine_rows), "quarantine_action")

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "primary_authority": "accepted_visual_fidelity_v2_plus_positive_recoveries_plus_final_audit_quarantine",
            "transcript_timing_authority": False,
            "geometry_only_semantic_promotion": False,
            "negative_ocr_promoted_to_absence": False,
            "source_absence_claims": 0,
            "per_cue_hardcoded_overrides": False,
            "screenshot_specific_overrides": False,
            "residual_unresolved_mutation_authorized": False,
            "quarantine_consumed_from_offline_authority": True,
            "fade_polish_deferred": True,
            "detector_score_controls_opacity": False,
            "protected_non_exit_motion_mutation_authorized": False,
            "occlusion_contract": "foreground_rgba_above_textplus",
            "visual_approval_required": True,
            "further_rollout_authorized": False,
            "resolve_modified": False,
        },
        "inputs": {str(rel): {"path": str(rel), "sha256": sha256(root/rel)} for rel in [VF,VF_VALIDATION,RECOVERY,RECOVERY_VALIDATION,CLASSIFICATION,CLASSIFICATION_VALIDATION,FINAL_AUDIT,FINAL_AUDIT_VALIDATION,UNIVERSAL,FOREGROUND,FOREGROUND_VALIDATION,MATTE_CONTRACT,PROTECTED_PERSISTENT]},
        "final_audit_source_contracts": {
            str(rel): {
                "path": str(rel),
                "normalized_text_sha256": normalized_text_sha256(root/rel),
                "expected_normalized_text_sha256": digest,
                "normalization": "utf8_strip_bom_crlf_to_lf",
            }
            for rel, digest in FINAL_AUDIT_SOURCE_CONTRACTS.items()
        },
        "protected_persistent_contract": {
            "path": str(PROTECTED_PERSISTENT),
            "raw_sha256_observed": sha256(root/PROTECTED_PERSISTENT),
            "semantic_projection": "all_fields_except_volatile_reacquire_calls",
            "semantic_sha256": protected_persistent_semantic_sha256(persistent),
            "expected_semantic_sha256": EXPECTED_PROTECTED_PERSISTENT_SEMANTIC_SHA256,
        },
        "recreate_plans": recreate,
        "preserve_unresolved": preserved,
        "quarantine_remove": quarantine_rows,
        "protected_exit_updates": protected_exit,
        "composite_structural_already_absent": list((vf.get("inventory") or {}).get("composite_structural_removed") or []),
        "layout_groups": list(vf.get("layout_groups") or []),
        "occlusion": occlusion,
        "summary": {
            "structural_total": EXPECTED_STRUCTURAL,
            "source_physical_textplus": EXPECTED_SOURCE_PHYSICAL,
            "v2_repair_input": EXPECTED_V2_REPAIR,
            "quarantined_remove": EXPECTED_QUARANTINE,
            "v2_repair_recreate": EXPECTED_V2_RECREATE,
            "semantic_recreate": EXPECTED_SEMANTIC_RECREATE,
            "visual_companion_recreate": EXPECTED_VISUAL_COMPANION,
            "recreate_total": 87,
            "preserved_unresolved": EXPECTED_PRESERVED,
            "protected_total": EXPECTED_PROTECTED,
            "protected_exit_updates": EXPECTED_PROTECTED_EXITS,
            "composite_structural_already_absent": EXPECTED_COMPOSITE_ABSENT,
            "layout_group_count": 12,
            "size_updates": size_updates,
            "fill_updates": fill_updates,
            "case_updates": case_updates,
            "dynamic_position_recreate": dynamic_position,
            "explicit_position_rows": explicit_position_rows,
            "occlusion_span_count": 1,
            "target_physical_textplus": EXPECTED_TARGET_PHYSICAL,
            "resolve_modified": False,
            "further_rollout_authorized": False,
        },
        "semantic_sha256": "",
    }
    require(len(result["composite_structural_already_absent"]) == EXPECTED_COMPOSITE_ABSENT, "composite_count")
    result["semantic_sha256"] = canonical_sha256({k:v for k,v in result.items() if k != "semantic_sha256"})
    write_json(output, result)
    return result

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()
    root = args.root.resolve(); output = (args.output or root/DEFAULT_OUTPUT).resolve()
    result = build(root, output)
    print(json.dumps(result["summary"], sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
