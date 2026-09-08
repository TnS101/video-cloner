"""Step 3B.3 V2: precedence-aware outline/shadow authority reconciliation.

This is intentionally offline.  It proves whether the accepted V4 caption snapshot
already satisfies the strongest currently accepted outline/shadow authority.

The historical Step 3B.3 detector/effect plan predates the later source-frame visual
correction for COME.  The later correction explicitly locks COME shading elements 2
and 3 disabled.  Monotonic non-regression therefore treats that later source-backed
proof as the authority for those two fields instead of re-enabling the stale plan.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3B3_OUTLINE_SHADOW_AUTHORITY_RECONCILIATION_V2"
ACCEPTED_TIMELINE = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_"
    "confirmed74_repair_metrics_v1_occlusion_complete_v4"
)
TARGET_CAPTION_NAME = "VC_TEXTPLUS_0052_sub_052"
EXPECTED_TEXTPLUS_COUNT = 114
EXPECTED_STALE_MISMATCHES = (
    (TARGET_CAPTION_NAME, "Enabled2", 1.0, 0.0),
    (TARGET_CAPTION_NAME, "Enabled3", 1.0, 0.0),
)

V1_RUNTIME_RELATIVE = "resolve_workspace/modules/step_3B3_outline_shadow_cloning_v1.py"
VISUAL_CORRECTION_RELATIVE = "resolve_workspace/modules/step_3D_visual_instance_correction.py"
EFFECT_PLAN_RELATIVE = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_effect_mode_plan_step_3B_3C.json"
EFFECT_VALIDATION_RELATIVE = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_effect_mode_plan_step_3B_3C_validation.json"
VISUAL_AUTHORITY_RELATIVE = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
HISTORICAL_FULL_RELATIVE = "data/DZsqH7auhjt/davinci/DZsqH7auhjt_resolve_outline_shadow_full_step_3B_3B_first_application_report.json"
V4_RUN_RELATIVE = (
    ".agent/reports/DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4/"
    "20260812T174800495896Z_07d0e09144764182a5c4b1ec41ca6952"
)
V4_REPORT_RELATIVE = V4_RUN_RELATIVE + "/report.json"
V4_PERSISTENT_RELATIVE = V4_RUN_RELATIVE + "/persistent_readback.json"


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _safe_numeric(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_safe_numeric(node.operand)
    if isinstance(node, ast.BinOp):
        left = _safe_numeric(node.left)
        right = _safe_numeric(node.right)
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
    raise ValueError(f"non_numeric_ast:{ast.dump(node, include_attributes=False)}")


def extract_come_source_frame_style(path: Path) -> Dict[str, float]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "COME_SOURCE_FRAME_STYLE" for target in targets):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            raise ValueError("come_source_frame_style_not_dict")
        output: Dict[str, float] = {}
        for key_node, value_node in zip(value.keys, value.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                raise ValueError("come_source_frame_style_key")
            output[key_node.value] = _safe_numeric(value_node)
        return output
    raise ValueError("come_source_frame_style_missing")


def _snapshot_row(snapshot: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("snapshot_rows")
    matches = [row for row in rows if isinstance(row, Mapping) and str(row.get("name") or "") == name]
    if len(matches) != 1:
        raise ValueError(f"snapshot_row:{name}:{len(matches)}")
    return matches[0]


def _series(row: Mapping[str, Any], field: str) -> Sequence[Any]:
    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError("snapshot_properties")
    prop = properties.get(field)
    if not isinstance(prop, Mapping) or prop.get("exists") is not True:
        raise ValueError(f"snapshot_field:{field}")
    values = prop.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError(f"snapshot_values:{field}")
    return values


def _all_zero(values: Sequence[Any], tolerance: float = 2e-5) -> bool:
    try:
        return bool(values) and all(abs(float(value)) <= tolerance for value in values)
    except (TypeError, ValueError):
        return False


def _historical_come_row(document: Mapping[str, Any]) -> Mapping[str, Any]:
    items = document.get("items")
    if not isinstance(items, list):
        raise ValueError("historical_items")
    matches = [
        item for item in items
        if isinstance(item, Mapping) and str(item.get("name") or "") == TARGET_CAPTION_NAME
    ]
    if len(matches) != 1:
        raise ValueError(f"historical_come:{len(matches)}")
    return matches[0]


def build_report(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    v1 = _load_module(root / V1_RUNTIME_RELATIVE, "vc_step3b3_v1_for_authority_v2")
    effect_plan = load_json(root / EFFECT_PLAN_RELATIVE)
    effect_validation = load_json(root / EFFECT_VALIDATION_RELATIVE)
    visual_authority = load_json(root / VISUAL_AUTHORITY_RELATIVE)
    historical = load_json(root / HISTORICAL_FULL_RELATIVE)
    v4_report = load_json(root / V4_REPORT_RELATIVE)
    v4_persistent = load_json(root / V4_PERSISTENT_RELATIVE)

    if effect_validation.get("ok") is not True or effect_validation.get("failures"):
        raise ValueError("effect_plan_validation")
    if v4_report.get("ok") is not True or v4_persistent.get("ok") is not True:
        raise ValueError("accepted_v4_not_ok")
    if str(v4_report.get("target_timeline_name") or "") != ACCEPTED_TIMELINE:
        raise ValueError("accepted_v4_timeline")

    snapshot = v4_persistent.get("target_caption_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("accepted_snapshot")
    if int(snapshot.get("count") or 0) != EXPECTED_TEXTPLUS_COUNT:
        raise ValueError("accepted_textplus_count")
    names = [str(name) for name in snapshot.get("names") or []]
    if len(names) != EXPECTED_TEXTPLUS_COUNT or len(set(names)) != EXPECTED_TEXTPLUS_COUNT:
        raise ValueError("accepted_snapshot_names")

    stale_authority = v1.build_authority(names, effect_plan, visual_authority)
    stale_audit = v1.audit_snapshot(snapshot, stale_authority)
    stale_signature = v1.mismatch_signature(stale_audit)
    expected_stale = tuple(sorted(EXPECTED_STALE_MISMATCHES, key=lambda row: (row[0], row[1])))
    if stale_signature != expected_stale:
        raise ValueError(f"unexpected_stale_mismatch:{stale_signature}")

    later_style = extract_come_source_frame_style(root / VISUAL_CORRECTION_RELATIVE)
    if abs(float(later_style.get("Enabled2", 999.0))) > 2e-5:
        raise ValueError("later_come_outline_not_disabled")
    if abs(float(later_style.get("Enabled3", 999.0))) > 2e-5:
        raise ValueError("later_come_shadow_not_disabled")

    come_row = _snapshot_row(snapshot, TARGET_CAPTION_NAME)
    come_enabled2 = _series(come_row, "Enabled2")
    come_enabled3 = _series(come_row, "Enabled3")
    if not _all_zero(come_enabled2) or not _all_zero(come_enabled3):
        raise ValueError("accepted_come_effect_state_changed")

    historical_come = _historical_come_row(historical)
    write = historical_come.get("write") if isinstance(historical_come.get("write"), Mapping) else {}
    if historical_come.get("modified") is not True or int(write.get("write_count") or 0) != 19:
        raise ValueError("historical_step3b3_proof")
    if int(historical_come.get("verified_required_input_count") or 0) != 14:
        raise ValueError("historical_required_contract")
    if int(historical_come.get("verified_optional_input_count") or 0) != 3:
        raise ValueError("historical_optional_contract")

    effective_authority = copy.deepcopy(stale_authority)
    rules = effective_authority.get("rules")
    if not isinstance(rules, dict):
        raise ValueError("effective_rules")
    come_rule = rules.get(TARGET_CAPTION_NAME)
    if not isinstance(come_rule, dict):
        raise ValueError("effective_come_rule")
    effect = come_rule.get("effect")
    target = effect.get("target") if isinstance(effect, dict) else None
    if not isinstance(target, dict):
        raise ValueError("effective_come_target")
    outline = target.get("outline")
    shadow = target.get("shadow")
    if not isinstance(outline, dict) or not isinstance(shadow, dict):
        raise ValueError("effective_come_shape")
    outline["enabled"] = False
    shadow["enabled"] = False
    come_rule["authority_override"] = {
        "source": "step_3D_visual_instance_correction.COME_SOURCE_FRAME_STYLE",
        "reason": "later_source_frame_visual_proof_supersedes_historical_step3b3_detector_for_enabled_state",
        "fields": {"Enabled2": 0.0, "Enabled3": 0.0},
    }

    effective_audit = v1.audit_snapshot(snapshot, effective_authority)
    if effective_audit.get("ok") is not True or int(effective_audit.get("mismatch_count") or 0) != 0:
        raise ValueError(f"effective_authority_mismatch:{v1.mismatch_signature(effective_audit)}")

    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "accepted_timeline": ACCEPTED_TIMELINE,
        "accepted_caption_snapshot_sha256": str(snapshot.get("sha256") or ""),
        "textplus_count": EXPECTED_TEXTPLUS_COUNT,
        "historical_authority": {
            "source": EFFECT_PLAN_RELATIVE,
            "stale_mismatch_count": int(stale_audit.get("mismatch_count") or 0),
            "stale_mismatch_signature": [list(row) for row in stale_signature],
            "historical_full_rollout_come_write_count": int(write.get("write_count") or 0),
            "historical_full_rollout_contract": {
                "required": int(historical_come.get("verified_required_input_count") or 0),
                "optional": int(historical_come.get("verified_optional_input_count") or 0),
            },
        },
        "stronger_later_authority": {
            "source": VISUAL_CORRECTION_RELATIVE,
            "come_source_frame_style": {
                "Enabled2": float(later_style["Enabled2"]),
                "Enabled3": float(later_style["Enabled3"]),
                "Thickness2": float(later_style.get("Thickness2", 0.0)),
            },
            "accepted_snapshot_enabled2_zero": _all_zero(come_enabled2),
            "accepted_snapshot_enabled3_zero": _all_zero(come_enabled3),
        },
        "effective_authority": {
            "policy": "monotonic_non_regression_later_source_visual_proof_wins_per_property",
            "override_caption": TARGET_CAPTION_NAME,
            "override_fields": {"Enabled2": 0.0, "Enabled3": 0.0},
            "mismatch_count": int(effective_audit.get("mismatch_count") or 0),
            "audit_ok": effective_audit.get("ok") is True,
        },
        "decision": {
            "step_3B3_status": "complete_no_mutation_required",
            "timeline_mutation_required": False,
            "resolve_invocations_required": 0,
            "save_calls_required": 0,
            "new_timeline_required": False,
            "accepted_timeline_remains": ACCEPTED_TIMELINE,
            "failed_outline_shadow_v1_targets_must_not_be_used": True,
            "next_boundary": "caption_motion_fade_application",
        },
    }
