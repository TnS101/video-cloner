#!/usr/bin/env python3
"""Validate Major Step 3B.6D contained source geometry rollout plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

VERSION = "validate_caption_source_geometry_contained_rollout_plan_step_3B_6D_v1_0"
SCHEMA = "video_cloner_caption_source_geometry_contained_rollout_plan"
EXPECTED_CUES = {"sub_007", "sub_013", "sub_110", "sub_114"}


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


def validate(plan: Dict[str, Any]) -> Dict[str, Any]:
    items = plan.get("rollout_items") or []
    summary = plan.get("summary") or {}
    safety = plan.get("safety_contract") or {}
    cue_ids = {str(row.get("cue_id")) for row in items}
    names = [str(row.get("name")) for row in items]
    targets = [target for row in items for target in (row.get("targets") or [])]
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
        "cue_set": cue_ids == EXPECTED_CUES,
        "unique_names": len(names) == len(set(names)) == 4,
        "all_accepted": all(str(row.get("source_exactness") or "") == "source_redetected_dense_word_instance" for row in items),
        "all_contained": all(bool((row.get("visibility") or {}).get("fully_contained_in_existing_item")) for row in items),
        "target_counts": int(summary.get("center_target_count") or 0) == 18 and int(summary.get("size_target_count") or 0) == 18 and int(summary.get("blend_target_count") or 0) == 6 and int(summary.get("total_target_count") or 0) == 42,
        "visibility_gated_count": int(summary.get("visibility_gated_caption_count") or 0) == 3,
        "target_input_contract": sorted(set(str(row.get("input")) for row in targets)) == ["Blend", "Center", "Size"],
        "target_ranges": all(int(target.get("local_frame") or 0) >= 0 for target in targets),
        "expected_first_counts": int(summary.get("expected_first_modified_count") or 0) == 3 and int(summary.get("expected_first_already_correct_count") or 0) == 1,
        "protected_animation_count": int(summary.get("protected_animation_caption_count") or 0) == 8 and int(summary.get("protected_animation_target_count") or 0) == 16,
        "only_contained_writable": bool(safety.get("only_contained_accepted_cues_writable")),
        "boundaries_read_only": bool(safety.get("timeline_item_boundaries_read_only")),
        "other_v3_read_only": bool(safety.get("other_v3_captions_read_only")),
        "opacity_proxy_diagnostic": bool(safety.get("opacity_proxy_diagnostic_only")),
        "binary_visibility_allowed": bool(safety.get("binary_visibility_gate_allowed")),
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
