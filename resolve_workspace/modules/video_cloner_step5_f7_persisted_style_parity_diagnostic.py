"""Read-only persisted style parity diagnostic for the three failed F7 objects."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import video_cloner_step5_f7_validation_rebuild as f7
from resolve_workspace.modules import video_cloner_step5_f7_why_style_diagnostic as why_diag

TASK_ID = "VIDEO_CLONER_STEP5_F7_PERSISTED_STYLE_PARITY_DIAGNOSTIC_V1"
MODE = "inspect_persisted_style_parity"
SOURCE_RUN_ID = "20261002T093228130622Z_8a43be1aa99a4e2fa6ec66203b559cbd"
TARGET_TIMELINE = "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_66203b559cbd"
TARGET_IDS = (
    "recovered_display_object_why_0001",
    "recovered_display_object_local_we_0002",
    "recovered_display_object_listing_0003",
)
SHADOW_INPUTS = (
    "Enabled3", "Red3", "Green3", "Blue3", "Alpha3",
    "Offset3", "SoftnessX3", "SoftnessY3",
)
FILL_INPUTS = ("Enabled1", "Red1", "Green1", "Blue1", "Alpha1", "Type1")


def _safe_detail(call: Any) -> dict[str, Any]:
    try:
        value = call()
        detail = {
            "ok": True,
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "json_safe": f7.IMPLEMENTATION.visual.base.json_safe(value),
        }
        for name, renderer in (("repr", repr), ("str", str)):
            try:
                detail[name] = renderer(value)
            except BaseException as exc:
                detail[name] = f7.IMPLEMENTATION.visual.base.compact_exception(exc)
        return detail
    except BaseException as exc:
        return {"ok": False, "error": f7.IMPLEMENTATION.visual.base.compact_exception(exc)}


def _input(tool: Any, name: str) -> tuple[Any, dict[str, Any]]:
    raw = f7.IMPLEMENTATION.visual.base.read_input(tool, name, 0)
    return raw, {"input": name, **_safe_detail(lambda: raw)}


def _tool_name(tool: Any) -> dict[str, Any]:
    attrs = _safe_detail(lambda: tool.GetAttrs())
    values = attrs.get("json_safe") if attrs.get("ok") else None
    name = None
    if isinstance(values, Mapping):
        name = values.get("TOOLS_Name") or values.get("TOOLB_NameSet")
    return {"name": name, "attrs": attrs}


def _expected_gradient(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "position": float(stop["position"]),
            "rgba": [*(float(value) / 255.0 for value in stop["rgb"]), float(stop.get("alpha", 1.0))],
        }
        for stop in row["fill"].get("stops", [])
    ]


def _gradient_stops(raw: Any) -> list[dict[str, Any]]:
    value = f7._gradient_value(raw)
    if not isinstance(value, Mapping):
        return []
    rows = []
    try:
        entries = sorted(value.items(), key=lambda item: float(item[0]))
    except (TypeError, ValueError):
        return []
    for position, channels in entries:
        if not isinstance(channels, Mapping):
            return []
        numeric = [channels.get(index, channels.get(str(index))) for index in range(1, 5)]
        if any(value is None for value in numeric):
            return []
        rows.append({"position": float(position), "numeric_channels": [float(value) for value in numeric]})
    return rows


def _operational(row: Mapping[str, Any]) -> dict[str, Any]:
    runtime_row = f7._runtime_style_row(row)
    shadow = runtime_row["advanced_effects"].get("shadow")
    fill = row["fill"]
    rgb = fill.get("resolve_rgb") or fill["stops"][0]["rgb"]
    return {
        "font_family": row["font"]["resolve_family"],
        "font_style": row["font"]["resolve_style"],
        "fill_rgba": [*(float(value) / 255.0 for value in rgb), float(row["opacity"]["resolve_value"])],
        "gradient": _expected_gradient(row),
        "shadow": {
            "immutable_authority": row["advanced_effects"].get("shadow"),
            "enabled": isinstance(shadow, Mapping),
            "interpretation": "no applied shadow" if not isinstance(shadow, Mapping) else "mapping-based applied shadow",
        },
    }


def _base_projection(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> dict[str, Any]:
    comparable_expected = copy.deepcopy(expected)
    comparable_actual = copy.deepcopy(actual)
    if comparable_expected["fill"].get("type") == "linear_gradient":
        comparable_expected["fill"]["resolve_rgb"] = comparable_expected["fill"]["stops"][0]["rgb"]
    comparable_actual["opacity"]["alpha1"] = 1.0
    try:
        result = f7.IMPLEMENTATION.base.parity({"objects": [comparable_expected]}, [comparable_actual])
        checks = result["rows"][0]["checks"]
        return {
            "fill": {
                "EXPECTED_RAW": comparable_expected["fill"],
                "EXPECTED_NORMALIZED": [value / 255.0 for value in comparable_expected["fill"]["resolve_rgb"]] + [1.0],
                "ACTUAL_RAW": actual["fill"],
                "ACTUAL_NORMALIZED": actual["fill"],
                "RESULT": checks["fill"],
                "FAILURE_REASON": None if checks["fill"] else "base parity compares persisted Red1/Green1/Blue1/Alpha1 to expected RGB plus alpha 1.0",
            },
            "shadow": {
                "EXPECTED_RAW": expected["advanced_effects"].get("shadow"),
                "EXPECTED_NORMALIZED": {"enabled": expected["advanced_effects"].get("shadow") is not None},
                "OPERATIONAL_EXPECTATION": _operational(expected)["shadow"],
                "ACTUAL_RAW": actual["shadow"],
                "ACTUAL_NORMALIZED": {"enabled": bool(actual["shadow"]["enabled"])},
                "RESULT": checks["shadow"],
                "FAILURE_REASON": None if checks["shadow"] else "base parity treats every non-null shadow authority, including a string sentinel, as enabled",
            },
        }
    except BaseException as exc:
        return {"error": f7.IMPLEMENTATION.visual.base.compact_exception(exc)}


def _gradient_projection(expected: Mapping[str, Any], raw: Any) -> dict[str, Any]:
    wanted = [row["rgba"] for row in _expected_gradient(expected)]
    persisted = f7._gradient_rgba(raw)
    json_safe = f7.IMPLEMENTATION.visual.base.json_safe(raw)
    current = f7._gradient_colors(json_safe)
    persisted_match = len(persisted) == len(wanted) and all(
        f7.IMPLEMENTATION.base.close(got, want) for got, want in zip(persisted, wanted)
    )
    current_match = len(current) >= len(wanted) and all(
        f7.IMPLEMENTATION.base.close(got, want[:3]) for got, want in zip(current[:len(wanted)], wanted)
    )
    return {
        "EXPECTED_RAW": expected["fill"].get("stops", []),
        "EXPECTED_NORMALIZED": wanted,
        "ACTUAL_RAW": _safe_detail(lambda: raw),
        "ACTUAL_NORMALIZED": persisted,
        "CURRENT_COMPARATOR_INPUT": json_safe,
        "CURRENT_COMPARATOR_NORMALIZED": current,
        "PERSISTED_VALUE_MATCH": persisted_match,
        "RESULT": current_match,
        "FAILURE_REASON": None if current_match else "current explicit gradient comparator operates on JSON-safe readback rather than guaranteed raw proxy value",
    }


def _classify(projections: Mapping[str, Any]) -> dict[str, str]:
    classes: dict[str, str] = {}
    fill = projections["base"].get("fill", {})
    shadow = projections["base"].get("shadow", {})
    operational_shadow = shadow.get("OPERATIONAL_EXPECTATION", {})
    actual_shadow = shadow.get("ACTUAL_NORMALIZED", {})
    if fill.get("RESULT") is False:
        expected = fill.get("EXPECTED_NORMALIZED") or []
        actual = fill.get("ACTUAL_NORMALIZED") or []
        same_rgb = len(expected) >= 3 and len(actual) >= 3 and f7.IMPLEMENTATION.base.close(actual[:3], expected[:3])
        classes["fill"] = "COMPARATOR_EXPECTATION_DEFECT" if same_rgb else "ACTUAL_STYLE_APPLICATION_DEFECT"
    if shadow.get("RESULT") is False:
        if operational_shadow.get("enabled") is False and actual_shadow.get("enabled") is False:
            classes["shadow"] = "SEMANTICALLY_EQUAL_STRUCTURALLY_DIFFERENT"
        else:
            classes["shadow"] = "ACTUAL_STYLE_APPLICATION_DEFECT"
    gradient = projections.get("gradient")
    if gradient and gradient.get("RESULT") is False:
        classes["gradient"] = "NORMALIZATION_DEFECT" if gradient.get("PERSISTED_VALUE_MATCH") else "PERSISTED_WRITE_DEFECT"
    return classes


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
    report_dir = Path(str(payload.get("report_dir") or "")).resolve()
    diagnostic_path = report_dir / "step5_f7_persisted_style_parity_diagnostic.json"
    diagnostic: dict[str, Any] = {
        "schema": "video_cloner_step5_f7_persisted_style_parity_diagnostic_v1",
        "task_id": TASK_ID,
        "run_id": run_id,
        "source_failed_run_id": SOURCE_RUN_ID,
        "target_timeline": TARGET_TIMELINE,
        "target_identities": list(TARGET_IDS),
        "read_only": True,
        "evidence_persisted_before_classification": False,
        "objects": [],
    }
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        if payload.get("source_run_id") != SOURCE_RUN_ID or payload.get("target_timeline") != TARGET_TIMELINE:
            raise ValueError("diagnostic_scope")
        contract_path = Path(str(payload["contract_path"])).resolve()
        if f7.IMPLEMENTATION.base.sha(contract_path) != payload.get("contract_sha256"):
            raise ValueError("contract_hash")
        contract = f7.IMPLEMENTATION.base.read(contract_path)
        expected_rows = [row for row in contract.get("objects", []) if row.get("source_identity") in TARGET_IDS]
        if tuple(row["source_identity"] for row in expected_rows) != TARGET_IDS:
            raise ValueError("target_identities")
        expected = {row["source_identity"]: row for row in expected_rows}

        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or carrier._safe(project, "GetName", default="") != contract["project"]:
            raise ValueError("project_identity")
        protected = f7.IMPLEMENTATION.base.find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"])
        target = f7.IMPLEMENTATION.base.find_timeline(project, TARGET_TIMELINE)
        if protected is None or target is None:
            raise ValueError("timeline_identity")
        protected_before = f7.IMPLEMENTATION.base.protected_snapshot(protected)

        wanted_keys = {
            (row["z_order_track"]["resolve_track"], *row["resolve_interval"]): row["source_identity"]
            for row in expected_rows
        }
        matched: dict[str, tuple[Any, int]] = {}
        for track in sorted({key[0] for key in wanted_keys}):
            for item in carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or []:
                key = (track, int(carrier._safe(item, "GetStart")), int(carrier._safe(item, "GetEnd")))
                identity = wanted_keys.get(key)
                if identity:
                    if identity in matched:
                        raise ValueError(f"ambiguous_item:{identity}")
                    matched[identity] = (item, track)
        if set(matched) != set(TARGET_IDS):
            raise ValueError(f"missing_items:{sorted(set(TARGET_IDS) - set(matched))}")

        live_rows = []
        for identity in TARGET_IDS:
            row = expected[identity]
            item, track = matched[identity]
            item_name = str(carrier._safe(item, "GetName", default="") or "")
            if item_name != row["intended_resolve_name"]:
                raise ValueError(f"item_name:{identity}")
            comp, tool = f7.IMPLEMENTATION.base.textplus(item)
            actual = f7.IMPLEMENTATION.base.read_object(item, row, track)
            if actual["text"] != row["text"]["value"]:
                raise ValueError(f"visible_text:{identity}")
            fill_raw = {}
            fill_evidence = {}
            for name in FILL_INPUTS:
                fill_raw[name], fill_evidence[name] = _input(tool, name)
            shadow_evidence = {}
            for name in SHADOW_INPUTS:
                _raw, shadow_evidence[name] = _input(tool, name)
            gradient_raw = fill_raw.get("ShadingGradient1")
            gradient_evidence = None
            if row["fill"].get("type") == "linear_gradient":
                gradient_raw, gradient_input = _input(tool, "ShadingGradient1")
                gradient_evidence = {
                    "input": gradient_input,
                    "proxy": why_diag._gradient_proxy_evidence(tool, gradient_raw),
                    "extracted_stops": _gradient_stops(gradient_raw),
                    "normalized_rgba": f7._gradient_rgba(gradient_raw),
                    "expected_stops": _expected_gradient(row),
                }
            immutable = {
                key: copy.deepcopy(row.get(key))
                for key in ("fill", "opacity", "font", "advanced_effects", "stroke")
            }
            evidence = {
                "identity": {
                    "source_identity": identity,
                    "intended_resolve_name": row["intended_resolve_name"],
                    "visible_text": actual["text"],
                    "resolve_track": track,
                    "lane": row["z_order_track"]["lane"],
                    "start": actual["start"],
                    "end": actual["end"],
                    "matched_item_unique_id": actual["item_unique_id"],
                    "matched_item_name": actual["item_name"],
                    "matched_textplus_tool": _tool_name(tool),
                },
                "immutable_expected_authority": immutable,
                "operational_expectation": _operational(row),
                "base_fill_persisted_readback": fill_evidence,
                "gradient_persisted_readback": gradient_evidence,
                "shadow_persisted_readback": shadow_evidence,
                "production_read_object_projection": actual,
            }
            diagnostic["objects"].append(evidence)
            live_rows.append((evidence, row, actual, gradient_raw))

        protected_after = f7.IMPLEMENTATION.base.protected_snapshot(protected)
        diagnostic["protected_timeline_current_state_captured"] = True
        diagnostic["protected_timeline"] = {
            "before": protected_before,
            "after": protected_after,
            "unchanged_during_diagnostic": protected_before == protected_after,
            "previous_full_run_unchanged_claimed": False,
        }
        diagnostic["evidence_persisted_before_classification"] = True
        f7.IMPLEMENTATION.base.write(diagnostic_path, diagnostic)

        for evidence, row, actual, gradient_raw in live_rows:
            projections: dict[str, Any] = {"base": _base_projection(row, actual)}
            if row["fill"].get("type") == "linear_gradient":
                projections["gradient"] = _gradient_projection(row, gradient_raw)
            evidence["current_comparator_projections"] = projections
            evidence["mismatch_classifications"] = _classify(projections)
        diagnostic["classification_complete"] = True
        diagnostic["sufficient_evidence"] = (
            len(diagnostic["objects"]) == len(TARGET_IDS)
            and all("error" not in evidence["current_comparator_projections"]["base"] for evidence in diagnostic["objects"])
            and all(
                row["ok"] is True
                for evidence in diagnostic["objects"]
                for row in (*evidence["base_fill_persisted_readback"].values(), *evidence["shadow_persisted_readback"].values())
            )
            and all(
                evidence["gradient_persisted_readback"] is None
                or evidence["gradient_persisted_readback"]["proxy"]["value_member"].get("ok") is True
                for evidence in diagnostic["objects"]
            )
        )
        f7.IMPLEMENTATION.base.write(diagnostic_path, diagnostic)
        if not diagnostic["sufficient_evidence"] or protected_before != protected_after:
            raise ValueError("persisted_readback_insufficient")
        result.update({
            "ok": True,
            "classification": "DIAGNOSIS_COMPLETE",
            "diagnostic_path": str(diagnostic_path),
            "target_identity_count": len(TARGET_IDS),
            "protected_timeline_current_state_captured": True,
        })
    except BaseException as exc:
        result["failures"] = [f7.IMPLEMENTATION.visual.base.compact_exception(exc)]
        if diagnostic.get("evidence_persisted_before_classification") is not True:
            try:
                f7.IMPLEMENTATION.base.write(diagnostic_path, diagnostic)
            except BaseException:
                pass
    return result

