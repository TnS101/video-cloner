from __future__ import annotations
import importlib.util, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODULE_PATH=ROOT/"resolve_workspace/modules/step_3E_remaining100_full_rollout_v1.py"
SPEC=importlib.util.spec_from_file_location("remaining100_rollout_under_test",MODULE_PATH); assert SPEC and SPEC.loader
module=importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name]=module; SPEC.loader.exec_module(module)
AUTH=ROOT/module.AUTHORITY_RELATIVE_PATH
PERSIST=ROOT/module.STEP3E3_PERSISTENT_RELATIVE_PATH
PREFLIGHT=ROOT/".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/polish_preflight.json"
class Remaining100FullRolloutTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.authority=json.loads(AUTH.read_text(encoding="utf-8-sig")); cls.unassigned=module.build_unassigned_plans(cls.authority); cls.persistent=json.loads(PERSIST.read_text(encoding="utf-8-sig")); cls.protected=module.protected_expectations(cls.persistent); cls.preflight=json.loads(PREFLIGHT.read_text(encoding="utf-8-sig")); names={r["target_name"] for r in cls.unassigned}; cls.occupied=[r for r in cls.preflight["source_inventory"] if r.get("name") not in names]; cls.plans=module.assign_tracks(cls.unassigned,cls.occupied)
 def test_scope_is_exactly_remaining100(self): self.assertEqual(len(self.plans),100); self.assertEqual(len({r["target_name"] for r in self.plans}),100); self.assertEqual(len({r["instance_id"] for r in self.plans}),100)
 def test_source_and_target_timelines_are_isolated(self): self.assertNotEqual(module.SOURCE_TIMELINE_NAME,module.TARGET_TIMELINE_NAME); self.assertIn("v4_17tokens_v1",module.SOURCE_TIMELINE_NAME); self.assertIn("all117_v1",module.TARGET_TIMELINE_NAME)
 def test_authority_partition_is_locked(self):
  s=self.authority["summary"]; self.assertEqual(s["accepted_visual_primary_instance_count"],39); self.assertEqual(s["source_pixel_redetected_instance_count"],61); self.assertEqual(s["low_confidence_pixel_readback_count"],0)
 def test_transcript_timing_never_becomes_authority(self): self.assertTrue(all(r["transcript_timing_authority"] is False for r in self.plans)); self.assertTrue(all(r["visual_timing_authority"] in {"source_pixel_redetection","accepted_source_visual_track_plus_pixel_readback"} for r in self.plans))
 def test_dense_frame_paths_total_803(self):
  total=0
  for r in self.plans:
   frames=[k["timeline_frame"] for k in r["position_keys"]]; self.assertEqual(frames,list(range(r["target_range"][0],r["target_range"][1]))); self.assertEqual(len(frames),len(r["size_keys"])); self.assertEqual(len(frames),len(r["opacity_keys"])); total+=len(frames)
  self.assertEqual(total,803)
 def test_track_allocator_stays_bounded(self): self.assertTrue(all(3<=r["target_track"]<=7 for r in self.plans))
 def test_track_allocator_has_no_caption_overlap(self):
  by={t:[] for t in range(3,8)}
  for r in self.occupied:
   t=int(r.get("track_index") or 0)
   if t in by: by[t].append((int(r["start"]),int(r["end"]),str(r["name"])))
  for r in self.plans:
   s,e=r["target_range"]; t=r["target_track"]; self.assertTrue(all(not module.intervals_overlap(s,e,a,b) for a,b,_ in by[t])); by[t].append((s,e,r["target_name"]))
 def test_occlusion_matte_is_respected(self):
  matte=[r for r in self.occupied if r.get("name")=="VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"]; self.assertEqual(len(matte),1); m=matte[0]; self.assertEqual((m["track_index"],m["start"],m["end"]),(4,429,434)); self.assertFalse(any(r["target_track"]==4 and module.intervals_overlap(r["target_range"][0],r["target_range"][1],429,434) for r in self.plans))
 def test_protected_v4_readback_is_17_and_397_rows(self): self.assertEqual(len(self.protected),17); self.assertEqual(sum(len(r.get("position_keys") or []) for r in self.protected),397); self.assertTrue(all(r.get("ok") for r in self.protected))
 def test_protected_and_remaining_names_do_not_overlap(self): self.assertFalse({r["target_name"] for r in self.plans}&{r["target_name"] for r in self.protected})
 def test_style_policy_is_source_comp_preservation(self): self.assertIn("static style",module.__doc__.lower()); self.assertIn("fusion comp",module.__doc__.lower()); self.assertIn("Thickness2",module.STATIC_STYLE_INPUTS)
 def test_fade_polish_is_deferred_not_silently_claimed_fixed(self): self.assertIn("Fade-in/fade-out refinement is explicitly deferred",module.__doc__)
 def test_final_contract_is_100_plus_17(self): self.assertEqual(module.EXPECTED_REMAINING,100); self.assertEqual(module.EXPECTED_PROTECTED,17); self.assertEqual(module.EXPECTED_TOTAL,117); self.assertEqual(module.EXPECTED_FRAME_ROWS,803)
if __name__=="__main__": unittest.main()
