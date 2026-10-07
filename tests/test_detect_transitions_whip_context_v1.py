import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np


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


def _metrics(*, direction="horizontal", context=None):
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
            "outgoing": {"p90_magnitude": 2.0, "direction": direction, "directional_coherence": 0.80},
            "incoming": {"p90_magnitude": 3.0, "direction": direction, "directional_coherence": 0.80},
        },
    }


def test_cross_cut_horizontal_spike_without_side_motion_is_candidate():
    kind, confidence, reasons = MODULE.classify_transition(_metrics(), _args())
    assert kind == "whip_pan_candidate"
    assert confidence == "medium"
    assert "within-shot" in " ".join(reasons)


def test_supported_horizontal_motion_remains_actionable_whip_pan():
    metrics = _metrics(
        context={
            "outgoing": {"p90_magnitude": 6.0, "direction": "horizontal", "directional_coherence": 0.55},
            "incoming": {"p90_magnitude": 1.0, "direction": "mixed", "directional_coherence": 0.10},
        }
    )
    kind, confidence, reasons = MODULE.classify_transition(metrics, _args())
    assert kind == "whip_pan"
    assert confidence == "high"
    assert "within-shot support" in " ".join(reasons)


def test_supported_vertical_slide_classification_remains_available():
    metrics = _metrics(
        direction="vertical",
        context={
            "outgoing": {"p90_magnitude": 6.0, "direction": "vertical", "directional_coherence": 0.55},
            "incoming": {"p90_magnitude": 1.0, "direction": "mixed", "directional_coherence": 0.10},
        },
    )
    kind, confidence, _ = MODULE.classify_transition(metrics, _args())
    assert kind == "slide_transition_candidate"
    assert confidence == "high"


def test_directional_context_never_measures_across_the_cut(monkeypatch):
    frames = [np.full((2, 2, 3), index, dtype=np.uint8) for index in range(7)]
    calls = []

    def fake_flow(a, b):
        left = int(a[0, 0, 0])
        right = int(b[0, 0, 0])
        calls.append((left, right))
        return {
            "mean_magnitude": 1.0,
            "p90_magnitude": float(right),
            "mean_x": 1.0,
            "mean_y": 0.0,
            "direction": "horizontal",
            "directional_coherence": 1.0,
            "radial_score": 0.0,
            "zoom_score": 0.0,
        }

    monkeypatch.setattr(MODULE, "flow_stats", fake_flow)
    result = MODULE.directional_context_stats(frames)

    assert calls == [(0, 1), (1, 2), (3, 4), (4, 5), (5, 6)]
    assert (2, 3) not in calls
    assert result["outgoing"]["pair_count"] == 2
    assert result["incoming"]["pair_count"] == 3


def test_whip_candidate_contract_is_non_actionable_and_zero_duration():
    parser = MODULE.build_parser()
    args = parser.parse_args(["--video", "x", "--shots", "y", "--output", "z"])
    duration = MODULE.transition_base_duration_frames("whip_pan_candidate", 24.0, args)
    actionable, reason = MODULE.is_editor_actionable(
        "whip_pan_candidate",
        "medium",
        {"ok": True},
        args,
    )
    assert duration == 0
    assert actionable is False
    assert reason == "candidate_transition_type:whip_pan_candidate"
