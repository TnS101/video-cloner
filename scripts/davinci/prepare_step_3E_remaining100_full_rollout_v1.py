#!/usr/bin/env python3
"""Publish exactly one Step 3E remaining-100 rollout command."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, uuid
from pathlib import Path
from typing import Any, Dict, List

TASK_ID = "DZSQH7AUHJT_STEP_3E_REMAINING100_FULL_ROLLOUT_V1"
MODE = "STEP_3E_REMAINING100_FULL_ROLLOUT"
MODULE = "resolve_workspace/modules/step_3E_remaining100_full_rollout_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_17tokens_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_all117_v1"
AUTHORITY = "artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/remaining100_visual_authority_v1.json"
AUTHORITY_VALIDATION = "artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/remaining100_visual_authority_validation.json"
STEP3E3_REPORT = ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/report.json"
STEP3E3_PERSISTENT = ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json"
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE, AUTHORITY, AUTHORITY_VALIDATION, STEP3E3_REPORT, STEP3E3_PERSISTENT,
    "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py",
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/VC_Agent_Bridge.py",
)
EXPECTED_REMAINING=100; EXPECTED_PROTECTED=17; EXPECTED_ROWS=803; EXPECTED_TOTAL=117

def utc_now(): return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00","Z")
def run_id_now(): return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex
def normalized_sha256(path: Path): return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n").replace(b"\r",b"\n")).hexdigest()
def raw_sha256(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()
def load_json(path: Path):
    value=json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value,dict): raise ValueError(f"expected_object:{path}")
    return value
def write_json(path: Path,payload: Any):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+".tmp"); tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(tmp,path)
def active_commands(root: Path)->List[Path]:
    rows=[]; q=root/".agent"/"commands"
    for state in ("pending","running"):
        d=q/state
        if d.is_dir(): rows.extend(sorted(d.glob("*.json")))
    return rows

def publish(root: Path)->Dict[str,Any]:
    root=root.resolve()
    if not (root/"AGENTS.md").is_file(): raise ValueError("repository_root")
    active=active_commands(root)
    if active: raise ValueError(f"active_command:{active[0].name}")
    for rel in (*SOURCE_PATHS,ACCEPTED_STATE):
        if not (root/rel).is_file(): raise ValueError(f"source_missing:{rel}")
    authority=load_json(root/AUTHORITY); summary=authority.get("summary") or {}; policy=authority.get("authority_policy") or {}
    if authority.get("task_id")!="DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1" or authority.get("ok") is not True: raise ValueError("authority")
    expected={"remaining_instance_count":EXPECTED_REMAINING,"protected_v4_token_count":EXPECTED_PROTECTED,"explicit_frame_row_count":EXPECTED_ROWS,"accepted_visual_primary_instance_count":39,"source_pixel_redetected_instance_count":61,"low_confidence_pixel_readback_count":0}
    for k,v in expected.items():
        if summary.get(k)!=v: raise ValueError(f"authority_summary:{k}")
    if policy.get("transcript_timing_authority") is not False or policy.get("remaining_caption_rollout_authorized") is not False: raise ValueError("authority_policy")
    validation=load_json(root/AUTHORITY_VALIDATION)
    if validation.get("ok") is not True: raise ValueError("authority_validation")
    prior=load_json(root/STEP3E3_REPORT); persistent=load_json(root/STEP3E3_PERSISTENT)
    if prior.get("ok") is not True or prior.get("target_timeline_name")!=SOURCE_TIMELINE_NAME or prior.get("final_textplus_count")!=EXPECTED_TOTAL or prior.get("save_call_count")!=1: raise ValueError("step3e3_report")
    if persistent.get("ok") is not True or len(persistent.get("rows") or [])!=EXPECTED_PROTECTED or not all((persistent.get("checks") or {}).values()): raise ValueError("step3e3_persistent")
    q=root/".agent"/"commands"
    for state in ("pending","running","completed","failed"):
        (q/state).mkdir(parents=True,exist_ok=True)
        if list((q/state).glob(f"{TASK_ID}_*.json")): raise ValueError(f"task_command_exists:{state}")
    report_root=root/".agent"/"reports"/TASK_ID
    if report_root.exists() and any(p.is_dir() for p in report_root.iterdir()): raise ValueError("task_report_exists")
    report_root.mkdir(parents=True,exist_ok=True); run_id=run_id_now(); report_dir=report_root/run_id; report_dir.mkdir()
    command={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"mode":MODE,"module":MODULE,"published_at":utc_now(),"artifacts_dir":str(report_dir.relative_to(root)).replace("/","\\"),"status_path":str((report_dir/"status.json").relative_to(root)).replace("/","\\"),"log_path":str((report_dir/"run.log").relative_to(root)).replace("/","\\"),"report_path":str((report_dir/"report.json").relative_to(root)).replace("/","\\"),"accepted_state_path":ACCEPTED_STATE.replace("/","\\"),"accepted_state_sha256":raw_sha256(root/ACCEPTED_STATE),"source_contract":{"version":1,"algorithm":SOURCE_HASH_ALGORITHM,"hashes":{rel:normalized_sha256(root/rel) for rel in SOURCE_PATHS}},"rollout":{"source_timeline_name":SOURCE_TIMELINE_NAME,"target_timeline_name":TARGET_TIMELINE_NAME,"authority":AUTHORITY,"authority_semantic_sha256":authority.get("semantic_sha256"),"remaining_instance_count":EXPECTED_REMAINING,"protected_v4_count":EXPECTED_PROTECTED,"explicit_frame_row_count":EXPECTED_ROWS,"expected_final_textplus_count":EXPECTED_TOTAL,"user_authorized_this_rollout":True,"transcript_timing_authority":False,"static_style_policy":"export_import_current_source_comp","fade_polish_deferred":True,"visual_approval_required":True}}
    command_path=q/"pending"/f"{TASK_ID}_{run_id}.json"; write_json(command_path,command)
    receipt={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"command_path":str(command_path.relative_to(root)).replace("/","\\"),"command_sha256":raw_sha256(command_path),"published_at":command["published_at"],"manual_action_required":"Workspace > Scripts > VC_Run_Agent_Task"}; write_json(report_dir/"publication_receipt.json",receipt); write_json(report_dir/"rollout_command.json",command); return receipt

def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=Path.cwd()); a=p.parse_args()
    try: result=publish(a.root)
    except Exception as exc: print(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"},sort_keys=True)); return 1
    print(json.dumps({"ok":True,**result},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
