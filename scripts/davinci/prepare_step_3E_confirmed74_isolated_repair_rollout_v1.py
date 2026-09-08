#!/usr/bin/env python3
"""Publish exactly one confirmed-74 isolated repair rollout command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT_V1"
MODE = "STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT"
MODULE = "resolve_workspace/modules/step_3E_confirmed74_isolated_repair_rollout_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_17tokens_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_v1"
AUTHORITY = "artifacts/DZSQH7AUHJT_STEP_3E_CONFIRMED74_REPAIR_AUTHORITY_V1/confirmed74_repair_authority_v1.json"
STEP3E3_REPORT = ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/report.json"
STEP3E3_PERSISTENT = ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json"
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE,
    AUTHORITY,
    STEP3E3_REPORT,
    STEP3E3_PERSISTENT,
    "scripts/analysis/build_step_3E_confirmed74_repair_authority_v1.py",
    "scripts/analysis/visual_caption_repair_core.py",
    "resolve_workspace/modules/step_3E_remaining100_full_rollout_v1.py",
    "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py",
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/VC_Agent_Bridge.py",
)
EXPECTED_REPAIR = 74
EXPECTED_UNRESOLVED = 23
EXPECTED_COMPOSITE_REMOVED = 3
EXPECTED_PROTECTED = 17
EXPECTED_PHYSICAL_TEXTPLUS = 114


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def active_commands(root: Path) -> List[Path]:
    rows: List[Path] = []
    queue = root / ".agent" / "commands"
    for state in ("pending", "running"):
        directory = queue / state
        if directory.is_dir():
            rows.extend(sorted(directory.glob("*.json")))
    return rows


def authority_input_path(root: Path, value: Any) -> Path:
    return root / Path(str(value or "").replace("\\", "/"))


def validate_authority(root: Path, authority: Mapping[str, Any]) -> None:
    if authority.get("task_id") != TASK_ID or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    semantic = str(authority.get("semantic_sha256") or "")
    expected_semantic = canonical_sha256({key: value for key, value in authority.items() if key != "semantic_sha256"})
    if not semantic or semantic != expected_semantic:
        raise ValueError("authority_semantic_sha256")
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    expected = {
        "repair_instances": EXPECTED_REPAIR,
        "preserve_unresolved": EXPECTED_UNRESOLVED,
        "remove_composite_structural": EXPECTED_COMPOSITE_REMOVED,
        "protected_v4": EXPECTED_PROTECTED,
        "expected_physical_textplus_count": EXPECTED_PHYSICAL_TEXTPLUS,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise ValueError(f"authority_summary:{key}:{summary.get(key)}")
    policy = authority.get("policy") if isinstance(authority.get("policy"), Mapping) else {}
    if policy.get("transcript_timing_authority") is not False or policy.get("unresolved_rows_receive_repair_geometry") is not False:
        raise ValueError("authority_policy")
    if policy.get("composite_structural_rows_recreated") is not False or policy.get("fade_polish_deferred") is not True:
        raise ValueError("authority_scope_policy")
    if policy.get("resolve_modified") is not False or policy.get("repair_rollout_authorized") is not False:
        raise ValueError("authority_pre_rollout_lock")
    inputs = authority.get("inputs") if isinstance(authority.get("inputs"), Mapping) else {}
    for key in ("universal_authority", "universal_validation", "semantic_coverage", "semantic_validation", "source_video"):
        row = inputs.get(key) if isinstance(inputs.get(key), Mapping) else {}
        path = authority_input_path(root, row.get("path"))
        expected_hash = str(row.get("sha256") or "")
        if not path.is_file() or not expected_hash or raw_sha256(path) != expected_hash:
            raise ValueError(f"authority_input:{key}")


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    for rel in (*SOURCE_PATHS, ACCEPTED_STATE):
        if not (root / rel).is_file():
            raise ValueError(f"source_missing:{rel}")
    authority = load_json(root / AUTHORITY)
    validate_authority(root, authority)
    prior = load_json(root / STEP3E3_REPORT)
    persistent = load_json(root / STEP3E3_PERSISTENT)
    if prior.get("ok") is not True or prior.get("target_timeline_name") != SOURCE_TIMELINE_NAME or prior.get("final_textplus_count") != 117 or prior.get("save_call_count") != 1:
        raise ValueError("step3e3_report")
    if persistent.get("ok") is not True or len(persistent.get("rows") or []) != EXPECTED_PROTECTED or not all((persistent.get("checks") or {}).values()):
        raise ValueError("step3e3_persistent")

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
    source_video = authority.get("inputs", {}).get("source_video") or {}
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
            "hashes": {rel: normalized_sha256(root / rel) for rel in SOURCE_PATHS},
        },
        "rollout": {
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "authority": AUTHORITY,
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "source_video_sha256": source_video.get("sha256"),
            "repair_instance_count": EXPECTED_REPAIR,
            "unresolved_preserved_count": EXPECTED_UNRESOLVED,
            "composite_structural_removed_count": EXPECTED_COMPOSITE_REMOVED,
            "protected_v4_count": EXPECTED_PROTECTED,
            "expected_physical_textplus_count": EXPECTED_PHYSICAL_TEXTPLUS,
            "user_authorized_this_rollout": True,
            "transcript_timing_authority": False,
            "unresolved_repair_authorized": False,
            "composite_structural_recreation_authorized": False,
            "static_style_policy": "source_comp_preserved_except_evidence_gated_fill",
            "fade_polish_deferred": True,
            "visual_approval_required": True,
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
    write_json(report_dir / "rollout_command.json", command)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = publish(args.root)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
