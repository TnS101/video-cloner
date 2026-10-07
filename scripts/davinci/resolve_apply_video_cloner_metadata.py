#!/usr/bin/env python3
"""
resolve_apply_video_cloner_metadata.py

Alpha DaVinci Resolve controller for the Video Cloner pipeline.

Purpose:
    Apply editor-specific DaVinci Resolve layers after a Video Cloner timeline has been imported.

    Supported imported timeline backends:
    - Full FCPXML timeline from compile_davinci_textplus_fcpxml.py
      (V1 video cuts, A1 audio, V2 editable Text/Title captions)
    - Legacy OTIO timeline from compile_davinci_otio.py

Expected flow:
    video.mp4
    -> analysis.json
    -> edit_plan.json
    -> validated_edit_plan.json
    -> generic_edit_commands.json
    -> EITHER compile_davinci_textplus_fcpxml.py --timeline-mode full_timeline
       -> import .fcpxml in DaVinci Resolve
       -> run this controller on V1 for zoom/speed probes

       OR legacy route:
       -> compile_davinci_otio.py
       -> import .otio in DaVinci Resolve
       -> run this controller

Important architecture rule:
    This controller is DaVinci-specific.
    The planner and generic compiler remain editor-agnostic.

Current alpha support:
    - Reads generic_edit_commands.json as source of truth.
    - Connects to the active DaVinci Resolve project/timeline.
    - Maps V1 timeline clips to generic commands by order.
    - Verifies clip count and rough duration match.
    - Applies static zoom values through Resolve clip properties.
    - Does not add debug markers by default. Use --add-debug-markers only when you intentionally want timeline marker diagnostics.
    - Attempts simple constant speed changes when Resolve exposes a usable property.
    - Creates editable Text+/Fusion-title subtitles from generic subtitle_clips when --apply-subtitles is used.
    - v0.5.1: protects V1/A1 with track locks, targets subtitle overlay track, and uses timeline in/out marks to request exact word-level title durations.
    - v0.5.4: verifies imported V2 caption/title clips without modifying captions.
    - v0.6.1: V2 caption verification is enabled by default, including Workspace -> Scripts runs.
    - v0.6.0: maps imported V2 captions to controllable Text+ provisioning/animation diagnostics and safe overlay creation.
    - v0.6.6: resolves detected/fallback fonts only against Resolve's installed inventory and supports meaningful cue selection for automatic one-caption probes.
    - v0.9.0 / Step 2F: imports validated full-resolution RGBA image sequences from analysis.json and places them idempotently on V4 above the linked V3 Text+ cue.
    - Does NOT claim reliable native speed ramps or transition insertion yet.
    - v0.9.2: fixes RGBA image-sequence endFrame off-by-one and waits for stable V4 range readback before rollback.

Why generic_edit_commands.json is used:
    Resolve may not expose all OTIO metadata/clip markers through the public scripting API
    in a consistent way after import. The deterministic source of truth is still the
    generic command file. OTIO markers are useful visually, but this script should not
    depend on them being readable from Resolve.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import threading
import queue
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "resolve_video_cloner_controller_v0_9_3_step_2G_major_step_2_completion_gate"

DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
FORCE_DIRECT_RESOLVE_CALLS = False
INTERNAL_MENU_MODE = False


def runtime_script_identity() -> Dict[str, Any]:
    """Return the exact script file/version/hash executed by Resolve."""
    raw_path = globals().get("__file__")
    resolved = None
    sha256 = None
    size_bytes = None
    modified_unix = None
    try:
        if raw_path:
            path = Path(str(raw_path)).resolve()
            resolved = str(path)
            if path.exists():
                payload = path.read_bytes()
                sha256 = hashlib.sha256(payload).hexdigest()
                size_bytes = len(payload)
                modified_unix = path.stat().st_mtime
    except Exception:
        pass
    return {
        "version": VERSION,
        "script_file": resolved or str(raw_path or ""),
        "sha256": sha256,
        "size_bytes": size_bytes,
        "modified_unix": modified_unix,
        "python": sys.executable,
    }


# -----------------------------
# Hard bootstrap debug logging
# -----------------------------

def choose_default_debug_log() -> Path:
    """
    Pick a writeable default debug log.

    Important: when this script lives inside ProgramData/Fusion/Scripts/Edit, writing
    next to the script can silently fail because of Windows permissions. Use env var
    first, then the Video Cloner project folder, then TEMP.
    """
    env_log = os.environ.get("VC_DEBUG_LOG")
    if env_log:
        return Path(env_log).resolve()

    project_data = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT)) / "data"
    if project_data.exists():
        return (project_data / "resolve_apply_debug.log").resolve()

    temp_dir = Path(os.environ.get("TEMP", os.getcwd()))
    return (temp_dir / "resolve_apply_debug.log").resolve()


HARD_DEBUG_LOG = choose_default_debug_log()

def hard_debug(message: str, payload: Any = None) -> None:
    """Write debug info even before Resolve/API logic starts. Never raise."""
    try:
        HARD_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(HARD_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
            if payload is not None:
                try:
                    f.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
                except Exception:
                    f.write(str(payload) + "\n")
            f.flush()
    except Exception:
        pass




def resolve_api_call(label: str, fn: Any, timeout_seconds: float = 15.0) -> Any:
    """
    Wrapper for Resolve API calls.

    External n8n/CLI runs keep timeout protection. Internal Workspace -> Scripts
    runs use direct calls because Resolve API objects can be unreliable from a
    background thread inside the Resolve runtime.
    """
    if FORCE_DIRECT_RESOLVE_CALLS:
        hard_debug(f"{label}_DIRECT_START", {"internal_menu_mode": INTERNAL_MENU_MODE})
        try:
            value = fn()
            hard_debug(f"{label}_DIRECT_OK", {"result_type": type(value).__name__, "truthy": bool(value)})
            return value
        except Exception as exc:
            hard_debug(f"{label}_DIRECT_ERROR", {"type": type(exc).__name__, "error": str(exc)})
            raise

    return timed_call(label, fn, timeout_seconds=timeout_seconds)


def get_injected_resolve_handle() -> Optional[Any]:
    """
    Try Resolve's internally injected globals first.

    When launched from Workspace -> Scripts, some Resolve/Fusion runtimes expose
    handles like resolve, fusion, or bmd directly. This avoids relying on the
    external DaVinciResolveScript module, which is the part that often fails in
    the free version / external mode.
    """
    for name in ("resolve", "Resolve"):
        candidate = globals().get(name)
        if candidate is not None and hasattr(candidate, "GetProjectManager"):
            hard_debug("INJECTED_RESOLVE_FOUND", {"name": name, "type": type(candidate).__name__})
            return candidate

    bmd_obj = globals().get("bmd")
    if bmd_obj is not None and hasattr(bmd_obj, "scriptapp"):
        try:
            candidate = bmd_obj.scriptapp("Resolve")
            if candidate and hasattr(candidate, "GetProjectManager"):
                hard_debug("INJECTED_BMD_SCRIPTAPP_RESOLVE_FOUND", {"type": type(candidate).__name__})
                return candidate
        except Exception as exc:
            hard_debug("INJECTED_BMD_SCRIPTAPP_RESOLVE_FAILED", {"type": type(exc).__name__, "error": str(exc)})

    fusion_obj = globals().get("fusion")
    if fusion_obj is not None:
        for method_name in ("GetResolve", "Resolve"):
            method = getattr(fusion_obj, method_name, None)
            if method:
                try:
                    candidate = method()
                    if candidate and hasattr(candidate, "GetProjectManager"):
                        hard_debug("INJECTED_FUSION_RESOLVE_FOUND", {"method": method_name, "type": type(candidate).__name__})
                        return candidate
                except Exception as exc:
                    hard_debug("INJECTED_FUSION_RESOLVE_FAILED", {"method": method_name, "type": type(exc).__name__, "error": str(exc)})

    hard_debug("INJECTED_RESOLVE_NOT_FOUND", {"globals_sample": sorted(list(globals().keys()))[:80]})
    return None


def discover_latest_generic_file(project_root: Optional[str] = None) -> Optional[str]:
    """
    Find the most recently modified *_generic_edit_commands.json.

    This is what makes Workspace -> Scripts usable: Resolve does not pass CLI
    arguments, so the controller must discover the latest Video Cloner output.
    """
    explicit = os.environ.get("VC_GENERIC")
    if explicit and Path(explicit).exists():
        return str(Path(explicit).resolve())

    roots: List[Path] = []
    for value in (project_root, os.environ.get("VC_PROJECT_ROOT"), DEFAULT_PROJECT_ROOT):
        if value:
            roots.append(Path(value))

    try:
        roots.append(Path.home() / "Downloads" / "Projects" / "Video Cloner")
    except Exception:
        pass

    try:
        roots.append(Path.cwd())
    except Exception:
        pass

    # De-duplicate while preserving order.
    unique_roots: List[Path] = []
    seen = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique_roots.append(root)

    patterns = [
        "data/*/davinci/*_generic_edit_commands.json",
        "data/**/*_generic_edit_commands.json",
        "**/*_generic_edit_commands.json",
    ]

    candidates: List[Path] = []
    for root in unique_roots:
        try:
            if not root.exists():
                continue
            for pattern in patterns:
                candidates.extend([p for p in root.glob(pattern) if p.is_file()])
        except Exception as exc:
            hard_debug("DISCOVER_GENERIC_ROOT_FAILED", {"root": str(root), "error": repr(exc)})

    if not candidates:
        hard_debug("DISCOVER_GENERIC_NONE", {"roots": [str(r) for r in unique_roots], "patterns": patterns})
        return None

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    hard_debug("DISCOVER_GENERIC_OK", {
        "selected": str(latest),
        "count": len(candidates),
        "latest_mtime": latest.stat().st_mtime,
    })
    return str(latest.resolve())


def default_report_path_for_generic(generic_path: str) -> str:
    """Return the preferred controller report path for a generic command file.

    Preferred project layout:
      data/<videoId>/planning/<videoId>_generic_edit_commands.json
      data/<videoId>/davinci/<videoId>_resolve_controller_report.json

    Older versions wrote the report beside the generic file. For Resolve menu
    mode the davinci folder is cleaner and matches the n8n Get Media Path node.
    """
    p = Path(generic_path)
    stem = p.stem
    if stem.endswith("_generic_edit_commands"):
        stem = stem[: -len("_generic_edit_commands")] + "_resolve_controller_report"
    else:
        stem = stem + "_resolve_controller_report"

    try:
        if p.parent.name.lower() in {"planning", "davinci"}:
            return str((p.parent.parent / "davinci" / f"{stem}.json").resolve())
    except Exception:
        pass

    return str((p.parent / f"{stem}.json").resolve())


def default_debug_log_for_generic(generic_path: str) -> str:
    """Return the preferred per-video debug log path."""
    p = Path(generic_path)
    try:
        if p.parent.name.lower() in {"planning", "davinci"}:
            logs_dir = p.parent.parent / "logs"
            return str((logs_dir / "resolve_apply_debug.log").resolve())
    except Exception:
        pass
    return str((p.parent / "resolve_apply_debug.log").resolve())


def default_config_path_for_generic(generic_path: str) -> str:
    """Return the preferred per-video controller config path."""
    p = Path(generic_path)
    try:
        if p.parent.name.lower() in {"planning", "davinci"}:
            return str((p.parent.parent / "davinci" / "resolve_controller_config.json").resolve())
    except Exception:
        pass
    return str((p.parent / "resolve_controller_config.json").resolve())


def normalize_user_path(path_value: Any) -> Optional[str]:
    if path_value is None:
        return None
    value = str(path_value).strip()
    if not value:
        return None
    try:
        return str(Path(os.path.expandvars(os.path.expanduser(value))).resolve())
    except Exception:
        return value


def discover_latest_controller_config(project_root: Optional[str] = None, generic_path: Optional[str] = None) -> Optional[str]:
    """Find a resolve_controller_config.json for Workspace -> Scripts mode.

    Discovery order:
      1) VC_RESOLVE_CONTROLLER_CONFIG / VC_CONTROLLER_CONFIG
      2) beside the discovered/provided generic file, usually data/<id>/davinci/
      3) most recently modified data/*/davinci/resolve_controller_config.json
      4) project-root resolve_controller_config.json
      5) cwd resolve_controller_config.json
    """
    for env_name in ("VC_RESOLVE_CONTROLLER_CONFIG", "VC_CONTROLLER_CONFIG"):
        explicit = normalize_user_path(os.environ.get(env_name))
        if explicit and Path(explicit).exists():
            hard_debug("DISCOVER_CONFIG_ENV_OK", {"env": env_name, "path": explicit})
            return explicit

    candidates: List[Path] = []
    if generic_path:
        try:
            candidates.append(Path(default_config_path_for_generic(generic_path)))
        except Exception:
            pass

    roots: List[Path] = []
    for value in (project_root, os.environ.get("VC_PROJECT_ROOT"), DEFAULT_PROJECT_ROOT):
        if value:
            roots.append(Path(value))
    try:
        roots.append(Path.home() / "Downloads" / "Projects" / "Video Cloner")
    except Exception:
        pass
    try:
        roots.append(Path.cwd())
    except Exception:
        pass

    unique_roots: List[Path] = []
    seen_roots = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen_roots:
            seen_roots.add(key)
            unique_roots.append(root)

    latest_candidates: List[Path] = []
    for root in unique_roots:
        try:
            if not root.exists():
                continue
            candidates.append(root / "resolve_controller_config.json")
            candidates.append(root / "davinci" / "resolve_controller_config.json")
            latest_candidates.extend([p for p in root.glob("data/*/davinci/resolve_controller_config.json") if p.is_file()])
        except Exception as exc:
            hard_debug("DISCOVER_CONFIG_ROOT_FAILED", {"root": str(root), "error": repr(exc)})

    # Exact candidates win before latest broad candidates.
    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.exists() and path.is_file():
                selected = str(path.resolve())
                hard_debug("DISCOVER_CONFIG_EXACT_OK", {"selected": selected})
                return selected
        except Exception:
            pass

    if latest_candidates:
        latest = max(latest_candidates, key=lambda p: p.stat().st_mtime)
        selected = str(latest.resolve())
        hard_debug("DISCOVER_CONFIG_LATEST_OK", {"selected": selected, "count": len(latest_candidates), "mtime": latest.stat().st_mtime})
        return selected

    hard_debug("DISCOVER_CONFIG_NONE", {"generic_path": generic_path, "roots": [str(r) for r in unique_roots]})
    return None


def load_controller_config(config_path: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    info: Dict[str, Any] = {
        "requested_path": config_path,
        "loaded": False,
        "path": None,
        "keys": [],
        "warnings": [],
        "errors": [],
    }
    if not config_path:
        return {}, info
    try:
        path = Path(config_path)
        if not path.exists():
            info["warnings"].append(f"Config file does not exist: {config_path}")
            return {}, info
        data = load_json(str(path))
        if not isinstance(data, dict):
            info["errors"].append("Config JSON root must be an object.")
            return {}, info
        info.update({
            "loaded": True,
            "path": str(path.resolve()),
            "keys": sorted([str(k) for k in data.keys()]),
        })
        hard_debug("CONTROLLER_CONFIG_LOADED", info)
        return data, info
    except Exception as exc:
        info["errors"].append(compact_exception(exc))
        hard_debug("CONTROLLER_CONFIG_LOAD_FAILED", {"path": config_path, "error": compact_exception(exc), "traceback": traceback.format_exc()})
        return {}, info


def config_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def config_int(value: Any, default: int = 0, min_value: Optional[int] = None) -> int:
    result = get_int(value, default)
    if min_value is not None:
        result = max(min_value, result)
    return result


def collect_cli_provided_dests(parser: argparse.ArgumentParser, argv: List[str]) -> set:
    provided = set()
    tokens = [str(a) for a in argv]
    for action in parser._actions:
        dest = getattr(action, "dest", None)
        if not dest or dest == "help":
            continue
        for opt in getattr(action, "option_strings", []) or []:
            if opt in tokens or any(token.startswith(opt + "=") for token in tokens):
                provided.add(dest)
    return provided


def apply_controller_config_to_args(args: argparse.Namespace, config: Dict[str, Any], cli_provided_dests: Optional[set] = None) -> Dict[str, Any]:
    """Apply resolve_controller_config.json values to parsed args.

    Config is designed for Resolve Workspace -> Scripts mode where CLI flags are
    unavailable. Explicit CLI args still win when the script is run externally.
    Environment overrides are applied later and can override config.
    """
    cli_provided_dests = cli_provided_dests or set()
    applied: Dict[str, Any] = {"applied": {}, "skipped_cli": [], "unknown_keys": [], "warnings": []}

    aliases = {
        "config": "config",
        "controller_config": "config",
        "resolve_controller_config": "config",
        "generic_path": "generic",
        "generic_edit_commands": "generic",
        "resolve_controller_report": "report",
        "report_path": "report",
        "debug_log_path": "debug_log",
        "caption_style_path": "caption_style",
        "caption_expected_report_path": "caption_expected_report",
        "fcpxml_report": "caption_expected_report",
        "textplus_full_timeline_report": "caption_expected_report",
        "textplus_track": "caption_textplus_track",
        "caption_textplus_enabled": "apply_caption_textplus",
        "apply_textplus": "apply_caption_textplus",
        "verify_textplus": "verify_caption_textplus",
        "animation": "caption_animation",
        "animation_mode": "caption_animation_mode",
        "max_textplus": "max_caption_textplus",
        "clear_old_textplus": "clear_old_vc_textplus",
    }

    path_keys = {
        "generic", "project_root", "report", "debug_log", "caption_expected_report", "caption_style", "caption_occlusion_analysis", "caption_occlusion_plan_output",
        "caption_occlusion_finalization_output", "caption_occlusion_finalization_state", "caption_occlusion_prior_step_2f_validation",
    }
    bool_keys = {
        "dry_run", "verify_only", "apply_zoom", "animated_zoom", "zoom_static_fallback",
        "clear_old_vc_zoom_tools", "attempt_speed", "apply_subtitles", "clear_old_vc_subtitles",
        "subtitle_track_guard", "subtitle_use_mark_in_out", "subtitle_strict_timing", "subtitle_stop_on_range_fail",
        "verify_captions", "caption_property_write_test", "apply_caption_textplus",
        "verify_caption_textplus", "caption_animation", "clear_old_vc_textplus", "caption_write_test",
        "caption_textplus_probe_only", "caption_keep_failed_probe_item", "caption_style_probe_only",
        "caption_shading_probe_only", "caption_apply_outline", "caption_apply_shadow",
        "caption_force_position_from_style", "caption_use_per_cue_style_events",
        "caption_disable_duration_strictness_for_probe",
        "caption_restore_static_titles_before_apply", "caption_allow_static_title_item_writes",
        "caption_compact_report", "caption_stop_on_first_failure", "apply_caption_occlusion", "caption_occlusion_plan_only",
        "caption_occlusion_bbox_fallback", "caption_occlusion_clear_old_v4", "caption_occlusion_stop_on_first_failure",
        "caption_occlusion_auto_rebuild_textplus_if_missing", "caption_occlusion_require_textplus_track",
        "caption_occlusion_require_editor_ready_assets", "caption_occlusion_reuse_media_pool_items",
        "caption_occlusion_set_straight_alpha", "caption_occlusion_require_v3_cue_linkage",
        "caption_occlusion_rollback_on_failure", "caption_occlusion_clear_legacy_bbox_v4",
        "caption_recovery_only_when_missing", "caption_recovery_clean_target_track",
        "caption_occlusion_finalize_major_step_2", "caption_occlusion_require_creation_and_reuse_passes",
        "add_debug_markers", "no_debug_markers", "clear_debug_markers",
    }
    int_keys = {
        "video_track", "audio_track", "duration_tolerance_frames", "subtitle_track",
        "subtitle_min_duration_frames", "max_subtitles", "caption_track",
        "caption_verify_sample_limit", "caption_timing_tolerance_frames", "caption_textplus_track",
        "caption_animation_sample_limit", "max_caption_textplus", "caption_probe_count",
        "caption_outline_element", "caption_shadow_element", "caption_checkpoint_interval",
        "caption_occlusion_target_track", "caption_occlusion_max_events", "caption_occlusion_bbox_padding_px",
        "caption_textplus_expected_count", "caption_occlusion_visual_review_frame",
    }
    float_keys = {
        "caption_force_textplus_size", "caption_textplus_size_scale",
        "caption_outline_thickness", "caption_outline_width_scale",
        "caption_shadow_offset_x", "caption_shadow_offset_y",
        "caption_shadow_opacity", "caption_shadow_softness",
        "caption_color_low_confidence_threshold", "caption_color_min_luma_gap", "caption_occlusion_min_score",
        "caption_occlusion_soft_edge", "caption_occlusion_verify_settle_timeout_sec",
        "caption_occlusion_verify_poll_interval_sec",
    }
    choice_values = {
        "timeline_backend": {"auto", "fcpxml_full", "otio_legacy"},
        "zoom_mode": {"start", "end", "average"},
        "clear_old_vc_zoom_scope": {"matching", "all"},
        "caption_static_title_policy": {"keep", "hide", "disable", "delete"},
        "caption_animation_mode": {"conservative", "full"},
        "caption_fill_color_policy": {"detected", "darkest_text_component_on_low_confidence", "force_black"},
        "caption_occlusion_asset_mode": {"rgba_sequence", "legacy_bbox"},
    }

    valid_keys = set(path_keys) | set(bool_keys) | set(int_keys) | set(float_keys) | set(choice_values.keys()) | {
        "subtitle_title_name", "caption_title_name", "caption_force_font_name",
        "caption_force_font_style", "caption_probe_text", "caption_probe_cue_id",
        "caption_font_fallback_order", "caption_occlusion_mask_root", "caption_occlusion_track_name",
        "caption_occlusion_item_prefix", "caption_occlusion_legacy_item_prefix",
        "caption_occlusion_alpha_mode", "caption_textplus_track_name", "config",
    }

    for raw_key, raw_value in config.items():
        key = aliases.get(str(raw_key), str(raw_key))
        if key == "config":
            continue
        if key not in valid_keys or not hasattr(args, key):
            applied["unknown_keys"].append(str(raw_key))
            continue
        if key in cli_provided_dests:
            applied["skipped_cli"].append(key)
            continue

        try:
            if key in path_keys:
                value = normalize_user_path(raw_value)
            elif key in bool_keys:
                value = config_bool(raw_value, bool(getattr(args, key, False)))
            elif key in int_keys:
                min_value = 1 if key.endswith("track") or key in {"video_track", "audio_track"} else 0
                value = config_int(raw_value, get_int(getattr(args, key, 0), 0), min_value=min_value)
            elif key in float_keys:
                nullable_float_keys = {
                    "caption_force_textplus_size",
                    "caption_outline_thickness",
                    "caption_shadow_opacity",
                    "caption_shadow_softness",
                }
                if raw_value is None or str(raw_value).strip() == "":
                    if key in nullable_float_keys:
                        value = None
                    elif key == "caption_textplus_size_scale":
                        value = 1.5
                    elif key == "caption_outline_width_scale":
                        value = 1.0
                    elif key in {"caption_shadow_offset_x", "caption_shadow_offset_y"}:
                        value = 0.003
                    else:
                        value = float(getattr(args, key, 0.0) or 0.0)
                else:
                    value = float(raw_value)
                    if key == "caption_force_textplus_size":
                        value = max(0.005, min(0.50, value))
                    elif key == "caption_textplus_size_scale":
                        value = max(0.10, min(10.0, value))
                    elif key == "caption_outline_thickness":
                        value = max(0.001, min(0.50, value))
                    elif key == "caption_outline_width_scale":
                        value = max(0.10, min(10.0, value))
                    elif key in {"caption_shadow_offset_x", "caption_shadow_offset_y"}:
                        value = max(-0.25, min(0.25, value))
                    elif key == "caption_shadow_opacity":
                        value = max(0.0, min(1.0, value))
                    elif key == "caption_shadow_softness":
                        value = max(0.0, min(0.50, value))
            elif key in choice_values:
                value = str(raw_value)
                if value not in choice_values[key]:
                    applied["warnings"].append(f"Ignored invalid {key}={raw_value!r}; allowed={sorted(choice_values[key])}")
                    continue
            else:
                value = str(raw_value) if raw_value is not None else None

            setattr(args, key, value)
            applied["applied"][key] = json_safe_value(value)
        except Exception as exc:
            applied["warnings"].append(f"Failed to apply config key {raw_key}: {compact_exception(exc)}")

    hard_debug("CONTROLLER_CONFIG_APPLIED", applied)
    return applied



class ResolveTimeoutError(RuntimeError):
    pass


def timed_call(label: str, fn: Any, timeout_seconds: float = 15.0) -> Any:
    """
    Run Resolve API calls with a timeout so n8n does not fail silently/hang forever.
    This is mainly for DaVinciResolveScript.scriptapp() and Project/Timeline calls.
    """
    hard_debug(f"{label}_START", {"timeout_seconds": timeout_seconds})
    q: "queue.Queue[Tuple[str, Any]]" = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            q.put(("ok", fn()))
        except Exception as exc:
            q.put(("err", exc))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        hard_debug(f"{label}_TIMEOUT", {"timeout_seconds": timeout_seconds})
        raise ResolveTimeoutError(
            f"{label} timed out after {timeout_seconds}s. "
            "Most likely Resolve scripting is blocked, Resolve is not open, "
            "or external scripting is not enabled."
        )

    status, value = q.get()
    if status == "err":
        hard_debug(f"{label}_ERROR", {"type": type(value).__name__, "error": str(value)})
        raise value

    hard_debug(f"{label}_OK", {"result_type": type(value).__name__, "truthy": bool(value)})
    return value


# -----------------------------
# Basic utilities
# -----------------------------


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_unix() -> float:
    return round(time.time(), 3)


def get_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def get_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(round(float(value)))
    except Exception:
        return default


def safe_call(obj: Any, method_name: str, *args: Any, default: Any = None) -> Any:
    try:
        method = getattr(obj, method_name, None)
        if not method:
            return default
        return method(*args)
    except Exception:
        return default


def safe_set_property(item: Any, prop_name: str, value: Any) -> Tuple[bool, Any]:
    """Set a Resolve TimelineItem property and return (ok, readback)."""
    try:
        ok = item.SetProperty(prop_name, value)
    except Exception:
        return False, None

    readback = None
    try:
        readback = item.GetProperty(prop_name)
    except Exception:
        pass

    return bool(ok), readback


# -----------------------------
# Resolve connection
# -----------------------------


def import_resolve_script_module() -> Any:
    """
    Import DaVinciResolveScript in the usual locations.

    This script can be run from:
    - Resolve Console / Scripts menu
    - External Python, if Resolve scripting paths are configured
    """
    hard_debug("IMPORT_RESOLVE_MODULE_START", {
        "python": sys.executable,
        "cwd": os.getcwd(),
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        "RESOLVE_SCRIPT_API": os.environ.get("RESOLVE_SCRIPT_API"),
    })

    try:
        import DaVinciResolveScript as dvr_script  # type: ignore
        hard_debug("IMPORT_RESOLVE_MODULE_DIRECT_OK", {"module": str(dvr_script)})
        return dvr_script
    except Exception as exc:
        hard_debug("IMPORT_RESOLVE_MODULE_DIRECT_FAILED", {"type": type(exc).__name__, "error": str(exc)})

    candidate_paths = []

    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    appdata = os.environ.get("APPDATA")

    candidate_paths.append(
        os.path.join(
            program_data,
            "Blackmagic Design",
            "DaVinci Resolve",
            "Support",
            "Developer",
            "Scripting",
            "Modules",
            "DaVinciResolveScript.py",
        )
    )

    if appdata:
        candidate_paths.append(
            os.path.join(
                appdata,
                "Blackmagic Design",
                "DaVinci Resolve",
                "Support",
                "Developer",
                "Scripting",
                "Modules",
                "DaVinciResolveScript.py",
            )
        )

    # Common Resolve Studio install path fallback.
    candidate_paths.append(
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Developer\Scripting\Modules\DaVinciResolveScript.py"
    )

    hard_debug("IMPORT_RESOLVE_MODULE_CANDIDATES", {
        "candidate_paths": candidate_paths,
        "exists": {path: os.path.exists(path) for path in candidate_paths},
    })

    for path in candidate_paths:
        hard_debug("IMPORT_RESOLVE_MODULE_TRY_PATH", {"path": path, "exists": os.path.exists(path)})
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("DaVinciResolveScript", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[attr-defined]
                hard_debug("IMPORT_RESOLVE_MODULE_PATH_OK", {"path": path, "module": str(module)})
                return module
            hard_debug("IMPORT_RESOLVE_MODULE_BAD_SPEC", {"path": path, "spec": str(spec)})

    raise RuntimeError(
        "Could not import DaVinciResolveScript. Run this from Resolve's Script menu, "
        "or configure Resolve scripting modules for your Python environment."
    )


def get_resolve_context() -> Tuple[Any, Any, Any, Any]:
    global FORCE_DIRECT_RESOLVE_CALLS

    hard_debug("GET_RESOLVE_CONTEXT_ENTER", {
        "force_direct_calls": FORCE_DIRECT_RESOLVE_CALLS,
        "internal_menu_mode": INTERNAL_MENU_MODE,
    })

    resolve = get_injected_resolve_handle()

    if resolve:
        # We are probably inside Resolve. Do not use threaded timeout calls.
        FORCE_DIRECT_RESOLVE_CALLS = True
        hard_debug("GET_RESOLVE_CONTEXT_USING_INJECTED_RESOLVE")
    else:
        dvr_script = import_resolve_script_module()
        hard_debug("GET_RESOLVE_CONTEXT_MODULE_READY", {"module_type": type(dvr_script).__name__})

        resolve = resolve_api_call(
            "RESOLVE_SCRIPTAPP",
            lambda: dvr_script.scriptapp("Resolve"),
            timeout_seconds=15.0,
        )

    if not resolve:
        raise RuntimeError(
            "Could not connect to DaVinci Resolve. If you use Resolve Free, run this from "
            "Workspace -> Scripts, or enable/check external scripting for external n8n execution."
        )

    project_manager = resolve_api_call(
        "RESOLVE_GET_PROJECT_MANAGER",
        lambda: resolve.GetProjectManager(),
        timeout_seconds=10.0,
    )
    if not project_manager:
        raise RuntimeError("Could not access ProjectManager.")

    project = resolve_api_call(
        "RESOLVE_GET_CURRENT_PROJECT",
        lambda: project_manager.GetCurrentProject(),
        timeout_seconds=10.0,
    )
    if not project:
        raise RuntimeError("No active Resolve project found.")

    timeline = resolve_api_call(
        "RESOLVE_GET_CURRENT_TIMELINE",
        lambda: project.GetCurrentTimeline(),
        timeout_seconds=10.0,
    )
    if not timeline:
        raise RuntimeError("No active timeline found. Import/select the OTIO timeline first.")

    hard_debug("GET_RESOLVE_CONTEXT_OK", {
        "project_type": type(project).__name__,
        "timeline_type": type(timeline).__name__,
        "direct_calls": FORCE_DIRECT_RESOLVE_CALLS,
    })
    return resolve, project_manager, project, timeline


# -----------------------------
# Generic command parsing
# -----------------------------


def validate_generic_commands(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["generic_edit_commands root must be an object"]
    if data.get("schema") != "generic_edit_commands":
        errors.append("schema must be generic_edit_commands")
    if not data.get("success"):
        errors.append("success must be true")
    if not isinstance(data.get("timeline"), list) or not data.get("timeline"):
        errors.append("timeline must be a non-empty list")
    source = data.get("source") or {}
    if get_float(source.get("fps"), 0.0) <= 0:
        errors.append("source.fps must be > 0")
    return errors


def get_fps(data: Dict[str, Any]) -> float:
    return get_float((data.get("source") or {}).get("fps"), 24.0) or 24.0


def command_duration_frames(cmd: Dict[str, Any], fps: float) -> int:
    source_clip = cmd.get("source_clip") or {}
    start_frame = source_clip.get("source_start_frame")
    end_frame = source_clip.get("source_end_frame")
    if start_frame is not None and end_frame is not None:
        return max(1, get_int(end_frame) - get_int(start_frame))
    duration_sec = get_float(source_clip.get("duration"), get_float(cmd.get("source_duration"), 0.0))
    return max(1, int(round(duration_sec * fps)))


def get_operation(cmd: Dict[str, Any], operation_name: str) -> Optional[Dict[str, Any]]:
    for op in cmd.get("operations") or []:
        if op.get("operation") == operation_name:
            return op
    return None


# -----------------------------
# Resolve timeline inspection
# -----------------------------


def get_track_items(timeline: Any, track_type: str, index: int) -> List[Any]:
    items = safe_call(timeline, "GetItemListInTrack", track_type, index, default=[])
    return list(items or [])


def timeline_item_summary(item: Any) -> Dict[str, Any]:
    name = safe_call(item, "GetName", default="")
    start = safe_call(item, "GetStart", default=None)
    end = safe_call(item, "GetEnd", default=None)
    duration = safe_call(item, "GetDuration", default=None)
    media_pool_item = safe_call(item, "GetMediaPoolItem", default=None)
    media_name = safe_call(media_pool_item, "GetName", default=None) if media_pool_item else None
    return {
        "name": name,
        "start": start,
        "end": end,
        "duration": duration,
        "media_pool_item_name": media_name,
    }


FCPXML_NATIVE_TRANSITION_NAME_HINTS = (
    "cross dissolve",
    "dissolve",
    "slide",
    "wipe",
    "fade",
    "transition",
    "push",
    "blur",
    "iris",
    "dip to",
)


def timeline_item_has_media_pool_item(item: Any) -> bool:
    media_pool_item = safe_call(item, "GetMediaPoolItem", default=None)
    return bool(media_pool_item)


def classify_timeline_item_for_mapping(item: Any) -> Dict[str, Any]:
    """Classify Resolve timeline items for controller mapping.

    Resolve's FCPXML importer exposes native transitions such as Cross Dissolve as
    separate timeline items on the same video track. If we map generic commands by
    simple index, every transition item shifts all following clips and zoom/speed
    actions are applied to the wrong clips.

    The stable rule for full FCPXML timelines is:
      - media-backed items on V1 are real video clips to map to generic commands
      - non-media items with transition-like names are imported native transitions
      - title/text items belong on upper caption tracks and are not command clips
    """
    summary = timeline_item_summary(item)
    name = str(summary.get("name") or "")
    name_l = name.lower().strip()
    media_name = summary.get("media_pool_item_name")
    has_media_pool_item = bool(media_name) or timeline_item_has_media_pool_item(item)

    transition_like = (
        not has_media_pool_item
        and any(hint in name_l for hint in FCPXML_NATIVE_TRANSITION_NAME_HINTS)
    )
    title_like = (
        not has_media_pool_item
        and not transition_like
        and ("text" in name_l or "title" in name_l or name_l.startswith("vc_sub"))
    )
    media_clip_like = bool(has_media_pool_item and not transition_like and not title_like)

    return {
        "name": name,
        "start": get_int(summary.get("start"), 0),
        "end": get_int(summary.get("end"), 0),
        "duration": get_int(summary.get("duration"), 0),
        "media_pool_item_name": media_name,
        "has_media_pool_item": has_media_pool_item,
        "transition_like": bool(transition_like),
        "title_like": bool(title_like),
        "media_clip_like": bool(media_clip_like),
        "summary": summary,
    }


def infer_effective_timeline_backend(args: argparse.Namespace, timeline_name: str, commands: List[Dict[str, Any]], clips: List[Any]) -> str:
    requested = str(getattr(args, "timeline_backend", "auto") or "auto").lower()
    if requested in {"fcpxml_full", "otio_legacy"}:
        return requested

    name_l = str(timeline_name or "").lower()
    if "textplus_full" in name_l or "textplus" in name_l or "fcpxml" in name_l:
        return "fcpxml_full"

    classifications = [classify_timeline_item_for_mapping(item) for item in clips]
    transition_like_count = sum(1 for c in classifications if c.get("transition_like"))
    media_clip_like_count = sum(1 for c in classifications if c.get("media_clip_like"))

    # Native FCPXML transitions usually appear as separate transition items on V1.
    # If removing them brings the media clip count back to command count, this is
    # almost certainly the full FCPXML route.
    if transition_like_count > 0 and media_clip_like_count == len(commands):
        return "fcpxml_full"

    if transition_like_count > 0 and len(clips) != len(commands):
        return "fcpxml_full"

    return "otio_legacy"


def map_commands_to_clips_stable(
    commands: List[Dict[str, Any]],
    clips: List[Any],
    timeline_backend: str = "auto",
    duration_tolerance_frames: int = 2,
) -> Tuple[List[Tuple[Dict[str, Any], Any]], Dict[str, Any]]:
    """Return stable command->clip mapping plus diagnostics.

    v0.5.3 fixes the FCPXML + native transitions case. Resolve imports native
    transitions as TimelineItems on the video track, so order-based zip() maps
    command 2 to a Cross Dissolve item, command 3 to the old clip 2, and so on.

    For fcpxml_full, we filter out transition/title-like non-media items first.
    For otio_legacy, we preserve old order mapping.
    """
    classifications = [classify_timeline_item_for_mapping(item) for item in clips]
    transition_items = [c for c in classifications if c.get("transition_like")]
    title_items = [c for c in classifications if c.get("title_like")]
    media_items_with_original_index: List[Tuple[int, Any, Dict[str, Any]]] = []
    for idx, (item, cls) in enumerate(zip(clips, classifications), start=1):
        if cls.get("media_clip_like"):
            media_items_with_original_index.append((idx, item, cls))

    effective_backend = str(timeline_backend or "auto")
    if effective_backend == "fcpxml_full":
        candidate_pairs = [(orig_idx, item, cls) for orig_idx, item, cls in media_items_with_original_index]
        strategy = "fcpxml_full_filter_native_transition_items"
    else:
        candidate_pairs = [(idx, item, cls) for idx, (item, cls) in enumerate(zip(clips, classifications), start=1)]
        strategy = "legacy_order_all_items"

    mapped: List[Tuple[Dict[str, Any], Any]] = []
    mapping_rows: List[Dict[str, Any]] = []
    for map_index, (cmd, pair) in enumerate(zip(commands, candidate_pairs), start=1):
        original_index, item, cls = pair
        # Use caller's normal verification later; keep this diagnostic compact here.
        mapped.append((cmd, item))
        mapping_rows.append({
            "map_index": map_index,
            "original_resolve_item_index": original_index,
            "command_id": cmd.get("command_id"),
            "shot_id": cmd.get("shot_id"),
            "item_name": cls.get("name"),
            "item_start": cls.get("start"),
            "item_end": cls.get("end"),
            "item_duration": cls.get("duration"),
            "media_pool_item_name": cls.get("media_pool_item_name"),
        })

    warnings: List[str] = []
    if len(candidate_pairs) != len(commands):
        warnings.append(
            f"Mapping candidate count mismatch after {strategy}: candidates={len(candidate_pairs)}, commands={len(commands)}. "
            f"Mapped min count={len(mapped)}."
        )

    info: Dict[str, Any] = {
        "strategy": strategy,
        "effective_timeline_backend": effective_backend,
        "input_items_count": len(clips),
        "commands_count": len(commands),
        "candidate_items_count": len(candidate_pairs),
        "mapped_count": len(mapped),
        "transition_like_items_count": len(transition_items),
        "title_like_items_count": len(title_items),
        "media_clip_like_items_count": len(media_items_with_original_index),
        "transition_like_items": transition_items[:50],
        "title_like_items": title_items[:20],
        "mapping_rows": mapping_rows[:200],
        "warnings": warnings,
    }
    return mapped, info


def map_commands_to_clips(commands: List[Dict[str, Any]], clips: List[Any]) -> List[Tuple[Dict[str, Any], Any]]:
    """Legacy compatibility wrapper. Prefer map_commands_to_clips_stable()."""
    return list(zip(commands, clips))



# -----------------------------
# Caption / title verification helpers
# -----------------------------

CAPTION_TEXT_INPUT_CANDIDATES = (
    "StyledText",
    "InputStyledText",
    "Text",
    "Title",
    "Value",
)

CAPTION_TRANSFORM_INPUT_CANDIDATES = (
    "Size",
    "Center",
    "Opacity",
    "Blend",
    "GlobalIn",
    "GlobalOut",
)

CAPTION_TIMELINE_PROPERTY_CANDIDATES = (
    "Text",
    "StyledText",
    "InputStyledText",
    "Title",
    "Size",
    "Center",
    "Opacity",
    "ZoomX",
    "ZoomY",
    "CompositeOpacity",
)

CAPTION_ITEM_METHOD_PROBES = (
    "GetName",
    "GetStart",
    "GetEnd",
    "GetDuration",
    "GetMediaPoolItem",
    "GetProperty",
    "SetProperty",
    "GetFusionCompCount",
    "GetFusionCompByIndex",
    "GetFusionCompNameList",
    "LoadFusionCompByName",
    "GetTrackTypeAndIndex",
)

CAPTION_COMP_METHOD_PROBES = (
    "GetToolList",
    "GetAttrs",
    "Lock",
    "Unlock",
)


def method_available(obj: Any, method_name: str) -> bool:
    try:
        return callable(getattr(obj, method_name, None))
    except Exception:
        return False


def json_safe_value(value: Any, max_string: int = 240) -> Any:
    """Convert Resolve/Fusion remote values to JSON-safe diagnostics."""
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str) and len(value) > max_string:
            return value[:max_string] + "..."
        return value
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in list(value.items())[:80]:
            out[str(k)] = json_safe_value(v, max_string=max_string)
        if len(value) > 80:
            out["_truncated_keys"] = len(value) - 80
        return out
    if isinstance(value, (list, tuple)):
        out_list = [json_safe_value(v, max_string=max_string) for v in list(value)[:80]]
        if len(value) > 80:
            out_list.append({"_truncated_items": len(value) - 80})
        return out_list
    try:
        text = str(value)
    except Exception:
        text = f"<{type(value).__name__}>"
    if len(text) > max_string:
        text = text[:max_string] + "..."
    return text


def caption_expected_report_candidates(generic_path: str, generic: Dict[str, Any]) -> List[Path]:
    candidates: List[Path] = []
    video_id = str(generic.get("video_id") or "").strip()
    try:
        gp = Path(generic_path)
        if video_id:
            candidates.append(gp.parent / f"{video_id}_textplus_full_timeline_report.json")
            candidates.append(gp.parent.parent / "davinci" / f"{video_id}_textplus_full_timeline_report.json")
            candidates.append(gp.parent.parent / "planning" / f"{video_id}_textplus_full_timeline_report.json")
        candidates.extend(gp.parent.glob("*_textplus_full_timeline_report.json"))
        candidates.extend((gp.parent.parent / "davinci").glob("*_textplus_full_timeline_report.json"))
    except Exception:
        pass

    out: List[Path] = []
    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def load_caption_expected_report(args: argparse.Namespace, generic: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "requested_path": getattr(args, "caption_expected_report", None),
        "loaded": False,
        "path": None,
        "cue_count": None,
        "raw_cue_count": None,
        "first_cue": None,
        "last_cue": None,
        "warnings": [],
        "errors": [],
    }

    candidates: List[Path] = []
    explicit = getattr(args, "caption_expected_report", None)
    if explicit:
        candidates.append(Path(str(explicit)))
    env_path = os.environ.get("VC_CAPTION_EXPECTED_REPORT")
    if env_path:
        candidates.append(Path(env_path))
    if getattr(args, "generic", None):
        candidates.extend(caption_expected_report_candidates(str(args.generic), generic))

    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if not path.exists():
                continue
            data = load_json(str(path))
            timing = data.get("timing") or {}
            result.update({
                "loaded": True,
                "path": str(path.resolve()),
                "cue_count": get_int(timing.get("cue_count"), 0),
                "raw_cue_count": get_int(timing.get("raw_cue_count"), 0),
                "first_cue": json_safe_value(timing.get("first_cue")),
                "last_cue": json_safe_value(timing.get("last_cue")),
            })
            return result
        except Exception as exc:
            result["errors"].append({"path": str(path), "error": compact_exception(exc)})

    if candidates:
        result["warnings"].append("No caption/FCPXML compiler report could be loaded from the candidate paths.")
    return result


def expected_caption_cues_from_generic(generic: Dict[str, Any], fps: float) -> List[Dict[str, Any]]:
    clips = generic.get("subtitle_clips") or []
    if not isinstance(clips, list):
        return []

    cues: List[Dict[str, Any]] = []
    for index, raw in enumerate(clips, start=1):
        if not isinstance(raw, dict):
            continue
        start_frame = get_int(raw.get("timeline_start_frame"), int(round(get_float(raw.get("timeline_start"), 0.0) * fps)))
        end_frame = get_int(raw.get("timeline_end_frame"), int(round(get_float(raw.get("timeline_end"), 0.0) * fps)))
        if end_frame < start_frame:
            end_frame = start_frame
        cues.append({
            "index": index,
            "id": raw.get("subtitle_id") or raw.get("id") or f"sub_{index:03d}",
            "text": str(raw.get("text") or ""),
            "start_seconds": round(start_frame / fps, 4) if fps else None,
            "end_seconds": round(end_frame / fps, 4) if fps else None,
            "duration_seconds": round(max(0, end_frame - start_frame) / fps, 4) if fps else None,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "duration_frames": max(0, end_frame - start_frame),
            "source": raw.get("source") or raw.get("unit_type"),
        })
    return cues


def actual_caption_item_record(item: Any, index: int, fps: float, caption_title_name: str = "") -> Dict[str, Any]:
    summary = timeline_item_summary(item)
    name = str(summary.get("name") or "")
    name_l = name.lower().strip()
    media_name = summary.get("media_pool_item_name")
    has_media_pool_item = bool(media_name) or timeline_item_has_media_pool_item(item)
    transition_like = (
        not has_media_pool_item
        and any(hint in name_l for hint in FCPXML_NATIVE_TRANSITION_NAME_HINTS)
    )

    title_name_l = str(caption_title_name or "").lower().replace(" ", "")
    normalized_name = name_l.replace(" ", "")
    textplus_like = (
        not has_media_pool_item
        and not transition_like
        and (
            "text+" in name_l
            or "textplus" in normalized_name
            or (title_name_l in {"text+", "textplus"} and ("text+" in name_l or "textplus" in normalized_name))
        )
    )
    explicit_basic_title_like = (
        not has_media_pool_item
        and not transition_like
        and (
            "basic title" in name_l
            or "title - text" in name_l
            or "title" in name_l
        )
    )

    # On the configured caption track, imported FCPXML Basic Title items may be
    # named after the word itself, e.g. "graduated", not "Basic Title". The only
    # stable Resolve-side signal is often: non-media + non-transition on V2.
    title_like = bool(not has_media_pool_item and not transition_like)
    basic_title_like = bool(title_like and not textplus_like and (explicit_basic_title_like or True))
    media_clip_like = bool(has_media_pool_item and not transition_like)
    unknown = not any((title_like, textplus_like, basic_title_like, media_clip_like, transition_like))

    start = get_int(summary.get("start"), 0)
    end = get_int(summary.get("end"), 0)
    duration = get_int(summary.get("duration"), max(0, end - start))

    method_availability = {name: method_available(item, name) for name in CAPTION_ITEM_METHOD_PROBES}
    fusion_comp_count_raw = safe_call(item, "GetFusionCompCount", default=None)
    fusion_comp_count = get_int(fusion_comp_count_raw, 0) if fusion_comp_count_raw is not None else None

    return {
        "index": index,
        "name": name,
        "start_frame": start,
        "end_frame": end,
        "duration_frames": duration,
        "start_seconds": round(start / fps, 4) if fps else None,
        "end_seconds": round(end / fps, 4) if fps else None,
        "duration_seconds": round(duration / fps, 4) if fps else None,
        "media_pool_item_name": media_name,
        "has_media_pool_item": has_media_pool_item,
        "classification": "transition_like" if transition_like else "media_clip_like" if media_clip_like else "textplus_like" if textplus_like else "basic_title_like" if basic_title_like else "title_like" if title_like else "unknown",
        "title_like": title_like,
        "textplus_like": bool(textplus_like),
        "basic_title_like": bool(basic_title_like),
        "media_clip_like": media_clip_like,
        "transition_like": bool(transition_like),
        "unknown": bool(unknown),
        "fusion_comp_count": fusion_comp_count,
        "method_availability": method_availability,
    }


def read_timeline_item_title_properties(item: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "can_call_get_property": method_available(item, "GetProperty"),
        "property_dict_available": False,
        "property_keys_sample": [],
        "candidate_values": {},
        "errors": [],
    }
    if not result["can_call_get_property"]:
        return result

    try:
        props = item.GetProperty()
        if isinstance(props, dict):
            result["property_dict_available"] = True
            result["property_keys_sample"] = [str(k) for k in list(props.keys())[:60]]
            for name in CAPTION_TIMELINE_PROPERTY_CANDIDATES:
                if name in props:
                    result["candidate_values"][name] = json_safe_value(props.get(name))
    except Exception as exc:
        result["errors"].append({"method": "GetProperty()", "error": compact_exception(exc)})

    for prop_name in CAPTION_TIMELINE_PROPERTY_CANDIDATES:
        try:
            value = item.GetProperty(prop_name)
            if value is not None and value != "":
                result["candidate_values"][prop_name] = json_safe_value(value)
        except Exception:
            pass

    return result


def get_existing_fusion_comp_readonly(item: Any) -> Tuple[Optional[Any], Dict[str, Any]]:
    info: Dict[str, Any] = {
        "attempted": True,
        "can_get_count": method_available(item, "GetFusionCompCount"),
        "can_get_by_index": method_available(item, "GetFusionCompByIndex"),
        "can_get_name_list": method_available(item, "GetFusionCompNameList"),
        "can_load_by_name": method_available(item, "LoadFusionCompByName"),
        "fusion_comp_count": None,
        "fusion_comp_names": [],
        "loaded": False,
        "loaded_by": None,
        "errors": [],
    }

    try:
        count_raw = safe_call(item, "GetFusionCompCount", default=None)
        info["fusion_comp_count"] = get_int(count_raw, 0) if count_raw is not None else None
        names_raw = safe_call(item, "GetFusionCompNameList", default=[]) or []
        if isinstance(names_raw, (list, tuple)):
            info["fusion_comp_names"] = [str(x) for x in names_raw[:20]]

        if get_int(info.get("fusion_comp_count"), 0) > 0:
            comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
            if comp:
                info["loaded"] = True
                info["loaded_by"] = "GetFusionCompByIndex(1)"
                return comp, info

        names = info.get("fusion_comp_names") or []
        if names:
            comp = safe_call(item, "LoadFusionCompByName", names[0], default=None)
            if comp:
                info["loaded"] = True
                info["loaded_by"] = f"LoadFusionCompByName({names[0]})"
                return comp, info
    except Exception as exc:
        info["errors"].append(compact_exception(exc))

    return None, info


def try_read_fusion_input(tool: Any, input_name: str) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []

    try:
        method = getattr(tool, "GetInput", None)
        if method:
            for call_args, label in (((input_name,), "GetInput(name)"), ((input_name, 0), "GetInput(name, 0)")):
                try:
                    value = method(*call_args)
                    attempts.append({"method": label, "input": input_name, "ok": True, "value": json_safe_value(value)})
                    if value is not None and value != "":
                        return {"ok": True, "input": input_name, "value": json_safe_value(value), "attempts": attempts}
                except Exception as exc:
                    attempts.append({"method": label, "input": input_name, "ok": False, "error": compact_exception(exc)})
    except Exception as exc:
        attempts.append({"method": "GetInput discovery", "input": input_name, "ok": False, "error": compact_exception(exc)})

    try:
        value = getattr(tool, input_name)
        attempts.append({"method": "getattr", "input": input_name, "ok": True, "value": json_safe_value(value)})
        if value is not None and value != "":
            return {"ok": True, "input": input_name, "value": json_safe_value(value), "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "getattr", "input": input_name, "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "input": input_name, "attempts": attempts[:4]}


def inspect_caption_property_access(item: Any, item_record: Dict[str, Any], write_test: bool = False) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "item_index": item_record.get("index"),
        "item_name": item_record.get("name"),
        "timeline_item_methods": item_record.get("method_availability") or {},
        "timeline_properties": read_timeline_item_title_properties(item),
        "fusion_comp": {},
        "comp_methods": {},
        "tools_count": 0,
        "tools_sample": [],
        "text_tool": None,
        "read_inputs": {},
        "can_access_fusion_comp": False,
        "can_access_text_tool": False,
        "can_read_text": False,
        "can_read_transform": False,
        "can_write_test_property": False,
        "write_test_skipped": not bool(write_test),
        "write_test_attempted": False,
        "warnings": [],
        "errors": [],
    }

    prop_values = (result.get("timeline_properties") or {}).get("candidate_values") or {}
    if any(str(k).lower() in {"text", "styledtext", "inputstyledtext", "title"} for k in prop_values.keys()):
        result["can_read_text"] = True
    if any(str(k).lower() in {"size", "center", "opacity", "zoomx", "zoomy", "compositeopacity"} for k in prop_values.keys()):
        result["can_read_transform"] = True

    comp, comp_info = get_existing_fusion_comp_readonly(item)
    result["fusion_comp"] = comp_info
    if not comp:
        return result

    result["can_access_fusion_comp"] = True
    result["comp_methods"] = {name: method_available(comp, name) for name in CAPTION_COMP_METHOD_PROBES}

    tools = list_fusion_tools(comp)
    result["tools_count"] = len(tools)
    result["tools_sample"] = [
        {"name": fusion_tool_name(t), "regid": fusion_tool_regid(t)} for t in tools[:20]
    ]

    text_tools = find_textplus_tools(comp)
    text_tool = text_tools[0] if text_tools else None
    if not text_tool:
        return result

    result["can_access_text_tool"] = True
    result["text_tool"] = {
        "name": fusion_tool_name(text_tool),
        "regid": fusion_tool_regid(text_tool),
        "attrs_keys_sample": [str(k) for k in list(safe_get_attrs(text_tool).keys())[:40]],
    }

    for input_name in CAPTION_TEXT_INPUT_CANDIDATES + CAPTION_TRANSFORM_INPUT_CANDIDATES:
        read_result = try_read_fusion_input(text_tool, input_name)
        if read_result.get("ok"):
            result["read_inputs"][input_name] = {
                "ok": True,
                "value": read_result.get("value"),
            }
            if input_name in CAPTION_TEXT_INPUT_CANDIDATES:
                result["can_read_text"] = True
            if input_name in CAPTION_TRANSFORM_INPUT_CANDIDATES:
                result["can_read_transform"] = True

    if write_test:
        # Keep this deliberately non-destructive. The controller must not mutate
        # imported captions during verification unless a later patch implements a
        # read -> write same value -> restore sequence for a specific Resolve build.
        result["write_test_attempted"] = False
        result["write_test_skipped"] = True
        result["warnings"].append("--caption-property-write-test was requested, but this patch keeps verification read-only and does not mutate caption properties.")

    return result


def caption_item_counts(records: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "actual_track_item_count": len(records),
        "title_like_items_count": sum(1 for r in records if r.get("title_like")),
        "textplus_like_items_count": sum(1 for r in records if r.get("textplus_like")),
        "basic_title_like_items_count": sum(1 for r in records if r.get("basic_title_like")),
        "media_clip_like_items_count": sum(1 for r in records if r.get("media_clip_like")),
        "transition_like_items_count": sum(1 for r in records if r.get("transition_like")),
        "unknown_items_count": sum(1 for r in records if r.get("unknown")),
    }


def scan_all_video_tracks_for_captions(timeline: Any, fps: float, caption_title_name: str = "") -> Dict[str, Any]:
    video_track_count = get_video_track_count(timeline)
    tracks: Dict[str, Any] = {}
    for track_index in range(1, video_track_count + 1):
        items = get_track_items(timeline, "video", track_index)
        records = [actual_caption_item_record(item, i, fps, caption_title_name=caption_title_name) for i, item in enumerate(items, start=1)]
        counts = caption_item_counts(records)
        tracks[str(track_index)] = {
            "track_index": track_index,
            **counts,
            "items_sample": [
                {
                    "index": r.get("index"),
                    "name": r.get("name"),
                    "classification": r.get("classification"),
                    "start_frame": r.get("start_frame"),
                    "end_frame": r.get("end_frame"),
                    "duration_frames": r.get("duration_frames"),
                    "media_pool_item_name": r.get("media_pool_item_name"),
                }
                for r in records[:12]
            ],
        }
    return {"video_track_count": video_track_count, "tracks": tracks}


def compare_caption_timing(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]], tolerance_frames: int = 1) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "passed": False,
        "compared_count": 0,
        "expected_count": len(expected),
        "actual_count": len(actual),
        "count_delta": len(actual) - len(expected),
        "tolerance_frames": max(0, get_int(tolerance_frames, 1)),
        "max_delta_frames": None,
        "avg_delta_frames": None,
        "first_deltas": None,
        "last_deltas": None,
        "largest_deltas_sample": [],
        "warnings": [],
    }
    if not expected:
        result["warnings"].append("No expected caption cues found in generic_edit_commands.subtitle_clips.")
        return result
    if not actual:
        result["warnings"].append("No actual title-like caption items found on the configured caption track.")
        return result

    pairs: List[Dict[str, Any]] = []
    for index, (exp, act) in enumerate(zip(expected, actual), start=1):
        start_delta = get_int(act.get("start_frame"), 0) - get_int(exp.get("start_frame"), 0)
        end_delta = get_int(act.get("end_frame"), 0) - get_int(exp.get("end_frame"), 0)
        duration_delta = get_int(act.get("duration_frames"), 0) - get_int(exp.get("duration_frames"), 0)
        max_abs = max(abs(start_delta), abs(end_delta), abs(duration_delta))
        pairs.append({
            "index": index,
            "expected_id": exp.get("id"),
            "expected_text": exp.get("text"),
            "actual_name": act.get("name"),
            "start_delta_frames": start_delta,
            "end_delta_frames": end_delta,
            "duration_delta_frames": duration_delta,
            "max_abs_delta_frames": max_abs,
        })

    deltas = [p["max_abs_delta_frames"] for p in pairs]
    result["compared_count"] = len(pairs)
    result["max_delta_frames"] = max(deltas) if deltas else None
    result["avg_delta_frames"] = round(sum(deltas) / len(deltas), 4) if deltas else None
    result["first_deltas"] = pairs[0] if pairs else None
    result["last_deltas"] = pairs[-1] if pairs else None
    result["largest_deltas_sample"] = sorted(pairs, key=lambda p: p.get("max_abs_delta_frames", 0), reverse=True)[:10]
    result["passed"] = (
        len(expected) == len(actual)
        and result["max_delta_frames"] is not None
        and result["max_delta_frames"] <= result["tolerance_frames"]
    )
    if len(expected) != len(actual):
        result["warnings"].append("Caption count mismatch. Timing may still be useful, but pass=false until counts match.")
    return result


def verify_imported_caption_track(timeline: Any, generic: Dict[str, Any], args: argparse.Namespace, fps: float) -> Dict[str, Any]:
    caption_track = max(1, get_int(getattr(args, "caption_track", getattr(args, "subtitle_track", 2)), 2))
    caption_title_name = str(getattr(args, "caption_title_name", getattr(args, "subtitle_title_name", "Text+")) or "")
    sample_limit = max(0, get_int(getattr(args, "caption_verify_sample_limit", 10), 10))
    timing_tolerance = max(0, get_int(getattr(args, "caption_timing_tolerance_frames", 1), 1))
    write_test = bool(getattr(args, "caption_property_write_test", False))

    result: Dict[str, Any] = {
        "enabled": True,
        "caption_track_index": caption_track,
        "caption_title_name": caption_title_name,
        "video_track_count": None,
        "expected_caption_count": 0,
        "expected_source": "generic.subtitle_clips",
        "fcpxml_compiler_report": None,
        "actual_track_item_count": 0,
        "title_like_items_count": 0,
        "textplus_like_items_count": 0,
        "basic_title_like_items_count": 0,
        "media_clip_like_items_count": 0,
        "transition_like_items_count": 0,
        "unknown_items_count": 0,
        "first_expected": None,
        "first_actual": None,
        "last_expected": None,
        "last_actual": None,
        "timing_check": None,
        "property_access": {
            "sample_limit": sample_limit,
            "sampled_count": 0,
            "can_access_fusion_comp": False,
            "can_access_text_tool": False,
            "can_read_text": False,
            "can_read_transform": False,
            "can_write_test_property": False,
            "write_test_skipped": not write_test,
            "sample_results": [],
        },
        "track_scan": None,
        "items_sample": [],
        "warnings": [],
        "errors": [],
    }

    hard_debug("CAPTION_VERIFY_START", {
        "caption_track": caption_track,
        "caption_title_name": caption_title_name,
        "sample_limit": sample_limit,
        "timing_tolerance_frames": timing_tolerance,
        "write_test": write_test,
    })

    try:
        result["video_track_count"] = get_video_track_count(timeline)
        expected = expected_caption_cues_from_generic(generic, fps)
        result["expected_caption_count"] = len(expected)
        result["first_expected"] = expected[0] if expected else None
        result["last_expected"] = expected[-1] if expected else None
        result["fcpxml_compiler_report"] = load_caption_expected_report(args, generic)

        if caption_track > get_int(result.get("video_track_count"), 0):
            result["warnings"].append(f"Configured caption track V{caption_track} is above current video track count {result.get('video_track_count')}.")

        items = get_track_items(timeline, "video", caption_track)
        hard_debug("CAPTION_TRACK_SCAN", {
            "caption_track": caption_track,
            "video_track_count": result.get("video_track_count"),
            "items_count": len(items),
        })

        records: List[Dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            record = actual_caption_item_record(item, index, fps, caption_title_name=caption_title_name)
            records.append(record)
            hard_debug("CAPTION_ITEM_CLASSIFIED", {
                "track": caption_track,
                "index": index,
                "name": record.get("name"),
                "classification": record.get("classification"),
                "start_frame": record.get("start_frame"),
                "end_frame": record.get("end_frame"),
                "duration_frames": record.get("duration_frames"),
                "media_pool_item_name": record.get("media_pool_item_name"),
            })

        counts = caption_item_counts(records)
        result.update(counts)
        result["items_sample"] = [
            {
                "index": r.get("index"),
                "name": r.get("name"),
                "classification": r.get("classification"),
                "start_frame": r.get("start_frame"),
                "end_frame": r.get("end_frame"),
                "duration_frames": r.get("duration_frames"),
                "start_seconds": r.get("start_seconds"),
                "end_seconds": r.get("end_seconds"),
                "media_pool_item_name": r.get("media_pool_item_name"),
                "fusion_comp_count": r.get("fusion_comp_count"),
                "method_availability": r.get("method_availability"),
            }
            for r in records[:max(0, sample_limit)]
        ]

        title_like_records = [r for r in records if r.get("title_like")]
        compare_records = title_like_records if title_like_records else records
        result["first_actual"] = compare_records[0] if compare_records else None
        result["last_actual"] = compare_records[-1] if compare_records else None

        timing_check = compare_caption_timing(expected, compare_records, tolerance_frames=timing_tolerance)
        result["timing_check"] = timing_check
        hard_debug("CAPTION_TIMING_CHECK", timing_check)

        samples_to_inspect = title_like_records[:sample_limit] if sample_limit > 0 else []
        for record in samples_to_inspect:
            # records are index-aligned to the original items list.
            item_index = max(1, get_int(record.get("index"), 1)) - 1
            if item_index < 0 or item_index >= len(items):
                continue
            access = inspect_caption_property_access(items[item_index], record, write_test=write_test)
            result["property_access"]["sample_results"].append(access)
            result["property_access"]["sampled_count"] += 1
            if access.get("can_access_fusion_comp"):
                result["property_access"]["can_access_fusion_comp"] = True
            if access.get("can_access_text_tool"):
                result["property_access"]["can_access_text_tool"] = True
            if access.get("can_read_text"):
                result["property_access"]["can_read_text"] = True
            if access.get("can_read_transform"):
                result["property_access"]["can_read_transform"] = True
            if access.get("can_write_test_property"):
                result["property_access"]["can_write_test_property"] = True

        result["property_access"]["write_test_skipped"] = not bool(write_test) or not result["property_access"].get("can_write_test_property")
        hard_debug("CAPTION_PROPERTY_ACCESS_CHECK", {
            "sampled_count": result["property_access"].get("sampled_count"),
            "can_access_fusion_comp": result["property_access"].get("can_access_fusion_comp"),
            "can_access_text_tool": result["property_access"].get("can_access_text_tool"),
            "can_read_text": result["property_access"].get("can_read_text"),
            "can_read_transform": result["property_access"].get("can_read_transform"),
        })

        if len(items) == 0 or len(title_like_records) == 0 or len(title_like_records) != len(expected):
            result["track_scan"] = scan_all_video_tracks_for_captions(timeline, fps, caption_title_name=caption_title_name)

        if len(items) == 0:
            result["warnings"].append(f"No items found on configured caption track V{caption_track}. Inspect track_scan to find where captions landed.")
        elif len(title_like_records) == 0:
            result["warnings"].append(f"Items exist on V{caption_track}, but none were classified as title-like. Inspect items_sample and track_scan.")
        elif len(title_like_records) != len(expected):
            result["warnings"].append(f"Title-like caption count mismatch on V{caption_track}: actual={len(title_like_records)}, expected={len(expected)}.")

        report_warnings = ((result.get("fcpxml_compiler_report") or {}).get("warnings") or [])
        if report_warnings:
            result["warnings"].extend([f"FCPXML report: {w}" for w in report_warnings])

    except Exception as exc:
        result["errors"].append(compact_exception(exc))
        hard_debug("CAPTION_VERIFY_EXCEPTION", {"error": compact_exception(exc), "traceback": traceback.format_exc()})

    hard_debug("CAPTION_VERIFY_DONE", {
        "expected_caption_count": result.get("expected_caption_count"),
        "actual_track_item_count": result.get("actual_track_item_count"),
        "title_like_items_count": result.get("title_like_items_count"),
        "textplus_like_items_count": result.get("textplus_like_items_count"),
        "basic_title_like_items_count": result.get("basic_title_like_items_count"),
        "timing_passed": (result.get("timing_check") or {}).get("passed"),
        "warnings": result.get("warnings"),
        "errors": result.get("errors"),
    })
    return result


# -----------------------------
# Marker helpers
# -----------------------------


RESOLVE_MARKER_COLORS = ["Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream"]


def normalize_marker_color(color: str) -> str:
    title = str(color or "Blue").strip().title()
    return title if title in RESOLVE_MARKER_COLORS else "Blue"


def add_timeline_marker(timeline: Any, frame_id: int, color: str, name: str, note: str, duration: int = 1, custom_data: str = "") -> bool:
    try:
        return bool(timeline.AddMarker(frame_id, normalize_marker_color(color), name, note, max(1, duration), custom_data))
    except Exception:
        return False


def marker_note(payload: Dict[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        return str(payload)


def truthy_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def make_run_id() -> str:
    return str(int(time.time() * 1000))


def short_run_id(run_id: str) -> str:
    return str(run_id)[-6:]


def get_timeline_marker_frames(timeline: Any) -> List[int]:
    """
    Resolve usually allows only one marker at a given timeline frame.
    We read existing marker frames so controller markers can shift slightly instead
    of silently failing when OTIO/import markers already occupy the clip start.
    """
    markers = safe_call(timeline, "GetMarkers", default={})
    frames: List[int] = []
    if isinstance(markers, dict):
        for key in markers.keys():
            try:
                frames.append(get_int(key, 0))
            except Exception:
                pass
    return sorted(set(frames))


def find_non_conflicting_marker_frame(
    timeline: Any,
    preferred_frame: int,
    min_frame: int = 0,
    max_frame: Optional[int] = None,
    search_radius: int = 18,
    prefer_forward: bool = True,
) -> Dict[str, Any]:
    preferred = max(min_frame, get_int(preferred_frame, 0))
    occupied = set(get_timeline_marker_frames(timeline))

    offsets: List[int] = [0]
    for i in range(1, max(1, search_radius) + 1):
        if prefer_forward:
            offsets.extend([i, -i])
        else:
            offsets.extend([-i, i])

    tried: List[int] = []
    for offset in offsets:
        candidate = preferred + offset
        if candidate < min_frame:
            continue
        if max_frame is not None and candidate > max_frame:
            continue
        tried.append(candidate)
        if candidate not in occupied:
            return {
                "frame": candidate,
                "preferred_frame": preferred,
                "shift": candidate - preferred,
                "conflict": candidate != preferred,
                "occupied_count": len(occupied),
                "tried": tried[:20],
            }

    # Last-resort fallback: still return preferred. AddMarker may fail, but the
    # report will make that visible.
    return {
        "frame": preferred,
        "preferred_frame": preferred,
        "shift": 0,
        "conflict": preferred in occupied,
        "occupied_count": len(occupied),
        "tried": tried[:20],
        "fallback": True,
    }


def add_non_conflicting_timeline_marker(
    timeline: Any,
    preferred_frame: int,
    color: str,
    name: str,
    note: str,
    duration: int = 1,
    custom_data: str = "",
    min_frame: int = 0,
    max_frame: Optional[int] = None,
    search_radius: int = 18,
    prefer_forward: bool = True,
) -> Dict[str, Any]:
    placement = find_non_conflicting_marker_frame(
        timeline=timeline,
        preferred_frame=preferred_frame,
        min_frame=min_frame,
        max_frame=max_frame,
        search_radius=search_radius,
        prefer_forward=prefer_forward,
    )
    frame_id = get_int(placement.get("frame"), preferred_frame)
    ok = add_timeline_marker(
        timeline=timeline,
        frame_id=frame_id,
        color=color,
        name=name,
        note=note,
        duration=duration,
        custom_data=custom_data,
    )
    return {
        "attempted": True,
        "applied": bool(ok),
        "requested_frame": get_int(preferred_frame, 0),
        "frame": frame_id,
        "placement": placement,
        "name": name,
        "custom_data": custom_data,
    }


VC_DEBUG_MARKER_NAME_PREFIXES = (
    "VC_DEBUG_",
    "VC_TRANSITION_",
    "VC_CONTROLLER_RAN_",
)


def marker_info_name(marker_info: Any) -> str:
    if isinstance(marker_info, dict):
        return str(marker_info.get("name") or marker_info.get("Name") or "")
    return ""


def marker_info_custom_data(marker_info: Any) -> str:
    if isinstance(marker_info, dict):
        return str(
            marker_info.get("customData")
            or marker_info.get("custom_data")
            or marker_info.get("customDataString")
            or ""
        )
    return ""


def marker_is_video_cloner_debug(marker_info: Any) -> bool:
    """Return True only for markers generated by this controller's debug mode.

    Important: this intentionally does NOT delete OTIO/import markers such as
    VC_OP_001_cut. Those may be useful as visual operation markers. It only removes
    controller debug markers that create the black JSON overlay/flood.
    """
    name = marker_info_name(marker_info)
    custom_data = marker_info_custom_data(marker_info)
    if any(name.startswith(prefix) for prefix in VC_DEBUG_MARKER_NAME_PREFIXES):
        return True
    if custom_data.startswith("video_cloner:transition:"):
        return True
    if custom_data.startswith("video_cloner:controller_ran:"):
        return True
    return False


def delete_marker_at_frame(timeline: Any, frame_id: int) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    frame_id = get_int(frame_id, 0)

    for method_name in ("DeleteMarkerAtFrame", "DeleteMarkerByFrame"):
        try:
            method = getattr(timeline, method_name, None)
            if not method:
                attempts.append({"method": method_name, "ok": False, "reason": "method_missing"})
                continue
            ok = method(frame_id)
            attempts.append({"method": method_name, "frame": frame_id, "ok": bool(ok)})
            if ok:
                return {"ok": True, "frame": frame_id, "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": method_name, "frame": frame_id, "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "frame": frame_id, "attempts": attempts}


def clear_video_cloner_debug_markers(timeline: Any) -> Dict[str, Any]:
    """Best-effort cleanup for old controller debug markers.

    This prevents repeated internal Resolve runs from filling the timeline with
    blue/red JSON markers. It preserves imported OTIO operation markers.
    """
    markers = safe_call(timeline, "GetMarkers", default={})
    result: Dict[str, Any] = {
        "attempted": True,
        "markers_seen": 0,
        "matched_count": 0,
        "deleted_count": 0,
        "matched": [],
        "delete_attempts": [],
        "ok": True,
    }

    if not isinstance(markers, dict):
        result["ok"] = False
        result["reason"] = "timeline.GetMarkers did not return a dict"
        return result

    result["markers_seen"] = len(markers)
    for frame_raw, marker_info in markers.items():
        try:
            frame_id = get_int(frame_raw, 0)
        except Exception:
            frame_id = 0
        if not marker_is_video_cloner_debug(marker_info):
            continue
        result["matched_count"] += 1
        match = {
            "frame": frame_id,
            "name": marker_info_name(marker_info),
            "custom_data": marker_info_custom_data(marker_info),
        }
        result["matched"].append(match)
        del_result = delete_marker_at_frame(timeline, frame_id)
        result["delete_attempts"].append(del_result)
        if del_result.get("ok"):
            result["deleted_count"] += 1

    result["ok"] = result["deleted_count"] == result["matched_count"]
    return result


# -----------------------------
# Fusion helpers for animated zoom
# -----------------------------


def compact_exception(exc: Exception) -> Dict[str, Any]:
    return {"type": type(exc).__name__, "error": str(exc)}


def safe_get_attrs(obj: Any) -> Dict[str, Any]:
    attrs = safe_call(obj, "GetAttrs", default={})
    return attrs if isinstance(attrs, dict) else {}


def fusion_tool_name(tool: Any) -> str:
    try:
        return str(tool.Name)
    except Exception:
        return str(safe_call(tool, "GetAttrs", default={}).get("TOOLS_Name", ""))


def fusion_tool_regid(tool: Any) -> str:
    attrs = safe_get_attrs(tool)
    for key in ("TOOLS_RegID", "TOOLB_Name", "TOOLST_RegID"):
        value = attrs.get(key)
        if value:
            return str(value)
    return ""


def get_fusion_tools(comp: Any) -> Dict[Any, Any]:
    tools = safe_call(comp, "GetToolList", False, default={})
    if isinstance(tools, dict):
        return tools
    return {}


def list_fusion_tools(comp: Any) -> List[Any]:
    tools = get_fusion_tools(comp)
    return [tool for _, tool in tools.items()]


def find_fusion_tools_by_name_prefix(comp: Any, prefix: str) -> List[Any]:
    prefix_l = str(prefix or "").lower()
    matches: List[Any] = []
    for tool in list_fusion_tools(comp):
        name = fusion_tool_name(tool)
        if name.lower().startswith(prefix_l):
            matches.append(tool)
    return matches


def find_fusion_tools_by_exact_name(comp: Any, exact_name: str) -> List[Any]:
    exact_l = str(exact_name or "").lower()
    matches: List[Any] = []
    for tool in list_fusion_tools(comp):
        if fusion_tool_name(tool).lower() == exact_l:
            matches.append(tool)
    return matches


def delete_fusion_tool(comp: Any, tool: Any) -> Dict[str, Any]:
    """
    Try known Fusion deletion methods without assuming one specific API surface.
    """
    tool_name = fusion_tool_name(tool)
    attempts: List[Dict[str, Any]] = []

    # Method 1: comp.DeleteTool(tool)
    try:
        method = getattr(comp, "DeleteTool", None)
        if method:
            ok = method(tool)
            attempts.append({"method": "comp.DeleteTool(tool)", "ok": bool(ok), "tool": tool_name})
            if ok:
                return {"ok": True, "tool": tool_name, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "comp.DeleteTool(tool)", "ok": False, "tool": tool_name, "error": compact_exception(exc)})

    # Method 2: tool.Delete()
    try:
        method = getattr(tool, "Delete", None)
        if method:
            ok = method()
            # Some Fusion methods return None on success.
            success = True if ok is None else bool(ok)
            attempts.append({"method": "tool.Delete()", "ok": success, "tool": tool_name})
            if success:
                return {"ok": True, "tool": tool_name, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "tool.Delete()", "ok": False, "tool": tool_name, "error": compact_exception(exc)})

    # Method 3: comp.DeleteTool(name)
    try:
        method = getattr(comp, "DeleteTool", None)
        if method and tool_name:
            ok = method(tool_name)
            attempts.append({"method": "comp.DeleteTool(name)", "ok": bool(ok), "tool": tool_name})
            if ok:
                return {"ok": True, "tool": tool_name, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "comp.DeleteTool(name)", "ok": False, "tool": tool_name, "error": compact_exception(exc)})

    return {"ok": False, "tool": tool_name, "attempts": attempts}


def set_fusion_tool_name(tool: Any, name: str) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []

    try:
        tool.SetAttrs({"TOOLS_Name": name})
        attempts.append({"method": "SetAttrs(TOOLS_Name)", "ok": True, "name": name})
        return {"ok": True, "name": name, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "SetAttrs(TOOLS_Name)", "ok": False, "error": compact_exception(exc)})

    try:
        setattr(tool, "Name", name)
        attempts.append({"method": "setattr(Name)", "ok": True, "name": name})
        return {"ok": True, "name": name, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "setattr(Name)", "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "name": name, "attempts": attempts}


def set_fusion_input_static(tool: Any, input_name: str, value: Any) -> Dict[str, Any]:
    """
    Best-effort reset of a Fusion input before writing keyframes.
    This helps reused VC_Zoom tools avoid stale values. It may or may not remove
    old splines depending on the Resolve/Fusion runtime, so the report keeps the
    exact attempts visible.
    """
    attempts: List[Dict[str, Any]] = []

    try:
        method = getattr(tool, "SetInput", None)
        if method:
            ok = method(input_name, value)
            attempts.append({"method": "SetInput(name, value)", "ok": bool(ok), "value": value})
            if ok:
                return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "SetInput(name, value)", "ok": False, "error": compact_exception(exc)})

    try:
        setattr(tool, input_name, value)
        attempts.append({"method": f"setattr({input_name}, value)", "ok": True, "value": value})
        return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": f"setattr({input_name}, value)", "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "attempts": attempts}



def find_fusion_tool(comp: Any, wanted_regids: List[str], wanted_names: List[str]) -> Optional[Any]:
    wanted_regids_l = {x.lower() for x in wanted_regids}
    wanted_names_l = {x.lower() for x in wanted_names}

    tools = get_fusion_tools(comp)
    for _, tool in tools.items():
        name = fusion_tool_name(tool).lower()
        regid = fusion_tool_regid(tool).lower()
        if name in wanted_names_l or regid in wanted_regids_l:
            return tool

    # fallback: contains match, because Resolve sometimes names imported tools differently.
    for _, tool in tools.items():
        name = fusion_tool_name(tool).lower()
        regid = fusion_tool_regid(tool).lower()
        if any(x in name for x in wanted_names_l if x) or any(x in regid for x in wanted_regids_l if x):
            return tool

    return None


def get_or_create_fusion_comp(item: Any) -> Tuple[Optional[Any], Dict[str, Any]]:
    """
    Get or create a Fusion comp for a timeline item.

    This is deliberately defensive. Resolve/Fusion scripting behavior differs
    between internal menu runs, external scripting, Free/Studio, and versions.
    """
    info: Dict[str, Any] = {
        "attempted": True,
        "existing_count": None,
        "created": False,
        "loaded_by": None,
        "errors": [],
    }

    try:
        count = get_int(safe_call(item, "GetFusionCompCount", default=0), 0)
        info["existing_count"] = count

        if count > 0:
            comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
            if comp:
                info["loaded_by"] = "GetFusionCompByIndex(1)"
                return comp, info

            names = safe_call(item, "GetFusionCompNameList", default=[]) or []
            if names:
                comp = safe_call(item, "LoadFusionCompByName", names[0], default=None)
                if comp:
                    info["loaded_by"] = f"LoadFusionCompByName({names[0]})"
                    return comp, info

        comp = safe_call(item, "AddFusionComp", default=None)
        if comp:
            info["created"] = True
            info["loaded_by"] = "AddFusionComp()"
            return comp, info

        info["errors"].append("Could not get or create Fusion comp.")
        return None, info

    except Exception as exc:
        info["errors"].append(compact_exception(exc))
        return None, info


def _fusion_output_candidates(source_tool: Any) -> List[Tuple[str, Any]]:
    """Return usable Fusion Output handles for a source tool.

    Fusion mask tools do not consistently expose `.Output` through Resolve's
    PyRemoteObject bridge. The official Fusion API exposes FindMainOutput(), and
    Operator.ConnectInput() can also accept the Tool object directly.
    """
    candidates: List[Tuple[str, Any]] = []
    seen: set = set()

    def add(label: str, value: Any) -> None:
        if value is None:
            return
        marker = repr(value)
        if marker in seen:
            return
        seen.add(marker)
        candidates.append((label, value))

    add("tool_object", source_tool)

    for attr_name in ("Output", "Mask", "MainOutput1"):
        try:
            add(f"attr:{attr_name}", getattr(source_tool, attr_name, None))
        except Exception:
            pass

    for index in range(1, 5):
        try:
            output = safe_call(source_tool, "FindMainOutput", index, default=None)
            if not output:
                break
            add(f"FindMainOutput({index})", output)
        except Exception:
            break

    try:
        output_list = safe_call(source_tool, "GetOutputList", default={}) or {}
        values = output_list.values() if isinstance(output_list, dict) else output_list
        for index, output in enumerate(values or [], start=1):
            add(f"GetOutputList:{index}", output)
    except Exception:
        pass

    return candidates


def _fusion_input_candidates(dest_tool: Any, requested_name: str) -> List[Tuple[str, Any]]:
    candidates: List[Tuple[str, Any]] = []
    seen: set = set()

    def add(label: str, value: Any) -> None:
        if value is None:
            return
        marker = repr(value)
        if marker in seen:
            return
        seen.add(marker)
        candidates.append((label, value))

    names = [str(requested_name)]
    normalized = re.sub(r"[^a-z0-9]", "", str(requested_name).lower())
    if normalized == "effectmask":
        names.extend(["EffectMask", "Effect Mask"])

    for name in names:
        try:
            add(f"attr:{name}", getattr(dest_tool, name, None))
        except Exception:
            pass

    try:
        input_list = safe_call(dest_tool, "GetInputList", default={}) or {}
        values = input_list.values() if isinstance(input_list, dict) else input_list
        for input_obj in values or []:
            attrs = safe_call(input_obj, "GetAttrs", default={}) or {}
            input_id = str(attrs.get("INPS_ID") or attrs.get("INPS_Name") or "")
            input_norm = re.sub(r"[^a-z0-9]", "", input_id.lower())
            if input_norm == normalized:
                add(f"GetInputList:{input_id}", input_obj)
    except Exception:
        pass

    return candidates


def connect_fusion_tools(source_tool: Any, dest_tool: Any, dest_input_name: str = "Input") -> Dict[str, Any]:
    """Connect a Fusion source tool/output to a destination input.

    Uses the documented Operator.ConnectInput(input, Tool|Output) form first,
    then direct PlainInput.ConnectTo(Output) and assignment fallbacks.
    """
    attempts: List[Dict[str, Any]] = []
    outputs = _fusion_output_candidates(source_tool)
    input_names = [str(dest_input_name)]
    if re.sub(r"[^a-z0-9]", "", str(dest_input_name).lower()) == "effectmask":
        input_names.extend(["Effect Mask"])

    method = getattr(dest_tool, "ConnectInput", None)
    if method:
        for input_name in input_names:
            for output_label, output in outputs:
                try:
                    ok = method(input_name, output)
                    attempts.append({
                        "method": "ConnectInput(name, Tool|Output)",
                        "input": input_name,
                        "source": output_label,
                        "ok": bool(ok),
                    })
                    if ok:
                        return {"ok": True, "attempts": attempts, "connected_by": "Operator.ConnectInput"}
                except Exception as exc:
                    attempts.append({
                        "method": "ConnectInput(name, Tool|Output)",
                        "input": input_name,
                        "source": output_label,
                        "ok": False,
                        "error": compact_exception(exc),
                    })

    input_candidates = _fusion_input_candidates(dest_tool, dest_input_name)
    output_handles = [(label, value) for label, value in outputs if label != "tool_object"]

    for input_label, input_obj in input_candidates:
        connect_to = getattr(input_obj, "ConnectTo", None)
        if connect_to:
            for output_label, output in output_handles:
                try:
                    ok = connect_to(output)
                    attempts.append({
                        "method": "PlainInput.ConnectTo(Output)",
                        "input": input_label,
                        "source": output_label,
                        "ok": bool(ok),
                    })
                    if ok:
                        return {"ok": True, "attempts": attempts, "connected_by": "PlainInput.ConnectTo"}
                except Exception as exc:
                    attempts.append({
                        "method": "PlainInput.ConnectTo(Output)",
                        "input": input_label,
                        "source": output_label,
                        "ok": False,
                        "error": compact_exception(exc),
                    })

    for input_name in input_names:
        for output_label, output in output_handles:
            try:
                setattr(dest_tool, input_name, output)
                attempts.append({
                    "method": "setattr(dest, input, Output)",
                    "input": input_name,
                    "source": output_label,
                    "ok": True,
                })
                return {"ok": True, "attempts": attempts, "connected_by": "assignment"}
            except Exception as exc:
                attempts.append({
                    "method": "setattr(dest, input, Output)",
                    "input": input_name,
                    "source": output_label,
                    "ok": False,
                    "error": compact_exception(exc),
                })

    return {"ok": False, "attempts": attempts}

def set_fusion_input_keyframe(tool: Any, input_name: str, frame: int, value: Any) -> Dict[str, Any]:
    """
    Set a Fusion input keyframe. Tries common Python Fusion API forms.

    In Fusion scripting, animated inputs are commonly addressable with indexed
    frame assignment, for example tool.Size[0] = 1.0.
    """
    attempts: List[Dict[str, Any]] = []
    frame = max(0, get_int(frame, 0))

    # Method 1: tool.Size[frame] = value
    try:
        inp = getattr(tool, input_name)
        inp[frame] = value
        attempts.append({"method": f"{input_name}[frame] = value", "ok": True, "frame": frame, "value": value})
        return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": f"{input_name}[frame] = value", "ok": False, "error": compact_exception(exc)})

    # Method 2: tool.SetInput("Size", value, frame)
    try:
        method = getattr(tool, "SetInput", None)
        if method:
            ok = method(input_name, value, frame)
            attempts.append({"method": "SetInput(name, value, frame)", "ok": bool(ok), "frame": frame, "value": value})
            if ok:
                return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "SetInput(name, value, frame)", "ok": False, "error": compact_exception(exc)})

    # Method 3: tool.SetInput("Size", value) as non-animated fallback.
    try:
        method = getattr(tool, "SetInput", None)
        if method:
            ok = method(input_name, value)
            attempts.append({"method": "SetInput(name, value)", "ok": bool(ok), "frame": frame, "value": value})
            if ok:
                return {"ok": True, "attempts": attempts, "warning": "Non-keyframed fallback was used."}
    except Exception as exc:
        attempts.append({"method": "SetInput(name, value)", "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "attempts": attempts}


def apply_fusion_animated_zoom(
    item: Any,
    cmd: Dict[str, Any],
    fps: float,
    expected_duration_frames: int,
    clear_old_vc_zoom_tools: bool = False,
    clear_old_vc_zoom_scope: str = "matching",
) -> Dict[str, Any]:
    """
    Real animated zoom using per-clip Fusion Transform keyframes.

    v0.4 makes the Fusion graph idempotent:
        - target tool name is deterministic: VC_Zoom_<shot_id>
        - existing matching VC_Zoom tool is reused/updated
        - duplicate matching tools are removed when possible
        - optional rebuild mode can clear old VC_Zoom tools before creating a clean one
    """
    op = get_operation(cmd, "transform_zoom")
    if not op:
        return {"attempted": False, "reason": "no transform_zoom operation"}

    params = op.get("parameters") or {}
    shot_id = cmd.get("shot_id")
    target_tool_name = f"VC_Zoom_{shot_id}"
    start_scale = get_float(params.get("start_scale"), 1.0)
    end_scale = get_float(params.get("end_scale"), 1.0)
    duration_frames = max(2, get_int(expected_duration_frames, 2))
    last_frame = max(1, duration_frames - 1)

    result: Dict[str, Any] = {
        "attempted": True,
        "operation": "fusion_transform_zoom",
        "requested": {
            "start_scale": start_scale,
            "end_scale": end_scale,
            "duration_frames": duration_frames,
            "keyframes": [
                {"frame": 0, "size": start_scale},
                {"frame": last_frame, "size": end_scale},
            ],
            "direction": params.get("direction"),
            "easing": params.get("easing"),
            "target_tool_name": target_tool_name,
        },
        "fusion_comp": {},
        "tool_management": {
            "target_tool_name": target_tool_name,
            "clear_old_requested": bool(clear_old_vc_zoom_tools),
            "clear_old_scope": clear_old_vc_zoom_scope,
            "existing_vc_zoom_count": 0,
            "existing_matching_count": 0,
            "deleted_count": 0,
            "delete_attempts": [],
            "reused": False,
            "created": False,
            "replaced": False,
            "duplicate_matches_removed": 0,
            "reset_before_keyframes": None,
        },
        "graph": {},
        "keyframes": [],
        "applied": False,
        "fallback_recommended": False,
    }

    comp, comp_info = get_or_create_fusion_comp(item)
    result["fusion_comp"] = comp_info

    if not comp:
        result["fallback_recommended"] = True
        result["error"] = "No Fusion comp available."
        return result

    try:
        # Lock/Unlock are not mandatory, but when available they reduce UI churn.
        safe_call(comp, "Lock", default=None)

        media_in = find_fusion_tool(comp, ["MediaIn"], ["MediaIn1"])
        media_out = find_fusion_tool(comp, ["MediaOut"], ["MediaOut1"])

        if not media_in:
            result["graph"]["media_in_found"] = False
            result["fallback_recommended"] = True
            return result
        if not media_out:
            result["graph"]["media_out_found"] = False
            result["fallback_recommended"] = True
            return result

        vc_zoom_tools = find_fusion_tools_by_name_prefix(comp, "VC_Zoom_")
        matching_tools = find_fusion_tools_by_exact_name(comp, target_tool_name)
        result["tool_management"]["existing_vc_zoom_count"] = len(vc_zoom_tools)
        result["tool_management"]["existing_matching_count"] = len(matching_tools)
        result["tool_management"]["existing_vc_zoom_names"] = [fusion_tool_name(t) for t in vc_zoom_tools]
        result["tool_management"]["existing_matching_names"] = [fusion_tool_name(t) for t in matching_tools]

        if clear_old_vc_zoom_tools:
            scope = str(clear_old_vc_zoom_scope or "matching").lower()
            if scope == "all":
                tools_to_delete = vc_zoom_tools
            else:
                tools_to_delete = matching_tools

            deleted_matching = False
            for old_tool in list(tools_to_delete):
                old_name = fusion_tool_name(old_tool)
                del_result = delete_fusion_tool(comp, old_tool)
                result["tool_management"]["delete_attempts"].append(del_result)
                if del_result.get("ok"):
                    result["tool_management"]["deleted_count"] += 1
                    if old_name.lower() == target_tool_name.lower():
                        deleted_matching = True

            result["tool_management"]["replaced"] = bool(deleted_matching or tools_to_delete)
            # Refresh after deletion attempt.
            vc_zoom_tools = find_fusion_tools_by_name_prefix(comp, "VC_Zoom_")
            matching_tools = find_fusion_tools_by_exact_name(comp, target_tool_name)
            result["tool_management"]["remaining_vc_zoom_count_after_clear"] = len(vc_zoom_tools)
            result["tool_management"]["remaining_matching_count_after_clear"] = len(matching_tools)

        transform = None
        if matching_tools:
            transform = matching_tools[0]
            result["tool_management"]["reused"] = True

            # Remove duplicate target tools so subsequent runs stay clean.
            duplicate_tools = matching_tools[1:]
            for duplicate in duplicate_tools:
                del_result = delete_fusion_tool(comp, duplicate)
                result["tool_management"]["delete_attempts"].append(del_result)
                if del_result.get("ok"):
                    result["tool_management"]["deleted_count"] += 1
                    result["tool_management"]["duplicate_matches_removed"] += 1
        else:
            transform = safe_call(comp, "AddTool", "Transform", -32768, -32768, default=None)
            result["tool_management"]["created"] = bool(transform)
            if transform:
                result["tool_management"]["name_set"] = set_fusion_tool_name(transform, target_tool_name)

        result["graph"].update({
            "media_in": fusion_tool_name(media_in),
            "media_out": fusion_tool_name(media_out),
            "transform": fusion_tool_name(transform) if transform else None,
            "transform_created": bool(result["tool_management"]["created"]),
            "transform_reused": bool(result["tool_management"]["reused"]),
            "transform_replaced": bool(result["tool_management"]["replaced"]),
        })

        if not transform:
            result["fallback_recommended"] = True
            result["error"] = "Could not create/find Transform tool."
            return result

        # Reset the current Size value before writing keyframes. This is mostly useful
        # when reusing an existing VC_Zoom tool. It does not guarantee spline deletion
        # in every Resolve build, so clean rebuild is available with --clear-old-vc-zoom-tools.
        result["tool_management"]["reset_before_keyframes"] = set_fusion_input_static(transform, "Size", start_scale)

        connect_1 = connect_fusion_tools(media_in, transform, "Input")
        connect_2 = connect_fusion_tools(transform, media_out, "Input")
        result["graph"]["connect_media_in_to_transform"] = connect_1
        result["graph"]["connect_transform_to_media_out"] = connect_2

        k0 = set_fusion_input_keyframe(transform, "Size", 0, start_scale)
        k1 = set_fusion_input_keyframe(transform, "Size", last_frame, end_scale)
        result["keyframes"] = [k0, k1]

        result["applied"] = bool(connect_1.get("ok") and connect_2.get("ok") and k0.get("ok") and k1.get("ok"))
        result["fallback_recommended"] = not result["applied"]

        return result

    except Exception as exc:
        result["error"] = compact_exception(exc)
        result["traceback"] = traceback.format_exc()
        result["fallback_recommended"] = True
        return result
    finally:
        try:
            safe_call(comp, "Unlock", default=None)
        except Exception:
            pass



def add_controller_ran_marker(timeline: Any, first_frame: int, generic_path: str, run_id: str) -> Dict[str, Any]:
    payload = {
        "controller": VERSION,
        "event": "controller_ran",
        "run_id": run_id,
        "generic_path": generic_path,
        "created_at_unix": now_unix(),
    }
    return add_non_conflicting_timeline_marker(
        timeline=timeline,
        preferred_frame=max(0, get_int(first_frame, 0) + 1),
        color="Green",
        name=f"VC_CONTROLLER_RAN_{short_run_id(run_id)}",
        note=marker_note(payload),
        duration=24,
        custom_data=f"video_cloner:controller_ran:{VERSION}:{run_id}",
        search_radius=48,
        prefer_forward=True,
    )



# -----------------------------
# Layer appliers
# -----------------------------


def apply_zoom(
    item: Any,
    cmd: Dict[str, Any],
    mode: str = "end",
    animated: bool = False,
    static_fallback: bool = True,
    fps: float = 24.0,
    expected_duration_frames: int = 1,
    clear_old_vc_zoom_tools: bool = False,
    clear_old_vc_zoom_scope: str = "matching",
) -> Dict[str, Any]:
    """
    Apply zoom.

    Preferred v0.4 strategy:
        - Try real animated zoom through a Fusion Transform node with Size keyframes.
        - If that fails, fall back to old static ZoomX/ZoomY clip properties.

    This is the correct step for Video Cloner right now: prove whether Resolve/Fusion
    accepts per-clip animated transforms from the internal script runtime.
    """
    op = get_operation(cmd, "transform_zoom")
    if not op:
        return {"attempted": False, "reason": "no transform_zoom operation"}

    params = op.get("parameters") or {}
    start_scale = get_float(params.get("start_scale"), 1.0)
    end_scale = get_float(params.get("end_scale"), 1.0)

    result: Dict[str, Any] = {
        "attempted": True,
        "operation": "transform_zoom",
        "animated_requested": bool(animated),
        "static_fallback_enabled": bool(static_fallback),
        "animated": None,
        "static": None,
        "applied": False,
        "applied_mode": None,
    }

    if animated:
        animated_result = apply_fusion_animated_zoom(
            item=item,
            cmd=cmd,
            fps=fps,
            expected_duration_frames=expected_duration_frames,
            clear_old_vc_zoom_tools=clear_old_vc_zoom_tools,
            clear_old_vc_zoom_scope=clear_old_vc_zoom_scope,
        )
        result["animated"] = animated_result
        if animated_result.get("applied"):
            result["applied"] = True
            result["applied_mode"] = "fusion_keyframed_zoom"
            return result

    if not static_fallback:
        result["applied"] = False
        result["applied_mode"] = None
        return result

    if mode == "start":
        scale = start_scale
    elif mode == "average":
        scale = round((start_scale + end_scale) / 2.0, 6)
    else:
        scale = end_scale

    ok_x, readback_x = safe_set_property(item, "ZoomX", scale)
    ok_y, readback_y = safe_set_property(item, "ZoomY", scale)

    static_result = {
        "attempted": True,
        "operation": "static_clip_property_zoom",
        "mode": mode,
        "requested": {
            "start_scale": start_scale,
            "end_scale": end_scale,
            "applied_static_scale": scale,
            "direction": params.get("direction"),
            "easing": params.get("easing"),
        },
        "set_property": {
            "ZoomX": {"ok": ok_x, "readback": readback_x},
            "ZoomY": {"ok": ok_y, "readback": readback_y},
        },
        "applied": bool(ok_x and ok_y),
        "limitation": "Static zoom only. Used as fallback when Fusion animated zoom is disabled or unavailable.",
    }
    result["static"] = static_result

    if static_result.get("applied"):
        result["applied"] = True
        result["applied_mode"] = "static_clip_property_zoom"

    return result

def apply_speed_change_attempt(item: Any, cmd: Dict[str, Any]) -> Dict[str, Any]:
    """
    Attempt constant speed change.

    DaVinci's public scripting support for retime/speed ramps is inconsistent.
    This function intentionally tests several likely property names and reports what works.
    """
    op = get_operation(cmd, "speed_ramp")
    if not op:
        return {"attempted": False, "reason": "no speed_ramp operation"}

    params = op.get("parameters") or {}
    multiplier = get_float(params.get("speed_multiplier"), 1.0)
    percent = round(multiplier * 100.0, 4)

    properties_before = safe_call(item, "GetProperty", default={})
    if not isinstance(properties_before, dict):
        properties_before = {}

    candidates = [
        ("SpeedChange", percent),
        ("Speed", percent),
        ("RetimeSpeed", percent),
    ]

    attempts = []
    applied = False

    for prop_name, value in candidates:
        ok, readback = safe_set_property(item, prop_name, value)
        attempts.append({"property": prop_name, "value": value, "ok": ok, "readback": readback})
        if ok:
            applied = True
            break

    return {
        "attempted": True,
        "operation": "speed_ramp",
        "requested": {
            "speed_multiplier": multiplier,
            "constant_speed_percent_attempt": percent,
            "ramp_in_percent": params.get("ramp_in_percent"),
            "hold_percent": params.get("hold_percent"),
            "ramp_out_percent": params.get("ramp_out_percent"),
            "style": params.get("style"),
        },
        "available_property_keys_before": sorted(list(properties_before.keys()))[:200],
        "attempts": attempts,
        "applied": applied,
        "limitation": "This is not a real speed ramp. It only attempts constant speed if Resolve exposes a compatible property.",
    }


def transition_report_only(cmd: Dict[str, Any]) -> Dict[str, Any]:
    op = get_operation(cmd, "transition_hint")
    if not op:
        return {"attempted": False, "reason": "no transition_hint operation"}

    params = op.get("parameters") or {}
    return {
        "attempted": True,
        "operation": "transition_hint",
        "requested": params,
        "applied": False,
        "limitation": "Native Resolve transition insertion is not reliably available through basic TimelineItem API. Use controller fallback: UI automation, preset timeline, or FCPXML transition compiler.",
    }



# -----------------------------
# Subtitle / Text+ helpers
# -----------------------------

VC_SUBTITLE_PREFIX = "VC_Sub_"
VC_SUBTITLE_TEXT_TOOL_PREFIX = "VC_SubText_"
VC_CAPTION_TEXTPLUS_PREFIX = "VC_TEXTPLUS_"
VC_CAPTION_TEXT_TOOL_PREFIX = "VC_CaptionText_"


def clamp_float(value: Any, min_value: float, max_value: float, default: float) -> float:
    try:
        if value is None:
            return default
        value_f = float(value)
        if value_f < min_value:
            return min_value
        if value_f > max_value:
            return max_value
        return value_f
    except Exception:
        return default


def parse_hex_color(value: Any, fallback: Tuple[float, float, float] = (1.0, 1.0, 1.0)) -> Tuple[float, float, float]:
    """Return RGB floats in 0..1 from #rrggbb-like input."""
    if not isinstance(value, str):
        return fallback
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return fallback
    try:
        r = int(text[0:2], 16) / 255.0
        g = int(text[2:4], 16) / 255.0
        b = int(text[4:6], 16) / 255.0
        return (round(r, 6), round(g, 6), round(b, 6))
    except Exception:
        return fallback


def color_luma_from_hex(value: Any, fallback: float = 1.0) -> float:
    """Return Rec.709 relative luma for a #RRGGBB color."""
    if not isinstance(value, str) or len(value.strip().lstrip("#")) != 6:
        return fallback
    r, g, b = parse_hex_color(value, fallback=(fallback, fallback, fallback))
    return round((0.2126 * r) + (0.7152 * g) + (0.0722 * b), 6)


def resolve_caption_fill_color(style: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    """Resolve a renderer fill from detector fill/stroke evidence.

    This does not pretend to repair upstream OCR/color detection. It is an
    opt-in rendering heuristic for cases where a low-confidence detector event
    reports a medium/bright fill while a much darker text component is present
    in the same event. The selected source and reason are always reported.
    """
    policy = str(getattr(args, "caption_fill_color_policy", "detected") or "detected").strip().lower()
    threshold = clamp_float(
        getattr(args, "caption_color_low_confidence_threshold", 0.70),
        0.0, 1.0, 0.70,
    )
    min_gap = clamp_float(
        getattr(args, "caption_color_min_luma_gap", 0.12),
        0.0, 1.0, 0.12,
    )
    detection = style.get("color_detection") if isinstance(style.get("color_detection"), dict) else {}
    detected_fill = style.get("text_color")
    detected_stroke = style.get("stroke_color")
    confidence_score = get_float(detection.get("confidence_score"), 0.0)
    fill_luma = color_luma_from_hex(detected_fill, fallback=1.0)
    stroke_luma = color_luma_from_hex(detected_stroke, fallback=1.0)

    selected = detected_fill
    source = "detected_fill"
    reason = "detected policy"

    if policy == "force_black":
        selected = "#000000"
        source = "explicit_policy"
        reason = "caption_fill_color_policy=force_black"
    elif policy == "darkest_text_component_on_low_confidence":
        low_confidence = confidence_score < threshold
        darker_stroke_available = (
            isinstance(detected_stroke, str)
            and stroke_luma + min_gap < fill_luma
        )
        if low_confidence and darker_stroke_available:
            selected = detected_stroke
            source = "stroke_as_fill_low_confidence"
            reason = (
                "low-confidence color event and stroke/text component is "
                "substantially darker than detected fill"
            )
        else:
            reason = (
                "kept detected fill because confidence/luma gate did not justify "
                "a darker-component fallback"
            )

    style["text_color"] = selected
    resolution = {
        "policy": policy,
        "detected_fill": detected_fill,
        "detected_stroke": detected_stroke,
        "confidence_score": confidence_score,
        "confidence_label": detection.get("confidence_label"),
        "confidence_threshold": threshold,
        "minimum_luma_gap": min_gap,
        "detected_fill_luma": fill_luma,
        "detected_stroke_luma": stroke_luma,
        "selected_fill": selected,
        "selection_source": source,
        "reason": reason,
        "style_event_id": style.get("style_event_id"),
    }
    style["color_resolution"] = resolution
    return resolution


def normalize_caption_style(generic: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize several caption_style_resolved shapes into one simple controller style.

    The generic compiler may emit either the v2/v2.1 flattened style or a richer
    nested style from analysis. This function keeps Resolve-specific code from
    depending on a single upstream schema variant.
    """
    raw = generic.get("caption_style_resolved") or {}
    if not isinstance(raw, dict):
        raw = {}

    text_obj = raw.get("text") if isinstance(raw.get("text"), dict) else {}
    stroke_obj = raw.get("stroke") if isinstance(raw.get("stroke"), dict) else {}
    placement_obj = raw.get("placement") if isinstance(raw.get("placement"), dict) else {}

    placement = raw.get("placement")
    if isinstance(placement, dict):
        placement = placement.get("label") or placement.get("name")
    placement = placement or raw.get("position") or "bottom_center"

    text_color = (
        raw.get("text_color")
        or raw.get("fill_color")
        or text_obj.get("fill_color")
        or text_obj.get("text_color")
        or "#ffffff"
    )
    stroke_color = (
        raw.get("stroke_color")
        or raw.get("outline_color")
        or stroke_obj.get("color")
        or text_obj.get("stroke_color")
        or "#000000"
    )

    font_size_px = (
        raw.get("font_size_px")
        or raw.get("font_size")
        or raw.get("estimated_font_size")
        or text_obj.get("font_size_px")
    )

    # Resolve/Fusion Text+ Size is normalized, not pixels. Use a sensible vertical
    # reels default if no OCR style was cloned.
    size_norm = raw.get("resolve_textplus_size") or raw.get("textplus_size")
    if size_norm is None:
        if font_size_px:
            size_norm = clamp_float(get_float(font_size_px, 54.0) / 900.0, 0.035, 0.12, 0.062)
        else:
            size_norm = 0.062

    stroke_width = (
        raw.get("stroke_width_px")
        or raw.get("stroke_width")
        or raw.get("outline_width")
        or stroke_obj.get("width_px")
        or text_obj.get("stroke_width_px")
        or 2
    )

    case_style = raw.get("case_style") or text_obj.get("case") or "preserve"

    return {
        "raw": raw,
        "placement": str(placement),
        "font_family": raw.get("font_family") or text_obj.get("font_family") or "Arial",
        "font_weight": raw.get("font_weight") or text_obj.get("font_weight") or "bold",
        "font_size_px": font_size_px,
        "textplus_size": clamp_float(size_norm, 0.025, 0.20, 0.062),
        "text_color": text_color,
        "stroke_color": stroke_color,
        "stroke_width": get_float(stroke_width, 2.0),
        "case_style": case_style,
        "animation": raw.get("animation") or "none",
        "source": raw.get("source") or raw.get("style_source") or "unknown",
        "safe_area": raw.get("safe_area") or {},
        "placement_raw": placement_obj,
    }


def apply_case_style(text: str, case_style: str) -> str:
    case_style_l = str(case_style or "preserve").lower()
    if case_style_l in {"upper", "uppercase", "all_caps"}:
        return text.upper()
    if case_style_l in {"lower", "lowercase"}:
        return text.lower()
    if case_style_l in {"title", "title_case"}:
        return text.title()
    return text


def fusion_center_for_placement(placement: str) -> List[float]:
    """
    Fusion Text+ Center uses normalized image coordinates. These defaults are
    vertical-reels friendly and can be refined later from OCR style data.
    """
    p = str(placement or "bottom_center").lower()
    x = 0.5
    y = 0.16

    if "top" in p:
        y = 0.84
    elif "middle" in p or "center" == p:
        y = 0.50
    elif "bottom" in p:
        y = 0.16

    if "left" in p:
        x = 0.22
    elif "right" in p:
        x = 0.78
    elif "center" in p:
        x = 0.50

    return [round(x, 4), round(y, 4)]


def frame_to_timecode(frame_id: int, fps: float) -> str:
    """Convert Resolve absolute timeline frame id into non-drop HH:MM:SS:FF."""
    fps_i = max(1, int(round(fps or 24.0)))
    frame_id = max(0, get_int(frame_id, 0))
    hours = frame_id // (fps_i * 3600)
    rem = frame_id % (fps_i * 3600)
    minutes = rem // (fps_i * 60)
    rem = rem % (fps_i * 60)
    seconds = rem // fps_i
    frames = rem % fps_i
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def set_timeline_current_frame(timeline: Any, absolute_frame: int, fps: float) -> Dict[str, Any]:
    tc = frame_to_timecode(absolute_frame, fps)
    attempts: List[Dict[str, Any]] = []

    try:
        method = getattr(timeline, "SetCurrentTimecode", None)
        if method:
            ok = method(tc)
            attempts.append({"method": "SetCurrentTimecode", "timecode": tc, "ok": bool(ok)})
            if ok:
                return {"ok": True, "absolute_frame": absolute_frame, "timecode": tc, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "SetCurrentTimecode", "timecode": tc, "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "absolute_frame": absolute_frame, "timecode": tc, "attempts": attempts}


def set_timeline_mark_in_out(timeline: Any, mark_in: int, mark_out: int, mark_type: str = "video") -> Dict[str, Any]:
    """
    Set Resolve timeline in/out marks before inserting a title.

    Resolve's title insertion API only documents titleName as an argument, but in/out
    marks often control the inserted title's duration from the UI/runtime. This is
    the safest non-ripple way to ask Resolve for a short Text+ item.
    """
    mark_in = max(0, get_int(mark_in, 0))
    mark_out = max(mark_in, get_int(mark_out, mark_in))
    attempts: List[Dict[str, Any]] = []

    for args in (
        (mark_in, mark_out, mark_type),
        (mark_in, mark_out, "all"),
        (mark_in, mark_out),
    ):
        try:
            method = getattr(timeline, "SetMarkInOut", None)
            if not method:
                attempts.append({"method": "SetMarkInOut", "args": args, "ok": False, "reason": "method_missing"})
                break
            ok = method(*args)
            attempts.append({"method": "SetMarkInOut", "args": args, "ok": bool(ok)})
            if ok:
                return {"ok": True, "mark_in": mark_in, "mark_out": mark_out, "mark_type": mark_type, "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "SetMarkInOut", "args": args, "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "mark_in": mark_in, "mark_out": mark_out, "mark_type": mark_type, "attempts": attempts}


def clear_timeline_mark_in_out(timeline: Any) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for args in (("all",), ("video",), tuple()):
        try:
            method = getattr(timeline, "ClearMarkInOut", None)
            if not method:
                attempts.append({"method": "ClearMarkInOut", "args": args, "ok": False, "reason": "method_missing"})
                break
            ok = method(*args)
            attempts.append({"method": "ClearMarkInOut", "args": args, "ok": bool(ok)})
            if ok:
                return {"ok": True, "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "ClearMarkInOut", "args": args, "ok": False, "error": compact_exception(exc)})
    return {"ok": False, "attempts": attempts}


def get_track_count(timeline: Any, track_type: str) -> int:
    count = safe_call(timeline, "GetTrackCount", track_type, default=0)
    return max(0, get_int(count, 0))


def get_video_track_count(timeline: Any) -> int:
    return get_track_count(timeline, "video")


def get_audio_track_count(timeline: Any) -> int:
    return get_track_count(timeline, "audio")


def get_track_lock_state(timeline: Any, track_type: str, track_index: int) -> Optional[bool]:
    value = safe_call(timeline, "GetIsTrackLocked", track_type, track_index, default=None)
    if value is None:
        return None
    return bool(value)


def set_track_lock_state(timeline: Any, track_type: str, track_index: int, locked: bool) -> Dict[str, Any]:
    try:
        method = getattr(timeline, "SetTrackLock", None)
        if not method:
            return {"ok": False, "track_type": track_type, "track_index": track_index, "locked": locked, "reason": "method_missing"}
        ok = method(track_type, track_index, bool(locked))
        readback = get_track_lock_state(timeline, track_type, track_index)
        return {"ok": bool(ok), "track_type": track_type, "track_index": track_index, "locked": bool(locked), "readback": readback}
    except Exception as exc:
        return {"ok": False, "track_type": track_type, "track_index": track_index, "locked": locked, "error": compact_exception(exc)}


def snapshot_track_locks(timeline: Any) -> Dict[str, Dict[int, Optional[bool]]]:
    snapshot: Dict[str, Dict[int, Optional[bool]]] = {"video": {}, "audio": {}}
    for track_type in ("video", "audio"):
        for idx in range(1, get_track_count(timeline, track_type) + 1):
            snapshot[track_type][idx] = get_track_lock_state(timeline, track_type, idx)
    return snapshot


def apply_subtitle_track_guard(timeline: Any, subtitle_track: int) -> Dict[str, Any]:
    """
    Lock every non-subtitle video track and all audio tracks while inserting Text+.

    Resolve title insertion is playhead/track-state driven. Locking V1/A1 is the
    strongest available API-level protection against accidentally rippling or
    pushing imported video/audio while creating overlay subtitles.
    """
    subtitle_track = max(1, get_int(subtitle_track, 2))
    before = snapshot_track_locks(timeline)
    attempts: List[Dict[str, Any]] = []

    for idx in range(1, get_video_track_count(timeline) + 1):
        attempts.append(set_track_lock_state(timeline, "video", idx, idx != subtitle_track))
    for idx in range(1, get_audio_track_count(timeline) + 1):
        attempts.append(set_track_lock_state(timeline, "audio", idx, True))

    return {
        "attempted": True,
        "subtitle_track": subtitle_track,
        "lock_snapshot_before": before,
        "attempts": attempts,
        "lock_snapshot_during": snapshot_track_locks(timeline),
    }


def restore_track_locks(timeline: Any, guard: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = (guard or {}).get("lock_snapshot_before") or {}
    attempts: List[Dict[str, Any]] = []
    for track_type, tracks in snapshot.items():
        if not isinstance(tracks, dict):
            continue
        for idx_raw, locked in tracks.items():
            if locked is None:
                continue
            attempts.append(set_track_lock_state(timeline, str(track_type), get_int(idx_raw, 1), bool(locked)))
    return {"attempted": True, "attempts": attempts, "lock_snapshot_after_restore": snapshot_track_locks(timeline)}


def timeline_item_track_info(item: Any) -> Dict[str, Any]:
    value = safe_call(item, "GetTrackTypeAndIndex", default=None)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return {"track_type": value[0], "track_index": get_int(value[1], 0), "raw": list(value)}
    return {"track_type": None, "track_index": None, "raw": value}


def timeline_item_unique_id(item: Any) -> Optional[str]:
    value = safe_call(item, "GetUniqueId", default=None)
    return str(value) if value else None


def timeline_item_is_title_like(item: Any) -> bool:
    name = timeline_item_name(item).lower()
    media_pool_item = safe_call(item, "GetMediaPoolItem", default=None)
    media_name = safe_call(media_pool_item, "GetName", default=None) if media_pool_item else None
    if name.startswith(VC_SUBTITLE_PREFIX.lower()):
        return True
    if name in {"text+", "text plus", "text", "fusion title"}:
        return True
    if media_pool_item is None and ("text" in name or not media_name):
        return True
    return False


def find_subtitle_track_title_items(timeline: Any, subtitle_track: int, include_title_like: bool = True) -> List[Any]:
    items = get_track_items(timeline, "video", max(1, get_int(subtitle_track, 2)))
    out: List[Any] = []
    for item in items:
        name = timeline_item_name(item)
        if name.startswith(VC_SUBTITLE_PREFIX):
            out.append(item)
        elif include_title_like and timeline_item_is_title_like(item):
            out.append(item)
    return out


def snapshot_core_tracks(timeline: Any, video_track: int, audio_track: int) -> Dict[str, List[Dict[str, Any]]]:
    def pack(track_type: str, track_index: int) -> List[Dict[str, Any]]:
        packed: List[Dict[str, Any]] = []
        for item in get_track_items(timeline, track_type, track_index):
            packed.append({
                "uid": timeline_item_unique_id(item),
                "name": timeline_item_name(item),
                "start": timeline_item_start(item),
                "end": timeline_item_end(item),
                "duration": max(0, timeline_item_end(item) - timeline_item_start(item)),
            })
        return packed
    return {
        "video": pack("video", max(1, get_int(video_track, 1))),
        "audio": pack("audio", max(1, get_int(audio_track, 1))),
    }


def compare_core_track_snapshots(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    changes: List[Dict[str, Any]] = []
    ok = True
    for track_type in ("video", "audio"):
        b_items = before.get(track_type) or []
        a_items = after.get(track_type) or []
        if len(b_items) != len(a_items):
            ok = False
            changes.append({"track_type": track_type, "type": "count_changed", "before": len(b_items), "after": len(a_items)})
            continue
        for i, (b, a) in enumerate(zip(b_items, a_items), start=1):
            if b.get("uid") and a.get("uid") and b.get("uid") != a.get("uid"):
                ok = False
                changes.append({"track_type": track_type, "item_index": i, "type": "uid_changed", "before": b, "after": a})
                continue
            if b.get("start") != a.get("start") or b.get("end") != a.get("end"):
                ok = False
                changes.append({"track_type": track_type, "item_index": i, "type": "range_changed", "before": b, "after": a})
    return {"ok": ok, "changes": changes[:20], "changes_count": len(changes)}


def ensure_video_track(timeline: Any, target_track: int) -> Dict[str, Any]:
    """Best-effort creation of enough video tracks for Text+ overlays."""
    target_track = max(1, get_int(target_track, 2))
    before = get_video_track_count(timeline)
    attempts: List[Dict[str, Any]] = []

    while before < target_track:
        try:
            method = getattr(timeline, "AddTrack", None)
            if not method:
                attempts.append({"method": "AddTrack", "ok": False, "reason": "method_missing"})
                break
            ok = method("video")
            attempts.append({"method": "AddTrack('video')", "ok": bool(ok), "before_count": before})
        except Exception as exc:
            attempts.append({"method": "AddTrack('video')", "ok": False, "error": compact_exception(exc)})
            break
        after = get_video_track_count(timeline)
        if after <= before:
            break
        before = after

    return {
        "target_track": target_track,
        "track_count_after": get_video_track_count(timeline),
        "attempts": attempts,
        "ok": get_video_track_count(timeline) >= target_track,
    }



def get_track_name_best_effort(timeline: Any, track_type: str, track_index: int) -> str:
    return str(safe_call(timeline, "GetTrackName", track_type, track_index, default="") or "")


def count_generated_caption_items_on_track(timeline: Any, track_index: int) -> int:
    return sum(
        1
        for item in get_track_items(timeline, "video", max(1, get_int(track_index, 1)))
        if timeline_item_name(item).startswith(VC_CAPTION_TEXTPLUS_PREFIX)
    )


def resolve_or_create_named_video_track(
    timeline: Any,
    requested_index: int,
    desired_name: str = "VC_TEXTPLUS_V3",
    generated_prefix: str = VC_CAPTION_TEXTPLUS_PREFIX,
) -> Dict[str, Any]:
    """Resolve a dedicated generated-caption track by identity, not brittle index alone.

    Priority:
      1. Exact track-name match.
      2. Track containing the most VC_TEXTPLUS_* items.
      3. Requested numeric track when it is empty/title-only.
      4. A newly added video track when the requested index is occupied by media/V4.
    """
    requested_index = max(1, get_int(requested_index, 3))
    desired_name = str(desired_name or "VC_TEXTPLUS_V3").strip() or "VC_TEXTPLUS_V3"
    before_count = get_video_track_count(timeline)
    tracks: List[Dict[str, Any]] = []
    for idx in range(1, before_count + 1):
        items = get_track_items(timeline, "video", idx)
        name = get_track_name_best_effort(timeline, "video", idx)
        prefix_count = sum(1 for item in items if timeline_item_name(item).startswith(generated_prefix))
        media_count = sum(1 for item in items if timeline_item_has_media_pool_item(item))
        title_like_count = sum(1 for item in items if timeline_item_is_title_like(item))
        tracks.append({
            "index": idx,
            "name": name,
            "item_count": len(items),
            "generated_prefix_count": prefix_count,
            "media_item_count": media_count,
            "title_like_count": title_like_count,
        })

    selected: Optional[int] = None
    selected_by: Optional[str] = None
    exact = [row for row in tracks if str(row.get("name") or "").casefold() == desired_name.casefold()]
    if exact:
        exact.sort(key=lambda row: (get_int(row.get("generated_prefix_count"), 0), get_int(row.get("item_count"), 0)), reverse=True)
        selected = get_int(exact[0].get("index"), requested_index)
        selected_by = "exact_track_name"

    if selected is None:
        with_generated = [row for row in tracks if get_int(row.get("generated_prefix_count"), 0) > 0]
        if with_generated:
            with_generated.sort(key=lambda row: (get_int(row.get("generated_prefix_count"), 0), get_int(row.get("title_like_count"), 0)), reverse=True)
            selected = get_int(with_generated[0].get("index"), requested_index)
            selected_by = "generated_item_prefix_density"

    requested_row = next((row for row in tracks if get_int(row.get("index"), 0) == requested_index), None)
    if selected is None and requested_row is not None:
        # Never rename a media-backed V4/V1 track into the caption track.
        if get_int(requested_row.get("media_item_count"), 0) == 0:
            selected = requested_index
            selected_by = "requested_empty_or_title_only_track"

    create_result: Dict[str, Any] = {"attempted": False}
    if selected is None:
        selected = max(before_count + 1, requested_index)
        create_result = ensure_video_track(timeline, selected)
        selected_by = "new_dedicated_track"
    else:
        create_result = ensure_video_track(timeline, selected)

    name_result = set_track_name_best_effort(timeline, "video", selected, desired_name)
    after_count = get_video_track_count(timeline)
    resolved_name = get_track_name_best_effort(timeline, "video", selected)
    result = {
        "ok": bool(after_count >= selected),
        "requested_index": requested_index,
        "desired_name": desired_name,
        "track_index": selected,
        "track_name": resolved_name,
        "selected_by": selected_by,
        "track_count_before": before_count,
        "track_count_after": after_count,
        "tracks_before": tracks,
        "create": create_result,
        "set_name": name_result,
    }
    hard_debug("CAPTION_TEXTPLUS_TRACK_RESOLVED", result)
    return result


def verify_caption_textplus_track_coverage(
    timeline: Any,
    track_index: int,
    generic: Dict[str, Any],
    fps: float,
    tolerance_frames: int = 2,
) -> Dict[str, Any]:
    """Verify one generated title-like item per generic cue by name or exact timing."""
    track_index = max(1, get_int(track_index, 3))
    tolerance_frames = max(0, get_int(tolerance_frames, 2))
    expected = expected_caption_cues_from_generic(generic, fps)
    items = get_track_items(timeline, "video", track_index)
    candidates: List[Dict[str, Any]] = []
    for item_index, item in enumerate(items, start=1):
        name = timeline_item_name(item)
        generated_by_name = name.startswith(VC_CAPTION_TEXTPLUS_PREFIX)
        media_backed = timeline_item_has_media_pool_item(item)
        # Native Fusion titles are non-media title items. The deterministic
        # recovery fallback introduced in v0.8.5 uses a short video-only carrier
        # clip whose Fusion output is replaced by TextPlus. Accept that carrier
        # only when it has the explicit VC_TEXTPLUS_ generated name.
        if media_backed and not generated_by_name:
            continue
        if not (generated_by_name or timeline_item_is_title_like(item)):
            continue
        candidates.append({
            "item": item,
            "item_index": item_index,
            "name": name,
            "start": timeline_item_start(item),
            "end": timeline_item_end(item),
            "duration": max(0, get_int(safe_call(item, "GetDuration", default=None), timeline_item_end(item) - timeline_item_start(item))),
        })

    used: set = set()
    matches: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    for cue in expected:
        cue_index = get_int(cue.get("index"), len(matches) + 1)
        cue_id = cue.get("id") or f"sub_{cue_index:04d}"
        wanted_name = generated_caption_item_name(cue_index, cue_id)
        start = get_int(cue.get("start_frame"), 0)
        end = get_int(cue.get("end_frame"), start + 1)
        duration = max(1, end - start)

        matched_idx: Optional[int] = None
        matched_by: Optional[str] = None
        for idx, row in enumerate(candidates):
            if idx in used:
                continue
            name = str(row.get("name") or "")
            if name.startswith(wanted_name) or (name.startswith(VC_CAPTION_TEXTPLUS_PREFIX) and str(cue_id) in name):
                matched_idx = idx
                matched_by = "name"
                break
        if matched_idx is None:
            for idx, row in enumerate(candidates):
                if idx in used:
                    continue
                row_start = get_int(row.get("start"), 0)
                row_end = get_int(row.get("end"), 0)
                row_duration = get_int(row.get("duration"), max(0, row_end - row_start))
                if (
                    abs(row_start - start) <= tolerance_frames
                    and abs(row_duration - duration) <= tolerance_frames
                    and (abs(row_end - end) <= tolerance_frames or abs((row_end + 1) - end) <= tolerance_frames)
                ):
                    matched_idx = idx
                    matched_by = "timing"
                    break
        if matched_idx is None:
            missing.append({"cue_id": cue_id, "index": cue_index, "text": cue.get("text"), "start": start, "end": end})
            continue
        used.add(matched_idx)
        row = candidates[matched_idx]
        matches.append({
            "cue_id": cue_id,
            "index": cue_index,
            "text": cue.get("text"),
            "matched_by": matched_by,
            "item_index": row.get("item_index"),
            "item_name": row.get("name"),
            "start": row.get("start"),
            "end": row.get("end"),
            "duration": row.get("duration"),
        })

    extras = [
        {k: json_safe_value(v) for k, v in row.items() if k != "item"}
        for idx, row in enumerate(candidates)
        if idx not in used
    ]
    expected_count = len(expected)
    matched_count = len(matches)
    candidate_count = len(candidates)
    coverage_ok = bool(expected_count > 0 and matched_count == expected_count and candidate_count == expected_count)
    return {
        "track_index": track_index,
        "track_name": get_track_name_best_effort(timeline, "video", track_index),
        "expected_count": expected_count,
        "timeline_item_count": len(items),
        "candidate_title_count": candidate_count,
        "generated_prefix_count": sum(1 for row in candidates if str(row.get("name") or "").startswith(VC_CAPTION_TEXTPLUS_PREFIX)),
        "matched_count": matched_count,
        "missing_count": len(missing),
        "extra_candidate_count": len(extras),
        "coverage_ok": coverage_ok,
        "matches_sample": matches[:12],
        "missing_sample": missing[:12],
        "extras_sample": extras[:12],
        "tolerance_frames": tolerance_frames,
    }


def clear_caption_textplus_target_track(
    timeline: Any,
    track_index: int,
    dedicated_track: bool = True,
) -> Dict[str, Any]:
    """Clear generated/title-like items only from the resolved V3 track.

    On an explicitly dedicated VC_TEXTPLUS_V3 track it is safe to remove all
    non-media title-like items, including stale unnamed duplicates from failed runs.
    """
    track_index = max(1, get_int(track_index, 3))
    items = get_track_items(timeline, "video", track_index)
    selected: List[Any] = []
    selected_rows: List[Dict[str, Any]] = []
    for item in items:
        name = timeline_item_name(item)
        media_backed = timeline_item_has_media_pool_item(item)
        generated = name.startswith(VC_CAPTION_TEXTPLUS_PREFIX)
        title_like = timeline_item_is_title_like(item)
        if generated or (dedicated_track and title_like and not media_backed):
            selected.append(item)
            selected_rows.append({
                "name": name,
                "start": timeline_item_start(item),
                "end": timeline_item_end(item),
                "generated_prefix": generated,
                "title_like": title_like,
            })
    deletion = delete_timeline_items(timeline, selected)
    return {
        "attempted": True,
        "track_index": track_index,
        "dedicated_track": dedicated_track,
        "selected_count": len(selected),
        "selected_sample": selected_rows[:20],
        "delete": deletion,
        "remaining_count": len(get_track_items(timeline, "video", track_index)),
        "ok": bool(get_int(deletion.get("deleted_count"), get_int(deletion.get("deleted"), 0)) == len(selected)),
    }


def bootstrap_empty_caption_textplus_track(
    timeline: Any,
    target_track: int,
    start_frame: int,
    fps: float,
    title_name: str = "Text+",
) -> Tuple[Optional[Any], Dict[str, Any]]:
    """Bootstrap a completely empty Text+ track with one temporary seed."""
    result: Dict[str, Any] = {
        "attempted": True,
        "target_track": target_track,
        "start_frame": start_frame,
        "track_count_before": len(get_track_items(timeline, "video", target_track)),
        "context": None,
        "methods": [],
        "created": False,
        "detected_by": None,
        "item": None,
    }
    if result["track_count_before"] > 0:
        result["attempted"] = False
        result["reason"] = "target_track_not_empty"
        return None, result

    result["context"] = stabilize_caption_insertion_context(timeline, target_track, start_frame, fps)
    result["clear_mark_in_out"] = clear_timeline_mark_in_out(timeline)
    result["set_time"] = set_timeline_current_frame(timeline, start_frame, fps)

    candidates = [
        ("InsertFusionCompositionIntoTimeline", []),
        ("InsertFusionTitleIntoTimeline", [title_name]),
        ("InsertFusionTitleIntoTimeline", ["Text+"]),
        ("InsertFusionTitleIntoTimeline", ["Text Plus"]),
        ("InsertTitleIntoTimeline", ["Text+"]),
        ("InsertTitleIntoTimeline", ["Text"]),
    ]
    seen = set()
    for method_name, method_args in candidates:
        key = (method_name, tuple(str(v) for v in method_args))
        if key in seen:
            continue
        seen.add(key)
        before_items, _ = snapshot_video_items_for_probe(timeline, include_item_details=False)
        row: Dict[str, Any] = {
            "method": method_name,
            "args": json_safe_value(method_args),
            "available": method_available(timeline, method_name),
            "returned_truthy": False,
            "created_item_detected": False,
        }
        if not row["available"]:
            row["reason"] = "method_missing"
            result["methods"].append(row)
            continue
        returned = None
        try:
            returned = getattr(timeline, method_name)(*method_args)
            row["returned_truthy"] = bool(returned)
            row["returned_type"] = type(returned).__name__ if returned is not None else None
        except Exception as exc:
            row["error"] = compact_exception(exc)
        try:
            time.sleep(0.25)
        except Exception:
            pass
        after_items, _ = snapshot_video_items_for_probe(timeline, include_item_details=False)
        new_items = new_items_between_probe_snapshots(before_items, after_items)
        detected = returned if is_timeline_item_object(returned) else None
        if detected is None:
            target_new = [item for item in new_items if get_int(timeline_item_track_info(item).get("track_index"), 0) == target_track]
            if target_new:
                detected = target_new[-1]
                row["detected_by"] = "new_item_on_target_track"
            elif new_items:
                detected = new_items[-1]
                row["detected_by"] = "new_item_on_other_video_track"
        else:
            row["detected_by"] = "returned_object"
        row["new_item_count"] = len(new_items)
        if detected is not None:
            row["created_item_detected"] = True
            row["detected_track"] = timeline_item_track_info(detected)
            row["detected_item"] = timeline_item_summary(detected)
            result["created"] = True
            result["detected_by"] = row.get("detected_by")
            result["item"] = timeline_item_summary(detected)
            result["methods"].append(row)
            hard_debug("CAPTION_TEXTPLUS_EMPTY_TRACK_SEED_CREATED", result)
            return detected, result
        result["methods"].append(row)
    hard_debug("CAPTION_TEXTPLUS_EMPTY_TRACK_SEED_FAILED", result)
    return None, result


def stabilize_caption_insertion_context(timeline: Any, target_track: int, start_frame: int, fps: float) -> Dict[str, Any]:
    """Reassert the Edit-page insertion context before a single safe retry."""
    attempts: List[Dict[str, Any]] = []
    ensure = ensure_video_track(timeline, target_track)
    for idx in range(1, get_video_track_count(timeline) + 1):
        attempts.append(set_track_lock_state(timeline, "video", idx, idx != target_track))
    for idx in range(1, get_audio_track_count(timeline) + 1):
        attempts.append(set_track_lock_state(timeline, "audio", idx, True))
    clear_marks = clear_timeline_mark_in_out(timeline)
    set_time = set_timeline_current_frame(timeline, start_frame, fps)
    try:
        time.sleep(0.20)
    except Exception:
        pass
    result = {
        "target_track": target_track,
        "ensure_track": ensure,
        "lock_attempts": attempts,
        "clear_mark_in_out": clear_marks,
        "set_time": set_time,
    }
    hard_debug("CAPTION_TEXTPLUS_INSERTION_CONTEXT_STABILIZED", result)
    return result


def get_all_video_items_by_track(timeline: Any) -> Dict[int, List[Any]]:
    count = get_video_track_count(timeline)
    return {idx: get_track_items(timeline, "video", idx) for idx in range(1, count + 1)}


def timeline_item_start(item: Any) -> int:
    return get_int(safe_call(item, "GetStart", default=0), 0)


def timeline_item_end(item: Any) -> int:
    return get_int(safe_call(item, "GetEnd", default=0), 0)


def timeline_item_name(item: Any) -> str:
    return str(safe_call(item, "GetName", default="") or "")


def find_items_by_name_prefix(timeline: Any, prefix: str) -> List[Any]:
    matches: List[Any] = []
    for _, items in get_all_video_items_by_track(timeline).items():
        for item in items:
            if timeline_item_name(item).startswith(prefix):
                matches.append(item)
    return matches


def delete_timeline_items(timeline: Any, items: List[Any]) -> Dict[str, Any]:
    if not items:
        return {"attempted": False, "requested_count": 0, "deleted": 0, "attempts": []}

    attempts: List[Dict[str, Any]] = []
    deleted = 0

    try:
        method = getattr(timeline, "DeleteClips", None)
        if method:
            # Resolve usually accepts DeleteClips([timeline_items], ripple=False).
            ok = method(items, False)
            attempts.append({"method": "timeline.DeleteClips(items, False)", "ok": bool(ok), "count": len(items)})
            if ok:
                return {"attempted": True, "requested_count": len(items), "deleted": len(items), "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "timeline.DeleteClips(items, False)", "ok": False, "error": compact_exception(exc)})

    for item in items:
        name = timeline_item_name(item)
        try:
            method = getattr(item, "Delete", None)
            if method:
                ok = method()
                success = True if ok is None else bool(ok)
                attempts.append({"method": "item.Delete()", "ok": success, "name": name})
                if success:
                    deleted += 1
                    continue
        except Exception as exc:
            attempts.append({"method": "item.Delete()", "ok": False, "name": name, "error": compact_exception(exc)})

    return {"attempted": True, "requested_count": len(items), "deleted": deleted, "attempts": attempts}


def set_timeline_item_name(item: Any, name: str) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for method_name in ("SetName", "SetClipName"):
        try:
            method = getattr(item, method_name, None)
            if method:
                ok = method(name)
                attempts.append({"method": method_name, "ok": bool(ok), "name": name})
                if ok:
                    return {"ok": True, "name": name, "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": method_name, "ok": False, "error": compact_exception(exc)})

    try:
        ok, readback = safe_set_property(item, "Name", name)
        attempts.append({"method": "SetProperty('Name')", "ok": ok, "readback": readback})
        if ok:
            return {"ok": True, "name": name, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "SetProperty('Name')", "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "name": name, "attempts": attempts}


def set_timeline_item_range(item: Any, start_frame: int, end_frame: int) -> Dict[str, Any]:
    """
    Best-effort verification/trim for inserted Text+ items.

    Resolve's documented TimelineItem API exposes GetStart/GetEnd but not a public
    SetStart/SetEnd. Some runtimes still expose hidden setters/properties, so we
    try them, but the primary duration control in v0.5.1 happens before insertion
    via timeline SetMarkInOut().
    """
    attempts: List[Dict[str, Any]] = []
    start_frame = get_int(start_frame, 0)
    end_frame = max(start_frame + 1, get_int(end_frame, start_frame + 1))
    duration = max(1, end_frame - start_frame)

    hidden_methods = (
        ("SetStart", (start_frame,)),
        ("SetEnd", (end_frame,)),
        ("SetDuration", (duration,)),
        ("SetLeftOffset", (0,)),
        ("SetRightOffset", (0,)),
    )
    for method_name, method_args in hidden_methods:
        try:
            method = getattr(item, method_name, None)
            if method:
                ok = method(*method_args)
                attempts.append({"method": method_name, "args": method_args, "ok": bool(ok)})
            else:
                attempts.append({"method": method_name, "args": method_args, "ok": False, "reason": "method_missing"})
        except Exception as exc:
            attempts.append({"method": method_name, "args": method_args, "ok": False, "error": compact_exception(exc)})

    for prop_name, value in (
        ("Start", start_frame),
        ("End", end_frame),
        ("Duration", duration),
        ("Record Start", start_frame),
        ("Record End", end_frame),
    ):
        ok, readback = safe_set_property(item, prop_name, value)
        attempts.append({"method": "SetProperty", "property": prop_name, "value": value, "ok": ok, "readback": readback})

    actual_start = timeline_item_start(item)
    actual_end = timeline_item_end(item)
    actual_duration = max(0, actual_end - actual_start)
    start_ok = abs(actual_start - start_frame) <= 1
    duration_ok = abs(actual_duration - duration) <= 2
    ok = bool(start_ok and duration_ok)

    return {
        "ok": ok,
        "start_ok": start_ok,
        "duration_ok": duration_ok,
        "requested": {"start": start_frame, "end": end_frame, "duration": duration},
        "actual": {"start": actual_start, "end": actual_end, "duration": actual_duration},
        "track": timeline_item_track_info(item),
        "attempts": attempts,
    }


def insert_textplus_timeline_item(
    timeline: Any,
    absolute_start_frame: int,
    absolute_end_frame: int,
    fps: float,
    title_name: str,
    target_track: int = 2,
    use_mark_in_out: bool = True,
    mark_start_frame: Optional[int] = None,
    mark_end_frame: Optional[int] = None,
) -> Dict[str, Any]:
    """Insert a Resolve Text+/Fusion title at the current playhead.

    v0.5.1 sets timeline in/out marks before insertion. The Resolve scripting docs
    only expose InsertFusionTitleIntoTimeline(titleName), but SetMarkInOut is the
    only documented way to constrain the insertion range without editing the item
    afterward.
    """
    attempts: List[Dict[str, Any]] = []
    absolute_start_frame = max(0, get_int(absolute_start_frame, 0))
    absolute_end_frame = max(absolute_start_frame + 1, get_int(absolute_end_frame, absolute_start_frame + 1))

    set_time = set_timeline_current_frame(timeline, absolute_start_frame, fps)
    mark_result = {"attempted": False, "reason": "use_mark_in_out disabled"}
    if use_mark_in_out:
        # SetMarkInOut appears to use timeline-relative frames in Resolve docs
        # (e.g. {'video': {'in': 0, 'out': 134}}), while SetCurrentTimecode
        # uses absolute timeline timecode. So we prefer relative subtitle frames
        # for marks, while still placing the playhead via absolute timecode.
        mark_in = get_int(mark_start_frame, absolute_start_frame)
        mark_out = get_int(mark_end_frame, absolute_end_frame - 1)
        mark_result = set_timeline_mark_in_out(timeline, mark_in, mark_out, "video")
        mark_result["absolute_candidate"] = {"mark_in": absolute_start_frame, "mark_out": absolute_end_frame - 1}

    insert_methods = [
        ("InsertFusionTitleIntoTimeline", [title_name]),
        ("InsertTitleIntoTimeline", [title_name]),
        ("InsertGeneratorIntoTimeline", [title_name]),
        ("InsertFusionTitleIntoTimeline", ["Text+"]),
        ("InsertTitleIntoTimeline", ["Text+"]),
        ("InsertGeneratorIntoTimeline", ["Text+"]),
        ("InsertFusionTitleIntoTimeline", ["Text Plus"]),
        ("InsertTitleIntoTimeline", ["Text"]),
    ]

    base_payload = {
        "set_time": set_time,
        "mark_in_out": mark_result,
        "target_track": target_track,
    }

    for method_name, method_args in insert_methods:
        try:
            method = getattr(timeline, method_name, None)
            if not method:
                attempts.append({"method": method_name, "args": method_args, "ok": False, "reason": "method_missing"})
                continue
            item = method(*method_args)
            ok = bool(item)
            track_info = timeline_item_track_info(item) if item else None
            attempts.append({
                "method": method_name,
                "args": method_args,
                "ok": ok,
                "result_type": type(item).__name__ if item else None,
                "track": track_info,
            })
            if item:
                clear_result = clear_timeline_mark_in_out(timeline)
                return {
                    "ok": True,
                    "item": item,
                    **base_payload,
                    "clear_mark_in_out": clear_result,
                    "actual_track": track_info,
                    "attempts": attempts,
                    "insert_method": method_name,
                    "insert_args": method_args,
                }
        except Exception as exc:
            attempts.append({"method": method_name, "args": method_args, "ok": False, "error": compact_exception(exc)})

    clear_result = clear_timeline_mark_in_out(timeline)
    return {"ok": False, "item": None, **base_payload, "clear_mark_in_out": clear_result, "attempts": attempts}


def set_fusion_input_best_effort(tool: Any, input_name: str, value: Any) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []

    try:
        method = getattr(tool, "SetInput", None)
        if method:
            ok = method(input_name, value)
            attempts.append({"method": "SetInput", "input": input_name, "value": value, "ok": bool(ok)})
            if ok:
                return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "SetInput", "input": input_name, "ok": False, "error": compact_exception(exc)})

    try:
        setattr(tool, input_name, value)
        attempts.append({"method": "setattr", "input": input_name, "value": value, "ok": True})
        return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "setattr", "input": input_name, "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "attempts": attempts}


def find_textplus_tools(comp: Any) -> List[Any]:
    matches: List[Any] = []
    for tool in list_fusion_tools(comp):
        regid = fusion_tool_regid(tool).lower()
        name = fusion_tool_name(tool).lower()
        if "textplus" in regid or "textplus" in name or "text" in regid or name.startswith("text"):
            matches.append(tool)
    return matches


def configure_textplus_tool(item: Any, subtitle: Dict[str, Any], style: Dict[str, Any], subtitle_index: int) -> Dict[str, Any]:
    text_raw = str(subtitle.get("text") or "").strip()
    text = apply_case_style(text_raw, style.get("case_style", "preserve"))
    result: Dict[str, Any] = {
        "attempted": True,
        "text": text,
        "style_source": style.get("source"),
        "fusion_comp": {},
        "tool": None,
        "inputs": {},
        "applied": False,
    }

    comp, comp_info = get_or_create_fusion_comp(item)
    result["fusion_comp"] = comp_info
    if not comp:
        result["error"] = "No Fusion comp available on inserted subtitle item."
        return result

    try:
        safe_call(comp, "Lock", default=None)
        tools = find_textplus_tools(comp)
        text_tool = tools[0] if tools else None
        if not text_tool:
            result["error"] = "No TextPlus/Text tool found in inserted title item."
            result["available_tools"] = [fusion_tool_name(t) for t in list_fusion_tools(comp)]
            return result

        set_name = set_fusion_tool_name(text_tool, f"{VC_SUBTITLE_TEXT_TOOL_PREFIX}{subtitle_index:04d}")
        result["tool"] = {
            "name_before": fusion_tool_name(text_tool),
            "name_set": set_name,
            "regid": fusion_tool_regid(text_tool),
        }

        r, g, b = parse_hex_color(style.get("text_color"), fallback=(1.0, 1.0, 1.0))
        sr, sg, sb = parse_hex_color(style.get("stroke_color"), fallback=(0.0, 0.0, 0.0))
        center = fusion_center_for_placement(str(subtitle.get("placement") or style.get("placement") or "bottom_center"))
        size = style.get("textplus_size", 0.062)

        # Text+ input names vary between template/title variants. Try common ones.
        input_plan = {
            "StyledText": text,
            "Size": size,
            "Center": center,
            "Red1": r,
            "Green1": g,
            "Blue1": b,
            "Alpha1": 1.0,
            "Red": r,
            "Green": g,
            "Blue": b,
            "Font": style.get("font_family") or "Arial",
        }

        # Best-effort outline/stroke. Some Text+ templates ignore these names.
        stroke_width = clamp_float(style.get("stroke_width"), 0.0, 12.0, 2.0)
        input_plan.update({
            "Enabled2": 1 if stroke_width > 0 else 0,
            "Red2": sr,
            "Green2": sg,
            "Blue2": sb,
            "Alpha2": 1.0 if stroke_width > 0 else 0.0,
            "LineWidth": stroke_width,
            "Thickness": stroke_width,
        })

        ok_count = 0
        required_ok = False
        for input_name, value in input_plan.items():
            set_result = set_fusion_input_best_effort(text_tool, input_name, value)
            result["inputs"][input_name] = set_result
            if set_result.get("ok"):
                ok_count += 1
                if input_name == "StyledText":
                    required_ok = True

        result["applied"] = bool(required_ok)
        result["ok_input_count"] = ok_count
        return result

    except Exception as exc:
        result["error"] = compact_exception(exc)
        result["traceback"] = traceback.format_exc()
        return result
    finally:
        try:
            safe_call(comp, "Unlock", default=None)
        except Exception:
            pass


def apply_one_subtitle_clip(
    timeline: Any,
    subtitle: Dict[str, Any],
    style: Dict[str, Any],
    subtitle_index: int,
    timeline_start_offset_frames: int,
    fps: float,
    title_name: str,
    min_duration_frames: int,
    target_track: int = 2,
    use_mark_in_out: bool = True,
    strict_timing: bool = True,
) -> Dict[str, Any]:
    text = str(subtitle.get("text") or "").strip()
    rel_start = get_int(subtitle.get("timeline_start_frame"), 0)
    rel_end = get_int(subtitle.get("timeline_end_frame"), rel_start + min_duration_frames)
    duration = max(get_int(min_duration_frames, 2), rel_end - rel_start)
    abs_start = timeline_start_offset_frames + rel_start
    abs_end = abs_start + duration
    subtitle_id = subtitle.get("subtitle_id") or f"sub_{subtitle_index:04d}"
    item_name = f"{VC_SUBTITLE_PREFIX}{subtitle_index:04d}_{subtitle_id}"

    result: Dict[str, Any] = {
        "attempted": True,
        "subtitle_index": subtitle_index,
        "subtitle_id": subtitle_id,
        "text": text,
        "requested": {
            "relative_start_frame": rel_start,
            "relative_end_frame": rel_end,
            "absolute_start_frame": abs_start,
            "absolute_end_frame": abs_end,
            "duration_frames": duration,
            "timecode": frame_to_timecode(abs_start, fps),
        },
        "insert": None,
        "name": None,
        "range": None,
        "style": None,
        "applied": False,
    }

    if not text:
        result["reason"] = "empty subtitle text"
        return result

    insert_result = insert_textplus_timeline_item(
        timeline=timeline,
        absolute_start_frame=abs_start,
        absolute_end_frame=abs_end,
        fps=fps,
        title_name=title_name,
        target_track=target_track,
        use_mark_in_out=use_mark_in_out,
        mark_start_frame=rel_start,
        mark_end_frame=max(rel_start, rel_end - 1),
    )
    # PyRemoteObject is not JSON serializable. Keep a report-safe copy and local item.
    item = insert_result.pop("item", None)
    result["insert"] = insert_result
    if not item:
        result["error"] = "Could not insert Text+/title item into timeline."
        return result

    result["name"] = set_timeline_item_name(item, item_name)
    result["track"] = timeline_item_track_info(item)
    result["range"] = set_timeline_item_range(item, abs_start, abs_end)

    track_ok = (result.get("track") or {}).get("track_type") == "video" and get_int((result.get("track") or {}).get("track_index"), 0) == get_int(target_track, 2)
    range_ok = bool((result.get("range") or {}).get("ok"))

    if strict_timing and (not range_ok or not track_ok):
        # Protect the timeline: if Resolve ignored the in/out range or inserted on
        # the wrong track, remove the just-created long title instead of leaving a
        # 120-frame clip that can push/cover the real edit.
        result["rollback_delete"] = delete_timeline_items(timeline, [item])
        result["timeline_item_after"] = timeline_item_summary(item)
        result["applied"] = False
        result["reason"] = "strict_timing_or_track_guard_failed"
        result["track_ok"] = bool(track_ok)
        result["range_ok"] = bool(range_ok)
        return result

    result["style"] = configure_textplus_tool(item, subtitle, style, subtitle_index)
    result["timeline_item_after"] = timeline_item_summary(item)
    result["track_after"] = timeline_item_track_info(item)
    result["track_ok"] = bool(track_ok)
    result["range_ok"] = bool(range_ok)
    result["applied"] = bool(result.get("style", {}).get("applied") and (range_ok or not strict_timing) and (track_ok or not strict_timing))
    return result


def apply_subtitles_to_timeline(timeline: Any, generic: Dict[str, Any], video_items: List[Any], args: argparse.Namespace, fps: float) -> Dict[str, Any]:
    subtitle_clips = generic.get("subtitle_clips") or []
    if not isinstance(subtitle_clips, list):
        subtitle_clips = []

    result: Dict[str, Any] = {
        "attempted": True,
        "operation": "resolve_textplus_subtitles",
        "subtitle_clips_count": len(subtitle_clips),
        "subtitle_track": getattr(args, "subtitle_track", 2),
        "timeline_start_offset_frames": None,
        "style": None,
        "track_setup": None,
        "clear_old": None,
        "items": [],
        "applied": False,
        "created_count": 0,
        "failed_count": 0,
        "warnings": [],
        "limitation": "Uses Resolve title/Text+ insertion APIs with track locks and timeline in/out marks. If Resolve ignores timing/track targeting, strict mode deletes the bad title to protect the timeline.",
    }

    if not subtitle_clips:
        result["reason"] = "generic_edit_commands.subtitle_clips is empty"
        return result

    if not video_items:
        result["reason"] = "no existing video items; cannot infer timeline start offset"
        return result

    timeline_start_offset = min(timeline_item_start(item) for item in video_items)
    result["timeline_start_offset_frames"] = timeline_start_offset

    subtitle_track = max(1, get_int(getattr(args, "subtitle_track", 2), 2))
    result["track_setup"] = ensure_video_track(timeline, subtitle_track)

    result["core_tracks_before"] = snapshot_core_tracks(
        timeline=timeline,
        video_track=get_int(getattr(args, "video_track", 1), 1),
        audio_track=get_int(getattr(args, "audio_track", 1), 1),
    )

    track_guard = {"attempted": False, "reason": "subtitle track guard disabled"}
    if getattr(args, "subtitle_track_guard", True):
        track_guard = apply_subtitle_track_guard(timeline, subtitle_track)
    result["track_guard"] = track_guard

    try:
        if getattr(args, "clear_old_vc_subtitles", False):
            # Prefer cleaning the dedicated subtitle overlay track. This catches old
            # Text+ items even when Resolve refuses to rename them from "Text+".
            old_items = find_subtitle_track_title_items(
                timeline=timeline,
                subtitle_track=subtitle_track,
                include_title_like=getattr(args, "clear_old_subtitle_track_titles", True),
            )
            # Also include any successfully named VC_Sub_* items on other tracks.
            for item in find_items_by_name_prefix(timeline, VC_SUBTITLE_PREFIX):
                if item not in old_items:
                    old_items.append(item)
            result["clear_old"] = delete_timeline_items(timeline, old_items)
        else:
            result["clear_old"] = {"attempted": False, "reason": "--clear-old-vc-subtitles not used"}

        style = normalize_caption_style(generic)
        result["style"] = style

        max_subtitles = get_int(getattr(args, "max_subtitles", 0), 0)
        clips_to_apply = subtitle_clips[:max_subtitles] if max_subtitles > 0 else subtitle_clips
        result["requested_create_count"] = len(clips_to_apply)

        stop_on_fail = bool(getattr(args, "subtitle_stop_on_range_fail", True))
        strict_timing = bool(getattr(args, "subtitle_strict_timing", True))
        use_mark_in_out = bool(getattr(args, "subtitle_use_mark_in_out", True))

        for subtitle_index, subtitle in enumerate(clips_to_apply, start=1):
            if not isinstance(subtitle, dict):
                continue
            item_result = apply_one_subtitle_clip(
                timeline=timeline,
                subtitle=subtitle,
                style=style,
                subtitle_index=subtitle_index,
                timeline_start_offset_frames=timeline_start_offset,
                fps=fps,
                title_name=getattr(args, "subtitle_title_name", "Text+"),
                min_duration_frames=max(1, get_int(getattr(args, "subtitle_min_duration_frames", 2), 2)),
                target_track=subtitle_track,
                use_mark_in_out=use_mark_in_out,
                strict_timing=strict_timing,
            )
            result["items"].append(item_result)
            if item_result.get("applied"):
                result["created_count"] += 1
            else:
                result["failed_count"] += 1
                if stop_on_fail and item_result.get("reason") == "strict_timing_or_track_guard_failed":
                    result["warnings"].append(
                        "Stopped subtitle creation because Resolve ignored exact timing or track targeting. "
                        "The failed title was deleted to protect the timeline."
                    )
                    break

            # Keep Resolve responsive for huge word-by-word batches.
            if subtitle_index % 25 == 0:
                hard_debug("SUBTITLE_BATCH_PROGRESS", {"created": result["created_count"], "attempted": subtitle_index})

    finally:
        if getattr(args, "subtitle_track_guard", True):
            result["track_guard_restore"] = restore_track_locks(timeline, track_guard)
        result["core_tracks_after"] = snapshot_core_tracks(
            timeline=timeline,
            video_track=get_int(getattr(args, "video_track", 1), 1),
            audio_track=get_int(getattr(args, "audio_track", 1), 1),
        )
        result["core_track_integrity"] = compare_core_track_snapshots(result.get("core_tracks_before") or {}, result.get("core_tracks_after") or {})
        if not result["core_track_integrity"].get("ok"):
            result["warnings"].append("Core video/audio track ranges changed during subtitle insertion. Inspect core_track_integrity immediately.")

    result["applied"] = result["created_count"] > 0
    return result


# -----------------------------
# Caption Text+ provisioning / animation helpers
# -----------------------------

CAPTION_TEXTPLUS_TIMELINE_METHOD_PROBES = (
    "InsertFusionCompositionIntoTimeline",
    "InsertFusionTitleIntoTimeline",
    "InsertTitleIntoTimeline",
    "InsertGeneratorIntoTimeline",
    "SetCurrentTimecode",
    "SetMarkInOut",
    "ClearMarkInOut",
    "AddTrack",
    "DeleteClips",
)

CAPTION_TEXTPLUS_WRITE_INPUTS = (
    "StyledText",
    "InputStyledText",
    "Size",
    "Center",
    "Blend",
    "Opacity",
    "Red1",
    "Green1",
    "Blue1",
    "Alpha1",
    "Enabled2",
    "Red2",
    "Green2",
    "Blue2",
    "Alpha2",
    "LineWidth",
    "Thickness",
    "Font",
)


def caption_style_candidates_from_generic(args: argparse.Namespace, generic: Dict[str, Any]) -> List[Path]:
    candidates: List[Path] = []
    explicit = getattr(args, "caption_style", None)
    if explicit:
        candidates.append(Path(str(explicit)))
    env_path = os.environ.get("VC_CAPTION_STYLE")
    if env_path:
        candidates.append(Path(env_path))

    video_id = str(generic.get("video_id") or "").strip()
    generic_path = getattr(args, "generic", None)
    if generic_path:
        try:
            gp = Path(str(generic_path))
            if video_id:
                candidates.append(gp.parent / f"{video_id}_caption_style.json")
                candidates.append(gp.parent.parent / "analysis" / f"{video_id}_caption_style.json")
                candidates.append(gp.parent.parent / "davinci" / f"{video_id}_caption_style.json")
            candidates.extend(gp.parent.glob("*_caption_style.json"))
            candidates.extend((gp.parent.parent / "analysis").glob("*_caption_style.json"))
        except Exception:
            pass

    out: List[Path] = []
    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def load_caption_style_report(args: argparse.Namespace, generic: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "requested_path": getattr(args, "caption_style", None),
        "loaded": False,
        "path": None,
        "style_events_count": 0,
        "warnings": [],
        "errors": [],
        "data": None,
    }
    candidates = caption_style_candidates_from_generic(args, generic)
    for path in candidates:
        try:
            if not path.exists():
                continue
            data = load_json(str(path))
            events = data.get("caption_style_events") or data.get("style_events") or []
            result.update({
                "loaded": True,
                "path": str(path.resolve()),
                "style_events_count": len(events) if isinstance(events, list) else 0,
                "data": data,
            })
            return result
        except Exception as exc:
            result["errors"].append({"path": str(path), "error": compact_exception(exc)})
    if candidates:
        result["warnings"].append("No caption_style report could be loaded from candidate paths.")
    else:
        result["warnings"].append("No caption_style path candidates were available.")
    return result


def normalized_cue_id_number(value: Any) -> Optional[int]:
    text = str(value or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def caption_style_events_list(caption_style_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(caption_style_data, dict):
        return []
    events = caption_style_data.get("caption_style_events") or caption_style_data.get("style_events") or []
    if not isinstance(events, list):
        return []
    return [ev for ev in events if isinstance(ev, dict)]


def build_style_event_index(caption_style_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    events = caption_style_events_list(caption_style_data)
    by_cue_id: Dict[str, Dict[str, Any]] = {}
    by_cue_num: Dict[int, Dict[str, Any]] = {}
    for ev in events:
        cue_id = ev.get("cue_id") or ev.get("subtitle_id")
        if cue_id:
            by_cue_id[str(cue_id)] = ev
            cue_num = normalized_cue_id_number(cue_id)
            if cue_num is not None and cue_num not in by_cue_num:
                by_cue_num[cue_num] = ev
    return {"events": events, "by_cue_id": by_cue_id, "by_cue_num": by_cue_num}


def pick_style_event_for_cue(cue: Dict[str, Any], style_index: Dict[str, Any], fps: float) -> Optional[Dict[str, Any]]:
    cue_id = str(cue.get("id") or cue.get("subtitle_id") or "")
    by_cue_id = style_index.get("by_cue_id") or {}
    if cue_id and cue_id in by_cue_id:
        return by_cue_id[cue_id]

    cue_num = normalized_cue_id_number(cue_id)
    by_cue_num = style_index.get("by_cue_num") or {}
    if cue_num is not None and cue_num in by_cue_num:
        return by_cue_num[cue_num]

    events = style_index.get("events") or []
    if not events:
        return None

    cue_start = get_float(cue.get("start_seconds"), get_int(cue.get("start_frame"), 0) / fps if fps else 0.0)
    cue_end = get_float(cue.get("end_seconds"), get_int(cue.get("end_frame"), 0) / fps if fps else cue_start)
    cue_mid = (cue_start + cue_end) / 2.0
    best: Optional[Dict[str, Any]] = None
    best_score = 999999.0
    cue_text = str(cue.get("text") or "").strip().lower()

    for ev in events:
        ev_start = get_float(ev.get("start"), 0.0)
        ev_end = get_float(ev.get("end"), ev_start)
        ev_mid = (ev_start + ev_end) / 2.0
        distance = abs(ev_mid - cue_mid)
        overlap = max(0.0, min(cue_end, ev_end) - max(cue_start, ev_start))
        ev_text = str(ev.get("text") or ev.get("observed_text") or "").strip().lower()
        text_bonus = 0.0 if cue_text and cue_text in ev_text else 0.35
        score = distance - min(overlap, 0.5) + text_bonus
        if score < best_score:
            best_score = score
            best = ev

    # Keep this loose. These events are visual OCR observations, not authoritative cues.
    if best is not None and best_score <= 1.5:
        return best
    return None


def rich_style_source(caption_style_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(caption_style_data, dict):
        return {}
    for key in ("caption_style_resolved", "resolved"):
        raw = caption_style_data.get(key)
        if isinstance(raw, dict):
            return raw
    return {}



def split_fusion_font_name(font_name: Any, explicit_style: Any = None) -> Tuple[str, Optional[str]]:
    """Split an explicit combined family/face name without inventing a face.

    Resolve Text+ exposes two separate menus: font family and typeface. A detected
    visual weight such as ``bold`` is only a hint; it is not proof that the chosen
    installed family contains a Bold/SemiBold face. Therefore this helper parses a
    face only when it is explicitly present in the requested name or supplied via
    ``explicit_style``.
    """
    raw = str(font_name or "").strip()
    if not raw or raw.lower() == "unknown":
        raw = "Arial"

    normalized = " ".join(raw.split())
    requested_style = str(explicit_style or "").strip() or None
    if requested_style:
        return normalized, requested_style

    suffixes = [
        (" Extra Bold Italic", "ExtraBold Italic"),
        (" ExtraBold Italic", "ExtraBold Italic"),
        (" Semi Bold Italic", "SemiBold Italic"),
        (" SemiBold Italic", "SemiBold Italic"),
        (" Demi Bold Italic", "DemiBold Italic"),
        (" DemiBold Italic", "DemiBold Italic"),
        (" Extra Bold", "ExtraBold"),
        (" ExtraBold", "ExtraBold"),
        (" Semi Bold", "SemiBold"),
        (" SemiBold", "SemiBold"),
        (" Demi Bold", "DemiBold"),
        (" DemiBold", "DemiBold"),
        (" Ultra Bold", "UltraBold"),
        (" UltraBold", "UltraBold"),
        (" Bold Italic", "Bold Italic"),
        (" Black Italic", "Black Italic"),
        (" Heavy Italic", "Heavy Italic"),
        (" Black", "Black"),
        (" Heavy", "Heavy"),
        (" Bold", "Bold"),
        (" Medium", "Medium"),
        (" Light", "Light"),
        (" Thin", "Thin"),
        (" Italic", "Italic"),
        (" Oblique", "Oblique"),
        (" Regular", "Regular"),
    ]
    lower = normalized.lower()
    for suffix, style_name in suffixes:
        if lower.endswith(suffix.lower()) and len(normalized) > len(suffix):
            family = normalized[:-len(suffix)].strip()
            if family:
                return family, requested_style or style_name

    return normalized, requested_style


def _flatten_font_list_strings(value: Any) -> List[str]:
    """Flatten Fusion FontManager.GetFontList() tables into file/name strings."""
    output: List[str] = []
    if value is None:
        return output
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key, item in value.items():
            output.extend(_flatten_font_list_strings(key))
            output.extend(_flatten_font_list_strings(item))
        return output
    if isinstance(value, (list, tuple, set)):
        for item in value:
            output.extend(_flatten_font_list_strings(item))
        return output
    return output


def probe_fusion_font_inventory(resolve: Any, font_family: Optional[str], font_style: Optional[str]) -> Dict[str, Any]:
    """Read Fusion's global installed font-file list for probe diagnostics.

    The official Fusion scripting API exposes Fusion.FontManager.GetFontList().
    It returns font files, not a guaranteed family/face lookup table, so this
    routine positively verifies the requested family file and treats ``Regular``
    as the only safe default face. It never invents Bold/SemiBold from OCR weight.
    """
    family = str(font_family or "").strip()
    style = str(font_style or "Regular").strip() or "Regular"
    report: Dict[str, Any] = {
        "attempted": bool(family),
        "family": family or None,
        "style": style if family else None,
        "fusion_handle_source": None,
        "font_manager_available": False,
        "font_list_available": False,
        "font_file_count": 0,
        "matched_files": [],
        "family_present": None,
        "style_present": None,
        "safe_to_write": bool(family),
        "warnings": [],
        "errors": [],
    }
    if not family:
        report["warnings"].append("No explicit font family requested; font inventory was not required.")
        return report

    fusion_app = None
    for name in ("fusion", "Fusion"):
        candidate = globals().get(name)
        if candidate is not None:
            try:
                if getattr(candidate, "FontManager", None) is not None:
                    fusion_app = candidate
                    report["fusion_handle_source"] = f"injected_global:{name}"
                    break
            except Exception as exc:
                report["errors"].append(f"{name}.FontManager: {compact_exception(exc)}")

    if fusion_app is None and resolve is not None:
        for method_name in ("Fusion", "GetFusion"):
            try:
                method = getattr(resolve, method_name, None)
                if method:
                    candidate = method()
                    if candidate is not None and getattr(candidate, "FontManager", None) is not None:
                        fusion_app = candidate
                        report["fusion_handle_source"] = f"resolve.{method_name}()"
                        break
            except Exception as exc:
                report["errors"].append(f"resolve.{method_name}: {compact_exception(exc)}")

    if fusion_app is None:
        report["warnings"].append(
            "Fusion FontManager was unavailable in this Workspace script runtime. "
            "Using only the explicit family/face supplied in resolve_controller_config.json."
        )
        return report

    try:
        font_manager = getattr(fusion_app, "FontManager", None)
        report["font_manager_available"] = font_manager is not None
        if font_manager is None:
            report["warnings"].append("Fusion handle exists but FontManager is missing.")
            return report
        getter = getattr(font_manager, "GetFontList", None)
        if not getter:
            report["warnings"].append("FontManager.GetFontList() is unavailable.")
            return report
        raw = getter()
        strings = _flatten_font_list_strings(raw)
        # De-duplicate while preserving order and ignore short metadata strings.
        files: List[str] = []
        seen = set()
        for value in strings:
            value_s = str(value).strip()
            if not value_s:
                continue
            key = value_s.lower()
            if key in seen:
                continue
            seen.add(key)
            files.append(value_s)
        report["font_list_available"] = True
        report["font_file_count"] = len(files)

        family_token = "".join(ch for ch in family.lower() if ch.isalnum())
        matched: List[str] = []
        for value_s in files:
            base = value_s.replace("\\", "/").split("/")[-1]
            stem = base.rsplit(".", 1)[0]
            stem_token = "".join(ch for ch in stem.lower() if ch.isalnum())
            full_token = "".join(ch for ch in value_s.lower() if ch.isalnum())
            if family_token and (family_token in stem_token or family_token in full_token):
                matched.append(value_s)
        report["matched_files"] = matched[:20]
        report["family_present"] = bool(matched)

        if style.lower() == "regular":
            report["style_present"] = bool(matched)
        else:
            style_token = "".join(ch for ch in style.lower() if ch.isalnum())
            style_matches = []
            for value_s in matched:
                base = value_s.replace("\\", "/").split("/")[-1]
                stem_token = "".join(ch for ch in base.rsplit(".", 1)[0].lower() if ch.isalnum())
                if style_token and style_token in stem_token:
                    style_matches.append(value_s)
            report["style_present"] = bool(style_matches)
            if not style_matches:
                report["warnings"].append(
                    "The requested non-Regular face could not be positively verified from font filenames; it will not be inferred from OCR weight."
                )

        report["safe_to_write"] = bool(report["family_present"] and report["style_present"])
        if not report["family_present"]:
            report["warnings"].append(f"Requested font family {family!r} was not found in Fusion FontManager.GetFontList().")
        elif not report["style_present"]:
            report["warnings"].append(f"Requested font face {style!r} was not positively verified for family {family!r}.")
    except Exception as exc:
        report["errors"].append(compact_exception(exc))
        report["warnings"].append("Font inventory read failed; explicit config remains the only font source of truth.")

    return report


DEFAULT_CAPTION_FONT_FALLBACK_ORDER = (
    "Impact|Regular,Arial Black|Regular,Anton|Regular,"
    "Montserrat|ExtraBold,Montserrat|Bold,Arial|Bold,Arial|Regular"
)
_FUSION_FONT_PROBE_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}


def normalize_caption_probe_text(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def parse_caption_font_fallback_order(value: Any) -> List[Tuple[str, str]]:
    raw = str(value or DEFAULT_CAPTION_FONT_FALLBACK_ORDER).strip()
    output: List[Tuple[str, str]] = []
    seen = set()
    for token in raw.replace(";", ",").split(","):
        token = " ".join(token.strip().split())
        if not token:
            continue
        if "|" in token:
            family_raw, style_raw = token.split("|", 1)
            family = family_raw.strip()
            style = style_raw.strip() or "Regular"
        else:
            family, parsed_style = split_fusion_font_name(token, None)
            style = parsed_style or "Regular"
        if not family:
            continue
        key = (family.lower(), style.lower())
        if key in seen:
            continue
        seen.add(key)
        output.append((family, style))
    return output


def cached_fusion_font_inventory(resolve: Any, family: str, style: str) -> Dict[str, Any]:
    key = (str(family or "").strip().lower(), str(style or "Regular").strip().lower())
    if key not in _FUSION_FONT_PROBE_CACHE:
        _FUSION_FONT_PROBE_CACHE[key] = probe_fusion_font_inventory(resolve, family, style)
    return _FUSION_FONT_PROBE_CACHE[key]


def resolve_caption_font(resolve: Any, style: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    """Resolve a detected/forced/fallback family+face against Resolve's inventory.

    This function never claims that a fallback was detected. It also never derives
    a font face from OCR weight. Only family/face combinations positively reported
    by Fusion FontManager are selected for automatic writes.
    """
    force_family_raw = str(getattr(args, "caption_force_font_name", "") or "").strip()
    force_style_raw = str(getattr(args, "caption_force_font_style", "") or "").strip()
    detected_family = str(style.get("detected_font_family") or "unknown").strip() or "unknown"
    detected_style = str(style.get("detected_font_style") or "").strip() or None
    fallback_order = str(
        getattr(args, "caption_font_fallback_order", DEFAULT_CAPTION_FONT_FALLBACK_ORDER)
        or DEFAULT_CAPTION_FONT_FALLBACK_ORDER
    )

    candidates: List[Dict[str, Any]] = []
    fallback_reason = None
    if force_family_raw:
        family, face = split_fusion_font_name(force_family_raw, force_style_raw or None)
        candidates.append({"family": family, "style": face or "Regular", "source": "explicit_override"})
    else:
        if detected_family.lower() != "unknown":
            candidates.append({
                "family": detected_family,
                "style": detected_style or "Regular",
                "source": "detected",
            })
        else:
            fallback_reason = "detector_font_family_unknown"
        for family, face in parse_caption_font_fallback_order(fallback_order):
            candidates.append({"family": family, "style": face, "source": "fallback_mapping"})

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for candidate in candidates:
        key = (candidate["family"].lower(), candidate["style"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    attempts: List[Dict[str, Any]] = []
    selected = None
    selected_inventory = None
    for candidate in deduped:
        inventory = cached_fusion_font_inventory(resolve, candidate["family"], candidate["style"])
        attempt = {
            "family": candidate["family"],
            "style": candidate["style"],
            "source": candidate["source"],
            "family_present": inventory.get("family_present"),
            "style_present": inventory.get("style_present"),
            "font_list_available": inventory.get("font_list_available"),
            "safe_to_write": bool(inventory.get("safe_to_write")),
            "matched_files": inventory.get("matched_files") or [],
            "warnings": inventory.get("warnings") or [],
            "errors": inventory.get("errors") or [],
        }
        attempts.append(attempt)
        if inventory.get("safe_to_write"):
            selected = candidate
            selected_inventory = inventory
            break

    if selected is None and force_family_raw:
        fallback_reason = "explicit_font_not_verified_in_resolve_inventory"
    elif selected is None and detected_family.lower() != "unknown":
        fallback_reason = "detected_and_fallback_fonts_not_verified_in_resolve_inventory"
    elif selected is None:
        fallback_reason = fallback_reason or "no_fallback_font_verified_in_resolve_inventory"
    elif selected.get("source") == "fallback_mapping" and detected_family.lower() != "unknown":
        fallback_reason = "detected_font_not_available_in_resolve"

    resolution = {
        "detected_font_family": detected_family,
        "detected_font_style": detected_style,
        "detected_font_weight_hint": style.get("font_weight_hint"),
        "selected_font_family": selected.get("family") if selected else None,
        "selected_font_style": selected.get("style") if selected else None,
        "font_selection_source": selected.get("source") if selected else "unresolved",
        "fallback_reason": fallback_reason,
        "resolve_inventory_verified": bool(selected_inventory and selected_inventory.get("safe_to_write")),
        "fallback_order": fallback_order,
        "candidates_attempted": attempts,
        "selected_inventory": selected_inventory,
    }

    style["font_resolution"] = resolution
    if selected:
        style["font_family"] = selected["family"]
        style["font_style"] = selected["style"]
        style["skip_font_write"] = False
    else:
        style["font_family"] = None
        style["font_style"] = None
        style["skip_font_write"] = True
    return resolution


def prepare_caption_runtime_style(
    resolve: Any,
    style: Dict[str, Any],
    args: argparse.Namespace,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Finalize a normalized caption style for an actual Resolve Text+ write.

    The analysis layer reports visible glyph pixels and may report an unknown font.
    This helper applies the configured Text+ calibration, resolves a real installed
    family/face through Fusion FontManager, and records the source of every choice.
    It is shared by verify, probe, and normal-apply paths so production cannot drift
    from the already-proven probe behavior.
    """
    force_size_raw = getattr(args, "caption_force_textplus_size", None)
    size_scale = clamp_float(
        getattr(args, "caption_textplus_size_scale", 1.5),
        0.10, 10.0, 1.5,
    )
    base_size = get_float(style.get("textplus_size_base"), 0.0)

    if force_size_raw is not None:
        selected_size = clamp_float(force_size_raw, 0.005, 0.50, 0.10)
        style["textplus_size"] = selected_size
        style["textplus_size_source"] = "caption_force_textplus_size"
        style["textplus_size_scale"] = None
    elif base_size > 0:
        selected_size = clamp_float(base_size * size_scale, 0.005, 0.50, 0.10)
        style["textplus_size"] = selected_size
        style["textplus_size_source"] = "detected_px_or_ratio_div_frame_width_times_scale"
        style["textplus_size_scale"] = size_scale
    else:
        selected_size = clamp_float(style.get("textplus_size"), 0.005, 0.50, 0.062)
        style["textplus_size"] = selected_size
        style["textplus_size_source"] = style.get("textplus_size_source") or "normalized_default"

    style["size_resolution"] = {
        "detected_font_height_px": style.get("font_size_px"),
        "detected_font_height_ratio": style.get("detected_font_height_ratio"),
        "frame_width": style.get("frame_width"),
        "frame_height": style.get("frame_height"),
        "textplus_size_base": style.get("textplus_size_base"),
        "textplus_size_scale": style.get("textplus_size_scale"),
        "selected_textplus_size": style.get("textplus_size"),
        "size_selection_source": style.get("textplus_size_source"),
    }

    resolve_caption_fill_color(style, args)
    font_resolution = resolve_caption_font(resolve, style, args)
    return style, font_resolution


def select_caption_probe_cues(
    cue_map: List[Dict[str, Any]],
    args: argparse.Namespace,
    probe_count: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    requested_text = str(getattr(args, "caption_probe_text", "") or "").strip()
    requested_cue_id = str(getattr(args, "caption_probe_cue_id", "") or "").strip()
    count = max(1, min(5, get_int(probe_count, 1)))
    diagnostics: Dict[str, Any] = {
        "requested_text": requested_text or None,
        "requested_cue_id": requested_cue_id or None,
        "requested_count": count,
        "matched": False,
        "match_strategy": None,
        "anchor_index": None,
        "selected_cue_ids": [],
        "selected_texts": [],
        "warnings": [],
    }
    if not cue_map:
        diagnostics["warnings"].append("Caption cue map is empty.")
        return [], diagnostics

    anchor = None
    if requested_cue_id:
        wanted = requested_cue_id.lower()
        for index, cue in enumerate(cue_map):
            if str(cue.get("cue_id") or "").strip().lower() == wanted:
                anchor = index
                diagnostics["matched"] = True
                diagnostics["match_strategy"] = "exact_cue_id"
                break
    if anchor is None and requested_text:
        wanted_text = normalize_caption_probe_text(requested_text)
        for index, cue in enumerate(cue_map):
            if normalize_caption_probe_text(cue.get("text")) == wanted_text:
                anchor = index
                diagnostics["matched"] = True
                diagnostics["match_strategy"] = "exact_normalized_text"
                break
        if anchor is None and wanted_text:
            for index, cue in enumerate(cue_map):
                cue_text = normalize_caption_probe_text(cue.get("text"))
                if wanted_text in cue_text or cue_text in wanted_text:
                    anchor = index
                    diagnostics["matched"] = True
                    diagnostics["match_strategy"] = "contained_normalized_text"
                    break

    if anchor is None:
        if requested_cue_id or requested_text:
            diagnostics["warnings"].append(
                "Requested probe cue was not found; selected the first meaningful caption instead."
            )
        # Avoid a one-character probe such as "I" because it gives weak visual
        # evidence for font family, size, and proportions.
        for index, cue in enumerate(cue_map):
            if len(normalize_caption_probe_text(cue.get("text"))) >= 4:
                anchor = index
                diagnostics["match_strategy"] = "first_meaningful_caption_fallback"
                break
    if anchor is None:
        anchor = 0
        diagnostics["match_strategy"] = "first_caption_fallback"

    selected = cue_map[anchor:anchor + count]
    if len(selected) < count:
        selected = cue_map[max(0, len(cue_map) - count):]
    diagnostics["anchor_index"] = anchor
    diagnostics["selected_cue_ids"] = [str(cue.get("cue_id") or "") for cue in selected]
    diagnostics["selected_texts"] = [str(cue.get("text") or "") for cue in selected]
    return selected, diagnostics


def fusion_input_values_equivalent(expected: Any, actual: Any, tolerance: float = 1e-5) -> bool:
    """Compare Fusion readback values without trusting a successful proxy setattr."""
    if actual is None:
        return False
    if isinstance(expected, str):
        return str(actual).strip().lower() == expected.strip().lower()
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= tolerance
    if isinstance(expected, (list, tuple)):
        if isinstance(actual, dict):
            actual_values = [actual.get(1), actual.get(2)]
            if actual_values[0] is None:
                actual_values = [actual.get("1"), actual.get("2")]
        elif isinstance(actual, (list, tuple)):
            actual_values = list(actual)
        else:
            return False
        if len(actual_values) < len(expected):
            return False
        return all(
            fusion_input_values_equivalent(exp, act, tolerance=tolerance)
            for exp, act in zip(expected, actual_values)
        )
    return actual == expected


def normalize_caption_textplus_style(
    generic: Dict[str, Any],
    caption_style_data: Optional[Dict[str, Any]],
    style_event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    style = normalize_caption_style(generic)
    rich = rich_style_source(caption_style_data)

    def update_from_rich(raw: Dict[str, Any]) -> None:
        if not isinstance(raw, dict):
            return
        colors = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
        typography = raw.get("typography") if isinstance(raw.get("typography"), dict) else {}
        placement = raw.get("placement") if isinstance(raw.get("placement"), dict) else {}
        stroke = raw.get("stroke") if isinstance(raw.get("stroke"), dict) else {}
        shadow = raw.get("shadow") if isinstance(raw.get("shadow"), dict) else {}

        if colors.get("fill"):
            style["text_color"] = colors.get("fill")
        if colors.get("stroke"):
            style["stroke_color"] = colors.get("stroke")
        if colors.get("shadow"):
            style["shadow_color"] = colors.get("shadow")
        if typography.get("font_family") and str(typography.get("font_family")).lower() != "unknown":
            style["font_family"] = typography.get("font_family")
        if typography.get("font_weight"):
            style["font_weight"] = typography.get("font_weight")
        if typography.get("case_style"):
            style["case_style"] = typography.get("case_style")
        if typography.get("font_height_px"):
            style["font_size_px"] = typography.get("font_height_px")
        if typography.get("font_height_ratio"):
            # OCR reports visible glyph height relative to frame height. Text+ Size
            # is a different unit: it is relative to image width, not a pixel/point
            # size. Keep the detector ratio as metadata and convert after the frame
            # dimensions are known.
            style["detected_font_height_ratio"] = get_float(typography.get("font_height_ratio"), 0.0)
        if placement.get("position"):
            style["placement"] = placement.get("position")
        anchor = placement.get("anchor") if isinstance(placement.get("anchor"), dict) else {}
        if anchor.get("x") is not None and anchor.get("y") is not None:
            anchor_x = clamp_float(anchor.get("x"), 0.0, 1.0, 0.5)
            anchor_y = clamp_float(anchor.get("y"), 0.0, 1.0, 0.5)
            coordinate_space = str(anchor.get("coordinate_space") or "normalized_frame").strip().lower()
            # Caption/OCR normalized-frame coordinates originate at the top-left,
            # while Fusion's normalized 2D coordinates originate at the bottom-left.
            # Writing detector Y directly therefore mirrors vertical placement.
            if coordinate_space in {
                "normalized_frame",
                "normalized_frame_top_left",
                "frame_normalized",
                "opencv_normalized",
                "image_normalized_top_left",
            }:
                fusion_y = 1.0 - anchor_y
                y_inverted = True
            else:
                fusion_y = anchor_y
                y_inverted = False
            style["detected_anchor"] = {
                "x": anchor_x,
                "y": anchor_y,
                "coordinate_space": coordinate_space,
            }
            style["center"] = [anchor_x, clamp_float(fusion_y, 0.0, 1.0, 0.5)]
            style["center_coordinate_conversion"] = {
                "source_space": coordinate_space,
                "target_space": "fusion_normalized_bottom_left",
                "input": [anchor_x, anchor_y],
                "output": list(style["center"]),
                "y_inverted": y_inverted,
            }
        if stroke.get("width_px_estimate") is not None:
            style["stroke_width"] = get_float(stroke.get("width_px_estimate"), style.get("stroke_width", 2.0))
        if stroke.get("color"):
            style["stroke_color"] = stroke.get("color")
        if shadow:
            style["shadow_enabled"] = bool(shadow.get("enabled", False))
            if shadow.get("color"):
                style["shadow_color"] = shadow.get("color")
            style["shadow_blur"] = get_float(shadow.get("blur_px_estimate"), 0.0)
            style["shadow_opacity"] = clamp_float(shadow.get("opacity_estimate"), 0.0, 1.0, 0.0)

    update_from_rich(rich)
    update_from_rich(style_event or {})

    event_confidence = (style_event or {}).get("confidence") if isinstance((style_event or {}).get("confidence"), dict) else {}
    rich_confidence = rich.get("confidence") if isinstance(rich.get("confidence"), dict) else {}
    selected_confidence = event_confidence or rich_confidence
    style["color_detection"] = {
        "detected_fill": style.get("text_color"),
        "detected_stroke": style.get("stroke_color"),
        "detected_shadow": style.get("shadow_color"),
        "confidence_score": get_float(selected_confidence.get("score"), 0.0),
        "confidence_label": selected_confidence.get("label"),
        "confidence_source": "style_event" if event_confidence else "resolved_primary_style",
        "style_event_id": (style_event or {}).get("event_id"),
    }

    # Preserve the detector result honestly. generic_edit_commands may already
    # contain an editor fallback such as Arial, but that is not proof that OCR
    # detected Arial. Rich caption-style typography is the detection source.
    rich_typography = rich.get("typography") if isinstance(rich.get("typography"), dict) else {}
    event_typography = (style_event or {}).get("typography") if isinstance((style_event or {}).get("typography"), dict) else {}
    detected_family_raw = event_typography.get("font_family") or rich_typography.get("font_family") or "unknown"
    detected_style_raw = event_typography.get("font_style") or rich_typography.get("font_style")
    detected_family = str(detected_family_raw or "unknown").strip() or "unknown"
    detected_style = str(detected_style_raw or "").strip() or None
    if detected_style and detected_style.lower() in {"unknown", "normal_or_unknown", "normal", "none"}:
        detected_style = None

    style["detected_font_family"] = detected_family
    style["detected_font_style"] = detected_style
    style["font_weight_hint"] = style.get("font_weight")
    if detected_family.lower() != "unknown":
        # A detector family is a family name, not a combined family/face string.
        style["font_family"] = detected_family
        style["font_style"] = detected_style or "Regular"
    else:
        style["font_family"] = None
        style["font_style"] = None

    video_info = caption_style_data.get("video_info") if isinstance(caption_style_data, dict) and isinstance(caption_style_data.get("video_info"), dict) else {}
    frame_width = get_float(video_info.get("width"), 0.0)
    frame_height = get_float(video_info.get("height"), 0.0)
    font_size_px = get_float(style.get("font_size_px"), 0.0)
    height_ratio = get_float(style.get("detected_font_height_ratio"), 0.0)
    textplus_size_base = 0.0
    size_source = "existing_default"
    if font_size_px > 0 and frame_width > 0:
        textplus_size_base = font_size_px / frame_width
        size_source = "font_height_px_div_frame_width"
    elif height_ratio > 0 and frame_width > 0 and frame_height > 0:
        textplus_size_base = height_ratio * frame_height / frame_width
        size_source = "font_height_ratio_converted_to_frame_width"
    elif height_ratio > 0:
        textplus_size_base = height_ratio
        size_source = "font_height_ratio_fallback"

    # Text+ Size is not a point/pixel value. A configurable calibration factor is
    # required because OCR measures visible glyph bounds while Text+ scales the
    # font's em box relative to image width. 1.5 maps this video's 71 px Impact
    # glyph estimate to ~0.10 on a 1080 px-wide vertical frame.
    default_size_scale = 1.5
    if textplus_size_base > 0:
        style["textplus_size_base"] = textplus_size_base
        style["textplus_size_scale"] = default_size_scale
        style["textplus_size_source"] = size_source
        style["frame_width"] = frame_width
        style["frame_height"] = frame_height
        style["textplus_size"] = textplus_size_base * default_size_scale

    if "center" not in style:
        style["center"] = fusion_center_for_placement(str(style.get("placement") or "middle_center"))
    style["textplus_size"] = clamp_float(style.get("textplus_size"), 0.020, 0.25, 0.062)
    style["opacity"] = clamp_float(style.get("opacity"), 0.0, 1.0, 1.0)
    style["style_event_id"] = (style_event or {}).get("event_id")
    style["style_profile_id"] = (style_event or {}).get("style_profile_id") or rich.get("primary_style_id")
    style["size_resolution"] = {
        "detected_font_height_px": font_size_px if font_size_px > 0 else None,
        "detected_font_height_ratio": height_ratio if height_ratio > 0 else None,
        "frame_width": frame_width if frame_width > 0 else None,
        "frame_height": frame_height if frame_height > 0 else None,
        "textplus_size_base": textplus_size_base if textplus_size_base > 0 else None,
        "textplus_size_scale": style.get("textplus_size_scale"),
        "selected_textplus_size": style.get("textplus_size"),
        "size_selection_source": style.get("textplus_size_source") or "existing_default",
    }
    return style


def get_timeline_frame_offset_from_video_items(video_items: List[Any]) -> int:
    if not video_items:
        return 0
    return min(timeline_item_start(item) for item in video_items)


def generated_caption_item_name(cue_index: int, cue_id: Any) -> str:
    safe_id = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(cue_id or f"sub_{cue_index:04d}"))
    return f"{VC_CAPTION_TEXTPLUS_PREFIX}{cue_index:04d}_{safe_id}"


def find_existing_caption_textplus_item(
    timeline: Any,
    target_track: int,
    cue_index: int,
    cue_id: Any,
    start_frame: int,
    end_frame: int,
    caption_track: int,
    allow_range_fallback: bool = False,
) -> Tuple[Optional[Any], Dict[str, Any]]:
    target_track = max(1, get_int(target_track, 2))
    cue_id_s = str(cue_id or "")
    wanted_prefix = generated_caption_item_name(cue_index, cue_id_s)
    diagnostics: Dict[str, Any] = {
        "target_track": target_track,
        "wanted_prefix": wanted_prefix,
        "searched_count": 0,
        "matched_by": None,
        "allow_range_fallback": bool(allow_range_fallback),
        "warnings": [],
    }

    # First: reliable named lookup.
    for item in get_track_items(timeline, "video", target_track):
        diagnostics["searched_count"] += 1
        name = timeline_item_name(item)
        if name.startswith(wanted_prefix) or (name.startswith(VC_CAPTION_TEXTPLUS_PREFIX) and cue_id_s and cue_id_s in name):
            diagnostics["matched_by"] = "name_prefix"
            return item, diagnostics

    # Optional legacy fallback. Production recovery keeps this disabled because
    # neighbouring word cues are often only 1-2 frames apart. The previous loose
    # tolerance reused the prior cue as the next cue (for example sub_073 as
    # sub_074), creating one missing caption and corrupting exact 1:1 coverage.
    # When explicitly enabled for a diagnostic probe, require an exact generated
    # item range and an existing VC_TEXTPLUS_ name.
    if allow_range_fallback and target_track != caption_track:
        wanted_duration = max(1, end_frame - start_frame)
        for item in get_track_items(timeline, "video", target_track):
            name = timeline_item_name(item)
            if not name.startswith(VC_CAPTION_TEXTPLUS_PREFIX):
                continue
            start = timeline_item_start(item)
            end = timeline_item_end(item)
            duration = max(0, get_int(safe_call(item, "GetDuration", default=None), end - start))
            if start == start_frame and duration == wanted_duration and (end == end_frame or end + 1 == end_frame):
                diagnostics["matched_by"] = "exact_generated_range"
                diagnostics["warnings"].append(
                    "Reused an explicitly generated Text+ item by exact range because its expected cue name was unavailable."
                )
                return item, diagnostics

    return None, diagnostics


def clear_old_caption_textplus_items(
    timeline: Any,
    target_track: Optional[int] = None,
    aggressive_dedicated_track: bool = False,
) -> Dict[str, Any]:
    if target_track is not None:
        return clear_caption_textplus_target_track(
            timeline,
            max(1, get_int(target_track, 3)),
            dedicated_track=bool(aggressive_dedicated_track),
        )
    items = find_items_by_name_prefix(timeline, VC_CAPTION_TEXTPLUS_PREFIX)
    return delete_timeline_items(timeline, items)


def caption_timeline_method_availability(timeline: Any) -> Dict[str, bool]:
    return {name: method_available(timeline, name) for name in CAPTION_TEXTPLUS_TIMELINE_METHOD_PROBES}


def get_or_create_existing_title_text_tool(item: Any, allow_add_fusion_comp: bool = False) -> Tuple[Optional[Any], Optional[Any], Dict[str, Any]]:
    info: Dict[str, Any] = {
        "attempted": True,
        "allow_add_fusion_comp": bool(allow_add_fusion_comp),
        "fusion_comp": None,
        "tools_count": 0,
        "text_tools_count": 0,
        "used_add_fusion_comp": False,
        "warnings": [],
        "errors": [],
    }

    comp = None
    comp_info: Dict[str, Any] = {}
    if allow_add_fusion_comp:
        comp, comp_info = get_or_create_fusion_comp(item)
        info["used_add_fusion_comp"] = bool((comp_info or {}).get("created"))
    else:
        comp, comp_info = get_existing_fusion_comp_readonly(item)
    info["fusion_comp"] = comp_info

    if not comp:
        return None, None, info

    tools = list_fusion_tools(comp)
    text_tools = find_textplus_tools(comp)
    info["tools_count"] = len(tools)
    info["text_tools_count"] = len(text_tools)
    info["tools_sample"] = [{"name": fusion_tool_name(t), "regid": fusion_tool_regid(t)} for t in tools[:20]]
    if not text_tools:
        info["warnings"].append("Fusion comp exists, but no TextPlus/Text tool is visible through GetToolList().")
        return comp, None, info
    return comp, text_tools[0], info


def set_caption_textplus_style_inputs(
    text_tool: Any,
    cue: Dict[str, Any],
    style: Dict[str, Any],
    cue_index: int,
    args: Optional[argparse.Namespace] = None,
    comp: Any = None,
) -> Dict[str, Any]:
    """Apply production Text+ controls with strict write/readback verification.

    The font family/face and calibrated Text+ size must already be finalized by
    ``prepare_caption_runtime_style``. Secondary shading remains disabled unless
    explicitly requested. Failed required controls make the item non-ready so a
    newly created partial title can be rolled back safely.
    """
    text_raw = str(cue.get("text") or "").strip()
    rendered_text = apply_case_style(text_raw, str(style.get("case_style") or "preserve"))
    r, g, b = parse_hex_color(style.get("text_color"), fallback=(1.0, 1.0, 1.0))
    center = (
        style.get("center")
        if isinstance(style.get("center"), list)
        else fusion_center_for_placement(str(style.get("placement") or "middle_center"))
    )
    size = clamp_float(style.get("textplus_size"), 0.005, 0.50, 0.062)
    font_family, parsed_style = split_fusion_font_name(
        style.get("font_family") or "Arial",
        style.get("font_style"),
    )
    font_style = str(style.get("font_style") or parsed_style or "Regular").strip() or "Regular"
    skip_font_write = bool(style.get("skip_font_write", False))

    result: Dict[str, Any] = {
        "attempted": True,
        "text": rendered_text,
        "font_family": font_family,
        "font_style": font_style,
        "font_resolution": json_safe_value(style.get("font_resolution")),
        "size_resolution": json_safe_value(style.get("size_resolution")),
        "text_color": style.get("text_color"),
        "stroke_color": style.get("stroke_color"),
        "color_resolution": json_safe_value(style.get("color_resolution")),
        "style_event_id": style.get("style_event_id"),
        "style_profile_id": style.get("style_profile_id"),
        "tool_name_before": fusion_tool_name(text_tool),
        "tool_regid": fusion_tool_regid(text_tool),
        "tool_name_set": set_fusion_tool_name(text_tool, f"{VC_CAPTION_TEXT_TOOL_PREFIX}{cue_index:04d}"),
        "inputs": {},
        "ok_input_count": 0,
        "required_text_ok": False,
        "font_family_ok": False,
        "font_style_ok": False,
        "size_ok": False,
        "color_ok": False,
        "position_ok": False,
        "secondary_reset_ok": False,
        "font_write_skipped": skip_font_write,
        "safe_shading_mode": "element_1_fill_only",
        "shading_probe": None,
        "styled_text_reset": None,
        "deferred_style_features": ["text_opacity"],
        "applied": False,
    }

    # Remove any hidden character-level formatting run before selecting family/face.
    reset_write = set_fusion_input_best_effort(text_tool, "StyledText", "")
    reset_readback = try_read_fusion_input(text_tool, "StyledText")
    result["styled_text_reset"] = {
        "write": reset_write,
        "readback": reset_readback,
        "verified": bool(reset_readback.get("ok"))
        and fusion_input_values_equivalent("", reset_readback.get("value")),
    }

    input_plan: List[Tuple[str, Any]] = []
    if not skip_font_write:
        input_plan.extend([("Font", font_family), ("Style", font_style)])

    input_plan.extend([
        ("Size", size),
        ("Center", center),
        ("Enabled1", 1),
        ("Red1", r),
        ("Green1", g),
        ("Blue1", b),
        ("Alpha1", 1.0),
    ])
    input_plan.extend((f"Enabled{index}", 0) for index in range(2, 9))
    input_plan.append(("StyledText", rendered_text))

    for input_name, value in input_plan:
        set_result = set_fusion_input_best_effort(text_tool, input_name, value)
        readback = try_read_fusion_input(text_tool, input_name)
        verified = bool(readback.get("ok")) and fusion_input_values_equivalent(value, readback.get("value"))
        result["inputs"][input_name] = {
            "write": set_result,
            "readback": readback,
            "verified": verified,
        }
        if verified:
            result["ok_input_count"] += 1

    def input_ok(name: str) -> bool:
        return bool((result["inputs"].get(name) or {}).get("verified"))

    result["required_text_ok"] = input_ok("StyledText")
    result["font_family_ok"] = True if skip_font_write else input_ok("Font")
    result["font_style_ok"] = True if skip_font_write else input_ok("Style")
    result["size_ok"] = input_ok("Size")
    result["position_ok"] = input_ok("Center")
    result["color_ok"] = all(input_ok(name) for name in ("Enabled1", "Red1", "Green1", "Blue1", "Alpha1"))
    result["secondary_reset_ok"] = all(input_ok(f"Enabled{index}") for index in range(2, 9))

    outline_requested = bool(args is not None and getattr(args, "caption_apply_outline", False))
    shadow_requested = bool(args is not None and getattr(args, "caption_apply_shadow", False))
    shading_required_ok = True
    if args is not None and (outline_requested or shadow_requested):
        shading = probe_safe_textplus_shading(text_tool, style, args, comp=comp)
        result["shading_probe"] = shading
        result["can_write_stroke"] = bool(shading.get("can_write_stroke"))
        result["can_write_shadow"] = bool(shading.get("can_write_shadow"))
        if result["can_write_stroke"] and result["can_write_shadow"]:
            result["safe_shading_mode"] = "element_1_fill_plus_verified_outline_and_shadow"
        elif result["can_write_stroke"]:
            result["safe_shading_mode"] = "element_1_fill_plus_verified_outline"
        elif result["can_write_shadow"]:
            result["safe_shading_mode"] = "element_1_fill_plus_verified_shadow"
        else:
            result["safe_shading_mode"] = "element_1_fill_only_shading_request_unverified"
        shading_required_ok = (
            (not outline_requested or result["can_write_stroke"])
            and (not shadow_requested or result["can_write_shadow"])
        )
    else:
        result["can_write_stroke"] = False
        result["can_write_shadow"] = False
        result["deferred_style_features"].extend(["stroke", "shadow"])

    result["base_required_ok"] = bool(
        result["required_text_ok"]
        and result["font_family_ok"]
        and result["font_style_ok"]
        and result["size_ok"]
        and result["color_ok"]
        and result["position_ok"]
        and result["secondary_reset_ok"]
    )
    result["shading_required_ok"] = bool(shading_required_ok)
    result["applied"] = bool(result["base_required_ok"] and result["shading_required_ok"])
    return result


def set_fusion_input_keyframe_best_effort(tool: Any, input_name: str, frame: int, value: Any) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    frame = get_int(frame, 0)

    try:
        method = getattr(tool, "SetInput", None)
        if method:
            ok = method(input_name, value, frame)
            attempts.append({"method": "SetInput(name, value, frame)", "input": input_name, "frame": frame, "value": json_safe_value(value), "ok": bool(ok)})
            if ok:
                return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "SetInput(name, value, frame)", "input": input_name, "frame": frame, "ok": False, "error": compact_exception(exc)})

    try:
        inp = getattr(tool, input_name)
        inp[frame] = value
        attempts.append({"method": "tool.<input>[frame] = value", "input": input_name, "frame": frame, "value": json_safe_value(value), "ok": True})
        return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "tool.<input>[frame] = value", "input": input_name, "frame": frame, "ok": False, "error": compact_exception(exc)})

    try:
        find_input = getattr(tool, "FindInput", None)
        if find_input:
            inp = find_input(input_name)
            if inp:
                inp[frame] = value
                attempts.append({"method": "FindInput(name)[frame] = value", "input": input_name, "frame": frame, "value": json_safe_value(value), "ok": True})
                return {"ok": True, "attempts": attempts}
            attempts.append({"method": "FindInput(name)", "input": input_name, "frame": frame, "ok": False, "reason": "input_missing"})
    except Exception as exc:
        attempts.append({"method": "FindInput(name)[frame] = value", "input": input_name, "frame": frame, "ok": False, "error": compact_exception(exc)})

    return {"ok": False, "attempts": attempts}


def animation_type_from_contract(style_event: Optional[Dict[str, Any]], args: argparse.Namespace, duration_frames: int) -> str:
    animation = (style_event or {}).get("animation") if isinstance((style_event or {}).get("animation"), dict) else {}
    explicit = str(animation.get("type") or animation.get("style") or "").strip().lower()
    if explicit in {"static", "none", "no_animation"}:
        return "static"
    if explicit in {"scale", "scale_pop", "pop_fade", "fade", "slide", "slide_fade"}:
        return explicit
    if not getattr(args, "caption_animation", False):
        return "static"
    if get_int(duration_frames, 0) < 3:
        return "static"
    # Conservative default: a small scale pop proves the path without heavy motion.
    return "scale_pop"


def apply_caption_animation_to_text_tool(
    text_tool: Any,
    cue: Dict[str, Any],
    style: Dict[str, Any],
    style_event: Optional[Dict[str, Any]],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    duration = max(0, get_int(cue.get("duration_frames"), 0))
    anim_type = animation_type_from_contract(style_event, args, duration)
    base_size = clamp_float(style.get("textplus_size"), 0.020, 0.20, 0.062)
    center = style.get("center") if isinstance(style.get("center"), list) else fusion_center_for_placement(str(style.get("placement") or "middle_center"))

    result: Dict[str, Any] = {
        "enabled": bool(getattr(args, "caption_animation", False)),
        "animation_type": anim_type,
        "duration_frames": duration,
        "keyframes": [],
        "keyframes_written": 0,
        "applied": False,
        "warnings": [],
        "errors": [],
    }
    if not getattr(args, "caption_animation", False):
        result["warnings"].append("caption_animation disabled")
        return result
    if duration < 3:
        result["warnings"].append("skipped_too_short")
        return result
    if anim_type == "static":
        return result

    key_plan: List[Tuple[str, int, Any]] = []
    f0 = 0
    f1 = max(1, min(duration - 1, int(round(duration * 0.28))))
    f2 = max(f1 + 1, min(duration - 1, int(round(duration * 0.55))))
    fend = max(1, duration - 1)

    explicit_keyframes = []
    animation = (style_event or {}).get("animation") if isinstance((style_event or {}).get("animation"), dict) else {}
    if isinstance(animation.get("keyframes"), list):
        explicit_keyframes = [k for k in animation.get("keyframes") if isinstance(k, dict)]

    if explicit_keyframes:
        for kf in explicit_keyframes:
            frame = get_int(kf.get("frame") or kf.get("relative_frame") or 0, 0)
            if kf.get("size") is not None or kf.get("scale") is not None:
                scale = get_float(kf.get("scale"), 1.0)
                key_plan.append(("Size", frame, clamp_float(kf.get("size"), 0.005, 0.50, base_size * scale)))
            if kf.get("opacity") is not None:
                key_plan.append(("Blend", frame, clamp_float(kf.get("opacity"), 0.0, 1.0, 1.0)))
            if kf.get("center") is not None:
                key_plan.append(("Center", frame, kf.get("center")))
    elif anim_type in {"scale", "scale_pop", "pop_fade"}:
        if anim_type == "scale":
            key_plan.extend([("Size", f0, base_size * 0.92), ("Size", f1, base_size)])
        else:
            key_plan.extend([("Size", f0, base_size * 0.85), ("Size", f1, base_size * 1.08), ("Size", f2, base_size)])
    if anim_type in {"fade", "pop_fade", "slide_fade"}:
        key_plan.extend([("Blend", f0, 0.0), ("Blend", f1, 1.0)])
    if anim_type in {"slide", "slide_fade"}:
        x = clamp_float(center[0] if len(center) > 0 else 0.5, 0.0, 1.0, 0.5)
        y = clamp_float(center[1] if len(center) > 1 else 0.5, 0.0, 1.0, 0.5)
        key_plan.extend([("Center", f0, [x, clamp_float(y - 0.025, 0.0, 1.0, y)]), ("Center", f1, [x, y])])

    for input_name, frame, value in key_plan:
        write = set_fusion_input_keyframe_best_effort(text_tool, input_name, frame, value)
        row = {"input": input_name, "frame": frame, "value": json_safe_value(value), "write": write}
        result["keyframes"].append(row)
        hard_debug("CAPTION_ANIMATION_KEYFRAME_WRITE", row)
        if write.get("ok"):
            result["keyframes_written"] += 1

    result["applied"] = result["keyframes_written"] > 0
    if key_plan and result["keyframes_written"] == 0:
        result["errors"].append("No requested animation keyframes could be written to the Text+ tool.")
    return result



def probe_item_identity(item: Any) -> str:
    """Stable-enough identity for before/after timeline scans inside one Resolve run."""
    uid = timeline_item_unique_id(item)
    if uid:
        return f"uid:{uid}"
    try:
        remote_repr = repr(item)
    except Exception:
        remote_repr = type(item).__name__
    track = timeline_item_track_info(item)
    return "|".join([
        remote_repr,
        str(track.get("track_type")),
        str(track.get("track_index")),
        timeline_item_name(item),
        str(timeline_item_start(item)),
        str(timeline_item_end(item)),
    ])


def snapshot_video_items_for_probe(
    timeline: Any,
    include_item_details: bool = True,
) -> Tuple[Dict[int, List[Any]], Dict[str, Any]]:
    items_by_track = get_all_video_items_by_track(timeline)
    report_tracks: Dict[str, Any] = {}
    for track_index, items in items_by_track.items():
        track_report: Dict[str, Any] = {"count": len(items)}
        if include_item_details:
            track_report["items"] = [
                {
                    "identity": probe_item_identity(item),
                    "uid": timeline_item_unique_id(item),
                    "name": timeline_item_name(item),
                    "start": timeline_item_start(item),
                    "end": timeline_item_end(item),
                    "duration": max(0, timeline_item_end(item) - timeline_item_start(item)),
                    "track": timeline_item_track_info(item),
                }
                for item in items
            ]
        report_tracks[str(track_index)] = track_report
    return items_by_track, {"video_track_count": get_video_track_count(timeline), "tracks": report_tracks}


def new_items_between_probe_snapshots(before: Dict[int, List[Any]], after: Dict[int, List[Any]]) -> List[Any]:
    before_counts: Dict[str, int] = {}
    for items in before.values():
        for item in items:
            identity = probe_item_identity(item)
            before_counts[identity] = before_counts.get(identity, 0) + 1

    new_items: List[Any] = []
    remaining = dict(before_counts)
    for track_index in sorted(after.keys()):
        for item in after.get(track_index) or []:
            identity = probe_item_identity(item)
            count = remaining.get(identity, 0)
            if count > 0:
                remaining[identity] = count - 1
            else:
                new_items.append(item)
    return new_items


def is_timeline_item_object(value: Any) -> bool:
    return value is not None and method_available(value, "GetStart") and method_available(value, "GetEnd")


def probe_title_creation_methods(
    timeline: Any,
    start_frame: int,
    end_frame: int,
    fps: float,
    title_name: str,
    target_track: int,
    detailed_diagnostics: bool = True,
) -> Tuple[Optional[Any], Dict[str, Any]]:
    """Try Resolve title insertion paths and detect items by both return value and track deltas."""
    start_frame = max(0, get_int(start_frame, 0))
    end_frame = max(start_frame + 1, get_int(end_frame, start_frame + 1))
    report: Dict[str, Any] = {
        "requested_start": start_frame,
        "requested_end": end_frame,
        "requested_duration": end_frame - start_frame,
        "target_track": target_track,
        "set_time": set_timeline_current_frame(timeline, start_frame, fps),
        "mark_in_out": set_timeline_mark_in_out(timeline, start_frame, max(start_frame, end_frame - 1), "video"),
        "method_results": [],
        "created_item_detected": False,
        "detected_by": None,
        "detected_track": None,
    }

    candidates = [
        ("InsertFusionTitleIntoTimeline", [title_name]),
        ("InsertFusionTitleIntoTimeline", ["Text+"]),
        ("InsertFusionTitleIntoTimeline", ["Text Plus"]),
        ("InsertTitleIntoTimeline", ["Text"]),
        ("InsertTitleIntoTimeline", [title_name]),
        ("InsertGeneratorIntoTimeline", ["Text+"]),
        ("InsertGeneratorIntoTimeline", [title_name]),
    ]
    deduped: List[Tuple[str, List[Any]]] = []
    seen = set()
    for method_name, method_args in candidates:
        key = (method_name, tuple(str(x) for x in method_args))
        if key not in seen:
            seen.add(key)
            deduped.append((method_name, method_args))

    detected_item: Optional[Any] = None
    for method_name, method_args in deduped:
        before_items, before_report = snapshot_video_items_for_probe(
            timeline, include_item_details=detailed_diagnostics
        )
        method_row: Dict[str, Any] = {
            "method": method_name,
            "args": json_safe_value(method_args),
            "available": method_available(timeline, method_name),
            "target_track_count_before": len(before_items.get(target_track) or []),
            "all_tracks_before": before_report,
            "returned_truthy": False,
            "returned_item_object": False,
            "created_item_detected": False,
            "detected_by": None,
            "new_items": [],
        }
        if not method_row["available"]:
            method_row["reason"] = "method_missing"
            report["method_results"].append(method_row)
            continue

        returned = None
        try:
            returned = getattr(timeline, method_name)(*method_args)
            method_row["returned_truthy"] = bool(returned)
            method_row["returned_type"] = type(returned).__name__ if returned is not None else None
            method_row["returned_item_object"] = is_timeline_item_object(returned)
        except Exception as exc:
            method_row["error"] = compact_exception(exc)

        # Resolve can mutate the timeline asynchronously and still return None.
        try:
            time.sleep(0.12)
        except Exception:
            pass
        after_items, after_report = snapshot_video_items_for_probe(
            timeline, include_item_details=detailed_diagnostics
        )
        new_items = new_items_between_probe_snapshots(before_items, after_items)
        method_row["target_track_count_after"] = len(after_items.get(target_track) or [])
        method_row["all_tracks_after"] = after_report
        method_row["new_items"] = [timeline_item_summary(item) | {"track": timeline_item_track_info(item)} for item in new_items]

        if is_timeline_item_object(returned):
            detected_item = returned
            method_row["created_item_detected"] = True
            method_row["detected_by"] = "returned_object"
        else:
            target_new = [item for item in new_items if get_int(timeline_item_track_info(item).get("track_index"), 0) == target_track]
            if target_new:
                detected_item = target_new[-1]
                method_row["created_item_detected"] = True
                method_row["detected_by"] = "new_item_on_target_track"
            elif new_items:
                detected_item = new_items[-1]
                method_row["created_item_detected"] = True
                method_row["detected_by"] = "new_item_on_other_video_track"

        if detected_item is not None:
            method_row["detected_item"] = timeline_item_summary(detected_item)
            method_row["detected_item"]["track"] = timeline_item_track_info(detected_item)
            report["created_item_detected"] = True
            report["detected_by"] = method_row.get("detected_by")
            report["detected_track"] = timeline_item_track_info(detected_item)
            report["insert_method"] = method_name
            report["insert_args"] = json_safe_value(method_args)

        report["method_results"].append(method_row)
        if detailed_diagnostics:
            hard_debug("CAPTION_TEXTPLUS_PROBE_CREATION_METHOD", method_row)
        else:
            hard_debug("CAPTION_TEXTPLUS_CREATION_METHOD", {
                "method": method_row.get("method"),
                "available": method_row.get("available"),
                "returned_truthy": method_row.get("returned_truthy"),
                "created_item_detected": method_row.get("created_item_detected"),
                "detected_by": method_row.get("detected_by"),
                "target_track_count_before": method_row.get("target_track_count_before"),
                "target_track_count_after": method_row.get("target_track_count_after"),
                "error": method_row.get("error"),
            })
        if detected_item is not None:
            # Stop at first real creation. Continuing would deliberately create duplicates.
            break

    report["clear_mark_in_out"] = clear_timeline_mark_in_out(timeline)
    return detected_item, report


def probe_fusion_access_and_text_tools(item: Any) -> Tuple[Optional[Any], Optional[Any], Dict[str, Any]]:
    report: Dict[str, Any] = {
        "can_get_comp": False,
        "can_add_comp": method_available(item, "AddFusionComp"),
        "method_availability": {
            name: method_available(item, name)
            for name in ("GetFusionCompCount", "AddFusionComp", "GetFusionCompByIndex", "GetFusionCompNameList", "LoadFusionCompByName")
        },
        "attempts": [],
        "fusion_comp_count_before": None,
        "fusion_comp_count_after": None,
        "fusion_comp_names": [],
        "tool_count": 0,
        "tools": [],
        "text_tool_candidates": [],
    }
    comp = None

    try:
        count = safe_call(item, "GetFusionCompCount", default=None)
        report["fusion_comp_count_before"] = get_int(count, 0) if count is not None else None
        report["attempts"].append({"method": "GetFusionCompCount", "ok": count is not None, "value": count})
    except Exception as exc:
        report["attempts"].append({"method": "GetFusionCompCount", "ok": False, "error": compact_exception(exc)})

    names = safe_call(item, "GetFusionCompNameList", default=[]) or []
    if isinstance(names, (list, tuple)):
        report["fusion_comp_names"] = [str(x) for x in names]
    report["attempts"].append({"method": "GetFusionCompNameList", "ok": isinstance(names, (list, tuple)), "value": json_safe_value(names)})

    count_before = get_int(report.get("fusion_comp_count_before"), 0)
    if count_before > 0:
        for index in (1, 0):
            candidate = safe_call(item, "GetFusionCompByIndex", index, default=None)
            report["attempts"].append({"method": "GetFusionCompByIndex", "index": index, "ok": bool(candidate), "result_type": type(candidate).__name__ if candidate else None})
            if candidate:
                comp = candidate
                report["loaded_by"] = f"GetFusionCompByIndex({index})"
                break

    if comp is None:
        for name in report.get("fusion_comp_names") or []:
            candidate = safe_call(item, "LoadFusionCompByName", name, default=None)
            report["attempts"].append({"method": "LoadFusionCompByName", "name": name, "ok": bool(candidate), "result_type": type(candidate).__name__ if candidate else None})
            if candidate:
                comp = candidate
                report["loaded_by"] = f"LoadFusionCompByName({name})"
                break

    if comp is None and report["can_add_comp"]:
        try:
            candidate = safe_call(item, "AddFusionComp", default=None)
            report["attempts"].append({"method": "AddFusionComp", "ok": bool(candidate), "result_type": type(candidate).__name__ if candidate else None})
            if candidate:
                comp = candidate
                report["loaded_by"] = "AddFusionComp()"
                report["added_comp"] = True
        except Exception as exc:
            report["attempts"].append({"method": "AddFusionComp", "ok": False, "error": compact_exception(exc)})
    elif comp is not None:
        report["attempts"].append({"method": "AddFusionComp", "attempted": False, "reason": "existing_comp_loaded"})

    count_after = safe_call(item, "GetFusionCompCount", default=None)
    report["fusion_comp_count_after"] = get_int(count_after, 0) if count_after is not None else None
    report["can_get_comp"] = bool(comp)

    if comp is None:
        return None, None, report

    tools = list_fusion_tools(comp)
    report["tool_count"] = len(tools)
    for tool in tools:
        row = {"name": fusion_tool_name(tool), "regid": fusion_tool_regid(tool)}
        report["tools"].append(row)
        haystack = f"{row['name']} {row['regid']}".lower()
        if "text" in haystack or "template" in haystack:
            report["text_tool_candidates"].append(row)

    text_tools = find_textplus_tools(comp)
    text_tool = text_tools[0] if text_tools else None
    if text_tool:
        report["selected_text_tool"] = {"name": fusion_tool_name(text_tool), "regid": fusion_tool_regid(text_tool)}
    return comp, text_tool, report


def probe_write_fusion_input(tool: Any, input_name: str, value: Any) -> Dict[str, Any]:
    write = set_fusion_input_best_effort(tool, input_name, value)
    readback = try_read_fusion_input(tool, input_name)
    verified = bool(readback.get("ok")) and fusion_input_values_equivalent(value, readback.get("value"))
    return {
        "input": input_name,
        "value": json_safe_value(value),
        "write": write,
        "readback": readback,
        "verified": verified,
        "ok": verified,
    }



def textplus_input_inventory(text_tool: Any) -> Dict[str, Any]:
    """Inventory real Text+ inputs before any secondary-shading write.

    FusionScript documents ``GetInputList()`` as the authoritative way to enumerate
    controls. This prevents false positives from Python ``setattr`` on an input ID
    that the current Resolve/Text+ build does not actually expose.
    """
    result: Dict[str, Any] = {
        "attempted": True,
        "available": False,
        "input_count": 0,
        "input_ids": [],
        "shading_inputs": [],
        "warnings": [],
        "errors": [],
    }
    method = getattr(text_tool, "GetInputList", None)
    if not method:
        result["errors"].append("Text tool does not expose GetInputList().")
        return result

    try:
        raw = method()
    except Exception as exc:
        result["errors"].append(compact_exception(exc))
        return result

    if isinstance(raw, dict):
        entries = list(raw.items())
    elif isinstance(raw, (list, tuple)):
        entries = list(enumerate(raw))
    else:
        try:
            entries = list(raw.items())
        except Exception:
            result["errors"].append(f"Unsupported GetInputList() result type: {type(raw).__name__}")
            return result

    rows: List[Dict[str, Any]] = []
    shading_rows: List[Dict[str, Any]] = []
    for key, input_obj in entries:
        attrs = safe_call(input_obj, "GetAttrs", default={})
        attrs = attrs if isinstance(attrs, dict) else {}
        input_id = str(
            attrs.get("INPS_ID")
            or key
            or attrs.get("INPS_Name")
            or ""
        ).strip()
        input_name = str(attrs.get("INPS_Name") or input_id).strip()
        simple_attrs: Dict[str, Any] = {}
        for attr_key, attr_value in attrs.items():
            if isinstance(attr_value, (str, int, float, bool)) or attr_value is None:
                simple_attrs[str(attr_key)] = attr_value

        row = {
            "id": input_id,
            "name": input_name,
            "data_type": attrs.get("INPS_DataType"),
            "control_page": attrs.get("INPS_IC_ControlPage") or attrs.get("INPS_ControlPage"),
            "control_group": attrs.get("INPS_IC_ControlGroup") or attrs.get("INPS_ControlGroup"),
            "attrs": simple_attrs,
        }
        rows.append(row)

        id_lower = input_id.lower()
        name_lower = input_name.lower()
        if (
            any(token in id_lower for token in (
                "enabled", "appearance", "red", "green", "blue", "alpha",
                "opacity", "thickness", "outside", "offset", "softness",
                "priority", "color", "type",
            ))
            or "shading" in str(row.get("control_page") or "").lower()
            or "shading" in str(row.get("control_group") or "").lower()
            or any(token in name_lower for token in (
                "appearance", "thickness", "outside only", "offset", "softness",
            ))
        ):
            shading_rows.append(row)

    result["available"] = True
    result["input_count"] = len(rows)
    result["input_ids"] = [row["id"] for row in rows if row.get("id")]
    result["shading_inputs"] = shading_rows
    return result


def find_inventory_input_id(inventory: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    available = {
        str(input_id).strip().lower(): str(input_id).strip()
        for input_id in (inventory.get("input_ids") or [])
        if str(input_id).strip()
    }
    for candidate in candidates:
        key = str(candidate or "").strip().lower()
        if key and key in available:
            return available[key]
    return None


def probe_write_inventoried_input(
    text_tool: Any,
    inventory: Dict[str, Any],
    candidates: List[str],
    value: Any,
    required: bool = True,
) -> Dict[str, Any]:
    input_id = find_inventory_input_id(inventory, candidates)
    if not input_id:
        return {
            "ok": False,
            "required": required,
            "candidates": candidates,
            "resolved_input_id": None,
            "reason": "input_not_in_GetInputList",
        }
    row = probe_write_fusion_input(text_tool, input_id, value)
    row.update({
        "required": required,
        "candidates": candidates,
        "resolved_input_id": input_id,
    })
    return row



def probe_write_textplus_candidate_input(
    text_tool: Any,
    inventory: Dict[str, Any],
    candidates: List[str],
    value: Any,
    required: bool = True,
    allow_hidden: bool = True,
) -> Dict[str, Any]:
    """Write a Text+ input using inventoried IDs first, then verified hidden IDs.

    Resolve exposes Enabled2..Enabled8 through GetInputList() while the remaining
    controls of disabled shading elements may stay hidden. Text+ settings use IDs
    such as ElementShape2, Red2 and Thickness2 even when those IDs are absent from
    the initial inventory. Hidden candidates are accepted only when a real write
    and readback both succeed.
    """
    ordered: List[str] = []
    inventoried_id = find_inventory_input_id(inventory, candidates)
    if inventoried_id:
        ordered.append(inventoried_id)
    if allow_hidden:
        for candidate in candidates:
            candidate_s = str(candidate or "").strip()
            if candidate_s and candidate_s.lower() not in {x.lower() for x in ordered}:
                ordered.append(candidate_s)

    attempts: List[Dict[str, Any]] = []
    for input_id in ordered:
        row = probe_write_fusion_input(text_tool, input_id, value)
        attempts.append(row)
        if row.get("ok"):
            return {
                "ok": True,
                "required": required,
                "candidates": candidates,
                "resolved_input_id": input_id,
                "source": "GetInputList" if inventoried_id and input_id.lower() == inventoried_id.lower() else "verified_hidden_input",
                "attempts": attempts,
                "write": row.get("write"),
                "readback": row.get("readback"),
                "value": json_safe_value(value),
            }

    return {
        "ok": False,
        "required": required,
        "candidates": candidates,
        "resolved_input_id": None,
        "source": None,
        "attempts": attempts,
        "value": json_safe_value(value),
        "reason": "no_candidate_verified_by_write_and_readback",
    }


def _fusion_comp_lock_best_effort(comp: Any) -> Dict[str, Any]:
    result = {"attempted": False, "method_available": False, "ok": False, "error": None}
    if comp is None:
        result["reason"] = "no_comp"
        return result
    method = getattr(comp, "Lock", None)
    result["method_available"] = bool(method)
    if not method:
        result["reason"] = "Lock_not_available"
        return result
    result["attempted"] = True
    try:
        method()
        result["ok"] = True
    except Exception as exc:
        result["error"] = compact_exception(exc)
    return result


def _fusion_comp_unlock_best_effort(comp: Any) -> Dict[str, Any]:
    result = {"attempted": False, "method_available": False, "ok": False, "error": None}
    if comp is None:
        result["reason"] = "no_comp"
        return result
    method = getattr(comp, "Unlock", None)
    result["method_available"] = bool(method)
    if not method:
        result["reason"] = "Unlock_not_available"
        return result
    result["attempted"] = True
    try:
        method()
        result["ok"] = True
    except Exception as exc:
        result["error"] = compact_exception(exc)
    return result


def _all_required_shading_rows_ok(rows: List[Dict[str, Any]]) -> bool:
    required_rows = [row for row in rows if bool(row.get("required", True))]
    return bool(required_rows) and all(bool(row.get("ok")) for row in required_rows)


def probe_safe_textplus_shading(
    text_tool: Any,
    style: Dict[str, Any],
    args: argparse.Namespace,
    comp: Any = None,
) -> Dict[str, Any]:
    """Configure Text+ outline/shadow with verified hidden-input support.

    Resolve 21 can expose only Enabled2..Enabled8 while a secondary shading
    element is disabled. Requested elements are enabled under the comp lock so
    their controls become addressable, then every property is written and read
    back. Unrequested elements remain disabled.
    """
    inventory_before = textplus_input_inventory(text_tool)
    outline_element = max(2, min(8, get_int(getattr(args, "caption_outline_element", 2), 2)))
    shadow_element = max(2, min(8, get_int(getattr(args, "caption_shadow_element", 3), 3)))
    if shadow_element == outline_element:
        shadow_element = 3 if outline_element != 3 else 4

    stroke_px = max(0.0, get_float(style.get("stroke_width"), 0.0))
    font_height_px = max(0.0, get_float(style.get("font_size_px"), 0.0))
    width_scale = clamp_float(getattr(args, "caption_outline_width_scale", 1.0), 0.10, 10.0, 1.0)
    thickness_override = getattr(args, "caption_outline_thickness", None)
    if thickness_override is None:
        if stroke_px > 0 and font_height_px > 0:
            outline_thickness = clamp_float((stroke_px / font_height_px) * width_scale, 0.001, 0.50, 0.045)
            thickness_source = "detected_stroke_px_div_detected_font_height_px_times_scale"
        else:
            outline_thickness = 0.045
            thickness_source = "conservative_default"
    else:
        outline_thickness = clamp_float(thickness_override, 0.001, 0.50, 0.045)
        thickness_source = "caption_outline_thickness"

    shadow_opacity_override = getattr(args, "caption_shadow_opacity", None)
    shadow_opacity = clamp_float(
        shadow_opacity_override if shadow_opacity_override is not None else style.get("shadow_opacity"),
        0.0, 1.0, 0.85,
    )
    shadow_offset = [
        clamp_float(getattr(args, "caption_shadow_offset_x", 0.003), -0.25, 0.25, 0.003),
        clamp_float(getattr(args, "caption_shadow_offset_y", 0.003), -0.25, 0.25, 0.003),
    ]
    shadow_softness_raw = getattr(args, "caption_shadow_softness", None)
    shadow_softness = None if shadow_softness_raw is None else clamp_float(shadow_softness_raw, 0.0, 0.50, 0.0)

    # Explicit configuration controls what is required. Probe mode no longer
    # silently forces shadow merely because OCR reported one.
    outline_requested = bool(getattr(args, "caption_apply_outline", False))
    shadow_requested = bool(getattr(args, "caption_apply_shadow", False))

    result: Dict[str, Any] = {
        "enabled": bool(getattr(args, "caption_shading_probe_only", False) or outline_requested or shadow_requested),
        "inventory": inventory_before,
        "inventory_after": None,
        "comp_lock": None,
        "comp_unlock": None,
        "appearance_contract": {
            "text_fill": 0,
            "text_outline": 1,
            "setting_id": "ElementShapeN",
            "source": "Text+ shading setting contract",
        },
        "outline": {
            "requested": outline_requested,
            "element": outline_element,
            "thickness": outline_thickness,
            "thickness_source": thickness_source,
            "detected_stroke_px": stroke_px or None,
            "detected_font_height_px": font_height_px or None,
            "attempts": [],
            "applied": False,
            "warnings": [],
            "errors": [],
        },
        "shadow": {
            "requested": shadow_requested,
            "element": shadow_element,
            "opacity": shadow_opacity,
            "offset": shadow_offset,
            "softness": shadow_softness,
            "attempts": [],
            "applied": False,
            "warnings": [],
            "errors": [],
        },
        "secondary_reset": [],
        "can_write_stroke": False,
        "can_write_shadow": False,
        "safe": True,
        "warnings": [],
        "errors": [],
    }

    if not result["enabled"]:
        result["reason"] = "shading probe and shading application disabled"
        return result
    if not inventory_before.get("available"):
        result["safe"] = False
        result["errors"].append("Text+ input inventory unavailable; secondary shading was not enabled.")
        return result

    result["comp_lock"] = _fusion_comp_lock_best_effort(comp)
    try:
        # Reset every secondary element first. Requested elements are enabled
        # again under the comp lock before their newly exposed controls are used.
        for element in range(2, 9):
            result["secondary_reset"].append(
                probe_write_textplus_candidate_input(
                    text_tool, inventory_before, [f"Enabled{element}"], 0,
                    required=False, allow_hidden=True,
                )
            )

        if outline_requested:
            e = outline_element
            outline_rows: List[Dict[str, Any]] = [
                probe_write_textplus_candidate_input(
                    text_tool, inventory_before, [f"Enabled{e}"], 1,
                )
            ]
            outline_inventory = textplus_input_inventory(text_tool)
            result["outline"]["inventory_after_enable"] = outline_inventory
            outline_rows.append(
                probe_write_textplus_candidate_input(
                    text_tool, outline_inventory,
                    [f"ElementShape{e}", f"Appearance{e}"], 1,
                )
            )

            sr, sg, sb = parse_hex_color(style.get("stroke_color"), fallback=(0.0, 0.0, 0.0))
            outline_rows.extend([
                probe_write_textplus_candidate_input(text_tool, outline_inventory, [f"Red{e}"], sr),
                probe_write_textplus_candidate_input(text_tool, outline_inventory, [f"Green{e}"], sg),
                probe_write_textplus_candidate_input(text_tool, outline_inventory, [f"Blue{e}"], sb),
                probe_write_textplus_candidate_input(text_tool, outline_inventory, [f"Alpha{e}"], 1.0),
                probe_write_textplus_candidate_input(text_tool, outline_inventory, [f"Thickness{e}"], outline_thickness),
            ])
            outline_rows.append(
                probe_write_textplus_candidate_input(
                    text_tool, outline_inventory, [f"OutsideOnly{e}"], 1,
                    required=False,
                )
            )

            required_ok = _all_required_shading_rows_ok(outline_rows)
            if required_ok:
                result["outline"]["applied"] = True
            else:
                result["outline"]["warnings"].append(
                    "Outline remained disabled because one or more required hidden/inventoried inputs failed verification."
                )
                outline_rows.append(
                    probe_write_textplus_candidate_input(
                        text_tool, inventory_before, [f"Enabled{e}"], 0,
                        required=False,
                    )
                )
            result["outline"]["attempts"] = outline_rows
            result["can_write_stroke"] = bool(result["outline"]["applied"])

        if shadow_requested:
            e = shadow_element
            shadow_rows: List[Dict[str, Any]] = [
                probe_write_textplus_candidate_input(
                    text_tool, inventory_before, [f"Enabled{e}"], 1,
                )
            ]
            shadow_inventory = textplus_input_inventory(text_tool)
            result["shadow"]["inventory_after_enable"] = shadow_inventory
            shadow_rows.append(
                probe_write_textplus_candidate_input(
                    text_tool, shadow_inventory,
                    [f"ElementShape{e}", f"Appearance{e}"], 0,
                )
            )
            rr, rg, rb = parse_hex_color(style.get("shadow_color"), fallback=(0.0, 0.0, 0.0))
            shadow_rows.extend([
                probe_write_textplus_candidate_input(text_tool, shadow_inventory, [f"Red{e}"], rr),
                probe_write_textplus_candidate_input(text_tool, shadow_inventory, [f"Green{e}"], rg),
                probe_write_textplus_candidate_input(text_tool, shadow_inventory, [f"Blue{e}"], rb),
                probe_write_textplus_candidate_input(text_tool, shadow_inventory, [f"Alpha{e}"], shadow_opacity),
                probe_write_textplus_candidate_input(text_tool, shadow_inventory, [f"Offset{e}"], shadow_offset),
            ])
            if shadow_softness is not None:
                shadow_rows.extend([
                    probe_write_textplus_candidate_input(
                        text_tool, shadow_inventory, [f"SoftnessX{e}", f"Softness{e}"],
                        shadow_softness, required=False,
                    ),
                    probe_write_textplus_candidate_input(
                        text_tool, shadow_inventory, [f"SoftnessY{e}"],
                        shadow_softness, required=False,
                    ),
                ])

            required_ok = _all_required_shading_rows_ok(shadow_rows)
            if required_ok:
                result["shadow"]["applied"] = True
            else:
                result["shadow"]["warnings"].append(
                    "Shadow remained disabled because one or more required hidden/inventoried inputs failed verification."
                )
                shadow_rows.append(
                    probe_write_textplus_candidate_input(
                        text_tool, inventory_before, [f"Enabled{e}"], 0,
                        required=False,
                    )
                )
            result["shadow"]["attempts"] = shadow_rows
            result["can_write_shadow"] = bool(result["shadow"]["applied"])
    finally:
        result["comp_unlock"] = _fusion_comp_unlock_best_effort(comp)
        result["inventory_after"] = textplus_input_inventory(text_tool)

    if outline_requested and not result["can_write_stroke"]:
        result["safe"] = False
    if shadow_requested and not result["can_write_shadow"]:
        result["safe"] = False
    return result


def probe_textplus_style_writes(text_tool: Any, cue: Dict[str, Any], style: Dict[str, Any], args: argparse.Namespace, comp: Any = None) -> Dict[str, Any]:
    """Probe safe Text+ text/style controls and optionally verified shading."""
    text_raw = str(cue.get("text") or "").strip()
    text = apply_case_style(text_raw, str(style.get("case_style") or "preserve"))
    r, g, b = parse_hex_color(style.get("text_color"), fallback=(1.0, 1.0, 1.0))
    size = clamp_float(style.get("textplus_size"), 0.020, 0.20, 0.062)
    center = style.get("center") if isinstance(style.get("center"), list) else fusion_center_for_placement(str(style.get("placement") or "middle_center"))
    font_family, font_style = split_fusion_font_name(
        style.get("font_family") or "Arial",
        style.get("font_style"),
    )

    skip_font_write = bool(style.get("skip_font_write", False))
    reset_text = probe_write_fusion_input(text_tool, "StyledText", "")
    groups: Dict[str, List[Tuple[str, Any]]] = {
        "font": [] if skip_font_write else [("Font", font_family)] + ([("Style", font_style)] if font_style else []),
        "size": [("Size", size)],
        "fill_color": [
            ("Enabled1", 1),
            ("Red1", r),
            ("Green1", g),
            ("Blue1", b),
            ("Alpha1", 1.0),
        ],
        "shading_reset": [(f"Enabled{index}", 0) for index in range(2, 9)],
        "opacity": [],
    }
    if bool(getattr(args, "caption_force_position_from_style", True)):
        groups["position"] = [("Center", center)]
    else:
        groups["position"] = []
    groups["text"] = [("StyledText", text)]

    attempts: Dict[str, Any] = {"styled_text_reset": [reset_text]}
    for group_name, plan in groups.items():
        attempts[group_name] = [probe_write_fusion_input(text_tool, input_name, value) for input_name, value in plan]

    def all_ok(group_name: str, allow_empty: bool = False) -> bool:
        rows = attempts.get(group_name) or []
        if not rows:
            return allow_empty
        return all(bool(row.get("ok")) for row in rows)

    font_rows = attempts.get("font") or []
    font_family_ok = False if skip_font_write else bool(font_rows and font_rows[0].get("ok"))
    font_style_ok = False if skip_font_write else (True if not font_style else bool(len(font_rows) > 1 and font_rows[1].get("ok")))

    shading_probe = probe_safe_textplus_shading(text_tool, style, args, comp=comp)
    can_write_stroke = bool(shading_probe.get("can_write_stroke"))
    can_write_shadow = bool(shading_probe.get("can_write_shadow"))

    deferred: List[str] = ["text_opacity"]
    if not can_write_stroke:
        deferred.append("stroke")
    if not can_write_shadow:
        deferred.append("shadow")
    if (shading_probe.get("shadow") or {}).get("softness") is None:
        deferred.append("shadow_softness")

    if shading_probe.get("enabled"):
        if can_write_stroke and can_write_shadow:
            safe_shading_mode = "element_1_fill_plus_verified_outline_and_shadow"
        elif can_write_stroke:
            safe_shading_mode = "element_1_fill_plus_verified_outline"
        elif can_write_shadow:
            safe_shading_mode = "element_1_fill_plus_verified_shadow"
        else:
            safe_shading_mode = "element_1_fill_only_shading_probe_failed_safe"
    else:
        safe_shading_mode = "element_1_fill_only"

    return {
        "attempted": True,
        "resolved": {
            "text": text,
            "font_override_raw": style.get("font_override_raw"),
            "font_family": font_family,
            "font_style": font_style,
            "font_resolution": style.get("font_resolution"),
            "font_write_skipped": skip_font_write,
            "size": size,
            "size_resolution": style.get("size_resolution"),
            "text_color": style.get("text_color"),
            "stroke_color": style.get("stroke_color"),
            "stroke_width_px": style.get("stroke_width"),
            "shadow_enabled": style.get("shadow_enabled"),
            "shadow_color": style.get("shadow_color"),
            "shadow_opacity": style.get("shadow_opacity"),
            "center": center,
            "detected_anchor": style.get("detected_anchor"),
            "center_coordinate_conversion": style.get("center_coordinate_conversion"),
            "force_position_from_style": bool(getattr(args, "caption_force_position_from_style", True)),
        },
        "safe_shading_mode": safe_shading_mode,
        "deferred_style_features": deferred,
        "attempts": attempts,
        "shading_probe": shading_probe,
        "can_write_text": all_ok("text"),
        "can_write_font": bool(font_family_ok and font_style_ok),
        "can_write_font_family": font_family_ok,
        "can_write_font_style": font_style_ok,
        "can_write_size": all_ok("size"),
        "can_write_color": all_ok("fill_color"),
        "can_reset_secondary_shading": all_ok("shading_reset"),
        "can_write_stroke": can_write_stroke,
        "can_write_shadow": can_write_shadow,
        "can_write_position": all_ok("position", allow_empty=not bool(getattr(args, "caption_force_position_from_style", True))),
        "can_write_opacity": False,
    }


def probe_scale_pop_animation(text_tool: Any, cue: Dict[str, Any], style: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "attempted": bool(getattr(args, "caption_animation", False)),
        "animation_type": "scale_pop",
        "keyframes_written": 0,
        "keyframes": [],
        "errors": [],
    }
    if not result["attempted"]:
        result["reason"] = "caption_animation disabled"
        return result

    duration = max(3, get_int(cue.get("duration_frames"), 3))
    end_frame = max(2, duration - 1)
    middle_frame = max(1, min(end_frame - 1, int(round(end_frame / 2.0))))
    base_size = clamp_float(style.get("textplus_size"), 0.020, 0.20, 0.062)
    plan = [
        (0, base_size * 0.85),
        (middle_frame, base_size * 1.08),
        (end_frame, base_size),
    ]
    for frame, value in plan:
        write = set_fusion_input_keyframe_best_effort(text_tool, "Size", frame, value)
        row = {"input": "Size", "frame": frame, "value": value, "write": write}
        result["keyframes"].append(row)
        if write.get("ok"):
            result["keyframes_written"] += 1
    if result["keyframes_written"] == 0:
        result["errors"].append("No scale_pop keyframes could be written.")
    result["applied"] = result["keyframes_written"] > 0
    return result


def textplus_probe_recommendation(probes: List[Dict[str, Any]]) -> str:
    if not probes or not any(row.get("created_item_detected") for row in probes):
        return "No title item was created or detected. Do not run full caption generation."
    if not any(((row.get("fusion_access") or {}).get("can_get_comp")) for row in probes):
        return "A timeline title item can be created, but no Fusion comp is accessible. Do not attempt caption animation."
    if not any(((row.get("fusion_access") or {}).get("text_tool_candidates")) for row in probes):
        return "A Fusion comp is accessible, but it contains no TextPlus/Text tool."
    duration_bad = any(row.get("created_item_detected") and not row.get("range_ok") for row in probes)
    if duration_bad:
        return "Text+ control works, but word-level duration trimming is unreliable. Switch to phrase-level Text+ clips."

    if len(probes) >= 5:
        all_track = all(bool(row.get("track_ok")) for row in probes)
        all_range = all(bool(row.get("range_ok")) for row in probes)
        all_style = all(bool((row.get("style_write") or {}).get("can_write_text")) for row in probes)
        requested_outlines = [
            row for row in probes
            if bool(((((row.get("style_write") or {}).get("shading_probe") or {}).get("outline") or {}).get("requested")))
        ]
        all_outline = all(bool((row.get("style_write") or {}).get("can_write_stroke")) for row in requested_outlines) if requested_outlines else True
        animation_requested = any(bool((row.get("animation_write") or {}).get("attempted")) for row in probes)
        all_animation = all(
            get_int((row.get("animation_write") or {}).get("keyframes_written"), 0) >= 3
            for row in probes
        ) if animation_requested else True
        if all_track and all_range and all_style and all_outline and all_animation:
            return "Strict five-caption Text+ generation passed with exact timing, per-cue styling, verified outline, and animation. Next run the normal applier capped at five captions."
        return "The strict five-caption batch is incomplete. Do not move to the normal applier until batch_integrity reports ok=true."

    shading_requested = any(
        bool((((row.get("style_write") or {}).get("shading_probe") or {}).get("enabled")))
        for row in probes
    )
    if shading_requested:
        requested_outlines = [
            row for row in probes
            if bool(((((row.get("style_write") or {}).get("shading_probe") or {}).get("outline") or {}).get("requested")))
        ]
        requested_shadows = [
            row for row in probes
            if bool(((((row.get("style_write") or {}).get("shading_probe") or {}).get("shadow") or {}).get("requested")))
        ]
        outline_ok = all(bool((row.get("style_write") or {}).get("can_write_stroke")) for row in requested_outlines) if requested_outlines else True
        shadow_ok = all(bool((row.get("style_write") or {}).get("can_write_shadow")) for row in requested_shadows) if requested_shadows else True
        if outline_ok and shadow_ok:
            return "Text+ creation, automatic font/size/style resolution, outline and shadow are proven for one cue. Next run the strict five-caption probe with per-cue styles."
        return "Text+ base styling works, but the safe shading probe is incomplete. Inspect shading_probe.inventory and failed required inputs before enabling shading in the five-caption/full applier."

    style_ok = any(((row.get("style_write") or {}).get("can_write_text")) for row in probes)
    animation_ok = any(get_int((row.get("animation_write") or {}).get("keyframes_written"), 0) > 0 for row in probes)
    if style_ok and animation_ok:
        return "Text+ creation, styling, and keyframe writing are proven. Run the safe one-caption shading probe next."
    if style_ok:
        return "Text+ creation and styling are proven, but animation keyframes are not."
    return "A controllable item exists, but text/style writes failed."


def run_textplus_creation_probe(
    resolve: Any,
    timeline: Any,
    generic: Dict[str, Any],
    cue_map: List[Dict[str, Any]],
    caption_style_data: Optional[Dict[str, Any]],
    args: argparse.Namespace,
    fps: float,
    target_track: int,
    caption_track: int,
) -> Dict[str, Any]:
    probe_count = max(1, min(5, get_int(getattr(args, "caption_probe_count", 1), 1)))
    keep_failed = bool(getattr(args, "caption_keep_failed_probe_item", False))
    style_probe_only = bool(getattr(args, "caption_style_probe_only", False))
    shading_probe_only = bool(getattr(args, "caption_shading_probe_only", False))
    duration_strictness_disabled = bool(getattr(args, "caption_disable_duration_strictness_for_probe", False))
    use_per_cue = bool(getattr(args, "caption_use_per_cue_style_events", True))
    force_font = str(getattr(args, "caption_force_font_name", "") or "").strip() or None
    force_font_style = str(getattr(args, "caption_force_font_style", "") or "").strip() or None
    force_size_raw = getattr(args, "caption_force_textplus_size", None)
    force_size = None if force_size_raw is None else clamp_float(force_size_raw, 0.005, 0.50, 0.10)
    size_scale = clamp_float(getattr(args, "caption_textplus_size_scale", 1.5), 0.10, 10.0, 1.5)
    selected_cues, probe_selection = select_caption_probe_cues(cue_map, args, probe_count)

    result: Dict[str, Any] = {
        "enabled": True,
        "probe_count": len(selected_cues),
        "probe_count_requested": probe_count,
        "probe_selection": probe_selection,
        "track": target_track,
        "caption_track": caption_track,
        "style_probe_only": style_probe_only,
        "shading_probe_only": shading_probe_only,
        "apply_outline": bool(getattr(args, "caption_apply_outline", False)),
        "apply_shadow": bool(getattr(args, "caption_apply_shadow", False)),
        "outline_element": max(2, min(8, get_int(getattr(args, "caption_outline_element", 2), 2))),
        "shadow_element": max(2, min(8, get_int(getattr(args, "caption_shadow_element", 3), 3))),
        "keep_failed_probe_item": keep_failed,
        "duration_strictness_disabled": duration_strictness_disabled,
        "use_per_cue_style_events": use_per_cue,
        "force_font_name": force_font,
        "force_font_style": force_font_style,
        "force_textplus_size": force_size,
        "textplus_size_scale": size_scale,
        "font_inventory": None,
        "font_resolution_summary": [],
        "force_position_from_style": bool(getattr(args, "caption_force_position_from_style", True)),
        "page": {},
        "track_setup": ensure_video_track(timeline, target_track),
        "clear_old": None,
        "track_guard": None,
        "track_guard_restore": None,
        "probes": [],
        "method_results": [],
        "v3_count_before": len(get_track_items(timeline, "video", target_track)),
        "v3_count_after_clear_old": None,
        "v3_count_after": None,
        "created_item_detected": False,
        "created_item_start": None,
        "created_item_end": None,
        "created_item_duration": None,
        "requested_start": None,
        "requested_end": None,
        "fusion_access": {"can_get_comp": False, "can_add_comp": False, "tool_count": 0, "text_tool_candidates": []},
        "style_write": {"can_write_text": False, "can_write_font": False, "can_write_size": False, "can_write_color": False, "can_write_position": False, "can_write_stroke": False, "can_write_shadow": False},
        "animation_write": {"attempted": bool(getattr(args, "caption_animation", False)), "keyframes_written": 0, "errors": []},
        "recommendation": None,
    }

    if resolve is not None:
        page_before = safe_call(resolve, "GetCurrentPage", default=None)
        open_result = safe_call(resolve, "OpenPage", "edit", default=None)
        page_after = safe_call(resolve, "GetCurrentPage", default=None)
        result["page"] = {"before": page_before, "open_edit_result": json_safe_value(open_result), "after": page_after}

    if getattr(args, "clear_old_vc_textplus", False) and not style_probe_only:
        result["clear_old"] = clear_old_caption_textplus_items(timeline)
    else:
        result["clear_old"] = {"attempted": False, "reason": "disabled or style_probe_only"}
    result["v3_count_after_clear_old"] = len(get_track_items(timeline, "video", target_track))

    core_before = snapshot_core_tracks(timeline, get_int(getattr(args, "video_track", 1), 1), get_int(getattr(args, "audio_track", 1), 1))
    result["core_tracks_before"] = core_before
    guard = apply_subtitle_track_guard(timeline, target_track)
    result["track_guard"] = guard

    try:
        for cue_row in selected_cues:
            cue_index = get_int(cue_row.get("cue_index"), len(result["probes"]) + 1)
            cue_id = cue_row.get("cue_id") or f"sub_{cue_index:04d}"
            start_frame = get_int(cue_row.get("start_frame"), 0)
            end_frame = max(start_frame + 1, get_int(cue_row.get("end_frame"), start_frame + 1))
            style_event = cue_row.get("style_event_raw") if use_per_cue else None
            style = normalize_caption_textplus_style(generic, caption_style_data, style_event)
            base_size = get_float(style.get("textplus_size_base"), 0.0)
            if force_size is not None:
                style["textplus_size"] = force_size
                style["textplus_size_source"] = "caption_force_textplus_size"
                style["textplus_size_scale"] = None
            elif base_size > 0:
                style["textplus_size"] = clamp_float(base_size * size_scale, 0.005, 0.50, 0.10)
                style["textplus_size_source"] = "detected_px_or_ratio_div_frame_width_times_scale"
                style["textplus_size_scale"] = size_scale
            style["size_resolution"] = {
                "detected_font_height_px": style.get("font_size_px"),
                "detected_font_height_ratio": style.get("detected_font_height_ratio"),
                "frame_width": style.get("frame_width"),
                "frame_height": style.get("frame_height"),
                "textplus_size_base": style.get("textplus_size_base"),
                "textplus_size_scale": style.get("textplus_size_scale"),
                "selected_textplus_size": style.get("textplus_size"),
                "size_selection_source": style.get("textplus_size_source"),
            }
            font_resolution = resolve_caption_font(resolve, style, args)
            result["font_resolution_summary"].append(font_resolution)
            if result.get("font_inventory") is None and isinstance(font_resolution.get("selected_inventory"), dict):
                result["font_inventory"] = font_resolution.get("selected_inventory")

            row: Dict[str, Any] = {
                "cue_id": cue_id,
                "cue_index": cue_index,
                "text": cue_row.get("text"),
                "requested_start": start_frame,
                "requested_end": end_frame,
                "requested_duration": end_frame - start_frame,
                "resolved_style": json_safe_value(style),
                "font_resolution": json_safe_value(font_resolution),
                "size_resolution": json_safe_value(style.get("size_resolution")),
                "created_item_detected": False,
                "created_new_item": False,
                "kept_item": False,
                "deleted_item": False,
                "warnings": [],
                "errors": [],
            }
            if not font_resolution.get("resolve_inventory_verified"):
                row["warnings"].append(
                    "No requested/detected/fallback font family+face was verified by Fusion FontManager; font write will be skipped."
                )

            item = None
            if style_probe_only:
                item, lookup = find_existing_caption_textplus_item(
                    timeline, target_track, cue_index, cue_id, start_frame, end_frame, caption_track,
                    allow_range_fallback=True,
                )
                row["existing_lookup"] = lookup
                if item is None:
                    candidates = [x for x in get_track_items(timeline, "video", target_track) if timeline_item_is_title_like(x)]
                    item = candidates[0] if candidates else None
                    if item:
                        row["warnings"].append("Style probe used the first title-like item on the target track because no named/range match was found.")
            else:
                before_target_count = len(get_track_items(timeline, "video", target_track))
                item, creation = probe_title_creation_methods(
                    timeline, start_frame, end_frame, fps,
                    str(getattr(args, "caption_title_name", "Text+") or "Text+"),
                    target_track,
                )
                row["creation"] = creation
                row["created_new_item"] = bool(item)
                row["target_count_before_creation"] = before_target_count

            if item is None:
                row["errors"].append("No timeline item was available for Fusion/Text+ probing.")
                result["probes"].append(row)
                continue

            row["created_item_detected"] = True
            row["name"] = set_timeline_item_name(item, generated_caption_item_name(cue_index, cue_id))
            row["initial_item"] = timeline_item_summary(item)
            row["initial_item"]["track"] = timeline_item_track_info(item)
            row["range_write"] = set_timeline_item_range(item, start_frame, end_frame)
            row["item_after_range"] = timeline_item_summary(item)
            row["item_after_range"]["track"] = timeline_item_track_info(item)
            row["created_item_start"] = row["item_after_range"].get("start")
            row["created_item_end"] = row["item_after_range"].get("end")
            row["created_item_duration"] = row["item_after_range"].get("duration")
            track_info = timeline_item_track_info(item)
            track_ok = track_info.get("track_type") == "video" and get_int(track_info.get("track_index"), 0) == target_track
            range_ok = bool((row.get("range_write") or {}).get("ok"))
            row["track_ok"] = track_ok
            row["range_ok"] = range_ok

            comp, text_tool, fusion_access = probe_fusion_access_and_text_tools(item)
            row["fusion_access"] = fusion_access
            if text_tool is not None:
                row["style_write"] = probe_textplus_style_writes(text_tool, cue_row, style, args, comp=comp)
                row["animation_write"] = probe_scale_pop_animation(text_tool, cue_row, style, args)
            else:
                row["style_write"] = {
                    "attempted": False,
                    "can_write_text": False,
                    "can_write_font": False,
                    "can_write_size": False,
                    "can_write_color": False,
                    "can_write_position": False,
                    "can_write_stroke": False,
                    "can_write_shadow": False,
                    "reason": "no TextPlus/Text tool candidate",
                }
                row["animation_write"] = {
                    "attempted": False,
                    "keyframes_written": 0,
                    "errors": ["no TextPlus/Text tool candidate"],
                }

            style_ok = bool((row.get("style_write") or {}).get("can_write_text"))
            shading_ok = True
            if shading_probe_only:
                shading_report = ((row.get("style_write") or {}).get("shading_probe") or {})
                outline_requested = bool(((shading_report.get("outline") or {}).get("requested")))
                shadow_requested = bool(((shading_report.get("shadow") or {}).get("requested")))
                shading_ok = (
                    (not outline_requested or bool((row.get("style_write") or {}).get("can_write_stroke")))
                    and (not shadow_requested or bool((row.get("style_write") or {}).get("can_write_shadow")))
                )
            row["shading_required_ok"] = shading_ok
            failed = (not track_ok) or (not range_ok and not duration_strictness_disabled) or (text_tool is None) or (not style_ok) or (not shading_ok)
            row["failed"] = failed

            should_delete = False
            if not style_probe_only:
                if keep_failed:
                    should_delete = False
                elif not track_ok:
                    should_delete = True
                elif not range_ok and not duration_strictness_disabled:
                    should_delete = True
                elif text_tool is None or not style_ok:
                    should_delete = True

            if should_delete:
                row["rollback_delete"] = delete_timeline_items(timeline, [item])
                row["deleted_item"] = bool((row.get("rollback_delete") or {}).get("deleted"))
            else:
                row["kept_item"] = True

            result["probes"].append(row)
            hard_debug("CAPTION_TEXTPLUS_PROBE_ITEM_DONE", row)

    finally:
        result["track_guard_restore"] = restore_track_locks(timeline, guard)
        core_after = snapshot_core_tracks(timeline, get_int(getattr(args, "video_track", 1), 1), get_int(getattr(args, "audio_track", 1), 1))
        result["core_tracks_after"] = core_after
        result["core_track_integrity"] = compare_core_track_snapshots(core_before, core_after)

    result["v3_count_after"] = len(get_track_items(timeline, "video", target_track))
    first = result["probes"][0] if result["probes"] else {}
    creation = first.get("creation") or {}
    item_after = first.get("item_after_range") or first.get("initial_item") or {}
    result["method_results"] = creation.get("method_results") or []
    result["created_item_detected"] = bool(first.get("created_item_detected"))
    result["created_item_start"] = item_after.get("start")
    result["created_item_end"] = item_after.get("end")
    result["created_item_duration"] = item_after.get("duration")
    result["requested_start"] = first.get("requested_start")
    result["requested_end"] = first.get("requested_end")
    result["fusion_access"] = first.get("fusion_access") or result["fusion_access"]
    result["style_write"] = first.get("style_write") or result["style_write"]
    result["animation_write"] = first.get("animation_write") or result["animation_write"]
    result["created_count"] = sum(1 for row in result["probes"] if row.get("created_new_item"))
    result["detected_count"] = sum(1 for row in result["probes"] if row.get("created_item_detected"))
    result["failed_count"] = sum(1 for row in result["probes"] if row.get("failed") or not row.get("created_item_detected"))
    result["keyframes_written"] = sum(get_int((row.get("animation_write") or {}).get("keyframes_written"), 0) for row in result["probes"])
    requested_outline = bool(getattr(args, "caption_apply_outline", False))
    requested_shadow = bool(getattr(args, "caption_apply_shadow", False))
    animation_requested = bool(getattr(args, "caption_animation", False))
    style_event_ids = [
        ((row.get("resolved_style") or {}).get("style_event_id"))
        for row in result["probes"]
        if ((row.get("resolved_style") or {}).get("style_event_id"))
    ]
    style_profile_ids = [
        ((row.get("resolved_style") or {}).get("style_profile_id"))
        for row in result["probes"]
        if ((row.get("resolved_style") or {}).get("style_profile_id"))
    ]
    result["batch_integrity"] = {
        "requested_count": probe_count,
        "selected_count": len(selected_cues),
        "detected_count": result["detected_count"],
        "created_count": result["created_count"],
        "failed_count": result["failed_count"],
        "all_track_ok": bool(result["probes"]) and all(bool(row.get("track_ok")) for row in result["probes"]),
        "all_range_ok": bool(result["probes"]) and all(bool(row.get("range_ok")) for row in result["probes"]),
        "all_text_ok": bool(result["probes"]) and all(bool((row.get("style_write") or {}).get("can_write_text")) for row in result["probes"]),
        "all_font_ok": bool(result["probes"]) and all(bool((row.get("style_write") or {}).get("can_write_font")) for row in result["probes"]),
        "all_size_ok": bool(result["probes"]) and all(bool((row.get("style_write") or {}).get("can_write_size")) for row in result["probes"]),
        "all_color_ok": bool(result["probes"]) and all(bool((row.get("style_write") or {}).get("can_write_color")) for row in result["probes"]),
        "all_position_ok": bool(result["probes"]) and all(bool((row.get("style_write") or {}).get("can_write_position")) for row in result["probes"]),
        "outline_requested": requested_outline,
        "all_outline_ok": (not requested_outline) or (
            bool(result["probes"]) and all(bool((row.get("style_write") or {}).get("can_write_stroke")) for row in result["probes"])
        ),
        "shadow_requested": requested_shadow,
        "all_shadow_ok": (not requested_shadow) or (
            bool(result["probes"]) and all(bool((row.get("style_write") or {}).get("can_write_shadow")) for row in result["probes"])
        ),
        "animation_requested": animation_requested,
        "all_animation_ok": (not animation_requested) or (
            bool(result["probes"]) and all(
                get_int((row.get("animation_write") or {}).get("keyframes_written"), 0) >= 3
                for row in result["probes"]
            )
        ),
        "keyframes_written": result["keyframes_written"],
        "per_cue_style_event_count": len(style_event_ids),
        "style_event_ids": style_event_ids,
        "unique_style_profile_ids": sorted(set(str(x) for x in style_profile_ids)),
        "core_track_integrity_ok": bool((result.get("core_track_integrity") or {}).get("ok")),
    }
    result["batch_integrity"]["ok"] = bool(
        result["batch_integrity"]["selected_count"] == result["batch_integrity"]["requested_count"]
        and result["batch_integrity"]["detected_count"] == result["batch_integrity"]["requested_count"]
        and result["batch_integrity"]["failed_count"] == 0
        and result["batch_integrity"]["all_track_ok"]
        and result["batch_integrity"]["all_range_ok"]
        and result["batch_integrity"]["all_text_ok"]
        and result["batch_integrity"]["all_font_ok"]
        and result["batch_integrity"]["all_size_ok"]
        and result["batch_integrity"]["all_color_ok"]
        and result["batch_integrity"]["all_position_ok"]
        and result["batch_integrity"]["all_outline_ok"]
        and result["batch_integrity"]["all_shadow_ok"]
        and result["batch_integrity"]["all_animation_ok"]
        and result["batch_integrity"]["core_track_integrity_ok"]
    )
    result["recommendation"] = textplus_probe_recommendation(result["probes"])
    hard_debug("CAPTION_TEXTPLUS_CREATION_PROBE_DONE", result)
    return result

def build_caption_textplus_cue_map(
    timeline: Any,
    generic: Dict[str, Any],
    caption_style_data: Optional[Dict[str, Any]],
    args: argparse.Namespace,
    fps: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Any]]:
    caption_track = max(1, get_int(getattr(args, "caption_track", 2), 2))
    expected = expected_caption_cues_from_generic(generic, fps)
    items = get_track_items(timeline, "video", caption_track)
    records = [actual_caption_item_record(item, i, fps, caption_title_name=getattr(args, "caption_title_name", "Text+")) for i, item in enumerate(items, start=1)]
    title_records = [r for r in records if r.get("title_like")]
    title_items = [items[get_int(r.get("index"), 1) - 1] for r in title_records if 0 <= get_int(r.get("index"), 1) - 1 < len(items)]
    style_index = build_style_event_index(caption_style_data)

    mapped: List[Dict[str, Any]] = []
    for index, cue in enumerate(expected, start=1):
        static_record = title_records[index - 1] if index - 1 < len(title_records) else None
        style_event = pick_style_event_for_cue(cue, style_index, fps)
        duration = get_int(cue.get("duration_frames"), max(0, get_int(cue.get("end_frame"), 0) - get_int(cue.get("start_frame"), 0)))
        animation_type = animation_type_from_contract(style_event, args, duration)
        timing_delta = None
        if static_record:
            timing_delta = {
                "start_delta_frames": get_int(static_record.get("start_frame"), 0) - get_int(cue.get("start_frame"), 0),
                "end_delta_frames": get_int(static_record.get("end_frame"), 0) - get_int(cue.get("end_frame"), 0),
                "duration_delta_frames": get_int(static_record.get("duration_frames"), 0) - duration,
            }
            timing_delta["max_abs_delta_frames"] = max(abs(get_int(timing_delta.get("start_delta_frames"), 0)), abs(get_int(timing_delta.get("end_delta_frames"), 0)), abs(get_int(timing_delta.get("duration_delta_frames"), 0)))
        mapped.append({
            "cue_id": cue.get("id") or cue.get("subtitle_id") or f"sub_{index:04d}",
            "cue_index": index,
            "text": cue.get("text"),
            "start_frame": get_int(cue.get("start_frame"), 0),
            "end_frame": get_int(cue.get("end_frame"), 0),
            "duration_frames": duration,
            "start_seconds": cue.get("start_seconds"),
            "end_seconds": cue.get("end_seconds"),
            "source_static_title_item": static_record,
            "mapped_static_title": bool(static_record),
            "timing_delta": timing_delta,
            "style_event": json_safe_value(style_event) if style_event else None,
            "style_event_raw": style_event,
            "animation": {"type": animation_type},
        })

    diagnostics = {
        "expected_count": len(expected),
        "caption_track": caption_track,
        "static_items_seen": len(items),
        "title_like_items_seen": len(title_records),
        "style_events_seen": len(style_index.get("events") or []),
        "mapped_count": len(mapped),
        "unmapped_expected_count": max(0, len(expected) - len(title_records)),
        "track_counts": caption_item_counts(records),
    }
    return mapped, diagnostics, title_items


def _property_value_matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return bool(value) is expected
    try:
        return abs(float(value) - float(expected)) <= 0.001
    except Exception:
        return value == expected


def restore_static_title_visibility(
    static_items: List[Any],
    allow_item_writes: bool = False,
) -> Dict[str, Any]:
    """
    Restore V2 reference titles before a rerun.

    Imported FCPXML Basic Title TimelineItem.SetProperty("Opacity", ...) caused
    repeatable native Resolve 21.0.1 crashes in Workspace -> Scripts. The API
    advertises SetProperty, but capability discovery is not proof that the write
    is safe for this item class. Writes are therefore hard-disabled by default.
    """
    result: Dict[str, Any] = {
        "attempted": True,
        "items_count": len(static_items),
        "restored_count": 0,
        "failed_count": 0,
        "all_ok": True,
        "items": [],
        "write_guard": {
            "allowed": bool(allow_item_writes),
            "reason": (
                "explicit unsafe opt-in"
                if allow_item_writes
                else "blocked: imported Basic Title SetProperty writes crash Resolve 21.0.1"
            ),
        },
    }
    if not allow_item_writes:
        result["attempted"] = False
        result["reason"] = "static_title_item_writes_blocked_for_resolve_crash_safety"
        return result

    for item in static_items:
        row = {"name": timeline_item_name(item), "property": "Opacity", "target": 100, "ok": False}
        ok, readback = safe_set_property(item, "Opacity", 100)
        row["set_ok"] = bool(ok)
        row["readback"] = json_safe_value(readback)
        row["ok"] = bool(ok and _property_value_matches(readback, 100))
        if row["ok"]:
            result["restored_count"] += 1
        else:
            result["failed_count"] += 1
            result["all_ok"] = False
        result["items"].append(row)
    return result


def apply_static_title_policy_to_items(
    timeline: Any,
    static_items: List[Any],
    policy: str,
    replacement_ready_count: int,
    target_count: int,
    allow_item_writes: bool = False,
) -> Dict[str, Any]:
    policy = str(policy or "keep").lower()
    result: Dict[str, Any] = {
        "policy": policy,
        "attempted": False,
        "items_count": len(static_items),
        "replacement_ready_count": replacement_ready_count,
        "target_count": target_count,
        "hidden_count": 0,
        "disabled_count": 0,
        "failed_count": 0,
        "all_ok": policy == "keep",
        "items": [],
        "warnings": [],
    }
    if policy == "keep":
        result["reason"] = "keep policy"
        return result
    if not allow_item_writes:
        result["warnings"].append(
            "Static V2 item writes were blocked because TimelineItem.SetProperty on imported "
            "Basic Titles caused repeatable native Resolve 21.0.1 crashes. Keep V2 visible; "
            "test track-level disable only after full V3 coverage on a duplicate timeline."
        )
        result["reason"] = "static_title_item_writes_blocked_for_resolve_crash_safety"
        result["all_ok"] = False
        return result
    if replacement_ready_count < target_count:
        result["warnings"].append("Static-title policy skipped because replacement Text+ coverage is incomplete.")
        result["all_ok"] = False
        return result
    if len(static_items) < target_count:
        result["warnings"].append("Static-title policy skipped because fewer V2 reference titles were mapped than replacement targets.")
        result["all_ok"] = False
        return result
    if policy == "delete":
        result["warnings"].append("delete policy remains intentionally disabled; use verified hide so the V2 timing reference is preserved.")
        result["all_ok"] = False
        return result

    result["attempted"] = True
    for item in static_items[:target_count]:
        item_result: Dict[str, Any] = {
            "name": timeline_item_name(item),
            "attempts": [],
            "ok": False,
            "resolved_property": None,
        }
        if policy == "hide":
            # Resolve exposes TimelineItem Opacity for imported Basic Titles in this
            # build. Try that first and require a numeric zero readback.
            for prop_name, value in (("Opacity", 0), ("CompositeOpacity", 0), ("Blend", 0)):
                ok, readback = safe_set_property(item, prop_name, value)
                verified = bool(ok and _property_value_matches(readback, value))
                item_result["attempts"].append({
                    "property": prop_name,
                    "value": value,
                    "set_ok": bool(ok),
                    "readback": json_safe_value(readback),
                    "verified": verified,
                })
                if verified:
                    item_result["ok"] = True
                    item_result["resolved_property"] = prop_name
                    result["hidden_count"] += 1
                    break
        elif policy == "disable":
            for prop_name, value in (("Enabled", False), ("Enable", False), ("Disable", True)):
                ok, readback = safe_set_property(item, prop_name, value)
                verified = bool(ok and _property_value_matches(readback, value))
                item_result["attempts"].append({
                    "property": prop_name,
                    "value": value,
                    "set_ok": bool(ok),
                    "readback": json_safe_value(readback),
                    "verified": verified,
                })
                if verified:
                    item_result["ok"] = True
                    item_result["resolved_property"] = prop_name
                    result["disabled_count"] += 1
                    break
        else:
            item_result["warnings"] = [f"Unknown static title policy: {policy}"]

        if not item_result["ok"]:
            result["failed_count"] += 1
        result["items"].append(item_result)

    result["all_ok"] = bool(
        len(result["items"]) == target_count
        and result["failed_count"] == 0
        and all(bool(row.get("ok")) for row in result["items"])
    )
    return result



def compact_font_resolution_record(value: Any) -> Dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "detected_font_family": row.get("detected_font_family"),
        "detected_font_style": row.get("detected_font_style"),
        "selected_font_family": row.get("selected_font_family"),
        "selected_font_style": row.get("selected_font_style"),
        "font_selection_source": row.get("font_selection_source"),
        "fallback_reason": row.get("fallback_reason"),
        "resolve_inventory_verified": bool(row.get("resolve_inventory_verified")),
    }


def compact_caption_insert_result(value: Any) -> Dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    methods = row.get("method_results") if isinstance(row.get("method_results"), list) else []
    return {
        "requested_start": row.get("requested_start"),
        "requested_end": row.get("requested_end"),
        "requested_duration": row.get("requested_duration"),
        "target_track": row.get("target_track"),
        "created_item_detected": bool(row.get("created_item_detected")),
        "detected_by": row.get("detected_by"),
        "detected_track": row.get("detected_track"),
        "methods": [
            {
                "method": method.get("method"),
                "args": method.get("args"),
                "available": method.get("available"),
                "returned_truthy": method.get("returned_truthy"),
                "created_item_detected": method.get("created_item_detected"),
                "detected_by": method.get("detected_by"),
                "error": method.get("error"),
            }
            for method in methods
        ],
    }


def compact_caption_style_result(value: Any) -> Dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    resolved = row.get("resolved") if isinstance(row.get("resolved"), dict) else {}
    return {
        "applied": bool(row.get("applied")),
        "required_text_ok": bool(row.get("required_text_ok")),
        "font_family_ok": bool(row.get("font_family_ok")),
        "font_style_ok": bool(row.get("font_style_ok")),
        "size_ok": bool(row.get("size_ok")),
        "color_ok": bool(row.get("color_ok")),
        "position_ok": bool(row.get("position_ok")),
        "resolved": {
            "font_family": resolved.get("font_family"),
            "font_style": resolved.get("font_style"),
            "size": resolved.get("size"),
            "text_color": resolved.get("text_color"),
            "center": resolved.get("center"),
            "style_event_id": resolved.get("style_event_id"),
        },
        "warnings": row.get("warnings") or [],
        "errors": row.get("errors") or [],
    }


def compact_caption_animation_result(value: Any) -> Dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "enabled": bool(row.get("enabled")),
        "animation_type": row.get("animation_type"),
        "duration_frames": row.get("duration_frames"),
        "keyframes_written": get_int(row.get("keyframes_written"), 0),
        "applied": bool(row.get("applied")),
        "warnings": row.get("warnings") or [],
        "errors": row.get("errors") or [],
    }


def compact_caption_item_result(value: Any) -> Dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    style = row.get("overlay_style") or row.get("in_place_style") or {}
    return {
        "cue_id": row.get("cue_id"),
        "cue_index": row.get("cue_index"),
        "text": row.get("text"),
        "start_frame": row.get("start_frame"),
        "end_frame": row.get("end_frame"),
        "duration_frames": row.get("duration_frames"),
        "style_event_id": row.get("style_event_id"),
        "provisioning_path": row.get("provisioning_path"),
        "name": row.get("name"),
        "textplus_ready": bool(row.get("textplus_ready")),
        "track_ok": bool(row.get("track_ok")),
        "range_ok": bool(row.get("range_ok")),
        "keyframes_written": get_int(row.get("keyframes_written"), 0),
        "animation_type": row.get("animation_type"),
        "font_resolution": compact_font_resolution_record(row.get("font_resolution")),
        "size_resolution": row.get("size_resolution") or {},
        "color_resolution": row.get("color_resolution") or {},
        "style": compact_caption_style_result(style),
        "animation": compact_caption_animation_result(row.get("animation")),
        "insert": compact_caption_insert_result(row.get("insert")),
        "media_carrier_fallback": (
            {
                "attempted": bool((row.get("media_carrier_fallback") or {}).get("attempted")),
                "backend": (row.get("media_carrier_fallback") or {}).get("backend"),
                "ok": bool((row.get("media_carrier_fallback") or {}).get("ok")),
                "append_ok": bool(((row.get("media_carrier_fallback") or {}).get("append") or {}).get("ok")),
                "graph_applied": bool(((row.get("media_carrier_fallback") or {}).get("graph") or {}).get("applied")),
                "errors": (row.get("media_carrier_fallback") or {}).get("errors") or [],
            }
            if row.get("media_carrier_fallback")
            else None
        ),
        "warnings": row.get("warnings") or [],
        "errors": row.get("errors") or [],
    }


def caption_checkpoint_path(args: argparse.Namespace) -> Optional[str]:
    report_path = str(getattr(args, "report", "") or "").strip()
    if not report_path:
        return None
    path = Path(report_path)
    return str(path.with_name(path.stem + "_caption_checkpoint.json"))


def write_caption_generation_checkpoint(
    args: argparse.Namespace,
    result: Dict[str, Any],
    processed_count: int,
    total_count: int,
    last_item: Optional[Dict[str, Any]],
    status: str = "running",
) -> Dict[str, Any]:
    path = caption_checkpoint_path(args)
    checkpoint = {
        "controller_version": VERSION,
        "created_at_unix": now_unix(),
        "status": status,
        "processed_count": processed_count,
        "total_count": total_count,
        "ready_count": sum(1 for row in (result.get("items") or []) if row.get("textplus_ready")),
        "failed_count": get_int(result.get("textplus_failed_count"), 0),
        "created_count": get_int(result.get("textplus_created_count"), 0),
        "keyframes_written": get_int((result.get("animation") or {}).get("keyframes_written_count"), 0),
        "last_item": compact_caption_item_result(last_item) if last_item else None,
        "core_tracks_before": result.get("core_tracks_before"),
        "warnings": result.get("warnings") or [],
        "errors": result.get("errors") or [],
    }
    if not path:
        return {"attempted": False, "reason": "report path unavailable", "checkpoint": checkpoint}
    try:
        save_json(path, checkpoint)
        hard_debug("CAPTION_TEXTPLUS_CHECKPOINT", {
            "path": path,
            "status": status,
            "processed_count": processed_count,
            "total_count": total_count,
            "ready_count": checkpoint.get("ready_count"),
            "failed_count": checkpoint.get("failed_count"),
            "last_cue_id": ((checkpoint.get("last_item") or {}).get("cue_id")),
        })
        return {"attempted": True, "ok": True, "path": path, "checkpoint": checkpoint}
    except Exception as exc:
        hard_debug("CAPTION_TEXTPLUS_CHECKPOINT_FAILED", {"path": path, "error": compact_exception(exc)})
        return {"attempted": True, "ok": False, "path": path, "error": compact_exception(exc)}



def verify_generated_item_range_readonly(
    item: Any,
    start_frame: int,
    end_frame: int,
    target_track: int,
) -> Dict[str, Any]:
    """Verify an already-appended generated item without mutating its range.

    The timeline contract is half-open: [start_frame, end_frame).
    Resolve can report GetEnd() as either exclusive or inclusive depending on
    item type, but GetDuration() must equal the requested occupied frame count.
    """
    start_frame = max(0, get_int(start_frame, 0))
    end_frame = max(start_frame + 1, get_int(end_frame, start_frame + 1))
    requested_duration = end_frame - start_frame
    actual_start = timeline_item_start(item)
    actual_end = timeline_item_end(item)
    actual_duration = max(
        0,
        get_int(
            safe_call(item, "GetDuration", default=None),
            max(0, actual_end - actual_start),
        ),
    )
    track = timeline_item_track_info(item)
    track_ok = (
        str(track.get("track_type") or "").lower() == "video"
        and get_int(track.get("track_index"), 0) == max(1, get_int(target_track, 1))
    )
    start_ok = actual_start == start_frame
    duration_ok = actual_duration == requested_duration
    end_semantics_ok = actual_end in {end_frame, end_frame - 1}
    return {
        "attempted": False,
        "verification_only": True,
        "ok": bool(track_ok and start_ok and duration_ok and end_semantics_ok),
        "track_ok": bool(track_ok),
        "start_ok": bool(start_ok),
        "duration_ok": bool(duration_ok),
        "end_semantics_ok": bool(end_semantics_ok),
        "requested": {
            "start": start_frame,
            "end": end_frame,
            "duration": requested_duration,
            "range_semantics": "half_open",
        },
        "actual": {
            "start": actual_start,
            "end": actual_end,
            "duration": actual_duration,
        },
        "accepted_end_values": [end_frame, end_frame - 1],
        "track": track,
        "attempts": [],
    }


def verify_generated_item_range_with_settle(
    item: Any,
    start_frame: int,
    end_frame: int,
    target_track: int,
    timeout_sec: float = 1.50,
    poll_interval_sec: float = 0.10,
) -> Dict[str, Any]:
    """Poll read-only range verification before allowing safe rollback.

    Resolve may expose a newly imported image-sequence item's duration one API
    tick late. The old Step 2F verified once after 150 ms and immediately
    rollback-deleted the clip. This helper never mutates the item; it only waits
    for stable API readback.
    """
    timeout_sec = max(0.0, min(10.0, get_float(timeout_sec, 1.50)))
    poll_interval_sec = max(0.02, min(1.0, get_float(poll_interval_sec, 0.10)))
    started = time.monotonic()
    snapshots: List[Dict[str, Any]] = []
    final: Dict[str, Any] = {}

    while True:
        current = verify_generated_item_range_readonly(
            item,
            start_frame,
            end_frame,
            target_track,
        )
        elapsed = max(0.0, time.monotonic() - started)
        snapshots.append({
            "elapsed_sec": round(elapsed, 4),
            "ok": bool(current.get("ok")),
            "track_ok": bool(current.get("track_ok")),
            "start_ok": bool(current.get("start_ok")),
            "duration_ok": bool(current.get("duration_ok")),
            "end_semantics_ok": bool(current.get("end_semantics_ok")),
            "actual": current.get("actual"),
        })
        final = current
        if current.get("ok"):
            break
        if elapsed >= timeout_sec:
            break
        time.sleep(min(poll_interval_sec, max(0.0, timeout_sec - elapsed)))

    final = dict(final)
    final["settle_verification"] = {
        "attempted": True,
        "timeout_sec": timeout_sec,
        "poll_interval_sec": poll_interval_sec,
        "poll_count": len(snapshots),
        "elapsed_sec": round(max(0.0, time.monotonic() - started), 4),
        "settled_ok": bool(final.get("ok")),
        "snapshots": snapshots,
    }
    return final


def _find_textplus_carrier_source(video_items: List[Any], duration_frames: int) -> Dict[str, Any]:
    """Find a safe media-backed source item for a video-only carrier clip."""
    duration_frames = max(1, get_int(duration_frames, 1))
    attempts: List[Dict[str, Any]] = []
    for index, item in enumerate(video_items or [], start=1):
        media_pool_item = safe_call(item, "GetMediaPoolItem", default=None)
        if not media_pool_item:
            continue
        item_duration = max(0, get_int(safe_call(item, "GetDuration", default=None), 0))
        left_offset = max(0, get_int(safe_call(item, "GetLeftOffset", default=0), 0))
        row = {
            "index": index,
            "item_name": timeline_item_name(item),
            "duration": item_duration,
            "left_offset": left_offset,
            "media_pool_item_name": safe_call(media_pool_item, "GetName", default=None),
        }
        attempts.append(row)
        if item_duration >= duration_frames:
            return {
                "ok": True,
                "source_item": item,
                "media_pool_item": media_pool_item,
                "source_start": left_offset,
                "source_end_inclusive": left_offset + duration_frames - 1,
                "attempts": attempts,
            }
    return {
        "ok": False,
        "source_item": None,
        "media_pool_item": None,
        "attempts": attempts,
        "error": f"No media-backed V1 item is long enough for a {duration_frames}-frame TextPlus carrier.",
    }


def _ensure_textplus_graph_on_carrier(item: Any, generated_name: str) -> Dict[str, Any]:
    """Replace a media carrier's Fusion output with transparent TextPlus output."""
    result: Dict[str, Any] = {
        "attempted": True,
        "generated_name": generated_name,
        "fusion_comp": None,
        "text_tool_created": False,
        "media_out_created": False,
        "connection": None,
        "applied": False,
        "warnings": [],
        "errors": [],
    }
    comp, comp_info = get_or_create_fusion_comp(item)
    result["fusion_comp"] = comp_info
    if not comp:
        result["errors"].append("Could not create a Fusion comp on the media carrier item.")
        return result

    locked = False
    try:
        if method_available(comp, "Lock"):
            safe_call(comp, "Lock", default=None)
            locked = True

        tools = list_fusion_tools(comp)
        text_tools = find_textplus_tools(comp)
        text_tool = text_tools[0] if text_tools else None
        if text_tool is None:
            for regid in ("TextPlus", "Text+"):
                try:
                    text_tool = safe_call(comp, "AddTool", regid, -32768, -32768, default=None)
                except Exception:
                    text_tool = None
                if text_tool:
                    result["text_tool_created"] = True
                    result["text_tool_regid"] = regid
                    break
        if text_tool is None:
            result["errors"].append("Fusion comp exists, but TextPlus could not be created.")
            return result

        media_out = find_fusion_tool(comp, ["MediaOut"], ["MediaOut1", "MediaOut"])
        if media_out is None:
            media_out = safe_call(comp, "AddTool", "MediaOut", -32768, -32768, default=None)
            result["media_out_created"] = bool(media_out)
        if media_out is None:
            result["errors"].append("Fusion comp has no MediaOut and one could not be created.")
            return result

        result["tool_names"] = {
            "text": fusion_tool_name(text_tool),
            "media_out": fusion_tool_name(media_out),
        }
        result["name_writes"] = {
            "text": set_fusion_tool_name(text_tool, f"{generated_name}_TextPlus"),
        }
        result["connection"] = connect_fusion_tools(text_tool, media_out, "Input")
        result["applied"] = bool((result.get("connection") or {}).get("ok"))
        if not result["applied"]:
            result["errors"].append("TextPlus could not be connected directly to MediaOut.")
        return result
    except Exception as exc:
        result["errors"].append(compact_exception(exc))
        result["traceback"] = traceback.format_exc()
        return result
    finally:
        if locked:
            safe_call(comp, "Unlock", default=None)



def ensure_explicit_textplus_node_on_item(item: Any, generated_name: str) -> Dict[str, Any]:
    """Create and read back a connected TextPlus node on any Fusion-capable item."""
    result: Dict[str, Any] = {
        "attempted": True,
        "generated_name": generated_name,
        "before": None,
        "graph_apply": None,
        "after": None,
        "textplus_verified": False,
        "textplus_count": 0,
        "textplus_tools": [],
        "applied": False,
        "errors": [],
    }

    comp_before, text_before, before_info = get_or_create_existing_title_text_tool(
        item, allow_add_fusion_comp=True
    )
    result["before"] = before_info
    if comp_before is not None and text_before is not None:
        result["textplus_verified"] = True
        result["textplus_count"] = 1
        result["textplus_tools"] = [{
            "name": fusion_tool_name(text_before),
            "regid": fusion_tool_regid(text_before),
        }]
        result["applied"] = True
        return result

    graph = _ensure_textplus_graph_on_carrier(item, generated_name)
    result["graph_apply"] = graph
    if not graph.get("applied"):
        result["errors"].extend(graph.get("errors") or ["TextPlus graph creation failed."])
        return result

    comp_after, text_after, after_info = get_or_create_existing_title_text_tool(
        item, allow_add_fusion_comp=False
    )
    result["after"] = after_info
    if comp_after is None:
        result["errors"].append("Fusion composition was not readable after graph creation.")
        return result

    tools = find_textplus_tools(comp_after)
    if text_after is not None and text_after not in tools:
        tools.insert(0, text_after)
    result["textplus_count"] = len(tools)
    result["textplus_tools"] = [
        {"name": fusion_tool_name(tool), "regid": fusion_tool_regid(tool)}
        for tool in tools
    ]
    result["textplus_verified"] = bool(tools)
    result["applied"] = bool(tools)
    if not result["applied"]:
        result["errors"].append(
            "Fusion graph write returned success, but no TextPlus node was visible on readback."
        )
    return result


def provision_textplus_fusion_composition(
    timeline: Any,
    start_frame: int,
    end_frame: int,
    fps: float,
    target_track: int,
    generated_name: str,
) -> Tuple[Optional[Any], Dict[str, Any]]:
    """Create a real Fusion Composition and explicitly populate it with TextPlus."""
    start_frame = max(0, get_int(start_frame, 0))
    end_frame = max(start_frame + 1, get_int(end_frame, start_frame + 1))
    result: Dict[str, Any] = {
        "attempted": True,
        "backend": "fusion_composition_explicit_textplus",
        "target_track": target_track,
        "requested_start": start_frame,
        "requested_end": end_frame,
        "requested_duration": end_frame - start_frame,
        "creation": None,
        "name": None,
        "range": None,
        "textplus_graph": None,
        "ok": False,
        "errors": [],
    }

    if not method_available(timeline, "InsertFusionCompositionIntoTimeline"):
        result["errors"].append("Timeline.InsertFusionCompositionIntoTimeline is unavailable.")
        return None, result

    before_items, _ = snapshot_video_items_for_probe(
        timeline, include_item_details=False
    )
    result["set_time"] = set_timeline_current_frame(timeline, start_frame, fps)
    result["mark_in_out"] = set_timeline_mark_in_out(
        timeline, start_frame, max(start_frame, end_frame - 1), "video"
    )

    returned = None
    try:
        returned = timeline.InsertFusionCompositionIntoTimeline()
    except Exception as exc:
        result["errors"].append(compact_exception(exc))

    time.sleep(0.15)
    after_items, _ = snapshot_video_items_for_probe(
        timeline, include_item_details=False
    )
    new_items = new_items_between_probe_snapshots(before_items, after_items)
    target_new = [
        item for item in new_items
        if get_int(timeline_item_track_info(item).get("track_index"), 0) == target_track
    ]

    requested_duration = end_frame - start_frame

    def _candidate_exact(candidate: Any) -> bool:
        if candidate is None:
            return False
        track = timeline_item_track_info(candidate)
        if track.get("track_type") != "video" or get_int(track.get("track_index"), 0) != target_track:
            return False
        actual_start = timeline_item_start(candidate)
        actual_end = timeline_item_end(candidate)
        actual_duration = max(0, get_int(
            safe_call(candidate, "GetDuration", default=None),
            actual_end - actual_start,
        ))
        return bool(
            actual_start == start_frame
            and actual_duration == requested_duration
            and (actual_end == end_frame or actual_end + 1 == end_frame)
        )

    returned_item = returned if is_timeline_item_object(returned) else None
    item = returned_item if _candidate_exact(returned_item) else None
    detected_by = "returned_object_exact_range" if item is not None else None
    if item is None:
        exact_target = [candidate for candidate in target_new if _candidate_exact(candidate)]
        if exact_target:
            item = exact_target[-1]
            detected_by = "new_item_on_target_track_exact_range"
    if item is None and returned_item is not None:
        item = returned_item
        detected_by = "returned_object_nonexact_fallback"
    if item is None and target_new:
        item = target_new[-1]
        detected_by = "new_item_on_target_track_fallback"
    elif item is None and new_items:
        item = new_items[-1]
        detected_by = "new_item_on_other_video_track_fallback"

    # Resolve 21 can create two items for one InsertFusionCompositionIntoTimeline
    # call when marks and short adjacent cues are involved: the requested clip plus
    # a 1-frame artifact. Keep only the selected item from this exact API call.
    selected_identity = probe_item_identity(item) if item is not None else None
    artifact_items = [
        candidate for candidate in new_items
        if selected_identity is None or probe_item_identity(candidate) != selected_identity
    ]
    artifact_cleanup = delete_timeline_items(timeline, artifact_items) if artifact_items else {
        "attempted": False, "requested_count": 0, "deleted": 0, "attempts": []
    }

    result["creation"] = {
        "returned_truthy": bool(returned),
        "returned_type": type(returned).__name__ if returned is not None else None,
        "new_item_count": len(new_items),
        "target_new_item_count": len(target_new),
        "detected_by": detected_by,
        "detected_track": timeline_item_track_info(item) if item else None,
        "artifact_count": len(artifact_items),
        "artifact_cleanup": artifact_cleanup,
    }
    result["clear_mark_in_out"] = clear_timeline_mark_in_out(timeline)

    if item is None:
        result["errors"].append("InsertFusionCompositionIntoTimeline created no detectable item.")
        return None, result

    result["name"] = set_timeline_item_name(item, generated_name)
    result["range"] = verify_generated_item_range_readonly(
        item, start_frame, end_frame, target_track
    )
    if not result["range"].get("ok"):
        result["range_write"] = set_timeline_item_range(item, start_frame, end_frame)
        result["range"] = verify_generated_item_range_readonly(
            item, start_frame, end_frame, target_track
        )

    if not result["range"].get("ok"):
        result["rollback_delete"] = delete_timeline_items(timeline, [item])
        result["errors"].append(
            "Fusion Composition did not verify exact target track/start/duration."
        )
        return None, result

    graph = ensure_explicit_textplus_node_on_item(item, generated_name)
    result["textplus_graph"] = graph
    if not graph.get("applied"):
        result["rollback_delete"] = delete_timeline_items(timeline, [item])
        result["errors"].extend(
            graph.get("errors") or ["Fusion Composition has no verified TextPlus node."]
        )
        return None, result

    result["ok"] = True
    hard_debug("CAPTION_TEXTPLUS_FUSION_COMPOSITION_READY", {
        "name": generated_name,
        "target_track": target_track,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "creation": result.get("creation"),
        "range": result.get("range"),
        "textplus_graph": result.get("textplus_graph"),
    })
    return item, result


def provision_textplus_media_carrier(
    project: Any,
    timeline: Any,
    video_items: List[Any],
    start_frame: int,
    end_frame: int,
    target_track: int,
    generated_name: str,
) -> Tuple[Optional[Any], Dict[str, Any]]:
    """Independent V3 backend used when Resolve's title insertion API returns false.

    Resolve 21's InsertFusionTitleIntoTimeline is UI-state dependent and can return
    False even though the exact same timeline accepted it earlier. AppendToTimeline
    with an explicit trackIndex/recordFrame is deterministic in this project and is
    already proven by the V4 backend. The appended video-only carrier is converted
    into a transparent Fusion TextPlus clip by connecting TextPlus directly to
    MediaOut; the original MediaIn remains unused.
    """
    start_frame = max(0, get_int(start_frame, 0))
    end_frame = max(start_frame + 1, get_int(end_frame, start_frame + 1))
    duration = end_frame - start_frame
    result: Dict[str, Any] = {
        "attempted": True,
        "backend": "media_pool_video_carrier_with_fusion_textplus",
        "target_track": target_track,
        "requested_start": start_frame,
        "requested_end": end_frame,
        "requested_duration": duration,
        "generated_name": generated_name,
        "source": None,
        "append": None,
        "graph": None,
        "name": None,
        "range": None,
        "ok": False,
        "errors": [],
    }
    if project is None:
        result["errors"].append("Current Resolve project was not supplied to the TextPlus carrier fallback.")
        return None, result

    source = _find_textplus_carrier_source(video_items, duration)
    result["source"] = {
        k: json_safe_value(v)
        for k, v in source.items()
        if k not in {"source_item", "media_pool_item"}
    }
    if not source.get("ok"):
        result["errors"].append(source.get("error") or "No carrier source was found.")
        return None, result

    clip_row = {
        "media_pool_item": source["media_pool_item"],
        "source_start": source["source_start"],
        "source_end_inclusive": source["source_end_inclusive"],
        "source_end_frame_api": source["source_start"] + duration,
        "api_end_semantics": "exclusive",
        "record_start": start_frame,
        "record_end": end_frame,
        "duration": duration,
    }
    append = _append_media_clip_infos(project, timeline, [clip_row], target_track)
    result["append"] = {
        k: json_safe_value(v)
        for k, v in append.items()
        if k not in {"returned_items", "detected_items"}
    }
    items = list(append.get("detected_items") or append.get("returned_items") or [])
    if not append.get("ok") or len(items) != 1:
        result["errors"].extend(append.get("errors") or ["AppendToTimeline did not return exactly one carrier item."])
        return None, result

    item = items[0]
    result["name"] = set_timeline_item_name(item, generated_name)
    result["range"] = verify_generated_item_range_readonly(item, start_frame, end_frame, target_track)
    if not result["range"].get("ok"):
        result["rollback_delete"] = delete_timeline_items(timeline, [item])
        result["errors"].append("Appended carrier did not verify exact target track/start/duration.")
        return None, result

    result["graph"] = _ensure_textplus_graph_on_carrier(item, generated_name)
    if not (result.get("graph") or {}).get("applied"):
        result["rollback_delete"] = delete_timeline_items(timeline, [item])
        result["errors"].append("Carrier Fusion graph could not be converted to TextPlus-only output.")
        return None, result

    result["ok"] = True
    hard_debug("CAPTION_TEXTPLUS_MEDIA_CARRIER_READY", {
        "name": generated_name,
        "target_track": target_track,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration": duration,
        "append": result.get("append"),
        "graph": result.get("graph"),
    })
    return item, result

def apply_caption_textplus_layer(
    timeline: Any,
    generic: Dict[str, Any],
    video_items: List[Any],
    args: argparse.Namespace,
    fps: float,
    resolve: Any = None,
    project: Any = None,
) -> Dict[str, Any]:
    apply_enabled = bool(getattr(args, "apply_caption_textplus", False))
    verify_enabled = bool(getattr(args, "verify_caption_textplus", False))
    probe_enabled = bool(getattr(args, "caption_textplus_probe_only", False) or getattr(args, "caption_style_probe_only", False) or getattr(args, "caption_shading_probe_only", False))
    mode = "probe" if probe_enabled else ("apply" if apply_enabled and not getattr(args, "dry_run", False) and not getattr(args, "verify_only", False) else "verify")
    caption_track = max(1, get_int(getattr(args, "caption_track", 2), 2))
    requested_textplus_track = max(1, get_int(getattr(args, "caption_textplus_track", caption_track), caption_track))
    requested_static_policy = str(getattr(args, "caption_static_title_policy", "keep") or "keep").lower()
    allow_static_title_item_writes = bool(
        getattr(args, "caption_allow_static_title_item_writes", False)
    )
    # Resolve 21.0.1 can hard-crash when SetProperty is called on imported
    # FCPXML Basic Title items. Unless the user explicitly opts into that unsafe
    # path, downgrade hide/disable/delete to a non-destructive keep policy.
    static_policy = (
        requested_static_policy
        if requested_static_policy == "keep" or allow_static_title_item_writes
        else "keep"
    )
    max_items = max(0, get_int(getattr(args, "max_caption_textplus", 0), 0))
    animation_limit = max(0, get_int(getattr(args, "caption_animation_sample_limit", 0), 0))
    compact_report = bool(getattr(args, "caption_compact_report", True))
    checkpoint_interval = max(0, get_int(getattr(args, "caption_checkpoint_interval", 10), 10))
    stop_on_first_failure = bool(getattr(args, "caption_stop_on_first_failure", True))
    caption_title_name = str(getattr(args, "caption_title_name", "Text+") or "Text+")

    result: Dict[str, Any] = {
        "enabled": bool(apply_enabled or verify_enabled or probe_enabled),
        "mode": mode,
        "caption_track_index": caption_track,
        "textplus_track_index": requested_textplus_track,
        "effective_textplus_track_index": requested_textplus_track,
        "expected_caption_count": 0,
        "static_title_items_seen": 0,
        "cue_map_count": 0,
        "textplus_created_count": 0,
        "textplus_reused_count": 0,
        "textplus_augmented_count": 0,
        "textplus_failed_count": 0,
        "static_title_policy": static_policy,
        "static_title_policy_requested": requested_static_policy,
        "static_title_policy_effective": static_policy,
        "static_title_item_writes_allowed": allow_static_title_item_writes,
        "static_title_write_safety": {
            "guard_active": not allow_static_title_item_writes,
            "reason": (
                None
                if allow_static_title_item_writes
                else "Resolve 21.0.1 native crash observed on imported Basic Title SetProperty"
            ),
        },
        "layering_policy": None,
        "caption_style_report": None,
        "caption_map_diagnostics": None,
        "font_resolution_summary": [],
        "method_availability": {
            "timeline": caption_timeline_method_availability(timeline),
            "can_access_fusion_comp": False,
            "can_add_fusion_comp": False,
            "can_get_tool_list": False,
            "can_set_styled_text": False,
            "can_set_size": False,
            "can_set_center": False,
            "can_set_opacity": False,
        },
        "animation": {
            "enabled": bool(getattr(args, "caption_animation", False)),
            "mode": getattr(args, "caption_animation_mode", "conservative"),
            "input_animation_events": 0,
            "animated_caption_count": 0,
            "static_caption_count": 0,
            "skipped_too_short_count": 0,
            "keyframes_written_count": 0,
            "failed_animation_count": 0,
            "animation_type_counts": {"scale_pop": 0, "scale": 0, "pop_fade": 0, "fade": 0, "slide": 0, "slide_fade": 0, "static": 0},
        },
        "clear_old": None,
        "samples": [],
        "items": [],
        "warnings": [],
        "errors": [],
        "textplus_creation_probe": {"enabled": False, "reason": "probe mode disabled"},
        "full_generation_controls": {
            "compact_report": compact_report,
            "checkpoint_interval": checkpoint_interval,
            "stop_on_first_failure": stop_on_first_failure,
        },
        "checkpoint": None,
    }

    if not result["enabled"]:
        result["reason"] = "--apply-caption-textplus/--verify-caption-textplus not used"
        return result

    hard_debug("CAPTION_TEXTPLUS_START", {
        "mode": mode,
        "caption_track": caption_track,
        "requested_textplus_track": requested_textplus_track,
        "static_policy_requested": requested_static_policy,
        "static_policy_effective": static_policy,
        "static_title_item_writes_allowed": allow_static_title_item_writes,
        "max_items": max_items,
        "caption_animation": getattr(args, "caption_animation", False),
        "caption_textplus_probe_only": getattr(args, "caption_textplus_probe_only", False),
        "caption_probe_count": getattr(args, "caption_probe_count", 1),
        "caption_probe_text": getattr(args, "caption_probe_text", None),
        "caption_probe_cue_id": getattr(args, "caption_probe_cue_id", None),
        "caption_keep_failed_probe_item": getattr(args, "caption_keep_failed_probe_item", False),
        "compact_report": compact_report,
        "checkpoint_interval": checkpoint_interval,
        "stop_on_first_failure": stop_on_first_failure,
    })

    caption_style_report = load_caption_style_report(args, generic)
    caption_style_data = caption_style_report.pop("data", None)
    result["caption_style_report"] = caption_style_report
    style_events_count = len(caption_style_events_list(caption_style_data))
    result["animation"]["input_animation_events"] = style_events_count
    hard_debug("CAPTION_TEXTPLUS_LOAD_INPUTS", {
        "caption_style_loaded": caption_style_report.get("loaded"),
        "caption_style_path": caption_style_report.get("path"),
        "style_events_count": style_events_count,
        "subtitle_clips_count": len(generic.get("subtitle_clips") or []),
    })

    try:
        cue_map, map_diag, static_items = build_caption_textplus_cue_map(timeline, generic, caption_style_data, args, fps)
        result["caption_map_diagnostics"] = map_diag
        result["expected_caption_count"] = get_int(map_diag.get("expected_count"), 0)
        result["static_title_items_seen"] = get_int(map_diag.get("title_like_items_seen"), 0)
        result["cue_map_count"] = len(cue_map)
        hard_debug("CAPTION_TEXTPLUS_TRACK_SCAN", map_diag)
        first_cue = cue_map[0] if cue_map else None
        hard_debug("CAPTION_TEXTPLUS_CUE_MAP_BUILT", {
            "cue_map_count": len(cue_map),
            "first": (
                {
                    "cue_id": first_cue.get("cue_id"),
                    "cue_index": first_cue.get("cue_index"),
                    "text": first_cue.get("text"),
                    "start_frame": first_cue.get("start_frame"),
                    "end_frame": first_cue.get("end_frame"),
                    "duration_frames": first_cue.get("duration_frames"),
                    "mapped_static_title": first_cue.get("mapped_static_title"),
                    "style_event_id": ((first_cue.get("style_event") or {}).get("event_id")),
                }
                if first_cue
                else None
            ),
        })

        if not cue_map:
            result["errors"].append("No caption cues could be built from generic_edit_commands.subtitle_clips.")
            return result
        if result["static_title_items_seen"] == 0:
            result["warnings"].append("No imported static title items were seen on the caption track; overlay can still use generic cue timing, but V2 anchor verification failed.")

        # Probe the first static item for in-place control capability without changing it.
        first_static = static_items[0] if static_items else None
        if first_static:
            probe_record = actual_caption_item_record(first_static, 1, fps, caption_title_name=caption_title_name)
            probe = inspect_caption_property_access(first_static, probe_record, write_test=False)
            result["method_availability"]["static_item_probe"] = probe
            result["method_availability"]["can_access_fusion_comp"] = bool(probe.get("can_access_fusion_comp"))
            result["method_availability"]["can_get_tool_list"] = bool((probe.get("comp_methods") or {}).get("GetToolList"))
            result["method_availability"]["can_add_fusion_comp"] = method_available(first_static, "AddFusionComp")
        hard_debug("CAPTION_TEXTPLUS_METHOD_PROBE", result["method_availability"])

        # Avoid overlaying on top of static titles on the same track while policy is keep.
        effective_track = requested_textplus_track
        overlay_requires_separate_track = static_policy == "keep" and requested_textplus_track == caption_track
        if overlay_requires_separate_track:
            effective_track = caption_track + 1
            result["effective_textplus_track_index"] = effective_track
            result["layering_policy"] = {
                "requested": "V1 base, V2 animated captions, V3 future foreground matte",
                "effective": f"V1 base, V{caption_track} static FCPXML captions/reference, V{effective_track} generated animated Text+, V{effective_track + 1} future foreground matte",
                "reason": "Static title policy is keep and overlay creation on the same caption track would risk collisions/duplicates.",
            }
            result["warnings"].append(f"Requested Text+ track V{requested_textplus_track} conflicts with kept static captions on V{caption_track}; overlay fallback will use V{effective_track}.")
        else:
            result["layering_policy"] = {
                "effective": f"V1 base, V{effective_track} animated Text+ captions, V{effective_track + 1} future foreground matte",
                "reason": "Requested Text+ track is usable for generated captions under current static-title policy.",
            }

        desired_track_name = str(getattr(args, "caption_textplus_track_name", "VC_TEXTPLUS_V3") or "VC_TEXTPLUS_V3")
        track_resolution = resolve_or_create_named_video_track(
            timeline=timeline,
            requested_index=effective_track,
            desired_name=desired_track_name,
            generated_prefix=VC_CAPTION_TEXTPLUS_PREFIX,
        )
        effective_track = max(1, get_int(track_resolution.get("track_index"), effective_track))
        args.caption_textplus_track = effective_track
        result["effective_textplus_track_index"] = effective_track
        result["track_resolution"] = track_resolution
        result["layering_policy"]["resolved_track_name"] = track_resolution.get("track_name")
        result["layering_policy"]["resolved_track_index"] = effective_track

        if resolve is not None:
            result["edit_page"] = {
                "before": safe_call(resolve, "GetCurrentPage", default=None),
                "open_result": json_safe_value(safe_call(resolve, "OpenPage", "edit", default=None)),
                "after": safe_call(resolve, "GetCurrentPage", default=None),
            }

        items_to_process = cue_map[:max_items] if max_items > 0 else cue_map
        result["requested_process_count"] = len(items_to_process)

        if probe_enabled:
            probe_result = run_textplus_creation_probe(
                resolve=resolve,
                timeline=timeline,
                generic=generic,
                cue_map=cue_map,
                caption_style_data=caption_style_data,
                args=args,
                fps=fps,
                target_track=effective_track,
                caption_track=caption_track,
            )
            result["textplus_creation_probe"] = probe_result
            result["font_resolution_summary"] = probe_result.get("font_resolution_summary") or []
            result["requested_process_count"] = get_int(probe_result.get("probe_count"), 1)
            result["textplus_created_count"] = get_int(probe_result.get("created_count"), 0)
            result["textplus_failed_count"] = get_int(probe_result.get("failed_count"), 0)
            result["items"] = probe_result.get("probes") or []
            result["clear_old"] = probe_result.get("clear_old")
            result["track_setup"] = probe_result.get("track_setup")
            result["track_guard"] = probe_result.get("track_guard")
            result["track_guard_restore"] = probe_result.get("track_guard_restore")
            result["core_tracks_before"] = probe_result.get("core_tracks_before")
            result["core_tracks_after"] = probe_result.get("core_tracks_after")
            result["core_track_integrity"] = probe_result.get("core_track_integrity")
            result["animation"]["keyframes_written_count"] = get_int(probe_result.get("keyframes_written"), 0)
            result["animation"]["animated_caption_count"] = sum(
                1 for row in (probe_result.get("probes") or [])
                if get_int((row.get("animation_write") or {}).get("keyframes_written"), 0) > 0
            )
            result["samples"] = [
                {
                    "cue_id": row.get("cue_id"),
                    "text": row.get("text"),
                    "created_item_detected": row.get("created_item_detected"),
                    "created_new_item": row.get("created_new_item"),
                    "track_ok": row.get("track_ok"),
                    "range_ok": row.get("range_ok"),
                    "kept_item": row.get("kept_item"),
                    "deleted_item": row.get("deleted_item"),
                    "fusion_access": row.get("fusion_access"),
                    "style_write": row.get("style_write"),
                    "animation_write": row.get("animation_write"),
                    "warnings": row.get("warnings") or [],
                    "errors": row.get("errors") or [],
                }
                for row in (probe_result.get("probes") or [])
            ]
            if probe_result.get("recommendation"):
                result["warnings"].append(probe_result.get("recommendation"))
            return result

        if mode == "verify":
            # Verification stops before creating or modifying any timeline item.
            sample_count = min(len(items_to_process), 20 if max_items == 0 else len(items_to_process))
            for cue_row in items_to_process[:sample_count]:
                sample_style = normalize_caption_textplus_style(generic, caption_style_data, cue_row.get("style_event_raw"))
                sample_style, font_resolution = prepare_caption_runtime_style(resolve, sample_style, args)
                result["font_resolution_summary"].append(font_resolution)
                result["samples"].append({
                    "cue_id": cue_row.get("cue_id"),
                    "text": cue_row.get("text"),
                    "start_frame": cue_row.get("start_frame"),
                    "end_frame": cue_row.get("end_frame"),
                    "duration_frames": cue_row.get("duration_frames"),
                    "mapped_static_title": cue_row.get("mapped_static_title"),
                    "textplus_ready": False,
                    "animation_type": (cue_row.get("animation") or {}).get("type"),
                    "resolved_style": {
                        "text_color": sample_style.get("text_color"),
                        "stroke_color": sample_style.get("stroke_color"),
                        "size": sample_style.get("textplus_size"),
                        "center": sample_style.get("center"),
                        "style_event_id": sample_style.get("style_event_id"),
                        "font_resolution": font_resolution,
                        "size_resolution": sample_style.get("size_resolution"),
                    },
                    "warnings": ["verify mode: no write attempted"],
                })
            return result

        if static_policy in {"hide", "disable"} and bool(getattr(args, "caption_restore_static_titles_before_apply", True)):
            result["static_title_restore_before_apply"] = restore_static_title_visibility(
                static_items[:len(items_to_process)],
                allow_item_writes=allow_static_title_item_writes,
            )
        else:
            result["static_title_restore_before_apply"] = {
                "attempted": False,
                "reason": "restore disabled or static policy keeps references visible",
            }

        result["track_setup"] = ensure_video_track(timeline, effective_track)
        if getattr(args, "clear_old_vc_textplus", False):
            result["clear_old"] = clear_old_caption_textplus_items(
                timeline,
                target_track=effective_track,
                aggressive_dedicated_track=bool(getattr(args, "caption_recovery_clean_target_track", True)),
            )
        else:
            result["clear_old"] = {"attempted": False, "reason": "--clear-old-vc-textplus not used"}

        track_guard = apply_subtitle_track_guard(timeline, effective_track)
        result["track_guard"] = track_guard
        core_before = snapshot_core_tracks(timeline, get_int(getattr(args, "video_track", 1), 1), get_int(getattr(args, "audio_track", 1), 1))
        result["core_tracks_before"] = core_before

        # Resolve's native title insertion backend is UI-state dependent. Try it
        # for the first missing item; if it returns no item, switch the rest of
        # this run to the explicit media-carrier Fusion backend.
        native_title_backend_enabled = True

        try:
            for cue_row in items_to_process:
                cue_index = get_int(cue_row.get("cue_index"), len(result["items"]) + 1)
                cue_id = cue_row.get("cue_id") or f"sub_{cue_index:04d}"
                start_frame = get_int(cue_row.get("start_frame"), 0)
                end_frame = max(start_frame + 1, get_int(cue_row.get("end_frame"), start_frame + 1))
                duration = max(1, end_frame - start_frame)
                style = normalize_caption_textplus_style(generic, caption_style_data, cue_row.get("style_event_raw"))
                style, font_resolution = prepare_caption_runtime_style(resolve, style, args)
                result["font_resolution_summary"].append(font_resolution)
                anim_type = (cue_row.get("animation") or {}).get("type") or "static"
                result["animation"]["animation_type_counts"][anim_type] = get_int(result["animation"]["animation_type_counts"].get(anim_type), 0) + 1

                item_result: Dict[str, Any] = {
                    "cue_id": cue_id,
                    "cue_index": cue_index,
                    "text": cue_row.get("text"),
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "duration_frames": duration,
                    "mapped_static_title": cue_row.get("mapped_static_title"),
                    "style_event_id": style.get("style_event_id"),
                    "font_resolution": json_safe_value(font_resolution),
                    "size_resolution": json_safe_value(style.get("size_resolution")),
                    "color_resolution": json_safe_value(style.get("color_resolution")),
                    "animation_type": anim_type,
                    "textplus_ready": False,
                    "keyframes_written": 0,
                    "warnings": [],
                    "errors": [],
                }

                # 1) In-place path: only if the imported static title already exposes a Text+ tool,
                # unless --caption-write-test explicitly allows adding a Fusion comp to the static item.
                static_item = None
                static_record = cue_row.get("source_static_title_item")
                if static_record:
                    static_idx = get_int(static_record.get("index"), cue_index) - 1
                    if 0 <= static_idx < len(static_items):
                        static_item = static_items[static_idx]

                if static_item is not None:
                    comp, text_tool, in_place_info = get_or_create_existing_title_text_tool(
                        static_item,
                        allow_add_fusion_comp=bool(getattr(args, "caption_write_test", False)),
                    )
                    item_result["in_place_probe"] = in_place_info
                    if comp and text_tool:
                        style_apply = set_caption_textplus_style_inputs(text_tool, cue_row, style, cue_index, args=args, comp=comp)
                        item_result["in_place_style"] = style_apply
                        if style_apply.get("applied"):
                            result["textplus_augmented_count"] += 1
                            item_result["textplus_ready"] = True
                            item_result["provisioning_path"] = "in_place_static_title_fusion_text_tool"
                            result["method_availability"]["can_set_styled_text"] = result["method_availability"]["can_set_styled_text"] or bool((style_apply.get("inputs") or {}).get("StyledText", {}).get("ok") or (style_apply.get("inputs") or {}).get("InputStyledText", {}).get("ok"))
                            result["method_availability"]["can_set_size"] = result["method_availability"]["can_set_size"] or bool((style_apply.get("inputs") or {}).get("Size", {}).get("ok"))
                            result["method_availability"]["can_set_center"] = result["method_availability"]["can_set_center"] or bool((style_apply.get("inputs") or {}).get("Center", {}).get("ok"))
                            result["method_availability"]["can_set_opacity"] = result["method_availability"]["can_set_opacity"] or bool((style_apply.get("inputs") or {}).get("Blend", {}).get("ok") or (style_apply.get("inputs") or {}).get("Opacity", {}).get("ok"))

                            if getattr(args, "caption_animation", False):
                                hard_debug("CAPTION_ANIMATION_START", {"cue_id": cue_id, "path": "in_place", "animation_type": anim_type})
                                anim = apply_caption_animation_to_text_tool(text_tool, cue_row, style, cue_row.get("style_event_raw"), args)
                                item_result["animation"] = anim
                                item_result["keyframes_written"] = get_int(anim.get("keyframes_written"), 0)
                                result["animation"]["keyframes_written_count"] += item_result["keyframes_written"]
                                if anim.get("applied"):
                                    result["animation"]["animated_caption_count"] += 1
                                elif "skipped_too_short" in (anim.get("warnings") or []):
                                    result["animation"]["skipped_too_short_count"] += 1
                                elif anim_type == "static":
                                    result["animation"]["static_caption_count"] += 1
                                else:
                                    result["animation"]["failed_animation_count"] += 1
                            result["items"].append(item_result)
                            hard_debug("CAPTION_TEXTPLUS_ITEM_READY", {"cue_id": cue_id, "path": "in_place", "keyframes_written": item_result.get("keyframes_written")})
                            hard_debug("CAPTION_TEXTPLUS_STYLE_APPLIED", {"cue_id": cue_id, "path": "in_place", "applied": True})
                            hard_debug("CAPTION_ANIMATION_ITEM_DONE", {"cue_id": cue_id, "keyframes_written": item_result.get("keyframes_written")})
                            continue
                    else:
                        item_result["warnings"].append("Imported static title did not expose a controllable Text+/Fusion text tool; using overlay fallback if possible.")

                # 2) Overlay path.
                existing_item, existing_diag = find_existing_caption_textplus_item(
                    timeline=timeline,
                    target_track=effective_track,
                    cue_index=cue_index,
                    cue_id=cue_id,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    caption_track=caption_track,
                    allow_range_fallback=False,
                )
                item_result["existing_lookup"] = existing_diag
                text_item = existing_item
                if text_item:
                    result["textplus_reused_count"] += 1
                    item_result["provisioning_path"] = "reused_overlay_textplus"
                else:
                    hard_debug("CAPTION_TEXTPLUS_ITEM_CREATE_ATTEMPT", {"cue_id": cue_id, "track": effective_track, "start_frame": start_frame, "end_frame": end_frame, "native_backend_enabled": native_title_backend_enabled})
                    wanted_name = generated_caption_item_name(cue_index, cue_id)

                    # Preferred path: create an empty Fusion Composition, then add
                    # and read back a real TextPlus node explicitly.
                    text_item, composition_result = provision_textplus_fusion_composition(
                        timeline=timeline,
                        start_frame=start_frame,
                        end_frame=end_frame,
                        fps=fps,
                        target_track=effective_track,
                        generated_name=wanted_name,
                    )
                    item_result["fusion_composition_backend"] = composition_result
                    composition_used = text_item is not None

                    # Secondary path: Fusion title/template insertion.
                    if text_item is None and native_title_backend_enabled:
                        text_item, insert_result = probe_title_creation_methods(
                            timeline=timeline,
                            start_frame=start_frame,
                            end_frame=end_frame,
                            fps=fps,
                            title_name=caption_title_name,
                            target_track=effective_track,
                            detailed_diagnostics=not compact_report,
                        )
                    elif text_item is None:
                        insert_result = {
                            "attempted": False,
                            "skipped": True,
                            "reason": "native_title_backend_disabled_after_first_no_item_result",
                            "target_track": effective_track,
                            "requested_start": start_frame,
                            "requested_end": end_frame,
                        }
                    else:
                        insert_result = {
                            "created_item_detected": True,
                            "skipped": True,
                            "reason": "explicit_fusion_composition_backend_succeeded",
                            "insert_method": "InsertFusionCompositionIntoTimeline",
                            "target_track": effective_track,
                            "requested_start": start_frame,
                            "requested_end": end_frame,
                        }
                    item_result["insert"] = insert_result

                    # Last fallback: append a media carrier and replace its Fusion
                    # output with a verified TextPlus-only graph.
                    carrier_used = False
                    if not text_item:
                        carrier_item, carrier_result = provision_textplus_media_carrier(
                            project=project,
                            timeline=timeline,
                            video_items=video_items,
                            start_frame=start_frame,
                            end_frame=end_frame,
                            target_track=effective_track,
                            generated_name=wanted_name,
                        )
                        item_result["media_carrier_fallback"] = carrier_result
                        if carrier_item is not None:
                            text_item = carrier_item
                            carrier_used = True
                            if native_title_backend_enabled and not insert_result.get("created_item_detected"):
                                native_title_backend_enabled = False
                                result["warnings"].append(
                                    "Resolve title insertion returned no item; switched remaining captions to explicit Fusion backends."
                                )
                                hard_debug("CAPTION_TEXTPLUS_NATIVE_BACKEND_DISABLED", {
                                    "after_cue_id": cue_id,
                                    "replacement_backend": "media_pool_video_carrier_with_fusion_textplus",
                                })

                    if text_item:
                        result["textplus_created_count"] += 1
                        item_result["provisioning_path"] = (
                            "fusion_composition_explicit_textplus"
                            if composition_used
                            else (
                                "media_carrier_fusion_textplus"
                                if carrier_used
                                else "created_overlay_textplus"
                            )
                        )
                    else:
                        item_result["errors"].append(
                            "Resolve native title insertion failed and the explicit media-carrier Fusion TextPlus fallback also failed."
                        )
                        result["textplus_failed_count"] += 1
                        result["items"].append(item_result)
                        if stop_on_first_failure:
                            result["checkpoint"] = write_caption_generation_checkpoint(
                                args, result, len(result.get("items") or []), len(items_to_process), item_result, status="failed"
                            )
                            break
                        continue

                wanted_name = generated_caption_item_name(cue_index, cue_id)
                item_result["name"] = set_timeline_item_name(text_item, wanted_name)
                item_result["track"] = timeline_item_track_info(text_item)
                if item_result.get("provisioning_path") in {
                    "media_carrier_fusion_textplus",
                    "fusion_composition_explicit_textplus",
                }:
                    item_result["range"] = verify_generated_item_range_readonly(
                        text_item, start_frame, end_frame, effective_track
                    )
                else:
                    item_result["range"] = set_timeline_item_range(text_item, start_frame, end_frame)
                track_ok = (item_result.get("track") or {}).get("track_type") == "video" and get_int((item_result.get("track") or {}).get("track_index"), 0) == effective_track
                range_ok = bool((item_result.get("range") or {}).get("ok"))
                item_result["track_ok"] = bool(track_ok)
                item_result["range_ok"] = bool(range_ok)
                if not track_ok or not range_ok:
                    item_result["warnings"].append("Inserted/reused Text+ item did not verify exact requested track/range. It was kept only if reused; newly created bad items are deleted.")
                    if not existing_item:
                        item_result["rollback_delete"] = delete_timeline_items(timeline, [text_item])
                        result["textplus_failed_count"] += 1
                        result["items"].append(item_result)
                        if stop_on_first_failure:
                            result["checkpoint"] = write_caption_generation_checkpoint(
                                args, result, len(result.get("items") or []), len(items_to_process), item_result, status="failed"
                            )
                            break
                        continue

                item_result["explicit_textplus_node"] = ensure_explicit_textplus_node_on_item(
                    text_item, wanted_name
                )
                comp, text_tool, tool_info = get_or_create_existing_title_text_tool(
                    text_item, allow_add_fusion_comp=False
                )
                item_result["overlay_text_tool"] = tool_info
                item_result["textplus_node_verified"] = bool(
                    (item_result.get("explicit_textplus_node") or {}).get("textplus_verified")
                    and text_tool is not None
                )
                if not comp or not text_tool:
                    item_result["errors"].append("Timeline item exists, but explicit TextPlus node creation/readback failed.")
                    if not existing_item:
                        item_result["rollback_delete"] = delete_timeline_items(timeline, [text_item])
                    result["textplus_failed_count"] += 1
                    result["items"].append(item_result)
                    if stop_on_first_failure:
                        result["checkpoint"] = write_caption_generation_checkpoint(
                            args, result, len(result.get("items") or []), len(items_to_process), item_result, status="failed"
                        )
                        break
                    continue

                style_apply = set_caption_textplus_style_inputs(text_tool, cue_row, style, cue_index, args=args, comp=comp)
                item_result["overlay_style"] = style_apply
                result["method_availability"]["can_access_fusion_comp"] = True
                result["method_availability"]["can_get_tool_list"] = True
                result["method_availability"]["can_set_styled_text"] = result["method_availability"]["can_set_styled_text"] or bool((style_apply.get("inputs") or {}).get("StyledText", {}).get("ok") or (style_apply.get("inputs") or {}).get("InputStyledText", {}).get("ok"))
                result["method_availability"]["can_set_size"] = result["method_availability"]["can_set_size"] or bool((style_apply.get("inputs") or {}).get("Size", {}).get("ok"))
                result["method_availability"]["can_set_center"] = result["method_availability"]["can_set_center"] or bool((style_apply.get("inputs") or {}).get("Center", {}).get("ok"))
                result["method_availability"]["can_set_opacity"] = result["method_availability"]["can_set_opacity"] or bool((style_apply.get("inputs") or {}).get("Blend", {}).get("ok") or (style_apply.get("inputs") or {}).get("Opacity", {}).get("ok"))

                if style_apply.get("applied"):
                    item_result["textplus_ready"] = True
                    hard_debug("CAPTION_TEXTPLUS_STYLE_APPLIED", {"cue_id": cue_id, "path": item_result.get("provisioning_path"), "applied": True})
                else:
                    item_result["errors"].append("Text+ required style/text inputs did not pass write/readback verification.")
                    if not existing_item:
                        item_result["rollback_delete"] = delete_timeline_items(timeline, [text_item])
                    result["textplus_failed_count"] += 1
                    result["items"].append(item_result)
                    if stop_on_first_failure:
                        result["checkpoint"] = write_caption_generation_checkpoint(
                            args, result, len(result.get("items") or []), len(items_to_process), item_result, status="failed"
                        )
                        break
                    continue

                if item_result.get("textplus_ready") and getattr(args, "caption_animation", False):
                    hard_debug("CAPTION_ANIMATION_START", {"cue_id": cue_id, "path": item_result.get("provisioning_path"), "animation_type": anim_type})
                    anim = apply_caption_animation_to_text_tool(text_tool, cue_row, style, cue_row.get("style_event_raw"), args)
                    item_result["animation"] = anim
                    item_result["keyframes_written"] = get_int(anim.get("keyframes_written"), 0)
                    result["animation"]["keyframes_written_count"] += item_result["keyframes_written"]
                    if anim.get("applied"):
                        result["animation"]["animated_caption_count"] += 1
                    elif "skipped_too_short" in (anim.get("warnings") or []):
                        result["animation"]["skipped_too_short_count"] += 1
                    elif anim_type == "static":
                        result["animation"]["static_caption_count"] += 1
                    else:
                        result["animation"]["failed_animation_count"] += 1

                if not item_result.get("textplus_ready") and not item_result.get("errors"):
                    result["textplus_failed_count"] += 1

                result["items"].append(item_result)
                processed_count = len(result.get("items") or [])
                hard_debug("CAPTION_TEXTPLUS_ITEM_READY", {
                    "cue_id": cue_id,
                    "processed_count": processed_count,
                    "total_count": len(items_to_process),
                    "path": item_result.get("provisioning_path"),
                    "ready": item_result.get("textplus_ready"),
                    "keyframes_written": item_result.get("keyframes_written"),
                })
                hard_debug("CAPTION_ANIMATION_ITEM_DONE", {"cue_id": cue_id, "keyframes_written": item_result.get("keyframes_written")})
                if checkpoint_interval > 0 and (processed_count % checkpoint_interval == 0 or processed_count == len(items_to_process)):
                    result["checkpoint"] = write_caption_generation_checkpoint(
                        args=args,
                        result=result,
                        processed_count=processed_count,
                        total_count=len(items_to_process),
                        last_item=item_result,
                        status="running" if processed_count < len(items_to_process) else "items_processed",
                    )
                if stop_on_first_failure and not item_result.get("textplus_ready"):
                    result["warnings"].append(
                        f"Stopped full caption generation after first failed cue: {cue_id}. Existing V2 references remain visible."
                    )
                    break
                if animation_limit > 0 and result["animation"]["animated_caption_count"] >= animation_limit:
                    result["warnings"].append(f"Stopped animation after --caption-animation-sample-limit={animation_limit} animated captions.")
                    # Continue styling existing items would defeat sample mode; stop the test batch.
                    break

        finally:
            result["track_guard_restore"] = restore_track_locks(timeline, track_guard)
            core_after = snapshot_core_tracks(timeline, get_int(getattr(args, "video_track", 1), 1), get_int(getattr(args, "audio_track", 1), 1))
            result["core_tracks_after"] = core_after
            result["core_track_integrity"] = compare_core_track_snapshots(core_before, core_after)
            if not result["core_track_integrity"].get("ok"):
                result["warnings"].append("Core video/audio track ranges changed during caption Text+ insertion. Inspect core_track_integrity immediately.")

        ready_count = sum(1 for row in result.get("items") or [] if row.get("textplus_ready"))

        def _production_style_row(item_row: Dict[str, Any]) -> Dict[str, Any]:
            return (
                item_row.get("overlay_style")
                or item_row.get("in_place_style")
                or {}
            )

        production_rows = result.get("items") or []
        requested_count = len(items_to_process)
        animation_requested = bool(getattr(args, "caption_animation", False))
        all_track_ok = all(bool(row.get("track_ok", row.get("provisioning_path") == "in_place_static_title_fusion_text_tool")) for row in production_rows) if production_rows else False
        all_range_ok = all(bool(row.get("range_ok", row.get("provisioning_path") == "in_place_static_title_fusion_text_tool")) for row in production_rows) if production_rows else False
        all_text_ok = all(bool(_production_style_row(row).get("required_text_ok")) for row in production_rows) if production_rows else False
        all_font_ok = all(
            bool(_production_style_row(row).get("font_family_ok"))
            and bool(_production_style_row(row).get("font_style_ok"))
            for row in production_rows
        ) if production_rows else False
        all_size_ok = all(bool(_production_style_row(row).get("size_ok")) for row in production_rows) if production_rows else False
        all_color_ok = all(bool(_production_style_row(row).get("color_ok")) for row in production_rows) if production_rows else False
        all_position_ok = all(bool(_production_style_row(row).get("position_ok")) for row in production_rows) if production_rows else False
        def _animation_row_ok(row: Dict[str, Any]) -> bool:
            if not animation_requested:
                return True
            animation_type = str(row.get("animation_type") or "static").lower()
            duration_frames = get_int(row.get("duration_frames"), 0)
            if animation_type == "static" or duration_frames < 3:
                return True
            expected_keyframes = 2 if animation_type in {"scale", "fade", "slide", "slide_fade"} else 3
            return get_int(row.get("keyframes_written"), 0) >= expected_keyframes

        all_animation_ok = all(_animation_row_ok(row) for row in production_rows) if production_rows else False
        core_integrity_ok = bool((result.get("core_track_integrity") or {}).get("ok"))

        target_track_coverage = verify_caption_textplus_track_coverage(
            timeline=timeline,
            track_index=effective_track,
            generic=generic,
            fps=fps,
            tolerance_frames=max(1, get_int(getattr(args, "caption_timing_tolerance_frames", 2), 2)),
        )
        result["target_track_coverage"] = target_track_coverage
        full_contract_requested = bool(requested_count == get_int(result.get("expected_caption_count"), requested_count))
        target_coverage_ok = bool(target_track_coverage.get("coverage_ok")) if full_contract_requested else bool(ready_count == requested_count)

        result["production_batch_integrity"] = {
            "mode": "normal_applier",
            "requested_count": requested_count,
            "item_result_count": len(production_rows),
            "ready_count": ready_count,
            "failed_count": result.get("textplus_failed_count"),
            "all_track_ok": all_track_ok,
            "all_range_ok": all_range_ok,
            "all_text_ok": all_text_ok,
            "all_font_ok": all_font_ok,
            "all_size_ok": all_size_ok,
            "all_color_write_ok": all_color_ok,
            "all_position_ok": all_position_ok,
            "animation_requested": animation_requested,
            "all_animation_ok": all_animation_ok,
            "keyframes_written": get_int((result.get("animation") or {}).get("keyframes_written_count"), 0),
            "outline_requested": bool(getattr(args, "caption_apply_outline", False)),
            "shadow_requested": bool(getattr(args, "caption_apply_shadow", False)),
            "core_track_integrity_ok": core_integrity_ok,
            "target_track_name": target_track_coverage.get("track_name"),
            "target_track_index": effective_track,
            "target_track_candidate_count": target_track_coverage.get("candidate_title_count"),
            "target_track_matched_count": target_track_coverage.get("matched_count"),
            "target_track_extra_count": target_track_coverage.get("extra_candidate_count"),
            "target_track_coverage_ok": target_coverage_ok,
            "ok": bool(
                requested_count > 0
                and len(production_rows) == requested_count
                and ready_count == requested_count
                and get_int(result.get("textplus_failed_count"), 0) == 0
                and all_track_ok
                and all_range_ok
                and all_text_ok
                and all_font_ok
                and all_size_ok
                and all_color_ok
                and all_position_ok
                and all_animation_ok
                and core_integrity_ok
                and target_coverage_ok
            ),
        }
        def _replacement_row_verified(row: Dict[str, Any]) -> bool:
            style_row = _production_style_row(row)
            base_ok = bool(
                row.get("textplus_ready")
                and row.get("track_ok", row.get("provisioning_path") == "in_place_static_title_fusion_text_tool")
                and row.get("range_ok", row.get("provisioning_path") == "in_place_static_title_fusion_text_tool")
                and style_row.get("required_text_ok")
                and style_row.get("font_family_ok")
                and style_row.get("font_style_ok")
                and style_row.get("size_ok")
                and style_row.get("color_ok")
                and style_row.get("position_ok")
            )
            animation_ok = _animation_row_ok(row)
            return bool(base_ok and animation_ok)

        replacement_verified_count = sum(1 for row in production_rows if _replacement_row_verified(row))
        result["static_title_policy_result"] = apply_static_title_policy_to_items(
            timeline=timeline,
            static_items=static_items[:len(items_to_process)],
            policy=static_policy,
            replacement_ready_count=replacement_verified_count,
            target_count=len(items_to_process),
            allow_item_writes=allow_static_title_item_writes,
        )
        static_policy_ok = bool((result.get("static_title_policy_result") or {}).get("all_ok"))
        result["production_batch_integrity"]["static_title_policy"] = static_policy
        result["production_batch_integrity"]["static_title_policy_ok"] = static_policy_ok
        result["production_batch_integrity"]["static_titles_hidden_count"] = get_int(
            (result.get("static_title_policy_result") or {}).get("hidden_count"), 0
        )
        result["production_batch_integrity"]["replacement_coverage_count"] = replacement_verified_count
        result["production_batch_integrity"]["ok"] = bool(
            result["production_batch_integrity"].get("ok") and static_policy_ok
        )

        result["checkpoint"] = write_caption_generation_checkpoint(
            args=args,
            result=result,
            processed_count=len(production_rows),
            total_count=requested_count,
            last_item=production_rows[-1] if production_rows else None,
            status="complete" if result["production_batch_integrity"].get("ok") else "incomplete",
        )

        result["milestone_status"] = {
            "sequence_step": 8,
            "milestone": "full_116_caption_v3_generation",
            "probe_mode": False,
            "current_test_caption_count": len(items_to_process),
            "full_generation_requested": len(items_to_process) == len(cue_map),
            "current_test_includes_sub_006_19": any(
                str(row.get("cue_id")) == "sub_006" for row in production_rows
            ),
            "completed_or_proven": [
                "Text+ provisioning on V3",
                "exact word-level timing",
                "installed font fallback resolution",
                "automatic Text+ size calibration",
                "OCR-to-Fusion position conversion",
                "per-cue style-event selection",
                "scale-pop keyframe writing",
                "V1/A1 integrity guard",
                "native Resolve crash isolated to imported V2 Basic Title item writes",
                "hard safety guard blocks V2 item SetProperty writes by default",
                "low-confidence renderer color fallback reporting",
            ],
            "deferred_controller_features": [
                "verified Text+ outline",
                "verified Text+ shadow",
                "safe V2 visibility replacement strategy (track-level only, on duplicate timeline)",
                "V4 foreground matte/occlusion",
            ],
            "known_upstream_fidelity_issues": [
                {
                    "layer": "resolve_static_title_visibility",
                    "observed": "TimelineItem.SetProperty on imported FCPXML Basic Titles caused repeatable native Resolve 21.0.1 crashes",
                    "mitigation": "V2 item writes hard-disabled; references remain visible during partial replacement tests",
                    "fully_fixed_upstream": False,
                },
                {
                    "layer": "caption_color_detection",
                    "observed": "detector fill can be gray while source text appears black",
                    "mitigation": "opt-in darkest text component fallback on low-confidence style events",
                    "fully_fixed_upstream": False,
                },
                {
                    "layer": "caption_text/transcription",
                    "observed": "source says 'nineteen' while subtitle contract supplies '19.'",
                    "fully_fixed_upstream": False,
                },
                {
                    "layer": "font_detection",
                    "observed": "true original font family remains unknown; Resolve uses verified fallback mapping",
                    "fully_fixed_upstream": False,
                },
            ],
        }

        # Keep report readable; full item diagnostics remain in debug log if needed.
        sample_limit = min(len(result.get("items") or []), 20 if max_items == 0 else len(result.get("items") or []))
        for row in (result.get("items") or [])[:sample_limit]:
            result["samples"].append({
                "cue_id": row.get("cue_id"),
                "text": row.get("text"),
                "start_frame": row.get("start_frame"),
                "end_frame": row.get("end_frame"),
                "duration_frames": row.get("duration_frames"),
                "mapped_static_title": row.get("mapped_static_title"),
                "textplus_ready": row.get("textplus_ready"),
                "provisioning_path": row.get("provisioning_path"),
                "animation_type": row.get("animation_type"),
                "keyframes_written": row.get("keyframes_written"),
                "warnings": row.get("warnings") or [],
                "errors": row.get("errors") or [],
            })

    except Exception as exc:
        result["errors"].append(compact_exception(exc))
        result["traceback"] = traceback.format_exc()
        hard_debug("CAPTION_TEXTPLUS_EXCEPTION", {"error": compact_exception(exc), "traceback": traceback.format_exc()})

    if compact_report and mode == "apply":
        production_rows_for_report = result.get("items") or []
        result["items"] = [compact_caption_item_result(row) for row in production_rows_for_report]
        unique_fonts: List[Dict[str, Any]] = []
        seen_fonts = set()
        for row in result.get("font_resolution_summary") or []:
            compact_font = compact_font_resolution_record(row)
            key = json.dumps(compact_font, sort_keys=True, ensure_ascii=False)
            if key not in seen_fonts:
                seen_fonts.add(key)
                unique_fonts.append(compact_font)
        result["font_resolution_summary"] = unique_fonts
        result["report_compaction"] = {
            "enabled": True,
            "item_count": len(result.get("items") or []),
            "unique_font_resolution_count": len(unique_fonts),
            "reason": "full-caption production report omits repeated Fusion inventories and before/after track snapshots",
        }

    hard_debug("CAPTION_TEXTPLUS_DONE", {
        "mode": result.get("mode"),
        "expected_caption_count": result.get("expected_caption_count"),
        "static_title_items_seen": result.get("static_title_items_seen"),
        "cue_map_count": result.get("cue_map_count"),
        "created": result.get("textplus_created_count"),
        "reused": result.get("textplus_reused_count"),
        "augmented": result.get("textplus_augmented_count"),
        "failed": result.get("textplus_failed_count"),
        "keyframes": (result.get("animation") or {}).get("keyframes_written_count"),
        "warnings": result.get("warnings"),
        "errors": result.get("errors"),
    })
    return result



def discover_occlusion_analysis_path(generic_path: Optional[str], explicit_path: Optional[str]) -> Optional[str]:
    if explicit_path:
        p = Path(explicit_path)
        return str(p.resolve()) if p.exists() else str(p)
    if not generic_path:
        return None
    gp = Path(generic_path)
    video_id = gp.name.replace("_generic_edit_commands.json", "")
    candidates = [
        gp.parent.parent / "analysis" / f"{video_id}_analysis.json",
        gp.parent / f"{video_id}_analysis.json",
    ]
    for p in candidates:
        if p.exists():
            return str(p.resolve())
    return str(candidates[0])


def _collect_occlusion_event_dicts(value: Any, out: List[Dict[str, Any]], seen: set) -> None:
    if isinstance(value, dict):
        cue_id = value.get("cue_id") or value.get("caption_id")
        occ = value.get("occlusion") if isinstance(value.get("occlusion"), dict) else {}
        layering = value.get("layering") if isinstance(value.get("layering"), dict) else {}
        required = bool(occ.get("needs_foreground_mask") or layering.get("foreground_mask_required") or layering.get("occluded_by_foreground"))
        if cue_id and required:
            key = (str(cue_id), get_int(value.get("start_frame"), -1), get_int(value.get("end_frame"), -1))
            if key not in seen:
                seen.add(key); out.append(value)
        for v in value.values():
            _collect_occlusion_event_dicts(v, out, seen)
    elif isinstance(value, list):
        for v in value:
            _collect_occlusion_event_dicts(v, out, seen)


def build_caption_occlusion_plan(generic: Dict[str, Any], args: argparse.Namespace, fps: float) -> Dict[str, Any]:
    analysis_path = discover_occlusion_analysis_path(getattr(args, "generic", None), getattr(args, "caption_occlusion_analysis", None))
    result: Dict[str, Any] = {
        "enabled": bool(getattr(args, "apply_caption_occlusion", False) or getattr(args, "caption_occlusion_plan_only", False)),
        "mode": "plan_only",
        "sequence_step": 9,
        "target_track": 4,
        "analysis_path": analysis_path,
        "analysis_exists": bool(analysis_path and Path(analysis_path).exists()),
        "mask_root": getattr(args, "caption_occlusion_mask_root", None),
        "events": [], "warnings": [], "errors": [],
    }
    if not result["enabled"]:
        result["status"] = "disabled"; return result
    if not result["analysis_exists"]:
        result["status"] = "blocked_missing_analysis"
        result["errors"].append("Occlusion analysis file was not found.")
        return result
    try:
        analysis = load_json(str(analysis_path))
        raw: List[Dict[str, Any]] = []
        _collect_occlusion_event_dicts(analysis, raw, set())
        min_score = float(getattr(args, "caption_occlusion_min_score", 0.50) or 0.50)
        mask_root = Path(getattr(args, "caption_occlusion_mask_root", "") or "") if getattr(args, "caption_occlusion_mask_root", None) else None
        for ev in raw:
            occ = ev.get("occlusion") if isinstance(ev.get("occlusion"), dict) else {}
            layering = ev.get("layering") if isinstance(ev.get("layering"), dict) else {}
            score = float(occ.get("score") or occ.get("max_score") or 0.0)
            if score < min_score: continue
            cue_id = str(ev.get("cue_id"))
            start_frame = get_int(ev.get("start_frame"), int(round(float(ev.get("start") or 0.0) * fps)))
            end_frame = get_int(ev.get("end_frame"), int(round(float(ev.get("end") or 0.0) * fps)))
            bbox = layering.get("mask_bbox") or ev.get("bbox")
            normalized_bbox = ev.get("normalized_bbox")
            candidates=[]
            if mask_root:
                for ext in (".png", ".exr", ".mov", ".mp4"):
                    candidates.append(mask_root / f"{cue_id}_foreground_mask{ext}")
                    candidates.append(mask_root / f"{cue_id}{ext}")
            asset = next((str(p.resolve()) for p in candidates if p.exists()), None)
            result["events"].append({
                "cue_id": cue_id, "text": ev.get("text"), "start_frame": start_frame,
                "end_frame": end_frame, "duration_frames": max(0,end_frame-start_frame),
                "occlusion_score": score, "occlusion_label": occ.get("label"),
                "mask_bbox": bbox, "normalized_bbox": normalized_bbox,
                "foreground_backend": ((ev.get("foreground") or {}).get("backend_requested") if isinstance(ev.get("foreground"),dict) else None),
                "mask_asset": asset, "mask_asset_exists": bool(asset),
                "v4_operation": "foreground_subject_matte_above_v3_caption",
            })
        result["event_count"] = len(result["events"])
        result["mask_asset_count"] = sum(1 for e in result["events"] if e.get("mask_asset_exists"))
        result["missing_mask_asset_count"] = result["event_count"] - result["mask_asset_count"]
        result["contract_valid"] = result["event_count"] > 0
        result["timeline_mutation_attempted"] = False
        result["status"] = "ready_for_v4_apply" if result["event_count"] and result["missing_mask_asset_count"] == 0 else "blocked_missing_mask_assets"
        result["reason"] = "BBox/occlusion metadata is sufficient for planning but not for a real foreground matte. Actual alpha/mask media is required."
        output = getattr(args, "caption_occlusion_plan_output", None)
        if not output and getattr(args, "report", None):
            rp=Path(args.report); output=str(rp.with_name(rp.stem + "_foreground_matte_plan.json"))
        if output:
            save_json(output, result); result["plan_output"] = str(Path(output).resolve())
    except Exception as exc:
        result["status"]="error"; result["errors"].append(compact_exception(exc)); result["traceback"]=traceback.format_exc()
    return result




def _path_from_status(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        raw = value.get("path")
    else:
        raw = value
    if raw is None:
        return None
    raw_text = str(raw).strip()
    return raw_text or None


def canonical_caption_cue_id(value: Any) -> Optional[str]:
    """Reconcile sub_052 and sub_0052 without changing the source contracts."""
    text_value = str(value or "")
    match = re.search(r"(?i)sub[_-]?0*(\d+)", text_value)
    if not match:
        return None
    try:
        return f"sub_{int(match.group(1)):04d}"
    except Exception:
        return None


def timeline_item_cue_ids(item: Any) -> List[str]:
    name = timeline_item_name(item)
    found: List[str] = []
    for token in re.findall(r"(?i)sub[_-]?\d+", name):
        canonical = canonical_caption_cue_id(token)
        if canonical and canonical not in found:
            found.append(canonical)
    return found


def build_caption_foreground_rgba_plan(
    generic: Dict[str, Any],
    args: argparse.Namespace,
    fps: float,
) -> Dict[str, Any]:
    analysis_path = discover_occlusion_analysis_path(
        getattr(args, "generic", None),
        getattr(args, "caption_occlusion_analysis", None),
    )
    result: Dict[str, Any] = {
        "enabled": bool(
            getattr(args, "apply_caption_occlusion", False)
            or getattr(args, "caption_occlusion_plan_only", False)
        ),
        "mode": "rgba_sequence_plan",
        "major_step": "2F",
        "sequence_step": 9,
        "analysis_path": analysis_path,
        "analysis_exists": bool(analysis_path and Path(str(analysis_path)).is_file()),
        "target_track": max(2, get_int(getattr(args, "caption_occlusion_target_track", 4), 4)),
        "asset_scope_required": "local_foreground_patch_intersecting_caption_region",
        "spans": [],
        "warnings": [],
        "errors": [],
        "timeline_mutation_attempted": False,
    }
    if not result["enabled"]:
        result["status"] = "disabled"
        return result
    if not result["analysis_exists"]:
        result["status"] = "blocked_missing_analysis"
        result["errors"].append("Unified Step 2E analysis.json was not found.")
        return result

    try:
        analysis = load_json(str(analysis_path))
        result["analysis_version"] = analysis.get("analysis_version")
        result["analysis_schema_version"] = analysis.get("schema_version")
        summary = analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}
        contract = (
            analysis.get("caption_foreground_asset_contract")
            if isinstance(analysis.get("caption_foreground_asset_contract"), dict)
            else {}
        )
        result["analysis_ready_flags"] = {
            "summary_v4_ready": bool(summary.get("caption_foreground_v4_ready")),
            "asset_contract_available": bool(contract.get("available")),
            "asset_contract_success": bool(contract.get("success")),
            "asset_contract_v4_ready": bool(contract.get("ready_for_v4_import")),
        }
        raw_spans = (((analysis.get("timeline") or {}).get("caption_foreground_asset_spans")) or [])
        if not isinstance(raw_spans, list):
            raw_spans = []
        max_spans = max(0, get_int(getattr(args, "caption_occlusion_max_events", 0), 0))
        if max_spans > 0:
            raw_spans = raw_spans[:max_spans]

        require_ready = bool(getattr(args, "caption_occlusion_require_editor_ready_assets", True))
        required_scope = result["asset_scope_required"]
        for index, span in enumerate(raw_spans):
            if not isinstance(span, dict):
                continue
            start_frame = get_int(span.get("timeline_frame_start"), -1)
            end_frame = get_int(span.get("timeline_frame_end_exclusive"), -1)
            duration = get_int(span.get("duration_frames"), max(0, end_frame - start_frame))
            rgba_asset = span.get("rgba_asset") if isinstance(span.get("rgba_asset"), dict) else {}
            rgba_pattern = _path_from_status(rgba_asset.get("rgba_pattern"))
            frame_checks = span.get("file_checks") if isinstance(span.get("file_checks"), list) else []
            affected_cues = [
                str(value) for value in (span.get("affected_cue_ids") or [])
                if str(value).strip()
            ]
            canonical_cues = sorted({
                cue for cue in (canonical_caption_cue_id(value) for value in affected_cues)
                if cue
            })
            row_errors: List[str] = []
            if require_ready and not span.get("editor_ready"):
                row_errors.append("span_not_editor_ready")
            if not span.get("complete"):
                row_errors.append("span_not_complete")
            if str(span.get("asset_scope") or "") != required_scope:
                row_errors.append("wrong_asset_scope")
            if start_frame < 0 or end_frame <= start_frame:
                row_errors.append("invalid_timeline_range")
            if duration != max(0, end_frame - start_frame):
                row_errors.append("duration_range_mismatch")
            if not rgba_pattern:
                row_errors.append("rgba_pattern_missing")
            if not canonical_cues:
                row_errors.append("affected_cue_ids_missing")
            if span.get("errors"):
                row_errors.append("span_errors_present")
            if span.get("missing_rgba_frames"):
                row_errors.append("missing_rgba_frames_reported")

            rgba_files: List[str] = []
            if rgba_pattern and start_frame >= 0 and end_frame > start_frame:
                for frame_index in range(start_frame, end_frame):
                    try:
                        file_path = str(rgba_pattern % frame_index)
                    except Exception:
                        row_errors.append("rgba_pattern_format_failed")
                        break
                    rgba_files.append(file_path)
                    if not Path(file_path).is_file():
                        row_errors.append(f"rgba_file_missing:{frame_index}")

            if frame_checks:
                checked_frames = {
                    get_int(check.get("timeline_frame"), -1)
                    for check in frame_checks if isinstance(check, dict) and check.get("rgba_exists")
                }
                expected_frames = set(range(start_frame, end_frame)) if start_frame >= 0 else set()
                if checked_frames != expected_frames:
                    row_errors.append("file_checks_do_not_cover_exact_span")

            item_name = (
                f"{str(getattr(args, 'caption_occlusion_item_prefix', 'VC_OCCLUSION_RGBA_') or 'VC_OCCLUSION_RGBA_')}"
                f"{str(span.get('span_id') or f'span_{index + 1:04d}')}"
                f"_{canonical_cues[0] if canonical_cues else 'unlinked'}"
            )
            result["spans"].append({
                "index": index,
                "span_id": str(span.get("span_id") or f"span_{index + 1:04d}"),
                "item_name": item_name,
                "editor_ready": bool(span.get("editor_ready")),
                "asset_scope": span.get("asset_scope"),
                "timeline_frame_start": start_frame,
                "timeline_frame_end_exclusive": end_frame,
                "duration_frames": duration,
                "contract_fps": get_float(span.get("contract_fps"), fps),
                "source_video_fps": get_float(span.get("source_video_fps"), 0.0),
                "affected_cue_ids": affected_cues,
                "canonical_cue_ids": canonical_cues,
                "rgba_pattern": rgba_pattern,
                "rgba_files": rgba_files,
                "first_rgba_file": rgba_files[0] if rgba_files else None,
                "last_rgba_file": rgba_files[-1] if rgba_files else None,
                "rgba_asset": rgba_asset,
                "caption_region": span.get("caption_region"),
                "errors": row_errors,
                "ready": not row_errors,
            })

        result["span_count"] = len(result["spans"])
        result["ready_span_count"] = sum(1 for span in result["spans"] if span.get("ready"))
        result["invalid_span_count"] = result["span_count"] - result["ready_span_count"]
        result["requested_frame_count"] = sum(
            get_int(span.get("duration_frames"), 0) for span in result["spans"]
        )
        result["contract_valid"] = bool(
            result["span_count"] > 0
            and result["invalid_span_count"] == 0
            and result["analysis_ready_flags"].get("summary_v4_ready")
            and result["analysis_ready_flags"].get("asset_contract_v4_ready")
        )
        if not result["span_count"]:
            result["errors"].append("No foreground RGBA spans exist in timeline.caption_foreground_asset_spans.")
        for span in result["spans"]:
            for error in span.get("errors") or []:
                result["errors"].append(f"{span.get('span_id')}:{error}")
        result["status"] = "ready_for_v4_rgba_apply" if result["contract_valid"] else "blocked_invalid_rgba_asset_contract"
        result["reason"] = (
            "Validated Step 2E local RGBA sequences are ready for exact V4 placement."
            if result["contract_valid"]
            else "Step 2E RGBA asset contract is incomplete or failed local file validation."
        )
        output = getattr(args, "caption_occlusion_plan_output", None)
        if not output and getattr(args, "report", None):
            report_path = Path(str(args.report))
            output = str(report_path.with_name(report_path.stem + "_foreground_rgba_plan.json"))
        if output:
            save_json(str(output), result)
            result["plan_output"] = str(Path(str(output)).resolve())
        return result
    except Exception as exc:
        result["status"] = "error"
        result["errors"].append(compact_exception(exc))
        result["traceback"] = traceback.format_exc()
        return result


def _media_pool_item_properties(item: Any) -> Dict[str, Any]:
    props = safe_call(item, "GetClipProperty", default={})
    return props if isinstance(props, dict) else {}


def _media_pool_item_file_paths(item: Any) -> List[str]:
    props = _media_pool_item_properties(item)
    values: List[str] = []
    for key, value in props.items():
        key_norm = str(key).strip().lower().replace("_", " ")
        if "path" not in key_norm and "file" not in key_norm:
            continue
        if isinstance(value, (str, Path)) and str(value).strip():
            values.append(str(value))
    name = str(safe_call(item, "GetName", default="") or "")
    if name:
        values.append(name)
    return values


def _walk_media_pool_folders(folder: Any, depth: int = 0) -> List[Any]:
    if folder is None or depth > 20:
        return []
    folders = [folder]
    children = safe_call(folder, "GetSubFolderList", default=[])
    if isinstance(children, (list, tuple)):
        for child in children:
            folders.extend(_walk_media_pool_folders(child, depth + 1))
    return folders


def _find_matching_rgba_media_pool_item(
    project: Any,
    span: Dict[str, Any],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"found": False, "item": None, "attempted": True, "candidates_scanned": 0}
    media_pool = safe_call(project, "GetMediaPool", default=None)
    if not media_pool:
        result["error"] = "project.GetMediaPool() returned no object."
        return result
    root = safe_call(media_pool, "GetRootFolder", default=None)
    if not root:
        result["error"] = "MediaPool.GetRootFolder() returned no object."
        return result
    expected_first = os.path.normcase(os.path.normpath(str(span.get("first_rgba_file") or "")))
    expected_name = str(span.get("item_name") or "")
    expected_frames = get_int(span.get("duration_frames"), 0)
    for folder in _walk_media_pool_folders(root):
        clips = safe_call(folder, "GetClipList", default=[])
        if not isinstance(clips, (list, tuple)):
            continue
        for item in clips:
            result["candidates_scanned"] += 1
            name = str(safe_call(item, "GetName", default="") or "")
            paths = _media_pool_item_file_paths(item)
            normalized_paths = [os.path.normcase(os.path.normpath(str(value))) for value in paths]
            props = _media_pool_item_properties(item)
            frames_value = None
            for key, value in props.items():
                if str(key).strip().lower() in {"frames", "frame count", "framecount"}:
                    frames_value = get_int(value, 0)
                    break
            path_match = bool(expected_first and any(
                path == expected_first
                or expected_first in path
                or os.path.basename(expected_first) in os.path.basename(path)
                for path in normalized_paths
            ))
            name_match = bool(expected_name and name == expected_name)
            frame_match = frames_value in {None, 0, expected_frames}
            if (path_match or name_match) and frame_match:
                result.update({
                    "found": True,
                    "item": item,
                    "name": name,
                    "paths": paths,
                    "properties": props,
                    "matched_by": "path" if path_match else "name",
                })
                return result
    return result


def _set_media_pool_item_name(item: Any, name: str) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    try:
        method = getattr(item, "SetName", None)
        if method:
            ok = method(name)
            attempts.append({"method": "SetName", "ok": bool(ok)})
            if ok:
                return {"ok": True, "name": name, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "SetName", "ok": False, "error": compact_exception(exc)})
    for key in ("Clip Name", "Name"):
        try:
            method = getattr(item, "SetClipProperty", None)
            if method:
                ok = method(key, name)
                attempts.append({"method": f"SetClipProperty({key})", "ok": bool(ok)})
                if ok:
                    return {"ok": True, "name": name, "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": f"SetClipProperty({key})", "ok": False, "error": compact_exception(exc)})
    return {"ok": False, "name": name, "attempts": attempts}


def _set_rgba_media_pool_properties(
    item: Any,
    timeline_fps: float,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"attempted": True, "writes": [], "properties_after": {}}
    method = getattr(item, "SetClipProperty", None)
    if method:
        for key, value in (
            ("Video Frame Rate", str(timeline_fps)),
            ("FPS", str(timeline_fps)),
        ):
            try:
                ok = method(key, value)
                result["writes"].append({"property": key, "value": value, "ok": bool(ok)})
                if ok:
                    break
            except Exception as exc:
                result["writes"].append({"property": key, "value": value, "ok": False, "error": compact_exception(exc)})
        if getattr(args, "caption_occlusion_set_straight_alpha", True):
            alpha_value = str(getattr(args, "caption_occlusion_alpha_mode", "Straight") or "Straight")
            for key in ("Alpha mode", "Alpha Mode"):
                try:
                    ok = method(key, alpha_value)
                    result["writes"].append({"property": key, "value": alpha_value, "ok": bool(ok)})
                    if ok:
                        break
                except Exception as exc:
                    result["writes"].append({"property": key, "value": alpha_value, "ok": False, "error": compact_exception(exc)})
    result["properties_after"] = _media_pool_item_properties(item)
    result["alpha_contract"] = "RGBA8 straight/unassociated alpha was independently validated upstream in Step 2D."
    return result


def _delete_media_pool_items(project: Any, items: List[Any]) -> Dict[str, Any]:
    if not items:
        return {"attempted": False, "requested_count": 0, "deleted": 0}
    media_pool = safe_call(project, "GetMediaPool", default=None)
    if not media_pool:
        return {"attempted": True, "requested_count": len(items), "deleted": 0, "error": "GetMediaPool failed"}
    try:
        ok = media_pool.DeleteClips(items)
        return {"attempted": True, "requested_count": len(items), "deleted": len(items) if ok else 0, "ok": bool(ok)}
    except Exception as exc:
        return {"attempted": True, "requested_count": len(items), "deleted": 0, "ok": False, "error": compact_exception(exc)}


def _import_rgba_sequence_media_pool(
    project: Any,
    span: Dict[str, Any],
    args: argparse.Namespace,
    fps: float,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "attempted": True,
        "backend": "MediaPool.ImportMedia_image_sequence",
        "reused": False,
        "imported": False,
        "item": None,
        "errors": [],
    }
    if getattr(args, "caption_occlusion_reuse_media_pool_items", True):
        reused = _find_matching_rgba_media_pool_item(project, span)
        result["reuse_search"] = {k: json_safe_value(v) for k, v in reused.items() if k != "item"}
        if reused.get("found"):
            item = reused.get("item")
            result["item"] = item
            result["reused"] = True
            result["media_pool_item_name"] = safe_call(item, "GetName", default=None)
            result["properties"] = _media_pool_item_properties(item)
            result["property_writes"] = _set_rgba_media_pool_properties(item, fps, args)
            result["ok"] = True
            return result

    media_pool = safe_call(project, "GetMediaPool", default=None)
    if not media_pool:
        result["errors"].append("project.GetMediaPool() returned no object.")
        result["ok"] = False
        return result
    pattern = str(span.get("rgba_pattern") or "")
    start_index = get_int(span.get("timeline_frame_start"), 0)
    end_index = max(start_index, get_int(span.get("timeline_frame_end_exclusive"), start_index + 1) - 1)
    payload = [{"FilePath": pattern, "StartIndex": start_index, "EndIndex": end_index}]
    result["import_payload"] = payload
    returned = None
    try:
        returned = media_pool.ImportMedia(payload)
    except Exception as exc:
        result["errors"].append(compact_exception(exc))
    time.sleep(0.25)
    items: List[Any] = []
    if isinstance(returned, (list, tuple)):
        items = list(returned)
    elif returned is not None:
        items = [returned]
    result["returned_type"] = type(returned).__name__ if returned is not None else None
    result["returned_count"] = len(items)
    if len(items) != 1:
        if items:
            result["rollback_media_pool"] = _delete_media_pool_items(project, items)
        result["errors"].append(
            f"Image-sequence import expected exactly one MediaPoolItem, received {len(items)}."
        )
        result["ok"] = False
        return result
    item = items[0]
    result["item"] = item
    result["imported"] = True
    result["name_write"] = _set_media_pool_item_name(item, str(span.get("item_name") or "VC_OCCLUSION_RGBA"))
    result["media_pool_item_name"] = safe_call(item, "GetName", default=None)
    result["properties"] = _media_pool_item_properties(item)
    result["property_writes"] = _set_rgba_media_pool_properties(item, fps, args)
    frames = 0
    for key, value in (result.get("properties") or {}).items():
        if str(key).strip().lower() in {"frames", "frame count", "framecount"}:
            frames = get_int(value, 0)
            break
    expected_frames = get_int(span.get("duration_frames"), 0)
    result["reported_frame_count"] = frames or None
    result["expected_frame_count"] = expected_frames
    if frames > 0 and frames != expected_frames:
        result["errors"].append(
            f"Imported image sequence reports {frames} frames; expected {expected_frames}."
        )
        result["rollback_media_pool"] = _delete_media_pool_items(project, [item])
        result["item"] = None
        result["ok"] = False
        return result
    result["ok"] = True
    return result


def verify_v3_cue_linkage_for_span(
    timeline: Any,
    v3_track: int,
    span: Dict[str, Any],
) -> Dict[str, Any]:
    expected = set(span.get("canonical_cue_ids") or [])
    asset_start = get_int(span.get("timeline_frame_start"), 0)
    asset_end = max(asset_start + 1, get_int(span.get("timeline_frame_end_exclusive"), asset_start + 1))
    rows: List[Dict[str, Any]] = []
    matched: List[Dict[str, Any]] = []
    for item in get_track_items(timeline, "video", max(1, get_int(v3_track, 3))):
        name = timeline_item_name(item)
        cue_ids = set(timeline_item_cue_ids(item))
        if not cue_ids.intersection(expected):
            continue
        start = timeline_item_start(item)
        end = timeline_item_end(item)
        overlap_start = max(asset_start, start)
        overlap_end = min(asset_end, end)
        row = {
            "name": name,
            "cue_ids": sorted(cue_ids),
            "start_frame": start,
            "end_frame": end,
            "duration_frames": max(0, get_int(safe_call(item, "GetDuration", default=None), end - start)),
            "overlap_start": overlap_start,
            "overlap_end": overlap_end,
            "overlap_frames": max(0, overlap_end - overlap_start),
            "track": timeline_item_track_info(item),
        }
        rows.append(row)
        if row["overlap_frames"] > 0:
            matched.append(row)
    matched_cues = {
        cue for row in matched for cue in row.get("cue_ids") or [] if cue in expected
    }
    missing = sorted(expected - matched_cues)
    return {
        "attempted": True,
        "v3_track": v3_track,
        "asset_range": [asset_start, asset_end],
        "expected_cue_ids": sorted(expected),
        "matched_cue_ids": sorted(matched_cues),
        "missing_cue_ids": missing,
        "candidate_items": rows,
        "matched_items": matched,
        "asset_preroll_frames": min(
            [max(0, row["start_frame"] - asset_start) for row in matched] or [0]
        ),
        "ok": bool(expected and not missing and matched),
    }


def _verify_existing_v4_item(
    item: Any,
    span: Dict[str, Any],
    target_track: int,
) -> Dict[str, Any]:
    expected_start = get_int(span.get("timeline_frame_start"), 0)
    expected_end = max(expected_start + 1, get_int(span.get("timeline_frame_end_exclusive"), expected_start + 1))
    range_result = verify_generated_item_range_readonly(item, expected_start, expected_end, target_track)
    expected_name = str(span.get("item_name") or "")
    actual_name = timeline_item_name(item)
    media_item = safe_call(item, "GetMediaPoolItem", default=None)
    return {
        "ok": bool(range_result.get("ok") and actual_name == expected_name and media_item),
        "expected_name": expected_name,
        "actual_name": actual_name,
        "range": range_result,
        "has_media_pool_item": bool(media_item),
        "media_pool_item_name": safe_call(media_item, "GetName", default=None) if media_item else None,
        "media_pool_paths": _media_pool_item_file_paths(media_item) if media_item else [],
    }


def _append_rgba_sequence_item(
    project: Any,
    timeline: Any,
    media_pool_item: Any,
    span: Dict[str, Any],
    target_track: int,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    """Append one RGBA image sequence with exact half-open source semantics.

    The imported sequence contains exactly `duration` source frames. In the
    tested Resolve 21 runtime, AppendToTimeline treats clipInfo.endFrame as an
    exclusive source boundary for this image-sequence MediaPoolItem. Passing
    duration - 1 caused a four-frame clip, which the verifier correctly rolled
    back. We now pass source_start + duration and poll stable readback before
    any rollback.
    """
    start = get_int(span.get("timeline_frame_start"), 0)
    end = max(start + 1, get_int(span.get("timeline_frame_end_exclusive"), start + 1))
    duration = end - start
    source_start_candidates: List[int] = []
    for candidate in (0, start):
        if candidate not in source_start_candidates:
            source_start_candidates.append(candidate)

    settle_timeout = max(
        0.0,
        get_float(getattr(args, "caption_occlusion_verify_settle_timeout_sec", 1.50), 1.50),
    )
    settle_interval = max(
        0.02,
        get_float(getattr(args, "caption_occlusion_verify_poll_interval_sec", 0.10), 0.10),
    )

    result: Dict[str, Any] = {
        "attempted": True,
        "target_track": target_track,
        "record_range": [start, end],
        "record_range_semantics": "half_open",
        "duration_frames": duration,
        "source_api_end_semantics": "exclusive_for_rgba_sequence",
        "verification_settle_timeout_sec": settle_timeout,
        "verification_poll_interval_sec": settle_interval,
        "attempts": [],
        "item": None,
        "errors": [],
    }

    for source_start in source_start_candidates:
        source_end_exclusive = source_start + duration
        clip_row = {
            "media_pool_item": media_pool_item,
            "source_start": source_start,
            "source_end_inclusive": source_end_exclusive - 1,
            "source_end_frame_api": source_end_exclusive,
            "api_end_semantics": "exclusive_for_rgba_sequence",
            "record_start": start,
            "record_end": end,
            "duration": duration,
        }
        append = _append_media_clip_infos(project, timeline, [clip_row], target_track)
        items = list(append.get("detected_items") or append.get("returned_items") or [])
        attempt = {
            "source_start": source_start,
            "source_end_inclusive_diagnostic": source_end_exclusive - 1,
            "source_end_frame_api": source_end_exclusive,
            "api_end_semantics": "exclusive_for_rgba_sequence",
            "append": {
                k: json_safe_value(v)
                for k, v in append.items()
                if k not in {"returned_items", "detected_items"}
            },
            "detected_count": len(items),
        }
        if len(items) == 1:
            item = items[0]
            attempt["name_write"] = set_timeline_item_name(
                item,
                str(span.get("item_name") or "VC_OCCLUSION_RGBA"),
            )
            attempt["verification"] = verify_generated_item_range_with_settle(
                item,
                start,
                end,
                target_track,
                timeout_sec=settle_timeout,
                poll_interval_sec=settle_interval,
            )
            media_item = safe_call(item, "GetMediaPoolItem", default=None)
            attempt["verification"]["expected_name"] = str(span.get("item_name") or "")
            attempt["verification"]["actual_name"] = timeline_item_name(item)
            attempt["verification"]["has_media_pool_item"] = bool(media_item)
            attempt["verification"]["media_pool_item_name"] = (
                safe_call(media_item, "GetName", default=None) if media_item else None
            )
            attempt["verification"]["media_pool_paths"] = (
                _media_pool_item_file_paths(media_item) if media_item else []
            )
            attempt["verification"]["ok"] = bool(
                attempt["verification"].get("ok")
                and attempt["verification"].get("actual_name")
                == attempt["verification"].get("expected_name")
                and media_item
            )

            if attempt["verification"].get("ok"):
                result["attempts"].append(attempt)
                result["item"] = item
                result["source_range_used"] = [source_start, source_end_exclusive]
                result["source_range_semantics"] = "half_open"
                result["verification"] = attempt["verification"]
                result["ok"] = True
                return result

            # Safe rollback remains enabled, but only after the corrected
            # exclusive-end append and the full settle-verification window.
            attempt["rollback_reason"] = "exact_range_or_media_verification_failed_after_settle_window"
            attempt["rollback"] = delete_timeline_items(timeline, [item])
        elif items:
            attempt["rollback_reason"] = "append_returned_unexpected_item_count"
            attempt["rollback"] = delete_timeline_items(timeline, items)
        result["attempts"].append(attempt)

    result["errors"].append(
        "Could not append and verify the RGBA image sequence at the exact V4 range "
        "after exclusive-end source trimming and settle polling."
    )
    result["ok"] = False
    return result


def apply_caption_occlusion_rgba_assets(
    project: Any,
    timeline: Any,
    args: argparse.Namespace,
    fps: float,
    plan: Dict[str, Any],
    v3_track: int,
) -> Dict[str, Any]:
    target_track = max(2, get_int(getattr(args, "caption_occlusion_target_track", 4), 4))
    prefix = str(getattr(args, "caption_occlusion_item_prefix", "VC_OCCLUSION_RGBA_") or "VC_OCCLUSION_RGBA_")
    legacy_prefix = str(getattr(args, "caption_occlusion_legacy_item_prefix", "VC_OCCLUSION_BBOX_") or "VC_OCCLUSION_BBOX_")
    result: Dict[str, Any] = {
        "enabled": True,
        "mode": "rgba_sequence_apply",
        "major_step": "2F",
        "sequence_step": 9,
        "target_track": target_track,
        "item_prefix": prefix,
        "timeline_mutation_attempted": True,
        "requested_span_count": len(plan.get("spans") or []),
        "spans": [],
        "created_count": 0,
        "reused_count": 0,
        "ready_count": 0,
        "failed_count": 0,
        "warnings": [],
        "errors": [],
    }
    if not plan.get("contract_valid"):
        result["status"] = "blocked_invalid_rgba_asset_contract"
        result["errors"].extend(plan.get("errors") or ["RGBA plan is not valid."])
        result["failed_count"] = result["requested_span_count"]
        result["ok"] = False
        result["timeline_mutation_attempted"] = False
        return result

    result["track_setup"] = ensure_video_track(timeline, target_track)
    if not result["track_setup"].get("ok"):
        result["status"] = "failed_track_setup"
        result["errors"].append("Could not create/access the requested V4 track.")
        result["failed_count"] = result["requested_span_count"]
        result["ok"] = False
        return result
    result["track_name"] = set_track_name_best_effort(
        timeline, "video", target_track,
        str(getattr(args, "caption_occlusion_track_name", "VC_OCCLUSION_V4") or "VC_OCCLUSION_V4"),
    )
    before_core = snapshot_core_tracks(
        timeline,
        max(1, get_int(args.video_track, 1)),
        max(1, get_int(args.audio_track, 1)),
    )

    spans = list(plan.get("spans") or [])
    expected_by_name = {str(span.get("item_name")): span for span in spans}
    existing_generated = find_items_by_name_prefix(timeline, prefix)
    reusable_by_name: Dict[str, Any] = {}
    stale_items: List[Any] = []
    existing_verification: List[Dict[str, Any]] = []
    for item in existing_generated:
        name = timeline_item_name(item)
        span = expected_by_name.get(name)
        verification = _verify_existing_v4_item(item, span, target_track) if span else {"ok": False, "reason": "unexpected_generated_name"}
        existing_verification.append({"name": name, "verification": verification})
        if span and verification.get("ok") and name not in reusable_by_name:
            reusable_by_name[name] = item
        else:
            stale_items.append(item)
    result["existing_generated_items"] = existing_verification

    if getattr(args, "caption_occlusion_clear_legacy_bbox_v4", True):
        stale_items.extend(find_items_by_name_prefix(timeline, legacy_prefix))
    unique_stale: List[Any] = []
    seen_stale: set = set()
    for item in stale_items:
        uid = timeline_item_unique_id(item) or f"object:{id(item)}"
        if uid not in seen_stale:
            seen_stale.add(uid)
            unique_stale.append(item)
    if unique_stale and getattr(args, "caption_occlusion_clear_old_v4", True):
        result["clear_stale"] = delete_timeline_items(timeline, unique_stale)
        if get_int((result.get("clear_stale") or {}).get("deleted"), 0) != len(unique_stale):
            result["errors"].append("Not all stale/duplicate Step 2F or legacy bbox V4 items could be deleted.")
    else:
        result["clear_stale"] = {"attempted": False, "requested_count": len(unique_stale), "deleted": 0}

    newly_created_items: List[Any] = []
    newly_imported_media: List[Any] = []
    stop_on_failure = bool(getattr(args, "caption_occlusion_stop_on_first_failure", True))
    require_linkage = bool(getattr(args, "caption_occlusion_require_v3_cue_linkage", True))

    for span in spans:
        span_row: Dict[str, Any] = {
            "span_id": span.get("span_id"),
            "item_name": span.get("item_name"),
            "timeline_range": [span.get("timeline_frame_start"), span.get("timeline_frame_end_exclusive")],
            "affected_cue_ids": span.get("affected_cue_ids") or [],
            "canonical_cue_ids": span.get("canonical_cue_ids") or [],
            "rgba_pattern": span.get("rgba_pattern"),
            "status": None,
            "errors": [],
        }
        dependency = verify_v3_cue_linkage_for_span(timeline, v3_track, span)
        span_row["v3_dependency"] = dependency
        if require_linkage and not dependency.get("ok"):
            span_row["status"] = "failed_v3_cue_linkage"
            span_row["errors"].append("The foreground asset could not be linked to an overlapping generated V3 Text+ cue.")
            result["spans"].append(span_row)
            result["failed_count"] += 1
            if stop_on_failure:
                break
            continue

        existing = reusable_by_name.get(str(span.get("item_name")))
        if existing is not None:
            span_row["existing_verification"] = _verify_existing_v4_item(existing, span, target_track)
            span_row["status"] = "reused_existing_verified_item"
            span_row["ok"] = bool(span_row["existing_verification"].get("ok"))
            if span_row["ok"]:
                result["reused_count"] += 1
                result["ready_count"] += 1
            else:
                span_row["errors"].append("Existing V4 item failed exact re-verification.")
                result["failed_count"] += 1
            result["spans"].append(span_row)
            if not span_row["ok"] and stop_on_failure:
                break
            continue

        imported = _import_rgba_sequence_media_pool(project, span, args, fps)
        span_row["media_import"] = {k: json_safe_value(v) for k, v in imported.items() if k != "item"}
        media_item = imported.get("item")
        if not imported.get("ok") or media_item is None:
            span_row["status"] = "failed_media_import"
            span_row["errors"].extend(imported.get("errors") or ["RGBA image sequence import failed."])
            result["spans"].append(span_row)
            result["failed_count"] += 1
            if stop_on_failure:
                break
            continue
        if imported.get("imported"):
            newly_imported_media.append(media_item)

        appended = _append_rgba_sequence_item(project, timeline, media_item, span, target_track, args)
        span_row["timeline_append"] = {k: json_safe_value(v) for k, v in appended.items() if k != "item"}
        item = appended.get("item")
        if not appended.get("ok") or item is None:
            span_row["status"] = "failed_timeline_append"
            span_row["errors"].extend(appended.get("errors") or ["RGBA V4 timeline append failed."])
            result["spans"].append(span_row)
            result["failed_count"] += 1
            if imported.get("imported"):
                span_row["media_import_rollback"] = _delete_media_pool_items(project, [media_item])
                try:
                    newly_imported_media.remove(media_item)
                except ValueError:
                    pass
            if stop_on_failure:
                break
            continue

        newly_created_items.append(item)
        span_row["status"] = "created_and_verified"
        span_row["ok"] = True
        span_row["final_verification"] = _verify_existing_v4_item(item, span, target_track)
        if not span_row["final_verification"].get("ok"):
            span_row["status"] = "failed_final_verification"
            span_row["ok"] = False
            span_row["errors"].append("New V4 item failed final exact verification.")
            result["failed_count"] += 1
            if stop_on_failure:
                result["spans"].append(span_row)
                break
        else:
            result["created_count"] += 1
            result["ready_count"] += 1
        result["spans"].append(span_row)

    expected_ready = len(spans)
    pass_ok = bool(
        result["ready_count"] == expected_ready
        and result["failed_count"] == 0
        and not result["errors"]
    )
    if not pass_ok and getattr(args, "caption_occlusion_rollback_on_failure", True):
        result["rollback_new_timeline_items"] = delete_timeline_items(timeline, newly_created_items)
        if newly_imported_media:
            result["rollback_new_media_pool_items"] = _delete_media_pool_items(project, newly_imported_media)
        result["ready_count_after_rollback"] = result["reused_count"]
    else:
        result["rollback_new_timeline_items"] = {"attempted": False, "requested_count": 0, "deleted": 0}

    after_core = snapshot_core_tracks(
        timeline,
        max(1, get_int(args.video_track, 1)),
        max(1, get_int(args.audio_track, 1)),
    )
    result["core_track_integrity"] = compare_core_track_snapshots(before_core, after_core)
    if not result["core_track_integrity"].get("ok"):
        result["errors"].append("V1/A1 integrity changed during the Step 2F pass.")
        pass_ok = False
    result["ok"] = bool(pass_ok and result["core_track_integrity"].get("ok"))
    result["status"] = (
        "applied_rgba_sequence"
        if result["ok"] and result["created_count"] > 0
        else "verified_idempotent_rgba_sequence"
        if result["ok"] and result["reused_count"] == expected_ready
        else "partial_or_failed_rgba_sequence"
    )
    result["fidelity"] = {
        "backend": "validated_full_resolution_rgba_png_sequence",
        "asset_scope": "local_foreground_patch_intersecting_caption_region",
        "quality": "source_editor_ready_asset",
        "legacy_bbox_fallback_used": False,
        "composition_order": ["V1_base_video", "V3_TextPlus_caption", "V4_local_RGBA_foreground"],
    }
    return result


def _safe_load_optional_json(path_value: Any) -> Dict[str, Any]:
    path = str(path_value or "").strip()
    if not path:
        return {}
    try:
        resolved = Path(path).resolve()
        if not resolved.exists() or not resolved.is_file():
            return {}
        data = load_json(str(resolved))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _default_step_2g_path(args: argparse.Namespace, suffix: str) -> str:
    report_value = str(getattr(args, "report", "") or "").strip()
    if report_value:
        report_path = Path(report_value).resolve()
        stem = report_path.stem
        video_id = stem.split("_resolve_controller_report", 1)[0] or stem
        return str((report_path.parent / f"{video_id}_{suffix}").resolve())
    plan_value = str(getattr(args, "caption_occlusion_plan_output", "") or "").strip()
    if plan_value:
        plan_path = Path(plan_value).resolve()
        stem = plan_path.stem
        video_id = stem.split("_foreground_rgba_import_plan", 1)[0] or stem
        return str((plan_path.parent / f"{video_id}_{suffix}").resolve())
    return str((HARD_DEBUG_LOG.parent / suffix).resolve())


def finalize_caption_occlusion_major_step_2(
    report: Dict[str, Any],
    args: argparse.Namespace,
    fps: float,
) -> Dict[str, Any]:
    """Step 2G: persist a two-pass completion gate for Major Step 2.

    This gate proves both successful creation and successful idempotent reuse of
    the exact V4 RGBA item. Pixel-level appearance still requires one manual
    viewer check because the Resolve scripting API cannot inspect composed viewer
    pixels or determine whether the alpha edge looks visually correct.
    """
    enabled = bool(getattr(args, "caption_occlusion_finalize_major_step_2", False))
    result: Dict[str, Any] = {
        "enabled": enabled,
        "major_step": 2,
        "step": "2G",
        "name": "Caption occlusion completion gate",
        "controller_version": VERSION,
        "technical_complete": False,
        "manual_visual_confirmation_required": True,
        "manual_visual_confirmation_observed": False,
        "completion_percent": 0,
        "failures": [],
        "warnings": [],
    }
    if not enabled:
        result["status"] = "disabled"
        return result

    output_path = str(
        getattr(args, "caption_occlusion_finalization_output", None)
        or _default_step_2g_path(args, "caption_occlusion_major_step_2_finalization.json")
    )
    state_path = str(
        getattr(args, "caption_occlusion_finalization_state", None)
        or _default_step_2g_path(args, "caption_occlusion_major_step_2_state.json")
    )
    prior_validation_path = str(
        getattr(args, "caption_occlusion_prior_step_2f_validation", None)
        or _default_step_2g_path(args, "resolve_step_2F_validation.json")
    )
    result["output_path"] = output_path
    result["state_path"] = state_path
    result["prior_step_2f_validation_path"] = prior_validation_path

    occlusion = report.get("caption_occlusion") if isinstance(report.get("caption_occlusion"), dict) else {}
    plan = report.get("caption_occlusion_plan") if isinstance(report.get("caption_occlusion_plan"), dict) else {}
    dependency = report.get("caption_dependency_guard") if isinstance(report.get("caption_dependency_guard"), dict) else {}
    prior_state = _safe_load_optional_json(state_path)
    prior_validation = _safe_load_optional_json(prior_validation_path)

    requested = get_int(occlusion.get("requested_span_count"), get_int(plan.get("span_count"), 0))
    ready = get_int(occlusion.get("ready_count"), 0)
    created = get_int(occlusion.get("created_count"), 0)
    reused = get_int(occlusion.get("reused_count"), 0)
    failed = get_int(occlusion.get("failed_count"), 0)
    current_ok = bool(occlusion.get("ok"))
    plan_ok = bool(plan.get("contract_valid")) and get_int(plan.get("invalid_span_count"), 0) == 0
    v3_ok = bool(dependency.get("coverage_ok"))
    core_integrity = occlusion.get("core_track_integrity") if isinstance(occlusion.get("core_track_integrity"), dict) else {}
    core_ok = bool(core_integrity.get("ok"))
    exact_count_ok = bool(requested > 0 and ready == requested and failed == 0 and created + reused == requested)
    rgba_mode_ok = str(occlusion.get("mode") or "") == "rgba_sequence_apply"
    fidelity = occlusion.get("fidelity") if isinstance(occlusion.get("fidelity"), dict) else {}
    legacy_fallback_unused = fidelity.get("legacy_bbox_fallback_used") is False

    current_creation_pass = bool(current_ok and exact_count_ok and created == requested and reused == 0)
    current_reuse_pass = bool(current_ok and exact_count_ok and reused == requested and created == 0)
    prior_creation_pass = bool(
        prior_state.get("creation_pass_ok")
        or (
            prior_validation.get("ok")
            and get_int(prior_validation.get("created_count"), 0) > 0
            and get_int(prior_validation.get("ready_count"), 0) > 0
            and get_int(prior_validation.get("failed_count"), 0) == 0
        )
    )
    prior_reuse_pass = bool(prior_state.get("idempotency_pass_ok"))
    creation_pass_ok = bool(prior_creation_pass or current_creation_pass)
    idempotency_pass_ok = bool(prior_reuse_pass or current_reuse_pass)

    require_two_pass = bool(getattr(args, "caption_occlusion_require_creation_and_reuse_passes", True))
    current_contract_ok = bool(
        current_ok and plan_ok and v3_ok and core_ok and exact_count_ok
        and rgba_mode_ok and legacy_fallback_unused
    )
    technical_complete = bool(
        current_contract_ok
        and creation_pass_ok
        and (idempotency_pass_ok if require_two_pass else True)
    )

    spans = occlusion.get("spans") if isinstance(occlusion.get("spans"), list) else []
    first_span = spans[0] if spans and isinstance(spans[0], dict) else {}
    timeline_range = first_span.get("timeline_range") if isinstance(first_span.get("timeline_range"), list) else []
    if len(timeline_range) < 2:
        plan_spans = plan.get("spans") if isinstance(plan.get("spans"), list) else []
        plan_first = plan_spans[0] if plan_spans and isinstance(plan_spans[0], dict) else {}
        timeline_range = [
            get_int(plan_first.get("timeline_frame_start"), 0),
            get_int(plan_first.get("timeline_frame_end_exclusive"), 0),
        ]
        first_span = first_span or plan_first
    review_frame = get_int(getattr(args, "caption_occlusion_visual_review_frame", 0), 0)
    if review_frame <= 0 and len(timeline_range) >= 2:
        review_frame = int((get_int(timeline_range[0], 0) + get_int(timeline_range[1], 0) - 1) // 2)
    review_seconds = round(review_frame / max(0.001, float(fps)), 6)

    checks = {
        "current_occlusion_ok": current_ok,
        "rgba_asset_plan_valid": plan_ok,
        "v3_exact_coverage_ok": v3_ok,
        "v1_a1_core_integrity_ok": core_ok,
        "exact_requested_ready_count_ok": exact_count_ok,
        "rgba_sequence_backend_ok": rgba_mode_ok,
        "legacy_bbox_fallback_unused": legacy_fallback_unused,
        "creation_pass_ok": creation_pass_ok,
        "idempotency_reuse_pass_ok": idempotency_pass_ok,
    }
    for key, value in checks.items():
        if not value:
            result["failures"].append(key)

    result.update({
        "status": (
            "technical_complete_visual_review_pending"
            if technical_complete
            else "waiting_for_idempotency_reuse_pass"
            if current_contract_ok and creation_pass_ok and not idempotency_pass_ok
            else "incomplete"
        ),
        "technical_complete": technical_complete,
        "completion_percent": 95 if technical_complete else 85 if current_contract_ok and creation_pass_ok else 70 if current_contract_ok else 0,
        "require_creation_and_reuse_passes": require_two_pass,
        "checks": checks,
        "current_run": {
            "status": occlusion.get("status"),
            "requested_span_count": requested,
            "created_count": created,
            "reused_count": reused,
            "ready_count": ready,
            "failed_count": failed,
            "creation_pass": current_creation_pass,
            "idempotency_reuse_pass": current_reuse_pass,
        },
        "accumulated_state": {
            "creation_pass_ok": creation_pass_ok,
            "idempotency_pass_ok": idempotency_pass_ok,
            "prior_creation_evidence_loaded": prior_creation_pass,
            "prior_reuse_evidence_loaded": prior_reuse_pass,
        },
        "visual_review": {
            "required": True,
            "review_frame": review_frame,
            "review_seconds": review_seconds,
            "timeline_range": timeline_range,
            "cue_ids": first_span.get("canonical_cue_ids") or first_span.get("affected_cue_ids") or ["sub_0052"],
            "expected_item_prefix": str(getattr(args, "caption_occlusion_item_prefix", "VC_OCCLUSION_RGBA_")),
            "checklist": [
                "The foreground person appears above the linked V3 caption only where the silhouette overlaps it.",
                "No black rectangle, opaque crop, full-frame duplicate, or white flash is visible.",
                "The caption remains visible outside the foreground silhouette.",
                "Exactly one V4 item exists for the matte span after a second controller run.",
            ],
        },
    })

    state_payload = {
        "schema": "video_cloner_caption_occlusion_major_step_2_state",
        "schema_version": "1.0",
        "controller_version": VERSION,
        "creation_pass_ok": creation_pass_ok,
        "idempotency_pass_ok": idempotency_pass_ok,
        "last_status": result["status"],
        "last_run": result["current_run"],
        "technical_complete": technical_complete,
        "updated_at_unix": now_unix(),
    }
    try:
        save_json(state_path, state_payload)
        result["state_written"] = True
    except Exception as exc:
        result["state_written"] = False
        result["warnings"].append(f"Could not write Step 2G state: {compact_exception(exc)}")
    try:
        save_json(output_path, result)
        result["output_written"] = True
        save_json(output_path, result)
    except Exception as exc:
        result["output_written"] = False
        result["warnings"].append(f"Could not write Step 2G finalization report: {compact_exception(exc)}")
    return result

def _recursive_dimension_candidates(value: Any, found: List[Tuple[int, int]], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(value, dict):
        pairs = (
            ("width", "height"), ("frame_width", "frame_height"),
            ("video_width", "video_height"), ("source_width", "source_height"),
            ("timelineResolutionWidth", "timelineResolutionHeight"),
        )
        for wk, hk in pairs:
            w = get_int(value.get(wk), 0)
            h = get_int(value.get(hk), 0)
            if w > 0 and h > 0:
                found.append((w, h))
        dims = value.get("source_dimensions") or value.get("dimensions") or value.get("resolution")
        if isinstance(dims, (list, tuple)) and len(dims) >= 2:
            w, h = get_int(dims[0], 0), get_int(dims[1], 0)
            if w > 0 and h > 0:
                found.append((w, h))
        elif isinstance(dims, dict):
            _recursive_dimension_candidates(dims, found, depth + 1)
        for child in value.values():
            if isinstance(child, (dict, list)):
                _recursive_dimension_candidates(child, found, depth + 1)
    elif isinstance(value, list):
        for child in value[:300]:
            if isinstance(child, (dict, list)):
                _recursive_dimension_candidates(child, found, depth + 1)


def resolve_occlusion_frame_dimensions(project: Any, analysis: Dict[str, Any], plan_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for wk, hk in (("timelineResolutionWidth", "timelineResolutionHeight"), ("timelineOutputResolutionWidth", "timelineOutputResolutionHeight")):
        w = get_int(safe_call(project, "GetSetting", wk, default=0), 0)
        h = get_int(safe_call(project, "GetSetting", hk, default=0), 0)
        attempts.append({"source": "project.GetSetting", "width_key": wk, "height_key": hk, "width": w, "height": h})
        if w > 0 and h > 0:
            return {"ok": True, "width": w, "height": h, "source": f"project_settings:{wk}/{hk}", "attempts": attempts}
    all_settings = safe_call(project, "GetSetting", default={})
    if isinstance(all_settings, dict):
        for wk, hk in (("timelineResolutionWidth", "timelineResolutionHeight"), ("timelineOutputResolutionWidth", "timelineOutputResolutionHeight")):
            w, h = get_int(all_settings.get(wk), 0), get_int(all_settings.get(hk), 0)
            attempts.append({"source": "project.GetSetting()", "width_key": wk, "height_key": hk, "width": w, "height": h})
            if w > 0 and h > 0:
                return {"ok": True, "width": w, "height": h, "source": f"project_settings_dict:{wk}/{hk}", "attempts": attempts}
    found: List[Tuple[int, int]] = []
    _recursive_dimension_candidates(analysis, found)
    for w, h in found:
        if w > 0 and h > 0:
            attempts.append({"source": "analysis", "width": w, "height": h})
            return {"ok": True, "width": w, "height": h, "source": "analysis_dimensions", "attempts": attempts}
    max_x = max([get_int((e.get("mask_bbox") or [0, 0, 0, 0])[2], 0) for e in plan_events if isinstance(e.get("mask_bbox"), (list, tuple)) and len(e.get("mask_bbox")) >= 4] or [0])
    max_y = max([get_int((e.get("mask_bbox") or [0, 0, 0, 0])[3], 0) for e in plan_events if isinstance(e.get("mask_bbox"), (list, tuple)) and len(e.get("mask_bbox")) >= 4] or [0])
    if max_x <= 1080 and max_y <= 1920 and max_x > 0 and max_y > 0:
        attempts.append({"source": "portrait_fallback_from_bbox_bounds", "max_x": max_x, "max_y": max_y, "width": 1080, "height": 1920})
        return {"ok": True, "width": 1080, "height": 1920, "source": "portrait_1080x1920_fallback", "attempts": attempts, "warning": "Timeline/analysis dimensions were not exposed; used the verified project portrait format fallback."}
    return {"ok": False, "width": 0, "height": 0, "source": None, "attempts": attempts, "error": "Could not resolve frame dimensions for bbox masking."}


def set_track_name_best_effort(timeline: Any, track_type: str, track_index: int, name: str) -> Dict[str, Any]:
    before = safe_call(timeline, "GetTrackName", track_type, track_index, default=None)
    ok = False
    error = None
    try:
        method = getattr(timeline, "SetTrackName", None)
        if method:
            ok = bool(method(track_type, track_index, name))
        else:
            error = "method_missing"
    except Exception as exc:
        error = compact_exception(exc)
    after = safe_call(timeline, "GetTrackName", track_type, track_index, default=None)
    verified = str(after or "") == str(name)
    return {"ok": bool(ok or verified), "verified": verified, "before": before, "after": after, "requested": name, "error": error}


def _bbox_to_fusion_rectangle(bbox: Any, frame_width: int, frame_height: int, padding_px: int) -> Dict[str, Any]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4 or frame_width <= 0 or frame_height <= 0:
        return {"ok": False, "reason": "invalid_bbox_or_dimensions", "bbox": json_safe_value(bbox)}
    x1, y1, x2, y2 = [get_float(v, 0.0) for v in bbox[:4]]
    pad = max(0.0, float(padding_px))
    x1 = max(0.0, min(float(frame_width), x1 - pad))
    y1 = max(0.0, min(float(frame_height), y1 - pad))
    x2 = max(x1 + 1.0, min(float(frame_width), x2 + pad))
    y2 = max(y1 + 1.0, min(float(frame_height), y2 + pad))
    cx = ((x1 + x2) * 0.5) / float(frame_width)
    cy_top = ((y1 + y2) * 0.5) / float(frame_height)
    width = (x2 - x1) / float(frame_width)
    height = (y2 - y1) / float(frame_height)
    return {
        "ok": True,
        "pixel_bbox": [round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)],
        "fusion_center": [round(cx, 7), round(1.0 - cy_top, 7)],
        "fusion_width": round(width, 7),
        "fusion_height": round(height, 7),
        "coordinate_conversion": "top_left_pixels_to_fusion_bottom_left_normalized",
    }


def _set_fusion_input_verified(tool: Any, name: str, value: Any) -> Dict[str, Any]:
    write = set_fusion_input_best_effort(tool, name, value)
    readback = try_read_fusion_input(tool, name)
    verified = bool(readback.get("ok")) and fusion_input_values_equivalent(value, readback.get("value"))
    return {"input": name, "requested": json_safe_value(value), "write": write, "readback": readback, "verified": verified, "ok": verified}


def configure_bbox_foreground_fusion(item: Any, rect: Dict[str, Any], item_name: str, soft_edge: float = 0.0) -> Dict[str, Any]:
    result: Dict[str, Any] = {"attempted": True, "item_name": item_name, "rectangle": rect, "applied": False, "errors": []}
    comp, comp_info = get_or_create_fusion_comp(item)
    result["fusion_comp"] = comp_info
    if not comp:
        result["errors"].append("Could not get/create Fusion comp on generated V4 media clip.")
        return result
    locked = False
    try:
        if method_available(comp, "Lock"):
            safe_call(comp, "Lock", default=None); locked = True
        media_in = find_fusion_tool(comp, ["MediaIn"], ["MediaIn1"])
        media_out = find_fusion_tool(comp, ["MediaOut"], ["MediaOut1"])
        if not media_in or not media_out:
            result["errors"].append("MediaIn1/MediaOut1 were not available in the generated clip Fusion comp.")
            return result
        transparent = safe_call(comp, "AddTool", "Background", -32768, -32768, default=None)
        merge = safe_call(comp, "AddTool", "Merge", -32768, -32768, default=None)
        mask = safe_call(comp, "AddTool", "RectangleMask", -32768, -32768, default=None)
        if not transparent or not merge or not mask:
            result["errors"].append("Could not create Background/Merge/RectangleMask Fusion tools.")
            return result
        result["tool_names"] = {
            "media_in": fusion_tool_name(media_in), "media_out": fusion_tool_name(media_out),
            "background": fusion_tool_name(transparent), "merge": fusion_tool_name(merge), "mask": fusion_tool_name(mask),
        }
        result["name_writes"] = {
            "background": set_fusion_tool_name(transparent, f"{item_name}_Transparent"),
            "merge": set_fusion_tool_name(merge, f"{item_name}_Merge"),
            "mask": set_fusion_tool_name(mask, f"{item_name}_Mask"),
        }
        result["inputs"] = {
            "background_alpha": _set_fusion_input_verified(transparent, "TopLeftAlpha", 0.0),
            "mask_center": _set_fusion_input_verified(mask, "Center", rect.get("fusion_center")),
            "mask_width": _set_fusion_input_verified(mask, "Width", rect.get("fusion_width")),
            "mask_height": _set_fusion_input_verified(mask, "Height", rect.get("fusion_height")),
            "mask_soft_edge": _set_fusion_input_verified(mask, "SoftEdge", max(0.0, float(soft_edge))),
        }
        result["connections"] = {
            "transparent_to_background": connect_fusion_tools(transparent, merge, "Background"),
            "media_to_foreground": connect_fusion_tools(media_in, merge, "Foreground"),
            "mask_to_effect_mask": connect_fusion_tools(mask, merge, "EffectMask"),
            "merge_to_output": connect_fusion_tools(merge, media_out, "Input"),
        }
        required_inputs = [result["inputs"][k].get("ok") for k in ("background_alpha", "mask_center", "mask_width", "mask_height")]
        required_connections = [result["connections"][k].get("ok") for k in ("transparent_to_background", "media_to_foreground", "mask_to_effect_mask", "merge_to_output")]
        result["applied"] = bool(all(required_inputs) and all(required_connections))
        return result
    except Exception as exc:
        result["errors"].append(compact_exception(exc)); result["traceback"] = traceback.format_exc(); return result
    finally:
        if locked and comp:
            safe_call(comp, "Unlock", default=None)


def _mapped_segments_for_event(mapped: List[Tuple[Dict[str, Any], Any]], event: Dict[str, Any]) -> List[Dict[str, Any]]:
    start = get_int(event.get("start_frame"), 0)
    end = max(start + 1, get_int(event.get("end_frame"), start + 1))
    segments: List[Dict[str, Any]] = []
    for cmd, item in mapped:
        item_start, item_end = timeline_item_start(item), timeline_item_end(item)
        overlap_start, overlap_end = max(start, item_start), min(end, item_end)
        if overlap_end <= overlap_start:
            continue
        media_pool_item = safe_call(item, "GetMediaPoolItem", default=None)
        if not media_pool_item:
            continue
        source_clip = cmd.get("source_clip") or {}
        source_base = get_int(source_clip.get("source_start_frame"), item_start)
        source_start = source_base + (overlap_start - item_start)
        duration = overlap_end - overlap_start
        segments.append({
            "command_id": cmd.get("command_id"), "shot_id": cmd.get("shot_id"),
            "source_item": item, "media_pool_item": media_pool_item,
            "record_start": overlap_start, "record_end": overlap_end, "duration": duration,
            "source_start": source_start, "source_end_inclusive": source_start + duration - 1,
        })
    return segments


def _append_media_clip_infos(project: Any, timeline: Any, clip_infos: List[Dict[str, Any]], target_track: int) -> Dict[str, Any]:
    result: Dict[str, Any] = {"attempted": True, "clip_info_count": len(clip_infos), "target_track": target_track, "returned_items": [], "detected_items": [], "errors": []}
    media_pool = safe_call(project, "GetMediaPool", default=None)
    if not media_pool:
        result["errors"].append("project.GetMediaPool() returned no object."); return result
    before = get_track_items(timeline, "video", target_track)
    before_ids = {timeline_item_unique_id(i) for i in before if timeline_item_unique_id(i)}
    api_infos = []
    source_range_semantics: List[Dict[str, Any]] = []
    for row in clip_infos:
        source_start = int(row["source_start"])
        # Existing V1/bbox callers retain their legacy inclusive endFrame value.
        # RGBA image sequences explicitly override this with a half-open API end
        # because the Resolve 21 runtime proved endFrame=4 yields only 4 frames
        # for a five-frame [0, 5) sequence.
        source_end_api = int(row.get("source_end_frame_api", row["source_end_inclusive"]))
        api_infos.append({
            "mediaPoolItem": row["media_pool_item"],
            "startFrame": source_start,
            "endFrame": source_end_api,
            "mediaType": 1,
            "trackIndex": int(target_track),
            "recordFrame": int(row["record_start"]),
        })
        source_range_semantics.append({
            "source_start": source_start,
            "source_end_frame_api": source_end_api,
            "source_end_inclusive_diagnostic": int(row.get("source_end_inclusive", source_end_api)),
            "api_end_semantics": str(row.get("api_end_semantics") or "legacy_caller_defined"),
        })
    result["api_clip_infos"] = [{k: (safe_call(v, "GetName", default=None) if k == "mediaPoolItem" else v) for k, v in info.items()} for info in api_infos]
    result["source_range_semantics"] = source_range_semantics
    returned = None
    try:
        returned = media_pool.AppendToTimeline(api_infos)
    except Exception as exc:
        result["errors"].append(compact_exception(exc))
    if isinstance(returned, (list, tuple)):
        result["returned_items"] = list(returned)
    elif returned is not None and is_timeline_item_object(returned):
        result["returned_items"] = [returned]
    time.sleep(0.15)
    after = get_track_items(timeline, "video", target_track)
    detected = []
    for item in after:
        uid = timeline_item_unique_id(item)
        if uid and uid not in before_ids:
            detected.append(item)
    if not detected and len(after) > len(before):
        detected = after[len(before):]
    items = result["returned_items"] if len(result["returned_items"]) == len(clip_infos) else detected
    items = sorted(items, key=lambda i: (timeline_item_start(i), timeline_item_end(i)))
    result["detected_items"] = items
    result["before_count"] = len(before); result["after_count"] = len(after)
    result["ok"] = len(items) == len(clip_infos)
    if not result["ok"]:
        result["errors"].append(f"AppendToTimeline expected {len(clip_infos)} generated items but detected {len(items)}.")
    return result


def apply_caption_occlusion_bbox_fallback(
    project: Any,
    timeline: Any,
    mapped: List[Tuple[Dict[str, Any], Any]],
    generic: Dict[str, Any],
    args: argparse.Namespace,
    fps: float,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    target_track = max(2, get_int(getattr(args, "caption_occlusion_target_track", 4), 4))
    prefix = str(getattr(args, "caption_occlusion_item_prefix", "VC_OCCLUSION_BBOX_") or "VC_OCCLUSION_BBOX_")
    result: Dict[str, Any] = {
        "enabled": True, "mode": "bbox_fallback_apply", "sequence_step": 9,
        "target_track": target_track, "item_prefix": prefix, "events": [], "warnings": [], "errors": [],
        "timeline_mutation_attempted": True,
    }
    result["track_setup"] = ensure_video_track(timeline, target_track)
    if not result["track_setup"].get("ok"):
        result["status"] = "failed_track_setup"; result["errors"].append("Could not create/access the requested V4 track."); return result
    result["track_name"] = set_track_name_best_effort(timeline, "video", target_track, str(getattr(args, "caption_occlusion_track_name", "VC_OCCLUSION_V4")))
    before_core = snapshot_core_tracks(timeline, max(1, get_int(args.video_track, 1)), max(1, get_int(args.audio_track, 1)))
    old_items = find_items_by_name_prefix(timeline, prefix) if getattr(args, "caption_occlusion_clear_old_v4", True) else []
    result["clear_old"] = delete_timeline_items(timeline, old_items) if old_items else {"attempted": False, "requested_count": 0, "deleted": 0}
    try:
        analysis = load_json(str(plan.get("analysis_path"))) if plan.get("analysis_path") and Path(str(plan.get("analysis_path"))).exists() else {}
    except Exception:
        analysis = {}
    dims = resolve_occlusion_frame_dimensions(project, analysis, list(plan.get("events") or []))
    result["frame_dimensions"] = dims
    if not dims.get("ok"):
        result["status"] = "failed_missing_dimensions"; result["errors"].append(dims.get("error")); return result
    events = list(plan.get("events") or [])
    max_events = max(0, get_int(getattr(args, "caption_occlusion_max_events", 0), 0))
    if max_events > 0:
        events = events[:max_events]
    result["requested_event_count"] = len(events)
    clip_rows: List[Dict[str, Any]] = []
    event_rows: List[Dict[str, Any]] = []
    for event_index, event in enumerate(events, start=1):
        rect = _bbox_to_fusion_rectangle(event.get("mask_bbox"), get_int(dims.get("width"), 0), get_int(dims.get("height"), 0), get_int(getattr(args, "caption_occlusion_bbox_padding_px", 4), 4))
        row = {"event_index": event_index, "cue_id": event.get("cue_id"), "text": event.get("text"), "start_frame": event.get("start_frame"), "end_frame": event.get("end_frame"), "rectangle": rect, "segments": []}
        if not rect.get("ok"):
            row["ok"] = False; row["error"] = rect.get("reason"); event_rows.append(row)
            if getattr(args, "caption_occlusion_stop_on_first_failure", True): break
            continue
        segments = _mapped_segments_for_event(mapped, event)
        if not segments:
            row["ok"] = False; row["error"] = "No media-backed V1 segment overlaps this occlusion event."; event_rows.append(row)
            if getattr(args, "caption_occlusion_stop_on_first_failure", True): break
            continue
        for segment_index, segment in enumerate(segments, start=1):
            item_name = f"{prefix}{event.get('cue_id')}_{segment_index:02d}"
            clip_rows.append({**segment, "event": event, "event_index": event_index, "segment_index": segment_index, "item_name": item_name, "rectangle": rect})
            row["segments"].append({k: json_safe_value(v) for k, v in segment.items() if k not in ("source_item", "media_pool_item")})
        row["ok"] = True; event_rows.append(row)
    result["events"] = event_rows
    if not clip_rows:
        result["status"] = "failed_no_appendable_segments"; result["errors"].append("No V4 bbox fallback segments were appendable."); return result
    append = _append_media_clip_infos(project, timeline, clip_rows, target_track)
    result["append"] = {k: v for k, v in append.items() if k not in ("returned_items", "detected_items")}
    items = append.get("detected_items") or []
    if not append.get("ok"):
        result["status"] = "failed_append"; result["errors"].extend(append.get("errors") or []); return result
    generated_rows = []
    failed = 0
    for clip_row, item in zip(clip_rows, items):
        name_result = set_timeline_item_name(item, clip_row["item_name"])
        actual_start, actual_end = timeline_item_start(item), timeline_item_end(item)
        actual_duration = timeline_item_duration(item)
        expected_start, expected_end = get_int(clip_row["record_start"], 0), get_int(clip_row["record_end"], 0)
        expected_duration = max(1, expected_end - expected_start)
        # Resolve's AppendToTimeline endFrame is inclusive while TimelineItem.GetEnd()
        # can surface either inclusive or exclusive semantics depending on item type.
        range_ok = bool(
            actual_start == expected_start
            and actual_duration == expected_duration
            and actual_end in {expected_end, expected_end - 1}
        )
        fusion = configure_bbox_foreground_fusion(item, clip_row["rectangle"], clip_row["item_name"], get_float(getattr(args, "caption_occlusion_soft_edge", 0.0), 0.0))
        ok = bool(range_ok and fusion.get("applied"))
        rollback = {"attempted": False}
        if not ok:
            rollback = delete_timeline_items(timeline, [item])
        row = {
            "cue_id": (clip_row.get("event") or {}).get("cue_id"), "text": (clip_row.get("event") or {}).get("text"),
            "item_name": clip_row["item_name"], "name_write": name_result,
            "expected_range": [expected_start, expected_end],
            "actual_range": [actual_start, actual_end],
            "expected_duration": expected_duration,
            "actual_duration": actual_duration,
            "accepted_end_conventions": [expected_end, expected_end - 1],
            "range_ok": range_ok,
            "track": timeline_item_track_info(item), "rectangle": clip_row["rectangle"],
            "fusion": fusion, "rollback": rollback, "ok": ok,
        }
        generated_rows.append(row)
        hard_debug("CAPTION_OCCLUSION_BBOX_ITEM", {"cue_id": row.get("cue_id"), "item_name": row.get("item_name"), "range_ok": range_ok, "fusion_applied": fusion.get("applied"), "ok": ok})
        if not ok:
            failed += 1
            if getattr(args, "caption_occlusion_stop_on_first_failure", True):
                break
    result["generated_items"] = generated_rows
    result["created_count"] = len(generated_rows)
    result["ready_count"] = sum(1 for row in generated_rows if row.get("ok"))
    result["failed_count"] = failed + max(0, len(clip_rows) - len(generated_rows))
    after_core = snapshot_core_tracks(timeline, max(1, get_int(args.video_track, 1)), max(1, get_int(args.audio_track, 1)))
    result["core_track_integrity"] = compare_core_track_snapshots(before_core, after_core)
    result["ok"] = bool(result["ready_count"] == len(clip_rows) and result["failed_count"] == 0 and result["core_track_integrity"].get("ok"))
    result["status"] = "applied_bbox_fallback" if result["ok"] else "partial_or_failed_bbox_fallback"
    result["fidelity"] = {
        "backend": "duplicate_v1_media_plus_fusion_rectangle_mask",
        "quality": "bbox_fallback",
        "limitation": "This restores the original V1 pixels over V3 inside the detected bbox. It is not a subject silhouette matte and can hide caption pixels that are not directly behind the subject.",
    }
    return result


# -----------------------------
# Controller
# -----------------------------



def should_defer_step_2f_after_v3_recovery(
    recovery_triggered: bool,
    recovery_only_requested: bool,
    coverage_ok: bool,
) -> bool:
    """Defer V4 only while the rebuilt V3 still fails exact verification.

    v0.9.0 deferred every successful recovery run. That left a valid V3 but no
    caption-occlusion plan or V4 item, so the external Step 2F validator emitted
    a cascade of unrelated plan/count failures. Once exact V3 coverage is true,
    the same Resolve run is safe to continue into Step 2F.
    """
    return bool(recovery_triggered and recovery_only_requested and not coverage_ok)


def run_controller(args: argparse.Namespace) -> Dict[str, Any]:
    run_id = make_run_id()
    hard_debug("RUN_ID_CREATED", {"run_id": run_id})
    hard_debug("LOAD_GENERIC_START", {"path": args.generic, "exists": os.path.exists(args.generic)})
    generic = load_json(args.generic)
    hard_debug("LOAD_GENERIC_OK", {
        "keys": list(generic.keys()),
        "schema": generic.get("schema"),
        "success": generic.get("success"),
        "timeline_count": len(generic.get("timeline") or []),
    })

    hard_debug("VALIDATE_GENERIC_START")
    errors = validate_generic_commands(generic)
    hard_debug("VALIDATE_GENERIC_DONE", {"errors": errors})
    if errors:
        return {"ok": False, "errors": errors}

    fps = get_fps(generic)
    commands: List[Dict[str, Any]] = list(generic.get("timeline") or [])
    hard_debug("GENERIC_PARSED", {"fps": fps, "commands_count": len(commands)})

    hard_debug("GET_RESOLVE_CONTEXT_START")
    resolve, project_manager, project, timeline = get_resolve_context()
    hard_debug("GET_RESOLVE_CONTEXT_DONE")

    hard_debug("TIMELINE_INSPECTION_START")
    timeline_name = safe_call(timeline, "GetName", default="")
    hard_debug("TIMELINE_NAME_READ", {"timeline_name": timeline_name})

    video_items = get_track_items(timeline, "video", args.video_track)
    hard_debug("VIDEO_ITEMS_READ", {"video_track": args.video_track, "count": len(video_items)})

    audio_items = get_track_items(timeline, "audio", args.audio_track)
    hard_debug("AUDIO_ITEMS_READ", {"audio_track": args.audio_track, "count": len(audio_items)})

    effective_timeline_backend = infer_effective_timeline_backend(args, timeline_name, commands, video_items)
    hard_debug("TIMELINE_BACKEND_INFERRED", {
        "requested": getattr(args, "timeline_backend", "auto"),
        "effective": effective_timeline_backend,
        "timeline_name": timeline_name,
        "video_items_count": len(video_items),
        "commands_count": len(commands),
    })

    report: Dict[str, Any] = {
        "ok": True,
        "controller_version": VERSION,
        "runtime_identity": runtime_script_identity(),
        "created_at_unix": now_unix(),
        "run_id": run_id,
        "project_name": safe_call(project, "GetName", default=None),
        "timeline_name": timeline_name,
        "generic_path": os.path.abspath(args.generic),
        "controller_config": getattr(args, "resolve_controller_config", {"loaded": False, "path": None}),
        "fps": fps,
        "tracks": {
            "video_track_index": args.video_track,
            "audio_track_index": args.audio_track,
            "video_items_count": len(video_items),
            "audio_items_count": len(audio_items),
            "commands_count": len(commands),
        },
        "options": {
            "config": getattr(args, "config", None),
            "config_loaded": bool((getattr(args, "resolve_controller_config", {}) or {}).get("loaded")),
            "dry_run": args.dry_run,
            "apply_zoom": args.apply_zoom,
            "animated_zoom": args.animated_zoom,
            "zoom_mode": args.zoom_mode,
            "zoom_static_fallback": args.zoom_static_fallback,
            "clear_old_vc_zoom_tools": args.clear_old_vc_zoom_tools,
            "clear_old_vc_zoom_scope": args.clear_old_vc_zoom_scope,
            "attempt_speed": args.attempt_speed,
            "apply_subtitles": getattr(args, "apply_subtitles", False),
            "subtitle_track": getattr(args, "subtitle_track", 2),
            "subtitle_title_name": getattr(args, "subtitle_title_name", "Text+"),
            "clear_old_vc_subtitles": getattr(args, "clear_old_vc_subtitles", False),
            "max_subtitles": getattr(args, "max_subtitles", 0),
            "subtitle_track_guard": getattr(args, "subtitle_track_guard", True),
            "subtitle_use_mark_in_out": getattr(args, "subtitle_use_mark_in_out", True),
            "subtitle_strict_timing": getattr(args, "subtitle_strict_timing", True),
            "subtitle_stop_on_range_fail": getattr(args, "subtitle_stop_on_range_fail", True),
            "verify_captions": getattr(args, "verify_captions", False),
            "caption_track": getattr(args, "caption_track", getattr(args, "subtitle_track", 2)),
            "caption_title_name": getattr(args, "caption_title_name", getattr(args, "subtitle_title_name", "Text+")),
            "caption_verify_sample_limit": getattr(args, "caption_verify_sample_limit", 10),
            "caption_timing_tolerance_frames": getattr(args, "caption_timing_tolerance_frames", 1),
            "caption_expected_report": getattr(args, "caption_expected_report", None),
            "caption_property_write_test": getattr(args, "caption_property_write_test", False),
            "apply_caption_textplus": getattr(args, "apply_caption_textplus", False),
            "verify_caption_textplus": getattr(args, "verify_caption_textplus", False),
            "caption_textplus_track": getattr(args, "caption_textplus_track", getattr(args, "caption_track", 2)),
            "caption_textplus_track_name": getattr(args, "caption_textplus_track_name", "VC_TEXTPLUS_V3"),
            "caption_textplus_expected_count": getattr(args, "caption_textplus_expected_count", 0),
            "caption_recovery_only_when_missing": getattr(args, "caption_recovery_only_when_missing", True),
            "caption_recovery_clean_target_track": getattr(args, "caption_recovery_clean_target_track", True),
            "caption_static_title_policy": getattr(args, "caption_static_title_policy", "keep"),
            "caption_restore_static_titles_before_apply": getattr(args, "caption_restore_static_titles_before_apply", True),
            "caption_allow_static_title_item_writes": getattr(args, "caption_allow_static_title_item_writes", False),
            "caption_fill_color_policy": getattr(args, "caption_fill_color_policy", "detected"),
            "apply_caption_occlusion": getattr(args, "apply_caption_occlusion", False),
            "caption_occlusion_plan_only": getattr(args, "caption_occlusion_plan_only", True),
            "caption_occlusion_analysis": getattr(args, "caption_occlusion_analysis", None),
            "caption_occlusion_plan_output": getattr(args, "caption_occlusion_plan_output", None),
            "caption_occlusion_mask_root": getattr(args, "caption_occlusion_mask_root", None),
            "caption_occlusion_min_score": getattr(args, "caption_occlusion_min_score", 0.50),
            "caption_occlusion_asset_mode": getattr(args, "caption_occlusion_asset_mode", "rgba_sequence"),
            "caption_occlusion_bbox_fallback": getattr(args, "caption_occlusion_bbox_fallback", False),
            "caption_occlusion_require_editor_ready_assets": getattr(args, "caption_occlusion_require_editor_ready_assets", True),
            "caption_occlusion_reuse_media_pool_items": getattr(args, "caption_occlusion_reuse_media_pool_items", True),
            "caption_occlusion_set_straight_alpha": getattr(args, "caption_occlusion_set_straight_alpha", True),
            "caption_occlusion_alpha_mode": getattr(args, "caption_occlusion_alpha_mode", "Straight"),
            "caption_occlusion_verify_settle_timeout_sec": getattr(args, "caption_occlusion_verify_settle_timeout_sec", 1.50),
            "caption_occlusion_verify_poll_interval_sec": getattr(args, "caption_occlusion_verify_poll_interval_sec", 0.10),
            "caption_occlusion_finalize_major_step_2": getattr(args, "caption_occlusion_finalize_major_step_2", False),
            "caption_occlusion_finalization_output": getattr(args, "caption_occlusion_finalization_output", None),
            "caption_occlusion_finalization_state": getattr(args, "caption_occlusion_finalization_state", None),
            "caption_occlusion_prior_step_2f_validation": getattr(args, "caption_occlusion_prior_step_2f_validation", None),
            "caption_occlusion_require_creation_and_reuse_passes": getattr(args, "caption_occlusion_require_creation_and_reuse_passes", True),
            "caption_occlusion_visual_review_frame": getattr(args, "caption_occlusion_visual_review_frame", 0),
            "caption_occlusion_require_v3_cue_linkage": getattr(args, "caption_occlusion_require_v3_cue_linkage", True),
            "caption_occlusion_rollback_on_failure": getattr(args, "caption_occlusion_rollback_on_failure", True),
            "caption_occlusion_clear_legacy_bbox_v4": getattr(args, "caption_occlusion_clear_legacy_bbox_v4", True),
            "caption_occlusion_legacy_item_prefix": getattr(args, "caption_occlusion_legacy_item_prefix", "VC_OCCLUSION_BBOX_"),
            "caption_occlusion_target_track": getattr(args, "caption_occlusion_target_track", 4),
            "caption_occlusion_max_events": getattr(args, "caption_occlusion_max_events", 0),
            "caption_occlusion_bbox_padding_px": getattr(args, "caption_occlusion_bbox_padding_px", 4),
            "caption_occlusion_soft_edge": getattr(args, "caption_occlusion_soft_edge", 0.0),
            "caption_occlusion_clear_old_v4": getattr(args, "caption_occlusion_clear_old_v4", True),
            "caption_occlusion_stop_on_first_failure": getattr(args, "caption_occlusion_stop_on_first_failure", True),
            "caption_occlusion_track_name": getattr(args, "caption_occlusion_track_name", "VC_OCCLUSION_V4"),
            "caption_occlusion_item_prefix": getattr(args, "caption_occlusion_item_prefix", "VC_OCCLUSION_RGBA_"),
            "caption_occlusion_auto_rebuild_textplus_if_missing": getattr(args, "caption_occlusion_auto_rebuild_textplus_if_missing", True),
            "caption_occlusion_require_textplus_track": getattr(args, "caption_occlusion_require_textplus_track", True),
            "caption_color_low_confidence_threshold": getattr(args, "caption_color_low_confidence_threshold", 0.70),
            "caption_color_min_luma_gap": getattr(args, "caption_color_min_luma_gap", 0.12),
            "caption_animation": getattr(args, "caption_animation", False),
            "caption_animation_mode": getattr(args, "caption_animation_mode", "conservative"),
            "caption_animation_sample_limit": getattr(args, "caption_animation_sample_limit", 0),
            "max_caption_textplus": getattr(args, "max_caption_textplus", 0),
            "caption_compact_report": getattr(args, "caption_compact_report", True),
            "caption_checkpoint_interval": getattr(args, "caption_checkpoint_interval", 10),
            "caption_stop_on_first_failure": getattr(args, "caption_stop_on_first_failure", True),
            "clear_old_vc_textplus": getattr(args, "clear_old_vc_textplus", False),
            "caption_write_test": getattr(args, "caption_write_test", False),
            "caption_style": getattr(args, "caption_style", None),
            "caption_textplus_probe_only": getattr(args, "caption_textplus_probe_only", False),
            "caption_probe_count": getattr(args, "caption_probe_count", 1),
            "caption_probe_text": getattr(args, "caption_probe_text", None),
            "caption_probe_cue_id": getattr(args, "caption_probe_cue_id", None),
            "caption_font_fallback_order": getattr(args, "caption_font_fallback_order", DEFAULT_CAPTION_FONT_FALLBACK_ORDER),
            "caption_keep_failed_probe_item": getattr(args, "caption_keep_failed_probe_item", False),
            "caption_style_probe_only": getattr(args, "caption_style_probe_only", False),
            "caption_shading_probe_only": getattr(args, "caption_shading_probe_only", False),
            "caption_apply_outline": getattr(args, "caption_apply_outline", False),
            "caption_apply_shadow": getattr(args, "caption_apply_shadow", False),
            "caption_outline_element": getattr(args, "caption_outline_element", 2),
            "caption_shadow_element": getattr(args, "caption_shadow_element", 3),
            "caption_outline_thickness": getattr(args, "caption_outline_thickness", None),
            "caption_outline_width_scale": getattr(args, "caption_outline_width_scale", 1.0),
            "caption_shadow_offset_x": getattr(args, "caption_shadow_offset_x", 0.003),
            "caption_shadow_offset_y": getattr(args, "caption_shadow_offset_y", 0.003),
            "caption_shadow_opacity": getattr(args, "caption_shadow_opacity", None),
            "caption_shadow_softness": getattr(args, "caption_shadow_softness", None),
            "caption_force_font_name": getattr(args, "caption_force_font_name", None),
            "caption_force_font_style": getattr(args, "caption_force_font_style", None),
            "caption_force_textplus_size": getattr(args, "caption_force_textplus_size", None),
            "caption_textplus_size_scale": getattr(args, "caption_textplus_size_scale", 1.5),
            "caption_force_position_from_style": getattr(args, "caption_force_position_from_style", True),
            "caption_use_per_cue_style_events": getattr(args, "caption_use_per_cue_style_events", True),
            "caption_disable_duration_strictness_for_probe": getattr(args, "caption_disable_duration_strictness_for_probe", False),
            "add_debug_markers": args.add_debug_markers,
            "no_debug_markers": getattr(args, "no_debug_markers", False),
            "clear_debug_markers": getattr(args, "clear_debug_markers", False),
            "timeline_backend": getattr(args, "timeline_backend", "auto"),
            "effective_timeline_backend": effective_timeline_backend,
            "verify_only": args.verify_only,
        },
        "verification": [],
        "clips": [],
        "summary": {
            "mapped_clips": 0,
            "controller_ran_marker_added": 0,
            "zoom_ops": 0,
            "zoom_applied": 0,
            "zoom_animated_applied": 0,
            "zoom_static_applied": 0,
            "zoom_tools_reused": 0,
            "zoom_tools_created": 0,
            "zoom_tools_replaced": 0,
            "zoom_tools_deleted": 0,
            "speed_ops": 0,
            "speed_applied": 0,
            "transition_ops": 0,
            "transition_markers_added": 0,
            "subtitle_clips_input": len(generic.get("subtitle_clips") or []),
            "subtitle_ops": 0,
            "subtitle_created": 0,
            "subtitle_failed": 0,
            "caption_textplus_ops": 0,
            "caption_textplus_created": 0,
            "caption_textplus_reused": 0,
            "caption_textplus_augmented": 0,
            "caption_textplus_failed": 0,
            "caption_animation_keyframes": 0,
            "caption_occlusion_ops": 0,
            "caption_occlusion_created": 0,
            "caption_occlusion_reused": 0,
            "caption_occlusion_failed": 0,
            "debug_markers_added": 0,
            "debug_markers_removed": 0,
            "warnings": [],
        },
    }

    if getattr(args, "clear_debug_markers", False) and not args.dry_run and not args.verify_only:
        clear_result = clear_video_cloner_debug_markers(timeline)
        report["clear_debug_markers"] = clear_result
        report["summary"]["debug_markers_removed"] = get_int(clear_result.get("deleted_count"), 0)

    if getattr(args, "verify_captions", False):
        report["caption_verification"] = verify_imported_caption_track(
            timeline=timeline,
            generic=generic,
            args=args,
            fps=fps,
        )
        caption_warnings = (report.get("caption_verification") or {}).get("warnings") or []
        if caption_warnings:
            report["summary"]["warnings"].extend([f"caption_verification: {w}" for w in caption_warnings])
        caption_errors = (report.get("caption_verification") or {}).get("errors") or []
        if caption_errors:
            report["summary"]["warnings"].extend([f"caption_verification_error: {json_safe_value(e)}" for e in caption_errors])
    else:
        report["caption_verification"] = {
            "enabled": False,
            "reason": "--verify-captions not used",
            "caption_track_index": getattr(args, "caption_track", getattr(args, "subtitle_track", 2)),
        }

    if not video_items:
        report["ok"] = False
        report["summary"]["warnings"].append("No video clips found on selected video track.")
        return report

    if args.add_debug_markers and not args.dry_run:
        first_frame = get_int(timeline_item_summary(video_items[0]).get("start"), 0)
        controller_marker = add_controller_ran_marker(timeline, first_frame, os.path.abspath(args.generic), run_id)
        report["controller_ran_marker"] = controller_marker
        if controller_marker.get("applied"):
            report["summary"]["controller_ran_marker_added"] += 1

    mapped, mapping_info = map_commands_to_clips_stable(
        commands=commands,
        clips=video_items,
        timeline_backend=effective_timeline_backend,
        duration_tolerance_frames=args.duration_tolerance_frames,
    )
    report["mapping"] = mapping_info
    report["tracks"]["media_clip_like_items_count"] = mapping_info.get("media_clip_like_items_count")
    report["tracks"]["transition_like_items_count"] = mapping_info.get("transition_like_items_count")
    report["tracks"]["title_like_items_count"] = mapping_info.get("title_like_items_count")

    if mapping_info.get("warnings"):
        report["summary"]["warnings"].extend(mapping_info.get("warnings") or [])

    if len(video_items) != len(commands) and effective_timeline_backend != "fcpxml_full":
        report["summary"]["warnings"].append(
            f"Clip count mismatch: Resolve V{args.video_track} has {len(video_items)} clips, generic commands has {len(commands)}. Legacy mapping uses min count by order."
        )
    elif len(video_items) != len(commands) and effective_timeline_backend == "fcpxml_full":
        report["summary"]["warnings"].append(
            f"Resolve V{args.video_track} has {len(video_items)} timeline items, generic commands has {len(commands)}. "
            f"This is expected when full FCPXML imports native transitions as separate items. "
            f"Controller mapped only {mapping_info.get('media_clip_like_items_count')} media-backed clip items."
        )

    report["summary"]["mapped_clips"] = len(mapped)

    hard_debug("CLIP_LOOP_START", {"mapped_count": len(mapped)})
    for index, (cmd, item) in enumerate(mapped, start=1):
        hard_debug("CLIP_START", {"index": index, "command_id": cmd.get("command_id"), "shot_id": cmd.get("shot_id")})
        item_info = timeline_item_summary(item)
        hard_debug("CLIP_ITEM_SUMMARY_OK", {"index": index, "item_info": item_info})
        expected_duration = command_duration_frames(cmd, fps)
        actual_duration = get_int(item_info.get("duration"), 0)
        duration_delta = actual_duration - expected_duration if actual_duration else None

        action = cmd.get("action") or {}
        action_type = action.get("type")
        source_clip = cmd.get("source_clip") or {}
        source_start_frame = get_int(source_clip.get("source_start_frame"), 0)

        clip_report: Dict[str, Any] = {
            "index": index,
            "command_id": cmd.get("command_id"),
            "shot_id": cmd.get("shot_id"),
            "action_type": action_type,
            "timeline_item": item_info,
            "mapping": {
                "strategy": (report.get("mapping") or {}).get("strategy"),
                "effective_timeline_backend": effective_timeline_backend,
            },
            "expected": {
                "source_start_frame": source_start_frame,
                "duration_frames": expected_duration,
            },
            "verification": {
                "duration_delta_frames": duration_delta,
                "duration_match_loose": duration_delta is not None and abs(duration_delta) <= args.duration_tolerance_frames,
            },
            "layers": {},
        }

        if duration_delta is None or abs(duration_delta) > args.duration_tolerance_frames:
            report["verification"].append({
                "level": "warning",
                "clip_index": index,
                "shot_id": cmd.get("shot_id"),
                "message": f"Duration mismatch. Expected {expected_duration}, got {actual_duration}.",
            })

        # Add debug timeline markers at clip starts, independent of actual effect application.
        if args.add_debug_markers and not args.dry_run:
            marker_payload = {
                "controller": VERSION,
                "shot_id": cmd.get("shot_id"),
                "command_id": cmd.get("command_id"),
                "action": action,
                "operations": cmd.get("operations") or [],
            }
            marker_name = f"VC_DEBUG_{cmd.get('shot_id')}_{action_type}_{short_run_id(run_id)}"
            marker_result = add_non_conflicting_timeline_marker(
                timeline=timeline,
                preferred_frame=get_int(item_info.get("start"), 0),
                color="Blue",
                name=marker_name,
                note=marker_note(marker_payload),
                duration=max(1, min(expected_duration, int(round(fps * 0.5)))),
                custom_data=f"video_cloner:debug:{cmd.get('command_id')}:{run_id}",
                min_frame=get_int(item_info.get("start"), 0),
                max_frame=max(get_int(item_info.get("start"), 0), get_int(item_info.get("end"), 0) - 1),
                search_radius=max(1, min(12, expected_duration - 1)),
                prefer_forward=True,
            )
            clip_report["layers"]["debug_marker"] = marker_result
            if marker_result.get("applied"):
                report["summary"]["debug_markers_added"] += 1

        # Zoom layer.
        if get_operation(cmd, "transform_zoom"):
            report["summary"]["zoom_ops"] += 1
            if args.apply_zoom and not args.dry_run and not args.verify_only:
                zoom_result = apply_zoom(
                    item=item,
                    cmd=cmd,
                    mode=args.zoom_mode,
                    animated=args.animated_zoom,
                    static_fallback=args.zoom_static_fallback,
                    fps=fps,
                    expected_duration_frames=expected_duration,
                    clear_old_vc_zoom_tools=args.clear_old_vc_zoom_tools,
                    clear_old_vc_zoom_scope=args.clear_old_vc_zoom_scope,
                )
            else:
                zoom_result = {"attempted": False, "reason": "apply_zoom disabled, dry_run, or verify_only"}
            clip_report["layers"]["zoom"] = zoom_result
            if zoom_result.get("applied"):
                report["summary"]["zoom_applied"] += 1
                if zoom_result.get("applied_mode") == "fusion_keyframed_zoom":
                    report["summary"]["zoom_animated_applied"] += 1
                elif zoom_result.get("applied_mode") == "static_clip_property_zoom":
                    report["summary"]["zoom_static_applied"] += 1

                tm = ((zoom_result.get("animated") or {}).get("tool_management") or {})
                if tm.get("reused"):
                    report["summary"]["zoom_tools_reused"] += 1
                if tm.get("created"):
                    report["summary"]["zoom_tools_created"] += 1
                if tm.get("replaced"):
                    report["summary"]["zoom_tools_replaced"] += 1
                report["summary"]["zoom_tools_deleted"] += get_int(tm.get("deleted_count"), 0)

        # Speed layer.
        if get_operation(cmd, "speed_ramp"):
            report["summary"]["speed_ops"] += 1
            if args.attempt_speed and not args.dry_run and not args.verify_only:
                speed_result = apply_speed_change_attempt(item, cmd)
            else:
                speed_result = {"attempted": False, "reason": "attempt_speed disabled, dry_run, or verify_only"}
            clip_report["layers"]["speed"] = speed_result
            if speed_result.get("applied"):
                report["summary"]["speed_applied"] += 1

        # Transition layer. In full FCPXML mode, transitions are already compiled
        # into the timeline as native FCPXML transition items. The controller must
        # not try to process them as clip operations, otherwise V1 mapping and
        # diagnostics become noisy/incorrect.
        if get_operation(cmd, "transition_hint"):
            report["summary"]["transition_ops"] += 1
            if effective_timeline_backend == "fcpxml_full":
                transition_result = {
                    "attempted": False,
                    "operation": "transition_hint",
                    "applied": False,
                    "reason": "skipped_fcpxml_full_backend",
                    "limitation": "Transitions are expected to be compiled into the imported full FCPXML timeline. Controller handles zoom/speed/VFX only.",
                    "requested": (get_operation(cmd, "transition_hint") or {}).get("parameters") or {},
                }
            else:
                transition_result = transition_report_only(cmd)
                if args.add_debug_markers and not args.dry_run:
                    trans_op = get_operation(cmd, "transition_hint") or {}
                    trans_params = trans_op.get("parameters") or {}
                    marker_result = add_non_conflicting_timeline_marker(
                        timeline=timeline,
                        preferred_frame=max(0, get_int(item_info.get("end"), 0) - 1),
                        color="Red",
                        name=f"VC_TRANSITION_{trans_params.get('transition_type', 'hint')}_{short_run_id(run_id)}",
                        note=marker_note({
                            "controller": VERSION,
                            "run_id": run_id,
                            "shot_id": cmd.get("shot_id"),
                            "command_id": cmd.get("command_id"),
                            "transition": trans_params,
                        }),
                        duration=max(1, int(round(fps * 0.25))),
                        custom_data=f"video_cloner:transition:{cmd.get('command_id')}:{run_id}",
                        min_frame=max(0, get_int(item_info.get("start"), 0)),
                        max_frame=max(0, get_int(item_info.get("end"), 0) + 12),
                        search_radius=18,
                        prefer_forward=False,
                    )
                    transition_result["debug_marker"] = marker_result
                    if marker_result.get("applied"):
                        report["summary"]["transition_markers_added"] += 1
            clip_report["layers"]["transition"] = transition_result

        report["clips"].append(clip_report)
        hard_debug("CLIP_DONE", {
            "index": index,
            "command_id": cmd.get("command_id"),
            "layers": list(clip_report.get("layers", {}).keys()),
        })

    # Step 1 — deterministic V3 recovery. Resolve the generated caption track by
    # identity/content, require exactly one title-like item per generic cue, and
    # isolate recovery from V4 mutation in the same run.
    expected_textplus_count = max(
        1,
        get_int(
            getattr(args, "caption_textplus_expected_count", 0),
            len(expected_caption_cues_from_generic(generic, fps)),
        ) or len(expected_caption_cues_from_generic(generic, fps)),
    )
    requested_textplus_track = max(1, get_int(getattr(args, "caption_textplus_track", 3), 3))
    desired_textplus_track_name = str(getattr(args, "caption_textplus_track_name", "VC_TEXTPLUS_V3") or "VC_TEXTPLUS_V3")
    textplus_track_resolution = resolve_or_create_named_video_track(
        timeline=timeline,
        requested_index=requested_textplus_track,
        desired_name=desired_textplus_track_name,
        generated_prefix=VC_CAPTION_TEXTPLUS_PREFIX,
    )
    textplus_track_index = max(1, get_int(textplus_track_resolution.get("track_index"), requested_textplus_track))
    args.caption_textplus_track = textplus_track_index
    textplus_coverage_before = verify_caption_textplus_track_coverage(
        timeline=timeline,
        track_index=textplus_track_index,
        generic=generic,
        fps=fps,
        tolerance_frames=max(1, get_int(getattr(args, "caption_timing_tolerance_frames", 2), 2)),
    )
    dependency_enabled = bool(
        getattr(args, "apply_caption_occlusion", False)
        and not getattr(args, "caption_occlusion_plan_only", False)
        and getattr(args, "caption_occlusion_require_textplus_track", True)
    )
    explicit_textplus_apply = bool(getattr(args, "apply_caption_textplus", False))
    needs_recovery = not bool(textplus_coverage_before.get("coverage_ok"))
    auto_rebuild = bool(getattr(args, "caption_occlusion_auto_rebuild_textplus_if_missing", True))
    recovery_triggered = bool(needs_recovery and (explicit_textplus_apply or (dependency_enabled and auto_rebuild)))
    recovery_only_requested = bool(
        recovery_triggered
        and getattr(args, "caption_recovery_only_when_missing", False)
    )
    # This is provisional until the post-rebuild exact coverage check completes.
    recovery_only_run = recovery_only_requested
    caption_dependency_guard = {
        "enabled": dependency_enabled,
        "workflow_step": "Step 1 — deterministic V3 Text+ recovery",
        "track_resolution": textplus_track_resolution,
        "textplus_track": textplus_track_index,
        "textplus_track_name": get_track_name_best_effort(timeline, "video", textplus_track_index),
        "expected_count": expected_textplus_count,
        "coverage_before": textplus_coverage_before,
        "existing_count_before": get_int(textplus_coverage_before.get("matched_count"), 0),
        "candidate_count_before": get_int(textplus_coverage_before.get("candidate_title_count"), 0),
        "extra_count_before": get_int(textplus_coverage_before.get("extra_candidate_count"), 0),
        "auto_rebuild_enabled": auto_rebuild,
        "rebuild_triggered": recovery_triggered,
        "recovery_only_requested": recovery_only_requested,
        "recovery_only_run": recovery_only_run,
        "continued_to_step_2f_after_recovery": False,
        "reason": None,
    }
    if recovery_triggered:
        args.apply_caption_textplus = True
        args.clear_old_vc_textplus = True
        args.max_caption_textplus = 0
        args.caption_recovery_clean_target_track = True
        caption_dependency_guard["reason"] = (
            "V3 is missing, partial, or contains duplicate generated titles; "
            "started a clean full rebuild on the resolved dedicated track."
        )
        hard_debug("CAPTION_V3_DETERMINISTIC_RECOVERY_TRIGGERED", caption_dependency_guard)
    elif needs_recovery:
        caption_dependency_guard["reason"] = "V3 exact coverage failed and automatic recovery is disabled for this run."
    else:
        caption_dependency_guard["reason"] = "V3 already has exact one-to-one coverage for the generic subtitle contract."
    report["caption_dependency_guard"] = caption_dependency_guard
    report["workflow_step"] = {
        "step": 1,
        "name": "Deterministic V3 Text+ recovery",
        "status": "rebuilding" if recovery_triggered else ("verified" if not needs_recovery else "blocked"),
        "recovery_only_requested": recovery_only_requested,
        "recovery_only_run": recovery_only_run,
        "continued_to_step_2f_after_recovery": False,
    }

    # Caption Text+ provisioning/animation layer. This is separate from legacy
    # --apply-subtitles because it uses imported FCPXML V2 captions as timing anchors.
    if (getattr(args, "apply_caption_textplus", False) or getattr(args, "verify_caption_textplus", False)
            or getattr(args, "caption_textplus_probe_only", False) or getattr(args, "caption_style_probe_only", False)
            or getattr(args, "caption_shading_probe_only", False)):
        caption_textplus_result = apply_caption_textplus_layer(
            timeline=timeline,
            generic=generic,
            video_items=video_items,
            args=args,
            fps=fps,
            resolve=resolve,
            project=project,
        )
        report["caption_textplus_applier"] = caption_textplus_result
        report["textplus_creation_probe"] = caption_textplus_result.get("textplus_creation_probe") or {"enabled": False}
        report["summary"]["caption_textplus_ops"] = caption_textplus_result.get("requested_process_count", 0)
        report["summary"]["caption_textplus_created"] = caption_textplus_result.get("textplus_created_count", 0)
        report["summary"]["caption_textplus_reused"] = caption_textplus_result.get("textplus_reused_count", 0)
        report["summary"]["caption_textplus_augmented"] = caption_textplus_result.get("textplus_augmented_count", 0)
        report["summary"]["caption_textplus_failed"] = caption_textplus_result.get("textplus_failed_count", 0)
        report["summary"]["caption_animation_keyframes"] = ((caption_textplus_result.get("animation") or {}).get("keyframes_written_count") or 0)
        if caption_textplus_result.get("warnings"):
            report["summary"]["warnings"].extend([f"caption_textplus: {w}" for w in (caption_textplus_result.get("warnings") or [])])
        if caption_textplus_result.get("errors"):
            report["summary"]["warnings"].extend([f"caption_textplus_error: {json_safe_value(e)}" for e in (caption_textplus_result.get("errors") or [])])
    else:
        report["caption_textplus_applier"] = {
            "enabled": False,
            "reason": "--apply-caption-textplus/--verify-caption-textplus not used",
            "caption_track_index": getattr(args, "caption_track", getattr(args, "subtitle_track", 2)),
            "textplus_track_index": getattr(args, "caption_textplus_track", getattr(args, "caption_track", 2)),
        }


    textplus_coverage_after = verify_caption_textplus_track_coverage(
        timeline=timeline,
        track_index=textplus_track_index,
        generic=generic,
        fps=fps,
        tolerance_frames=max(1, get_int(getattr(args, "caption_timing_tolerance_frames", 2), 2)),
    )
    caption_dependency_guard["coverage_after"] = textplus_coverage_after
    caption_dependency_guard["existing_count_after"] = get_int(textplus_coverage_after.get("matched_count"), 0)
    caption_dependency_guard["candidate_count_after"] = get_int(textplus_coverage_after.get("candidate_title_count"), 0)
    caption_dependency_guard["extra_count_after"] = get_int(textplus_coverage_after.get("extra_candidate_count"), 0)
    caption_dependency_guard["coverage_ok"] = bool(textplus_coverage_after.get("coverage_ok"))

    recovery_only_run = should_defer_step_2f_after_v3_recovery(
        recovery_triggered=recovery_triggered,
        recovery_only_requested=recovery_only_requested,
        coverage_ok=caption_dependency_guard["coverage_ok"],
    )
    continued_after_recovery = bool(
        recovery_triggered
        and caption_dependency_guard["coverage_ok"]
        and not recovery_only_run
    )
    caption_dependency_guard["recovery_only_run"] = recovery_only_run
    caption_dependency_guard["continued_to_step_2f_after_recovery"] = continued_after_recovery
    report["workflow_step"]["recovery_only_run"] = recovery_only_run
    report["workflow_step"]["continued_to_step_2f_after_recovery"] = continued_after_recovery
    if continued_after_recovery:
        hard_debug("CAPTION_V3_RECOVERY_VERIFIED_CONTINUE_TO_STEP_2F", {
            "textplus_track": textplus_track_index,
            "matched_count": get_int(textplus_coverage_after.get("matched_count"), 0),
            "expected_count": expected_textplus_count,
        })

    report["workflow_step"]["status"] = "complete" if caption_dependency_guard["coverage_ok"] else "failed"
    report["workflow_step"]["verdict"] = (
        ("V3 exact coverage restored; continuing directly to Step 2F." if continued_after_recovery else "V3 exact coverage verified.")
        if caption_dependency_guard["coverage_ok"]
        else "V3 recovery is not complete; V4 remains blocked."
    )

    if recovery_triggered and not caption_dependency_guard["coverage_ok"]:
        report["ok"] = False
        report["summary"]["warnings"].append(
            "Deterministic V3 recovery failed exact 1:1 coverage verification."
        )

    if recovery_only_run and getattr(args, "apply_caption_occlusion", False):
        report["caption_occlusion"] = {
            "enabled": True,
            "mode": "blocked",
            "sequence_step": 9,
            "status": "blocked_after_unverified_v3_recovery",
            "ok": False,
            "timeline_mutation_attempted": False,
            "reason": "The V3 rebuild still failed exact coverage verification, so Step 2F was correctly blocked.",
        }
        report["summary"]["warnings"].append(
            "Step 2F was blocked because the V3 recovery did not pass exact post-rebuild verification."
        )

    if (getattr(args, "apply_caption_occlusion", False) or getattr(args, "caption_occlusion_plan_only", False)) and not recovery_only_run:
        asset_mode = str(getattr(args, "caption_occlusion_asset_mode", "rgba_sequence") or "rgba_sequence").lower()
        hard_debug("CAPTION_OCCLUSION_PLAN_START", {
            "analysis": getattr(args, "caption_occlusion_analysis", None),
            "asset_mode": asset_mode,
        })
        if asset_mode == "rgba_sequence":
            occlusion_plan = build_caption_foreground_rgba_plan(generic=generic, args=args, fps=fps)
        else:
            occlusion_plan = build_caption_occlusion_plan(generic=generic, args=args, fps=fps)
        report["caption_occlusion_plan"] = occlusion_plan
        hard_debug("CAPTION_OCCLUSION_PLAN_DONE", {
            "asset_mode": asset_mode,
            "span_count": occlusion_plan.get("span_count"),
            "ready_span_count": occlusion_plan.get("ready_span_count"),
            "event_count": occlusion_plan.get("event_count"),
            "status": occlusion_plan.get("status"),
            "errors": occlusion_plan.get("errors"),
        })

        can_apply = bool(
            getattr(args, "apply_caption_occlusion", False)
            and not getattr(args, "caption_occlusion_plan_only", False)
            and caption_dependency_guard.get("coverage_ok", True)
            and not args.dry_run
            and not args.verify_only
        )
        if can_apply and asset_mode == "rgba_sequence":
            hard_debug("CAPTION_OCCLUSION_RGBA_APPLY_START", {
                "target_track": getattr(args, "caption_occlusion_target_track", 4),
                "span_count": occlusion_plan.get("span_count"),
                "v3_track": textplus_track_index,
            })
            report["caption_occlusion"] = apply_caption_occlusion_rgba_assets(
                project=project,
                timeline=timeline,
                args=args,
                fps=fps,
                plan=occlusion_plan,
                v3_track=textplus_track_index,
            )
            report["summary"]["caption_occlusion_ops"] = report["caption_occlusion"].get("requested_span_count", 0)
            report["summary"]["caption_occlusion_created"] = report["caption_occlusion"].get("created_count", 0)
            report["summary"]["caption_occlusion_reused"] = report["caption_occlusion"].get("reused_count", 0)
            report["summary"]["caption_occlusion_failed"] = report["caption_occlusion"].get("failed_count", 0)
            report["caption_occlusion_workflow_step"] = {
                "major_step": "2F",
                "name": "Resolve V4 local RGBA sequence import",
                "status": "complete" if report["caption_occlusion"].get("ok") else "failed",
                "verdict": (
                    "Validated local foreground RGBA spans are placed on V4 above their linked V3 cues."
                    if report["caption_occlusion"].get("ok")
                    else "Step 2F did not reach exact editor-safe V4 placement."
                ),
            }
            if not report["caption_occlusion"].get("ok"):
                report["ok"] = False
                report["summary"]["warnings"].append("Step 2F RGBA V4 application failed; newly created Step 2F items were rolled back when configured.")
            hard_debug("CAPTION_OCCLUSION_RGBA_APPLY_DONE", {
                "status": report["caption_occlusion"].get("status"),
                "created_count": report["caption_occlusion"].get("created_count"),
                "reused_count": report["caption_occlusion"].get("reused_count"),
                "ready_count": report["caption_occlusion"].get("ready_count"),
                "failed_count": report["caption_occlusion"].get("failed_count"),
                "ok": report["caption_occlusion"].get("ok"),
            })
        elif can_apply and asset_mode == "legacy_bbox" and getattr(args, "caption_occlusion_bbox_fallback", False):
            report["caption_occlusion"] = apply_caption_occlusion_bbox_fallback(
                project=project, timeline=timeline, mapped=mapped, generic=generic,
                args=args, fps=fps, plan=occlusion_plan,
            )
            report["summary"]["caption_occlusion_ops"] = report["caption_occlusion"].get("requested_event_count", 0)
            report["summary"]["caption_occlusion_created"] = report["caption_occlusion"].get("ready_count", 0)
            report["summary"]["caption_occlusion_failed"] = report["caption_occlusion"].get("failed_count", 0)
            if not report["caption_occlusion"].get("ok"):
                report["ok"] = False
        elif getattr(args, "apply_caption_occlusion", False) and not getattr(args, "caption_occlusion_plan_only", False) and not caption_dependency_guard.get("coverage_ok", True):
            report["caption_occlusion"] = {
                "enabled": True,
                "mode": asset_mode,
                "major_step": "2F",
                "sequence_step": 9,
                "status": "blocked_missing_textplus_dependency",
                "ok": False,
                "timeline_mutation_attempted": False,
                "expected_textplus_count": expected_textplus_count,
                "actual_textplus_count": get_int(textplus_coverage_after.get("matched_count"), 0),
                "dependency_guard": caption_dependency_guard,
            }
            report["summary"]["caption_occlusion_failed"] = get_int(
                occlusion_plan.get("span_count"), get_int(occlusion_plan.get("event_count"), 0)
            )
            report["ok"] = False
            hard_debug("CAPTION_OCCLUSION_BLOCKED_MISSING_TEXTPLUS", report["caption_occlusion"])
        else:
            report["caption_occlusion"] = occlusion_plan


    if getattr(args, "caption_occlusion_finalize_major_step_2", False):
        hard_debug("CAPTION_OCCLUSION_STEP_2G_FINALIZATION_START", {
            "prior_validation": getattr(args, "caption_occlusion_prior_step_2f_validation", None),
            "state": getattr(args, "caption_occlusion_finalization_state", None),
            "output": getattr(args, "caption_occlusion_finalization_output", None),
        })
        step_2g = finalize_caption_occlusion_major_step_2(report=report, args=args, fps=fps)
        report["major_step_2_finalization"] = step_2g
        report["major_step_2"] = {
            "technical_complete": bool(step_2g.get("technical_complete")),
            "status": step_2g.get("status"),
            "completion_percent": step_2g.get("completion_percent"),
            "manual_visual_confirmation_required": True,
            "next_action": (
                "Inspect the composed viewer at the recorded review frame. No further occlusion code is required if the visual checklist passes."
                if step_2g.get("technical_complete")
                else "Run the controller once more without deleting V4 so the reuse/idempotency pass can be recorded."
            ),
        }
        if step_2g.get("warnings"):
            report["summary"]["warnings"].extend([f"step_2g: {w}" for w in step_2g.get("warnings") or []])
        hard_debug("CAPTION_OCCLUSION_STEP_2G_FINALIZATION_DONE", step_2g)

    # Subtitle / Text+ layer. This is applied once after clip-level layers,
    # because subtitle_clips are top-level generic timeline overlays, not per-shot clip effects.
    if getattr(args, "apply_subtitles", False) and not args.dry_run and not args.verify_only:
        hard_debug("SUBTITLE_LAYER_START", {"subtitle_clips_count": len(generic.get("subtitle_clips") or [])})
        subtitle_result = apply_subtitles_to_timeline(
            timeline=timeline,
            generic=generic,
            video_items=video_items,
            args=args,
            fps=fps,
        )
        report["subtitles"] = subtitle_result
        report["summary"]["subtitle_ops"] = subtitle_result.get("subtitle_clips_count", 0)
        report["summary"]["subtitle_created"] = subtitle_result.get("created_count", 0)
        report["summary"]["subtitle_failed"] = subtitle_result.get("failed_count", 0)
        if subtitle_result.get("warnings"):
            report["summary"]["warnings"].extend(subtitle_result.get("warnings") or [])
        hard_debug("SUBTITLE_LAYER_DONE", {
            "applied": subtitle_result.get("applied"),
            "created_count": subtitle_result.get("created_count"),
            "failed_count": subtitle_result.get("failed_count"),
        })
    else:
        report["subtitles"] = {
            "attempted": False,
            "reason": "apply_subtitles disabled, dry_run, or verify_only",
            "subtitle_clips_count": len(generic.get("subtitle_clips") or []),
        }

    hard_debug("RUN_CONTROLLER_RETURN", {"ok": report.get("ok"), "summary": report.get("summary")})
    return report


# -----------------------------
# CLI
# -----------------------------


def parse_args() -> argparse.Namespace:
    global INTERNAL_MENU_MODE

    parser = argparse.ArgumentParser(
        description="Apply Video Cloner generic edit command layers to the active DaVinci Resolve timeline."
    )
    parser.add_argument("--generic", default=None, help="Path to generic_edit_commands.json. Optional in internal Resolve menu mode.")
    parser.add_argument("--project-root", default=None, help="Optional Video Cloner project root used for auto-discovery.")
    parser.add_argument("--report", default=None, help="Optional output report JSON path")
    parser.add_argument("--debug-log", default=None, help="Optional hard debug log path. Also configurable with VC_DEBUG_LOG env var.")
    parser.add_argument("--config", default=None, help="Optional resolve_controller_config.json path. Useful for Resolve Workspace -> Scripts menu mode where CLI flags cannot be passed.")
    parser.add_argument("--video-track", type=int, default=1, help="Video track index to process. Default: 1. For full FCPXML use V1 for video cuts.")
    parser.add_argument("--audio-track", type=int, default=1, help="Audio track index for verification. Default: 1")
    parser.add_argument("--duration-tolerance-frames", type=int, default=2, help="Allowed duration mismatch in frames. Default: 2")
    parser.add_argument(
        "--timeline-backend",
        choices=["auto", "fcpxml_full", "otio_legacy"],
        default="auto",
        help="Imported timeline backend. Use fcpxml_full for the TextPlus full-timeline FCPXML so native transition items are filtered from clip mapping.",
    )

    parser.add_argument("--dry-run", action="store_true", help="Inspect and report without modifying Resolve timeline")
    parser.add_argument("--verify-only", action="store_true", help="Only verify mapping/timing; no effect attempts")

    parser.add_argument("--apply-zoom", action="store_true", help="Apply zoom values to clips with transform_zoom operations")
    parser.add_argument(
        "--animated-zoom",
        action="store_true",
        help="Experimental: apply real animated zoom using per-clip Fusion Transform keyframes.",
    )
    parser.add_argument(
        "--no-zoom-static-fallback",
        dest="zoom_static_fallback",
        action="store_false",
        help="Disable static ZoomX/ZoomY fallback if animated Fusion zoom fails.",
    )
    parser.set_defaults(zoom_static_fallback=True)
    parser.add_argument(
        "--clear-old-vc-zoom-tools",
        action="store_true",
        help="Delete old VC_Zoom_* Fusion tools before building/updating animated zoom tools. Useful after changing generic commands.",
    )
    parser.add_argument(
        "--clear-old-vc-zoom-scope",
        choices=["matching", "all"],
        default="matching",
        help="Scope for --clear-old-vc-zoom-tools. 'matching' deletes only VC_Zoom_<shot_id>; 'all' deletes all VC_Zoom_* tools inside that clip Fusion comp.",
    )
    parser.add_argument(
        "--zoom-mode",
        choices=["start", "end", "average"],
        default="end",
        help="Static zoom fallback mode. Default: end",
    )

    parser.add_argument(
        "--attempt-speed",
        action="store_true",
        help="Attempt constant speed changes for speed_ramp operations. Not true ramps yet.",
    )

    parser.add_argument(
        "--apply-subtitles",
        action="store_true",
        help="Create editable Resolve Text+/Fusion-title subtitle overlays from generic_edit_commands.subtitle_clips.",
    )
    parser.add_argument(
        "--subtitle-track",
        type=int,
        default=2,
        help="Preferred video track for subtitle overlays. Default: 2. Actual targeting depends on Resolve title insertion behavior.",
    )
    parser.add_argument(
        "--subtitle-title-name",
        default="Text+",
        help="Resolve title/generator name to insert for each subtitle. Default: Text+.",
    )
    parser.add_argument(
        "--verify-captions",
        dest="verify_captions",
        action="store_true",
        default=True,
        help="Read-only verification of imported caption/title clips on the configured caption track. Enabled by default. Does not create or modify captions.",
    )
    parser.add_argument(
        "--no-verify-captions",
        dest="verify_captions",
        action="store_false",
        help="Disable the default read-only V2 caption/title verification pass.",
    )
    parser.add_argument(
        "--caption-track",
        type=int,
        default=None,
        help="Video track index that should contain imported caption/title clips. Defaults to --subtitle-track, usually 2.",
    )
    parser.add_argument(
        "--caption-title-name",
        default=None,
        help="Expected Resolve title type/name for imported captions. Defaults to --subtitle-title-name.",
    )
    parser.add_argument(
        "--caption-verify-sample-limit",
        type=int,
        default=10,
        help="Number of title-like caption items to inspect for property/Fusion access. Default: 10.",
    )
    parser.add_argument(
        "--caption-timing-tolerance-frames",
        type=int,
        default=1,
        help="Allowed max frame delta for imported caption timing verification. Default: 1.",
    )
    parser.add_argument(
        "--caption-expected-report",
        default=None,
        help="Optional FCPXML compiler report JSON used for expected cue-count diagnostics.",
    )
    parser.add_argument(
        "--caption-property-write-test",
        action="store_true",
        help="Explicit opt-in placeholder for future non-destructive caption property write tests. This patch still remains read-only.",
    )
    parser.add_argument("--apply-caption-occlusion", action="store_true", help="Plan or apply V4 foreground matte/occlusion layers from the unified analysis contract.")
    parser.add_argument("--caption-occlusion-plan-only", action="store_true", help="Build the V4 foreground asset plan without modifying the timeline.")
    parser.add_argument("--caption-occlusion-analysis", default=None, help="Path to *_analysis.json containing caption occlusion/layering events. Auto-discovered from the generic path when omitted.")
    parser.add_argument("--caption-occlusion-plan-output", default=None, help="Output path for the normalized foreground matte plan JSON.")
    parser.add_argument("--caption-occlusion-mask-root", default=None, help="Optional directory containing real per-event foreground mask assets.")
    parser.add_argument("--caption-occlusion-min-score", type=float, default=0.50, help="Minimum occlusion score to include in the V4 plan. Default: 0.50.")
    parser.add_argument(
        "--caption-occlusion-asset-mode",
        choices=["rgba_sequence", "legacy_bbox"],
        default="rgba_sequence",
        help="V4 backend. rgba_sequence consumes validated Step 2E foreground assets. legacy_bbox is retained only for explicit diagnostics.",
    )
    parser.add_argument("--caption-occlusion-bbox-fallback", action="store_true", help="Explicit legacy-only fallback that duplicates V1 and applies a rectangular Fusion mask. Disabled in the Step 2F production config.")
    parser.add_argument("--caption-occlusion-require-editor-ready-assets", dest="caption_occlusion_require_editor_ready_assets", action="store_true", help="Require every selected Step 2E foreground asset span to be editor_ready. Default: true.")
    parser.add_argument("--no-caption-occlusion-require-editor-ready-assets", dest="caption_occlusion_require_editor_ready_assets", action="store_false")
    parser.set_defaults(caption_occlusion_require_editor_ready_assets=True)
    parser.add_argument("--caption-occlusion-reuse-media-pool-items", dest="caption_occlusion_reuse_media_pool_items", action="store_true", help="Reuse a matching imported RGBA sequence when possible. Default: true.")
    parser.add_argument("--no-caption-occlusion-reuse-media-pool-items", dest="caption_occlusion_reuse_media_pool_items", action="store_false")
    parser.set_defaults(caption_occlusion_reuse_media_pool_items=True)
    parser.add_argument("--caption-occlusion-set-straight-alpha", dest="caption_occlusion_set_straight_alpha", action="store_true", help="Best-effort set the imported PNG sequence alpha interpretation to Straight. Default: true.")
    parser.add_argument("--no-caption-occlusion-set-straight-alpha", dest="caption_occlusion_set_straight_alpha", action="store_false")
    parser.set_defaults(caption_occlusion_set_straight_alpha=True)
    parser.add_argument("--caption-occlusion-alpha-mode", default="Straight", help="Requested MediaPool alpha mode for the imported RGBA sequence. Default: Straight.")
    parser.add_argument(
        "--caption-occlusion-verify-settle-timeout-sec",
        type=float,
        default=1.50,
        help="Maximum time to poll a newly appended RGBA V4 item before rollback. Resolve may expose image-sequence duration asynchronously. Default: 1.50.",
    )
    parser.add_argument(
        "--caption-occlusion-verify-poll-interval-sec",
        type=float,
        default=0.10,
        help="Polling interval used while a newly appended RGBA V4 item settles. Default: 0.10.",
    )
    parser.add_argument(
        "--caption-occlusion-finalize-major-step-2",
        dest="caption_occlusion_finalize_major_step_2",
        action="store_true",
        help="Write the Step 2G two-pass completion gate and visual-review contract.",
    )
    parser.add_argument(
        "--no-caption-occlusion-finalize-major-step-2",
        dest="caption_occlusion_finalize_major_step_2",
        action="store_false",
    )
    parser.set_defaults(caption_occlusion_finalize_major_step_2=False)
    parser.add_argument("--caption-occlusion-finalization-output", default=None, help="Step 2G finalization JSON output path.")
    parser.add_argument("--caption-occlusion-finalization-state", default=None, help="Persistent Step 2G creation/reuse evidence state JSON path.")
    parser.add_argument("--caption-occlusion-prior-step-2f-validation", default=None, help="Prior successful Step 2F validation JSON used to bootstrap creation-pass evidence.")
    parser.add_argument(
        "--caption-occlusion-require-creation-and-reuse-passes",
        dest="caption_occlusion_require_creation_and_reuse_passes",
        action="store_true",
        help="Require both a successful creation run and a successful idempotent reuse run before technical completion. Default: true.",
    )
    parser.add_argument(
        "--no-caption-occlusion-require-creation-and-reuse-passes",
        dest="caption_occlusion_require_creation_and_reuse_passes",
        action="store_false",
    )
    parser.set_defaults(caption_occlusion_require_creation_and_reuse_passes=True)
    parser.add_argument(
        "--caption-occlusion-visual-review-frame",
        type=int,
        default=0,
        help="Optional exact timeline frame for the final manual viewer check. 0 derives the center of the first V4 span.",
    )
    parser.add_argument("--caption-occlusion-require-v3-cue-linkage", dest="caption_occlusion_require_v3_cue_linkage", action="store_true", help="Require the asset cue to resolve to an overlapping generated V3 Text+ item. Default: true.")
    parser.add_argument("--no-caption-occlusion-require-v3-cue-linkage", dest="caption_occlusion_require_v3_cue_linkage", action="store_false")
    parser.set_defaults(caption_occlusion_require_v3_cue_linkage=True)
    parser.add_argument("--caption-occlusion-rollback-on-failure", dest="caption_occlusion_rollback_on_failure", action="store_true", help="Delete only newly-created Step 2F V4 items if the pass fails. Default: true.")
    parser.add_argument("--no-caption-occlusion-rollback-on-failure", dest="caption_occlusion_rollback_on_failure", action="store_false")
    parser.set_defaults(caption_occlusion_rollback_on_failure=True)
    parser.add_argument("--caption-occlusion-clear-legacy-bbox-v4", dest="caption_occlusion_clear_legacy_bbox_v4", action="store_true", help="Delete stale VC_OCCLUSION_BBOX_* timeline items before the RGBA pass. Default: true.")
    parser.add_argument("--no-caption-occlusion-clear-legacy-bbox-v4", dest="caption_occlusion_clear_legacy_bbox_v4", action="store_false")
    parser.set_defaults(caption_occlusion_clear_legacy_bbox_v4=True)
    parser.add_argument("--caption-occlusion-legacy-item-prefix", default="VC_OCCLUSION_BBOX_", help="Legacy V4 item prefix eligible for safe cleanup.")
    parser.add_argument("--caption-occlusion-target-track", type=int, default=4, help="Target video track for generated foreground bbox fallback clips. Default: 4.")
    parser.add_argument("--caption-occlusion-max-events", type=int, default=0, help="Maximum occlusion events to apply. 0 means all matching events.")
    parser.add_argument("--caption-occlusion-bbox-padding-px", type=int, default=4, help="Pixels added around each detected mask bbox. Default: 4.")
    parser.add_argument("--caption-occlusion-soft-edge", type=float, default=0.0, help="Rectangle mask soft edge in Fusion normalized units. Default: 0.")
    parser.add_argument("--caption-occlusion-clear-old-v4", action="store_true", help="Delete previous generated VC_OCCLUSION_BBOX items before applying the new V4 pass.")
    parser.add_argument("--caption-occlusion-stop-on-first-failure", action="store_true", help="Stop the bbox fallback pass after the first failed event.")
    parser.add_argument("--caption-occlusion-track-name", default="VC_OCCLUSION_V4", help="Name assigned to the dedicated bbox fallback track.")
    parser.add_argument("--caption-occlusion-item-prefix", default="VC_OCCLUSION_RGBA_", help="Generated V4 RGBA timeline item prefix used for idempotency, safe cleanup and verification.")
    parser.add_argument("--caption-occlusion-auto-rebuild-textplus-if-missing", action="store_true", help="Rebuild the full V3 Text+ layer from the generic subtitle contract when occlusion is requested and V3 coverage is missing.")
    parser.add_argument("--caption-occlusion-require-textplus-track", action="store_true", help="Block V4 occlusion application unless the expected V3 Text+ coverage exists.")

    parser.add_argument(
        "--apply-caption-textplus",
        action="store_true",
        help="Provision controllable Text+ captions from imported static V2 caption/title anchors. Safe/idempotent; does not delete static captions by default.",
    )
    parser.add_argument(
        "--verify-caption-textplus",
        action="store_true",
        help="Verify Caption Text+ provisioning/control paths without creating or modifying Text+ captions.",
    )
    parser.add_argument(
        "--caption-textplus-track",
        type=int,
        default=None,
        help="Requested video track for generated Text+ captions. Defaults to --caption-track; if static captions are kept, overlay fallback automatically uses the next safe track.",
    )
    parser.add_argument(
        "--caption-textplus-track-name",
        default="VC_TEXTPLUS_V3",
        help="Stable identity for the generated Text+ track. The controller resolves this name before using a numeric index.",
    )
    parser.add_argument(
        "--caption-textplus-expected-count",
        type=int,
        default=0,
        help="Expected full V3 caption count. 0 derives it from generic_edit_commands.subtitle_clips.",
    )
    parser.add_argument(
        "--caption-recovery-only-when-missing",
        dest="caption_recovery_only_when_missing",
        action="store_true",
        help="Compatibility switch. A successful V3 rebuild continues to Step 2F in the same run; only an unverified rebuild remains blocked. Default: false.",
    )
    parser.add_argument(
        "--no-caption-recovery-only-when-missing",
        dest="caption_recovery_only_when_missing",
        action="store_false",
        help="Continue to Step 2F immediately after exact V3 recovery verification.",
    )
    parser.set_defaults(caption_recovery_only_when_missing=False)
    parser.add_argument(
        "--caption-recovery-clean-target-track",
        dest="caption_recovery_clean_target_track",
        action="store_true",
        help="Clear all non-media title-like items from the dedicated V3 track before a full recovery. Default: true.",
    )
    parser.add_argument(
        "--no-caption-recovery-clean-target-track",
        dest="caption_recovery_clean_target_track",
        action="store_false",
        help="Only clear VC_TEXTPLUS_* named items during recovery.",
    )
    parser.set_defaults(caption_recovery_clean_target_track=True)

    parser.add_argument(
        "--caption-static-title-policy",
        choices=["keep", "hide", "disable", "delete"],
        default="keep",
        help="Policy for imported static FCPXML captions after Text+ provisioning. Default: keep. Delete is intentionally not executed in this stage.",
    )
    parser.add_argument(
        "--caption-animation",
        action="store_true",
        help="Apply conservative Fusion/Text+ caption keyframes after Text+ provisioning succeeds.",
    )
    parser.add_argument(
        "--caption-animation-mode",
        choices=["conservative", "full"],
        default="conservative",
        help="Caption animation strictness. Conservative uses small scale-pop defaults and supports 3-frame word cues.",
    )
    parser.add_argument(
        "--caption-animation-sample-limit",
        type=int,
        default=0,
        help="Testing limit for animated captions. 0 means no animation-specific cap; --max-caption-textplus still limits processed captions.",
    )
    parser.add_argument(
        "--max-caption-textplus",
        type=int,
        default=0,
        help="Testing limit for Caption Text+ provisioning. 0 means process all cues. Use 5 for smoke tests.",
    )
    parser.add_argument(
        "--caption-compact-report",
        dest="caption_compact_report",
        action="store_true",
        help="Keep full-generation reports compact by omitting repeated Fusion inventories and track snapshots. Default: true.",
    )
    parser.add_argument(
        "--no-caption-compact-report",
        dest="caption_compact_report",
        action="store_false",
        help="Keep full per-caption diagnostics. Not recommended for 116-caption generation.",
    )
    parser.set_defaults(caption_compact_report=True)
    parser.add_argument(
        "--caption-checkpoint-interval",
        type=int,
        default=10,
        help="Write a compact caption-generation checkpoint every N processed captions. 0 disables checkpoints.",
    )
    parser.add_argument(
        "--caption-stop-on-first-failure",
        dest="caption_stop_on_first_failure",
        action="store_true",
        help="Stop the full run after the first failed cue while keeping V2 references visible. Default: true.",
    )
    parser.add_argument(
        "--no-caption-stop-on-first-failure",
        dest="caption_stop_on_first_failure",
        action="store_false",
        help="Continue after failed caption cues.",
    )
    parser.set_defaults(caption_stop_on_first_failure=True)
    parser.add_argument(
        "--clear-old-vc-textplus",
        action="store_true",
        help="Delete existing named VC_TEXTPLUS_ generated caption items before creating/reusing caption Text+ items.",
    )
    parser.add_argument(
        "--caption-write-test",
        action="store_true",
        help="Explicit opt-in to write/probe static title Fusion comps. Without this, imported static titles are not modified unless they already expose a controllable Text tool.",
    )
    parser.add_argument(
        "--caption-style",
        default=None,
        help="Optional caption_style.json path for rich style/style_event/animation metadata. Auto-discovered from generic path when omitted.",
    )
    parser.add_argument(
        "--caption-textplus-probe-only",
        action="store_true",
        help="Run only the dedicated Text+ creation/style/animation probe instead of the full caption applier.",
    )
    parser.add_argument(
        "--caption-probe-count",
        type=int,
        default=1,
        help="Number of leading caption cues to probe. Clamped to 1-5.",
    )
    parser.add_argument(
        "--caption-probe-text",
        default=None,
        help="Select the first probe cue by exact/normalized text, for example graduated.",
    )
    parser.add_argument(
        "--caption-probe-cue-id",
        default=None,
        help="Select the first probe cue by exact cue id, for example sub_002.",
    )
    parser.add_argument(
        "--caption-keep-failed-probe-item",
        action="store_true",
        help="Keep a probe item even when track/range/Fusion/style verification fails so it can be inspected in Resolve.",
    )
    parser.add_argument(
        "--caption-style-probe-only",
        action="store_true",
        help="Do not create a title; probe style/animation writes on an existing generated Text+ item on the target track.",
    )
    parser.add_argument(
        "--caption-shading-probe-only",
        action="store_true",
        help="Run the one-caption Text+ probe with verified input inventory plus safe outline/shadow shading writes.",
    )
    parser.add_argument(
        "--caption-apply-outline",
        action="store_true",
        help="Request Text+ shading element 2 as an explicitly configured Text Outline.",
    )
    parser.add_argument(
        "--caption-apply-shadow",
        action="store_true",
        help="Request Text+ shading element 3 as an explicitly configured offset Text Fill shadow.",
    )
    parser.add_argument(
        "--caption-outline-element",
        type=int,
        default=2,
        help="Text+ shading element index reserved for outline. Default: 2.",
    )
    parser.add_argument(
        "--caption-shadow-element",
        type=int,
        default=3,
        help="Text+ shading element index reserved for shadow. Default: 3.",
    )
    parser.add_argument(
        "--caption-outline-thickness",
        type=float,
        default=None,
        help="Optional exact Text+ outline Thickness override. When omitted, derive it from detected stroke px / detected font height px.",
    )
    parser.add_argument(
        "--caption-outline-width-scale",
        type=float,
        default=1.0,
        help="Calibration multiplier for the derived Text+ outline thickness. Default: 1.0.",
    )
    parser.add_argument(
        "--caption-shadow-offset-x",
        type=float,
        default=0.003,
        help="Text+ shading-element shadow X offset in normalized image coordinates. Default: 0.003.",
    )
    parser.add_argument(
        "--caption-shadow-offset-y",
        type=float,
        default=0.003,
        help="Text+ shading-element shadow Y offset in normalized image coordinates. Default: 0.003.",
    )
    parser.add_argument(
        "--caption-shadow-opacity",
        type=float,
        default=None,
        help="Optional exact shadow opacity override in 0..1. When omitted, use the detected style value.",
    )
    parser.add_argument(
        "--caption-shadow-softness",
        type=float,
        default=None,
        help="Optional Text+ shadow softness override. Omitted for the first safe probe unless the actual input is inventoried.",
    )
    parser.add_argument(
        "--caption-fill-color-policy",
        choices=("detected", "darkest_text_component_on_low_confidence", "force_black"),
        default="detected",
        help="Renderer color policy. The low-confidence mode may use a much darker stroke/text component as fill and reports the decision.",
    )
    parser.add_argument(
        "--caption-color-low-confidence-threshold",
        type=float,
        default=0.70,
        help="Style-event confidence below which the darkest-component fill heuristic may run. Default: 0.70.",
    )
    parser.add_argument(
        "--caption-color-min-luma-gap",
        type=float,
        default=0.12,
        help="Minimum Rec.709 luma gap required before replacing detected fill with the darker text component. Default: 0.12.",
    )
    parser.add_argument(
        "--caption-restore-static-titles-before-apply",
        dest="caption_restore_static_titles_before_apply",
        action="store_true",
        help="Restore V2 reference title Opacity to 100 before rebuilding V3 replacements. Default: true.",
    )
    parser.add_argument(
        "--no-caption-restore-static-titles-before-apply",
        dest="caption_restore_static_titles_before_apply",
        action="store_false",
        help="Do not restore previously hidden V2 reference titles before rebuilding replacements.",
    )
    parser.set_defaults(caption_restore_static_titles_before_apply=True)
    parser.add_argument(
        "--caption-allow-static-title-item-writes",
        dest="caption_allow_static_title_item_writes",
        action="store_true",
        help=(
            "UNSAFE diagnostic opt-in. Allow TimelineItem.SetProperty writes on imported "
            "FCPXML Basic Titles. Disabled by default because Resolve Studio 21.0.1 "
            "crashed natively during Opacity writes."
        ),
    )
    parser.add_argument(
        "--no-caption-allow-static-title-item-writes",
        dest="caption_allow_static_title_item_writes",
        action="store_false",
        help="Keep the crash-safety guard enabled for imported V2 Basic Titles.",
    )
    parser.set_defaults(caption_allow_static_title_item_writes=False)
    parser.add_argument(
        "--caption-force-font-name",
        default=None,
        help="Exact installed Text+ font family override for the probe, for example Impact.",
    )
    parser.add_argument(
        "--caption-force-font-style",
        default=None,
        help="Exact installed Text+ typeface override, for example Regular. Detector weight is never treated as proof that a face exists.",
    )
    parser.add_argument(
        "--caption-font-fallback-order",
        default=DEFAULT_CAPTION_FONT_FALLBACK_ORDER,
        help="Comma-separated installed family|face candidates used only when the detector family is unknown or unavailable.",
    )
    parser.add_argument(
        "--caption-force-textplus-size",
        type=float,
        default=None,
        help="Exact normalized Text+ Size value. This is relative to image width, not pixels or points.",
    )
    parser.add_argument(
        "--caption-textplus-size-scale",
        type=float,
        default=1.5,
        help="Calibration multiplier applied after converting detected glyph pixels to frame-width-relative Text+ Size. Default: 1.5.",
    )
    parser.add_argument(
        "--caption-force-position-from-style",
        dest="caption_force_position_from_style",
        action="store_true",
        help="Write Fusion Center from the detected caption-style anchor during the probe.",
    )
    parser.add_argument(
        "--no-caption-force-position-from-style",
        dest="caption_force_position_from_style",
        action="store_false",
        help="Skip Center writes during the Text+ probe.",
    )
    parser.set_defaults(caption_force_position_from_style=True)
    parser.add_argument(
        "--caption-use-per-cue-style-events",
        dest="caption_use_per_cue_style_events",
        action="store_true",
        help="Use matched per-cue caption style events during the probe.",
    )
    parser.add_argument(
        "--no-caption-use-per-cue-style-events",
        dest="caption_use_per_cue_style_events",
        action="store_false",
        help="Use only the primary resolved caption style during the probe.",
    )
    parser.set_defaults(caption_use_per_cue_style_events=True)
    parser.add_argument(
        "--caption-disable-duration-strictness-for-probe",
        action="store_true",
        help="Do not reject/delete a probe item only because Resolve kept its default duration.",
    )
    parser.add_argument(
        "--subtitle-min-duration-frames",
        type=int,
        default=2,
        help="Minimum subtitle overlay duration in frames. Default: 2.",
    )
    parser.add_argument(
        "--clear-old-vc-subtitles",
        action="store_true",
        help="Delete existing timeline items whose names start with VC_Sub_ before creating subtitles.",
    )
    parser.add_argument(
        "--max-subtitles",
        type=int,
        default=0,
        help="Testing limit. 0 means create all subtitle_clips. Use 10 for a quick smoke test.",
    )
    parser.add_argument(
        "--no-subtitle-track-guard",
        dest="subtitle_track_guard",
        action="store_false",
        help="Disable temporary locking of non-subtitle video tracks and audio tracks during Text+ insertion.",
    )
    parser.set_defaults(subtitle_track_guard=True)
    parser.add_argument(
        "--no-subtitle-mark-in-out",
        dest="subtitle_use_mark_in_out",
        action="store_false",
        help="Disable timeline in/out mark duration control before inserting each Text+ title.",
    )
    parser.set_defaults(subtitle_use_mark_in_out=True)
    parser.add_argument(
        "--allow-untrimmed-subtitles",
        dest="subtitle_strict_timing",
        action="store_false",
        help="Allow subtitles even if Resolve ignores exact word-level duration/track targeting. Not recommended for production.",
    )
    parser.set_defaults(subtitle_strict_timing=True)
    parser.add_argument(
        "--keep-going-on-subtitle-range-fail",
        dest="subtitle_stop_on_range_fail",
        action="store_false",
        help="Continue creating subtitles even after a timing/track guard failure. Not recommended for production.",
    )
    parser.set_defaults(subtitle_stop_on_range_fail=True)

    parser.add_argument(
        "--add-debug-markers",
        dest="add_debug_markers",
        action="store_true",
        help="Debug mode only: add Resolve timeline markers at clip starts with JSON payload.",
    )
    parser.add_argument(
        "--no-debug-markers",
        dest="add_debug_markers",
        action="store_false",
        help="Production mode: do not add controller, per-clip, or transition debug markers. This is the default.",
    )
    parser.set_defaults(add_debug_markers=False)
    parser.add_argument(
        "--clear-debug-markers",
        dest="clear_debug_markers",
        action="store_true",
        help="Remove existing VC_DEBUG_/VC_TRANSITION_/VC_CONTROLLER_RAN_ markers before applying effects. Default: true.",
    )
    parser.add_argument(
        "--keep-existing-debug-markers",
        dest="clear_debug_markers",
        action="store_false",
        help="Do not clean old Video Cloner controller debug markers.",
    )
    parser.set_defaults(clear_debug_markers=True)

    # Resolve can pass odd/non-standard argv values in embedded runtimes. Unknowns
    # should not kill the script silently when launched from Workspace -> Scripts.
    args, unknown = parser.parse_known_args()
    cli_provided_dests = collect_cli_provided_dests(parser, sys.argv[1:])
    if unknown:
        hard_debug("ARGPARSE_UNKNOWN_ARGS_IGNORED", {"unknown": unknown, "argv": sys.argv})

    add_debug_markers_requested = (
        "--add-debug-markers" in sys.argv[1:]
        or truthy_env("VC_ADD_DEBUG_MARKERS", False)
    )
    no_debug_markers_requested = (
        "--no-debug-markers" in sys.argv[1:]
        or truthy_env("VC_NO_DEBUG_MARKERS", False)
        or (truthy_env("VC_PRODUCTION_MODE", True) and not add_debug_markers_requested)
    )
    setattr(args, "no_debug_markers", bool(no_debug_markers_requested))

    # If there are no meaningful CLI flags, assume manual Workspace -> Scripts launch.
    INTERNAL_MENU_MODE = not any(str(arg).startswith("--") for arg in sys.argv[1:])
    setattr(args, "internal_menu_mode", INTERNAL_MENU_MODE)

    config_info: Dict[str, Any] = {"loaded": False, "path": None, "source": None, "applied": {}}

    # First pass: explicit config path only. This lets a config file provide
    # generic/report/debug paths before auto-discovery runs.
    explicit_config = normalize_user_path(
        args.config
        or os.environ.get("VC_RESOLVE_CONTROLLER_CONFIG")
        or os.environ.get("VC_CONTROLLER_CONFIG")
    )
    if explicit_config:
        config_data, loaded_info = load_controller_config(explicit_config)
        config_info.update(loaded_info)
        config_info["source"] = "explicit_or_env"
        if loaded_info.get("loaded"):
            config_info["applied"] = apply_controller_config_to_args(args, config_data, cli_provided_dests)

    if not args.generic:
        args.generic = discover_latest_generic_file(args.project_root)

    if args.generic:
        args.generic = str(Path(args.generic).resolve())

    # Second pass: per-video config near the selected generic file or latest
    # config under data/*/davinci. This is the normal Resolve menu-mode path.
    if not config_info.get("loaded"):
        discovered_config = discover_latest_controller_config(args.project_root, args.generic)
        if discovered_config:
            config_data, loaded_info = load_controller_config(discovered_config)
            config_info.update(loaded_info)
            config_info["source"] = "auto_discovered"
            if loaded_info.get("loaded"):
                config_info["applied"] = apply_controller_config_to_args(args, config_data, cli_provided_dests)

    if args.generic:
        args.generic = str(Path(args.generic).resolve())

    setattr(args, "resolve_controller_config", config_info)

    env_timeline_backend = os.environ.get("VC_TIMELINE_BACKEND")
    if env_timeline_backend in {"auto", "fcpxml_full", "otio_legacy"}:
        args.timeline_backend = env_timeline_backend

    # Internal menu mode used to force zoom back on even when the discovered
    # controller config explicitly set apply_zoom=false. That made caption probes
    # modify unrelated clips and invalidated isolation. Respect explicit config.
    config_applied_values = {}
    if isinstance(config_info.get("applied"), dict):
        config_applied_values = config_info.get("applied", {}).get("applied") or {}

    if INTERNAL_MENU_MODE:
        apply_zoom_explicit = "apply_zoom" in config_applied_values
        animated_zoom_explicit = "animated_zoom" in config_applied_values
        zoom_mode_explicit = "zoom_mode" in config_applied_values

        if not apply_zoom_explicit and not args.apply_zoom and not args.dry_run and not args.verify_only:
            args.apply_zoom = True
        if args.apply_zoom and not args.dry_run and not args.verify_only:
            # Only supply the legacy menu defaults when the config did not.
            if not animated_zoom_explicit:
                args.animated_zoom = True
            if not zoom_mode_explicit and args.zoom_mode == "end":
                args.zoom_mode = "average"
        if not args.clear_old_vc_zoom_tools and truthy_env("VC_CLEAR_OLD_ZOOM_TOOLS", False):
            args.clear_old_vc_zoom_tools = True
        env_clear_scope = os.environ.get("VC_CLEAR_OLD_ZOOM_SCOPE")
        if env_clear_scope in {"matching", "all"}:
            args.clear_old_vc_zoom_scope = env_clear_scope

        # Subtitle/Text+ behavior for Workspace -> Scripts runs. It is opt-in by
        # environment variable because word-level subtitles can create hundreds of
        # editable title items.
        if truthy_env("VC_APPLY_SUBTITLES", False):
            args.apply_subtitles = True
        if truthy_env("VC_CLEAR_OLD_SUBTITLES", False):
            args.clear_old_vc_subtitles = True
        env_sub_track = os.environ.get("VC_SUBTITLE_TRACK")
        if env_sub_track:
            args.subtitle_track = max(1, get_int(env_sub_track, args.subtitle_track))
        env_max_subtitles = os.environ.get("VC_MAX_SUBTITLES")
        if env_max_subtitles:
            args.max_subtitles = max(0, get_int(env_max_subtitles, args.max_subtitles))
        env_title_name = os.environ.get("VC_SUBTITLE_TITLE_NAME")
        if env_title_name:
            args.subtitle_title_name = env_title_name
        if os.environ.get("VC_SUBTITLE_TRACK_GUARD") is not None:
            args.subtitle_track_guard = truthy_env("VC_SUBTITLE_TRACK_GUARD", True)
        if os.environ.get("VC_SUBTITLE_USE_MARK_IN_OUT") is not None:
            args.subtitle_use_mark_in_out = truthy_env("VC_SUBTITLE_USE_MARK_IN_OUT", True)
        if truthy_env("VC_ALLOW_UNTRIMMED_SUBTITLES", False):
            args.subtitle_strict_timing = False
        if os.environ.get("VC_SUBTITLE_STOP_ON_RANGE_FAIL") is not None:
            args.subtitle_stop_on_range_fail = truthy_env("VC_SUBTITLE_STOP_ON_RANGE_FAIL", True)

        if truthy_env("VC_APPLY_CAPTION_TEXTPLUS", False):
            args.apply_caption_textplus = True
        if truthy_env("VC_VERIFY_CAPTION_TEXTPLUS", False):
            args.verify_caption_textplus = True
        if truthy_env("VC_CAPTION_ANIMATION", False):
            args.caption_animation = True
        env_caption_textplus_track = os.environ.get("VC_CAPTION_TEXTPLUS_TRACK")
        if env_caption_textplus_track:
            args.caption_textplus_track = max(1, get_int(env_caption_textplus_track, args.caption_textplus_track or args.caption_track or args.subtitle_track))
        env_max_caption_textplus = os.environ.get("VC_MAX_CAPTION_TEXTPLUS")
        if env_max_caption_textplus:
            args.max_caption_textplus = max(0, get_int(env_max_caption_textplus, args.max_caption_textplus))
        env_caption_static_policy = os.environ.get("VC_CAPTION_STATIC_TITLE_POLICY")
        if env_caption_static_policy in {"keep", "hide", "disable", "delete"}:
            args.caption_static_title_policy = env_caption_static_policy
        env_caption_animation_mode = os.environ.get("VC_CAPTION_ANIMATION_MODE")
        if env_caption_animation_mode in {"conservative", "full"}:
            args.caption_animation_mode = env_caption_animation_mode
        env_caption_animation_sample_limit = os.environ.get("VC_CAPTION_ANIMATION_SAMPLE_LIMIT")
        if env_caption_animation_sample_limit:
            args.caption_animation_sample_limit = max(0, get_int(env_caption_animation_sample_limit, args.caption_animation_sample_limit))
        if truthy_env("VC_CLEAR_OLD_TEXTPLUS", False):
            args.clear_old_vc_textplus = True
        if truthy_env("VC_CAPTION_WRITE_TEST", False):
            args.caption_write_test = True
        env_caption_style = os.environ.get("VC_CAPTION_STYLE")
        if env_caption_style:
            args.caption_style = env_caption_style

        # Production default: never add timeline debug markers from Workspace -> Scripts.
        # They create the black JSON overlays and marker flood. Use env
        # VC_ADD_DEBUG_MARKERS=true or CLI --add-debug-markers only when you explicitly
        # want marker diagnostics.
        if add_debug_markers_requested and not no_debug_markers_requested:
            args.add_debug_markers = True
        else:
            args.add_debug_markers = False

        if os.environ.get("VC_CLEAR_DEBUG_MARKERS") is not None:
            args.clear_debug_markers = truthy_env("VC_CLEAR_DEBUG_MARKERS", True)
        if args.generic and not args.report:
            args.report = default_report_path_for_generic(args.generic)
        if args.generic and not args.debug_log:
            args.debug_log = default_debug_log_for_generic(args.generic)

    # Environment overrides also work for external/n8n runs.
    if truthy_env("VC_APPLY_SUBTITLES", False):
        args.apply_subtitles = True
    if truthy_env("VC_CLEAR_OLD_SUBTITLES", False):
        args.clear_old_vc_subtitles = True
    env_sub_track = os.environ.get("VC_SUBTITLE_TRACK")
    if env_sub_track:
        args.subtitle_track = max(1, get_int(env_sub_track, args.subtitle_track))
    env_max_subtitles = os.environ.get("VC_MAX_SUBTITLES")
    if env_max_subtitles:
        args.max_subtitles = max(0, get_int(env_max_subtitles, args.max_subtitles))
    env_title_name = os.environ.get("VC_SUBTITLE_TITLE_NAME")
    if env_title_name:
        args.subtitle_title_name = env_title_name
    if os.environ.get("VC_SUBTITLE_TRACK_GUARD") is not None:
        args.subtitle_track_guard = truthy_env("VC_SUBTITLE_TRACK_GUARD", True)
    if os.environ.get("VC_SUBTITLE_USE_MARK_IN_OUT") is not None:
        args.subtitle_use_mark_in_out = truthy_env("VC_SUBTITLE_USE_MARK_IN_OUT", True)
    if truthy_env("VC_ALLOW_UNTRIMMED_SUBTITLES", False):
        args.subtitle_strict_timing = False
    if os.environ.get("VC_SUBTITLE_STOP_ON_RANGE_FAIL") is not None:
        args.subtitle_stop_on_range_fail = truthy_env("VC_SUBTITLE_STOP_ON_RANGE_FAIL", True)

    if add_debug_markers_requested and not no_debug_markers_requested:
        args.add_debug_markers = True
    else:
        args.add_debug_markers = False

    if os.environ.get("VC_CLEAR_DEBUG_MARKERS") is not None:
        args.clear_debug_markers = truthy_env("VC_CLEAR_DEBUG_MARKERS", True)

    # Caption verification environment overrides. These are intentionally separate
    # from subtitle creation. Verification must not imply --apply-subtitles.
    # v0.6.1 production default: caption verification is ON because it is read-only
    # and Workspace -> Scripts cannot pass CLI flags. Use --no-verify-captions or
    # VC_VERIFY_CAPTIONS=false to disable it intentionally.
    if os.environ.get("VC_VERIFY_CAPTIONS") is not None:
        args.verify_captions = truthy_env("VC_VERIFY_CAPTIONS", True)
    env_caption_track = os.environ.get("VC_CAPTION_TRACK")
    if env_caption_track:
        args.caption_track = max(1, get_int(env_caption_track, args.caption_track or args.subtitle_track))
    if args.caption_track is None:
        args.caption_track = max(1, get_int(args.subtitle_track, 2))

    env_caption_title_name = os.environ.get("VC_CAPTION_TITLE_NAME")
    if env_caption_title_name:
        args.caption_title_name = env_caption_title_name
    if args.caption_title_name is None:
        args.caption_title_name = args.subtitle_title_name

    env_caption_sample_limit = os.environ.get("VC_CAPTION_VERIFY_SAMPLE_LIMIT")
    if env_caption_sample_limit:
        args.caption_verify_sample_limit = max(0, get_int(env_caption_sample_limit, args.caption_verify_sample_limit))
    env_caption_tolerance = os.environ.get("VC_CAPTION_TIMING_TOLERANCE_FRAMES")
    if env_caption_tolerance:
        args.caption_timing_tolerance_frames = max(0, get_int(env_caption_tolerance, args.caption_timing_tolerance_frames))
    env_caption_expected_report = os.environ.get("VC_CAPTION_EXPECTED_REPORT")
    if env_caption_expected_report:
        args.caption_expected_report = env_caption_expected_report
    if truthy_env("VC_CAPTION_PROPERTY_WRITE_TEST", False):
        args.caption_property_write_test = True

    if truthy_env("VC_APPLY_CAPTION_TEXTPLUS", False):
        args.apply_caption_textplus = True
    if truthy_env("VC_VERIFY_CAPTION_TEXTPLUS", False):
        args.verify_caption_textplus = True
    if truthy_env("VC_CAPTION_ANIMATION", False):
        args.caption_animation = True
    env_caption_textplus_track = os.environ.get("VC_CAPTION_TEXTPLUS_TRACK")
    if env_caption_textplus_track:
        args.caption_textplus_track = max(1, get_int(env_caption_textplus_track, args.caption_textplus_track or args.caption_track or args.subtitle_track))
    if args.caption_textplus_track is None:
        args.caption_textplus_track = max(1, get_int(args.caption_track or args.subtitle_track, 2))
    env_max_caption_textplus = os.environ.get("VC_MAX_CAPTION_TEXTPLUS")
    if env_max_caption_textplus:
        args.max_caption_textplus = max(0, get_int(env_max_caption_textplus, args.max_caption_textplus))
    env_caption_static_policy = os.environ.get("VC_CAPTION_STATIC_TITLE_POLICY")
    if env_caption_static_policy in {"keep", "hide", "disable", "delete"}:
        args.caption_static_title_policy = env_caption_static_policy
    env_caption_animation_mode = os.environ.get("VC_CAPTION_ANIMATION_MODE")
    if env_caption_animation_mode in {"conservative", "full"}:
        args.caption_animation_mode = env_caption_animation_mode
    env_caption_animation_sample_limit = os.environ.get("VC_CAPTION_ANIMATION_SAMPLE_LIMIT")
    if env_caption_animation_sample_limit:
        args.caption_animation_sample_limit = max(0, get_int(env_caption_animation_sample_limit, args.caption_animation_sample_limit))
    if truthy_env("VC_CLEAR_OLD_TEXTPLUS", False):
        args.clear_old_vc_textplus = True
    if truthy_env("VC_CAPTION_WRITE_TEST", False):
        args.caption_write_test = True
    env_caption_style = os.environ.get("VC_CAPTION_STYLE")
    if env_caption_style:
        args.caption_style = env_caption_style
    if truthy_env("VC_CAPTION_TEXTPLUS_PROBE_ONLY", False):
        args.caption_textplus_probe_only = True
    env_caption_probe_count = os.environ.get("VC_CAPTION_PROBE_COUNT")
    if env_caption_probe_count:
        args.caption_probe_count = max(1, min(5, get_int(env_caption_probe_count, args.caption_probe_count)))
    env_caption_probe_text = os.environ.get("VC_CAPTION_PROBE_TEXT")
    if env_caption_probe_text:
        args.caption_probe_text = env_caption_probe_text
    env_caption_probe_cue_id = os.environ.get("VC_CAPTION_PROBE_CUE_ID")
    if env_caption_probe_cue_id:
        args.caption_probe_cue_id = env_caption_probe_cue_id
    if truthy_env("VC_CAPTION_KEEP_FAILED_PROBE_ITEM", False):
        args.caption_keep_failed_probe_item = True
    if truthy_env("VC_CAPTION_STYLE_PROBE_ONLY", False):
        args.caption_style_probe_only = True
    if truthy_env("VC_CAPTION_SHADING_PROBE_ONLY", False):
        args.caption_shading_probe_only = True
    if truthy_env("VC_CAPTION_APPLY_OUTLINE", False):
        args.caption_apply_outline = True
    if truthy_env("VC_CAPTION_APPLY_SHADOW", False):
        args.caption_apply_shadow = True
    env_outline_element = os.environ.get("VC_CAPTION_OUTLINE_ELEMENT")
    if env_outline_element:
        args.caption_outline_element = max(2, min(8, get_int(env_outline_element, args.caption_outline_element)))
    env_shadow_element = os.environ.get("VC_CAPTION_SHADOW_ELEMENT")
    if env_shadow_element:
        args.caption_shadow_element = max(2, min(8, get_int(env_shadow_element, args.caption_shadow_element)))
    env_outline_thickness = os.environ.get("VC_CAPTION_OUTLINE_THICKNESS")
    if env_outline_thickness:
        args.caption_outline_thickness = clamp_float(env_outline_thickness, 0.001, 0.50, 0.04)
    env_outline_scale = os.environ.get("VC_CAPTION_OUTLINE_WIDTH_SCALE")
    if env_outline_scale:
        args.caption_outline_width_scale = clamp_float(env_outline_scale, 0.10, 10.0, 1.0)
    env_shadow_offset_x = os.environ.get("VC_CAPTION_SHADOW_OFFSET_X")
    if env_shadow_offset_x:
        args.caption_shadow_offset_x = clamp_float(env_shadow_offset_x, -0.25, 0.25, 0.003)
    env_shadow_offset_y = os.environ.get("VC_CAPTION_SHADOW_OFFSET_Y")
    if env_shadow_offset_y:
        args.caption_shadow_offset_y = clamp_float(env_shadow_offset_y, -0.25, 0.25, 0.003)
    env_shadow_opacity = os.environ.get("VC_CAPTION_SHADOW_OPACITY")
    if env_shadow_opacity:
        args.caption_shadow_opacity = clamp_float(env_shadow_opacity, 0.0, 1.0, 0.85)
    env_shadow_softness = os.environ.get("VC_CAPTION_SHADOW_SOFTNESS")
    if env_shadow_softness:
        args.caption_shadow_softness = clamp_float(env_shadow_softness, 0.0, 0.50, 0.0)
    env_caption_force_font = os.environ.get("VC_CAPTION_FORCE_FONT_NAME")
    if env_caption_force_font:
        args.caption_force_font_name = env_caption_force_font
    env_caption_force_font_style = os.environ.get("VC_CAPTION_FORCE_FONT_STYLE")
    if env_caption_force_font_style:
        args.caption_force_font_style = env_caption_force_font_style
    env_caption_font_fallback_order = os.environ.get("VC_CAPTION_FONT_FALLBACK_ORDER")
    if env_caption_font_fallback_order:
        args.caption_font_fallback_order = env_caption_font_fallback_order
    env_caption_force_size = os.environ.get("VC_CAPTION_FORCE_TEXTPLUS_SIZE")
    if env_caption_force_size:
        args.caption_force_textplus_size = clamp_float(env_caption_force_size, 0.005, 0.50, 0.10)
    env_caption_size_scale = os.environ.get("VC_CAPTION_TEXTPLUS_SIZE_SCALE")
    if env_caption_size_scale:
        args.caption_textplus_size_scale = clamp_float(env_caption_size_scale, 0.10, 10.0, 1.5)
    if os.environ.get("VC_CAPTION_FORCE_POSITION_FROM_STYLE") is not None:
        args.caption_force_position_from_style = truthy_env("VC_CAPTION_FORCE_POSITION_FROM_STYLE", True)
    if os.environ.get("VC_CAPTION_USE_PER_CUE_STYLE_EVENTS") is not None:
        args.caption_use_per_cue_style_events = truthy_env("VC_CAPTION_USE_PER_CUE_STYLE_EVENTS", True)
    if truthy_env("VC_CAPTION_DISABLE_DURATION_STRICTNESS_FOR_PROBE", False):
        args.caption_disable_duration_strictness_for_probe = True

    return args


def main() -> None:
    global HARD_DEBUG_LOG, FORCE_DIRECT_RESOLVE_CALLS

    identity = runtime_script_identity()
    hard_debug("SCRIPT_ENTER", {
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "python": sys.executable,
        "version": VERSION,
        "script_file": identity.get("script_file"),
        "script_sha256": identity.get("sha256"),
        "script_size_bytes": identity.get("size_bytes"),
        "initial_debug_log": str(HARD_DEBUG_LOG),
    })
    hard_debug("SCRIPT_RUNTIME_IDENTITY", identity)

    try:
        args = parse_args()
        if args.debug_log:
            HARD_DEBUG_LOG = Path(args.debug_log).resolve()
        if getattr(args, "internal_menu_mode", False):
            FORCE_DIRECT_RESOLVE_CALLS = True
        hard_debug("ARGS_PARSED", vars(args))
    except SystemExit as exc:
        hard_debug("ARGPARSE_SYSTEM_EXIT", {"code": exc.code, "argv": sys.argv})
        raise
    except Exception as exc:
        hard_debug("ARGPARSE_EXCEPTION", {"error": repr(exc), "traceback": traceback.format_exc()})
        raise

    report: Dict[str, Any]

    if not args.generic:
        if not args.report:
            args.report = str((HARD_DEBUG_LOG.parent / "resolve_controller_missing_generic_report.json").resolve())
        report = {
            "ok": False,
            "controller_version": VERSION,
            "runtime_identity": runtime_script_identity(),
            "created_at_unix": now_unix(),
            "error_type": "MissingGenericCommands",
            "error": "Could not find *_generic_edit_commands.json automatically.",
            "debug_log": str(HARD_DEBUG_LOG),
            "fix": {
                "option_1": "Set environment variable VC_GENERIC to the exact generic_edit_commands.json path before launching Resolve.",
                "option_2": f"Keep your Video Cloner outputs under {DEFAULT_PROJECT_ROOT}\\data\\<videoId>\\davinci\\.",
                "option_3": "Run externally with --generic <path> --report <path>.",
            },
        }
        hard_debug("MISSING_GENERIC_COMMANDS", report)
    else:
        try:
            hard_debug("RUN_CONTROLLER_START")
            report = run_controller(args)
            hard_debug("RUN_CONTROLLER_DONE", {
                "ok": report.get("ok"),
                "summary": report.get("summary"),
                "error": report.get("error"),
                "errors": report.get("errors"),
            })
        except Exception as exc:
            hard_debug("RUN_CONTROLLER_EXCEPTION", {
                "type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })
            report = {
                "ok": False,
                "controller_version": VERSION,
                "runtime_identity": runtime_script_identity(),
                "created_at_unix": now_unix(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "debug_log": str(HARD_DEBUG_LOG),
                "hint": "Make sure DaVinci Resolve is open, the full FCPXML or legacy OTIO timeline is imported and selected, and the latest generic_edit_commands.json exists.",
            }

    if args.report:
        try:
            save_json(args.report, report)
            hard_debug("REPORT_WRITTEN", {"report": os.path.abspath(args.report)})
        except Exception as exc:
            hard_debug("REPORT_WRITE_FAILED", {"report": args.report, "error": repr(exc)})
            report["ok"] = False
            report["report_write_error"] = str(exc)

    # In Resolve's menu runtime stdout is usually invisible, but keep it useful for external n8n runs.
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    hard_debug("STDOUT_PRINTED", {"ok": report.get("ok")})

    if not report.get("ok"):
        hard_debug("EXIT_NON_ZERO", {"code": 1})
        sys.exit(1)

    hard_debug("EXIT_ZERO", {"code": 0})


if __name__ == "__main__":
    main()
