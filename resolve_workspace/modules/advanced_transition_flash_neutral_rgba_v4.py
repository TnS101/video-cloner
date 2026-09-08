"""Apply source-backed flash cuts with a neutral transparent RGBA carrier.

Architecture family: advanced_transition_flash_neutral_rgba_carrier_v1.
Architecture attempt: 1.

The previous media-backed flash carrier reused the first frames of the source
proxy. Manual review proved those pixels could become visible and create false
jump cuts. This architecture closes that mechanism: the isolated target uses a
four-frame, fully transparent RGBA image sequence as the only carrier beneath
the proven Fusion white-flash graph. No source-video pixels can exist on the
flash track.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import struct
import traceback
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
_V2_PATH = _HERE / "advanced_transition_flash_replacement_v2.py"
_V2_SPEC = importlib.util.spec_from_file_location("vc_flash_replacement_v2_parent_for_neutral_v4", _V2_PATH)
if _V2_SPEC is None or _V2_SPEC.loader is None:
    raise ImportError(f"cannot_load_parent:{_V2_PATH}")
V2 = importlib.util.module_from_spec(_V2_SPEC)
_V2_SPEC.loader.exec_module(V2)
V1 = V2.V1

TASK_ID = "DZSQH7AUHJT_ADVANCED_TRANSITION_FLASH_NEUTRAL_RGBA_V4"
MODE = "ADVANCED_TRANSITION_FLASH_NEUTRAL_RGBA_V4"
VERSION = "advanced_transition_flash_neutral_rgba_v4_0"
ARCHITECTURE_FAMILY = "advanced_transition_flash_neutral_rgba_carrier_v1"
ATTEMPT_NUMBER = 1

SOURCE_TIMELINE_NAME = V1.SOURCE_TIMELINE_NAME
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_flash_transition_v4"
EXPECTED_TEXTPLUS_COUNT = V1.EXPECTED_TEXTPLUS_COUNT
EXPECTED_FLASH_FRAMES = V1.EXPECTED_FLASH_FRAMES
FLASH_PREFIX = V1.FLASH_PREFIX

NEUTRAL_ASSET_DIR_RELATIVE = "data/DZsqH7auhjt/davinci/flash_neutral_rgba_v4"
NEUTRAL_PATTERN = "rgba_%06d.png"
NEUTRAL_FRAME_COUNT = 4
NEUTRAL_MEDIA_POOL_ITEM_NAME = "VC_FLASH_NEUTRAL_RGBA_V4"
NEUTRAL_PNG_SHA256 = "dc22de19adbdf38081eaecb095e0ef5bd2af94f757041a895aced6173d528d9f"
NEUTRAL_PNG_SIZE = (1080, 1920)


def validate_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != "video_cloner_flash_neutral_rgba_plan" or plan.get("schema_version") != 4:
        raise ValueError("plan_schema")
    if plan.get("task_id") != TASK_ID:
        raise ValueError("plan_task_id")
    if plan.get("architecture_family") != ARCHITECTURE_FAMILY or int(plan.get("attempt_number") or 0) != ATTEMPT_NUMBER:
        raise ValueError("plan_architecture")
    if plan.get("source_timeline_name") != SOURCE_TIMELINE_NAME or plan.get("target_timeline_name") != TARGET_TIMELINE_NAME:
        raise ValueError("plan_timeline")
    if int(plan.get("expected_textplus_count") or 0) != EXPECTED_TEXTPLUS_COUNT:
        raise ValueError("plan_textplus_count")

    carrier = plan.get("carrier")
    if not isinstance(carrier, Mapping):
        raise ValueError("plan_carrier")
    carrier_checks = (
        carrier.get("kind") == "transparent_rgba_sequence",
        carrier.get("asset_dir") == NEUTRAL_ASSET_DIR_RELATIVE,
        carrier.get("pattern") == NEUTRAL_PATTERN,
        int(carrier.get("frame_count") or 0) == NEUTRAL_FRAME_COUNT,
        int(carrier.get("source_start", -1)) == 0,
        int(carrier.get("source_end_exclusive") or -1) == NEUTRAL_FRAME_COUNT,
        carrier.get("media_pool_item_name") == NEUTRAL_MEDIA_POOL_ITEM_NAME,
        carrier.get("source_video_pixels_possible") is False,
        carrier.get("png_sha256") == NEUTRAL_PNG_SHA256,
    )
    if not all(carrier_checks):
        raise ValueError("plan_carrier_contract")

    rows = plan.get("flashes")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_FLASH_FRAMES):
        raise ValueError("plan_flash_count")
    frames = tuple(int(row.get("cut_frame") or -1) for row in rows if isinstance(row, Mapping))
    if frames != EXPECTED_FLASH_FRAMES:
        raise ValueError(f"plan_flash_frames:{frames}")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"plan_flash_row:{index}")
        cut = EXPECTED_FLASH_FRAMES[index - 1]
        stale = row.get("stale_native_transition")
        expected_stale = V2.EXPECTED_STALE_NATIVE_TRANSITIONS[cut]
        checks = (
            row.get("name") == f"{FLASH_PREFIX}{index:03d}_frame_{cut:04d}",
            row.get("transition_type") == "flash_cut",
            row.get("confidence") == "high",
            row.get("editor_actionable") is True,
            int(row.get("duration_frames") or 0) == 4,
            int(row.get("outgoing_frames") or 0) == 2,
            int(row.get("incoming_frames") or 0) == 2,
            int(row.get("start_frame") or -1) == cut - 2,
            row.get("flash_color") == [1.0, 1.0, 1.0],
            row.get("alpha_keyframes") == [[0, 0.0], [2, 0.75], [3, 0.0]],
            isinstance(stale, Mapping),
            isinstance(stale, Mapping) and stale.get("name") == expected_stale[0],
            isinstance(stale, Mapping) and int(stale.get("start_frame") or -1) == expected_stale[1],
            isinstance(stale, Mapping) and int(stale.get("end_frame") or -1) == expected_stale[2],
        )
        if not all(checks):
            raise ValueError(f"plan_flash_contract:{index}")

    unhashed = dict(plan)
    expected_hash = str(unhashed.pop("plan_sha256", "") or "")
    if not expected_hash or V1.canonical_sha256(unhashed) != expected_hash:
        raise ValueError("plan_hash")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_transparent_rgba_png(path: Path) -> Dict[str, Any]:
    data = path.read_bytes()
    result: Dict[str, Any] = {"path": str(path), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "ok": False}
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        result["error"] = "png_signature"
        return result
    offset = 8
    ihdr = None
    idat = bytearray()
    try:
        while offset + 12 <= len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            payload = data[offset + 8:offset + 8 + length]
            offset += 12 + length
            if kind == b"IHDR":
                ihdr = payload
            elif kind == b"IDAT":
                idat.extend(payload)
            elif kind == b"IEND":
                break
        if ihdr is None or len(ihdr) != 13:
            raise ValueError("ihdr")
        width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", ihdr)
        result.update({"width": width, "height": height, "bit_depth": bit_depth, "color_type": color_type})
        if (width, height) != NEUTRAL_PNG_SIZE or (bit_depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
            raise ValueError("rgba8_contract")
        raw = zlib.decompress(bytes(idat))
        stride = width * 4
        if len(raw) != height * (stride + 1):
            raise ValueError("raw_size")
        for row_index in range(height):
            row = raw[row_index * (stride + 1):(row_index + 1) * (stride + 1)]
            if row[0] != 0 or any(row[1:]):
                raise ValueError(f"nontransparent_pixel:{row_index}")
        if result["sha256"] != NEUTRAL_PNG_SHA256:
            raise ValueError("asset_hash")
        result["all_rgba_zero"] = True
        result["ok"] = True
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def validate_neutral_assets(root: Path) -> Dict[str, Any]:
    directory = root / NEUTRAL_ASSET_DIR_RELATIVE
    rows = []
    for index in range(NEUTRAL_FRAME_COUNT):
        path = directory / f"rgba_{index:06d}.png"
        if not path.is_file():
            rows.append({"path": str(path), "ok": False, "error": "missing"})
        else:
            rows.append(_validate_transparent_rgba_png(path))
    return {
        "ok": len(rows) == NEUTRAL_FRAME_COUNT and all(row.get("ok") is True for row in rows),
        "asset_dir": str(directory),
        "pattern": str((directory / NEUTRAL_PATTERN).resolve()),
        "frame_count": NEUTRAL_FRAME_COUNT,
        "source_video_pixels_possible": False,
        "rows": rows,
    }


def _set_media_pool_item_name(item: Any, name: str) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for method in ("SetName",):
        value, call = V1.direct_call(item, method, name)
        attempts.append(call)
        if value and str(V1.safe_call(item, "GetName", default="") or "") == name:
            return {"ok": True, "name": name, "attempts": attempts}
    for key in ("Clip Name", "Name"):
        value, call = V1.direct_call(item, "SetClipProperty", key, name)
        attempts.append(call)
        if value and str(V1.safe_call(item, "GetName", default="") or "") == name:
            return {"ok": True, "name": name, "attempts": attempts}
    return {"ok": False, "name": name, "attempts": attempts, "readback": str(V1.safe_call(item, "GetName", default="") or "")}


def _set_neutral_media_properties(item: Any) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for key, value in (("Video Frame Rate", "24"), ("FPS", "24"), ("Alpha mode", "Straight"), ("Alpha Mode", "Straight")):
        returned, call = V1.direct_call(item, "SetClipProperty", key, value)
        attempts.append(call)
    return {"attempts": attempts}


def _normal_path(value: Any) -> str:
    return os.path.normcase(os.path.normpath(str(Path(str(value)).resolve()))) if value else ""


def _clip_properties(item: Any) -> Dict[str, Any]:
    value = V1.safe_call(item, "GetClipProperty", default={}) or {}
    return dict(value) if isinstance(value, Mapping) else {}


def _media_row(item: Any, folder_path: str = "") -> Dict[str, Any]:
    properties = _clip_properties(item)
    path = next((properties[key] for key in ("File Path", "FilePath", "Path") if properties.get(key)), "")
    unique_id = str(V1.safe_call(item, "GetUniqueId", default="") or "")
    if not unique_id:
        unique_id = next((str(properties[key]) for key in ("Media ID", "Unique ID", "Clip ID") if properties.get(key)), "")
    return {
        "item": item,
        "folder_path": folder_path,
        "name": str(V1.safe_call(item, "GetName", default="") or ""),
        "unique_id": unique_id or None,
        "normalized_source_path": _normal_path(path),
        "frame_rate": next((properties.get(key) for key in ("Video Frame Rate", "FPS", "Frame Rate") if properties.get(key) not in (None, "")), None),
        "alpha_mode": next((properties.get(key) for key in ("Alpha mode", "Alpha Mode") if properties.get(key) not in (None, "")), None),
    }


def _public_media_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in ("folder_path", "name", "unique_id", "normalized_source_path", "frame_rate", "alpha_mode")}


def _media_inventory(media_pool: Any) -> Dict[str, Any]:
    root, root_call = V1.direct_call(media_pool, "GetRootFolder")
    if not root_call.get("ok") or root is None:
        return {"complete": False, "rows": []}
    rows: List[Dict[str, Any]] = []
    seen = set()
    complete = [True]

    def walk(folder: Any, parents: List[str]) -> None:
        marker = id(folder)
        if marker in seen:
            return
        seen.add(marker)
        name = str(V1.safe_call(folder, "GetName", default="") or "")
        here = parents + ([name] if name else [])
        clips, clips_call = V1.direct_call(folder, "GetClipList")
        if not clips_call.get("ok"):
            complete[0] = False
            clips = []
        clips = clips or []
        for item in (clips.values() if isinstance(clips, Mapping) else clips):
            rows.append(_media_row(item, "/".join(here)))
        children, children_call = V1.direct_call(folder, "GetSubFolderList")
        if not children_call.get("ok"):
            complete[0] = False
            children = []
        children = children or []
        for child in (children.values() if isinstance(children, Mapping) else children):
            walk(child, here)

    walk(root, [])
    return {"complete": complete[0], "rows": rows}


def _expected_source_paths(root: Path) -> set[str]:
    directory = root / NEUTRAL_ASSET_DIR_RELATIVE
    return {
        _normal_path(directory / NEUTRAL_PATTERN),
        _normal_path(directory / "rgba_[000000-000003].png"),
    }


def _compatible(row: Mapping[str, Any], expected_paths: set[str]) -> Dict[str, Any]:
    try:
        fps_ok = abs(float(row.get("frame_rate")) - 24.0) <= 1e-6
    except (TypeError, ValueError):
        fps_ok = False
    checks = {
        "source_path": row.get("normalized_source_path") in expected_paths,
        "name": row.get("name") == NEUTRAL_MEDIA_POOL_ITEM_NAME,
        "frame_rate": fps_ok,
        "alpha_mode": str(row.get("alpha_mode") or "").strip().lower() == "straight",
    }
    readable = row.get("frame_rate") not in (None, "") and row.get("alpha_mode") not in (None, "")
    return {"ok": all(checks.values()), "readable": readable, "checks": checks}


def _inventory_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("unique_id") or ""), str(row.get("normalized_source_path") or ""), str(row.get("name") or ""))


def _delete_owned_media_pool_item(media_pool: Any, ownership: Mapping[str, Any] | None) -> Dict[str, Any]:
    permitted = bool(ownership and ownership.get("ownership_classification") == "NEWLY_CREATED" and ownership.get("rollback_delete_permitted") is True)
    item = ownership.get("item") if ownership else None
    if not permitted or item is None:
        return {"permitted": permitted, "attempted": False, "ok": True, "deleted": 0}
    value, call = V1.direct_call(media_pool, "DeleteClips", [item])
    return {"permitted": True, "attempted": True, "ok": bool(value), "deleted": 1 if value else 0, "call": call}


def import_neutral_carrier(media_pool: Any, root: Path, assets: Mapping[str, Any]) -> Dict[str, Any]:
    pattern = str((root / NEUTRAL_ASSET_DIR_RELATIVE / NEUTRAL_PATTERN).resolve())
    expected_paths = _expected_source_paths(root)
    payload = [{"FilePath": pattern, "StartIndex": 0, "EndIndex": NEUTRAL_FRAME_COUNT - 1}]
    before = _media_inventory(media_pool)
    result: Dict[str, Any] = {
        "ok": False,
        "kind": "transparent_rgba_sequence",
        "source_video_pixels_possible": False,
        "payload": payload,
        "item": None,
        "inventory_complete": before["complete"],
        "pre_import_candidates": [],
        "returned_media_identity": None,
        "selected_media_identity": None,
        "ownership_classification": "OWNERSHIP_AMBIGUOUS",
        "compatible": False,
        "import_performed": False,
        "rename_write_count": 0,
        "property_write_count": 0,
        "rollback_delete_permitted": False,
    }
    if not before["complete"]:
        result["error"] = "pre_import_inventory_incomplete"
        return result
    candidates = [row for row in before["rows"] if row["normalized_source_path"] in expected_paths]
    result["pre_import_candidates"] = [_public_media_row(row) for row in candidates]
    if len(candidates) > 1:
        result["error"] = "duplicate_preexisting_source"
        return result
    if candidates:
        item = candidates[0]
        compatibility = _compatible(item, expected_paths)
        result.update({"item": item["item"], "selected_media_identity": _public_media_row(item), "compatibility": compatibility, "compatible": compatibility["ok"]})
        if compatibility["ok"]:
            result.update({"ok": assets.get("ok") is True, "ownership_classification": "PREEXISTING_COMPATIBLE", "media_pool_item_name": item["name"], "source_start": 0, "source_end_exclusive": NEUTRAL_FRAME_COUNT})
        else:
            result["ownership_classification"] = "OWNERSHIP_AMBIGUOUS" if not compatibility["readable"] else "PREEXISTING_INCOMPATIBLE"
            result["error"] = "preexisting_contract_unproven" if not compatibility["readable"] else "preexisting_contract_incompatible"
        return result

    returned, call = V1.direct_call(media_pool, "ImportMedia", payload)
    items = list(returned) if isinstance(returned, (list, tuple)) else ([returned] if returned is not None else [])
    result.update({"call": call, "returned_count": len(items), "import_performed": True})
    if len(items) != 1:
        result["error"] = f"neutral_import_count:{len(items)}"
        return result
    item = items[0]
    returned_row = _media_row(item)
    result.update({"item": item, "returned_media_identity": _public_media_row(returned_row), "selected_media_identity": _public_media_row(returned_row)})
    after = _media_inventory(media_pool)
    result["post_import_inventory_complete"] = after["complete"]
    if not after["complete"] or returned_row["normalized_source_path"] not in expected_paths:
        result["error"] = "post_import_identity_unproven"
        return result
    if returned_row["unique_id"]:
        existed = any(row["unique_id"] == returned_row["unique_id"] for row in before["rows"] if row["unique_id"])
        present = sum(row["unique_id"] == returned_row["unique_id"] for row in after["rows"]) == 1
        proven_new = not existed and present
    else:
        delta = Counter(map(_inventory_key, after["rows"])) - Counter(map(_inventory_key, before["rows"]))
        reverse = Counter(map(_inventory_key, before["rows"])) - Counter(map(_inventory_key, after["rows"]))
        proven_new = not reverse and sum(delta.values()) == 1 and delta[_inventory_key(returned_row)] == 1
    if not proven_new:
        result["error"] = "returned_media_ownership_ambiguous"
        return result
    result.update({"ownership_classification": "NEWLY_CREATED", "rollback_delete_permitted": True})
    rename = _set_media_pool_item_name(item, NEUTRAL_MEDIA_POOL_ITEM_NAME)
    properties = _set_neutral_media_properties(item)
    readback = _media_row(item)
    compatibility = _compatible(readback, expected_paths)
    result.update({
        "rename": rename,
        "properties": properties,
        "rename_write_count": len(rename.get("attempts") or []),
        "property_write_count": len(properties.get("attempts") or []),
        "returned_media_identity": _public_media_row(readback),
        "selected_media_identity": _public_media_row(readback),
        "compatibility": compatibility,
        "compatible": compatibility["ok"],
        "media_pool_item_name": readback["name"],
        "source_start": 0,
        "source_end_exclusive": NEUTRAL_FRAME_COUNT,
        "asset_verification_ok": assets.get("ok") is True,
        "ok": bool(rename.get("ok") and compatibility["ok"] and assets.get("ok") is True),
    })
    return result


def neutral_flash_snapshot(timeline: Any, flashes: Sequence[Mapping[str, Any]], expected_track: int) -> Dict[str, Any]:
    base = V1.flash_snapshot(timeline, flashes, expected_track)
    by_name: Dict[str, Dict[str, Any]] = {}
    for track_index, item in V1.all_video_items(timeline):
        name = V1.item_name(item)
        if not name.startswith(FLASH_PREFIX):
            continue
        media_item = V1.safe_call(item, "GetMediaPoolItem", default=None)
        media_name = str(V1.safe_call(media_item, "GetName", default="") or "") if media_item is not None else ""
        by_name[name] = {
            "track_index": track_index,
            "media_pool_item_name": media_name,
            "has_media_pool_item": media_item is not None,
            "neutral_carrier_ok": bool(media_item is not None and media_name == NEUTRAL_MEDIA_POOL_ITEM_NAME),
            "source_video_pixels_possible": False if media_name == NEUTRAL_MEDIA_POOL_ITEM_NAME else True,
        }
    rows = []
    for row in list(base.get("rows") or []):
        merged = dict(row)
        carrier = by_name.get(str(row.get("name") or ""), {})
        merged["carrier"] = carrier
        merged["contract_ok"] = bool(row.get("contract_ok") and carrier.get("neutral_carrier_ok") is True and carrier.get("source_video_pixels_possible") is False)
        rows.append(merged)
    result = dict(base)
    result["rows"] = rows
    result["neutral_carrier_count"] = sum(1 for row in rows if row.get("carrier", {}).get("neutral_carrier_ok") is True)
    result["source_video_carrier_count"] = sum(1 for row in rows if row.get("carrier", {}).get("source_video_pixels_possible") is True)
    result["ok"] = bool(base.get("ok") and len(rows) == len(flashes) and all(row.get("contract_ok") for row in rows) and result["source_video_carrier_count"] == 0)
    return result


def target_contract(source: Mapping[str, Any], target: Any, flashes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    target_captions = V1.caption_snapshot(target)
    target_native = V2.native_transition_snapshot(target)
    target_media = V2.media_geometry_snapshot(target)
    stale = V2.stale_transition_snapshot(target, flashes)
    expected_track = int(source["captions"]["video_track_count"]) + 1
    flash = neutral_flash_snapshot(target, flashes, expected_track)
    expected_native_hash = V1.canonical_sha256(V2.expected_native_rows_after_removal(source["native_transitions"], flashes))
    result = {
        "caption_snapshot": target_captions,
        "native_transition_snapshot": target_native,
        "media_geometry_snapshot": target_media,
        "stale_transition_snapshot": stale,
        "flash_snapshot": flash,
        "caption_count_ok": target_captions["count"] == EXPECTED_TEXTPLUS_COUNT,
        "caption_geometry_unchanged": target_captions["sha256"] == source["captions"]["sha256"],
        "media_geometry_unchanged": target_media["sha256"] == source["media_geometry"]["sha256"],
        "unrelated_transitions_unchanged": target_native["sha256"] == expected_native_hash,
        "stale_transitions_absent": stale["count"] == 0,
        "track_count_ok": target_captions["video_track_count"] == expected_track,
        "neutral_carrier_only": flash.get("source_video_carrier_count") == 0 and flash.get("neutral_carrier_count") == len(flashes),
    }
    result["ok"] = bool(
        result["caption_count_ok"]
        and result["caption_geometry_unchanged"]
        and result["media_geometry_unchanged"]
        and result["unrelated_transitions_unchanged"]
        and result["stale_transitions_absent"]
        and result["track_count_ok"]
        and result["neutral_carrier_only"]
        and flash.get("ok")
    )
    return result


def cleanup_failed(project_manager: Any, project: Any, media_pool: Any, source: Any, target_name: str, media_ownership: Mapping[str, Any] | None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"attempted": True, "errors": [], "ok": False}
    value, restore = V1.direct_call(project, "SetCurrentTimeline", source)
    result["restore_source"] = restore
    if not value:
        result["errors"].append("restore_source")
    target = V1.find_timeline(project, target_name)
    if target is not None:
        value, delete_target = V1.direct_call(media_pool, "DeleteTimelines", [target])
        result["delete_target"] = delete_target
        result["target_deleted"] = bool(value)
        if not value:
            result["errors"].append("delete_target")
    else:
        result["target_deleted"] = True
    delete_media = _delete_owned_media_pool_item(media_pool, media_ownership)
    result["delete_imported_neutral_media"] = delete_media
    if delete_media.get("attempted") and not delete_media.get("ok"):
        result["errors"].append("delete_imported_neutral_media")
    value, save = V1.direct_call(project_manager, "SaveProject")
    result["save_cleanup"] = save
    if not value:
        result["errors"].append("save_cleanup")
    result["ok"] = not result["errors"]
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = V1.repository_root()
    command = context.get("command") if isinstance(context, Mapping) else None
    if not isinstance(command, Mapping):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
        raise ValueError("command_identity")
    flash_config = command.get("flash")
    if not isinstance(flash_config, Mapping):
        raise ValueError("flash_config")
    run_mode = str(flash_config.get("run_mode") or "")
    if run_mode not in {"apply", "idempotency"}:
        raise ValueError("run_mode")

    report_dir = V1.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    plan = V1.load_json(V1.relative_path(root, flash_config.get("plan_path")))
    validate_plan(plan)
    flashes = list(plan["flashes"])

    report: Dict[str, Any] = {
        "schema_version": 4,
        "task_id": TASK_ID,
        "version": VERSION,
        "architecture_family": ARCHITECTURE_FAMILY,
        "attempt_number": ATTEMPT_NUMBER,
        "run_id": run_id,
        "run_mode": run_mode,
        "ok": False,
        "started_at": V1.utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
        "expected_flash_count": len(flashes),
        "expected_stale_transition_delete_count": len(flashes),
        "carrier_architecture": "transparent_rgba_sequence_no_source_video_pixels",
        "save_call_count": 0,
        "timeline_duplicate_count": 0,
        "stale_transition_delete_count": 0,
        "video_track_add_count": 0,
        "flash_carrier_append_count": 0,
        "fusion_flash_configure_count": 0,
        "neutral_media_import_count": 0,
        "source_timeline_unchanged": False,
        "visual_approval_required": run_mode == "apply",
        "failures": [],
    }
    duplicate_created = False
    saved = False
    media_ownership = None
    project_manager = project = media_pool = source = None
    try:
        report["source_contract"] = V1.verify_source_contract(root, command)
        assets = validate_neutral_assets(root)
        report["neutral_asset_verification"] = assets
        if not assets["ok"]:
            raise RuntimeError("neutral_asset_verification")

        project_manager = V1.safe_call(resolve, "GetProjectManager", default=None)
        if project_manager is None:
            raise RuntimeError("project_manager")
        project = V1.safe_call(project_manager, "GetCurrentProject", default=None)
        if project is None:
            raise RuntimeError("project")
        media_pool = V1.safe_call(project, "GetMediaPool", default=None)
        if media_pool is None:
            raise RuntimeError("media_pool")

        source = V1.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        source_before = V2.source_state(source)
        report["source_before"] = source_before["captions"]
        report["source_transition_before"] = source_before["native_transitions"]
        report["source_media_before"] = source_before["media_geometry"]
        if source_before["captions"]["count"] != EXPECTED_TEXTPLUS_COUNT:
            raise RuntimeError(f"source_textplus_count:{source_before['captions']['count']}")
        source_stale = V2.stale_transition_snapshot(source, flashes)
        report["source_stale_transition_snapshot"] = source_stale
        if source_stale["count"] != len(flashes):
            raise RuntimeError(f"source_stale_transition_count:{source_stale['count']}")

        existing_target = V1.find_timeline(project, TARGET_TIMELINE_NAME)
        if run_mode == "idempotency":
            if existing_target is None:
                raise RuntimeError("idempotency_target_missing")
            target_before = target_contract(source_before, existing_target, flashes)
            report["target_before"] = target_before
            if not target_before["ok"]:
                raise RuntimeError("idempotency_target_contract")
            source_after = V2.source_state(source)
            report["source_after"] = source_after["captions"]
            report["source_transition_after"] = source_after["native_transitions"]
            report["source_media_after"] = source_after["media_geometry"]
            report["source_timeline_unchanged"] = V2.source_state_unchanged(source_before, source_after)
            report["target_after"] = target_contract(source_after, existing_target, flashes)
            report["idempotent"] = bool(
                report["source_timeline_unchanged"]
                and report["target_after"]["ok"]
                and report["save_call_count"] == 0
                and report["timeline_duplicate_count"] == 0
                and report["stale_transition_delete_count"] == 0
                and report["video_track_add_count"] == 0
                and report["flash_carrier_append_count"] == 0
                and report["fusion_flash_configure_count"] == 0
                and report["neutral_media_import_count"] == 0
            )
            report["ok"] = report["idempotent"]
            if not report["ok"]:
                raise RuntimeError("idempotency_contract")
            report["finished_at"] = V1.utc_now()
            V1.write_json(report_dir / "flash_transition_replacement.json", report)
            return report

        if existing_target is not None:
            raise RuntimeError("target_exists")

        value, duplicate_call = V1.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = value if value is not None else V1.find_timeline(project, TARGET_TIMELINE_NAME)
        report["duplicate_call"] = duplicate_call
        if target is None:
            raise RuntimeError("duplicate_timeline")
        duplicate_created = True
        report["timeline_duplicate_count"] = 1
        if V1.timeline_name(target) != TARGET_TIMELINE_NAME:
            raise RuntimeError("target_timeline_name")

        value, set_current = V1.direct_call(project, "SetCurrentTimeline", target)
        report["set_current_target"] = set_current
        if not value:
            raise RuntimeError("set_current_target")

        duplicated_state = V2.source_state(target)
        report["duplicate_caption_snapshot"] = duplicated_state["captions"]
        report["duplicate_transition_snapshot"] = duplicated_state["native_transitions"]
        report["duplicate_media_snapshot"] = duplicated_state["media_geometry"]
        if (
            duplicated_state["captions"]["sha256"] != source_before["captions"]["sha256"]
            or duplicated_state["native_transitions"]["sha256"] != source_before["native_transitions"]["sha256"]
            or duplicated_state["media_geometry"]["sha256"] != source_before["media_geometry"]["sha256"]
        ):
            raise RuntimeError("duplicate_source_state")

        removal = V2.remove_stale_native_transitions(target, flashes)
        report["stale_transition_removal"] = V1.json_safe(removal)
        if not removal["ok"]:
            raise RuntimeError("stale_flash_transition_removal")
        report["stale_transition_delete_count"] = int(removal["delete_count"])

        post_removal_captions = V1.caption_snapshot(target)
        report["post_removal_caption_snapshot"] = post_removal_captions
        if post_removal_captions["sha256"] != source_before["captions"]["sha256"]:
            raise RuntimeError("caption_changed_by_transition_removal")

        track_setup = V1.ensure_extra_video_track(target, int(source_before["captions"]["video_track_count"]))
        report["track_setup"] = track_setup
        if not track_setup["ok"]:
            raise RuntimeError("flash_track")
        report["video_track_add_count"] = 1
        flash_track = int(track_setup["target_track"])

        imported = import_neutral_carrier(media_pool, root, assets)
        media_ownership = imported
        imported_media_item = imported.get("item")
        report["carrier_source"] = {k: V1.json_safe(v) for k, v in imported.items() if k != "item"}
        if not imported["ok"] or imported_media_item is None:
            raise RuntimeError("neutral_carrier_import")
        report["neutral_media_import_count"] = int(imported.get("import_performed") is True)

        carrier = {"ok": True, "media_pool_item": imported_media_item, "source_start": 0}
        append = V1.append_flash_carriers(media_pool, target, carrier, flashes, flash_track)
        report["append"] = {k: V1.json_safe(v) for k, v in append.items() if k != "assigned"}
        if not append["ok"]:
            raise RuntimeError("flash_append")
        report["flash_carrier_append_count"] = len(flashes)

        configure_rows = []
        for index, (spec, item) in enumerate(append["assigned"], start=1):
            row = V1.configure_flash(item, spec, index)
            configure_rows.append(row)
            if not row.get("ok"):
                report["configure_rows"] = configure_rows
                raise RuntimeError(f"flash_fusion:{index}")
        report["configure_rows"] = configure_rows
        report["fusion_flash_configure_count"] = len(configure_rows)

        target_before_save = target_contract(source_before, target, flashes)
        report["target_before_save"] = target_before_save
        if not target_before_save["ok"]:
            raise RuntimeError("pre_save_target_contract")
        source_mid = V2.source_state(source)
        report["source_mid"] = source_mid["captions"]
        if not V2.source_state_unchanged(source_before, source_mid):
            raise RuntimeError("source_changed_before_save")

        value, save_call = V1.direct_call(project_manager, "SaveProject")
        report["save_call"] = save_call
        report["save_call_count"] = 1
        if not value:
            raise RuntimeError("save_project")
        saved = True

        persistent_target = V1.find_timeline(project, TARGET_TIMELINE_NAME)
        if persistent_target is None:
            raise RuntimeError("persistent_target_missing")
        source_after = V2.source_state(source)
        target_after = target_contract(source_after, persistent_target, flashes)
        report["source_after"] = source_after["captions"]
        report["source_transition_after"] = source_after["native_transitions"]
        report["source_media_after"] = source_after["media_geometry"]
        report["target_after"] = target_after
        report["source_timeline_unchanged"] = V2.source_state_unchanged(source_before, source_after)
        report["persistent_readback_ok"] = bool(report["source_timeline_unchanged"] and target_after["ok"])
        report["ok"] = report["persistent_readback_ok"]
        if not report["ok"]:
            raise RuntimeError("persistent_readback")

        report["finished_at"] = V1.utc_now()
        V1.write_json(report_dir / "flash_transition_replacement.json", report)
        return report

    except BaseException as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
        if duplicate_created and not saved and project_manager is not None and project is not None and media_pool is not None and source is not None:
            report["cleanup"] = cleanup_failed(project_manager, project, media_pool, source, TARGET_TIMELINE_NAME, media_ownership)
            report["save_call_count"] += 1
        report["finished_at"] = V1.utc_now()
        try:
            V1.write_json(report_dir / "flash_transition_replacement.json", report)
        except Exception:
            pass
        return report
