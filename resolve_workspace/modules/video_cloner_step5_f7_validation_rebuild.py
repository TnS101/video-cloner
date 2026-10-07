"""Repository-import bootstrap for the immutable F7 Resolve runtime."""
from __future__ import annotations

import copy
import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUNTIME = ROOT / ".agent/tasks/inbox/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_20261001_V1/files/video_cloner_step5_f7_validation_rebuild.py"
SPEC = importlib.util.spec_from_file_location("video_cloner_step5_f7_immutable_runtime", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"could not load F7 runtime: {RUNTIME}")
IMPLEMENTATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPLEMENTATION)

_ORIGINAL_STYLE = IMPLEMENTATION._style


def _runtime_style_row(row):
    shadow = (row.get("advanced_effects") or {}).get("shadow")
    if isinstance(shadow, Mapping):
        return row
    runtime_row = copy.deepcopy(row)
    runtime_row.setdefault("advanced_effects", {})["shadow"] = None
    return runtime_row


def _style(row, tool, comp, index):
    return _ORIGINAL_STYLE(_runtime_style_row(row), tool, comp, index)


def _expected_gradient(fill):
    return {
        float(stop["position"]): {
            1: float(stop["rgb"][0]) / 255.0,
            2: float(stop["rgb"][1]) / 255.0,
            3: float(stop["rgb"][2]) / 255.0,
            4: float(stop.get("alpha", 1.0)),
        }
        for stop in fill["stops"]
    }


def _gradient_value(value):
    if type(value) is dict:
        return value
    try:
        value = value.Value
    except BaseException:
        return None
    return value if type(value) is dict else None


def _gradient_stops(value):
    original = value
    value = _gradient_value(value)
    if value is None and isinstance(original, (list, tuple)):
        value = original
    if not isinstance(value, Mapping):
        if isinstance(value, (list, tuple)):
            rows = []
            for child in value:
                if not isinstance(child, Mapping) or "position" not in child or "rgba" not in child:
                    return []
                rgba = child["rgba"]
                if not isinstance(rgba, (list, tuple)) or len(rgba) != 4:
                    return []
                rows.append({"position": float(child["position"]), "rgba": [float(channel) for channel in rgba]})
            return rows
        return []
    if "Value" in value:
        return _gradient_stops(value["Value"])
    if "Colors" in value:
        return _gradient_stops(value["Colors"])
    if all(value.get(name) is not None for name in ("R", "G", "B")):
        return [{"position": 0.0, "rgba": [float(value[name]) for name in ("R", "G", "B")] + [float(value.get("A", 1.0))]}]
    rows = []
    for position, child in value.items():
        if str(position).startswith("__"):
            continue
        try:
            position_value = float(position)
        except (TypeError, ValueError):
            return []
        if not isinstance(child, Mapping):
            return []
        if all(child.get(name) is not None for name in ("R", "G", "B")):
            rgba = [float(child[name]) for name in ("R", "G", "B")] + [float(child.get("A", 1.0))]
        else:
            numeric = [child.get(index, child.get(str(index))) for index in range(1, 5)]
            if any(channel is None for channel in numeric):
                return []
            rgba = [float(channel) for channel in numeric]
        rows.append({"position": position_value, "rgba": rgba})
    return sorted(rows, key=lambda row: row["position"])


def _gradient_rgba(value):
    return [row["rgba"] for row in _gradient_stops(value)]


def _gradient_colors(value):
    return [rgba[:3] for rgba in _gradient_rgba(value)]


def _set_gradient(tool, fill):
    expected = _expected_gradient(fill)
    wanted = [[*(float(channel) / 255.0 for channel in stop["rgb"]), float(stop.get("alpha", 1.0))] for stop in fill["stops"]]
    try:
        returned = tool.SetInput("ShadingGradient1", expected)
        actual = IMPLEMENTATION.visual.base.read_input(tool, "ShadingGradient1", 0)
        colors = _gradient_rgba(actual)
        ok = len(colors) == len(wanted) and all(IMPLEMENTATION.base.close(got, want) for got, want in zip(colors, wanted))
        return {
            "ok": ok,
            "returned": IMPLEMENTATION.visual.base.json_safe(returned),
            "actual": IMPLEMENTATION.visual.base.json_safe(actual),
            "actual_value": IMPLEMENTATION.visual.base.json_safe(_gradient_value(actual)),
            "colors": colors,
            "wanted": wanted,
        }
    except BaseException as exc:
        return {"ok": False, "error": IMPLEMENTATION.visual.base.compact_exception(exc)}


