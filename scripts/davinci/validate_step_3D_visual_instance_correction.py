"""Validate the single-run visual-instance correction proof."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_INSTANCE_CORRECTION_V3"
MODE = "STEP_3D_VISUAL_INSTANCE_CORRECTION"
REQUIRED_SUCCESS_ARTIFACTS = (
    "source_contract_verification.json",
    "visual_instance_plan.json",
    "probe_preflight.json",
    "source_comp_exports.json",
    "duplicate_timeline_setup.json",
    "carrier_append.json",
    "correction_application.json",
    "persistent_readback.json",
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
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
    found = []
    for state in ("pending", "running", "completed", "failed"):
        path = root / ".agent" / "commands" / state / name
        if path.is_file():
            found.append((state, path))
    if len(found) > 1:
        raise ValueError("command_multiple_states")
    return found[0] if found else (None, None)


def wait_for_terminal(root: Path, run_id: str, timeout_seconds: float, poll_seconds: float) -> Tuple[str, Path, Dict[str, Any]]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    observations = []
    while True:
        state, path = locate_command(root, run_id)
        observations.append({"state": state, "path": str(path) if path else None})
        if state in {"completed", "failed"} and path is not None:
            return state, path, {"observations": observations, "timed_out": False}
        if time.monotonic() >= deadline:
            raise TimeoutError(f"command_not_terminal:{state}")
        time.sleep(max(0.1, poll_seconds))


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
        f"- Backend: `{validation.get('backend')}`",
        f"- Probe timeline: `{validation.get('probe_timeline_name')}`",
        f"- Append returned/detected: `{validation.get('append_returned_count')} / {validation.get('append_detected_count')}`",
        f"- Imported Fusion comps: `{validation.get('comp_clone_count')}`",
        f"- Visual aliases merged: `{validation.get('visual_instance_source_cue_ids')}`",
        f"- Style source: `{validation.get('visual_instance_style_source_cue_id')}`",
        f"- Relative layout verified: `{validation.get('relative_layout_verified')}`",
        f"- COME exit verified: `{validation.get('come_exit_verified')}`",
        f"- COME source-frame style verified: `{validation.get('come_style_verified')}`",
        f"- `they` shimmer stabilized: `{validation.get('they_shimmer_stabilized')}`",
        f"- Protected source unchanged: `{validation.get('source_timeline_unchanged')}`",
        f"- Accepted state unchanged: `{validation.get('accepted_state_unchanged')}`",
        f"- Save calls: `{validation.get('save_call_count')}`",
        f"- Visual review required: `{validation.get('visual_review_required')}`",
    ]
    if validation.get("failures"):
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- `{failure}`" for failure in validation["failures"])
    if validation.get("ok"):
        lines.extend([
            "",
            "## Manual visual review",
            "",
            f"Open `{validation.get('probe_timeline_name')}` and review frames 428-452.",
            "Confirm reconstructed lower-case `they` stays stable above `COME` without shimmer.",
            "Confirm `COME` matches the baked dark-gray glyph size/color with no outline.",
            "Confirm `COME` holds, rolls right, and decays over frames 448-451.",
        ])
    return "\n".join(lines) + "\n"


def validate(root: Path, run_id: str, timeout_seconds: float = 1800.0, poll_seconds: float = 1.0) -> Dict[str, Any]:
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
    if command_copy.get("task_id") != TASK_ID or command_copy.get("mode") != MODE:
        raise ValueError("command_identity")

    state, command_path, wait_evidence = wait_for_terminal(root, run_id, timeout_seconds, poll_seconds)
    command = load_json(command_path)
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
            failures.append(f"runtime:{runtime_report.get('error') or 'not_ok'}")

    if state == "completed" and runtime_report.get("ok"):
        for name in REQUIRED_SUCCESS_ARTIFACTS:
            path = report_dir / name
            if not path.is_file() or path.stat().st_size == 0:
                failures.append(f"artifact:{name}")

    accepted_path = root / ".agent" / "state" / "latest_accepted.json"
    accepted_unchanged = accepted_path.is_file() and raw_sha256(accepted_path) == command.get("accepted_state_sha256")
    checks = {
        "task_id": runtime_report.get("task_id") == TASK_ID,
        "mode": runtime_report.get("mode") == MODE,
        "backend": runtime_report.get("backend") == "media_pool_append_plus_import_fusion_comp_style_stabilization",
        "run_id": runtime_report.get("run_id") == run_id,
        "source_contract": runtime_report.get("source_contract_verified_count") == 7,
        "source_comp_exports": runtime_report.get("source_comp_export_count") == 2,
        "append_returned": runtime_report.get("append_returned_count") == 2,
        "carrier_appends": runtime_report.get("carrier_append_count") == 2,
        "comp_clones": runtime_report.get("comp_clone_count") == 2,
        "persistent_targets": runtime_report.get("target_readback_count") == 2,
        "merged_aliases": runtime_report.get("visual_instance_source_cue_ids") == ["sub_051", "sub_054"],
        "style_source": runtime_report.get("visual_instance_style_source_cue_id") == "sub_051",
        "visual_window": runtime_report.get("visual_instance_window") == [428, 452],
        "relative_layout": runtime_report.get("relative_layout_verified") is True,
        "come_exit": runtime_report.get("come_exit_verified") is True,
        "come_style": runtime_report.get("come_style_verified") is True,
        "they_shimmer": runtime_report.get("they_shimmer_stabilized") is True,
        "source_unchanged": runtime_report.get("source_timeline_unchanged") is True,
        "accepted_runtime": runtime_report.get("accepted_state_unchanged") is True,
        "accepted_disk": accepted_unchanged,
        "probe_kept": runtime_report.get("probe_timeline_kept") is True,
        "visual_review_required": runtime_report.get("visual_review_required") is True,
        "save_call_count": runtime_report.get("save_call_count") == 1,
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
        "backend": runtime_report.get("backend"),
        "probe_timeline_name": runtime_report.get("probe_timeline_name"),
        "append_returned_count": runtime_report.get("append_returned_count"),
        "append_detected_count": runtime_report.get("append_detected_count"),
        "carrier_append_count": runtime_report.get("carrier_append_count"),
        "comp_clone_count": runtime_report.get("comp_clone_count"),
        "target_readback_count": runtime_report.get("target_readback_count"),
        "visual_instance_source_cue_ids": runtime_report.get("visual_instance_source_cue_ids"),
        "visual_instance_style_source_cue_id": runtime_report.get("visual_instance_style_source_cue_id"),
        "relative_layout_verified": runtime_report.get("relative_layout_verified"),
        "come_exit_verified": runtime_report.get("come_exit_verified"),
        "come_style_verified": runtime_report.get("come_style_verified"),
        "they_shimmer_stabilized": runtime_report.get("they_shimmer_stabilized"),
        "source_timeline_unchanged": runtime_report.get("source_timeline_unchanged"),
        "accepted_state_unchanged": accepted_unchanged,
        "save_call_count": runtime_report.get("save_call_count"),
        "visual_review_required": runtime_report.get("visual_review_required"),
        "runtime_report": runtime_report,
    }
    write_json(report_dir / "probe_validation.json", validation)
    write_text(report_dir / "FINAL_REPORT.md", report_markdown(validation))
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    result = validate(Path(args.root), args.run_id, args.timeout_seconds, args.poll_seconds)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
