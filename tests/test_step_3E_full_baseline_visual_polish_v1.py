from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace/modules/step_3E_full_baseline_visual_polish_v1.py"
SPEC = importlib.util.spec_from_file_location("step3e3_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

AUTHORITY = ROOT / module.V4_AUTHORITY_RELATIVE_PATH
BASELINE = ROOT / module.BASELINE_PLAN_RELATIVE_PATH
GROUP02 = ROOT / module.GROUP02_CONTRACT_RELATIVE_PATH


class Step3EFullBaselineVisualPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authority = json.loads(AUTHORITY.read_text(encoding="utf-8-sig"))
        cls.baseline = json.loads(BASELINE.read_text(encoding="utf-8-sig"))
        cls.group02 = json.loads(GROUP02.read_text(encoding="utf-8-sig"))
        cls.plans = module.build_v4_application_plans(cls.authority, cls.baseline)
        cls.by = {row["visual_token_id"]: row for row in cls.plans}
        cls.source_plans = module.build_source_readback_plans(cls.baseline, cls.group02)
        cls.source_by = {row["visual_token_id"]: row for row in cls.source_plans}

    def test_task_is_isolated_duplicate_not_source_mutation(self):
        self.assertEqual(module.TASK_ID, "DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1")
        self.assertNotEqual(module.SOURCE_TIMELINE_NAME, module.TARGET_TIMELINE_NAME)
        self.assertIn("g02_fontmetrics_v1", module.SOURCE_TIMELINE_NAME)
        self.assertIn("v4_17tokens_v1", module.TARGET_TIMELINE_NAME)

    def test_v4_scope_is_exactly_seven_groups_and_seventeen_tokens(self):
        self.assertEqual(len(self.authority["groups"]), 7)
        self.assertEqual(len(self.plans), 17)
        self.assertEqual(len(self.by), 17)

    def test_every_v4_frame_is_explicit_and_contiguous(self):
        total = 0
        for row in self.plans:
            frames = [key["timeline_frame"] for key in row["position_keys"]]
            self.assertEqual(frames, list(range(row["target_range"][0], row["target_range"][1])))
            self.assertEqual(len(row["size_keys"]), len(frames))
            self.assertEqual(len(row["opacity_keys"]), len(frames))
            total += len(frames)
        self.assertEqual(total, 397)

    def test_target_names_and_tracks_are_inherited_from_full_baseline(self):
        baseline = {row["visual_token_id"]: row for row in self.baseline["visual_first_instances"]}
        for token_id, row in self.by.items():
            self.assertEqual(row["target_name"], baseline[token_id]["target_name"])
            self.assertEqual(row["target_track"], baseline[token_id]["target_track"])
        self.assertEqual(sorted(row["target_track"] for row in self.plans), list(range(8, 25)))

    def test_visual_windows_control_target_timing_not_transcript(self):
        for row in self.plans:
            self.assertEqual(row["target_range"], row["visual_window"])
            self.assertFalse(row["transcript_timing_promoted_to_authority"])
        self.assertEqual(self.by["vf_02_already"]["target_range"], [245, 270])
        self.assertEqual(self.by["vf_02_decorative_glyph"]["target_range"], [245, 270])

    def test_group02_accepted_font_metrics_are_preserved_in_v4(self):
        already = self.by["vf_02_already"]
        glyph = self.by["vf_02_decorative_glyph"]
        self.assertEqual((already["font"]["font_family"], already["font"]["font_style"]), ("Verdana", "Bold"))
        self.assertEqual((glyph["font"]["font_family"], glyph["font"]["font_style"]), ("Segoe Script", "Regular"))
        self.assertTrue(all(abs(key["value"] - 0.158) < 1e-12 for key in already["size_keys"]))
        self.assertTrue(all(abs(key["value"] - 0.162) < 1e-12 for key in glyph["size_keys"]))

    def test_group02_vertical_top_to_bottom_motion_is_explicit(self):
        for token_id in ("vf_02_already", "vf_02_decorative_glyph"):
            row = self.by[token_id]
            xs = [key["source_top_origin_value"][0] for key in row["position_keys"]]
            ys = [key["source_top_origin_value"][1] for key in row["position_keys"]]
            self.assertAlmostEqual(max(xs) - min(xs), 0.0, places=9)
            self.assertTrue(all(later >= earlier for earlier, later in zip(ys, ys[1:])))
            self.assertEqual(row["position_keys"][-1]["timeline_frame"], 269)

    def test_fusion_and_top_origin_coordinates_are_consistent(self):
        for row in self.plans:
            for key in row["position_keys"]:
                x, fusion_y = key["value"]
                top_x, top_y = key["source_top_origin_value"]
                self.assertAlmostEqual(x, top_x, places=9)
                self.assertAlmostEqual(fusion_y + top_y, 1.0, places=6)

    def test_size_and_opacity_rows_match_v4_frame_authority(self):
        authority_tokens = {
            token["visual_token_id"]: token
            for group in self.authority["groups"]
            for token in group["tokens"]
        }
        for token_id, row in self.by.items():
            original = authority_tokens[token_id]["frame_path"]
            for index, frame in enumerate(original):
                self.assertAlmostEqual(row["size_keys"][index]["value"], frame["application_size_candidate"], places=12)
                self.assertAlmostEqual(row["size_keys"][index]["scale"], frame["size_scale"], places=12)
                self.assertAlmostEqual(row["opacity_keys"][index]["factor"], frame["opacity_factor"], places=12)

    def test_style_scope_keeps_stroke_disabled_for_all_tokens(self):
        for row in self.plans:
            self.assertIs(row["style_lock"]["stroke"]["enabled"], False)
            self.assertIn("fill", row["style_lock"])
            self.assertIn("shadow", row["style_lock"])

    def test_source_readback_uses_latest_group02_state_only_for_two_tokens(self):
        baseline = {row["visual_token_id"]: row for row in self.baseline["visual_first_instances"]}
        self.assertEqual(set(self.source_by), set(baseline))
        for token_id, row in self.source_by.items():
            if token_id in module.GROUP02_TOKEN_IDS:
                self.assertEqual(row["target_range"], [245, 270])
            else:
                self.assertEqual(row["target_range"], baseline[token_id]["target_range"])

    def test_remaining_caption_rollout_stays_out_of_scope(self):
        policy = self.authority["authority_policy"]
        boundary = self.authority["next_boundary"]
        self.assertFalse(policy["full_rollout_authorized"])
        self.assertFalse(boundary["remaining_100_rollout_allowed"])
        self.assertEqual(module.EXPECTED_V6_TEXTPLUS, 100)
        self.assertEqual(module.EXPECTED_TOTAL_TEXTPLUS, 117)


if __name__ == "__main__":
    unittest.main()
