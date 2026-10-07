from __future__ import annotations

import sys
import types
from types import SimpleNamespace


if "paddleocr" not in sys.modules:
    paddleocr = types.ModuleType("paddleocr")
    paddleocr.PaddleOCR = object
    sys.modules["paddleocr"] = paddleocr

import video_cloner.analysis.caption_style as detector


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        mode="viral_transcript_aware",
        viral_min_y=0.18,
        viral_min_x=0.10,
        viral_max_x=0.90,
        transcript_match_threshold=0.30,
        regular_caption_score_threshold=0.46,
        enable_visual_spoken_fallback=True,
        visual_spoken_min_confidence=0.55,
        visual_spoken_score_threshold=0.56,
        visual_spoken_min_y=0.38,
        visual_spoken_max_y=0.84,
        visual_spoken_min_x=0.12,
        visual_spoken_max_x=0.88,
        visual_spoken_min_font_ratio=0.020,
        visual_spoken_min_width_ratio=0.055,
        visual_hook_score_threshold=0.64,
        hook_min_confidence=0.70,
        hook_min_y=0.15,
        top_ui_caption_max_y=0.40,
        top_ui_max_font_ratio=0.018,
        top_ui_allow_match_threshold=0.55,
    )


def _detection(text: str, timestamp: float = 5.4) -> dict:
    return {
        "text": text,
        "timestamp": timestamp,
        "confidence": 0.70,
        "center": {"x": 0.50, "y": 0.25},
        "estimated_font_height_ratio": 0.06,
        "estimated_box_width_ratio": 0.30,
        "has_dark_stroke": True,
        "has_shadow": False,
        "has_bright_text": True,
    }


def _context(text: str, timestamp: float, cue_text: str, start: float, end: float) -> dict:
    return {
        "timestamp": timestamp,
        "text": text,
        "cue_ids": ["context"],
        "cues": [{
            "id": "nearby",
            "source": "subtitle_candidates",
            "text": cue_text,
            "start": start,
            "end": end,
        }],
    }


def test_nearby_individual_cue_rescues_sign_ocr_variants(monkeypatch):
    monkeypatch.setattr(detector, "visual_caption_score", lambda _det: 0.80)
    monkeypatch.setattr(detector, "hook_visual_score", lambda _det: 0.43)

    for text, timestamp in (("sion", 5.4), ("Sian", 6.045)):
        accepted, score = detector.classify_caption_candidate(
            _detection(text, timestamp),
            _context("before the sign hits the yard", timestamp, "sign", 5.42, 5.64),
            _args(),
        )
        assert accepted is True
        assert score["transcript_match_score"] == 0.375
        assert score["score"] >= 0.46


def test_distant_individual_cue_does_not_rescue_branding_collision(monkeypatch):
    monkeypatch.setattr(detector, "visual_caption_score", lambda _det: 0.61)
    monkeypatch.setattr(detector, "hook_visual_score", lambda _det: 0.20)

    accepted, score = detector.classify_caption_candidate(
        _detection("REALTY", 32.242),
        _context("", 32.242, "really", 31.00, 31.44),
        _args(),
    )

    assert accepted is False
    assert score["transcript_match_score"] == 0.0


def test_individual_match_cannot_replace_stronger_existing_context(monkeypatch):
    monkeypatch.setattr(detector, "visual_caption_score", lambda _det: 0.80)
    monkeypatch.setattr(detector, "hook_visual_score", lambda _det: 0.43)
    detection = _detection("matching", 10.0)
    args = _args()

    without_individual, without_score = detector.classify_caption_candidate(
        detection, {"timestamp": 10.0, "text": "matching", "cue_ids": [], "cues": []}, args
    )
    with_individual, with_score = detector.classify_caption_candidate(
        detection, _context("matching", 10.0, "x", 9.9, 10.1), args
    )

    assert with_individual == without_individual
    assert with_score["transcript_match_score"] == without_score["transcript_match_score"]
    assert with_score["score"] == without_score["score"]
