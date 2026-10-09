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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


WORKSPACE_VERSION = (
    "resolve_caption_animation_step_3C_v1_2_"
    "persistent_modifier_keyframes_archived_reports"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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


def _collection_values(value: Any) -> List[Any]:
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return list(value.values())
    except Exception:
        return []


def _tool_regid(tool: Any) -> str:
    try:
        attrs = tool.GetAttrs() or {}
    except Exception:
        attrs = {}
    return str(attrs.get("TOOLS_RegID") or "") if isinstance(attrs, dict) else ""


def _parse_fcpx_color(value: Any) -> List[float]:
    parts = [as_float(part) for part in str(value or "").split()]
    if len(parts) != 4 or any(part is None for part in parts):
        raise ValueError("caption_static_color")
    return [float(part) for part in parts]


def _carrier_static_styles(
    fcpxml_path: Path,
    selected: Sequence[Dict[str, Any]],
    frame_width: int,
) -> Dict[str, Dict[str, Any]]:
    if frame_width <= 0:
        raise ValueError("caption_static_frame_width")
    by_number: Dict[int, Dict[str, Any]] = {}
    for title in ET.parse(fcpxml_path).getroot().iter("title"):
        match = re.search(r"VC Caption\s+(\d+)", str(title.get("name") or ""), re.IGNORECASE)
        text_node = title.find("./text/text-style")
        style_node = title.find("./text-style-def/text-style")
        if match is None or text_node is None or style_node is None:
            continue
        font_size = as_float(style_node.get("fontSize"))
        stroke_width = as_float(style_node.get("strokeWidth"))
        shadow_offset = as_float(style_node.get("shadowOffset"))
        if font_size is None or font_size <= 0 or stroke_width is None:
            raise ValueError("caption_static_typography")
        fill = _parse_fcpx_color(style_node.get("fontColor"))
        outline = _parse_fcpx_color(style_node.get("strokeColor"))
        shadow = _parse_fcpx_color(style_node.get("shadowColor") or "0 0 0 0")
        by_number[int(match.group(1))] = {
            "text": str(text_node.text or ""),
            "Font": str(style_node.get("font") or "Arial"),
            "Style": "Bold" if style_node.get("bold") == "1" else "Regular",
            "Size": max(0.02, font_size / float(frame_width) * 1.5),
            "Center": [0.5, 0.5],
            "Enabled1": 1.0,
            "Red1": fill[0], "Green1": fill[1], "Blue1": fill[2], "Alpha1": fill[3],
            "Enabled2": 1.0 if stroke_width > 0 and outline[3] > 0 else 0.0,
            "ElementShape2": 1.0,
            "Red2": outline[0], "Green2": outline[1], "Blue2": outline[2], "Alpha2": outline[3],
            "Thickness2": max(0.001, stroke_width / font_size),
            "OutsideOnly2": 1.0,
            "Enabled3": 1.0 if shadow[3] > 0 else 0.0,
            "ElementShape3": 0.0,
            "Red3": shadow[0], "Green3": shadow[1], "Blue3": shadow[2], "Alpha3": shadow[3],
            "Offset3": [float(shadow_offset or 0.0) / frame_width] * 2,
        }
    result: Dict[str, Dict[str, Any]] = {}
    for row in selected:
        cue_id = str(row.get("cue_id") or "")
        cue_match = re.fullmatch(r"sub_(\d+)", cue_id, re.IGNORECASE)
        number = int(cue_match.group(1)) if cue_match else -1
        style = by_number.get(number)
        if style is None or style["text"] != str(row.get("text") or ""):
            raise ValueError(f"caption_static_contract:{cue_id}")
        result[cue_id] = style
    return result


def _set_static_input(tool: Any, name: str, value: Any) -> None:
    try:
        returned = tool.SetInput(name, value)
    except Exception as exc:
        raise RuntimeError(f"caption_static_write:{name}:{exc}") from exc
    actual = read_input(tool, name, 0)
    if isinstance(value, str):
        matched = str(actual or "") == value
    elif isinstance(value, (list, tuple)):
        normalized = normalize_point(actual)
        matched = normalized is not None and all(abs(normalized[index] - float(value[index])) <= 1e-5 for index in (0, 1))
    else:
        number = as_float(actual)
        matched = number is not None and abs(number - float(value)) <= 1e-5
    if not matched:
        raise RuntimeError(
            f"caption_static_readback:{name}:set_return={returned!r}:"
            f"actual_type={type(actual).__name__}:actual={actual!r}"
        )


def _apply_static_style(tool: Any, style: Dict[str, Any]) -> Dict[str, Any]:
    _set_static_input(tool, "StyledText", style["text"])
    for name in ("Font", "Style", "Size", "Center", "Enabled1", "Red1", "Green1", "Blue1", "Alpha1"):
        _set_static_input(tool, name, style[name])
    for element in (2, 3):
        _set_static_input(tool, f"Enabled{element}", 0.0)
    if style["Enabled2"]:
        _set_static_input(tool, "Enabled2", style["Enabled2"])
        for name in ("ElementShape2", "Red2", "Green2", "Blue2", "Alpha2", "Thickness2", "OutsideOnly2"):
            _set_static_input(tool, name, style[name])
    if style["Enabled3"]:
        _set_static_input(tool, "Enabled3", style["Enabled3"])
        for name in ("ElementShape3", "Red3", "Green3", "Blue3", "Alpha3", "Offset3"):
            _set_static_input(tool, name, style[name])
    return {key: style[key] for key in ("text", "Font", "Style", "Size", "Center", "Enabled2", "Enabled3")}


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


def validated_animation_targets(
    tool: Any,
    payload: Dict[str, Any],
    duration_frames: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("animation_payload_type")

    allowed_keys = {
        "authority",
        "source_evidence_id",
        "source_type",
        "property",
        "keyframes",
    }
    if set(payload) - allowed_keys:
        raise ValueError("animation_payload_unexpected_fields")
    if payload.get("authority") != "visual_observed":
        raise ValueError("animation_authority")

    input_name = str(payload.get("property") or "")
    source_type = str(payload.get("source_type") or "")
    if (input_name, source_type) not in {
        ("Center", "slide"),
        ("Size", "scale"),
        ("Size", "scale_pop"),
    }:
        raise ValueError("animation_property_or_type")
    if not str(payload.get("source_evidence_id") or ""):
        raise ValueError("animation_source_evidence_id")
    if not isinstance(duration_frames, int) or isinstance(duration_frames, bool) or duration_frames <= 0:
        raise ValueError("animation_duration_frames")

    raw_keyframes = payload.get("keyframes")
    if not isinstance(raw_keyframes, list) or not raw_keyframes:
        raise ValueError("animation_keyframes")

    targets: List[Dict[str, Any]] = []
    seen: Dict[int, Any] = {}
    previous_frame = -1
    for keyframe in raw_keyframes:
        if not isinstance(keyframe, dict) or set(keyframe) != {"frame", "relative_time", "value"}:
            raise ValueError("animation_keyframe_shape")
        frame = keyframe.get("frame")
        relative_time = as_float(keyframe.get("relative_time"))
        value = normalize_value(input_name, keyframe.get("value"))
        if (
            not isinstance(frame, int)
            or isinstance(frame, bool)
            or relative_time is None
            or not 0.0 <= relative_time <= 1.0
            or value is None
        ):
            raise ValueError("animation_keyframe_value")
        if frame < 0 or frame >= duration_frames:
            raise ValueError("animation_keyframe_out_of_range")
        if frame in seen:
            if not values_match(input_name, seen[frame], value):
                raise ValueError("animation_duplicate_frame_conflict")
            raise ValueError("animation_duplicate_frame")
        if frame <= previous_frame:
            raise ValueError("animation_keyframe_order")
        seen[frame] = value
        previous_frame = frame
        targets.append({"input": input_name, "local_frame": frame, "expected": value})

    if find_input(tool, input_name) is None:
        raise RuntimeError(f"animation_input_not_found:{input_name}")

    return input_name, targets


def apply_authorized_animation(
    comp: Any,
    tool: Any,
    payload: Optional[Dict[str, Any]],
    duration_frames: int,
) -> Dict[str, Any]:
    """Apply one authorized payload and prove persistent temporal readback."""
    if payload is None:
        return {
            "ok": True,
            "selected": False,
            "modified": False,
            "keyframes_written": 0,
            "readback": [],
        }

    input_name, targets = validated_animation_targets(
        tool,
        payload,
        duration_frames,
    )
    if input_targets_are_correct(tool, input_name, targets):
        return {
            "ok": True,
            "selected": True,
            "modified": False,
            "already_correct": True,
            "property": input_name,
            "keyframes_written": 0,
            "readback": [
                {**target, "actual": normalize_value(input_name, read_input(tool, input_name, target["local_frame"])), "matched": True}
                for target in targets
            ],
        }

    try:
        comp.Lock()
    except Exception:
        pass
    writes: List[Dict[str, Any]] = []
    try:
        modifier = ensure_modifier(comp, tool, input_name)
        if modifier.get("ok") is not True:
            raise RuntimeError(f"animation_modifier_not_connected:{input_name}")
        for target in targets:
            write = write_key(tool, input_name, target["local_frame"], target["expected"])
            writes.append({**target, "write": write})
            if write.get("ok") is not True:
                raise RuntimeError(f"animation_keyframe_write:{input_name}@{target['local_frame']}")
    finally:
        try:
            comp.Unlock()
        except Exception:
            pass

    readback = [
        {
            **target,
            "actual": normalize_value(input_name, read_input(tool, input_name, target["local_frame"])),
            "modifier_connected": connected_output(find_input(tool, input_name)) is not None,
            "matched": values_match(input_name, read_input(tool, input_name, target["local_frame"]), target["expected"]),
        }
        for target in targets
    ]
    if not input_targets_are_correct(tool, input_name, targets) or not all(row["matched"] for row in readback):
        raise RuntimeError(f"animation_temporal_readback:{input_name}")
    return {
        "ok": True,
        "selected": True,
        "modified": True,
        "already_correct": False,
        "property": input_name,
        "modifier": modifier,
        "keyframes_written": len(writes),
        "writes": writes,
        "readback": readback,
    }


def _legacy_run() -> Dict[str, Any]:
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

    if len(v3_after) != int(
        source_payload.get("expected_caption_count") or len(v3_after)
    ):
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
            "plan_item_count": int(
                source_payload.get("expected_caption_count") or len(v3_after)
            ),
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


def _required_payload(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    command = (context or {}).get("command") or {}
    payload = command.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("command_payload")

    required = {
        "video_id",
        "target_timeline_name",
        "target_timeline_uid",
        "animation_plan_path",
        "expected_caption_count",
        "caption_track_index",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"command_payload_missing:{','.join(missing)}")
    if payload.get("apply_caption_animation") is not True:
        raise ValueError("apply_caption_animation_not_authorized")
    if payload.get("regenerate_captions") is not False:
        raise ValueError("caption_regeneration_must_be_false")
    if payload.get("carrier_fallback") is True:
        for key in ("static_fcpxml_path", "frame_width", "carrier_track_index"):
            if key not in payload:
                raise ValueError(f"command_payload_missing:{key}")
        if payload.get("owned_carrier_rollback_permitted") is not True:
            raise ValueError("carrier_rollback_not_authorized")
    return payload


def _repository_path(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("animation_plan_path")
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (PROJECT_ROOT / candidate).resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("animation_plan_outside_repository") from exc
    if not resolved.is_file():
        raise ValueError("animation_plan_missing")
    return resolved


def _timeline_uid(timeline: Any) -> str:
    try:
        return str(timeline.GetUniqueId() or "")
    except Exception:
        return ""


def _caption_items(timeline: Any, track_index: int) -> List[Any]:
    try:
        return list(timeline.GetItemListInTrack("video", track_index) or [])
    except Exception:
        return []


def _item_uid(item: Any) -> str:
    try:
        return str(item.GetUniqueId() or "")
    except Exception:
        return ""


def _find_carrier_source(timeline: Any, minimum_duration: int) -> Dict[str, Any]:
    for item in _caption_items(timeline, 1):
        try:
            media = item.GetMediaPoolItem()
            duration = int(item.GetDuration())
            source_start = int(item.GetLeftOffset())
        except Exception:
            continue
        if media is not None and duration >= minimum_duration and source_start >= 0:
            return {"media_pool_item": media, "source_start": source_start}
    raise RuntimeError("caption_carrier_source_missing")


def _ensure_carrier_track(timeline: Any, track_index: int) -> bool:
    try:
        count = int(timeline.GetTrackCount("video") or 0)
    except Exception as exc:
        raise RuntimeError("caption_carrier_track_count") from exc
    if count == track_index - 1:
        if timeline.AddTrack("video") is not True:
            raise RuntimeError("caption_carrier_track_add")
        return True
    if count < track_index:
        raise RuntimeError("caption_carrier_track_gap")
    if _caption_items(timeline, track_index):
        raise RuntimeError("caption_carrier_track_not_empty")
    return False


def _set_item_name(item: Any, name: str) -> None:
    try:
        if item.SetName(name) is True and safe_name(item) == name:
            return
    except Exception:
        pass
    try:
        if item.SetProperty("Name", name) is True and safe_name(item) == name:
            return
    except Exception:
        pass
    raise RuntimeError("caption_carrier_name")


def _append_carrier(
    pool: Any,
    timeline: Any,
    source: Dict[str, Any],
    row: Dict[str, Any],
    track_index: int,
) -> Any:
    before = {_item_uid(item) for item in _caption_items(timeline, track_index) if _item_uid(item)}
    duration = int(row["duration_frames"])
    clip_info = {
        "mediaPoolItem": source["media_pool_item"],
        "startFrame": int(source["source_start"]),
        "endFrame": int(source["source_start"]) + duration,
        "mediaType": 1,
        "trackIndex": track_index,
        "recordFrame": int(row["start_frame"]),
    }
    returned = pool.AppendToTimeline([clip_info])
    returned_items = list(returned) if isinstance(returned, (list, tuple)) else []
    candidates = [item for item in _caption_items(timeline, track_index) if _item_uid(item) and _item_uid(item) not in before]
    item = returned_items[0] if len(returned_items) == 1 else candidates[0] if len(candidates) == 1 else None
    if (
        item is None
        or safe_start(item) != int(row["start_frame"])
        or safe_end(item) != int(row["end_frame"])
    ):
        raise RuntimeError(f"caption_carrier_geometry:{row.get('cue_id')}")
    _set_item_name(item, str(row["name"]))
    return item


def _create_textplus(item: Any) -> Tuple[Any, Any]:
    try:
        if int(item.GetFusionCompCount() or 0) != 0:
            raise RuntimeError("caption_carrier_existing_comp")
        comp = item.AddFusionComp()
    except Exception as exc:
        raise RuntimeError(f"caption_carrier_comp:{exc}") from exc
    if comp is None or int(item.GetFusionCompCount() or 0) != 1:
        raise RuntimeError("caption_carrier_comp_readback")
    tools = _collection_values(comp.GetToolList(False) or {})
    media_out = next((tool for tool in tools if _tool_regid(tool) == "MediaOut"), None)
    if media_out is None:
        raise RuntimeError("caption_carrier_media_out")
    tool = comp.AddTool("TextPlus", -32768, -32768)
    if tool is None or _tool_regid(tool) != "TextPlus":
        raise RuntimeError("caption_carrier_textplus")
    if media_out.ConnectInput("Input", tool.FindMainOutput(1)) is not True:
        raise RuntimeError("caption_carrier_connection")
    return comp, tool


def _item_opacity(item: Any) -> float:
    try:
        value = (item.GetProperty() or {}).get("Opacity")
    except Exception:
        value = None
    opacity = as_float(value)
    if opacity is None:
        raise RuntimeError("caption_source_opacity_readback")
    return opacity


def _set_item_opacity(item: Any, value: float) -> None:
    if item.SetProperty("Opacity", value) is not True or abs(_item_opacity(item) - value) > 1e-5:
        raise RuntimeError("caption_source_opacity_write")


def _selected_plan_items(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    if plan.get("ok") is not True:
        raise ValueError("animation_plan_not_ok")
    items = plan.get("items")
    if not isinstance(items, list):
        raise ValueError("animation_plan_items")
    selected = [row for row in items if isinstance(row, dict) and row.get("selected")]
    if not selected:
        raise ValueError("animation_plan_selected_empty")
    cue_ids = [str(row.get("cue_id") or "") for row in selected]
    if any(not cue_id for cue_id in cue_ids) or len(cue_ids) != len(set(cue_ids)):
        raise ValueError("animation_plan_cue_identity")
    return selected


def _bind_plan_items(
    captions: Sequence[Any],
    selected: Sequence[Dict[str, Any]],
) -> List[Tuple[Dict[str, Any], Any]]:
    bound: List[Tuple[Dict[str, Any], Any]] = []
    used: set[int] = set()
    for row in selected:
        start = as_int(row.get("start_frame"))
        end = as_int(row.get("end_frame"))
        duration = as_int(row.get("duration_frames"))
        matches = [
            item
            for item in captions
            if safe_start(item) == start
            and safe_end(item) == end
            and end is not None
            and start is not None
            and end - start == duration
        ]
        if len(matches) != 1 or id(matches[0]) in used:
            raise ValueError(f"caption_geometry_identity:{row.get('cue_id')}")
        used.add(id(matches[0]))
        bound.append((row, matches[0]))
    return bound


def _runtime_animation(row: Dict[str, Any], tool: Any) -> Dict[str, Any]:
    animation = row.get("animation")
    if not isinstance(animation, dict):
        raise ValueError("animation_plan_payload")
    family = str(animation.get("animation_type") or "")
    source_id = str(animation.get("source_event_id") or "")
    keyframes = animation.get("keyframes")
    if not source_id or not isinstance(keyframes, list):
        raise ValueError("animation_plan_source_evidence")
    stable_frame = int(row["duration_frames"]) - 1

    if family in {"scale", "scale_pop"}:
        base = as_float(read_input(tool, "Size", stable_frame))
        if base is None or base <= 0:
            raise ValueError(f"caption_static_size:{row.get('cue_id')}")
        prop = "Size"
        values = [
            {
                "frame": keyframe.get("frame"),
                "relative_time": keyframe.get("relative_time"),
                "value": base * float(keyframe["size_multiplier"]),
            }
            for keyframe in keyframes
        ]
    elif family == "slide":
        base = normalize_point(read_input(tool, "Center", stable_frame))
        if base is None:
            raise ValueError(f"caption_static_center:{row.get('cue_id')}")
        prop = "Center"
        values = [
            {
                "frame": keyframe.get("frame"),
                "relative_time": keyframe.get("relative_time"),
                "value": [
                    base[0] + float(keyframe["center_offset"][0]),
                    base[1] + float(keyframe["center_offset"][1]),
                ],
            }
            for keyframe in keyframes
        ]
    else:
        raise ValueError(f"animation_family:{family}")

    return {
        "authority": "visual_observed",
        "source_evidence_id": source_id,
        "source_type": family,
        "property": prop,
        "keyframes": values,
    }


def _run_carrier_fallback(
    project: Any,
    timeline: Any,
    payload: Dict[str, Any],
    selected: Sequence[Dict[str, Any]],
    bound: Sequence[Tuple[Dict[str, Any], Any]],
) -> List[Dict[str, Any]]:
    if any(get_fusion_comp(item) is not None for _, item in bound):
        raise RuntimeError("caption_carrier_mixed_source_representation")
    styles = _carrier_static_styles(
        _repository_path(payload["static_fcpxml_path"]),
        selected,
        int(payload["frame_width"]),
    )
    original_opacity = [(item, _item_opacity(item)) for _, item in bound]
    if any(abs(value - 100.0) > 1e-5 for _, value in original_opacity):
        raise RuntimeError("caption_source_opacity_precondition")
    carrier_track = int(payload["carrier_track_index"])
    try:
        existing_tracks = int(timeline.GetTrackCount("video") or 0)
    except Exception as exc:
        raise RuntimeError("caption_carrier_track_count") from exc
    if existing_tracks >= carrier_track and _caption_items(timeline, carrier_track):
        raise RuntimeError("caption_carrier_track_not_empty")
    source = _find_carrier_source(timeline, max(int(row["duration_frames"]) for row in selected))
    pool = project.GetMediaPool()
    if pool is None:
        raise RuntimeError("caption_carrier_media_pool")

    created: List[Any] = []
    added_track = False
    prepared: List[Tuple[Dict[str, Any], Any, Any, Any, Dict[str, Any], Dict[str, Any]]] = []
    try:
        added_track = _ensure_carrier_track(timeline, carrier_track)
        for row in selected:
            item = _append_carrier(pool, timeline, source, row, carrier_track)
            created.append(item)
            comp, tool = _create_textplus(item)
            static_readback = _apply_static_style(tool, styles[str(row["cue_id"])])
            animation = _runtime_animation(row, tool)
            validated_animation_targets(tool, animation, int(row["duration_frames"]))
            prepared.append((row, item, comp, tool, animation, static_readback))

        results = []
        for row, item, comp, tool, animation, static_readback in prepared:
            applied = apply_authorized_animation(comp, tool, animation, int(row["duration_frames"]))
            results.append({
                "cue_id": row["cue_id"],
                "name": row["name"],
                "start_frame": row["start_frame"],
                "end_frame": row["end_frame"],
                "animation_type": animation["source_type"],
                "source_evidence_id": animation["source_evidence_id"],
                "carrier": "media_backed_fusion_textplus",
                "static_contract": static_readback,
                **applied,
            })
        for _, source_item in bound:
            _set_item_opacity(source_item, 0.0)
        return results
    except Exception:
        for item, opacity in original_opacity:
            try:
                _set_item_opacity(item, opacity)
            except Exception:
                pass
        owned = list(_caption_items(timeline, carrier_track)) if existing_tracks < carrier_track else created
        if owned:
            try:
                timeline.DeleteClips(owned, False)
            except Exception:
                pass
        if added_track:
            try:
                timeline.DeleteTrack("video", carrier_track)
            except Exception:
                pass
        raise


def run(resolve: Any = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = _required_payload(context)
    plan_path = _repository_path(payload["animation_plan_path"])
    plan = load_json(plan_path)
    selected = _selected_plan_items(plan)
    requested_cues = payload.get("caption_cue_ids")
    if requested_cues is not None:
        if not isinstance(requested_cues, list) or not requested_cues or len(requested_cues) != len(set(map(str, requested_cues))):
            raise ValueError("caption_cue_ids")
        requested = {str(value) for value in requested_cues}
        available = {str(row.get("cue_id") or "") for row in selected}
        if not requested <= available:
            raise ValueError("caption_cue_ids_not_selected")
        selected = [row for row in selected if str(row.get("cue_id") or "") in requested]
    expected_count = as_int(payload["expected_caption_count"])
    track_index = as_int(payload["caption_track_index"])
    if expected_count is None or expected_count <= 0 or track_index is None or track_index <= 0:
        raise ValueError("caption_contract_counts")
    if int((plan.get("summary") or {}).get("v3_item_count") or 0) != expected_count:
        raise ValueError("animation_plan_caption_count")
    if payload.get("expected_selected_caption_count") is not None and int(payload["expected_selected_caption_count"]) != len(selected):
        raise ValueError("animation_plan_selected_count")
    if payload.get("expected_static_untouched_count") is not None and int(payload["expected_static_untouched_count"]) != expected_count - len(selected):
        raise ValueError("animation_plan_static_count")

    resolve_app = resolve if resolve is not None else get_resolve()
    manager = resolve_app.GetProjectManager()
    project = manager.GetCurrentProject()
    if project is None:
        raise RuntimeError("resolve_project_missing")
    expected_project = str(payload.get("expected_project") or "")
    if expected_project and str(project.GetName() or "") != expected_project:
        raise ValueError("resolve_project_identity")
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("resolve_timeline_missing")
    if safe_name(timeline) != str(payload["target_timeline_name"]):
        raise ValueError("resolve_timeline_name")
    if _timeline_uid(timeline) != str(payload["target_timeline_uid"]):
        raise ValueError("resolve_timeline_uid")

    captions = _caption_items(timeline, track_index)
    if len(captions) != expected_count:
        raise ValueError("resolve_caption_count")
    bound = _bind_plan_items(captions, selected)
    track_before = scan_tracks(timeline)
    direct = [(row, item, get_fusion_comp(item)) for row, item in bound]
    use_carrier = all(comp is None for _, _, comp in direct)
    if use_carrier:
        if payload.get("carrier_fallback") is not True:
            raise RuntimeError("caption_carrier_fallback_not_authorized")
        results = _run_carrier_fallback(project, timeline, payload, selected, bound)
        carrier_track = int(payload["carrier_track_index"])
    elif any(comp is None for _, _, comp in direct):
        raise RuntimeError("caption_mixed_carrier_representation")
    else:
        results = []
        carrier_track = track_index
    prepared = []

    # Validate every selected payload before the first mutation.
    for row, item, comp in ([] if use_carrier else direct):
        tool = get_text_tool(comp) if comp else None
        if comp is None or tool is None:
            raise RuntimeError(f"caption_textplus_missing:{row.get('cue_id')}")
        animation = _runtime_animation(row, tool)
        validated_animation_targets(tool, animation, int(row["duration_frames"]))
        prepared.append((row, item, comp, tool, animation, identity(tool, item)))

    for row, item, comp, tool, animation, before in prepared:
        result = apply_authorized_animation(
            comp,
            tool,
            animation,
            int(row["duration_frames"]),
        )
        results.append({
            "cue_id": row["cue_id"],
            "name": row.get("name"),
            "start_frame": row["start_frame"],
            "end_frame": row["end_frame"],
            "animation_type": animation["source_type"],
            "source_evidence_id": animation["source_evidence_id"],
            "identity_before": before,
            "identity_after": identity(tool, item),
            **result,
        })

    if payload.get("save_project") is not True or manager.SaveProject() is not True:
        raise RuntimeError("resolve_project_save_failed")
    timeline = project.GetCurrentTimeline()
    if (
        timeline is None
        or safe_name(timeline) != str(payload["target_timeline_name"])
        or _timeline_uid(timeline) != str(payload["target_timeline_uid"])
    ):
        raise RuntimeError("resolve_timeline_reacquire_failed")
    rebound = _bind_plan_items(_caption_items(timeline, carrier_track), selected)
    for result, (row, item) in zip(results, rebound):
        comp = get_fusion_comp(item)
        tool = get_text_tool(comp) if comp else None
        if tool is None:
            raise RuntimeError(f"caption_readback_missing:{result['cue_id']}")
        animation = _runtime_animation(row, tool)
        input_name, targets = validated_animation_targets(
            tool,
            animation,
            safe_end(item) - safe_start(item),
        )
        if not input_targets_are_correct(tool, input_name, targets):
            raise RuntimeError(f"caption_persistent_readback:{result['cue_id']}")
        result["identity_after"] = identity(tool, item)
        result["persistent_readback"] = True
    if not use_carrier and scan_tracks(timeline) != track_before:
        raise RuntimeError("timeline_structure_changed")
    if use_carrier:
        source_after = _caption_items(timeline, track_index)
        if len(source_after) != expected_count or any(_item_opacity(item) != 0.0 for _, item in _bind_plan_items(source_after, selected)):
            raise RuntimeError("caption_source_overlay_readback")
    else:
        protected = ("name", "start", "end", "text", "font", "style")
        for result in results:
            if any(result["identity_before"].get(key) != result["identity_after"].get(key) for key in protected):
                raise RuntimeError(f"caption_identity_changed:{result['cue_id']}")

    counts: Dict[str, int] = {}
    for result in results:
        family = result["animation_type"]
        counts[family] = counts.get(family, 0) + 1
    return {
        "ok": True,
        "workspace_version": WORKSPACE_VERSION,
        "video_id": payload["video_id"],
        "target_timeline_name": payload["target_timeline_name"],
        "target_timeline_uid": payload["target_timeline_uid"],
        "animation_plan_path": str(plan_path),
        "plan_hash": plan.get("plan_hash"),
        "selected_caption_count": len(results),
        "animation_family_counts": counts,
        "modified_count": sum(bool(row.get("modified")) for row in results),
        "already_correct_count": sum(bool(row.get("already_correct")) for row in results),
        "static_untouched_count": expected_count - len(results),
        "caption_identity_preserved": True,
        "timeline_structure_preserved": not use_carrier,
        "carrier_type": "media_backed_fusion_textplus_overlay" if use_carrier else "existing_fusion_textplus",
        "source_basic_titles_preserved": use_carrier,
        "items": results,
    }


def main() -> None:
    raise SystemExit("Run this adapter through one command-bound VC Agent task.")


if __name__ == "__main__" and os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1":
    main()
