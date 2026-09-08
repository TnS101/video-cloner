#!/usr/bin/env python3
"""Validate Major Step 3B.6D contained source geometry rollout plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

VERSION = "validate_caption_source_geometry_contained_rollout_plan_step_3B_6D_v1_1_center_size_only"
SCHEMA = "video_cloner_caption_source_geometry_contained_rollout_plan"
EXPECTED_CUES = {
    "sub_007": ("While", 196, 199),
    "sub_013": ("out", 224, 230),
    "sub_110": ("looks", 862, 868),
    "sub_114": ("AND", 888, 894),
}
ALLOWED_PROPERTIES = {"Center", "Size"}
EXPECTED_EXCLUDED_BLEND_BY_CUE = {"sub_007": 2, "sub_013": 2, "sub_110": 2, "sub_114": 0}


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def canonical_hash(value: Dict[str, Any], ignored: Sequence[str] = ()) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    for key in ignored:
        clean.pop(key, None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def operation_input(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    nested = row.get("target")
    return str((nested.get("input") if isinstance(nested, dict) else row.get("input")) or "")


def manifest_operations(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if not isinstance(value, dict):
        return []
    if operation_input(value):
        return [value]
    rows: List[Dict[str, Any]] = []
    for key in ("operations", "targets", "writes"):
        rows.extend(manifest_operations(value.get(key)))
    return rows


def validate(plan: Dict[str, Any]) -> Dict[str, Any]:
    items = plan.get("rollout_items") or []
    summary = plan.get("summary") or {}
    safety = plan.get("safety_contract") or {}
    cue_id_list = [str(row.get("cue_id")) for row in items]
    cue_ids = set(cue_id_list)
    names = [str(row.get("name")) for row in items]
    targets = [target for row in items for target in (row.get("targets") or [])]
    center_targets = [target for target in targets if operation_input(target) == "Center"]
    size_targets = [target for target in targets if operation_input(target) == "Size"]
    excluded = [target for row in items for target in (row.get("excluded_targets") or [])]
    manifest = manifest_operations(plan.get("mutation_manifest"))
    executable_properties = {operation_input(row) for row in targets + manifest}
    executable_properties.discard("")
    property_contract = plan.get("property_contract") or {}
    failures: List[str] = []
    checks = {
        "plan_ok": bool(plan.get("ok")),
        "schema": plan.get("schema") == SCHEMA,
        "plan_hash": str(plan.get("plan_hash") or "") == canonical_hash(plan, ignored=("created_at_unix",)),
        "v3_count": int(summary.get("v3_item_count") or 0) == 116,
        "accepted_count": int(summary.get("accepted_source_instance_count") or 0) == 45,
        "unresolved_count": int(summary.get("unresolved_source_instance_count") or 0) == 30,
        "timing_mismatch_count": int(summary.get("timing_mismatch_excluded_count") or 0) == 41,
        "rollout_count": len(items) == 4 and int(summary.get("rollout_item_count") or 0) == 4,
        "cue_set": cue_ids == set(EXPECTED_CUES),
        "unique_cues": len(cue_id_list) == len(set(cue_id_list)) == 4,
        "unique_names": len(names) == len(set(names)) == 4,
        "exact_identity": all(
            str(row.get("cue_id")) in EXPECTED_CUES
            and str(row.get("text")) == EXPECTED_CUES[str(row.get("cue_id"))][0]
            and int(row.get("start_frame") or -1) == EXPECTED_CUES[str(row.get("cue_id"))][1]
            and int(row.get("end_frame") or -1) == EXPECTED_CUES[str(row.get("cue_id"))][2]
            and str(row.get("name")) == f"VC_TEXTPLUS_{int(str(row.get('cue_id'))[-3:]):04d}_{row.get('cue_id')}"
            for row in items
        ),
        "all_accepted": all(
            bool(row.get("accepted_source_instance"))
            and str(row.get("source_exactness") or "") == "source_redetected_dense_word_instance"
            and not row.get("fallback_reasons")
            for row in items
        ),
        "all_contained": all(bool((row.get("visibility") or {}).get("fully_contained_in_existing_item")) for row in items),
        "target_counts": len(center_targets) == int(summary.get("center_target_count") or 0) == 18
        and len(size_targets) == int(summary.get("size_target_count") or 0) == 18
        and int(summary.get("blend_target_count") or 0) == 0
        and int(summary.get("other_property_target_count") or 0) == 0
        and len(targets) == int(summary.get("total_target_count") or 0) == 36,
        "visibility_gated_count": int(summary.get("visibility_gated_caption_count") or 0) == 0,
        "target_input_contract": executable_properties == ALLOWED_PROPERTIES,
        "item_target_partitions": all(
            list(row.get("center_targets") or []) == [target for target in (row.get("targets") or []) if operation_input(target) == "Center"]
            and list(row.get("size_targets") or []) == [target for target in (row.get("targets") or []) if operation_input(target) == "Size"]
            and not row.get("blend_targets")
            and set(str(value) for value in (row.get("write_inputs") or [])) == ALLOWED_PROPERTIES
            for row in items
        ),
        "excluded_blend_audit": len(excluded) == int(summary.get("excluded_blend_target_count") or 0) == 6
        and all(operation_input(row) == "Blend" and row.get("executable") is False and row.get("provenance") == "source_visibility_boundary" for row in excluded)
        and all(len(row.get("excluded_targets") or []) == EXPECTED_EXCLUDED_BLEND_BY_CUE.get(str(row.get("cue_id")), -1) for row in items),
        "property_contract": set(property_contract.get("allowed_operation_properties") or []) == ALLOWED_PROPERTIES
        and property_contract.get("known_excluded_source_properties") == ["Blend"]
        and property_contract.get("unknown_properties_fail_closed") is True,
        "mutation_manifest_contract": all(operation_input(row) in ALLOWED_PROPERTIES for row in manifest),
        "target_ranges": all(int(target.get("local_frame") or 0) >= 0 for target in targets),
        "expected_first_counts": int(summary.get("expected_first_modified_count") or 0) == 3 and int(summary.get("expected_first_already_correct_count") or 0) == 1,
        "protected_animation_count": int(summary.get("protected_animation_caption_count") or 0) == 8 and int(summary.get("protected_animation_target_count") or 0) == 16,
        "only_contained_writable": bool(safety.get("only_contained_accepted_cues_writable")),
        "boundaries_read_only": bool(safety.get("timeline_item_boundaries_read_only")),
        "other_v3_read_only": bool(safety.get("other_v3_captions_read_only")),
        "opacity_proxy_diagnostic": bool(safety.get("opacity_proxy_diagnostic_only")),
        "binary_visibility_forbidden": safety.get("binary_visibility_gate_allowed") is False,
        "center_size_allowlist": bool(safety.get("center_size_property_allowlist_enforced")),
        "unknown_properties_fail_closed": bool(safety.get("unknown_properties_fail_closed")),
        "z_order_read_only": bool(safety.get("z_order_read_only")),
        "hard_outline_forbidden": bool(safety.get("hard_outline_default_forbidden")) and bool(safety.get("solid_outline_100pct_no_blur_forbidden")),
        "no_plan_failures": not plan.get("failures"),
    }
    failures.extend(name for name, ok in checks.items() if not ok)
    return {
        "ok": not failures,
        "step": "Major Step 3B.6D",
        "validator_version": VERSION,
        "summary": summary,
        "checks": checks,
        "warnings": plan.get("warnings") or [],
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    try:
        payload = validate(load_json(Path(args.plan).resolve()))
        payload["plan"] = str(Path(args.plan).resolve())
        payload["output"] = str(output)
    except Exception as exc:
        payload = {"ok": False, "step": "Major Step 3B.6D", "validator_version": VERSION, "failures": ["validator_exception"], "exception": f"{type(exc).__name__}: {exc}", "output": str(output)}
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
