"""Step 3B.3 V1: monotonic outline/shadow reconciliation on the accepted V4 timeline.

The accepted V4 caption snapshot already preserves the historical source-backed
3B.3/effect-mode result for 113/114 current Text+ instances.  The only visible
source-authority drift is COME (`sub_052`): its latent source-backed outline and
shadow values are still present, but both shading elements are disabled.

This module therefore refuses broad style reapplication.  It verifies the
entire 114-item effect authority against the exact accepted V4 preimage,
duplicates that accepted timeline, enables only COME's outline/shadow elements,
then proves every unrelated caption property and the accepted V4 occlusion
state are unchanged before the single save and after persistent reacquisition.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3B3_OUTLINE_SHADOW_CLONING_V1"
MODE = "STEP_3B3_OUTLINE_SHADOW_CLONING_V1"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3B3_outline_shadow_cloning_v1.py"
SOURCE_TIMELINE_NAME = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_"
    "confirmed74_repair_metrics_v1_occlusion_complete_v4"
)
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_outline_shadow_v1"
EXPECTED_TEXTPLUS_COUNT = 114
TARGET_CAPTION_NAME = "VC_TEXTPLUS_0052_sub_052"
TARGET_CUE_ID = "sub_052"
MERGED_THEY_NAME = "VC_TEXTPLUS_VISUAL_INSTANCE_THEY_sub_051_sub_054"
EFFECT_PLAN_RELATIVE = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_effect_mode_plan_step_3B_3C.json"
EFFECT_PLAN_VALIDATION_RELATIVE = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_effect_mode_plan_step_3B_3C_validation.json"
VISUAL_AUTHORITY_RELATIVE = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
EXPECTED_AUTHORITY_COUNTS = {"legacy": 96, "merged": 1, "visual_first": 17, "total": 114}
EXPECTED_SOURCE_MISMATCHES = (
    (TARGET_CAPTION_NAME, "Enabled2", 1.0, 0.0),
    (TARGET_CAPTION_NAME, "Enabled3", 1.0, 0.0),
)
AUTHORIZED_EFFECT_FIELDS = frozenset({"Enabled2", "Enabled3"})
TARGET_EFFECT_SNAPSHOT_FIELDS = frozenset({
    "Enabled2", "Red2", "Green2", "Blue2", "Alpha2", "Opacity2", "Thickness2",
    "Enabled3", "Red3", "Green3", "Blue3", "Alpha3", "Opacity3", "Thickness3",
})
FLOAT_TOLERANCE = 2e-5


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime(root: Path):
    v4 = _load(
        "vc_final_occlusion_v4_for_step3b3",
        root / "resolve_workspace" / "modules" / "final_occlusion_composition_v4.py",
    )
    return v4, v4.base, v4.V1, v4.full


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _rgb(hex_color: str) -> Tuple[float, float, float]:
    text = str(hex_color or "").strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"invalid_color:{hex_color}")
    return tuple(int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4))  # type: ignore[return-value]


def _close(actual: Any, expected: Any, tolerance: float = FLOAT_TOLERANCE) -> bool:
    try:
        a = float(actual)
        e = float(expected)
    except (TypeError, ValueError):
        return False
    return math.isfinite(a) and math.isfinite(e) and abs(a - e) <= tolerance


def _snapshot_rows(snapshot: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("snapshot_rows")
    return [row for row in rows if isinstance(row, Mapping)]


def _row_name(row: Mapping[str, Any]) -> str:
    return str(row.get("name") or (row.get("summary") or {}).get("name") or "")


def _property(row: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    value = properties.get(field)
    return value if isinstance(value, Mapping) else {}


def _values(row: Mapping[str, Any], field: str) -> List[Any] | None:
    prop = _property(row, field)
    if prop.get("exists") is not True:
        return None
    values = prop.get("values")
    return list(values) if isinstance(values, list) else None


def _series_matches(values: Sequence[Any] | None, expected: float, tolerance: float = FLOAT_TOLERANCE) -> bool:
    return bool(values) and all(_close(value, expected, tolerance) for value in values)


def _series_actual(values: Sequence[Any] | None) -> Any:
    if not values:
        return None
    try:
        numbers = [float(value) for value in values]
    except (TypeError, ValueError):
        return list(values[:4])
    if max(numbers) - min(numbers) <= FLOAT_TOLERANCE:
        return round(numbers[0], 9)
    return {"min": min(numbers), "max": max(numbers), "count": len(numbers)}


def _effect_target(row: Mapping[str, Any]) -> Mapping[str, Any]:
    effect = row.get("effect")
    if not isinstance(effect, Mapping):
        raise ValueError(f"effect_missing:{row.get('name')}")
    target = effect.get("target")
    if not isinstance(target, Mapping):
        raise ValueError(f"effect_target_missing:{row.get('name')}")
    return target


def build_authority(
    snapshot_names: Sequence[str],
    effect_plan: Mapping[str, Any],
    visual_authority: Mapping[str, Any],
) -> Dict[str, Any]:
    """Map the historical source-backed effects onto the current 114-item topology."""
    if effect_plan.get("ok") is not True:
        raise ValueError("effect_plan_not_ok")
    plan_items = effect_plan.get("items")
    if not isinstance(plan_items, list) or len(plan_items) != 116:
        raise ValueError("effect_plan_count")
    plan_by_name = {str(row.get("name")): row for row in plan_items if isinstance(row, Mapping) and row.get("name")}
    plan_by_cue = {str(row.get("cue_id")): row for row in plan_items if isinstance(row, Mapping) and row.get("cue_id")}
    if len(plan_by_name) != 116 or len(plan_by_cue) != 116:
        raise ValueError("effect_plan_uniqueness")

    if visual_authority.get("ok") is not True:
        raise ValueError("visual_authority_not_ok")
    groups = visual_authority.get("groups")
    if not isinstance(groups, list):
        raise ValueError("visual_groups")
    visual_rules: Dict[str, Dict[str, Any]] = {}
    visual_index = 0
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        tokens = group.get("tokens")
        if not isinstance(tokens, list):
            continue
        for token in tokens:
            if not isinstance(token, Mapping):
                continue
            visual_index += 1
            token_id = str(token.get("visual_token_id") or "")
            style = token.get("style_lock")
            if not token_id or not isinstance(style, Mapping) or style.get("source_locked") is not True:
                raise ValueError(f"visual_style_lock:{token_id}")
            name = f"VC_VISUAL_FIRST_FULL_{visual_index:04d}_{token_id}"
            visual_rules[name] = {
                "kind": "visual_first",
                "name": name,
                "token_id": token_id,
                "style_lock": copy.deepcopy(dict(style)),
            }
    if visual_index != 17:
        raise ValueError(f"visual_count:{visual_index}")

    merged_51 = _effect_target(plan_by_cue.get("sub_051") or {})
    merged_54 = _effect_target(plan_by_cue.get("sub_054") or {})
    if canonical_sha256(merged_51) != canonical_sha256(merged_54):
        raise ValueError("merged_they_authority_disagrees")

    rules: Dict[str, Dict[str, Any]] = {}
    counts = {"legacy": 0, "merged": 0, "visual_first": 0, "total": 0}
    unknown: List[str] = []
    for name in snapshot_names:
        if name in plan_by_name:
            row = plan_by_name[name]
            rules[name] = {
                "kind": "legacy",
                "name": name,
                "cue_id": str(row.get("cue_id") or ""),
                "effect": copy.deepcopy(dict(row.get("effect") or {})),
            }
            counts["legacy"] += 1
        elif name == MERGED_THEY_NAME:
            rules[name] = {
                "kind": "merged",
                "name": name,
                "cue_ids": ["sub_051", "sub_054"],
                "effect": {"target": copy.deepcopy(dict(merged_51))},
            }
            counts["merged"] += 1
        elif name in visual_rules:
            rules[name] = visual_rules[name]
            counts["visual_first"] += 1
        else:
            unknown.append(name)
    counts["total"] = len(rules)
    if unknown:
        raise ValueError(f"authority_unknown:{unknown[:5]}")
    if counts != EXPECTED_AUTHORITY_COUNTS:
        raise ValueError(f"authority_counts:{counts}")
    if set(rules) != set(snapshot_names):
        raise ValueError("authority_coverage")
    return {"rules": rules, "counts": counts, "ok": True}


def _append_mismatch(
    output: List[Dict[str, Any]],
    name: str,
    field: str,
    expected: Any,
    values: Sequence[Any] | None,
    authority: str,
) -> None:
    output.append({
        "name": name,
        "field": field,
        "expected": expected,
        "actual": _series_actual(values),
        "authority": authority,
    })


def audit_snapshot(snapshot: Mapping[str, Any], authority: Mapping[str, Any]) -> Dict[str, Any]:
    rows = _snapshot_rows(snapshot)
    by_name = {_row_name(row): row for row in rows}
    rules = authority.get("rules")
    if not isinstance(rules, Mapping):
        raise ValueError("authority_rules")
    if set(by_name) != set(rules):
        raise ValueError("audit_coverage")
    mismatches: List[Dict[str, Any]] = []

    for name in sorted(rules):
        rule = rules[name]
        if not isinstance(rule, Mapping):
            raise ValueError(f"authority_rule:{name}")
        row = by_name[name]
        kind = str(rule.get("kind") or "")
        if kind in {"legacy", "merged"}:
            effect = rule.get("effect")
            target = effect.get("target") if isinstance(effect, Mapping) else None
            if not isinstance(target, Mapping):
                raise ValueError(f"target:{name}")
            outline = target.get("outline")
            shadow = target.get("shadow")
            if not isinstance(outline, Mapping) or not isinstance(shadow, Mapping):
                raise ValueError(f"effect_shape:{name}")
            expected_e2 = 1.0 if outline.get("enabled") is True else 0.0
            expected_e3 = 1.0 if shadow.get("enabled") is True else 0.0
            v2 = _values(row, "Enabled2")
            v3 = _values(row, "Enabled3")
            if not _series_matches(v2, expected_e2):
                _append_mismatch(mismatches, name, "Enabled2", expected_e2, v2, "effect_mode_plan")
            if not _series_matches(v3, expected_e3):
                _append_mismatch(mismatches, name, "Enabled3", expected_e3, v3, "effect_mode_plan")
            if outline.get("enabled") is True:
                for field, expected in zip(("Red2", "Green2", "Blue2"), _rgb(str(outline.get("color") or ""))):
                    values = _values(row, field)
                    if not _series_matches(values, expected):
                        _append_mismatch(mismatches, name, field, expected, values, "effect_mode_plan")
            if shadow.get("enabled") is True:
                for field, expected in zip(("Red3", "Green3", "Blue3"), _rgb(str(shadow.get("color") or ""))):
                    values = _values(row, field)
                    if not _series_matches(values, expected):
                        _append_mismatch(mismatches, name, field, expected, values, "effect_mode_plan")
                expected_opacity = float(shadow.get("opacity") or 0.0)
                values = _values(row, "Opacity3")
                if not _series_matches(values, expected_opacity):
                    _append_mismatch(mismatches, name, "Opacity3", expected_opacity, values, "effect_mode_plan")
        elif kind == "visual_first":
            style = rule.get("style_lock")
            if not isinstance(style, Mapping):
                raise ValueError(f"visual_style:{name}")
            stroke = style.get("stroke")
            shadow = style.get("shadow")
            if not isinstance(stroke, Mapping) or not isinstance(shadow, Mapping):
                raise ValueError(f"visual_effect_shape:{name}")
            expected_e2 = 1.0 if stroke.get("enabled") is True else 0.0
            expected_e3 = 1.0 if shadow.get("enabled") is True else 0.0
            v2 = _values(row, "Enabled2")
            v3 = _values(row, "Enabled3")
            if not _series_matches(v2, expected_e2):
                _append_mismatch(mismatches, name, "Enabled2", expected_e2, v2, "visual_style_lock")
            if not _series_matches(v3, expected_e3):
                _append_mismatch(mismatches, name, "Enabled3", expected_e3, v3, "visual_style_lock")
            if shadow.get("enabled") is True:
                for field, expected in zip(("Red3", "Green3", "Blue3"), _rgb(str(shadow.get("color") or ""))):
                    values = _values(row, field)
                    if not _series_matches(values, expected):
                        _append_mismatch(mismatches, name, field, expected, values, "visual_style_lock")
                opacity1 = _values(row, "Opacity1")
                opacity3 = _values(row, "Opacity3")
                ratio = float(shadow.get("opacity") or 0.0)
                ratio_ok = bool(
                    opacity1 and opacity3 and len(opacity1) == len(opacity3)
                    and all(_close(b, float(a) * ratio) for a, b in zip(opacity1, opacity3))
                )
                if not ratio_ok:
                    mismatches.append({
                        "name": name,
                        "field": "Opacity3/Opacity1",
                        "expected": ratio,
                        "actual": {
                            "opacity1": _series_actual(opacity1),
                            "opacity3": _series_actual(opacity3),
                        },
                        "authority": "visual_style_lock_ratio",
                    })
        else:
            raise ValueError(f"authority_kind:{name}:{kind}")

    return {
        "count": int(snapshot.get("count") or len(rows)),
        "authority_counts": copy.deepcopy(dict(authority.get("counts") or {})),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "ok": len(mismatches) == 0,
    }


def mismatch_signature(audit: Mapping[str, Any]) -> Tuple[Tuple[Any, ...], ...]:
    rows = audit.get("mismatches")
    if not isinstance(rows, list):
        return ()
    signature: List[Tuple[Any, ...]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        expected = row.get("expected")
        actual = row.get("actual")
        if isinstance(expected, float):
            expected = round(expected, 9)
        if isinstance(actual, float):
            actual = round(actual, 9)
        signature.append((str(row.get("name") or ""), str(row.get("field") or ""), expected, actual))
    return tuple(sorted(signature, key=lambda value: (str(value[0]), str(value[1]))))


def expected_source_mismatch_signature() -> Tuple[Tuple[Any, ...], ...]:
    return tuple(sorted(EXPECTED_SOURCE_MISMATCHES, key=lambda value: (value[0], value[1])))


def _normalized_snapshot_for_frozen_compare(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Compare frozen caption state while delegating COME's effect slot to its full source contract.

    Enabling a dormant Text+ shading element changes Resolve's runtime representation of
    the whole element slot (for example ``data_type``/``exists`` visibility on color,
    alpha, thickness and opacity inputs).  Treating those representation changes as
    caption regressions caused the V1 false stop.  Only COME's outline/shadow slot is
    normalized here; its actual values are validated separately by
    :func:`validate_target_effect_contract`.  Every non-effect property on COME and
    every property on the other 113 captions remains byte-for-byte frozen.
    """
    value = copy.deepcopy(dict(snapshot))
    value.pop("sha256", None)
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise ValueError("snapshot_rows")
    for row in rows:
        if not isinstance(row, MutableMapping) or _row_name(row) != TARGET_CAPTION_NAME:
            continue
        properties = row.get("properties")
        if not isinstance(properties, MutableMapping):
            raise ValueError("snapshot_properties")
        for field in TARGET_EFFECT_SNAPSHOT_FIELDS:
            if field not in properties:
                raise ValueError(f"target_effect_field_missing:{field}")
            properties[field] = {"validated_by_target_effect_contract": field}
    return value


