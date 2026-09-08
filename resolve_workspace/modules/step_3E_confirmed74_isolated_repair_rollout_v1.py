"""Apply only the source-confirmed 74-caption Step 3E repair on an isolated timeline.

The source is the visually approved 17-token V4 timeline. Seventy-four
non-protected structural Text+ items with genuine source-semantic evidence are
removed and recreated from the locked confirmed-74 authority. Twenty-three
semantic-unresolved Text+ items are never deleted or modified. Three redundant
structural Text+ rows represented by already accepted protected composites are
removed and deliberately not recreated, preventing duplicate visual layers.
The 17 protected V4 instances remain exact.

The imported source Fusion comp remains the static-style base. A fill override
is applied only when the offline authority carries a generic source-pixel fill
gate. Center/Size come from source authority; opacity is a hold so detector
noise cannot create flicker. Fade refinement remains explicitly deferred.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT_V1"
MODE = "STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3E_confirmed74_isolated_repair_rollout_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_17tokens_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_v1"
AUTHORITY_RELATIVE_PATH = "artifacts/DZSQH7AUHJT_STEP_3E_CONFIRMED74_REPAIR_AUTHORITY_V1/confirmed74_repair_authority_v1.json"
STEP3E3_PERSISTENT_RELATIVE_PATH = (
    ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/"
    "20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json"
)
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
EXPECTED_REPAIR = 74
EXPECTED_UNRESOLVED = 23
EXPECTED_COMPOSITE_REMOVED = 3
EXPECTED_STRUCTURAL_SOURCE = 100
EXPECTED_PROTECTED = 17
EXPECTED_STRUCTURAL_TARGET = 97
EXPECTED_PHYSICAL_TEXTPLUS = 114
TRACK_MIN = 3
TRACK_MAX = 7
APPEND_BATCH_SIZE = 6


def _module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_old() -> Any:
    return _module(Path(__file__).with_name("step_3E_remaining100_full_rollout_v1.py"), "vc_remaining100_for_confirmed74")


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def authority_partition(authority: Mapping[str, Any]) -> Dict[str, Any]:
    if authority.get("task_id") != TASK_ID or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    policy = authority.get("policy") if isinstance(authority.get("policy"), Mapping) else {}
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    expected = {
        "repair_instances": EXPECTED_REPAIR,
        "preserve_unresolved": EXPECTED_UNRESOLVED,
        "remove_composite_structural": EXPECTED_COMPOSITE_REMOVED,
        "protected_v4": EXPECTED_PROTECTED,
        "structural_nonprotected_rows": EXPECTED_STRUCTURAL_SOURCE,
        "expected_physical_textplus_count": EXPECTED_PHYSICAL_TEXTPLUS,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise ValueError(f"authority_summary:{key}:{summary.get(key)}")
    if policy.get("transcript_timing_authority") is not False:
        raise ValueError("transcript_policy")
    if policy.get("unresolved_rows_receive_repair_geometry") is not False:
        raise ValueError("unresolved_policy")
    if policy.get("composite_structural_rows_recreated") is not False:
        raise ValueError("composite_policy")
    if policy.get("fade_polish_deferred") is not True or policy.get("repair_rollout_authorized") is not False:
        raise ValueError("rollout_policy")

    repair = [dict(row) for row in authority.get("repair_instances") or [] if isinstance(row, Mapping)]
    unresolved = [dict(row) for row in authority.get("preserve_unresolved") or [] if isinstance(row, Mapping)]
    composite = [dict(row) for row in authority.get("remove_composite_structural") or [] if isinstance(row, Mapping)]
    protected = [dict(row) for row in authority.get("protected_v4") or [] if isinstance(row, Mapping)]
    if (len(repair), len(unresolved), len(composite), len(protected)) != (EXPECTED_REPAIR, EXPECTED_UNRESOLVED, EXPECTED_COMPOSITE_REMOVED, EXPECTED_PROTECTED):
        raise ValueError("authority_partition")
    sets = [
        {str(row.get("target_name") or "") for row in repair},
        {str(row.get("target_name") or "") for row in unresolved},
        {str(row.get("target_name") or "") for row in composite},
        {str(row.get("target_name") or "") for row in protected},
    ]
    if any("" in values for values in sets):
        raise ValueError("authority_blank_name")
    for index, left in enumerate(sets):
        for right in sets[index + 1:]:
            if left & right:
                raise ValueError("authority_scope_overlap")
    if len(sets[0] | sets[1] | sets[2]) != EXPECTED_STRUCTURAL_SOURCE:
        raise ValueError("authority_structural_scope")
    return {"repair": repair, "unresolved": unresolved, "composite": composite, "protected": protected}


def build_unassigned_plans(authority: Mapping[str, Any]) -> List[Dict[str, Any]]:
    partition = authority_partition(authority)
    plans: List[Dict[str, Any]] = []
    for row in partition["repair"]:
        instance_id = str(row["instance_id"])
        window = [int(value) for value in row.get("visual_window") or []]
        path = row.get("frame_path")
        if len(window) != 2 or window[1] <= window[0] or not isinstance(path, list) or not path:
            raise ValueError(f"visual_window:{instance_id}")
        frames = [int(frame["timeline_frame"]) for frame in path]
        if frames != list(range(window[0], window[1])):
            raise ValueError(f"dense_path:{instance_id}")
        if int(row.get("explicit_frame_row_count") or 0) != len(path):
            raise ValueError(f"frame_count:{instance_id}")
        position_keys: List[Dict[str, Any]] = []
        size_keys: List[Dict[str, Any]] = []
        opacity_keys: List[Dict[str, Any]] = []
        for frame in path:
            timeline_frame = int(frame["timeline_frame"])
            local = timeline_frame - window[0]
            fusion = [float(v) for v in frame.get("position_fusion") or []]
            if len(fusion) != 2:
                raise ValueError(f"position:{instance_id}:{timeline_frame}")
            size = float(frame["application_size_candidate"])
            opacity = float(frame["opacity_factor"])
            if size <= 0.0 or opacity != 1.0:
                raise ValueError(f"frame_value:{instance_id}:{timeline_frame}")
            position_keys.append({"timeline_frame": timeline_frame, "local_frame": local, "value": fusion})
            size_keys.append({"timeline_frame": timeline_frame, "local_frame": local, "value": size})
            opacity_keys.append({"timeline_frame": timeline_frame, "local_frame": local, "factor": 1.0})
        font = row.get("font") if isinstance(row.get("font"), Mapping) else {}
        if not font.get("font_family") or not font.get("font_style"):
            raise ValueError(f"font:{instance_id}")
        fill = row.get("fill_repair") if isinstance(row.get("fill_repair"), Mapping) else {}
        plans.append(
            {
                "instance_id": instance_id,
                "target_name": str(row["target_name"]),
                "display_text": str(row.get("canonical_text") or ""),
                "authority_source": str(row.get("authority_source") or ""),
                "target_range": window,
                "visual_window": window,
                "target_track": 0,
                "font": {"font_family": str(font["font_family"]), "font_style": str(font["font_style"])},
                "fill_repair": dict(fill),
                "transcript_timing_authority": False,
                "position_keys": position_keys,
                "size_keys": size_keys,
                "opacity_keys": opacity_keys,
            }
        )
    if len(plans) != EXPECTED_REPAIR:
        raise ValueError(f"repair_plans:{len(plans)}")
    return plans


def rgb_inputs(fill_hex: str) -> Dict[str, float]:
    text = str(fill_hex or "").strip()
    if len(text) != 7 or not text.startswith("#"):
        raise ValueError(f"fill_hex:{fill_hex}")
    return {
        "Red1": int(text[1:3], 16) / 255.0,
        "Green1": int(text[3:5], 16) / 255.0,
        "Blue1": int(text[5:7], 16) / 255.0,
    }


def apply_fill_override(old: Any, base: Any, pilot: Any, item: Any, plan: Mapping[str, Any], static_style: Mapping[str, Any]) -> Dict[str, Any]:
    expected = dict(static_style)
    repair = plan.get("fill_repair") if isinstance(plan.get("fill_repair"), Mapping) else {}
    if repair.get("apply") is not True:
        return {"applied": False, "expected_static_style": expected, "result": {"ok": True}, "ok": True}
    values = rgb_inputs(str(repair.get("fill_hex") or ""))
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        return {"applied": False, "expected_static_style": expected, "result": {"ok": False, "error": "comp_or_text_tool"}, "ok": False}
    result = pilot.set_static_inputs(tool, values)
    expected.update(values)
    return {
        "applied": True,
        "fill_hex": str(repair.get("fill_hex") or ""),
        "source": str(repair.get("source") or ""),
        "confidence": float(repair.get("confidence") or 0.0),
        "expected_static_style": expected,
        "result": result,
        "ok": result.get("ok") is True,
    }


def cleanup_failure(resolve: Any, old: Any, base: Any, project_manager: Any, project: Any, media_pool: Any, original_timeline: Any, original_page: str, accepted_path: Path, accepted_hash: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        target = base.find_timeline(project, TARGET_TIMELINE_NAME) if project is not None else None
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
    old = load_old()
    full, pilot, v6, base, media, visual = old.load_runtime()
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
        "repair_instance_count": 0,
        "unresolved_preserved_count": 0,
        "composite_structural_removed_count": 0,
        "protected_v4_count": 0,
        "explicit_frame_row_count": 0,
        "final_textplus_count": 0,
        "save_call_count": 0,
        "source_timeline_unchanged": False,
        "accepted_state_unchanged": False,
        "target_timeline_kept": False,
        "confirmed74_repair_rollout_completed": False,
        "visual_approval_required": True,
        "fade_polish_deferred": True,
        "further_rollout_authorized": False,
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
        authority = load_json(root / AUTHORITY_RELATIVE_PATH)
        partition = authority_partition(authority)
        unassigned = build_unassigned_plans(authority)
        step3e3_persistent = load_json(root / STEP3E3_PERSISTENT_RELATIVE_PATH)
        protected_expected = old.protected_expectations(step3e3_persistent)
        repair_names = [str(row["target_name"]) for row in unassigned]
        unresolved_names = [str(row["target_name"]) for row in partition["unresolved"]]
        composite_names = [str(row["target_name"]) for row in partition["composite"]]
        protected_names = [str(row["target_name"]) for row in protected_expected]
        deletion_names = repair_names + composite_names
        expected_structural_target = sorted(repair_names + unresolved_names)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        original_timeline = base.safe_value(project, "GetCurrentTimeline", default=None)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_timeline_exists")
        source_unique_id = base.timeline_unique_id(source)
        source_before = full.timeline_inventory(source)
        source_structural_names = full.source_textplus_names(source)
        if len(source_structural_names) != EXPECTED_STRUCTURAL_SOURCE:
            raise RuntimeError("source_structural_count")
        if sorted(source_structural_names) != sorted(repair_names + unresolved_names + composite_names):
            raise RuntimeError("source_structural_names")
        if len(full.visual_first_names(source)) != EXPECTED_PROTECTED or sorted(full.visual_first_names(source)) != sorted(protected_names):
            raise RuntimeError("source_protected_names")
        if len(source_structural_names) + len(full.visual_first_names(source)) != EXPECTED_STRUCTURAL_SOURCE + EXPECTED_PROTECTED:
            raise RuntimeError("source_total")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")
        protected_source_rows = old.verify_protected(base, source, protected_expected)
        if len(protected_source_rows) != EXPECTED_PROTECTED or not all(row.get("ok") for row in protected_source_rows):
            raise RuntimeError("protected_source_state")

        unresolved_source_inventory = full.stable_inventory([row for row in source_before if str(row.get("name") or "") in set(unresolved_names)])
        occupied_rows = [row for row in source_before if str(row.get("name") or "") not in set(deletion_names)]
        plans = old.assign_tracks(unassigned, occupied_rows)
        explicit_rows = sum(len(row["position_keys"]) for row in plans)
        if explicit_rows != int((authority.get("summary") or {}).get("explicit_repair_frame_rows") or 0):
            raise RuntimeError("explicit_frame_rows")
        max_duration = max(int(row["target_range"][1]) - int(row["target_range"][0]) for row in plans)
        carrier_source = base.choose_carrier_source(source, max_duration + 1)
        if not carrier_source.get("ok"):
            raise RuntimeError("carrier_source")

        export_dir = report_dir / "source_comp_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_rows: List[Dict[str, Any]] = []
        source_meta: Dict[str, Dict[str, Any]] = {}
        source_inventory_by_name = {str(row.get("name") or ""): row for row in source_before}
        for plan in plans:
            name = str(plan["target_name"])
            track, source_item = base.find_named_item(source, name)
            if source_item is None:
                raise RuntimeError(f"source_item:{name}")
            comp_path = export_dir / f"{plan['instance_id']}.comp"
            value, call = base.direct_call(source_item, "ExportFusionComp", str(comp_path), 1)
            file_ok = bool(value and comp_path.is_file() and comp_path.stat().st_size > 0)
            inventory_row = source_inventory_by_name.get(name) or {}
            static_style = old.capture_static_style(base, source_item)
            source_meta[name] = {
                "comp_path": comp_path,
                "static_style": static_style,
                "expected_static_style": dict(static_style),
                "opacity_bases": old.capture_opacity_bases(base, source_item, int(inventory_row.get("duration") or 1)),
            }
            export_rows.append({
                "instance_id": plan["instance_id"],
                "target_name": name,
                "track": track,
                "path": str(comp_path),
                "size": comp_path.stat().st_size if comp_path.is_file() else 0,
                "sha256": base.raw_sha256(comp_path) if file_ok else None,
                "call": call,
                "ok": file_ok,
            })
            if not file_ok:
                raise RuntimeError(f"source_comp_export:{name}")
        base.write_json(report_dir / "source_comp_exports.json", {"rows": export_rows, "exported_count": len(export_rows), "ok": len(export_rows) == EXPECTED_REPAIR and all(row["ok"] for row in export_rows)})

        plan_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "repair_instance_count": len(plans),
            "unresolved_preserved_count": len(unresolved_names),
            "composite_structural_removed_count": len(composite_names),
            "protected_v4_count": len(protected_expected),
            "explicit_frame_row_count": explicit_rows,
            "expected_physical_textplus_count": EXPECTED_PHYSICAL_TEXTPLUS,
            "track_range": [TRACK_MIN, TRACK_MAX],
            "transcript_timing_authority": False,
            "static_style_policy": "source_comp_preserved_except_evidence_gated_fill",
            "fade_polish_deferred": True,
            "unresolved_target_names": unresolved_names,
            "composite_removed_target_names": composite_names,
            "plans": plans,
            "ok": len(plans) == EXPECTED_REPAIR,
        }
        base.write_json(report_dir / "rollout_plan.json", plan_document)
        if not plan_document["ok"]:
            raise RuntimeError("rollout_plan")
        base.write_json(report_dir / "rollout_preflight.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "resolve_calls": resolve_calls,
            "source_unique_id": source_unique_id,
            "source_inventory": source_before,
            "source_structural_count": len(source_structural_names),
            "source_protected_count": len(full.visual_first_names(source)),
            "source_v2_item_count": len(full.track_two_item_names(source)),
            "protected_source_rows": protected_source_rows,
            "unresolved_source_inventory": unresolved_source_inventory,
            "carrier_source": {key: base.json_safe(value) for key, value in carrier_source.items() if key not in {"item", "media_pool_item"}},
            "ok": True,
        })

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")
        deletion = full.delete_named_textplus(target, deletion_names)
        time.sleep(0.20)
        if not deletion.get("ok") or deletion.get("deleted") != EXPECTED_REPAIR + EXPECTED_COMPOSITE_REMOVED:
            raise RuntimeError("delete_confirmed74_plus_composite3")
        track_setup = base.ensure_video_tracks(target, TRACK_MAX)
        if not track_setup.get("ok"):
            raise RuntimeError("track_setup")
        after_delete_inventory = full.timeline_inventory(target)
        unresolved_after_delete = full.stable_inventory([row for row in after_delete_inventory if str(row.get("name") or "") in set(unresolved_names)])
        if unresolved_after_delete != unresolved_source_inventory:
            raise RuntimeError("unresolved_changed_after_delete")
        if sorted(full.source_textplus_names(target)) != sorted(unresolved_names):
            raise RuntimeError("structural_after_delete")
        protected_after_delete = old.verify_protected(base, target, protected_expected)
        if not all(row.get("ok") for row in protected_after_delete):
            raise RuntimeError("protected_after_delete")
        base.write_json(report_dir / "rollout_timeline_setup.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "duplicate_call": duplicate_call,
            "select_call": select_call,
            "delete": deletion,
            "track_setup": track_setup,
            "unresolved_after_delete": len(full.source_textplus_names(target)),
            "protected_after_delete": protected_after_delete,
            "composite_structural_removed_count": EXPECTED_COMPOSITE_REMOVED,
            "ok": len(full.source_textplus_names(target)) == EXPECTED_UNRESOLVED and len(full.visual_first_names(target)) == EXPECTED_PROTECTED,
        })

        specs = [{"cue_id": row["instance_id"], "name": row["target_name"], "text": row["display_text"], "target_range": row["target_range"], "target_track": row["target_track"]} for row in plans]
        assigned: Dict[str, Any] = {}
        append_rows: List[Dict[str, Any]] = []
        for batch_index, batch in enumerate(pilot.chunked(specs, APPEND_BATCH_SIZE)):
            result = v6.append_batch_by_placement(media_pool, target, carrier_source, batch)
            ok = result.get("ok") is True and len(result.get("assigned") or []) == len(batch)
            append_rows.append({"batch_index": batch_index, "requested_count": len(batch), "assigned_count": len(result.get("assigned") or []), "result": base.json_safe({key: value for key, value in result.items() if key != "assigned"}), "ok": ok})
            if not ok:
                raise RuntimeError(f"append_batch:{batch_index}")
            for spec, item in result["assigned"]:
                cue_id = str(spec["cue_id"])
                if cue_id in assigned:
                    raise RuntimeError(f"duplicate_assignment:{cue_id}")
                assigned[cue_id] = item
        base.write_json(report_dir / "rollout_carrier_append.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "batch_count": len(append_rows), "requested_count": len(specs), "assigned_count": len(assigned), "batches": append_rows, "ok": len(assigned) == EXPECTED_REPAIR and all(row["ok"] for row in append_rows)})

        application_rows: List[Dict[str, Any]] = []
        for plan in plans:
            item = assigned.get(str(plan["instance_id"]))
            meta = source_meta[str(plan["target_name"])]
            if item is None:
                raise RuntimeError(f"assigned_item:{plan['instance_id']}")
            imported, import_call = base.direct_call(item, "ImportFusionComp", str(meta["comp_path"]))
            clone = {"returned": base.json_safe(imported), "call": import_call, "ok": bool(imported and base.as_int(base.safe_value(item, "GetFusionCompCount", default=0), 0) == 1)}
            application = old.apply_plan(base, visual, pilot, item, plan, meta["opacity_bases"]) if clone["ok"] else {"ok": False, "error": "clone"}
            fill = apply_fill_override(old, base, pilot, item, plan, meta["static_style"]) if application.get("ok") else {"ok": False, "error": "application"}
            meta["expected_static_style"] = fill.get("expected_static_style") or meta["static_style"]
            style_ok = old.style_matches(base, item, meta["expected_static_style"]) if fill.get("ok") else False
            row = {
                "instance_id": plan["instance_id"],
                "target_name": plan["target_name"],
                "explicit_frame_rows": len(plan["position_keys"]),
                "authority_source": plan["authority_source"],
                "clone": clone,
                "application": application,
                "fill_repair": fill,
                "static_style_expected": meta["expected_static_style"],
                "static_style_ok": style_ok,
                "ok": bool(clone["ok"] and application.get("ok") and fill.get("ok") and style_ok),
            }
            application_rows.append(row)
            base.write_json(report_dir / "rollout_application.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "expected_instance_count": EXPECTED_REPAIR, "instance_count": len(application_rows), "complete": False, "rows": application_rows, "ok": False})
            if not row["ok"]:
                raise RuntimeError(f"apply:{plan['instance_id']}")
        base.write_json(report_dir / "rollout_application.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "expected_instance_count": EXPECTED_REPAIR, "instance_count": len(application_rows), "explicit_frame_row_count": explicit_rows, "fill_override_count": sum(1 for row in application_rows if (row.get("fill_repair") or {}).get("applied") is True), "complete": True, "rows": application_rows, "ok": len(application_rows) == EXPECTED_REPAIR and all(row["ok"] for row in application_rows)})

        found = pilot.target_items(target, plans)
        readback_rows: List[Dict[str, Any]] = []
        for plan in plans:
            item = found.get(str(plan["target_name"]), (0, None))[1]
            meta = source_meta[str(plan["target_name"])]
            readback_rows.append(old.read_plan(base, item, target, plan, meta["opacity_bases"], meta["expected_static_style"]) if item is not None else {"target_name": plan["target_name"], "ok": False, "error": "missing"})
        protected_before_save = old.verify_protected(base, target, protected_expected)
        target_inventory = full.timeline_inventory(target)
        unresolved_before_save = full.stable_inventory([row for row in target_inventory if str(row.get("name") or "") in set(unresolved_names)])
        target_structural_names = full.source_textplus_names(target)
        pre_checks = {
            "repair_exact": len(readback_rows) == EXPECTED_REPAIR and all(row.get("ok") for row in readback_rows),
            "unresolved_preserved": unresolved_before_save == unresolved_source_inventory and all(name in target_structural_names for name in unresolved_names),
            "composite_structural_absent": not any(name in target_structural_names for name in composite_names),
            "protected_v4_exact": len(protected_before_save) == EXPECTED_PROTECTED and all(row.get("ok") for row in protected_before_save),
            "structural_names_exact": sorted(target_structural_names) == expected_structural_target,
            "protected_names_exact": sorted(full.visual_first_names(target)) == sorted(protected_names),
            "physical_textplus_count": len(target_structural_names) + len(full.visual_first_names(target)) == EXPECTED_PHYSICAL_TEXTPLUS,
            "v2_empty": not full.track_two_item_names(target),
            "non_scope_inventory_preserved": old.filtered_stable_inventory(full, target_inventory, deletion_names) == old.filtered_stable_inventory(full, source_before, deletion_names),
        }
        base.write_json(report_dir / "rollout_readback_before_save.json", {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "rows": readback_rows, "protected_v4_rows": protected_before_save, "unresolved_inventory": unresolved_before_save, "composite_removed_target_names": composite_names, "explicit_frame_row_count": explicit_rows, "checks": pre_checks, "ok": all(pre_checks.values())})
        if not all(pre_checks.values()):
            raise RuntimeError("readback_before_save")

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
        source_after_inventory = full.timeline_inventory(source_after)
        target_after_inventory = full.timeline_inventory(target_after)
        found_after = pilot.target_items(target_after, plans)
        persistent_rows: List[Dict[str, Any]] = []
        for plan in plans:
            item = found_after.get(str(plan["target_name"]), (0, None))[1]
            meta = source_meta[str(plan["target_name"])]
            persistent_rows.append(old.read_plan(base, item, target_after, plan, meta["opacity_bases"], meta["expected_static_style"]) if item is not None else {"target_name": plan["target_name"], "ok": False, "error": "missing"})
        protected_after = old.verify_protected(base, target_after, protected_expected)
        target_after_structural = full.source_textplus_names(target_after)
        unresolved_after_save = full.stable_inventory([row for row in target_after_inventory if str(row.get("name") or "") in set(unresolved_names)])
        persistent_checks = {
            "source_timeline_unchanged": base.timeline_unique_id(source_after) == source_unique_id and full.stable_inventory(source_after_inventory) == full.stable_inventory(source_before),
            "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
            "target_retained": base.timeline_name(target_after) == TARGET_TIMELINE_NAME,
            "repair_exact": len(persistent_rows) == EXPECTED_REPAIR and all(row.get("ok") for row in persistent_rows),
            "unresolved_preserved": unresolved_after_save == unresolved_source_inventory,
            "composite_structural_absent": not any(name in target_after_structural for name in composite_names),
            "protected_v4_exact": len(protected_after) == EXPECTED_PROTECTED and all(row.get("ok") for row in protected_after),
            "structural_names_exact": sorted(target_after_structural) == expected_structural_target,
            "protected_names_exact": sorted(full.visual_first_names(target_after)) == sorted(protected_names),
            "physical_textplus_count": len(target_after_structural) + len(full.visual_first_names(target_after)) == EXPECTED_PHYSICAL_TEXTPLUS,
            "v2_empty": not full.track_two_item_names(target_after),
            "non_scope_inventory_preserved": old.filtered_stable_inventory(full, target_after_inventory, deletion_names) == old.filtered_stable_inventory(full, source_before, deletion_names),
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "rows": persistent_rows,
            "protected_v4_rows": protected_after,
            "unresolved_inventory": unresolved_after_save,
            "composite_removed_target_names": composite_names,
            "explicit_frame_row_count": explicit_rows,
            "checks": persistent_checks,
            "save": save,
            "confirmed74_repair_rollout_completed": True,
            "visual_approval_required": True,
            "fade_polish_deferred": True,
            "further_rollout_authorized": False,
            "ok": all(persistent_checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")
        report.update({
            "ok": True,
            "finished_at": base.utc_now(),
            "repair_instance_count": EXPECTED_REPAIR,
            "unresolved_preserved_count": EXPECTED_UNRESOLVED,
            "composite_structural_removed_count": EXPECTED_COMPOSITE_REMOVED,
            "protected_v4_count": EXPECTED_PROTECTED,
            "explicit_frame_row_count": explicit_rows,
            "final_textplus_count": EXPECTED_PHYSICAL_TEXTPLUS,
            "source_timeline_unchanged": persistent_checks["source_timeline_unchanged"],
            "accepted_state_unchanged": persistent_checks["accepted_state_unchanged"],
            "target_timeline_kept": True,
            "confirmed74_repair_rollout_completed": True,
        })
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if target_created and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_failure(resolve, old, base, project_manager, project, media_pool, original_timeline, original_page, accepted_path, accepted_hash)
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["failure_cleanup_ok"] = cleanup.get("ok") is True
            report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
        report["finished_at"] = base.utc_now()
        return report
