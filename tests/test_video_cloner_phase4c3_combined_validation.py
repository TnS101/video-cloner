from __future__ import annotations
from pathlib import Path
from resolve_workspace.modules import video_cloner_phase4c3_combined_validation as runtime
from scripts.davinci import prepare_video_cloner_phase4c3_combined_validation as prepare
def authority():return {"transitions":[{"transition_type":"flash_cut","cut_frame":c,"duration_frames":4,"outgoing_frames":2,"incoming_frames":2} for c in runtime.C2.C1.EXPECTED_FLASH_FRAMES]}
def test_plan_is_strictly_read_only(tmp_path):
    source=Path(runtime.__file__).read_text();assert "SaveProject" not in source;assert "AppendToTimeline" not in source;assert "DeleteClips" not in source;assert "AddTrack" not in source
def test_runtime_has_zero_save_and_mutation_contract():
    source=Path(runtime.__file__).read_text();assert '"save_project_count":0' in source;assert '"mutation_count":0' in source
def test_combined_inventory_is_exact_four_track_authority():
    source=Path(runtime.__file__).read_text();assert '[22,5,1,1]' in source;assert 'len(before)!=29' in source
def test_overlap_contract_covers_both_flash_boundaries():
    source=Path(runtime.__file__).read_text();assert '"range_half_open":[426,454]' in source;assert '"flash_cut_frames":[426,454]' in source;assert '"flash_carrier_starts":[424,452]' in source
def test_plan_builder_indexes_seven_existing_visual_boundaries():
    source=Path(prepare.__file__).read_text();assert source.count('(\"')>=7;assert "first_flash" in source and "active_overlap_431" in source and "final_flash" in source
def test_validator_requires_source_base_flash_come_matte_protected_and_read_only():
    source=Path(__file__).resolve().parents[1]/"scripts/davinci/validate_video_cloner_phase4c3_combined_validation.py";text=source.read_text();
    for key in ('"base"','"flash"','"come"','"matte"','"protected"','"source"','"read_only"'):assert key in text
