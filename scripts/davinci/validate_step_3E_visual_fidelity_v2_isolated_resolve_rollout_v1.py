#!/usr/bin/env python3
"""Validate one completed isolated Visual Fidelity V2 Resolve rollout run."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_ISOLATED_RESOLVE_ROLLOUT_V1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_visual_fidelity_v2_v1"
AUTHORITY = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1/visual_fidelity_v2_resolve_rollout_authority_v1.json")
EXPECTED_RECREATE = 87
EXPECTED_PRESERVE = 9
EXPECTED_QUARANTINE = 1
EXPECTED_PROTECTED = 17
EXPECTED_PROTECTED_EXITS = 3
EXPECTED_STRUCTURAL = 96
EXPECTED_PHYSICAL = 113
EXPECTED_OCCLUSION_SPANS = 1


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def locate(root: Path, run_id: str, timeout: float, poll: float) -> tuple[str, Path]:
    queue = root / ".agent" / "commands"
    deadline = time.time() + timeout
    while time.time() <= deadline:
        for state in ("completed", "failed", "running", "pending"):
            folder = queue / state
            matches = list(folder.glob(f"{TASK_ID}_{run_id}.json")) if folder.is_dir() else []
            if matches:
                return state, matches[0]
        time.sleep(poll)
    raise ValueError("command_not_found")


def all_true(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value) and all(item is True for item in value.values())


def validate(root: Path, run_id: str, timeout: float, poll: float) -> dict[str, Any]:
    root = root.resolve()
    state, command_path = locate(root, run_id, timeout, poll)
    command = load(command_path)
    if state != "completed":
        raise ValueError(f"command_state:{state}")

    report_dir = root / Path(str(command.get("artifacts_dir") or "").replace("\\", "/"))
    report = load(report_dir / "report.json")
    preflight = load(report_dir / "rollout_preflight.json")
    application = load(report_dir / "rollout_application.json")
    readback = load(report_dir / "rollout_readback_before_save.json")
    persistent = load(report_dir / "persistent_readback.json")
    source_contract = load(report_dir / "source_contract_verification.json")
    authority = load(root / AUTHORITY)
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    rollout = command.get("rollout") if isinstance(command.get("rollout"), Mapping) else {}

    recreate_rows = persistent.get("rows") if isinstance(persistent.get("rows"), list) else []
    protected_scope = persistent.get("protected_scope_rows") if isinstance(persistent.get("protected_scope_rows"), list) else []
    protected_exits = persistent.get("protected_exit_rows") if isinstance(persistent.get("protected_exit_rows"), list) else []
    occlusion = persistent.get("occlusion") if isinstance(persistent.get("occlusion"), Mapping) else {}
    occ_rows = occlusion.get("rows") if isinstance(occlusion.get("rows"), list) else []
    occ_row = occ_rows[0] if len(occ_rows) == 1 and isinstance(occ_rows[0], Mapping) else {}
    max_caption_track = int(occlusion.get("max_caption_track") or 0)

    protected_updated = [row for row in protected_scope if isinstance(row, Mapping) and row.get("updated_center_frames")]
    protected_static = [row for row in protected_scope if isinstance(row, Mapping) and not row.get("updated_center_frames")]

    checks = {
        "command_identity": command.get("task_id") == TASK_ID and command.get("run_id") == run_id,
        "command_scope": rollout.get("recreate_total") == EXPECTED_RECREATE and rollout.get("preserved_unresolved") == EXPECTED_PRESERVE and rollout.get("quarantined_remove") == EXPECTED_QUARANTINE and rollout.get("protected_exit_updates") == EXPECTED_PROTECTED_EXITS and rollout.get("expected_physical_textplus_count") == EXPECTED_PHYSICAL,
        "command_policy": rollout.get("foreground_rgba_above_textplus") is True and rollout.get("transcript_timing_authority") is False and rollout.get("fade_polish_deferred") is True and rollout.get("visual_approval_required") is True and rollout.get("user_authorized_this_isolated_rollout") is True,
        "authority_ok": authority.get("ok") is True and summary.get("recreate_total") == EXPECTED_RECREATE and summary.get("preserved_unresolved") == EXPECTED_PRESERVE and summary.get("quarantined_remove") == EXPECTED_QUARANTINE and summary.get("protected_total") == EXPECTED_PROTECTED and summary.get("protected_exit_updates") == EXPECTED_PROTECTED_EXITS and summary.get("target_physical_textplus") == EXPECTED_PHYSICAL and summary.get("occlusion_span_count") == EXPECTED_OCCLUSION_SPANS,
        "source_contract_present": bool(source_contract),
        "preflight_ok": preflight.get("ok") is True and preflight.get("source_structural_count") == 97 and preflight.get("source_protected_count") == EXPECTED_PROTECTED and len(preflight.get("exports") or []) == EXPECTED_RECREATE and all(row.get("ok") is True for row in preflight.get("exports") or []),
        "application_ok": application.get("ok") is True and all_true(application.get("checks")) and len(application.get("application_rows") or []) == EXPECTED_RECREATE and all(row.get("ok") is True for row in application.get("application_rows") or []) and len(application.get("protected_exit_rows") or []) == EXPECTED_PROTECTED_EXITS and len(application.get("protected_scope_rows") or []) == EXPECTED_PROTECTED,
        "readback_ok": readback.get("ok") is True and all_true(readback.get("checks")) and len(readback.get("rows") or []) == EXPECTED_RECREATE and all(row.get("ok") is True for row in readback.get("rows") or []) and len(readback.get("protected_scope_rows") or []) == EXPECTED_PROTECTED and all(row.get("ok") is True for row in readback.get("protected_scope_rows") or []),
        "persistent_ok": persistent.get("ok") is True and all_true(persistent.get("checks")) and len(recreate_rows) == EXPECTED_RECREATE and all(row.get("ok") is True for row in recreate_rows),
        "protected_scope_exact": len(protected_scope) == EXPECTED_PROTECTED and len(protected_updated) == EXPECTED_PROTECTED_EXITS and len(protected_static) == EXPECTED_PROTECTED - EXPECTED_PROTECTED_EXITS and all(row.get("ok") is True for row in protected_scope),
        "protected_exit_exact": len(protected_exits) == EXPECTED_PROTECTED_EXITS and all(row.get("ok") is True for row in protected_exits),
        "occlusion_exact": occlusion.get("ok") is True and occlusion.get("required_layer_order") == "foreground_rgba_above_textplus" and len(occ_rows) == 1 and int(occ_row.get("track_index") or 0) > max_caption_track and int(occ_row.get("duration") or -1) == 5,
        "report_ok": report.get("ok") is True and report.get("run_id") == run_id and not report.get("failures"),
        "report_counts": report.get("recreated_count") == EXPECTED_RECREATE and report.get("preserved_unresolved_count") == EXPECTED_PRESERVE and report.get("quarantine_removed_count") == EXPECTED_QUARANTINE and report.get("protected_exit_update_count") == EXPECTED_PROTECTED_EXITS and report.get("final_textplus_count") == EXPECTED_PHYSICAL and report.get("v2_item_count") == 0 and report.get("save_call_count") == 1,
        "report_isolation": report.get("source_timeline_unchanged") is True and report.get("accepted_state_unchanged") is True and report.get("target_timeline_kept") is True,
        "report_policy": report.get("occlusion_above_textplus") is True and report.get("visual_approval_required") is True and report.get("fade_polish_deferred") is True and report.get("further_rollout_authorized") is False,
    }

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_state": state,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "checks": checks,
        "counts": {
            "recreated": EXPECTED_RECREATE,
            "preserved_unresolved": EXPECTED_PRESERVE,
            "quarantined_removed": EXPECTED_QUARANTINE,
            "protected_total": EXPECTED_PROTECTED,
            "protected_exit_updates": EXPECTED_PROTECTED_EXITS,
            "structural_textplus": EXPECTED_STRUCTURAL,
            "physical_textplus": EXPECTED_PHYSICAL,
            "v2_items": 0,
            "occlusion_spans": EXPECTED_OCCLUSION_SPANS,
        },
        "occlusion_target_track": int(occ_row.get("track_index") or 0),
        "max_caption_track": max_caption_track,
        "visual_approval_required": True,
        "fade_polish_deferred": True,
        "further_rollout_authorized": False,
        "ok": all(checks.values()),
    }
    write(report_dir / "visual_fidelity_v2_isolated_resolve_rollout_validation.json", result)
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
