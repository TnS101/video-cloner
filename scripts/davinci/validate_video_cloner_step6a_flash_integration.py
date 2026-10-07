"""Validate one completed Step 6A apply or idempotency report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_step6a_flash_integration as runtime


def validate(report: dict, expected_mode: str) -> dict:
    errors = []
    classification = report.get("classification")
    expected_classification = classification in {"FIRST_APPLICATION", "PARTIAL_TARGET_REPAIRED"} if expected_mode == "apply" else classification == "ALREADY_VALID_REUSED"
    checks = {
        "identity": report.get("task_id") == runtime.TASK_ID and report.get("mode") == runtime.MODE,
        "result": report.get("ok") is True and expected_classification,
        "authority": (report.get("authority_verification") or {}).get("ok") is True,
        "source_unchanged": report.get("source_timeline_unchanged") is True,
        "unrelated_unchanged": report.get("unrelated_timelines_unchanged") is True,
        "target_contract": ((report.get("target_after") or {}).get("ok") is True),
        "fusion_persisted": (((report.get("target_after") or {}).get("persisted_fusion") or {}).get("ok") is True),
        "current_restored": ((report.get("previous_timeline_restoration") or {}).get("ok") is True),
        "no_failures": not report.get("failures"),
    }
    if expected_mode == "apply":
        expected_mutations = 1 if classification == "FIRST_APPLICATION" else 0
        checks.update({"bounded_duplicate": report.get("timeline_duplicate_count") == expected_mutations, "bounded_track": report.get("track_add_count") == expected_mutations, "bounded_flash_append": report.get("flash_carrier_append_count") == expected_mutations, "visible_render": (report.get("visual_evidence") or {}).get("ok") is True, "saved_once": report.get("save_project_count") == 1, "persistent": report.get("persistent_readback_ok") is True})
    else:
        checks.update({"no_duplicate": report.get("timeline_duplicate_count") == 0, "no_track": report.get("track_add_count") == 0, "no_flash": report.get("flash_carrier_append_count") == 0, "no_media_import": report.get("media_import_count") == 0, "no_save": report.get("save_project_count") == 0, "idempotent": report.get("idempotent") is True})
    errors.extend(name for name, ok in checks.items() if not ok)
    return {"ok": not errors, "expected_mode": expected_mode, "checks": checks, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--run-mode", choices=("apply", "idempotency"), required=True)
    args = parser.parse_args()
    try:
        result = validate(json.loads(args.report.read_text(encoding="utf-8")), args.run_mode)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
