import json
from pathlib import Path

import pytest

from video_cloner.transition_policy import TransitionFilterError, filter_mvp_transitions, normalize_oss003_recipes


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


def test_oss003_normalizes_only_the_three_source_backed_blur_handoffs():
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / "data/DZatr0EJt4B/analysis/DZatr0EJt4B_transitions_mvp_resolve.json").read_text())
    normalized = normalize_oss003_recipes(source)

    assert normalized["schema"] == "video_cloner.transition_recipe_set.v1"
    assert [(row["boundary_frame"], row["duration_frames"]) for row in normalized["recipes"]] == [(80, 11), (286, 11), (376, 11)]
    assert [row["intensity"] for row in normalized["recipes"]] == [0.6474, 0.4298, 0.2806]
    assert all(row["direction"] == "none" and row["family"] == "blur_handoff" for row in normalized["recipes"])
    assert normalized["deferred_to_oss004"] == [461]
    assert normalized["analysis_only"] == [211, 629]

    source["transitions"][0]["duration_frames"] = 0
    with pytest.raises(TransitionFilterError, match="cut 80"):
        normalize_oss003_recipes(source)
