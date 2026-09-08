from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "scripts" / "analysis"
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))
SCRIPT = ANALYSIS / "remove_baked_captions_window_temporal.py"
VALIDATOR = ANALYSIS / "validate_baked_caption_removal_window_temporal.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_module(SCRIPT, "remove_baked_captions_window_temporal")
validator = load_module(VALIDATOR, "validate_baked_caption_removal_window_temporal")


class TemporalCaptionRemovalTests(unittest.TestCase):
    def test_donor_offsets_are_symmetric(self) -> None:
        self.assertEqual(probe.donor_offsets(12, 3), (-12, -9, -6, -3, 3, 6, 9, 12))

    def test_caption_region_mask_rasterizes_tracked_bbox(self) -> None:
        mask = probe.caption_region_mask((100, 200, 3), (0.25, 0.30, 0.75, 0.60))
        self.assertGreater(int(np.count_nonzero(mask)), 0)
        ratio = float(np.count_nonzero(mask)) / float(mask.size)
        self.assertGreaterEqual(ratio, 0.10)
        self.assertLessEqual(ratio, 0.20)

    def test_full_masks_do_not_drop_active_caption_boxes(self) -> None:
        frames = [np.zeros((100, 200, 3), np.uint8) for _ in range(3)]
        masks, active = probe.build_full_caption_masks(
            frames=frames,
            frame_start=10,
            fps=30.0,
            target_cues=("sub_001",),
            style_map={"sub_001": {"placement": {"normalized_bbox": [0.3, 0.4, 0.7, 0.6]}}},
            profile_map={},
            lifecycle_map={},
            track_map={},
            removal_windows={"sub_001": (10, 13)},
        )
        self.assertEqual(active, [["sub_001"], ["sub_001"], ["sub_001"]])
        self.assertTrue(all(int(np.count_nonzero(mask)) > 0 for mask in masks))

    def test_flow_identity_is_near_zero(self) -> None:
        image = np.zeros((80, 100, 3), np.uint8)
        cv2.circle(image, (50, 40), 15, (255, 255, 255), -1)
        mask = np.zeros((80, 100), np.uint8)
        _, flow, consistency = probe.flow_pair(image, image, mask, mask, 100)
        self.assertLess(float(np.median(np.linalg.norm(flow, axis=2))), 0.05)
        self.assertLess(float(np.median(consistency)), 0.05)

    def test_reconstruction_uses_uncaptioned_temporal_donor(self) -> None:
        height, width = 96, 128
        frames = []
        masks = []
        foreground = []
        for index in range(5):
            frame = np.full((height, width, 3), (180, 160, 130), np.uint8)
            x = 40 + index * 2
            cv2.rectangle(frame, (x, 25), (x + 28, 80), (35, 70, 160), -1)
            mask = np.zeros((height, width), np.uint8)
            if index == 2:
                cv2.putText(frame, "X", (50, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 4, cv2.LINE_AA)
                cv2.rectangle(mask, (45, 25), (82, 65), 255, -1)
            frames.append(frame)
            masks.append(mask)
            fg = np.zeros((height, width), np.uint8)
            cv2.rectangle(fg, (x, 25), (x + 28, 80), 255, -1)
            foreground.append(fg)
        cleaned, _, meta = probe.reconstruct_frame(
            2,
            frames,
            masks,
            foreground,
            (-2, -1, 1, 2),
            128,
            5.0,
            0.1,
        )
        self.assertGreater(meta["coverage_ratio"], 0.45)
        original_white = np.mean(frames[2][masks[2] > 0])
        cleaned_white = np.mean(cleaned[masks[2] > 0])
        self.assertLess(cleaned_white, original_white)
        self.assertTrue(np.array_equal(cleaned[masks[2] == 0], frames[2][masks[2] == 0]))

    def test_palette_residual_falls_after_replacement(self) -> None:
        mask = np.zeros((40, 60), np.uint8)
        mask[10:30, 10:50] = 255
        before = np.full((40, 60, 3), 150, np.uint8)
        before[10:30, 10:50] = (255, 255, 255)
        after = np.full((40, 60, 3), 150, np.uint8)
        before_ratio = probe.palette_residual_ratio(before, mask, [(255, 255, 255)])
        after_ratio = probe.palette_residual_ratio(after, mask, [(255, 255, 255)])
        self.assertGreater(before_ratio, after_ratio)

    def test_validator_accepts_complete_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            artifacts = {}
            for key, filename in {
                "cleaned_video": "cleaned.mkv",
                "before_after_contact_sheet": "before.jpg",
                "mask_contact_sheet": "mask.jpg",
                "donor_coverage_contact_sheet": "coverage.jpg",
            }.items():
                path = output / filename
                path.write_bytes(b"x")
                artifacts[key] = str(path)
            for key, (directory_name, prefix) in {
                "cleaned_frames": ("frames", "frame"),
                "caption_masks": ("masks", "mask"),
                "foreground_masks": ("foreground", "foreground"),
                "donor_coverage": ("coverage", "coverage"),
            }.items():
                directory = output / directory_name
                directory.mkdir()
                for index in range(43):
                    (directory / f"{prefix}_{index:06d}.png").write_bytes(b"x")
                artifacts[key] = str(directory)
            report = {
                "task_id": probe.TASK_ID,
                "schema": probe.SCHEMA,
                "ok": True,
                "context_window": [416, 468],
                "output_window": [420, 463],
                "clean_window": [428, 452],
                "output_frame_count": 43,
                "target_frame_count": 24,
                "max_outside_mask_mean_abs_diff": 0.0,
                "median_donor_coverage_ratio": 0.4,
                "max_unresolved_ratio": 0.8,
                "median_masked_local_contrast_ratio": 0.7,
                "median_palette_residual_ratio": 1.0,
                "palette_residual_metric_role": "diagnostic_only",
                "minimum_target_mask_area_ratio": 0.03,
                "maximum_target_mask_area_ratio": 0.07,
                "median_inside_mask_mean_abs_diff": 12.0,
                "segmentation_backend_counts": {"paddle_humanseg": 52},
                "checks": {"all": True},
                "artifacts": artifacts,
            }
            (output / "report.json").write_text(json.dumps(report), encoding="utf-8")
            self.assertTrue(validator.validate(output)["ok"])

    def test_validator_rejects_insufficient_donor_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "report.json").write_text(
                json.dumps(
                    {
                        "task_id": probe.TASK_ID,
                        "schema": probe.SCHEMA,
                        "ok": True,
                        "context_window": [416, 468],
                        "output_window": [420, 463],
                        "clean_window": [428, 452],
                        "output_frame_count": 43,
                        "target_frame_count": 24,
                        "max_outside_mask_mean_abs_diff": 0.0,
                        "median_donor_coverage_ratio": 0.2,
                        "max_unresolved_ratio": 0.2,
                        "median_masked_local_contrast_ratio": 0.7,
                        "median_palette_residual_ratio": 1.0,
                        "palette_residual_metric_role": "diagnostic_only",
                        "minimum_target_mask_area_ratio": 0.03,
                        "maximum_target_mask_area_ratio": 0.07,
                        "median_inside_mask_mean_abs_diff": 12.0,
                        "segmentation_backend_counts": {"paddle_humanseg": 52},
                        "checks": {},
                        "artifacts": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "donor_coverage_insufficient"):
                validator.validate(output)


    def test_validator_rejects_unbounded_target_mask_area(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "report.json").write_text(
                json.dumps(
                    {
                        "task_id": probe.TASK_ID,
                        "schema": probe.SCHEMA,
                        "ok": True,
                        "context_window": [416, 468],
                        "output_window": [420, 463],
                        "clean_window": [428, 452],
                        "output_frame_count": 43,
                        "target_frame_count": 24,
                        "max_outside_mask_mean_abs_diff": 0.0,
                        "median_donor_coverage_ratio": 0.4,
                        "max_unresolved_ratio": 0.8,
                        "median_masked_local_contrast_ratio": 0.7,
                        "median_palette_residual_ratio": 1.0,
                        "palette_residual_metric_role": "diagnostic_only",
                        "minimum_target_mask_area_ratio": 0.03,
                        "maximum_target_mask_area_ratio": 0.25,
                        "median_inside_mask_mean_abs_diff": 12.0,
                        "segmentation_backend_counts": {"paddle_humanseg": 52},
                        "checks": {},
                        "artifacts": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "target_mask_area_too_large"):
                validator.validate(output)


if __name__ == "__main__":
    unittest.main()
