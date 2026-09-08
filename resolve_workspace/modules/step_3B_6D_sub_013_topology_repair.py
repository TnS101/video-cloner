"""Remove only the two erroneous time-2 keys created by the failed sub_013 recovery."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_TOPOLOGY_REPAIR_V1"
SOURCE_RECOVERY_TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1"
SOURCE_RECOVERY_RUN_ID = "20260802T185045608Z_e574ca97eb634e518481365d1398d3d9"
SOURCE_RESUME_TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_RESUME_V1"
SOURCE_RESUME_RUN_ID = "20260803T084043222Z_eee718d810174f3595316a82d477f8e3"
CAPTURE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1"
CAPTURE_RUN_ID = "20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
PLAN_PATH = ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prepared_plan_one.json"
RESUME_TOPOLOGY_PATH = f".agent/reports/{SOURCE_RESUME_TASK_ID}/{SOURCE_RESUME_RUN_ID}/topology_preservation_audit.json"
RESUME_LINEAGE_PATH = f".agent/reports/{SOURCE_RESUME_TASK_ID}/{SOURCE_RESUME_RUN_ID}/resume_lineage_validation.json"
CAPTURE_COMPARISON_PATH = f".agent/reports/{CAPTURE_TASK_ID}/{CAPTURE_RUN_ID}/operation_current_state_comparison.json"
CAPTURE_KEYFRAME_PATH = f".agent/reports/{CAPTURE_TASK_ID}/{CAPTURE_RUN_ID}/raw_keyframe_inventory.json"
EXPECTED = {
    "project": "New Project 1",
    "timeline": "DZsqH7auhjt_textplus_full",
    "track": 3,
    "count": 116,
}
TARGETS = {
    "sub_007": ("While", "VC_TEXTPLUS_0007_sub_007", 196, 199),
    "sub_013": ("out", "VC_TEXTPLUS_0013_sub_013", 224, 230),
    "sub_110": ("looks", "VC_TEXTPLUS_0110_sub_110", 862, 868),
    "sub_114": ("AND", "VC_TEXTPLUS_0114_sub_114", 888, 894),
}
REPAIR_PROPERTIES = ("Center", "Size")
EXTRA_KEY_TIME = 2.0
RAW_KEY_IDENTIFIER = 2
EXPECTED_RAW_TIME = 1.0
TECHNICAL_VERDICT = "TOPOLOGY_RESTORED — STEP_3B_6D_DIRECT_FRAME_ACCEPTANCE_REQUIRES_CLOUD_REVIEW"


def safe(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception:
        return default


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def point(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        value = [value.get(1, value.get("1")), value.get(2, value.get("2"))]
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError, IndexError):
        return None


def equal(property_name: str, actual: Any, expected: Any) -> bool:
    if property_name == "Center":
        left = point(actual)
        right = point(expected)
        return bool(left and right and all(abs(a - b) <= 1e-5 for a, b in zip(left, right)))
    try:
        number = float(actual)
        target = float(expected)
        return math.isfinite(number) and abs(number - target) <= 1e-5
    except (TypeError, ValueError):
        return False


def input_for(tool: Any, property_name: str) -> Any:
    return safe(tool, "FindInput", property_name) or getattr(tool, property_name, None)


def read_at(tool: Any, property_name: str, time_value: float | int) -> Any:
    input_obj = input_for(tool, property_name)
    if input_obj is None:
        return None
    try:
        return input_obj[time_value]
    except Exception:
        return safe(tool, "GetInput", property_name, time_value)


def tool_for(item: Any) -> Any:
    comp_count = int(safe(item, "GetFusionCompCount", default=0) or 0)
    comp = safe(item, "GetFusionCompByIndex", 1) if comp_count else safe(item, "GetFusionCompByName", "Composition 1")
    for tool in (safe(comp, "GetToolList", False, default={}) or {}).values():
        attrs = safe(tool, "GetAttrs", default={}) or {}
        reg_id = str(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID") or "")
        if reg_id in ("TextPlus", "Text3D"):
            return tool
    return None


def normalize_keyframes(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("keyframe_structure_not_object")
    normalized = {str(key): float(item) for key, item in value.items()}
    return dict(sorted(normalized.items(), key=lambda pair: int(float(pair[0]))))


def structural_topology(tool: Any, property_name: str) -> dict[str, Any]:
    input_obj = input_for(tool, property_name)
    if input_obj is None:
        raise ValueError(f"missing_input:{property_name}")
    output = safe(input_obj, "GetConnectedOutput")
    input_attrs = safe(input_obj, "GetAttrs", default={}) or {}
    output_attrs = safe(output, "GetAttrs", default={}) or {}
    return {
        "input": {
            "INPS_ID": input_attrs.get("INPS_ID"),
            "INPS_DataType": input_attrs.get("INPS_DataType"),
            "INPB_Connected": bool(input_attrs.get("INPB_Connected")),
        },
        "modifier_connected": output is not None,
        "modifier": {
            "OUTS_Name": output_attrs.get("OUTS_Name"),
            "OUTS_DataType": output_attrs.get("OUTS_DataType"),
            "OUTS_ID": output_attrs.get("OUTS_ID"),
        },
        "raw_keyframe_structure": normalize_keyframes(safe(input_obj, "GetKeyFrames", default={}) or {}),
    }


def topology_for_tools(tools: dict[str, Any]) -> dict[str, Any]:
    return {
        cue_id: {property_name: structural_topology(tool, property_name) for property_name in REPAIR_PROPERTIES}
        for cue_id, tool in tools.items()
    }


def validate_topology_evidence(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if document.get("ok") is not False or document.get("v3_candidate_count") != EXPECTED["count"]:
        raise ValueError("resume_topology_evidence_status")
    current = document.get("current")
    expected = document.get("expected")
    if not isinstance(current, dict) or not isinstance(expected, dict) or set(current) != set(TARGETS) or set(expected) != set(TARGETS):
        raise ValueError("resume_topology_evidence_targets")
    for cue_id in TARGETS:
        if set(current.get(cue_id, {})) != set(REPAIR_PROPERTIES) or set(expected.get(cue_id, {})) != set(REPAIR_PROPERTIES):
            raise ValueError(f"resume_topology_evidence_properties:{cue_id}")
        for property_name in REPAIR_PROPERTIES:
            current_property = current[cue_id][property_name]
            expected_property = expected[cue_id][property_name]
            if cue_id != "sub_013":
                if current_property != expected_property:
                    raise ValueError(f"unexpected_topology_drift:{cue_id}:{property_name}")
                continue
            current_keys = current_property.get("raw_keyframe_structure")
            expected_keys = expected_property.get("raw_keyframe_structure")
            if current_keys != {"1": 0.0, "2": 1.0, "3": 2.0, "4": 3.0, "5": 4.0}:
                raise ValueError(f"unexpected_current_sub_013_keys:{property_name}")
            if expected_keys != {"1": 0.0, "2": 1.0, "3": 3.0, "4": 4.0}:
                raise ValueError(f"unexpected_expected_sub_013_keys:{property_name}")
            current_without_keys = dict(current_property)
            expected_without_keys = dict(expected_property)
            current_without_keys.pop("raw_keyframe_structure", None)
            expected_without_keys.pop("raw_keyframe_structure", None)
            if current_without_keys != expected_without_keys:
                raise ValueError(f"non_key_topology_drift:{property_name}")
    return current, expected


def find_items(resolve: Any) -> tuple[dict[str, Any], list[Any]]:
    project_manager = safe(resolve, "GetProjectManager")
    project = safe(project_manager, "GetCurrentProject")
    timeline = safe(project, "GetCurrentTimeline")
    if safe(project, "GetName") != EXPECTED["project"] or safe(timeline, "GetName") != EXPECTED["timeline"]:
        raise ValueError("project_timeline")
    items = list(safe(timeline, "GetItemListInTrack", "video", EXPECTED["track"], default=[]) or [])
    if len(items) != EXPECTED["count"]:
        raise ValueError("v3_count")
    found: dict[str, Any] = {}
    for cue_id, (text, name, start, end) in TARGETS.items():
        matches = [
            item
            for item in items
            if safe(item, "GetName", default="") == name
            and [safe(item, "GetStart"), safe(item, "GetEnd")] == [start, end]
        ]
        if len(matches) != 1:
            raise ValueError(f"item_identity:{cue_id}")
        tool = tool_for(matches[0])
        if tool is None or str(read_at(tool, "StyledText", 0) or "").strip() != text:
            raise ValueError(f"text_tool:{cue_id}")
        found[cue_id] = tool
    return found, items


def validate_hashes(root: Path, hashes: dict[str, str]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for relative_path, expected_hash in hashes.items():
        path = root / relative_path
        actual_hash = sha256(path) if path.is_file() else None
        evidence[relative_path] = {
            "exists": path.is_file(),
            "expected_sha256": expected_hash,
            "actual_sha256": actual_hash,
            "match": actual_hash == expected_hash,
        }
        if actual_hash != expected_hash:
            raise ValueError(f"prerequisite_hash:{relative_path}")
    return evidence


def classify_direct(tools: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        cue_id = str(row.get("cue_id") or "")
        property_name = str(row.get("property") or "")
        local_frame = int(row.get("local_frame"))
        current = read_at(tools[cue_id], property_name, local_frame)
        classification = "CURRENT_TARGET" if equal(property_name, current, row.get("target_value")) else "CURRENT_OTHER"
        comparisons.append(
            {
                "plan_operation_index": row.get("plan_operation_index"),
                "cue_id": cue_id,
                "property": property_name,
                "local_frame": local_frame,
                "timeline_frame": row.get("timeline_frame"),
                "current_value": json_safe(current),
                "target_value": row.get("target_value"),
                "capture_current_raw_value": row.get("current_raw_value"),
                "classification": classification,
            }
        )
    return comparisons


def raw_address_map(raw_inventory: dict[str, Any]) -> dict[tuple[str, str, int], dict[str, Any]]:
    result: dict[tuple[str, str, int], dict[str, Any]] = {}
    for target in raw_inventory.get("targets", []):
        cue_id = str(target.get("cue_id") or "")
        for property_name, property_data in (target.get("properties") or {}).items():
            for key in property_data.get("keys") or []:
                raw_identifier = int(key.get("raw_key_identifier"))
                result[(cue_id, str(property_name), raw_identifier)] = key
    return result


def classify_address_resolved(
    tools: dict[str, Any],
    rows: list[dict[str, Any]],
    addresses: dict[tuple[str, str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    recovery_keys = {("sub_013", "Center", 2), ("sub_013", "Size", 2)}
    for row in rows:
        cue_id = str(row.get("cue_id") or "")
        property_name = str(row.get("property") or "")
        local_frame = int(row.get("local_frame"))
        direct_value = read_at(tools[cue_id], property_name, local_frame)
        address_key = (cue_id, property_name, local_frame)
        if address_key in recovery_keys:
            raw_address = addresses.get((cue_id, property_name, RAW_KEY_IDENTIFIER))
            if not raw_address or raw_address.get("mapping_ambiguous") is not False:
                raise ValueError(f"raw_address_missing_or_ambiguous:{property_name}")
            raw_time = float(raw_address.get("raw_value"))
            if raw_time != EXPECTED_RAW_TIME or int(raw_address.get("modifier_local_frame")) != local_frame:
                raise ValueError(f"raw_address_identity:{property_name}")
            resolved_value = read_at(tools[cue_id], property_name, raw_time)
            addressing = "capture_raw_key_identity"
            raw_identifier: int | None = RAW_KEY_IDENTIFIER
        else:
            resolved_value = direct_value
            addressing = "direct_clip_local_frame"
            raw_identifier = None
            raw_time = None
        classification = "CURRENT_TARGET" if equal(property_name, resolved_value, row.get("target_value")) else "CURRENT_OTHER"
        comparisons.append(
            {
                "plan_operation_index": row.get("plan_operation_index"),
                "cue_id": cue_id,
                "property": property_name,
                "local_frame": local_frame,
                "timeline_frame": row.get("timeline_frame"),
                "addressing": addressing,
                "raw_key_identifier": raw_identifier,
                "raw_time": raw_time,
                "direct_frame_value": json_safe(direct_value),
                "resolved_value": json_safe(resolved_value),
                "target_value": row.get("target_value"),
                "classification": classification,
            }
        )
    return comparisons


def retained_values(tool: Any, property_name: str, expected_property_topology: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for raw_time in expected_property_topology["raw_keyframe_structure"].values():
        values[str(float(raw_time))] = json_safe(read_at(tool, property_name, float(raw_time)))
    return values


def retained_values_equal(property_name: str, before: dict[str, Any], after: dict[str, Any]) -> bool:
    return set(before) == set(after) and all(equal(property_name, before[key], after[key]) for key in before)


def delete_extra_key(
    tool: Any,
    property_name: str,
    expected_before: dict[str, Any],
    expected_after: dict[str, Any],
) -> dict[str, Any]:
    before = structural_topology(tool, property_name)
    if before != expected_before:
        raise ValueError(f"pre_delete_topology_drift:{property_name}")
    before_retained = retained_values(tool, property_name, expected_after)
    input_obj = input_for(tool, property_name)
    try:
        input_obj[EXTRA_KEY_TIME] = None
    except Exception as exc:
        raise RuntimeError(f"key_delete_failed:{property_name}") from exc
    after = structural_topology(tool, property_name)
    after_retained = retained_values(tool, property_name, expected_after)
    if after != expected_after:
        raise ValueError(f"key_delete_topology_readback:{property_name}")
    if not retained_values_equal(property_name, before_retained, after_retained):
        raise ValueError(f"retained_key_value_changed:{property_name}")
    return {
        "cue_id": "sub_013",
        "property": property_name,
        "deleted_time": EXTRA_KEY_TIME,
        "before_topology": before,
        "after_topology": after,
        "retained_values_before": before_retained,
        "retained_values_after": after_retained,
        "retained_values_unchanged": True,
        "ok": True,
    }


def summary(comparisons: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "operation_count": len(comparisons),
        "current_target": sum(item.get("classification") == "CURRENT_TARGET" for item in comparisons),
        "current_other": sum(item.get("classification") == "CURRENT_OTHER" for item in comparisons),
        "missing": 0,
        "ambiguous": 0,
        "blend": 0,
        "other_property": 0,
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": "sub_013_topology_repair",
        "source_recovery_run_id": SOURCE_RECOVERY_RUN_ID,
        "source_resume_run_id": SOURCE_RESUME_RUN_ID,
        "value_setter_call_count": 0,
        "key_delete_call_count": 0,
        "effective_mutation_count": 0,
        "save_call_count": 0,
        "modifier_mutation_call_count": 0,
        "blend_operation_count": 0,
        "timeline_modified": False,
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        if (
            payload.get("source_recovery_run_id") != SOURCE_RECOVERY_RUN_ID
            or payload.get("source_resume_run_id") != SOURCE_RESUME_RUN_ID
            or payload.get("read_only_capture_run_id") != CAPTURE_RUN_ID
            or payload.get("plan_hash") != PLAN_HASH
            or payload.get("repair_policy") != "delete_exact_two_erroneous_time_2_keys_then_validate_capture_raw_addressing"
        ):
            raise ValueError("command_contract")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        output_dir = root / str(payload.get("report_dir") or "")
        output_dir.mkdir(parents=True, exist_ok=True)
        command_name = f"{TASK_ID}_{run_id}.json"
        running_path = root / ".agent" / "commands" / "running" / command_name
        receipt = load_json(output_dir / "publication_receipt.json")
        if not running_path.is_file() or sha256(running_path) != receipt.get("command_sha256"):
            raise ValueError("running_lifecycle_observation")

        prerequisite_hashes = payload.get("prerequisite_hashes")
        if not isinstance(prerequisite_hashes, dict):
            raise ValueError("prerequisite_hash_contract")
        hash_evidence = validate_hashes(root, prerequisite_hashes)
        accepted_state_path = root / ".agent" / "state" / "latest_accepted.json"
        expected_accepted_hash = payload.get("accepted_state_sha256")
        current_accepted_hash = sha256(accepted_state_path) if accepted_state_path.is_file() else None
        if current_accepted_hash != expected_accepted_hash:
            raise ValueError("accepted_state_drift")
        plan = load_json(root / PLAN_PATH)
        if plan.get("plan_hash") != PLAN_HASH:
            raise ValueError("plan_semantic_hash")

        resume_lineage = load_json(root / RESUME_LINEAGE_PATH)
        if resume_lineage.get("ok") is not True or resume_lineage.get("exact_two_allowlisted_corrections") is not True:
            raise ValueError("resume_lineage_contract")
        resume_topology = load_json(root / RESUME_TOPOLOGY_PATH)
        expected_current_topology, expected_restored_topology = validate_topology_evidence(resume_topology)

        capture_comparison = load_json(root / CAPTURE_COMPARISON_PATH)
        rows = capture_comparison.get("operations") or []
        if len(rows) != 36:
            raise ValueError("capture_operation_count")
        capture_other = [row for row in rows if row.get("classification") == "CURRENT_OTHER"]
        if {(row.get("cue_id"), row.get("property"), row.get("local_frame")) for row in capture_other} != {
            ("sub_013", "Center", 2),
            ("sub_013", "Size", 2),
        }:
            raise ValueError("capture_other_identity")
        raw_inventory = load_json(root / CAPTURE_KEYFRAME_PATH)
        addresses = raw_address_map(raw_inventory)
        for property_name in REPAIR_PROPERTIES:
            address = addresses.get(("sub_013", property_name, RAW_KEY_IDENTIFIER))
            if (
                not address
                or float(address.get("raw_value")) != EXPECTED_RAW_TIME
                or int(address.get("modifier_local_frame")) != 2
                or int(address.get("timeline_frame")) != 226
                or address.get("mapping_ambiguous") is not False
            ):
                raise ValueError(f"capture_raw_address_contract:{property_name}")

        tools, _ = find_items(resolve)
        live_before_topology = topology_for_tools(tools)
        if live_before_topology != expected_current_topology:
            raise ValueError("live_pre_repair_topology_drift")
        direct_before = classify_direct(tools, rows)
        direct_before_summary = summary(direct_before)
        if direct_before_summary["current_target"] != 36 or direct_before_summary["current_other"] != 0:
            raise ValueError("pre_repair_direct_state_not_36_target")
        write_json(
            output_dir / "topology_repair_pre_state.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "hashes": hash_evidence,
                "topology": live_before_topology,
                "direct_frame_summary": direct_before_summary,
                "direct_frame_operations": direct_before,
                "accepted_state_sha256": current_accepted_hash,
            },
        )

        deletion_journal: list[dict[str, Any]] = []
        for property_name in REPAIR_PROPERTIES:
            entry = delete_extra_key(
                tools["sub_013"],
                property_name,
                expected_current_topology["sub_013"][property_name],
                expected_restored_topology["sub_013"][property_name],
            )
            report["key_delete_call_count"] += 1
            report["effective_mutation_count"] += 1
            report["timeline_modified"] = True
            deletion_journal.append(entry)
            write_json(output_dir / "key_deletion_journal.json", deletion_journal)

        tools_after, _ = find_items(resolve)
        live_after_topology = topology_for_tools(tools_after)
        topology_ok = live_after_topology == expected_restored_topology
        write_json(
            output_dir / "topology_preservation_audit.json",
            {
                "ok": topology_ok,
                "comparison_scope": "structural fields and raw key times; dynamic values excluded",
                "source_resume_run_id": SOURCE_RESUME_RUN_ID,
                "before": expected_current_topology,
                "expected_after": expected_restored_topology,
                "actual_after": live_after_topology,
                "deleted_keys": [
                    {"cue_id": "sub_013", "property": "Center", "time": EXTRA_KEY_TIME},
                    {"cue_id": "sub_013", "property": "Size", "time": EXTRA_KEY_TIME},
                ],
                "v3_candidate_count": EXPECTED["count"],
            },
        )
        if not topology_ok:
            raise ValueError("post_repair_topology_mismatch")

        direct_after = classify_direct(tools_after, rows)
        direct_after_summary = summary(direct_after)
        direct_other = [item for item in direct_after if item["classification"] == "CURRENT_OTHER"]
        expected_direct_other = {("sub_013", "Center", 2), ("sub_013", "Size", 2)}
        if (
            direct_after_summary["current_target"] != 34
            or direct_after_summary["current_other"] != 2
            or {(item["cue_id"], item["property"], item["local_frame"]) for item in direct_other} != expected_direct_other
            or any(not equal(item["property"], item["current_value"], item["capture_current_raw_value"]) for item in direct_other)
        ):
            raise ValueError("restored_direct_interpolation_contract")
        write_json(
            output_dir / "direct_frame_state_comparison.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                **direct_after_summary,
                "interpretation": "Two local-frame-2 values are interpolated non-key samples after topology restoration.",
                "operations": direct_after,
            },
        )

        address_resolved = classify_address_resolved(tools_after, rows, addresses)
        address_summary = summary(address_resolved)
        if address_summary["current_target"] != 36 or address_summary["current_other"] != 0:
            raise ValueError("address_resolved_state_not_36_target")
        write_json(
            output_dir / "address_resolved_operation_comparison.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                **address_summary,
                "addressing_policy": "Use capture raw-key identity for the two addressing-mismatch rows; never derive raw addressing from local frame 2.",
                "operations": address_resolved,
            },
        )

        before_by_index = {item["plan_operation_index"]: item for item in direct_before}
        after_by_index = {item["plan_operation_index"]: item for item in direct_after}
        protected_indices = [
            row.get("plan_operation_index")
            for row in rows
            if (row.get("cue_id"), row.get("property"), row.get("local_frame")) not in expected_direct_other
        ]
        protected_unchanged = all(
            equal(
                after_by_index[index]["property"],
                before_by_index[index]["current_value"],
                after_by_index[index]["current_value"],
            )
            for index in protected_indices
        )
        protected_audit = {
            "ok": len(protected_indices) == 34 and protected_unchanged,
            "protected_operation_count": len(protected_indices),
            "protected_values_unchanged": protected_unchanged,
            "value_setter_call_count": 0,
            "key_delete_call_count": 2,
            "non_target_write_count": 0,
            "blend_operation_count": 0,
            "modifier_mutation_call_count": 0,
        }
        write_json(output_dir / "protected_state_audit.json", protected_audit)
        if not protected_audit["ok"]:
            raise ValueError("protected_state_changed")

        phase3_tools, _ = find_items(resolve)
        phase3_topology = topology_for_tools(phase3_tools)
        phase3_direct = classify_direct(phase3_tools, rows)
        phase3_direct_summary = summary(phase3_direct)
        phase3_resolved = classify_address_resolved(phase3_tools, rows, addresses)
        phase3_resolved_summary = summary(phase3_resolved)
        phase3 = {
            "ok": phase3_topology == expected_restored_topology
            and phase3_direct_summary["current_target"] == 34
            and phase3_direct_summary["current_other"] == 2
            and phase3_resolved_summary["current_target"] == 36
            and phase3_resolved_summary["current_other"] == 0,
            "value_setter_calls": 0,
            "key_delete_calls": 0,
            "effective_mutations": 0,
            "blend_operations": 0,
            "modifier_mutations": 0,
            "timeline_modified": False,
            "structural_topology_restored": phase3_topology == expected_restored_topology,
            "direct_frame_current_target": phase3_direct_summary["current_target"],
            "direct_frame_current_other": phase3_direct_summary["current_other"],
            "address_resolved_current_target": phase3_resolved_summary["current_target"],
            "address_resolved_current_other": phase3_resolved_summary["current_other"],
        }
        write_json(output_dir / "phase3_idempotency_report.json", phase3)
        if not phase3["ok"]:
            raise ValueError("phase3_validation")

        final_accepted_hash = sha256(accepted_state_path) if accepted_state_path.is_file() else None
        if final_accepted_hash != expected_accepted_hash:
            raise ValueError("accepted_state_changed")
        write_json(
            output_dir / "topology_repair_post_state.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "topology": live_after_topology,
                "direct_frame_summary": direct_after_summary,
                "address_resolved_summary": address_summary,
                "accepted_state_sha256": final_accepted_hash,
            },
        )
        write_json(
            output_dir / "lifecycle_runtime_observation.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "running_observed": True,
                "running_command_path": str(running_path.relative_to(root)).replace("\\", "/"),
                "running_command_sha256": sha256(running_path),
            },
        )
        report.update(
            {
                "ok": True,
                "technical_verdict": TECHNICAL_VERDICT,
                "step_3B_6D_acceptance_status": "BLOCKED_PENDING_CLOUD_REVIEW",
                "manual_visual_approval_required": True,
                "topology_restored": True,
                "direct_frame_current_target": 34,
                "direct_frame_current_other": 2,
                "address_resolved_current_target": 36,
                "address_resolved_current_other": 0,
                "phase3": phase3,
                "accepted_state_unchanged": True,
            }
        )
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
