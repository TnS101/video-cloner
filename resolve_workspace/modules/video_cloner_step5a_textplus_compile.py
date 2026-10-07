from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import step_3D_visual_instance_correction as visual
from scripts.davinci.resolve_apply_video_cloner_metadata import set_caption_textplus_style_inputs

TASK_ID = "VIDEO_CLONER_STEP5A_REAL_TEXTPLUS_COMPILE_V1"
MODE = "apply_or_verify"


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def find_timeline(project: Any, name: str, uid: str | None = None) -> Any:
    rows = [row for row in carrier._timelines(project) if str(carrier._safe(row, "GetName", default="") or "") == name]
    if uid:
        rows = [row for row in rows if carrier._unique_id(row) == uid]
    return rows[0] if len(rows) == 1 else None


def protected_snapshot(timeline: Any) -> dict[str, Any]:
    snap = carrier.timeline_snapshot(timeline)
    return {"name": snap["name"], "unique_id": snap["unique_id"], "signature": snap["signature"], "item_count": len(snap["items"]), "video_track_count": snap["video_track_count"], "audio_track_count": snap["audio_track_count"]}


def textplus(item: Any) -> tuple[Any, Any]:
    comp = carrier._safe(item, "GetFusionCompByIndex", 1)
    tools = carrier._safe(comp, "GetToolList", False, "TextPlus", default={}) if comp is not None else {}
    found = [tool for tool in tools.values() if carrier._tool_regid(tool) == "TextPlus"] if isinstance(tools, Mapping) else []
    if comp is None or len(found) != 1:
        raise ValueError("textplus_identity")
    return comp, found[0]


def rgb_hex(values: list[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(value))):02x}" for value in values)


def style_for(row: Mapping[str, Any]) -> tuple[dict[str, Any], argparse.Namespace]:
    shadow = row["advanced_effects"]["shadow"]
    style = {
        "font_family": row["font"]["resolve_family"], "font_style": row["font"]["resolve_style"],
        "textplus_size": row["size"]["resolve_value"], "center": row["position"]["resolve_center"],
        "text_color": rgb_hex(row["fill"]["resolve_rgb"]), "stroke_color": rgb_hex(row["stroke"]["resolve_rgb"]),
        "stroke_width": row["stroke"]["resolve_width"], "shadow_enabled": shadow is not None,
        "shadow_color": rgb_hex((shadow or {}).get("color", {}).get("effective_composite_rgb") or [0, 0, 0]),
        "shadow_opacity": float((shadow or {}).get("strength", {}).get("effective_darkening") or 0), "case_style": "preserve",
    }
    args = argparse.Namespace(
        caption_apply_outline=bool(row["stroke"]["resolve_enabled"]), caption_apply_shadow=shadow is not None,
        caption_shading_probe_only=False, caption_outline_element=2, caption_shadow_element=3,
        caption_outline_width_scale=1.0, caption_outline_thickness=row["stroke"]["resolve_width"] or None,
        caption_shadow_opacity=style["shadow_opacity"] or None,
        caption_shadow_offset_x=float((shadow or {}).get("offset", {}).get("x_normalized") or 0),
        caption_shadow_offset_y=float((shadow or {}).get("offset", {}).get("y_normalized") or 0),
        caption_shadow_softness=float((shadow or {}).get("softness", {}).get("normalized_value") or 0) or None,
    )
    return style, args


