"""Polish Group 02 font metrics and relative placement on the accepted motion-polished full reel.

This task duplicates the successful 117-Text+ Group-02 motion timeline, removes
only the two Group-02 visual-first items, and recreates them with source-pixel
font/size/center candidates while freezing the accepted vertical motion, timing,
opacity, text identity, colors, and all other 115 editable caption items.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

FULL_MODULE_PATH = Path(__file__).with_name("step_3D_visual_first_full_rollout_baseline.py")
_spec = importlib.util.spec_from_file_location("vc_full_rollout_for_g02_polish", FULL_MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{FULL_MODULE_PATH}")
full = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = full
_spec.loader.exec_module(full)

pilot = full.pilot
v6 = full.v6
base = full.base
media = full.media

TASK_ID = "DZSQH7AUHJT_STEP_3E_GROUP02_FONT_METRICS_POLISH_V1"
MODE = "STEP_3E_GROUP02_FONT_METRICS_POLISH"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3E_group02_font_metrics_polish.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_fontmetrics_v1"
CONTRACT_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_font_metrics_v1.json"
SOURCE_MOTION_CONTRACT_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_vertical_motion_v1.json"
ACCEPTED_STATE_RELATIVE_PATH = full.ACCEPTED_STATE_RELATIVE_PATH
SOURCE_HASH_ALGORITHM = full.SOURCE_HASH_ALGORITHM
FULL_PREFIX = full.FULL_NAME_PREFIX
MAX_TRACK = full.MAX_TRACK
EXPECTED_TOTAL_TEXTPLUS = 117
EXPECTED_V6_TEXTPLUS = 100
EXPECTED_VISUAL_FIRST = 17
EXPECTED_POLISHED = 2
EXPECTED_UNCHANGED_ITEMS = EXPECTED_TOTAL_TEXTPLUS - EXPECTED_POLISHED
GROUP_ID = "vf_group_02_already_decorated"
TARGET_NAMES = (
    "VC_VISUAL_FIRST_FULL_0002_vf_02_already",
    "VC_VISUAL_FIRST_FULL_0003_vf_02_decorative_glyph",
)


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def contract_plans(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if document.get("task_id") != TASK_ID or document.get("ok") is not True:
        raise ValueError("contract_identity")
    if document.get("group_id") != GROUP_ID:
        raise ValueError("contract_group")
    plans = document.get("plans")
    if not isinstance(plans, list) or len(plans) != EXPECTED_POLISHED:
        raise ValueError("contract_plan_count")
    rows: List[Dict[str, Any]] = []
    for raw in plans:
        if not isinstance(raw, Mapping):
            raise ValueError("contract_plan")
        row = dict(raw)
        if str(row.get("target_name") or "") not in TARGET_NAMES:
            raise ValueError(f"contract_target:{row.get('target_name')}")
        if [int(v) for v in row.get("target_range") or []] != [245, 270]:
            raise ValueError(f"contract_range:{row.get('visual_token_id')}")
        if row.get("group_id") != GROUP_ID:
            raise ValueError("contract_plan_group")
        if row.get("transcript_timing_promoted_to_authority") is not False:
            raise ValueError("contract_transcript_timing")
        font = row.get("font") if isinstance(row.get("font"), Mapping) else {}
        expected_font = {
            "vf_02_already": ("Verdana", "Bold"),
            "vf_02_decorative_glyph": ("Segoe Script", "Regular"),
        }.get(str(row.get("visual_token_id") or ""))
        if expected_font is None or (font.get("font_family"), font.get("font_style")) != expected_font:
            raise ValueError(f"contract_font:{row.get('visual_token_id')}:{font}")
        metrics = row.get("font_metrics_polish")
        if not isinstance(metrics, Mapping) or int(metrics.get("source_frame") or -1) != 255:
            raise ValueError(f"contract_metrics:{row.get('visual_token_id')}")
        xs = [float(key["source_top_origin_value"][0]) for key in row.get("position_keys") or []]
        ys = [float(key["source_top_origin_value"][1]) for key in row.get("position_keys") or []]
        if not xs or max(xs) - min(xs) > 1e-9:
            raise ValueError(f"contract_horizontal_motion:{row.get('visual_token_id')}")
        if any(later < earlier for earlier, later in zip(ys, ys[1:])):
            raise ValueError(f"contract_vertical_direction:{row.get('visual_token_id')}")
        sizes = [float(key["scale"]) for key in row.get("size_keys") or []]
        if not sizes or any(abs(value - 1.0) > 1e-9 for value in sizes):
            raise ValueError(f"contract_size_motion:{row.get('visual_token_id')}")
        opacities = [float(key["factor"]) for key in row.get("opacity_keys") or []]
        if not opacities or abs(opacities[-1] - 1.0) > 1e-9:
            raise ValueError(f"contract_hold_opacity:{row.get('visual_token_id')}")
        rows.append(row)
    if {row["target_name"] for row in rows} != set(TARGET_NAMES):
        raise ValueError("contract_target_coverage")
    return rows


def timeline_inventory(timeline: Any) -> List[Dict[str, Any]]:
    return full.timeline_inventory(timeline)


def stable_inventory(rows: Sequence[Mapping[str, Any]]) -> List[Tuple[Any, ...]]:
    return full.stable_inventory(rows)


def filtered_stable_inventory(rows: Sequence[Mapping[str, Any]]) -> List[Tuple[Any, ...]]:
    return stable_inventory([row for row in rows if str(row.get("name") or "") not in TARGET_NAMES])


def target_items(timeline: Any, plans: Sequence[Mapping[str, Any]]) -> Dict[str, Tuple[int, Any]]:
    return pilot.target_items(timeline, plans)


def total_editable_textplus_count(timeline: Any) -> int:
    return len(full.source_textplus_names(timeline)) + len(full.visual_first_names(timeline))


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
        target = base.find_timeline(project, TARGET_TIMELINE_NAME) if project is not None else None
        if original_timeline is not None and project is not None:
            value, call = base.direct_call(project, "SetCurrentTimeline", original_timeline)
            result["restore_timeline"] = call
            if not value:
                result["errors"].append("restore_timeline")
        if target is not None and media_pool is not None:
            value, call = base.direct_call(media_pool, "DeleteTimelines", [target])
            result["delete_target"] = call
            if not value:
                result["errors"].append("delete_target")
        if original_page:
            value, call = base.direct_call(resolve, "OpenPage", original_page)
            result["restore_page"] = call
            if not value:
                result["errors"].append("restore_page")
        if project_manager is not None:
            save = base.save_project(project_manager)
            result["save"] = save
            result["save_call_count"] = 1
            if not save.get("success"):
                result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc))
        result["traceback"] = traceback.format_exc()
    try:
        result["target_deleted"] = project is not None and base.find_timeline(project, TARGET_TIMELINE_NAME) is None
    except BaseException:
        result["target_deleted"] = False
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
        "ok": False,
        "started_at": base.utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "group_id": GROUP_ID,
        "polished_instance_count": 0,
        "final_textplus_count": 0,
        "source_timeline_unchanged": False,
        "accepted_state_unchanged": False,
        "save_call_count": 0,
        "target_timeline_kept": False,
        "font_metrics_polish_applied": False,
        "font_visual_approval_required": True,
        "full_rollout_authorized": False,
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
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")

        contract = load_json(root / CONTRACT_RELATIVE_PATH)
        plans = contract_plans(contract)
        base.write_json(report_dir / "polish_plan.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "contract": CONTRACT_RELATIVE_PATH,
            "plans": plans,
            "source_evidence": contract.get("source_evidence"),
            "known_remaining_visual_risks": contract.get("known_remaining_visual_risks"),
            "ok": True,
        })

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        original_timeline = base.safe_value(project, "GetCurrentTimeline", default=None)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_timeline_exists")

        source_unique_id = base.timeline_unique_id(source)
        source_before = timeline_inventory(source)
        if len(full.source_textplus_names(source)) != EXPECTED_V6_TEXTPLUS:
            raise RuntimeError("source_v6_textplus_count")
        if len(full.visual_first_names(source)) != EXPECTED_VISUAL_FIRST:
            raise RuntimeError("source_visual_first_count")
        if total_editable_textplus_count(source) != EXPECTED_TOTAL_TEXTPLUS:
            raise RuntimeError("source_total_textplus_count")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")

        source_group = target_items(source, plans)
        if set(source_group) != set(TARGET_NAMES):
            raise RuntimeError("source_group_targets")

        # Freeze the accepted Group-02 motion/timing state before replacing the
        # two items for font/metrics polishing. This prevents an unrelated
        # manual edit from being silently incorporated into the new target.
        motion_contract = load_json(root / SOURCE_MOTION_CONTRACT_RELATIVE_PATH)
        motion_plans = []
        raw_motion_plans = motion_contract.get("plans") if isinstance(motion_contract.get("plans"), list) else []
        if motion_contract.get("group_id") != GROUP_ID or len(raw_motion_plans) != EXPECTED_POLISHED:
            raise RuntimeError("source_motion_contract")
        motion_plans = [dict(row) for row in raw_motion_plans]
        source_motion_rows: List[Dict[str, Any]] = []
        source_motion_items = target_items(source, motion_plans)
        for motion_plan in motion_plans:
            track, item = source_motion_items.get(motion_plan["target_name"], (0, None))
            if item is None:
                source_motion_rows.append({"visual_token_id": motion_plan["visual_token_id"], "ok": False, "error": "missing"})
                continue
            check_plan = dict(motion_plan)
            check_plan["timeline"] = source
            row = pilot.read_token(item, check_plan)
            row["visual_token_id"] = motion_plan["visual_token_id"]
            source_motion_rows.append(row)
        if len(source_motion_rows) != EXPECTED_POLISHED or not all(row.get("ok") for row in source_motion_rows):
            raise RuntimeError("source_group_motion_state")

        max_duration = max(int(row["target_range"][1]) - int(row["target_range"][0]) for row in plans)
        carrier_source = base.choose_carrier_source(source, max_duration + 1)
        if not carrier_source.get("ok"):
            raise RuntimeError("carrier_source")

        base.write_json(report_dir / "polish_preflight.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "resolve_calls": resolve_calls,
            "source_unique_id": source_unique_id,
            "source_inventory": source_before,
            "source_v6_textplus_count": len(full.source_textplus_names(source)),
            "source_visual_first_count": len(full.visual_first_names(source)),
            "source_total_textplus_count": total_editable_textplus_count(source),
            "source_v2_item_count": len(full.track_two_item_names(source)),
            "source_group_target_names": sorted(source_group),
            "source_group_motion_readback": source_motion_rows,
            "source_group_motion_readback_ok": all(row.get("ok") for row in source_motion_rows),
            "carrier_source": {key: base.json_safe(value) for key, value in carrier_source.items() if key not in {"item", "media_pool_item"}},
            "ok": True,
        })

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

        deletion = full.delete_named_textplus(target, TARGET_NAMES)
        time.sleep(0.25)
        if not deletion.get("ok") or deletion.get("deleted") != EXPECTED_POLISHED:
            raise RuntimeError("delete_group02")

        track_setup = base.ensure_video_tracks(target, MAX_TRACK)
        if not track_setup.get("ok"):
            raise RuntimeError("track_setup")

        after_delete = timeline_inventory(target)
        if filtered_stable_inventory(after_delete) != filtered_stable_inventory(source_before):
            raise RuntimeError("unrelated_inventory_after_delete")

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
        append_result = v6.append_batch_by_placement(media_pool, target, carrier_source, specs)
        append_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "result": base.json_safe({key: value for key, value in append_result.items() if key != "assigned"}),
            "requested_count": len(specs),
            "assigned_count": len(append_result.get("assigned") or []),
            "ok": append_result.get("ok") is True and len(append_result.get("assigned") or []) == EXPECTED_POLISHED,
        }
        base.write_json(report_dir / "polish_carrier_append.json", append_document)
        if not append_document["ok"]:
            raise RuntimeError("carrier_append")

        assigned = {str(spec["cue_id"]): item for spec, item in append_result["assigned"]}
        template_path = root / pilot.TEMPLATE_COMP_RELATIVE_PATH
        rows: List[Dict[str, Any]] = []
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
            rows.append(row)
            base.write_json(report_dir / "polish_application.json", {
                "schema_version": 1,
                "task_id": TASK_ID,
                "run_id": run_id,
                "expected_instance_count": EXPECTED_POLISHED,
                "instance_count": len(rows),
                "complete": False,
                "rows": rows,
                "ok": False,
            })
            if not row["ok"]:
                stage = "clone" if not clone.get("ok") else pilot.application_failure_stage(application)
                raise RuntimeError(f"apply_token:{plan['visual_token_id']}:{stage}")

        base.write_json(report_dir / "polish_application.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "expected_instance_count": EXPECTED_POLISHED,
            "instance_count": len(rows),
            "complete": True,
            "rows": rows,
            "ok": len(rows) == EXPECTED_POLISHED and all(row["ok"] for row in rows),
        })

        found = target_items(target, plans)
        readback_rows: List[Dict[str, Any]] = []
        for plan in plans:
            track, item = found.get(plan["target_name"], (0, None))
            if item is None:
                readback_rows.append({"visual_token_id": plan["visual_token_id"], "ok": False, "error": "missing"})
                continue
            check_plan = dict(plan)
            check_plan["timeline"] = target
            row = pilot.read_token(item, check_plan)
            row["visual_token_id"] = plan["visual_token_id"]
            readback_rows.append(row)

        target_inventory = timeline_inventory(target)
        checks = {
            "polished_exact": len(readback_rows) == EXPECTED_POLISHED and all(row.get("ok") for row in readback_rows),
            "unchanged_inventory_exact": filtered_stable_inventory(target_inventory) == filtered_stable_inventory(source_before),
            "v6_textplus_count": len(full.source_textplus_names(target)) == EXPECTED_V6_TEXTPLUS,
            "visual_first_count": len(full.visual_first_names(target)) == EXPECTED_VISUAL_FIRST,
            "final_textplus_count": total_editable_textplus_count(target) == EXPECTED_TOTAL_TEXTPLUS,
            "v2_empty": not full.track_two_item_names(target),
        }
        base.write_json(report_dir / "polish_readback_before_save.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "rows": readback_rows,
            "checks": checks,
            "ok": all(checks.values()),
        })
        if not all(checks.values()):
            raise RuntimeError("polish_readback")

        base.direct_call(project, "SetCurrentTimeline", target)
        base.direct_call(resolve, "OpenPage", "edit")
        save = base.save_project(project_manager)
        report["save_call_count"] = 1 if save.get("success") else 0
        if not save.get("success"):
            raise RuntimeError("save")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("reacquire_timeline")

        source_after_inventory = timeline_inventory(source_after)
        target_after_inventory = timeline_inventory(target_after)
        found_after = target_items(target_after, plans)
        persistent_rows: List[Dict[str, Any]] = []
        for plan in plans:
            track, item = found_after.get(plan["target_name"], (0, None))
            if item is None:
                persistent_rows.append({"visual_token_id": plan["visual_token_id"], "ok": False, "error": "missing"})
                continue
            check_plan = dict(plan)
            check_plan["timeline"] = target_after
            row = pilot.read_token(item, check_plan)
            row["visual_token_id"] = plan["visual_token_id"]
            persistent_rows.append(row)

        persistent_checks = {
            "source_timeline_unchanged": base.timeline_unique_id(source_after) == source_unique_id and stable_inventory(source_after_inventory) == stable_inventory(source_before),
            "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
            "target_retained": base.timeline_name(target_after) == TARGET_TIMELINE_NAME,
            "polished_exact": len(persistent_rows) == EXPECTED_POLISHED and all(row.get("ok") for row in persistent_rows),
            "unchanged_inventory_exact": filtered_stable_inventory(target_after_inventory) == filtered_stable_inventory(source_before),
            "v6_textplus_count": len(full.source_textplus_names(target_after)) == EXPECTED_V6_TEXTPLUS,
            "visual_first_count": len(full.visual_first_names(target_after)) == EXPECTED_VISUAL_FIRST,
            "final_textplus_count": total_editable_textplus_count(target_after) == EXPECTED_TOTAL_TEXTPLUS,
            "v2_empty": not full.track_two_item_names(target_after),
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "rows": persistent_rows,
            "checks": persistent_checks,
            "save": save,
            "font_metrics_polish_applied": True,
            "font_visual_approval_required": True,
            "visual_approval_required": True,
            "full_rollout_authorized": False,
            "ok": all(persistent_checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")

        report.update({
            "ok": True,
            "finished_at": base.utc_now(),
            "polished_instance_count": EXPECTED_POLISHED,
            "unchanged_item_count": EXPECTED_UNCHANGED_ITEMS,
            "final_textplus_count": EXPECTED_TOTAL_TEXTPLUS,
            "source_timeline_unchanged": persistent_checks["source_timeline_unchanged"],
            "accepted_state_unchanged": persistent_checks["accepted_state_unchanged"],
            "target_timeline_kept": True,
            "font_metrics_polish_applied": True,
            "font_visual_approval_required": True,
            "visual_approval_required": True,
        })
        return report

    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
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
            report["failure_cleanup_ok"] = cleanup.get("ok") is True
            report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
        report["finished_at"] = base.utc_now()
        return report
