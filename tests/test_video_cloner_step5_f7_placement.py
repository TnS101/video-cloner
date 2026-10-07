from __future__ import annotations

import copy
import importlib.util
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "scripts/davinci/prepare_video_cloner_step5_f7_validation_rebuild.py"
F6 = ROOT / ".agent/reports/VIDEO_CLONER_STEP5_F6_6000_LIFECYCLE_20261001_V1/20261001T083958505Z_1d261c7ba2c6/first/step5_f6_compile_contract.json"
AUTHORITY = ROOT / "config/DcJRJtUKScu.accepted_f7_physical_track_placement.json"
RUNTIME = ROOT / "resolve_workspace/modules/video_cloner_step5_f7_validation_rebuild.py"


def load():
    spec = importlib.util.spec_from_file_location("f7_placement_prepare", PREPARE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_bounded_f7_placement_is_complete_and_deterministic() -> None:
    module = load()
    source = json.loads(F6.read_text(encoding="utf-8-sig"))
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8-sig"))
    corrected, validation = module.apply_placement_authority(source, authority)
    rerun, rerun_validation = module.apply_placement_authority(source, authority)

    assert module.fingerprint(corrected) == module.fingerprint(rerun)
    assert validation["derived_objects_sha256"] == rerun_validation["derived_objects_sha256"]
    assert validation["pass"] is True
    assert validation["object_count"] == 65
    assert validation["tracks_scanned"] == [2, 3, 4, 5, 6, 7, 8]
    assert validation["missing_lane_count"] == 0
    assert validation["lane_track_mismatch_count"] == 0
    assert validation["same_track_overlap_count"] == 0
    assert validation["carrier_plan"]["result"] == "PASS"
    assert validation["carrier_plan"]["title_count"] == 65
    assert validation["unchanged_physical_placement_count"] == 62
    assert validation["physical_placement_changes"] == {
        "recovered_display_object_local_we_0002": {"before": [3, 2], "after": [4, 3]},
        "caption_tracklet_0092": {"before": [2, 1], "after": [3, 2]},
        "caption_tracklet_0093": {"before": [2, 1], "after": [3, 2]},
    }
    assert all(value["before"] == value["after"] for value in validation["invariant_hashes"].values())

    by_id = {row["source_identity"]: row for row in corrected["objects"]}
    assert by_id["caption_tracklet_0089"]["resolve_interval"] == [542, 596]
    assert len(by_id["caption_tracklet_0089"]["keyframes"]["scale"]) == 9
    assert all(row["z_order_track"]["lane"] == row["z_order_track"]["resolve_track"] - 1 for row in corrected["objects"])

    normalized_source = copy.deepcopy(source)
    for row in normalized_source["objects"]:
        row["z_order_track"]["lane"] = row["z_order_track"]["resolve_track"] - 1
    expected_by_id = {row["source_identity"]: row for row in normalized_source["objects"]}
    for identity, row in by_id.items():
        if identity not in validation["physical_placement_changes"]:
            assert row == expected_by_id[identity]


def test_f7_style_path_handles_all_shadow_schemas_without_mutating_authority(monkeypatch) -> None:
    runtime_spec = importlib.util.spec_from_file_location("f7_runtime_shadow_test", RUNTIME)
    runtime = importlib.util.module_from_spec(runtime_spec)
    assert runtime_spec.loader
    runtime_spec.loader.exec_module(runtime)
    source = json.loads(F6.read_text(encoding="utf-8-sig"))
    rows = source["objects"]
    before = runtime.IMPLEMENTATION.carrier._fingerprint(rows)
    schemas = Counter()
    applied = {}

    for row in rows:
        effects = row.get("advanced_effects") or {}
        shadow = effects.get("shadow")
        kind = "mapping" if isinstance(shadow, Mapping) else "string" if isinstance(shadow, str) else "null_missing" if shadow is None else "other"
        schemas[kind] += 1
        runtime_row = runtime._runtime_style_row(row)
        if kind == "mapping":
            assert runtime_row is row
            assert runtime_row["advanced_effects"]["shadow"] == shadow
        else:
            assert runtime_row["advanced_effects"]["shadow"] is None

    def capture(_tool, cue, style, index, **_kwargs):
        applied[index] = {"text": cue["text"], "style": copy.deepcopy(style)}
        return {"applied": True}

    monkeypatch.setattr(runtime.IMPLEMENTATION, "set_caption_textplus_style_inputs", capture)
    monkeypatch.setattr(runtime.IMPLEMENTATION.visual, "set_static", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(runtime.IMPLEMENTATION, "_set_gradient", lambda *_args, **_kwargs: {"ok": True})
    for index, row in enumerate(rows, 1):
        assert runtime.IMPLEMENTATION._style(row, object(), object(), index)["ok"] is True

    assert schemas == Counter({"null_missing": 61, "string": 3, "mapping": 1})
    assert len(applied) == 65
    mapping_index = next(index for index, row in enumerate(rows, 1) if isinstance(row["advanced_effects"]["shadow"], Mapping))
    assert applied[mapping_index]["style"]["shadow_enabled"] is True
    assert applied[mapping_index]["style"]["shadow_opacity"] == 0.174431
    for index, row in enumerate(rows, 1):
        if not isinstance(row["advanced_effects"]["shadow"], Mapping):
            assert applied[index]["style"]["shadow_enabled"] is False
            assert applied[index]["style"]["shadow_opacity"] == 0.0
    assert [applied[index]["text"] for index in range(1, 66)] == [row["text"]["value"] for row in rows]
    assert runtime.IMPLEMENTATION.carrier._fingerprint(rows) == before


def test_f7_gradient_serializer_and_proxy_normalizer() -> None:
    runtime_spec = importlib.util.spec_from_file_location("f7_runtime_gradient_test", RUNTIME)
    runtime = importlib.util.module_from_spec(runtime_spec)
    assert runtime_spec.loader
    runtime_spec.loader.exec_module(runtime)
    fill = {"stops": [
        {"position": 0.0, "rgb": [190, 68, 78]},
        {"position": 1.0, "rgb": [169, 50, 115]},
    ]}
    expected = {
        0.0: {1: 190 / 255, 2: 68 / 255, 3: 78 / 255, 4: 1.0},
        1.0: {1: 169 / 255, 2: 50 / 255, 3: 115 / 255, 4: 1.0},
    }

    class Proxy:
        Value = expected

        @property
        def __class__(self):
            raise AssertionError("raw proxy class metadata must not be inspected")

    assert runtime._expected_gradient(fill) == expected
    assert runtime._gradient_value(expected) is expected
    assert runtime._gradient_rgba(Proxy()) == [list(stop.values()) for stop in expected.values()]
    assert runtime._gradient_stops(Proxy()) == [
        {"position": 0.0, "rgba": list(expected[0.0].values())},
        {"position": 1.0, "rgba": list(expected[1.0].values())},
    ]
    assert runtime._gradient_rgba({0.0: {"R": 190 / 255, "G": 68 / 255, "B": 78 / 255, "A": 1.0}}) == [[190 / 255, 68 / 255, 78 / 255, 1.0]]
    assert runtime._gradient_stops({"Value": {"Colors": expected}})[1]["position"] == 1.0
    assert runtime._gradient_stops("<BlackmagicFusion.PyRemoteObject object>") == []
    assert runtime._gradient_value(type("MalformedProxy", (), {"Value": []})()) is None
    assert runtime._gradient_rgba({0.0: {1: 1.0, 2: 0.0, 3: 0.0}}) == []


def _ideal_readback(row: dict) -> dict:
    fill = row["fill"]
    rgb = fill.get("resolve_rgb") or fill["stops"][0]["rgb"]
    shadow = row["advanced_effects"].get("shadow")
    if isinstance(shadow, Mapping):
        shadow_readback = {
            "enabled": 1.0,
            "rgba": [value / 255.0 for value in shadow["color"]["effective_composite_rgb"]] + [shadow["strength"]["effective_darkening"]],
            "offset": [shadow["offset"]["x_normalized"], shadow["offset"]["y_normalized"]],
            "softness_x": shadow["softness"]["normalized_value"],
            "softness_y": shadow["softness"]["normalized_value"],
        }
    else:
        shadow_readback = {"enabled": 0.0, "rgba": [None] * 4, "offset": None, "softness_x": None, "softness_y": None}
    gradient = [
        {"position": float(stop["position"]), "rgba": [*(value / 255.0 for value in stop["rgb"]), float(stop.get("alpha", 1.0))]}
        for stop in fill.get("stops", [])
    ]
    return {
        "source_identity": row["source_identity"],
        "text": row["text"]["value"],
        "start": row["resolve_interval"][0],
        "end": row["resolve_interval"][1],
        "font": row["font"]["resolve_family"],
        "font_style": row["font"]["resolve_style"],
        "size": row["size"]["resolve_value"],
        "center": row["position"]["resolve_center"],
        "fill": [*(value / 255.0 for value in rgb), row["opacity"]["resolve_value"]],
        "stroke": {"enabled": float(bool(row["stroke"]["resolve_enabled"])), "width": row["stroke"]["resolve_width"], "rgba": [0.0, 0.0, 0.0, 0.0]},
        "opacity": {"alpha1": row["opacity"]["resolve_value"], "opacity1": 1.0},
        "shadow": shadow_readback,
        "static_rotation": row["static_rotation"]["resolve_degrees"] or 0.0,
        "track": row["z_order_track"]["resolve_track"],
        "keyframes": {
            channel: [{"expected": key["value"], "actual": key["value"]} for key in row["keyframes"][channel]]
            for channel in ("position", "scale", "rotation", "relative_visibility")
        },
        "style_extensions": {
            "alpha": row["opacity"]["resolve_value"],
            "type1": 2.0 if fill.get("type") == "linear_gradient" else 0.0,
            "gradient": gradient,
            "transform_shear": (row["font"].get("italic_treatment") or {}).get("value", 0.0),
        },
    }


def test_corrected_f7_parity_projection_passes_all_65_without_mutating_authority() -> None:
    runtime_spec = importlib.util.spec_from_file_location("f7_runtime_parity_test", RUNTIME)
    runtime = importlib.util.module_from_spec(runtime_spec)
    assert runtime_spec.loader
    runtime_spec.loader.exec_module(runtime)
    contract = json.loads(F6.read_text(encoding="utf-8-sig"))
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8-sig"))
    contract, _validation = load().apply_placement_authority(contract, authority)
    before = runtime.IMPLEMENTATION.carrier._fingerprint(contract)
    rows = [_ideal_readback(row) for row in contract["objects"]]

    result = runtime.IMPLEMENTATION._parity(contract, rows)

    assert result["ok"] is True
    assert result["object_count"] == 65
    assert result["failures"] == []
    assert runtime.IMPLEMENTATION.carrier._fingerprint(contract) == before
    why = next(row for row in rows if row["source_identity"] == "recovered_display_object_why_0001")
    assert why["fill"][3] == 0.75
    assert why["style_extensions"]["alpha"] == 0.75
    normal = next(row for row in rows if row["style_extensions"]["alpha"] == 1.0)
    assert normal["fill"][3] == 1.0

    missing = runtime.IMPLEMENTATION._parity(contract, rows[:-1])
    assert missing["ok"] is False
    assert any(value.startswith("missing:") for value in missing["failures"])
    extra = copy.deepcopy(rows[0]); extra["source_identity"] = "unexpected_object"
    unexpected = runtime.IMPLEMENTATION._parity(contract, [*rows, extra])
    assert unexpected["ok"] is False
    assert "unexpected:unexpected_object" in unexpected["failures"]


def test_shadow_projection_is_schema_aware_and_mapping_checks_remain_detailed() -> None:
    runtime_spec = importlib.util.spec_from_file_location("f7_runtime_shadow_projection_test", RUNTIME)
    runtime = importlib.util.module_from_spec(runtime_spec)
    assert runtime_spec.loader
    runtime_spec.loader.exec_module(runtime)
    sentinel = "STYLE_UNRESOLVED_F5"
    mapping = {"enabled": True}
    assert runtime._shadow_for_parity(sentinel) is None
    assert sentinel == "STYLE_UNRESOLVED_F5"
    assert runtime._shadow_for_parity(None) is None
    assert runtime._shadow_for_parity(mapping) is mapping
    with pytest.raises(ValueError, match="shadow_authority:list"):
        runtime._shadow_for_parity([])

    contract = json.loads(F6.read_text(encoding="utf-8-sig"))
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8-sig"))
    contract, _validation = load().apply_placement_authority(contract, authority)
    rows = [_ideal_readback(row) for row in contract["objects"]]
    mapping_identity = next(row["source_identity"] for row in contract["objects"] if isinstance(row["advanced_effects"].get("shadow"), Mapping))
    actual = next(row for row in rows if row["source_identity"] == mapping_identity)
    actual["shadow"]["enabled"] = 0.0
    result = runtime.IMPLEMENTATION._parity(contract, rows)
    assert result["ok"] is False
    assert f"{mapping_identity}:shadow" in result["failures"]
