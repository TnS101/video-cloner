"""Build and render the seven-window visual-first caption pilot.

The task consumes the locked Step 3D visual authority and uses only the proven
Resolve route:

    MediaPool.AppendToTimeline -> TimelineItem.ImportFusionComp

It duplicates the retained V6 Text+-only timeline, removes the 115 prior
transcript-first Text+ items from the duplicate, and creates exactly 17 pilot
Text+ instances on isolated tracks. The source timeline and accepted state are
read-only. On PASS the pilot timeline is retained in overlay state and three
review renders are produced for frames 176-692:

* source_only: original baked source captions, pilot Text+ disabled;
* generated_only: pilot Text+ on black, all source video items disabled;
* alignment_overlay: source and pilot Text+ enabled together.

No full-reel rollout is authorized by this task. Visual approval is required.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

V6_MODULE_PATH = Path(__file__).with_name("step_3D_full_lifecycle_textplus_rollout.py")
_spec = importlib.util.spec_from_file_location("vc_step3d_v6_for_visual_first_pilot", V6_MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{V6_MODULE_PATH}")
v6 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v6
_spec.loader.exec_module(v6)
visual = v6.visual
media = v6.media
base = v6.base

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_RESOLVE_PILOT_V1"
MODE = "STEP_3D_VISUAL_FIRST_RESOLVE_PILOT"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete_v6_textplus_only"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_pilot_v1"
AUTHORITY_TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3"
AUTHORITY_MANIFEST_RELATIVE_PATH = (
    "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3/"
    "visual_authority_script_renderability_v3.json"
)
AUTHORITY_VALIDATION_RELATIVE_PATH = (
    "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3/"
    "script_renderability_validation.json"
)
V6_TASK_ID = "DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6"
V6_RUN_ID = "20260806T143907620439Z_857f371ddfb146d7ac136f9087f7d96d"
V6_COMP_EXPORT_ROOT = (
    f".agent/reports/{V6_TASK_ID}/{V6_RUN_ID}/source_comp_exports"
)
TEMPLATE_COMP_RELATIVE_PATH = f"{V6_COMP_EXPORT_ROOT}/sub_018.comp"
ACCEPTED_STATE_RELATIVE_PATH = v6.ACCEPTED_STATE_RELATIVE_PATH
SOURCE_HASH_ALGORITHM = v6.SOURCE_HASH_ALGORITHM
EXPECTED_SOURCE_TEXTPLUS_COUNT = 115
EXPECTED_GROUP_COUNT = 7
EXPECTED_TOKEN_COUNT = 17
EXPECTED_VISUAL_ONLY_COUNT = 2
PILOT_TRACK_BASE = 8
EXPECTED_MAX_TRACK = PILOT_TRACK_BASE + EXPECTED_TOKEN_COUNT - 1
PILOT_NAME_PREFIX = "VC_VISUAL_FIRST_PILOT_"
RENDER_FRAME_IN = 176
RENDER_FRAME_OUT = 692
EXPECTED_RENDER_FRAME_COUNT = RENDER_FRAME_OUT - RENDER_FRAME_IN + 1
RENDER_WIDTH = 540
RENDER_HEIGHT = 960
RENDER_TIMEOUT_SECONDS = 900.0
RENDER_POLL_SECONDS = 0.25
APPEND_BATCH_SIZE = 6
POINT_TOLERANCE = 0.003
SCALAR_TOLERANCE = 1e-5

FONT_CLASS_MAP: Dict[str, Dict[str, str]] = {
    "heavy_geometric_sans": {
        "font_family": "Clash Grotesk Variable",
        "font_style": "Bold",
        "authority": "existing_selected_font_mapping_and_source_comp_exports",
    },
    "high_contrast_script": {
        "font_family": "Gabriola",
        "font_style": "Regular",
        "authority": "windows_installed_renderable_candidate_pending_visual_approval",
    },
}

# Visual-only decorations have no transcript cue. Their absolute Text+ base
# size is anchored to the source comp size of the primary word in the same
# reviewed composition; the locked size_path remains the animation multiplier.
DECORATION_BASE_CUE = {
    "vf_02_decorative_glyph": "sub_018",
    "vf_05_decorative_glyph": "sub_076",
}


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def hex_rgb(value: str) -> List[float]:
    text = str(value or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        raise ValueError(f"hex_color:{value}")
    return [int(text[index:index + 2], 16) / 255.0 for index in (1, 3, 5)]


def fusion_center(value: Sequence[Any]) -> List[float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("position")
    x = float(value[0])
    y_top = float(value[1])
    if not (0.0 <= x <= 1.0 and 0.0 <= y_top <= 1.0):
        raise ValueError("position_range")
    return [x, 1.0 - y_top]


def parse_comp_base_size(path: Path) -> float:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    static = re.search(r"\bSize\s*=\s*Input\s*\{\s*Value\s*=\s*([0-9.]+)", text)
    if static:
        value = float(static.group(1))
        if value > 0.0:
            return value
    spline = re.search(r"\[0\]\s*=\s*\{\s*([0-9.]+)", text)
    if spline:
        value = float(spline.group(1))
        if value > 0.0:
            return value
    raise ValueError(f"comp_base_size:{path}")


def token_source_cue(token: Mapping[str, Any]) -> Optional[str]:
    links = token.get("transcript_links") if isinstance(token.get("transcript_links"), list) else []
    cue_ids = [str(row.get("cue_id") or "") for row in links if isinstance(row, Mapping)]
    cue_ids = [value for value in cue_ids if value]
    if len(cue_ids) > 1:
        raise ValueError(f"multiple_cues:{token.get('visual_token_id')}")
    return cue_ids[0] if cue_ids else None


def flatten_authority(authority: Mapping[str, Any], root: Path) -> List[Dict[str, Any]]:
    if authority.get("task_id") != AUTHORITY_TASK_ID or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    next_boundary = authority.get("next_boundary") if isinstance(authority.get("next_boundary"), Mapping) else {}
    if summary.get("group_count") != EXPECTED_GROUP_COUNT:
        raise ValueError("authority_group_count")
    if summary.get("visual_token_count") != EXPECTED_TOKEN_COUNT:
        raise ValueError("authority_token_count")
    if summary.get("unresolved_component_count") != 0 or summary.get("placeholder_count") != 0:
        raise ValueError("authority_unresolved")
    if summary.get("transcript_timing_promoted_count") != 0:
        raise ValueError("transcript_timing_promoted")
    if summary.get("visual_text_correction_count") != 1:
        raise ValueError("authority_visual_text_correction_count")
    if summary.get("provisional_script_font_candidate_count") != 2:
        raise ValueError("authority_script_font_candidate_count")
    if next_boundary.get("resolve_action_allowed") is not True or next_boundary.get("scope") != "seven_windows_only":
        raise ValueError("authority_boundary")
    if next_boundary.get("full_rollout_allowed") is not False:
        raise ValueError("full_rollout_authorized")

    groups = authority.get("groups") if isinstance(authority.get("groups"), list) else []
    rows: List[Dict[str, Any]] = []
    global_index = 0
    for group in groups:
        if not isinstance(group, Mapping):
            raise ValueError("authority_group")
        group_id = str(group.get("group_id") or "")
        group_window = [int(value) for value in group.get("group_window") or []]
        tokens = group.get("tokens") if isinstance(group.get("tokens"), list) else []
        ordered = sorted(tokens, key=lambda token: (int(token.get("z_order") or 0), str(token.get("visual_token_id") or "")))
        for token in ordered:
            token_id = str(token.get("visual_token_id") or "")
            display_text = str(token.get("display_text") or "")
            visual_window = [int(value) for value in token.get("visual_window") or []]
            if len(visual_window) != 2 or visual_window[1] <= visual_window[0]:
                raise ValueError(f"visual_window:{token_id}")
            if not (group_window[0] <= visual_window[0] < visual_window[1] <= group_window[1]):
                raise ValueError(f"visual_window_group:{token_id}")
            style_lock = token.get("style_lock") if isinstance(token.get("style_lock"), Mapping) else {}
            font_class = str(style_lock.get("font_class") or "")
            if font_class not in FONT_CLASS_MAP:
                raise ValueError(f"font_class:{token_id}:{font_class}")
            explicit_family = str(style_lock.get("font_family") or "")
            explicit_style = str(style_lock.get("font_style") or "")
            if bool(explicit_family) != bool(explicit_style):
                raise ValueError(f"font_override_incomplete:{token_id}")
            if explicit_family:
                font = {
                    "font_family": explicit_family,
                    "font_style": explicit_style,
                    "authority": str(style_lock.get("font_resolution_status") or "explicit_authority_font"),
                }
            else:
                font = dict(FONT_CLASS_MAP[font_class])
            source_cue = token_source_cue(token)
            base_cue = source_cue or DECORATION_BASE_CUE.get(token_id)
            if not base_cue:
                raise ValueError(f"base_cue:{token_id}")
            source_comp = root / V6_COMP_EXPORT_ROOT / f"{base_cue}.comp"
            if not source_comp.is_file():
                raise ValueError(f"source_comp_missing:{base_cue}")
            base_size = parse_comp_base_size(source_comp)
            target_track = PILOT_TRACK_BASE + global_index
            name = f"{PILOT_NAME_PREFIX}{token_id}"
            position_keys = [
                {
                    "timeline_frame": int(row["timeline_frame"]),
                    "local_frame": int(row["timeline_frame"]) - visual_window[0],
                    "value": fusion_center(row["value"]),
                    "source_top_origin_value": [float(row["value"][0]), float(row["value"][1])],
                }
                for row in token.get("position_path") or []
            ]
            size_keys = [
                {
                    "timeline_frame": int(row["timeline_frame"]),
                    "local_frame": int(row["timeline_frame"]) - visual_window[0],
                    "scale": float(row["value"]),
                    "value": base_size * float(row["value"]),
                }
                for row in token.get("size_path") or []
            ]
            opacity_keys = [
                {
                    "timeline_frame": int(row["timeline_frame"]),
                    "local_frame": int(row["timeline_frame"]) - visual_window[0],
                    "factor": float(row["value"]),
                }
                for row in token.get("opacity_path") or []
            ]
            if not position_keys or not size_keys or not opacity_keys:
                raise ValueError(f"animation_keys:{token_id}")
            rows.append(
                {
                    "group_id": group_id,
                    "group_label": str(group.get("label") or ""),
                    "group_window": group_window,
                    "visual_token_id": token_id,
                    "visual_kind": str(token.get("visual_kind") or ""),
                    "display_text": display_text,
                    "text_authority": str(token.get("text_authority") or ""),
                    "source_cue_id": source_cue,
                    "base_size_cue_id": base_cue,
                    "base_size": base_size,
                    "visual_window": visual_window,
                    "target_range": visual_window,
                    "target_track": target_track,
                    "target_name": name,
                    "z_order": int(token.get("z_order") or 0),
                    "role": str(token.get("role") or ""),
                    "font": font,
                    "style_lock": dict(style_lock),
                    "position_keys": position_keys,
                    "size_keys": size_keys,
                    "opacity_keys": opacity_keys,
                    "animation_phases": dict(token.get("animation_phases") or {}),
                    "transcript_timing_promoted_to_authority": False,
                }
            )
            global_index += 1
    if len(rows) != EXPECTED_TOKEN_COUNT:
        raise ValueError(f"token_count:{len(rows)}")
    if len({row["target_name"] for row in rows}) != EXPECTED_TOKEN_COUNT:
        raise ValueError("target_name_duplicate")
    if len({row["target_track"] for row in rows}) != EXPECTED_TOKEN_COUNT:
        raise ValueError("target_track_duplicate")
    if sum(1 for row in rows if row["visual_kind"] == "visual_only_text_decoration") != EXPECTED_VISUAL_ONLY_COUNT:
        raise ValueError("visual_only_count")
    return rows


def chunked(rows: Sequence[Dict[str, Any]], size: int = APPEND_BATCH_SIZE) -> List[List[Dict[str, Any]]]:
    return [list(rows[index:index + size]) for index in range(0, len(rows), size)]


def timeline_inventory(timeline: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for track, item in base.all_video_items(timeline):
        row = base.item_summary(track, item)
        row["clip_enabled"] = base.json_safe(base.safe_value(item, "GetClipEnabled", default=None))
        rows.append(row)
    return sorted(rows, key=lambda row: (int(row["track_index"]), int(row["start"]), str(row["name"])))


def stable_inventory(rows: Sequence[Mapping[str, Any]]) -> List[Tuple[Any, ...]]:
    fields = ("name", "track_index", "start", "end", "duration", "media_pool_item_name", "fusion_comp_count")
    return sorted(tuple(row.get(field) for field in fields) for row in rows)


def target_items(timeline: Any, plans: Sequence[Mapping[str, Any]]) -> Dict[str, Tuple[int, Any]]:
    wanted = {str(row["target_name"]) for row in plans}
    found: Dict[str, Tuple[int, Any]] = {}
    for track, item in base.all_video_items(timeline):
        name = base.item_name(item)
        if name in wanted:
            if name in found:
                raise RuntimeError(f"duplicate_target:{name}")
            found[name] = (track, item)
    return found


def static_value_matches(input_name: str, actual: Any, expected: Any) -> bool:
    if input_name in {"StyledText", "Font", "Style"}:
        return str(actual or "") == str(expected)
    try:
        return abs(float(actual) - float(expected)) <= 1e-4
    except (TypeError, ValueError):
        return False


def set_static_input(text_tool: Any, input_name: str, value: Any) -> Dict[str, Any]:
    attempts = []
    try:
        returned = text_tool.SetInput(input_name, value)
        actual = base.read_input(text_tool, input_name, 0)
        matched = static_value_matches(input_name, actual, value)
        attempts.append(
            {
                "returned": base.json_safe(returned),
                "actual": base.json_safe(actual),
                "matched": matched,
            }
        )
        return {"ok": matched, "attempts": attempts}
    except BaseException as exc:
        attempts.append({"error": base.compact_exception(exc)})
        return {"ok": False, "attempts": attempts}


def set_static_inputs(text_tool: Any, values: Mapping[str, Any]) -> Dict[str, Any]:
    rows = []
    for input_name, value in values.items():
        result = set_static_input(text_tool, input_name, value)
        rows.append({"input": input_name, "value": base.json_safe(value), "result": result, "ok": result.get("ok") is True})
    return {"rows": rows, "ok": all(row["ok"] for row in rows)}


def write_scalar_series(text_tool: Any, input_name: str, keys: Sequence[Mapping[str, Any]], value_key: str) -> Dict[str, Any]:
    rows = []
    for key in keys:
        result = visual.write_key(text_tool, input_name, int(key["local_frame"]), float(key[value_key]))
        rows.append({"input": input_name, "key": dict(key), "result": result, "ok": result.get("ok") is True})
    return {"input": input_name, "rows": rows, "ok": all(row["ok"] for row in rows)}


def static_input_policy(plan: Mapping[str, Any]) -> Dict[str, Any]:
    style_lock = plan["style_lock"]
    fill = hex_rgb(str(style_lock["fill"]))
    stroke = style_lock.get("stroke") if isinstance(style_lock.get("stroke"), Mapping) else {}
    if stroke.get("enabled") is not False:
        raise ValueError(f"stroke_policy:{plan.get('visual_token_id')}")
    shadow = style_lock.get("shadow") if isinstance(style_lock.get("shadow"), Mapping) else {}
    shadow_enabled = shadow.get("enabled") is True and float(shadow.get("opacity") or 0.0) > 0.0
    values: Dict[str, Any] = {
        "StyledText": str(plan["display_text"]),
        "Font": str(plan["font"]["font_family"]),
        "Style": str(plan["font"]["font_style"]),
        "Red1": fill[0],
        "Green1": fill[1],
        "Blue1": fill[2],
        "Alpha1": 1.0,
        # Layer 2 is disabled for every locked pilot token. Resolve's Text+
        # template clamps Thickness2 to 0.03125 and does not expose Opacity2,
        # so those dependent values are deliberately not written or verified.
        "Enabled2": 0.0,
        "Enabled3": 1.0 if shadow_enabled else 0.0,
        "VerticalJustificationNew": 3.0,
        "HorizontalJustificationNew": 3.0,
    }
    skipped_inputs = ["Thickness2", "Opacity2"]
    if shadow_enabled:
        shadow_rgb = hex_rgb(str(shadow.get("color") or "#000000"))
        values.update(
            {
                "Red3": shadow_rgb[0],
                "Green3": shadow_rgb[1],
                "Blue3": shadow_rgb[2],
                "Opacity3": float(shadow.get("opacity") or 0.0),
            }
        )
    else:
        skipped_inputs.extend(["Red3", "Green3", "Blue3", "Opacity3"])
    return {
        "values": values,
        "stroke_disabled": True,
        "shadow_enabled": shadow_enabled,
        "skipped_inputs": skipped_inputs,
    }


def apply_token(item: Any, plan: Mapping[str, Any]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    text_tool = base.get_text_tool(comp)
    if comp is None or text_tool is None:
        return {"ok": False, "error": "comp_or_text_tool"}
    duration = int(plan["target_range"][1]) - int(plan["target_range"][0])
    comp_range = visual.extend_comp_range(comp, text_tool, duration - 1)
    static_policy = static_input_policy(plan)
    static_result = set_static_inputs(text_tool, static_policy["values"])
    center_result = visual.apply_center_series(text_tool, plan["position_keys"])
    size_modifier = visual.ensure_modifier(text_tool, "Size", "BezierSpline")
    size_result = (
        write_scalar_series(text_tool, "Size", plan["size_keys"], "value")
        if size_modifier.get("ok")
        else {"input": "Size", "rows": [], "ok": False, "error": "size_modifier"}
    )
    opacity_result = visual.apply_opacity_series(text_tool, plan["opacity_keys"])
    return {
        "comp_range": comp_range,
        "static_policy": static_policy,
        "static": static_result,
        "center": center_result,
        "size_modifier": size_modifier,
        "size": size_result,
        "opacity": opacity_result,
        "ok": bool(
            comp_range.get("ok")
            and static_result.get("ok")
            and center_result.get("ok")
            and size_modifier.get("ok")
            and size_result.get("ok")
            and opacity_result.get("ok")
        ),
    }


def application_failure_stage(application: Mapping[str, Any]) -> str:
    for stage in ("comp_range", "static", "center", "size_modifier", "size", "opacity"):
        value = application.get(stage)
        if isinstance(value, Mapping) and value.get("ok") is not True:
            return stage
    return "unknown"


def scalar_matches(actual: Any, expected: float, tolerance: float = SCALAR_TOLERANCE) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def read_token(item: Any, plan: Mapping[str, Any]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    text_tool = base.get_text_tool(comp)
    track = int(base.item_track_index(plan.get("timeline"), item) or 0) if plan.get("timeline") is not None else 0
    summary = base.item_summary(track, item)
    rows: Dict[str, Any] = {
        "summary": summary,
        "fusion_comp_count": base.as_int(base.safe_value(item, "GetFusionCompCount", default=0), 0),
        "text": base.text_readback(text_tool) if text_tool is not None else "",
        "font": base.json_safe(base.read_input(text_tool, "Font", 0)) if text_tool is not None else None,
        "style": base.json_safe(base.read_input(text_tool, "Style", 0)) if text_tool is not None else None,
        "position_keys": [],
        "size_keys": [],
        "opacity_keys": [],
    }
    for key in plan["position_keys"]:
        actual = base.read_input(text_tool, "Center", int(key["local_frame"])) if text_tool is not None else None
        rows["position_keys"].append({"key": dict(key), "actual": base.json_safe(actual), "matched": base.point_matches(actual, key["value"], POINT_TOLERANCE)})
    for key in plan["size_keys"]:
        actual = base.read_input(text_tool, "Size", int(key["local_frame"])) if text_tool is not None else None
        rows["size_keys"].append({"key": dict(key), "actual": base.json_safe(actual), "matched": scalar_matches(actual, key["value"])})
    for key in plan["opacity_keys"]:
        actual = base.read_input(text_tool, "Opacity1", int(key["local_frame"])) if text_tool is not None else None
        rows["opacity_keys"].append({"key": dict(key), "actual": base.json_safe(actual), "matched": scalar_matches(actual, key["factor"])})
    expected_range = [int(value) for value in plan["target_range"]]
    rows["checks"] = {
        "track": summary.get("track_index") == int(plan["target_track"]),
        "range": [summary.get("start"), summary.get("end")] == expected_range,
        "duration": summary.get("duration") == expected_range[1] - expected_range[0],
        "comp": rows["fusion_comp_count"] == 1,
        "text": rows["text"] == str(plan["display_text"]),
        "font": str(rows["font"] or "") == str(plan["font"]["font_family"]),
        "style": str(rows["style"] or "") == str(plan["font"]["font_style"]),
        "position": all(row["matched"] for row in rows["position_keys"]),
        "size": all(row["matched"] for row in rows["size_keys"]),
        "opacity": all(row["matched"] for row in rows["opacity_keys"]),
    }
    rows["ok"] = all(rows["checks"].values())
    return rows


def render_codec_score(extension: str, description: str, value: str) -> int:
    text = f"{description} {value}".lower().replace(".", "")
    score = 0
    if extension == "mp4":
        score += 500
    elif extension == "mov":
        score += 300
    if "h264" in text or "avc" in text:
        score += 400
    if "nvidia" in text:
        score += 25
    if "native" in text:
        score += 20
    return score


def select_review_video_format(formats: Mapping[str, Any], codecs_by_format: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for render_format, raw_extension in formats.items():
        extension = str(raw_extension or "").lower().lstrip(".")
        if extension not in {"mp4", "mov"}:
            continue
        codecs = codecs_by_format.get(str(render_format)) or {}
        if not isinstance(codecs, Mapping):
            continue
        for description, codec in codecs.items():
            score = render_codec_score(extension, str(description), str(codec))
            if score < 400:
                continue
            candidates.append({
                "format": str(render_format),
                "extension": extension,
                "codec_description": str(description),
                "codec": str(codec),
                "score": score,
            })
    candidates.sort(key=lambda row: (-int(row["score"]), str(row["format"]), str(row["codec_description"])))
    return {"ok": bool(candidates), "selected": candidates[0] if candidates else None, "candidates": candidates}


def timeline_dimensions(timeline: Any, project: Any) -> Dict[str, Any]:
    raw_rate = base.safe_value(timeline, "GetSetting", "timelineFrameRate", default=None)
    if raw_rate in (None, ""):
        raw_rate = base.safe_value(project, "GetSetting", "timelineFrameRate", default=30)
    try:
        frame_rate = float(str(raw_rate).split()[0])
    except (TypeError, ValueError):
        frame_rate = 30.0
    return {"width": RENDER_WIDTH, "height": RENDER_HEIGHT, "frame_rate": frame_rate}


def render_settings(output_dir: Path, custom_name: str, dimensions: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "SelectAllFrames": False,
        "MarkIn": RENDER_FRAME_IN,
        "MarkOut": RENDER_FRAME_OUT,
        "TargetDir": str(output_dir),
        "CustomName": custom_name,
        "UniqueFilenameStyle": 1,
        "ExportVideo": True,
        "ExportAudio": False,
        "FormatWidth": int(dimensions["width"]),
        "FormatHeight": int(dimensions["height"]),
        "FrameRate": float(dimensions["frame_rate"]),
        "PixelAspectRatio": "square",
        "ReplaceExistingFilesInPlace": True,
    }


REQUIRED_RENDER_SETTING_GROUPS = (
    ("destination", ("TargetDir", "CustomName")),
    ("range", ("SelectAllFrames", "MarkIn", "MarkOut")),
    ("streams", ("ExportVideo", "ExportAudio")),
)
OPTIONAL_RENDER_SETTING_GROUPS = (
    ("filename_style", ("UniqueFilenameStyle",)),
    ("dimensions", ("FormatWidth", "FormatHeight")),
    ("frame_rate", ("FrameRate",)),
    ("pixel_aspect", ("PixelAspectRatio",)),
    ("replacement", ("ReplaceExistingFilesInPlace",)),
)


def apply_render_settings(project: Any, settings: Mapping[str, Any]) -> Dict[str, Any]:
    calls: List[Dict[str, Any]] = []
    required_rows: List[Dict[str, Any]] = []
    optional_rows: List[Dict[str, Any]] = []
    effective: Dict[str, Any] = {}

    for group_name, keys in REQUIRED_RENDER_SETTING_GROUPS:
        payload = {key: settings[key] for key in keys}
        value, call = base.direct_call(project, "SetRenderSettings", payload)
        calls.append(call)
        row = {
            "group": group_name,
            "required": True,
            "settings": payload,
            "accepted": bool(value),
            "call": call,
        }
        required_rows.append(row)
        if not value:
            return {
                "ok": False,
                "failed_group": group_name,
                "required": required_rows,
                "optional": optional_rows,
                "effective_settings": effective,
                "calls": calls,
            }
        effective.update(payload)

    for group_name, keys in OPTIONAL_RENDER_SETTING_GROUPS:
        payload = {key: settings[key] for key in keys}
        value, call = base.direct_call(project, "SetRenderSettings", payload)
        calls.append(call)
        accepted = bool(value)
        optional_rows.append({
            "group": group_name,
            "required": False,
            "settings": payload,
            "accepted": accepted,
            "call": call,
        })
        if accepted:
            effective.update(payload)

    return {
        "ok": True,
        "failed_group": None,
        "required": required_rows,
        "optional": optional_rows,
        "effective_settings": effective,
        "calls": calls,
    }


def configure_review_render(
    project: Any,
    settings: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []

    for candidate in candidates:
        selected = dict(candidate)
        value, format_call = base.direct_call(
            project,
            "SetCurrentRenderFormatAndCodec",
            selected["format"],
            selected["codec"],
        )
        calls.append(format_call)
        attempt: Dict[str, Any] = {
            "selection": selected,
            "format_call": format_call,
            "format_ok": bool(value),
            "settings": None,
            "ok": False,
        }
        if not value:
            attempts.append(attempt)
            continue

        value, mode_call = base.direct_call(project, "SetCurrentRenderMode", 1)
        calls.append(mode_call)
        attempt["mode_call"] = mode_call
        attempt["mode_ok"] = bool(value)
        if not value:
            attempts.append(attempt)
            continue

        setting_result = apply_render_settings(project, settings)
        calls.extend(setting_result["calls"])
        attempt["settings"] = setting_result
        attempt["ok"] = bool(setting_result.get("ok"))
        attempts.append(attempt)
        if attempt["ok"]:
            return {
                "ok": True,
                "selection": selected,
                "settings": setting_result,
                "attempts": attempts,
                "calls": calls,
            }

    return {
        "ok": False,
        "selection": None,
        "settings": None,
        "attempts": attempts,
        "calls": calls,
    }


def status_text(status: Any) -> str:
    if not isinstance(status, Mapping):
        return ""
    for key in ("JobStatus", "jobStatus", "Status", "status"):
        if status.get(key) is not None:
            return str(status.get(key)).strip().lower()
    return ""


def render_attempt_dir(output_dir: Path, attempt_index: int, candidate: Mapping[str, Any]) -> Path:
    codec = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(candidate.get("codec") or "codec")).strip("._") or "codec"
    return output_dir / f"attempt_{attempt_index:02d}_{codec}"


def render_video(
    project: Any,
    timeline: Any,
    output_dir: Path,
    custom_name: str,
    candidates: Sequence[Mapping[str, Any]],
    dimensions: Mapping[str, Any],
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    calls: List[Dict[str, Any]] = []
    runtime_attempts: List[Dict[str, Any]] = []

    selected, call = base.direct_call(project, "SetCurrentTimeline", timeline)
    calls.append(call)
    if not selected:
        return {
            "ok": False,
            "timeline_name": base.timeline_name(timeline),
            "output_dir": str(output_dir),
            "candidate_count": len(candidates),
            "calls": calls,
            "runtime_attempts": runtime_attempts,
            "error": "RuntimeError: set_current_timeline",
        }

    for attempt_index, raw_candidate in enumerate(candidates, start=1):
        candidate = dict(raw_candidate)
        attempt_dir = render_attempt_dir(output_dir, attempt_index, candidate)
        attempt_dir.mkdir(parents=True, exist_ok=False)
        settings = render_settings(attempt_dir, custom_name, dimensions)
        configuration = configure_review_render(project, settings, [candidate])
        calls.extend(configuration["calls"])
        attempt: Dict[str, Any] = {
            "attempt_index": attempt_index,
            "selection": candidate,
            "output_dir": str(attempt_dir),
            "requested_settings": settings,
            "configuration": configuration,
            "job_id": "",
            "statuses": [],
            "file": None,
            "file_size": None,
            "file_sha256": None,
            "ok": False,
            "error": None,
        }
        runtime_attempts.append(attempt)

        if not configuration.get("ok"):
            attempt["error"] = "RuntimeError: configure_review_render"
            continue

        job_id = ""
        try:
            raw_job_id, call = base.direct_call(project, "AddRenderJob")
            calls.append(call)
            job_id = str(raw_job_id or "")
            attempt["job_id"] = job_id
            if not job_id:
                raise RuntimeError("add_render_job")

            value, call = base.direct_call(project, "StartRendering", job_id)
            calls.append(call)
            if not value:
                raise RuntimeError("start_rendering")

            deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS
            statuses: List[Dict[str, Any]] = []
            while time.monotonic() < deadline:
                raw_status = base.safe_value(project, "GetRenderJobStatus", job_id, default={})
                rendering = bool(base.safe_value(project, "IsRenderingInProgress", default=False))
                text = status_text(raw_status)
                if not statuses or statuses[-1].get("status_text") != text or statuses[-1].get("rendering") != rendering:
                    statuses.append({
                        "status": base.json_safe(raw_status),
                        "status_text": text,
                        "rendering": rendering,
                        "observed_at": base.utc_now(),
                    })
                if any(word in text for word in ("fail", "cancel", "error")):
                    raise RuntimeError(f"render_failed:{text}")
                if text in {"complete", "completed", "success", "succeeded"} and not rendering:
                    break
                time.sleep(RENDER_POLL_SECONDS)
            else:
                raise RuntimeError("render_timeout")

            attempt["statuses"] = statuses
            files = sorted(path for path in attempt_dir.glob(f"*.{candidate['extension']}") if path.is_file())
            if len(files) != 1 or files[0].stat().st_size <= 0:
                raise RuntimeError(f"render_files:{len(files)}")

            attempt["file"] = str(files[0])
            attempt["file_size"] = files[0].stat().st_size
            attempt["file_sha256"] = base.raw_sha256(files[0])
            attempt["ok"] = True
            return {
                "ok": True,
                "timeline_name": base.timeline_name(timeline),
                "output_dir": str(output_dir),
                "file": str(files[0]),
                "file_size": files[0].stat().st_size,
                "file_sha256": attempt["file_sha256"],
                "selection": candidate,
                "requested_settings": settings,
                "effective_settings": dict((configuration.get("settings") or {}).get("effective_settings") or {}),
                "configuration": configuration,
                "job_id": job_id,
                "statuses": statuses,
                "runtime_attempts": runtime_attempts,
                "calls": calls,
            }
        except BaseException as exc:
            attempt["error"] = base.compact_exception(exc)
            attempt["traceback"] = traceback.format_exc()
            if not attempt["statuses"] and job_id:
                raw_status = base.safe_value(project, "GetRenderJobStatus", job_id, default={})
                rendering = bool(base.safe_value(project, "IsRenderingInProgress", default=False))
                attempt["statuses"] = [{
                    "status": base.json_safe(raw_status),
                    "status_text": status_text(raw_status),
                    "rendering": rendering,
                    "observed_at": base.utc_now(),
                }]
            if bool(base.safe_value(project, "IsRenderingInProgress", default=False)):
                _, stop_call = base.direct_call(project, "StopRendering")
                calls.append(stop_call)
                attempt["stop_call"] = stop_call
        finally:
            if job_id:
                _, delete_call = base.direct_call(project, "DeleteRenderJob", job_id)
                calls.append(delete_call)
                attempt["delete_job_call"] = delete_call

    errors = [
        f"{row['selection'].get('format')}/{row['selection'].get('codec')}:{row.get('error')}"
        for row in runtime_attempts
    ]
    return {
        "ok": False,
        "timeline_name": base.timeline_name(timeline),
        "output_dir": str(output_dir),
        "selection": None,
        "candidate_count": len(candidates),
        "runtime_attempts": runtime_attempts,
        "calls": calls,
        "error": "RuntimeError: render_candidates_exhausted:" + "|".join(errors),
    }


def capture_enabled_states(timeline: Any) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for track, item in base.all_video_items(timeline):
        unique_id = base.item_unique_id(item) or f"{track}:{base.item_name(item)}:{base.item_start(item)}"
        rows[unique_id] = {
            "item": item,
            "name": base.item_name(item),
            "track": track,
            "enabled": base.safe_value(item, "GetClipEnabled", default=True) is not False,
        }
    return rows


def set_render_mode_items(states: Mapping[str, Mapping[str, Any]], target_names: Iterable[str], mode: str) -> Dict[str, Any]:
    targets = set(target_names)
    rows = []
    for identity, state in states.items():
        is_target = str(state["name"]) in targets
        if mode == "source_only":
            desired = False if is_target else bool(state["enabled"])
        elif mode == "generated_only":
            desired = True if is_target else False
        elif mode == "alignment_overlay":
            desired = True if is_target else bool(state["enabled"])
        else:
            raise ValueError(f"render_mode:{mode}")
        item = state["item"]
        value, call = base.direct_call(item, "SetClipEnabled", desired)
        actual = base.safe_value(item, "GetClipEnabled", default=None)
        ok = bool(value is not False and actual is desired)
        rows.append({"identity": identity, "name": state["name"], "track": state["track"], "is_target": is_target, "desired": desired, "actual": base.json_safe(actual), "call": call, "ok": ok})
    return {"mode": mode, "rows": rows, "ok": all(row["ok"] for row in rows)}


def cleanup_failure(resolve: Any, project_manager: Any, project: Any, media_pool: Any, original_timeline: Any, original_page: str, accepted_path: Path, accepted_hash: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        target = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if original_timeline is not None:
            value, call = base.direct_call(project, "SetCurrentTimeline", original_timeline)
            result["restore_timeline"] = call
            if not value:
                result["errors"].append("restore_timeline")
        if target is not None:
            value, call = base.direct_call(media_pool, "DeleteTimelines", [target])
            result["delete_target"] = call
            if not value:
                result["errors"].append("delete_target")
        if original_page:
            value, call = base.direct_call(resolve, "OpenPage", original_page)
            result["restore_page"] = call
            if not value:
                result["errors"].append("restore_page")
        save = base.save_project(project_manager)
        result["save"] = save
        result["save_call_count"] = 1
        if not save.get("success"):
            result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc))
        result["traceback"] = traceback.format_exc()
    result["target_deleted"] = base.find_timeline(project, TARGET_TIMELINE_NAME) is None
    result["accepted_state_unchanged"] = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
    result["ok"] = bool(not result["errors"] and result["target_deleted"] and result["accepted_state_unchanged"])
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if not run_id:
        raise ValueError("run_id")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")
    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "backend": "visual_authority_17_textplus_three_mode_review_render",
        "ok": False,
        "started_at": base.utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "failures": [],
        "save_call_count": 0,
        "target_timeline_kept": False,
        "visual_review_required": True,
    }
    project_manager = project = media_pool = None
    original_timeline = None
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    source_before: List[Dict[str, Any]] = []
    source_unique_id = ""
    original_render: Dict[str, Any] = {}
    target_created = False
    try:
        source_contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        report["source_contract_verified_count"] = source_contract["verified_count"]
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")

        authority = load_json(root / AUTHORITY_MANIFEST_RELATIVE_PATH)
        validation = load_json(root / AUTHORITY_VALIDATION_RELATIVE_PATH)
        if validation.get("ok") is not True:
            raise RuntimeError("authority_validation")
        plans = flatten_authority(authority, root)
        plan_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "authority_task_id": AUTHORITY_TASK_ID,
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "group_count": EXPECTED_GROUP_COUNT,
            "token_count": len(plans),
            "visual_only_count": sum(1 for row in plans if row["visual_kind"] == "visual_only_text_decoration"),
            "render_window": [RENDER_FRAME_IN, RENDER_FRAME_OUT],
            "transcript_timing_promoted_count": 0,
            "full_rollout_authorized": False,
            "instances": plans,
            "ok": True,
        }
        base.write_json(report_dir / "authority_plan.json", plan_document)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        original_timeline = base.safe_value(project, "GetCurrentTimeline", default=None)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_timeline_exists")
        source_unique_id = base.timeline_unique_id(source)
        source_before = timeline_inventory(source)
        source_textplus = [row for row in source_before if str(row["name"]).startswith("VC_TEXTPLUS_")]
        if len(source_textplus) != EXPECTED_SOURCE_TEXTPLUS_COUNT:
            raise RuntimeError(f"source_textplus_count:{len(source_textplus)}")
        max_duration = max(int(row["target_range"][1]) - int(row["target_range"][0]) for row in plans)
        carrier_source = base.choose_carrier_source(source, max_duration + 1)
        if not carrier_source.get("ok"):
            raise RuntimeError("carrier_source")

        formats = base.safe_value(project, "GetRenderFormats", default={}) or {}
        codecs_by_format: Dict[str, Mapping[str, Any]] = {}
        for render_format in formats:
            codecs_by_format[str(render_format)] = base.safe_value(project, "GetRenderCodecs", render_format, default={}) or {}
        selection = select_review_video_format(formats, codecs_by_format)
        if not selection.get("ok"):
            raise RuntimeError("review_video_format")
        selected_format = selection["selected"]
        dimensions = timeline_dimensions(source, project)
        original_render = {
            "format_codec": base.json_safe(base.safe_value(project, "GetCurrentRenderFormatAndCodec", default={})),
            "mode": base.safe_value(project, "GetCurrentRenderMode", default=None),
        }
        preflight = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "resolve_calls": resolve_calls,
            "original_page": original_page,
            "source_timeline_unique_id": source_unique_id,
            "source_inventory": source_before,
            "source_textplus_count": len(source_textplus),
            "authority_summary": authority.get("summary"),
            "carrier_source": {key: base.json_safe(value) for key, value in carrier_source.items() if key not in {"item", "media_pool_item"}},
            "render_selection": selection,
            "render_dimensions": dimensions,
            "original_render": original_render,
            "ok": True,
        }
        base.write_json(report_dir / "pilot_preflight.json", preflight)

        opened, open_call = base.direct_call(resolve, "OpenPage", "edit")
        if not opened:
            raise RuntimeError("open_edit")
        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected_target, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected_target:
            raise RuntimeError("select_target")
        target_before = timeline_inventory(target)
        if stable_inventory(target_before) != stable_inventory(source_before):
            raise RuntimeError("duplicate_inventory")
        old_textplus_items = [item for _, item in base.all_video_items(target) if base.item_name(item).startswith("VC_TEXTPLUS_")]
        deletion = base.delete_items(target, old_textplus_items)
        time.sleep(0.30)
        old_remaining = [base.item_name(item) for _, item in base.all_video_items(target) if base.item_name(item).startswith("VC_TEXTPLUS_")]
        track_setup = base.ensure_video_tracks(target, EXPECTED_MAX_TRACK)
        setup = {
            "open_edit_call": open_call,
            "duplicate_call": duplicate_call,
            "select_call": select_call,
            "source_target_inventory_equal_before_cleanup": stable_inventory(target_before) == stable_inventory(source_before),
            "old_textplus_delete": deletion,
            "old_textplus_count_before": len(old_textplus_items),
            "old_textplus_remaining": old_remaining,
            "track_setup": track_setup,
            "ok": bool(deletion.get("ok") and len(old_textplus_items) == EXPECTED_SOURCE_TEXTPLUS_COUNT and not old_remaining and track_setup.get("ok")),
        }
        base.write_json(report_dir / "duplicate_timeline_setup.json", setup)
        if not setup["ok"]:
            raise RuntimeError("duplicate_timeline_setup")

        specs = [
            {
                "cue_id": row["visual_token_id"],
                "name": row["target_name"],
                "text": row["display_text"],
                "target_range": row["target_range"],
                "target_track": row["target_track"],
            }
            for row in plans
        ]
        append_rows = []
        assigned: Dict[str, Any] = {}
        for batch_index, batch in enumerate(chunked(specs)):
            result = v6.append_batch_by_placement(media_pool, target, carrier_source, batch)
            append_rows.append({"batch_index": batch_index, "result": base.json_safe({key: value for key, value in result.items() if key != "assigned"}), "ok": result.get("ok") is True})
            if not result.get("ok"):
                raise RuntimeError(f"append_batch:{batch_index}")
            for spec, item in result["assigned"]:
                assigned[str(spec["cue_id"])] = item
        append_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "batch_count": len(append_rows),
            "requested_count": len(specs),
            "assigned_count": len(assigned),
            "batches": append_rows,
            "ok": len(assigned) == EXPECTED_TOKEN_COUNT and all(row["ok"] for row in append_rows),
        }
        base.write_json(report_dir / "carrier_append.json", append_document)
        if not append_document["ok"]:
            raise RuntimeError("carrier_append")

        template_path = root / TEMPLATE_COMP_RELATIVE_PATH
        application_rows = []
        application_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "template_comp": str(template_path),
            "expected_instance_count": EXPECTED_TOKEN_COUNT,
            "instance_count": 0,
            "complete": False,
            "rows": application_rows,
            "ok": False,
        }
        base.write_json(report_dir / "pilot_application.json", application_document)
        for plan in plans:
            item = assigned.get(plan["visual_token_id"])
            if item is None:
                raise RuntimeError(f"assigned_item:{plan['visual_token_id']}")
            clone = media.import_source_comp(item, template_path)
            application = apply_token(item, plan) if clone.get("ok") else {"ok": False, "error": "clone"}
            row = {
                "visual_token_id": plan["visual_token_id"],
                "target_name": plan["target_name"],
                "clone": clone,
                "application": application,
                "ok": bool(clone.get("ok") and application.get("ok")),
            }
            application_rows.append(row)
            application_document["instance_count"] = len(application_rows)
            application_document["rows"] = application_rows
            base.write_json(report_dir / "pilot_application.json", application_document)
            if not row["ok"]:
                stage = "clone" if not clone.get("ok") else application_failure_stage(application)
                raise RuntimeError(f"apply_token:{plan['visual_token_id']}:{stage}")
        application_document.update(
            {
                "instance_count": len(application_rows),
                "complete": True,
                "rows": application_rows,
                "ok": len(application_rows) == EXPECTED_TOKEN_COUNT and all(row["ok"] for row in application_rows),
            }
        )
        base.write_json(report_dir / "pilot_application.json", application_document)

        found = target_items(target, plans)
        readback_rows = []
        for plan in plans:
            track, item = found.get(plan["target_name"], (0, None))
            if item is None:
                readback_rows.append({"visual_token_id": plan["visual_token_id"], "ok": False, "error": "missing"})
                continue
            plan_for_readback = dict(plan)
            plan_for_readback["timeline"] = target
            row = read_token(item, plan_for_readback)
            row["visual_token_id"] = plan["visual_token_id"]
            row["target_name"] = plan["target_name"]
            readback_rows.append(row)
        readback = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "instance_count": len(readback_rows),
            "rows": readback_rows,
            "ok": len(readback_rows) == EXPECTED_TOKEN_COUNT and all(row.get("ok") for row in readback_rows),
        }
        base.write_json(report_dir / "pilot_readback_before_render.json", readback)
        if not readback["ok"]:
            raise RuntimeError("pilot_readback")

        states = capture_enabled_states(target)
        target_names = [row["target_name"] for row in plans]
        renders: Dict[str, Any] = {}
        mode_rows = []
        opened_deliver, deliver_call = base.direct_call(resolve, "OpenPage", "deliver")
        if not opened_deliver:
            raise RuntimeError("open_deliver")
        for mode_name in ("source_only", "generated_only", "alignment_overlay"):
            mode_result = set_render_mode_items(states, target_names, mode_name)
            mode_rows.append(mode_result)
            if not mode_result.get("ok"):
                raise RuntimeError(f"set_render_mode_items:{mode_name}")
            result = render_video(
                project,
                target,
                report_dir / f"render_{mode_name}",
                mode_name,
                selection["candidates"],
                dimensions,
            )
            base.write_json(report_dir / f"render_{mode_name}.json", result)
            renders[mode_name] = result
            if not result.get("ok"):
                raise RuntimeError(f"render:{mode_name}:{result.get('error')}")
        render_document = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "frame_range": [RENDER_FRAME_IN, RENDER_FRAME_OUT],
            "expected_frame_count": EXPECTED_RENDER_FRAME_COUNT,
            "selection": selected_format,
            "dimensions": dimensions,
            "open_deliver_call": deliver_call,
            "mode_state_changes": mode_rows,
            "renders": renders,
            "ok": all(result.get("ok") for result in renders.values()) and len(renders) == 3,
        }
        base.write_json(report_dir / "review_renders.json", render_document)
        if not render_document["ok"]:
            raise RuntimeError("review_renders")

        # Restore overlay mode and the prior render configuration before saving
        # the retained pilot. The pilot remains selected on the Edit page.
        overlay_restore = set_render_mode_items(states, target_names, "alignment_overlay")
        if not overlay_restore.get("ok"):
            raise RuntimeError("overlay_restore")
        original_fc = original_render.get("format_codec")
        if isinstance(original_fc, Mapping):
            render_format = original_fc.get("format") or original_fc.get("Format")
            codec = original_fc.get("codec") or original_fc.get("Codec")
            if render_format and codec:
                base.direct_call(project, "SetCurrentRenderFormatAndCodec", render_format, codec)
        if isinstance(original_render.get("mode"), int):
            base.direct_call(project, "SetCurrentRenderMode", int(original_render["mode"]))
        base.direct_call(project, "SetRenderSettings", {"SelectAllFrames": True})
        base.direct_call(project, "SetCurrentTimeline", target)
        base.direct_call(resolve, "OpenPage", "edit")
        save = base.save_project(project_manager)
        report["save_call_count"] = 1 if save.get("success") else 0
        if not save.get("success"):
            raise RuntimeError("save_pilot")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("timeline_reacquire")
        source_after_inventory = timeline_inventory(source_after)
        target_after_found = target_items(target_after, plans)
        persistent_rows = []
        for plan in plans:
            track, item = target_after_found.get(plan["target_name"], (0, None))
            if item is None:
                persistent_rows.append({"visual_token_id": plan["visual_token_id"], "ok": False, "error": "missing"})
                continue
            plan_for_readback = dict(plan)
            plan_for_readback["timeline"] = target_after
            row = read_token(item, plan_for_readback)
            row["visual_token_id"] = plan["visual_token_id"]
            row["target_name"] = plan["target_name"]
            persistent_rows.append(row)
        persistent_checks = {
            "source_timeline_unchanged": base.timeline_unique_id(source_after) == source_unique_id and stable_inventory(source_after_inventory) == stable_inventory(source_before),
            "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
            "target_retained": base.timeline_name(target_after) == TARGET_TIMELINE_NAME,
            "pilot_instance_count": len(persistent_rows) == EXPECTED_TOKEN_COUNT,
            "pilot_instances_exact": all(row.get("ok") for row in persistent_rows),
            "old_textplus_absent": not any(base.item_name(item).startswith("VC_TEXTPLUS_") for _, item in base.all_video_items(target_after)),
            "overlay_state": all(base.safe_value(item, "GetClipEnabled", default=None) is not False for _, item in target_after_found.values()),
            "review_renders": all(Path(str(renders[mode]["file"])).is_file() for mode in renders),
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "source_inventory_before": source_before,
            "source_inventory_after": source_after_inventory,
            "pilot_rows": persistent_rows,
            "checks": persistent_checks,
            "save": save,
            "ok": all(persistent_checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")

        report.update({
            "ok": True,
            "finished_at": base.utc_now(),
            "group_count": EXPECTED_GROUP_COUNT,
            "visual_token_count": EXPECTED_TOKEN_COUNT,
            "visual_only_component_count": EXPECTED_VISUAL_ONLY_COUNT,
            "transcript_timing_promoted_count": 0,
            "full_rollout_authorized": False,
            "pilot_tracks": [PILOT_TRACK_BASE, EXPECTED_MAX_TRACK],
            "pilot_instance_count": EXPECTED_TOKEN_COUNT,
            "source_textplus_removed_from_duplicate": EXPECTED_SOURCE_TEXTPLUS_COUNT,
            "review_render_count": 3,
            "review_render_frame_range": [RENDER_FRAME_IN, RENDER_FRAME_OUT],
            "source_timeline_unchanged": True,
            "accepted_state_unchanged": True,
            "target_timeline_kept": True,
            "target_timeline_unique_id": base.timeline_unique_id(target_after),
            "visual_review_required": True,
            "visual_review_instruction": (
                "Review the generated contact sheets and the three synchronized renders. "
                "Approve or reject each of the seven groups. Do not authorize the full rollout from technical PASS alone."
            ),
        })
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["error"] = base.compact_exception(exc)
        report["traceback"] = traceback.format_exc()
        if target_created and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_failure(resolve, project_manager, project, media_pool, original_timeline, original_page, accepted_path, accepted_hash)
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["save_call_count"] = cleanup.get("save_call_count", 0)
            report["target_timeline_kept"] = False
            if not cleanup.get("ok"):
                report["failures"].append("failure_cleanup")
        report["finished_at"] = base.utc_now()
    return report
