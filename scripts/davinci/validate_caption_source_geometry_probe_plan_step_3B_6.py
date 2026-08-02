#!/usr/bin/env python3
"""Validate Major Step 3B.6C dense source geometry/motion probe plan."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Sequence

VERSION = "validate_caption_source_geometry_probe_plan_step_3B_6C_v1_0"
EXPECTED_SCHEMA = "video_cloner_caption_source_geometry_probe_plan"
EXPECTED_V3_COUNT = 116


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


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def validate(plan: Dict[str, Any]) -> Dict[str, Any]:
    failures: List[str] = []
    warnings = list(plan.get("warnings") or [])
    checks: Dict[str, bool] = {}

    checks["plan_ok"] = bool(plan.get("ok"))
    checks["schema"] = plan.get("schema") == EXPECTED_SCHEMA
    checks["schema_version"] = plan.get("schema_version") == "1.0"
    checks["plan_hash"] = str(plan.get("plan_hash") or "") == canonical_hash(plan, ignored=("created_at_unix",))
    checks["v3_count"] = int(plan.get("expected_v3_count") or 0) == EXPECTED_V3_COUNT
    checks["preferred_scene"] = plan.get("selected_scene_id") == plan.get("validated_preferred_scene_id") == "caption_scene_015"

    probe = plan.get("probe") or {}
    checks["one_probe"] = int((plan.get("summary") or {}).get("probe_item_count") or 0) == 1 and bool(probe)
    checks["probe_cue"] = probe.get("cue_id") == "sub_114" and probe.get("text") == "AND"
    checks["probe_name"] = probe.get("name") == "VC_TEXTPLUS_0114_sub_114"
    checks["probe_source_exact"] = probe.get("source_exactness") == "source_redetected_dense_word_instance"
    checks["probe_high_confidence"] = (probe.get("confidence") or {}).get("label") == "high"
    checks["probe_fully_contained"] = bool((probe.get("visibility") or {}).get("fully_contained_in_existing_item"))
    checks["probe_duration"] = int(probe.get("duration_frames") or 0) == 6

    center = probe.get("center_targets") or []
    size = probe.get("size_targets") or []
    targets = probe.get("targets") or []
    expected_frames = list(range(6))
    checks["center_count"] = len(center) == 6
    checks["size_count"] = len(size) == 6
    checks["target_count"] = len(targets) == 12
    checks["center_frames"] = [int(row.get("local_frame") or 0) for row in center] == expected_frames
    checks["size_frames"] = [int(row.get("local_frame") or 0) for row in size] == expected_frames
    checks["center_values"] = all(
        isinstance(row.get("expected"), list)
        and len(row["expected"]) == 2
        and all(finite(v) and 0 <= float(v) <= 1 for v in row["expected"])
        for row in center
    )
    checks["size_values"] = all(finite(row.get("expected")) and 0.001 <= float(row["expected"]) <= 0.5 for row in size)
    checks["source_frames_present"] = all(row.get("source_frame") is not None for row in center + size)
    checks["only_center_size_writes"] = sorted(set(str(row.get("input")) for row in targets)) == ["Center", "Size"]

    diagnostics = probe.get("opacity_diagnostics") or []
    checks["opacity_diagnostic_only"] = len(diagnostics) == 6 and all(row.get("applied") is False for row in diagnostics)
    checks["forbidden_writes"] = all(
        name in (probe.get("forbidden_writes") or [])
        for name in ("clip_start", "clip_end", "track_index", "z_order", "Alpha1", "Blend", "outline", "shadow", "fill", "font", "text")
    )

    context = plan.get("scene_context") or []
    connected = next((row for row in context if row.get("cue_id") == "sub_116"), None)
    checks["connected_context_present"] = connected is not None
    checks["connected_excluded_for_timing"] = bool(
        connected
        and not connected.get("apply_eligible")
        and "source_visibility_outside_existing_v3_item" in (connected.get("exclusion_reasons") or [])
        and int(((connected.get("visibility") or {}).get("source_visibility_preroll_frames") or 0)) == 2
    )

    contract = plan.get("safety_contract") or {}
    checks["one_caption_only"] = bool(contract.get("one_probe_caption_only"))
    checks["timeline_boundaries_read_only"] = bool(contract.get("timeline_item_boundaries_read_only"))
    checks["other_v3_read_only"] = bool(contract.get("other_v3_captions_read_only"))
    checks["z_order_read_only"] = bool(contract.get("z_order_read_only"))
    checks["hard_outline_forbidden"] = bool(contract.get("hard_outline_default_forbidden"))
    checks["effect_policy"] = bool((plan.get("effect_policy") or {}).get("hard_outline_default_forbidden"))
    checks["protected_animation_targets"] = int((plan.get("summary") or {}).get("protected_animation_target_count") or 0) > 0
    checks["no_plan_failures"] = not plan.get("failures")

    for name, ok in checks.items():
        if not ok:
            failures.append(name)

    return {
        "ok": not failures,
        "step": "Major Step 3B.6C plan",
        "validator_version": VERSION,
        "summary": plan.get("summary") or {},
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        plan_path = Path(args.plan).resolve()
        payload = validate(load_json(plan_path))
        payload["plan"] = str(plan_path)
    except Exception as exc:
        payload = {
            "ok": False,
            "step": "Major Step 3B.6C plan",
            "validator_version": VERSION,
            "failures": ["validator_exception"],
            "exception": f"{type(exc).__name__}: {exc}",
        }
    write_json(Path(args.output).resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
