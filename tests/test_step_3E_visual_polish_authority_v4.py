from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts/davinci/build_step_3E_visual_polish_authority_v4.py"
SPEC = importlib.util.spec_from_file_location("step3e_v4_builder_under_test", BUILDER_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)
AUTHORITY = ROOT / builder.OUTPUT
MEASUREMENTS = ROOT / builder.MEASUREMENTS


class Step3ETemporalVisualAuthorityV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authority = json.loads(AUTHORITY.read_text(encoding="utf-8-sig"))
        cls.measurements = json.loads(MEASUREMENTS.read_text(encoding="utf-8-sig"))
        cls.tokens = [token for group in cls.authority["groups"] for token in group["tokens"]]
        cls.by = {token["visual_token_id"]: token for token in cls.tokens}

    def test_exact_scope_is_seven_groups_and_seventeen_tokens(self):
        self.assertEqual(self.authority["summary"]["group_count"], 7)
        self.assertEqual(self.authority["summary"]["visual_token_count"], 17)
        self.assertEqual(len(self.by), 17)

    def test_every_visual_frame_has_explicit_position_size_and_opacity(self):
        self.assertEqual(self.authority["summary"]["explicit_frame_row_count"], 397)
        for token in self.tokens:
            start, end = token["visual_window"]
            self.assertEqual([row["timeline_frame"] for row in token["frame_path"]], list(range(start, end)))
            self.assertTrue(all(len(row["position_top_origin"]) == 2 and len(row["position_fusion"]) == 2 for row in token["frame_path"]))

    def test_transcript_never_controls_visual_timing(self):
        self.assertFalse(self.authority["authority_policy"]["transcript_timing_authority"])
        self.assertTrue(all(token["transcript_timing_promoted_to_authority"] is False for token in self.tokens))

    def test_all_tokens_have_source_and_generated_pixel_anchors(self):
        self.assertEqual(len(self.measurements["tokens"]), 17)
        for token in self.tokens:
            anchor = token["source_pixel_anchor"]
            self.assertEqual(len(anchor["source_bbox_px_540x960"]), 4)
            self.assertEqual(len(anchor["generated_bbox_px_540x960"]), 4)
            self.assertGreater(anchor["source_width_px"], 0)
            self.assertGreater(anchor["source_height_px"], 0)

    def test_group02_replaces_right_roll_with_vertical_settle_and_cut_hold(self):
        for token_id in ("vf_02_already", "vf_02_decorative_glyph"):
            token = self.by[token_id]
            self.assertEqual(token["visual_window"], [245, 270])
            xs = [row["position_top_origin"][0] for row in token["frame_path"]]
            self.assertAlmostEqual(max(xs), min(xs), places=9)
            self.assertEqual(token["motion_summary"]["axis"], "vertical")
            self.assertEqual(token["motion_summary"]["direction_top_origin"], "down")
            self.assertEqual(token["frame_path"][-1]["timeline_frame"], 269)
            self.assertEqual(token["frame_path"][10]["position_top_origin"], token["frame_path"][-1]["position_top_origin"])

    def test_group02_font_metrics_are_the_accepted_pilot_values(self):
        primary = self.by["vf_02_already"]
        script = self.by["vf_02_decorative_glyph"]
        self.assertEqual((primary["font"]["font_family"], primary["font"]["font_style"]), ("Verdana", "Bold"))
        self.assertEqual((script["font"]["font_family"], script["font"]["font_style"]), ("Segoe Script", "Regular"))
        self.assertAlmostEqual(primary["application_base_size_candidate"], 0.158, places=12)
        self.assertAlmostEqual(script["application_base_size_candidate"], 0.162, places=12)

    def test_group04_is_reanchored_to_source_pixels(self):
        self.assertEqual(self.by["vf_04_that"]["source_pixel_anchor"]["source_bbox_center_normalized_top_origin"], [0.323148, 0.270833])
        self.assertEqual(self.by["vf_04_knows"]["source_pixel_anchor"]["source_bbox_center_normalized_top_origin"], [0.472222, 0.326042])
        self.assertEqual(self.by["vf_04_market"]["source_pixel_anchor"]["source_bbox_center_normalized_top_origin"], [0.585185, 0.372917])

    def test_group05_primary_word_is_shifted_to_source_anchor(self):
        know = self.by["vf_05_know"]
        self.assertEqual(know["source_pixel_anchor"]["source_bbox_center_normalized_top_origin"], [0.440741, 0.360417])
        self.assertLess(know["source_pixel_anchor"]["v4_center_shift_from_v3_normalized"][0], -0.05)

    def test_group06_source_layout_remains_near_existing_source_reviewed_geometry(self):
        self.assertAlmostEqual(self.by["vf_06_buildings"]["source_pixel_anchor"]["source_bbox_center_normalized_top_origin"][0], 0.282407, places=6)
        self.assertAlmostEqual(self.by["vf_06_builders"]["source_pixel_anchor"]["source_bbox_center_normalized_top_origin"][0], 0.500926, places=6)
        self.assertAlmostEqual(self.by["vf_06_blocks"]["source_pixel_anchor"]["source_bbox_center_normalized_top_origin"][0], 0.652778, places=6)

    def test_source_locked_colors_and_styles_survive_into_v4(self):
        self.assertEqual(self.by["vf_03_high"]["style_lock"]["fill"], "#D85ACD")
        self.assertEqual(self.by["vf_04_knows"]["style_lock"]["fill"], "#F28A00")
        self.assertEqual(self.by["vf_07_something"]["style_lock"]["fill"], "#15171A")

    def test_v4_does_not_modify_resolve_or_authorize_remaining_rollout(self):
        self.assertFalse(self.authority["authority_policy"]["resolve_modified"])
        self.assertFalse(self.authority["authority_policy"]["full_rollout_authorized"])
        self.assertFalse(self.authority["next_boundary"]["remaining_100_rollout_allowed"])
        self.assertTrue(self.authority["next_boundary"]["protected_source_timeline_must_remain_immutable"])

    def test_v4_deterministically_rebuilds_from_locked_inputs(self):
        rebuilt = builder.build_authority(ROOT)
        self.assertEqual(rebuilt, self.authority)
        semantic = dict(self.authority)
        digest = semantic.pop("semantic_sha256")
        self.assertEqual(digest, builder.canonical_sha256(semantic))


if __name__ == "__main__":
    unittest.main()
