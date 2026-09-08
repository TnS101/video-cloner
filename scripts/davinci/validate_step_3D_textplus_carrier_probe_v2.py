"""Wait for and validate one corrected Step 3D TextPlus carrier probe."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_TEXTPLUS_CARRIER_PROBE_V2"
MODE = "STEP_3D_TEXTPLUS_CARRIER_PROBE_V2"
REQUIRED_SUCCESS_ARTIFACTS = (
    "source_contract_verification.json",
    "probe_preflight.json",
    "duplicate_timeline_setup.json",
    "probe_provisioning.json",
    "probe_creation.json",
    "probe_persistent_readback.json",
    "probe_cleanup.json",
    "probe_result.json",
    "report.json",
    "status.json",
    "run.log",
)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def command_name(run_id: str) -> str:
    return f"{TASK_ID}_{run_id}.json"


def locate_command(root: Path, run_id: str) -> Tuple[Optional[str], Optional[Path]]:
    name = command_name(run_id)
    queue = root / ".agent" / "commands"
    found = []
    for state in ("pending", "running", "completed", "failed"):
        path = queue / state / name
        if path.is_file():
            found.append((state, path))
    if len(found) > 1:
        raise ValueError("command_multiple_states")
    return found[0] if found else (None, None)


def wait_for_terminal(
    root: Path,
    run_id: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> Tuple[str, Path, Dict[str, Any]]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    observations = []
    while True:
        state, path = locate_command(root, run_id)
        observations.append(
            {"state": state, "path": str(path) if path else None}
        )
        if state in {"completed", "failed"} and path is not None:
            return state, path, {
                "observations": observations,
                "timed_out": False,
            }
        if time.monotonic() >= deadline:
            raise TimeoutError(f"command_not_terminal:{state}")
        time.sleep(max(0.05, poll_seconds))


def report_markdown(validation: Dict[str, Any]) -> str:
    outcome = "PASS" if validation.get("ok") else "FAIL"
    lines = [
        f"# {TASK_ID}",
        "",
        f"## Result\n\n{outcome}",
        "",
        "## Evidence",
        "",
        f"- Run ID: `{validation.get('run_id')}`",
        f"- Command state: `{validation.get('command_state')}`",
        f"- Backend: `{validation.get('carrier_backend')}`",
        f"- Edit page active: `{validation.get('edit_page_active')}`",
        f"- Production call returned item: "
        f"`{validation.get('production_call_returned_item')}`",
        f"- New item count: `{validation.get('new_item_count')}`",
        f"- Text readback: `{validation.get('text_readback_ok')}`",
        f"- Modifier connected: `{validation.get('modifier_connected')}`",
        f"- Frame 0 keyframe: `{validation.get('frame_0_readback_ok')}`",
        f"- Frame 3 keyframe: `{validation.get('frame_3_readback_ok')}`",
        f"- Duplicate deleted: `{validation.get('temporary_timeline_deleted')}`",
        f"- Original timeline restored: "
        f"`{validation.get('original_timeline_restored')}`",
        f"- Original page restored: "
        f"`{validation.get('original_page_restored')}`",
        f"- Protected source unchanged: "
        f"`{validation.get('protected_source_unchanged')}`",
        f"- Accepted state unchanged: "
        f"`{validation.get('accepted_state_unchanged')}`",
        f"- Save calls: `{validation.get('save_call_count')}`",
    ]
    if validation.get("failures"):
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- `{value}`" for value in validation["failures"])
    return "\n".join(lines) + "\n"


def validate(
    root: Path,
    run_id: str,
    timeout_seconds: float = 900.0,
    poll_seconds: float = 1.0,
) -> Dict[str, Any]:
    root = root.resolve()
    report_dir = root / ".agent" / "reports" / TASK_ID / run_id
    if not report_dir.is_dir():
        raise ValueError("report_dir")

    receipt_path = report_dir / "publication_receipt.json"
    command_copy_path = report_dir / "probe_command.json"
    if not receipt_path.is_file() or not command_copy_path.is_file():
        raise ValueError("publication_evidence")
    receipt = load_json(receipt_path)
    command_copy = load_json(command_copy_path)
    if receipt.get("run_id") != run_id or command_copy.get("run_id") != run_id:
        raise ValueError("run_id")
    if command_copy.get("task_id") != TASK_ID:
        raise ValueError("task_id")
    if command_copy.get("mode") != MODE:
        raise ValueError("mode")

    state, command_path, wait_evidence = wait_for_terminal(
        root,
        run_id,
        timeout_seconds,
        poll_seconds,
    )
    if raw_sha256(command_path) != receipt.get("command_sha256"):
        raise ValueError("command_sha256")

    report_path = report_dir / "report.json"
    status_path = report_dir / "status.json"
    if not report_path.is_file() or not status_path.is_file():
        raise ValueError("terminal_report_missing")
    runtime_report = load_json(report_path)
    status = load_json(status_path)

    failures = []
    if state != "completed":
        failures.append(f"command_state:{state}")
    if status.get("running") is not False:
        failures.append("status_running")
    if not runtime_report.get("ok"):
        runtime_failures = runtime_report.get("failures")
        if isinstance(runtime_failures, list) and runtime_failures:
            failures.extend(f"runtime:{value}" for value in runtime_failures)
        else:
            failures.append("runtime:not_ok")

    if state == "completed" and runtime_report.get("ok"):
        for name in REQUIRED_SUCCESS_ARTIFACTS:
            path = report_dir / name
            if not path.is_file() or path.stat().st_size == 0:
                failures.append(f"artifact:{name}")

    accepted_path = root / ".agent" / "state" / "latest_accepted.json"
    accepted_unchanged = bool(
        accepted_path.is_file()
        and raw_sha256(accepted_path)
        == command_copy.get("accepted_state_sha256")
    )
    provisioning = runtime_report.get("provisioning") or {}
    creation = provisioning.get("creation") or {}
    checks = {
        "task_id": runtime_report.get("task_id") == TASK_ID,
        "mode": runtime_report.get("mode") == MODE,
        "run_id": runtime_report.get("run_id") == run_id,
        "carrier_backend": runtime_report.get("carrier_backend")
        == "fusion_composition_explicit_textplus",
        "source_contract": runtime_report.get(
            "source_contract_verified_count"
        )
        == 5,
        "edit_page_active": runtime_report.get("edit_page_active") is True,
        "protected_caption_count": runtime_report.get(
            "protected_caption_count_before"
        )
        == 116,
        "production_call_returned_item": creation.get(
            "returned_truthy"
        )
        is True,
        "new_item_count": creation.get("new_item_count") == 1,
        "text_readback": runtime_report.get("text_readback_ok") is True,
        "modifier_connected": runtime_report.get("modifier_connected")
        is True,
        "frame_0_readback": runtime_report.get("frame_0_readback_ok")
        is True,
        "frame_3_readback": runtime_report.get("frame_3_readback_ok")
        is True,
        "temporary_timeline_deleted": runtime_report.get(
            "temporary_timeline_deleted"
        )
        is True,
        "original_timeline_restored": runtime_report.get(
            "original_timeline_restored"
        )
        is True,
        "original_page_restored": runtime_report.get(
            "original_page_restored"
        )
        is True,
        "protected_source_unchanged": runtime_report.get(
            "protected_source_unchanged"
        )
        is True,
        "accepted_state_runtime": runtime_report.get(
            "accepted_state_unchanged"
        )
        is True,
        "accepted_state_disk": accepted_unchanged,
        "save_call_count": runtime_report.get("save_call_count") == 2,
    }
    for name, ok in checks.items():
        if not ok:
            failures.append(f"check:{name}")

    validation = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "ok": not failures,
        "command_state": state,
        "command_path": str(command_path),
        "wait": wait_evidence,
        "checks": checks,
        "failures": failures,
        "carrier_backend": runtime_report.get("carrier_backend"),
        "edit_page_active": runtime_report.get("edit_page_active"),
        "production_call_returned_item": creation.get("returned_truthy"),
        "new_item_count": creation.get("new_item_count"),
        "text_readback_ok": runtime_report.get("text_readback_ok"),
        "modifier_connected": runtime_report.get("modifier_connected"),
        "frame_0_readback_ok": runtime_report.get(
            "frame_0_readback_ok"
        ),
        "frame_3_readback_ok": runtime_report.get(
            "frame_3_readback_ok"
        ),
        "temporary_timeline_deleted": runtime_report.get(
            "temporary_timeline_deleted"
        ),
        "original_timeline_restored": runtime_report.get(
            "original_timeline_restored"
        ),
        "original_page_restored": runtime_report.get(
            "original_page_restored"
        ),
        "protected_source_unchanged": runtime_report.get(
            "protected_source_unchanged"
        ),
        "accepted_state_unchanged": accepted_unchanged,
        "save_call_count": runtime_report.get("save_call_count"),
        "runtime_report": runtime_report,
    }
    write_json(report_dir / "probe_validation.json", validation)
    write_text(
        report_dir / "FINAL_REPORT.md",
        report_markdown(validation),
    )
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    result = validate(
        Path(args.root),
        args.run_id,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
