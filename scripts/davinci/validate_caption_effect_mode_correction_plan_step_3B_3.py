#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any, Dict

VERSION = "validate_caption_effect_mode_correction_plan_step_3B_3C_v1_0"

def load(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as h:
        data=json.load(h)
    if not isinstance(data,dict): raise ValueError("plan is not an object")
    return data

def canon(data: Dict[str, Any]) -> str:
    clean=dict(data); clean.pop("plan_hash",None)
    raw=json.dumps(clean,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="\n") as h:
        json.dump(data,h,ensure_ascii=False,indent=2); h.write("\n")

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--plan",required=True); p.add_argument("--output",required=True); a=p.parse_args()
    plan=load(Path(a.plan)); items=plan.get("items") or []; summary=plan.get("summary") or {}
    modes={}
    for row in items:
        mode=(((row.get("effect") or {}).get("classification") or {}).get("mode"))
        modes[mode]=modes.get(mode,0)+1
    checks={
        "plan_ok": bool(plan.get("ok")),
        "step": plan.get("step")=="Major Step 3B.3C",
        "plan_hash": plan.get("plan_hash")==canon(plan),
        "v3_item_count": len(items)==116,
        "glow_target_count": modes.get("shadow_glow_only",0)==99 and int(summary.get("glow_target_count") or 0)==99,
        "retained_outline_count": modes.get("outline_and_shadow",0)==14 and int(summary.get("retained_outline_count") or 0)==14,
        "no_effect_count": modes.get("none",0)==3 and int(summary.get("no_effect_count") or 0)==3,
        "animation_target_count": sum(len(row.get("protected_animation_targets") or []) for row in items)==16,
        "no_plan_failures": not plan.get("failures"),
    }
    result={"ok":all(checks.values()),"step":"Major Step 3B.3C","validator_version":VERSION,"plan":str(Path(a.plan).resolve()),"checks":checks,"summary":summary,"warnings":plan.get("warnings") or [],"failures":[k for k,v in checks.items() if not v]}
    write(Path(a.output),result); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["ok"] else 1
if __name__=="__main__": raise SystemExit(main())
