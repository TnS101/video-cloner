"""Apply four OSS-derived compound caption recipes through the proven carrier."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any


MODULE_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canary = _load("vc_oss002_canary", MODULE_DIR / "oss002_sub008_production_canary.py")
batch = _load("vc_oss002_batch", MODULE_DIR / "oss002_16_caption_batch_rollout.py")
recipe_contract = _load("vc_animation_recipe", MODULE_DIR.parents[1] / "video_cloner" / "animation_recipe.py")

TASK_ID = "OSS002_OSS_ANIMATION_REPRESENTATIVE_BATCH_V1"
MODE = "oss002_oss_animation_representative_batch"
EXPECTED_RESOLVE_VERSION = "21.0.4.5"
EXPECTED_PROJECT = "VIDEO_CLONER_REEL3_FREE2104"
EXPECTED_TIMELINE = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1"
EXPECTED_TIMELINE_UID = "a89f3e7c-50d9-4969-b2b6-b01548b66879"
EXPECTED_CAPTIONS = 112
EXPECTED_VIDEO_TRACKS = 3
EXPECTED_EXISTING_NESTED = 16
EXPECTED_ORDINALS = (9, 12, 15, 26)
SOURCE_PREFIX = "_VC_OSS002_OSS_SUB"


def _recipe_set(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema") != "video_cloner.caption_animation_recipe_set"
        or payload.get("schema_version") != 1
        or payload.get("reel") != "DZatr0EJt4B"
        or payload.get("route") != "opencv_multiscale_template"
        or payload.get("decision") != "COMBINE"
    ):
        raise ValueError("recipe_set_authority")
    recipes = [recipe_contract.validate_recipe(row) for row in payload.get("recipes") or []]
    ordinals = tuple(int(str(row["caption_id"]).rsplit("_", 1)[-1]) for row in recipes)
    if ordinals != EXPECTED_ORDINALS or 8 in ordinals:
        raise ValueError(f"recipe_targets:{ordinals}")
    return recipes


def _source_name(ordinal: int, run_id: str) -> str:
    token = str(run_id).rsplit("_", 1)[-1][:12]
    if not token:
        raise ValueError("run_id_source_name")
    return f"{SOURCE_PREFIX}{ordinal:03d}_{token}"


def _stable_nested(timeline: Any, base_frame: int) -> list[tuple[Any, ...]]:
    return sorted(
        (
            row["source"]["name"],
            row["source"]["unique_id"],
            row["track"],
            row["start"] - base_frame,
            row["duration"],
        )
        for row in batch._nested_items(timeline)
    )


def _caption_snapshot(rows: list[dict[str, Any]], base_frame: int) -> list[tuple[Any, ...]]:
    if len(rows) != EXPECTED_CAPTIONS:
        raise ValueError(f"basic_title_count:{len(rows)}")
    return [
        (ordinal, row["start"] - base_frame, row["duration"], row["enabled"], row["text_readback"])
        for ordinal, row in enumerate(rows, start=1)
    ]


def _channel_targets(recipe: dict[str, Any], style: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    targets: dict[str, list[dict[str, Any]]] = {}
    for channel, keys in recipe["channels"].items():
        if channel == "position":
            base = style["Center"]
            input_name = "Center"
            values = [[base[0] + float(row["value"][0]), base[1] + float(row["value"][1])] for row in keys]
        elif channel == "scale":
            if any(abs(float(row["value"][0]) - float(row["value"][1])) > 1e-6 for row in keys):
                raise ValueError("nonuniform_textplus_scale")
            input_name = "Size"
            values = [float(style["Size"]) * float(row["value"][0]) for row in keys]
        else:
            input_name = "Opacity1"
            values = [float(row["value"]) for row in keys]
        targets[input_name] = [
            {"input": input_name, "local_frame": int(row["frame"]), "expected": value}
            for row, value in zip(keys, values)
        ]
    return targets


def _ensure_scalar_modifier(comp: Any, tool: Any, input_name: str) -> dict[str, Any]:
    input_object = canary.animation.find_input(tool, input_name)
    if input_object is None:
        return {"ok": False, "failure": f"input_not_found:{input_name}"}
    if canary.animation.connected_output(input_object) is not None:
        return {"ok": True, "created": False, "modifier": "existing_connected_modifier"}
    attempts = []
    try:
        returned = tool.AddModifier(input_name, "BezierSpline")
        attempts.append({"method": "Tool.AddModifier", "returned": str(returned)})
    except Exception as exc:
        attempts.append({"method": "Tool.AddModifier", "error": f"{type(exc).__name__}: {exc}"})
    if canary.animation.connected_output(canary.animation.find_input(tool, input_name)) is None:
        try:
            setattr(tool, input_name, comp.BezierSpline())
            attempts.append({"method": "comp.BezierSpline", "assigned": True})
        except Exception as exc:
            attempts.append({"method": "comp.BezierSpline", "error": f"{type(exc).__name__}: {exc}"})
    ok = canary.animation.connected_output(canary.animation.find_input(tool, input_name)) is not None
    return {"ok": ok, "created": ok, "modifier": "BezierSpline", "attempts": attempts}


def apply_recipe_channels(comp: Any, tool: Any, recipe: dict[str, Any], style: dict[str, Any]) -> dict[str, Any]:
    results = {}
    for input_name, targets in _channel_targets(recipe_contract.validate_recipe(recipe), style).items():
        modifier = (
            canary.animation.ensure_modifier(comp, tool, input_name)
            if input_name in {"Center", "Size"}
            else _ensure_scalar_modifier(comp, tool, input_name)
        )
        if not modifier.get("ok"):
            raise RuntimeError(f"modifier:{input_name}:{modifier}")
        writes = []
        for target in targets:
            write = canary.animation.write_key(tool, input_name, target["local_frame"], target["expected"])
            writes.append({**target, "write": write})
            if not write.get("ok"):
                raise RuntimeError(f"key_write:{input_name}:{target['local_frame']}")
        if not canary.animation.input_targets_are_correct(tool, input_name, targets):
            raise RuntimeError(f"key_readback:{input_name}")
        results[input_name] = {"modifier": modifier, "writes": writes, "ok": True}
    return {"ok": True, "channels": results}


def _rollback(project: Any, pool: Any, sources: list[Any], placed: list[Any], ordinals: list[int], created_tracks: list[int], caption_before: list[tuple[Any, ...]], nested_before: list[tuple[Any, ...]], base_frame: int) -> dict[str, Any]:
    restored = deleted = sources_deleted = tracks_removed = True
    try:
        target = canary._activate_target(project)
        rows = canary.basic_title_rows(target)
        for ordinal in ordinals:
            item = rows[ordinal - 1]["item"]
            restored = restored and canary._optional(item, "SetClipEnabled", True, default=False) is not False and canary._clip_enabled(item) is True
        if placed:
            deleted = canary._optional(target, "DeleteClips", placed, False, default=False) is True
        for track in sorted(created_tracks, reverse=True):
            items = canary._optional(target, "GetItemListInTrack", "video", track)
            tracks_removed = tracks_removed and isinstance(items, (list, tuple)) and not items and canary._optional(target, "DeleteTrack", "video", track, default=False) is True
        if sources:
            canary._optional(project, "SetCurrentTimeline", target, default=False)
            sources_deleted = canary._optional(pool, "DeleteTimelines", sources, default=False) is True
        target = canary._activate_target(project)
        verified = _caption_snapshot(canary.basic_title_rows(target), base_frame) == caption_before and _stable_nested(target, base_frame) == nested_before
    except Exception:
        verified = False
    return {"originals_restored": restored, "replacements_deleted": deleted, "source_timelines_deleted": sources_deleted, "created_tracks_removed": tracks_removed, "baseline_verified": verified, "ok": restored and deleted and sources_deleted and tracks_removed and verified}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_called": False, "failures": []}
    project = pool = None
    sources: list[Any] = []
    placed: list[Any] = []
    hidden: list[int] = []
    created_tracks: list[int] = []
    caption_before: list[tuple[Any, ...]] = []
    nested_before: list[tuple[Any, ...]] = []
    base_frame = 0
    saved = False
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "expected_project": EXPECTED_PROJECT,
            "target_timeline": EXPECTED_TIMELINE,
            "target_timeline_uid": EXPECTED_TIMELINE_UID,
            "expected_caption_count": EXPECTED_CAPTIONS,
            "expected_video_track_count": EXPECTED_VIDEO_TRACKS,
            "expected_existing_nested_count": EXPECTED_EXISTING_NESTED,
            "target_ordinals": list(EXPECTED_ORDINALS),
            "save_after_verification": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        result["resolve_version"] = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != EXPECTED_RESOLVE_VERSION:
            raise ValueError(f"resolve_version:{result['resolve_version']}")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        recipe_path = canary._repository_file(root, payload.get("recipe_path"), payload.get("recipe_sha256"), "recipe")
        fcpxml_path = canary._repository_file(root, payload.get("fcpxml_path"), payload.get("fcpxml_sha256"), "fcpxml")
        recipes = _recipe_set(recipe_path)
        styles = batch._styles_by_ordinal(fcpxml_path)
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != EXPECTED_PROJECT:
            raise ValueError(f"project_identity:{canary._name(project) if project else ''}")
        pool = canary.carrier._call(project, "GetMediaPool")
        target = canary._activate_target(project)
        if canary._timeline_identity(target)["unique_id"] != EXPECTED_TIMELINE_UID:
            raise ValueError("target_timeline_uid")
        if int(canary.carrier._call(target, "GetTrackCount", "video") or 0) != EXPECTED_VIDEO_TRACKS:
            raise ValueError("video_track_count")
        base_frame = int(canary.carrier._call(target, "GetStartFrame") or 0)
        captions = canary.basic_title_rows(target)
        caption_before = _caption_snapshot(captions, base_frame)
        nested_before = _stable_nested(target, base_frame)
        if len(nested_before) != EXPECTED_EXISTING_NESTED:
            raise ValueError(f"existing_nested_count:{len(nested_before)}")
        accepted = batch._accepted_sub008(target, base_frame)
        if captions[7]["enabled"] is not False:
            raise ValueError("accepted_sub008_original_enabled")
        targets = []
        for recipe in recipes:
            ordinal = int(recipe["caption_id"].rsplit("_", 1)[-1])
            row = captions[ordinal - 1]
            if row["start"] - base_frame != recipe["start_frame"] or row["duration"] != recipe["duration"] or row["enabled"] is not True:
                raise ValueError(f"source_caption_contract:{recipe['caption_id']}")
            if row["text_readback"] is not None and row["text_readback"] != recipe["text"]:
                raise ValueError(f"source_caption_text:{recipe['caption_id']}")
            if styles[ordinal]["StyledText"] != recipe["text"]:
                raise ValueError(f"fcpxml_caption_text:{recipe['caption_id']}")
            targets.append({"ordinal": ordinal, "start": recipe["start_frame"], "end": recipe["start_frame"] + recipe["duration"]})
        occupied = {
            track: [(canary._item_start(item) - base_frame, canary._item_start(item) - base_frame + canary._item_duration(item)) for item in canary._optional(target, "GetItemListInTrack", "video", track, default=[]) or []]
            for track in range(3, EXPECTED_VIDEO_TRACKS + 1)
        }
        allocation = batch.allocate_tracks(targets, occupied)
        while int(canary.carrier._call(target, "GetTrackCount", "video") or 0) < max(allocation.values(), default=3):
            if canary.carrier._call(target, "AddTrack", "video") is not True:
                raise RuntimeError("overlay_track_create")
            created_tracks.append(int(canary.carrier._call(target, "GetTrackCount", "video") or 0))
        existing_names = {row["name"] for row in canary._timeline_inventory(project)}
        names = {row["ordinal"]: _source_name(row["ordinal"], run_id) for row in targets}
        if any(name in existing_names for name in names.values()):
            raise ValueError("source_timeline_collision")
        technical = []
        for recipe in recipes:
            ordinal = int(recipe["caption_id"].rsplit("_", 1)[-1])
            source = canary.carrier._call(pool, "CreateEmptyTimeline", names[ordinal])
            sources.append(source)
            identity = canary._timeline_identity(source)
            if source is None or identity["name"] != names[ordinal] or not identity["unique_id"] or canary.carrier._call(project, "SetCurrentTimeline", source) is not True:
                raise RuntimeError(f"source_timeline_create:{recipe['caption_id']}")
            canary.carrier._call(source, "InsertFusionTitleIntoTimeline", "Text+")
            _, tool = canary.carrier._find_textplus(source)
            style = styles[ordinal]
            static = canary._set_static_style(tool, style)
            comp = canary.carrier._call((canary.carrier._find_textplus(source))[0], "GetFusionCompByIndex", 1)
            applied = apply_recipe_channels(comp, tool, recipe, style)
            source_item = canary.carrier._call(source, "GetMediaPoolItem")
            target = canary._activate_target(project)
            returned = canary.carrier._call(pool, "AppendToTimeline", [{"mediaPoolItem": source_item, "startFrame": 0, "endFrame": recipe["duration"], "trackIndex": allocation[ordinal], "recordFrame": base_frame + recipe["start_frame"]}])
            if not isinstance(returned, (list, tuple)) or len(returned) != 1 or returned[0] is None:
                raise RuntimeError(f"replacement_append:{recipe['caption_id']}")
            item = returned[0]
            placed.append(item)
            track_type, track_index = canary.carrier._call(item, "GetTrackTypeAndIndex")
            placement = {"track_type": track_type, "track": int(track_index), "start": canary._item_start(item) - base_frame, "duration": canary._item_duration(item)}
            expected = {"track_type": "video", "track": allocation[ordinal], "start": recipe["start_frame"], "duration": recipe["duration"]}
            if placement != expected:
                raise RuntimeError(f"replacement_placement:{recipe['caption_id']}:{placement!r}")
            inner = canary.carrier._call(canary.carrier._call(item, "GetMediaPoolItem"), "GetTimeline")
            if inner is None or canary.carrier._timeline_key(inner) != canary.carrier._timeline_key(source):
                raise RuntimeError(f"replacement_inner_timeline:{recipe['caption_id']}")
            _, inner_tool = canary.carrier._find_textplus(inner)
            animated_inputs = _channel_targets(recipe, style)
            static_readback = [
                {
                    "input": name,
                    "expected": expected,
                    "actual": canary.animation.read_input(inner_tool, name, 0),
                    "matched": canary._matches(canary.animation.read_input(inner_tool, name, 0), expected),
                }
                for name, expected in style.items()
                if name not in animated_inputs
            ]
            if any(not row["matched"] for row in static_readback):
                raise RuntimeError(f"replacement_static_readback:{recipe['caption_id']}")
            for input_name, channel_targets in animated_inputs.items():
                if not canary.animation.input_targets_are_correct(inner_tool, input_name, channel_targets):
                    raise RuntimeError(f"replacement_animation_readback:{recipe['caption_id']}:{input_name}")
            original = canary.basic_title_rows(target)[ordinal - 1]["item"]
            hidden.append(ordinal)
            if canary.carrier._call(original, "SetClipEnabled", False) is False or canary._clip_enabled(original) is not False:
                raise RuntimeError(f"source_caption_disable:{recipe['caption_id']}")
            technical.append({"caption_id": recipe["caption_id"], "text": recipe["text"], "placement": placement, "source_timeline": identity, "channels": sorted(recipe["channels"]), "application": applied, "static_readback": static_readback, "technical_status": "PASS"})
        target = canary._activate_target(project)
        captions_after = canary.basic_title_rows(target)
        expected_caption = [tuple(row) for row in caption_before]
        for ordinal in EXPECTED_ORDINALS:
            row = list(expected_caption[ordinal - 1])
            row[3] = False
            expected_caption[ordinal - 1] = tuple(row)
        if _caption_snapshot(captions_after, base_frame) != expected_caption:
            raise RuntimeError("basic_caption_boundary")
        nested_after = _stable_nested(target, base_frame)
        if len(nested_after) != len(nested_before) + len(recipes) or not set(nested_before).issubset(nested_after):
            raise RuntimeError("existing_nested_changed")
        accepted_after = batch._accepted_sub008(target, base_frame)
        if accepted_after["source"] != accepted["source"] or accepted_after["track"] != accepted["track"] or accepted_after["start"] != accepted["start"] or accepted_after["duration"] != accepted["duration"]:
            raise RuntimeError("accepted_sub008_changed")
        result.update({
            "technical_rows": technical,
            "allocation": allocation,
            "created_source_timeline_count": len(sources),
            "created_track_count": len(created_tracks),
            "protected_sub008": {
                "source": accepted_after["source"],
                "track": accepted_after["track"],
                "start": accepted_after["start"] - base_frame,
                "duration": accepted_after["duration"],
            },
            "verification": "PASS",
        })
        result["save_project_called"] = True
        result["save_project_returned"] = canary.carrier._call(manager, "SaveProject")
        if result["save_project_returned"] is not True:
            raise RuntimeError("save_project")
        saved = True
        result["ok"] = True
        return result
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if project is not None and pool is not None and not saved:
            result["rollback"] = _rollback(project, pool, sources, placed, hidden, created_tracks, caption_before, nested_before, base_frame)
        return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
