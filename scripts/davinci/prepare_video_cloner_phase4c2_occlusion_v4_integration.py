"""Publish one exact standalone COME Occlusion V4 bridge command."""
from __future__ import annotations
import argparse,json,os,re,sys
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from resolve_workspace.modules import video_cloner_phase4c2_occlusion_v4_integration as runtime
from scripts.davinci import prepare_video_cloner_phase4c1_flash_v4_integration as c1prepare
MODULE="resolve_workspace/modules/video_cloner_phase4c2_occlusion_v4_integration.py"
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_name(path.name+".tmp"); temp.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(temp,path)
def rid():
    now=datetime.now(timezone.utc); return f"{now:%Y%m%dT%H%M%S}{now.microsecond//1000:03d}Z_{uuid4().hex}"
def build_plan(authority):
    flashes=c1prepare.build_plan(authority)["flashes"]
    plan={"schema":"video_cloner.phase4c2_occlusion_v4_plan","schema_version":1,"task_id":runtime.TASK_ID,"architecture":"final_occlusion_composition_v4_native_index_same_frame_pixel_restore","project_name":runtime.PROJECT_NAME,"target_timeline_name":runtime.TARGET_TIMELINE_NAME,"protected_timeline_name":runtime.PROTECTED_TIMELINE_NAME,"protected_signature":runtime.PROTECTED_SIGNATURE,"base_signature":runtime.BASE_SIGNATURE,"come":{"name":runtime.COME_NAME,"text":"COME","start_frame":426,"end_frame_exclusive":454,"duration_frames":28,"track":3,"Enabled2":0.0,"Enabled3":0.0},"matte":{"name":runtime.MATTE_NAME,"start_frame":426,"end_frame_exclusive":454,"duration_frames":28,"track":4,"architecture":"same_frame_pixel_restore_rgba_v4","native_source_range":[426,454]},"source_video_sha256":runtime.O4.SOURCE_VIDEO_SHA256,"anchor_mask_hashes":{str(k):v for k,v in runtime.O4.ANCHOR_HASHES.items()},"flashes":flashes,"forbidden":{"caption_removal":True,"inpainting":True,"source_replacement":True}}
    plan["plan_sha256"]=runtime.V1.canonical_sha256(plan); return plan
def publish(root,authority,fcpxml,fcpxml_sha,python_exe,mode,run_id=None):
    root=root.resolve(); fcpxml=fcpxml.resolve(); authority=authority.resolve()
    if mode not in {"apply","idempotency"} or runtime.P4B.sha256(fcpxml)!=fcpxml_sha or not Path(python_exe).is_file(): raise ValueError("input_contract")
    plan=build_plan(json.loads(authority.read_text(encoding="utf-8-sig"))); runtime.verify_authority(root,plan)
    run_id=run_id or rid()
    if not re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}",run_id): raise ValueError("run_id")
    queue=root/".agent"/"commands"
    for state in ("pending","running","completed","failed"): (queue/state).mkdir(parents=True,exist_ok=True)
    if any(any((queue/s).glob("*.json")) for s in ("pending","running")): raise ValueError("active_command")
    rel=f".agent/reports/{runtime.TASK_ID}/{run_id}"; out=root/rel; out.mkdir(parents=True,exist_ok=False); plan_path=out/"occlusion_plan.json"; write(plan_path,plan)
    command={"schema_version":1,"task":runtime.TASK_ID,"run_id":run_id,"module":MODULE,"mode":runtime.MODE,"status_path":f"{rel}/status.json","log_path":f"{rel}/run.log","report_path":f"{rel}/report.json","artifacts_dir":rel,"occlusion":{"external_python":str(Path(python_exe).resolve())},"payload":{"repository_root":str(root),"report_dir":rel,"run_mode":mode,"plan_path":str(plan_path),"plan_sha256":runtime.raw_sha(plan_path),"fcpxml_path":str(fcpxml),"fcpxml_sha256":fcpxml_sha}}
    pending=queue/"pending"/f"{runtime.TASK_ID}_{run_id}.json"; write(pending,command); write(out/"command.json",command); receipt={"ok":True,"task_id":runtime.TASK_ID,"run_id":run_id,"run_mode":mode,"command_path":str(pending.relative_to(root)).replace("\\","/"),"command_sha256":runtime.raw_sha(pending),"plan_sha256":runtime.raw_sha(plan_path)}; write(out/"publication_receipt.json",receipt); return receipt
def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,required=True); p.add_argument("--authority",type=Path,required=True); p.add_argument("--fcpxml",type=Path,required=True); p.add_argument("--fcpxml-sha256",required=True); p.add_argument("--python",required=True); p.add_argument("--run-mode",choices=("apply","idempotency"),required=True); p.add_argument("--run-id"); a=p.parse_args()
    try: value=publish(a.root,a.authority,a.fcpxml,a.fcpxml_sha256,a.python,a.run_mode,a.run_id)
    except Exception as e: print(f"FAIL: {type(e).__name__}: {e}"); return 1
    print(json.dumps(value,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
