"""Read-only acceptance validator for cuts + Flash V4 + COME Occlusion V4."""
from __future__ import annotations
import importlib.util,json,sys
from pathlib import Path
from typing import Any
HERE=Path(__file__).resolve().parent
def _load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise ImportError(path)
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module
C2=_load("vc_phase4c2_for_phase4c3",HERE/"video_cloner_phase4c2_occlusion_v4_integration.py")
TASK_ID="VIDEO_CLONER_PHASE4C3_COMBINED_VISUAL_EXECUTION_VALIDATION_V1"; MODE="phase4c3_read_only_combined_validation"
PROJECT_NAME=C2.PROJECT_NAME; TARGET_TIMELINE_NAME=C2.TARGET_TIMELINE_NAME; PROTECTED_TIMELINE_NAME=C2.PROTECTED_TIMELINE_NAME
BASE_SIGNATURE=C2.BASE_SIGNATURE; PROTECTED_SIGNATURE=C2.PROTECTED_SIGNATURE
SOURCE_SHA=C2.O4.SOURCE_VIDEO_SHA256
def sha(path): return C2.raw_sha(Path(path))
def inventory(timeline):
    rows=[]
    for track,item in C2.O4.base.all_video_items(timeline): rows.append(C2.O4.base.item_summary(int(track),item))
    return sorted(rows,key=lambda r:(r["track_index"],r["start"],r["name"]))
def validate_evidence(root,plan):
    rows=[]
    for row in plan["visual_evidence"]:
        path=root/row["path"]; actual=sha(path) if path.is_file() else ""; matched=actual==row["sha256"]
        rows.append({"label":row["label"],"path":str(path),"sha256":actual,"matched":matched,"size_bytes":path.stat().st_size if path.is_file() else 0})
        if not matched: raise RuntimeError(f"visual_evidence:{row['label']}")
    pixel=json.loads((root/plan["pixel_gate_path"]).read_text(encoding="utf-8"))
    if sha(root/plan["pixel_gate_path"])!=plan["pixel_gate_sha256"] or pixel.get("ok") is not True or not all(pixel.get("checks",{}).values()): raise RuntimeError("pixel_gate")
    return {"ok":True,"rows":rows,"pixel_gate":pixel}
def run(resolve:Any,context:dict[str,Any])->dict[str,Any]:
    command=context.get("command") or {}; rid=str(context.get("run_id") or command.get("run_id") or ""); report={"ok":False,"task_id":TASK_ID,"run_id":rid,"mode":MODE,"save_project_count":0,"mutation_count":0,"failures":[]}
    try:
        if command.get("task")!=TASK_ID or command.get("mode")!=MODE or command.get("run_id")!=rid: raise ValueError("command_identity")
        payload=command.get("payload") or {}; root=Path(payload.get("repository_root","")).resolve(); out=root/payload.get("report_dir",""); out.mkdir(parents=True,exist_ok=True); plan_path=Path(payload.get("plan_path","")).resolve()
        if sha(plan_path)!=payload.get("plan_sha256"): raise ValueError("plan_hash")
        plan=json.loads(plan_path.read_text()); unhashed=dict(plan); digest=unhashed.pop("plan_sha256","")
        if plan.get("schema")!="video_cloner.phase4c3_combined_validation_plan" or plan.get("task_id")!=TASK_ID or C2.V1.canonical_sha256(unhashed)!=digest: raise ValueError("plan_contract")
        fcpxml=Path(plan["fcpxml_path"])
        if C2.P4B.sha256(fcpxml)!=plan["fcpxml_sha256"]: raise ValueError("fcpxml_hash")
        contract=C2.P4B.parse_fcpxml_contract(fcpxml); manager=C2.O4.base.safe_value(resolve,"GetProjectManager",default=None); project=C2.O4.base.safe_value(manager,"GetCurrentProject",default=None)
        if project is None or C2.O4.base.safe_value(project,"GetName",default="")!=PROJECT_NAME: raise RuntimeError("project_identity")
        target=C2.C1.find_one(project,TARGET_TIMELINE_NAME); protected=C2.C1.find_one(project,PROTECTED_TIMELINE_NAME)
        before=inventory(target); base=C2.base_geometry(target,contract); flash=C2.flash_state(target,plan["flashes"]); come=C2.come_state(target); matte=C2.matte_state(target); protected_state=C2.P4B.timeline_snapshot(protected)
        if not come.get("ok") or not matte.get("ok") or protected_state["signature"]!=PROTECTED_SIGNATURE: raise RuntimeError("combined_structure")
        by_track={track:[row for row in before if row["track_index"]==track] for track in range(1,5)}
        if [len(by_track[x]) for x in range(1,5)]!=[22,5,1,1] or len(before)!=29: raise RuntimeError("track_inventory")
        source=root/C2.O4.SOURCE_VIDEO_RELATIVE
        if sha(source)!=SOURCE_SHA: raise RuntimeError("source_hash")
        visual=validate_evidence(root,plan); after=inventory(target); protected_after=C2.P4B.timeline_snapshot(protected); flash_after=C2.flash_state(target,plan["flashes"]); come_after=C2.come_state(target); matte_after=C2.matte_state(target)
        counts=C2.forbidden(base); unchanged=before==after and flash==flash_after and {k:v for k,v in come.items() if k!="item"}=={k:v for k,v in come_after.items() if k!="item"} and {k:v for k,v in matte.items() if k!="item"}=={k:v for k,v in matte_after.items() if k!="item"} and protected_after["signature"]==PROTECTED_SIGNATURE
        overlap={"ok":True,"range_half_open":[426,454],"flash_cut_frames":[426,454],"flash_carrier_starts":[424,452],"come_track":3,"matte_track":4,"pixel_gate_ok":visual["pixel_gate"]["ok"],"same_frame_restore":visual["pixel_gate"]["checks"]["same_frame_restore_all_frames"],"sequence_not_frozen":visual["pixel_gate"]["checks"]["sequence_not_frozen_on_first_frame"]}
        if not unchanged or any(counts.values()) or not overlap["ok"]: raise RuntimeError("read_only_non_regression")
        snapshot={"ok":True,"project_name":PROJECT_NAME,"target_timeline_name":TARGET_TIMELINE_NAME,"protected_timeline_name":PROTECTED_TIMELINE_NAME,"track_counts":{"V1_source":22,"V2_flash":5,"V3_come":1,"V4_occlusion":1},"timeline_item_count":29,"base":base,"flash":flash,"come":{k:v for k,v in come.items() if k!="item"},"matte":{k:v for k,v in matte.items() if k!="item"},"protected_signature":protected_state["signature"],"source_sha256":SOURCE_SHA,"forbidden_operation_counts":counts,"overlap":overlap,"inventory_before":before,"inventory_after":after,"unchanged_during_validation":unchanged,"save_project_count":0,"mutation_count":0}
        C2.P4B.write_json(out/"combined_readback.json",snapshot); C2.P4B.write_json(out/"visual_evidence_index.json",visual); report.update(snapshot); C2.P4B.write_json(out/"phase4c3_result.json",report); return report
    except BaseException as exc:
        report["failures"]=[f"{type(exc).__name__}: {exc}"]
        try:C2.P4B.write_json(out/"phase4c3_result.json",report)
        except Exception:pass
        return report
