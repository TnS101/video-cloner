import hashlib
import json
from pathlib import Path

from video_cloner import profile_comparison as COMPARE
from video_cloner import profiles as PROFILE

ROOT = Path(__file__).resolve().parents[1]


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fresh_profile():
    base = ROOT / "data/DZatr0EJt4B"
    return PROFILE.build_profile(
        base / "analysis/DZatr0EJt4B_analysis.json",
        base / "planning/DZatr0EJt4B_edit_plan.json",
        base / "analysis/DZatr0EJt4B_transitions.json",
        base / "analysis/DZatr0EJt4B_camera_style_profile.json",
        base / "analysis/DZatr0EJt4B_caption_style_grammar.json",
        "DZatr0EJt4B",
    )


def test_generic_profile_is_deterministic_and_preserves_authority_boundaries():
    accepted = ROOT / "data/DcJRJtUKScu/analysis/DcJRJtUKScu_style_profile_mvp.json"
    accepted_hash = _hash(accepted)
    profile = _fresh_profile()

    assert json.loads(json.dumps(profile, sort_keys=True)) == profile
    assert json.dumps(profile, sort_keys=True) == json.dumps(_fresh_profile(), sort_keys=True)
    assert set(profile) >= {"cuts_pacing", "transitions", "camera", "captions", "deferred", "source_artifacts"}
    assert profile["cuts_pacing"]["observed"]["shot_count"] == 8
    assert profile["cuts_pacing"]["observed"]["cut_count"] == 7
    assert all(not row["family"].endswith("_candidate") for row in profile["transitions"]["recommended"]["merged_conservative_events"])
    assert profile["captions"]["observed"]["opacity_rules"]["status"] == "UNKNOWN"
    assert set(profile["deferred"]) == {"flash_execution", "generic_vfx", "occlusion_reconstruction", "sfx", "graphics"}
    assert _hash(accepted) == accepted_hash
    source = (ROOT / "video_cloner/profiles.py").read_text(encoding="utf-8").lower()
    assert not any(term in source for term in ("dcjrjtukscu", "dzatr0ejt4b", ".agent/gold", ".drt"))


def test_comparator_separates_style_difference_unknown_and_limitation():
    reference = json.loads((ROOT / "data/DcJRJtUKScu/analysis/DcJRJtUKScu_style_profile_mvp.json").read_text(encoding="utf-8-sig"))
    candidate = _fresh_profile()
    comparison = COMPARE.compare_profiles(reference, candidate)
    repeat = COMPARE.compare_profiles(reference, candidate)
    checks = {row["field"]: row["classification"] for row in comparison["dimensions"]["captions"]["checks"]}
    transition_checks = {row["field"]: row["classification"] for row in comparison["dimensions"]["transitions"]["checks"]}

    assert json.dumps(comparison, sort_keys=True) == json.dumps(repeat, sort_keys=True)
    assert comparison["verdict"] == "PASS_UNSEEN_REEL_MVP_GENERALIZATION"
    assert comparison["dimensions"]["cuts_pacing"]["classification"] == "STYLE_DIFFERENCE"
    assert checks["opacity_status"] == "UNKNOWN"
    assert checks["enter_exit_availability"] == "PIPELINE_LIMITATION"
    assert transition_checks["candidate_authority_separation"] == "MATCH"
    assert comparison["pipeline_generalization"]["status"] == "PASS"
    source = (ROOT / "video_cloner/profile_comparison.py").read_text(encoding="utf-8").lower()
    assert not any(term in source for term in ("dcjrjtukscu", "dzatr0ejt4b", ".agent/gold", ".drt"))