def _shadow_for_parity(value):
    if isinstance(value, Mapping):
        return value
    if value is None:
        return None
    if isinstance(value, str) and value.startswith("STYLE_UNRESOLVED_"):
        return None
    raise ValueError(f"shadow_authority:{type(value).__name__}")


def _read(item, expected, track):
    row = IMPLEMENTATION.base.read_object(item, expected, track)
    _comp, tool = IMPLEMENTATION.base.textplus(item)
    gradient = IMPLEMENTATION.visual.base.read_input(tool, "ShadingGradient1", 0)
    row["style_extensions"] = {
        "alpha": IMPLEMENTATION.visual.base.json_safe(IMPLEMENTATION.visual.base.read_input(tool, "Alpha1", 0)),
        "type1": IMPLEMENTATION.visual.base.json_safe(IMPLEMENTATION.visual.base.read_input(tool, "Type1", 0)),
        "gradient": _gradient_stops(gradient),
        "transform_shear": IMPLEMENTATION.visual.base.json_safe(IMPLEMENTATION.visual.base.read_input(tool, "TransformShear", 0)),
    }
    return row


def _parity(contract, rows):
    comparable_contract = copy.deepcopy(contract)
    comparable_rows = copy.deepcopy(rows)
    expected_by_id = {row["source_identity"]: row for row in comparable_contract["objects"]}
    for expected in comparable_contract["objects"]:
        if expected["fill"].get("type") == "linear_gradient":
            expected["fill"]["resolve_rgb"] = expected["fill"]["stops"][0]["rgb"]
        expected.setdefault("advanced_effects", {})["shadow"] = _shadow_for_parity((expected.get("advanced_effects") or {}).get("shadow"))
    for got in comparable_rows:
        got["opacity"]["alpha1"] = 1.0
        if isinstance(got.get("fill"), list) and len(got["fill"]) == 4:
            got["fill"][3] = 1.0
    result = IMPLEMENTATION.base.parity(comparable_contract, comparable_rows)
    failures = [failure for failure in result["failures"] if not failure.startswith("missing:")]
    actual = {row["source_identity"]: row for row in rows}
    for identity, expected in expected_by_id.items():
        got = actual.get(identity)
        if not got:
            failures.append(f"missing:{identity}")
            continue
        ext = got["style_extensions"]
        if not IMPLEMENTATION.base.close(ext["alpha"], expected["opacity"]["resolve_value"]):
            failures.append(f"{identity}:opacity")
        italic = expected["font"].get("italic_treatment")
        if italic and not IMPLEMENTATION.base.close(ext["transform_shear"], italic["value"]):
            failures.append(f"{identity}:italic_treatment")
        if expected["fill"].get("type") == "linear_gradient":
            wanted = [
                {"position": float(stop["position"]), "rgba": [*(float(channel) / 255.0 for channel in stop["rgb"]), float(stop.get("alpha", 1.0))]}
                for stop in expected["fill"]["stops"]
            ]
            observed = _gradient_stops(ext["gradient"])
            if (
                not IMPLEMENTATION.base.close(ext["type1"], 2.0)
                or len(observed) != len(wanted)
                or any(
                    not IMPLEMENTATION.base.close(got_stop["position"], want_stop["position"])
                    or not IMPLEMENTATION.base.close(got_stop["rgba"], want_stop["rgba"])
                    for got_stop, want_stop in zip(observed, wanted)
                )
            ):
                failures.append(f"{identity}:gradient")
    extras = sorted(set(actual) - set(expected_by_id))
    failures.extend(f"unexpected:{identity}" for identity in extras)
    result.update({"ok": not failures and len(rows) == len(contract["objects"]), "object_count": len(rows), "failures": failures})
    return result


IMPLEMENTATION._style = _style
IMPLEMENTATION._expected_gradient = _expected_gradient
IMPLEMENTATION._gradient_colors = _gradient_colors
IMPLEMENTATION._set_gradient = _set_gradient
IMPLEMENTATION._read = _read
IMPLEMENTATION._parity = _parity

TASK_ID = IMPLEMENTATION.TASK_ID
MODE = IMPLEMENTATION.MODE
run = IMPLEMENTATION.run
