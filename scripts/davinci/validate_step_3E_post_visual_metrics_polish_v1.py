#!/usr/bin/env python3
"""Validate one completed isolated post-visual metrics polish run."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
AUTHORITY = Path("artifacts/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/post_visual_metrics_polish_v1.json")
EXPECTED_PHYSICAL = 114


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
            directory = queue / state
            matches = list(directory.glob(f"{TASK_ID}_{run_id}.json")) if directory.is_dir() else []
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
    preflight = load(report_dir / "metrics_preflight.json")
    application = load(report_dir / "metrics_application.json")
    readback = load(report_dir / "metrics_readback_before_save.json")
    persistent = load(report_dir / "persistent_readback.json")
    authority = load(root / AUTHORITY)
    summary = authority.get("summary") or {}
    expected_size = int(summary.get("protected_size_updates") or 0) + int(summary.get("repair_size_updates") or 0)
    expected_text = int(summary.get("protected_text_updates") or 0)
    polish = command.get("polish") or {}
    checks = {
        "command_identity": command.get("task_id") == TASK_ID and command.get("run_id") == run_id,
        "command_scope": polish.get("size_update_count") == expected_size and polish.get("text_update_count") == expected_text and polish.get("position_updates") == 0 and polish.get("opacity_updates") == 0 and polish.get("expected_physical_textplus_count") == EXPECTED_PHYSICAL,
        "command_policy": polish.get("fade_appearance_reassessment_deferred_until_baked_original_is_removed") is True and polish.get("visual_approval_required") is True,
        "report_ok": report.get("ok") is True and report.get("run_id") == run_id and not report.get("failures"),
        "report_counts": report.get("size_update_count") == expected_size and report.get("text_update_count") == expected_text and report.get("position_updates") == 0 and report.get("opacity_updates") == 0 and report.get("final_textplus_count") == EXPECTED_PHYSICAL and report.get("save_call_count") == 1,
        "report_policy": report.get("source_timeline_unchanged") is True and report.get("accepted_state_unchanged") is True and report.get("target_timeline_kept") is True and report.get("visual_approval_required") is True and report.get("further_rollout_authorized") is False,
        "preflight": preflight.get("ok") is True and preflight.get("size_update_count") == expected_size and preflight.get("text_update_count") == expected_text and preflight.get("position_updates") == 0 and preflight.get("opacity_updates") == 0,
        "application": application.get("ok") is True and len(application.get("rows") or []) == len(preflight.get("mutation_names") or []) and all(row.get("ok") for row in application.get("rows") or []),
        "readback": readback.get("ok") is True and all(row.get("ok") for row in readback.get("rows") or []),
        "persistent": persistent.get("ok") is True and persistent.get("size_update_count") == expected_size and persistent.get("text_update_count") == expected_text and persistent.get("position_update_count") == 0 and persistent.get("opacity_update_count") == 0 and persistent.get("expected_physical_textplus_count") == EXPECTED_PHYSICAL and all((persistent.get("checks") or {}).values()) and all(row.get("ok") for row in persistent.get("rows") or []),
        "preserved_position_opacity": all((row.get("preserved") or {}).get("center") is True and (row.get("preserved") or {}).get("opacity1") is True for row in persistent.get("rows") or []),
        "authority_policy": authority.get("policy", {}).get("transcript_timing_authority") is False and authority.get("policy", {}).get("per_cue_hardcoded_overrides") is False and authority.get("policy", {}).get("position_mutation_authorized") is False and authority.get("policy", {}).get("opacity_mutation_authorized") is False,
    }
    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_state": state,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "checks": checks,
        "counts": {"size_updates": expected_size, "text_updates": expected_text, "physical_textplus_count": EXPECTED_PHYSICAL, "position_updates": 0, "opacity_updates": 0},
        "visual_approval_required": True,
        "fade_appearance_reassessment_deferred_until_baked_original_is_removed": True,
        "further_rollout_authorized": False,
        "ok": all(checks.values()),
    }
    write(report_dir / "post_visual_metrics_polish_validation.json", result)
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
