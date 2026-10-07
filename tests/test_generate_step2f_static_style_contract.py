from __future__ import annotations

import copy
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/generate_step2f_static_style_contract.py"
LINKAGE_VALIDATION = ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_LINKAGE_STEP2B2_RERANK_CORRECTION_20260926/20260926T160000000Z_caption_tracklet_0074/bounded_linkage_repair_validation.json"
SPEC = importlib.util.spec_from_file_location("step2f", SCRIPT)
step2f = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(step2f)

PATHS = {
    "glyph": ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_FINAL_MULTI_OBJECT_MASK_ISOLATION_REPAIR_20260927/20260927T000000000Z_bounded/reel2_glyph_evidence_v2_mask_isolation_corrected.json",
    "font": ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_FINAL_MULTI_OBJECT_MASK_ISOLATION_REPAIR_20260927/20260927T000000000Z_bounded/reel2_known_region_font_rerank_mask_isolation_corrected.json",
    "candidate_reduction": ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_FINAL_MULTI_OBJECT_MASK_ISOLATION_REPAIR_20260927/20260927T000000000Z_bounded/whole_reel_full_pool_benchmark_mask_isolation_corrected.json",
    "stroke": ROOT / ".agent/reports/VIDEO_CLONER_STEP2C_STROKE_OWNERSHIP_CORRECTION_20260925/20260925T162120849Z_identity_ownership/step2c_stroke_ownership_inference.json",
    "color": ROOT / ".agent/reports/VIDEO_CLONER_STEP2D_COLOR_OPACITY_INFERENCE_20260925/20260925T180000000Z_first_run/step2d_color_opacity_inference.json",
    "composition": ROOT / ".agent/reports/VIDEO_CLONER_STEP2E_COMPOSITION_RELATIONSHIPS_20260925/20260925T220000000Z_source_graph/step2e_composition_relationships.json",
    "preview": ROOT / ".agent/reports/VIDEO_CLONER_STEP2_REEL2_STATIC_CAPTION_FIDELITY_V1_20260925/20260925T085122980Z_static_fidelity/reel2_l4_preview.json",
    "linkage_audit": ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_FINAL_MULTI_OBJECT_MASK_ISOLATION_REPAIR_20260927/20260927T000000000Z_bounded/whole_reel_text_mask_linkage_audit_after_mask_isolation_repair.json",
    "adjudication": ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_LINKAGE_CANDIDATE_ADJUDICATION_20260926/20260926T200000000Z_readonly/adjudication_decisions.json",
    "coverage": ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_REJECTED_OBSERVATION_COVERAGE_AUDIT_20260926/20260926T223000000Z_readonly/step2b1_rejected_observation_coverage_audit.json",
}


def contract():
    inputs = {name: step2f.load(path) for name, path in PATHS.items()}
    names = {name: str(path) for name, path in PATHS.items()}
    hashes = {name: step2f.sha256(path) for name, path in PATHS.items()}
    return step2f.build_contract(inputs, names, hashes)


def test_bounded_linkage_repair_preserves_masks_and_non_target_decisions():
    validation = step2f.load(LINKAGE_VALIDATION)
    assert validation["result"] == "PASS_BOUNDED_FONT_TEXT_LINKAGE_REPAIR"
    assert validation["corrected_scoring_text"] == "behind"
    assert validation["masks_bboxes_observations_unchanged"]
    assert validation["non_target_font_rankings_unchanged"]
    assert validation["non_target_candidate_reduction_rows_unchanged"]