def apply_keys(tool: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    static_angle = row["static_rotation"]["resolve_degrees"]
    if static_angle is not None:
        results["static_rotation"] = visual.set_static(tool, "AngleZ", float(static_angle))
    mapping = {"position": ("Center", "Path"), "scale": ("Size", "BezierSpline"), "rotation": ("AngleZ", "BezierSpline")}
    for channel, (input_name, modifier_name) in mapping.items():
        keys = row["keyframes"][channel]
        if not keys:
            continue
        modifier = visual.ensure_modifier(tool, input_name, modifier_name)
        writes = [visual.write_key(tool, input_name, int(key["local_frame"]), key["value"]) for key in keys] if modifier.get("ok") else []
        results[channel] = {"modifier": modifier, "write_count": len(writes), "writes_ok": len(writes) == len(keys) and all(item.get("ok") for item in writes), "failed_writes": [{"key": keys[index], "result": item} for index, item in enumerate(writes) if not item.get("ok")]}
    visibility = row["keyframes"]["relative_visibility"]
    if visibility:
        inputs = [name for name in ("Opacity1", "Opacity2", "Opacity3") if visual.base.find_input(tool, name) is not None]
        visibility_rows = []
        for name in inputs:
            modifier = visual.ensure_modifier(tool, name, "BezierSpline")
            writes = [visual.write_key(tool, name, int(key["local_frame"]), float(key["value"])) for key in visibility] if modifier.get("ok") else []
            visibility_rows.append({"input": name, "modifier": modifier, "write_count": len(writes), "writes_ok": len(writes) == len(visibility) and all(item.get("ok") for item in writes), "failed_writes": [{"key": visibility[index], "result": item} for index, item in enumerate(writes) if not item.get("ok")]})
        results["relative_visibility"] = {"inputs": visibility_rows, "ok": bool(visibility_rows) and all(item["writes_ok"] for item in visibility_rows)}
    ok = all(value.get("ok", value.get("writes_ok", True)) for value in results.values())
    results["ok"] = ok
    return results


def read_object(item: Any, expected: Mapping[str, Any], actual_track: int) -> dict[str, Any]:
    _comp, tool = textplus(item)
    base = visual.base
    def point(value: Any) -> Any:
        if isinstance(value, Mapping):
            x, y = value.get(1, value.get("1")), value.get(2, value.get("2"))
            return [float(x), float(y)] if x is not None and y is not None else base.json_safe(value)
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return [float(value[0]), float(value[1])]
        return base.json_safe(value)

    actual = {
        "source_identity": expected["source_identity"], "item_unique_id": carrier._unique_id(item),
        "item_name": str(carrier._safe(item, "GetName", default="") or ""),
        "track": actual_track, "start": int(carrier._safe(item, "GetStart")), "end": int(carrier._safe(item, "GetEnd")),
        "text": str(base.read_input(tool, "StyledText", 0) or ""), "font": str(base.read_input(tool, "Font", 0) or ""),
        "font_style": str(base.read_input(tool, "Style", 0) or ""), "size": base.json_safe(base.read_input(tool, "Size", 0)),
        "center": point(base.read_input(tool, "Center", 0)), "fill": [base.read_input(tool, name, 0) for name in ("Red1", "Green1", "Blue1", "Alpha1")],
        "stroke": {"enabled": base.json_safe(base.read_input(tool, "Enabled2", 0)), "width": base.json_safe(base.read_input(tool, "Thickness2", 0)), "rgba": [base.read_input(tool, name, 0) for name in ("Red2", "Green2", "Blue2", "Alpha2")]},
        "opacity": {"alpha1": base.json_safe(base.read_input(tool, "Alpha1", 0)), "opacity1": base.json_safe(base.read_input(tool, "Opacity1", 0))},
        "shadow": {"enabled": base.json_safe(base.read_input(tool, "Enabled3", 0)), "rgba": [base.read_input(tool, name, 0) for name in ("Red3", "Green3", "Blue3", "Alpha3")], "offset": point(base.read_input(tool, "Offset3", 0)), "softness_x": base.json_safe(base.read_input(tool, "SoftnessX3", 0)), "softness_y": base.json_safe(base.read_input(tool, "SoftnessY3", 0))},
        "static_rotation": base.json_safe(base.read_input(tool, "AngleZ", 0)), "keyframes": {},
    }
    input_map = {"position": "Center", "scale": "Size", "rotation": "AngleZ", "relative_visibility": "Opacity1"}
    for channel, input_name in input_map.items():
        actual["keyframes"][channel] = [{"timeline_frame": key["timeline_frame"], "local_frame": key["local_frame"], "expected": key["value"], "actual": point(base.read_input(tool, input_name, int(key["local_frame"]))) if channel == "position" else base.json_safe(base.read_input(tool, input_name, int(key["local_frame"]))) } for key in expected["keyframes"][channel]]
    return actual


def close(a: Any, b: Any, tolerance: float = 1e-4) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tolerance) for x, y in zip(a, b))
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return str(a) == str(b)


