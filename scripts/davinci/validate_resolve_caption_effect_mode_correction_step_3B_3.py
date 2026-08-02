#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any, Dict

VERSION="validate_resolve_caption_effect_mode_step_3B_3C_v1_1_supported_workspace_versions"
SUPPORTED_WORKSPACE_VERSIONS = {
    "resolve_caption_effect_mode_step_3B_3C_v1_0_glow_classifier",
    "resolve_caption_effect_mode_step_3B_3C_v1_1_prepare_precondition_guard",
}

def load(path: Path)->Dict[str,Any]:
    with path.open("r",encoding="utf-8-sig") as h: data=json.load(h)
    if not isinstance(data,dict): raise ValueError(f"Expected object: {path}")
    return data

def canon(data: Dict[str,Any])->str:
    clean=dict(data); clean.pop("plan_hash",None)
    return hashlib.sha256(json.dumps(clean,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()

def write(path: Path,data: Dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="\n") as h: json.dump(data,h,ensure_ascii=False,indent=2); h.write("\n")

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--plan",required=True); p.add_argument("--report",required=True); p.add_argument("--mode",choices=("first_application_pass","idempotent_second_run"),required=True); p.add_argument("--output",required=True); a=p.parse_args()
    plan=load(Path(a.plan)); report=load(Path(a.report)); s=report.get("summary") or {}
    expected_run="first_application" if a.mode=="first_application_pass" else "idempotent_second_run"
    checks={
        "plan_ok": bool(plan.get("ok")), "plan_hash_valid": plan.get("plan_hash")==canon(plan),
        "report_ok": bool(report.get("ok")), "workspace_version": report.get("workspace_version") in SUPPORTED_WORKSPACE_VERSIONS,
        "report_run_mode": report.get("run_mode")==expected_run, "plan_hash_match": report.get("plan_hash")==plan.get("plan_hash"),
        "v3_candidate_count": int(s.get("v3_candidate_count") or 0)==116,
        "plan_item_count": int(s.get("plan_item_count") or 0)==116,
        "glow_target_count": int(s.get("glow_target_count") or 0)==99,
        "retained_outline_count": int(s.get("retained_outline_count") or 0)==14,
        "no_effect_count": int(s.get("no_effect_count") or 0)==3,
        "mapped_count": int(s.get("mapped_count") or 0)==116,
        "glow_verified_count": int(s.get("glow_verified_count") or 0)==99,
        "retained_outline_verified_count": int(s.get("retained_outline_verified_count") or 0)==14,
        "no_effect_verified_count": int(s.get("no_effect_verified_count") or 0)==3,
        "fill_integrity": int(s.get("fill_integrity_failure_count") or 0)==0 and int(s.get("protected_fill_verified_count") or 0)==116,
        "animation_integrity": int(s.get("animation_integrity_failure_count") or 0)==0 and int(s.get("protected_animation_target_count") or 0)==16 and int(s.get("protected_animation_verified_count") or 0)==16,
        "identity_integrity": int(s.get("identity_integrity_failure_count") or 0)==0,
        "layout_integrity": int(s.get("layout_integrity_failure_count") or 0)==0,
        "timeline_integrity": int(s.get("timeline_integrity_failure_count") or 0)==0 and bool((report.get("track_integrity") or {}).get("ok")),
        "rollback_not_performed": int(s.get("rollback_performed_count") or 0)==0,
        "failed_count": int(s.get("failed_count") or 0)==0,
        "no_report_failures": not report.get("failures"),
    }
    if a.mode=="first_application_pass":
        checks["first_run_modified_count"]=int(s.get("modified_count") or 0)==99
        checks["first_run_already_correct_count"]=int(s.get("already_correct_count") or 0)==17
    else:
        checks["second_run_modified_count"]=int(s.get("modified_count") or 0)==0
        checks["second_run_already_correct_count"]=int(s.get("already_correct_count") or 0)==116
    failures=[k for k,v in checks.items() if not v]
    result={"ok":not failures,"step":"Major Step 3B.3C","validator_version":VERSION,"mode":a.mode,"plan":str(Path(a.plan).resolve()),"report":str(Path(a.report).resolve()),"summary":s,"checks":checks,"warnings":report.get("warnings") or [],"failures":failures,"output":str(Path(a.output).resolve())}
    write(Path(a.output),result); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["ok"] else 1
if __name__=="__main__": raise SystemExit(main())
