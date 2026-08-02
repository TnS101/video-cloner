#!/usr/bin/env python3
"""Independent validator for Major Step 3B.4A fill-color probe plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

VERSION = "validate_caption_fill_color_probe_plan_step_3B_4_v1_0"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Plan must be a JSON object")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def canonical_hash(payload: Dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--probe-cue-id", default="sub_019")
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    failures = []
    try:
        plan = load_json(plan_path)
        items = [row for row in (plan.get("items") or []) if isinstance(row, dict)]
        selected = [row for row in items if row.get("probe_selected")]
        item = selected[0] if len(selected) == 1 else {}
        fill = item.get("source_fill") or {}
        checks = {
            "plan_ok": plan.get("ok") is True,
            "step": plan.get("step") == "Major Step 3B.4A",
            "plan_hash": plan.get("plan_hash") == canonical_hash(plan),
            "expected_v3_count": int(plan.get("expected_v3_count") or 0) == args.expected_v3_count,
            "one_probe": len(selected) == 1,
            "probe_cue_id": item.get("cue_id") == args.probe_cue_id,
            "identity_complete": all(item.get(key) not in (None, "") for key in ("name", "text", "expected_font_family", "expected_font_face")),
            "fill_hex": isinstance(fill.get("hex"), str) and len(fill.get("hex")) == 7,
            "fill_rgb": all(isinstance(fill.get(key), (int, float)) and 0.0 <= float(fill.get(key)) <= 1.0 for key in ("red", "green", "blue", "alpha")),
            "animation_targets": len(item.get("protected_animation_targets") or []) == 2,
            "no_plan_failures": not (plan.get("failures") or []),
        }
        failures = [key for key, value in checks.items() if not value]
        result = {
            "ok": not failures,
            "step": "Major Step 3B.4A",
            "validator_version": VERSION,
            "plan": str(plan_path),
            "checks": checks,
            "summary": plan.get("summary") or {},
            "failures": failures,
        }
    except Exception as exc:
        result = {
            "ok": False,
            "step": "Major Step 3B.4A",
            "validator_version": VERSION,
            "plan": str(plan_path),
            "checks": {},
            "failures": [f"{type(exc).__name__}: {exc}"],
        }
    write_json(Path(args.output), result)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
