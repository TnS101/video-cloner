#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

VERSION = "validate_caption_outline_shadow_plan_step_3B_3_v1_0"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def canonical_hash(payload: Dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def integer(payload: Dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Major Step 3B.3A probe plan.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--probe-cue-id", default="sub_019")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    output_path = Path(args.output)
    plan = load_json(plan_path)
    summary = plan.get("summary") or {}
    items = plan.get("items") or []
    profiles = plan.get("profile_calibration") or {}
    expected = int(args.expected_v3_count)
    failures: List[str] = []
    warnings: List[str] = []

    selected = [row for row in items if isinstance(row, dict) and row.get("probe_selected")]
    probe = selected[0] if len(selected) == 1 else {}
    protected = probe.get("protected_animation_targets") or []
    source_effect = probe.get("source_effect") or {}

    checks = {
        "plan_ok": bool(plan.get("ok")),
        "schema": plan.get("schema") == "video_cloner_caption_outline_shadow_plan",
        "schema_version": str(plan.get("schema_version")) == "1.0",
        "mode": plan.get("mode") == "single_caption_safety_probe",
        "plan_hash_present": bool(plan.get("plan_hash")),
        "plan_hash_valid": plan.get("plan_hash") == canonical_hash(plan),
        "expected_v3_count": integer(plan, "expected_v3_count") == expected,
        "item_count": len(items) == expected,
        "summary_item_count": integer(summary, "v3_item_count") == expected,
        "profile_count": len(profiles) == 4 and integer(summary, "profile_count") == 4,
        "probe_item_count": len(selected) == 1 and integer(summary, "probe_item_count") == 1,
        "probe_cue_id": probe.get("cue_id") == args.probe_cue_id,
        "probe_outline_enabled": bool((source_effect.get("outline") or {}).get("enabled")),
        "probe_shadow_enabled": bool((source_effect.get("shadow") or {}).get("enabled")),
        "probe_animation_protected": len(protected) == 2,
        "outline_element": integer(plan, "outline_element") == 2,
        "shadow_element": integer(plan, "shadow_element") == 3,
        "elements_distinct": integer(plan, "outline_element") != integer(plan, "shadow_element"),
        "no_plan_failures": not (plan.get("failures") or []),
    }

    names = [str(row.get("name") or "") for row in items if isinstance(row, dict)]
    cues = [str(row.get("cue_id") or "") for row in items if isinstance(row, dict)]
    checks["unique_names"] = len(names) == expected and len(set(names)) == expected and all(names)
    checks["unique_cues"] = len(cues) == expected and len(set(cues)) == expected and all(cues)

    for key, passed in checks.items():
        if not passed:
            failures.append(f"check_failed:{key}")

    if integer(summary, "disabled_both_count") > 0:
        warnings.append(
            "The upstream detector marks some cues with neither outline nor shadow. "
            "The probe does not promote those uncertain cues to enabled effects."
        )

    validation = {
        "ok": not failures,
        "step": "Major Step 3B.3A",
        "validator_version": VERSION,
        "plan": str(plan_path),
        "plan_hash": plan.get("plan_hash"),
        "probe_cue_id": args.probe_cue_id,
        "checks": checks,
        "summary": summary,
        "warnings": warnings,
        "failures": failures,
    }
    write_json(output_path, validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
