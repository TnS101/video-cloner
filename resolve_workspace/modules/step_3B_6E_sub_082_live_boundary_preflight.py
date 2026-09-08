"""Live, read-only Resolve capability and adjacency preflight for sub_082.

This module is intentionally non-mutating. It inspects the current TimelineItem
API surface, captures the target/neighbor ranges, verifies the protected Step 3C
neighbor, and proves that all observed state is unchanged within the run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable

TASK_ID = "DZSQH7AUHJT_STEP_3B_6E_SUB_082_LIVE_BOUNDARY_PREFLIGHT_V1"
SOURCE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6E_V3_BOUNDARY_TIMING_STRATEGY_ASSESSMENT_V3"
SOURCE_RUN_ID = "20260803T135506176634Z_1ef963ee80834a36b8965fc01bad065e"
SOURCE_REPORT_REL = f".agent/reports/{SOURCE_TASK_ID}/{SOURCE_RUN_ID}"
ANIMATION_TARGETS_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_animation_step_3C_source_targets.json"
EXPECTED = {
    "project": "New Project 1",
    "timeline": "DZsqH7auhjt_textplus_full",
    "video_track": 3,
    "v3_count": 116,
}
ITEMS = {
    "sub_081": {
        "cue_id": "sub_081",
        "name": "VC_TEXTPLUS_0081_sub_081",
        "text": "the",
        "start": 646,
        "end": 649,
        "step_3C_protected": True,
    },
    "sub_082": {
        "cue_id": "sub_082",
        "name": "VC_TEXTPLUS_0082_sub_082",
        "text": "blocks.",
        "start": 649,
        "end": 656,
        "step_3C_protected": False,
    },
    "sub_083": {
        "cue_id": "sub_083",
        "name": "VC_TEXTPLUS_0083_sub_083",
        "text": "That's",
        "start": 659,
        "end": 665,
        "step_3C_protected": False,
    },
}
SOURCE_VISIBILITY = {
    "cue_id": "sub_082",
    "first_visible_frame": 649,
    "last_visible_frame": 656,
    "expected_visible_frames": list(range(649, 657)),
    "dense_visible_frame_coverage_complete": True,
}
PROPOSED_OPERATION = {
    "field": "end_frame",
    "from": 656,
    "to": 657,
    "delta_frames": 1,
}
GETTER_METHODS = ("GetStart", "GetEnd", "GetDuration", "GetProperty")
MUTATION_METHODS = ("SetStart", "SetEnd", "SetProperty")
CAPABILITY_METHODS = GETTER_METHODS + MUTATION_METHODS
V3_NAME_RE = re.compile(r"^VC_TEXTPLUS_(?P<index>\d+)_(?P<cue>sub_\d+)$", re.IGNORECASE)
TECHNICAL_VERDICT = "LIVE_READ_ONLY_BOUNDARY_PREFLIGHT_COMPLETE"
ALLOWED_CLASSIFICATIONS = {
    "DIRECT_END_SETTER_EXPOSED_PERSISTENCE_ROLLBACK_UNPROVEN",
    "GENERIC_SETTER_EXPOSED_BOUNDARY_CONTRACT_UNPROVEN",
    "NO_BOUNDARY_MUTATION_API_SURFACE_EXPOSED",
}


def safe(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception:
        return default


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def point(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        value = [value.get(1, value.get("1")), value.get(2, value.get("2"))]
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x = as_float(value[0])
        y = as_float(value[1])
        if x is not None and y is not None:
            return [x, y]
    return None


def values_match(input_name: str, actual: Any, expected: Any, tolerance: float = 1e-5) -> bool:
    if input_name == "Center":
        left = point(actual)
        right = point(expected)
        return bool(left and right and all(abs(a - b) <= tolerance for a, b in zip(left, right)))
    left = as_float(actual)
    right = as_float(expected)
    return left is not None and right is not None and abs(left - right) <= tolerance


def item_snapshot(item: Any) -> dict[str, Any]:
    return {
        "name": str(safe(item, "GetName", default="") or ""),
        "start": as_int(safe(item, "GetStart")),
        "end": as_int(safe(item, "GetEnd")),
    }


def input_for(tool: Any, input_name: str) -> Any:
    return safe(tool, "FindInput", input_name) or getattr(tool, input_name, None)


def read_input(tool: Any, input_name: str, frame: int) -> Any:
    input_object = input_for(tool, input_name)
    if input_object is not None:
        try:
            return input_object[frame]
        except Exception:
            pass
    return safe(tool, "GetInput", input_name, frame)


def text_tool(item: Any) -> Any:
    count = int(safe(item, "GetFusionCompCount", default=0) or 0)
    comp = safe(item, "GetFusionCompByIndex", 1) if count else None
    if comp is None:
        names = safe(item, "GetFusionCompNameList", default=[]) or []
        for name in names:
            comp = safe(item, "GetFusionCompByName", name)
            if comp is not None:
                break
    tools = safe(comp, "GetToolList", False, default={}) or {}
    if isinstance(tools, dict):
        for tool in tools.values():
            attrs = safe(tool, "GetAttrs", default={}) or {}
            if str(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID") or "") in {"TextPlus", "Text3D"}:
                return tool
    return None


def full_v3_inventory(items: Iterable[Any]) -> list[dict[str, Any]]:
    rows = [item_snapshot(item) for item in items]
    rows.sort(key=lambda row: (row["start"] if row["start"] is not None else 10**9, row["end"] if row["end"] is not None else 10**9, row["name"]))
    return rows


def find_live_context(resolve: Any) -> tuple[Any, Any, list[Any], dict[str, Any], dict[str, Any]]:
    manager = safe(resolve, "GetProjectManager")
    project = safe(manager, "GetCurrentProject")
    timeline = safe(project, "GetCurrentTimeline")
    identity = {
        "project": str(safe(project, "GetName", default="") or ""),
        "timeline": str(safe(timeline, "GetName", default="") or ""),
        "video_track": EXPECTED["video_track"],
    }
    if identity["project"] != EXPECTED["project"] or identity["timeline"] != EXPECTED["timeline"]:
        raise ValueError("project_timeline_identity")
    items = list(safe(timeline, "GetItemListInTrack", "video", EXPECTED["video_track"], default=[]) or [])
    if len(items) != EXPECTED["v3_count"]:
        raise ValueError(f"v3_count:{len(items)}")
    snapshots = [item_snapshot(item) for item in items]
    if any(not V3_NAME_RE.match(row["name"]) for row in snapshots):
        raise ValueError("non_v3_item_on_expected_track")
    if len({row["name"] for row in snapshots}) != EXPECTED["v3_count"]:
        raise ValueError("duplicate_v3_name")
    found: dict[str, Any] = {}
    live_rows: dict[str, Any] = {}
    for cue_id, expected in ITEMS.items():
        matches = [
            item
            for item in items
            if str(safe(item, "GetName", default="") or "") == expected["name"]
            and as_int(safe(item, "GetStart")) == expected["start"]
            and as_int(safe(item, "GetEnd")) == expected["end"]
        ]
        if len(matches) != 1:
            raise ValueError(f"item_identity:{cue_id}:{len(matches)}")
        tool = text_tool(matches[0])
        actual_text = str(read_input(tool, "StyledText", 0) or "").strip() if tool is not None else ""
        if tool is None or actual_text != expected["text"]:
            raise ValueError(f"text_identity:{cue_id}:{actual_text!r}")
        found[cue_id] = matches[0]
        live_rows[cue_id] = {**item_snapshot(matches[0]), "cue_id": cue_id, "text": actual_text}
    return project, timeline, items, found, {"identity": identity, "items": live_rows}


def adjacency_snapshot(items: list[Any], found: dict[str, Any]) -> dict[str, Any]:
    inventory = full_v3_inventory(items)
    by_name = {row["name"]: index for index, row in enumerate(inventory)}
    target_name = ITEMS["sub_082"]["name"]
    index = by_name.get(target_name)
    if index is None or index <= 0 or index >= len(inventory) - 1:
        raise ValueError("target_not_internal_to_v3_inventory")
    previous = inventory[index - 1]
    target = inventory[index]
    following = inventory[index + 1]
    if previous != {"name": ITEMS["sub_081"]["name"], "start": 646, "end": 649}:
        raise ValueError(f"previous_neighbor:{previous}")
    if target != {"name": target_name, "start": 649, "end": 656}:
        raise ValueError(f"target_range:{target}")
    if following != {"name": ITEMS["sub_083"]["name"], "start": 659, "end": 665}:
        raise ValueError(f"next_neighbor:{following}")
    proposed_start = target["start"]
    proposed_end = PROPOSED_OPERATION["to"]
    overlaps = [
        row
        for row in inventory
        if row["name"] != target_name
        and row["start"] is not None
        and row["end"] is not None
        and row["start"] < proposed_end
        and row["end"] > proposed_start
    ]
    result = {
        "ok": not overlaps,
        "previous": {**previous, "cue_id": "sub_081"},
        "target": {**target, "cue_id": "sub_082", "text": "blocks."},
        "next": {**following, "cue_id": "sub_083"},
        "current_gap_after_target_frames": following["start"] - target["end"],
        "proposed_gap_after_target_frames": following["start"] - proposed_end,
        "proposed_operation": PROPOSED_OPERATION,
        "proposed_range": [proposed_start, proposed_end],
        "proposed_overlap_count": len(overlaps),
        "proposed_overlaps": overlaps,
        "previous_contiguous_with_target": previous["end"] == target["start"],
        "next_starts_after_proposed_end": following["start"] >= proposed_end,
    }
    if (
        not result["ok"]
        or result["current_gap_after_target_frames"] != 3
        or result["proposed_gap_after_target_frames"] != 2
        or result["previous_contiguous_with_target"] is not True
        or result["next_starts_after_proposed_end"] is not True
    ):
        raise ValueError("adjacency_contract")
    return result


def method_capability(obj: Any, method_name: str) -> dict[str, Any]:
    names: set[str] = set()
    dir_error = None
    try:
        names = set(dir(obj))
    except Exception as exc:
        dir_error = f"{type(exc).__name__}: {exc}"
    attribute = None
    getattr_error = None
    try:
        attribute = getattr(obj, method_name)
    except Exception as exc:
        getattr_error = f"{type(exc).__name__}: {exc}"
    doc = getattr(attribute, "__doc__", None) if attribute is not None else None
    return {
        "method": method_name,
        "listed_by_dir": method_name in names,
        "dir_error": dir_error,
        "getattr_succeeded": getattr_error is None and attribute is not None,
        "getattr_error": getattr_error,
        "callable": callable(attribute),
        "attribute_type": type(attribute).__name__ if attribute is not None else None,
        "attribute_repr": repr(attribute)[:500] if attribute is not None else None,
        "doc": str(doc)[:1000] if doc else None,
        "invoked": False,
    }


def capability_inventory(item: Any) -> dict[str, Any]:
    methods = [method_capability(item, name) for name in CAPABILITY_METHODS]
    by_name = {row["method"]: row for row in methods}
    set_end = bool(by_name["SetEnd"]["callable"])
    set_property = bool(by_name["SetProperty"]["callable"])
    if set_end:
        classification = "DIRECT_END_SETTER_EXPOSED_PERSISTENCE_ROLLBACK_UNPROVEN"
        candidate_surface = "SetEnd"
    elif set_property:
        classification = "GENERIC_SETTER_EXPOSED_BOUNDARY_CONTRACT_UNPROVEN"
        candidate_surface = "SetProperty"
    else:
        classification = "NO_BOUNDARY_MUTATION_API_SURFACE_EXPOSED"
        candidate_surface = None
    result = {
        "ok": classification in ALLOWED_CLASSIFICATIONS,
        "inspection_policy": "Attribute discovery only; no discovered method is invoked.",
        "methods": methods,
        "classification": classification,
        "candidate_surface": candidate_surface,
        "direct_end_setter_callable": set_end,
        "generic_setter_callable": set_property,
        "mutation_method_invocation_count": 0,
        "persistence_proven": False,
        "rollback_proven": False,
        "mutation_authorized": False,
    }
    return result


def normalize_keyframes(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return dict(sorted(((str(key), json_safe(item)) for key, item in value.items()), key=lambda pair: pair[0]))


def fusion_baseline(item: Any) -> dict[str, Any]:
    tool = text_tool(item)
    if tool is None:
        raise ValueError("target_text_tool_missing")
    inputs: dict[str, Any] = {}
    for input_name in ("Center", "Size"):
        input_object = input_for(tool, input_name)
        output = safe(input_object, "GetConnectedOutput") if input_object is not None else None
        inputs[input_name] = {
            "frame_0": json_safe(read_input(tool, input_name, 0)),
            "frame_6": json_safe(read_input(tool, input_name, 6)),
            "modifier_connected": output is not None,
            "input_attrs": json_safe(safe(input_object, "GetAttrs", default={}) or {}),
            "output_attrs": json_safe(safe(output, "GetAttrs", default={}) or {}),
            "raw_keyframes": normalize_keyframes(safe(input_object, "GetKeyFrames", default={}) or {}),
        }
    return {
        "item": item_snapshot(item),
        "styled_text": str(read_input(tool, "StyledText", 0) or "").strip(),
        "inputs": inputs,
    }


def protected_window_audit(root: Path, found: dict[str, Any]) -> dict[str, Any]:
    document = load_json(root / ANIMATION_TARGETS_REL)
    rows = document.get("items") or []
    index = {str(row.get("cue_id") or ""): row for row in rows if isinstance(row, dict)}
    protected_ids = {cue_id for cue_id in ITEMS if cue_id in index}
    if protected_ids != {"sub_081"}:
        raise ValueError(f"protected_window_identity:{sorted(protected_ids)}")
    source = index["sub_081"]
    targets = source.get("targets") or []
    if len(targets) != 2 or {(row.get("input"), int(row.get("local_frame"))) for row in targets} != {("Center", 0), ("Center", 2)}:
        raise ValueError("sub_081_protected_target_contract")
    tool = text_tool(found["sub_081"])
    input_object = input_for(tool, "Center")
    connected = safe(input_object, "GetConnectedOutput") is not None if input_object is not None else False
    live_rows = []
    for target in targets:
        frame = int(target["local_frame"])
        actual = read_input(tool, "Center", frame)
        live_rows.append({
            "input": "Center",
            "local_frame": frame,
            "expected": target.get("expected"),
            "actual": json_safe(actual),
            "matched": values_match("Center", actual, target.get("expected")),
        })
    ok = connected and all(row["matched"] for row in live_rows)
    if not ok:
        raise ValueError("sub_081_live_protected_target_mismatch")
    return {
        "ok": True,
        "protected_cues_in_window": ["sub_081"],
        "target_sub_082_protected": False,
        "next_sub_083_protected": False,
        "sub_081_modifier_connected": connected,
        "sub_081_target_count": 2,
        "sub_081_verified_target_count": sum(1 for row in live_rows if row["matched"]),
        "sub_081_targets": live_rows,
        "protected_target_mutation_count": 0,
    }


def validate_source_assessment(root: Path) -> dict[str, Any]:
    report_dir = root / SOURCE_REPORT_REL
    status = load_json(report_dir / "status.json")
    report = load_json(report_dir / "report.json")
    summary = load_json(report_dir / "strategy_summary.json")
    allowlist = load_json(report_dir / "boundary_probe_candidate_allowlist.json")
    protection = load_json(report_dir / "state_protection_audit.json")
    final_report = (report_dir / "FINAL_REPORT.md").read_text(encoding="utf-8-sig")
    candidate_rows = allowlist.get("candidates") or []
    candidate = candidate_rows[0] if len(candidate_rows) == 1 else {}
    checks = {
        "status": status.get("ok") is True and status.get("stage") == "completed" and status.get("run_id") == SOURCE_RUN_ID,
        "report_identity": report.get("ok") is True and report.get("task_id") == SOURCE_TASK_ID and report.get("run_id") == SOURCE_RUN_ID,
        "classification": report.get("classification") == "ONE_STRUCTURALLY_ISOLATED_BOUNDARY_EXTENSION_CANDIDATE",
        "summary": (summary.get("summary") or {}).get("remaining_accepted_boundary_cue_count") == 41
        and (summary.get("summary") or {}).get("structurally_isolated_candidate_count") == 1,
        "candidate_count": allowlist.get("candidate_count") == 1 and len(candidate_rows) == 1,
        "candidate_identity": candidate.get("cue_id") == "sub_082"
        and candidate.get("name") == ITEMS["sub_082"]["name"]
        and candidate.get("text") == ITEMS["sub_082"]["text"],
        "candidate_ranges": candidate.get("current_range") == [649, 656]
        and candidate.get("proposed_range") == [649, 657]
        and candidate.get("boundary_operations") == [PROPOSED_OPERATION],
        "candidate_safety": candidate.get("live_read_only_preflight_required") is True
        and candidate.get("mutation_command_permitted") is False
        and allowlist.get("production_mutation_authorized") is False,
        "source_state_protection": protection.get("ok") is True
        and protection.get("accepted_state_unchanged") is True
        and protection.get("command_inventory_unchanged") is True
        and protection.get("timeline_modified") is False,
        "final_report": "PASS — STEP_3B.6E_V3_BOUNDARY_TIMING_STRATEGY_ASSESSED" in final_report,
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("source_assessment_contract:" + ",".join(failures))
    return {
        "ok": True,
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "checks": checks,
        "candidate": candidate,
        "source_report_semantic_sha256": canonical_json_sha256(report),
        "source_allowlist_semantic_sha256": canonical_json_sha256(allowlist),
    }


def command_inventory(root: Path, exclude_run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        for path in sorted((queue / state).glob("*.json")):
            if exclude_run_id and exclude_run_id in path.name:
                continue
            rows.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha256(path),
            })
    return rows


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": "live_read_only_boundary_preflight",
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "technical_verdict": None,
        "classification": None,
        "boundary_setter_call_count": 0,
        "generic_setter_call_count": 0,
        "set_input_call_count": 0,
        "save_call_count": 0,
        "modifier_mutation_call_count": 0,
        "effective_mutation_count": 0,
        "timeline_modified": False,
        "mutation_authorized": False,
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != "live_read_only_boundary_preflight":
            raise ValueError("command_identity")
        if (
            payload.get("source_task_id") != SOURCE_TASK_ID
            or payload.get("source_run_id") != SOURCE_RUN_ID
            or payload.get("mutation_permitted") is not False
            or payload.get("proposed_operation") != PROPOSED_OPERATION
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
        accepted_path = root / ".agent" / "state" / "latest_accepted.json"
        accepted_before = sha256(accepted_path) if accepted_path.is_file() else None
        if accepted_before != payload.get("accepted_state_sha256"):
            raise ValueError("accepted_state_drift_before")
        source_validation = validate_source_assessment(root)
        write_json(output_dir / "source_assessment_validation.json", source_validation)

        _, _, items_before, found_before, identity_before = find_live_context(resolve)
        inventory_before = full_v3_inventory(items_before)
        inventory_hash_before = canonical_json_sha256(inventory_before)
        adjacency = adjacency_snapshot(items_before, found_before)
        target_fusion_before = fusion_baseline(found_before["sub_082"])
        protected = protected_window_audit(root, found_before)
        capability = capability_inventory(found_before["sub_082"])

        write_json(output_dir / "project_timeline_identity.json", {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            **identity_before,
            "v3_count": len(inventory_before),
        })
        write_json(output_dir / "v3_track_inventory.json", {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            "v3_count": len(inventory_before),
            "unique_name_count": len({row["name"] for row in inventory_before}),
            "semantic_sha256": inventory_hash_before,
            "items": inventory_before,
        })
        write_json(output_dir / "target_adjacency_snapshot.json", {
            "task_id": TASK_ID,
            "run_id": run_id,
            **adjacency,
        })
        write_json(output_dir / "source_visibility_contract.json", {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            **SOURCE_VISIBILITY,
            "current_item_range": [649, 656],
            "proposed_item_range": [649, 657],
            "proposed_operation": PROPOSED_OPERATION,
            "source_assessment_candidate_semantic_sha256": canonical_json_sha256(source_validation["candidate"]),
        })
        write_json(output_dir / "boundary_api_capability_inventory.json", {
            "task_id": TASK_ID,
            "run_id": run_id,
            **capability,
        })
        write_json(output_dir / "protected_target_window_audit.json", {
            "task_id": TASK_ID,
            "run_id": run_id,
            **protected,
        })
        write_json(output_dir / "target_fusion_baseline.json", {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            "before": target_fusion_before,
        })

        # Reacquire and compare after all read-only inspection.
        _, _, items_after, found_after, identity_after = find_live_context(resolve)
        inventory_after = full_v3_inventory(items_after)
        target_fusion_after = fusion_baseline(found_after["sub_082"])
        adjacency_after = adjacency_snapshot(items_after, found_after)
        accepted_after = sha256(accepted_path) if accepted_path.is_file() else None
        non_current_commands_after = command_inventory(root, run_id)
        expected_non_current_commands = payload.get("command_inventory_before_publication")
        audit = {
            "ok": inventory_after == inventory_before
            and target_fusion_after == target_fusion_before
            and adjacency_after == adjacency
            and identity_after == identity_before
            and accepted_after == accepted_before
            and non_current_commands_after == expected_non_current_commands,
            "inventory_semantic_sha256_before": inventory_hash_before,
            "inventory_semantic_sha256_after": canonical_json_sha256(inventory_after),
            "v3_inventory_unchanged": inventory_after == inventory_before,
            "target_fusion_unchanged": target_fusion_after == target_fusion_before,
            "adjacency_unchanged": adjacency_after == adjacency,
            "identity_unchanged": identity_after == identity_before,
            "accepted_state_sha256_before": accepted_before,
            "accepted_state_sha256_after": accepted_after,
            "accepted_state_unchanged": accepted_after == accepted_before,
            "non_current_command_inventory_expected": expected_non_current_commands,
            "non_current_command_inventory_after": non_current_commands_after,
            "non_current_command_inventory_unchanged": non_current_commands_after == expected_non_current_commands,
            "boundary_setter_call_count": 0,
            "generic_setter_call_count": 0,
            "set_input_call_count": 0,
            "save_call_count": 0,
            "modifier_mutation_call_count": 0,
            "effective_mutation_count": 0,
            "timeline_modified": False,
        }
        write_json(output_dir / "mutation_prohibition_audit.json", audit)
        if not audit["ok"]:
            raise ValueError("read_only_state_changed")

        classification = capability["classification"]
        if classification not in ALLOWED_CLASSIFICATIONS:
            raise ValueError("capability_classification")
        next_boundary = (
            "No supported boundary setter was exposed by the current TimelineItem proxy; stop and select a different documented Resolve integration route."
            if classification == "NO_BOUNDARY_MUTATION_API_SURFACE_EXPOSED"
            else "A possible setter surface exists, but persistence and rollback are unproven; a separate reversible one-item mutation probe is required before any production boundary change."
        )
        preflight = {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            "technical_verdict": TECHNICAL_VERDICT,
            "classification": classification,
            "candidate_cue_id": "sub_082",
            "candidate_operation": PROPOSED_OPERATION,
            "live_state_matches_offline_strategy": True,
            "adjacency_safe_for_proposed_range": True,
            "protected_window_verified": True,
            "persistence_proven": False,
            "rollback_proven": False,
            "mutation_authorized": False,
            "next_boundary": next_boundary,
        }
        write_json(output_dir / "preflight_classification.json", preflight)
        write_json(output_dir / "lifecycle_runtime_observation.json", {
            "task_id": TASK_ID,
            "run_id": run_id,
            "running_observed": True,
            "running_command_path": str(running_path.relative_to(root)).replace("\\", "/"),
            "running_command_sha256": sha256(running_path),
        })
        report.update({
            "ok": True,
            "technical_verdict": TECHNICAL_VERDICT,
            "classification": classification,
            "candidate_cue_id": "sub_082",
            "candidate_operation": PROPOSED_OPERATION,
            "v3_count": 116,
            "previous_neighbor": "sub_081",
            "next_neighbor": "sub_083",
            "current_gap_after_target_frames": 3,
            "proposed_gap_after_target_frames": 2,
            "protected_target_verified_count": 2,
            "api_candidate_surface": capability.get("candidate_surface"),
            "persistence_proven": False,
            "rollback_proven": False,
            "accepted_state_unchanged": True,
            "non_current_command_inventory_unchanged": True,
            "next_boundary": next_boundary,
        })
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
