from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".agent/reports/VIDEO_CLONER_PHASE4C1_ACCEPTED_FLASH_V4_INTEGRATION/20260818T155057413Z_bc06f111358f4bf8916dc121111459c4/flash_plan.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load("reel1_restore_prepare", ROOT / "scripts/davinci/prepare_video_cloner_phase5_reel1_flash_v4_orphan_restoration.py")
base = load("reel1_restore_base", ROOT / "resolve_workspace/modules/video_cloner_phase4c1_flash_v4_integration.py")


def source_plan() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8-sig"))


def test_historical_reel1_schema1_rejection_is_fixed_by_canonical_normalization():
    legacy = source_plan()
    with pytest.raises(ValueError, match="^plan_schema$"):
        base.validate_plan(legacy)
    plan = prepare.normalize_plan(ROOT, legacy)
    base.validate_plan(plan)
    assert plan["schema_version"] == 2
    assert plan["target_timeline_name"] == prepare.TARGET
    assert plan["artifact"] == {"timeline_name": prepare.TARGET, "clip_count": 22, "duration_frames": 965, "fps": 24, "fcpxml_sha256": "legacy_phase4c2_compatibility"}
    assert [row["cut_frame"] for row in plan["flashes"]] == list(prepare.EXPECTED_CUTS)
    assert [(row["start_frame"], row["start_frame"] + row["duration_frames"]) for row in plan["flashes"]] == list(prepare.EXPECTED_SPANS)
    assert all(row["authority"] == {"editor_actionable": True, "confidence": "high"} for row in plan["flashes"])
    assert 596 not in [row["cut_frame"] for row in plan["flashes"]]


@pytest.mark.parametrize("mutation,error", [
    (lambda plan: plan.update(schema_version=2), "reel1_plan_identity"),
    (lambda plan: plan.update(target_timeline_name="DcJRJtUKScu_standalone_timeline"), "reel1_plan_identity"),
    (lambda plan: plan["flashes"].pop(), "reel1_plan_geometry"),
    (lambda plan: plan["flashes"][0].update(cut_frame=596), "reel1_plan_geometry"),
])
def test_noncanonical_schema_identity_count_and_frames_fail_closed(mutation, error):
    plan = copy.deepcopy(source_plan())
    mutation(plan)
    with pytest.raises(ValueError, match=f"^{error}$"):
        prepare.normalize_plan(ROOT, plan)


def test_authority_drift_fails_closed_even_when_geometry_is_unchanged():
    plan = copy.deepcopy(source_plan())
    plan["flashes"][0]["flash_color"] = [0.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="^reel1_plan_authority_hash$"):
        prepare.normalize_plan(ROOT, plan)
