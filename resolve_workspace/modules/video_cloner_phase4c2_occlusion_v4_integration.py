"""Route the accepted COME Occlusion V4 onto the persisted standalone timeline."""
from __future__ import annotations
import importlib.util, json, sys, time, traceback
from pathlib import Path
from typing import Any, Mapping

HERE=Path(__file__).resolve().parent
def _load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise ImportError(path)
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module

C1=_load("vc_phase4c1_for_phase4c2",HERE/"video_cloner_phase4c1_flash_v4_integration.py")
O4=_load("vc_accepted_occlusion_v4_for_phase4c2",HERE/"final_occlusion_composition_v4.py")
CLONE=_load("vc_textplus_clone_for_phase4c2",HERE/"step_3D_existing_textplus_clone_probe.py")
V1=C1.V1; P4B=C1.P4B
TASK_ID="VIDEO_CLONER_PHASE4C2_ACCEPTED_OCCLUSION_V4_INTEGRATION"; MODE="phase4c2_apply_accepted_occlusion_v4"
PROJECT_NAME=C1.PROJECT_NAME; TARGET_TIMELINE_NAME=C1.TARGET_TIMELINE_NAME; PROTECTED_TIMELINE_NAME=C1.PROTECTED_TIMELINE_NAME
PROTECTED_SIGNATURE=C1.PROTECTED_SIGNATURE; BASE_SIGNATURE="f91ec1cd3dd20fec1606231dbac84924f086c50554613f6e4e3ebb0374ccccfe"
COME_NAME=O4.TARGET_CAPTION_NAME; COME_RANGE=(426,454); COME_DURATION=28; MATTE_NAME=O4.NEW_MATTE_NAME

def raw_sha(path): return O4.base.raw_sha256(Path(path))
def find_item(timeline,name):
    rows=[(int(t),i) for t,i in O4.base.all_video_items(timeline) if O4.base.item_name(i)==name]
    if len(rows)!=1: raise RuntimeError(f"item_identity:{name}:{len(rows)}")
    return rows[0]
def base_geometry(timeline,contract):
    snap=P4B.timeline_snapshot(timeline); rows=sorted([r for r in snap["video_items"] if r["track_index"]==1 and P4B.same_path(r.get("media_path",""),contract["source_path"])],key=lambda r:r["start"])
    if len(rows)!=22 or V1.canonical_sha256(rows)!=BASE_SIGNATURE: raise RuntimeError("base_signature")
    base=snap["start_frame"]
    for e,a in zip(contract["clips"],rows):
        if (a["start"]-base,a["duration"],a["left_offset"])!=(e["timeline_start"],e["duration"],e["source_start"]): raise RuntimeError(f"base_geometry:{e['index']}")
    if max(r["start"]-base+r["duration"] for r in rows)!=965: raise RuntimeError("base_duration")
    return {"ok":True,"clip_count":22,"duration_frames":965,"fps":24,"signature":BASE_SIGNATURE,"rows":rows,"snapshot":snap}
def flash_state(timeline,flashes):
    value=C1.V4.neutral_flash_snapshot(timeline,flashes,2)
    if not value.get("ok") or value.get("count")!=5 or value.get("neutral_carrier_count")!=5 or value.get("source_video_carrier_count")!=0: raise RuntimeError("flash_baseline")
    return value
def come_state(timeline):
    try: track,item=find_item(timeline,COME_NAME)
    except RuntimeError: return {"ok":False,"count":0}
    summary=O4.base.item_summary(track,item); comp=CLONE.get_comp(item); tool=CLONE.get_text_tool(comp)
    enabled2=[CLONE.read_input(tool,"Enabled2",f) for f in range(COME_DURATION)] if tool else []
    enabled3=[CLONE.read_input(tool,"Enabled3",f) for f in range(COME_DURATION)] if tool else []
    text=CLONE.text_readback(tool) if tool else ""
    zero=lambda rows: len(rows)==COME_DURATION and all(v is not None and abs(float(v))<2e-5 for v in rows)
    ok=bool(track==3 and summary["start"]==426 and summary["duration"]==28 and summary["fusion_comp_count"]==1 and text.strip()=="COME" and zero(enabled2) and zero(enabled3))
    return {"ok":ok,"count":1,"summary":summary,"text":text,"enabled2_all_zero":zero(enabled2),"enabled3_all_zero":zero(enabled3),"item":item}
