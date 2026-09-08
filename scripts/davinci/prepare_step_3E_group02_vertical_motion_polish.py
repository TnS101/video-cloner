#!/usr/bin/env python3
"""Publish exactly one group-02 vertical-motion polish command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

TASK_ID = "DZSQH7AUHJT_STEP_3E_GROUP02_VERTICAL_MOTION_POLISH_V1"
MODE = "STEP_3E_GROUP02_VERTICAL_MOTION_POLISH"
MODULE = "resolve_workspace/modules/step_3E_group02_vertical_motion_polish.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_baseline_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_v1"
CONTRACT = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_vertical_motion_v1.json"
BASELINE_TASK = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1"
BASELINE_RUN = "20260810T080927254297Z_befb7b9f1474440fb817520c47ba8cd3"
BASELINE_REPORT_ROOT = f".agent/reports/{BASELINE_TASK}/{BASELINE_RUN}"
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"

SOURCE_PATHS = (
    MODULE,
    CONTRACT,
    "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py",
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    f"{BASELINE_REPORT_ROOT}/full_rollout_validation.json",
    f"{BASELINE_REPORT_ROOT}/persistent_readback.json",
    f"{BASELINE_REPORT_ROOT}/full_rollout_plan.json",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}_{uuid.uuid4().hex}"


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


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


def active_commands(root: Path) -> List[Path]:
    queue = root / ".agent" / "commands"
    rows: List[Path] = []
    for state in ("pending", "running"):
        directory = queue / state
        if directory.is_dir():
            rows.extend(sorted(directory.glob("*.json")))
    return rows


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    for relative in (*SOURCE_PATHS, ACCEPTED_STATE):
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    baseline_validation = load_json(root / f"{BASELINE_REPORT_ROOT}/full_rollout_validation.json")
    baseline_persistent = load_json(root / f"{BASELINE_REPORT_ROOT}/persistent_readback.json")
    baseline_plan = load_json(root / f"{BASELINE_REPORT_ROOT}/full_rollout_plan.json")
    if baseline_validation.get("ok") is not True or baseline_validation.get("run_id") != BASELINE_RUN:
        raise ValueError("baseline_validation")
    if baseline_persistent.get("ok") is not True:
        raise ValueError("baseline_persistent")
    counts = baseline_plan.get("counts") if isinstance(baseline_plan.get("counts"), dict) else {}
    if counts != {
        "source_textplus": 115,
        "replaced_textplus": 15,
        "preserved_textplus": 100,
        "visual_first": 17,
        "final_textplus": 117,
    }:
        raise ValueError(f"baseline_counts:{counts}")
    if baseline_plan.get("full_rollout_authorized") is not False:
        raise ValueError("baseline_visual_state")

    contract = load_json(root / CONTRACT)
    if contract.get("task_id") != TASK_ID or contract.get("ok") is not True:
        raise ValueError("polish_contract")
    if contract.get("group_id") != "vf_group_02_already_decorated":
        raise ValueError("polish_group")
    plans = contract.get("plans") if isinstance(contract.get("plans"), list) else []
    if len(plans) != 2:
        raise ValueError("polish_plan_count")
    if any(row.get("font", {}) != next(
        source["font"]
        for source in baseline_plan["visual_first_instances"]
        if source["visual_token_id"] == row["visual_token_id"]
    ) for row in plans):
        raise ValueError("font_changed_in_polish_contract")

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
        if list((queue / state).glob(f"{TASK_ID}_*.json")):
            raise ValueError(f"task_command_exists:{state}")

    report_root = root / ".agent" / "reports" / TASK_ID
    if report_root.exists() and any(path.is_dir() for path in report_root.iterdir()):
        raise ValueError("task_report_exists")
    report_root.mkdir(parents=True, exist_ok=True)

    run_id = run_id_now()
    report_dir = report_root / run_id
    report_dir.mkdir()

    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": utc_now(),
        "artifacts_dir": str(report_dir.relative_to(root)).replace("/", "\\"),
        "status_path": str((report_dir / "status.json").relative_to(root)).replace("/", "\\"),
        "log_path": str((report_dir / "run.log").relative_to(root)).replace("/", "\\"),
        "report_path": str((report_dir / "report.json").relative_to(root)).replace("/", "\\"),
        "accepted_state_path": ACCEPTED_STATE.replace("/", "\\"),
        "accepted_state_sha256": raw_sha256(root / ACCEPTED_STATE),
        "source_contract": {
            "version": 1,
            "algorithm": SOURCE_HASH_ALGORITHM,
            "hashes": {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS},
        },
        "polish": {
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "group_id": contract["group_id"],
            "contract": CONTRACT,
            "token_ids": [row["visual_token_id"] for row in plans],
            "target_names": [row["target_name"] for row in plans],
            "target_range": [245, 270],
            "entrance_direction": "top_to_bottom",
            "horizontal_motion_allowed": False,
            "exit_motion_allowed": False,
            "font_polish_deferred": True,
            "expected_final_textplus_count": 117,
            "full_rollout_authorized": False,
        },
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path.relative_to(root)).replace("/", "\\"),
        "command_sha256": raw_sha256(command_path),
        "published_at": command["published_at"],
        "manual_action_required": "Workspace > Scripts > VC_Run_Agent_Task",
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    write_json(report_dir / "polish_command.json", command)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = publish(args.root)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
