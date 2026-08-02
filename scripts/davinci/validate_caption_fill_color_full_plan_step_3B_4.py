#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any, Dict
VERSION="validate_caption_fill_color_full_plan_step_3B_4B_v1_0"

def load(path:Path)->Dict[str,Any]:
    with path.open("r",encoding="utf-8-sig") as h:data=json.load(h)
    if not isinstance(data,dict):raise ValueError("plan is not an object")
    return data

def canon(data:Dict[str,Any])->str:
    clean=dict(data);clean.pop("plan_hash",None)
    return hashlib.sha256(json.dumps(clean,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()

def write(path:Path,data:Dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="\n") as h:json.dump(data,h,ensure_ascii=False,indent=2);h.write("\n")

def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--plan",required=True);p.add_argument("--output",required=True);a=p.parse_args()
    plan=load(Path(a.plan));items=[r for r in (plan.get("items") or []) if isinstance(r,dict)];s=plan.get("summary") or {}
    sources={}
    modes={}
    for row in items:
        source=str((row.get("target_fill") or {}).get("source") or "");sources[source]=sources.get(source,0)+1
        mode=str(row.get("protected_effect_mode") or "");modes[mode]=modes.get(mode,0)+1
    checks={
        "plan_ok":bool(plan.get("ok")),"step":plan.get("step")=="Major Step 3B.4B","plan_hash":plan.get("plan_hash")==canon(plan),
        "v3_item_count":len(items)==116,"direct_event_fill_count":sources.get("caption_style_event.colors.fill",0)==66,
        "group_estimated_fill_count":sources.get("classified_caption_group.estimated_text_color",0)==50,
        "target_fill_complete":all(isinstance((r.get("target_fill") or {}).get("hex"),str) and len((r.get("target_fill") or {}).get("hex"))==7 for r in items),
        "effect_modes":modes.get("shadow_glow_only",0)==99 and modes.get("outline_and_shadow",0)==14 and modes.get("none",0)==3,
        "animation_target_count":sum(len(r.get("protected_animation_targets") or []) for r in items)==16,
        "summary_counts":int(s.get("direct_event_fill_count") or 0)==66 and int(s.get("group_estimated_fill_count") or 0)==50,
        "forbidden_policy_absent":((plan.get("policy") or {}).get("forbidden")=="darkest_text_component_on_low_confidence"),
        "no_plan_failures":not plan.get("failures"),
    }
    failures=[k for k,v in checks.items() if not v]
    result={"ok":not failures,"step":"Major Step 3B.4B","validator_version":VERSION,"plan":str(Path(a.plan).resolve()),"checks":checks,"summary":s,"warnings":plan.get("warnings") or [],"failures":failures}
    write(Path(a.output),result);print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result["ok"] else 1
if __name__=="__main__":raise SystemExit(main())
