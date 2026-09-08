from __future__ import annotations
import importlib.util,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODULE_PATH=ROOT/"resolve_workspace/modules/step_3E_group02_font_metrics_polish.py"
SPEC=importlib.util.spec_from_file_location("g02_fontmetrics_under_test",MODULE_PATH); assert SPEC and SPEC.loader
module=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=module;SPEC.loader.exec_module(module)
CONTRACT=ROOT/module.CONTRACT_RELATIVE_PATH
MOTION=ROOT/module.SOURCE_MOTION_CONTRACT_RELATIVE_PATH
class Group02FontMetricsPolishTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.contract=json.loads(CONTRACT.read_text(encoding="utf-8-sig"));cls.plans=module.contract_plans(cls.contract);cls.by={r["visual_token_id"]:r for r in cls.plans}
  cls.motion=json.loads(MOTION.read_text(encoding="utf-8-sig"));cls.motion_by={r["visual_token_id"]:r for r in cls.motion["plans"]}
 def test_exact_scope(self):
  self.assertEqual(self.contract["task_id"],module.TASK_ID);self.assertEqual(set(self.by),{"vf_02_already","vf_02_decorative_glyph"});self.assertEqual(len(self.plans),2)
 def test_primary_font_candidate_is_source_supported_and_installed(self):
  r=self.by["vf_02_already"];self.assertEqual((r["font"]["font_family"],r["font"]["font_style"]),("Verdana","Bold"));self.assertTrue(r["font"]["visual_approval_required"]);self.assertIn("sub_018",r["font"]["authority"])
 def test_script_font_candidate_is_connected_script_and_installed(self):
  r=self.by["vf_02_decorative_glyph"];self.assertEqual((r["font"]["font_family"],r["font"]["font_style"]),("Segoe Script","Regular"));self.assertTrue(r["font"]["visual_approval_required"]);self.assertEqual(r["font"]["windows_font_file"],r"C:\Windows\Fonts\segoesc.ttf")
 def test_text_identity_unchanged(self):
  self.assertEqual(self.by["vf_02_already"]["display_text"],"already");self.assertEqual(self.by["vf_02_decorative_glyph"]["display_text"],"Already")
 def test_motion_timing_opacity_are_frozen(self):
  for token,row in self.by.items():
   old=self.motion_by[token]
   self.assertEqual(row["target_range"],old["target_range"]);self.assertEqual(row["visual_window"],old["visual_window"]);self.assertEqual(row["opacity_keys"],old["opacity_keys"]);self.assertEqual(row["animation_phases"],old["animation_phases"]);self.assertEqual([k["timeline_frame"] for k in row["position_keys"]],[k["timeline_frame"] for k in old["position_keys"]])
 def test_vertical_motion_deltas_are_preserved_exactly(self):
  for token,row in self.by.items():
   old=self.motion_by[token];a=[k["value"][1] for k in row["position_keys"]];b=[k["value"][1] for k in old["position_keys"]]
   da=[round(x-a[-1],6) for x in a];db=[round(x-b[-1],6) for x in b];self.assertEqual(da,db)
 def test_sizes_are_constant_and_polished(self):
  self.assertAlmostEqual(self.by["vf_02_already"]["base_size"],0.158,places=9);self.assertAlmostEqual(self.by["vf_02_decorative_glyph"]["base_size"],0.162,places=9)
  for r in self.plans:self.assertTrue(all(abs(k["value"]-r["base_size"])<1e-12 and abs(k["scale"]-1.0)<1e-12 for k in r["size_keys"]))
 def test_settled_centers_match_source_pixel_measurement(self):
  p=self.by["vf_02_already"]["position_keys"][-1]["value"];s=self.by["vf_02_decorative_glyph"]["position_keys"][-1]["value"];self.assertEqual(p,[0.5,0.628646]);self.assertEqual(s,[0.434259,0.690625])
 def test_bbox_measurements_are_visual_not_transcript(self):
  ev=self.contract["source_evidence"];self.assertEqual(ev["settled_measurement_frame"],255);self.assertIn("source_only",ev["measurement_method"]);self.assertFalse(self.contract["policy"]["transcript_timing_authority"]);self.assertEqual(ev["primary_word"]["source_bbox_px_540x960"],[156,330,384,383])
 def test_other_115_items_remain_out_of_scope(self):
  self.assertEqual(self.contract["polish_scope"]["other_editable_caption_items_must_remain_exact"],115);self.assertEqual(module.EXPECTED_UNCHANGED_ITEMS,115);self.assertEqual(module.EXPECTED_TOTAL_TEXTPLUS,117)
 def test_visual_approval_and_full_rollout_state(self):
  self.assertTrue(self.contract["visual_approval_required"]);self.assertFalse(self.contract["full_rollout_authorized"]);self.assertNotEqual(module.SOURCE_TIMELINE_NAME,module.TARGET_TIMELINE_NAME)
 def test_known_risks_are_explicit(self):
  risks=" ".join(self.contract["known_remaining_visual_risks"]);self.assertIn("visual approval",risks);self.assertIn("Color",risks)
if __name__=="__main__":unittest.main()
