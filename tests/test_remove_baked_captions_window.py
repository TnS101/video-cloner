from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analysis" / "remove_baked_captions_window.py"
VALIDATOR = ROOT / "scripts" / "analysis" / "validate_baked_caption_removal_window.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_module(SCRIPT, "remove_baked_captions_window")
validator = load_module(VALIDATOR, "validate_baked_caption_removal_window")


def _write_pngs(directory: Path, prefix: str, count: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    image = np.zeros((8, 8, 3), np.uint8)
    for index in range(count):
        if not cv2.imwrite(str(directory / f"{prefix}_{index:06d}.png"), image):
            raise AssertionError("cv2.imwrite failed")


class RemoveBakedCaptionsWindowTests(unittest.TestCase):
    def test_normalize_cue_id(self) -> None:
        self.assertEqual(probe.normalize_cue_id("sub_0052"), "sub_052")
        self.assertEqual(probe.normalize_cue_id("VC_TEXTPLUS_0052_sub_052"), "sub_052")

    def test_observation_bbox_interpolates_short_gap(self) -> None:
        track = {
            "frame_observations": [
                {"timeline_frame": 10, "normalized_bbox": [0.1, 0.2, 0.3, 0.4]},
                {"timeline_frame": 12, "normalized_bbox": [0.3, 0.4, 0.5, 0.6]},
            ]
        }
        actual = probe._observation_bbox(track, 11)
        self.assertIsNotNone(actual)
        np.testing.assert_allclose(actual, [0.2, 0.3, 0.4, 0.5], rtol=0.0, atol=1e-12)

    def test_removal_window_unions_contract_sources(self) -> None:
        style = {"sub_052": {"start": 10.0, "end": 10.2}}
        lifecycle = {"sub_052": {"lifecycle_window": [242, 250]}}
        tracks = {"sub_052": {"geometry": {"first_visible_frame": 239, "last_visible_frame": 251}}}
        self.assertEqual(probe.removal_window("sub_052", 24.0, style, lifecycle, tracks), (237, 253))

    def test_caption_mask_excludes_foreground_and_detects_text(self) -> None:
        frame = np.full((120, 160, 3), (220, 190, 150), np.uint8)
        cv2.putText(frame, "COME", (30, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (25, 25, 25), 3, cv2.LINE_AA)
        foreground = np.zeros((120, 160), np.uint8)
        foreground[:, 75:95] = 255
        mask = probe.caption_pixel_mask(frame, [0.1, 0.2, 0.9, 0.7], foreground, [(25, 25, 25)])
        self.assertGreater(np.count_nonzero(mask), 0)
        self.assertEqual(np.count_nonzero(mask[:, 75:95]), 0)

    def test_inpaint_preserves_every_pixel_outside_mask(self) -> None:
        frame = np.full((60, 80, 3), 180, np.uint8)
        cv2.rectangle(frame, (25, 20), (50, 35), (0, 0, 0), -1)
        mask = np.zeros((60, 80), np.uint8)
        cv2.rectangle(mask, (25, 20), (50, 35), 255, -1)
        cleaned = probe.inpaint_caption_pixels(frame, mask)
        self.assertTrue(np.array_equal(cleaned[mask == 0], frame[mask == 0]))
        self.assertGreater(float(np.mean(cleaned[mask > 0])), float(np.mean(frame[mask > 0])))

    def test_validator_accepts_complete_terminal_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "probe"
            output.mkdir()
            frames = output / "frames"
            masks = output / "masks"
            foreground = output / "foreground_masks"
            _write_pngs(frames, "frame", 43)
            _write_pngs(masks, "mask", 43)
            _write_pngs(foreground, "foreground", 43)
            for name in ("cleaned.mkv", "before.jpg", "masks.jpg"):
                (output / name).write_bytes(b"x")
            report = {
                "task_id": probe.TASK_ID,
                "schema": probe.SCHEMA,
                "ok": True,
                "frame_window": [420, 463],
                "clean_window": [428, 452],
                "frame_count": 43,
                "target_frame_count": 24,
                "masked_target_frame_count": 22,
                "minimum_masked_target_frame_count": 18,
                "max_outside_mask_mean_abs_diff": 0.0,
                "max_protected_foreground_mean_abs_diff": 0.0,
                "median_masked_local_contrast_ratio": 0.6,
                "segmentation_backend_counts": {"paddle_humanseg": 43},
                "checks": {"all": True},
                "artifacts": {
                    "cleaned_video": str(output / "cleaned.mkv"),
                    "before_after_contact_sheet": str(output / "before.jpg"),
                    "mask_contact_sheet": str(output / "masks.jpg"),
                    "cleaned_frames": str(frames),
                    "caption_masks": str(masks),
                    "foreground_masks": str(foreground),
                },
            }
            (output / "report.json").write_text(json.dumps(report), encoding="utf-8")
            self.assertTrue(validator.validate(output)["ok"])

    def test_validator_rejects_foreground_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "probe"
            output.mkdir()
            (output / "report.json").write_text(
                json.dumps(
                    {
                        "task_id": probe.TASK_ID,
                        "schema": probe.SCHEMA,
                        "ok": True,
                        "frame_window": [420, 463],
                        "clean_window": [428, 452],
                        "frame_count": 43,
                        "target_frame_count": 24,
                        "masked_target_frame_count": 24,
                        "minimum_masked_target_frame_count": 18,
                        "max_outside_mask_mean_abs_diff": 0.0,
                        "max_protected_foreground_mean_abs_diff": 0.1,
                        "median_masked_local_contrast_ratio": 0.5,
                        "segmentation_backend_counts": {"paddle_humanseg": 43},
                        "checks": {},
                        "artifacts": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "foreground_changed"):
                validator.validate(output)


if __name__ == "__main__":
    unittest.main()
