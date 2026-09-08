"""Apply generic post-visual Text+ metrics corrections on an isolated timeline.

The source is the technically successful confirmed-74 repair target. This stage
changes only evidence-authorized Size keys plus semantic protected-composite
text. Center and opacity are read before mutation and must remain identical
after the single save. Twenty-three unresolved structural captions are untouched
and the three already-removed redundant structural rows stay absent.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1"
MODE = "STEP_3E_POST_VISUAL_METRICS_POLISH"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
AUTHORITY_RELATIVE_PATH = "artifacts/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/post_visual_metrics_polish_v1.json"
CONFIRMED_RELATIVE_PATH = "artifacts/DZSQH7AUHJT_STEP_3E_CONFIRMED74_REPAIR_AUTHORITY_V1/confirmed74_repair_authority_v1.json"
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
EXPECTED_PHYSICAL = 114
EXPECTED_REPAIR = 74
EXPECTED_PROTECTED = 17
EXPECTED_UNRESOLVED = 23
EXPECTED_REMOVED = 3


def _module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_previous() -> Any:
    return _module(Path(__file__).with_name("step_3E_confirmed74_isolated_repair_rollout_v1.py"), "vc_confirmed74_for_metrics")


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def scalar_match(actual: Any, expected: float, tolerance: float = 1e-4) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def authority_plans(authority: Mapping[str, Any]) -> Dict[str, Any]:
    if authority.get("task_id") != TASK_ID or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    policy = authority.get("policy") if isinstance(authority.get("policy"), Mapping) else {}
    if policy.get("transcript_timing_authority") is not False:
        raise ValueError("transcript_policy")
    if policy.get("position_mutation_authorized") is not False or policy.get("opacity_mutation_authorized") is not False:
        raise ValueError("mutation_policy")
    if policy.get("per_cue_hardcoded_overrides") is not False or policy.get("screenshot_specific_overrides") is not False:
        raise ValueError("override_policy")
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    for key, expected in {
        "confirmed74_repair_instances": EXPECTED_REPAIR,
        "protected_v4_instances": EXPECTED_PROTECTED,
        "unresolved_preserved": EXPECTED_UNRESOLVED,
        "composite_structural_removed": EXPECTED_REMOVED,
        "expected_physical_textplus_count": EXPECTED_PHYSICAL,
    }.items():
        if summary.get(key) != expected:
            raise ValueError(f"authority_summary:{key}:{summary.get(key)}")
    size = []
    for row in list(authority.get("protected_size_updates") or []) + list(authority.get("repair_size_updates") or []):
        if not isinstance(row, Mapping):
            continue
        window = [int(v) for v in row.get("target_range") or []]
        keys = [dict(v) for v in row.get("size_keys") or [] if isinstance(v, Mapping)]
        if len(window) != 2 or window[1] <= window[0]:
            raise ValueError(f"size_window:{row.get('target_name')}")
        if [int(v["local_frame"]) for v in keys] != list(range(window[1] - window[0])):
            raise ValueError(f"size_dense:{row.get('target_name')}")
        size.append({"instance_id": str(row.get("instance_id") or ""), "target_name": str(row.get("target_name") or ""), "target_range": window, "size_keys": keys})
    text = []
    for row in authority.get("protected_text_updates") or []:
        if not isinstance(row, Mapping):
            continue
        window = [int(v) for v in row.get("target_range") or []]
        if len(window) != 2 or window[1] <= window[0]:
            raise ValueError(f"text_window:{row.get('target_name')}")
        text.append({"instance_id": str(row.get("instance_id") or ""), "target_name": str(row.get("target_name") or ""), "target_range": window, "old_text": str(row.get("old_text") or ""), "new_text": str(row.get("new_text") or "")})
    names = [row["target_name"] for row in size]
    if not names or any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("size_scope")
    text_names = [row["target_name"] for row in text]
    if any(not name for name in text_names) or len(text_names) != len(set(text_names)):
        raise ValueError("text_scope")
    return {"size": size, "text": text}


def capture_preserved_inputs(base: Any, item: Any, local_frames: Sequence[int]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        raise RuntimeError("comp_or_text_tool")
    frames = sorted(set(int(v) for v in local_frames))
    return {
        "center": [{"local_frame": frame, "value": base.json_safe(base.read_input(tool, "Center", frame))} for frame in frames],
        "opacity1": [{"local_frame": frame, "value": base.json_safe(base.read_input(tool, "Opacity1", frame))} for frame in frames],
        "font": str(base.read_input(tool, "Font", 0) or ""),
        "style": str(base.read_input(tool, "Style", 0) or ""),
        "text": str(base.text_readback(tool)),
    }


def same_value(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1e-4
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return False
        return all(same_value(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
    return str(left) == str(right)


def verify_preserved(before: Mapping[str, Any], after: Mapping[str, Any], expected_text: str | None = None) -> Dict[str, bool]:
    checks = {
        "center": same_value(before.get("center"), after.get("center")),
        "opacity1": same_value(before.get("opacity1"), after.get("opacity1")),
        "font": str(before.get("font") or "") == str(after.get("font") or ""),
        "style": str(before.get("style") or "") == str(after.get("style") or ""),
    }
    if expected_text is None:
        checks["text"] = str(before.get("text") or "") == str(after.get("text") or "")
    else:
        checks["text"] = str(after.get("text") or "") == expected_text
    return checks


def apply_size(base: Any, visual: Any, pilot: Any, item: Any, plan: Mapping[str, Any]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        return {"ok": False, "error": "comp_or_text_tool"}
    modifier = visual.ensure_modifier(tool, "Size", "BezierSpline")
    write = pilot.write_scalar_series(tool, "Size", plan["size_keys"], "value") if modifier.get("ok") else {"ok": False, "error": "size_modifier"}
    return {"modifier": modifier, "write": write, "ok": bool(modifier.get("ok") and write.get("ok"))}


def apply_text(base: Any, pilot: Any, item: Any, text: str) -> Dict[str, Any]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        return {"ok": False, "error": "comp_or_text_tool"}
    return pilot.set_static_input(tool, "StyledText", text)


def read_size(base: Any, item: Any, keys: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        return {"ok": False, "error": "comp_or_text_tool"}
    rows = []
    for key in keys:
        frame = int(key["local_frame"])
        expected = float(key["value"])
        actual = base.read_input(tool, "Size", frame)
        rows.append({"local_frame": frame, "expected": expected, "actual": base.json_safe(actual), "matched": scalar_match(actual, expected)})
    return {"rows": rows, "ok": bool(rows and all(row["matched"] for row in rows))}


def cleanup_failure(base: Any, project_manager: Any, project: Any, media_pool: Any, source: Any, target_created: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        target = base.find_timeline(project, TARGET_TIMELINE_NAME) if project is not None else None
        if source is not None and project is not None:
            value, call = base.direct_call(project, "SetCurrentTimeline", source)
            result["restore_source"] = call
            if not value:
                result["errors"].append("restore_source")
        if target_created and target is not None and media_pool is not None:
            value, call = base.direct_call(media_pool, "DeleteTimelines", [target])
            result["delete_target"] = call
            if not value:
                result["errors"].append("delete_target")
        if target_created and project_manager is not None:
            save = base.save_project(project_manager)
            result["save"] = save
            result["save_call_count"] = 1
            if not save.get("success"):
                result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc))
        result["traceback"] = traceback.format_exc()
    result["ok"] = not result["errors"]
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    previous = load_previous()
    old = previous.load_old()
    full, pilot, v6, base, media, visual = old.load_runtime()
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
        raise ValueError("command_identity")
    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    report: Dict[str, Any] = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "ok": False,
        "source_timeline_name": SOURCE_TIMELINE_NAME, "target_timeline_name": TARGET_TIMELINE_NAME,
        "save_call_count": 0, "position_updates": 0, "opacity_updates": 0,
        "visual_approval_required": True, "further_rollout_authorized": False, "failures": [],
    }
    project_manager = project = media_pool = None
    source = None
    source_before: List[Dict[str, Any]] = []
    source_unique_id = ""
    target_created = False
    try:
        source_contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")
        authority = load_json(root / AUTHORITY_RELATIVE_PATH)
        plans = authority_plans(authority)
        confirmed = load_json(root / CONFIRMED_RELATIVE_PATH)
        confirmed_partition = previous.authority_partition(confirmed)
        repair_names = {str(row["target_name"]) for row in confirmed_partition["repair"]}
        unresolved_names = {str(row["target_name"]) for row in confirmed_partition["unresolved"]}
        composite_names = {str(row["target_name"]) for row in confirmed_partition["composite"]}
        protected_names = {str(row["target_name"]) for row in confirmed_partition["protected"]}
        expected_structural = sorted(repair_names | unresolved_names)
        expected_visual = sorted(protected_names)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_timeline_exists")
        source_unique_id = base.timeline_unique_id(source)
        source_before = full.timeline_inventory(source)
        if sorted(full.source_textplus_names(source)) != expected_structural:
            raise RuntimeError("source_structural_names")
        if sorted(full.visual_first_names(source)) != expected_visual:
            raise RuntimeError("source_protected_names")
        if any(name in full.source_textplus_names(source) for name in composite_names):
            raise RuntimeError("composite_present")
        if len(expected_structural) + len(expected_visual) != EXPECTED_PHYSICAL:
            raise RuntimeError("physical_partition")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2")

        size_by_name = {str(row["target_name"]): row for row in plans["size"]}
        text_by_name = {str(row["target_name"]): row for row in plans["text"]}
        mutation_names = sorted(set(size_by_name) | set(text_by_name))
        if not set(mutation_names) <= (repair_names | protected_names):
            raise RuntimeError("mutation_scope")
        if set(mutation_names) & unresolved_names:
            raise RuntimeError("unresolved_scope")

        before_inputs: Dict[str, Any] = {}
        for name in mutation_names:
            _, item = base.find_named_item(source, name)
            if item is None:
                raise RuntimeError(f"source_item:{name}")
            plan = size_by_name.get(name) or text_by_name.get(name)
            duration = int(plan["target_range"][1]) - int(plan["target_range"][0])
            before_inputs[name] = capture_preserved_inputs(base, item, range(duration))
            if name in text_by_name and before_inputs[name]["text"] != str(text_by_name[name]["old_text"]):
                raise RuntimeError(f"text_preimage:{name}")

        base.write_json(report_dir / "metrics_preflight.json", {
            "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "resolve_calls": resolve_calls,
            "source_unique_id": source_unique_id, "source_inventory": source_before,
            "size_update_count": len(plans["size"]), "text_update_count": len(plans["text"]),
            "mutation_names": mutation_names, "unresolved_count": len(unresolved_names),
            "position_updates": 0, "opacity_updates": 0, "ok": True,
        })

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")

        applications = []
        for name in mutation_names:
            _, item = base.find_named_item(target, name)
            if item is None:
                raise RuntimeError(f"target_item:{name}")
            row: Dict[str, Any] = {"target_name": name, "size": None, "text": None, "ok": True}
            if name in size_by_name:
                row["size"] = apply_size(base, visual, pilot, item, size_by_name[name])
                row["ok"] = row["ok"] and row["size"].get("ok") is True
            if name in text_by_name:
                row["text"] = apply_text(base, pilot, item, str(text_by_name[name]["new_text"]))
                row["ok"] = row["ok"] and row["text"].get("ok") is True
            applications.append(row)
            if not row["ok"]:
                raise RuntimeError(f"application:{name}")
        base.write_json(report_dir / "metrics_application.json", {"rows": applications, "ok": len(applications) == len(mutation_names) and all(row["ok"] for row in applications)})

        pre_save_rows = []
        for name in mutation_names:
            _, item = base.find_named_item(target, name)
            if item is None:
                raise RuntimeError(f"pre_save_item:{name}")
            plan = size_by_name.get(name) or text_by_name.get(name)
            duration = int(plan["target_range"][1]) - int(plan["target_range"][0])
            after = capture_preserved_inputs(base, item, range(duration))
            expected_text = str(text_by_name[name]["new_text"]) if name in text_by_name else None
            preserve = verify_preserved(before_inputs[name], after, expected_text)
            size = read_size(base, item, size_by_name[name]["size_keys"]) if name in size_by_name else {"ok": True, "rows": []}
            ok = all(preserve.values()) and size.get("ok") is True
            pre_save_rows.append({"target_name": name, "preserved": preserve, "size": size, "ok": ok})
            if not ok:
                raise RuntimeError(f"pre_save_readback:{name}")
        base.write_json(report_dir / "metrics_readback_before_save.json", {"rows": pre_save_rows, "ok": all(row["ok"] for row in pre_save_rows)})

        save = base.save_project(project_manager)
        report["save_call_count"] = 1
        if not save.get("success"):
            raise RuntimeError("save")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("reacquire")
        persistent_rows = []
        for name in mutation_names:
            _, item = base.find_named_item(target_after, name)
            if item is None:
                persistent_rows.append({"target_name": name, "ok": False, "error": "missing"})
                continue
            plan = size_by_name.get(name) or text_by_name.get(name)
            duration = int(plan["target_range"][1]) - int(plan["target_range"][0])
            after = capture_preserved_inputs(base, item, range(duration))
            expected_text = str(text_by_name[name]["new_text"]) if name in text_by_name else None
            preserve = verify_preserved(before_inputs[name], after, expected_text)
            size = read_size(base, item, size_by_name[name]["size_keys"]) if name in size_by_name else {"ok": True, "rows": []}
            persistent_rows.append({"target_name": name, "preserved": preserve, "size": size, "ok": all(preserve.values()) and size.get("ok") is True})

        source_after_inventory = full.timeline_inventory(source_after)
        target_after_inventory = full.timeline_inventory(target_after)
        persistent_checks = {
            "source_timeline_unchanged": base.timeline_unique_id(source_after) == source_unique_id and full.stable_inventory(source_after_inventory) == full.stable_inventory(source_before),
            "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
            "target_retained": base.timeline_name(target_after) == TARGET_TIMELINE_NAME,
            "all_metrics_persisted": len(persistent_rows) == len(mutation_names) and all(row.get("ok") for row in persistent_rows),
            "structural_names_exact": sorted(full.source_textplus_names(target_after)) == expected_structural,
            "protected_names_exact": sorted(full.visual_first_names(target_after)) == expected_visual,
            "composite_rows_absent": not any(name in full.source_textplus_names(target_after) for name in composite_names),
            "physical_textplus_count": len(full.source_textplus_names(target_after)) + len(full.visual_first_names(target_after)) == EXPECTED_PHYSICAL,
            "v2_empty": not full.track_two_item_names(target_after),
            "inventory_unchanged": full.stable_inventory(target_after_inventory) == full.stable_inventory(source_before),
        }
        persistent = {
            "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "reacquire_calls": reacquire_calls,
            "rows": persistent_rows, "checks": persistent_checks, "save": save,
            "size_update_count": len(plans["size"]), "text_update_count": len(plans["text"]),
            "position_update_count": 0, "opacity_update_count": 0,
            "expected_physical_textplus_count": EXPECTED_PHYSICAL,
            "visual_approval_required": True, "fade_appearance_reassessment_deferred_until_baked_original_is_removed": True,
            "further_rollout_authorized": False, "ok": all(persistent_checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")
        report.update({
            "ok": True, "size_update_count": len(plans["size"]), "text_update_count": len(plans["text"]),
            "final_textplus_count": EXPECTED_PHYSICAL, "source_timeline_unchanged": True,
            "accepted_state_unchanged": True, "target_timeline_kept": True,
            "position_updates": 0, "opacity_updates": 0,
        })
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if target_created and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_failure(base, project_manager, project, media_pool, source, target_created)
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
        return report
