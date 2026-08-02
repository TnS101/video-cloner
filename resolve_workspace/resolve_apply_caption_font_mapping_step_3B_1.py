#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import traceback
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "resolve_caption_font_step_3B_1_v1_1_workspace_autorun_feedback"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_font_step_3B_1_config.json"
V3_ITEM_RE = re.compile(r"^VC_TEXTPLUS_(?P<index>\d+)_(?P<cue>.+)$", re.IGNORECASE)


def now_unix() -> float:
    return round(time.time(), 6)


def safe_call(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    if obj is None:
        return default
    fn = getattr(obj, method, None)
    if not callable(fn):
        return default
    try:
        return fn(*args)
    except Exception:
        return default


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    try:
        return str(value)
    except Exception:
        return repr(value)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def default_runtime_config() -> Dict[str, Any]:
    project_root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    analysis_dir = project_root / "data" / video_id / "analysis"
    davinci_dir = project_root / "data" / video_id / "davinci"
    return {
        "video_id": video_id,
        "font_mapping_path": str(analysis_dir / f"{video_id}_caption_font_mapping_step_3A_3.json"),
        "caption_style_path": str(analysis_dir / f"{video_id}_caption_style.json"),
        "output_report_path": str(davinci_dir / f"{video_id}_resolve_font_step_3B_1_report.json"),
        "workspace_status_path": str(davinci_dir / f"{video_id}_resolve_font_step_3B_1_workspace_status.json"),
        "workspace_launch_log_path": str(davinci_dir / f"{video_id}_resolve_font_step_3B_1_workspace.log"),
        "v3_track": 3,
        "v3_track_name": "VC_TEXTPLUS_V3",
        "item_prefix": "VC_TEXTPLUS_",
        "expected_v3_count": 116,
        "require_full_mapping": True,
        "allow_primary_fallback": False,
        "profile_aliases": {},
        "rollback_on_item_failure": True,
        "dry_run": False,
        "readback_delay_sec": 0.03,
        "preserve_inputs": ["StyledText", "Size", "Center"],
        "show_completion_message": True,
    }


def load_runtime_config(config_path: Path) -> Dict[str, Any]:
    config = default_runtime_config()
    if config_path.is_file():
        loaded = load_json(config_path)
        config.update(loaded)
    return config


def append_workspace_log(path: Path, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp_unix": now_unix(),
            "event": event,
            "version": VERSION,
            "module_name": globals().get("__name__"),
            "script_path": globals().get("__file__"),
        }
        if payload:
            row.update(json_safe(payload))
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def show_windows_message(title: str, message: str, is_error: bool = False) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        flags = 0x00000010 if is_error else 0x00000040
        ctypes.windll.user32.MessageBoxW(0, str(message), str(title), flags)
    except Exception:
        pass


def norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm_token(value: Any) -> str:
    return "".join(ch.lower() for ch in norm_text(value) if ch.isalnum())


def norm_pair(family: Any, face: Any) -> Tuple[str, str]:
    return norm_token(family), norm_token(face or "Regular")


def cue_number(value: Any) -> Optional[int]:
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def cue_key_variants(value: Any) -> List[str]:
    raw = norm_text(value)
    number = cue_number(raw)
    variants = []
    if raw:
        variants.append(raw.lower())
    if number is not None:
        variants.extend([
            str(number),
            f"sub_{number}",
            f"sub_{number:03d}",
            f"sub_{number:04d}",
        ])
    output = []
    seen = set()
    for row in variants:
        if row not in seen:
            seen.add(row)
            output.append(row)
    return output


def values_equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, str) or isinstance(actual, str):
        return norm_token(expected) == norm_token(actual)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= 1e-6
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        return len(expected) == len(actual) and all(values_equal(a, b) for a, b in zip(expected, actual))
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected) != set(actual):
            return False
        return all(values_equal(expected[k], actual[k]) for k in expected)
    return json_safe(expected) == json_safe(actual)


