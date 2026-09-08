"""Apply the locked Step 3E V4 visual authority to exactly 17 visual-first Text+ instances.

The task duplicates the latest retained Group-02 font-metrics timeline, removes
only the 17 visual-first Text+ items, and recreates those 17 items from the
offline V4 source-pixel authority. The other 100 editable V6 Text+ items and all
non-caption timeline inventory must remain unchanged.

This task does not render and does not authorize the remaining-caption rollout.
The new timeline is retained only for Step 3E.4 seven-window visual acceptance.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1"
MODE = "STEP_3E_FULL_BASELINE_VISUAL_POLISH"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3E_full_baseline_visual_polish_v1.py"

SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_fontmetrics_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_17tokens_v1"

V4_AUTHORITY_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
BASELINE_PLAN_RELATIVE_PATH = (
    ".agent/reports/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1/"
    "20260810T080927254297Z_befb7b9f1474440fb817520c47ba8cd3/full_rollout_plan.json"
)
GROUP02_CONTRACT_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_font_metrics_v1.json"
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"

EXPECTED_GROUP_COUNT = 7
EXPECTED_VISUAL_FIRST = 17
EXPECTED_V6_TEXTPLUS = 100
EXPECTED_TOTAL_TEXTPLUS = 117
EXPECTED_EXPLICIT_FRAME_ROWS = 397
APPEND_BATCH_SIZE = 6
FULL_PREFIX = "VC_VISUAL_FIRST_FULL_"
GROUP02_TOKEN_IDS = {"vf_02_already", "vf_02_decorative_glyph"}


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def _runtime_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime() -> Tuple[Any, Any, Any, Any, Any]:
    full_path = Path(__file__).with_name("step_3D_visual_first_full_rollout_baseline.py")
    full = _runtime_module(full_path, "vc_full_rollout_for_step3e3")
    return full, full.pilot, full.v6, full.base, full.media


def flatten_v4_tokens(authority: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if authority.get("task_id") != "DZSQH7AUHJT_STEP_3E_TEMPORAL_VISUAL_AUTHORITY_V4":
        raise ValueError("v4_task")
    if authority.get("ok") is not True:
        raise ValueError("v4_not_ok")
    policy = authority.get("authority_policy") if isinstance(authority.get("authority_policy"), Mapping) else {}
    if policy.get("primary_authority") != "source_video_pixels":
        raise ValueError("v4_primary_authority")
    if policy.get("transcript_timing_authority") is not False:
        raise ValueError("v4_transcript_timing")
    if policy.get("resolve_modified") is not False:
        raise ValueError("v4_resolve_modified")
    if policy.get("full_rollout_authorized") is not False:
        raise ValueError("v4_full_rollout")

    groups = authority.get("groups")
    if not isinstance(groups, list) or len(groups) != EXPECTED_GROUP_COUNT:
        raise ValueError("v4_group_count")

    rows: List[Dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            raise ValueError("v4_group")
        tokens = group.get("tokens")
        if not isinstance(tokens, list):
            raise ValueError("v4_group_tokens")
        for token in tokens:
            if not isinstance(token, Mapping):
                raise ValueError("v4_token")
            row = dict(token)
            row["group_id"] = str(group.get("group_id") or "")
            row["group_label"] = str(group.get("label") or "")
            row["group_window"] = [int(v) for v in group.get("group_window") or []]
            rows.append(row)

    if len(rows) != EXPECTED_VISUAL_FIRST:
        raise ValueError(f"v4_token_count:{len(rows)}")
    token_ids = [str(row.get("visual_token_id") or "") for row in rows]
    if not all(token_ids) or len(set(token_ids)) != EXPECTED_VISUAL_FIRST:
        raise ValueError("v4_token_identity")
    return rows


def baseline_plans(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if document.get("task_id") != "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1":
        raise ValueError("baseline_task")
    if document.get("ok") is not True:
        raise ValueError("baseline_not_ok")
    plans = document.get("visual_first_instances")
    if not isinstance(plans, list) or len(plans) != EXPECTED_VISUAL_FIRST:
        raise ValueError("baseline_visual_count")
    rows = [dict(row) for row in plans if isinstance(row, Mapping)]
    if len(rows) != EXPECTED_VISUAL_FIRST:
        raise ValueError("baseline_plan")
    if len({str(row.get("visual_token_id") or "") for row in rows}) != EXPECTED_VISUAL_FIRST:
        raise ValueError("baseline_token_identity")
    return rows


def build_v4_application_plans(
    authority: Mapping[str, Any],
    baseline_document: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    tokens = flatten_v4_tokens(authority)
    baseline = {str(row["visual_token_id"]): row for row in baseline_plans(baseline_document)}
    plans: List[Dict[str, Any]] = []
    total_frames = 0

    for token in tokens:
        token_id = str(token["visual_token_id"])
        source = baseline.get(token_id)
        if source is None:
            raise ValueError(f"baseline_token_missing:{token_id}")

        frame_path = token.get("frame_path")
        if not isinstance(frame_path, list) or not frame_path:
            raise ValueError(f"frame_path:{token_id}")
        window = [int(v) for v in token.get("visual_window") or []]
        if len(window) != 2 or window[1] <= window[0]:
            raise ValueError(f"visual_window:{token_id}")

        timeline_frames = [int(row["timeline_frame"]) for row in frame_path]
        expected_frames = list(range(window[0], window[1]))
        if timeline_frames != expected_frames:
            raise ValueError(f"frame_path_not_explicit:{token_id}")
        total_frames += len(frame_path)

        position_keys: List[Dict[str, Any]] = []
        size_keys: List[Dict[str, Any]] = []
        opacity_keys: List[Dict[str, Any]] = []
        for raw in frame_path:
            frame = int(raw["timeline_frame"])
            local = frame - window[0]
            fusion = [float(v) for v in raw.get("position_fusion") or []]
            top_origin = [float(v) for v in raw.get("position_top_origin") or []]
            if len(fusion) != 2 or len(top_origin) != 2:
                raise ValueError(f"position:{token_id}:{frame}")
            size = float(raw["application_size_candidate"])
            scale = float(raw["size_scale"])
            opacity = float(raw["opacity_factor"])
            if size <= 0.0 or scale <= 0.0 or not 0.0 <= opacity <= 1.0:
                raise ValueError(f"frame_value:{token_id}:{frame}")
            position_keys.append({
                "timeline_frame": frame,
                "local_frame": local,
                "value": fusion,
                "source_top_origin_value": top_origin,
            })
            size_keys.append({
                "timeline_frame": frame,
                "local_frame": local,
                "value": size,
                "scale": scale,
            })
            opacity_keys.append({
                "timeline_frame": frame,
                "local_frame": local,
                "factor": opacity,
            })

        style_lock = token.get("style_lock") if isinstance(token.get("style_lock"), Mapping) else {}
        stroke = style_lock.get("stroke") if isinstance(style_lock.get("stroke"), Mapping) else {}
        if stroke.get("enabled") is not False:
            raise ValueError(f"stroke_policy:{token_id}")

        plan = {
            "visual_token_id": token_id,
            "group_id": token["group_id"],
            "group_label": token["group_label"],
            "group_window": token["group_window"],
            "display_text": str(token["display_text"]),
            "source_cue_id": token.get("source_cue_id"),
            "role": token.get("role"),
            "visual_kind": token.get("visual_kind"),
            "z_order": token.get("z_order"),
            "text_authority": token.get("text_authority"),
            "font": dict(token["font"]),
            "style_lock": dict(style_lock),
            "animation_phases": dict(token.get("animation_phases") or {}),
            "motion_summary": dict(token.get("motion_summary") or {}),
            "source_pixel_anchor": dict(token.get("source_pixel_anchor") or {}),
            "position_basis": token.get("position_basis"),
            "font_metrics_status": token.get("font_metrics_status"),
            "base_size": float(token["application_base_size_candidate"]),
            "visual_window": window,
            "target_range": window,
            "target_track": int(source["target_track"]),
            "target_name": str(source["target_name"]),
            "position_keys": position_keys,
            "size_keys": size_keys,
            "opacity_keys": opacity_keys,
            "transcript_timing_promoted_to_authority": False,
        }
        plans.append(plan)

    if total_frames != EXPECTED_EXPLICIT_FRAME_ROWS:
        raise ValueError(f"explicit_frame_rows:{total_frames}")
    if len({row["target_name"] for row in plans}) != EXPECTED_VISUAL_FIRST:
        raise ValueError("target_name_duplicate")
    if len({row["target_track"] for row in plans}) != EXPECTED_VISUAL_FIRST:
        raise ValueError("target_track_duplicate")
    if sorted(row["target_track"] for row in plans) != list(range(8, 25)):
        raise ValueError("target_tracks")
    return plans


def build_source_readback_plans(
    baseline_document: Mapping[str, Any],
    group02_contract: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    baseline = baseline_plans(baseline_document)
    g02_raw = group02_contract.get("plans")
    if group02_contract.get("task_id") != "DZSQH7AUHJT_STEP_3E_GROUP02_FONT_METRICS_POLISH_V1":
        raise ValueError("group02_contract_task")
    if group02_contract.get("ok") is not True or not isinstance(g02_raw, list) or len(g02_raw) != 2:
        raise ValueError("group02_contract")
    g02 = {str(row["visual_token_id"]): dict(row) for row in g02_raw if isinstance(row, Mapping)}
    if set(g02) != GROUP02_TOKEN_IDS:
        raise ValueError("group02_tokens")

    rows: List[Dict[str, Any]] = []
    for source in baseline:
        token_id = str(source["visual_token_id"])
        row = dict(g02[token_id]) if token_id in g02 else dict(source)
        if str(row.get("target_name") or "") != str(source.get("target_name") or ""):
            raise ValueError(f"source_target_name:{token_id}")
        if int(row.get("target_track") or 0) != int(source.get("target_track") or 0):
            raise ValueError(f"source_target_track:{token_id}")
        rows.append(row)
    return rows


def target_names(plans: Sequence[Mapping[str, Any]]) -> List[str]:
    names = [str(row["target_name"]) for row in plans]
    if len(names) != EXPECTED_VISUAL_FIRST or len(set(names)) != EXPECTED_VISUAL_FIRST:
        raise ValueError("target_names")
    return names


def filtered_stable_inventory(
    full: Any,
    rows: Sequence[Mapping[str, Any]],
    names: Iterable[str],
) -> List[Tuple[Any, ...]]:
    blocked = set(str(value) for value in names)
    return full.stable_inventory([row for row in rows if str(row.get("name") or "") not in blocked])


def total_editable_textplus_count(full: Any, timeline: Any) -> int:
    return len(full.source_textplus_names(timeline)) + len(full.visual_first_names(timeline))


def read_plans(pilot: Any, timeline: Any, plans: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    found = pilot.target_items(timeline, plans)
    rows: List[Dict[str, Any]] = []
    for plan in plans:
        token_id = str(plan["visual_token_id"])
        track, item = found.get(str(plan["target_name"]), (0, None))
        if item is None:
            rows.append({"visual_token_id": token_id, "target_name": plan["target_name"], "ok": False, "error": "missing"})
            continue
        check_plan = dict(plan)
        check_plan["timeline"] = timeline
        row = pilot.read_token(item, check_plan)
        row["visual_token_id"] = token_id
        row["target_name"] = plan["target_name"]
        rows.append(row)
    return rows


def cleanup_failure(
    resolve: Any,
    base: Any,
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
    full, pilot, v6, base, media = load_runtime()
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
        "polished_instance_count": 0,
        "unchanged_item_count": 0,
        "final_textplus_count": 0,
        "explicit_frame_row_count": 0,
        "source_timeline_unchanged": False,
        "accepted_state_unchanged": False,
        "save_call_count": 0,
        "target_timeline_kept": False,
        "visual_approval_required": True,
        "remaining_caption_rollout_authorized": False,
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

        authority = load_json(root / V4_AUTHORITY_RELATIVE_PATH)
        baseline_document = load_json(root / BASELINE_PLAN_RELATIVE_PATH)
        group02_contract = load_json(root / GROUP02_CONTRACT_RELATIVE_PATH)
        plans = build_v4_application_plans(authority, baseline_document)
        source_plans = build_source_readback_plans(baseline_document, group02_contract)
        names = target_names(plans)

        explicit_rows = sum(len(row["position_keys"]) for row in plans)
        plan_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "authority_task_id": authority.get("task_id"),
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "authority_path": V4_AUTHORITY_RELATIVE_PATH,
            "baseline_plan_path": BASELINE_PLAN_RELATIVE_PATH,
            "group02_source_contract": GROUP02_CONTRACT_RELATIVE_PATH,
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "group_count": EXPECTED_GROUP_COUNT,
            "visual_token_count": len(plans),
            "explicit_frame_row_count": explicit_rows,
            "transcript_timing_authority": False,
            "remaining_caption_rollout_authorized": False,
            "visual_approval_required": True,
            "plans": plans,
            "ok": len(plans) == EXPECTED_VISUAL_FIRST and explicit_rows == EXPECTED_EXPLICIT_FRAME_ROWS,
        }
        base.write_json(report_dir / "polish_plan.json", plan_document)
        if not plan_document["ok"]:
            raise RuntimeError("polish_plan")

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        original_timeline = base.safe_value(project, "GetCurrentTimeline", default=None)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_timeline_exists")

        source_unique_id = base.timeline_unique_id(source)
        source_before = full.timeline_inventory(source)
        if len(full.source_textplus_names(source)) != EXPECTED_V6_TEXTPLUS:
            raise RuntimeError("source_v6_textplus_count")
        if len(full.visual_first_names(source)) != EXPECTED_VISUAL_FIRST:
            raise RuntimeError("source_visual_first_count")
        if total_editable_textplus_count(full, source) != EXPECTED_TOTAL_TEXTPLUS:
            raise RuntimeError("source_total_textplus_count")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")
        if sorted(full.visual_first_names(source)) != sorted(names):
            raise RuntimeError("source_visual_names")

        source_readback = read_plans(pilot, source, source_plans)
        source_state_ok = len(source_readback) == EXPECTED_VISUAL_FIRST and all(row.get("ok") for row in source_readback)
        if not source_state_ok:
            raise RuntimeError("source_visual_state")

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
            "source_total_textplus_count": total_editable_textplus_count(full, source),
            "source_v2_item_count": len(full.track_two_item_names(source)),
            "source_visual_state_rows": source_readback,
            "source_visual_state_exact": source_state_ok,
            "carrier_source": {
                key: base.json_safe(value)
                for key, value in carrier_source.items()
                if key not in {"item", "media_pool_item"}
            },
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

        target_before = full.timeline_inventory(target)
        duplicate_exact = full.stable_inventory(target_before) == full.stable_inventory(source_before)
        if not duplicate_exact:
            raise RuntimeError("duplicate_inventory")

        deletion = full.delete_named_textplus(target, names)
        time.sleep(0.25)
        if not deletion.get("ok") or deletion.get("deleted") != EXPECTED_VISUAL_FIRST:
            raise RuntimeError("delete_visual_first")

        track_setup = base.ensure_video_tracks(target, max(row["target_track"] for row in plans))
        if not track_setup.get("ok"):
            raise RuntimeError("track_setup")

        after_delete = full.timeline_inventory(target)
        unrelated_after_delete_exact = (
            filtered_stable_inventory(full, after_delete, names)
            == filtered_stable_inventory(full, source_before, names)
        )
        if not unrelated_after_delete_exact:
            raise RuntimeError("unrelated_inventory_after_delete")

        base.write_json(report_dir / "polish_timeline_setup.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "open_edit_call": open_call,
            "duplicate_call": duplicate_call,
            "select_call": select_call,
            "duplicate_inventory_exact": duplicate_exact,
            "visual_first_delete": deletion,
            "track_setup": track_setup,
            "unrelated_inventory_after_delete_exact": unrelated_after_delete_exact,
            "ok": True,
        })

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
                "requested_count": len(batch),
                "assigned_count": len(result.get("assigned") or []),
                "result": base.json_safe({key: value for key, value in result.items() if key != "assigned"}),
                "ok": result.get("ok") is True and len(result.get("assigned") or []) == len(batch),
            })
            if not append_rows[-1]["ok"]:
                raise RuntimeError(f"append_batch:{batch_index}")
            for spec, item in result["assigned"]:
                cue_id = str(spec["cue_id"])
                if cue_id in assigned:
                    raise RuntimeError(f"duplicate_assignment:{cue_id}")
                assigned[cue_id] = item

        append_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "batch_count": len(append_rows),
            "requested_count": len(specs),
            "assigned_count": len(assigned),
            "batches": append_rows,
            "ok": len(assigned) == EXPECTED_VISUAL_FIRST and all(row["ok"] for row in append_rows),
        }
        base.write_json(report_dir / "polish_carrier_append.json", append_document)
        if not append_document["ok"]:
            raise RuntimeError("carrier_append")

        template_path = root / pilot.TEMPLATE_COMP_RELATIVE_PATH
        application_rows: List[Dict[str, Any]] = []
        for plan in plans:
            item = assigned.get(str(plan["visual_token_id"]))
            if item is None:
                raise RuntimeError(f"assigned_item:{plan['visual_token_id']}")
            clone = media.import_source_comp(item, template_path)
            application = pilot.apply_token(item, plan) if clone.get("ok") else {"ok": False, "error": "clone"}
            row = {
                "visual_token_id": plan["visual_token_id"],
                "target_name": plan["target_name"],
                "explicit_frame_rows": len(plan["position_keys"]),
                "clone": clone,
                "application": application,
                "ok": bool(clone.get("ok") and application.get("ok")),
            }
            application_rows.append(row)
            base.write_json(report_dir / "polish_application.json", {
                "schema_version": 1,
                "task_id": TASK_ID,
                "run_id": run_id,
                "expected_instance_count": EXPECTED_VISUAL_FIRST,
                "instance_count": len(application_rows),
                "complete": False,
                "rows": application_rows,
                "ok": False,
            })
            if not row["ok"]:
                stage = "clone" if not clone.get("ok") else pilot.application_failure_stage(application)
                raise RuntimeError(f"apply_token:{plan['visual_token_id']}:{stage}")

        base.write_json(report_dir / "polish_application.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "expected_instance_count": EXPECTED_VISUAL_FIRST,
            "instance_count": len(application_rows),
            "explicit_frame_row_count": explicit_rows,
            "complete": True,
            "rows": application_rows,
            "ok": len(application_rows) == EXPECTED_VISUAL_FIRST and all(row["ok"] for row in application_rows),
        })

        readback_rows = read_plans(pilot, target, plans)
        target_inventory = full.timeline_inventory(target)
        pre_save_checks = {
            "visual_first_exact": len(readback_rows) == EXPECTED_VISUAL_FIRST and all(row.get("ok") for row in readback_rows),
            "unchanged_inventory_exact": (
                filtered_stable_inventory(full, target_inventory, names)
                == filtered_stable_inventory(full, source_before, names)
            ),
            "v6_textplus_count": len(full.source_textplus_names(target)) == EXPECTED_V6_TEXTPLUS,
            "visual_first_count": len(full.visual_first_names(target)) == EXPECTED_VISUAL_FIRST,
            "visual_first_names_exact": sorted(full.visual_first_names(target)) == sorted(names),
            "final_textplus_count": total_editable_textplus_count(full, target) == EXPECTED_TOTAL_TEXTPLUS,
            "v2_empty": not full.track_two_item_names(target),
        }
        base.write_json(report_dir / "polish_readback_before_save.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "rows": readback_rows,
            "explicit_frame_row_count": explicit_rows,
            "checks": pre_save_checks,
            "ok": all(pre_save_checks.values()),
        })
        if not all(pre_save_checks.values()):
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

        source_after_inventory = full.timeline_inventory(source_after)
        target_after_inventory = full.timeline_inventory(target_after)
        persistent_rows = read_plans(pilot, target_after, plans)
        persistent_checks = {
            "source_timeline_unchanged": (
                base.timeline_unique_id(source_after) == source_unique_id
                and full.stable_inventory(source_after_inventory) == full.stable_inventory(source_before)
            ),
            "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
            "target_retained": base.timeline_name(target_after) == TARGET_TIMELINE_NAME,
            "visual_first_exact": len(persistent_rows) == EXPECTED_VISUAL_FIRST and all(row.get("ok") for row in persistent_rows),
            "unchanged_inventory_exact": (
                filtered_stable_inventory(full, target_after_inventory, names)
                == filtered_stable_inventory(full, source_before, names)
            ),
            "v6_textplus_count": len(full.source_textplus_names(target_after)) == EXPECTED_V6_TEXTPLUS,
            "visual_first_count": len(full.visual_first_names(target_after)) == EXPECTED_VISUAL_FIRST,
            "visual_first_names_exact": sorted(full.visual_first_names(target_after)) == sorted(names),
            "final_textplus_count": total_editable_textplus_count(full, target_after) == EXPECTED_TOTAL_TEXTPLUS,
            "v2_empty": not full.track_two_item_names(target_after),
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "rows": persistent_rows,
            "explicit_frame_row_count": explicit_rows,
            "checks": persistent_checks,
            "save": save,
            "visual_approval_required": True,
            "remaining_caption_rollout_authorized": False,
            "full_rollout_authorized": False,
            "ok": all(persistent_checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")

        report.update({
            "ok": True,
            "finished_at": base.utc_now(),
            "polished_instance_count": EXPECTED_VISUAL_FIRST,
            "unchanged_item_count": EXPECTED_V6_TEXTPLUS,
            "final_textplus_count": EXPECTED_TOTAL_TEXTPLUS,
            "explicit_frame_row_count": explicit_rows,
            "source_timeline_unchanged": persistent_checks["source_timeline_unchanged"],
            "accepted_state_unchanged": persistent_checks["accepted_state_unchanged"],
            "target_timeline_kept": True,
            "visual_approval_required": True,
            "remaining_caption_rollout_authorized": False,
            "full_rollout_authorized": False,
        })
        return report

    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if target_created and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_failure(
                resolve,
                base,
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
