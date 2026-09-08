#!/usr/bin/env python3
"""Publish exactly one Visual Fidelity V2 isolated Resolve rollout command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_ISOLATED_RESOLVE_ROLLOUT_V1"
MODE = "STEP_3E_VISUAL_FIDELITY_V2_ISOLATED_RESOLVE_ROLLOUT"
MODULE = "resolve_workspace/modules/step_3E_visual_fidelity_v2_isolated_resolve_rollout_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_visual_fidelity_v2_v1"
AUTHORITY = "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1/visual_fidelity_v2_resolve_rollout_authority_v1.json"
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
EXPECTED_TARGET_PHYSICAL = 113
SOURCE_PATHS = (
    MODULE,
    AUTHORITY,
    "scripts/analysis/build_step_3E_visual_fidelity_v2_resolve_rollout_authority_v1.py",
    "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_v1.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_v1.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_v1.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_validation.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_foreground_assets.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_foreground_assets_validation.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_matte_contract.json",
    ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json",
    "resolve_workspace/modules/step_3E_post_visual_metrics_polish_v1.py",
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

def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()

def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)

def active_commands(root: Path) -> list[Path]:
    rows: list[Path] = []
    for state in ("pending", "running"):
        d = root / ".agent" / "commands" / state
        if d.is_dir(): rows.extend(sorted(d.glob("*.json")))
    return rows

def task_commands(root: Path, state: str) -> list[Path]:
    folder = root / ".agent" / "commands" / state
    return sorted(folder.glob(f"{TASK_ID}_*.json")) if folder.is_dir() else []

def validate_retry_state(root: Path) -> dict[str, Any]:
    """Allow one retry only after a failed run proved successful cleanup.

    This task normally publishes once. A trivial runtime integration defect may be
    repaired once, but only when the prior failed command is inactive, its cleanup
    artifact is successful, and accepted state was preserved. A second failed run
    remains a hard stop.
    """
    completed = task_commands(root, "completed")
    if completed:
        raise ValueError(f"task_command_exists:completed:{completed[0].name}")
    failed = task_commands(root, "failed")
    if len(failed) > 1:
        raise ValueError(f"repair_retry_limit:{len(failed)}")
    if not failed:
        return {"repair_retry": False, "prior_failed_run_id": ""}
    command = load_json(failed[0])
    run_id = str(command.get("run_id") or "")
    artifacts_dir = str(command.get("artifacts_dir") or "").replace("\\", "/")
    if command.get("task_id") != TASK_ID or not run_id or not artifacts_dir:
        raise ValueError("prior_failed_command_identity")
    cleanup_path = root / artifacts_dir / "failure_cleanup.json"
    if not cleanup_path.is_file():
        raise ValueError("prior_failure_cleanup_missing")
    cleanup = load_json(cleanup_path)
    if cleanup.get("ok") is not True or cleanup.get("accepted_state_unchanged") is not True or cleanup.get("errors") not in ([], None):
        raise ValueError("prior_failure_cleanup")
    return {"repair_retry": True, "prior_failed_run_id": run_id}

def validate_authority(authority: Mapping[str, Any]) -> None:
    if authority.get("task_id") != "DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1" or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    semantic = str(authority.get("semantic_sha256") or "")
    if not semantic or semantic != canonical_sha256({k:v for k,v in authority.items() if k != "semantic_sha256"}):
        raise ValueError("authority_semantic_sha256")
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    expected = {
        "v2_repair_recreate": 73,
        "semantic_recreate": 13,
        "visual_companion_recreate": 1,
        "recreate_total": 87,
        "preserved_unresolved": 9,
        "quarantined_remove": 1,
        "protected_total": 17,
        "protected_exit_updates": 3,
        "target_physical_textplus": EXPECTED_TARGET_PHYSICAL,
        "occlusion_span_count": 1,
    }
    for key, value in expected.items():
        if summary.get(key) != value: raise ValueError(f"authority_summary:{key}:{summary.get(key)}")
    policy = authority.get("policy") if isinstance(authority.get("policy"), Mapping) else {}
    if policy.get("transcript_timing_authority") is not False or policy.get("geometry_only_semantic_promotion") is not False:
        raise ValueError("authority_semantic_policy")
    if policy.get("residual_unresolved_mutation_authorized") is not False or policy.get("source_absence_claims") != 0:
        raise ValueError("authority_unresolved_policy")
    if policy.get("occlusion_contract") != "foreground_rgba_above_textplus" or policy.get("visual_approval_required") is not True:
        raise ValueError("authority_occlusion_policy")
    if policy.get("further_rollout_authorized") is not False or policy.get("resolve_modified") is not False:
        raise ValueError("authority_lock")


def publish(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file(): raise ValueError("repository_root")
    active = active_commands(root)
    if active: raise ValueError(f"active_command:{active[0].name}")
    retry_state = validate_retry_state(root)
    for rel in (*SOURCE_PATHS, ACCEPTED_STATE):
        if not (root / rel).is_file(): raise ValueError(f"source_missing:{rel}")
    authority = load_json(root / AUTHORITY); validate_authority(authority)
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue/state).mkdir(parents=True, exist_ok=True)
    report_root = root / ".agent" / "reports" / TASK_ID
    report_root.mkdir(parents=True, exist_ok=True)
    run_id = run_id_now(); report_dir = report_root / run_id; report_dir.mkdir()
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": utc_now(),
        "artifacts_dir": str(report_dir.relative_to(root)).replace("/", "\\"),
        "status_path": str((report_dir/"status.json").relative_to(root)).replace("/", "\\"),
        "log_path": str((report_dir/"run.log").relative_to(root)).replace("/", "\\"),
        "report_path": str((report_dir/"report.json").relative_to(root)).replace("/", "\\"),
        "accepted_state_path": ACCEPTED_STATE.replace("/", "\\"),
        "accepted_state_sha256": raw_sha256(root/ACCEPTED_STATE),
        "repair_retry": retry_state,
        "source_contract": {"version":1, "algorithm":SOURCE_HASH_ALGORITHM, "hashes":{rel: normalized_sha256(root/rel) for rel in SOURCE_PATHS}},
        "rollout": {
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "authority": AUTHORITY,
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "recreate_total": 87,
            "preserved_unresolved": 9,
            "quarantined_remove": 1,
            "protected_exit_updates": 3,
            "expected_physical_textplus_count": EXPECTED_TARGET_PHYSICAL,
            "foreground_rgba_above_textplus": True,
            "transcript_timing_authority": False,
            "fade_polish_deferred": True,
            "visual_approval_required": True,
            "user_authorized_this_isolated_rollout": True,
        },
    }
    command_path = queue/"pending"/f"{TASK_ID}_{run_id}.json"
    write_json(command_path, command)
    receipt = {"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"command_path":str(command_path.relative_to(root)).replace("/","\\"),"command_sha256":raw_sha256(command_path),"published_at":command["published_at"],"repair_retry":retry_state,"manual_action_required":"Workspace > Scripts > VC_Run_Agent_Task"}
    write_json(report_dir/"publication_receipt.json", receipt)
    write_json(report_dir/"rollout_command.json", command)
    return receipt

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--root",type=Path,default=Path.cwd()); args=p.parse_args()
    try: result=publish(args.root)
    except Exception as exc:
        print(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"},sort_keys=True)); return 1
    print(json.dumps({"ok":True,**result},sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
