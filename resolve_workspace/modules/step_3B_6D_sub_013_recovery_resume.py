"""Read-only resume validation for the already-applied sub_013 recovery setters."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_RESUME_V1"
SOURCE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1"
SOURCE_RUN_ID = "20260802T185045608Z_e574ca97eb634e518481365d1398d3d9"
FAILED_RUNTIME_ID = "20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379"
CAPTURE_RUN_ID = "20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
PLAN_PATH = ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prepared_plan_one.json"
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
ALLOWLIST = [
    {
        "cue_id": "sub_013",
        "text": "out",
        "item_identity": "VC_TEXTPLUS_0013_sub_013",
        "property": "Center",
        "local_frame": 2,
        "timeline_frame": 226,
        "raw_key_identifier": 2,
        "current_value": {"1": 0.506203705, "2": 0.52842448, "3": 0.0},
        "target_value": [0.50611111, 0.5284375],
        "modifier": {"OUTS_ID": "Position", "OUTS_DataType": "Point"},
    },
    {
        "cue_id": "sub_013",
        "text": "out",
        "item_identity": "VC_TEXTPLUS_0013_sub_013",
        "property": "Size",
        "local_frame": 2,
        "timeline_frame": 226,
        "raw_key_identifier": 2,
        "current_value": 0.08768857685550001,
        "target_value": 0.087467395905,
        "modifier": {"OUTS_ID": "Value", "OUTS_DataType": "Number"},
    },
]


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


def input_for(tool: Any, name: str) -> Any:
    return safe(tool, "FindInput", name) or getattr(tool, name, None)


def read_value(tool: Any, name: str, frame: int) -> Any:
    value = safe(tool, "GetInput", name, frame)
    if value is not None:
        return value
    input_obj = input_for(tool, name)
    try:
        return input_obj[frame]
    except Exception:
        return None


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
    normalized: dict[str, float] = {}
    for raw_identifier, raw_time in value.items():
        normalized[str(raw_identifier)] = float(raw_time)
    return dict(sorted(normalized.items(), key=lambda item: int(float(item[0]))))


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


def expected_topology(raw_inventory: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for target in raw_inventory.get("targets", []):
        cue_id = str(target.get("cue_id") or "")
        result[cue_id] = {}
        for property_name in ("Center", "Size"):
            property_data = (target.get("properties") or {}).get(property_name) or {}
            input_attrs = property_data.get("input_attrs") or {}
            modifier_attrs = property_data.get("modifier_attrs") or {}
            result[cue_id][property_name] = {
                "input": {
                    "INPS_ID": input_attrs.get("INPS_ID"),
                    "INPS_DataType": input_attrs.get("INPS_DataType"),
                    "INPB_Connected": bool(input_attrs.get("INPB_Connected")),
                },
                "modifier_connected": bool(property_data.get("modifier_connected")),
                "modifier": {
                    "OUTS_Name": modifier_attrs.get("OUTS_Name"),
                    "OUTS_DataType": modifier_attrs.get("OUTS_DataType"),
                    "OUTS_ID": modifier_attrs.get("OUTS_ID"),
                },
                "raw_keyframe_structure": normalize_keyframes(property_data.get("raw_keyframe_structure") or {}),
            }
    if set(result) != set(TARGETS):
        raise ValueError("capture_topology_targets")
    return result


def find_items(resolve: Any) -> tuple[Any, dict[str, Any], list[Any]]:
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
        if tool is None or str(read_value(tool, "StyledText", 0) or "").strip() != text:
            raise ValueError(f"text_tool:{cue_id}")
        found[cue_id] = tool
    return timeline, found, items


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


def validate_source_lineage(root: Path, hashes: dict[str, str]) -> dict[str, Any]:
    hash_evidence = validate_hashes(root, hashes)
    source_dir = root / ".agent" / "reports" / SOURCE_TASK_ID / SOURCE_RUN_ID
    command = load_json(source_dir / "recovery_command.json")
    status = load_json(source_dir / "status.json")
    report = load_json(source_dir / "report.json")
    journal = load_json(source_dir / "setter_journal.json")
    if command.get("task") != SOURCE_TASK_ID or command.get("run_id") != SOURCE_RUN_ID:
        raise ValueError("source_command_identity")
    payload = command.get("payload") or {}
    if (
        payload.get("failed_run_id") != FAILED_RUNTIME_ID
        or payload.get("read_only_capture_run_id") != CAPTURE_RUN_ID
        or payload.get("plan_hash") != PLAN_HASH
        or payload.get("recovery_allowlist") != ALLOWLIST
    ):
        raise ValueError("source_command_contract")
    if status.get("run_id") != SOURCE_RUN_ID or status.get("ok") is not False or status.get("running") is not False:
        raise ValueError("source_status_contract")
    failures = report.get("failures") or []
    if (
        report.get("ok") is not False
        or report.get("setter_call_count") != 2
        or report.get("effective_mutation_count") != 2
        or report.get("save_call_count") != 0
        or report.get("modifier_mutation_call_count") != 0
        or "ValueError: topology_changed" not in failures
    ):
        raise ValueError("source_report_contract")
    if not isinstance(journal, list) or len(journal) != 2:
        raise ValueError("source_setter_journal_count")
    for expected, entry in zip(ALLOWLIST, journal):
        if entry.get("operation") != expected or entry.get("ok") is not True:
            raise ValueError("source_setter_journal_operation")
        if not equal(expected["property"], entry.get("immediate_value"), expected["target_value"]):
            raise ValueError("source_setter_journal_readback")
    return {
        "ok": True,
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_failure": "ValueError: topology_changed",
        "source_setter_call_count": 2,
        "source_effective_mutation_count": 2,
        "source_save_call_count": 0,
        "source_modifier_mutation_call_count": 0,
        "exact_two_allowlisted_corrections": True,
        "hashes": hash_evidence,
    }


def classify_operations(tools: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        cue_id = str(row.get("cue_id"))
        property_name = str(row.get("property"))
        local_frame = int(row.get("local_frame"))
        current = read_value(tools[cue_id], property_name, local_frame)
        if current is None:
            classification = "MISSING"
        elif equal(property_name, current, row.get("target_value")):
            classification = "CURRENT_TARGET"
        else:
            classification = "CURRENT_OTHER"
        comparisons.append(
            {
                "plan_operation_index": row.get("plan_operation_index"),
                "cue_id": cue_id,
                "property": property_name,
                "local_frame": local_frame,
                "timeline_frame": row.get("timeline_frame"),
                "current_value": json_safe(current),
                "target_value": row.get("target_value"),
                "classification": classification,
            }
        )
    return comparisons


def topology_for_tools(tools: dict[str, Any]) -> dict[str, Any]:
    return {
        cue_id: {property_name: structural_topology(tool, property_name) for property_name in ("Center", "Size")}
        for cue_id, tool in tools.items()
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": "recovery_resume_read_only",
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "failed_runtime_id": FAILED_RUNTIME_ID,
        "read_only_capture_run_id": CAPTURE_RUN_ID,
        "plan_hash": PLAN_HASH,
        "source_setter_call_count": 2,
        "source_effective_mutation_count": 2,
        "current_run_setter_call_count": 0,
        "current_run_effective_mutation_count": 0,
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
            payload.get("source_task_id") != SOURCE_TASK_ID
            or payload.get("source_run_id") != SOURCE_RUN_ID
            or payload.get("failed_runtime_id") != FAILED_RUNTIME_ID
            or payload.get("read_only_capture_run_id") != CAPTURE_RUN_ID
            or payload.get("plan_hash") != PLAN_HASH
            or payload.get("recovery_allowlist") != ALLOWLIST
            or payload.get("resume_policy") != "read_only_validation_of_already_applied_two_setters"
        ):
            raise ValueError("command_contract")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        output_dir = root / str(payload.get("report_dir") or "")
        output_dir.mkdir(parents=True, exist_ok=True)
        command_name = f"{TASK_ID}_{run_id}.json"
        running_path = root / ".agent" / "commands" / "running" / command_name
        receipt_path = output_dir / "publication_receipt.json"
        receipt = load_json(receipt_path) if receipt_path.is_file() else {}
        if not running_path.is_file() or sha256(running_path) != str(receipt.get("command_sha256") or ""):
            raise ValueError("running_lifecycle_observation")

        prerequisite_hashes = payload.get("prerequisite_hashes") or {}
        if not isinstance(prerequisite_hashes, dict):
            raise ValueError("prerequisite_hash_contract")
        lineage = validate_source_lineage(root, prerequisite_hashes)
        if load_json(root / PLAN_PATH).get("plan_hash") != PLAN_HASH:
            raise ValueError("plan_semantic_hash")
        write_json(output_dir / "resume_lineage_validation.json", lineage)

        capture_path = root / ".agent" / "reports" / "DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1" / CAPTURE_RUN_ID
        rows_document = load_json(capture_path / "operation_current_state_comparison.json")
        rows = rows_document.get("operations") or []
        if len(rows) != 36:
            raise ValueError("capture_operation_count")
        capture_other = [row for row in rows if row.get("classification") == "CURRENT_OTHER"]
        if len(capture_other) != 2 or {
            (row.get("cue_id"), row.get("property"), row.get("local_frame")) for row in capture_other
        } != {("sub_013", "Center", 2), ("sub_013", "Size", 2)}:
            raise ValueError("capture_allowlist")
        raw_inventory = load_json(capture_path / "raw_keyframe_inventory.json")
        expected_structure = expected_topology(raw_inventory)

        _, tools, _ = find_items(resolve)
        current_structure = topology_for_tools(tools)
        topology_ok = current_structure == expected_structure
        write_json(
            output_dir / "topology_preservation_audit.json",
            {
                "ok": topology_ok,
                "comparison_scope": "structural fields only; dynamic values excluded",
                "expected": expected_structure,
                "current": current_structure,
                "unchanged_item_identities": sorted(tools),
                "v3_candidate_count": EXPECTED["count"],
            },
        )
        if not topology_ok:
            raise ValueError("structural_topology_drift")

        phase2 = classify_operations(tools, rows)
        target_count = sum(item["classification"] == "CURRENT_TARGET" for item in phase2)
        other_count = sum(item["classification"] == "CURRENT_OTHER" for item in phase2)
        missing_count = sum(item["classification"] == "MISSING" for item in phase2)
        write_json(output_dir / "persistent_post_recovery_state.json", phase2)
        write_json(
            output_dir / "operation_current_state_comparison.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "operation_count": len(phase2),
                "current_target": target_count,
                "current_other": other_count,
                "missing": missing_count,
                "ambiguous": 0,
                "blend": 0,
                "other_property": 0,
                "operations": phase2,
            },
        )
        protected = [
            item
            for item in phase2
            if (item["cue_id"], item["property"], item["local_frame"])
            not in {("sub_013", "Center", 2), ("sub_013", "Size", 2)}
        ]
        recovered = [item for item in phase2 if item not in protected]
        protected_audit = {
            "ok": len(protected) == 34
            and all(item["classification"] == "CURRENT_TARGET" for item in protected)
            and len(recovered) == 2
            and all(item["classification"] == "CURRENT_TARGET" for item in recovered),
            "protected_operation_count": len(protected),
            "protected_current_target": sum(item["classification"] == "CURRENT_TARGET" for item in protected),
            "recovered_operation_count": len(recovered),
            "recovered_current_target": sum(item["classification"] == "CURRENT_TARGET" for item in recovered),
            "non_target_write_count": 0,
            "blend_operation_count": 0,
            "other_property_operation_count": 0,
        }
        write_json(output_dir / "protected_state_audit.json", protected_audit)
        if target_count != 36 or other_count != 0 or missing_count != 0 or not protected_audit["ok"]:
            raise ValueError("resume_state_not_36_target_equal")

        _, phase3_tools, _ = find_items(resolve)
        phase3_structure = topology_for_tools(phase3_tools)
        phase3_rows = classify_operations(phase3_tools, rows)
        phase3_target_count = sum(item["classification"] == "CURRENT_TARGET" for item in phase3_rows)
        phase3_other_count = sum(item["classification"] == "CURRENT_OTHER" for item in phase3_rows)
        phase3_missing_count = sum(item["classification"] == "MISSING" for item in phase3_rows)
        phase3 = {
            "ok": phase3_target_count == 36 and phase3_other_count == 0 and phase3_missing_count == 0 and phase3_structure == expected_structure,
            "setter_calls": 0,
            "center_setters": 0,
            "size_setters": 0,
            "effective_mutations": 0,
            "blend_operations": 0,
            "modifier_mutations": 0,
            "timeline_modified": False,
            "current_target": phase3_target_count,
            "current_other": phase3_other_count,
            "missing": phase3_missing_count,
            "ambiguous": 0,
            "structural_topology_unchanged": phase3_structure == expected_structure,
        }
        write_json(output_dir / "phase3_idempotency_report.json", phase3)
        if not phase3["ok"]:
            raise ValueError("phase3_read_only_validation")

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
                "technical_verdict": "TECHNICAL_PASS — MANUAL_VISUAL_APPROVAL_REQUIRED",
                "exact_two_allowlisted_corrections_proven_from_source_run": True,
                "phase2_current_target": 36,
                "phase2_current_other": 0,
                "phase3": phase3,
                "structural_topology_unchanged": True,
                "protected_state_unchanged": True,
            }
        )
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
