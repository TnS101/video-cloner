#!/usr/bin/env python3
"""Publish exactly one isolated post-visual metrics polish command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1"
MODE = "STEP_3E_POST_VISUAL_METRICS_POLISH"
MODULE = "resolve_workspace/modules/step_3E_post_visual_metrics_polish_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
AUTHORITY = "artifacts/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/post_visual_metrics_polish_v1.json"
CONFIRMED = "artifacts/DZSQH7AUHJT_STEP_3E_CONFIRMED74_REPAIR_AUTHORITY_V1/confirmed74_repair_authority_v1.json"
PRIOR_REPORT = ".agent/reports/DZSQH7AUHJT_STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT_V1/20260810T174657583683Z_59f3a2bf17ea4be697beb5de5f442fa9/report.json"
PRIOR_PERSISTENT = ".agent/reports/DZSQH7AUHJT_STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT_V1/20260810T174657583683Z_59f3a2bf17ea4be697beb5de5f442fa9/persistent_readback.json"
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
EXPECTED_PHYSICAL = 114
SOURCE_PATHS = (
    MODULE,
    AUTHORITY,
    CONFIRMED,
    "scripts/analysis/build_step_3E_post_visual_metrics_polish_v1.py",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_v1.json",
    PRIOR_REPORT,
    PRIOR_PERSISTENT,
    "resolve_workspace/modules/step_3E_confirmed74_isolated_repair_rollout_v1.py",
    "resolve_workspace/modules/step_3E_remaining100_full_rollout_v1.py",
    "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py",
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/VC_Agent_Bridge.py",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def active_commands(root: Path) -> List[Path]:
    result: List[Path] = []
    for state in ("pending", "running"):
        directory = root / ".agent" / "commands" / state
        if directory.is_dir():
            result.extend(sorted(directory.glob("*.json")))
    return result


def validate_authority(authority: Mapping[str, Any]) -> None:
    if authority.get("task_id") != TASK_ID or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    semantic = str(authority.get("semantic_sha256") or "")
    expected = canonical_sha256({key: value for key, value in authority.items() if key != "semantic_sha256"})
    if not semantic or semantic != expected:
        raise ValueError("authority_semantic_sha256")
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    if summary.get("expected_physical_textplus_count") != EXPECTED_PHYSICAL:
        raise ValueError("authority_physical")
    if "position_updates" not in summary or "opacity_updates" not in summary:
        raise ValueError("authority_mutation_scope")
    if int(summary["position_updates"]) != 0 or int(summary["opacity_updates"]) != 0:
        raise ValueError("authority_mutation_scope")
    policy = authority.get("policy") if isinstance(authority.get("policy"), Mapping) else {}
    if policy.get("transcript_timing_authority") is not False or policy.get("per_cue_hardcoded_overrides") is not False:
        raise ValueError("authority_policy")
    if policy.get("position_mutation_authorized") is not False or policy.get("opacity_mutation_authorized") is not False:
        raise ValueError("authority_position_opacity")


def validate_prior_persistent(persistent: Mapping[str, Any]) -> None:
    checks = persistent.get("checks")
    if not isinstance(checks, Mapping) or not checks:
        raise ValueError("prior_persistent")
    declared_count = persistent.get("expected_physical_textplus_count")
    if declared_count is not None and declared_count != EXPECTED_PHYSICAL:
        raise ValueError("prior_persistent")
    if persistent.get("ok") is not True or checks.get("physical_textplus_count") is not True:
        raise ValueError("prior_persistent")
    if not all(value is True for value in checks.values()):
        raise ValueError("prior_persistent")


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
    validate_authority(authority)
    prior = load_json(root / PRIOR_REPORT)
    persistent = load_json(root / PRIOR_PERSISTENT)
    if prior.get("ok") is not True or prior.get("target_timeline_name") != SOURCE_TIMELINE_NAME or prior.get("final_textplus_count") != EXPECTED_PHYSICAL or prior.get("save_call_count") != 1:
        raise ValueError("prior_report")
    validate_prior_persistent(persistent)

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
        "source_contract": {"version": 1, "algorithm": SOURCE_HASH_ALGORITHM, "hashes": {rel: normalized_sha256(root / rel) for rel in SOURCE_PATHS}},
        "polish": {
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "authority": AUTHORITY,
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "size_update_count": (authority.get("summary") or {}).get("protected_size_updates", 0) + (authority.get("summary") or {}).get("repair_size_updates", 0),
            "text_update_count": (authority.get("summary") or {}).get("protected_text_updates", 0),
            "position_updates": 0,
            "opacity_updates": 0,
            "expected_physical_textplus_count": EXPECTED_PHYSICAL,
            "fade_appearance_reassessment_deferred_until_baked_original_is_removed": True,
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
    write_json(report_dir / "polish_command.json", command)
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
