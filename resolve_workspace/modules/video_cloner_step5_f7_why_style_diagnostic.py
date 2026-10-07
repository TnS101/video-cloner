"""Live, disposable diagnostic for the F7 ``why?`` Text+ style application."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import video_cloner_step5_f7_validation_rebuild as f7

TASK_ID = "VIDEO_CLONER_STEP5_F7_WHY_STYLE_LIVE_DIAGNOSTIC_V1"
MODE = "diagnose_why_style"
WHY_ID = "recovered_display_object_why_0001"


class _RecordingTool:
    def __init__(self, tool: Any) -> None:
        object.__setattr__(self, "_tool", tool)
        object.__setattr__(self, "writes", [])

    def __getattr__(self, name: str) -> Any:
        return getattr(self._tool, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._tool, name, value)

    def SetInput(self, name: str, value: Any, *args: Any) -> Any:  # Resolve API name
        try:
            returned = self._tool.SetInput(name, value, *args)
            self.writes.append({
                "input": name,
                "value": f7.IMPLEMENTATION.visual.base.json_safe(value),
                "value_json": json.dumps(f7.IMPLEMENTATION.visual.base.json_safe(value), sort_keys=True),
                "args": f7.IMPLEMENTATION.visual.base.json_safe(args),
                "returned": f7.IMPLEMENTATION.visual.base.json_safe(returned),
            })
            return returned
        except BaseException as exc:
            self.writes.append({
                "input": name,
                "value": f7.IMPLEMENTATION.visual.base.json_safe(value),
                "value_json": json.dumps(f7.IMPLEMENTATION.visual.base.json_safe(value), sort_keys=True),
                "args": f7.IMPLEMENTATION.visual.base.json_safe(args),
                "exception": f7.IMPLEMENTATION.visual.base.compact_exception(exc),
            })
            raise


def _write_for(style: Mapping[str, Any], name: str, expected: Any) -> dict[str, Any]:
    result = dict((style.get("writes") or {}).get(name) or {})
    attempt = ((result.get("attempts") or [{}])[0]) if name != "gradient" else {}
    return {
        "input": "ShadingGradient1" if name == "gradient" else ("Type1" if name == "gradient_type" else "Alpha1"),
        "expected": expected,
        "set_input_result": attempt.get("returned", result.get("returned")),
        "actual_readback": attempt.get("actual", result.get("actual")),
        "matched": attempt.get("matched", result.get("ok")),
        "ok": result.get("ok") is True,
        "raw_result": result,
    }


def _failure_reason(style: Mapping[str, Any]) -> dict[str, Any]:
    primary = style.get("primary") or {}
    writes = style.get("writes") or {}
    failed_inputs = [name for name, row in (primary.get("inputs") or {}).items() if row.get("verified") is not True]
    failed_writes = [name for name, row in writes.items() if row.get("ok") is not True]
    return {
        "style_ok": style.get("ok") is True,
        "primary_applied": primary.get("applied") is True,
        "failed_primary_inputs": failed_inputs,
        "failed_writes": failed_writes,
        "expression": "primary.applied and all(write.ok for write in writes)",
    }


def _capture(call: Any) -> dict[str, Any]:
    try:
        value = call()
        return {
            "ok": True,
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "repr": repr(value),
            "str": str(value),
            "value": f7.IMPLEMENTATION.visual.base.json_safe(value),
            "colors": f7.IMPLEMENTATION._gradient_colors(value),
        }
    except BaseException as exc:
        return {"ok": False, "error": f7.IMPLEMENTATION.visual.base.compact_exception(exc)}


def _relevant_attrs(value: Any) -> dict[str, Any]:
    attrs = value.GetAttrs()
    return {
        str(key): f7.IMPLEMENTATION.visual.base.json_safe(item)
        for key, item in attrs.items()
        if any(token in str(key).lower() for token in ("name", "id", "type", "datatype"))
    } if isinstance(attrs, Mapping) else {"raw": f7.IMPLEMENTATION.visual.base.json_safe(attrs)}


def _settings_gradient(value: Any, path: str = "") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if "shadinggradient1" in str(key).lower():
                found.append({"path": child_path, "value": f7.IMPLEMENTATION.visual.base.json_safe(child), "colors": f7.IMPLEMENTATION._gradient_colors(child)})
            found.extend(_settings_gradient(child, child_path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.extend(_settings_gradient(child, f"{path}[{index}]"))
    return found


def _gradient_proxy_evidence(tool: Any, raw: Any) -> dict[str, Any]:
    evidence = {
        "readback": _capture(lambda: raw),
        "dir": _capture(lambda: sorted(dir(raw))),
        "value_member": _capture(lambda: raw.Value),
        "get_attrs": _capture(lambda: raw.GetAttrs()),
    }
    try:
        handles = tool.GetInputList("Gradient")
        rows = []
        for key, handle in handles.items() if isinstance(handles, Mapping) else []:
            attrs = _capture(lambda handle=handle: _relevant_attrs(handle))
            rows.append({
                "key": str(key),
                "type": f"{type(handle).__module__}.{type(handle).__qualname__}",
                "repr": repr(handle),
                "attrs": attrs,
                "value_member": _capture(lambda handle=handle: handle.Value),
            })
        evidence["gradient_input_list"] = {
            "ok": True,
            "type": f"{type(handles).__module__}.{type(handles).__qualname__}",
            "count": len(handles) if isinstance(handles, Mapping) else None,
            "rows": rows,
        }
    except BaseException as exc:
        evidence["gradient_input_list"] = {"ok": False, "error": f7.IMPLEMENTATION.visual.base.compact_exception(exc)}
    try:
        settings = tool.SaveSettings()
        evidence["save_settings"] = {
            "ok": True,
            "type": f"{type(settings).__module__}.{type(settings).__qualname__}",
            "gradient_matches": _settings_gradient(settings),
        }
    except BaseException as exc:
        evidence["save_settings"] = {"ok": False, "error": f7.IMPLEMENTATION.visual.base.compact_exception(exc)}
    return evidence


def _numeric_gradient_colors(value: Any) -> list[list[float]]:
    if not isinstance(value, Mapping):
        return []
    colors = []
    try:
        stops = sorted(value.items(), key=lambda item: float(item[0]))
    except (TypeError, ValueError):
        return []
    for _position, stop in stops:
        if not isinstance(stop, Mapping):
            return []
        channels = [stop.get(index, stop.get(str(index))) for index in range(1, 5)]
        if any(channel is None for channel in channels):
            return []
        colors.append([float(channel) for channel in channels])
    return colors


def _channel_mapping(value: Any, expected: list[list[float]]) -> dict[str, str]:
    if not isinstance(value, Mapping) or not expected:
        return {}
    try:
        stops = [stop for _position, stop in sorted(value.items(), key=lambda item: float(item[0]))]
    except (TypeError, ValueError):
        return {}
    if not stops or any(not isinstance(stop, Mapping) for stop in stops):
        return {}
    expected_by_name = {name: [row[index] for row in expected] for index, name in enumerate(("R", "G", "B", "A"))}
    mapping = {}
    for slot in range(1, 5):
        observed = [stop.get(slot, stop.get(str(slot))) for stop in stops]
        for name, wanted in expected_by_name.items():
            if len(observed) == len(wanted) and all(f7.IMPLEMENTATION.base.close(got, want) for got, want in zip(observed, wanted)):
                mapping[str(slot)] = name
                break
    return mapping


def _gradient_candidates(expected: list[list[float]]) -> list[tuple[str, Any]]:
    numeric = {
        0.0: {index + 1: value for index, value in enumerate(expected[0])},
        1.0: {index + 1: value for index, value in enumerate(expected[1])},
    }
    return [
        ("numeric_channel_table", numeric),
        ("numeric_channel_table_with_flags", {position: {**stop, "__flags": 256} for position, stop in numeric.items()}),
        ("serialized_gradient_value", {"__ctor": "Gradient", "Colors": {position: {**stop, "__flags": 256} for position, stop in numeric.items()}}),
    ]


def _test_gradient_candidates(tool: Any, expected: list[list[float]]) -> dict[str, Any]:
    results = []
    for name, candidate in _gradient_candidates(expected):
        row: dict[str, Any] = {"name": name, "representation_repr": repr(candidate), "representation": f7.IMPLEMENTATION.visual.base.json_safe(candidate)}
        try:
            returned = tool.SetInput("ShadingGradient1", candidate)
            proxy = tool.GetInput("ShadingGradient1")
            value = proxy.Value
            colors = _numeric_gradient_colors(value)
            matched = len(colors) == len(expected) and all(f7.IMPLEMENTATION.base.close(got, want) for got, want in zip(colors, expected))
            row.update({
                "set_input_result": f7.IMPLEMENTATION.visual.base.json_safe(returned),
                "proxy_type": f"{type(proxy).__module__}.{type(proxy).__qualname__}",
                "value_readback": f7.IMPLEMENTATION.visual.base.json_safe(value),
                "normalized_colors": colors,
                "channel_mapping": _channel_mapping(value, expected),
                "matched": matched,
            })
        except BaseException as exc:
            row.update({"matched": False, "error": f7.IMPLEMENTATION.visual.base.compact_exception(exc)})
        results.append(row)
        if row["matched"] is True:
            break
    winner = next((row["name"] for row in results if row["matched"] is True), None)
    return {"expected_colors": expected, "attempts": results, "working_candidate": winner, "pass": winner is not None}


def _diagnosis_complete(evidence_persisted: Any, cleanup: Mapping[str, Any]) -> bool:
    cleanup_ok = (
        cleanup.get("probe_timeline_deleted") is True
        and cleanup.get("previous_timeline_restored") is True
        and cleanup.get("project_saved") is False
        and cleanup.get("timeline_inventory_unchanged") is True
        and cleanup.get("protected_timeline_unchanged") is True
        and cleanup.get("target_absent") is True
    )
    return evidence_persisted is True and cleanup_ok


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "classification": "BLOCKED",
        "failures": [],
        "mutation_counts": {"timeline_create": 0, "textplus_create": 0, "project_save": 0, "delete": 0},
    }
    project = target = previous = protected = None
    report_dir = Path(str(payload.get("report_dir") or "")).resolve()
    diagnostic_path = report_dir / "why_style_diagnostic.json"
    diagnostic: dict[str, Any] = {
        "schema": "video_cloner_f7_why_style_live_diagnostic_v1",
        "task_id": TASK_ID,
        "run_id": run_id,
        "source_identity": WHY_ID,
        "evidence_persisted_before_cleanup": False,
    }
    timeline_ids_before: set[str] = set()
    protected_before = None
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        contract_path = Path(str(payload["contract_path"])).resolve()
        baseline = Path(str(payload["baseline_fcpxml"])).resolve()
        if f7.IMPLEMENTATION.base.sha(contract_path) != payload.get("contract_sha256") or f7.IMPLEMENTATION.base.sha(baseline) != payload.get("baseline_fcpxml_sha256"):
            raise ValueError("artifact_hash")
        contract = f7.IMPLEMENTATION.base.read(contract_path)
        matches = [row for row in contract.get("objects", []) if row.get("source_identity") == WHY_ID]
        if len(matches) != 1:
            raise ValueError("why_identity")
        row = matches[0]
        if row["text"]["value"] != "why?" or row["advanced_effects"]["shadow"] != "STYLE_UNRESOLVED_F5":
            raise ValueError("why_authority")

        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or carrier._safe(project, "GetName", default="") != contract["project"]:
            raise ValueError("project_identity")
        protected = f7.IMPLEMENTATION.base.find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"])
        if protected is None:
            raise ValueError("protected_timeline_identity")
        protected_before = f7.IMPLEMENTATION.base.protected_snapshot(protected)
        previous = carrier._safe(project, "GetCurrentTimeline")
        timeline_ids_before = {carrier._unique_id(item) for item in carrier._timelines(project)}
        if f7.IMPLEMENTATION.base.find_timeline(project, payload["target_timeline"]) is not None:
            raise ValueError("fresh_probe_already_exists")

        pool = carrier._safe(project, "GetMediaPool")
        returned = carrier._safe(pool, "ImportTimelineFromFile", str(baseline), {"timelineName": payload["target_timeline"]})
        delta = [item for item in carrier._timelines(project) if carrier._unique_id(item) not in timeline_ids_before]
        target = returned if returned not in (None, False, True) else delta[0] if len(delta) == 1 else None
        if target is None or len(delta) != 1:
            raise ValueError("probe_ownership")
        result["mutation_counts"]["timeline_create"] = 1
        carrier._safe(target, "SetName", payload["target_timeline"])
        if carrier._safe(target, "GetName", default="") != payload["target_timeline"]:
            raise ValueError("probe_name")
        while int(carrier._safe(target, "GetTrackCount", "video", default=0) or 0) < 2:
            if not carrier._safe(target, "AddTrack", "video", default=False):
                raise ValueError("probe_track_creation")
        if not carrier._safe(project, "SetCurrentTimeline", target, default=False):
            raise ValueError("probe_activation")
        v1 = list(carrier._safe(target, "GetItemListInTrack", "video", 1, default=[]) or [])
        source = carrier._safe(v1[0], "GetMediaPoolItem") if v1 else None
        title = {"caption_id": WHY_ID, "text": "why?", "timeline_start": row["resolve_interval"][0], "duration": row["resolve_interval"][1] - row["resolve_interval"][0], "lane": 1}
        provision = carrier.apply_carrier_textplus_v2(project, target, [title], source, {"ownership": carrier.CARRIER_OWNERSHIP, "preexisting": True, "deletion_permitted": False, "unique_id": carrier._unique_id(source), "source_start": 0})
        if provision.get("ok") is not True or provision.get("created_count") != 1:
            raise ValueError(f"probe_textplus:{provision.get('failures')}")
        result["mutation_counts"]["textplus_create"] = 1
        link = provision["rows"][0]
        items = {carrier._unique_id(item): item for item in carrier._safe(target, "GetItemListInTrack", "video", 2, default=[]) or []}
        item = items.get(link["item_unique_id"])
        if item is None:
            raise ValueError("probe_item_reacquire")
        carrier._safe(item, "SetName", row["intended_resolve_name"])
        comp, tool = f7.IMPLEMENTATION.base.textplus(item)
        recording_tool = _RecordingTool(tool)
        try:
            style = f7.IMPLEMENTATION._style(row, recording_tool, comp, 1)
            style_exception = None
        except BaseException as exc:
            style = {"primary": None, "writes": {}, "ok": False}
            style_exception = f7.IMPLEMENTATION.visual.base.compact_exception(exc)

        fill = row["fill"]
        expected_gradient = f7.IMPLEMENTATION._expected_gradient(fill)
        gradient_raw = f7.IMPLEMENTATION.visual.base.read_input(tool, "ShadingGradient1", 0)
        expected_colors = [[channel / 255.0 for channel in stop["rgb"]] + [1.0] for stop in fill["stops"]]
        actual_colors = f7._gradient_rgba(gradient_raw)
        gradient_write = _write_for(style, "gradient", f7.IMPLEMENTATION.visual.base.json_safe(expected_gradient))
        sent = next((write for write in reversed(recording_tool.writes) if write["input"] == "ShadingGradient1"), None)
        gradient_write.update({
            "serialized_value_sent": (sent or {}).get("value_json"),
            "value_sent": (sent or {}).get("value"),
            "set_input_result": (sent or {}).get("returned"),
            "exception": (sent or {}).get("exception") or (style.get("writes") or {}).get("gradient", {}).get("error"),
            "raw_readback": f7.IMPLEMENTATION.visual.base.json_safe(gradient_raw),
            "normalized_extracted_colors": actual_colors,
            "expected_colors": expected_colors,
            "matched": len(actual_colors) >= len(expected_colors) and all(f7.IMPLEMENTATION.base.close(got, want) for got, want in zip(actual_colors[:len(expected_colors)], expected_colors)),
        })
        gradient_write["ok"] = gradient_write["matched"] is True
        diagnostic.update({
            "authority": {
                "font": [row["font"]["resolve_family"], row["font"]["resolve_style"]],
                "size": row["size"]["resolve_value"],
                "center": row["position"]["resolve_center"],
                "opacity": row["opacity"]["resolve_value"],
                "gradient_stops": fill["stops"],
                "shadow": row["advanced_effects"]["shadow"],
            },
            "primary": style.get("primary"),
            "opacity_write": _write_for(style, "opacity", 0.75),
            "gradient_mode_write": _write_for(style, "gradient_type", 2.0),
            "gradient_write": gradient_write,
            "gradient_proxy_evidence": _gradient_proxy_evidence(tool, gradient_raw),
            "all_set_input_calls": recording_tool.writes,
            "style_exception": style_exception,
            "final_false_reason": _failure_reason(style),
            "production_style_result": style,
            "evidence_persisted_before_cleanup": True,
            "cleanup": {"pending": True},
        })
        f7.IMPLEMENTATION.base.write(diagnostic_path, diagnostic)
    except BaseException as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
        diagnostic["probe_exception"] = f7.IMPLEMENTATION.visual.base.compact_exception(exc)
    finally:
        restored = False
        deleted = False
        if project is not None and previous is not None:
            restored = bool(carrier._safe(project, "SetCurrentTimeline", previous, default=False)) and carrier._same_timeline(carrier._safe(project, "GetCurrentTimeline"), previous)
        if project is not None and target is not None:
            deleted = bool(carrier._safe(carrier._safe(project, "GetMediaPool"), "DeleteTimelines", [target], default=False))
            result["mutation_counts"]["delete"] = int(deleted)
        timeline_ids_after = {carrier._unique_id(item) for item in carrier._timelines(project)} if project is not None else set()
        target_absent = target is None or carrier._unique_id(target) not in timeline_ids_after
        protected_after = f7.IMPLEMENTATION.base.protected_snapshot(protected) if protected is not None else None
        cleanup = {
            "probe_timeline_deleted": deleted and target_absent,
            "previous_timeline_restored": restored,
            "project_saved": False,
            "timeline_inventory_unchanged": bool(timeline_ids_before) and timeline_ids_before == timeline_ids_after,
            "protected_timeline_unchanged": protected_before is not None and protected_before == protected_after,
            "target_absent": target_absent,
        }
        diagnostic["cleanup"] = cleanup
        diagnostic["diagnosis_complete"] = _diagnosis_complete(
            diagnostic.get("evidence_persisted_before_cleanup"), cleanup
        )
        try:
            f7.IMPLEMENTATION.base.write(diagnostic_path, diagnostic)
        except BaseException as exc:
            result["failures"].append(f"diagnostic_write:{type(exc).__name__}: {exc}")
        result.update({
            "ok": diagnostic.get("diagnosis_complete") is True and not result["failures"],
            "classification": "DIAGNOSIS_COMPLETE" if diagnostic.get("diagnosis_complete") is True and not result["failures"] else "BLOCKED",
            "diagnostic_report_path": str(diagnostic_path),
            "why_style_results": {
                "primary_applied": bool((diagnostic.get("primary") or {}).get("applied")),
                "opacity_ok": bool((diagnostic.get("opacity_write") or {}).get("ok")),
                "gradient_type_ok": bool((diagnostic.get("gradient_mode_write") or {}).get("ok")),
                "gradient_write_readback_ok": bool((diagnostic.get("gradient_write") or {}).get("ok")),
            },
            "final_state": cleanup,
        })
    return result
