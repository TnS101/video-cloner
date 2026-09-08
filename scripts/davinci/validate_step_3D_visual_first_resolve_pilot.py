#!/usr/bin/env python3
"""Validate one completed seven-window visual-first Resolve pilot run."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_RESOLVE_PILOT_V1"
MODE = "STEP_3D_VISUAL_FIRST_RESOLVE_PILOT"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_pilot_v1"
REVIEW_BUILDER_RELATIVE = Path("scripts/analysis/build_step_3D_visual_first_resolve_pilot_review.py")
REQUIRED_RUNTIME_ARTIFACTS = (
    "source_contract_verification.json",
    "authority_plan.json",
    "pilot_preflight.json",
    "duplicate_timeline_setup.json",
    "carrier_append.json",
    "pilot_application.json",
    "pilot_readback_before_render.json",
    "render_source_only.json",
    "render_generated_only.json",
    "render_alignment_overlay.json",
    "review_renders.json",
    "persistent_readback.json",
    "report.json",
    "status.json",
    "run.log",
)
REQUIRED_REVIEW_ARTIFACTS = (
    "visual_review/review_manifest.json",
    "visual_review/VISUAL_REVIEW.md",
)


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValidationError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command_name(run_id: str) -> str:
    return f"{TASK_ID}_{run_id}.json"


def locate_command(root: Path, run_id: str) -> Tuple[Optional[str], Optional[Path]]:
    found = []
    for state in ("pending", "running", "completed", "failed"):
        path = root / ".agent" / "commands" / state / command_name(run_id)
        if path.is_file():
            found.append((state, path))
    if len(found) > 1:
        raise ValidationError("command_multiple_states")
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


def load_review_builder(root: Path):
    path = root / REVIEW_BUILDER_RELATIVE
    spec = importlib.util.spec_from_file_location("visual_first_pilot_review_builder", path)
    if spec is None or spec.loader is None:
        raise ValidationError(f"review_builder_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(code)


def status_is_completed(status: Mapping[str, Any], run_id: str) -> bool:
    explicit_state = status.get("state") or status.get("status")
    if explicit_state is not None:
        return str(explicit_state).lower() == "completed"
    return (
        status.get("ok") is True
        and status.get("running") is False
        and status.get("run_id") == run_id
        and bool(status.get("finished_at"))
    )


def validate(root: Path, run_id: str, timeout_seconds: float, poll_seconds: float) -> Dict[str, Any]:
    root = root.resolve()
    state, command_path, wait = wait_for_terminal(root, run_id, timeout_seconds, poll_seconds)
    command = load_json(command_path)
    require(command.get("task_id") == TASK_ID, "command_task")
    require(command.get("mode") == MODE, "command_mode")
    require(command.get("run_id") == run_id, "command_run_id")
    report_dir = root / str(command.get("artifacts_dir") or "").replace("\\", "/")
    require(report_dir.is_dir(), "report_dir")
    missing_runtime = [name for name in REQUIRED_RUNTIME_ARTIFACTS if not (report_dir / name).is_file()]
    require(not missing_runtime, f"runtime_artifacts_missing:{','.join(missing_runtime)}")

    report = load_json(report_dir / "report.json")
    status = load_json(report_dir / "status.json")
    authority_plan = load_json(report_dir / "authority_plan.json")
    preflight = load_json(report_dir / "pilot_preflight.json")
    duplicate = load_json(report_dir / "duplicate_timeline_setup.json")
    append = load_json(report_dir / "carrier_append.json")
    application = load_json(report_dir / "pilot_application.json")
    readback = load_json(report_dir / "pilot_readback_before_render.json")
    renders = load_json(report_dir / "review_renders.json")
    persistent = load_json(report_dir / "persistent_readback.json")

    require(state == "completed", f"command_state:{state}")
    require(status_is_completed(status, run_id), f"status_terminal:{status.get('state') or status.get('status')}")
    require(report.get("ok") is True, f"report_not_ok:{report.get('error')}")
    require(not report.get("failures"), f"report_failures:{report.get('failures')}")
    require(report.get("task_id") == TASK_ID and report.get("run_id") == run_id, "report_identity")
    require(report.get("target_timeline_name") == TARGET_TIMELINE_NAME, "target_timeline_name")
    require(report.get("target_timeline_kept") is True, "target_not_kept")
    require(report.get("save_call_count") == 1, "save_call_count")
    require(report.get("source_timeline_unchanged") is True, "source_changed")
    require(report.get("accepted_state_unchanged") is True, "accepted_changed")
    require(report.get("visual_review_required") is True, "visual_review_not_required")
    require(report.get("full_rollout_authorized") is False, "full_rollout_authorized")
    require(report.get("group_count") == 7, "group_count")
    require(report.get("visual_token_count") == 17, "token_count")
    require(report.get("visual_only_component_count") == 2, "visual_only_count")
    require(report.get("transcript_timing_promoted_count") == 0, "transcript_timing_promoted")
    require(report.get("review_render_count") == 3, "render_count")

    require(authority_plan.get("ok") is True, "authority_plan")
    require(authority_plan.get("group_count") == 7, "authority_group_count")
    require(authority_plan.get("token_count") == 17, "authority_token_count")
    require(authority_plan.get("visual_only_count") == 2, "authority_visual_only_count")
    require(authority_plan.get("transcript_timing_promoted_count") == 0, "authority_transcript_timing")
    require(authority_plan.get("full_rollout_authorized") is False, "authority_full_rollout")
    require(len(authority_plan.get("instances") or []) == 17, "authority_instances")
    require(all(row.get("transcript_timing_promoted_to_authority") is False for row in authority_plan["instances"]), "instance_transcript_timing")

    require(preflight.get("ok") is True, "preflight")
    require(preflight.get("source_textplus_count") == 115, "source_textplus_count")
    require(duplicate.get("ok") is True, "duplicate_setup")
    require(duplicate.get("old_textplus_count_before") == 115, "duplicate_old_textplus_count")
    require(duplicate.get("old_textplus_remaining") == [], "old_textplus_remaining")
    require(append.get("ok") is True and append.get("assigned_count") == 17, "append")
    require(application.get("ok") is True and application.get("instance_count") == 17, "application")
    require(readback.get("ok") is True and readback.get("instance_count") == 17, "readback")
    require(renders.get("ok") is True, "renders")
    require(renders.get("frame_range") == [176, 692], "render_range")
    require(set((renders.get("renders") or {}).keys()) == {"source_only", "generated_only", "alignment_overlay"}, "render_modes")
    for mode, row in renders["renders"].items():
        require(row.get("ok") is True, f"render_mode:{mode}")
        path = Path(str(row.get("file") or ""))
        if not path.is_absolute():
            path = root / path
        require(path.is_file() and path.stat().st_size > 0, f"render_file:{mode}")
        require(raw_sha256(path) == row.get("file_sha256"), f"render_hash:{mode}")
    require(persistent.get("ok") is True, "persistent")
    require(all((persistent.get("checks") or {}).values()), "persistent_checks")
    require(len(persistent.get("pilot_rows") or []) == 17, "persistent_rows")
    require(all(row.get("ok") is True for row in persistent["pilot_rows"]), "persistent_instance")

    review_builder = load_review_builder(root)
    review_manifest = review_builder.build(root, report_dir)
    missing_review = [name for name in REQUIRED_REVIEW_ARTIFACTS if not (report_dir / name).is_file()]
    require(not missing_review, f"review_artifacts_missing:{','.join(missing_review)}")
    require(review_manifest.get("ok") is True, "review_manifest")
    require(review_manifest.get("group_count") == 7, "review_group_count")
    require(review_manifest.get("token_count") == 17, "review_token_count")
    require(len(review_manifest.get("renders") or {}) == 3, "review_renders")
    require(len(review_manifest.get("groups") or []) == 7, "review_groups")
    require(all(Path(row["contact_sheet"]).is_file() and Path(row["contact_sheet"]).stat().st_size > 0 for row in review_manifest["groups"]), "review_contact_sheets")
    require(review_manifest.get("visual_approval_required") is True, "review_approval")
    require(review_manifest.get("full_rollout_authorized") is False, "review_full_rollout")

    validation = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "ok": True,
        "command_state": state,
        "wait": wait,
        "command_path": str(command_path),
        "command_sha256": raw_sha256(command_path),
        "report_dir": str(report_dir),
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "group_count": 7,
        "visual_token_count": 17,
        "visual_only_component_count": 2,
        "transcript_timing_promoted_count": 0,
        "old_textplus_removed_count": 115,
        "review_render_count": 3,
        "review_contact_sheet_count": 7,
        "source_timeline_unchanged": True,
        "accepted_state_unchanged": True,
        "target_timeline_kept": True,
        "save_call_count": 1,
        "visual_review_required": True,
        "full_rollout_authorized": False,
        "review_directory": str(report_dir / "visual_review"),
        "review_manifest": str(report_dir / "visual_review" / "review_manifest.json"),
    }
    write_json(report_dir / "pilot_validation.json", validation)
    lines = [
        f"# {TASK_ID}",
        "",
        "## Result",
        "",
        "PASS",
        "",
        "## Evidence",
        "",
        f"- Run ID: `{run_id}`",
        "- Groups: `7`",
        "- Visual tokens: `17`",
        "- Visual-only components: `2`",
        "- Transcript timing promoted: `0`",
        "- Prior transcript-first Text+ removed from pilot duplicate: `115`",
        "- Review renders: `3`",
        "- Contact sheets: `7`",
        f"- Retained timeline: `{TARGET_TIMELINE_NAME}`",
        "- Source timeline and accepted state unchanged: `true`",
        "- Full rollout authorized: `false`",
        "- Visual review required: `true`",
        "",
        "Open the visual_review directory and approve or reject every group. Technical PASS is not visual approval.",
    ]
    write_text(report_dir / "FINAL_REPORT.md", "\n".join(lines) + "\n")
    return validation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate(args.root, args.run_id, args.timeout_seconds, args.poll_seconds)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("VISUAL_REVIEW_REQUIRED: technical PASS does not authorize full rollout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
