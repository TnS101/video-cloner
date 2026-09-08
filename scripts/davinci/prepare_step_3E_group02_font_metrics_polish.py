#!/usr/bin/env python3
"""Publish exactly one Group-02 font/metrics polish command."""
from __future__ import annotations

import argparse, datetime as dt, hashlib, json, os, uuid
from pathlib import Path
from typing import Any, Dict, List

TASK_ID = 'DZSQH7AUHJT_STEP_3E_GROUP02_FONT_METRICS_POLISH_V1'
MODE = 'STEP_3E_GROUP02_FONT_METRICS_POLISH'
MODULE = "resolve_workspace/modules/step_3E_group02_font_metrics_polish.py"
SOURCE_TIMELINE_NAME = 'DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_v1'
TARGET_TIMELINE_NAME = 'DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_fontmetrics_v1'
CONTRACT = 'data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_font_metrics_v1.json'
SOURCE_MOTION_CONTRACT = 'data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_vertical_motion_v1.json'
BASELINE_TASK = 'DZSQH7AUHJT_STEP_3E_GROUP02_VERTICAL_MOTION_POLISH_V1'
BASELINE_RUN = '20260810T085030365572Z_edaf62cea6b04364a63712904db4718a'
BASELINE_REPORT_ROOT = f".agent/reports/{BASELINE_TASK}/{BASELINE_RUN}"
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
FONT_FILES = (Path(r"C:/Windows/Fonts/verdanab.ttf"), Path(r"C:/Windows/Fonts/segoesc.ttf"))

SOURCE_PATHS = (
    MODULE, CONTRACT, SOURCE_MOTION_CONTRACT,
    "resolve_workspace/modules/step_3E_group02_vertical_motion_polish.py",
    "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py",
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    f"{BASELINE_REPORT_ROOT}/polish_validation.json",
    f"{BASELINE_REPORT_ROOT}/persistent_readback.json",
    f"{BASELINE_REPORT_ROOT}/polish_plan.json",
    f"{BASELINE_REPORT_ROOT}/report.json",
)

def utc_now(): return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00","Z")
def run_id_now(): return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex
def normalized_sha256(path:Path): return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n").replace(b"\r",b"\n")).hexdigest()
def raw_sha256(path:Path): return hashlib.sha256(path.read_bytes()).hexdigest()
def load_json(path:Path):
    value=json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value,dict): raise ValueError(f"expected_object:{path}")
    return value
def write_json(path:Path,payload:Any):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(tmp,path)
def active_commands(root:Path)->List[Path]:
    rows=[]; q=root/".agent"/"commands"
    for state in ("pending","running"):
        d=q/state
        if d.is_dir(): rows.extend(sorted(d.glob("*.json")))
    return rows

def publish(root:Path)->Dict[str,Any]:
    root=root.resolve()
    if not (root/"AGENTS.md").is_file(): raise ValueError("repository_root")
    active=active_commands(root)
    if active: raise ValueError(f"active_command:{active[0].name}")
    for relative in (*SOURCE_PATHS,ACCEPTED_STATE):
        if not (root/relative).is_file(): raise ValueError(f"source_missing:{relative}")
    for font_path in FONT_FILES:
        if not font_path.is_file(): raise ValueError(f"font_missing:{font_path}")

    validation=load_json(root/f"{BASELINE_REPORT_ROOT}/polish_validation.json")
    persistent=load_json(root/f"{BASELINE_REPORT_ROOT}/persistent_readback.json")
    report=load_json(root/f"{BASELINE_REPORT_ROOT}/report.json")
    if validation.get("ok") is not True or validation.get("run_id")!=BASELINE_RUN: raise ValueError("baseline_validation")
    if persistent.get("ok") is not True or not all((persistent.get("checks") or {}).values()): raise ValueError("baseline_persistent")
    if report.get("ok") is not True or report.get("final_textplus_count")!=117 or report.get("polished_instance_count")!=2: raise ValueError("baseline_report")

    contract=load_json(root/CONTRACT)
    if contract.get("task_id")!=TASK_ID or contract.get("ok") is not True or contract.get("group_id")!="vf_group_02_already_decorated": raise ValueError("contract")
    plans=contract.get("plans") if isinstance(contract.get("plans"),list) else []
    if len(plans)!=2: raise ValueError("plan_count")
    fonts={row["visual_token_id"]:(row.get("font") or {}).get("font_family") for row in plans}
    if fonts!={"vf_02_already":"Verdana","vf_02_decorative_glyph":"Segoe Script"}: raise ValueError(f"font_contract:{fonts}")
    if any(row.get("transcript_timing_promoted_to_authority") is not False for row in plans): raise ValueError("transcript_timing")

    queue=root/".agent"/"commands"
    for state in ("pending","running","completed","failed"):
        (queue/state).mkdir(parents=True,exist_ok=True)
        if list((queue/state).glob(f"{TASK_ID}_*.json")): raise ValueError(f"task_command_exists:{state}")
    report_root=root/".agent"/"reports"/TASK_ID
    if report_root.exists() and any(p.is_dir() for p in report_root.iterdir()): raise ValueError("task_report_exists")
    report_root.mkdir(parents=True,exist_ok=True)
    run_id=run_id_now(); report_dir=report_root/run_id; report_dir.mkdir()
    command={
      "schema_version":1,"task_id":TASK_ID,"run_id":run_id,"mode":MODE,"module":MODULE,"published_at":utc_now(),
      "artifacts_dir":str(report_dir.relative_to(root)).replace("/","\\"),
      "status_path":str((report_dir/"status.json").relative_to(root)).replace("/","\\"),
      "log_path":str((report_dir/"run.log").relative_to(root)).replace("/","\\"),
      "report_path":str((report_dir/"report.json").relative_to(root)).replace("/","\\"),
      "accepted_state_path":ACCEPTED_STATE.replace("/","\\"),"accepted_state_sha256":raw_sha256(root/ACCEPTED_STATE),
      "source_contract":{"version":1,"algorithm":SOURCE_HASH_ALGORITHM,"hashes":{r:normalized_sha256(root/r) for r in SOURCE_PATHS}},
      "polish":{"source_timeline_name":SOURCE_TIMELINE_NAME,"target_timeline_name":TARGET_TIMELINE_NAME,"group_id":contract["group_id"],
        "contract":CONTRACT,"token_ids":[r["visual_token_id"] for r in plans],"target_names":[r["target_name"] for r in plans],
        "target_range":[245,270],"font_metrics_polish_applied":True,"expected_final_textplus_count":117,"full_rollout_authorized":False},
    }
    command_path=queue/"pending"/f"{TASK_ID}_{run_id}.json"; write_json(command_path,command)
    receipt={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"command_path":str(command_path.relative_to(root)).replace("/","\\"),
      "command_sha256":raw_sha256(command_path),"published_at":command["published_at"],"manual_action_required":"Workspace > Scripts > VC_Run_Agent_Task"}
    write_json(report_dir/"publication_receipt.json",receipt); write_json(report_dir/"polish_command.json",command); return receipt

def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=Path.cwd()); a=p.parse_args()
    try: result=publish(a.root)
    except Exception as exc: print(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"},sort_keys=True)); return 1
    print(json.dumps({"ok":True,**result},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
