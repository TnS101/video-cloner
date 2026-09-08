#!/usr/bin/env python3
"""Validate one completed Step 3E.3 17-token V4 full-baseline polish run."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1"
MODE = "STEP_3E_FULL_BASELINE_VISUAL_POLISH"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_17tokens_v1"

EXPECTED = {
    "polished_instance_count": 17,
    "unchanged_item_count": 100,
    "final_textplus_count": 117,
    "explicit_frame_row_count": 397,
}
REQUIRED_ARTIFACTS = (
    "source_contract_verification.json",
    "polish_plan.json",
    "polish_preflight.json",
    "polish_timeline_setup.json",
    "polish_carrier_append.json",
    "polish_application.json",
    "polish_readback_before_save.json",
    "persistent_readback.json",
    "report.json",
    "status.json",
)


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def find_command(root: Path, state: str, run_id: str) -> Path | None:
    path = root / ".agent" / "commands" / state / f"{TASK_ID}_{run_id}.json"
    return path if path.is_file() else None


def wait_for_terminal(root: Path, run_id: str, timeout_seconds: float, poll_seconds: float) -> tuple[str, Path]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        for state in ("completed", "failed"):
            path = find_command(root, state, run_id)
            if path is not None:
                return state, path
        if time.monotonic() >= deadline:
            raise TimeoutError("command_not_terminal")
        time.sleep(poll_seconds)


def validate(root: Path, run_id: str, timeout_seconds: float, poll_seconds: float) -> Dict[str, Any]:
    root = root.resolve()
    state, command_path = wait_for_terminal(root, run_id, timeout_seconds, poll_seconds)
    command = load_json(command_path)
    if command.get("mode") != MODE or command.get("run_id") != run_id:
        raise ValueError("command_identity")

    report_dir = root / str(command.get("artifacts_dir") or "").replace("\\", "/")
    missing = [name for name in REQUIRED_ARTIFACTS if not (report_dir / name).is_file()]
    if missing:
        raise ValueError("runtime_artifacts_missing:" + ",".join(missing))

    status = load_json(report_dir / "status.json")
    report = load_json(report_dir / "report.json")
    plan = load_json(report_dir / "polish_plan.json")
    preflight = load_json(report_dir / "polish_preflight.json")
    setup = load_json(report_dir / "polish_timeline_setup.json")
    append = load_json(report_dir / "polish_carrier_append.json")
    application = load_json(report_dir / "polish_application.json")
    readback = load_json(report_dir / "polish_readback_before_save.json")
    persistent = load_json(report_dir / "persistent_readback.json")

    plans = plan.get("plans") if isinstance(plan.get("plans"), list) else []
    pre_source_rows = preflight.get("source_visual_state_rows") if isinstance(preflight.get("source_visual_state_rows"), list) else []
    read_rows = readback.get("rows") if isinstance(readback.get("rows"), list) else []
    persistent_rows = persistent.get("rows") if isinstance(persistent.get("rows"), list) else []

    checks = {
        "command_completed": state == "completed",
        "status_terminal_ok": (
            status.get("run_id") == run_id
            and status.get("ok") is True
            and status.get("running") is False
            and bool(status.get("finished_at"))
        ),
        "report_ok": report.get("ok") is True and report.get("run_id") == run_id,
        "target_retained": (
            report.get("target_timeline_kept") is True
            and report.get("target_timeline_name") == TARGET_TIMELINE_NAME
        ),
        "source_unchanged": report.get("source_timeline_unchanged") is True,
        "accepted_state_unchanged": report.get("accepted_state_unchanged") is True,
        "save_exactly_once": report.get("save_call_count") == 1,
        "visual_approval_required": report.get("visual_approval_required") is True,
        "remaining_rollout_locked": (
            report.get("remaining_caption_rollout_authorized") is False
            and report.get("full_rollout_authorized") is False
        ),
        "plan_ok": (
            plan.get("ok") is True
            and plan.get("group_count") == 7
            and plan.get("visual_token_count") == 17
            and plan.get("explicit_frame_row_count") == 397
            and plan.get("transcript_timing_authority") is False
            and len(plans) == 17
        ),
        "plan_frames_exact": sum(len(row.get("position_keys") or []) for row in plans if isinstance(row, dict)) == 397,
        "preflight_ok": (
            preflight.get("ok") is True
            and preflight.get("source_v6_textplus_count") == 100
            and preflight.get("source_visual_first_count") == 17
            and preflight.get("source_total_textplus_count") == 117
            and preflight.get("source_v2_item_count") == 0
            and preflight.get("source_visual_state_exact") is True
            and len(pre_source_rows) == 17
            and all(row.get("ok") for row in pre_source_rows)
        ),
        "setup_ok": (
            setup.get("ok") is True
            and setup.get("duplicate_inventory_exact") is True
            and setup.get("unrelated_inventory_after_delete_exact") is True
            and (setup.get("visual_first_delete") or {}).get("deleted") == 17
        ),
        "append_ok": (
            append.get("ok") is True
            and append.get("batch_count") == 3
            and append.get("requested_count") == 17
            and append.get("assigned_count") == 17
        ),
        "application_ok": (
            application.get("ok") is True
            and application.get("complete") is True
            and application.get("instance_count") == 17
            and application.get("explicit_frame_row_count") == 397
        ),
        "readback_ok": (
            readback.get("ok") is True
            and readback.get("explicit_frame_row_count") == 397
            and len(read_rows) == 17
            and all(row.get("ok") for row in read_rows)
            and all((readback.get("checks") or {}).values())
        ),
        "persistent_ok": (
            persistent.get("ok") is True
            and persistent.get("explicit_frame_row_count") == 397
            and len(persistent_rows) == 17
            and all(row.get("ok") for row in persistent_rows)
            and all((persistent.get("checks") or {}).values())
        ),
        "persistent_rollout_locked": (
            persistent.get("visual_approval_required") is True
            and persistent.get("remaining_caption_rollout_authorized") is False
            and persistent.get("full_rollout_authorized") is False
        ),
    }
    for key, value in EXPECTED.items():
        checks[f"report_{key}"] = report.get(key) == value

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_state": state,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "checks": checks,
        "counts": EXPECTED,
        "visual_approval_required": True,
        "remaining_caption_rollout_authorized": False,
        "full_rollout_authorized": False,
        "ok": all(checks.values()),
    }
    write_json(report_dir / "full_baseline_visual_polish_validation.json", result)
    if not result["ok"]:
        raise ValueError("validation_failed:" + ",".join(key for key, value in checks.items() if not value))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    args = parser.parse_args()
    try:
        result = validate(args.root, args.run_id, args.timeout_seconds, args.poll_seconds)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
