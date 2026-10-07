from scripts.standalone.video_cloner_mvp_transition_filter import filter_mvp_transitions


def test_unsupported_transition_is_demoted_without_losing_cut_evidence():
    source = {
        "success": True,
        "schema": "video_cloner_transitions",
        "transitions": [
            {
                "cut_frame": 461,
                "transition_type": "whip_pan",
                "editor_actionable": True,
                "duration_frames": 8,
                "duration_seconds": 0.3333,
                "outgoing_frames": 4,
                "incoming_frames": 4,
                "scores": {"directional_context": {"outgoing": {}, "incoming": {}}},
            },
            {"cut_frame": 99, "transition_type": "flash_cut", "editor_actionable": True},
        ],
    }

    filtered = filter_mvp_transitions(source)
    candidate, supported = filtered["transitions"]

    assert source["transitions"][0]["transition_type"] == "whip_pan"
    assert candidate["cut_frame"] == 461
    assert (candidate["transition_type"], candidate["editor_actionable"]) == ("whip_pan_candidate", False)
    assert (candidate["duration_frames"], candidate["outgoing_frames"], candidate["incoming_frames"]) == (0, 0, 0)
    assert supported["transition_type"] == "flash_cut" and supported["editor_actionable"] is True
    assert filtered["summary"] == {"flash_cut": 1, "whip_pan_candidate": 1}
    assert filtered["mvp_filter"]["demoted_count"] == 1