def test_whole_reel_contract_and_authority_guards():
    value = contract()
    validation = step2f.validate_contract(value, 113, SCRIPT)
    ids = [row["identity"]["stable_identity_id"] for row in value["identities"]]
    assert len(ids) == len(set(ids)) == 113
    assert validation["result"] == "PASS_STEP_2F_CORRECTED_WHOLE_REEL_STATIC_STYLE_READY_FOR_HUMAN_REVIEW"
    assert validation["silent_default_check"]["pass"]
    assert validation["unresolved_properties_have_reasons"]
    assert not validation["provisional_authority_promoted"]
    assert not validation["composition_creates_shared_style"]
    assert not validation["physical_word_members_merged"]
    assert validation["generalization_gate"]["pass"]
    assert validation["step2b2_precedence_applied"]
    assert validation["step2b1_history_preserved"]
    assert validation["linkage_accounting"]["raw_mismatch_count"] == 14
    assert validation["linkage_accounting"]["accepted_harmless_mismatch_count"] == 14
    assert validation["linkage_accounting"]["unaccounted_true_mismatch_count"] == 0
    assert validation["linkage_accounting"]["coverage_gap_count"] == 0
    assert all(item["provenance"]["composition"]["sha256"] for item in value["identities"])


def test_step2b2_winner_and_downgrade_override_step2b1_with_history():
    value = contract()
    rows = {row["identity"]["stable_identity_id"]: row for row in value["identities"]}
    primary_launch = rows["caption_tracklet_0009"]["typography"]["font"]
    matching = rows["caption_tracklet_0094"]["typography"]["font"]
    behind = rows["caption_tracklet_0074"]["typography"]["font"]

    assert primary_launch["step2b1_history"]["selected_candidate"]["family"] == "Impact"
    assert primary_launch["selected_candidate"]["family"] == "Verdana"
    assert matching["step2b1_history"]["authority"] == "AUTHORITATIVE_FONT_RANKING"
    assert matching["authority"]["status"] == "PROVISIONAL"
    assert behind["selected_candidate"]["family"] == "Franklin Gothic Medium"
    assert behind["step2b1_history"]["selected_candidate"]["family"] == "Corbel"
    assert behind["authority"]["status"] == "PROVISIONAL"


def test_unresolved_and_renderer_defaults_cannot_be_promoted():
    value = contract()
    unresolved = next(row for row in value["identities"] if row["opacity"]["authority"]["status"] == "UNRESOLVED")
    assert unresolved["opacity"]["value"] is None
    broken = copy.deepcopy(value)
    broken["identities"][0]["opacity"]["value"] = 1.0
    assert not step2f.validate_contract(broken, 113, SCRIPT)["silent_default_check"]["pass"]
    broken = copy.deepcopy(value)
    provisional = next(row for row in broken["identities"] if row["fill"]["authority"]["status"] == "PROVISIONAL")
    provisional["fill"]["authority"]["status"] = "AUTHORITATIVE"
    assert step2f.validate_contract(broken, 113, SCRIPT)["provisional_authority_promoted"]


def test_latest_mask_isolation_downgrade_removes_stale_font_but_keeps_bbox_provenance():
    rows = {row["identity"]["stable_identity_id"]: row for row in contract()["identities"]}
    for identity in ("caption_tracklet_0068", "caption_tracklet_0069"):
        row = rows[identity]
        assert row["typography"]["font"]["authority"]["status"] == "UNRESOLVED"
        assert row["typography"]["font"]["selected_candidate"] is None
        assert row["geometry"]["source_observation_provenance"]
        assert not row["geometry"]["accepted_source_observations"]


def test_composition_and_physical_word_are_references_not_style_merges():
    value = contract()
    composed = [row for row in value["identities"] if row["composition"]["composition_ids"]]
    assert composed and all(not row["composition"]["style_sharing_authorized"] for row in composed)
    fragments = [row for row in value["identities"] if row["identity"]["physical_word_memberships"]]
    assert len(fragments) == 2
    assert len({row["identity"]["stable_identity_id"] for row in fragments}) == 2
    assert value["style_equivalence_relationships"][0]["outcome"] == "EXPLICITLY_UNRESOLVED"
    assert value["style_equivalence_relationships"][0]["style_sharing_applied"] is False


def test_generation_is_deterministic():
    import json
    first = json.dumps(contract(), indent=2) + "\n"
    second = json.dumps(contract(), indent=2) + "\n"
    assert first.encode() == second.encode()
