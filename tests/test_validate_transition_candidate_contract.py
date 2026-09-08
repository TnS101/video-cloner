from copy import deepcopy

import pytest

from scripts.planning.validate_edit_plan import validate_transition_contract


def candidate():
    return {
        "transition_type": "slide_transition_candidate",
        "confidence": "high",
        "cut_frame": 38,
        "editor_actionable": False,
        "is_editor_candidate": False,
        "duration_frames": 0,
        "duration_seconds": 0.0,
        "scores": {"directional_context": {"outgoing": {"p90_magnitude": 5.6}}},
        "reasons": ["vertical optical-flow spike with within-shot support"],
    }


def shot(transition):
    return {"shot_id": 1, "start_frame": 0, "end_frame": 38, "transition_to_next": transition}


def messages(transition):
    errors, _ = validate_transition_contract(
        shot(transition),
        {"shot_id": 2, "start_frame": 38, "end_frame": 78},
        24.0,
    )
    return [error["message"] for error in errors]


def test_high_confidence_slide_candidate_stays_observational_and_valid():
    transition = candidate()
    assert messages(transition) == []
    assert transition["editor_actionable"] is False
    assert transition["duration_frames"] == 0
    assert transition["scores"]["directional_context"]


@pytest.mark.parametrize(
    "change",
    [
        {"editor_actionable": True},
        {"is_editor_candidate": True},
        {"duration_frames": 8, "duration_seconds": 1 / 3},
        {"scores": {}, "reasons": []},
    ],
)
def test_malformed_or_executable_candidate_does_not_bypass_concrete_requirement(change):
    transition = deepcopy(candidate())
    transition.update(change)
    assert "high-confidence transition must have concrete transition_type" in messages(transition)


@pytest.mark.parametrize("transition_type", ["slide_transition", "whip_pan"])
def test_unsupported_executable_transition_stays_rejected(transition_type):
    transition = candidate() | {
        "transition_type": transition_type,
        "editor_actionable": True,
        "is_editor_candidate": True,
        "duration_frames": 8,
        "duration_seconds": 1 / 3,
    }
    assert "unsupported executable transition_type" in messages(transition)
