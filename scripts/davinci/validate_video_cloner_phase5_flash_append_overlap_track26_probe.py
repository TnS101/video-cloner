"""Offline validator for the disposable track-26 overlap probe."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TASK_ID = "VIDEO_CLONER_PHASE5_FLASH_APPEND_OVERLAP_TRACK26_PROBE_V1"
MODE = "phase5_flash_append_overlap_track26_probe"
DECISIVE = {
    "SAME_TRACK_DESTINATION_OVERLAP_CONFIRMED",
    "TRACK26_EMPTY_APPEND_FAILED",
    "APPEND_HELPER_POST_API_CLASSIFICATION_DEFECT",
    "OVERLAP_APPEND_SUCCEEDED",
}
REQUIRED = (
    "command.json",
    "publication_receipt.json",
    "probe_append_evidence.json",
    "probe_cleanup_evidence.json",
    "report.json",
    "status.json",
    "run.log",
)


def validate(root: Path, run_id: str) -> dict:
    directory = root.resolve() / ".agent" / "reports" / TASK_ID / run_id
    failures = []
    for name in REQUIRED:
        path = directory / name
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"artifact:{name}")
    if failures:
        return {"ok": False, "task_id": TASK_ID, "run_id": run_id, "failures": failures}
    report = json.loads((directory / "report.json").read_text(encoding="utf-8-sig"))
    cleanup = report.get("cleanup") or {}
    checks = {
        "identity": report.get("task_id") == TASK_ID and report.get("mode") == MODE and report.get("run_id") == run_id,
        "runtime": report.get("ok") is True,
        "decisive_classification": report.get("classification") in DECISIVE,
        "classification_preserved": report.get("classification") == report.get("probe_classification"),
        "first_evidence": isinstance((report.get("append_evidence") or {}).get("first_append"), dict),
        "track26": (report.get("append_evidence") or {}).get("track_provisioning", {}).get("final_video_track_count", 0) >= 26,
        "timeline_deleted": cleanup.get("disposable_timeline_deleted") is True,
        "previous_restored": cleanup.get("previous_current_timeline_restored") is True,
        "protected_unchanged": cleanup.get("protected_timelines_unchanged") is True,
        "media_cleanup": (cleanup.get("media_delete") or {}).get("ok") is True,
        "cleanup_safe": cleanup.get("safe") is True,
        "no_project_save": report.get("save_project_count") == 0,
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    return {
        "ok": not failures,
        "task_id": TASK_ID,
        "run_id": run_id,
        "classification": report.get("classification"),
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = validate(args.root, args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
