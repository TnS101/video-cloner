"""Apply the first Reel #3 caption animation through the proven OSS carrier.

Carrier adapted from samuelgursky/davinci-resolve-mcp, commit
94c7a885d53f13be78522ce96561a9e9e21d64c5,
tests/live_workaround_verification.py::case_nested_title (MIT License).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import xml.etree.ElementTree as ET
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


carrier = _load("vc_oss001_carrier", MODULE_DIR / "oss001_nested_textplus_compat.py")
_autorun = os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN")
os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = "1"
try:
    animation = _load("vc_caption_animation", MODULE_DIR.parent / "resolve_apply_caption_animation_step_3C.py")
finally:
    if _autorun is None:
        os.environ.pop("VC_DISABLE_WORKSPACE_AUTORUN", None)
    else:
        os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = _autorun

TASK_ID = "OSS002_SUB008_PRODUCTION_CANARY_V1"
MODE = "oss002_sub008_production_canary"
PROJECT_NAME = "VIDEO_CLONER_REEL3_FREE2104"
TARGET_TIMELINE = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1"
STALE_SOURCE_TIMELINE = "_VC_OSS002_SUB008_SOURCE"
SOURCE_TIMELINE_PREFIX = "_VC_OSS002_SUB008_"
EXPECTED_RESOLVE_VERSION = "21.0.4.5"
EXPECTED_CAPTIONS = 112
ORDINAL = 8
TEXT = "this"
RELATIVE_START = 39
DURATION = 5
ANIMATION_KEYS = (
    (0, 0.0, (-0.0514, 0.0005)),
    (3, 0.666, (0.0, 0.0)),
    (4, 1.0, (0.0, 0.0)),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_file(root: Path, value: object, expected_hash: object, label: str) -> Path:
    path = (root / str(value or "")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}_outside_repository") from exc
    if not path.is_file() or _sha256(path) != expected_hash:
        raise ValueError(f"{label}_identity")
    return path


def _optional(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        function = getattr(obj, method, None)
        return function(*args) if callable(function) else default
    except Exception:
        return default


def _name(value: Any) -> str:
    return str(_optional(value, "GetName", default="") or "")


def _timeline_identity(value: Any) -> dict[str, str]:
    return {"name": _name(value), "unique_id": str(_optional(value, "GetUniqueId", default="") or "")}


def _find_timeline(project: Any, name: str) -> Any:
    matches = [
        _optional(project, "GetTimelineByIndex", index)
        for index in range(1, int(_optional(project, "GetTimelineCount", default=0) or 0) + 1)
    ]
    matches = [row for row in matches if row is not None and _name(row) == name]
    if len(matches) != 1:
        raise ValueError(f"target_timeline_name:{len(matches)}")
    identity = _timeline_identity(matches[0])
    if not identity["unique_id"]:
        raise ValueError("target_timeline_uid_missing")
    return matches[0]


def _timeline_inventory(project: Any) -> list[dict[str, str]]:
    return [
        _timeline_identity(_optional(project, "GetTimelineByIndex", index))
        for index in range(1, int(_optional(project, "GetTimelineCount", default=0) or 0) + 1)
    ]


def _source_timeline_name(run_id: str) -> str:
    token = str(run_id).rsplit("_", 1)[-1][:12]
    if not token:
        raise ValueError("run_id_source_name")
    return SOURCE_TIMELINE_PREFIX + token


def _item_start(item: Any) -> int:
    value = _optional(item, "GetStart")
    if value is None:
        raise ValueError("caption_start_missing")
    return int(value)


def _item_duration(item: Any) -> int:
    value = _optional(item, "GetDuration")
    if value is None:
        raise ValueError("caption_duration_missing")
    return int(value)


def _clip_enabled(item: Any) -> bool:
    value = _optional(item, "GetClipEnabled")
    if not isinstance(value, bool):
        raise ValueError("caption_enabled_readback")
    return value


def _optional_title_text(item: Any) -> str | None:
    values = _optional(item, "GetProperty", default={}) or {}
    if isinstance(values, dict):
        for key in ("Text", "StyledText", "Title"):
            if values.get(key) not in (None, ""):
                return str(values[key])
    for key in ("Text", "StyledText", "Title"):
        value = _optional(item, "GetProperty", key)
        if value not in (None, ""):
            return str(value)
    return None


def basic_title_rows(timeline: Any) -> list[dict[str, Any]]:
    rows = []
    for track in range(1, int(_optional(timeline, "GetTrackCount", "video", default=0) or 0) + 1):
        for index, item in enumerate(_optional(timeline, "GetItemListInTrack", "video", track, default=[]) or []):
            if _optional(item, "GetMediaPoolItem") is None and int(_optional(item, "GetFusionCompCount", default=0) or 0) == 0:
                rows.append({
                    "item": item, "track": track, "track_ordinal": index,
                    "start": _item_start(item), "duration": _item_duration(item),
                    "enabled": _clip_enabled(item), "text_readback": _optional_title_text(item),
                })
    return sorted(rows, key=lambda row: (row["start"], row["track"], row["track_ordinal"]))


def _other_caption_snapshot(rows: list[dict[str, Any]], base_frame: int) -> list[tuple[Any, ...]]:
    if len(rows) != EXPECTED_CAPTIONS:
        raise ValueError(f"basic_title_count:{len(rows)}")
    return [
        (ordinal, row["start"] - base_frame, row["duration"], row["enabled"])
        for ordinal, row in enumerate(rows, start=1) if ordinal != ORDINAL
    ]


def _source_contract(fcpxml: Path) -> dict[str, Any]:
    root = ET.parse(fcpxml).getroot()
    titles = list(root.findall("./library/event/project/sequence/spine/title"))
    formats = list(root.findall("./resources/format"))
    if len(titles) != EXPECTED_CAPTIONS or len(formats) != 1:
        raise ValueError("fcpxml_caption_contract")
    title = titles[ORDINAL - 1]
    text_node = title.find("./text/text-style")
    style_node = title.find("./text-style-def/text-style")
    width = int(formats[0].get("width") or 0)
    if text_node is None or style_node is None or width <= 0:
        raise ValueError("fcpxml_sub008_style")
    offset = str(title.get("offset") or "")
    duration = str(title.get("duration") or "")
    if str(text_node.text or "") != TEXT or offset != "39/24s" or duration != "5/24s":
        raise ValueError("fcpxml_sub008_identity")

    def color(name: str, default: str = "0 0 0 0") -> list[float]:
        values = [float(value) for value in str(style_node.get(name) or default).split()]
        if len(values) != 4:
            raise ValueError(f"fcpxml_color:{name}")
        return values

    font_size = float(style_node.get("fontSize") or 0)
    stroke_width = float(style_node.get("strokeWidth") or 0)
    shadow_offset = float(style_node.get("shadowOffset") or 0)
    fill, outline, shadow = color("fontColor"), color("strokeColor"), color("shadowColor")
    return {
        "StyledText": TEXT,
        "Font": str(style_node.get("font") or "Arial"),
        "Style": "Bold" if style_node.get("bold") == "1" else "Regular",
        "Size": max(0.02, font_size / width * 1.5),
        "Center": [0.5, 0.5],
        "Enabled1": 1.0,
        "Red1": fill[0], "Green1": fill[1], "Blue1": fill[2], "Alpha1": fill[3],
        "Enabled2": 1.0, "ElementShape2": 1.0,
        "Red2": outline[0], "Green2": outline[1], "Blue2": outline[2], "Alpha2": outline[3],
        "Thickness2": stroke_width / font_size, "OutsideOnly2": 1.0,
        "Enabled3": 1.0, "ElementShape3": 0.0,
        "Red3": shadow[0], "Green3": shadow[1], "Blue3": shadow[2], "Alpha3": shadow[3],
        "Offset3": [shadow_offset / width, shadow_offset / width],
    }


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str):
        return str(actual or "") == expected
    if isinstance(expected, (list, tuple)):
        point = animation.normalize_point(actual)
        return point is not None and all(abs(point[index] - float(expected[index])) <= 1e-5 for index in (0, 1))
    number = animation.as_float(actual)
    return number is not None and abs(number - float(expected)) <= 1e-5


def _set_static_style(tool: Any, style: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for name, expected in style.items():
        returned = carrier._call(tool, "SetInput", name, expected)
        actual = animation.read_input(tool, name, 0)
        matched = _matches(actual, expected)
        rows.append({"input": name, "expected": expected, "actual": actual, "returned": returned, "matched": matched})
        if not matched:
            raise RuntimeError(f"static_style_readback:{name}")
    return {"ok": True, "rows": rows}


def _animation_payload(style: dict[str, Any]) -> dict[str, Any]:
    center = style["Center"]
    return {
        "authority": "visual_observed",
        "source_evidence_id": "style_event_caption_tracklet_0010",
        "source_type": "slide",
        "property": "Center",
        "keyframes": [
            {"frame": frame, "relative_time": relative_time, "value": [center[0] + offset[0], center[1] + offset[1]]}
            for frame, relative_time, offset in ANIMATION_KEYS
        ],
    }


def _animation_targets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"input": "Center", "local_frame": int(row["frame"]), "expected": list(row["value"])}
        for row in payload["keyframes"]
    ]


def _replacement_exists(timeline: Any, source: Any) -> bool:
    source_key = carrier._timeline_key(source)
    for track in range(1, int(_optional(timeline, "GetTrackCount", "video", default=0) or 0) + 1):
        for item in _optional(timeline, "GetItemListInTrack", "video", track, default=[]) or []:
            pool_item = _optional(item, "GetMediaPoolItem")
            inner = _optional(pool_item, "GetTimeline")
            if inner is not None and carrier._timeline_key(inner) == source_key:
                return True
    return False


def _activate_target(project: Any) -> Any:
    target = _find_timeline(project, TARGET_TIMELINE)
    if _optional(project, "SetCurrentTimeline", target, default=False) is not True:
        raise RuntimeError("target_timeline_activation")
    return target


def _rollback(project: Any, pool: Any, source: Any, placed: Any, original_enabled: bool, hide_attempted: bool, others_before: list[tuple[Any, ...]], created_track: int | None, track_count_before: int) -> dict[str, Any]:
    try:
        target = _activate_target(project)
    except Exception:
        target = None
    restored = not hide_attempted
    if hide_attempted and target is not None:
        try:
            original = basic_title_rows(target)[ORDINAL - 1]["item"]
            returned = _optional(original, "SetClipEnabled", original_enabled, default=False)
            restored = returned is not False and _clip_enabled(original) is original_enabled
        except Exception:
            restored = False
    deleted = True
    if placed is not None and target is not None:
        deleted = _optional(target, "DeleteClips", [placed], False, default=False) is True and not _replacement_exists(target, source)
    elif placed is not None:
        deleted = False
    if created_track is not None and target is not None:
        track_items = _optional(target, "GetItemListInTrack", "video", created_track)
        track_removed = (
            isinstance(track_items, (list, tuple)) and not track_items
            and _optional(target, "DeleteTrack", "video", created_track, default=False) is True
            and int(_optional(target, "GetTrackCount", "video", default=-1)) == track_count_before
        )
    else:
        track_removed = created_track is None
    if source is not None:
        if target is not None:
            _optional(project, "SetCurrentTimeline", target, default=False)
        source_deleted = _optional(pool, "DeleteTimelines", [source], default=False) is True
        remaining = [_timeline_identity(_optional(project, "GetTimelineByIndex", index)) for index in range(1, int(_optional(project, "GetTimelineCount", default=0) or 0) + 1)]
        source_deleted = source_deleted and _timeline_identity(source) not in remaining
    else:
        source_deleted = True
    try:
        target = _activate_target(project)
        rows_after = basic_title_rows(target)
        base_frame = int(_optional(target, "GetStartFrame", default=0) or 0)
        others_unchanged = _other_caption_snapshot(rows_after, base_frame) == others_before
        if hide_attempted:
            restored = restored and rows_after[ORDINAL - 1]["enabled"] is original_enabled
        if created_track is not None:
            track_removed = track_removed and int(_optional(target, "GetTrackCount", "video", default=-1)) == track_count_before
    except Exception:
        others_unchanged = False
    return {"original_restored": restored, "replacement_deleted": deleted, "source_timeline_deleted": source_deleted, "created_track_removed": track_removed, "other_111_unchanged": others_unchanged, "ok": restored and deleted and source_deleted and track_removed and others_unchanged}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_called": False, "failures": []}
    project = pool = target = source = placed = original = None
    original_enabled = True
    hide_attempted = False
    created_track: int | None = None
    track_count_before = 0
    others_before: list[tuple[Any, ...]] = []
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        source_timeline_name = _source_timeline_name(run_id)
        required = {
            "expected_project": PROJECT_NAME, "target_timeline": TARGET_TIMELINE,
            "source_timeline": source_timeline_name, "expected_caption_count": EXPECTED_CAPTIONS,
            "source_ordinal": ORDINAL, "expected_text": TEXT, "relative_start": RELATIVE_START,
            "duration": DURATION, "hide_property": "ClipEnabled", "save_after_verification": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        result["resolve_version"] = str(carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != EXPECTED_RESOLVE_VERSION:
            raise ValueError(f"resolve_version:{result['resolve_version']}")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        fcpxml = _repository_file(root, payload.get("fcpxml_path"), payload.get("fcpxml_sha256"), "fcpxml")
        _repository_file(root, payload.get("animation_plan_path"), payload.get("animation_plan_sha256"), "animation_plan")
        style = _source_contract(fcpxml)

        manager = carrier._call(resolve, "GetProjectManager")
        project = carrier._call(manager, "GetCurrentProject")
        if project is None or _name(project) != PROJECT_NAME:
            raise ValueError(f"project_identity:{_name(project) if project else ''}")
        pool = carrier._call(project, "GetMediaPool")
        target = _find_timeline(project, TARGET_TIMELINE)
        result["target"] = {"project": PROJECT_NAME, **_timeline_identity(target)}
        target = _activate_target(project)
        inventory_before = _timeline_inventory(project)
        stale_matches = [row for row in inventory_before if row["name"] == STALE_SOURCE_TIMELINE]
        result["inline_recovery"] = {
            "stale_name": STALE_SOURCE_TIMELINE,
            "match_count": len(stale_matches),
            "deleted": False,
            "inventory_before": inventory_before,
        }
        if len(stale_matches) > 1:
            raise ValueError(f"stale_source_count:{len(stale_matches)}")
        if stale_matches:
            stale_identity = stale_matches[0]
            target_identity = _timeline_identity(target)
            if not stale_identity["unique_id"] or stale_identity["unique_id"] == target_identity["unique_id"]:
                raise ValueError("stale_source_is_production")
            stale = _find_timeline(project, STALE_SOURCE_TIMELINE)
            if carrier._call(pool, "DeleteTimelines", [stale]) is not True:
                raise RuntimeError("stale_source_delete")
            inventory_after = _timeline_inventory(project)
            if any(row["unique_id"] == stale_identity["unique_id"] for row in inventory_after):
                raise RuntimeError("stale_source_delete_readback")
            target = _activate_target(project)
            result["inline_recovery"].update({"deleted": True, "deleted_timeline": stale_identity, "inventory_after": inventory_after})
        else:
            result["inline_recovery"]["inventory_after"] = inventory_before
        base_frame = int(carrier._call(target, "GetStartFrame") or 0)
        captions = basic_title_rows(target)
        if len(captions) != EXPECTED_CAPTIONS:
            raise ValueError(f"basic_title_count:{len(captions)}")
        original_row = captions[ORDINAL - 1]
        original = original_row["item"]
        if original_row["start"] - base_frame != RELATIVE_START or original_row["duration"] != DURATION:
            raise ValueError(f"sub008_timing:start={original_row['start']}:base={base_frame}:duration={original_row['duration']}")
        if original_row["text_readback"] is not None and original_row["text_readback"] != TEXT:
            raise ValueError(f"sub008_text:{original_row['text_readback']!r}")
        original_enabled = original_row["enabled"]
        if original_enabled is not True:
            raise ValueError("sub008_original_not_visible")
        others_before = _other_caption_snapshot(captions, base_frame)
        track_count_before = int(carrier._call(target, "GetTrackCount", "video") or 0)
        result["source_caption"] = {
            "ordinal": ORDINAL, "text": TEXT, "text_readback": original_row["text_readback"],
            "relative_start": RELATIVE_START, "actual_start": original_row["start"],
            "duration": original_row["duration"], "track": original_row["track"],
            "timeline_base_frame": base_frame,
        }
        existing_names = [row["name"] for row in _timeline_inventory(project)]
        if source_timeline_name in existing_names:
            raise ValueError("source_timeline_collision")

        source = carrier._call(pool, "CreateEmptyTimeline", source_timeline_name)
        source_identity = _timeline_identity(source)
        result["run_source_timeline"] = source_identity
        if source is None or source_identity["name"] != source_timeline_name or not source_identity["unique_id"] or carrier._call(project, "SetCurrentTimeline", source) is not True:
            raise RuntimeError("source_timeline_create")
        carrier._call(source, "InsertFusionTitleIntoTimeline", "Text+")
        _, tool = carrier._find_textplus(source)
        static_result = _set_static_style(tool, style)
        comp = carrier._call((carrier._find_textplus(source))[0], "GetFusionCompByIndex", 1)
        animation_payload = _animation_payload(style)
        animation_result = animation.apply_authorized_animation(comp, tool, animation_payload, DURATION)
        source_item = carrier._call(source, "GetMediaPoolItem")
        if source_item is None:
            raise RuntimeError("source_timeline_media_pool_item_missing")

        replacement_track = original_row["track"] + 1
        if track_count_before < replacement_track:
            if carrier._call(target, "AddTrack", "video") is not True:
                raise RuntimeError("replacement_track_create")
            created_track = replacement_track
        if int(carrier._call(target, "GetTrackCount", "video") or 0) < replacement_track:
            raise RuntimeError("replacement_track_count")
        if carrier._call(project, "SetCurrentTimeline", target) is not True:
            raise RuntimeError("target_timeline_reactivation")
        returned = carrier._call(pool, "AppendToTimeline", [{
            "mediaPoolItem": source_item, "startFrame": 0, "endFrame": DURATION,
            "trackIndex": replacement_track, "recordFrame": original_row["start"],
        }])
        if not isinstance(returned, (list, tuple)) or len(returned) != 1 or returned[0] is None:
            raise RuntimeError("replacement_append_result")
        placed = returned[0]
        track_type, track_index = carrier._call(placed, "GetTrackTypeAndIndex")
        placement = {"track_type": track_type, "track": int(track_index), "start": _item_start(placed), "duration": _item_duration(placed)}
        expected_placement = {"track_type": "video", "track": replacement_track, "start": original_row["start"], "duration": DURATION}
        if placement != expected_placement:
            raise RuntimeError(f"replacement_placement:{placement!r}")
        placed_pool_item = carrier._call(placed, "GetMediaPoolItem")
        if placed_pool_item is None:
            raise RuntimeError("replacement_media_pool_item_missing")
        inner = carrier._call(placed_pool_item, "GetTimeline")
        if inner is None or carrier._timeline_key(inner) != carrier._timeline_key(source):
            raise RuntimeError("replacement_inner_timeline")
        _, inner_tool = carrier._find_textplus(inner)
        static_readback = [
            {"input": name, "expected": expected, "actual": animation.read_input(inner_tool, name, 0), "matched": _matches(animation.read_input(inner_tool, name, 0), expected)}
            for name, expected in style.items() if name != "Center"
        ]
        input_name, targets = "Center", _animation_targets(animation_payload)
        if any(not row["matched"] for row in static_readback) or input_name != "Center" or not animation.input_targets_are_correct(inner_tool, input_name, targets):
            raise RuntimeError("replacement_inner_readback")
        target = _activate_target(project)
        captions_before_hide = basic_title_rows(target)
        if _other_caption_snapshot(captions_before_hide, base_frame) != others_before:
            raise RuntimeError("other_captions_changed_before_hide")
        original = captions_before_hide[ORDINAL - 1]["item"]

        hide_attempted = True
        hide_returned = carrier._call(original, "SetClipEnabled", False)
        hidden = _clip_enabled(original) is False
        if hide_returned is False or not hidden:
            raise RuntimeError("original_clip_disable")
        if not _replacement_exists(target, source):
            raise RuntimeError("replacement_missing_after_hide")
        if _other_caption_snapshot(basic_title_rows(target), base_frame) != others_before:
            raise RuntimeError("other_111_changed")
        if carrier._call(manager, "SaveProject") is not True:
            raise RuntimeError("save_project_failed")
        result.update({
            "ok": True, "save_project_called": True, "save_project_returned": True,
            "carrier": {"source_timeline": _timeline_identity(source), "placement": placement, "end_frame_exclusive": True, "inner_timeline": _timeline_identity(inner)},
            "style": static_result, "style_readback": static_readback,
            "animation": animation_result, "original_sub008": {"clip_enabled_before": original_enabled, "clip_enabled_after": _clip_enabled(original), "hidden_after_replacement_verification": True},
            "other_111_untouched": True,
        })
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if project is not None and pool is not None and target is not None and (source is not None or placed is not None or hide_attempted or created_track is not None):
            rollback = _rollback(project, pool, source, placed, original_enabled, hide_attempted, others_before, created_track, track_count_before)
            result["rollback"] = rollback
            if not rollback["ok"]:
                result["failures"].append("RuntimeError: rollback_failed")
    return result
