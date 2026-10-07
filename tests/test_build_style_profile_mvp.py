import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/build_style_profile_mvp.py"
SPEC = importlib.util.spec_from_file_location("build_style_profile_mvp", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_profile_is_deterministic_and_preserves_authority_boundaries():
    profile = MODULE.build_profile(ROOT)

    assert profile["schema"] == "video_cloner.style_profile.mvp.v1"
    assert set(profile) >= {"cuts_pacing", "transitions", "camera", "captions", "deferred", "source_artifacts"}
    assert profile["cuts_pacing"]["observed"]["shot_count"] == 14
    assert profile["transitions"]["recommended"]["step6a_authoritative_event"]["family"] == "flash_cut"
    candidates = profile["transitions"]["observed"]["candidate_only_events"]
    assert candidates and all(event["family"].endswith("_candidate") for event in candidates)
    assert not any(event["family"].endswith("_candidate") for event in [profile["transitions"]["recommended"]["step6a_authoritative_event"]])
    assert profile["transitions"]["deferred_unknown"]["execution_support"]["flash"] == "deferred"
    assert set(profile["deferred"]) == {"flash_execution", "generic_vfx", "occlusion", "sfx", "graphics"}
    assert profile["captions"]["observed"]["opacity_rules"]["unresolved_count"] == 113
    assert json.dumps(profile, sort_keys=True) == json.dumps(MODULE.build_profile(ROOT), sort_keys=True)
