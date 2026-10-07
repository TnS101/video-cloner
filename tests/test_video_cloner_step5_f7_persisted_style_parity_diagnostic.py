from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "resolve_workspace/modules/video_cloner_step5_f7_persisted_style_parity_diagnostic.py"


def load():
    spec = importlib.util.spec_from_file_location("f7_persisted_parity_diagnostic", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_scope_is_exact_and_runtime_has_no_resolve_mutation_calls() -> None:
    module = load()
    assert module.TARGET_TIMELINE == "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_66203b559cbd"
    assert module.TARGET_IDS == (
        "recovered_display_object_why_0001",
        "recovered_display_object_local_we_0002",
        "recovered_display_object_listing_0003",
    )
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not called & {
        "SetInput", "SaveProject", "ImportTimelineFromFile", "DeleteTimelines",
        "AddTrack", "SetName", "SetCurrentTimeline", "AddFusionComp",
    }


def test_evidence_is_written_before_comparator_or_classification() -> None:
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    source = ast.get_source_segment(RUNTIME.read_text(encoding="utf-8"), run)
    first_write = source.index("base.write(diagnostic_path, diagnostic)")
    comparator = source.index("_base_projection(row, actual)")
    classifier = source.index("_classify(projections)")
    assert first_write < comparator < classifier


def test_shadow_classification_preserves_sentinel_semantics() -> None:
    module = load()
    projections = {
        "base": {
            "fill": {"RESULT": True},
            "shadow": {
                "RESULT": False,
                "OPERATIONAL_EXPECTATION": {"enabled": False},
                "ACTUAL_NORMALIZED": {"enabled": False},
            },
        }
    }
    assert module._classify(projections) == {"shadow": "SEMANTICALLY_EQUAL_STRUCTURALLY_DIFFERENT"}

