from __future__ import annotations

import sys
import types

import numpy as np
import pytest


if "paddleocr" not in sys.modules:
    paddleocr = types.ModuleType("paddleocr")
    paddleocr.PaddleOCR = object
    sys.modules["paddleocr"] = paddleocr

from scripts.analysis.detect_caption_style import box_to_bbox, refine_merged_ocr_regions


def _box(x1: float, y1: float, x2: float, y2: float) -> list[list[float]]:
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class FakeOCR:
    def __init__(self, calls: list[tuple[list[list[list[float]]], list[tuple[str, float]]]]):
        self.calls = list(calls)
        self.recognitions: list[tuple[str, float]] = []

    def text_detector(self, _image):
        boxes, self.recognitions = self.calls.pop(0)
        return np.asarray(boxes, dtype=np.float32), 0.0

    def text_recognizer(self, crops):
        assert len(crops) == len(self.recognitions)
        return self.recognitions, 0.0


@pytest.mark.parametrize(
    "recognitions",
    [[], [("", 0.99)], [("child", 0.49)], [("child", 0.99)]],
)
def test_weak_crop_refinement_preserves_parent_exactly(recognitions):
    parent = (_box(100, 200, 300, 300), "parent", 0.91)
    child_boxes = [_box(30, 30, 330, 180) for _ in recognitions]

    result = refine_merged_ocr_regions(FakeOCR([(child_boxes, recognitions)]), np.zeros((600, 600, 3), np.uint8), [parent])

    assert result == [parent]


def test_multi_child_replacement_maps_geometry_to_source_coordinates():
    parent = (_box(100, 200, 300, 300), "merged", 0.91)
    ocr = FakeOCR([(
        [_box(30, 60, 330, 180), _box(360, 60, 570, 180)],
        [("left", 0.95), ("right", 0.90)],
    )])

    result = refine_merged_ocr_regions(ocr, np.zeros((600, 600, 3), np.uint8), [parent])

    assert [(text, confidence) for _, text, confidence in result] == [("left", 0.95), ("right", 0.90)]
    assert box_to_bbox(result[0][0], 600, 600) == [110, 220, 210, 260]
    assert box_to_bbox(result[1][0], 600, 600) == [220, 220, 290, 260]


def test_refined_child_duplicate_prefers_direct_detection():
    merged = (_box(100, 100, 300, 220), "merged", 0.91)
    direct = (_box(220, 120, 280, 180), "direct", 0.88)
    ocr = FakeOCR([
        (
            [_box(15, 30, 315, 180), _box(330, 30, 570, 180), _box(360, 60, 540, 240)],
            [("left", 0.95), ("right", 0.90), ("duplicate", 0.99)],
        ),
        ([], []),
    ])

    result = refine_merged_ocr_regions(ocr, np.zeros((600, 600, 3), np.uint8), [merged, direct])

    assert [text for _, text, _ in result] == ["direct", "left", "right"]
    assert result[0] == direct


def test_simple_parent_with_one_child_remains_unsplit():
    parent = (_box(40, 50, 200, 120), "simple", 0.97)
    ocr = FakeOCR([([_box(15, 15, 450, 180)], [("simple", 0.99)])])

    assert refine_merged_ocr_regions(ocr, np.zeros((300, 300, 3), np.uint8), [parent]) == [parent]


def test_crop_refinement_failure_preserves_parent_exactly():
    parent = (_box(40, 50, 200, 120), "simple", 0.97)

    class FailingOCR:
        def text_detector(self, _image):
            raise RuntimeError("crop OCR unavailable")

        def text_recognizer(self, _crops):
            raise AssertionError("recognizer must not run")

    assert refine_merged_ocr_regions(FailingOCR(), np.zeros((300, 300, 3), np.uint8), [parent]) == [parent]
