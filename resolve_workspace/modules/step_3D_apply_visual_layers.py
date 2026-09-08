"""Apply accepted Step 3B positions and Step 3C animations to the Step 3D lifecycle timeline."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable

TASK_ID = "DZSQH7AUHJT_STEP_3D_LIFECYCLE_VISUAL_LAYER_FUSION_PAGE_RECOVERY_V1"
MODE = "apply_step_3D_visual_layers_fusion_page_recovery_v1"
EXPECTED_PROJECT = "New Project 1"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_lifecycle"
EXPECTED_CAPTION_COUNT = 116
EXPECTED_ANIMATION_COUNT = 8
EXPECTED_KEYFRAME_COUNT = 16
EXPECTED_CAPTION_LANE_COUNT = 5
EXPECTED_BASE_CLIP_COUNT = 22
EXPECTED_TRANSITION_COUNT = 11

POSITION_HELPER_REL = "resolve_workspace/resolve_apply_caption_position_full_step_3B_5.py"
ANIMATION_HELPER_REL = "resolve_workspace/resolve_apply_caption_animation_step_3C.py"
IMPORT_HELPER_REL = "resolve_workspace/modules/step_3D_import_lifecycle_timeline.py"
POSITION_PLAN_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_position_full_plan_step_3B_5B.json"
ANIMATION_TARGETS_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_animation_step_3C_source_targets.json"
LIFECYCLE_PLAN_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json"
FCPXML_REL = "data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_step_3D_lifecycle.fcpxml"
SOURCE_HASH_CONTRACT_VERSION = 2
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
CLONE_STRATEGY = "IMPORT_THEN_FUSION_PAGE_LOAD_AND_ORPHAN_RECOVERY_V4"
FUSION_PAGE = "fusion"
SOURCE_DEPENDENCY_PATHS = (
    "resolve_workspace/modules/step_3D_apply_visual_layers.py",
    POSITION_HELPER_REL,
    ANIMATION_HELPER_REL,
    IMPORT_HELPER_REL,
    POSITION_PLAN_REL,
    ANIMATION_TARGETS_REL,
    LIFECYCLE_PLAN_REL,
    FCPXML_REL,
)


def safe(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception:
        return default


def page_name(resolve: Any) -> str:
    return str(safe(resolve, "GetCurrentPage", default="") or "").strip()


def activate_fusion_page(
    resolve: Any,
    *,
    attempts: int = 50,
    poll_seconds: float = 0.1,
) -> dict[str, Any]:
    before = page_name(resolve)
    open_called = before.casefold() != FUSION_PAGE
    open_result = True
    if open_called:
        open_result = bool(safe(resolve, "OpenPage", FUSION_PAGE, default=False))

    after = page_name(resolve)
    for attempt in range(max(1, attempts)):
        if after.casefold() == FUSION_PAGE:
            break
        if attempt + 1 < attempts and poll_seconds > 0:
            time.sleep(poll_seconds)
        after = page_name(resolve)

    if after.casefold() != FUSION_PAGE:
        raise RuntimeError(
            f"fusion_page_activation:{before!r}:{after!r}:{open_result}"
        )

    return {
        "ok": True,
        "page_before": before,
        "page_after": after,
        "open_called": open_called,
        "open_result": open_result,
    }


def restore_page(resolve: Any, page: str) -> dict[str, Any]:
    requested = str(page or "").strip()
    current = page_name(resolve)
    if not requested or requested.casefold() == current.casefold():
        return {
            "ok": True,
            "requested_page": requested,
            "page_after": current,
            "open_called": False,
        }
    opened = bool(safe(resolve, "OpenPage", requested, default=False))
    after = page_name(resolve)
    return {
        "ok": opened and after.casefold() == requested.casefold(),
        "requested_page": requested,
        "page_after": after,
        "open_called": True,
        "open_result": opened,
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text_lf(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_json_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_module(
    path: Path,
    module_name: str,
    *,
    suppress_workspace_autorun: bool = False,
) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"module_spec:{path}")
    module = importlib.util.module_from_spec(spec)
    previous = os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN")
    if suppress_workspace_autorun:
        os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = "1"
    try:
        spec.loader.exec_module(module)
    finally:
        if suppress_workspace_autorun:
            if previous is None:
                os.environ.pop("VC_DISABLE_WORKSPACE_AUTORUN", None)
            else:
                os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = previous
    return module


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def timeline_name(timeline: Any) -> str:
    return str(safe(timeline, "GetName", default="") or "")


def project_timelines(project: Any) -> list[Any]:
    count = int(safe(project, "GetTimelineCount", default=0) or 0)
    rows = []
    for index in range(1, count + 1):
        timeline = safe(project, "GetTimelineByIndex", index)
        if timeline is not None:
            rows.append(timeline)
    return rows


def find_timeline(project: Any, name: str) -> Any:
    matches = [item for item in project_timelines(project) if timeline_name(item) == name]
    if len(matches) != 1:
        raise ValueError(f"timeline_identity:{name}:{len(matches)}")
    return matches[0]


def source_hash_contract(root: Path, payload: dict[str, Any]) -> dict[str, str]:
    if payload.get("source_hash_contract_version") != SOURCE_HASH_CONTRACT_VERSION:
        raise ValueError("source_hash_contract_version")
    if payload.get("source_hash_algorithm") != SOURCE_HASH_ALGORITHM:
        raise ValueError("source_hash_algorithm")

    declared = payload.get("source_hashes")
    if not isinstance(declared, dict):
        raise ValueError("source_hash_payload_type")

    expected_paths = set(SOURCE_DEPENDENCY_PATHS)
    declared_paths = set(declared)
    if declared_paths != expected_paths:
        missing = sorted(expected_paths - declared_paths)
        extra = sorted(declared_paths - expected_paths)
        raise ValueError(
            "source_hash_payload_paths:"
            + f"missing={','.join(missing)}:"
            + f"extra={','.join(extra)}"
        )

    verified: dict[str, str] = {}
    for relative in SOURCE_DEPENDENCY_PATHS:
        expected = declared.get(relative)
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError(f"source_hash_payload_digest:{relative}")
        path = root / relative
        if not path.is_file():
            raise ValueError(f"source_missing:{relative}")
        actual = sha256_text_lf(path)
        if actual != expected:
            raise ValueError(f"source_hash:{relative}")
        verified[relative] = actual
    return verified


def validate_plan_contract(
    position_plan: dict[str, Any],
    lifecycle_plan: dict[str, Any],
    animation_targets: dict[str, Any],
) -> dict[str, Any]:
    if position_plan.get("ok") is not True:
        raise ValueError("position_plan_not_ok")
    position_items = [
        row for row in (position_plan.get("items") or [])
        if isinstance(row, dict) and row.get("rollout_target") is True
    ]
    if len(position_items) != EXPECTED_CAPTION_COUNT:
        raise ValueError(f"position_item_count:{len(position_items)}")

    if lifecycle_plan.get("ok") is not True:
        raise ValueError("lifecycle_plan_not_ok")
    lifecycle_items = [row for row in (lifecycle_plan.get("layers") or []) if isinstance(row, dict)]
    if len(lifecycle_items) != EXPECTED_CAPTION_COUNT:
        raise ValueError(f"lifecycle_item_count:{len(lifecycle_items)}")
    summary = lifecycle_plan.get("summary") or {}
    if (
        summary.get("caption_layer_count") != EXPECTED_CAPTION_COUNT
        or summary.get("visual_primary_count") != 49
        or summary.get("transcript_fallback_count") != 67
        or summary.get("selected_animation_count") != EXPECTED_ANIMATION_COUNT
        or summary.get("mandatory_redetection_count") != 0
    ):
        raise ValueError("lifecycle_summary")

    if animation_targets.get("ok") is not True:
        raise ValueError("animation_targets_not_ok")
    animation_items = [row for row in (animation_targets.get("items") or []) if isinstance(row, dict)]
    if len(animation_items) != EXPECTED_ANIMATION_COUNT:
        raise ValueError(f"animation_item_count:{len(animation_items)}")
    keyframe_count = sum(len(row.get("targets") or []) for row in animation_items)
    if keyframe_count != EXPECTED_KEYFRAME_COUNT:
        raise ValueError(f"animation_keyframe_count:{keyframe_count}")

    position_by_cue = {str(row.get("cue_id") or ""): row for row in position_items}
    lifecycle_by_cue = {str(row.get("cue_id") or ""): row for row in lifecycle_items}
    animation_by_cue = {str(row.get("cue_id") or ""): row for row in animation_items}
    if "" in position_by_cue or "" in lifecycle_by_cue or "" in animation_by_cue:
        raise ValueError("blank_cue_id")
    if len(position_by_cue) != EXPECTED_CAPTION_COUNT or len(lifecycle_by_cue) != EXPECTED_CAPTION_COUNT:
        raise ValueError("duplicate_caption_cue")
    if len(animation_by_cue) != EXPECTED_ANIMATION_COUNT:
        raise ValueError("duplicate_animation_cue")
    if set(position_by_cue) != set(lifecycle_by_cue):
        raise ValueError("caption_cue_partition")
    if not set(animation_by_cue).issubset(lifecycle_by_cue):
        raise ValueError("animation_cue_partition")

    windows: set[tuple[int, int]] = set()
    for cue_id, layer in lifecycle_by_cue.items():
        window = layer.get("lifecycle_window")
        if not isinstance(window, list) or len(window) != 2:
            raise ValueError(f"lifecycle_window:{cue_id}")
        start, end = int(window[0]), int(window[1])
        if start < 0 or end <= start:
            raise ValueError(f"lifecycle_window_range:{cue_id}")
        if (start, end) in windows:
            raise ValueError(f"duplicate_lifecycle_window:{cue_id}")
        windows.add((start, end))
        if normalize_text(position_by_cue[cue_id].get("text")) != normalize_text(layer.get("text")):
            raise ValueError(f"caption_text_contract:{cue_id}")

    expected_modifier_inputs: dict[str, set[str]] = {}
    for cue_id, animation in animation_by_cue.items():
        duration = int(lifecycle_by_cue[cue_id]["lifecycle_window"][1]) - int(
            lifecycle_by_cue[cue_id]["lifecycle_window"][0]
        )
        inputs: set[str] = set()
        for target in animation.get("targets") or []:
            input_name = str(target.get("input") or "")
            local_frame = int(target.get("local_frame") or 0)
            if input_name not in {"Center", "Size"}:
                raise ValueError(f"animation_input:{cue_id}:{input_name}")
            if local_frame < 0 or local_frame >= duration:
                raise ValueError(f"animation_frame_range:{cue_id}:{local_frame}:{duration}")
            inputs.add(input_name)
        expected_modifier_inputs[cue_id] = inputs

    translated = {
        cue_id for cue_id, row in position_by_cue.items()
        if row.get("position_write_mode") == "translated_center_animation"
    }
    center_animated = {
        cue_id for cue_id, inputs in expected_modifier_inputs.items() if "Center" in inputs
    }
    if translated != center_animated or len(translated) != 4:
        raise ValueError("translated_center_partition")
    size_animated = {
        cue_id for cue_id, inputs in expected_modifier_inputs.items() if "Size" in inputs
    }
    if len(size_animated) != 4:
        raise ValueError("scale_animation_partition")

    return {
        "position_items": position_items,
        "lifecycle_items": lifecycle_items,
        "animation_items": animation_items,
        "position_by_cue": position_by_cue,
        "lifecycle_by_cue": lifecycle_by_cue,
        "animation_by_cue": animation_by_cue,
        "expected_modifier_inputs": expected_modifier_inputs,
        "summary": {
            "caption_count": EXPECTED_CAPTION_COUNT,
            "animation_count": EXPECTED_ANIMATION_COUNT,
            "keyframe_count": EXPECTED_KEYFRAME_COUNT,
            "translated_center_count": len(translated),
            "scale_animation_count": len(size_animated),
            "visual_primary_count": 49,
            "transcript_fallback_count": 67,
        },
    }


def collect_candidate_rows(
    timeline: Any,
    lifecycle_items: Iterable[dict[str, Any]],
    position_helper: Any,
) -> list[dict[str, Any]]:
    expected_windows = {
        (int(row["lifecycle_window"][0]), int(row["lifecycle_window"][1]))
        for row in lifecycle_items
    }
    rows: list[dict[str, Any]] = []
    track_count = int(safe(timeline, "GetTrackCount", "video", default=0) or 0)
    for track_index in range(1, track_count + 1):
        items = safe(timeline, "GetItemListInTrack", "video", track_index, default=[]) or []
        if isinstance(items, dict):
            items = list(items.values())
        for item in list(items):
            start = position_helper.item_start(item)
            end = position_helper.item_end(item)
            if (start, end) not in expected_windows:
                continue
            comp = position_helper.fusion_comp(item)
            tool = position_helper.textplus_tool(comp) if comp is not None else None
            text = position_helper.read_input(tool, "StyledText") if tool is not None else None
            rows.append({
                "item": item,
                "comp": comp,
                "tool": tool,
                "track_index": track_index,
                "start": start,
                "end": end,
                "text": str(text or ""),
                "name": position_helper.item_name(item),
            })
    return rows


def match_caption_rows(
    lifecycle_items: Iterable[dict[str, Any]],
    candidate_rows: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_window: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in candidate_rows:
        by_window.setdefault((int(row["start"]), int(row["end"])), []).append(row)

    matched: dict[str, dict[str, Any]] = {}
    for layer in lifecycle_items:
        cue_id = str(layer.get("cue_id") or "")
        window = (int(layer["lifecycle_window"][0]), int(layer["lifecycle_window"][1]))
        rows = by_window.get(window, [])
        if len(rows) != 1:
            raise ValueError(f"caption_window_match:{cue_id}:{window[0]}:{window[1]}:{len(rows)}")
        row = rows[0]
        if row.get("comp") is None or row.get("tool") is None:
            raise ValueError(f"caption_fusion_missing:{cue_id}")
        if normalize_text(row.get("text")) != normalize_text(layer.get("text")):
            raise ValueError(f"caption_text_match:{cue_id}:{row.get('text')!r}")
        matched[cue_id] = row
    if len(matched) != EXPECTED_CAPTION_COUNT:
        raise ValueError(f"caption_match_count:{len(matched)}")
    return matched


def source_caption_rows(
    source_timeline: Any,
    contract: dict[str, Any],
    position_helper: Any,
) -> dict[str, dict[str, Any]]:
    scanned = position_helper.scan_v3(source_timeline)
    if len(scanned) != EXPECTED_CAPTION_COUNT:
        raise ValueError(f"source_caption_count:{len(scanned)}")
    rows: dict[str, dict[str, Any]] = {}
    for name, item in scanned.items():
        match = position_helper.V3_NAME_RE.match(name)
        if match is None:
            raise ValueError(f"source_caption_name:{name}")
        cue_id = str(match.group("cue") or "")
        if cue_id in rows:
            raise ValueError(f"source_caption_duplicate:{cue_id}")
        comp = position_helper.fusion_comp(item)
        tool = position_helper.textplus_tool(comp) if comp is not None else None
        if comp is None or tool is None:
            raise ValueError(f"source_caption_fusion_missing:{cue_id}")
        text = str(position_helper.read_input(tool, "StyledText") or "")
        expected = contract["lifecycle_by_cue"].get(cue_id)
        if expected is None:
            raise ValueError(f"source_caption_unknown:{cue_id}")
        if normalize_text(text) != normalize_text(expected.get("text")):
            raise ValueError(f"source_caption_text:{cue_id}:{text!r}")
        rows[cue_id] = {
            "item": item,
            "comp": comp,
            "tool": tool,
            "name": name,
            "text": text,
        }
    if set(rows) != set(contract["lifecycle_by_cue"]):
        raise ValueError("source_caption_partition")
    return rows


def target_caption_rows_by_window(
    target_timeline: Any,
    lifecycle_items: Iterable[dict[str, Any]],
    position_helper: Any,
) -> dict[str, dict[str, Any]]:
    candidates = collect_candidate_rows(target_timeline, lifecycle_items, position_helper)
    by_window: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in candidates:
        by_window.setdefault((int(row["start"]), int(row["end"])), []).append(row)
    matched: dict[str, dict[str, Any]] = {}
    for layer in lifecycle_items:
        cue_id = str(layer.get("cue_id") or "")
        window = (int(layer["lifecycle_window"][0]), int(layer["lifecycle_window"][1]))
        rows = by_window.get(window, [])
        if len(rows) != 1:
            raise ValueError(
                f"target_caption_window:{cue_id}:{window[0]}:{window[1]}:{len(rows)}"
            )
        matched[cue_id] = rows[0]
    if len(matched) != EXPECTED_CAPTION_COUNT:
        raise ValueError(f"target_caption_count:{len(matched)}")
    return matched


def fusion_comp_names(item: Any) -> list[str]:
    values = safe(item, "GetFusionCompNameList", default=[]) or []
    return [str(value) for value in values]


def collection_values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return list(value.values())
    values = safe(value, "values", default=None)
    if values is not None:
        try:
            return list(values)
        except TypeError:
            pass
    try:
        return list(value or [])
    except TypeError:
        return []


def comp_tools(comp: Any) -> list[Any]:
    return collection_values(safe(comp, "GetToolList", False, default={}) or {})


def is_comp_handle(value: Any) -> bool:
    return value is not None and callable(getattr(value, "GetToolList", None))


def comp_by_name_or_index(item: Any, comp_name: str, fallback: Any = None) -> Any:
    if is_comp_handle(fallback):
        return fallback

    comp = safe(item, "GetFusionCompByName", comp_name, default=None)
    if is_comp_handle(comp):
        return comp

    names = fusion_comp_names(item)
    if comp_name in names:
        loaded = safe(item, "LoadFusionCompByName", comp_name, default=None)
        if is_comp_handle(loaded):
            return loaded

        comp = safe(item, "GetFusionCompByName", comp_name, default=None)
        if is_comp_handle(comp):
            return comp

        comp = safe(
            item,
            "GetFusionCompByIndex",
            names.index(comp_name) + 1,
            default=None,
        )
        if is_comp_handle(comp):
            return comp

    comp = safe(item, "GetFusionCompByIndex", 1, default=None)
    return comp if is_comp_handle(comp) else None


def wait_for_comp_handle(
    item: Any,
    comp_name: str,
    fallback: Any = None,
    *,
    attempts: int = 50,
    poll_seconds: float = 0.1,
) -> Any:
    for attempt in range(max(1, attempts)):
        comp = comp_by_name_or_index(item, comp_name, fallback)
        if comp is not None:
            return comp
        if attempt + 1 < attempts and poll_seconds > 0:
            time.sleep(poll_seconds)
    return None


def wait_for_new_comp_names(
    item: Any,
    before_names: Iterable[str],
    *,
    attempts: int = 10,
    poll_seconds: float = 0.05,
) -> tuple[list[str], list[str]]:
    before = set(str(name) for name in before_names)
    after_names = fusion_comp_names(item)
    new_names = [name for name in after_names if name not in before]
    for attempt in range(max(1, attempts)):
        if new_names:
            break
        if attempt + 1 < attempts and poll_seconds > 0:
            time.sleep(poll_seconds)
        after_names = fusion_comp_names(item)
        new_names = [name for name in after_names if name not in before]
    return after_names, new_names


def snapshot_comp_settings(comp: Any, cue_id: str) -> tuple[Any, int]:
    tools = comp_tools(comp)
    if not tools:
        return None, 0
    settings = safe(comp, "CopySettings", tools, default=None)
    if settings is None:
        raise RuntimeError(f"target_existing_comp_copy_settings:{cue_id}")
    return settings, len(tools)


def copy_comp_settings(source_comp: Any, cue_id: str) -> Any:
    tools = comp_tools(source_comp)
    if not tools:
        raise RuntimeError(f"source_comp_tools:{cue_id}:0")
    settings = safe(source_comp, "CopySettings", tools, default=None)
    if settings is None:
        raise RuntimeError(f"source_comp_copy_settings:{cue_id}")
    return settings


def replace_comp_tools_from_settings(target_comp: Any, settings: Any, cue_id: str) -> int:
    safe(target_comp, "Lock", default=None)
    try:
        existing = comp_tools(target_comp)
        for tool in existing:
            safe(tool, "Delete", default=None)
        remaining = comp_tools(target_comp)
        if remaining:
            raise RuntimeError(f"target_comp_clear:{cue_id}:{len(remaining)}")
        pasted = safe(target_comp, "Paste", settings, default=False)
        if pasted is not True:
            raise RuntimeError(f"target_comp_paste:{cue_id}")
        pasted_tools = comp_tools(target_comp)
        if not pasted_tools:
            raise RuntimeError(f"target_comp_paste_empty:{cue_id}")
        return len(pasted_tools)
    finally:
        safe(target_comp, "Unlock", default=None)


def restore_comp_tools(
    target_comp: Any,
    settings: Any,
    expected_tool_count: int,
    cue_id: str,
) -> bool:
    safe(target_comp, "Lock", default=None)
    try:
        for tool in comp_tools(target_comp):
            safe(tool, "Delete", default=None)
        if comp_tools(target_comp):
            return False
        if settings is not None:
            pasted = safe(target_comp, "Paste", settings, default=False)
            if pasted is not True:
                return False
        return len(comp_tools(target_comp)) == expected_tool_count
    finally:
        safe(target_comp, "Unlock", default=None)


def source_visual_snapshots(
    source_live: dict[str, dict[str, Any]],
    contract: dict[str, Any],
    position_helper: Any,
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for cue_id in sorted(source_live):
        position_item = contract["position_by_cue"][cue_id]
        animation_item = contract["animation_by_cue"].get(cue_id)
        targets = target_union(position_item, animation_item)
        source = source_live[cue_id]
        snap = position_helper.item_snapshot(source["item"], source["tool"], targets, 1e-5)
        identity = snap.get("identity") or {}
        snap["identity"] = {
            "text": identity.get("text"),
            "font": identity.get("font"),
            "style": identity.get("style"),
        }
        rows[cue_id] = snap
    return rows


def verify_source_visual_contract(
    source_live: dict[str, dict[str, Any]],
    contract: dict[str, Any],
    position_helper: Any,
    animation_helper: Any,
) -> dict[str, Any]:
    position_count = 0
    animation_count = 0
    keyframe_count = 0
    center_cues: list[str] = []
    size_cues: list[str] = []
    failures: list[str] = []
    for cue_id in sorted(source_live):
        row = source_live[cue_id]
        position_item = contract["position_by_cue"][cue_id]
        animation_item = contract["animation_by_cue"].get(cue_id)
        if position_helper.target_position_is_correct(row["tool"], position_item, 1e-6):
            position_count += 1
        else:
            failures.append(f"source_position:{cue_id}")
        center_connected = position_helper.connected_output(
            position_helper.find_input(row["tool"], "Center")
        ) is not None
        size_connected = position_helper.connected_output(
            position_helper.find_input(row["tool"], "Size")
        ) is not None
        if center_connected:
            center_cues.append(cue_id)
        if size_connected:
            size_cues.append(cue_id)
        expected_inputs = contract["expected_modifier_inputs"].get(cue_id, set())
        if center_connected != ("Center" in expected_inputs):
            failures.append(f"source_center_modifier:{cue_id}")
        if size_connected != ("Size" in expected_inputs):
            failures.append(f"source_size_modifier:{cue_id}")
        if animation_item is not None:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for target in animation_item.get("targets") or []:
                grouped.setdefault(str(target["input"]), []).append(target)
            ok = all(
                animation_helper.input_targets_are_correct(row["tool"], input_name, targets)
                for input_name, targets in grouped.items()
            )
            if ok:
                animation_count += 1
                keyframe_count += sum(len(targets) for targets in grouped.values())
            else:
                failures.append(f"source_animation:{cue_id}")
    if position_count != EXPECTED_CAPTION_COUNT:
        failures.append(f"source_position_count:{position_count}")
    if animation_count != EXPECTED_ANIMATION_COUNT:
        failures.append(f"source_animation_count:{animation_count}")
    if keyframe_count != EXPECTED_KEYFRAME_COUNT:
        failures.append(f"source_keyframe_count:{keyframe_count}")
    if len(center_cues) != 4:
        failures.append(f"source_center_modifier_count:{len(center_cues)}")
    if len(size_cues) != 4:
        failures.append(f"source_size_modifier_count:{len(size_cues)}")
    return {
        "ok": not failures,
        "position_verified_count": position_count,
        "animation_verified_count": animation_count,
        "keyframe_verified_count": keyframe_count,
        "center_modifier_cues": center_cues,
        "size_modifier_cues": size_cues,
        "failures": failures,
    }


def source_visual_contract_gate(source_readback: dict[str, Any]) -> dict[str, Any]:
    """Record live source readback without blocking plan-driven target reconstruction.

    The source timeline is used as the accepted Text+ style/identity donor. Positions and
    animation keyframes are reapplied from accepted Step 3B/3C plans and must pass target
    persistent readback before SaveProject. Live source position/modifier readback is
    therefore diagnostic rather than an execution gate.
    """
    failures = [str(value) for value in (source_readback.get("failures") or [])]
    return {
        "ok": True,
        "authority": "ACCEPTED_SOURCE_COMP_IDENTITY_PLUS_PLAN_DRIVEN_TARGET_READBACK",
        "live_source_readback_ok": source_readback.get("ok") is True,
        "live_source_readback_failures": failures,
        "source_caption_fusion_and_text_gate": True,
        "target_position_readback_required": EXPECTED_CAPTION_COUNT,
        "target_animation_readback_required": EXPECTED_ANIMATION_COUNT,
        "target_keyframe_readback_required": EXPECTED_KEYFRAME_COUNT,
    }


def export_source_fusion_comps(
    source_live: dict[str, dict[str, Any]],
    export_dir: Path,
) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    export_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    rows: list[dict[str, Any]] = []
    for cue_id in sorted(source_live):
        path = export_dir / f"{cue_id}.comp"
        result = safe(
            source_live[cue_id]["item"],
            "ExportFusionComp",
            str(path),
            1,
            default=False,
        )
        if result is not True or not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"source_comp_export:{cue_id}")
        paths[cue_id] = path
        rows.append({
            "cue_id": cue_id,
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    return paths, rows


def clone_fusion_comps(
    target_live: dict[str, dict[str, Any]],
    source_live: dict[str, dict[str, Any]],
    export_paths: dict[str, Path],
    position_helper: Any,
    *,
    rollback_records: list[dict[str, Any]] | None = None,
    mutation_state: dict[str, bool] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    rollback = rollback_records if rollback_records is not None else []
    state = mutation_state if mutation_state is not None else {}
    state.setdefault("started", False)
    imported_count = 0
    already_present_count = 0
    direct_import_count = 0
    add_copy_settings_count = 0
    recovered_blank_count = 0

    def emit(cue_id: str, stage: str, error: str | None = None) -> None:
        if progress_callback is None:
            return
        progress_callback({
            "ok": error is None,
            "clone_strategy": CLONE_STRATEGY,
            "cue_id": cue_id,
            "stage": stage,
            "error": error,
            "completed_count": len(results),
            "mutation_started": bool(state["started"]),
            "rollback_record_count": len(rollback),
            "items": list(results),
        })

    for cue_id in sorted(target_live):
        emit(cue_id, "start")
        try:
            row = target_live[cue_id]
            item = row["item"]
            before_names = fusion_comp_names(item)
            if len(before_names) > 1:
                raise ValueError(
                    f"target_unexpected_fusion_comp:{cue_id}:{len(before_names)}"
                )

            comp = None
            tool = None
            if len(before_names) == 1:
                comp = wait_for_comp_handle(item, before_names[0])
                if comp is None:
                    raise RuntimeError(f"target_existing_comp_handle:{cue_id}")
                tool = position_helper.textplus_tool(comp)

            if comp is not None and tool is not None:
                text = str(position_helper.read_input(tool, "StyledText") or "")
                if normalize_text(text) != normalize_text(source_live[cue_id]["text"]):
                    raise ValueError(f"target_existing_comp_text:{cue_id}:{text!r}")
                row.update({"comp": comp, "tool": tool, "text": text})
                already_present_count += 1
                results.append({
                    "cue_id": cue_id,
                    "status": "already_present",
                    "clone_method": "existing",
                    "before_comp_names": before_names,
                    "after_comp_names": before_names,
                })
                emit(cue_id, "completed")
                continue

            source_comp = source_live[cue_id].get("comp")
            settings = None
            clone_method = ""
            pasted_tool_count: int | None = None
            new_names: list[str] = []
            after_names = list(before_names)

            if len(before_names) == 1:
                if source_comp is None:
                    raise RuntimeError(f"source_comp_missing:{cue_id}")
                settings = copy_comp_settings(source_comp, cue_id)
                original_settings, original_tool_count = snapshot_comp_settings(comp, cue_id)
                state["started"] = True
                rollback.append({
                    "action": "restore_settings",
                    "cue_id": cue_id,
                    "item": item,
                    "comp_name": before_names[0],
                    "settings": original_settings,
                    "expected_tool_count": original_tool_count,
                })
                emit(cue_id, "recover_existing_blank_registered")
                pasted_tool_count = replace_comp_tools_from_settings(
                    comp, settings, cue_id
                )
                clone_method = "recover_existing_blank_comp_copy_settings"
                recovered_blank_count += 1
                new_names = [before_names[0]]
            else:
                imported = safe(
                    item,
                    "ImportFusionComp",
                    str(export_paths[cue_id]),
                    default=None,
                )
                after_names, new_names = wait_for_new_comp_names(item, before_names)
                clone_method = "import_fusion_comp"

                if len(new_names) == 1:
                    state["started"] = True
                    rollback.append({
                        "action": "delete_comp",
                        "cue_id": cue_id,
                        "item": item,
                        "comp_name": new_names[0],
                    })
                    emit(cue_id, "direct_import_registered")
                    comp = wait_for_comp_handle(item, new_names[0], imported)
                    if comp is None:
                        raise RuntimeError(f"target_comp_import_handle:{cue_id}")
                    direct_import_count += 1
                elif len(new_names) == 0:
                    if source_comp is None:
                        raise RuntimeError(f"source_comp_missing:{cue_id}")
                    settings = copy_comp_settings(source_comp, cue_id)
                    created = safe(item, "AddFusionComp", default=None)
                    after_names, new_names = wait_for_new_comp_names(item, before_names)
                    if len(new_names) != 1:
                        raise RuntimeError(
                            f"target_comp_add:{cue_id}:{len(before_names)}:{len(after_names)}"
                        )
                    state["started"] = True
                    rollback.append({
                        "action": "delete_comp",
                        "cue_id": cue_id,
                        "item": item,
                        "comp_name": new_names[0],
                    })
                    emit(cue_id, "add_fusion_comp_registered")
                    comp = wait_for_comp_handle(item, new_names[0], created)
                    if comp is None:
                        raise RuntimeError(f"target_comp_add_handle:{cue_id}")
                    pasted_tool_count = replace_comp_tools_from_settings(
                        comp, settings, cue_id
                    )
                    clone_method = "add_fusion_comp_copy_settings"
                    add_copy_settings_count += 1
                else:
                    raise RuntimeError(
                        f"target_comp_import_count:{cue_id}:{len(before_names)}:{len(after_names)}"
                    )

            tool = position_helper.textplus_tool(comp) if comp is not None else None
            if tool is None:
                comp = position_helper.fusion_comp(item)
                tool = position_helper.textplus_tool(comp) if comp is not None else None
            if comp is None or tool is None:
                raise RuntimeError(f"target_comp_textplus:{cue_id}")
            text = str(position_helper.read_input(tool, "StyledText") or "")
            if normalize_text(text) != normalize_text(source_live[cue_id]["text"]):
                raise ValueError(f"target_imported_comp_text:{cue_id}:{text!r}")
            row.update({"comp": comp, "tool": tool, "text": text})
            imported_count += 1
            results.append({
                "cue_id": cue_id,
                "status": "imported",
                "clone_method": clone_method,
                "before_comp_names": before_names,
                "after_comp_names": after_names,
                "imported_comp_name": new_names[0],
                "pasted_tool_count": pasted_tool_count,
                "source_comp_sha256": sha256(export_paths[cue_id]),
            })
            emit(cue_id, "completed")
        except Exception as exc:
            emit(cue_id, "failed", f"{type(exc).__name__}: {exc}")
            raise

    return {
        "ok": True,
        "clone_strategy": CLONE_STRATEGY,
        "caption_count": len(results),
        "imported_count": imported_count,
        "already_present_count": already_present_count,
        "direct_import_count": direct_import_count,
        "add_copy_settings_count": add_copy_settings_count,
        "recovered_blank_count": recovered_blank_count,
        "items": results,
    }, rollback


def rollback_fusion_clones(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for record in reversed(list(records)):
        cue_id = str(record["cue_id"])
        item = record["item"]
        comp_name = str(record["comp_name"])
        action = str(record.get("action") or "delete_comp")

        if action == "delete_comp":
            deleted = bool(safe(item, "DeleteFusionCompByName", comp_name, default=False))
            names_after = fusion_comp_names(item)
            ok = deleted and comp_name not in names_after
            row = {
                "cue_id": cue_id,
                "action": action,
                "comp_name": comp_name,
                "deleted": deleted,
                "names_after": names_after,
                "ok": ok,
            }
        elif action == "restore_settings":
            comp = wait_for_comp_handle(item, comp_name)
            restored = comp is not None and restore_comp_tools(
                comp,
                record.get("settings"),
                int(record.get("expected_tool_count") or 0),
                cue_id,
            )
            names_after = fusion_comp_names(item)
            ok = bool(restored and comp_name in names_after)
            row = {
                "cue_id": cue_id,
                "action": action,
                "comp_name": comp_name,
                "restored": bool(restored),
                "names_after": names_after,
                "ok": ok,
            }
        else:
            ok = False
            row = {
                "cue_id": cue_id,
                "action": action,
                "comp_name": comp_name,
                "ok": False,
            }

        if not ok:
            failures.append(f"rollback_comp:{cue_id}:{comp_name}:{action}")
        rows.append(row)
    return {"ok": not failures, "items": rows, "failures": failures}


def target_union(
    position_item: dict[str, Any],
    animation_item: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for sources in (
        position_item.get("expected_animation_targets_after") or [],
        (animation_item or {}).get("targets") or [],
    ):
        if not isinstance(sources, list):
            raise ValueError("animation_target_group_type")
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("animation_target_type")
            key = (str(source.get("input") or ""), int(source.get("local_frame") or 0))
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(source))
    return rows


def snapshot_items(
    live: dict[str, dict[str, Any]],
    contract: dict[str, Any],
    position_helper: Any,
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for cue_id in sorted(live):
        position_item = contract["position_by_cue"][cue_id]
        animation_item = contract["animation_by_cue"].get(cue_id)
        targets = target_union(position_item, animation_item)
        row = live[cue_id]
        snap = position_helper.item_snapshot(row["item"], row["tool"], targets, 1e-5)
        snap["cue_id"] = cue_id
        snap["track_index"] = row["track_index"]
        rows[cue_id] = snap
    return rows


def apply_animation_items(
    live: dict[str, dict[str, Any]],
    animation_items: Iterable[dict[str, Any]],
    animation_helper: Any,
) -> dict[str, Any]:
    results = []
    modified_count = 0
    already_correct_count = 0
    keyframes_written = 0
    for item in animation_items:
        cue_id = str(item["cue_id"])
        row = live[cue_id]
        comp = row["comp"]
        tool = row["tool"]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for target in item.get("targets") or []:
            grouped.setdefault(str(target["input"]), []).append(target)
        already_correct = all(
            animation_helper.input_targets_are_correct(tool, input_name, targets)
            for input_name, targets in grouped.items()
        )
        result = {
            "cue_id": cue_id,
            "animation_type": item.get("animation_type"),
            "already_correct_before": already_correct,
            "targets": [],
            "modifiers": {},
        }
        if already_correct:
            already_correct_count += 1
            result["ok"] = True
            results.append(result)
            continue

        safe(comp, "Lock", default=None)
        try:
            for input_name, targets in grouped.items():
                modifier = animation_helper.ensure_modifier(comp, tool, input_name)
                result["modifiers"][input_name] = modifier
                if modifier.get("ok") is not True:
                    raise RuntimeError(f"modifier_apply:{cue_id}:{input_name}")
                for target in sorted(targets, key=lambda value: int(value["local_frame"])):
                    write = animation_helper.write_key(
                        tool,
                        input_name,
                        int(target["local_frame"]),
                        target["expected"],
                    )
                    result["targets"].append({**target, "write": write})
                    if write.get("ok") is not True:
                        raise RuntimeError(
                            f"animation_write:{cue_id}:{input_name}:{target['local_frame']}"
                        )
                    keyframes_written += 1
        finally:
            safe(comp, "Unlock", default=None)
        modified_count += 1
        result["ok"] = True
        results.append(result)

    return {
        "ok": True,
        "selected_animation_count": len(results),
        "modified_count": modified_count,
        "already_correct_count": already_correct_count,
        "keyframes_written_count": keyframes_written,
        "items": results,
    }


def apply_position_items(
    live: dict[str, dict[str, Any]],
    position_items: Iterable[dict[str, Any]],
    position_helper: Any,
) -> dict[str, Any]:
    results = []
    modified_count = 0
    already_correct_count = 0
    for item in position_items:
        cue_id = str(item["cue_id"])
        row = live[cue_id]
        already_correct = position_helper.target_position_is_correct(row["tool"], item, 1e-6)
        if already_correct:
            write = {"ok": True, "write_mode": "not_required_already_correct"}
            already_correct_count += 1
        else:
            write = position_helper.write_position(row["comp"], row["tool"], item, 1e-6)
            if write.get("ok") is not True:
                raise RuntimeError(f"position_write:{cue_id}")
            modified_count += 1
        results.append({
            "cue_id": cue_id,
            "position_write_mode": item.get("position_write_mode"),
            "target_center": item.get("target_center"),
            "already_correct_before": already_correct,
            "modified": not already_correct,
            "write": write,
        })
    return {
        "ok": True,
        "position_count": len(results),
        "modified_count": modified_count,
        "already_correct_count": already_correct_count,
        "items": results,
    }


def verify_readback(
    live: dict[str, dict[str, Any]],
    contract: dict[str, Any],
    source_snapshots: dict[str, Any],
    position_helper: Any,
    animation_helper: Any,
) -> dict[str, Any]:
    position_verified = 0
    animation_item_verified = 0
    keyframe_verified = 0
    identity_verified = 0
    style_verified = 0
    layout_verified = 0
    static_size_verified = 0
    center_modifier_cues: list[str] = []
    size_modifier_cues: list[str] = []
    failures: list[str] = []
    items: list[dict[str, Any]] = []

    for cue_id in sorted(live):
        row = live[cue_id]
        position_item = contract["position_by_cue"][cue_id]
        animation_item = contract["animation_by_cue"].get(cue_id)
        targets = target_union(position_item, animation_item)
        after = position_helper.item_snapshot(row["item"], row["tool"], targets, 1e-5)
        before = source_snapshots[cue_id]

        position_ok = position_helper.target_position_is_correct(row["tool"], position_item, 1e-6)
        if position_ok:
            position_verified += 1
        else:
            failures.append(f"position_readback:{cue_id}")

        after_identity = after.get("identity") or {}
        protected_identity = {
            "text": after_identity.get("text"),
            "font": after_identity.get("font"),
            "style": after_identity.get("style"),
        }
        identity_ok = position_helper.snapshots_match(
            protected_identity, before["identity"], 1e-6
        )
        if identity_ok:
            identity_verified += 1
        else:
            failures.append(f"identity_changed:{cue_id}")

        fill_ok = position_helper.snapshots_match(after["fill"], before["fill"], 1e-6)
        shading_ok = position_helper.snapshots_match(after["shading"], before["shading"], 1e-6)
        if fill_ok and shading_ok:
            style_verified += 1
        else:
            failures.append(f"style_changed:{cue_id}")

        layout_ok = position_helper.snapshots_match(
            after["layout_without_center"], before["layout_without_center"], 1e-6
        )
        if layout_ok:
            layout_verified += 1
        else:
            failures.append(f"layout_changed:{cue_id}")

        expected_inputs = contract["expected_modifier_inputs"].get(cue_id, set())
        center_connected = position_helper.connected_output(
            position_helper.find_input(row["tool"], "Center")
        ) is not None
        size_connected = position_helper.connected_output(
            position_helper.find_input(row["tool"], "Size")
        ) is not None
        if center_connected:
            center_modifier_cues.append(cue_id)
        if size_connected:
            size_modifier_cues.append(cue_id)
        if center_connected != ("Center" in expected_inputs):
            failures.append(f"center_modifier_partition:{cue_id}")
        if size_connected != ("Size" in expected_inputs):
            failures.append(f"size_modifier_partition:{cue_id}")

        if "Size" not in expected_inputs:
            if position_helper.snapshots_match(after["size"], before["size"], 1e-6):
                static_size_verified += 1
            else:
                failures.append(f"static_size_changed:{cue_id}")

        animation_ok = True
        verified_targets = []
        if animation_item is not None:
            for target in animation_item.get("targets") or []:
                input_name = str(target["input"])
                frame = int(target["local_frame"])
                input_object = animation_helper.find_input(row["tool"], input_name)
                connected = animation_helper.connected_output(input_object) is not None
                actual = animation_helper.read_input(row["tool"], input_name, frame)
                matched = animation_helper.values_match(input_name, actual, target["expected"])
                present = connected and matched
                verified_targets.append({
                    **target,
                    "actual": animation_helper.normalize_value(input_name, actual),
                    "modifier_connected": connected,
                    "matched": matched,
                    "present": present,
                })
                if present:
                    keyframe_verified += 1
                else:
                    animation_ok = False
                    failures.append(f"animation_readback:{cue_id}:{input_name}:{frame}")
            if animation_ok:
                animation_item_verified += 1

        items.append({
            "cue_id": cue_id,
            "position_ok": position_ok,
            "identity_ok": identity_ok,
            "style_ok": fill_ok and shading_ok,
            "layout_ok": layout_ok,
            "center_modifier_connected": center_connected,
            "size_modifier_connected": size_connected,
            "animation_ok": animation_ok if animation_item is not None else None,
            "targets": verified_targets,
        })

    if position_verified != EXPECTED_CAPTION_COUNT:
        failures.append(f"position_verified_count:{position_verified}")
    if animation_item_verified != EXPECTED_ANIMATION_COUNT:
        failures.append(f"animation_verified_count:{animation_item_verified}")
    if keyframe_verified != EXPECTED_KEYFRAME_COUNT:
        failures.append(f"keyframe_verified_count:{keyframe_verified}")
    if len(center_modifier_cues) != 4:
        failures.append(f"center_modifier_count:{len(center_modifier_cues)}")
    if len(size_modifier_cues) != 4:
        failures.append(f"size_modifier_count:{len(size_modifier_cues)}")
    if identity_verified != EXPECTED_CAPTION_COUNT:
        failures.append(f"identity_verified_count:{identity_verified}")
    if style_verified != EXPECTED_CAPTION_COUNT:
        failures.append(f"style_verified_count:{style_verified}")
    if layout_verified != EXPECTED_CAPTION_COUNT:
        failures.append(f"layout_verified_count:{layout_verified}")
    if static_size_verified != EXPECTED_CAPTION_COUNT - 4:
        failures.append(f"static_size_verified_count:{static_size_verified}")

    return {
        "ok": not failures,
        "position_verified_count": position_verified,
        "animation_verified_count": animation_item_verified,
        "keyframe_verified_count": keyframe_verified,
        "identity_verified_count": identity_verified,
        "style_verified_count": style_verified,
        "layout_verified_count": layout_verified,
        "static_size_verified_count": static_size_verified,
        "center_modifier_cues": center_modifier_cues,
        "size_modifier_cues": size_modifier_cues,
        "items": items,
        "failures": failures,
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "classification": None,
        "target_timeline_modified": False,
        "source_timeline_modified": None,
        "timeline_created": False,
        "save_call_count": 0,
        "rollback_save_call_count": 0,
        "failures": [],
    }
    mutation_started = False
    manager = None
    output_dir: Path | None = None
    rollback_records: list[dict[str, Any]] = []
    temp_export_dir: Path | None = None
    page_before = ""
    page_activation: dict[str, Any] | None = None
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if (
            command.get("task") != TASK_ID
            or command.get("run_id") != run_id
            or command.get("mode") != MODE
        ):
            raise ValueError("command_identity")
        if payload.get("apply_permitted") is not True:
            raise ValueError("apply_not_authorized")
        if payload.get("create_timeline") is not False or payload.get("delete_timeline") is not False:
            raise ValueError("timeline_creation_contract")
        if payload.get("save_project") is not True:
            raise ValueError("save_contract")
        if payload.get("clone_source_fusion_comps") is not True:
            raise ValueError("fusion_clone_contract")
        if payload.get("activate_fusion_page") is not True:
            raise ValueError("fusion_page_contract")
        if payload.get("clone_strategy") != CLONE_STRATEGY:
            raise ValueError("fusion_clone_strategy")

        root = Path(str(payload.get("repository_root") or "")).resolve()
        output_dir = root / str(payload.get("report_dir") or "")
        output_dir.mkdir(parents=True, exist_ok=True)
        source_hashes = source_hash_contract(root, payload)

        position_helper = load_module(
            root / POSITION_HELPER_REL,
            "vc_step3b_position_helper",
            suppress_workspace_autorun=True,
        )
        animation_helper = load_module(
            root / ANIMATION_HELPER_REL,
            "vc_step3c_animation_helper",
            suppress_workspace_autorun=True,
        )
        import_helper = load_module(root / IMPORT_HELPER_REL, "vc_step3d_import_helper")
        position_plan = load_json(root / POSITION_PLAN_REL)
        lifecycle_plan = load_json(root / LIFECYCLE_PLAN_REL)
        animation_targets = load_json(root / ANIMATION_TARGETS_REL)
        contract = validate_plan_contract(position_plan, lifecycle_plan, animation_targets)

        manager = safe(resolve, "GetProjectManager")
        project = safe(manager, "GetCurrentProject")
        if project is None or str(safe(project, "GetName", default="") or "") != EXPECTED_PROJECT:
            raise ValueError("project_identity")

        source_timeline = find_timeline(project, SOURCE_TIMELINE_NAME)
        target_timeline = find_timeline(project, TARGET_TIMELINE_NAME)
        timeline_names_before = [timeline_name(item) for item in project_timelines(project)]
        source_before = import_helper.timeline_snapshot(source_timeline)
        target_structure_before = import_helper.validate_imported_timeline(
            target_timeline, root / FCPXML_REL
        )
        if (
            target_structure_before.get("caption_item_count") != EXPECTED_CAPTION_COUNT
            or target_structure_before.get("caption_lane_count") != EXPECTED_CAPTION_LANE_COUNT
            or target_structure_before.get("base_video_item_count") != EXPECTED_BASE_CLIP_COUNT
            or target_structure_before.get("transition_item_count") != EXPECTED_TRANSITION_COUNT
            or target_structure_before.get("unmatched_video_item_count") != 0
        ):
            raise ValueError("target_timeline_structure")

        if not safe(project, "SetCurrentTimeline", target_timeline, default=False):
            if timeline_name(safe(project, "GetCurrentTimeline")) != TARGET_TIMELINE_NAME:
                raise ValueError("target_timeline_selection")

        source_live = source_caption_rows(source_timeline, contract, position_helper)
        source_readback = verify_source_visual_contract(
            source_live, contract, position_helper, animation_helper
        )
        source_visual_gate = source_visual_contract_gate(source_readback)
        source_snapshots = source_visual_snapshots(source_live, contract, position_helper)

        target_live = target_caption_rows_by_window(
            target_timeline, contract["lifecycle_items"], position_helper
        )
        target_comp_counts = {
            cue_id: len(fusion_comp_names(row["item"])) for cue_id, row in target_live.items()
        }
        invalid_target_counts = {
            cue_id: count for cue_id, count in target_comp_counts.items() if count not in {0, 1}
        }
        if invalid_target_counts:
            raise ValueError("target_comp_count_contract")

        preflight = {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            "project_name": EXPECTED_PROJECT,
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "target_timeline_selected": timeline_name(safe(project, "GetCurrentTimeline"))
            == TARGET_TIMELINE_NAME,
            "source_hash_contract_version": SOURCE_HASH_CONTRACT_VERSION,
            "source_hash_algorithm": SOURCE_HASH_ALGORITHM,
            "source_hashes": source_hashes,
            "source_dependency_count": len(SOURCE_DEPENDENCY_PATHS),
            "clone_strategy": CLONE_STRATEGY,
            "plan_summary": contract["summary"],
            "target_structure": target_structure_before,
            "source_caption_count": len(source_live),
            "target_caption_count": len(target_live),
            "target_zero_comp_count": sum(1 for count in target_comp_counts.values() if count == 0),
            "target_existing_comp_count": sum(1 for count in target_comp_counts.values() if count == 1),
            "source_visual_readback": source_readback,
            "source_visual_contract_gate": source_visual_gate,
            "writes_attempted": False,
        }
        write_json(output_dir / "visual_layer_preflight.json", preflight)

        temp_export_dir = Path(tempfile.mkdtemp(prefix="vc_step3d_comp_clone_", dir=str(output_dir)))
        export_paths, export_rows = export_source_fusion_comps(source_live, temp_export_dir)
        export_result = {
            "ok": True,
            "caption_count": len(export_rows),
            "files": export_rows,
        }
        write_json(output_dir / "source_fusion_comp_exports.json", export_result)

        page_before = page_name(resolve)
        page_activation = activate_fusion_page(resolve)
        target_timeline = find_timeline(project, TARGET_TIMELINE_NAME)
        if not safe(project, "SetCurrentTimeline", target_timeline, default=False):
            if timeline_name(safe(project, "GetCurrentTimeline")) != TARGET_TIMELINE_NAME:
                raise ValueError("target_timeline_selection_after_fusion_page")
        target_live = target_caption_rows_by_window(
            target_timeline, contract["lifecycle_items"], position_helper
        )
        page_activation["target_timeline_name"] = TARGET_TIMELINE_NAME
        page_activation["target_timeline_selected"] = (
            timeline_name(safe(project, "GetCurrentTimeline")) == TARGET_TIMELINE_NAME
        )
        page_activation["target_caption_count_after_activation"] = len(target_live)
        page_activation["target_existing_comp_count_after_activation"] = sum(
            1 for row in target_live.values() if len(fusion_comp_names(row["item"])) == 1
        )
        write_json(output_dir / "fusion_page_activation.json", page_activation)

        clone_mutation_state = {"started": False}

        def write_clone_progress(value: dict[str, Any]) -> None:
            write_json(output_dir / "fusion_comp_clone_progress.json", value)

        try:
            clone_application, rollback_records = clone_fusion_comps(
                target_live,
                source_live,
                export_paths,
                position_helper,
                rollback_records=rollback_records,
                mutation_state=clone_mutation_state,
                progress_callback=write_clone_progress,
            )
        finally:
            mutation_started = clone_mutation_state["started"]
        write_json(output_dir / "fusion_comp_clone_application.json", clone_application)

        animation_application = apply_animation_items(
            target_live, contract["animation_items"], animation_helper
        )
        position_application = apply_position_items(
            target_live, contract["position_items"], position_helper
        )
        report["target_timeline_modified"] = bool(
            clone_application["imported_count"]
            or animation_application["modified_count"]
            or position_application["modified_count"]
        )
        write_json(output_dir / "animation_application.json", animation_application)
        write_json(output_dir / "position_application.json", position_application)

        save_result = safe(manager, "SaveProject", default=False)
        report["save_call_count"] = 1
        if save_result is False:
            raise RuntimeError("project_save_failed")
        time.sleep(1.0)

        target_timeline_after = find_timeline(project, TARGET_TIMELINE_NAME)
        if not safe(project, "SetCurrentTimeline", target_timeline_after, default=False):
            if timeline_name(safe(project, "GetCurrentTimeline")) != TARGET_TIMELINE_NAME:
                raise ValueError("target_timeline_reselection")
        target_live_after = target_caption_rows_by_window(
            target_timeline_after, contract["lifecycle_items"], position_helper
        )
        live_after = match_caption_rows(contract["lifecycle_items"], target_live_after.values())
        readback = verify_readback(
            live_after,
            contract,
            source_snapshots,
            position_helper,
            animation_helper,
        )
        write_json(output_dir / "visual_layer_readback.json", readback)
        if readback.get("ok") is not True:
            raise RuntimeError("visual_layer_readback_failed")

        target_structure_after = import_helper.validate_imported_timeline(
            target_timeline_after, root / FCPXML_REL
        )
        for key, expected in (
            ("caption_item_count", EXPECTED_CAPTION_COUNT),
            ("caption_lane_count", EXPECTED_CAPTION_LANE_COUNT),
            ("base_video_item_count", EXPECTED_BASE_CLIP_COUNT),
            ("transition_item_count", EXPECTED_TRANSITION_COUNT),
            ("unmatched_video_item_count", 0),
        ):
            if target_structure_after.get(key) != expected:
                raise ValueError(f"target_structure_after:{key}")

        source_after = import_helper.timeline_snapshot(find_timeline(project, SOURCE_TIMELINE_NAME))
        source_unchanged = source_after == source_before
        if not source_unchanged:
            raise ValueError("source_timeline_changed")
        timeline_names_after = [timeline_name(item) for item in project_timelines(project)]
        if timeline_names_after != timeline_names_before:
            raise ValueError("timeline_inventory_changed")
        if timeline_name(safe(project, "GetCurrentTimeline")) != TARGET_TIMELINE_NAME:
            raise ValueError("current_timeline_changed")

        accepted_path = root / ".agent/state/latest_accepted.json"
        accepted_hash = sha256(accepted_path)
        if accepted_hash != payload.get("accepted_state_sha256"):
            raise ValueError("accepted_state_changed")

        protection = {
            "ok": True,
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "source_timeline_unchanged": True,
            "source_before": source_before,
            "source_after": source_after,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "target_structure_before": target_structure_before,
            "target_structure_after": target_structure_after,
            "timeline_names_before": timeline_names_before,
            "timeline_names_after": timeline_names_after,
            "timeline_created": False,
            "timeline_deleted": False,
            "accepted_state_sha256_before": payload.get("accepted_state_sha256"),
            "accepted_state_sha256_after": accepted_hash,
            "save_call_count": 1,
        }
        write_json(output_dir / "source_timeline_protection.json", protection)

        result = {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            "classification": "SOURCE_FUSION_COMPS_CLONED_TO_LIFECYCLE_TIMELINE",
            "clone_strategy": CLONE_STRATEGY,
            "fusion_page_activated": bool(
                page_activation and page_activation.get("ok") is True
            ),
            "fusion_page_before": page_activation.get("page_before")
            if page_activation
            else None,
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "current_timeline_name": timeline_name(safe(project, "GetCurrentTimeline")),
            "caption_count": EXPECTED_CAPTION_COUNT,
            "caption_lane_count": EXPECTED_CAPTION_LANE_COUNT,
            "fusion_comp_imported_count": clone_application["imported_count"],
            "fusion_comp_already_present_count": clone_application["already_present_count"],
            "fusion_comp_direct_import_count": clone_application["direct_import_count"],
            "fusion_comp_add_copy_settings_count": clone_application[
                "add_copy_settings_count"
            ],
            "fusion_comp_recovered_blank_count": clone_application[
                "recovered_blank_count"
            ],
            "position_verified_count": readback["position_verified_count"],
            "animation_verified_count": readback["animation_verified_count"],
            "keyframe_verified_count": readback["keyframe_verified_count"],
            "center_modifier_count": len(readback["center_modifier_cues"]),
            "size_modifier_count": len(readback["size_modifier_cues"]),
            "position_modified_count": position_application["modified_count"],
            "animation_modified_count": animation_application["modified_count"],
            "source_timeline_modified": False,
            "target_timeline_modified": report["target_timeline_modified"],
            "timeline_created": False,
            "save_call_count": 1,
            "accepted_state_changed": False,
            "visual_approval_required": True,
            "next_boundary": "Play the lifecycle timeline and visually compare cloned Text+ positions and animations with the source video.",
        }
        write_json(output_dir / "visual_layer_application_result.json", result)
        report.update(result)
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
        report["mutation_started"] = mutation_started
        if mutation_started and rollback_records:
            rollback = rollback_fusion_clones(rollback_records)
            report["rollback"] = rollback
            if output_dir is not None:
                write_json(output_dir / "fusion_comp_clone_rollback.json", rollback)
            rollback_saved = bool(safe(manager, "SaveProject", default=False)) if manager is not None else False
            report["rollback_save_call_count"] = 1 if manager is not None else 0
            report["rollback_saved"] = rollback_saved
            if rollback.get("ok") is True and rollback_saved:
                report["target_timeline_modified"] = False
                report["target_timeline_state"] = "ROLLED_BACK_TO_PRE_RUN_STATE"
            else:
                report["target_timeline_state"] = "MUTATED_STATE_REQUIRES_REVIEW"
        elif mutation_started:
            report["target_timeline_state"] = "MUTATED_STATE_REQUIRES_REVIEW"
    finally:
        if page_activation is not None:
            page_restore = restore_page(resolve, page_before)
            report["page_restore"] = page_restore
            if output_dir is not None:
                try:
                    write_json(output_dir / "fusion_page_restore.json", page_restore)
                except Exception as restore_artifact_error:
                    report["page_restore_artifact_error"] = (
                        f"{type(restore_artifact_error).__name__}: {restore_artifact_error}"
                    )
        if temp_export_dir is not None:
            shutil.rmtree(temp_export_dir, ignore_errors=True)
    return report
