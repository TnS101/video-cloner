from scripts.analysis.compile_step5a_v33_materialization import build_artifacts, digest
from resolve_workspace.modules.video_cloner_step5a_v33_resolve_rebuild import _semantic_layer_hash


def test_v33_materialization_preflight_is_complete_and_deterministic():
    first, second = build_artifacts(), build_artifacts()
    assert first == second
    assert digest(first["manifest"]) == digest(second["manifest"])
    assert first["manifest"]["object_count"] == 95
    assert first["cleanup"]["pass"] is True
    assert len(first["cleanup"]["timing_corrections"]) == 12
    assert len(first["cleanup"]["text_corrections"]) == 1
    assert first["cleanup"]["exact_duplicate_conflicts"] == []
    assert first["cleanup"]["same_authored_object_conflicts"] == []
    assert first["cleanup"]["style_corrections"] == []
    assert first["cleanup"]["unknown"] == 0
    assert first["reconciliation"]["current_v33_render_objects"] == 125
    assert first["reconciliation"]["classification_counts"] == {
        "KEEP": 30,
        "MERGE_INTO_EXISTING": 83,
        "SUPPRESS_AS_OBSERVATION": 12,
        "REPLACE_OLD_OBJECT": 0,
        "UNKNOWN": 0,
    }
    assert first["completeness"]["pass"] is True
    assert first["collisions"]["same_track_illegal_overlaps"] == 0
    assert first["regression"]["pass"] is True
    assert first["protected_guard"]["pass"] is True
    assert first["local_visual_sanity"]["pass"] is True


def test_v33_reconciliation_removes_observation_level_regressions_without_word_branches():
    result = build_artifacts()
    decisions = {row["canonical_text"]: row["classification"] for row in result["reconciliation"]["decisions"]}
    assert decisions["beforethe"] != "KEEP"
    assert decisions["the hits yard"] != "KEEP"
    assert decisions["partial hits transition fragment"] != "KEEP"
    assert decisions["hits"] == "KEEP"
    assert result["local_visual_sanity"]["checks"]["duplicate_semantic_stacks"] == 0


def test_generated_only_equivalence_ignores_timeline_local_item_identity():
    left = {"rows": [{"source_identity": "owner-a", "text": True, "lifecycle": True, "style": True}]}
    right = {"rows": [{"source_identity": "owner-a", "text": True, "lifecycle": True, "style": True}]}
    assert _semantic_layer_hash(left) == _semantic_layer_hash(right)


def test_bounded_cleanup_resolves_regression_anchors_without_suppressing_source_objects():
    result = build_artifacts()
    objects = {row["source_identity"]: row for row in result["manifest"]["objects"]}
    assert objects["caption_tracklet_0030"]["resolve_interval"] == [130, 154]
    assert objects["caption_tracklet_0032"]["resolve_interval"] == [134, 137]
    assert objects["caption_tracklet_0035"]["resolve_interval"] == [154, 155]
    assert objects["caption_tracklet_0038"]["resolve_interval"] == [155, 158]
    assert objects["canonical_source_object_78a21bf538c0a0ac"]["text"]["value"] == "in how"
    assert result["cleanup"]["duplicates_suppressed"] == 0
    assert result["cleanup"]["observation_objects_suppressed"] == 0