def resolve_config_path() -> Path:
    env_path = os.environ.get("VC_STEP_3B1_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()

    project_root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    candidates = [
        project_root / "data" / video_id / "davinci" / DEFAULT_CONFIG_NAME,
    ]
    script_file = globals().get("__file__")
    if script_file:
        try:
            candidates.append(Path(str(script_file)).resolve().with_name(DEFAULT_CONFIG_NAME))
        except Exception:
            pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def get_resolve() -> Any:
    try:
        import DaVinciResolveScript as dvr_script  # type: ignore
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is not None:
            return resolve
    except Exception:
        pass

    bmd_obj = globals().get("bmd")
    if bmd_obj is not None:
        resolve = safe_call(bmd_obj, "scriptapp", "Resolve")
        if resolve is not None:
            return resolve

    raise RuntimeError(
        "Resolve API is unavailable. Run this script from DaVinci Resolve: "
        "Workspace -> Scripts."
    )


def timeline_fps(project: Any, timeline: Any) -> float:
    raw = safe_call(timeline, "GetSetting", "timelineFrameRate", default=None)
    if raw in (None, ""):
        raw = safe_call(project, "GetSetting", "timelineFrameRate", default=None)
    try:
        return float(str(raw).split()[0])
    except Exception:
        return 24.0


def timeline_item_name(item: Any) -> str:
    name = safe_call(item, "GetName", default=None)
    if not name:
        props = safe_call(item, "GetProperty", default={}) or {}
        if isinstance(props, dict):
            name = props.get("Name") or props.get("Clip Name")
    return norm_text(name)


def timeline_item_start(item: Any) -> int:
    try:
        return int(round(float(safe_call(item, "GetStart", default=0) or 0)))
    except Exception:
        return 0


def timeline_item_end(item: Any) -> int:
    try:
        return int(round(float(safe_call(item, "GetEnd", default=0) or 0)))
    except Exception:
        return 0


def get_track_items(timeline: Any, track_type: str, index: int) -> List[Any]:
    items = safe_call(timeline, "GetItemListInTrack", track_type, int(index), default=[]) or []
    if isinstance(items, dict):
        items = list(items.values())
    return list(items)


def track_name(timeline: Any, track_type: str, index: int) -> str:
    return norm_text(safe_call(timeline, "GetTrackName", track_type, int(index), default=""))


def item_record(item: Any) -> Dict[str, Any]:
    start = timeline_item_start(item)
    end = timeline_item_end(item)
    return {
        "name": timeline_item_name(item),
        "start": start,
        "end": end,
        "duration": max(0, end - start),
    }


def snapshot_track(timeline: Any, track_type: str, index: int) -> List[Dict[str, Any]]:
    return [item_record(item) for item in get_track_items(timeline, track_type, index)]


def parse_v3_identity(item: Any) -> Dict[str, Any]:
    name = timeline_item_name(item)
    match = V3_ITEM_RE.match(name)
    cue_id = None
    cue_index = None
    if match:
        cue_index = int(match.group("index"))
        cue_id = match.group("cue")
    if cue_id is None:
        sub_match = re.search(r"(sub[_-]?\d+)", name, flags=re.IGNORECASE)
        cue_id = sub_match.group(1) if sub_match else None
    return {
        "name": name,
        "cue_index": cue_index,
        "cue_id": cue_id,
        "cue_number": cue_number(cue_id) if cue_id else cue_index,
        "start": timeline_item_start(item),
        "end": timeline_item_end(item),
    }


def get_fusion_comps(item: Any) -> List[Any]:
    comps = []
    count = safe_call(item, "GetFusionCompCount", default=0) or 0
    try:
        count = int(count)
    except Exception:
        count = 0
    for index in range(1, count + 1):
        comp = safe_call(item, "GetFusionCompByIndex", index, default=None)
        if comp is not None:
            comps.append(comp)
    if not comps:
        comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
        if comp is not None:
            comps.append(comp)
    return comps


def tool_regid(tool: Any) -> str:
    attrs = safe_call(tool, "GetAttrs", default={}) or {}
    if isinstance(attrs, dict):
        return norm_text(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID"))
    return ""


def get_tool_list(comp: Any) -> List[Any]:
    tools = safe_call(comp, "GetToolList", False, "TextPlus", default=None)
    if not tools:
        tools = safe_call(comp, "GetToolList", False, default={}) or {}
    if isinstance(tools, dict):
        tools = list(tools.values())
    return list(tools or [])


def find_textplus_tool(item: Any) -> Tuple[Optional[Any], Dict[str, Any]]:
    diagnostics = {"fusion_comp_count": 0, "tools_seen": [], "matched": False}
    for comp in get_fusion_comps(item):
        diagnostics["fusion_comp_count"] += 1
        for tool in get_tool_list(comp):
            regid = tool_regid(tool)
            name = norm_text(safe_call(tool, "GetAttrs", default={}).get("TOOLS_Name") if isinstance(safe_call(tool, "GetAttrs", default={}), dict) else "")
            diagnostics["tools_seen"].append({"name": name, "regid": regid})
            if regid.lower() in {"textplus", "text3d"} or "textplus" in regid.lower():
                diagnostics["matched"] = True
                return tool, diagnostics
    return None, diagnostics


def get_input_value(tool: Any, name: str) -> Any:
    value = safe_call(tool, "GetInput", name, default=None)
    if value is not None:
        return value
    input_obj = getattr(tool, name, None)
    if input_obj is not None:
        try:
            return input_obj[0]
        except Exception:
            pass
    return None


def input_keyframes(tool: Any, name: str) -> Any:
    input_obj = getattr(tool, name, None)
    if input_obj is None:
        return None
    value = safe_call(input_obj, "GetKeyFrames", default=None)
    if value is None:
        value = safe_call(input_obj, "GetKeyFrames", True, default=None)
    return json_safe(value)


def snapshot_preserved_inputs(tool: Any, names: Sequence[str]) -> Dict[str, Any]:
    return {
        name: {
            "value": json_safe(get_input_value(tool, name)),
            "keyframes": input_keyframes(tool, name),
        }
        for name in names
    }


def preserved_inputs_equal(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
    return values_equal(before, after)


def set_input_static(tool: Any, name: str, value: Any) -> Dict[str, Any]:
    attempts = []
    ok = False
    try:
        result = tool.SetInput(name, value)
        attempts.append({"method": "SetInput", "result": json_safe(result)})
        ok = result is not False
    except Exception as exc:
        attempts.append({"method": "SetInput", "error": f"{type(exc).__name__}: {exc}"})

    if not ok:
        try:
            setattr(tool, name, value)
            attempts.append({"method": "setattr", "result": True})
            ok = True
        except Exception as exc:
            attempts.append({"method": "setattr", "error": f"{type(exc).__name__}: {exc}"})

    return {"ok": bool(ok), "attempts": attempts}


def set_and_verify(tool: Any, name: str, value: Any, delay: float) -> Dict[str, Any]:
    before = json_safe(get_input_value(tool, name))
    write = set_input_static(tool, name, value)
    if delay > 0:
        time.sleep(delay)
    after = json_safe(get_input_value(tool, name))
    verified = bool(write.get("ok")) and values_equal(value, after)
    return {
        "name": name,
        "requested": json_safe(value),
        "before": before,
        "write": write,
        "after": after,
        "verified": verified,
    }


def hex_rgb(value: Any) -> Optional[Tuple[float, float, float]]:
    text = norm_text(value).lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore
    except Exception:
        return None


def rgb_luma(rgb: Optional[Tuple[float, float, float]]) -> float:
    if rgb is None:
        return 0.5
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def rgb_saturation(rgb: Optional[Tuple[float, float, float]]) -> float:
    if rgb is None:
        return 0.0
    return max(rgb) - min(rgb)


def rgb_hue_degrees(rgb: Optional[Tuple[float, float, float]]) -> float:
    if rgb is None:
        return 0.0
    r, g, b = rgb
    mx, mn = max(rgb), min(rgb)
    delta = mx - mn
    if delta <= 1e-9:
        return 0.0
    if mx == r:
        hue = ((g - b) / delta) % 6
    elif mx == g:
        hue = ((b - r) / delta) + 2
    else:
        hue = ((r - g) / delta) + 4
    return hue * 60.0


def color_bucket(value: Any) -> str:
    rgb = hex_rgb(value)
    luma = rgb_luma(rgb)
    sat = rgb_saturation(rgb)
    hue = rgb_hue_degrees(rgb)
    if luma >= 0.72 and sat <= 0.28:
        return "white"
    if luma <= 0.30:
        return "dark"
    if sat >= 0.35 and (hue >= 345 or hue <= 12):
        return "red"
    if sat >= 0.30 and 12 < hue <= 52:
        return "orange"
    if sat >= 0.30 and 285 <= hue < 345:
        return "pink"
    return "neutral"


def case_bucket(value: Any) -> str:
    text = norm_text(value)
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "lowercase_or_sentence"
    upper = sum(ch.isupper() for ch in letters)
    lower = sum(ch.islower() for ch in letters)
    if upper / len(letters) >= 0.86:
        return "uppercase"
    tokens = [token for token in re.split(r"\s+", text) if token]
    mixed_tokens = sum(
        any(ch.isupper() for ch in token[1:]) and any(ch.islower() for ch in token)
        for token in tokens
    )
    if mixed_tokens or (upper > 1 and lower > 1 and upper / len(letters) > 0.25):
        return "mixed"
    return "lowercase_or_sentence"


def position_bucket(group: Dict[str, Any]) -> str:
    position = group.get("position") or {}
    vertical = norm_text(position.get("vertical_zone") if isinstance(position, dict) else "")
    align = norm_text(position.get("horizontal_align") if isinstance(position, dict) else "")
    if not vertical:
        center = group.get("center") or {}
        y = float(center.get("y", 0.5)) if isinstance(center, dict) else 0.5
        vertical = "top" if y < 0.34 else ("bottom" if y > 0.67 else "middle")
    if not align:
        center = group.get("center") or {}
        x = float(center.get("x", 0.5)) if isinstance(center, dict) else 0.5
        align = "left" if x < 0.36 else ("right" if x > 0.64 else "center")
    return f"{vertical}_{align}"


def size_bucket(group: Dict[str, Any]) -> str:
    ratio = group.get("estimated_font_height_ratio")
    if ratio is None:
        px = group.get("estimated_font_height_px")
        try:
            ratio = float(px) / 1920.0
        except Exception:
            ratio = 0.04
    try:
        ratio = float(ratio)
    except Exception:
        ratio = 0.04
    return "large" if ratio >= 0.060 else "medium"


def group_bucket_key(group: Dict[str, Any]) -> str:
    role = norm_text(group.get("role") or "spoken_caption")
    fill = color_bucket(group.get("estimated_text_color"))
    stroke = color_bucket(group.get("estimated_stroke_color"))
    position = position_bucket(group)
    size = size_bucket(group)
    case = case_bucket(group.get("text"))
    return "|".join([role, fill, stroke, position, size, case])


def profile_features(profile: Dict[str, Any]) -> Dict[str, Any]:
    placement = profile.get("placement") or {}
    typography = profile.get("typography") or {}
    colors = profile.get("colors") or {}
    return {
        "style_id": norm_text(profile.get("style_id") or profile.get("style_profile_id")),
        "bucket_key": norm_text(profile.get("bucket_key")),
        "role": norm_text(profile.get("role") or "spoken_caption"),
        "position": norm_text(placement.get("position") if isinstance(placement, dict) else ""),
        "font_height_ratio": float(typography.get("font_height_ratio") or 0.04) if isinstance(typography, dict) else 0.04,
        "case": norm_text(typography.get("case_style") if isinstance(typography, dict) else ""),
        "fill": colors.get("fill") if isinstance(colors, dict) else None,
        "stroke": colors.get("stroke") if isinstance(colors, dict) else None,
    }


def color_distance(a: Any, b: Any) -> float:
    ra, rb = hex_rgb(a), hex_rgb(b)
    if ra is None or rb is None:
        return 0.5
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(ra, rb))) / math.sqrt(3.0)


def classify_group(group: Dict[str, Any], profiles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    bucket = group_bucket_key(group)
    exact = [p for p in profiles if norm_text(p.get("bucket_key")) == bucket]
    if exact:
        return {
            "style_profile_id": exact[0].get("style_id"),
            "method": "exact_bucket_key",
            "bucket_key": bucket,
            "distance": 0.0,
            "margin": 999.0,
        }

    scored = []
    group_ratio = float(group.get("estimated_font_height_ratio") or 0.04)
    group_position = position_bucket(group)
    group_case = case_bucket(group.get("text"))
    for profile in profiles:
        p = profile_features(profile)
        distance = 0.0
        if p["role"] and p["role"] != norm_text(group.get("role") or "spoken_caption"):
            distance += 3.0
        if p["position"] and p["position"] != group_position:
            distance += 1.5
        if p["case"] and p["case"] != group_case:
            distance += 0.9
        distance += min(2.0, abs(math.log(max(group_ratio, 1e-4) / max(p["font_height_ratio"], 1e-4))))
        distance += color_distance(group.get("estimated_text_color"), p["fill"]) * 1.7
        distance += color_distance(group.get("estimated_stroke_color"), p["stroke"]) * 1.0
        scored.append((distance, p["style_id"]))
    scored.sort()
    if not scored:
        return {"style_profile_id": None, "method": "no_profiles", "bucket_key": bucket}
    margin = scored[1][0] - scored[0][0] if len(scored) > 1 else 999.0
    return {
        "style_profile_id": scored[0][1],
        "method": "nearest_profile_features",
        "bucket_key": bucket,
        "distance": round(scored[0][0], 6),
        "margin": round(margin, 6),
    }


def style_profiles(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = data.get("caption_style_profiles") or data.get("style_profiles") or []
    return [row for row in rows if isinstance(row, dict)]


def style_events(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = data.get("caption_style_events") or data.get("style_events") or []
    return [row for row in rows if isinstance(row, dict)]


def style_groups(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = data.get("subtitle_groups") or data.get("caption_groups") or []
    return [row for row in rows if isinstance(row, dict)]


def mapping_rows(mapping: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = (
        mapping.get("profile_mappings")
        or mapping.get("mappings")
        or mapping.get("profiles")
        or []
    )
    output = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        style_id = norm_text(row.get("style_profile_id") or row.get("style_id"))
        family = norm_text(row.get("family") or row.get("font_family"))
        face = norm_text(row.get("face") or row.get("font_style") or "Regular")
        if style_id and family:
            output[style_id] = {
                **row,
                "style_profile_id": style_id,
                "family": family,
                "face": face or "Regular",
            }
    return output


def cue_text_similarity(a: Any, b: Any) -> float:
    aa, bb = norm_token(a), norm_token(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    return SequenceMatcher(None, aa, bb).ratio()


def build_profile_resolver(
    caption_style: Dict[str, Any],
    aliases: Dict[str, str],
) -> Dict[str, Any]:
    profiles = style_profiles(caption_style)
    events = style_events(caption_style)
    groups = style_groups(caption_style)

    direct_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        cue_id = event.get("cue_id") or event.get("subtitle_id") or event.get("matched_cue_id")
        profile_id = norm_text(event.get("style_profile_id") or event.get("style_id"))
        if not cue_id or not profile_id:
            continue
        for key in cue_key_variants(cue_id):
            direct_by_key.setdefault(key, []).append({
                "style_profile_id": aliases.get(profile_id, profile_id),
                "source": "caption_style_event",
                "event": event,
            })

    groups_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for group in groups:
        classification = classify_group(group, profiles)
        profile_id = norm_text(classification.get("style_profile_id"))
        if profile_id:
            profile_id = aliases.get(profile_id, profile_id)
        cue_ids = group.get("matched_cue_ids") or group.get("cue_ids") or []
        if not isinstance(cue_ids, list):
            cue_ids = [cue_ids]
        for cue_id in cue_ids:
            for key in cue_key_variants(cue_id):
                groups_by_key.setdefault(key, []).append({
                    "style_profile_id": profile_id,
                    "source": "classified_caption_group",
                    "group": group,
                    "classification": classification,
                })

    primary = norm_text(
        (caption_style.get("caption_style_resolved") or {}).get("primary_style_id")
        or (caption_style.get("resolved") or {}).get("primary_style_id")
    )
    if primary:
        primary = aliases.get(primary, primary)

    return {
        "profiles": profiles,
        "events": events,
        "groups": groups,
        "direct_by_key": direct_by_key,
        "groups_by_key": groups_by_key,
        "primary_style_id": primary,
    }


def resolve_item_profile(
    identity: Dict[str, Any],
    rendered_text: Any,
    resolver: Dict[str, Any],
    fps: float,
    mapping: Dict[str, Dict[str, Any]],
    allow_primary_fallback: bool,
) -> Dict[str, Any]:
    keys = cue_key_variants(identity.get("cue_id") or identity.get("cue_number"))

    direct_candidates = []
    for key in keys:
        direct_candidates.extend(resolver["direct_by_key"].get(key, []))
    direct_candidates = [
        row for row in direct_candidates
        if row.get("style_profile_id") in mapping
    ]
    if direct_candidates:
        return {
            "style_profile_id": direct_candidates[0]["style_profile_id"],
            "source": "caption_style_event",
            "confidence": 1.0,
            "details": json_safe(direct_candidates[0]),
        }

    group_candidates = []
    for key in keys:
        group_candidates.extend(resolver["groups_by_key"].get(key, []))

    ranked = []
    item_mid_sec = ((identity["start"] + identity["end"]) / 2.0) / max(fps, 1e-6)
    for row in group_candidates:
        profile_id = row.get("style_profile_id")
        if not profile_id or profile_id not in mapping:
            continue
        group = row.get("group") or {}
        text_score = cue_text_similarity(rendered_text, group.get("text"))
        caption_score = float(group.get("caption_score") or 0.0)
        transcript_score = float(group.get("transcript_match_score") or 0.0)
        timestamp = float(group.get("timestamp") or item_mid_sec)
        time_score = max(0.0, 1.0 - min(1.0, abs(timestamp - item_mid_sec) / 0.75))
        score = 0.52 * text_score + 0.22 * caption_score + 0.12 * transcript_score + 0.14 * time_score
        ranked.append((score, row))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    if ranked:
        best_score, best = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        return {
            "style_profile_id": best["style_profile_id"],
            "source": "classified_caption_group",
            "confidence": round(best_score, 6),
            "margin": round(best_score - second_score, 6),
            "details": json_safe(best),
        }

    if allow_primary_fallback:
        primary = resolver.get("primary_style_id")
        if primary in mapping:
            return {
                "style_profile_id": primary,
                "source": "explicit_primary_fallback",
                "confidence": 0.0,
                "details": None,
            }

    return {
        "style_profile_id": None,
        "source": "unresolved",
        "confidence": 0.0,
        "details": {
            "cue_keys": keys,
            "candidate_group_count": len(group_candidates),
        },
    }


def normalize_aliases(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    output = {}
    for source, target in raw.items():
        source_n, target_n = norm_text(source), norm_text(target)
        if source_n and target_n:
            output[source_n] = target_n
    return output


def main() -> int:
    started = now_unix()
    config_path = resolve_config_path()
    config = load_runtime_config(config_path)

    mapping_path = Path(config["font_mapping_path"])
    caption_style_path = Path(config["caption_style_path"])
    report_path = Path(config["output_report_path"])
    mapping_payload = load_json(mapping_path)
    caption_style = load_json(caption_style_path)

    mapping_ready = bool(
        mapping_payload.get("ready_for_controller_apply")
        or mapping_payload.get("ready_for_full_controller_apply")
    )
    if not mapping_ready:
        raise RuntimeError(f"Font mapping is not controller-ready: {mapping_path}")

    mappings = mapping_rows(mapping_payload)
    if not mappings:
        raise RuntimeError(f"No profile mappings found: {mapping_path}")

    aliases = normalize_aliases(config.get("profile_aliases"))
    resolver = build_profile_resolver(caption_style, aliases)

    resolve = get_resolve()
    project_manager = safe_call(resolve, "GetProjectManager", default=None)
    project = safe_call(project_manager, "GetCurrentProject", default=None)
    timeline = safe_call(project, "GetCurrentTimeline", default=None)
    if project is None or timeline is None:
        raise RuntimeError("No current Resolve project/timeline.")

    fps = timeline_fps(project, timeline)
    v3_track = max(1, int(config.get("v3_track", 3)))
    prefix = norm_text(config.get("item_prefix") or "VC_TEXTPLUS_")
    expected_count = max(0, int(config.get("expected_v3_count", 116)))
    require_full_mapping = bool(config.get("require_full_mapping", True))
    allow_primary_fallback = bool(config.get("allow_primary_fallback", False))
    rollback_on_failure = bool(config.get("rollback_on_item_failure", True))
    dry_run = bool(config.get("dry_run", False))
    delay = max(0.0, float(config.get("readback_delay_sec", 0.03)))
    preserve_names = config.get("preserve_inputs") or ["StyledText", "Size", "Center"]
    preserve_names = [norm_text(name) for name in preserve_names if norm_text(name)]

    all_v3_items = get_track_items(timeline, "video", v3_track)
    candidates = [
        item for item in all_v3_items
        if timeline_item_name(item).lower().startswith(prefix.lower())
    ]

    core_before = {
        "v1": snapshot_track(timeline, "video", 1),
        "a1": snapshot_track(timeline, "audio", 1),
        "v3": [item_record(item) for item in candidates],
    }

    preflight_items = []
    unresolved = []
    missing_mapping = []
    textplus_missing = []

    for item in candidates:
        identity = parse_v3_identity(item)
        tool, tool_diag = find_textplus_tool(item)
        if tool is None:
            row = {
                **identity,
                "error": "textplus_tool_not_found",
                "tool_diagnostics": tool_diag,
            }
            textplus_missing.append(row)
            preflight_items.append(row)
            continue

        rendered_text = get_input_value(tool, "StyledText")
        profile_resolution = resolve_item_profile(
            identity=identity,
            rendered_text=rendered_text,
            resolver=resolver,
            fps=fps,
            mapping=mappings,
            allow_primary_fallback=allow_primary_fallback,
        )
        profile_id = profile_resolution.get("style_profile_id")
        map_row = mappings.get(profile_id) if profile_id else None
        row = {
            **identity,
            "rendered_text": json_safe(rendered_text),
            "profile_resolution": profile_resolution,
            "mapping": json_safe(map_row),
            "_item": item,
            "_tool": tool,
        }
        if not profile_id:
            unresolved.append({k: json_safe(v) for k, v in row.items() if not k.startswith("_")})
        elif map_row is None:
            missing_mapping.append({k: json_safe(v) for k, v in row.items() if not k.startswith("_")})
        preflight_items.append(row)

    preflight_ok = bool(
        len(candidates) == expected_count
        and not textplus_missing
        and (not require_full_mapping or (not unresolved and not missing_mapping))
    )

    report: Dict[str, Any] = {
        "ok": False,
        "step": "Major Step 3B.1",
        "version": VERSION,
        "created_at_unix": started,
        "config_path": str(config_path),
        "mapping_path": str(mapping_path),
        "caption_style_path": str(caption_style_path),
        "project_name": safe_call(project, "GetName", default=None),
        "timeline_name": safe_call(timeline, "GetName", default=None),
        "timeline_fps": fps,
        "v3_track": v3_track,
        "v3_track_name": track_name(timeline, "video", v3_track),
        "expected_v3_count": expected_count,
        "v3_candidate_count": len(candidates),
        "mapping_profile_count": len(mappings),
        "mapping_profile_ids": sorted(mappings),
        "profile_aliases": aliases,
        "allow_primary_fallback": allow_primary_fallback,
        "require_full_mapping": require_full_mapping,
        "dry_run": dry_run,
        "preflight": {
            "ok": preflight_ok,
            "textplus_missing_count": len(textplus_missing),
            "unresolved_profile_count": len(unresolved),
            "missing_profile_mapping_count": len(missing_mapping),
            "textplus_missing": textplus_missing[:20],
            "unresolved_profiles": unresolved[:30],
            "missing_profile_mappings": missing_mapping[:30],
        },
        "created_count": 0,
        "modified_count": 0,
        "already_correct_count": 0,
        "mapped_count": 0,
        "readback_success_count": 0,
        "failed_count": 0,
        "primary_fallback_count": 0,
        "preserved_input_failure_count": 0,
        "items": [],
        "core_tracks_before": core_before,
        "failures": [],
        "warnings": [],
    }

    if not preflight_ok:
        report["failures"].append("preflight_not_safe_for_transaction")
        report["status"] = "blocked_before_writes"
        report["runtime_seconds"] = round(now_unix() - started, 6)
        write_json(report_path, report)
        print(json.dumps({
            "ok": False,
            "status": report["status"],
            "v3_candidate_count": len(candidates),
            "expected_v3_count": expected_count,
            "unresolved_profile_count": len(unresolved),
            "missing_profile_mapping_count": len(missing_mapping),
            "textplus_missing_count": len(textplus_missing),
            "report": str(report_path),
        }, ensure_ascii=False))
        return 1

    if dry_run:
        report["status"] = "dry_run_preflight_passed"
        report["mapped_count"] = len(preflight_items)
        report["ok"] = True
        report["runtime_seconds"] = round(now_unix() - started, 6)
        write_json(report_path, report)
        print(json.dumps({"ok": True, "status": report["status"], "report": str(report_path)}, ensure_ascii=False))
        return 0

    for row in preflight_items:
        item = row.pop("_item")
        tool = row.pop("_tool")
        map_row = row.get("mapping") or {}
        family = norm_text(map_row.get("family"))
        face = norm_text(map_row.get("face") or "Regular")
        profile_resolution = row.get("profile_resolution") or {}
        if profile_resolution.get("source") == "explicit_primary_fallback":
            report["primary_fallback_count"] += 1

        before_font = json_safe(get_input_value(tool, "Font"))
        before_style = json_safe(get_input_value(tool, "Style"))
        preserved_before = snapshot_preserved_inputs(tool, preserve_names)

        item_result = {
            **{k: json_safe(v) for k, v in row.items()},
            "requested_family": family,
            "requested_face": face,
            "font_before": before_font,
            "style_before": before_style,
            "preserved_inputs_before": preserved_before,
            "status": None,
            "writes": {},
            "rollback": None,
            "preserved_inputs_after": None,
            "preserved_inputs_ok": False,
            "readback_ok": False,
        }

        report["mapped_count"] += 1

        if values_equal(family, before_font) and values_equal(face, before_style):
            item_result["status"] = "already_correct"
            report["already_correct_count"] += 1
        else:
            family_write = set_and_verify(tool, "Font", family, delay)
            face_write = set_and_verify(tool, "Style", face, delay)
            item_result["writes"] = {"Font": family_write, "Style": face_write}
            if family_write["verified"] and face_write["verified"]:
                item_result["status"] = "applied"
                report["modified_count"] += 1
            else:
                item_result["status"] = "write_failed"
                report["failed_count"] += 1
                if rollback_on_failure:
                    rollback_family = set_and_verify(tool, "Font", before_font, delay)
                    rollback_style = set_and_verify(tool, "Style", before_style, delay)
                    item_result["rollback"] = {
                        "Font": rollback_family,
                        "Style": rollback_style,
                        "ok": rollback_family["verified"] and rollback_style["verified"],
                    }

        final_font = json_safe(get_input_value(tool, "Font"))
        final_style = json_safe(get_input_value(tool, "Style"))
        item_result["font_after"] = final_font
        item_result["style_after"] = final_style
        item_result["readback_ok"] = values_equal(family, final_font) and values_equal(face, final_style)
        if item_result["readback_ok"]:
            report["readback_success_count"] += 1
        elif item_result["status"] != "write_failed":
            report["failed_count"] += 1
            item_result["status"] = "readback_failed"

        preserved_after = snapshot_preserved_inputs(tool, preserve_names)
        item_result["preserved_inputs_after"] = preserved_after
        item_result["preserved_inputs_ok"] = preserved_inputs_equal(preserved_before, preserved_after)
        if not item_result["preserved_inputs_ok"]:
            report["preserved_input_failure_count"] += 1
            report["failed_count"] += 1
            item_result["status"] = "preserved_input_changed"

        report["items"].append(item_result)

    core_after = {
        "v1": snapshot_track(timeline, "video", 1),
        "a1": snapshot_track(timeline, "audio", 1),
        "v3": [item_record(item) for item in candidates],
    }
    report["core_tracks_after"] = core_after
    report["core_track_integrity"] = {
        "v1_unchanged": values_equal(core_before["v1"], core_after["v1"]),
        "a1_unchanged": values_equal(core_before["a1"], core_after["a1"]),
        "v3_ranges_unchanged": values_equal(core_before["v3"], core_after["v3"]),
    }
    report["core_track_integrity"]["ok"] = all(report["core_track_integrity"].values())

    profile_counts: Dict[str, int] = {}
    for item_result in report["items"]:
        profile_id = ((item_result.get("profile_resolution") or {}).get("style_profile_id"))
        if profile_id:
            profile_counts[profile_id] = profile_counts.get(profile_id, 0) + 1
    report["profile_item_counts"] = dict(sorted(profile_counts.items()))

    report["created_count"] = 0
    report["ok"] = bool(
        len(candidates) == expected_count
        and report["mapped_count"] == expected_count
        and report["readback_success_count"] == expected_count
        and report["failed_count"] == 0
        and report["preserved_input_failure_count"] == 0
        and report["core_track_integrity"]["ok"]
        and (allow_primary_fallback or report["primary_fallback_count"] == 0)
    )
    report["status"] = "applied_and_verified" if report["ok"] else "completed_with_failures"
    report["runtime_seconds"] = round(now_unix() - started, 6)
    if not report["ok"]:
        report["failures"].append("step_3B_1_integrity_failed")

    write_json(report_path, report)
    print(json.dumps({
        "ok": report["ok"],
        "status": report["status"],
        "expected_v3_count": expected_count,
        "mapped_count": report["mapped_count"],
        "modified_count": report["modified_count"],
        "already_correct_count": report["already_correct_count"],
        "readback_success_count": report["readback_success_count"],
        "failed_count": report["failed_count"],
        "primary_fallback_count": report["primary_fallback_count"],
        "core_track_integrity_ok": report["core_track_integrity"]["ok"],
        "report": str(report_path),
    }, ensure_ascii=False))
    return 0 if report["ok"] else 1



def execute_workspace_entrypoint() -> int:
    """
    Resolve's Workspace -> Scripts loader may execute a Python file as an imported
    module instead of assigning __name__ == "__main__". The v1.0 script only ran
    inside that guard, so clicking the menu could import the file and do nothing.

    This entrypoint is intentionally executed at module load time. It writes a
    launch/status artifact immediately, runs the transaction once, and never lets
    SystemExit silently terminate Resolve's script host.
    """
    config_path = resolve_config_path()
    try:
        config = load_runtime_config(config_path)
    except Exception:
        config = default_runtime_config()

    report_path = Path(config.get("output_report_path") or default_runtime_config()["output_report_path"])
    status_path = Path(config.get("workspace_status_path") or default_runtime_config()["workspace_status_path"])
    log_path = Path(config.get("workspace_launch_log_path") or default_runtime_config()["workspace_launch_log_path"])
    show_message = bool(config.get("show_completion_message", True))
    launch_id = f"step3b1_{int(time.time() * 1000)}"

    append_workspace_log(log_path, "workspace_script_started", {
        "launch_id": launch_id,
        "config_path": str(config_path),
        "config_exists": config_path.is_file(),
        "report_path": str(report_path),
    })
    try:
        write_json(status_path, {
            "ok": False,
            "running": True,
            "step": "Major Step 3B.1",
            "version": VERSION,
            "launch_id": launch_id,
            "started_at_unix": now_unix(),
            "module_name": globals().get("__name__"),
            "script_path": globals().get("__file__"),
            "config_path": str(config_path),
            "config_exists": config_path.is_file(),
            "report_path": str(report_path),
        })
    except Exception:
        pass

    try:
        return_code = int(main())
        report_payload: Dict[str, Any] = {}
        if report_path.is_file():
            try:
                report_payload = load_json(report_path)
            except Exception:
                report_payload = {}

        ok = bool(return_code == 0 and report_payload.get("ok"))
        summary = {
            "ok": ok,
            "running": False,
            "step": "Major Step 3B.1",
            "version": VERSION,
            "launch_id": launch_id,
            "finished_at_unix": now_unix(),
            "return_code": return_code,
            "report_path": str(report_path),
            "report_exists": report_path.is_file(),
            "report_status": report_payload.get("status"),
            "v3_candidate_count": report_payload.get("v3_candidate_count"),
            "mapped_count": report_payload.get("mapped_count"),
            "modified_count": report_payload.get("modified_count"),
            "already_correct_count": report_payload.get("already_correct_count"),
            "readback_success_count": report_payload.get("readback_success_count"),
            "failed_count": report_payload.get("failed_count"),
            "failures": report_payload.get("failures") or [],
        }
        try:
            write_json(status_path, summary)
        except Exception:
            pass
        append_workspace_log(log_path, "workspace_script_finished", summary)

        if show_message:
            if ok:
                show_windows_message(
                    "Video Cloner — Step 3B.1 complete",
                    (
                        f"Font mapping finished.\n\n"
                        f"V3 clips: {summary.get('v3_candidate_count')}\n"
                        f"Mapped: {summary.get('mapped_count')}\n"
                        f"Modified: {summary.get('modified_count')}\n"
                        f"Already correct: {summary.get('already_correct_count')}\n"
                        f"Failures: {summary.get('failed_count')}\n\n"
                        f"Report:\n{report_path}"
                    ),
                    is_error=False,
                )
            else:
                show_windows_message(
                    "Video Cloner — Step 3B.1 failed",
                    (
                        f"The script executed but did not pass validation.\n\n"
                        f"Status: {summary.get('report_status')}\n"
                        f"V3 clips found: {summary.get('v3_candidate_count')}\n"
                        f"Failures: {summary.get('failed_count')}\n\n"
                        f"Report:\n{report_path}\n\n"
                        f"Workspace log:\n{log_path}"
                    ),
                    is_error=True,
                )
        return return_code

    except BaseException as exc:
        payload = {
            "ok": False,
            "running": False,
            "step": "Major Step 3B.1",
            "version": VERSION,
            "status": "workspace_entrypoint_exception",
            "launch_id": launch_id,
            "finished_at_unix": now_unix(),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "config_path": str(config_path),
            "report_path": str(report_path),
            "failures": ["unhandled_workspace_entrypoint_exception"],
        }
        try:
            write_json(report_path, payload)
        except Exception:
            pass
        try:
            write_json(status_path, payload)
        except Exception:
            pass
        append_workspace_log(log_path, "workspace_script_exception", payload)
        print(json.dumps(payload, ensure_ascii=False))
        if show_message:
            show_windows_message(
                "Video Cloner — Step 3B.1 exception",
                (
                    f"{payload['error']}\n\n"
                    f"Report:\n{report_path}\n\n"
                    f"Workspace log:\n{log_path}"
                ),
                is_error=True,
            )
        return 1


# Do not use only `if __name__ == "__main__"` here. Resolve may import Workspace
# scripts as modules. The sentinel prevents accidental double execution inside the
# same module namespace while still allowing every fresh menu invocation to run.
if not globals().get("_VC_STEP_3B1_AUTORUN_EXECUTED", False):
    _VC_STEP_3B1_AUTORUN_EXECUTED = True
    _VC_STEP_3B1_RETURN_CODE = execute_workspace_entrypoint()
