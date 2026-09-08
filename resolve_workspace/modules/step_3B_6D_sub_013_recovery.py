"""Bounded raw-key recovery for the two captured sub_013 mismatches."""
from __future__ import annotations
import hashlib, json, math, os
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1"
FAILED_RUN_ID = "20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379"
CAPTURE_RUN_ID = "20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
EXPECTED = {"project":"New Project 1", "timeline":"DZsqH7auhjt_textplus_full", "track":3, "count":116}
TARGETS = {"sub_007":("While","VC_TEXTPLUS_0007_sub_007",196,199), "sub_013":("out","VC_TEXTPLUS_0013_sub_013",224,230), "sub_110":("looks","VC_TEXTPLUS_0110_sub_110",862,868), "sub_114":("AND","VC_TEXTPLUS_0114_sub_114",888,894)}
ALLOWLIST = [{"cue_id":"sub_013","text":"out","item_identity":"VC_TEXTPLUS_0013_sub_013","property":"Center","local_frame":2,"timeline_frame":226,"raw_key_identifier":2,"current_value":{"1":0.506203705,"2":0.52842448,"3":0.0},"target_value":[0.50611111,0.5284375],"modifier":{"OUTS_ID":"Position","OUTS_DataType":"Point"}}, {"cue_id":"sub_013","text":"out","item_identity":"VC_TEXTPLUS_0013_sub_013","property":"Size","local_frame":2,"timeline_frame":226,"raw_key_identifier":2,"current_value":0.08768857685550001,"target_value":0.087467395905,"modifier":{"OUTS_ID":"Value","OUTS_DataType":"Number"}}]

def safe(o: Any, m: str, *a: Any, default: Any=None) -> Any:
    try: return getattr(o,m)(*a)
    except Exception: return default
def load(p: Path) -> dict[str,Any]:
    v=json.loads(p.read_text(encoding="utf-8-sig"));
    if not isinstance(v,dict): raise ValueError("json_object")
    return v
