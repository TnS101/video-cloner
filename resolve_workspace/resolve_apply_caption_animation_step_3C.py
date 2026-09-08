#!/usr/bin/env python3
"""
Video Cloner — Major Step 3C Resolve Workspace applier v1.2

Fixes the Step 3C v1.0 failure where SetInput(name, value, frame)
changed evaluated values but did not create persistent Fusion keyframes.

Persistent animation implementation:
- Text+ Size   -> BezierSpline
- Text+ Center -> Path
- Temporal value readback after project save
- Connected-modifier verification
- First-run and second-run idempotency reporting
- Immutable mode-specific report snapshots so a second run cannot
  overwrite the first-application proof.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


WORKSPACE_VERSION = (
    "resolve_caption_animation_step_3C_v1_2_"
    "persistent_modifier_keyframes_archived_reports"
)

PROJECT_ROOT = Path(
    r"C:\Users\User\Downloads\Projects\Video Cloner"
)
VIDEO_ID = "DZsqH7auhjt"

DATA_ROOT = PROJECT_ROOT / "data" / VIDEO_ID
ANALYSIS_ROOT = DATA_ROOT / "analysis"
DAVINCI_ROOT = DATA_ROOT / "davinci"

PLAN_PATH = (
    ANALYSIS_ROOT
    / f"{VIDEO_ID}_caption_animation_plan_step_3C.json"
)

REPORT_PATH = (
    DAVINCI_ROOT
    / f"{VIDEO_ID}_resolve_animation_step_3C_report.json"
)

FIRST_REPORT_PATH = (
    DAVINCI_ROOT
    / f"{VIDEO_ID}_resolve_animation_step_3C_first_application_report.json"
)

IDEMPOTENCY_REPORT_PATH = (
    DAVINCI_ROOT
    / f"{VIDEO_ID}_resolve_animation_step_3C_idempotency_report.json"
)

STATE_PATH = (
    DAVINCI_ROOT
    / f"{VIDEO_ID}_resolve_animation_step_3C_state.json"
)

SOURCE_TARGETS_PATH = (
    ANALYSIS_ROOT
    / f"{VIDEO_ID}_caption_animation_step_3C_source_targets.json"
)

EXPECTED_V3_COUNT = 116

V3_NAME_RE = re.compile(
    r"^VC_TEXTPLUS_(?P<index>\d+)_(?P<cue>sub_\d+)$",
    re.IGNORECASE,
)


def show_message(
    title: str,
    message: str,
    error: bool = False,
) -> None:
    try:
        icon = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            title,
            icon,
        )
    except Exception:
        print(title)
        print(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")

    temporary.replace(path)


def walk_nodes(root: Any) -> Iterable[Any]:
    stack = [root]

    while stack:
        node = stack.pop()
        yield node

        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def as_int(value: Any) -> Optional[int]:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(result):
        return None

    return result


def first_value(
    node: Dict[str, Any],
    names: Sequence[str],
) -> Any:
    for name in names:
        if name in node and node[name] is not None:
            return node[name]

    return None


def normalize_point(value: Any) -> Optional[List[float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x = as_float(value[0])
        y = as_float(value[1])

        if x is not None and y is not None:
            return [x, y]

    if isinstance(value, dict):
        x = first_value(
            value,
            (1, "1", "x", "X"),
        )
        y = first_value(
            value,
            (2, "2", "y", "Y"),
        )

        x_float = as_float(x)
        y_float = as_float(y)

        if x_float is not None and y_float is not None:
            return [x_float, y_float]

    return None


def normalize_value(
    input_name: str,
    value: Any,
) -> Any:
    if input_name == "Center":
        return normalize_point(value)

    return as_float(value)


def values_match(
    input_name: str,
    actual: Any,
    expected: Any,
    tolerance: float = 1e-5,
) -> bool:
    expected_normalized = normalize_value(
        input_name,
        expected,
    )
    actual_normalized = normalize_value(
        input_name,
        actual,
    )

    if expected_normalized is None:
        return False

    if actual_normalized is None:
        return False

    if input_name == "Center":
        return (
            abs(
                actual_normalized[0]
                - expected_normalized[0]
            )
            <= tolerance
            and abs(
                actual_normalized[1]
                - expected_normalized[1]
            )
            <= tolerance
        )

    return (
        abs(actual_normalized - expected_normalized)
        <= tolerance
    )


def clean_target(
    target: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    input_name = str(
        target.get("input")
        or target.get("input_name")
        or ""
    ).strip()

    if input_name not in {"Size", "Center"}:
        return None

    frame = as_int(
        first_value(
            target,
            (
                "local_frame",
                "frame",
                "target_frame",
                "relative_frame",
            ),
        )
    )

    expected = first_value(
        target,
        (
            "expected",
            "value",
            "target_value",
            "resolved_value",
        ),
    )

    normalized = normalize_value(
        input_name,
        expected,
    )

    if frame is None or normalized is None:
        return None

    return {
        "input": input_name,
        "local_frame": frame,
        "frame": frame,
        "expected": normalized,
    }


def clean_source_item(
    item: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    name = str(
        item.get("name")
        or item.get("item_name")
        or ""
    ).strip()

    if not V3_NAME_RE.match(name):
        return None

    targets: List[Dict[str, Any]] = []

    for target in item.get("targets") or []:
        if not isinstance(target, dict):
            continue

        cleaned = clean_target(target)

        if cleaned is not None:
            targets.append(cleaned)

    if not targets:
        for node in walk_nodes(item):
            if not isinstance(node, dict):
                continue

            cleaned = clean_target(node)

            if cleaned is not None:
                targets.append(cleaned)

    deduplicated: Dict[Tuple[str, int], Dict[str, Any]] = {}

    for target in targets:
        key = (
            target["input"],
            target["local_frame"],
        )
        deduplicated[key] = target

    targets = sorted(
        deduplicated.values(),
        key=lambda row: (
            row["input"],
            row["local_frame"],
        ),
    )

    if not targets:
        return None

    cue_match = V3_NAME_RE.match(name)

    return {
        "cue_id": (
            item.get("cue_id")
            or (
                cue_match.group("cue")
                if cue_match
                else None
            )
        ),
        "name": name,
        "animation_type": str(
            item.get("animation_type")
            or item.get("type")
            or "unknown"
        ),
        "targets": targets,
    }


def extract_items_from_plan(
    plan: Any,
) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}

    for node in walk_nodes(plan):
        if not isinstance(node, dict):
            continue

        name = str(
            node.get("name")
            or node.get("item_name")
            or ""
        ).strip()

        if not V3_NAME_RE.match(name):
            continue

        cleaned = clean_source_item(node)

        if cleaned is not None:
            found[name] = cleaned

    return sorted(
        found.values(),
        key=lambda row: row["name"],
    )


def source_is_valid(
    payload: Any,
) -> bool:
    if not isinstance(payload, dict):
        return False

    items = payload.get("items")

    if not isinstance(items, list) or not items:
        return False

    return all(
        isinstance(item, dict)
        and item.get("targets")
        for item in items
    )


def load_source_targets() -> Dict[str, Any]:
    if SOURCE_TARGETS_PATH.exists():
        payload = load_json(SOURCE_TARGETS_PATH)

        if source_is_valid(payload):
            return payload

    # The current failed report contains the exact 8 mapped clips
    # and all 16 expected target keyframes.
    if REPORT_PATH.exists():
        previous_report = load_json(REPORT_PATH)

        source_items: List[Dict[str, Any]] = []

        for item in previous_report.get("items") or []:
            if not isinstance(item, dict):
                continue

            cleaned = clean_source_item(item)

            if cleaned is not None:
                source_items.append(cleaned)

        if source_items:
            payload = {
                "ok": True,
                "schema": (
                    "video_cloner_caption_animation_"
                    "source_targets"
                ),
                "schema_version": "1.1",
                "version": WORKSPACE_VERSION,
                "source": str(REPORT_PATH),
                "plan": previous_report.get("plan"),
                "plan_hash": previous_report.get("plan_hash"),
                "items": source_items,
            }

            write_json(SOURCE_TARGETS_PATH, payload)
            return payload

    if PLAN_PATH.exists():
        plan = load_json(PLAN_PATH)
        source_items = extract_items_from_plan(plan)

        if source_items:
            payload = {
                "ok": True,
                "schema": (
                    "video_cloner_caption_animation_"
                    "source_targets"
                ),
                "schema_version": "1.1",
                "version": WORKSPACE_VERSION,
                "source": str(PLAN_PATH),
                "plan": str(PLAN_PATH),
                "plan_hash": plan.get("plan_hash"),
                "items": source_items,
            }

            write_json(SOURCE_TARGETS_PATH, payload)
            return payload

    raise RuntimeError(
        "No usable Step 3C source targets were found. "
        "Keep the previous failed Resolve report in place "
        "for the first recovery run."
    )


def get_resolve() -> Any:
    existing = globals().get("resolve")

    if existing is not None:
        return existing

    bmd_module = globals().get("bmd")

    if bmd_module is not None:
        resolved = bmd_module.scriptapp("Resolve")

        if resolved is not None:
            return resolved

    try:
        import DaVinciResolveScript as dvr  # type: ignore

        resolved = dvr.scriptapp("Resolve")

        if resolved is not None:
            return resolved
    except Exception:
        pass

    raise RuntimeError(
        "Could not connect to DaVinci Resolve."
    )


def safe_name(item: Any) -> str:
    try:
        return str(item.GetName() or "")
    except Exception:
        return ""


def safe_start(item: Any) -> Optional[int]:
    try:
        return as_int(item.GetStart())
    except Exception:
        return None


def safe_end(item: Any) -> Optional[int]:
    try:
        return as_int(item.GetEnd())
    except Exception:
        return None


def scan_tracks(
    timeline: Any,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    for track_type in ("video", "audio"):
        try:
            count = int(
                timeline.GetTrackCount(track_type) or 0
            )
        except Exception:
            count = 0

        for index in range(1, count + 1):
            key = (
                f"V{index}"
                if track_type == "video"
                else f"A{index}"
            )

            entries = []

            try:
                items = (
                    timeline.GetItemListInTrack(
                        track_type,
                        index,
                    )
                    or []
                )
            except Exception:
                items = []

            for item in items:
                entries.append(
                    {
                        "name": safe_name(item),
                        "start": safe_start(item),
                        "end": safe_end(item),
                    }
                )

            result[key] = entries

    return result


def scan_v3_items(
    timeline: Any,
) -> Dict[str, Any]:
    found: Dict[str, Any] = {}

    try:
        track_count = int(
            timeline.GetTrackCount("video") or 0
        )
    except Exception:
        track_count = 0

    for track_index in range(1, track_count + 1):
        try:
            items = (
                timeline.GetItemListInTrack(
                    "video",
                    track_index,
                )
                or []
            )
        except Exception:
            items = []

        for item in items:
            name = safe_name(item)

            if V3_NAME_RE.match(name):
                found[name] = item

    return found


def v3_snapshot(
    items: Dict[str, Any],
) -> List[Dict[str, Any]]:
    result = []

    for name in sorted(items):
        item = items[name]

        result.append(
            {
                "name": name,
                "start": safe_start(item),
                "end": safe_end(item),
            }
        )

    return result


def get_fusion_comp(item: Any) -> Any:
    try:
        comp = item.GetFusionCompByIndex(1)

        if comp is not None:
            return comp
    except Exception:
        pass

    try:
        names = item.GetFusionCompNameList() or []

        for name in names:
            comp = item.GetFusionCompByName(name)

            if comp is not None:
                return comp
    except Exception:
        pass

    return None


def get_text_tool(comp: Any) -> Any:
    try:
        tools = comp.GetToolList(False, "TextPlus") or {}

        if isinstance(tools, dict) and tools:
            return next(iter(tools.values()))
    except Exception:
        pass

    try:
        tools = comp.GetToolList(False) or {}
    except Exception:
        tools = {}

    if isinstance(tools, dict):
        for tool in tools.values():
            try:
                attrs = tool.GetAttrs() or {}
            except Exception:
                attrs = {}

            if str(
                attrs.get("TOOLS_RegID") or ""
            ) == "TextPlus":
                return tool

    return None


def find_input(tool: Any, input_name: str) -> Any:
    try:
        input_object = tool.FindInput(input_name)

        if input_object is not None:
            return input_object
    except Exception:
        pass

    try:
        input_object = getattr(tool, input_name)

        if input_object is not None:
            return input_object
    except Exception:
        pass

    try:
        inputs = tool.GetInputList() or {}
    except Exception:
        inputs = {}

    if isinstance(inputs, dict):
        for input_object in inputs.values():
            try:
                attrs = input_object.GetAttrs() or {}
            except Exception:
                attrs = {}

            if (
                attrs.get("INPS_ID") == input_name
                or attrs.get("INPS_Name") == input_name
            ):
                return input_object

    return None


def connected_output(input_object: Any) -> Any:
    if input_object is None:
        return None

    try:
        return input_object.GetConnectedOutput()
    except Exception:
        return None


def ensure_modifier(
    comp: Any,
    tool: Any,
    input_name: str,
) -> Dict[str, Any]:
    input_object = find_input(tool, input_name)

    if input_object is None:
        return {
            "ok": False,
            "created": False,
            "failure": f"input_not_found:{input_name}",
        }

    if connected_output(input_object) is not None:
        return {
            "ok": True,
            "created": False,
            "modifier": "existing_connected_modifier",
        }

    modifier_name = (
        "BezierSpline"
        if input_name == "Size"
        else "Path"
    )

    attempts: List[Dict[str, Any]] = []

    try:
        returned = tool.AddModifier(
            input_name,
            modifier_name,
        )

        attempts.append(
            {
                "method": "Tool.AddModifier",
                "modifier": modifier_name,
                "returned": str(returned),
            }
        )
    except Exception as exc:
        attempts.append(
            {
                "method": "Tool.AddModifier",
                "modifier": modifier_name,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    time.sleep(0.05)

    input_object = find_input(tool, input_name)

    if connected_output(input_object) is not None:
        return {
            "ok": True,
            "created": True,
            "modifier": modifier_name,
            "attempts": attempts,
        }

    # Fallback for Resolve/Fusion builds where AddModifier
    # does not return a useful status object.
    try:
        factory = getattr(comp, modifier_name)

        modifier = factory()
        setattr(tool, input_name, modifier)

        attempts.append(
            {
                "method": f"comp.{modifier_name}()",
                "assigned": True,
            }
        )
    except Exception as exc:
        attempts.append(
            {
                "method": f"comp.{modifier_name}()",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    time.sleep(0.05)

    input_object = find_input(tool, input_name)

    return {
        "ok": connected_output(input_object) is not None,
        "created": connected_output(input_object) is not None,
        "modifier": modifier_name,
        "attempts": attempts,
        "failure": (
            None
            if connected_output(input_object) is not None
            else f"modifier_not_connected:{input_name}"
        ),
    }


def read_input(
    tool: Any,
    input_name: str,
    frame: int,
) -> Any:
    try:
        return tool.GetInput(input_name, frame)
    except Exception:
        pass

    input_object = find_input(tool, input_name)

    if input_object is not None:
        try:
            return input_object[frame]
        except Exception:
            pass

    return None


def fusion_variants(
    input_name: str,
    expected: Any,
) -> List[Any]:
    normalized = normalize_value(
        input_name,
        expected,
    )

    if input_name == "Center":
        x, y = normalized

        return [
            {1: x, 2: y, 3: 0.0},
            {1: x, 2: y},
            [x, y],
        ]

    return [normalized]


def write_key(
    tool: Any,
    input_name: str,
    frame: int,
    expected: Any,
) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    input_object = find_input(tool, input_name)

    for variant in fusion_variants(
        input_name,
        expected,
    ):
        if input_object is not None:
            try:
                input_object[frame] = variant

                actual = read_input(
                    tool,
                    input_name,
                    frame,
                )

                matched = values_match(
                    input_name,
                    actual,
                    expected,
                )

                attempts.append(
                    {
                        "method": "Input[frame]=value",
                        "variant": str(variant),
                        "matched": matched,
                    }
                )

                if matched:
                    return {
                        "ok": True,
                        "attempts": attempts,
                    }
            except Exception as exc:
                attempts.append(
                    {
                        "method": "Input[frame]=value",
                        "variant": str(variant),
                        "error": (
                            f"{type(exc).__name__}: {exc}"
                        ),
                    }
                )

        try:
            returned = tool.SetInput(
                input_name,
                variant,
                frame,
            )

            actual = read_input(
                tool,
                input_name,
                frame,
            )

            matched = values_match(
                input_name,
                actual,
                expected,
            )

            attempts.append(
                {
                    "method": (
                        "SetInput after connected modifier"
                    ),
                    "variant": str(variant),
                    "returned": str(returned),
                    "matched": matched,
                }
            )

            if matched:
                return {
                    "ok": True,
                    "attempts": attempts,
                }
        except Exception as exc:
            attempts.append(
                {
                    "method": (
                        "SetInput after connected modifier"
                    ),
                    "variant": str(variant),
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            )

    return {
        "ok": False,
        "attempts": attempts,
    }


def identity(tool: Any, item: Any) -> Dict[str, Any]:
    return {
        "name": safe_name(item),
        "start": safe_start(item),
        "end": safe_end(item),
        "text": str(
            read_input(tool, "StyledText", 0) or ""
        ),
        "font": str(
            read_input(tool, "Font", 0) or ""
        ),
        "style": str(
            read_input(tool, "Style", 0) or ""
        ),
    }


def input_targets_are_correct(
    tool: Any,
    input_name: str,
    targets: Sequence[Dict[str, Any]],
) -> bool:
    input_object = find_input(tool, input_name)

    # A matching value without a connected modifier is not
    # persistent animation and therefore is not "correct".
    if connected_output(input_object) is None:
        return False

    return all(
        values_match(
            input_name,
            read_input(
                tool,
                input_name,
                target["local_frame"],
            ),
            target["expected"],
        )
        for target in targets
    )


def run() -> Dict[str, Any]:
    source_payload = load_source_targets()
    source_items = source_payload["items"]

    resolve_app = get_resolve()
    project_manager = resolve_app.GetProjectManager()
    project = project_manager.GetCurrentProject()

    if project is None:
        raise RuntimeError("No Resolve project is open.")

    timeline = project.GetCurrentTimeline()

    if timeline is None:
        raise RuntimeError("No Resolve timeline is open.")

    track_before = scan_tracks(timeline)
    v3_before = scan_v3_items(timeline)
    v3_before_snapshot = v3_snapshot(v3_before)

    preliminary: List[Dict[str, Any]] = []
    keyframes_written_count = 0

    for source_item in source_items:
        name = source_item["name"]
        timeline_item = v3_before.get(name)

        result_item: Dict[str, Any] = {
            "cue_id": source_item.get("cue_id"),
            "name": name,
            "animation_type": (
                source_item.get("animation_type")
            ),
            "targets": [],
            "failures": [],
        }

        if timeline_item is None:
            result_item["failures"].append(
                "v3_timeline_item_not_found"
            )
            preliminary.append(result_item)
            continue

        comp = get_fusion_comp(timeline_item)

        if comp is None:
            result_item["failures"].append(
                "fusion_comp_not_found"
            )
            preliminary.append(result_item)
            continue

        tool = get_text_tool(comp)

        if tool is None:
            result_item["failures"].append(
                "textplus_tool_not_found"
            )
            preliminary.append(result_item)
            continue

        result_item["identity_before"] = identity(
            tool,
            timeline_item,
        )

        grouped: Dict[str, List[Dict[str, Any]]] = {}

        for target in source_item["targets"]:
            grouped.setdefault(
                target["input"],
                [],
            ).append(target)

        already_correct = all(
            input_targets_are_correct(
                tool,
                input_name,
                targets,
            )
            for input_name, targets in grouped.items()
        )

        result_item["already_correct_before"] = (
            already_correct
        )

        if already_correct:
            preliminary.append(result_item)
            continue

        try:
            comp.Lock()
        except Exception:
            pass

        try:
            for input_name, targets in grouped.items():
                modifier_result = ensure_modifier(
                    comp,
                    tool,
                    input_name,
                )

                result_item.setdefault(
                    "modifiers",
                    {},
                )[input_name] = modifier_result

                if not modifier_result["ok"]:
                    result_item["failures"].append(
                        modifier_result.get("failure")
                        or (
                            f"modifier_failed:"
                            f"{input_name}"
                        )
                    )
                    continue

                for target in sorted(
                    targets,
                    key=lambda row: row["local_frame"],
                ):
                    frame = target["local_frame"]
                    actual_before = read_input(
                        tool,
                        input_name,
                        frame,
                    )

                    write_result = write_key(
                        tool,
                        input_name,
                        frame,
                        target["expected"],
                    )

                    if write_result["ok"]:
                        keyframes_written_count += 1
                    else:
                        result_item["failures"].append(
                            f"keyframe_write_failed:"
                            f"{input_name}@{frame}"
                        )

                    result_item["targets"].append(
                        {
                            **target,
                            "actual_before": (
                                normalize_value(
                                    input_name,
                                    actual_before,
                                )
                            ),
                            "write": write_result,
                        }
                    )
        finally:
            try:
                comp.Unlock()
            except Exception:
                pass

        preliminary.append(result_item)

    # Force Resolve to commit the Fusion modifier graph.
    try:
        project_manager.SaveProject()
    except Exception:
        pass

    time.sleep(1.0)

    # Reacquire the timeline and every Fusion object. Reusing old
    # Python handles is not a valid persistence test.
    timeline = project.GetCurrentTimeline()
    v3_after = scan_v3_items(timeline)

    modified_count = 0
    already_correct_count = 0
    mapped_count = 0
    readback_success_count = 0
    readback_keyframe_count = 0
    failed_count = 0
    font_integrity_failure_count = 0

    final_items: List[Dict[str, Any]] = []

    for preliminary_item in preliminary:
        name = preliminary_item["name"]
        source_item = next(
            (
                row
                for row in source_items
                if row["name"] == name
            ),
            None,
        )

        item_result = dict(preliminary_item)
        timeline_item = v3_after.get(name)

        if source_item is None or timeline_item is None:
            item_result["ok"] = False
            item_result.setdefault(
                "failures",
                [],
            ).append("readback_item_not_found")
            failed_count += 1
            final_items.append(item_result)
            continue

        mapped_count += 1

        comp = get_fusion_comp(timeline_item)
        tool = get_text_tool(comp) if comp else None

        if tool is None:
            item_result["ok"] = False
            item_result.setdefault(
                "failures",
                [],
            ).append("readback_textplus_not_found")
            failed_count += 1
            final_items.append(item_result)
            continue

        identity_after = identity(
            tool,
            timeline_item,
        )
        item_result["identity_after"] = identity_after

        identity_before = (
            item_result.get("identity_before")
            or identity_after
        )

        for protected_field in (
            "name",
            "start",
            "end",
            "text",
            "font",
            "style",
        ):
            if (
                identity_before.get(protected_field)
                != identity_after.get(protected_field)
            ):
                item_result.setdefault(
                    "failures",
                    [],
                ).append(
                    f"identity_changed:{protected_field}"
                )

                if protected_field in {
                    "font",
                    "style",
                }:
                    font_integrity_failure_count += 1

        verified_targets: List[Dict[str, Any]] = []
        all_targets_ok = True

        for target in source_item["targets"]:
            input_name = target["input"]
            frame = target["local_frame"]

            input_object = find_input(
                tool,
                input_name,
            )

            modifier_connected = (
                connected_output(input_object) is not None
            )

            actual_after = read_input(
                tool,
                input_name,
                frame,
            )

            matched_after = values_match(
                input_name,
                actual_after,
                target["expected"],
            )

            # A connected modifier plus correct values at all
            # independent times is the persistence test. This avoids
            # the false negative caused by querying GetKeyFrames()
            # on the Text+ input instead of the connected modifier.
            present_after = (
                modifier_connected
                and matched_after
            )

            if present_after:
                readback_keyframe_count += 1
            else:
                all_targets_ok = False
                item_result.setdefault(
                    "failures",
                    [],
                ).append(
                    f"keyframe_readback_failed:"
                    f"{input_name}@{frame}"
                )

            verified_targets.append(
                {
                    **target,
                    "actual_after": normalize_value(
                        input_name,
                        actual_after,
                    ),
                    "modifier_connected": (
                        modifier_connected
                    ),
                    "present_after": present_after,
                    "matched_after": matched_after,
                    "verification_method": (
                        "connected_modifier_and_"
                        "temporal_value_readback"
                    ),
                }
            )

        item_result["targets"] = verified_targets

        failures = item_result.get("failures") or []
        item_ok = all_targets_ok and not failures

        item_result["ok"] = item_ok

        was_already_correct = bool(
            item_result.get("already_correct_before")
        )

        item_result["already_correct"] = (
            item_ok and was_already_correct
        )
        item_result["modified"] = (
            item_ok and not was_already_correct
        )

        if item_ok:
            readback_success_count += 1

            if was_already_correct:
                already_correct_count += 1
            else:
                modified_count += 1
        else:
            failed_count += 1

        final_items.append(item_result)

    try:
        project_manager.SaveProject()
    except Exception:
        pass

    track_after = scan_tracks(timeline)
    v3_after_snapshot = v3_snapshot(v3_after)

    core_track_integrity_ok = (
        track_before.get("V1")
        == track_after.get("V1")
        and track_before.get("A1")
        == track_after.get("A1")
    )

    v3_track_integrity_ok = (
        v3_before_snapshot == v3_after_snapshot
    )

    target_keyframe_count = sum(
        len(item.get("targets") or [])
        for item in source_items
    )

    selected_animation_count = len(source_items)

    animation_type_counts: Dict[str, int] = {}

    for item in source_items:
        animation_type = str(
            item.get("animation_type") or "unknown"
        )

        animation_type_counts[animation_type] = (
            animation_type_counts.get(
                animation_type,
                0,
            )
            + 1
        )

    failures: List[str] = []

    if len(v3_after) != EXPECTED_V3_COUNT:
        failures.append("v3_candidate_count_mismatch")

    if mapped_count != selected_animation_count:
        failures.append("mapped_count_mismatch")

    if (
        readback_success_count
        != selected_animation_count
    ):
        failures.append(
            "readback_success_count_mismatch"
        )

    if (
        readback_keyframe_count
        != target_keyframe_count
    ):
        failures.append(
            "readback_keyframe_count_mismatch"
        )

    if failed_count != 0:
        failures.append("failed_count_nonzero")

    if font_integrity_failure_count != 0:
        failures.append(
            "font_integrity_failure_count_nonzero"
        )

    if not core_track_integrity_ok:
        failures.append("core_track_integrity_false")

    if not v3_track_integrity_ok:
        failures.append("v3_track_integrity_false")

    run_mode = (
        "idempotent_second_run"
        if (
            already_correct_count
            == selected_animation_count
            and modified_count == 0
        )
        else "first_application"
    )

    mode_report_path = (
        IDEMPOTENCY_REPORT_PATH
        if run_mode == "idempotent_second_run"
        else FIRST_REPORT_PATH
    )

    report = {
        "ok": not failures,
        "step": "Major Step 3C",
        "workspace_version": WORKSPACE_VERSION,
        "run_mode": run_mode,
        "latest_report": str(REPORT_PATH),
        "mode_report": str(mode_report_path),
        "first_application_report": str(FIRST_REPORT_PATH),
        "idempotency_report": str(IDEMPOTENCY_REPORT_PATH),
        "plan": (
            source_payload.get("plan")
            or str(PLAN_PATH)
        ),
        "plan_hash": source_payload.get("plan_hash"),
        "state": str(STATE_PATH),
        "source_targets": str(SOURCE_TARGETS_PATH),
        "summary": {
            "v3_candidate_count": len(v3_after),
            "plan_item_count": EXPECTED_V3_COUNT,
            "selected_animation_count": (
                selected_animation_count
            ),
            "mapped_count": mapped_count,
            "modified_count": modified_count,
            "already_correct_count": (
                already_correct_count
            ),
            "static_untouched_count": (
                len(v3_after)
                - selected_animation_count
            ),
            "target_keyframe_count": (
                target_keyframe_count
            ),
            "keyframes_written_count": (
                keyframes_written_count
            ),
            "readback_success_count": (
                readback_success_count
            ),
            "readback_keyframe_count": (
                readback_keyframe_count
            ),
            "failed_count": failed_count,
            "font_integrity_failure_count": (
                font_integrity_failure_count
            ),
            "timeline_integrity_failure_count": (
                0
                if (
                    core_track_integrity_ok
                    and v3_track_integrity_ok
                )
                else 1
            ),
            "keyframe_presence_verified": (
                readback_keyframe_count
                == target_keyframe_count
            ),
            "animation_type_counts": (
                animation_type_counts
            ),
        },
        "core_track_integrity": {
            "ok": core_track_integrity_ok,
            "before": {
                "V1": track_before.get("V1", []),
                "A1": track_before.get("A1", []),
            },
            "after": {
                "V1": track_after.get("V1", []),
                "A1": track_after.get("A1", []),
            },
        },
        "v3_track_integrity": {
            "ok": v3_track_integrity_ok,
            "before": v3_before_snapshot,
            "after": v3_after_snapshot,
            "scan_failures": [],
        },
        "items": final_items,
        "failures": failures,
    }

    state = {
        "ok": report["ok"],
        "step": "Major Step 3C",
        "workspace_version": WORKSPACE_VERSION,
        "plan_hash": report.get("plan_hash"),
        "run_mode": run_mode,
        "latest_report": str(REPORT_PATH),
        "mode_report": str(mode_report_path),
        "first_application_report": str(FIRST_REPORT_PATH),
        "idempotency_report": str(IDEMPOTENCY_REPORT_PATH),
        "selected_animation_count": (
            selected_animation_count
        ),
        "target_keyframe_count": (
            target_keyframe_count
        ),
        "modified_count": modified_count,
        "already_correct_count": (
            already_correct_count
        ),
        "readback_success_count": (
            readback_success_count
        ),
        "readback_keyframe_count": (
            readback_keyframe_count
        ),
        "source_targets": str(SOURCE_TARGETS_PATH),
    }

    # REPORT_PATH remains the latest-run convenience pointer. The
    # mode-specific report is the immutable validation input for its phase.
    # A second Resolve run therefore cannot destroy the first-run evidence.
    write_json(REPORT_PATH, report)
    write_json(mode_report_path, report)
    write_json(STATE_PATH, state)

    return report


def main() -> None:
    try:
        report = run()

        summary = report["summary"]

        if report["ok"]:
            show_message(
                "Video Cloner — Step 3C complete",
                (
                    "Caption animation cloning finished.\n\n"
                    f"V3 clips: "
                    f"{summary['v3_candidate_count']}\n"
                    f"Animated clips: "
                    f"{summary['selected_animation_count']}\n"
                    f"Modified: "
                    f"{summary['modified_count']}\n"
                    f"Already correct: "
                    f"{summary['already_correct_count']}\n"
                    f"Persistent keyframes: "
                    f"{summary['readback_keyframe_count']}\n"
                    f"Failures: "
                    f"{summary['failed_count']}\n\n"
                    f"Mode report:\n"
                    f"{report.get('mode_report') or REPORT_PATH}\n\n"
                    f"Latest report:\n{REPORT_PATH}"
                ),
            )
        else:
            show_message(
                "Video Cloner — Step 3C failed",
                (
                    "Caption animation cloning failed "
                    "validation.\n\n"
                    + "\n".join(report["failures"])
                    + f"\n\nReport:\n{REPORT_PATH}"
                ),
                error=True,
            )

    except Exception as exc:
        failure_report = {
            "ok": False,
            "step": "Major Step 3C",
            "workspace_version": WORKSPACE_VERSION,
            "status": "exception",
            "exception": (
                f"{type(exc).__name__}: {exc}"
            ),
            "traceback": traceback.format_exc(),
            "failures": ["workspace_exception"],
        }

        try:
            write_json(REPORT_PATH, failure_report)
        except Exception:
            pass

        show_message(
            "Video Cloner — Step 3C exception",
            (
                f"{type(exc).__name__}: {exc}\n\n"
                f"Report:\n{REPORT_PATH}"
            ),
            error=True,
        )


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1":
    main()
