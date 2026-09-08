"""Validate the single-run complete Step 3D Text+ lifecycle rollout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6"
MODE = "STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT"
FINAL_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete_v6_exact_lifecycles"
REQUIRED_SUCCESS_ARTIFACTS = (
    "source_contract_verification.json",
    "rollout_plan.json",
    "source_inventory_before.json",
    "rollout_preflight.json",
    "source_comp_exports.json",
    "duplicate_timeline_setup.json",
    "carrier_plan_audit.json",
    "carrier_append_progress.json",
    "comp_import_progress.json",
    "correction_application_progress.json",
    "persistent_readback_progress.json",
    "persistent_readback.json",
    "rollout_result.json",
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
        f"- Final timeline: `{validation.get('final_timeline_name')}`",
        f"- Source captions: `{validation.get('source_caption_count')}`",
        f"- Source range policy: `{validation.get('source_range_policy')}`",
        f"- Resolve bounded source-range adjustments: `{validation.get('source_range_adjustment_count')}`",
        f"- Adjusted source cues: `{validation.get('source_range_adjustment_cue_ids')}`",
        f"- Visual instances: `{validation.get('visual_instance_count')}`",
        f"- Represented transcript cues: `{validation.get('represented_cue_count')}`",
        f"- Merged aliases: `{validation.get('merged_aliases')}`",
        f"- Caption lanes: `{validation.get('lane_count')}`",
        f"- One-frame carrier accommodations: `{validation.get('one_frame_carrier_count')}`",
        f"- One-frame carrier IDs: `{validation.get('one_frame_carrier_ids')}`",
        f"- Base-collision relocations: `{validation.get('base_collision_relocation_ids')}`",
        f"- Carrier plan audit: `{validation.get('carrier_plan_audit_ok')}`",
        f"- Physical carrier track usage: `{validation.get('carrier_track_usage')}`",
        f"- Carriers appended: `{validation.get('carrier_append_count')}`",
        f"- Fusion comps imported: `{validation.get('comp_import_count')}`",
        f"- Persistent instances: `{validation.get('persistent_instance_count')}`",
        f"- Exact lifecycle durations: `{validation.get('exact_lifecycle_instance_count')}` / `115`",
        f"- Append source endpoint padding: `{validation.get('append_source_end_padding_frames')}` frame",
        f"- Accepted animations verified: `{validation.get('animated_verified_count')}`",
        f"- Same-track overlaps: `{validation.get('same_track_overlap_count')}`",
        f"- Special COME/they corrections: `{validation.get('special_corrections_verified')}`",
        f"- Protected source unchanged: `{validation.get('source_timeline_unchanged')}`",
        f"- Accepted state unchanged: `{validation.get('accepted_state_unchanged')}`",
        f"- Base timeline structure unchanged: `{validation.get('base_timeline_structure_unchanged')}`",
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
            f"Open `{validation.get('final_timeline_name')}`.",
            "Review the listed animation/overlap windows, then scrub the entire timeline.",
            "Confirm the merged lower-case `they` remains above `COME`, and `COME` keeps the accepted dark style and rightward fade.",
            "Confirm all remaining captions keep the protected source style/position and calibrated lifecycle windows.",
        ])
    return "\n".join(lines) + "\n"


def validate(root: Path, run_id: str, timeout_seconds: float = 3600.0, poll_seconds: float = 1.0) -> Dict[str, Any]:
    root = root.resolve()
    report_dir = root / ".agent" / "reports" / TASK_ID / run_id
    if not report_dir.is_dir():
        raise ValueError("report_dir")
    receipt_path = report_dir / "publication_receipt.json"
    command_copy_path = report_dir / "rollout_command.json"
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
        export_dir = report_dir / "source_comp_exports"
        comp_files = list(export_dir.glob("*.comp")) if export_dir.is_dir() else []
        if len(comp_files) != 115 or any(path.stat().st_size == 0 for path in comp_files):
            failures.append(f"artifact:source_comp_exports:{len(comp_files)}")

    accepted_path = root / ".agent" / "state" / "latest_accepted.json"
    accepted_unchanged = accepted_path.is_file() and raw_sha256(accepted_path) == command.get("accepted_state_sha256")
    checks = {
        "task_id": runtime_report.get("task_id") == TASK_ID,
        "mode": runtime_report.get("mode") == MODE,
        "backend": runtime_report.get("backend") == "media_pool_append_plus_import_fusion_comp_full_lifecycle_rollout",
        "run_id": runtime_report.get("run_id") == run_id,
        "source_contract": runtime_report.get("source_contract_verified_count") == 10,
        "final_timeline_name": runtime_report.get("final_timeline_name") == FINAL_TIMELINE_NAME,
        "source_caption_count": runtime_report.get("source_caption_count") == 116,
        "source_inventory": runtime_report.get("source_inventory_ok") is True,
        "source_range_policy": runtime_report.get("source_range_policy") == "exact_or_resolve_end_shortened_up_to_2_frames",
        "source_range_adjustments": (
            isinstance(runtime_report.get("source_range_adjustment_count"), int)
            and isinstance(runtime_report.get("source_range_adjustment_cue_ids"), list)
            and runtime_report.get("source_range_adjustment_count") == len(runtime_report.get("source_range_adjustment_cue_ids"))
        ),
        "source_comp_exports": runtime_report.get("source_comp_export_count") == 115,
        "visual_instances": runtime_report.get("visual_instance_count") == 115,
        "represented_cues": runtime_report.get("represented_cue_count") == 116,
        "merge_group_count": runtime_report.get("merge_group_count") == 1,
        "merged_aliases": runtime_report.get("merged_aliases") == ["sub_051", "sub_054"],
        "lane_count": runtime_report.get("lane_count") == 5,
        "lane_usage": runtime_report.get("lane_usage") == {"1": 71, "2": 22, "3": 16, "4": 5, "5": 1},
        "one_frame_carrier_count": runtime_report.get("one_frame_carrier_count") == 1,
        "one_frame_carrier_ids": runtime_report.get("one_frame_carrier_ids") == ["sub_073"],
        "base_collision_relocation_count": runtime_report.get("base_collision_relocation_count") == 1,
        "base_collision_relocation_ids": runtime_report.get("base_collision_relocation_ids") == ["sub_052"],
        "carrier_plan_audit": runtime_report.get("carrier_plan_audit_ok") is True,
        "carrier_track_usage": runtime_report.get("carrier_track_usage") == {"3": 71, "4": 21, "5": 16, "6": 5, "7": 2},
        "exact_lifecycle_instances": runtime_report.get("exact_lifecycle_instance_count") == 115,
        "append_source_end_padding": runtime_report.get("append_source_end_padding_frames") == 1,
        "carrier_overlaps": runtime_report.get("carrier_overlap_count") == 0,
        "carrier_base_collisions": runtime_report.get("carrier_base_collision_count") == 0,
        "append_batches": isinstance(runtime_report.get("append_batch_count"), int) and runtime_report.get("append_batch_count") > 0,
        "carrier_appends": runtime_report.get("carrier_append_count") == 115,
        "comp_imports": runtime_report.get("comp_import_count") == 115,
        "instance_applications": runtime_report.get("instance_application_count") == 115,
        "persistent_instances": runtime_report.get("persistent_instance_count") == 115,
        "animated_count": runtime_report.get("animated_instance_count") == 8,
        "animated_verified": runtime_report.get("animated_verified_count") == 8,
        "same_track_overlaps": runtime_report.get("same_track_overlap_count") == 0,
        "special_corrections": runtime_report.get("special_corrections_verified") is True,
        "source_unchanged": runtime_report.get("source_timeline_unchanged") is True,
        "accepted_runtime": runtime_report.get("accepted_state_unchanged") is True,
        "accepted_disk": accepted_unchanged,
        "base_structure": runtime_report.get("base_timeline_structure_unchanged") is True,
        "final_kept": runtime_report.get("final_timeline_kept") is True,
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
        "final_timeline_name": runtime_report.get("final_timeline_name"),
        "source_caption_count": runtime_report.get("source_caption_count"),
        "source_range_policy": runtime_report.get("source_range_policy"),
        "source_range_adjustment_count": runtime_report.get("source_range_adjustment_count"),
        "source_range_adjustment_cue_ids": runtime_report.get("source_range_adjustment_cue_ids"),
        "visual_instance_count": runtime_report.get("visual_instance_count"),
        "represented_cue_count": runtime_report.get("represented_cue_count"),
        "merged_aliases": runtime_report.get("merged_aliases"),
        "lane_count": runtime_report.get("lane_count"),
        "one_frame_carrier_count": runtime_report.get("one_frame_carrier_count"),
        "one_frame_carrier_ids": runtime_report.get("one_frame_carrier_ids"),
        "base_collision_relocation_count": runtime_report.get("base_collision_relocation_count"),
        "base_collision_relocation_ids": runtime_report.get("base_collision_relocation_ids"),
        "carrier_plan_audit_ok": runtime_report.get("carrier_plan_audit_ok"),
        "carrier_track_usage": runtime_report.get("carrier_track_usage"),
        "carrier_append_count": runtime_report.get("carrier_append_count"),
        "comp_import_count": runtime_report.get("comp_import_count"),
        "persistent_instance_count": runtime_report.get("persistent_instance_count"),
        "exact_lifecycle_instance_count": runtime_report.get("exact_lifecycle_instance_count"),
        "append_source_end_padding_frames": runtime_report.get("append_source_end_padding_frames"),
        "animated_verified_count": runtime_report.get("animated_verified_count"),
        "same_track_overlap_count": runtime_report.get("same_track_overlap_count"),
        "special_corrections_verified": runtime_report.get("special_corrections_verified"),
        "source_timeline_unchanged": runtime_report.get("source_timeline_unchanged"),
        "accepted_state_unchanged": accepted_unchanged,
        "base_timeline_structure_unchanged": runtime_report.get("base_timeline_structure_unchanged"),
        "save_call_count": runtime_report.get("save_call_count"),
        "visual_review_required": runtime_report.get("visual_review_required"),
        "visual_review_windows": runtime_report.get("visual_review_windows"),
        "runtime_report": runtime_report,
    }
    write_json(report_dir / "rollout_validation.json", validation)
    write_text(report_dir / "FINAL_REPORT.md", report_markdown(validation))
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    result = validate(Path(args.root), args.run_id, args.timeout_seconds, args.poll_seconds)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
