"""Reconcile only the two owned Fusion comps that implement Reel #3 boundary 80."""
from __future__ import annotations

import hashlib
import importlib.util
import json
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


batch = _load("vc_oss003_batch_for_repair", HERE / "oss003_transition_representative_batch.py")
canary, rep, full, fusion = batch.canary, batch.rep, batch.full, batch.fusion

TASK_ID = "OSS003_BLUR_BOUNDARY80_REPAIR_V1"
MODE = "oss003_blur_boundary80_repair"
OLD_RUN_ID = "20261011T101751230Z_0679951c9b1d4940aca2b15d59fcdafd"
OLD_TOKEN = "0679951c9b1d"
TARGETS = {
    0: f"{batch.COMP_PREFIX}SHOT_001_{OLD_TOKEN}",
    1: f"{batch.COMP_PREFIX}SHOT_002_{OLD_TOKEN}",
}
PEAK_BLUR = 6.474  # HyperFrames medium 10px scaled by source transition_strength 0.6474.


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _comp_range(comp: Any, duration: int) -> tuple[int, int, dict[str, Any]]:
    attrs = canary._optional(comp, "GetAttrs", default={}) or {}
    required = ("COMPN_GlobalStart", "COMPN_GlobalEnd", "COMPN_RenderStart", "COMPN_RenderEnd")
    if not isinstance(attrs, dict) or any(attrs.get(key) is None for key in required):
        raise ValueError("comp_range_attrs")
    start = max(int(attrs["COMPN_GlobalStart"]), int(attrs["COMPN_RenderStart"]))
    end = min(int(attrs["COMPN_GlobalEnd"]), int(attrs["COMPN_RenderEnd"]))
    if end - start + 1 != int(duration):
        raise ValueError(f"comp_visible_range:{start}:{end}:{duration}")
    return start, end, {key: attrs[key] for key in required}


def _keys(side: str, start: int, end: int, peak: float = PEAK_BLUR) -> list[tuple[int, float]]:
    if side == "outgoing":
        return [(start, 0.0), (end - 4, 0.0), (end - 1, round(peak * 0.75, 6)), (end, peak)]
    if side == "incoming":
        return [(start, peak), (start + 1, round(peak * 0.75, 6)), (start + 5, 0.0), (end, 0.0)]
    raise ValueError(f"side:{side}")


def _source_tool(tool: Any, input_name: str) -> Any:
    output = fusion.connected_output(fusion.find_input_object(tool, input_name))
    return canary._optional(output, "GetTool", default=output) if output is not None else None


def _topology(comp: Any, blur: Any) -> dict[str, Any]:
    media_in, media_out = fusion.find_tool(comp, "MediaIn"), fusion.find_tool(comp, "MediaOut")
    blur_source, out_source = _source_tool(blur, "Input"), _source_tool(media_out, "Input") if media_out is not None else None
    blur_attrs = canary._optional(blur, "GetAttrs", default={}) or {}
    return {
        "media_in": fusion.fusion_tool_name(media_in) if media_in is not None else "",
        "blur": fusion.fusion_tool_name(blur),
        "media_out": fusion.fusion_tool_name(media_out) if media_out is not None else "",
        "blur_input_source": fusion.fusion_tool_name(blur_source) if blur_source is not None else "",
        "media_out_input_source": fusion.fusion_tool_name(out_source) if out_source is not None else "",
        "blur_enabled": blur_attrs.get("TOOLB_PassThrough") in (False, 0),
        "x_input": fusion.find_input_object(blur, "XBlurSize") is not None,
        "y_input": fusion.find_input_object(blur, "YBlurSize") is not None,
        "ok": bool(
            media_in is not None and media_out is not None
            and fusion.fusion_tool_regid(blur_source) == "MediaIn"
            and fusion.fusion_tool_regid(out_source) == "Blur"
            and blur_attrs.get("TOOLB_PassThrough") in (False, 0)
            and fusion.find_input_object(blur, "XBlurSize") is not None
            and fusion.find_input_object(blur, "YBlurSize") is not None
        ),
    }


def _sample(blur: Any, frames: list[int]) -> dict[str, list[tuple[int, Any]]]:
    return {name: [(frame, fusion.read_input(blur, name, frame).get("value")) for frame in frames] for name in ("XBlurSize", "YBlurSize")}


def _comp_signature(item: Any) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    rows = []
    for name in canary._optional(item, "GetFusionCompNameList", default=[]) or []:
        comp = canary._optional(item, "GetFusionCompByName", name, default=None)
        tools = tuple(sorted((fusion.fusion_tool_regid(tool), fusion.fusion_tool_name(tool)) for tool in fusion.fusion_tools(comp)))
        rows.append((str(name), tools))
    return sorted(rows)