def frozen_snapshot_equal(source: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    return canonical_sha256(_normalized_snapshot_for_frozen_compare(source)) == canonical_sha256(
        _normalized_snapshot_for_frozen_compare(target)
    )


def _authority(root: Path, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    effect_plan = load_json(root / EFFECT_PLAN_RELATIVE)
    effect_validation = load_json(root / EFFECT_PLAN_VALIDATION_RELATIVE)
    visual = load_json(root / VISUAL_AUTHORITY_RELATIVE)
    if effect_validation.get("ok") is not True or effect_validation.get("failures"):
        raise RuntimeError("effect_plan_validation")
    names = [str(name) for name in snapshot.get("names") or []]
    if len(names) != EXPECTED_TEXTPLUS_COUNT or len(set(names)) != EXPECTED_TEXTPLUS_COUNT:
        raise RuntimeError("snapshot_names")
    authority = build_authority(names, effect_plan, visual)
    return {
        **authority,
        "effect_plan_hash": str(effect_plan.get("plan_hash") or canonical_sha256(effect_plan)),
        "visual_authority_semantic_sha256": str(visual.get("semantic_sha256") or canonical_sha256(visual)),
    }




def _target_effect_rule(authority: Mapping[str, Any]) -> Mapping[str, Any]:
    rules = authority.get("rules")
    if not isinstance(rules, Mapping):
        raise ValueError("authority_rules")
    rule = rules.get(TARGET_CAPTION_NAME)
    if not isinstance(rule, Mapping) or rule.get("kind") != "legacy":
        raise ValueError("target_effect_rule")
    effect = rule.get("effect")
    target = effect.get("target") if isinstance(effect, Mapping) else None
    if not isinstance(target, Mapping):
        raise ValueError("target_effect_target")
    return target


def target_effect_contract_spec(authority: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Return the complete proven Text+ outline/shadow input contract for COME.

    The 14 required + 3 optional fields mirror the historical Step 3B.3 probe/full
    rollout contract.  V1 only audited enable/color/opacity, which was too narrow.
    """
    target = _target_effect_rule(authority)
    outline = target.get("outline")
    shadow = target.get("shadow")
    if not isinstance(outline, Mapping) or not isinstance(shadow, Mapping):
        raise ValueError("target_effect_shape")
    or_, og, ob = _rgb(str(outline.get("color") or ""))
    sr, sg, sb = _rgb(str(shadow.get("color") or ""))
    offset = shadow.get("offset")
    if not isinstance(offset, Sequence) or isinstance(offset, (str, bytes)) or len(offset) < 2:
        raise ValueError("target_shadow_offset")
    return [
        {"label": "outline_enabled", "candidates": ["Enabled2"], "expected": 1.0, "required": True},
        {"label": "outline_shape", "candidates": ["ElementShape2", "Appearance2"], "expected": 1.0, "required": True},
        {"label": "outline_red", "candidates": ["Red2"], "expected": or_, "required": True},
        {"label": "outline_green", "candidates": ["Green2"], "expected": og, "required": True},
        {"label": "outline_blue", "candidates": ["Blue2"], "expected": ob, "required": True},
        {"label": "outline_alpha", "candidates": ["Alpha2"], "expected": 1.0, "required": True},
        {"label": "outline_thickness", "candidates": ["Thickness2"], "expected": float(outline.get("thickness")), "required": True},
        {"label": "outline_outside_only", "candidates": ["OutsideOnly2"], "expected": float(outline.get("outside_only", 1.0)), "required": False},
        {"label": "shadow_enabled", "candidates": ["Enabled3"], "expected": 1.0, "required": True},
        {"label": "shadow_shape", "candidates": ["ElementShape3", "Appearance3"], "expected": 0.0, "required": True},
        {"label": "shadow_red", "candidates": ["Red3"], "expected": sr, "required": True},
        {"label": "shadow_green", "candidates": ["Green3"], "expected": sg, "required": True},
        {"label": "shadow_blue", "candidates": ["Blue3"], "expected": sb, "required": True},
        {"label": "shadow_opacity", "candidates": ["Opacity3", "Alpha3"], "expected": float(shadow.get("opacity")), "required": True},
        {"label": "shadow_offset", "candidates": ["Offset3"], "expected": [float(offset[0]), float(offset[1])], "required": True},
        {"label": "shadow_softness_x", "candidates": ["SoftnessX3", "Softness3"], "expected": float(shadow.get("softness")), "required": False},
        {"label": "shadow_softness_y", "candidates": ["SoftnessY3"], "expected": float(shadow.get("softness")), "required": False},
    ]


def _point_pair(value: Any) -> Tuple[float, float] | None:
    if isinstance(value, Mapping):
        for xk, yk in ((1, 2), ("1", "2"), ("x", "y"), ("X", "Y")):
            if xk in value and yk in value:
                try:
                    return float(value[xk]), float(value[yk])
                except (TypeError, ValueError):
                    return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _contract_value_matches(actual: Any, expected: Any) -> bool:
    expected_point = _point_pair(expected)
    if expected_point is not None:
        actual_point = _point_pair(actual)
        return actual_point is not None and all(_close(a, e) for a, e in zip(actual_point, expected_point))
    return _close(actual, expected)


def validate_target_effect_contract(base: Any, tool: Any, authority: Mapping[str, Any]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for spec in target_effect_contract_spec(authority):
        candidates = [str(value) for value in spec["candidates"]]
        resolved = None
        for candidate in candidates:
            if base.find_input(tool, candidate) is not None:
                resolved = candidate
                break
        actual = base.read_input(tool, resolved, 0) if resolved else None
        matched = resolved is not None and _contract_value_matches(actual, spec["expected"])
        rows.append({
            "label": spec["label"],
            "candidates": candidates,
            "resolved_input": resolved,
            "required": bool(spec["required"]),
            "expected": base.json_safe(spec["expected"]),
            "actual": base.json_safe(actual),
            "exposed": resolved is not None,
            "matched": matched,
        })
    required = [row for row in rows if row["required"]]
    optional = [row for row in rows if not row["required"]]
    # This Resolve/Text+ environment historically exposed all three optional inputs.
    # Treat their disappearance as an integration mismatch instead of silently weakening
    # the source-backed contract.
    ok = (
        len(required) == 14
        and all(row["matched"] for row in required)
        and len(optional) == 3
        and all(row["exposed"] and row["matched"] for row in optional)
    )
    return {
        "ok": ok,
        "required_count": len(required),
        "required_matched_count": sum(bool(row["matched"]) for row in required),
        "optional_count": len(optional),
        "optional_exposed_count": sum(bool(row["exposed"]) for row in optional),
        "optional_matched_count": sum(bool(row["matched"]) for row in optional),
        "rows": rows,
    }


def _target_text_tool(base: Any, timeline: Any) -> Any:
    item = _find_caption(base, timeline, TARGET_CAPTION_NAME)
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if tool is None:
        raise RuntimeError("target_text_tool")
    return tool


def _find_caption(base: Any, timeline: Any, name: str) -> Any:
    rows = [item for _track, item in base.all_video_items(timeline) if base.item_name(item) == name]
    if len(rows) != 1:
        raise RuntimeError(f"caption_count:{name}:{len(rows)}")
    return rows[0]


def _set_static(base: Any, tool: Any, field: str, expected: float) -> Dict[str, Any]:
    input_object = base.find_input(tool, field)
    if input_object is None:
        raise RuntimeError(f"input_missing:{field}")
    before = base.read_input(tool, field, 0)
    if _close(before, expected):
        return {"field": field, "before": base.json_safe(before), "after": base.json_safe(before), "written": False, "ok": True}
    returned = tool.SetInput(field, expected)
    after = base.read_input(tool, field, 0)
    ok = _close(after, expected)
    return {
        "field": field,
        "before": base.json_safe(before),
        "requested": expected,
        "returned": base.json_safe(returned),
        "after": base.json_safe(after),
        "written": True,
        "ok": ok,
    }


def ensure_target_effect(base: Any, v1: Any, timeline: Any, authority: Mapping[str, Any]) -> Dict[str, Any]:
    before = v1.caption_snapshot(timeline)
    audit_before = audit_snapshot(before, authority)
    tool = _target_text_tool(base, timeline)
    if audit_before.get("ok") is True:
        contract = validate_target_effect_contract(base, tool, authority)
        if contract.get("ok") is not True:
            raise RuntimeError("target_effect_contract_idempotent")
        return {
            "ok": True,
            "mutated": False,
            "idempotent_noop": True,
            "write_count": 0,
            "writes": [],
            "audit_before": audit_before,
            "audit_after": audit_before,
            "target_effect_contract": contract,
        }
    if mismatch_signature(audit_before) != expected_source_mismatch_signature():
        raise RuntimeError(f"unexpected_effect_mismatch:{mismatch_signature(audit_before)}")

    writes = [
        _set_static(base, tool, "Enabled2", 1.0),
        _set_static(base, tool, "Enabled3", 1.0),
    ]
    if not all(row.get("ok") is True for row in writes):
        raise RuntimeError(f"effect_readback:{writes}")
    if sum(1 for row in writes if row.get("written")) != 2:
        raise RuntimeError(f"effect_write_count:{writes}")

    after = v1.caption_snapshot(timeline)
    audit_after = audit_snapshot(after, authority)
    if audit_after.get("ok") is not True:
        raise RuntimeError(f"effect_post_audit:{mismatch_signature(audit_after)}")
    contract = validate_target_effect_contract(base, tool, authority)
    if contract.get("ok") is not True:
        raise RuntimeError("target_effect_contract")
    if not frozen_snapshot_equal(before, after):
        raise RuntimeError("unrelated_caption_regression")
    return {
        "ok": True,
        "mutated": True,
        "idempotent_noop": False,
        "write_count": 2,
        "writes": writes,
        "audit_before": audit_before,
        "audit_after": audit_after,
        "target_effect_contract": contract,
    }


def _delete_target(v4: Any, media_pool: Any, target: Any) -> Dict[str, Any]:
    try:
        return dict(v4._delete_timeline(media_pool, target))
    except BaseException as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if not run_id or command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")

    # Resolve the root without importing the runtime dependency chain at module import time.
    module_path = Path(__file__).resolve()
    root = module_path.parents[2]
    v4, base, v1, full = load_runtime(root)
    root = base.repository_root()
    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    config = command.get("outline_shadow") if isinstance(command.get("outline_shadow"), Mapping) else {}

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "ok": False,
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "final_textplus_count": 0,
        "targeted_caption_count": 1,
        "targeted_effect_write_count": 0,
        "unrelated_caption_mutation_count": 0,
        "occlusion_mutation_count": 0,
        "save_call_count": 0,
        "resolve_invocation_contract": 1,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
        "failures": [],
    }
    project_manager = project = media_pool = source = target = None
    target_created = False
    saved = False
    try:
        contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", contract)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_exists")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")

        source_uid = base.timeline_unique_id(source)
        source_snapshot = v1.caption_snapshot(source)
        source_inventory = v1.stable_inventory(source)
        source_occlusion = v4.verify_v4_occlusion(source)
        if source_occlusion.get("ok") is not True:
            raise RuntimeError("accepted_v4_occlusion_missing")
        expected_snapshot_sha = str(config.get("accepted_caption_snapshot_sha256") or "")
        if source_snapshot.get("sha256") != expected_snapshot_sha:
            raise RuntimeError(f"accepted_snapshot_mismatch:{source_snapshot.get('sha256')}:{expected_snapshot_sha}")
        if source_snapshot.get("count") != EXPECTED_TEXTPLUS_COUNT:
            raise RuntimeError("source_textplus_count")

        authority = _authority(root, source_snapshot)
        source_audit = audit_snapshot(source_snapshot, authority)
        if mismatch_signature(source_audit) != expected_source_mismatch_signature():
            raise RuntimeError(f"source_effect_preimage:{mismatch_signature(source_audit)}")
        base.write_json(report_dir / "outline_shadow_preflight.json", {
            "resolve_calls": resolve_calls,
            "source_unique_id": source_uid,
            "source_caption_snapshot_sha256": source_snapshot.get("sha256"),
            "accepted_caption_snapshot_sha256": expected_snapshot_sha,
            "source_effect_audit": source_audit,
            "authority_counts": authority.get("counts"),
            "effect_plan_hash": authority.get("effect_plan_hash"),
            "visual_authority_semantic_sha256": authority.get("visual_authority_semantic_sha256"),
            "source_v4_occlusion": source_occlusion,
            "authorized_target": {
                "caption": TARGET_CAPTION_NAME,
                "cue_id": TARGET_CUE_ID,
                "fields": sorted(AUTHORIZED_EFFECT_FIELDS),
                "values": {"Enabled2": 1.0, "Enabled3": 1.0},
            },
            "target_effect_contract_spec": target_effect_contract_spec(authority),
            "frozen_caption_contract": [
                "text", "Center", "Size", "Font", "Style", "case", "Fill", "timing", "track",
                "lifecycle", "Opacity1", "Opacity2", "Opacity3", "all animation/keyframe topology",
                "all non-target outline/shadow fields",
            ],
            "occlusion_frozen": True,
            "ok": True,
        })

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_target")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")

        duplicate_snapshot = v1.caption_snapshot(target)
        duplicate_occlusion = v4.verify_v4_occlusion(target)
        if not v1.caption_snapshots_equal(source_snapshot, duplicate_snapshot):
            raise RuntimeError("duplicate_caption_regression")
        if v1.stable_inventory(target) != source_inventory:
            raise RuntimeError("duplicate_inventory_regression")
        if duplicate_occlusion.get("ok") is not True:
            raise RuntimeError("duplicate_occlusion_regression")

        first = ensure_target_effect(base, v1, target, authority)
        after_first = v1.caption_snapshot(target)
        after_first_occ = v4.verify_v4_occlusion(target)
        if (
            first.get("ok") is not True or first.get("mutated") is not True or first.get("write_count") != 2
            or not frozen_snapshot_equal(source_snapshot, after_first)
            or after_first_occ.get("ok") is not True
            or v1.stable_inventory(target) != source_inventory
        ):
            raise RuntimeError("first_application_contract")

        second = ensure_target_effect(base, v1, target, authority)
        after_second = v1.caption_snapshot(target)
        after_second_occ = v4.verify_v4_occlusion(target)
        if (
            second.get("ok") is not True or second.get("mutated") is not False
            or second.get("idempotent_noop") is not True or second.get("write_count") != 0
            or after_second.get("sha256") != after_first.get("sha256")
            or after_second_occ.get("ok") is not True
        ):
            raise RuntimeError("idempotency_contract")

        post_audit = audit_snapshot(after_second, authority)
        if post_audit.get("ok") is not True:
            raise RuntimeError("post_authority_audit")
        base.write_json(report_dir / "outline_shadow_application.json", {
            "duplicate_call": duplicate_call,
            "select_target_call": select_call,
            "duplicate_caption_snapshot_sha256": duplicate_snapshot.get("sha256"),
            "first_application": first,
            "second_application": second,
            "post_effect_audit": post_audit,
            "checks": {
                "duplicate_exact": v1.caption_snapshots_equal(source_snapshot, duplicate_snapshot),
                "targeted_write_count_2": first.get("write_count") == 2,
                "targeted_caption_only": all(row.get("field") in AUTHORIZED_EFFECT_FIELDS for row in first.get("writes") or []),
                "first_full_effect_contract": isinstance(first.get("target_effect_contract"), Mapping) and first["target_effect_contract"].get("ok") is True,
                "second_full_effect_contract": isinstance(second.get("target_effect_contract"), Mapping) and second["target_effect_contract"].get("ok") is True,
                "frozen_caption_state_unchanged": frozen_snapshot_equal(source_snapshot, after_second),
                "v4_occlusion_unchanged": after_second_occ.get("ok") is True,
                "inventory_unchanged": v1.stable_inventory(target) == source_inventory,
                "authority_complete": post_audit.get("ok") is True,
                "idempotent_second_noop": second.get("idempotent_noop") is True and second.get("write_count") == 0,
            },
            "source_caption_snapshot": source_snapshot,
            "target_caption_snapshot": after_second,
            "ok": True,
        })

        save = base.save_project(project_manager)
        report["save_call_count"] = 1
        saved = True
        if save.get("success") is not True:
            raise RuntimeError("save")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("persistent_reacquire")
        source_after_snapshot = v1.caption_snapshot(source_after)
        target_after_snapshot = v1.caption_snapshot(target_after)
        source_after_occ = v4.verify_v4_occlusion(source_after)
        target_after_occ = v4.verify_v4_occlusion(target_after)
        target_after_audit = audit_snapshot(target_after_snapshot, authority)
        target_after_contract = validate_target_effect_contract(base, _target_text_tool(base, target_after), authority)
        persistent_checks = {
            "source_unique_id_unchanged": base.timeline_unique_id(source_after) == source_uid,
            "source_caption_snapshot_unchanged": v1.caption_snapshots_equal(source_snapshot, source_after_snapshot),
            "source_inventory_unchanged": v1.stable_inventory(source_after) == source_inventory,
            "source_v4_occlusion_unchanged": source_after_occ.get("ok") is True,
            "target_frozen_caption_state_unchanged": frozen_snapshot_equal(source_snapshot, target_after_snapshot),
            "target_effect_authority_complete": target_after_audit.get("ok") is True,
            "target_full_effect_contract_complete": target_after_contract.get("ok") is True,
            "target_inventory_unchanged": v1.stable_inventory(target_after) == source_inventory,
            "target_v4_occlusion_unchanged": target_after_occ.get("ok") is True,
            "textplus_114": target_after_snapshot.get("count") == EXPECTED_TEXTPLUS_COUNT,
            "v2_track_empty": not full.track_two_item_names(target_after),
            "one_save": report.get("save_call_count") == 1,
            "idempotency": second.get("idempotent_noop") is True and second.get("write_count") == 0,
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "save": save,
            "source_caption_snapshot_before": source_snapshot,
            "source_caption_snapshot_after": source_after_snapshot,
            "target_caption_snapshot": target_after_snapshot,
            "source_occlusion": source_after_occ,
            "target_occlusion": target_after_occ,
            "target_effect_audit": target_after_audit,
            "target_effect_contract": target_after_contract,
            "checks": persistent_checks,
            "visual_approval_required": True,
            "further_rollout_authorized": False,
            "ok": all(value is True for value in persistent_checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if persistent.get("ok") is not True:
            raise RuntimeError("persistent_readback")

        report.update({
            "ok": True,
            "final_textplus_count": EXPECTED_TEXTPLUS_COUNT,
            "targeted_effect_write_count": 2,
            "targeted_caption_count": 1,
            "targeted_caption_name": TARGET_CAPTION_NAME,
            "targeted_effect_fields": sorted(AUTHORIZED_EFFECT_FIELDS),
            "unrelated_caption_mutation_count": 0,
            "occlusion_mutation_count": 0,
            "source_timeline_unchanged": True,
            "v4_occlusion_preserved": True,
            "persistent_readback_ok": True,
            "idempotency_ok": True,
            "target_timeline_kept": True,
        })
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if not saved and project_manager is not None and project is not None and media_pool is not None and target_created:
            cleanup: Dict[str, Any] = {"errors": [], "save_call_count": 0}
            try:
                if source is not None:
                    selected, call = base.direct_call(project, "SetCurrentTimeline", source)
                    cleanup["restore_source"] = call
                    if not selected:
                        cleanup["errors"].append("restore_source")
                live_target = base.find_timeline(project, TARGET_TIMELINE_NAME)
                if live_target is not None:
                    deletion = _delete_target(v4, media_pool, live_target)
                    cleanup["delete_target"] = deletion
                    if deletion.get("ok") is not True:
                        cleanup["errors"].append("delete_target")
                save = base.save_project(project_manager)
                cleanup["save"] = save
                cleanup["save_call_count"] = 1
                report["save_call_count"] = 1
                if save.get("success") is not True:
                    cleanup["errors"].append("save_cleanup")
            except BaseException as cleanup_exc:
                cleanup["errors"].append(base.compact_exception(cleanup_exc))
                cleanup["traceback"] = traceback.format_exc()
            cleanup["ok"] = not cleanup["errors"]
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["failure_cleanup_ok"] = cleanup.get("ok") is True
            report["failed_target_retained"] = False if cleanup.get("ok") is True else None
        elif saved:
            report["post_save_failure_target_retained"] = True
        return report
