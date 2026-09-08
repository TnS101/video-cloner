#!/usr/bin/env python3
"""Publish exactly one monotonic VF2 regression-recovery Resolve command."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, uuid
from pathlib import Path
from typing import Any, Mapping

TASK_ID="DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_V1"
MODE="STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY"
MODULE="resolve_workspace/modules/step_3E_vf2_monotonic_regression_recovery_v1.py"
SOURCE_TIMELINE_NAME="DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME="DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_vf2_regression_recovery_v1"
AUTHORITY="artifacts/DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_AUTHORITY_V1/vf2_monotonic_regression_recovery_authority_v1.json"
ACCEPTED_STATE=".agent/state/latest_accepted.json"
SOURCE_PATHS=(
    MODULE,
    AUTHORITY,
    "scripts/analysis/build_step_3E_vf2_monotonic_regression_recovery_authority_v1.py",
    "resolve_workspace/modules/step_3E_visual_fidelity_v2_isolated_resolve_rollout_v1.py",
    "resolve_workspace/modules/step_3E_post_visual_metrics_polish_v1.py",
    "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1/visual_fidelity_v2_resolve_rollout_authority_v1.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_v1.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_v1.json",
    "artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_v1.json",
    "resolve_workspace/VC_Agent_Bridge.py",
)
def utc_now(): return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00","Z")
def run_id_now(): return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex
def raw_sha256(p:Path): return hashlib.sha256(p.read_bytes()).hexdigest()
def normalized_sha256(p:Path): return hashlib.sha256(p.read_bytes().replace(b"\r\n",b"\n").replace(b"\r",b"\n")).hexdigest()
def load_json(p:Path):
    v=json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(v,dict): raise ValueError(f"expected_object:{p}")
    return v
def write_json(p:Path,v:Any):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_name(p.name+".tmp")
    t.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n"); os.replace(t,p)
def active_commands(root:Path):
    out=[]
    for state in ("pending","running"):
        d=root/".agent"/"commands"/state
        if d.is_dir(): out.extend(sorted(d.glob("*.json")))
    return out
def task_commands(root:Path,state:str):
    d=root/".agent"/"commands"/state
    return sorted(d.glob(f"{TASK_ID}_*.json")) if d.is_dir() else []

def validate_retry_state(root:Path):
    """Allow one patched retry only after successful failed-run cleanup.

    A completed run remains terminal.  Exactly one failed run may be retried when
    its cleanup artifact proves accepted-state preservation and no cleanup errors.
    A second failed run is a hard stop.
    """
    completed=task_commands(root,"completed")
    if completed: raise ValueError(f"task_command_exists:completed:{completed[0].name}")
    failed=task_commands(root,"failed")
    if len(failed)>1: raise ValueError(f"repair_retry_limit:{len(failed)}")
    if not failed: return {"repair_retry":False,"prior_failed_run_id":""}
    command=load_json(failed[0])
    run_id=str(command.get("run_id") or "")
    artifacts_dir=str(command.get("artifacts_dir") or "").replace("\\","/")
    if command.get("task_id")!=TASK_ID or not run_id or not artifacts_dir:
        raise ValueError("prior_failed_command_identity")
    cleanup_path=root/artifacts_dir/"failure_cleanup.json"
    if not cleanup_path.is_file(): raise ValueError("prior_failure_cleanup_missing")
    cleanup=load_json(cleanup_path)
    if cleanup.get("ok") is not True or cleanup.get("accepted_state_unchanged") is not True or cleanup.get("errors") not in ([],None):
        raise ValueError("prior_failure_cleanup")
    return {"repair_retry":True,"prior_failed_run_id":run_id}
def validate_authority(a:Mapping[str,Any]):
    if a.get("task_id")!="DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_AUTHORITY_V1" or a.get("ok") is not True: raise ValueError("authority_identity")
    s=a.get("summary") or {}; p=a.get("policy") or {}
    expected={"center_corrections":14,"protected_exit_updates":3,"quarantine_removed":1,"target_physical_textplus":113,"recreated_textplus":0,"size_updates":0,"fill_updates":0,"case_updates":0,"opacity_updates":0}
    for k,v in expected.items():
        if s.get(k)!=v: raise ValueError(f"authority_summary:{k}:{s.get(k)}")
    if p.get("monotonic_non_regression") is not True or p.get("failed_v2_target_may_be_used_as_source") is not False: raise ValueError("monotonic_policy")
def publish(root:Path):
    root=root.resolve()
    if not (root/"AGENTS.md").is_file(): raise ValueError("repository_root")
    active=active_commands(root)
    if active: raise ValueError(f"active_command:{active[0].name}")
    retry_state=validate_retry_state(root)
    for rel in (*SOURCE_PATHS,ACCEPTED_STATE):
        if not (root/rel).is_file(): raise ValueError(f"source_missing:{rel}")
    authority=load_json(root/AUTHORITY); validate_authority(authority)
    queue=root/".agent"/"commands"
    for state in ("pending","running","completed","failed"): (queue/state).mkdir(parents=True,exist_ok=True)
    run_id=run_id_now(); report_dir=root/".agent"/"reports"/TASK_ID/run_id; report_dir.mkdir(parents=True)
    command={
        "schema_version":1,"task_id":TASK_ID,"run_id":run_id,"mode":MODE,"module":MODULE,"published_at":utc_now(),
        "artifacts_dir":str(report_dir.relative_to(root)).replace("/","\\"),
        "status_path":str((report_dir/"status.json").relative_to(root)).replace("/","\\"),
        "log_path":str((report_dir/"run.log").relative_to(root)).replace("/","\\"),
        "report_path":str((report_dir/"report.json").relative_to(root)).replace("/","\\"),
        "accepted_state_path":ACCEPTED_STATE.replace("/","\\"),
        "accepted_state_sha256":raw_sha256(root/ACCEPTED_STATE),
        "repair_retry":retry_state,
        "source_contract":{"version":1,"algorithm":"sha256_text_lf_normalized","hashes":{rel:normalized_sha256(root/rel) for rel in SOURCE_PATHS}},
        "rollout":{
            "source_timeline_name":SOURCE_TIMELINE_NAME,"target_timeline_name":TARGET_TIMELINE_NAME,"authority":AUTHORITY,
            "authority_semantic_sha256":authority.get("semantic_sha256"),"center_corrections":14,"protected_exit_updates":3,
            "quarantine_removed":1,"expected_physical_textplus_count":113,"recreated_textplus":0,
            "monotonic_non_regression":True,"visual_approval_required":True,"further_rollout_authorized":False,
        },
    }
    cp=queue/"pending"/f"{TASK_ID}_{run_id}.json"; write_json(cp,command)
    receipt={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"command_path":str(cp.relative_to(root)).replace("/","\\"),
             "command_sha256":raw_sha256(cp),"published_at":command["published_at"],"repair_retry":retry_state,
             "manual_action_required":"Workspace > Scripts > VC_Run_Agent_Task"}
    write_json(report_dir/"publication_receipt.json",receipt); write_json(report_dir/"rollout_command.json",command)
    return receipt
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--root",type=Path,default=Path.cwd()); args=p.parse_args()
    try:r=publish(args.root)
    except Exception as exc:
        print(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"},sort_keys=True)); return 1
    print(json.dumps({"ok":True,**r},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
