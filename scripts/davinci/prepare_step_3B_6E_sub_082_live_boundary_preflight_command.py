"""Publish one canonical read-only Resolve command for the sub_082 boundary preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

TASK_ID = "DZSQH7AUHJT_STEP_3B_6E_SUB_082_LIVE_BOUNDARY_PREFLIGHT_V1"
SOURCE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6E_V3_BOUNDARY_TIMING_STRATEGY_ASSESSMENT_V3"
SOURCE_RUN_ID = "20260803T135506176634Z_1ef963ee80834a36b8965fc01bad065e"
SOURCE_REPORT_REL = f".agent/reports/{SOURCE_TASK_ID}/{SOURCE_RUN_ID}"
LATEST_ACCEPTED_SHA256 = "71a11be5dad7dfdd2e4d7735962159cf8cebceed9442e6a39d53177956e70cba"
ANIMATION_PLAN_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_animation_plan_step_3C.json"
ANIMATION_PLAN_SHA256 = "a94a238f8cb71c2e38f3f0ac17813e1f0d98e9199b15b0e3ad1ccd84f3cd4898"
ANIMATION_TARGETS_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_animation_step_3C_source_targets.json"
ANIMATION_TARGETS_SHA256 = "f47585c666075aeaa99e6bc7ee86dbc21ac804c7248f1297848f77cf9513a0b9"
PROPOSED_OPERATION = {"field": "end_frame", "from": 656, "to": 657, "delta_frames": 1}
EXPECTED = {
    "project": "New Project 1",
    "timeline": "DZsqH7auhjt_textplus_full",
    "video_track": 3,
    "v3_count": 116,
    "target": {"cue_id": "sub_082", "name": "VC_TEXTPLUS_0082_sub_082", "text": "blocks.", "start": 649, "end": 656},
    "previous": {"cue_id": "sub_081", "name": "VC_TEXTPLUS_0081_sub_081", "text": "the", "start": 646, "end": 649},
    "next": {"cue_id": "sub_083", "name": "VC_TEXTPLUS_0083_sub_083", "text": "That's", "start": 659, "end": 665},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def command_inventory(root: Path, exclude_run_id: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        for path in sorted((queue / state).glob("*.json")):
            if exclude_run_id and exclude_run_id in path.name:
                continue
            rows.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha256(path),
            })
    return rows


def validate_base_files(root: Path) -> dict[str, Any]:
    rows = []
    expected = {
        ".agent/state/latest_accepted.json": LATEST_ACCEPTED_SHA256,
        ANIMATION_PLAN_REL: ANIMATION_PLAN_SHA256,
        ANIMATION_TARGETS_REL: ANIMATION_TARGETS_SHA256,
    }
    failures = []
    for relative, wanted in expected.items():
        path = root / relative
        actual = sha256(path) if path.is_file() else None
        matched = actual == wanted
        rows.append({"path": relative, "expected_sha256": wanted, "actual_sha256": actual, "matched": matched})
        if not matched:
            failures.append(relative)
    if failures:
        raise ValueError("base_file_hash:" + ",".join(failures))
    latest = load_json(root / ".agent/state/latest_accepted.json")
    if (
        latest.get("accepted_task") != "DZSQH7AUHJT_STEP_3B_6D_ACCEPTANCE_FINALIZER_V1"
        or latest.get("accepted_run_id") != "20260803T100743276853Z_f39a4d108f93450b8f22ceb45d3ae352"
        or latest.get("accepted_step") != "Step 3B.6D"
        or latest.get("step_3B_6D_status") != "ACCEPTED"
        or latest.get("timeline_modified") is not False
    ):
        raise ValueError("latest_accepted_contract")
    return {"ok": True, "files": rows}


def validate_source_assessment(root: Path) -> dict[str, Any]:
    report_dir = root / SOURCE_REPORT_REL
    required = (
        "status.json",
        "report.json",
        "strategy_summary.json",
        "boundary_probe_candidate_allowlist.json",
        "state_protection_audit.json",
        "FINAL_REPORT.md",
    )
    missing = [name for name in required if not (report_dir / name).is_file()]
    if missing:
        raise ValueError("source_assessment_missing:" + ",".join(missing))
    status = load_json(report_dir / "status.json")
    report = load_json(report_dir / "report.json")
    strategy = load_json(report_dir / "strategy_summary.json")
    allowlist = load_json(report_dir / "boundary_probe_candidate_allowlist.json")
    protection = load_json(report_dir / "state_protection_audit.json")
    final_report = (report_dir / "FINAL_REPORT.md").read_text(encoding="utf-8-sig")
    candidates = allowlist.get("candidates") or []
    candidate = candidates[0] if len(candidates) == 1 else {}
    summary = strategy.get("summary") or {}
    checks = {
        "status": status.get("ok") is True and status.get("stage") == "completed" and status.get("run_id") == SOURCE_RUN_ID,
        "report_identity": report.get("ok") is True and report.get("task_id") == SOURCE_TASK_ID and report.get("run_id") == SOURCE_RUN_ID,
        "classification": report.get("classification") == "ONE_STRUCTURALLY_ISOLATED_BOUNDARY_EXTENSION_CANDIDATE",
        "summary": summary.get("remaining_accepted_boundary_cue_count") == 41
        and summary.get("structurally_isolated_candidate_count") == 1
        and summary.get("neighbor_collision_count") == 40
        and summary.get("self_step_3C_protected_count") == 4,
        "candidate_count": allowlist.get("candidate_count") == 1 and len(candidates) == 1,
        "candidate_identity": candidate.get("cue_id") == "sub_082"
        and candidate.get("name") == EXPECTED["target"]["name"]
        and candidate.get("text") == EXPECTED["target"]["text"],
        "candidate_ranges": candidate.get("current_range") == [649, 656]
        and candidate.get("proposed_range") == [649, 657]
        and candidate.get("boundary_operations") == [PROPOSED_OPERATION],
        "candidate_safety": candidate.get("live_read_only_preflight_required") is True
        and candidate.get("mutation_command_permitted") is False
        and allowlist.get("production_mutation_authorized") is False,
        "state_protection": protection.get("ok") is True
        and protection.get("accepted_state_unchanged") is True
        and protection.get("command_inventory_unchanged") is True
        and protection.get("timeline_modified") is False,
        "final_report": "PASS — STEP_3B.6E_V3_BOUNDARY_TIMING_STRATEGY_ASSESSED" in final_report,
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("source_assessment_contract:" + ",".join(failures))
    return {"ok": True, "source_task_id": SOURCE_TASK_ID, "source_run_id": SOURCE_RUN_ID, "checks": checks, "candidate": candidate}


def validate_no_conflicts(root: Path) -> None:
    queue = root / ".agent" / "commands"
    for state in ("pending", "running"):
        active = sorted((queue / state).glob("*.json"))
        if active:
            raise ValueError(f"active_command:{state}:{active[0].name}")
    for state in ("pending", "running", "completed", "failed"):
        existing = sorted((queue / state).glob(f"*{TASK_ID}*.json"))
        if existing:
            raise ValueError(f"task_command_already_exists:{state}:{existing[0].name}")
    if (root / ".agent" / "reports" / TASK_ID).exists():
        raise ValueError("task_report_root_already_exists")


def allocate_run_id() -> str:
    now = datetime.now(timezone.utc)
    milliseconds = now.microsecond // 1000
    return f"{now:%Y%m%dT%H%M%S}{milliseconds:03d}Z_{uuid4().hex}"


def publish(root: Path, run_id: str | None = None) -> Path:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    if not (root / "resolve_workspace" / "VC_Agent_Bridge.py").is_file():
        raise ValueError("bridge_missing")
    module_path = root / "resolve_workspace" / "modules" / "step_3B_6E_sub_082_live_boundary_preflight.py"
    if not module_path.is_file():
        raise ValueError("runtime_module_missing")
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)

    base_validation = validate_base_files(root)
    source_validation = validate_source_assessment(root)
    validate_no_conflicts(root)
    baseline_inventory = command_inventory(root)
    accepted_state_path = root / ".agent" / "state" / "latest_accepted.json"
    accepted_state_hash = sha256(accepted_state_path)

    run_id = run_id or allocate_run_id()
    if not re_run_id(run_id):
        raise ValueError("run_id")
    relative_report_dir = f".agent/reports/{TASK_ID}/{run_id}"
    report_dir = root / relative_report_dir
    report_dir.mkdir(parents=True, exist_ok=False)
    command_name = f"{TASK_ID}_{run_id}.json"
    command_path = queue / "pending" / command_name
    command: dict[str, Any] = {
        "schema_version": 1,
        "task": TASK_ID,
        "run_id": run_id,
        "module": "resolve_workspace/modules/step_3B_6E_sub_082_live_boundary_preflight.py",
        "mode": "live_read_only_boundary_preflight",
        "status_path": f"{relative_report_dir}/status.json",
        "log_path": f"{relative_report_dir}/run.log",
        "report_path": f"{relative_report_dir}/report.json",
        "payload": {
            "repository_root": str(root),
            "report_dir": relative_report_dir,
            "source_task_id": SOURCE_TASK_ID,
            "source_run_id": SOURCE_RUN_ID,
            "expected": EXPECTED,
            "source_visibility": {
                "first_visible_frame": 649,
                "last_visible_frame": 656,
                "expected_visible_frames": list(range(649, 657)),
            },
            "proposed_operation": PROPOSED_OPERATION,
            "mutation_permitted": False,
            "accepted_state_sha256": accepted_state_hash,
            "command_inventory_before_publication": baseline_inventory,
            "base_validation": base_validation,
            "source_assessment_validation": source_validation,
            "forbidden_actions": [
                "call SetStart",
                "call SetEnd",
                "call SetProperty",
                "call SetInput",
                "call SaveProject",
                "create/delete modifiers",
                "publish a mutation command",
                "change any V3 item boundary",
            ],
        },
    }
    write_json(command_path, command)
    command_hash = sha256(command_path)
    write_json(report_dir / "preflight_command.json", command)
    write_json(report_dir / "publication_receipt.json", {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "pending_observed": command_path.is_file(),
        "command_path": str(command_path.relative_to(root)).replace("\\", "/"),
        "command_sha256": command_hash,
        "accepted_state_sha256": accepted_state_hash,
        "non_current_command_inventory": baseline_inventory,
        "manual_action_required": "Run Workspace > Scripts > VC_Agent_Bridge exactly once.",
    })
    print(json.dumps({
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path),
        "command_sha256": command_hash,
        "manual_action_required": "Run Workspace > Scripts > VC_Agent_Bridge exactly once.",
    }, indent=2))
    return command_path


def re_run_id(value: str) -> bool:
    import re
    return re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", value) is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        publish(args.root, args.run_id)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
