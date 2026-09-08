from __future__ import annotations
from pathlib import Path
from resolve_workspace.modules import video_cloner_phase4c2_occlusion_v4_integration as runtime
from scripts.davinci import prepare_video_cloner_phase4c2_occlusion_v4_integration as prepare

def authority(): return {"transitions":[{"transition_type":"flash_cut","cut_frame":c,"duration_frames":4,"outgoing_frames":2,"incoming_frames":2} for c in runtime.C1.EXPECTED_FLASH_FRAMES]}
def test_plan_routes_only_standalone_target():
    p=prepare.build_plan(authority()); assert p["target_timeline_name"]=="DZsqH7auhjt_standalone_timeline"; assert p["protected_timeline_name"]=="DZsqH7auhjt_textplus_full"
def test_plan_reuses_exact_v4_identity_and_range():
    p=prepare.build_plan(authority()); assert p["architecture"]=="final_occlusion_composition_v4_native_index_same_frame_pixel_restore"; assert p["come"]["name"]=="VC_TEXTPLUS_0052_sub_052"; assert [p["come"]["start_frame"],p["come"]["end_frame_exclusive"]]==[426,454]
def test_plan_preserves_enabled2_enabled3_zero():
    p=prepare.build_plan(authority()); assert p["come"]["Enabled2"]==p["come"]["Enabled3"]==0.0
def test_plan_layering_is_source_flash_come_foreground():
    p=prepare.build_plan(authority()); assert p["come"]["track"]==3; assert p["matte"]["track"]==4; assert p["matte"]["native_source_range"]==[426,454]
def test_plan_freezes_five_flash_carriers():
    p=prepare.build_plan(authority()); assert [r["name"] for r in p["flashes"]]==[f"VC_FLASH_{i:03d}_frame_{c:04d}" for i,c in enumerate(runtime.C1.EXPECTED_FLASH_FRAMES,1)]
def test_plan_forbids_removal_inpainting_source_replacement():
    assert prepare.build_plan(authority())["forbidden"]=={"caption_removal":True,"inpainting":True,"source_replacement":True}
def test_authority_verifies_real_sidecars_and_hashes():
    runtime.verify_authority(Path(__file__).resolve().parents[1],prepare.build_plan(authority()))
def test_authority_rejects_protected_as_target():
    p=prepare.build_plan(authority()); p["target_timeline_name"]=runtime.PROTECTED_TIMELINE_NAME; p["plan_sha256"]=runtime.V1.canonical_sha256({k:v for k,v in p.items() if k!="plan_sha256"})
    try: runtime.verify_authority(Path(__file__).resolve().parents[1],p)
    except ValueError as e: assert str(e)=="plan_timeline"
    else: raise AssertionError("protected target accepted")
def test_forbidden_counts_zero_for_accepted_base():
    assert not any(runtime.forbidden({"rows":[{"properties":{"ZoomX":1.0,"ZoomY":1.0},"fusion_comp_count":0}]}).values())
class Timeline:
    def __init__(self): self.deleted=[]; self.tracks=[]
    def DeleteClips(self,items,ripple): self.deleted+=items; return not ripple
    def DeleteTrack(self,kind,index): self.tracks.append((kind,index)); return True
class Pool:
    def __init__(self): self.deleted=[]
    def DeleteClips(self,items): self.deleted+=items; return True
def test_failure_cleanup_is_unsaved_and_scoped():
    t,p=Timeline(),Pool(); a,b=object(),object(); value=runtime.cleanup(t,p,[a],b,[3,4]); assert value["ok"] and value["saved"] is False; assert t.deleted==[a]; assert t.tracks==[("video",4),("video",3)]; assert p.deleted==[b]
def test_runtime_places_pixel_gate_before_save():
    source=Path(runtime.__file__).read_text(); assert source.index("O4._run_pre_save_pixel_gate")<source.index('"SaveProject"')
def test_idempotency_branch_declares_all_zero_mutations():
    source=Path(runtime.__file__).read_text(); assert '"created_come":0' in source and '"created_mattes":0' in source and '"created_fusion":0' in source and '"save_project_count":0' in source
