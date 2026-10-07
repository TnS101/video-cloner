import numpy as np

from scripts.standalone import video_cloner_composition_relationships as relationships


def _kinds(rows):
    return {row["relationship_type"]: row for row in rows}


def _mask(height, width, top=0, bottom=None, left=0, right=None):
    value = np.zeros((height, width), dtype=bool)
    value[top:bottom, left:right] = True
    return value


def test_same_baseline_and_known_offset_use_visible_glyph_geometry():
    same = relationships.infer_pair_relationships("a", "b", [{
        "frame": 1,
        "a_bbox": [0, 0, 20, 30], "a_mask": _mask(30, 20, top=10),
        "b_bbox": [30, 0, 50, 30], "b_mask": _mask(30, 20, top=2),
    }])
    offset = relationships.infer_pair_relationships("a", "b", [{
        "frame": 1,
        "a_bbox": [0, 0, 20, 30], "a_mask": _mask(30, 20, top=10),
        "b_bbox": [30, 5, 50, 35], "b_mask": _mask(30, 20, top=2),
    }])

    assert _kinds(same)["SAME_BASELINE"]["measurement"]["source_pixels"] == 0
    assert _kinds(same)["SAME_BASELINE"]["measurement"]["typographic_baseline_exact"] is False
    assert _kinds(offset)["BASELINE_OFFSET"]["measurement"]["source_pixels"] == 5


def test_horizontal_glyph_gap_and_mask_overlap_are_measured():
    gap = relationships.infer_pair_relationships("a", "b", [{
        "frame": 2,
        "a_bbox": [0, 0, 20, 20], "a_mask": _mask(20, 20, left=2, right=18),
        "b_bbox": [25, 0, 45, 20], "b_mask": _mask(20, 20, left=2, right=18),
    }])
    overlap = relationships.infer_pair_relationships("a", "b", [{
        "frame": 3,
        "a_bbox": [0, 0, 20, 20], "a_mask": _mask(20, 20, left=5),
        "b_bbox": [10, 0, 30, 20], "b_mask": _mask(20, 20, right=15),
    }])

    assert _kinds(gap)["HORIZONTAL_GAP"]["measurement"]["source_pixels"] == 9
    assert _kinds(overlap)["OVERLAPS"]["measurement"]["median_overlap_area_source_px"] == 200


def test_intersecting_bboxes_without_common_mask_pixels_do_not_invent_overlap():
    rows = relationships.infer_pair_relationships("a", "b", [{
        "frame": 4,
        "a_bbox": [0, 0, 20, 20], "a_mask": _mask(20, 20, left=0, right=8),
        "b_bbox": [5, 0, 25, 20], "b_mask": _mask(20, 20, left=10, right=20),
    }])

    assert "OVERLAPS" not in _kinds(rows)


def test_z_order_requires_directional_ownership_and_otherwise_fails_closed():
    base = {"frame": 5, "a_bbox": [0, 0, 20, 20], "b_bbox": [10, 0, 30, 20], "overlap_area_px": 12, "overlap_ratio": 0.1}
    known = relationships.infer_pair_relationships("a", "b", [{**base, "front_identity": "b"}])
    unknown = relationships.infer_pair_relationships("a", "b", [base])

    assert _kinds(known)["Z_ORDER"]["source_identity"] == "b"
    assert "Z_ORDER_UNRESOLVED" not in _kinds(known)
    assert _kinds(unknown)["Z_ORDER_UNRESOLVED"]["authority"] == "UNRESOLVED"


def test_physical_word_preserves_members_and_nearby_unrelated_items_stay_separate():
    identities = [
        {"identity": "fragment_a", "observations": [{"source_frame": 1, "bbox": [0, 0, 20, 20], "accepted": True}]},
        {"identity": "fragment_b", "observations": [{"source_frame": 1, "bbox": [20, 0, 40, 20], "accepted": True}]},
        {"identity": "nearby", "observations": [{"source_frame": 1, "bbox": [42, 0, 62, 20], "accepted": True}]},
    ]
    graph = relationships.build_composition_graph(
        identities,
        {"fragment_a": "hint_one", "fragment_b": "hint_two", "nearby": "hint_three"},
        [{"joint_evidence_available": True, "member_identities": ["fragment_a", "fragment_b"]}],
    )

    assert graph["compositions"] == [{
        "composition_id": "composition_0001",
        "member_identities": ["fragment_a", "fragment_b"],
        "visible_source_frame_range": [1, 1],
        "supporting_frames": [1],
        "authority": "SOURCE_DERIVED_MEMBERSHIP",
    }]
    assert "nearby" in graph["standalone_identities"]
    assert "PHYSICAL_WORD_FRAGMENT" in _kinds(graph["relationships"])


def test_changing_spacing_is_time_varying_not_static_average():
    rows = relationships.infer_pair_relationships("a", "b", [
        {"frame": 1, "a_bbox": [0, 0, 20, 20], "b_bbox": [25, 0, 45, 20]},
        {"frame": 2, "a_bbox": [0, 0, 20, 20], "b_bbox": [60, 0, 80, 20]},
    ])
    gap = _kinds(rows)["HORIZONTAL_GAP"]

    assert gap["consistency"] == "ANIMATED_OR_TIME_VARYING_RELATIONSHIP"
    assert gap["measurement"]["spread_source_pixels"] == 35


def test_vertical_composition_is_reported_without_renderer_coordinates():
    rows = relationships.infer_pair_relationships("top", "bottom", [{
        "frame": 1, "a_bbox": [0, 0, 40, 20], "b_bbox": [0, 30, 40, 50],
    }])

    assert _kinds(rows)["ABOVE"]["source_identity"] == "top"
    assert _kinds(rows)["VERTICAL_GAP"]["measurement"]["source_pixels"] == 10
