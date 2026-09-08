#!/usr/bin/env python3
"""Validate one completed confirmed-74 isolated repair rollout run."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT_V1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_v1"
AUTHORITY = Path("artifacts/DZSQH7AUHJT_STEP_3E_CONFIRMED74_REPAIR_AUTHORITY_V1/confirmed74_repair_authority_v1.json")
EXPECTED_REPAIR = 74
EXPECTED_UNRESOLVED = 23
EXPECTED_COMPOSITE_REMOVED = 3
EXPECTED_PROTECTED = 17
EXPECTED_PHYSICAL_TEXTPLUS = 114
EXPECTED_BATCHES = 13


def load(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def locate(root: Path, run_id: str, timeout: float, poll: float):
    queue = root / ".agent" / "commands"
    deadline = time.time() + timeout
    while time.time() <= deadline:
        for state in ("completed", "failed", "running", "pending"):
            matches = list((queue / state).glob(f"{TASK_ID}_{run_id}.json")) if (queue / state).is_dir() else []
            if matches:
                return state, matches[0]
        time.sleep(poll)
    raise ValueError("command_not_found")


def validate(root: Path, run_id: str, timeout: float, poll: float) -> Dict[str, Any]:
    root = root.resolve()
    state, command_path = locate(root, run_id, timeout, poll)
    command = load(command_path)
    if state != "completed":
        raise ValueError(f"command_state:{state}")
    report_dir = root / Path(str(command["artifacts_dir"]).replace("\\", "/"))
    report = load(report_dir / "report.json")
    plan = load(report_dir / "rollout_plan.json")
    setup = load(report_dir / "rollout_timeline_setup.json")
    exports = load(report_dir / "source_comp_exports.json")
    append = load(report_dir / "rollout_carrier_append.json")
    application = load(report_dir / "rollout_application.json")
    readback = load(report_dir / "rollout_readback_before_save.json")
    persistent = load(report_dir / "persistent_readback.json")
    authority = load(root / AUTHORITY)
    summary = authority.get("summary") or {}
    explicit_rows = int(summary.get("explicit_repair_frame_rows") or 0)
    fill_overrides = int(summary.get("fill_override_instances") or 0)

    rollout = command.get("rollout") or {}
    checks = {
        "command_identity": command.get("task_id") == TASK_ID and command.get("run_id") == run_id and rollout.get("user_authorized_this_rollout") is True,
        "command_scope": rollout.get("repair_instance_count") == EXPECTED_REPAIR and rollout.get("unresolved_preserved_count") == EXPECTED_UNRESOLVED and rollout.get("composite_structural_removed_count") == EXPECTED_COMPOSITE_REMOVED and rollout.get("protected_v4_count") == EXPECTED_PROTECTED and rollout.get("expected_physical_textplus_count") == EXPECTED_PHYSICAL_TEXTPLUS,
        "command_policy": rollout.get("transcript_timing_authority") is False and rollout.get("unresolved_repair_authorized") is False and rollout.get("composite_structural_recreation_authorized") is False and rollout.get("fade_polish_deferred") is True,
        "report_ok": report.get("ok") is True and report.get("run_id") == run_id and not report.get("failures"),
        "report_counts": report.get("repair_instance_count") == EXPECTED_REPAIR and report.get("unresolved_preserved_count") == EXPECTED_UNRESOLVED and report.get("composite_structural_removed_count") == EXPECTED_COMPOSITE_REMOVED and report.get("protected_v4_count") == EXPECTED_PROTECTED and report.get("explicit_frame_row_count") == explicit_rows and report.get("final_textplus_count") == EXPECTED_PHYSICAL_TEXTPLUS and report.get("save_call_count") == 1,
        "report_policy": report.get("source_timeline_unchanged") is True and report.get("accepted_state_unchanged") is True and report.get("target_timeline_kept") is True and report.get("confirmed74_repair_rollout_completed") is True and report.get("visual_approval_required") is True and report.get("fade_polish_deferred") is True and report.get("further_rollout_authorized") is False,
        "plan_ok": plan.get("ok") is True and plan.get("repair_instance_count") == EXPECTED_REPAIR and plan.get("unresolved_preserved_count") == EXPECTED_UNRESOLVED and plan.get("composite_structural_removed_count") == EXPECTED_COMPOSITE_REMOVED and plan.get("protected_v4_count") == EXPECTED_PROTECTED and plan.get("explicit_frame_row_count") == explicit_rows and plan.get("expected_physical_textplus_count") == EXPECTED_PHYSICAL_TEXTPLUS and len(plan.get("plans") or []) == EXPECTED_REPAIR,
        "plan_policy": plan.get("transcript_timing_authority") is False and plan.get("fade_polish_deferred") is True and all(row.get("transcript_timing_authority") is False for row in plan.get("plans") or []),
        "export_ok": exports.get("ok") is True and exports.get("exported_count") == EXPECTED_REPAIR and len(exports.get("rows") or []) == EXPECTED_REPAIR,
        "setup_ok": setup.get("ok") is True and (setup.get("delete") or {}).get("deleted") == EXPECTED_REPAIR + EXPECTED_COMPOSITE_REMOVED and setup.get("unresolved_after_delete") == EXPECTED_UNRESOLVED and setup.get("composite_structural_removed_count") == EXPECTED_COMPOSITE_REMOVED and len(setup.get("protected_after_delete") or []) == EXPECTED_PROTECTED and all(row.get("ok") for row in setup.get("protected_after_delete") or []),
        "append_ok": append.get("ok") is True and append.get("requested_count") == EXPECTED_REPAIR and append.get("assigned_count") == EXPECTED_REPAIR and append.get("batch_count") == EXPECTED_BATCHES,
        "application_ok": application.get("ok") is True and application.get("complete") is True and application.get("instance_count") == EXPECTED_REPAIR and application.get("explicit_frame_row_count") == explicit_rows and application.get("fill_override_count") == fill_overrides and len(application.get("rows") or []) == EXPECTED_REPAIR and all(row.get("ok") for row in application.get("rows") or []),
        "readback_ok": readback.get("ok") is True and readback.get("explicit_frame_row_count") == explicit_rows and len(readback.get("rows") or []) == EXPECTED_REPAIR and all(row.get("ok") for row in readback.get("rows") or []) and len(readback.get("protected_v4_rows") or []) == EXPECTED_PROTECTED and all(row.get("ok") for row in readback.get("protected_v4_rows") or []) and len(readback.get("unresolved_inventory") or []) == EXPECTED_UNRESOLVED and len(readback.get("composite_removed_target_names") or []) == EXPECTED_COMPOSITE_REMOVED and all((readback.get("checks") or {}).values()),
        "persistent_ok": persistent.get("ok") is True and persistent.get("explicit_frame_row_count") == explicit_rows and len(persistent.get("rows") or []) == EXPECTED_REPAIR and all(row.get("ok") for row in persistent.get("rows") or []) and len(persistent.get("protected_v4_rows") or []) == EXPECTED_PROTECTED and all(row.get("ok") for row in persistent.get("protected_v4_rows") or []) and len(persistent.get("unresolved_inventory") or []) == EXPECTED_UNRESOLVED and len(persistent.get("composite_removed_target_names") or []) == EXPECTED_COMPOSITE_REMOVED and all((persistent.get("checks") or {}).values()),
        "persistent_policy": persistent.get("confirmed74_repair_rollout_completed") is True and persistent.get("visual_approval_required") is True and persistent.get("fade_polish_deferred") is True and persistent.get("further_rollout_authorized") is False,
    }
    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_state": state,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "checks": checks,
        "counts": {
            "repair_instance_count": EXPECTED_REPAIR,
            "unresolved_preserved_count": EXPECTED_UNRESOLVED,
            "composite_structural_removed_count": EXPECTED_COMPOSITE_REMOVED,
            "protected_v4_count": EXPECTED_PROTECTED,
            "physical_textplus_count": EXPECTED_PHYSICAL_TEXTPLUS,
            "explicit_frame_row_count": explicit_rows,
            "fill_override_count": fill_overrides,
        },
        "visual_approval_required": True,
        "fade_polish_deferred": True,
        "further_rollout_authorized": False,
        "ok": all(checks.values()),
    }
    write(report_dir / "confirmed74_isolated_repair_rollout_validation.json", result)
    if not result["ok"]:
        raise ValueError("validation_failed:" + ",".join(key for key, value in checks.items() if not value))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    args = parser.parse_args()
    try:
        result = validate(args.root, args.run_id, args.timeout_seconds, args.poll_seconds)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
