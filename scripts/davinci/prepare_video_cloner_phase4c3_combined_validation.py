"""Publish one read-only Phase 4C3 validation command."""
from __future__ import annotations
import argparse,json,os,re,sys
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from resolve_workspace.modules import video_cloner_phase4c3_combined_validation as runtime
from scripts.davinci import prepare_video_cloner_phase4c1_flash_v4_integration as c1
MODULE="resolve_workspace/modules/video_cloner_phase4c3_combined_validation.py"
C1_RUN="20260818T155057413Z_bc06f111358f4bf8916dc121111459c4"; C2_RUN="20260818T161210850Z_a881603cc00b44fbb812313196448885"
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_name(path.name+".tmp"); temp.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(temp,path)
def new_id():
    now=datetime.now(timezone.utc); return f"{now:%Y%m%dT%H%M%S}{now.microsecond//1000:03d}Z_{uuid4().hex}"
def build_plan(root,authority,fcpxml):
    flashes=c1.build_plan(authority)["flashes"]
    c1base=Path(f".agent/reports/VIDEO_CLONER_PHASE4C1_ACCEPTED_FLASH_V4_INTEGRATION/{C1_RUN}/visual_evidence")
    c2base=Path(f".agent/reports/VIDEO_CLONER_PHASE4C2_ACCEPTED_OCCLUSION_V4_INTEGRATION/{C2_RUN}/render_target_occlusion_v4")
    sources=[("first_flash",c1base/"cut_0096/flash_0096_00000096.png"),("flash_377",c1base/"cut_0377/flash_0377_00000377.png"),("overlap_start_426",c2base/"target_occlusion_v4_00000426.png"),("active_overlap_431",c2base/"target_occlusion_v4_00000431.png"),("active_overlap_443",c2base/"target_occlusion_v4_00000443.png"),("overlap_end_453",c2base/"target_occlusion_v4_00000453.png"),("final_flash",c1base/"cut_0758/flash_0758_00000758.png")]
    evidence=[]
    for label,rel in sources:
        path=root/rel
        if not path.is_file() or path.stat().st_size==0: raise ValueError(f"visual:{label}")
        evidence.append({"label":label,"path":str(rel).replace("\\","/"),"sha256":runtime.sha(path)})
    pixel=Path(f".agent/reports/VIDEO_CLONER_PHASE4C2_ACCEPTED_OCCLUSION_V4_INTEGRATION/{C2_RUN}/pre_save_pixel_validation_v4.json")
    plan={"schema":"video_cloner.phase4c3_combined_validation_plan","schema_version":1,"task_id":runtime.TASK_ID,"project_name":runtime.PROJECT_NAME,"target_timeline_name":runtime.TARGET_TIMELINE_NAME,"protected_timeline_name":runtime.PROTECTED_TIMELINE_NAME,"base_signature":runtime.BASE_SIGNATURE,"protected_signature":runtime.PROTECTED_SIGNATURE,"source_sha256":runtime.SOURCE_SHA,"fcpxml_path":str(fcpxml.resolve()),"fcpxml_sha256":runtime.C2.P4B.sha256(fcpxml),"flashes":flashes,"visual_evidence":evidence,"pixel_gate_path":str(pixel).replace("\\","/"),"pixel_gate_sha256":runtime.sha(root/pixel),"save_project_expected":0,"mutation_expected":0}
    plan["plan_sha256"]=runtime.C2.V1.canonical_sha256(plan); return plan
def publish(root,authority_path,fcpxml,run_id=None):
    root=root.resolve(); fcpxml=fcpxml.resolve(); authority=json.loads(authority_path.resolve().read_text(encoding="utf-8-sig")); plan=build_plan(root,authority,fcpxml); run_id=run_id or new_id()
    if not re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}",run_id):raise ValueError("run_id")
    queue=root/".agent"/"commands"
    for state in ("pending","running","completed","failed"):(queue/state).mkdir(parents=True,exist_ok=True)
    if any(any((queue/s).glob("*.json")) for s in ("pending","running")):raise ValueError("active_command")
    rel=f".agent/reports/{runtime.TASK_ID}/{run_id}"; out=root/rel; out.mkdir(parents=True,exist_ok=False); plan_path=out/"combined_plan.json"; write(plan_path,plan)
    command={"schema_version":1,"task":runtime.TASK_ID,"run_id":run_id,"module":MODULE,"mode":runtime.MODE,"status_path":f"{rel}/status.json","log_path":f"{rel}/run.log","report_path":f"{rel}/report.json","payload":{"repository_root":str(root),"report_dir":rel,"plan_path":str(plan_path),"plan_sha256":runtime.sha(plan_path),"read_only":True,"save_project":False}}
    pending=queue/"pending"/f"{runtime.TASK_ID}_{run_id}.json"; write(pending,command); write(out/"command.json",command); receipt={"ok":True,"task_id":runtime.TASK_ID,"run_id":run_id,"command_path":str(pending.relative_to(root)).replace("\\","/"),"command_sha256":runtime.sha(pending),"plan_sha256":runtime.sha(plan_path),"read_only":True}; write(out/"publication_receipt.json",receipt); return receipt
def main():
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--authority",type=Path,required=True);p.add_argument("--fcpxml",type=Path,required=True);p.add_argument("--run-id");a=p.parse_args()
    try:value=publish(a.root,a.authority,a.fcpxml,a.run_id)
    except Exception as e:print(f"FAIL: {type(e).__name__}: {e}");return 1
    print(json.dumps(value,indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