def _reconcile(comp: Any, old_blur: Any, side: str, start: int, end: int, run_id: str) -> dict[str, Any]:
    old_graph = _topology(comp, old_blur)
    old_frames = [start, end - 1, end] if side == "outgoing" else [start, start + 1, end]
    old_values = _sample(old_blur, old_frames)
    new_name = f"VC_OSS003_B80_{side.upper()}_{run_id.rsplit('_', 1)[-1][:12]}"
    blur = canary._optional(comp, "AddTool", "Blur", -32768, -32768, default=None)
    if blur is None or not fusion.set_tool_name(blur, new_name):
        raise RuntimeError(f"repair_blur_create:{side}")
    canary._optional(blur, "SetAttrs", {"TOOLB_PassThrough": False}, default=None)
    media_in, media_out = fusion.find_tool(comp, "MediaIn"), fusion.find_tool(comp, "MediaOut")
    if not fusion.connect_tool(media_in, blur).get("ok") or not fusion.connect_tool(blur, media_out).get("ok"):
        raise RuntimeError(f"repair_connect:{side}")
    keys = _keys(side, start, end)
    for input_name in ("XBlurSize", "YBlurSize"):
        if not fusion.ensure_bezier_modifier(comp, blur, input_name).get("ok"):
            raise RuntimeError(f"repair_modifier:{side}:{input_name}")
        for frame, value in keys:
            if not fusion.write_animated_scalar(blur, input_name, frame, value).get("ok"):
                raise RuntimeError(f"repair_key:{side}:{input_name}:{frame}")
    graph = _topology(comp, blur)
    values = _sample(blur, old_frames)
    expected = [dict(keys)[frame] for frame in old_frames]
    if not graph["ok"] or any(not fusion.numeric_close(value, wanted) for channel in values.values() for (_, value), wanted in zip(channel, expected)):
        fusion.connect_tool(old_blur, media_out)
        canary._optional(comp, "DeleteTool", blur, default=None)
        raise RuntimeError(f"repair_evaluated_readback:{side}")
    canary._optional(comp, "DeleteTool", old_blur, default=None)
    if old_blur in fusion.fusion_tools(comp) or len([tool for tool in fusion.fusion_tools(comp) if fusion.fusion_tool_regid(tool) == "Blur"]) != 1:
        raise RuntimeError(f"old_blur_delete:{side}")
    return {
        "side": side, "comp_range": [start, end], "old_graph": old_graph, "old_evaluated_values": old_values,
        "topology": graph, "keyframes": keys, "evaluated_frames": old_frames, "evaluated_values": values,
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_count": 0, "failures": []}
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT, "target_timeline": rep.EXPECTED_TIMELINE,
            "target_timeline_uid": rep.EXPECTED_TIMELINE_UID, "boundary_frame": 80,
            "source_batch_run_id": OLD_RUN_ID, "expected_old_comp_names": list(TARGETS.values()),
            "peak_blur": PEAK_BLUR, "save_after_verification": True,
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
        captions = canary.basic_title_rows(target)
        nested = rep._stable_nested(target, base)
        if len(captions) != 112 or len(nested) != batch.EXPECTED_NESTED:
            raise ValueError("caption_baseline")
        for index, expected in TARGETS.items():
            if batch._owned_names(v1[index]["item"]) != [expected]:
                raise ValueError(f"boundary80_ownership:{index + 1}")
        frozen = {index: _comp_signature(v1[index]["item"]) for index in range(2, 8)}
        safety_before = {"v1_audio": full._unrelated_snapshot(target), "captions": rep._caption_snapshot(captions, base), "nested": nested, "tracks": 3}
        applications = []
        for index, side in ((0, "outgoing"), (1, "incoming")):
            item, name = v1[index]["item"], TARGETS[index]
            comp = canary._optional(item, "GetFusionCompByName", name, default=None)
            if comp is None:
                raise ValueError(f"owned_comp_missing:{side}")
            blurs = [tool for tool in fusion.fusion_tools(comp) if fusion.fusion_tool_regid(tool) == "Blur"]
            if len(blurs) != 1:
                raise ValueError(f"old_blur_count:{side}:{len(blurs)}")
            start, end, attrs = _comp_range(comp, v1[index]["duration"])
            row = _reconcile(comp, blurs[0], side, start, end, run_id)
            row.update({"comp_name": name, "comp_attrs": attrs})
            applications.append(row)
        target = canary._activate_target(project)
        v1_after = batch._v1_contract(target, base)
        safety_after = {
            "v1_audio": full._unrelated_snapshot(target), "captions": rep._caption_snapshot(canary.basic_title_rows(target), base),
            "nested": rep._stable_nested(target, base), "tracks": int(canary.carrier._call(target, "GetTrackCount", "video") or 0),
        }
        if safety_after != safety_before or frozen != {index: _comp_signature(v1_after[index]["item"]) for index in range(2, 8)}:
            raise RuntimeError("unrelated_state_changed")
        if any(batch._owned_names(v1_after[index]["item"]) != [TARGETS[index]] for index in TARGETS):
            raise RuntimeError("boundary80_ownership_changed")
        saved = canary.carrier._call(manager, "SaveProject")
        result.update({"save_project_count": 1, "save_project_return": saved})
        if saved is not True:
            raise RuntimeError("save_project")
        result.update({"ok": True, "verification": "PASS", "boundary_frame": 80, "peak_blur": PEAK_BLUR, "applications": applications})
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
