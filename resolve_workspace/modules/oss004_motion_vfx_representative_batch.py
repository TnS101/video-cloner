"""Apply five source-backed Reel #3 motion/VFX recipes on an owned derivative."""
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


oss003 = _load("vc_oss004_oss003", HERE / "oss003_transition_representative_batch.py")
repair = _load("vc_oss004_fusion", HERE / "oss003_blur_boundary80_repair.py")
canary, rep, fusion = oss003.canary, oss003.rep, repair.fusion

TASK_ID = "OSS004_MOTION_VFX_REPRESENTATIVE_BATCH_V1"
MODE = "oss004_motion_vfx_representative_batch"
BASELINE_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_TRANSITIONS_V1"
BASELINE_UID = "75c9bc1b-ef1b-4463-9d7f-0ccb4b41e2b1"
DERIVATIVE_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS004_MOTION_VFX_V1"
BOUNDARIES = ((80, 11), (286, 11), (376, 11))
EXPECTED_COUNTS = {"V1": 8, "V2": 112, "V3": 69}
SOURCE_INVENTORY = {"shot_motion_events": 8, "boundary_motion_vfx_events": 3, "total_evidence_events": 11, "deferred_to_oss005": ["shot_001", "shot_002", "shot_004"]}

# HyperFrames-style independent seekable channels, populated only from existing Reel #3 evidence.
RECIPES = (
    {
        "id": "shot_001_pull_out", "shot": 1, "window": [0, 79], "behavior": "full-shot pull-out",
        "position": [], "scale": [[0, 1.12], [79, 1.0]], "blur": [], "confidence": "high",
        "provenance": ["DZatr0EJt4B_motion.json:segments[0].zoom_profile"],
    },
    {
        "id": "boundary_211_slide_in", "shot": 3, "window": [0, 5], "behavior": "incoming slide left/up settling to center",
        "position": [[0, [0.54, 0.49]], [5, [0.5, 0.5]]], "scale": [], "blur": [], "confidence": "medium",
        "provenance": ["DZatr0EJt4B_transitions.json:cut_frame=211 incoming flow", "DZatr0EJt4B_motion.json:shot_id=3"],
    },
    {
        "id": "shot_004_push_in_pan", "shot": 4, "window": [0, 89], "behavior": "push-in with right/down reframe",
        "position": [[0, [0.5, 0.5]], [89, [0.536, 0.485]]], "scale": [[0, 1.0], [89, 1.18]], "blur": [], "confidence": "medium",
        "provenance": ["DZatr0EJt4B_motion.json:segments[3].motion_profile", "DZatr0EJt4B_motion.json:segments[3].zoom_profile"],
    },
    {
        "id": "boundary_461_whip_out", "shot": 5, "window": [81, 84], "behavior": "outgoing left/down whip into cut",
        "position": [[81, [0.5, 0.5]], [84, [0.455, 0.488]]], "scale": [], "blur": [[81, [0.0, 0.0]], [84, [2.7308, 0.6827]]], "confidence": "high",
        "provenance": ["DZatr0EJt4B_transitions.json:cut_frame=461 outgoing directional_context"],
    },
    {
        "id": "boundary_461_whip_in", "shot": 6, "window": [0, 3], "behavior": "incoming left/down whip settling after cut",
        "position": [[0, [0.515, 0.508]], [3, [0.5, 0.5]]], "scale": [], "blur": [[0, [2.7308, 0.6827]], [3, [0.0, 0.0]]], "confidence": "high",
        "provenance": ["DZatr0EJt4B_transitions.json:cut_frame=461 incoming directional_context"],
    },
    {
        "id": "boundary_629_slide_in", "shot": 8, "window": [0, 5], "behavior": "incoming slide left/up settling to center",
        "position": [[0, [0.515, 0.49]], [5, [0.5, 0.5]]], "scale": [], "blur": [], "confidence": "medium",
        "provenance": ["DZatr0EJt4B_transitions.json:cut_frame=629 incoming flow"],
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_recipes(rows: Any = RECIPES) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        if set(row) != {"id", "shot", "window", "behavior", "position", "scale", "blur", "confidence", "provenance"}:
            raise ValueError(f"recipe_fields:{row.get('id', '')}")
        shot, window = int(row["shot"]), [int(value) for value in row["window"]]
        if shot < 1 or shot > len(oss003.EXPECTED_V1) or window[0] < 0 or window[1] < window[0] or window[1] >= oss003.EXPECTED_V1[shot - 1][1]:
            raise ValueError(f"recipe_scope:{row['id']}")
        position = [[int(frame), [float(value[0]), float(value[1])]] for frame, value in row["position"]]
        scale = [[int(frame), float(value)] for frame, value in row["scale"]]
        blur = [[int(frame), [float(value[0]), float(value[1])]] for frame, value in row["blur"]]
        if not any((position, scale, blur)) or any(frame < window[0] or frame > window[1] for channel in (position, scale, blur) for frame, _ in channel):
            raise ValueError(f"recipe_channels:{row['id']}")
        normalized.append({**row, "shot": shot, "window": window, "position": position, "scale": scale, "blur": blur})
    if [row["id"] for row in normalized] != [row["id"] for row in RECIPES] or len({row["id"] for row in normalized}) != len(normalized):
        raise ValueError("recipe_identity")
    return normalized


def absolute_keys(recipe: dict[str, Any], comp_start: int, comp_end: int) -> dict[str, list[list[Any]]]:
    duration = oss003.EXPECTED_V1[recipe["shot"] - 1][1]
    if comp_end - comp_start + 1 != duration:
        raise ValueError(f"comp_visible_range:{recipe['id']}:{comp_start}:{comp_end}:{duration}")
    return {channel: [[comp_start + int(frame), value] for frame, value in recipe[channel]] for channel in ("position", "scale", "blur")}


def _find_optional(project: Any, name: str) -> Any:
    matches = [canary._optional(project, "GetTimelineByIndex", index) for index in range(1, int(canary._optional(project, "GetTimelineCount", default=0) or 0) + 1)]
    matches = [row for row in matches if row is not None and canary._name(row) == name]
    if len(matches) > 1:
        raise ValueError(f"timeline_name_ambiguous:{name}:{len(matches)}")
    return matches[0] if matches else None


def _media_rows(timeline: Any) -> list[Any]:
    rows = [item for item in (canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []) if canary._optional(item, "GetMediaPoolItem") is not None]
    return sorted(rows, key=canary._item_start)


def _item_tuple(item: Any, base_frame: int) -> tuple[Any, ...]:
    media = canary._optional(item, "GetMediaPoolItem")
    properties = canary._optional(item, "GetProperty", default={}) or {}
    speed = properties.get("Speed") if isinstance(properties, dict) else canary._optional(item, "GetProperty", "Speed", default=None)
    return (canary._name(item), canary._item_start(item) - base_frame, canary._item_duration(item), canary._name(media) if media is not None else "", canary._optional(item, "GetClipEnabled", default=None), speed)


def _snapshot(timeline: Any) -> dict[str, Any]:
    base_frame = int(canary._optional(timeline, "GetStartFrame", default=0) or 0)
    groups: dict[str, list[tuple[Any, ...]]] = {}
    for track_type, tracks in (("video", (1, 2, 3)), ("audio", (1,))):
        for track in tracks:
            rows = []
            for item in canary._optional(timeline, "GetItemListInTrack", track_type, track, default=[]) or []:
                if track_type == "video" and track == 1 and canary._optional(item, "GetMediaPoolItem") is None:
                    continue
                rows.append(_item_tuple(item, base_frame))
            groups[f"{track_type[0].upper()}{track}"] = sorted(rows, key=lambda row: (row[1], row[2], row[0]))
    counts = {key: len(value) for key, value in groups.items()}
    if any(counts[key] != value for key, value in EXPECTED_COUNTS.items()) or counts["A1"] == 0:
        raise ValueError(f"baseline_counts:{counts}")
    return {
        "counts": counts,
        "hashes": {key: hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest() for key, value in groups.items()},
        "start": base_frame, "end": int(canary._optional(timeline, "GetEndFrame", default=-1) or -1),
    }


def _transitions(timeline: Any) -> list[tuple[str, int, int, int]]:
    base_frame = int(canary._optional(timeline, "GetStartFrame", default=0) or 0)
    rows = []
    for item in canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []:
        if canary._optional(item, "GetMediaPoolItem") is None:
            rows.append((canary._name(item), canary._item_start(item) - base_frame, canary._item_duration(item), int(canary._optional(item, "GetEnd", default=-1) or -1) - base_frame))
    rows.sort(key=lambda row: row[1])
    expected = [("Blur Dissolve", cut - duration // 2, duration, cut - duration // 2 + duration) for cut, duration in BOUNDARIES]
    if rows != expected:
        raise ValueError(f"native_transitions:{rows!r}")
    return rows


def _comp_range(comp: Any, duration: int) -> tuple[int, int, dict[str, Any]]:
    attrs = canary._optional(comp, "GetAttrs", default={}) or {}
    required = ("COMPN_GlobalStart", "COMPN_GlobalEnd", "COMPN_RenderStart", "COMPN_RenderEnd")
    if any(attrs.get(key) is None for key in required):
        raise ValueError("comp_range_attrs")
    start = max(int(attrs["COMPN_GlobalStart"]), int(attrs["COMPN_RenderStart"]))
    end = min(int(attrs["COMPN_GlobalEnd"]), int(attrs["COMPN_RenderEnd"]))
    if end - start + 1 != duration:
        raise ValueError(f"comp_visible_range:{start}:{end}:{duration}")
    return start, end, {key: attrs[key] for key in required}


def _source_tool(tool: Any, input_name: str) -> Any:
    output = fusion.connected_output(fusion.find_input_object(tool, input_name))
    return canary._optional(output, "GetTool", default=output) if output is not None else None


def _apply_recipe(item: Any, recipe: dict[str, Any], name: str) -> dict[str, Any]:
    before = [str(value) for value in (canary._optional(item, "GetFusionCompNameList", default=[]) or [])]
    if name in before or any(value.startswith("VC_OSS004_") for value in before):
        raise ValueError(f"oss004_comp_collision:{recipe['id']}:{before!r}")
    comp = canary._optional(item, "AddFusionComp", default=None)
    after = [str(value) for value in (canary._optional(item, "GetFusionCompNameList", default=[]) or [])]
    created = [value for value in after if value not in before]
    if comp is None or len(created) != 1 or canary._optional(item, "RenameFusionCompByName", created[0], name, default=False) is not True:
        raise RuntimeError(f"fusion_comp_create:{recipe['id']}")
    loaded = canary._optional(item, "LoadFusionCompByName", name, default=None)
    if loaded is None:
        raise RuntimeError(f"fusion_comp_authority:{recipe['id']}:{before!r}")
    start, end, attrs = _comp_range(loaded, canary._item_duration(item))
    channels = absolute_keys(recipe, start, end)
    media_in, media_out = fusion.find_tool(loaded, "MediaIn"), fusion.find_tool(loaded, "MediaOut")
    transform = canary._optional(loaded, "AddTool", "Transform", -32768, -32768, default=None)
    if media_in is None or media_out is None or transform is None or not fusion.set_tool_name(transform, f"{name}_TRANSFORM"):
        raise RuntimeError(f"transform_create:{recipe['id']}")
    canary._optional(transform, "SetAttrs", {"TOOLB_PassThrough": False}, default=None)
    blur_tool = None
    if channels["blur"]:
        blur_tool = canary._optional(loaded, "AddTool", "Blur", -32768, -32768, default=None)
        if blur_tool is None or not fusion.set_tool_name(blur_tool, f"{name}_BLUR"):
            raise RuntimeError(f"blur_create:{recipe['id']}")
        canary._optional(blur_tool, "SetAttrs", {"TOOLB_PassThrough": False}, default=None)
    path = [media_in, transform, blur_tool, media_out] if blur_tool is not None else [media_in, transform, media_out]
    if any(not fusion.connect_tool(source, target).get("ok") for source, target in zip(path, path[1:])):
        raise RuntimeError(f"graph_connect:{recipe['id']}")
    for input_name, channel in (("Center", channels["position"]), ("Size", channels["scale"])):
        if not channel:
            continue
        if not canary.animation.ensure_modifier(loaded, transform, input_name).get("ok"):
            raise RuntimeError(f"transform_modifier:{recipe['id']}:{input_name}")
        targets = [{"input": input_name, "local_frame": frame, "expected": value} for frame, value in channel]
        for target in targets:
            if not canary.animation.write_key(transform, input_name, target["local_frame"], target["expected"]).get("ok"):
                raise RuntimeError(f"transform_key:{recipe['id']}:{input_name}:{target['local_frame']}")
        if not canary.animation.input_targets_are_correct(transform, input_name, targets):
            raise RuntimeError(f"transform_readback:{recipe['id']}:{input_name}")
    if blur_tool is not None:
        for input_name, value_index in (("XBlurSize", 0), ("YBlurSize", 1)):
            if not fusion.ensure_bezier_modifier(loaded, blur_tool, input_name).get("ok"):
                raise RuntimeError(f"blur_modifier:{recipe['id']}:{input_name}")
            for frame, value in channels["blur"]:
                if not fusion.write_animated_scalar(blur_tool, input_name, frame, value[value_index]).get("ok"):
                    raise RuntimeError(f"blur_key:{recipe['id']}:{input_name}:{frame}")
    active_source = _source_tool(media_out, "Input")
    expected_regid = "Blur" if blur_tool is not None else "Transform"
    if fusion.fusion_tool_regid(active_source) != expected_regid:
        raise RuntimeError(f"active_render_path:{recipe['id']}:{fusion.fusion_tool_regid(active_source)}")
    return {
        "recipe": recipe, "comp": name, "legacy_comps": before, "created_comp": True, "loaded_authoritatively": True,
        "comp_range": [start, end], "comp_attrs": attrs,
        "graph": [fusion.fusion_tool_regid(tool) for tool in path], "channels": channels,
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_count": 0, "failures": []}
    project = pool = baseline = derivative = None
    derivative_uid = ""
    saved = False
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT, "baseline_timeline": BASELINE_NAME, "baseline_uid": BASELINE_UID,
            "derivative_timeline": DERIVATIVE_NAME, "target_ids": [row["id"] for row in RECIPES],
            "retiming_mutation": False, "retain_after_verification": True, "save_after_verification": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file() or _sha256(Path(__file__).resolve()) != payload.get("module_sha256"):
            raise ValueError("module_identity")
        for field in ("motion_authority", "transition_authority"):
            path = Path(str(payload.get(f"{field}_path") or "")).resolve()
            path.relative_to(root)
            if not path.is_file() or _sha256(path) != payload.get(f"{field}_sha256"):
                raise ValueError(f"{field}_identity")
        recipes = normalize_recipes()
        result["resolve_version"] = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError("resolve_version")
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        baseline = canary._find_timeline(project, BASELINE_NAME)
        if canary._timeline_identity(baseline)["unique_id"] != BASELINE_UID or _find_optional(project, DERIVATIVE_NAME) is not None:
            raise ValueError("baseline_or_derivative_identity")
        baseline_snapshot, baseline_transitions = _snapshot(baseline), _transitions(baseline)
        placements = tuple((canary._item_start(item) - baseline_snapshot["start"], canary._item_duration(item)) for item in _media_rows(baseline))
        if placements != oss003.EXPECTED_V1:
            raise ValueError(f"v1_contract:{placements!r}")
        derivative = canary._optional(baseline, "DuplicateTimeline", DERIVATIVE_NAME, default=None)
        derivative_uid = canary._timeline_identity(derivative)["unique_id"] if derivative is not None else ""
        if derivative is None or canary._name(derivative) != DERIVATIVE_NAME or not derivative_uid or canary._optional(project, "SetCurrentTimeline", derivative, default=False) is not True:
            raise RuntimeError("derivative_create")
        items = _media_rows(derivative)
        token = run_id.rsplit("_", 1)[-1][:12]
        technical = []
        for recipe in recipes:
            technical.append(_apply_recipe(items[recipe["shot"] - 1], recipe, f"VC_OSS004_{recipe['id'].upper()}_{token}"))
        derivative_snapshot, derivative_transitions = _snapshot(derivative), _transitions(derivative)
        if derivative_snapshot != baseline_snapshot or derivative_transitions != baseline_transitions or _snapshot(baseline) != baseline_snapshot or _transitions(baseline) != baseline_transitions:
            raise RuntimeError("preservation")
        if canary._optional(project, "SetCurrentTimeline", derivative, default=False) is not True:
            raise RuntimeError("derivative_reactivation")
        saved_value = canary._optional(manager, "SaveProject", default=False)
        result.update({"save_project_count": 1, "save_project_return": saved_value})
        if saved_value is not True:
            raise RuntimeError("save_project")
        saved = True
        identity = canary._timeline_identity(derivative)
        if canary._timeline_identity(canary._optional(project, "GetCurrentTimeline", default=None)) != identity:
            raise RuntimeError("derivative_not_current")
        result.update({
            "ok": True, "verification": "PASS", "source_inventory": SOURCE_INVENTORY, "recipes": technical,
            "baseline": {**canary._timeline_identity(baseline), "untouched": True}, "derivative": identity,
            "native_transitions": derivative_transitions, "preservation": derivative_snapshot,
            "retiming_mutation": False, "derivative_retained": True, "current_timeline": identity,
        })
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if project is not None and derivative is not None and derivative_uid and not saved:
            if baseline is not None:
                canary._optional(project, "SetCurrentTimeline", baseline, default=False)
            pool = canary._optional(project, "GetMediaPool", default=None)
            result["owned_derivative_cleanup"] = bool(pool is not None and canary._timeline_identity(derivative)["unique_id"] == derivative_uid and canary._optional(pool, "DeleteTimelines", [derivative], default=False) is True)
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