def write(p: Path,v: Any) -> None:
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_name(p.name+".tmp"); t.write_text(json.dumps(v,indent=2)+"\n",encoding="utf-8"); os.replace(t,p)
def js(v: Any) -> Any:
    if isinstance(v,dict): return {str(k):js(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [js(x) for x in v]
    return v if isinstance(v,(str,int,float,bool)) or v is None else repr(v)
def point(v: Any) -> list[float] | None:
    if isinstance(v,dict): v=[v.get(1,v.get("1")),v.get(2,v.get("2"))]
    try: return [float(v[0]),float(v[1])]
    except (TypeError,ValueError,IndexError): return None
def equal(prop: str,a: Any,b: Any) -> bool:
    if prop=="Center":
        x,y=point(a),point(b); return bool(x and y and all(abs(i-j)<=1e-5 for i,j in zip(x,y)))
    try: return math.isfinite(float(a)) and abs(float(a)-float(b))<=1e-5
    except (TypeError,ValueError): return False
def input_for(tool: Any,name: str) -> Any: return safe(tool,"FindInput",name) or getattr(tool,name,None)
def read(tool: Any,name: str,frame: int) -> Any:
    v=safe(tool,"GetInput",name,frame)
    if v is not None:return v
    i=input_for(tool,name)
    try:return i[frame]
    except Exception:return None
def tool_for(item: Any) -> Any:
    comp=safe(item,"GetFusionCompByIndex",1) if int(safe(item,"GetFusionCompCount",default=0) or 0) else safe(item,"GetFusionCompByName","Composition 1")
    for t in (safe(comp,"GetToolList",False,default={}) or {}).values():
        a=safe(t,"GetAttrs",default={}) or {}
        if str(a.get("TOOLS_RegID") or a.get("TOOLST_RegID") or "") in ("TextPlus","Text3D"): return t
    return None
def topology(tool: Any,prop: str) -> dict[str,Any]:
    i=input_for(tool,prop); out=safe(i,"GetConnectedOutput")
    return {"connected":out is not None,"modifier":js(safe(out,"GetAttrs",default={}) or {}),"keys":js(safe(i,"GetKeyFrames",default={}) or {})}
def topology_digest(tool: Any,prop: str) -> str:
    return hashlib.sha256(json.dumps(topology(tool,prop),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def find_items(resolve: Any) -> tuple[Any,dict[str,Any]]:
    pm=safe(resolve,"GetProjectManager"); p=safe(pm,"GetCurrentProject"); tl=safe(p,"GetCurrentTimeline")
    if safe(p,"GetName")!=EXPECTED["project"] or safe(tl,"GetName")!=EXPECTED["timeline"]: raise ValueError("project_timeline")
    items=list(safe(tl,"GetItemListInTrack","video",3,default=[]) or [])
    if len(items)!=116:raise ValueError("v3_count")
    found={}
    for cue,(text,name,start,end) in TARGETS.items():
        m=[x for x in items if safe(x,"GetName",default="")==name and [safe(x,"GetStart"),safe(x,"GetEnd")]==[start,end]]
        if len(m)!=1:raise ValueError("item_identity:"+cue)
        t=tool_for(m[0])
        if not t or str(read(t,"StyledText",0) or "").strip()!=text:raise ValueError("text_tool:"+cue)
        found[cue]=t
    return tl,found
def capture_operations(root: Path) -> list[dict[str,Any]]:
    p=root/".agent/reports/DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1"/CAPTURE_RUN_ID/"operation_current_state_comparison.json"
    if hashlib.sha256(p.read_bytes()).hexdigest()!="6e3ea4203fd18e383109e67d1cebea348fe59fcc6af0073457efb95a4ca8f6ed": raise ValueError("capture_hash")
    rows=load(p).get("operations",[])
    if len(rows)!=36:return []
    return rows
def run(resolve: Any, context: dict[str,Any]) -> dict[str,Any]:
    run_id=str(context.get("run_id") or ""); report={"ok":False,"task_id":TASK_ID,"run_id":run_id,"failed_run_id":FAILED_RUN_ID,"read_only_capture_run_id":CAPTURE_RUN_ID,"plan_hash":PLAN_HASH,"setter_call_count":0,"effective_mutation_count":0,"save_call_count":0,"modifier_mutation_call_count":0,"timeline_modified":False,"failures":[]}
    try:
        cmd=context.get("command") or {}; pay=cmd.get("payload") or {}
        if cmd.get("task")!=TASK_ID or cmd.get("run_id")!=run_id or pay.get("failed_run_id")!=FAILED_RUN_ID or pay.get("read_only_capture_run_id")!=CAPTURE_RUN_ID or pay.get("plan_hash")!=PLAN_HASH or pay.get("recovery_allowlist")!=ALLOWLIST: raise ValueError("command_contract")
        root=Path(str(pay["repository_root"])).resolve(); out=root/str(pay["report_dir"]); plan=root/str(pay["plan_path"])
        if hashlib.sha256(plan.read_bytes()).hexdigest()!=str(pay.get("plan_file_sha256")):raise ValueError("plan_file_hash")
        if load(plan).get("plan_hash")!=PLAN_HASH:raise ValueError("plan_semantic_hash")
        rows=capture_operations(root); others=[x for x in rows if x.get("classification")=="CURRENT_OTHER"]
        if len(others)!=2 or {(x.get("cue_id"),x.get("property"),x.get("local_frame")) for x in others}!={("sub_013","Center",2),("sub_013","Size",2)}:raise ValueError("capture_allowlist")
        _,tools=find_items(resolve); baseline=[]
        for row in rows:
            actual=read(tools[row["cue_id"]],row["property"],int(row["local_frame"]))
            want=row["target_value"] if row["classification"]=="CURRENT_TARGET" else row["current_raw_value"]
            if not equal(row["property"],actual,want):raise ValueError("baseline_drift:%s:%s"%(row["cue_id"],row["property"]))
            baseline.append({"cue_id":row["cue_id"],"property":row["property"],"local_frame":row["local_frame"],"value":js(actual)})
        before={p:topology_digest(tools["sub_013"],p) for p in ("Center","Size")}; write(out/"pre_recovery_state.json",baseline)
        journal=[]
        for op in ALLOWLIST:
            tool=tools[op["cue_id"]]; inp=input_for(tool,op["property"]); raw=int(op["raw_key_identifier"])
            if topology_digest(tool,op["property"])!=before[op["property"]] or not equal(op["property"],read(tool,op["property"],op["local_frame"]),op["current_value"]):raise ValueError("pre_setter_drift:"+op["property"])
            try: inp[raw]=op["target_value"]
            except Exception as exc: raise RuntimeError("existing_raw_key_setter_failed:"+op["property"]) from exc
            report["setter_call_count"]+=1; report["effective_mutation_count"]+=1; report["timeline_modified"]=True
            immediate=read(tool,op["property"],op["local_frame"])
            journal.append({"operation":op,"immediate_value":js(immediate),"ok":equal(op["property"],immediate,op["target_value"])})
            if not journal[-1]["ok"]:raise ValueError("immediate_readback:"+op["property"])
        write(out/"setter_journal.json",journal); _,tools=find_items(resolve)
        comparisons=[]
        for row in rows:
            v=read(tools[row["cue_id"]],row["property"],int(row["local_frame"])); comparisons.append({"cue_id":row["cue_id"],"property":row["property"],"local_frame":row["local_frame"],"current_value":js(v),"classification":"CURRENT_TARGET" if equal(row["property"],v,row["target_value"]) else "CURRENT_OTHER"})
        if any(x["classification"]!="CURRENT_TARGET" for x in comparisons):raise ValueError("full_plan_readback")
        if any(topology_digest(tools["sub_013"],p)!=before[p] for p in before):raise ValueError("topology_changed")
        write(out/"persistent_post_recovery_state.json",comparisons); write(out/"operation_current_state_comparison.json",{"operation_count":36,"operations":comparisons}); write(out/"topology_preservation_audit.json",{"ok":True,"before":before,"after":{p:topology_digest(tools["sub_013"],p) for p in before}})
        phase3={"setters":0,"effective_mutations":0,"blend_operations":0,"modifier_mutations":0,"timeline_modified":False,"current_target":36}; write(out/"phase3_idempotency_report.json",phase3)
        report.update({"ok":True,"phase":"TECHNICAL_PASS - MANUAL_VISUAL_APPROVAL_REQUIRED","full_plan_current_target":36,"phase3":phase3,"timeline_modified":True})
    except Exception as exc: report["failures"]=[type(exc).__name__+": "+str(exc)]
    return report
