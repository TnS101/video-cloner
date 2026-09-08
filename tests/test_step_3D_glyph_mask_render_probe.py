from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_glyph_mask_render_probe.py"
ANALYSIS_PATH = ROOT / "scripts" / "analysis" / "build_textplus_glyph_masks_from_renders.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load_module("glyph_runtime_test", RUNTIME_PATH)
analysis = load_module("glyph_analysis_test", ANALYSIS_PATH)


class FakeItem:
    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    def GetName(self):
        return self.name

    def SetClipEnabled(self, value: bool):
        self.enabled = value
        return True

    def GetClipEnabled(self):
        return self.enabled


class FakeTimeline:
    def __init__(self, items: list[FakeItem]):
        self.items = items

    def GetTrackCount(self, track_type: str):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type: str, track_index: int):
        return self.items if track_type == "video" and track_index == 1 else []


class GlyphProbeTests(unittest.TestCase):
    def test_select_lossless_render_format_prefers_png_16bit(self):
        result = runtime.select_lossless_render_format(
            {"QuickTime": "mov", "PNG": "png", "TIFF": "tif"},
            {
                "QuickTime": {"DNxHR HQX": "DNXHRHQX"},
                "PNG": {"RGB 8-bit": "RGB8", "RGB 16-bit": "RGB16"},
                "TIFF": {"RGB 16-bit": "RGB16"},
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected"]["format"], "PNG")
        self.assertEqual(result["selected"]["codec"], "RGB16")

    def test_select_lossless_render_format_rejects_video_only(self):
        result = runtime.select_lossless_render_format(
            {"QuickTime": "mov", "MP4": "mp4"},
            {"QuickTime": {"DNxHR": "DNXHR"}, "MP4": {"H.264": "H264"}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "lossless_image_sequence_unavailable")

    def test_build_render_settings_is_bounded_and_silent(self):
        settings = runtime.build_render_settings(
            Path("C:/tmp/out"),
            "glyph",
            {"width": 1080, "height": 1920, "frame_rate": 25.0},
        )
        self.assertEqual(settings["MarkIn"], 420)
        self.assertEqual(settings["MarkOut"], 462)
        self.assertFalse(settings["SelectAllFrames"])
        self.assertTrue(settings["ExportVideo"])
        self.assertFalse(settings["ExportAudio"])

    def test_render_status_classification(self):
        self.assertTrue(runtime.status_is_success({"JobStatus": "Complete"}))
        self.assertTrue(runtime.status_is_failure({"JobStatus": "Failed"}))
        self.assertFalse(runtime.status_is_success({"JobStatus": "Rendering"}))
        self.assertFalse(runtime.status_is_failure({"JobStatus": "Rendering"}))

    def test_disable_generated_items_disables_exact_names(self):
        timeline = FakeTimeline([FakeItem("A"), FakeItem("B"), FakeItem("base")])
        result = runtime.disable_generated_items(timeline, ["A", "B"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["disabled_count"], 2)
        self.assertFalse(timeline.items[0].enabled)
        self.assertFalse(timeline.items[1].enabled)
        self.assertTrue(timeline.items[2].enabled)

    def test_compare_inventory_ignores_unique_id_by_design(self):
        left = [{
            "name": "clip", "track_index": 1, "start": 0, "end": 10,
            "duration": 10, "media_pool_item_name": "media", "fusion_comp_count": 0,
            "unique_id": "left",
        }]
        right = [dict(left[0], unique_id="right")]
        self.assertTrue(runtime.compare_stable_inventory(left, right)["ok"])

    def test_build_glyph_mask_is_compact_and_nonempty(self):
        without = np.full((120, 200, 3), 80, dtype=np.uint8)
        with_text = without.copy()
        cv2.putText(with_text, "COME", (25, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (240, 240, 240), 3, cv2.LINE_AA)
        mask, metrics = analysis.build_glyph_mask(with_text, without)
        self.assertGreater(metrics["mask_pixels"], 0)
        self.assertLess(metrics["area_ratio"], 0.25)
        self.assertLessEqual(metrics["max_component_fill_ratio"], 0.93)
        self.assertEqual(mask.shape, without.shape[:2])

    def test_build_glyph_mask_empty_for_identical_frames(self):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        _, metrics = analysis.build_glyph_mask(frame, frame)
        self.assertEqual(metrics["mask_pixels"], 0)
        self.assertEqual(metrics["area_ratio"], 0.0)

    def test_expected_target_names_requires_115_unique_names(self):
        plan = {"instances": [{"target_name": f"item_{index:03d}"} for index in range(115)]}
        names = runtime.expected_target_names(plan)
        self.assertEqual(len(names), 115)
        plan["instances"][-1]["target_name"] = plan["instances"][0]["target_name"]
        with self.assertRaises(ValueError):
            runtime.expected_target_names(plan)


if __name__ == "__main__":
    unittest.main()
