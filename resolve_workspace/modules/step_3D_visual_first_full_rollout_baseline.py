"""Build the full-reel visual-first baseline used for later visual polishing.

This task deliberately does not claim visual acceptance.  It duplicates the
retained V6 Text+-only full timeline, removes only the 15 transcript-first
Text+ instances that are explicitly superseded by the locked seven-window V3
visual authority, and inserts the 17 V3 visual-first instances on isolated
tracks.  The other 100 V6 Text+ instances remain byte/placement-equivalent on
the duplicate.

The result is a complete editable reel suitable for iterative visual polishing:

    115 V6 Text+ - 15 superseded + 17 visual-first = 117 Text+ instances.

No render is performed by this task.  The source timeline, successful pilot,
accepted state and accepted V2/V3 authority artifacts are read-only.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

PILOT_MODULE_PATH = Path(__file__).with_name("step_3D_visual_first_resolve_pilot.py")
_spec = importlib.util.spec_from_file_location("vc_step3d_visual_first_pilot_for_full_rollout", PILOT_MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{PILOT_MODULE_PATH}")
pilot = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = pilot
_spec.loader.exec_module(pilot)

v6 = pilot.v6
base = pilot.base
media = pilot.media

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1"
MODE = "STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py"
SOURCE_TIMELINE_NAME = pilot.SOURCE_TIMELINE_NAME
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_baseline_v1"
AUTHORITY_TASK_ID = pilot.AUTHORITY_TASK_ID
AUTHORITY_MANIFEST_RELATIVE_PATH = pilot.AUTHORITY_MANIFEST_RELATIVE_PATH
AUTHORITY_VALIDATION_RELATIVE_PATH = pilot.AUTHORITY_VALIDATION_RELATIVE_PATH
V6_ROLLOUT_PLAN_RELATIVE_PATH = (
    ".agent/reports/DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6/"
    "20260806T143907620439Z_857f371ddfb146d7ac136f9087f7d96d/rollout_plan.json"
)
ACCEPTED_STATE_RELATIVE_PATH = pilot.ACCEPTED_STATE_RELATIVE_PATH
SOURCE_HASH_ALGORITHM = pilot.SOURCE_HASH_ALGORITHM
EXPECTED_SOURCE_TEXTPLUS_COUNT = 115
EXPECTED_REPLACED_TEXTPLUS_COUNT = 15
EXPECTED_PRESERVED_TEXTPLUS_COUNT = 100
EXPECTED_VISUAL_FIRST_COUNT = 17
EXPECTED_FINAL_TEXTPLUS_COUNT = 117
EXPECTED_VISUAL_ONLY_COUNT = 2
FULL_NAME_PREFIX = "VC_VISUAL_FIRST_FULL_"
MAX_TRACK = pilot.EXPECTED_MAX_TRACK
APPEND_BATCH_SIZE = pilot.APPEND_BATCH_SIZE


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def linked_cue_ids(plans: Sequence[Mapping[str, Any]]) -> List[str]:
    values: List[str] = []
    for plan in plans:
        cue_id = str(plan.get("source_cue_id") or "")
        if cue_id:
            values.append(cue_id)
    result = sorted(set(values))
    if len(values) != len(result):
        raise ValueError("duplicate_authority_source_cue")
    if len(result) != EXPECTED_REPLACED_TEXTPLUS_COUNT:
        raise ValueError(f"replacement_cue_count:{len(result)}")
    return result


def retarget_plans(plans: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, source in enumerate(plans, start=1):
        row = dict(source)
        token_id = str(row["visual_token_id"])
        row["target_name"] = f"{FULL_NAME_PREFIX}{index:04d}_{token_id}"
        rows.append(row)
    if len(rows) != EXPECTED_VISUAL_FIRST_COUNT:
        raise ValueError(f"visual_first_count:{len(rows)}")
    if len({row["target_name"] for row in rows}) != len(rows):
        raise ValueError("full_target_name_duplicate")
    return rows


def replacement_plan(v6_plan: Mapping[str, Any], plans: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    instances = v6_plan.get("instances") if isinstance(v6_plan.get("instances"), list) else []
    if len(instances) != EXPECTED_SOURCE_TEXTPLUS_COUNT:
        raise ValueError(f"v6_instance_count:{len(instances)}")
    cues = set(linked_cue_ids(plans))
    replacement_rows: List[Dict[str, Any]] = []
    preserved_rows: List[Dict[str, Any]] = []
    covered: set[str] = set()
    for raw in instances:
        if not isinstance(raw, Mapping):
            raise ValueError("v6_instance")
        source_cues = [str(value) for value in raw.get("source_cue_ids") or [] if str(value)]
        overlap = sorted(cues.intersection(source_cues))
        row = {
            "instance_id": str(raw.get("instance_id") or ""),
            "source_cue_ids": source_cues,
            "target_name": str(raw.get("target_name") or ""),
            "target_range": [int(value) for value in raw.get("target_range") or []],
            "target_track": int(raw.get("target_track") or 0),
            "text": str(raw.get("text") or ""),
            "matched_authority_cues": overlap,
        }
        if overlap:
            if len(overlap) != 1:
                raise ValueError(f"replacement_multi_cue:{row['instance_id']}:{overlap}")
            covered.update(overlap)
            replacement_rows.append(row)
        else:
            preserved_rows.append(row)
    if covered != cues:
        raise ValueError(f"replacement_cue_coverage:{sorted(cues - covered)}")
    if len(replacement_rows) != EXPECTED_REPLACED_TEXTPLUS_COUNT:
        raise ValueError(f"replacement_instance_count:{len(replacement_rows)}")
    if len(preserved_rows) != EXPECTED_PRESERVED_TEXTPLUS_COUNT:
        raise ValueError(f"preserved_instance_count:{len(preserved_rows)}")
    if len({row["target_name"] for row in replacement_rows}) != len(replacement_rows):
        raise ValueError("replacement_target_duplicate")
    return {
        "replacement_cue_ids": sorted(cues),
        "replacement_rows": sorted(replacement_rows, key=lambda row: row["target_name"]),
        "preserved_rows": sorted(preserved_rows, key=lambda row: row["target_name"]),
        "replacement_target_names": sorted(row["target_name"] for row in replacement_rows),
        "preserved_target_names": sorted(row["target_name"] for row in preserved_rows),
        "expected_final_textplus_count": EXPECTED_FINAL_TEXTPLUS_COUNT,
        "ok": True,
    }


def timeline_inventory(timeline: Any) -> List[Dict[str, Any]]:
    return pilot.timeline_inventory(timeline)


def stable_inventory(rows: Sequence[Mapping[str, Any]]) -> List[Tuple[Any, ...]]:
    return pilot.stable_inventory(rows)


def full_target_items(timeline: Any, plans: Sequence[Mapping[str, Any]]) -> Dict[str, Tuple[int, Any]]:
    return pilot.target_items(timeline, plans)


def delete_named_textplus(timeline: Any, names: Iterable[str]) -> Dict[str, Any]:
    wanted = set(str(value) for value in names)
    found: Dict[str, Any] = {}
    duplicates: List[str] = []
    for _, item in base.all_video_items(timeline):
        name = base.item_name(item)
        if name not in wanted:
            continue
        if name in found:
            duplicates.append(name)
        found[name] = item
    missing = sorted(wanted - set(found))
    if missing or duplicates:
        return {"ok": False, "missing": missing, "duplicates": sorted(set(duplicates)), "deleted": 0}
    result = base.delete_items(timeline, list(found.values()))
    remaining = sorted(
        base.item_name(item)
        for _, item in base.all_video_items(timeline)
        if base.item_name(item) in wanted
    )
    return {
        "ok": bool(result.get("ok") and not remaining),
        "requested": len(wanted),
        "deleted": len(wanted) if result.get("ok") and not remaining else 0,
        "remaining": remaining,
        "delete_result": result,
    }


def source_textplus_names(timeline: Any) -> List[str]:
    return sorted(
        base.item_name(item)
        for _, item in base.all_video_items(timeline)
        if base.item_name(item).startswith("VC_TEXTPLUS_")
    )


def visual_first_names(timeline: Any) -> List[str]:
    return sorted(
        base.item_name(item)
        for _, item in base.all_video_items(timeline)
        if base.item_name(item).startswith(FULL_NAME_PREFIX)
    )


def track_two_item_names(timeline: Any) -> List[str]:
    return sorted(
        base.item_name(item)
        for track, item in base.all_video_items(timeline)
        if int(track) == 2
    )


def cleanup_failure(
    resolve: Any,
    project_manager: Any,
    project: Any,
    media_pool: Any,
    original_timeline: Any,
    original_page: str,
    accepted_path: Path,
    accepted_hash: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        target = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if original_timeline is not None:
            value, call = base.direct_call(project, "SetCurrentTimeline", original_timeline)
            result["restore_timeline"] = call
            if not value:
                result["errors"].append("restore_timeline")
        if target is not None:
            value, call = base.direct_call(media_pool, "DeleteTimelines", [target])
            result["delete_target"] = call
            if not value:
                result["errors"].append("delete_target")
        if original_page:
            value, call = base.direct_call(resolve, "OpenPage", original_page)
            result["restore_page"] = call
            if not value:
                result["errors"].append("restore_page")
        save = base.save_project(project_manager)
        result["save"] = save
        result["save_call_count"] = 1
        if not save.get("success"):
            result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc))
        result["traceback"] = traceback.format_exc()
    result["target_deleted"] = base.find_timeline(project, TARGET_TIMELINE_NAME) is None
    result["accepted_state_unchanged"] = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
    result["ok"] = bool(not result["errors"] and result["target_deleted"] and result["accepted_state_unchanged"])
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if not run_id:
        raise ValueError("run_id")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")

    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "backend": "v6_full_timeline_plus_visual_first_v3_replacements",
        "ok": False,
        "started_at": base.utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "visual_polish_deferred": True,
        "full_rollout_authorized": False,
        "save_call_count": 0,
        "target_timeline_kept": False,
        "failures": [],
    }
    project_manager = project = media_pool = None
    original_timeline = None
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    source_before: List[Dict[str, Any]] = []
    source_unique_id = ""
    target_created = False
    try:
        source_contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        report["source_contract_verified_count"] = source_contract["verified_count"]
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")

        authority = load_json(root / AUTHORITY_MANIFEST_RELATIVE_PATH)
        authority_validation = load_json(root / AUTHORITY_VALIDATION_RELATIVE_PATH)
        if authority_validation.get("ok") is not True:
            raise RuntimeError("authority_validation")
        raw_plans = pilot.flatten_authority(authority, root)
        plans = retarget_plans(raw_plans)
        v6_plan = load_json(root / V6_ROLLOUT_PLAN_RELATIVE_PATH)
        replacements = replacement_plan(v6_plan, plans)
        plan_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "authority_task_id": AUTHORITY_TASK_ID,
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "visual_first_instances": plans,
            "replacements": replacements,
            "counts": {
                "source_textplus": EXPECTED_SOURCE_TEXTPLUS_COUNT,
                "replaced_textplus": EXPECTED_REPLACED_TEXTPLUS_COUNT,
                "preserved_textplus": EXPECTED_PRESERVED_TEXTPLUS_COUNT,
                "visual_first": EXPECTED_VISUAL_FIRST_COUNT,
                "final_textplus": EXPECTED_FINAL_TEXTPLUS_COUNT,
            },
            "visual_polish_deferred": True,
            "full_rollout_authorized": False,
            "ok": True,
        }
        base.write_json(report_dir / "full_rollout_plan.json", plan_document)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        original_timeline = base.safe_value(project, "GetCurrentTimeline", default=None)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_timeline_exists")
        source_unique_id = base.timeline_unique_id(source)
        source_before = timeline_inventory(source)
        old_source_names = source_textplus_names(source)
        if len(old_source_names) != EXPECTED_SOURCE_TEXTPLUS_COUNT:
            raise RuntimeError(f"source_textplus_count:{len(old_source_names)}")
        if visual_first_names(source):
            raise RuntimeError("source_visual_first_items")
        if track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")
        if sorted(old_source_names) != sorted(replacements["replacement_target_names"] + replacements["preserved_target_names"]):
            raise RuntimeError("source_v6_names")
        max_duration = max(int(row["target_range"][1]) - int(row["target_range"][0]) for row in plans)
        carrier_source = base.choose_carrier_source(source, max_duration + 1)
        if not carrier_source.get("ok"):
            raise RuntimeError("carrier_source")
        preflight = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "resolve_calls": resolve_calls,
            "source_unique_id": source_unique_id,
            "source_inventory": source_before,
            "source_textplus_count": len(old_source_names),
            "source_v2_item_count": len(track_two_item_names(source)),
            "replacement_count": len(replacements["replacement_target_names"]),
            "preserved_count": len(replacements["preserved_target_names"]),
            "visual_first_count": len(plans),
            "carrier_source": {key: base.json_safe(value) for key, value in carrier_source.items() if key not in {"item", "media_pool_item"}},
            "ok": True,
        }
        base.write_json(report_dir / "full_rollout_preflight.json", preflight)

        opened, open_call = base.direct_call(resolve, "OpenPage", "edit")
        if not opened:
            raise RuntimeError("open_edit")
        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")
        target_before = timeline_inventory(target)
        if stable_inventory(target_before) != stable_inventory(source_before):
            raise RuntimeError("duplicate_inventory")

        deletion = delete_named_textplus(target, replacements["replacement_target_names"])
        time.sleep(0.25)
        track_setup = base.ensure_video_tracks(target, MAX_TRACK)
        preserved_after_delete = source_textplus_names(target)
        setup = {
            "open_edit_call": open_call,
            "duplicate_call": duplicate_call,
            "select_call": select_call,
            "duplicate_inventory_exact": stable_inventory(target_before) == stable_inventory(source_before),
            "replacement_delete": deletion,
            "preserved_textplus_names": preserved_after_delete,
            "track_setup": track_setup,
            "v2_items": track_two_item_names(target),
            "ok": bool(
                deletion.get("ok")
                and deletion.get("deleted") == EXPECTED_REPLACED_TEXTPLUS_COUNT
                and preserved_after_delete == replacements["preserved_target_names"]
                and track_setup.get("ok")
                and not track_two_item_names(target)
            ),
        }
        base.write_json(report_dir / "full_rollout_timeline_setup.json", setup)
        if not setup["ok"]:
            raise RuntimeError("full_rollout_timeline_setup")

        specs = [
            {
                "cue_id": row["visual_token_id"],
                "name": row["target_name"],
                "text": row["display_text"],
                "target_range": row["target_range"],
                "target_track": row["target_track"],
            }
            for row in plans
        ]
        append_rows: List[Dict[str, Any]] = []
        assigned: Dict[str, Any] = {}
        for batch_index, batch in enumerate(pilot.chunked(specs, APPEND_BATCH_SIZE)):
            result = v6.append_batch_by_placement(media_pool, target, carrier_source, batch)
            append_rows.append({
                "batch_index": batch_index,
                "result": base.json_safe({key: value for key, value in result.items() if key != "assigned"}),
                "ok": result.get("ok") is True,
            })
            if not result.get("ok"):
                raise RuntimeError(f"append_batch:{batch_index}")
            for spec, item in result["assigned"]:
                assigned[str(spec["cue_id"])] = item
        append_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "batch_count": len(append_rows),
            "requested_count": len(specs),
            "assigned_count": len(assigned),
            "batches": append_rows,
            "ok": len(assigned) == EXPECTED_VISUAL_FIRST_COUNT and all(row["ok"] for row in append_rows),
        }
        base.write_json(report_dir / "full_rollout_carrier_append.json", append_document)
        if not append_document["ok"]:
            raise RuntimeError("carrier_append")

        template_path = root / pilot.TEMPLATE_COMP_RELATIVE_PATH
        application_rows: List[Dict[str, Any]] = []
        application_document: Dict[str, Any] = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "expected_instance_count": EXPECTED_VISUAL_FIRST_COUNT,
            "instance_count": 0,
            "complete": False,
            "rows": application_rows,
            "ok": False,
        }
        base.write_json(report_dir / "full_rollout_application.json", application_document)
        for plan in plans:
            item = assigned.get(plan["visual_token_id"])
            if item is None:
                raise RuntimeError(f"assigned_item:{plan['visual_token_id']}")
            clone = media.import_source_comp(item, template_path)
            application = pilot.apply_token(item, plan) if clone.get("ok") else {"ok": False, "error": "clone"}
            row = {
                "visual_token_id": plan["visual_token_id"],
                "target_name": plan["target_name"],
                "clone": clone,
                "application": application,
                "ok": bool(clone.get("ok") and application.get("ok")),
            }
            application_rows.append(row)
            application_document["instance_count"] = len(application_rows)
            application_document["rows"] = application_rows
            base.write_json(report_dir / "full_rollout_application.json", application_document)
            if not row["ok"]:
                stage = "clone" if not clone.get("ok") else pilot.application_failure_stage(application)
                raise RuntimeError(f"apply_token:{plan['visual_token_id']}:{stage}")
        application_document.update({
            "instance_count": len(application_rows),
            "complete": True,
            "rows": application_rows,
            "ok": len(application_rows) == EXPECTED_VISUAL_FIRST_COUNT and all(row["ok"] for row in application_rows),
        })
        base.write_json(report_dir / "full_rollout_application.json", application_document)

        found = full_target_items(target, plans)
        readback_rows: List[Dict[str, Any]] = []
        for plan in plans:
            track, item = found.get(plan["target_name"], (0, None))
            if item is None:
                readback_rows.append({"visual_token_id": plan["visual_token_id"], "ok": False, "error": "missing"})
                continue
            plan_for_readback = dict(plan)
            plan_for_readback["timeline"] = target
            row = pilot.read_token(item, plan_for_readback)
            row["visual_token_id"] = plan["visual_token_id"]
            row["target_name"] = plan["target_name"]
            readback_rows.append(row)
        preserved_names = source_textplus_names(target)
        visual_names = visual_first_names(target)
        pre_save_checks = {
            "visual_first_exact": len(readback_rows) == EXPECTED_VISUAL_FIRST_COUNT and all(row.get("ok") for row in readback_rows),
            "preserved_textplus_exact": preserved_names == replacements["preserved_target_names"],
            "replacement_textplus_absent": not set(replacements["replacement_target_names"]).intersection(preserved_names),
            "visual_first_name_count": len(visual_names) == EXPECTED_VISUAL_FIRST_COUNT,
            "final_textplus_count": len(preserved_names) + len(visual_names) == EXPECTED_FINAL_TEXTPLUS_COUNT,
            "v2_empty": not track_two_item_names(target),
        }
        readback = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "visual_first_rows": readback_rows,
            "preserved_textplus_names": preserved_names,
            "visual_first_names": visual_names,
            "checks": pre_save_checks,
            "ok": all(pre_save_checks.values()),
        }
        base.write_json(report_dir / "full_rollout_readback_before_save.json", readback)
        if not readback["ok"]:
            raise RuntimeError("full_rollout_readback")

        base.direct_call(project, "SetCurrentTimeline", target)
        base.direct_call(resolve, "OpenPage", "edit")
        save = base.save_project(project_manager)
        report["save_call_count"] = 1 if save.get("success") else 0
        if not save.get("success"):
            raise RuntimeError("save_full_rollout")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("timeline_reacquire")
        source_after_inventory = timeline_inventory(source_after)
        found_after = full_target_items(target_after, plans)
        persistent_rows: List[Dict[str, Any]] = []
        for plan in plans:
            track, item = found_after.get(plan["target_name"], (0, None))
            if item is None:
                persistent_rows.append({"visual_token_id": plan["visual_token_id"], "ok": False, "error": "missing"})
                continue
            plan_for_readback = dict(plan)
            plan_for_readback["timeline"] = target_after
            row = pilot.read_token(item, plan_for_readback)
            row["visual_token_id"] = plan["visual_token_id"]
            persistent_rows.append(row)
        persistent_preserved = source_textplus_names(target_after)
        persistent_visual = visual_first_names(target_after)
        checks = {
            "source_timeline_unchanged": base.timeline_unique_id(source_after) == source_unique_id and stable_inventory(source_after_inventory) == stable_inventory(source_before),
            "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
            "target_retained": base.timeline_name(target_after) == TARGET_TIMELINE_NAME,
            "preserved_textplus_exact": persistent_preserved == replacements["preserved_target_names"],
            "replacement_textplus_absent": not set(replacements["replacement_target_names"]).intersection(persistent_preserved),
            "visual_first_count": len(persistent_visual) == EXPECTED_VISUAL_FIRST_COUNT,
            "visual_first_exact": len(persistent_rows) == EXPECTED_VISUAL_FIRST_COUNT and all(row.get("ok") for row in persistent_rows),
            "final_textplus_count": len(persistent_preserved) + len(persistent_visual) == EXPECTED_FINAL_TEXTPLUS_COUNT,
            "v2_empty": not track_two_item_names(target_after),
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "source_inventory_before": source_before,
            "source_inventory_after": source_after_inventory,
            "preserved_textplus_names": persistent_preserved,
            "visual_first_names": persistent_visual,
            "visual_first_rows": persistent_rows,
            "checks": checks,
            "save": save,
            "visual_polish_deferred": True,
            "full_rollout_authorized": False,
            "ok": all(checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")

        report.update({
            "ok": True,
            "completed_at": base.utc_now(),
            "source_timeline_unchanged": True,
            "accepted_state_unchanged": True,
            "target_timeline_kept": True,
            "target_timeline_unique_id": base.timeline_unique_id(target_after),
            "source_textplus_count": EXPECTED_SOURCE_TEXTPLUS_COUNT,
            "replaced_textplus_count": EXPECTED_REPLACED_TEXTPLUS_COUNT,
            "preserved_textplus_count": EXPECTED_PRESERVED_TEXTPLUS_COUNT,
            "visual_first_instance_count": EXPECTED_VISUAL_FIRST_COUNT,
            "visual_only_component_count": EXPECTED_VISUAL_ONLY_COUNT,
            "final_textplus_count": EXPECTED_FINAL_TEXTPLUS_COUNT,
            "v2_item_count": 0,
        })
        base.write_json(report_dir / "report.json", report)
        return report
    except BaseException as exc:
        report["error"] = base.compact_exception(exc)
        report["traceback"] = traceback.format_exc()
        report["failures"] = [report["error"]]
        if target_created and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_failure(
                resolve,
                project_manager,
                project,
                media_pool,
                original_timeline,
                original_page,
                accepted_path,
                accepted_hash,
            )
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["cleanup"] = cleanup
            report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
        report["completed_at"] = base.utc_now()
        base.write_json(report_dir / "report.json", report)
        return report