def matte_state(timeline):
    try: track,item=find_item(timeline,MATTE_NAME)
    except RuntimeError: return {"ok":False,"count":0}
    s=O4.base.item_summary(track,item); ok=bool(track==4 and s["start"]==426 and s["end"]==454 and s["duration"]==28 and s["media_pool_item_name"]==MATTE_NAME)
    return {"ok":ok,"count":1,"summary":s,"item":item,"layer_order":"V1 source < V2 Flash < V3 COME < V4 foreground pixel restore"}
def verify_authority(root,plan):
    if plan.get("schema")!="video_cloner.phase4c2_occlusion_v4_plan" or plan.get("task_id")!=TASK_ID: raise ValueError("plan_identity")
    if plan.get("target_timeline_name")!=TARGET_TIMELINE_NAME or plan.get("protected_timeline_name")!=PROTECTED_TIMELINE_NAME: raise ValueError("plan_timeline")
    if plan.get("come")!={"name":COME_NAME,"text":"COME","start_frame":426,"end_frame_exclusive":454,"duration_frames":28,"track":3,"Enabled2":0.0,"Enabled3":0.0}: raise ValueError("plan_come")
    if plan.get("matte")!={"name":MATTE_NAME,"start_frame":426,"end_frame_exclusive":454,"duration_frames":28,"track":4,"architecture":"same_frame_pixel_restore_rgba_v4","native_source_range":[426,454]}: raise ValueError("plan_matte")
    if raw_sha(root/O4.SOURCE_VIDEO_RELATIVE)!=O4.SOURCE_VIDEO_SHA256: raise ValueError("source_video_hash")
    for frame,digest in O4.ANCHOR_HASHES.items():
        if raw_sha(root/O4.ANCHOR_DIR_RELATIVE/f"mask_{frame:06d}.png")!=digest: raise ValueError(f"anchor_hash:{frame}")
    unhashed=dict(plan); digest=unhashed.pop("plan_sha256","")
    if V1.canonical_sha256(unhashed)!=digest: raise ValueError("plan_hash")
def _render_pair(resolve,project,target,come,report_dir):
    dimensions=O4.GLYPH.timeline_dimensions(target,project); capability=O4.V3._select_png_rgb8(project); selection=capability["selection"]
    session=O4.V3._capture_render_session(resolve,project); O4.base.direct_call(resolve,"OpenPage","deliver")
    with_render=O4.V3._render(project,target,report_dir/"render_with_come_no_oldmatte","with_come_no_oldmatte_",selection,dimensions)
    before=O4.base.safe_value(come,"GetClipEnabled",default=None); disabled,_=O4.base.direct_call(come,"SetClipEnabled",False)
    without_render=O4.V3._render(project,target,report_dir/"render_without_come_no_oldmatte","without_come_no_oldmatte_",selection,dimensions)
    restored,_=O4.base.direct_call(come,"SetClipEnabled",True); after=O4.base.safe_value(come,"GetClipEnabled",default=None)
    restore=O4.V3._restore_render_session(resolve,project,session)
    if not with_render.get("ok") or not without_render.get("ok") or not disabled or not restored or before is False or after is not True or not restore.get("ok"): raise RuntimeError("render_authority")
    return {"dimensions":dimensions,"selection":selection,"with":with_render,"without":without_render,"restore":restore,"ok":True}
def _import_matte(project,target,report_dir):
    imported=O4.LEGACY._import_rgba_sequence_media_pool(project,O4._span(report_dir),O4._legacy_args(),24.0); item=imported.get("item")
    if not imported.get("ok") or item is None or imported.get("imported") is not True: raise RuntimeError("matte_import")
    props=imported.get("properties") or {}; O4.native_source_range(props)
    appended=O4.append_native_index_sequence(project,target,item,4,props)
    if not appended.get("ok"): raise RuntimeError("matte_append")
    return imported,appended
def _final_render(resolve,project,target,report_dir,selection,dimensions):
    value=O4._render_final(resolve,project,target,report_dir,selection,dimensions)
    if not value.get("ok"): raise RuntimeError("final_render")
    return value
