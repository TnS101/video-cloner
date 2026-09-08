#!/usr/bin/env python3
"""Validate one completed group-02 vertical-motion polish run."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3E_GROUP02_VERTICAL_MOTION_POLISH_V1"
MODE = "STEP_3E_GROUP02_VERTICAL_MOTION_POLISH"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_v1"
EXPECTED = {
    "polished_instance_count": 2,
    "unchanged_item_count": 115,
    "final_textplus_count": 117,
}
REQUIRED_ARTIFACTS = (
    "source_contract_verification.json",
    "polish_plan.json",
    "polish_preflight.json",
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
            raise TimeoutError(f"terminal_command:{run_id}")
        time.sleep(poll_seconds)


def validate(root: Path, run_id: str, timeout_seconds: float, poll_seconds: float) -> Dict[str, Any]:
    root = root.resolve()
    state, command_path = wait_for_terminal(root, run_id, timeout_seconds, poll_seconds)
    command = load_json(command_path)
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
        raise ValueError("command_identity")
    report_dir = root / str(command.get("artifacts_dir") or "").replace("\\", "/")
    if not report_dir.is_dir():
        raise ValueError("report_dir")
    missing = [name for name in REQUIRED_ARTIFACTS if not (report_dir / name).is_file()]
    if missing:
        raise ValueError("runtime_artifacts_missing:" + ",".join(missing))

    report = load_json(report_dir / "report.json")
    status = load_json(report_dir / "status.json")
    plan = load_json(report_dir / "polish_plan.json")
    preflight = load_json(report_dir / "polish_preflight.json")
    append = load_json(report_dir / "polish_carrier_append.json")
    application = load_json(report_dir / "polish_application.json")
    readback = load_json(report_dir / "polish_readback_before_save.json")
    persistent = load_json(report_dir / "persistent_readback.json")

    plans = plan.get("plans") if isinstance(plan.get("plans"), list) else []
    position_policy_ok = True
    for row in plans:
        keys = row.get("position_keys") if isinstance(row.get("position_keys"), list) else []
        xs = [float(key["source_top_origin_value"][0]) for key in keys]
        ys = [float(key["source_top_origin_value"][1]) for key in keys]
        position_policy_ok = position_policy_ok and bool(xs) and max(xs) - min(xs) <= 1e-9
        position_policy_ok = position_policy_ok and all(later >= earlier for earlier, later in zip(ys, ys[1:]))

    checks = {
        "command_completed": state == "completed",
        "status_terminal_ok": status.get("run_id") == run_id and status.get("ok") is True and status.get("running") is False and bool(status.get("finished_at")),
        "report_ok": report.get("ok") is True and report.get("run_id") == run_id,
        "target_retained": report.get("target_timeline_kept") is True and report.get("target_timeline_name") == TARGET_TIMELINE_NAME,
        "source_unchanged": report.get("source_timeline_unchanged") is True,
        "accepted_state_unchanged": report.get("accepted_state_unchanged") is True,
        "save_exactly_once": report.get("save_call_count") == 1,
        "font_polish_deferred": report.get("font_polish_deferred") is True,
        "full_rollout_not_authorized": report.get("full_rollout_authorized") is False,
        "plan_ok": plan.get("ok") is True and len(plans) == 2,
        "top_to_bottom_policy": position_policy_ok,
        "preflight_ok": preflight.get("ok") is True and preflight.get("source_total_textplus_count") == 117 and preflight.get("source_v2_item_count") == 0,
        "append_ok": append.get("ok") is True and append.get("requested_count") == 2 and append.get("assigned_count") == 2,
        "application_ok": application.get("ok") is True and application.get("complete") is True and application.get("instance_count") == 2,
        "readback_ok": readback.get("ok") is True and all(readback.get("checks", {}).values()),
        "persistent_ok": persistent.get("ok") is True and all(persistent.get("checks", {}).values()),
        "visual_approval_required": persistent.get("visual_approval_required") is True,
    }
    for key, expected in EXPECTED.items():
        checks[f"report_{key}"] = report.get(key) == expected

    validation = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_state": state,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "group_id": "vf_group_02_already_decorated",
        "checks": checks,
        "counts": EXPECTED,
        "known_remaining_visual_risks": plan.get("known_remaining_visual_risks"),
        "visual_approval_required": True,
        "full_rollout_authorized": False,
        "ok": all(checks.values()),
    }
    write_json(report_dir / "polish_validation.json", validation)
    if not validation["ok"]:
        failures = [key for key, value in checks.items() if not value]
        raise ValueError("validation_failed:" + ",".join(failures))
    return validation


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
