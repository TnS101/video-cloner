"""Bounded disposable live proof for the STEP 4B Text+ animation adapter."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import traceback
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "VIDEO_CLONER_STEP4C_ANIMATION_LIVE_PROBE_V1"
MODE = "step4c_animation_live_probe"
PROJECT_NAME = "New Project 1"
REEL1 = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4_flash_transition_v4"
REEL2 = "DcJRJtUKScu_standalone_timeline"
SOURCE_TIMELINE = REEL1
PROBE_PREFIX = "VC_STEP4C_ANIMATION_PROBE_"
TARGET_TRACK = 3
TARGET_FRAMES = (100, 250, 400)
EXISTING_TARGET_FRAMES = (250, 400, 550)
ITEM_NAMES = ("VC_STEP4C_CENTER", "VC_STEP4C_SIZE", "VC_STEP4C_STATIC")
STATIC_PROOF_NAME = "VC_STEP4C_STATIC_PROOF"
STATIC_PROOF_FRAME = 100
TITLE_DURATION = 12

CENTER_PAYLOAD = {
    "authority": "visual_observed",
    "source_evidence_id": "step4c_disposable_center",
    "source_type": "slide",
    "property": "Center",
    "keyframes": [
        {"frame": 0, "relative_time": 0.0, "value": [-0.0106, 0.0565]},
        {"frame": 2, "relative_time": 1.0, "value": [0.0, 0.0]},
    ],
}
SIZE_PAYLOAD = {
    "authority": "visual_observed",
    "source_evidence_id": "step4c_disposable_size",
    "source_type": "scale",
    "property": "Size",
    "keyframes": [
        {"frame": 0, "relative_time": 0.0, "value": 1.30217657},
        {"frame": 7, "relative_time": 1.0, "value": 1.0},
    ],
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dependencies(root: Path) -> tuple[Any, Any, Any, Any]:
    previous = os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN")
    os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = "1"
    try:
        animation = _load("vc_step4c_animation", root / "resolve_workspace/resolve_apply_caption_animation_step_3C.py")
    finally:
        if previous is None:
            os.environ.pop("VC_DISABLE_WORKSPACE_AUTORUN", None)
        else:
            os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = previous
    return (
        _load("vc_step4c_native", root / "resolve_workspace/modules/step_3D_native_textplus_title_probe.py"),
        animation,
        _load("vc_step4c_snapshot", root / "resolve_workspace/modules/video_cloner_phase4b_timeline_application.py"),
        _load("vc_step4c_carrier", root / "scripts/davinci/resolve_apply_video_cloner_metadata.py"),
    )


def _find_unique(native: Any, project: Any, name: str) -> Any:
    matches = []
    for index in range(1, native.timeline_count(project) + 1):
        timeline = native.safe_value(project, "GetTimelineByIndex", index, default=None)
        if timeline is not None and native.timeline_name(timeline) == name:
            matches.append(timeline)
    return matches[0] if len(matches) == 1 else None


def queue_preflight(root: Path, run_id: str) -> dict[str, Any]:
    queue = root / ".agent/commands"
    pending = sorted((queue / "pending").glob("*.json"))
    running = sorted((queue / "running").glob("*.json"))
    if pending or len(running) != 1:
        raise RuntimeError(f"queue_state:pending={len(pending)}:running={len(running)}")
    command = json.loads(running[0].read_text(encoding="utf-8-sig"))
    if command.get("run_id") != run_id or command.get("task_id") != TASK_ID:
        raise RuntimeError("queue_identity")
    return {"pending_count": 0, "running_count": 1, "running_command": running[0].name}


def _modifier(animation: Any, native: Any, tool: Any, input_name: str) -> dict[str, Any]:
    output = animation.connected_output(animation.find_input(tool, input_name))
    if output is None:
        return {"connected": False, "type": None, "keyframes": {}, "keyframe_count": 0}
    modifier = native.safe_value(output, "GetTool", default=None)
    attrs = native.safe_value(modifier, "GetAttrs", default={}) if modifier is not None else {}
    output_attrs = native.safe_value(output, "GetAttrs", default={}) or {}
    modifier_type = str((attrs or {}).get("TOOLS_RegID") or (attrs or {}).get("TOOLS_Name") or output_attrs.get("OUTS_Name") or "")
    keyframes = native.safe_value(modifier, "GetKeyFrames", default=None) if modifier is not None else None
    if keyframes is None:
        keyframes = native.safe_value(output, "GetKeyFrames", default={}) or {}
    safe_keys = native.json_safe(keyframes)
    count = len(safe_keys) if isinstance(safe_keys, (dict, list)) else 0
    return {"connected": True, "type": modifier_type, "keyframes": safe_keys, "keyframe_count": count}


def _tool_state(animation: Any, native: Any, tool: Any) -> dict[str, Any]:
    return {name: _modifier(animation, native, tool, name) for name in ("Center", "Size")}


def _temporal_readback(animation: Any, tool: Any, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    name = str(payload["property"])
    return [
        {
            "frame": row["frame"],
            "expected": row["value"],
            "actual": animation.normalize_value(name, animation.read_input(tool, name, row["frame"])),
            "matched": animation.values_match(name, animation.read_input(tool, name, row["frame"]), row["value"]),
        }
        for row in payload["keyframes"]
    ]


def protected_snapshot(native: Any, animation: Any, snapshots: Any, timeline: Any) -> dict[str, Any]:
    base = snapshots.timeline_snapshot(timeline)
    topology = []
    for track, item in native.all_video_items(timeline):
        tools = native.get_text_tools(native.get_comp(item))
        for index, tool in enumerate(tools):
            topology.append({
                "item_unique_id": native.item_unique_id(item),
                "item_name": native.item_name(item),
                "track": track,
                "tool_index": index,
                "inputs": _tool_state(animation, native, tool),
            })
    topology.sort(key=lambda row: (row["track"], row["item_name"], row["item_unique_id"], row["tool_index"]))
    result = {"timeline": base, "animation_topology": topology}
    result["signature"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def _timeline_identity(native: Any, project: Any) -> dict[str, str]:
    current = native.safe_value(project, "GetCurrentTimeline", default=None)
    return {
        "name": native.timeline_name(current) if current is not None else "",
        "unique_id": native.timeline_unique_id(current) if current is not None else "",
    }


def _insert_title(
    native: Any,
    animation: Any,
    carrier: Any,
    resolve: Any,
    project: Any,
    timeline: Any,
    frame: int,
    name: str,
) -> dict[str, Any]:
    expected_timeline = {"name": native.timeline_name(timeline), "unique_id": native.timeline_unique_id(timeline)}
    selected, selection_call = native.direct_call(project, "SetCurrentTimeline", timeline)
    current_before = _timeline_identity(native, project)
    if not selected or not all(expected_timeline.values()) or current_before != expected_timeline:
        raise RuntimeError(f"title_timeline_identity:{name}:before")
    setup = native.stabilize_native_title_context(resolve, project, timeline, frame, TARGET_TRACK)
    current_at_insert = _timeline_identity(native, project)
    if setup.get("ok") is not True or current_at_insert != expected_timeline:
        raise RuntimeError(f"title_context:{name}")
    before = native.video_item_snapshot(timeline)
    if any(key.startswith("object:") for key in before):
        raise RuntimeError(f"title_ownership:{name}:preexisting_uid_missing")
    returned, provisioning = carrier.provision_textplus_media_carrier(
        project=project,
        timeline=timeline,
        video_items=[item for _track, item in native.all_video_items(timeline)],
        start_frame=frame,
        end_frame=frame + TITLE_DURATION,
        target_track=TARGET_TRACK,
        generated_name=name,
    )
    added = native.find_new_video_items(timeline, before)
    returned_uid = native.item_unique_id(returned) if returned is not None else ""
    delta_uids = [native.item_unique_id(item) for item in added]
    if (not isinstance(provisioning, dict) or provisioning.get("ok") is not True
            or len(added) != 1 or not returned_uid or delta_uids != [returned_uid]):
        raise RuntimeError(f"title_ownership:{name}:delta={len(added)}")
    item = added[0]
    summary = native.item_summary(timeline, item)
    current_after = _timeline_identity(native, project)
    if (current_after != expected_timeline or summary.get("track_index") != TARGET_TRACK
            or summary.get("start") != frame or summary.get("duration") != TITLE_DURATION
            or summary.get("fusion_comp_count") != 1):
        raise RuntimeError(f"title_placement_or_timeline:{name}")
    comp = native.get_comp(item)
    tools = native.get_text_tools(comp)
    all_tools = carrier.list_fusion_tools(comp) if comp is not None else []
    media_outs = [tool for tool in all_tools if carrier.fusion_tool_regid(tool) == "MediaOut"]
    if len(tools) != 1 or len(media_outs) != 1:
        raise RuntimeError(f"title_identity:{name}")
    output = animation.connected_output(animation.find_input(media_outs[0], "Input"))
    source_tool = native.safe_value(output, "GetTool", default=None) if output is not None else None
    if source_tool is None or carrier.fusion_tool_regid(source_tool) != "TextPlus" or carrier.fusion_tool_name(source_tool) != carrier.fusion_tool_name(tools[0]):
        raise RuntimeError(f"title_output_connection:{name}")
    text_write = native.set_static_input(tools[0], "StyledText", name)
    text_readback = native.read_text(tools[0])
    if text_write.get("ok") is not True or text_readback != name:
        raise RuntimeError(f"title_text_identity:{name}")
    return {
        "item": item,
        "tool": tools[0],
        "summary": summary,
        "provisioning": provisioning,
        "setup": setup,
        "selection_call": selection_call,
        "timeline_before": current_before,
        "timeline_at_insert": current_at_insert,
        "timeline_after": current_after,
        "inventory_before_count": len(before),
        "inventory_after_count": len(before) + len(added),
        "delta_uids": delta_uids,
        "returned_uid": returned_uid,
        "fusion_comp_count": summary["fusion_comp_count"],
        "textplus_node_count": len(tools),
        "output_connection": {
            "connected": True,
            "source_name": carrier.fusion_tool_name(source_tool),
            "source_regid": carrier.fusion_tool_regid(source_tool),
        },
        "text_write": text_write,
        "text_readback": text_readback,
    }


def execute(resolve: Any, context: Mapping[str, Any], dependencies: tuple[Any, Any, Any, Any] | None = None) -> dict[str, Any]:
    command = context.get("command") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    root = repository_root()
    report: dict[str, Any] = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "mode": MODE,
        "ok": False, "classification": "STEP4C_PROBE_BLOCKED", "ownership": None,
        "failures": [], "mutation_counts": {"timeline_create": 0, "title_insert": 0, "animation_keyframes_first": 0,
        "animation_keyframes_second": 0, "static_animation_mutations": 0, "project_saves": 0,
        "imports": 0, "disposable_caption_deletes": 0, "unrelated_deletes": 0, "relinks": 0, "replaces": 0},
    }
    native = animation = snapshots = carrier = project = previous = disposable = None
    previous_page = ""
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
            raise ValueError("command_identity")
        payload = command.get("payload") or {}
        disposable_name = str(payload.get("disposable_timeline_name") or "")
        if (payload.get("expected_project") != PROJECT_NAME or payload.get("protected_timelines") != [REEL1, REEL2]
                or not disposable_name.startswith(PROBE_PREFIX) or payload.get("mutation_permitted") is not True
                or payload.get("cleanup_permitted") is not False):
            raise ValueError("probe_contract")
        report["queue_preflight"] = queue_preflight(root, run_id)
        native, animation, snapshots, carrier = dependencies or load_dependencies(root)
        report["source_contract"] = native.verify_source_contract(root, command)
        manager, project, media_pool, calls = native.get_project(resolve)
        report["resolve_connection"] = calls
        if native.safe_value(project, "GetName", default="") != PROJECT_NAME:
            raise RuntimeError("project_identity")
        previous = native.safe_value(project, "GetCurrentTimeline", default=None)
        previous_page = str(native.safe_value(resolve, "GetCurrentPage", default="") or "")
        reel1 = _find_unique(native, project, REEL1)
        reel2 = _find_unique(native, project, REEL2)
        static_only = payload.get("static_insertion_only") is True
        reuse_existing = payload.get("reuse_existing_owned_disposable") is True
        existing_disposable = _find_unique(native, project, disposable_name)
        if (reel1 is None or reel2 is None or disposable_name in (REEL1, REEL2)
                or (not static_only and not reuse_existing and existing_disposable is not None)):
            raise RuntimeError("protected_or_disposable_identity")
        before = {REEL1: protected_snapshot(native, animation, snapshots, reel1), REEL2: protected_snapshot(native, animation, snapshots, reel2)}
        report["protected_before"] = before

        if static_only:
            expected_uid = str(payload.get("expected_disposable_uid") or "")
            if (payload.get("ownership_required") != "EXISTING_NEWLY_CREATED" or existing_disposable is None
                    or not expected_uid or native.timeline_unique_id(existing_disposable) != expected_uid):
                raise RuntimeError("existing_disposable_ownership")
            disposable = existing_disposable
            report["ownership"] = "EXISTING_NEWLY_CREATED"
            report["disposable_target"] = {"name": disposable_name, "unique_id": expected_uid, "cleanup": "LEFT_ISOLATED"}
            proof = _insert_title(native, animation, carrier, resolve, project, disposable,
                                  native.as_int(native.safe_value(disposable, "GetStartFrame", default=0), 0) + STATIC_PROOF_FRAME,
                                  STATIC_PROOF_NAME)
            report["mutation_counts"]["title_insert"] = 1
            report["static_proof"] = {key: value for key, value in proof.items() if key not in {"item", "tool"}}
            reel1_after, reel2_after = _find_unique(native, project, REEL1), _find_unique(native, project, REEL2)
            after = {REEL1: protected_snapshot(native, animation, snapshots, reel1_after), REEL2: protected_snapshot(native, animation, snapshots, reel2_after)}
            report["protected_after"] = after
            report["protected_unchanged"] = {name: before[name]["signature"] == after[name]["signature"] for name in (REEL1, REEL2)}
            if not all(report["protected_unchanged"].values()):
                raise RuntimeError("protected_state_changed")
            report["classification"] = "STEP4C_STATIC_INSERTION_PASS"
            report["ok"] = True
            return report

        if reuse_existing:
            expected_uid = str(payload.get("expected_disposable_uid") or "")
            if (payload.get("ownership_required") != "EXISTING_NEWLY_CREATED" or existing_disposable is None
                    or not expected_uid or native.timeline_unique_id(existing_disposable) != expected_uid
                    or native.track_count(existing_disposable, "video") < TARGET_TRACK):
                raise RuntimeError("existing_disposable_ownership")
            disposable = existing_disposable
            uid = expected_uid
            selected, selection_call = native.direct_call(project, "SetCurrentTimeline", disposable)
            identity = _timeline_identity(native, project)
            if not selected or identity != {"name": disposable_name, "unique_id": expected_uid}:
                raise RuntimeError("existing_disposable_identity")
            report["existing_target_preflight"] = {"selection_call": selection_call, "identity": identity}
            report["ownership"] = "EXISTING_NEWLY_CREATED"
            report["disposable_target"] = {"name": disposable_name, "unique_id": uid, "cleanup": "LEFT_ISOLATED"}
            target_frames = EXISTING_TARGET_FRAMES
        else:
            disposable, create_call = native.direct_call(reel1, "DuplicateTimeline", disposable_name)
            report["mutation_counts"]["timeline_create"] = 1 if create_call.get("ok") else 0
            owned = _find_unique(native, project, disposable_name)
            uid = native.timeline_unique_id(owned) if owned is not None else ""
            if disposable is None or owned is None or not uid or native.timeline_unique_id(disposable) != uid:
                raise RuntimeError("disposable_ownership")
            report["ownership"] = "NEWLY_CREATED"
            report["disposable_target"] = {"name": disposable_name, "unique_id": uid, "cleanup": "LEFT_ISOLATED"}
            if not native.safe_value(project, "SetCurrentTimeline", owned, default=False):
                raise RuntimeError("disposable_selection")
            copied_captions = [item for _track, item in native.caption_items(owned)]
            deletion = native.delete_items(owned, copied_captions)
            report["mutation_counts"]["disposable_caption_deletes"] = len(copied_captions)
            if deletion.get("ok") is not True or native.caption_items(owned):
                raise RuntimeError("disposable_caption_isolation")
            while native.track_count(owned, "video") < TARGET_TRACK:
                _value, add_call = native.direct_call(owned, "AddTrack", "video")
                if not add_call.get("ok"):
                    raise RuntimeError("probe_track_creation")
            disposable = owned
            target_frames = TARGET_FRAMES
        start = native.as_int(native.safe_value(disposable, "GetStartFrame", default=0), 0)
        created = [_insert_title(native, animation, carrier, resolve, project, disposable, start + offset, name) for offset, name in zip(target_frames, ITEM_NAMES)]
        report["mutation_counts"]["title_insert"] = len(created)
        center, size, static = created

        static_before = _tool_state(animation, native, static["tool"])
        static_result = animation.apply_authorized_animation(native.get_comp(static["item"]), static["tool"], None, 8)
        static_after = _tool_state(animation, native, static["tool"])
        if static_result.get("modified") or static_result.get("keyframes_written") or static_before != static_after:
            raise RuntimeError("static_noop")
        report["static"] = {"before": static_before, "result": static_result, "after": static_after}

        center_comp, size_comp = native.get_comp(center["item"]), native.get_comp(size["item"])
        center_first = animation.apply_authorized_animation(center_comp, center["tool"], CENTER_PAYLOAD, 3)
        size_first = animation.apply_authorized_animation(size_comp, size["tool"], SIZE_PAYLOAD, 8)
        if center_first.get("ok") is not True or size_first.get("ok") is not True:
            raise RuntimeError("first_application")
        report["mutation_counts"]["animation_keyframes_first"] = center_first.get("keyframes_written", 0) + size_first.get("keyframes_written", 0)
        immediate = {
            "Center": {"result": center_first, "modifier": _modifier(animation, native, center["tool"], "Center")},
            "Size": {"result": size_first, "modifier": _modifier(animation, native, size["tool"], "Size")},
        }
        if immediate["Center"]["modifier"]["type"] != "Path" or immediate["Size"]["modifier"]["type"] != "BezierSpline":
            raise RuntimeError("modifier_type")
        report["immediate_readback"] = immediate

        save = native.save_project(manager)
        report["mutation_counts"]["project_saves"] = 1
        if save.get("success") is not True:
            raise RuntimeError("project_save")
        manager, project, media_pool, reacquire_calls = native.get_project(resolve)
        reacquired = _find_unique(native, project, disposable_name)
        if reacquired is None or native.timeline_unique_id(reacquired) != uid:
            raise RuntimeError("persistent_timeline_reacquire")
        items = {}
        for created_row in created:
            _track, item = native.find_item_by_unique_id(reacquired, created_row["summary"]["unique_id"])
            if item is None:
                raise RuntimeError("persistent_item_reacquire")
            tools = native.get_text_tools(native.get_comp(item))
            if len(tools) != 1:
                raise RuntimeError("persistent_tool_reacquire")
            items[created_row["summary"]["name"]] = (item, tools[0])
        center_tool = items[ITEM_NAMES[0]][1]
        size_tool = items[ITEM_NAMES[1]][1]
        persistent = {
            "Center": {"modifier": _modifier(animation, native, center_tool, "Center"), "readback": _temporal_readback(animation, center_tool, CENTER_PAYLOAD), "targets_ok": animation.input_targets_are_correct(center_tool, "Center", [{"local_frame": k["frame"], "expected": k["value"]} for k in CENTER_PAYLOAD["keyframes"]])},
            "Size": {"modifier": _modifier(animation, native, size_tool, "Size"), "readback": _temporal_readback(animation, size_tool, SIZE_PAYLOAD), "targets_ok": animation.input_targets_are_correct(size_tool, "Size", [{"local_frame": k["frame"], "expected": k["value"]} for k in SIZE_PAYLOAD["keyframes"]])},
            "reacquire_calls": reacquire_calls,
        }
        if (persistent["Center"]["modifier"]["type"] != "Path" or persistent["Size"]["modifier"]["type"] != "BezierSpline"
                or not persistent["Center"]["targets_ok"] or not persistent["Size"]["targets_ok"]
                or not all(row["matched"] for name in ("Center", "Size") for row in persistent[name]["readback"])):
            raise RuntimeError("persistent_readback")
        report["persistent_readback"] = persistent

        before_second = {"Center": persistent["Center"]["modifier"], "Size": persistent["Size"]["modifier"]}
        center_second = animation.apply_authorized_animation(native.get_comp(items[ITEM_NAMES[0]][0]), center_tool, CENTER_PAYLOAD, 3)
        size_second = animation.apply_authorized_animation(native.get_comp(items[ITEM_NAMES[1]][0]), size_tool, SIZE_PAYLOAD, 8)
        after_second = {"Center": _modifier(animation, native, center_tool, "Center"), "Size": _modifier(animation, native, size_tool, "Size")}
        second_writes = center_second.get("keyframes_written", 0) + size_second.get("keyframes_written", 0)
        report["mutation_counts"]["animation_keyframes_second"] = second_writes
        if second_writes != 0 or center_second.get("modified") or size_second.get("modified") or before_second != after_second:
            raise RuntimeError("second_application_not_idempotent")
        report["second_application"] = {"Center": center_second, "Size": size_second, "before": before_second, "after": after_second}

        reel1_after, reel2_after = _find_unique(native, project, REEL1), _find_unique(native, project, REEL2)
        after = {REEL1: protected_snapshot(native, animation, snapshots, reel1_after), REEL2: protected_snapshot(native, animation, snapshots, reel2_after)}
        report["protected_after"] = after
        report["protected_unchanged"] = {name: before[name]["signature"] == after[name]["signature"] for name in (REEL1, REEL2)}
        if not all(report["protected_unchanged"].values()):
            raise RuntimeError("protected_state_changed")
        report["classification"] = "STEP4C_PROBE_PASS"
        report["ok"] = True
    except BaseException as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
    finally:
        if native is not None and project is not None and previous is not None:
            restored = bool(native.safe_value(project, "SetCurrentTimeline", previous, default=False))
            report["original_timeline_restored"] = restored
            if previous_page:
                native.safe_value(resolve, "OpenPage", previous_page, default=False)
            report["original_page_restored"] = str(native.safe_value(resolve, "GetCurrentPage", default="") or "") == previous_page
            if not restored or not report["original_page_restored"]:
                report["ok"] = False
                report["classification"] = "STEP4C_PROBE_BLOCKED"
                report["failures"].append("workspace_context_restore")
    return report


run = execute