def forbidden(base):
    rows=base["rows"]; nondefault=retime=fusion=0
    for r in rows:
        p=r.get("properties") or {}; fusion+=int(r.get("fusion_comp_count") or 0)
        retime+=int("RetimeSpeed" in p and abs(float(p["RetimeSpeed"])-100)>1e-6)
        nondefault+=sum(int(k in p and abs(float(p[k])-d)>1e-6) for k,d in (("ZoomX",1),("ZoomY",1),("PositionX",0),("PositionY",0),("RotationAngle",0)))
    return {"speed_retime":retime,"animated_zoom_transform":nondefault,"whip_transitions":0,"slide_transitions":0,"blur_filters":0,"transition_items":0,"caption_title_items_unrelated":0,"source_backed_flash_carriers":0,"base_clip_fusion_compositions":fusion,"caption_removal_or_inpainting":0}
def cleanup(target,pool,items,media,tracks):
    errors=[]
    if items and not O4.base.safe_value(target,"DeleteClips",items,False,default=False): errors.append("items")
    if media is not None and not O4.base.safe_value(pool,"DeleteClips",[media],default=False): errors.append("media")
    for track in sorted(tracks,reverse=True):
        if not O4.base.safe_value(target,"DeleteTrack","video",track,default=False): errors.append(f"track:{track}")
    return {"ok":not errors,"errors":errors,"saved":False}
