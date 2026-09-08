from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py"
SPEC = importlib.util.spec_from_file_location("full_rollout_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

AUTHORITY = ROOT / module.AUTHORITY_MANIFEST_RELATIVE_PATH
V6_PLAN = ROOT / module.V6_ROLLOUT_PLAN_RELATIVE_PATH


class VisualFirstFullRolloutBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authority = json.loads(AUTHORITY.read_text(encoding="utf-8-sig"))
        cls.v6_plan = json.loads(V6_PLAN.read_text(encoding="utf-8-sig"))
        cls.raw_plans = module.pilot.flatten_authority(cls.authority, ROOT)
        cls.plans = module.retarget_plans(cls.raw_plans)
        cls.replacements = module.replacement_plan(cls.v6_plan, cls.plans)

    def test_authority_is_v3_and_still_not_visually_approved_for_full_rollout(self):
        self.assertEqual(module.AUTHORITY_TASK_ID, "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3")
        self.assertFalse(self.authority["next_boundary"]["full_rollout_allowed"])
        self.assertEqual(self.authority["summary"]["transcript_timing_promoted_count"], 0)

    def test_retargeting_changes_only_target_names(self):
        self.assertEqual(len(self.raw_plans), 17)
        self.assertEqual(len(self.plans), 17)
        for before, after in zip(self.raw_plans, self.plans):
            expected = dict(before)
            expected["target_name"] = after["target_name"]
            self.assertEqual(expected, after)
            self.assertTrue(after["target_name"].startswith(module.FULL_NAME_PREFIX))

    def test_exact_15_transcript_first_instances_are_superseded(self):
        self.assertEqual(len(self.replacements["replacement_rows"]), 15)
        self.assertEqual(len(self.replacements["replacement_cue_ids"]), 15)
        self.assertEqual(
            self.replacements["replacement_cue_ids"],
            [
                "sub_006", "sub_018", "sub_032", "sub_033", "sub_034",
                "sub_057", "sub_058", "sub_060", "sub_063", "sub_065",
                "sub_076", "sub_078", "sub_080", "sub_082", "sub_085",
            ],
        )

    def test_visual_only_decorations_do_not_delete_extra_transcript_cues(self):
        visual_only = [row for row in self.plans if row["visual_kind"] == "visual_only_text_decoration"]
        self.assertEqual(len(visual_only), 2)
        self.assertEqual([row["source_cue_id"] for row in visual_only], [None, None])
        self.assertEqual(len(self.replacements["replacement_cue_ids"]), 15)

    def test_remaining_v6_textplus_count_is_100(self):
        self.assertEqual(len(self.v6_plan["instances"]), 115)
        self.assertEqual(len(self.replacements["preserved_rows"]), 100)
        self.assertEqual(len(self.replacements["preserved_target_names"]), 100)

    def test_final_editable_textplus_count_is_117(self):
        self.assertEqual(module.EXPECTED_SOURCE_TEXTPLUS_COUNT, 115)
        self.assertEqual(module.EXPECTED_REPLACED_TEXTPLUS_COUNT, 15)
        self.assertEqual(module.EXPECTED_PRESERVED_TEXTPLUS_COUNT, 100)
        self.assertEqual(module.EXPECTED_VISUAL_FIRST_COUNT, 17)
        self.assertEqual(module.EXPECTED_FINAL_TEXTPLUS_COUNT, 117)
        self.assertEqual(115 - 15 + 17, 117)

    def test_known_non_authority_words_remain_in_preserved_full_reel(self):
        preserved_cues = {
            cue
            for row in self.replacements["preserved_rows"]
            for cue in row["source_cue_ids"]
        }
        for cue in ("sub_019", "sub_020", "sub_059", "sub_061", "sub_067", "sub_083", "sub_089"):
            self.assertIn(cue, preserved_cues)

    def test_full_rollout_uses_isolated_visual_first_tracks(self):
        tracks = [row["target_track"] for row in self.plans]
        self.assertEqual(tracks, list(range(8, 25)))
        self.assertEqual(module.MAX_TRACK, 24)

    def test_current_animation_and_font_authority_is_carried_forward_unchanged(self):
        for before, after in zip(self.raw_plans, self.plans):
            self.assertEqual(before["position_keys"], after["position_keys"])
            self.assertEqual(before["size_keys"], after["size_keys"])
            self.assertEqual(before["opacity_keys"], after["opacity_keys"])
            self.assertEqual(before["font"], after["font"])
            self.assertEqual(before["style_lock"], after["style_lock"])

    def test_already_and_i_script_components_are_present(self):
        by_id = {row["visual_token_id"]: row for row in self.plans}
        self.assertEqual(by_id["vf_02_decorative_glyph"]["display_text"], "Already")
        self.assertEqual(by_id["vf_05_decorative_glyph"]["display_text"], "I")
        self.assertEqual(by_id["vf_02_decorative_glyph"]["font"]["font_family"], "Gabriola")
        self.assertEqual(by_id["vf_05_decorative_glyph"]["font"]["font_family"], "Gabriola")

    def test_target_timeline_is_separate_from_v6_and_pilot(self):
        self.assertNotEqual(module.TARGET_TIMELINE_NAME, module.SOURCE_TIMELINE_NAME)
        self.assertNotEqual(module.TARGET_TIMELINE_NAME, module.pilot.TARGET_TIMELINE_NAME)
        self.assertIn("full_rollout_baseline", module.TARGET_TIMELINE_NAME)

    def test_replacement_target_names_match_v6_plan_not_visual_overlap(self):
        replacement_names = set(self.replacements["replacement_target_names"])
        by_cue = {
            cue: row["target_name"]
            for row in self.v6_plan["instances"]
            for cue in row["source_cue_ids"]
        }
        for cue in self.replacements["replacement_cue_ids"]:
            self.assertIn(by_cue[cue], replacement_names)
        self.assertNotIn(by_cue["sub_019"], replacement_names)
        self.assertNotIn(by_cue["sub_067"], replacement_names)


if __name__ == "__main__":
    unittest.main()
