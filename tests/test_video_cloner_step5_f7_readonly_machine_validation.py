from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "resolve_workspace/modules/video_cloner_step5_f7_readonly_machine_validation.py"
CONTRACT = ROOT / ".agent/reports/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_V1/20261002T093228130622Z_8a43be1aa99a4e2fa6ec66203b559cbd/step5_f7_compile_contract.json"


def load():
    spec = importlib.util.spec_from_file_location("f7_readonly_machine_validation", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_readonly_validation_scope_and_placement_are_complete() -> None:
    module = load()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8-sig"))
    placement = module._placement(contract)
    assert module.TARGET_TIMELINE == "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_66203b559cbd"
    assert placement == {
        "object_count": 65,
        "missing_lane_count": 0,
        "lane_track_mismatch_count": 0,
        "lane_track_mismatches": [],
        "same_track_overlap_count": 0,
        "same_track_overlaps": [],
        "pass": True,
    }
    target = next(row for row in contract["objects"] if row["source_identity"] == "caption_tracklet_0089")
    assert target["resolve_interval"] == [542, 596]
    assert len(target["keyframes"]["scale"]) == 9


def test_readonly_validation_has_no_resolve_mutation_calls() -> None:
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not called & {
        "SetInput", "SaveProject", "ImportTimelineFromFile", "DeleteTimelines",
        "AddTrack", "SetName", "SetCurrentTimeline", "AddFusionComp",
    }

