from scripts.analysis.generate_step4a_timing_persistence import overlaps


def test_half_open_overlap_and_adjacency():
    def row(identity, start, end):
        return {"identity": identity, "source": {"visibility_intervals": [[start, end]]}}

    result = overlaps([row("a", 1, 5), row("b", 4, 8), row("c", 8, 9)])

    assert result == [{
        "identity_a": "a", "identity_b": "b",
        "source_overlap_intervals": [[4, 5]], "generated_overlap_intervals": [[4, 5]],
        "source_overlap_frame_count": 1, "generated_overlap_frame_count": 1,
        "interval_match": True, "frame_count_delta": 0,
    }]
