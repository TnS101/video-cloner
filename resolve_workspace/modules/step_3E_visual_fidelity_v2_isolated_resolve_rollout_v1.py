"""Apply the accepted Visual Fidelity V2 authority on one isolated Resolve timeline.

The source post-metrics timeline remains read-only. Eighty-seven source-backed
Text+ items are recreated at source-pixel windows; one sparse short-token false
positive is removed; nine residual ambiguities stay byte/placement-preserved;
three protected V4 captions receive Center-only source exit trajectories. The
validated foreground RGBA matte is moved above every physical Text+ layer.

No transcript timing, geometry-only semantic promotion, or detector-score alpha
is used. Fade refinement remains deferred. One save only on success.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_ISOLATED_RESOLVE_ROLLOUT_V1"
MODE = "STEP_3E_VISUAL_FIDELITY_V2_ISOLATED_RESOLVE_ROLLOUT"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_visual_fidelity_v2_v1"
AUTHORITY_RELATIVE_PATH = "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1/visual_fidelity_v2_resolve_rollout_authority_v1.json"
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
EXPECTED_SOURCE_PHYSICAL = 114
EXPECTED_TARGET_PHYSICAL = 113
EXPECTED_RECREATE = 87
EXPECTED_PRESERVED = 9
EXPECTED_QUARANTINE = 1
EXPECTED_PROTECTED = 17
EXPECTED_PROTECTED_EXITS = 3
EXPECTED_STRUCTURAL_TARGET = 96
TRACK_MIN = 3
TRACK_MAX = 7
APPEND_BATCH_SIZE = 6


def _module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module); return module

def load_post() -> Any:
    return _module(Path(__file__).with_name("step_3E_post_visual_metrics_polish_v1.py"), "vc_post_metrics_for_vf2_rollout")

def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict): raise ValueError(f"expected_object:{path}")
    return value

def hex_rgb(value: str, prefix: str = "") -> dict[str, float]:
    text = str(value or "").strip()
    if len(text) != 7 or not text.startswith("#"): raise ValueError(f"fill_hex:{value}")
    suffix = prefix or "1"
    return {f"Red{suffix}":int(text[1:3],16)/255.0, f"Green{suffix}":int(text[3:5],16)/255.0, f"Blue{suffix}":int(text[5:7],16)/255.0}

def authority_partition(authority: Mapping[str, Any]) -> dict[str, Any]:
    if authority.get("task_id") != "DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1" or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    summary = authority.get("summary") or {}; policy = authority.get("policy") or {}
    expected = {"recreate_total":87,"preserved_unresolved":9,"quarantined_remove":1,"protected_total":17,"protected_exit_updates":3,"target_physical_textplus":113,"occlusion_span_count":1}
    for key, value in expected.items():
        if summary.get(key) != value: raise ValueError(f"authority_summary:{key}")
    if policy.get("transcript_timing_authority") is not False or policy.get("geometry_only_semantic_promotion") is not False: raise ValueError("semantic_policy")
    if policy.get("residual_unresolved_mutation_authorized") is not False or policy.get("source_absence_claims") != 0: raise ValueError("unresolved_policy")
    if policy.get("occlusion_contract") != "foreground_rgba_above_textplus" or policy.get("fade_polish_deferred") is not True: raise ValueError("occlusion_fade_policy")
    recreate = [dict(x) for x in authority.get("recreate_plans") or [] if isinstance(x, Mapping)]
    preserve = [dict(x) for x in authority.get("preserve_unresolved") or [] if isinstance(x, Mapping)]
    quarantine = [dict(x) for x in authority.get("quarantine_remove") or [] if isinstance(x, Mapping)]
    exits = [dict(x) for x in authority.get("protected_exit_updates") or [] if isinstance(x, Mapping)]
    if (len(recreate),len(preserve),len(quarantine),len(exits)) != (87,9,1,3): raise ValueError("authority_partition")
    groups = [{str(x.get("target_name") or "") for x in rows} for rows in (recreate,preserve,quarantine,exits)]
    if any("" in x for x in groups): raise ValueError("blank_target")
    if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]: raise ValueError("structural_scope_overlap")
    occlusion = authority.get("occlusion") if isinstance(authority.get("occlusion"), Mapping) else {}
    if occlusion.get("required_layer_order") != "foreground_rgba_above_textplus": raise ValueError("occlusion_authority")
    return {"recreate":recreate,"preserve":preserve,"quarantine":quarantine,"exits":exits,"occlusion":dict(occlusion)}

def capture_source_size(base: Any, item: Any) -> float:
    comp=base.get_comp(item); tool=base.get_text_tool(comp)
    if comp is None or tool is None: raise RuntimeError("source_comp_or_text_tool")
    try: value=float(base.read_input(tool,"Size",0))
    except (TypeError,ValueError): raise RuntimeError("source_size")
    if value <= 0: raise RuntimeError("source_size")
    return value

def materialize_plan(plan: Mapping[str, Any], source_size: float) -> dict[str, Any]:
    row=dict(plan); start,end=[int(v) for v in row["target_range"]]; duration=end-start
    if duration < 1: raise ValueError(f"duration:{row.get('instance_id')}")
    position=[dict(x) for x in row.get("position_keys") or []]
    if [int(x["local_frame"]) for x in position] != list(range(duration)): raise ValueError(f"position_dense:{row.get('instance_id')}")
    target_size=float(row.get("target_size") or 0.0) if row.get("size_action")=="source_target" else float(source_size)
    if target_size <= 0: raise ValueError(f"size:{row.get('instance_id')}")
    row["size_keys"]=[{"timeline_frame":start+i,"local_frame":i,"value":target_size} for i in range(duration)]
    row["opacity_keys"]=[{"timeline_frame":start+i,"local_frame":i,"factor":1.0} for i in range(duration)]
    row["target_track"]=0
    return row

def static_overrides(plan: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if plan.get("case_action") == "source_override": values["StyledText"] = str(plan.get("display_text") or "")
    if plan.get("fill_action") == "source_override": values.update(hex_rgb(str(plan.get("fill_hex") or ""), "1"))
    if plan.get("kind") == "visual_companion_recovered":
        font=plan.get("font_override") or {}; style=plan.get("style_lock") or {}
        values.update({"StyledText":str(plan.get("display_text") or ""),"Font":str(font.get("font_family") or ""),"Style":str(font.get("font_style") or ""),"Enabled2":0.0})
        values.update(hex_rgb(str(plan.get("fill_hex") or "#F6F3EF"),"1"))
        shadow=style.get("shadow") or {}
        values["Enabled3"] = 1.0 if shadow.get("enabled") is True else 0.0
        if shadow.get("enabled") is True:
            values.update(hex_rgb(str(shadow.get("color") or "#6A6A6A"),"3")); values["Alpha3"]=float(shadow.get("opacity") or 0.28)
    return values

def apply_static_overrides(base: Any, pilot: Any, item: Any, values: Mapping[str, Any]) -> dict[str, Any]:
    if not values: return {"ok":True,"values":{}}
    comp=base.get_comp(item); tool=base.get_text_tool(comp)
    if comp is None or tool is None: return {"ok":False,"error":"comp_or_text_tool"}
    result=pilot.set_static_inputs(tool, dict(values))
    return {"ok":result.get("ok") is True,"values":dict(values),"result":result}

def point_matches(base: Any, actual: Any, expected: Any, tolerance: float = 0.0025) -> bool:
    """Compare Resolve point values after normalizing both operands.

    Resolve readback may expose points as list-like values while persisted JSON
    snapshots may use keyed point structures. The shared legacy helper normalized
    only the actual operand, which made a valid keyed expected value raise
    ``KeyError: 0``. Keep comparison strict while treating malformed shapes as a
    simple mismatch rather than a runtime exception.
    """
    try:
        normalized_actual = base.normalize_point(actual)
        normalized_expected = base.normalize_point(expected)
        if normalized_actual is None or normalized_expected is None:
            return False
        return all(
            abs(float(normalized_actual[index]) - float(normalized_expected[index])) <= float(tolerance)
            for index in (0, 1)
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return False

def read_center_keys(base: Any, item: Any, keys: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    comp=base.get_comp(item); tool=base.get_text_tool(comp)
    if comp is None or tool is None: return {"ok":False,"error":"comp_or_text_tool"}
    rows=[]
    for key in keys:
        actual=base.read_input(tool,"Center",int(key["local_frame"])); expected=key["value"]
        rows.append({"local_frame":int(key["local_frame"]),"expected":expected,"actual":base.json_safe(actual),"matched":point_matches(base,actual,expected,0.003)})
    return {"rows":rows,"ok":bool(rows and all(x["matched"] for x in rows))}

def capture_noncenter(base: Any, old: Any, item: Any, local_frames: Sequence[int]) -> dict[str, Any]:
    comp=base.get_comp(item); tool=base.get_text_tool(comp)
    if comp is None or tool is None: raise RuntimeError("protected_comp")
    frames=sorted(set(int(x) for x in local_frames))
    return {"static_style":old.capture_static_style(base,item),"size":[base.json_safe(base.read_input(tool,"Size",f)) for f in frames],"opacity1":[base.json_safe(base.read_input(tool,"Opacity1",f)) for f in frames]}

def same_json(left: Any, right: Any) -> bool:
    return json.dumps(left,sort_keys=True,separators=(",",":"),default=str)==json.dumps(right,sort_keys=True,separators=(",",":"),default=str)

def capture_protected_snapshot(base: Any, old: Any, timeline: Any, name: str) -> dict[str, Any]:
    track,item=base.find_named_item(timeline,name)
    if item is None: raise RuntimeError(f"protected_source_missing:{name}")
    summary=base.item_summary(int(track or 0),item); duration=int(summary.get("duration") or 0)
    if duration < 1: raise RuntimeError(f"protected_duration:{name}")
    comp=base.get_comp(item); tool=base.get_text_tool(comp)
    if comp is None or tool is None: raise RuntimeError(f"protected_comp:{name}")
    return {
        "target_name":name,
        "summary":{k:summary.get(k) for k in ("track_index","start","end","duration","fusion_comp_count","media_pool_item_name")},
        "static_style":old.capture_static_style(base,item),
        "center":[base.json_safe(base.read_input(tool,"Center",f)) for f in range(duration)],
        "size":[base.json_safe(base.read_input(tool,"Size",f)) for f in range(duration)],
        "opacity1":[base.json_safe(base.read_input(tool,"Opacity1",f)) for f in range(duration)],
    }

def verify_protected_snapshot(base: Any, old: Any, timeline: Any, snapshot: Mapping[str, Any], exit_keys: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    name=str(snapshot["target_name"]); track,item=base.find_named_item(timeline,name)
    if item is None: return {"target_name":name,"ok":False,"error":"missing"}
    summary=base.item_summary(int(track or 0),item); expected_summary=snapshot.get("summary") or {}; duration=int(expected_summary.get("duration") or 0)
    comp=base.get_comp(item); tool=base.get_text_tool(comp)
    if comp is None or tool is None: return {"target_name":name,"ok":False,"error":"comp_or_text_tool"}
    updated={int(x["local_frame"]):x["value"] for x in (exit_keys or [])}
    center_ok=True
    for frame,source_value in enumerate(snapshot.get("center") or []):
        actual=base.read_input(tool,"Center",frame); expected=updated.get(frame,source_value)
        center_ok=center_ok and point_matches(base,actual,expected,0.003 if frame in updated else 1e-4)
    size_ok=all(old.scalar_match(base.read_input(tool,"Size",f),float(v),1e-4) for f,v in enumerate(snapshot.get("size") or []))
    opacity_ok=all(old.scalar_match(base.read_input(tool,"Opacity1",f),float(v),1e-4) for f,v in enumerate(snapshot.get("opacity1") or []))
    summary_ok=all(summary.get(k)==expected_summary.get(k) for k in expected_summary)
    style_ok=old.style_matches(base,item,snapshot.get("static_style") or {})
    checks={"summary":summary_ok,"static_style":style_ok,"center":center_ok,"size":size_ok,"opacity1":opacity_ok}
    return {"target_name":name,"checks":checks,"updated_center_frames":sorted(updated),"ok":all(checks.values())}

def apply_protected_exit(base: Any, old: Any, visual: Any, timeline: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    track,item=base.find_named_item(timeline,str(row["target_name"]))
    if item is None: return {"ok":False,"error":"missing","target_name":row["target_name"]}
    start=int(base.item_summary(int(track or 0),item).get("start") or 0)
    keys=[{"timeline_frame":int(x["timeline_frame"]),"local_frame":int(x["timeline_frame"])-start,"value":list(x["value"])} for x in row.get("position_keys") or []]
    if any(int(x["local_frame"])<0 for x in keys): return {"ok":False,"error":"local_frame"}
    before=capture_noncenter(base,old,item,[x["local_frame"] for x in keys])
    comp=base.get_comp(item); tool=base.get_text_tool(comp)
    write=visual.apply_center_series(tool,keys) if tool is not None else {"ok":False}
    read=read_center_keys(base,item,keys)
    after=capture_noncenter(base,old,item,[x["local_frame"] for x in keys])
    return {"target_name":row["target_name"],"visual_token_id":row["visual_token_id"],"track":track,"keys":keys,"write":write,"readback":read,"noncenter_unchanged":same_json(before,after),"before_noncenter":before,"after_noncenter":after,"ok":bool(write.get("ok") and read.get("ok") and same_json(before,after))}

def caption_track_max(base: Any, timeline: Any) -> int:
    tracks=[]
    for track,item in base.all_video_items(timeline):
        name=base.item_name(item)
        if name.startswith("VC_TEXTPLUS_") or name.startswith("VC_VISUAL_FIRST_FULL_"): tracks.append(int(track))
    if not tracks: raise RuntimeError("caption_tracks")
    return max(tracks)

def occlusion_inventory(base: Any, timeline: Any, name: str) -> list[dict[str, Any]]:
    return [base.item_summary(int(track),item) for track,item in base.all_video_items(timeline) if base.item_name(item)==name]

def move_occlusion_above_text(base: Any, v6: Any, media_pool: Any, timeline: Any, authority: Mapping[str, Any]) -> dict[str, Any]:
    name=str(authority["item_name"]); start,end=[int(v) for v in authority["source_record_range"]]; duration=end-start
    matches=[(int(track),item) for track,item in base.all_video_items(timeline) if base.item_name(item)==name]
    if len(matches)!=1: return {"ok":False,"error":f"source_matte_count:{len(matches)}"}
    old_track,item=matches[0]; media_item=base.safe_value(item,"GetMediaPoolItem",default=None)
    if media_item is None: return {"ok":False,"error":"matte_media_pool_item"}
    before=base.item_summary(old_track,item)
    deletion=base.delete_items(timeline,[item]); time.sleep(0.15)
    if not deletion.get("ok") or occlusion_inventory(base,timeline,name): return {"ok":False,"error":"matte_delete","deletion":deletion}
    target_track=caption_track_max(base,timeline)+1
    track_setup=base.ensure_video_tracks(timeline,target_track)
    if not track_setup.get("ok"): return {"ok":False,"error":"matte_track_setup","track_setup":track_setup}
    carrier={"media_pool_item":media_item,"source_start":0}
    spec={"cue_id":"foreground_rgba","name":name,"text":"","target_range":[start,end],"target_track":target_track}
    append=v6.append_batch_by_placement(media_pool,timeline,carrier,[spec])
    rows=occlusion_inventory(base,timeline,name)
    ok=bool(append.get("ok") and len(rows)==1 and int(rows[0].get("track_index") or 0)==target_track and int(rows[0].get("start") or -1)==start and int(rows[0].get("end") or -1)==end and target_track>caption_track_max(base,timeline))
    return {"name":name,"before":before,"deletion":deletion,"append":base.json_safe({k:v for k,v in append.items() if k!="assigned"}),"target_track":target_track,"rows":rows,"ok":ok}

def verify_occlusion(base: Any, timeline: Any, authority: Mapping[str, Any]) -> dict[str, Any]:
    name=str(authority["item_name"]); start,end=[int(v) for v in authority["source_record_range"]]
    rows=occlusion_inventory(base,timeline,name); max_caption=caption_track_max(base,timeline)
    ok=bool(len(rows)==1 and int(rows[0].get("track_index") or 0)>max_caption and int(rows[0].get("start") or -1)==start and int(rows[0].get("end") or -1)==end and int(rows[0].get("duration") or -1)==end-start)
    return {"rows":rows,"max_caption_track":max_caption,"required_layer_order":"foreground_rgba_above_textplus","ok":ok}

def cleanup_failure(resolve: Any, base: Any, project_manager: Any, project: Any, media_pool: Any, original: Any, original_page: str, accepted_path: Path, accepted_hash: str) -> dict[str, Any]:
    result={"errors":[],"save_call_count":0}
    try:
        target=base.find_timeline(project,TARGET_TIMELINE_NAME) if project is not None else None
        if original is not None and project is not None:
            value,_=base.direct_call(project,"SetCurrentTimeline",original)
            if not value: result["errors"].append("restore_timeline")
        if target is not None and media_pool is not None:
            value,_=base.direct_call(media_pool,"DeleteTimelines",[target])
            if not value: result["errors"].append("delete_target")
        if original_page: base.direct_call(resolve,"OpenPage",original_page)
        if project_manager is not None:
            save=base.save_project(project_manager); result["save_call_count"]=1 if save.get("success") else 0
            if not save.get("success"): result["errors"].append("save_cleanup")
    except BaseException as exc: result["errors"].append(base.compact_exception(exc)); result["traceback"]=traceback.format_exc()
    result["accepted_state_unchanged"]=accepted_path.is_file() and base.raw_sha256(accepted_path)==accepted_hash
    result["ok"]=bool(not result["errors"] and result["accepted_state_unchanged"]); return result

def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    post=load_post(); confirmed=post.load_previous(); old=confirmed.load_old(); full,pilot,v6,base,media,visual=old.load_runtime()
    root=base.repository_root(); command=context.get("command") if isinstance(context,dict) else None
    if not isinstance(command,dict): raise ValueError("command")
    run_id=str(context.get("run_id") or command.get("run_id") or "")
    if command.get("task_id")!=TASK_ID or command.get("mode")!=MODE or not run_id: raise ValueError("command_identity")
    report_dir=base.relative_path(root,command.get("artifacts_dir")); report_dir.mkdir(parents=True,exist_ok=True)
    accepted_path=root/ACCEPTED_STATE_RELATIVE_PATH; accepted_hash=str(command.get("accepted_state_sha256") or "")
    report={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"mode":MODE,"ok":False,"source_timeline_name":SOURCE_TIMELINE_NAME,"target_timeline_name":TARGET_TIMELINE_NAME,"save_call_count":0,"recreated_count":0,"preserved_unresolved_count":0,"quarantine_removed_count":0,"protected_exit_update_count":0,"final_textplus_count":0,"v2_item_count":0,"visual_approval_required":True,"fade_polish_deferred":True,"further_rollout_authorized":False,"failures":[]}
    project_manager=project=media_pool=None; original=None; source=None; target_created=False; original_page=str(base.safe_value(resolve,"GetCurrentPage",default="") or ""); source_before=[]; source_uid=""
    try:
        source_contract=base.verify_source_contract(root,command); base.write_json(report_dir/"source_contract_verification.json",source_contract)
        if not accepted_path.is_file() or base.raw_sha256(accepted_path)!=accepted_hash: raise RuntimeError("accepted_state")
        authority=load_json(root/AUTHORITY_RELATIVE_PATH); part=authority_partition(authority)
        recreate_raw=part["recreate"]; preserve_names={str(x["target_name"]) for x in part["preserve"]}; quarantine_names={str(x["target_name"]) for x in part["quarantine"]}; deletion_names={str(x["target_name"]) for x in recreate_raw}|quarantine_names
        project_manager,project,media_pool,resolve_calls=base.get_project(resolve); original=base.safe_value(project,"GetCurrentTimeline",default=None)
        source=base.find_timeline(project,SOURCE_TIMELINE_NAME)
        if source is None: raise RuntimeError("source_timeline")
        if base.find_timeline(project,TARGET_TIMELINE_NAME) is not None: raise RuntimeError("target_exists")
        source_uid=base.timeline_unique_id(source); source_before=full.timeline_inventory(source)
        source_structural=full.source_textplus_names(source); source_protected=full.visual_first_names(source)
        if len(source_structural)+len(source_protected)!=EXPECTED_SOURCE_PHYSICAL or len(source_protected)!=EXPECTED_PROTECTED: raise RuntimeError("source_physical")
        if full.track_two_item_names(source): raise RuntimeError("source_v2")
        if not deletion_names<=set(source_structural) or not preserve_names<=set(source_structural): raise RuntimeError("source_scope")
        if deletion_names & preserve_names: raise RuntimeError("scope_overlap")
        if deletion_names | preserve_names != set(source_structural): raise RuntimeError("source_scope_partition")
        exit_by_name={str(x["target_name"]):x for x in part["exits"]}
        protected_source_snapshots={name:capture_protected_snapshot(base,old,source,name) for name in source_protected}
        source_preserved_inventory=full.stable_inventory([x for x in source_before if str(x.get("name") or "") in preserve_names])
        source_occlusion=verify_occlusion(base,source,part["occlusion"])
        # Existing source may still carry the matte below some protected tracks; require exact clip, not final order.
        source_occlusion_rows=occlusion_inventory(base,source,str(part["occlusion"]["item_name"]))
        if len(source_occlusion_rows)!=1: raise RuntimeError("source_occlusion_count")
        occ_start,occ_end=[int(v) for v in part["occlusion"]["source_record_range"]]
        occ_row=source_occlusion_rows[0]
        if int(occ_row.get("start") or -1)!=occ_start or int(occ_row.get("end") or -1)!=occ_end or int(occ_row.get("duration") or -1)!=(occ_end-occ_start): raise RuntimeError("source_occlusion_geometry")

        export_dir=report_dir/"source_comp_exports"; export_dir.mkdir(parents=True,exist_ok=True); source_meta={}; export_rows=[]; source_inventory_by_name={str(x.get("name") or ""):x for x in source_before}
        materialized=[]
        for raw in recreate_raw:
            name=str(raw["target_name"]); track,item=base.find_named_item(source,name)
            if item is None: raise RuntimeError(f"source_item:{name}")
            comp_path=export_dir/f"{raw['instance_id']}.comp"; value,call=base.direct_call(item,"ExportFusionComp",str(comp_path),1); file_ok=bool(value and comp_path.is_file() and comp_path.stat().st_size>0)
            if not file_ok: raise RuntimeError(f"source_comp_export:{name}")
            inv=source_inventory_by_name.get(name) or {}; static_style=old.capture_static_style(base,item); source_size=capture_source_size(base,item)
            plan=materialize_plan(raw,source_size); materialized.append(plan)
            source_meta[name]={"comp_path":comp_path,"static_style":static_style,"expected_static_style":dict(static_style),"opacity_bases":old.capture_opacity_bases(base,item,int(inv.get("duration") or 1)),"source_size":source_size}
            export_rows.append({"instance_id":raw["instance_id"],"target_name":name,"track":track,"path":str(comp_path),"sha256":base.raw_sha256(comp_path),"ok":True})
        occupied=[x for x in source_before if str(x.get("name") or "") not in deletion_names]
        plans=old.assign_tracks(materialized,occupied)
        max_duration=max(int(x["target_range"][1])-int(x["target_range"][0]) for x in plans); carrier=base.choose_carrier_source(source,max_duration+1)
        if not carrier.get("ok"): raise RuntimeError("carrier_source")
        base.write_json(report_dir/"rollout_preflight.json",{"resolve_calls":resolve_calls,"source_unique_id":source_uid,"source_inventory":source_before,"source_structural_count":len(source_structural),"source_protected_count":len(source_protected),"preserved_inventory":source_preserved_inventory,"source_occlusion_rows":source_occlusion_rows,"exports":export_rows,"authority_semantic_sha256":authority.get("semantic_sha256"),"ok":True})

        dup,dup_call=base.direct_call(source,"DuplicateTimeline",TARGET_TIMELINE_NAME); target=dup if dup is not None else base.find_timeline(project,TARGET_TIMELINE_NAME)
        if target is None: raise RuntimeError("duplicate_timeline")
        target_created=True; selected,_=base.direct_call(project,"SetCurrentTimeline",target)
        if not selected: raise RuntimeError("select_target")
        deletion=full.delete_named_textplus(target,sorted(deletion_names)); time.sleep(0.20)
        if not deletion.get("ok") or deletion.get("deleted")!=len(deletion_names): raise RuntimeError("delete_scope")
        track_setup=base.ensure_video_tracks(target,TRACK_MAX)
        if not track_setup.get("ok"): raise RuntimeError("track_setup")
        after_delete=full.timeline_inventory(target); preserved_after=full.stable_inventory([x for x in after_delete if str(x.get("name") or "") in preserve_names])
        if preserved_after!=source_preserved_inventory: raise RuntimeError("preserved_after_delete")
        if any(name in full.source_textplus_names(target) for name in quarantine_names): raise RuntimeError("quarantine_still_present")

        specs=[{"cue_id":x["instance_id"],"name":x["target_name"],"text":x["display_text"],"target_range":x["target_range"],"target_track":x["target_track"]} for x in plans]
        assigned={}; append_rows=[]
        for batch_index,batch in enumerate(pilot.chunked(specs,APPEND_BATCH_SIZE)):
            result=v6.append_batch_by_placement(media_pool,target,carrier,batch); ok=result.get("ok") is True and len(result.get("assigned") or [])==len(batch); append_rows.append({"batch_index":batch_index,"requested":len(batch),"assigned":len(result.get("assigned") or []),"ok":ok})
            if not ok: raise RuntimeError(f"append_batch:{batch_index}")
            for spec,item in result["assigned"]: assigned[str(spec["cue_id"])]=item
        if len(assigned)!=EXPECTED_RECREATE: raise RuntimeError("assigned_count")

        application_rows=[]
        for plan in plans:
            item=assigned.get(str(plan["instance_id"])); meta=source_meta[str(plan["target_name"])]
            if item is None: raise RuntimeError(f"assigned_item:{plan['instance_id']}")
            imported,import_call=base.direct_call(item,"ImportFusionComp",str(meta["comp_path"])); clone_ok=bool(imported and base.as_int(base.safe_value(item,"GetFusionCompCount",default=0),0)==1)
            application=old.apply_plan(base,visual,pilot,item,plan,meta["opacity_bases"]) if clone_ok else {"ok":False}
            overrides=static_overrides(plan); static_result=apply_static_overrides(base,pilot,item,overrides) if application.get("ok") else {"ok":False}
            meta["expected_static_style"].update(overrides)
            style_ok=old.style_matches(base,item,meta["expected_static_style"]) if static_result.get("ok") else False
            row={"instance_id":plan["instance_id"],"target_name":plan["target_name"],"kind":plan["kind"],"clone_ok":clone_ok,"application":application,"static_overrides":static_result,"style_ok":style_ok,"ok":bool(clone_ok and application.get("ok") and static_result.get("ok") and style_ok)}; application_rows.append(row)
            if not row["ok"]: raise RuntimeError(f"apply:{plan['instance_id']}")

        protected_rows=[]
        for row in part["exits"]:
            result=apply_protected_exit(base,old,visual,target,row); protected_rows.append(result)
            if not result.get("ok"): raise RuntimeError(f"protected_exit:{row['visual_token_id']}")

        occlusion_move=move_occlusion_above_text(base,v6,media_pool,target,part["occlusion"])
        if not occlusion_move.get("ok"): raise RuntimeError("occlusion_move")
        protected_snapshot_before=[]
        for name,snapshot in protected_source_snapshots.items():
            exit_row=exit_by_name.get(name); keys=None
            if exit_row is not None:
                track,item=base.find_named_item(target,name); item_start=int(base.item_summary(int(track or 0),item).get("start") or 0) if item is not None else 0
                keys=[{"local_frame":int(x["timeline_frame"])-item_start,"value":x["value"]} for x in exit_row["position_keys"]]
            protected_snapshot_before.append(verify_protected_snapshot(base,old,target,snapshot,keys))
        if len(protected_snapshot_before)!=EXPECTED_PROTECTED or not all(x.get("ok") for x in protected_snapshot_before): raise RuntimeError("protected_snapshot_before_save")
        base.write_json(report_dir/"rollout_application.json",{
            "schema_version":1,"task_id":TASK_ID,"run_id":run_id,
            "append_batches":append_rows,"application_rows":application_rows,
            "protected_exit_rows":protected_rows,"protected_scope_rows":protected_snapshot_before,
            "occlusion_move":occlusion_move,
            "checks":{
                "append_exact":sum(int(x.get("assigned") or 0) for x in append_rows)==EXPECTED_RECREATE and all(x.get("ok") for x in append_rows),
                "application_exact":len(application_rows)==EXPECTED_RECREATE and all(x.get("ok") for x in application_rows),
                "protected_exit_exact":len(protected_rows)==EXPECTED_PROTECTED_EXITS and all(x.get("ok") for x in protected_rows),
                "all_protected_scope_exact":len(protected_snapshot_before)==EXPECTED_PROTECTED and all(x.get("ok") for x in protected_snapshot_before),
                "occlusion_move_exact":occlusion_move.get("ok") is True,
            },
            "ok":True,
        })

        found=pilot.target_items(target,plans); readback=[]
        for plan in plans:
            item=found.get(str(plan["target_name"]),(0,None))[1]; meta=source_meta[str(plan["target_name"])]
            readback.append(old.read_plan(base,item,target,plan,meta["opacity_bases"],meta["expected_static_style"]) if item is not None else {"target_name":plan["target_name"],"ok":False})
        target_inventory=full.timeline_inventory(target); preserved_before=full.stable_inventory([x for x in target_inventory if str(x.get("name") or "") in preserve_names]); structural_names=full.source_textplus_names(target); protected_names=full.visual_first_names(target); occlusion_before=verify_occlusion(base,target,part["occlusion"])
        pre_checks={
            "recreate_exact":len(readback)==EXPECTED_RECREATE and all(x.get("ok") for x in readback),
            "preserved_unresolved_exact":preserved_before==source_preserved_inventory and preserve_names<=set(structural_names),
            "quarantine_absent":not quarantine_names & set(structural_names),
            "structural_count":len(structural_names)==EXPECTED_STRUCTURAL_TARGET,
            "protected_count":len(protected_names)==EXPECTED_PROTECTED,
            "physical_textplus_count":len(structural_names)+len(protected_names)==EXPECTED_TARGET_PHYSICAL,
            "protected_exit_exact":len(protected_rows)==EXPECTED_PROTECTED_EXITS and all(x.get("ok") for x in protected_rows),
            "all_protected_scope_exact":len(protected_snapshot_before)==EXPECTED_PROTECTED and all(x.get("ok") for x in protected_snapshot_before),
            "v2_empty":not full.track_two_item_names(target),
            "occlusion_above_textplus":occlusion_before.get("ok") is True,
        }
        base.write_json(report_dir/"rollout_readback_before_save.json",{"rows":readback,"protected_exit_rows":protected_rows,"protected_scope_rows":protected_snapshot_before,"occlusion":occlusion_before,"checks":pre_checks,"ok":all(pre_checks.values())})
        if not all(pre_checks.values()): raise RuntimeError("readback_before_save")

        base.direct_call(project,"SetCurrentTimeline",target); base.direct_call(resolve,"OpenPage","edit"); save=base.save_project(project_manager); report["save_call_count"]=1 if save.get("success") else 0
        if not save.get("success"): raise RuntimeError("save")
        project_manager,project,media_pool,reacquire=base.get_project(resolve); source_after=base.find_timeline(project,SOURCE_TIMELINE_NAME); target_after=base.find_timeline(project,TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None: raise RuntimeError("reacquire_timeline")
        source_after_inventory=full.timeline_inventory(source_after); target_after_inventory=full.timeline_inventory(target_after)
        found_after=pilot.target_items(target_after,plans); persistent_rows=[]
        for plan in plans:
            item=found_after.get(str(plan["target_name"]),(0,None))[1]; meta=source_meta[str(plan["target_name"])]
            persistent_rows.append(old.read_plan(base,item,target_after,plan,meta["opacity_bases"],meta["expected_static_style"]) if item is not None else {"target_name":plan["target_name"],"ok":False})
        persistent_exits=[]
        for row in part["exits"]:
            track,item=base.find_named_item(target_after,str(row["target_name"])); start=int(base.item_summary(int(track or 0),item).get("start") or 0) if item is not None else 0
            keys=[{"local_frame":int(x["timeline_frame"])-start,"value":x["value"]} for x in row["position_keys"]]
            read=read_center_keys(base,item,keys) if item is not None else {"ok":False}
            persistent_exits.append({"target_name":row["target_name"],"readback":read,"ok":bool(item is not None and read.get("ok"))})
        protected_snapshot_after=[]
        for name,snapshot in protected_source_snapshots.items():
            exit_row=exit_by_name.get(name); keys=None
            if exit_row is not None:
                track,item=base.find_named_item(target_after,name); item_start=int(base.item_summary(int(track or 0),item).get("start") or 0) if item is not None else 0
                keys=[{"local_frame":int(x["timeline_frame"])-item_start,"value":x["value"]} for x in exit_row["position_keys"]]
            protected_snapshot_after.append(verify_protected_snapshot(base,old,target_after,snapshot,keys))
        structural_after=full.source_textplus_names(target_after); protected_after=full.visual_first_names(target_after); preserved_after_save=full.stable_inventory([x for x in target_after_inventory if str(x.get("name") or "") in preserve_names]); occlusion_after=verify_occlusion(base,target_after,part["occlusion"])
        persistent_checks={
            "source_timeline_unchanged":base.timeline_unique_id(source_after)==source_uid and full.stable_inventory(source_after_inventory)==full.stable_inventory(source_before),
            "accepted_state_unchanged":accepted_path.is_file() and base.raw_sha256(accepted_path)==accepted_hash,
            "target_retained":base.timeline_name(target_after)==TARGET_TIMELINE_NAME,
            "recreate_exact":len(persistent_rows)==EXPECTED_RECREATE and all(x.get("ok") for x in persistent_rows),
            "preserved_unresolved_exact":preserved_after_save==source_preserved_inventory and preserve_names<=set(structural_after),
            "quarantine_absent":not quarantine_names & set(structural_after),
            "structural_count":len(structural_after)==EXPECTED_STRUCTURAL_TARGET,
            "protected_count":len(protected_after)==EXPECTED_PROTECTED,
            "physical_textplus_count":len(structural_after)+len(protected_after)==EXPECTED_TARGET_PHYSICAL,
            "protected_exit_exact":len(persistent_exits)==EXPECTED_PROTECTED_EXITS and all(x.get("ok") for x in persistent_exits),
            "all_protected_scope_exact":len(protected_snapshot_after)==EXPECTED_PROTECTED and all(x.get("ok") for x in protected_snapshot_after),
            "v2_empty":not full.track_two_item_names(target_after),
            "occlusion_above_textplus":occlusion_after.get("ok") is True,
        }
        persistent={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"rows":persistent_rows,"protected_exit_rows":persistent_exits,"protected_scope_rows":protected_snapshot_after,"occlusion":occlusion_after,"checks":persistent_checks,"save":save,"visual_approval_required":True,"fade_polish_deferred":True,"further_rollout_authorized":False,"ok":all(persistent_checks.values())}; base.write_json(report_dir/"persistent_readback.json",persistent)
        if not persistent["ok"]: raise RuntimeError("persistent_readback")
        report.update({"ok":True,"recreated_count":EXPECTED_RECREATE,"preserved_unresolved_count":EXPECTED_PRESERVED,"quarantine_removed_count":EXPECTED_QUARANTINE,"protected_exit_update_count":EXPECTED_PROTECTED_EXITS,"final_textplus_count":EXPECTED_TARGET_PHYSICAL,"v2_item_count":0,"source_timeline_unchanged":True,"accepted_state_unchanged":True,"target_timeline_kept":True,"occlusion_above_textplus":True,"occlusion_target_track":occlusion_after["rows"][0]["track_index"],"finished_at":base.utc_now()})
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc)); report["traceback"]=traceback.format_exc()
        if target_created and project_manager is not None and project is not None and media_pool is not None:
            cleanup=cleanup_failure(resolve,base,project_manager,project,media_pool,original,original_page,accepted_path,accepted_hash); base.write_json(report_dir/"failure_cleanup.json",cleanup); report["failure_cleanup_ok"]=cleanup.get("ok") is True; report["save_call_count"]=int(cleanup.get("save_call_count") or 0)
        report["finished_at"]=base.utc_now(); return report
