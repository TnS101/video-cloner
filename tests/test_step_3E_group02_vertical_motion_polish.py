from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace/modules/step_3E_group02_vertical_motion_polish.py"
SPEC = importlib.util.spec_from_file_location("g02_polish_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

CONTRACT = ROOT / module.CONTRACT_RELATIVE_PATH
BASELINE_PLAN = (
    ROOT
    / ".agent/reports/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1"
    / "20260810T080927254297Z_befb7b9f1474440fb817520c47ba8cd3"
    / "full_rollout_plan.json"
)


class Group02VerticalMotionPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8-sig"))
        cls.plans = module.contract_plans(cls.contract)
        cls.by_id = {row["visual_token_id"]: row for row in cls.plans}
        cls.baseline = json.loads(BASELINE_PLAN.read_text(encoding="utf-8-sig"))
        cls.baseline_by_id = {
            row["visual_token_id"]: row for row in cls.baseline["visual_first_instances"]
        }

    def test_contract_is_exactly_group02(self):
        self.assertEqual(self.contract["task_id"], module.TASK_ID)
        self.assertEqual(self.contract["group_id"], module.GROUP_ID)
        self.assertTrue(self.contract["ok"])
        self.assertEqual(len(self.plans), 2)

    def test_exact_two_visual_tokens_are_polished(self):
        self.assertEqual(
            set(self.by_id),
            {"vf_02_already", "vf_02_decorative_glyph"},
        )
        self.assertEqual(
            {row["target_name"] for row in self.plans},
            set(module.TARGET_NAMES),
        )

    def test_horizontal_motion_is_removed(self):
        for row in self.plans:
            xs = [key["source_top_origin_value"][0] for key in row["position_keys"]]
            self.assertAlmostEqual(max(xs), min(xs), places=9)
            self.assertFalse(row["animation_phases"]["horizontal_motion_allowed"])
            self.assertFalse(row["animation_phases"]["exit_motion_allowed"])

    def test_motion_is_top_to_bottom(self):
        for row in self.plans:
            ys = [key["source_top_origin_value"][1] for key in row["position_keys"]]
            self.assertTrue(all(b >= a for a, b in zip(ys, ys[1:])))
            self.assertGreater(ys[-1], ys[0])
            self.assertIn("top_to_bottom", row["animation_phases"]["classification"])

    def test_source_measurements_prove_vertical_not_horizontal_motion(self):
        evidence = self.contract["source_evidence"]
        self.assertEqual(evidence["measured_horizontal_motion_px"]["primary_word_max_abs"], 0)
        self.assertLessEqual(evidence["measured_horizontal_motion_px"]["decorative_script_max_abs"], 1)
        self.assertEqual(evidence["primary_word_vertical_offset_px_vs_f258"]["246"], -32)
        self.assertEqual(evidence["decorative_script_vertical_offset_px_vs_f258"]["245"], -26)

    def test_size_pop_is_removed(self):
        for row in self.plans:
            self.assertTrue(all(abs(key["scale"] - 1.0) < 1e-9 for key in row["size_keys"]))
            self.assertTrue(all(abs(key["value"] - row["base_size"]) < 1e-12 for key in row["size_keys"]))

    def test_artificial_right_roll_exit_is_removed(self):
        for row in self.plans:
            last = row["position_keys"][-1]
            settled = next(key for key in row["position_keys"] if key["timeline_frame"] == 255)
            self.assertEqual(last["source_top_origin_value"], settled["source_top_origin_value"])
            self.assertEqual(row["opacity_keys"][-1]["factor"], 1.0)
            self.assertEqual(row["size_keys"][-1]["scale"], 1.0)

    def test_source_visible_hold_is_extended_to_scene_cut(self):
        for row in self.plans:
            self.assertEqual(row["target_range"], [245, 270])
            self.assertEqual(row["visual_window"], [245, 270])
            self.assertEqual(row["position_keys"][-1]["timeline_frame"], 269)
        self.assertEqual(self.contract["source_evidence"]["source_absent_after_cut_frame"], 270)

    def test_font_and_style_are_not_changed_in_motion_patch(self):
        for token_id, row in self.by_id.items():
            old = self.baseline_by_id[token_id]
            self.assertEqual(row["font"], old["font"])
            self.assertEqual(row["style_lock"], old["style_lock"])
            self.assertEqual(row["display_text"], old["display_text"])

    def test_other_fifteen_visual_first_tokens_are_out_of_scope(self):
        baseline_ids = {row["visual_token_id"] for row in self.baseline["visual_first_instances"]}
        untouched = baseline_ids - set(self.by_id)
        self.assertEqual(len(untouched), 15)
        self.assertEqual(self.contract["polish_scope"]["other_visual_first_tokens_must_remain_exact"], 15)

    def test_full_reel_count_invariants_are_preserved(self):
        self.assertEqual(module.EXPECTED_TOTAL_TEXTPLUS, 117)
        self.assertEqual(module.EXPECTED_V6_TEXTPLUS, 100)
        self.assertEqual(module.EXPECTED_VISUAL_FIRST, 17)
        self.assertEqual(module.EXPECTED_POLISHED, 2)
        self.assertEqual(module.EXPECTED_UNCHANGED_ITEMS, 115)

    def test_polish_timeline_is_separate_and_visual_approval_stays_required(self):
        self.assertNotEqual(module.SOURCE_TIMELINE_NAME, module.TARGET_TIMELINE_NAME)
        self.assertTrue(self.contract["visual_approval_required"])
        self.assertFalse(self.contract["full_rollout_authorized"])
        self.assertTrue(self.contract["known_remaining_visual_risks"])


if __name__ == "__main__":
    unittest.main()