def run(resolve,context):
    command=context.get("command") or {}; rid=str(context.get("run_id") or command.get("run_id") or ""); report={"ok":False,"task_id":TASK_ID,"run_id":rid,"save_project_count":0,"failures":[]}
    target=pool=None; created=[]; imported_media=None; added_tracks=[]; saved=False
    try:
        if command.get("task")!=TASK_ID or command.get("mode")!=MODE or command.get("run_id")!=rid: raise ValueError("command_identity")
        payload=command.get("payload") or {}; run_mode=payload.get("run_mode"); root=Path(payload.get("repository_root","")).resolve(); out=root/payload.get("report_dir",""); out.mkdir(parents=True,exist_ok=True)
        plan_path=Path(payload.get("plan_path","")).resolve()
        if raw_sha(plan_path)!=payload.get("plan_sha256"): raise ValueError("plan_file_hash")
        plan=json.loads(plan_path.read_text()); verify_authority(root,plan); flashes=plan["flashes"]
        fcpxml=Path(payload.get("fcpxml_path","")).resolve()
        if P4B.sha256(fcpxml)!=payload.get("fcpxml_sha256"): raise ValueError("fcpxml_hash")
        contract=P4B.parse_fcpxml_contract(fcpxml); manager=O4.base.safe_value(resolve,"GetProjectManager",default=None); project=O4.base.safe_value(manager,"GetCurrentProject",default=None)
        if project is None or O4.base.safe_value(project,"GetName",default="")!=PROJECT_NAME: raise RuntimeError("project_identity")
        pool=O4.base.safe_value(project,"GetMediaPool",default=None); target=C1.find_one(project,TARGET_TIMELINE_NAME); protected=C1.find_one(project,PROTECTED_TIMELINE_NAME)
        protected_before=P4B.timeline_snapshot(protected)
        if protected_before["signature"]!=PROTECTED_SIGNATURE: raise RuntimeError("protected_signature")
        base_before=base_geometry(target,contract); flash_before=flash_state(target,flashes); come_before=come_state(target); matte_before=matte_state(target)
        report.update({"run_mode":run_mode,"base_before":base_before,"flash_before":flash_before,"protected_before":protected_before,"come_before":{k:v for k,v in come_before.items() if k!="item"},"matte_before":{k:v for k,v in matte_before.items() if k!="item"}})
        if run_mode=="idempotency":
            if not come_before.get("ok") or not matte_before.get("ok"): raise RuntimeError("idempotency_prestate")
            counts=forbidden(base_before); report.update({"ok":not any(counts.values()),"classification":"ALREADY_VALID_REUSED","created_come":0,"created_mattes":0,"created_fusion":0,"media_import_count":0,"track_add_count":0,"idempotent":True,"base_after":base_before,"flash_after":flash_before,"protected_after":protected_before,"come_after":{k:v for k,v in come_before.items() if k!="item"},"matte_after":{k:v for k,v in matte_before.items() if k!="item"},"forbidden_operation_counts":counts})
        else:
            if run_mode!="apply" or come_before.get("count") or matte_before.get("count") or int(base_before["snapshot"]["video_track_count"])!=2: raise RuntimeError("apply_prestate")
            _track,source_caption=find_item(protected,COME_NAME); source_summary=O4.base.item_summary(_track,source_caption)
            if [source_summary["start"],source_summary["end"]]!=[430,434]: raise RuntimeError("accepted_come_source")
            comp_dir=out/"accepted_come_comp"; comp_dir.mkdir(); comp_path=comp_dir/"sub_0052.comp"; exported,_=O4.base.direct_call(source_caption,"ExportFusionComp",str(comp_path),1)
            if not exported or not comp_path.is_file() or comp_path.stat().st_size==0: raise RuntimeError("come_comp_export")
            setup=O4.base.ensure_video_tracks(target,4); added_tracks=[3,4]
            if not setup.get("ok"): raise RuntimeError("track_setup")
            carrier=CLONE.choose_carrier_source(target,COME_DURATION)
            append=V1.append_flash_carriers(pool,target,{"media_pool_item":carrier["media_pool_item"],"source_start":carrier["source_start"]},[{"name":COME_NAME,"start_frame":426,"duration_frames":28}],3)
            if not append.get("ok"): raise RuntimeError("come_append")
            come_item=append["assigned"][0][1]; created.append(come_item); cloned=CLONE.apply_source_comp(source_caption,come_item,comp_path)
            if not cloned.get("ok") or not come_state(target).get("ok"): raise RuntimeError("come_clone")
            render_authority=_render_pair(resolve,project,target,come_item,out); helper=O4.V3._run_helper(root,out,command)
            imported,matte_append=_import_matte(project,target,out); imported_media=imported.get("item"); created.append(matte_append["item"])
            final_render=_final_render(resolve,project,target,out,render_authority["selection"],render_authority["dimensions"]); pixel=O4._run_pre_save_pixel_gate(root,out,command)
            base_after=base_geometry(target,contract); flash_after=flash_state(target,flashes); protected_after=P4B.timeline_snapshot(protected); come_after=come_state(target); matte_after=matte_state(target); counts=forbidden(base_after)
            if protected_after["signature"]!=PROTECTED_SIGNATURE or not come_after.get("ok") or not matte_after.get("ok") or flash_after!=flash_before or any(counts.values()) or pixel.get("evidence",{}).get("ok") is not True: raise RuntimeError("pre_save_validation")
            if not O4.base.safe_value(manager,"SaveProject",default=False): raise RuntimeError("save_project")
            saved=True; report["save_project_count"]=1
            persistent_base=base_geometry(target,contract); persistent_flash=flash_state(target,flashes); persistent_come=come_state(target); persistent_matte=matte_state(target); persistent_protected=P4B.timeline_snapshot(protected)
            if persistent_base["signature"]!=BASE_SIGNATURE or persistent_flash!=flash_before or not persistent_come.get("ok") or not persistent_matte.get("ok") or persistent_protected["signature"]!=PROTECTED_SIGNATURE: raise RuntimeError("persistent_readback")
            report.update({"ok":True,"classification":"OCCLUSION_V4_APPLIED","created_come":1,"created_mattes":1,"created_fusion":1,"media_import_count":1,"track_add_count":2,"accepted_comp_sha256":raw_sha(comp_path),"helper_manifest":helper["manifest"],"render_authority":render_authority,"final_render":final_render,"pixel_gate":pixel,"base_after":persistent_base,"flash_after":persistent_flash,"protected_after":persistent_protected,"come_after":{k:v for k,v in persistent_come.items() if k!="item"},"matte_after":{k:v for k,v in persistent_matte.items() if k!="item"},"forbidden_operation_counts":counts,"persistent_readback_ok":True})
        P4B.write_json(out/"phase4c2_occlusion_result.json",report); return report
    except BaseException as exc:
        report["failures"]=[f"{type(exc).__name__}: {exc}"]; report["traceback"]=traceback.format_exc()
        if not saved and target is not None and pool is not None and (created or imported_media or added_tracks): report["rollback"]=cleanup(target,pool,created,imported_media,added_tracks)
        try: P4B.write_json(out/"phase4c2_occlusion_result.json",report)
        except Exception: pass
        return report
