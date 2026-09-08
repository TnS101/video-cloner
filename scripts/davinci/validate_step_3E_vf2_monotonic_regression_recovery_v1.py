#!/usr/bin/env python3
"""Validate one completed monotonic VF2 regression-recovery Resolve run."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any, Mapping

TASK_ID="DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_V1"
TARGET_TIMELINE_NAME="DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_vf2_regression_recovery_v1"
def load_json(p:Path):
    v=json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(v,dict): raise ValueError(f"expected_object:{p}")
    return v
def validate(root:Path, run_id:str)->dict[str,Any]:
    report_dir=root/".agent"/"reports"/TASK_ID/run_id
    report=load_json(report_dir/"report.json")
    persistent=load_json(report_dir/"persistent_readback.json")
    if report.get("task_id")!=TASK_ID or report.get("run_id")!=run_id: raise ValueError("report_identity")
    if report.get("ok") is not True: raise ValueError("runtime_not_ok")
    expected_report={
        "center_correction_count":14,"quarantine_removed_count":1,"protected_exit_update_count":3,
        "final_textplus_count":113,"v2_item_count":0,"save_call_count":1,
        "monotonic_non_regression":True,"source_timeline_unchanged":True,
        "accepted_state_unchanged":True,"target_timeline_kept":True,"occlusion_unchanged":True,
    }
    for k,v in expected_report.items():
        if report.get(k)!=v: raise ValueError(f"report:{k}:{report.get(k)}")
    if report.get("target_timeline_name")!=TARGET_TIMELINE_NAME: raise ValueError("target_name")
    if persistent.get("ok") is not True or persistent.get("task_id")!=TASK_ID or persistent.get("run_id")!=run_id: raise ValueError("persistent_identity")
    checks=persistent.get("checks")
    if not isinstance(checks,Mapping) or not checks or not all(v is True for v in checks.values()): raise ValueError("persistent_checks")
    mono=persistent.get("monotonic")
    if not isinstance(mono,Mapping) or mono.get("ok") is not True: raise ValueError("monotonic")
    mchecks=mono.get("checks")
    if not isinstance(mchecks,Mapping) or not all(v is True for v in mchecks.values()): raise ValueError("monotonic_checks")
    rows=mono.get("rows") or []
    if len(rows)!=114 or not all(isinstance(x,Mapping) and x.get("ok") is True for x in rows): raise ValueError("monotonic_rows")
    kinds={}
    for row in rows:kinds[str(row.get("kind") or "")]=kinds.get(str(row.get("kind") or ""),0)+1
    if kinds.get("center_only")!=14 or kinds.get("protected_exit_center_only")!=3 or kinds.get("quarantine")!=1 or kinds.get("unchanged")!=96:
        raise ValueError(f"monotonic_partition:{kinds}")
    result={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"ok":True,"checks":{
        "runtime_ok":True,"persistent_ok":True,"monotonic_non_regression":True,"target_physical_textplus":113,
        "source_unchanged":True,"accepted_state_unchanged":True,"visual_approval_required":True,
        "further_rollout_authorized":False,
    }}
    out=report_dir/"validation.json"; out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--root",type=Path,required=True); p.add_argument("--run-id",required=True); a=p.parse_args()
    try:r=validate(a.root.resolve(),a.run_id)
    except Exception as exc:
        print(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"},sort_keys=True)); return 1
    print(json.dumps(r,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
