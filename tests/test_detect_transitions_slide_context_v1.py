import importlib.util
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "video_cloner" / "analysis" / "transitions.py"
SPEC = importlib.util.spec_from_file_location("detect_transitions_proxy", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _args():
    return SimpleNamespace(
        dip_black_ratio=0.55,
        dip_luma_delta=0.14,
        flash_white_ratio=0.45,
        flash_luma_delta=0.16,
        directional_flow_p90=9.0,
        directional_high_flow_p90=13.0,
        directional_hist_delta=0.30,
        directional_coherence=0.10,
        whip_context_flow_p90=4.5,
        whip_context_coherence=0.25,
        slide_context_flow_p90=4.5,
        slide_context_coherence=0.25,
        blur_drop=0.45,
        blur_flow_p90=3.0,
        zoom_score=0.55,
        crossfade_gradual_score=0.58,
        crossfade_hist_delta=0.20,
        crossfade_max_flow_p90=8.0,
        hard_cut_hist_delta=0.35,
        hard_cut_luma_delta=0.22,
    )


def _metrics(*, context=None, direction="vertical"):
    return {
        "hist_delta": 0.70,
        "luma_delta": 0.05,
        "black_ratio_max": 0.02,
        "white_ratio_max": 0.02,
        "blur_drop": 0.10,
        "gradual_change_score": 0.10,
        "transition_strength": 0.70,
        "zoom_score": 0.05,
        "flow": {
            "p90_magnitude": 14.0,
            "direction": direction,
            "directional_coherence": 0.35,
        },
        "directional_context": context
        or {
            "outgoing": {"p90_magnitude": 1.5, "direction": "vertical", "directional_coherence": 0.70},
            "incoming": {"p90_magnitude": 2.0, "direction": "mixed", "directional_coherence": 0.20},
        },
    }


def test_cross_cut_vertical_spike_without_side_motion_is_candidate():
    kind, confidence, reasons = MODULE.classify_transition(_metrics(), _args())
    assert kind == "slide_transition_candidate"
    assert confidence == "medium"
    assert "within-shot" in " ".join(reasons)


def test_supported_vertical_motion_remains_high_confidence_candidate():
    metrics = _metrics(
        context={
            "outgoing": {"p90_magnitude": 6.5, "direction": "vertical", "directional_coherence": 0.55},
            "incoming": {"p90_magnitude": 1.0, "direction": "mixed", "directional_coherence": 0.10},
        }
    )
    kind, confidence, reasons = MODULE.classify_transition(metrics, _args())
    parser = MODULE.build_parser()
    args = parser.parse_args(["--video", "x", "--shots", "y", "--output", "z"])
    duration = MODULE.transition_base_duration_frames(kind, 24.0, args)
    actionable, reason = MODULE.is_editor_actionable(kind, confidence, {"ok": True}, args)

    assert kind == "slide_transition_candidate"
    assert confidence == "high"
    assert "within-shot support" in " ".join(reasons)
    assert metrics["directional_context"]["outgoing"] == {
        "p90_magnitude": 6.5,
        "direction": "vertical",
        "directional_coherence": 0.55,
    }
    assert duration == 0
    assert actionable is False
    assert reason == "candidate_transition_type:slide_transition_candidate"


def test_horizontal_whip_branch_is_unchanged_by_slide_guard():
    metrics = _metrics(
        direction="horizontal",
        context={
            "outgoing": {"p90_magnitude": 6.5, "direction": "horizontal", "directional_coherence": 0.55},
            "incoming": {"p90_magnitude": 1.0, "direction": "mixed", "directional_coherence": 0.10},
        },
    )
    kind, confidence, _ = MODULE.classify_transition(metrics, _args())
    assert kind == "whip_pan"
    assert confidence == "high"


def test_slide_candidate_contract_is_non_actionable_and_zero_duration():
    parser = MODULE.build_parser()
    args = parser.parse_args(["--video", "x", "--shots", "y", "--output", "z"])
    duration = MODULE.transition_base_duration_frames("slide_transition_candidate", 24.0, args)
    actionable, reason = MODULE.is_editor_actionable(
        "slide_transition_candidate",
        "medium",
        {"ok": True},
        args,
    )
    assert duration == 0
    assert actionable is False
    assert reason == "candidate_transition_type:slide_transition_candidate"


def test_slide_context_thresholds_are_exposed_by_parser():
    parser = MODULE.build_parser()
    args = parser.parse_args(["--video", "x", "--shots", "y", "--output", "z"])
    assert args.slide_context_flow_p90 == 4.5
    assert args.slide_context_coherence == 0.25
