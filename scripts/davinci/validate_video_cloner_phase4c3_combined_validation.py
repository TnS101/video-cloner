"""Validate immutable Phase 4C3 read-only bridge evidence."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from resolve_workspace.modules import video_cloner_phase4c3_combined_validation as runtime
def validate(root,rid):
    d=root.resolve()/".agent"/"reports"/runtime.TASK_ID/rid; required=("command.json","publication_receipt.json","combined_plan.json","combined_readback.json","visual_evidence_index.json","phase4c3_result.json","status.json","report.json","run.log"); failures=[f"missing:{x}" for x in required if not(d/x).is_file() or(d/x).stat().st_size==0]
    if failures:return {"ok":False,"failures":failures},failures
    r=json.loads((d/"phase4c3_result.json").read_text()); v=json.loads((d/"visual_evidence_index.json").read_text()); checks={"runtime":r.get("ok") is True,"tracks":r.get("track_counts")=={"V1_source":22,"V2_flash":5,"V3_come":1,"V4_occlusion":1},"base":(r.get("base")or{}).get("signature")==runtime.BASE_SIGNATURE,"flash":(r.get("flash")or{}).get("ok") is True,"come":(r.get("come")or{}).get("ok") is True,"matte":(r.get("matte")or{}).get("ok") is True,"overlap":(r.get("overlap")or{}).get("ok") is True,"protected":r.get("protected_signature")==runtime.PROTECTED_SIGNATURE,"source":r.get("source_sha256")==runtime.SOURCE_SHA,"visual":v.get("ok") is True and len(v.get("rows",[]))==7,"unchanged":r.get("unchanged_during_validation") is True,"read_only":r.get("mutation_count")==0 and r.get("save_project_count")==0,"forbidden":not any((r.get("forbidden_operation_counts")or{}).values())}; failures.extend(k for k,vv in checks.items() if not vv);return {"ok":not failures,"task_id":runtime.TASK_ID,"run_id":rid,"checks":checks,"save_project_count":r.get("save_project_count"),"mutation_count":r.get("mutation_count"),"failures":failures},failures
def main():
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--run-id",required=True);a=p.parse_args();value,fail=validate(a.root,a.run_id);d=a.root.resolve()/".agent"/"reports"/runtime.TASK_ID/a.run_id;(d/"validation.json").write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8");print(json.dumps(value,indent=2,sort_keys=True));return int(bool(fail))
if __name__=="__main__":raise SystemExit(main())
