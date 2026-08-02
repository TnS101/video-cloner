#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VERSION = "resolve_caption_font_probe_v1_0_snapshot_restore"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_CONFIG = str(Path(DEFAULT_PROJECT_ROOT) / "data" / "DZsqH7auhjt" / "davinci" / "resolve_font_probe_config.json")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def compact_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def safe_call(obj: Any, name: str, *args: Any, default: Any = None) -> Any:
    try:
        method = getattr(obj, name, None)
        if method is None:
            return default
        return method(*args)
    except Exception:
        return default


def normalize(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    try:
        return str(value)
    except Exception:
        return None


def get_resolve() -> Any:
    for name in ("resolve", "Resolve"):
        candidate = globals().get(name)
        if candidate is not None:
            return candidate
    bmd_obj = globals().get("bmd")
    if bmd_obj is not None:
        try:
            candidate = bmd_obj.scriptapp("Resolve")
            if candidate is not None:
                return candidate
        except Exception:
            pass
    try:
        import DaVinciResolveScript as dvr_script
        return dvr_script.scriptapp("Resolve")
    except Exception:
        return None


def get_fusion(resolve_obj: Any) -> Any:
    for name in ("fusion", "Fusion"):
        candidate = globals().get(name)
        if candidate is not None:
            return candidate
    for method_name in ("Fusion", "GetFusion"):
        candidate = safe_call(resolve_obj, method_name, default=None)
        if candidate is not None:
            return candidate
    return None


def flatten_strings(value: Any) -> List[str]:
    output: List[str] = []
    if value is None:
        return output
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key, item in value.items():
            output.extend(flatten_strings(key))
            output.extend(flatten_strings(item))
        return output
    if isinstance(value, (list, tuple, set)):
        for item in value:
            output.extend(flatten_strings(item))
    return output


def font_manager_files(fusion_obj: Any) -> Dict[str, Any]:
    result = {
        "available": False,
        "font_file_count": 0,
        "font_files": [],
        "errors": [],
    }
    try:
        manager = getattr(fusion_obj, "FontManager", None)
        getter = getattr(manager, "GetFontList", None) if manager is not None else None
        if getter is None:
            return result
        raw = getter()
        values = []
        seen = set()
        for value in flatten_strings(raw):
            text = str(value).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            values.append(text)
        result["available"] = True
        result["font_file_count"] = len(values)
        result["font_files"] = values
    except Exception as exc:
        result["errors"].append(compact_exception(exc))
    return result


def item_name(item: Any) -> str:
    for method in ("GetName",):
        value = safe_call(item, method, default=None)
        if value:
            return str(value)
    props = safe_call(item, "GetProperty", default={}) or {}
    for key in ("Name", "Clip Name"):
        if props.get(key):
            return str(props[key])
    return ""


def fusion_comp(item: Any) -> Any:
    count = safe_call(item, "GetFusionCompCount", default=0) or 0
    try:
        count_i = int(count)
    except Exception:
        count_i = 0
    if count_i > 0:
        comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
        if comp is not None:
            return comp
    names = safe_call(item, "GetFusionCompNameList", default=[]) or []
    if isinstance(names, (list, tuple)) and names:
        return safe_call(item, "LoadFusionCompByName", names[0], default=None)
    return None


def tool_regid(tool: Any) -> str:
    attrs = safe_call(tool, "GetAttrs", default={}) or {}
    return str(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID") or "")


def tool_name(tool: Any) -> str:
    attrs = safe_call(tool, "GetAttrs", default={}) or {}
    return str(attrs.get("TOOLS_Name") or attrs.get("TOOLST_Name") or "")


def list_tools(comp: Any) -> List[Any]:
    raw = safe_call(comp, "GetToolList", False, default={}) or {}
    if isinstance(raw, dict):
        return list(raw.values())
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return []


def find_textplus(comp: Any) -> Optional[Any]:
    for tool in list_tools(comp):
        regid = tool_regid(tool).lower()
        name = tool_name(tool).lower()
        if "textplus" in regid or regid in {"textplus", "text+"} or name.startswith("text"):
            return tool
    return None


def get_input(tool: Any, names: Sequence[str]) -> Dict[str, Any]:
    attempts = []
    for name in names:
        try:
            method = getattr(tool, "GetInput", None)
            if method:
                for args in ((name,), (name, 0)):
                    try:
                        value = method(*args)
                        attempts.append({"name": name, "method": f"GetInput{args}", "value": json_safe(value)})
                        if value not in (None, ""):
                            return {"ok": True, "name": name, "value": json_safe(value), "attempts": attempts}
                    except Exception as exc:
                        attempts.append({"name": name, "error": compact_exception(exc)})
        except Exception:
            pass
        try:
            value = getattr(tool, name)
            attempts.append({"name": name, "method": "getattr", "value": json_safe(value)})
            if value not in (None, ""):
                return {"ok": True, "name": name, "value": json_safe(value), "attempts": attempts}
        except Exception as exc:
            attempts.append({"name": name, "error": compact_exception(exc)})
    return {"ok": False, "value": None, "attempts": attempts}


def set_input(tool: Any, names: Sequence[str], value: Any) -> Dict[str, Any]:
    attempts = []
    for name in names:
        try:
            method = getattr(tool, "SetInput", None)
            if method:
                ok = method(name, value)
                attempts.append({"name": name, "method": "SetInput", "ok": bool(ok)})
                if ok:
                    return {"ok": True, "name": name, "attempts": attempts}
        except Exception as exc:
            attempts.append({"name": name, "method": "SetInput", "error": compact_exception(exc)})
        try:
            setattr(tool, name, value)
            attempts.append({"name": name, "method": "setattr", "ok": True})
            return {"ok": True, "name": name, "attempts": attempts}
        except Exception as exc:
            attempts.append({"name": name, "method": "setattr", "error": compact_exception(exc)})
    return {"ok": False, "attempts": attempts}


def family_file_match(candidate: Dict[str, Any], inventory_files: Sequence[str]) -> Dict[str, Any]:
    family = normalize(candidate.get("family"))
    face = normalize(candidate.get("face") or "Regular")
    expected_file = str(candidate.get("font_file") or "").replace("\\", "/").split("/")[-1].lower()
    matched = []
    for value in inventory_files:
        normalized_path = str(value).replace("\\", "/")
        base = normalized_path.split("/")[-1].lower()
        token = normalize(base.rsplit(".", 1)[0])
        if expected_file and base == expected_file:
            matched.append(value)
            continue
        if family and family in token:
            if face == "regular" or not face or face in token:
                matched.append(value)
    return {
        "matched": bool(matched),
        "matched_files": matched[:10],
    }


def select_probe_item(timeline: Any, track_index: int, prefix: str) -> Tuple[Optional[Any], Dict[str, Any]]:
    items = safe_call(timeline, "GetItemListInTrack", "video", track_index, default=[]) or []
    attempts = []
    for item in items:
        name = item_name(item)
        if prefix and not name.startswith(prefix):
            continue
        comp = fusion_comp(item)
        if comp is None:
            attempts.append({"name": name, "reason": "no_fusion_comp"})
            continue
        tool = find_textplus(comp)
        if tool is None:
            attempts.append({"name": name, "reason": "no_textplus_tool"})
            continue
        return item, {
            "selected": True,
            "name": name,
            "track_index": track_index,
            "fusion_comp_found": True,
            "textplus_tool_name": tool_name(tool),
            "textplus_tool_regid": tool_regid(tool),
            "attempts": attempts,
        }
    return None, {
        "selected": False,
        "track_index": track_index,
        "attempts": attempts,
    }


def runtime_identity() -> Dict[str, Any]:
    try:
        path = Path(__file__).resolve()
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "version": VERSION,
        }
    except Exception:
        return {"path": None, "sha256": None, "version": VERSION}


def main() -> int:
    config_path = Path(os.environ.get("VC_FONT_PROBE_CONFIG", DEFAULT_CONFIG))
    if not config_path.is_file():
        raise FileNotFoundError(f"Font probe config not found: {config_path}")
    config = load_json(config_path)

    candidate_path = Path(config["font_candidates"])
    output_path = Path(config["resolve_font_inventory_output"])
    if not candidate_path.is_file():
        raise FileNotFoundError(candidate_path)
    candidates_payload = load_json(candidate_path)

    resolve_obj = get_resolve()
    if resolve_obj is None:
        raise RuntimeError("Resolve handle is unavailable. Run from Workspace -> Scripts.")
    project_manager = safe_call(resolve_obj, "GetProjectManager", default=None)
    project = safe_call(project_manager, "GetCurrentProject", default=None)
    timeline = safe_call(project, "GetCurrentTimeline", default=None)
    if timeline is None:
        raise RuntimeError("No active Resolve timeline")

    fusion_obj = get_fusion(resolve_obj)
    inventory = font_manager_files(fusion_obj) if fusion_obj is not None else {
        "available": False,
        "font_file_count": 0,
        "font_files": [],
        "errors": ["Fusion handle unavailable"],
    }

    track_index = int(config.get("caption_textplus_track") or 3)
    prefix = str(config.get("caption_item_prefix") or "VC_TEXTPLUS_")
    item, selection = select_probe_item(timeline, track_index, prefix)
    if item is None:
        raise RuntimeError(
            f"No existing V3 Text+ item was found on video track {track_index}. "
            "Step 3A never creates or deletes caption items."
        )
    comp = fusion_comp(item)
    tool = find_textplus(comp)
    if tool is None:
        raise RuntimeError("Selected V3 item has no TextPlus tool")

    family_names = config.get("font_family_inputs") or ["Font"]
    face_names = config.get("font_face_inputs") or ["Style", "FontStyle"]
    original_family = get_input(tool, family_names)
    original_face = get_input(tool, face_names)

    max_candidates = int(config.get("max_candidates") or 24)
    candidate_rows = candidates_payload.get("resolve_probe_candidates") or []
    candidate_rows = candidate_rows[:max_candidates]

    results = []
    accepted_keys = set()
    for candidate in candidate_rows:
        family = str(candidate.get("family") or "").strip()
        face = str(candidate.get("face") or "Regular").strip() or "Regular"
        inventory_match = family_file_match(candidate, inventory.get("font_files") or [])
        row = {
            "family": family,
            "face": face,
            "visual_score": candidate.get("visual_score"),
            "font_file": candidate.get("font_file"),
            "inventory_match": inventory_match,
            "write_attempted": False,
            "family_write": None,
            "face_write": None,
            "family_readback": None,
            "face_readback": None,
            "accepted": False,
            "errors": [],
        }
        if not inventory_match["matched"]:
            row["errors"].append("not_present_in_fusion_font_manager")
            results.append(row)
            continue

        row["write_attempted"] = True
        family_write = set_input(tool, family_names, family)
        face_write = set_input(tool, face_names, face)
        row["family_write"] = family_write
        row["face_write"] = face_write
        time.sleep(float(config.get("readback_delay_sec") or 0.08))
        family_read = get_input(tool, family_names)
        face_read = get_input(tool, face_names)
        row["family_readback"] = family_read
        row["face_readback"] = face_read

        read_family = str(family_read.get("value") or "")
        read_face = str(face_read.get("value") or "")
        family_ok = normalize(family) == normalize(read_family)
        face_ok = (
            normalize(face) == normalize(read_face)
            or (normalize(face) == "regular" and not normalize(read_face))
        )
        row["accepted"] = bool(
            family_write.get("ok")
            and face_write.get("ok")
            and family_ok
            and face_ok
        )
        if row["accepted"]:
            accepted_keys.add((normalize(family), normalize(face)))
        else:
            if not family_ok:
                row["errors"].append("family_readback_mismatch")
            if not face_ok:
                row["errors"].append("face_readback_mismatch")
        results.append(row)

    restore_family = set_input(tool, family_names, original_family.get("value"))
    restore_face = set_input(tool, face_names, original_face.get("value"))
    time.sleep(float(config.get("readback_delay_sec") or 0.08))
    restored_family = get_input(tool, family_names)
    restored_face = get_input(tool, face_names)
    restore_ok = bool(
        restore_family.get("ok")
        and restore_face.get("ok")
        and normalize(restored_family.get("value")) == normalize(original_family.get("value"))
        and normalize(restored_face.get("value")) == normalize(original_face.get("value"))
    )

    accepted = [row for row in results if row.get("accepted")]
    profiles = []
    for profile in candidates_payload.get("profiles") or []:
        selected = None
        for candidate in profile.get("candidates") or []:
            key = (normalize(candidate.get("family")), normalize(candidate.get("face") or "Regular"))
            if key in accepted_keys:
                selected = {
                    "family": candidate.get("family"),
                    "face": candidate.get("face") or "Regular",
                    "font_file": candidate.get("path"),
                    "visual_score": candidate.get("visual_score"),
                    "resolve_verified": True,
                }
                break
        profiles.append({
            "style_profile_id": profile.get("style_profile_id"),
            "is_primary_style": bool(profile.get("is_primary_style")),
            "visual_selection_status": profile.get("selection_status"),
            "selected_mapping": selected,
            "mapping_status": "resolve_verified" if selected else "unresolved",
        })

    primary = next((row for row in profiles if row.get("is_primary_style")), None)
    payload = {
        "success": bool(accepted and restore_ok and primary and primary.get("selected_mapping")),
        "schema": "video_cloner_resolve_font_inventory",
        "schema_version": "1.0",
        "analysis_version": VERSION,
        "runtime_identity": runtime_identity(),
        "config_path": str(config_path),
        "font_candidates_path": str(candidate_path),
        "timeline": {
            "name": safe_call(timeline, "GetName", default=None),
            "caption_textplus_track": track_index,
        },
        "probe_item": selection,
        "snapshot": {
            "font_family": original_family,
            "font_face": original_face,
        },
        "fusion_font_manager": {
            "available": inventory.get("available"),
            "font_file_count": inventory.get("font_file_count"),
            "errors": inventory.get("errors"),
        },
        "candidates_tested": len(results),
        "accepted_count": len(accepted),
        "accepted_candidates": accepted,
        "candidate_results": results,
        "profile_mappings": profiles,
        "primary_mapping": primary,
        "restore": {
            "ok": restore_ok,
            "family_write": restore_family,
            "face_write": restore_face,
            "family_readback": restored_family,
            "face_readback": restored_face,
        },
        "policy": {
            "probe_only": True,
            "no_caption_items_created": True,
            "no_caption_items_deleted": True,
            "font_inputs_restored": restore_ok,
            "automatic_full_v3_apply_not_performed": True,
        },
        "failures": [],
    }
    if not accepted:
        payload["failures"].append("no_candidate_accepted_by_resolve")
    if not restore_ok:
        payload["failures"].append("font_snapshot_restore_failed")
    if not primary or not primary.get("selected_mapping"):
        payload["failures"].append("primary_style_not_resolve_mapped")

    write_json(output_path, payload)
    print(json.dumps({
        "success": payload["success"],
        "output": str(output_path),
        "candidates_tested": len(results),
        "accepted_count": len(accepted),
        "primary_mapping": (primary or {}).get("selected_mapping"),
        "restore_ok": restore_ok,
        "failures": payload["failures"],
    }, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        try:
            config_path = Path(os.environ.get("VC_FONT_PROBE_CONFIG", DEFAULT_CONFIG))
            config = load_json(config_path) if config_path.is_file() else {}
            output = Path(config.get("resolve_font_inventory_output") or (
                Path(DEFAULT_PROJECT_ROOT) / "data" / "DZsqH7auhjt" / "davinci" /
                "DZsqH7auhjt_resolve_font_inventory.json"
            ))
            write_json(output, {
                "success": False,
                "schema": "video_cloner_resolve_font_inventory",
                "schema_version": "1.0",
                "analysis_version": VERSION,
                "runtime_identity": runtime_identity(),
                "failures": [compact_exception(exc)],
            })
        except Exception:
            pass
        raise
