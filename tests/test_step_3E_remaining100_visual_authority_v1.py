from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "scripts" / "analysis" / "build_step_3E_remaining100_visual_authority_v1.py"
VALIDATE_PATH = ROOT / "scripts" / "analysis" / "validate_step_3E_remaining100_visual_authority_v1.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


b = load_module(BUILD_PATH, "remaining100_builder")
v = load_module(VALIDATE_PATH, "remaining100_validator")


def test_cue_key_normalizes_zero_padding():
    assert b.cue_key("sub_0005") == "sub_005"
    assert b.cue_key("sub_85") == "sub_085"


def test_hex_to_bgr():
    assert b.hex_to_bgr("#112233") == (0x33, 0x22, 0x11)


def test_canonical_hash_stable_for_dict_order():
    assert b.canonical_sha256({"b": 2, "a": 1}) == b.canonical_sha256({"a": 1, "b": 2})


def test_seed_fill_uses_existing_visual_fill():
    fill_map = {"sub_001": {"target_fill": {"hex": "#abcdef"}}}
    value, bgr = b.seed_fill(["sub_001"], fill_map)
    assert value == "#abcdef"
    assert bgr == (0xEF, 0xCD, 0xAB)


def test_seed_geometry_converts_fusion_center_to_top_origin():
    position = {
        "sub_001": {
            "target_center": [0.4, 0.7],
            "style_profile_id": "style_01",
            "source_position": {},
        }
    }
    result = b.seed_geometry(
        ["sub_001"],
        "word",
        position,
        {},
        {},
        {"style_01": {"typography": {"font_height_ratio": 0.04}}},
        540,
        960,
    )
    assert result["center_top_origin"] == [0.4, 0.3]
    assert result["expected_height_px"] == pytest.approx(38.4, abs=0.01)


def synthetic_text_frame(fill=(245, 245, 245)):
    frame = np.zeros((960, 540, 3), dtype=np.uint8)
    # Multiple separated glyph-like bars produce edge-supported colored pixels.
    x = 205
    for width in (18, 22, 16, 20, 18):
        cv2.rectangle(frame, (x, 440), (x + width, 492), fill, -1)
        x += width + 8
    return frame


def test_pixel_measure_detects_text_like_pixels():
    frame = synthetic_text_frame()
    result = b.pixel_measure(frame, [0.5, 0.485], (245, 245, 245), 170, 55)
    assert result["score"] > 0
    assert result["candidate_pixels"] > 0
    assert result["bbox"] is not None


def test_pixel_measure_rejects_empty_dark_frame_for_white_fill():
    frame = np.zeros((960, 540, 3), dtype=np.uint8)
    result = b.pixel_measure(frame, [0.5, 0.5], (245, 245, 245), 170, 55)
    assert result["score"] == 0
    assert result["bbox"] is None


def test_derive_visibility_uses_pixel_scores_not_seed_as_authority():
    frames = list(range(10, 20))
    scores = [0, 0, 0.001, 0.004, 0.006, 0.006, 0.003, 0.0001, 0, 0]
    result = b.derive_visibility(scores, frames, [12, 18])
    assert result["ok"] is True
    assert result["window"][0] >= 12
    assert result["window"][1] <= 18
    assert result["peak_frame"] in (14, 15)


def test_derive_visibility_fails_zero_signal():
    result = b.derive_visibility([0, 0, 0], [5, 6, 7], [5, 7])
    assert result["ok"] is False
    assert result["window"] is None


def test_build_frame_path_is_dense_and_coordinate_converted():
    measures = {
        20: {"score": 0.5, "bbox": [200, 400, 300, 450]},
        21: {"score": 1.0, "bbox": [210, 402, 310, 452]},
        22: {"score": 0.5, "bbox": [220, 404, 320, 454]},
    }
    path = b.build_frame_path(
        [20, 23],
        measures,
        [0.5, 0.45],
        0.1,
        540,
        960,
        {"peak_score": 1.0},
    )
    assert [row["timeline_frame"] for row in path] == [20, 21, 22]
    for row in path:
        assert row["position_fusion"][0] == pytest.approx(row["position_top_origin"][0], abs=1e-6)
        assert row["position_fusion"][1] == pytest.approx(1 - row["position_top_origin"][1], abs=2e-6)


def test_lifecycle_seed_prefers_visual_primary():
    lifecycle = {
        "sub_001": {
            "timing_authority": "visual_primary",
            "lifecycle_window": [10, 18],
            "visual_source_exactness": "source_observed",
        }
    }
    result = b.lifecycle_seed(["sub_001"], lifecycle)
    assert result["visual_primary"] is True
    assert result["visual_window"] == [10, 18]


def test_lifecycle_seed_does_not_promote_transcript_fallback():
    lifecycle = {
        "sub_001": {
            "timing_authority": "transcript_fallback",
            "lifecycle_window": [10, 18],
        }
    }
    result = b.lifecycle_seed(["sub_001"], lifecycle)
    assert result["visual_primary"] is False
    assert result["visual_window"] is None


def test_validator_frame_path_rejects_transcript_style_gaps():
    instance = {
        "instance_id": "x",
        "visual_window": [1, 4],
        "frame_path": [
            {
                "timeline_frame": 1,
                "position_top_origin": [0.5, 0.4],
                "position_fusion": [0.5, 0.6],
                "opacity_factor": 1.0,
                "size_scale": 1.0,
                "application_size_candidate": 0.1,
            },
            {
                "timeline_frame": 3,
                "position_top_origin": [0.5, 0.4],
                "position_fusion": [0.5, 0.6],
                "opacity_factor": 1.0,
                "size_scale": 1.0,
                "application_size_candidate": 0.1,
            },
        ],
    }
    with pytest.raises(v.ValidationError):
        v.validate_frame_path(instance)
