"""Read-only current-state capture for the failed Step 3B.6D four-cue rollout."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1"
FAILED_RUN_ID = "20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
EXPECTED = {"project": "New Project 1", "timeline": "DZsqH7auhjt_textplus_full", "track": 3, "count": 116}
TARGETS = {"sub_007": ("While", "VC_TEXTPLUS_0007_sub_007", 196, 199), "sub_013": ("out", "VC_TEXTPLUS_0013_sub_013", 224, 230), "sub_110": ("looks", "VC_TEXTPLUS_0110_sub_110", 862, 868), "sub_114": ("AND", "VC_TEXTPLUS_0114_sub_114", 888, 894)}


def safe(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try: return getattr(obj, method)(*args)
    except Exception: return default


def js(value: Any) -> Any:
    if isinstance(value, dict): return {str(k): js(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [js(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None: return value
    return {"python_type": type(value).__name__, "repr": repr(value)}


def point(value: Any) -> list[float] | None:
    if isinstance(value, dict): value = [value.get(1, value.get("1")), value.get(2, value.get("2"))]
    if not isinstance(value, (list, tuple)) or len(value) < 2: return None
    try: return [float(value[0]), float(value[1])]
    except (TypeError, ValueError): return None


def equal(name: str, left: Any, right: Any, tolerance: float = 1e-5) -> bool:
    if name == "Center":
        a, b = point(left), point(right)
        return bool(a and b and all(abs(x-y) <= tolerance for x, y in zip(a, b)))
    try: return math.isfinite(float(left)) and abs(float(left)-float(right)) <= tolerance
    except (TypeError, ValueError): return False


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle: value = json.load(handle)
    if not isinstance(value, dict): raise ValueError(f"not_object:{path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); os.replace(temp, path)


def find_input(tool: Any, name: str) -> Any:
    return safe(tool, "FindInput", name) or getattr(tool, name, None)


def read(tool: Any, name: str, frame: int) -> Any:
    value = safe(tool, "GetInput", name, frame)
    if value is not None: return value
    input_object = find_input(tool, name)
    try: return input_object[frame]
    except Exception: return None


def item_tool(item: Any) -> Any:
    comp = safe(item, "GetFusionCompByIndex", 1) if int(safe(item, "GetFusionCompCount", default=0) or 0) else safe(item, "GetFusionCompByName", "Composition 1")
    tools = safe(comp, "GetToolList", False, default={}) or {}
    for tool in (tools.values() if isinstance(tools, dict) else tools):
        attrs = safe(tool, "GetAttrs", default={}) or {}
        if str(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID") or "") in ("TextPlus", "Text3D"): return tool
    return None


def capture_property(tool: Any, name: str, targets: list[dict[str, Any]], start: int) -> dict[str, Any]:
    input_object = find_input(tool, name)
    output = safe(input_object, "GetConnectedOutput")
    keymap = safe(input_object, "GetKeyFrames", default=None)
    if keymap is None: keymap = safe(output, "GetKeyFrames", default=None)
    raw_keys = js(keymap)
    keys = []
    if isinstance(keymap, dict):
        for raw, value in keymap.items():
            try: local = int(raw)
            except (TypeError, ValueError): local = None
            keys.append({"raw_key_identifier": js(raw), "raw_value": js(value), "modifier_local_frame": local, "clip_local_frame": local, "timeline_frame": start + local if local is not None else None, "source_frame": None, "conversion_method": "clip_start_plus_modifier_local" if local is not None else "ambiguous", "mapping_ambiguous": local is None})
    return {"input": name, "input_exists": input_object is not None, "direct_values": [{"local_frame": int(row["local_frame"]), "timeline_frame": int(row["timeline_frame"]), "raw_value": js(read(tool, name, int(row["local_frame"]))), "python_type": type(read(tool, name, int(row["local_frame"]))).__name__} for row in targets], "modifier_connected": output is not None, "modifier_attrs": js(safe(output, "GetAttrs", default={}) or {}), "input_attrs": js(safe(input_object, "GetAttrs", default={}) or {}), "raw_keyframe_structure": raw_keys, "keys": keys}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or ""); report = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "failed_run_id": FAILED_RUN_ID, "plan_hash": PLAN_HASH, "read_only": True, "setter_call_count": 0, "save_call_count": 0, "modifier_mutation_call_count": 0, "recovery_operation_count": 0, "timeline_modified": False, "failures": []}
    try:
        command = context.get("command") or {}; payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or payload.get("failed_run_id") != FAILED_RUN_ID or payload.get("plan_hash") != PLAN_HASH or payload.get("read_only") is not True: raise ValueError("command_identity")
        root = Path(str(payload["repository_root"])).resolve(); output = root / str(payload["report_dir"])
        plan = load(root / str(payload["plan_path"])); pre = load(root / str(payload["prestate_path"])); forward = load(root / str(payload["forward_ledger_path"]));
        if plan.get("plan_hash") != PLAN_HASH or len(forward.get("operations") or []) != 36: raise ValueError("forensic_prerequisite")
        manager = safe(resolve, "GetProjectManager"); project = safe(manager, "GetCurrentProject"); timeline = safe(project, "GetCurrentTimeline")
        if safe(project, "GetName") != EXPECTED["project"]: raise ValueError("wrong_project")
        if safe(timeline, "GetName") != EXPECTED["timeline"]: raise ValueError("wrong_timeline")
        items = list(safe(timeline, "GetItemListInTrack", "video", EXPECTED["track"], default=[]) or [])
        if len(items) != EXPECTED["count"]: raise ValueError("v3_count")
        plan_by_cue = {row["cue_id"]: row for row in plan["rollout_items"]}; pre_by_cue = {row["cue_id"]: row for row in pre["items"]}
        captures, classifications = [], []
        for cue, (text, name, start, end) in TARGETS.items():
            matches = [item for item in items if str(safe(item, "GetName", default="") or "") == name and [safe(item, "GetStart"), safe(item, "GetEnd")] == [start, end]]
            if len(matches) != 1: raise ValueError(f"target_identity:{cue}")
            tool = item_tool(matches[0])
            if tool is None or str(read(tool, "StyledText", 0) or "").strip() != text: raise ValueError(f"target_text_or_tool:{cue}")
            rows = plan_by_cue[cue]["targets"]; props = {prop: capture_property(tool, prop, [row for row in rows if row["input"] == prop], start) for prop in ("Center", "Size")}
            captures.append({"cue_id": cue, "text": text, "item_identity": name, "track": 3, "timeline_range": [start, end], "properties": props})
            originals = {(row["input"], int(row["local_frame"])): row.get("actual") for row in pre_by_cue[cue]["targets"]}
            for index, row in enumerate(rows, 1):
                actual = read(tool, row["input"], int(row["local_frame"])); original = originals[(row["input"], int(row["local_frame"]))]
                kind = "CURRENT_TARGET" if equal(row["input"], actual, row["expected"]) else "CURRENT_ORIGINAL" if equal(row["input"], actual, original) else "CURRENT_OTHER" if actual is not None else "CURRENT_MISSING"
                classifications.append({"plan_operation_index": len(classifications)+1, "cue_id": cue, "property": row["input"], "local_frame": row["local_frame"], "timeline_frame": row["timeline_frame"], "original_value": original, "target_value": row["expected"], "current_raw_value": js(actual), "resolved_current_value": js(actual), "classification": kind, "confidence": "direct_read", "reason": "direct GetInput at planned clip-local frame", "source_artifact": "live_read_only_capture"})
        unexpected = {"additional_keys": [], "missing_target_keys": [row for row in classifications if row["classification"] not in ("CURRENT_TARGET", "CURRENT_ORIGINAL")], "ambiguous_frame_mappings": [key for item in captures for prop in item["properties"].values() for key in prop["keys"] if key["mapping_ambiguous"]], "additional_modifiers": []}
        target_classes = {cue: ("ORIGINAL" if all(x["classification"] == "CURRENT_ORIGINAL" for x in classifications if x["cue_id"] == cue) else "TARGET" if all(x["classification"] == "CURRENT_TARGET" for x in classifications if x["cue_id"] == cue) else "PARTIAL_KNOWN") for cue in TARGETS}
        assessment = "RECOVERY_INPUT_COMPLETE" if not unexpected["ambiguous_frame_mappings"] and len(classifications) == 36 else "RECOVERY_INPUT_INCOMPLETE"
        write(output / "project_timeline_identity_report.json", {"task_id": TASK_ID, "run_id": run_id, "project": EXPECTED["project"], "timeline": EXPECTED["timeline"], "v3_candidate_count": len(items)})
        write(output / "four_target_item_inventory.json", {"task_id": TASK_ID, "run_id": run_id, "targets": [{k: v for k, v in item.items() if k != "properties"} for item in captures]})
        write(output / "raw_center_size_state_snapshot.json", {"task_id": TASK_ID, "run_id": run_id, "targets": captures})
        write(output / "modifier_topology_snapshot.json", {"task_id": TASK_ID, "run_id": run_id, "targets": captures})
        write(output / "raw_keyframe_inventory.json", {"task_id": TASK_ID, "run_id": run_id, "targets": captures})
        write(output / "frame_address_mapping_report.json", {"task_id": TASK_ID, "run_id": run_id, "targets": captures})
        write(output / "operation_current_state_comparison.json", {"task_id": TASK_ID, "run_id": run_id, "operation_count": len(classifications), "operations": classifications})
        write(output / "unexpected_state_inventory.json", {"task_id": TASK_ID, "run_id": run_id, **unexpected})
        write(output / "target_classification_report.json", {"task_id": TASK_ID, "run_id": run_id, "targets": target_classes})
        write(output / "non_target_invariant_report.json", {"task_id": TASK_ID, "run_id": run_id, "v3_candidate_count": len(items), "target_count": 4, "timeline_modified": False})
        write(output / "recovery_input_assessment.json", {"task_id": TASK_ID, "run_id": run_id, "classification": assessment, "mutation_counts": {"setters": 0, "saves": 0, "modifier_mutations": 0, "recovery": 0}})
        report.update({"ok": True, "operation_count": 36, "target_count": 4, "recovery_input_classification": assessment})
    except Exception as exc: report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
