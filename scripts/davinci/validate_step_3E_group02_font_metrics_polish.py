#!/usr/bin/env python3
"""Validate one completed Group-02 font/metrics polish run."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
from typing import Any,Dict
TASK_ID='DZSQH7AUHJT_STEP_3E_GROUP02_FONT_METRICS_POLISH_V1'; MODE='STEP_3E_GROUP02_FONT_METRICS_POLISH'; TARGET_TIMELINE_NAME='DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_fontmetrics_v1'
EXPECTED={"polished_instance_count":2,"unchanged_item_count":115,"final_textplus_count":117}
REQUIRED_ARTIFACTS=("source_contract_verification.json","polish_plan.json","polish_preflight.json","polish_carrier_append.json","polish_application.json","polish_readback_before_save.json","persistent_readback.json","report.json","status.json")
def load_json(path:Path)->Dict[str,Any]:
 v=json.loads(path.read_text(encoding="utf-8-sig"));
 if not isinstance(v,dict): raise ValueError(f"expected_object:{path}")
 return v
def write_json(path:Path,payload:Any): path.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def find_command(root:Path,state:str,run_id:str):
 p=root/".agent"/"commands"/state/f"{TASK_ID}_{run_id}.json"; return p if p.is_file() else None
def wait_for_terminal(root:Path,run_id:str,timeout_seconds:float,poll_seconds:float):
 deadline=time.monotonic()+timeout_seconds
 while True:
  for state in ("completed","failed"):
   p=find_command(root,state,run_id)
   if p is not None:return state,p
  if time.monotonic()>=deadline: raise TimeoutError("command_not_terminal")
  time.sleep(poll_seconds)
def validate(root:Path,run_id:str,timeout_seconds:float,poll_seconds:float):
 root=root.resolve(); state,command_path=wait_for_terminal(root,run_id,timeout_seconds,poll_seconds); command=load_json(command_path)
 if command.get("mode")!=MODE or command.get("run_id")!=run_id: raise ValueError("command_identity")
 report_dir=root/str(command.get("artifacts_dir") or "").replace("\\","/")
 missing=[n for n in REQUIRED_ARTIFACTS if not (report_dir/n).is_file()]
 if missing: raise ValueError("runtime_artifacts_missing:"+",".join(missing))
 status=load_json(report_dir/"status.json"); report=load_json(report_dir/"report.json"); plan=load_json(report_dir/"polish_plan.json"); pre=load_json(report_dir/"polish_preflight.json")
 append=load_json(report_dir/"polish_carrier_append.json"); app=load_json(report_dir/"polish_application.json"); read=load_json(report_dir/"polish_readback_before_save.json"); persistent=load_json(report_dir/"persistent_readback.json")
 plans=plan.get("plans") if isinstance(plan.get("plans"),list) else []
 fonts={r.get("visual_token_id"):((r.get("font") or {}).get("font_family"),(r.get("font") or {}).get("font_style")) for r in plans}
 checks={
  "command_completed":state=="completed",
  "status_terminal_ok":status.get("run_id")==run_id and status.get("ok") is True and status.get("running") is False and bool(status.get("finished_at")),
  "report_ok":report.get("ok") is True and report.get("run_id")==run_id,
  "target_retained":report.get("target_timeline_kept") is True and report.get("target_timeline_name")==TARGET_TIMELINE_NAME,
  "source_unchanged":report.get("source_timeline_unchanged") is True,
  "accepted_state_unchanged":report.get("accepted_state_unchanged") is True,
  "save_exactly_once":report.get("save_call_count")==1,
  "font_metrics_polish_applied":report.get("font_metrics_polish_applied") is True,
  "full_rollout_not_authorized":report.get("full_rollout_authorized") is False,
  "plan_ok":plan.get("ok") is True and len(plans)==2,
  "font_candidates_exact":fonts=={"vf_02_already":("Verdana","Bold"),"vf_02_decorative_glyph":("Segoe Script","Regular")},
  "preflight_ok":pre.get("ok") is True and pre.get("source_total_textplus_count")==117 and pre.get("source_v2_item_count")==0 and pre.get("source_group_motion_readback_ok") is True,
  "append_ok":append.get("ok") is True and append.get("requested_count")==2 and append.get("assigned_count")==2,
  "application_ok":app.get("ok") is True and app.get("complete") is True and app.get("instance_count")==2,
  "readback_ok":read.get("ok") is True and all((read.get("checks") or {}).values()),
  "persistent_ok":persistent.get("ok") is True and all((persistent.get("checks") or {}).values()),
  "persistent_font_metrics":persistent.get("font_metrics_polish_applied") is True and persistent.get("font_visual_approval_required") is True,
  "visual_approval_required":persistent.get("visual_approval_required") is True,
 }
 for k,v in EXPECTED.items(): checks["report_"+k]=report.get(k)==v
 result={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"command_state":state,"target_timeline_name":TARGET_TIMELINE_NAME,"checks":checks,"counts":EXPECTED,"font_candidates":fonts,"visual_approval_required":True,"full_rollout_authorized":False,"ok":all(checks.values())}
 write_json(report_dir/"font_metrics_polish_validation.json",result)
 if not result["ok"]: raise ValueError("validation_failed:"+",".join(k for k,v in checks.items() if not v))
 return result
def main():
 p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=Path.cwd());p.add_argument("--run-id",required=True);p.add_argument("--timeout-seconds",type=float,default=30.0);p.add_argument("--poll-seconds",type=float,default=0.25);a=p.parse_args()
 try:r=validate(a.root,a.run_id,a.timeout_seconds,a.poll_seconds)
 except Exception as exc: print(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"},sort_keys=True));return 1
 print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