def parity(contract: Mapping[str, Any], readback: list[dict[str, Any]]) -> dict[str, Any]:
    actual = {row["source_identity"]: row for row in readback}
    rows, failures = [], []
    for expected in contract["objects"]:
        identity = expected["source_identity"]; got = actual.get(identity)
        if got is None:
            failures.append(f"missing:{identity}"); continue
        shadow = expected["advanced_effects"]["shadow"]
        shadow_expected = shadow is not None
        checks = {
            "text": got["text"] == expected["text"]["value"], "timing": [got["start"], got["end"]] == expected["resolve_interval"],
            "font": got["font"] == expected["font"]["resolve_family"], "font_style": got["font_style"] == expected["font"]["resolve_style"],
            "size": True if expected["keyframes"]["scale"] else close(got["size"], expected["size"]["resolve_value"]), "position": True if expected["keyframes"]["position"] else close(got["center"], expected["position"]["resolve_center"]),
            "fill": close(got["fill"], [value / 255 for value in expected["fill"]["resolve_rgb"]] + [1.0]),
            "stroke": bool(got["stroke"]["enabled"]) == bool(expected["stroke"]["resolve_enabled"]),
            "opacity_visibility": close(got["opacity"]["alpha1"], 1.0),
            "z_order": got["track"] == expected["z_order_track"]["resolve_track"],
            "shadow": bool(got["shadow"]["enabled"]) == shadow_expected and (not shadow_expected or (close(got["shadow"]["rgba"], [value / 255 for value in shadow["color"]["effective_composite_rgb"]] + [shadow["strength"]["effective_darkening"]]) and close(got["shadow"]["offset"], [shadow["offset"]["x_normalized"], shadow["offset"]["y_normalized"]]) and close(got["shadow"]["softness_x"], shadow["softness"]["normalized_value"]) and close(got["shadow"]["softness_y"], shadow["softness"]["normalized_value"]))),
            "static_rotation": True if expected["keyframes"]["rotation"] or expected["static_rotation"]["resolve_degrees"] is None else close(got["static_rotation"], expected["static_rotation"]["resolve_degrees"]),
            "keyframes": all(close(key["actual"], key["expected"]) for values in got["keyframes"].values() for key in values),
        }
        rows.append({"source_identity": identity, "checks": checks, "all_match": all(checks.values())})
        failures.extend(f"{identity}:{name}" for name, value in checks.items() if not value)
    counts = {name: {"match": sum(row["checks"].get(name) is True for row in rows), "mismatch": sum(row["checks"].get(name) is False for row in rows)} for name in ("text", "timing", "font", "font_style", "size", "position", "fill", "stroke", "opacity_visibility", "z_order", "shadow", "static_rotation", "keyframes")}
    return {"schema": "video_cloner_step5a_property_parity_validation", "ok": len(rows) == 113 and not failures, "object_count": len(rows), "counts": counts, "failures": failures, "rows": rows}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}; payload = command.get("payload") or {}; run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "failures": [], "mutation_counts": {"timeline_create": 0, "textplus_create": 0, "project_save": 0, "delete": 0}}
    target = project = previous = None; created = saved = False
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        contract_path = Path(str(payload["contract_path"])).resolve(); report_dir = Path(str(payload["report_dir"])).resolve(); baseline = Path(str(payload["baseline_fcpxml"])).resolve()
        if sha(contract_path) != payload.get("contract_sha256") or sha(baseline) != payload.get("baseline_fcpxml_sha256"):
            raise ValueError("artifact_hash")
        contract = read(contract_path)
        if contract.get("object_count") != 113 or contract.get("validation_timeline") != payload.get("target_timeline"):
            raise ValueError("compile_contract")
        manager = carrier._safe(resolve, "GetProjectManager"); project = carrier._safe(manager, "GetCurrentProject")
        if project is None or str(carrier._safe(project, "GetName", default="") or "") != contract["project"]:
            raise ValueError("project_identity")
        protected = find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"])
        if protected is None:
            raise ValueError("protected_timeline_identity")
        protected_before = protected_snapshot(protected); previous = carrier._safe(project, "GetCurrentTimeline")
        target = find_timeline(project, contract["validation_timeline"])
        first_application = target is None
        application_rows = []
        if first_application:
            before = carrier._timelines(project); before_ids = {carrier._unique_id(row) for row in before}
            returned = carrier._safe(carrier._safe(project, "GetMediaPool"), "ImportTimelineFromFile", str(baseline), {"timelineName": contract["validation_timeline"]})
            delta = [row for row in carrier._timelines(project) if carrier._unique_id(row) not in before_ids]
            target = returned if returned not in (None, False, True) else delta[0] if len(delta) == 1 else None
            if target is None or len(delta) != 1:
                raise ValueError("target_ownership")
            created = True; result["mutation_counts"]["timeline_create"] = 1
            carrier._safe(target, "SetName", contract["validation_timeline"])
            if str(carrier._safe(target, "GetName", default="") or "") != contract["validation_timeline"]:
                raise ValueError("target_name")
            max_track = max(row["z_order_track"]["resolve_track"] for row in contract["objects"])
            while int(carrier._safe(target, "GetTrackCount", "video", default=0) or 0) < max_track:
                if not carrier._safe(target, "AddTrack", "video", default=False):
                    raise ValueError("track_creation")
            if not carrier._safe(project, "SetCurrentTimeline", target, default=False):
                raise ValueError("target_activation")
            v1 = list(carrier._safe(target, "GetItemListInTrack", "video", 1, default=[]) or []); source = carrier._safe(v1[0], "GetMediaPoolItem") if v1 else None
            titles = [{"caption_id": row["source_identity"], "text": row["text"]["value"], "timeline_start": row["resolve_interval"][0], "duration": row["resolve_interval"][1] - row["resolve_interval"][0], "lane": row["z_order_track"]["lane"]} for row in contract["objects"]]
            provision = carrier.apply_carrier_textplus_v2(project, target, titles, source, {"ownership": carrier.CARRIER_OWNERSHIP, "preexisting": True, "deletion_permitted": False, "unique_id": carrier._unique_id(source), "source_start": 0})
            if provision.get("ok") is not True or provision.get("created_count") != 113:
                raise ValueError(f"textplus_provision:{provision.get('failures')}")
            result["mutation_counts"]["textplus_create"] = 113
            items = {carrier._unique_id(item): item for track in range(2, max_track + 1) for item in (carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or [])}
            provision_rows = {row["caption_id"]: row for row in provision["rows"]}
            for index, row in enumerate(contract["objects"], 1):
                item = items.get(provision_rows[row["source_identity"]]["item_unique_id"])
                if item is None: raise ValueError(f"item_reacquire:{row['source_identity']}")
                carrier._safe(item, "SetName", row["intended_resolve_name"])
                comp, tool = textplus(item); style, args = style_for(row)
                styled = set_caption_textplus_style_inputs(tool, {"text": row["text"]["value"]}, style, index, args=args, comp=comp)
                keys = apply_keys(tool, row)
                if styled.get("applied") is not True or keys.get("ok") is not True:
                    result["failed_application"] = {"source_identity": row["source_identity"], "style": styled, "keyframe_application": keys}
                    raise ValueError(f"application:{row['source_identity']}:style={styled.get('applied')}:keys={keys.get('ok')}")
                application_rows.append({"source_identity": row["source_identity"], "item_unique_id": carrier._unique_id(item), "track": row["z_order_track"]["resolve_track"], "style": styled, "keyframe_application": keys})
            if carrier._safe(manager, "SaveProject", default=False) is False:
                raise ValueError("save_project")
            saved = True; result["mutation_counts"]["project_save"] = 1
            project = carrier._safe(manager, "GetCurrentProject"); target = find_timeline(project, contract["validation_timeline"])
        if target is None or carrier._same_timeline(target, protected):
            raise ValueError("target_safety")
        max_track = max(row["z_order_track"]["resolve_track"] for row in contract["objects"])
        actual_items = []
        for track in range(2, max_track + 1):
            for item in carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or []:
                if carrier._safe(item, "GetFusionCompCount", default=0): actual_items.append((track, item))
        if len(actual_items) != 113:
            raise ValueError(f"object_count:{len(actual_items)}")
        expected_by_geometry = {(row["z_order_track"]["resolve_track"], row["resolve_interval"][0], row["resolve_interval"][1]): row for row in contract["objects"]}
        readback = []
        for track, item in actual_items:
            key = (track, int(carrier._safe(item, "GetStart")), int(carrier._safe(item, "GetEnd")))
            expected = expected_by_geometry.get(key)
            if expected is None: raise ValueError(f"unexpected_object:{key}")
            readback.append(read_object(item, expected, track))
        parity_result = parity(contract, readback)
        if not parity_result["ok"]:
            raise ValueError(f"parity:{parity_result['failures'][:10]}")
        protected_after = protected_snapshot(find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"]))
        protected_validation = {"schema": "video_cloner_step5a_protected_timeline_validation", "before": protected_before, "after": protected_after, "mutated": protected_before != protected_after, "status": "PASS" if protected_before == protected_after else "FAIL"}
        if protected_validation["mutated"]: raise ValueError("protected_timeline_mutated")
        target_snap = carrier.timeline_snapshot(target)
        application = {"schema": "video_cloner_step5a_resolve_application_manifest", "project": contract["project"], "protected_timeline": contract["protected_timeline"], "validation_timeline": {"name": target_snap["name"], "unique_id": target_snap["unique_id"], "signature": target_snap["signature"]}, "first_application": first_application, "objects": application_rows if first_application else [{"source_identity": row["source_identity"], "item_unique_id": row["item_unique_id"], "track": row["track"]} for row in readback], "object_count": 113, "rollback_scope": "OWNED_VALIDATION_TIMELINE_ONLY", "save_count": result["mutation_counts"]["project_save"]}
        readback_doc = {"schema": "video_cloner_step5a_resolve_readback", "project": contract["project"], "timeline": application["validation_timeline"], "object_count": 113, "objects": sorted(readback, key=lambda row: row["source_identity"])}
        write(report_dir / "step5a_resolve_application_manifest.json", application)
        write(report_dir / "step5a_resolve_readback.json", readback_doc)
        write(report_dir / "step5a_property_parity_validation.json", parity_result)
        write(report_dir / "step5a_protected_timeline_validation.json", protected_validation)
        idempotency = {"schema": "video_cloner_step5a_idempotency_validation", "run_id": run_id, "mode": "FIRST_APPLICATION" if first_application else "SECOND_IDENTICAL_APPLICATION", "object_count": 113, "created_this_run": result["mutation_counts"]["textplus_create"], "duplicate_semantic_identities": 0, "timeline_signature": target_snap["signature"], "protected_unchanged": True, "pass": True}
        write(report_dir / "step5a_idempotency_validation.json", idempotency)
        result.update({"ok": True, "classification": "STEP5A_REAL_TEXTPLUS_COMPILE_PASS" if first_application else "STEP5A_IDEMPOTENT_READBACK_PASS", "project": contract["project"], "validation_timeline": application["validation_timeline"], "object_count": 113, "parity": parity_result["counts"], "protected_timeline_mutated": False, "first_application": first_application})
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
        if created and not saved and project is not None and target is not None:
            deleted = bool(carrier._safe(carrier._safe(project, "GetMediaPool"), "DeleteTimelines", [target], default=False))
            result["mutation_counts"]["delete"] = int(deleted); result["rollback"] = {"attempted": True, "deleted_owned_validation_timeline": deleted}
        else:
            result["rollback"] = {"attempted": False, "reason": "saved" if saved else "no_owned_unsaved_timeline"}
    finally:
        if project is not None and previous is not None:
            carrier._safe(project, "SetCurrentTimeline", previous, default=False)
    return result
