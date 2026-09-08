"""Validate one completed Phase 4C2 bridge run."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from resolve_workspace.modules import video_cloner_phase4c2_occlusion_v4_integration as runtime
def load(p): return json.loads(p.read_text(encoding="utf-8-sig"))
def validate(root,rid,mode):
    d=root.resolve()/".agent"/"reports"/runtime.TASK_ID/rid; required=("command.json","publication_receipt.json","occlusion_plan.json","phase4c2_occlusion_result.json","status.json","report.json","run.log"); failures=[f"missing:{x}" for x in required if not (d/x).is_file() or (d/x).stat().st_size==0]
    if failures:return {"ok":False,"failures":failures},failures
    result=load(d/"phase4c2_occlusion_result.json"); flash=result.get("flash_after") or {}; come=result.get("come_after") or {}; matte=result.get("matte_after") or {}; counts=result.get("forbidden_operation_counts") or {}
    checks={"runtime":result.get("ok") is True,"mode":result.get("run_mode")==mode,"base":(result.get("base_after") or {}).get("signature")==runtime.BASE_SIGNATURE,"protected":(result.get("protected_after") or {}).get("signature")==runtime.PROTECTED_SIGNATURE,"flash":flash.get("ok") is True and flash.get("count")==5 and flash.get("neutral_carrier_count")==5 and flash.get("source_video_carrier_count")==0,"come":come.get("ok") is True and come.get("enabled2_all_zero") is True and come.get("enabled3_all_zero") is True,"matte":matte.get("ok") is True and (matte.get("summary") or {}).get("track_index")==4,"forbidden":counts and not any(counts.values()),"save":result.get("save_project_count")== (1 if mode=="apply" else 0)}
    if mode=="apply": checks.update({"pixel_gate":((result.get("pixel_gate") or {}).get("evidence") or {}).get("ok") is True,"created":result.get("created_come")==1 and result.get("created_mattes")==1 and result.get("created_fusion")==1})
    else: checks["idempotent"]=result.get("idempotent") is True and all(result.get(k)==0 for k in ("created_come","created_mattes","created_fusion","media_import_count","track_add_count"))
    failures.extend(k for k,v in checks.items() if not v); summary={"ok":not failures,"task_id":runtime.TASK_ID,"run_id":rid,"run_mode":mode,"checks":checks,"come":come,"matte":matte,"save_project_count":result.get("save_project_count"),"failures":failures}; return summary,failures
def main():
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,required=True); p.add_argument("--run-id",required=True); p.add_argument("--run-mode",choices=("apply","idempotency"),required=True); a=p.parse_args(); value,fail=validate(a.root,a.run_id,a.run_mode); d=a.root.resolve()/".agent"/"reports"/runtime.TASK_ID/a.run_id; (d/"validation.json").write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8"); print(json.dumps(value,indent=2,sort_keys=True)); return int(bool(fail))
if __name__=="__main__": raise SystemExit(main())
