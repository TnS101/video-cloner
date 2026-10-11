"""Complete only the incoming half of the Reel #3 boundary-80 blur proof."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repair = _load("vc_oss003_b80_repair_for_completion", HERE / "oss003_blur_boundary80_repair.py")
batch, canary, rep, full, fusion = repair.batch, repair.canary, repair.rep, repair.full, repair.fusion

TASK_ID = "OSS003_BOUNDARY80_COMPLETE_HANDOFF_V1"
MODE = "oss003_boundary80_complete_handoff"
OUTGOING_COMP = repair.TARGETS[0]
INCOMING_COMP = repair.TARGETS[1]
OUTGOING_ACTIVE = "VC_OSS003_B80_OUTGOING_fcc8ca3dfe4e"
OLD_OUTGOING = f"{OUTGOING_COMP}_TOOL"
OLD_INCOMING = f"{INCOMING_COMP}_TOOL"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _active_blur(comp: Any) -> tuple[Any, dict[str, Any]]:
    media_out = fusion.find_tool(comp, "MediaOut")
    source = repair._source_tool(media_out, "Input") if media_out is not None else None
    topology = {
        "media_out": fusion.fusion_tool_name(media_out) if media_out is not None else "",
        "active_name": fusion.fusion_tool_name(source) if source is not None else "",
        "active_regid": fusion.fusion_tool_regid(source) if source is not None else "",
    }
    topology["ok"] = bool(media_out is not None and topology["active_regid"] == "Blur")
    return source, topology


def _verify_outgoing(comp: Any, start: int, end: int) -> dict[str, Any]:
    blur, topology = _active_blur(comp)
    graph = repair._topology(comp, blur) if blur is not None else {"ok": False}
    frames, expected = [start, end - 1, end], [0.0, 4.8555, 6.474]
    values = repair._sample(blur, frames) if blur is not None else {}
    matched = bool(
        topology["active_name"] == OUTGOING_ACTIVE and graph["ok"]
        and all(fusion.numeric_close(actual, wanted) for channel in values.values() for (_, actual), wanted in zip(channel, expected))
        and len(values) == 2
    )
    return {"topology": graph, "active_path": topology, "comp_range": [start, end], "evaluated_frames": frames, "evaluated_values": values, "old_orphan": OLD_OUTGOING, "ok": matched}


def _create_incoming(comp: Any, start: int, end: int, run_id: str) -> dict[str, Any]:
    active_before, before = _active_blur(comp)
    if before["active_name"] != OLD_INCOMING:
        raise ValueError(f"incoming_prestate:{before['active_name']}")
    name = f"VC_OSS003_B80_INCOMING_{run_id.rsplit('_', 1)[-1][:12]}"
    if any(fusion.fusion_tool_name(tool) == name for tool in fusion.fusion_tools(comp)):
        raise ValueError("incoming_name_collision")
    blur = canary._optional(comp, "AddTool", "Blur", -32768, -32768, default=None)
    if blur is None or not fusion.set_tool_name(blur, name):
        raise RuntimeError("incoming_blur_create")
    canary._optional(blur, "SetAttrs", {"TOOLB_PassThrough": False}, default=None)
    media_in, media_out = fusion.find_tool(comp, "MediaIn"), fusion.find_tool(comp, "MediaOut")
    if not fusion.connect_tool(media_in, blur).get("ok") or not fusion.connect_tool(blur, media_out).get("ok"):
        raise RuntimeError("incoming_connect")
    keys = repair._keys("incoming", start, end)
    for input_name in ("XBlurSize", "YBlurSize"):
        if not fusion.ensure_bezier_modifier(comp, blur, input_name).get("ok"):
            raise RuntimeError(f"incoming_modifier:{input_name}")
        for frame, value in keys:
            if not fusion.write_animated_scalar(blur, input_name, frame, value).get("ok"):
                raise RuntimeError(f"incoming_key:{input_name}:{frame}")
    active_after, after = _active_blur(comp)
    graph = repair._topology(comp, active_after) if active_after is not None else {"ok": False}
    frames, expected = [start, start + 1, start + 5], [6.474, 4.8555, 0.0]
    values = repair._sample(active_after, frames) if active_after is not None else {}
    old_is_orphan = before["active_name"] == OLD_INCOMING and after["active_name"] == name
    matched = bool(
        old_is_orphan and after["ok"] and graph["ok"]
        and all(fusion.numeric_close(actual, wanted) for channel in values.values() for (_, actual), wanted in zip(channel, expected))
        and len(values) == 2
    )
    if not matched:
        raise RuntimeError("incoming_active_readback")
    return {
        "node": name, "topology_before": before, "topology": graph, "active_path": after, "comp_range": [start, end],
        "keyframes": keys, "evaluated_frames": frames, "evaluated_values": values,
        "old_orphan": OLD_INCOMING, "old_orphan_outside_render_path": old_is_orphan, "ok": True,
    }


def _save_once(manager: Any) -> Any:
    return canary.carrier._call(manager, "SaveProject")


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_count": 0, "failures": []}
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT, "target_timeline": rep.EXPECTED_TIMELINE,
            "target_timeline_uid": rep.EXPECTED_TIMELINE_UID, "boundary_frame": 80,
            "outgoing_comp": OUTGOING_COMP, "incoming_comp": INCOMING_COMP,
            "outgoing_active_node": OUTGOING_ACTIVE, "peak_blur": repair.PEAK_BLUR,
            "save_after_verification": True, "delete_tools": False,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        if _sha256(Path(__file__).resolve()) != payload.get("module_sha256"):
            raise ValueError("module_hash")
        if str(canary.carrier._call(resolve, "GetVersionString") or "") != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError("resolve_version")
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        target = canary._activate_target(project)
        if canary._timeline_identity(target)["unique_id"] != rep.EXPECTED_TIMELINE_UID or int(canary.carrier._call(target, "GetTrackCount", "video") or 0) != 3:
            raise ValueError("timeline_identity")
        base = int(canary.carrier._call(target, "GetStartFrame") or 0)
        v1 = batch._v1_contract(target, base)
        captions, nested = canary.basic_title_rows(target), rep._stable_nested(target, base)
        if len(captions) != 112 or len(nested) != batch.EXPECTED_NESTED:
            raise ValueError("caption_baseline")
        if batch._owned_names(v1[0]["item"]) != [OUTGOING_COMP] or batch._owned_names(v1[1]["item"]) != [INCOMING_COMP]:
            raise ValueError("boundary80_ownership")
        outgoing_comp = canary._optional(v1[0]["item"], "GetFusionCompByName", OUTGOING_COMP, default=None)
        incoming_comp = canary._optional(v1[1]["item"], "GetFusionCompByName", INCOMING_COMP, default=None)
        if outgoing_comp is None or incoming_comp is None:
            raise ValueError("boundary80_comp_missing")
        outgoing_signature = repair._comp_signature(v1[0]["item"])
        frozen = {index: repair._comp_signature(v1[index]["item"]) for index in range(2, 8)}
        safety_before = {"v1_audio": full._unrelated_snapshot(target), "captions": rep._caption_snapshot(captions, base), "nested": nested, "tracks": 3}
        out_start, out_end, _ = repair._comp_range(outgoing_comp, v1[0]["duration"])
        outgoing = _verify_outgoing(outgoing_comp, out_start, out_end)
        if not outgoing["ok"]:
            raise RuntimeError("outgoing_active_readback")
        in_start, in_end, in_attrs = repair._comp_range(incoming_comp, v1[1]["duration"])
        incoming = _create_incoming(incoming_comp, in_start, in_end, run_id)
        incoming["comp_attrs"] = in_attrs
        target = canary._activate_target(project)
        v1_after = batch._v1_contract(target, base)
        safety_after = {
            "v1_audio": full._unrelated_snapshot(target), "captions": rep._caption_snapshot(canary.basic_title_rows(target), base),
            "nested": rep._stable_nested(target, base), "tracks": int(canary.carrier._call(target, "GetTrackCount", "video") or 0),
        }
        if safety_after != safety_before or outgoing_signature != repair._comp_signature(v1_after[0]["item"]):
            raise RuntimeError("outgoing_or_timeline_changed")
        if frozen != {index: repair._comp_signature(v1_after[index]["item"]) for index in range(2, 8)}:
            raise RuntimeError("other_transition_changed")
        saved = _save_once(manager)
        result.update({"save_project_count": 1, "save_project_return": saved})
        if saved is not True:
            raise RuntimeError("save_project")
        result.update({"ok": True, "verification": "PASS", "boundary_frame": 80, "outgoing": outgoing, "incoming": incoming})
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
