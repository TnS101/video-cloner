#!/usr/bin/env python3
"""Validate one completed remaining-100 rollout run."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
from typing import Any, Dict
TASK_ID="DZSQH7AUHJT_STEP_3E_REMAINING100_FULL_ROLLOUT_V1"
TARGET_TIMELINE_NAME="DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_all117_v1"
EXPECTED={"remaining_instance_count":100,"protected_v4_count":17,"explicit_frame_row_count":803,"final_textplus_count":117,"save_call_count":1,"source_timeline_unchanged":True,"accepted_state_unchanged":True,"target_timeline_kept":True,"remaining_caption_rollout_completed":True,"visual_approval_required":True,"fade_polish_deferred":True,"further_rollout_authorized":False}
def load(path:Path)->Dict[str,Any]:
    v=json.loads(path.read_text(encoding="utf-8-sig"));
    if not isinstance(v,dict): raise ValueError(f"expected_object:{path}")
    return v
def write(path:Path,v:Any): path.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def locate(root:Path,run_id:str,timeout:float,poll:float):
    q=root/".agent"/"commands"; deadline=time.time()+timeout
    while time.time()<=deadline:
        for state in ("completed","failed","running","pending"):
            matches=list((q/state).glob(f"{TASK_ID}_{run_id}.json")) if (q/state).is_dir() else []
            if matches: return state,matches[0]
        time.sleep(poll)
    raise ValueError("command_not_found")
def validate(root:Path,run_id:str,timeout:float,poll:float)->Dict[str,Any]:
    root=root.resolve(); state,cmd_path=locate(root,run_id,timeout,poll); cmd=load(cmd_path)
    if state!="completed": raise ValueError(f"command_state:{state}")
    report_dir=root/Path(str(cmd["artifacts_dir"]).replace("\\","/")); report=load(report_dir/"report.json"); plan=load(report_dir/"rollout_plan.json"); setup=load(report_dir/"rollout_timeline_setup.json"); exports=load(report_dir/"source_comp_exports.json"); append=load(report_dir/"rollout_carrier_append.json"); application=load(report_dir/"rollout_application.json"); readback=load(report_dir/"rollout_readback_before_save.json"); persistent=load(report_dir/"persistent_readback.json")
    checks={
        "command_identity":cmd.get("task_id")==TASK_ID and cmd.get("run_id")==run_id and (cmd.get("rollout") or {}).get("user_authorized_this_rollout") is True,
        "report_ok":report.get("ok") is True and report.get("run_id")==run_id and not report.get("failures"),
        "plan_ok":plan.get("ok") is True and plan.get("remaining_instance_count")==100 and plan.get("protected_v4_count")==17 and plan.get("explicit_frame_row_count")==803 and len(plan.get("plans") or [])==100,
        "export_ok":exports.get("ok") is True and exports.get("exported_count")==100 and len(exports.get("rows") or [])==100,
        "setup_ok":setup.get("ok") is True and (setup.get("delete") or {}).get("deleted")==100 and len(setup.get("protected_after_delete") or [])==17 and all(r.get("ok") for r in setup.get("protected_after_delete") or []),
        "append_ok":append.get("ok") is True and append.get("requested_count")==100 and append.get("assigned_count")==100 and append.get("batch_count")==17,
        "application_ok":application.get("ok") is True and application.get("complete") is True and application.get("instance_count")==100 and application.get("explicit_frame_row_count")==803 and all(r.get("static_style_preserved") is True for r in application.get("rows") or []),
        "readback_ok":readback.get("ok") is True and readback.get("explicit_frame_row_count")==803 and len(readback.get("rows") or [])==100 and all(r.get("ok") for r in readback.get("rows") or []) and len(readback.get("protected_v4_rows") or [])==17 and all(r.get("ok") for r in readback.get("protected_v4_rows") or []) and all((readback.get("checks") or {}).values()),
        "persistent_ok":persistent.get("ok") is True and persistent.get("explicit_frame_row_count")==803 and len(persistent.get("rows") or [])==100 and all(r.get("ok") for r in persistent.get("rows") or []) and len(persistent.get("protected_v4_rows") or [])==17 and all(r.get("ok") for r in persistent.get("protected_v4_rows") or []) and all((persistent.get("checks") or {}).values()),
        "persistent_policy":persistent.get("remaining_caption_rollout_completed") is True and persistent.get("visual_approval_required") is True and persistent.get("fade_polish_deferred") is True and persistent.get("further_rollout_authorized") is False,
    }
    for k,v in EXPECTED.items(): checks[f"report_{k}"]=report.get(k)==v
    result={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"command_state":state,"target_timeline_name":TARGET_TIMELINE_NAME,"checks":checks,"counts":EXPECTED,"visual_approval_required":True,"fade_polish_deferred":True,"further_rollout_authorized":False,"ok":all(checks.values())}; write(report_dir/"remaining100_full_rollout_validation.json",result)
    if not result["ok"]: raise ValueError("validation_failed:"+",".join(k for k,v in checks.items() if not v))
    return result

def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=Path.cwd()); p.add_argument("--run-id",required=True); p.add_argument("--timeout-seconds",type=float,default=30.0); p.add_argument("--poll-seconds",type=float,default=.25); a=p.parse_args()
    try:r=validate(a.root,a.run_id,a.timeout_seconds,a.poll_seconds)
    except Exception as exc: print(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"},sort_keys=True)); return 1
    print(json.dumps(r,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
