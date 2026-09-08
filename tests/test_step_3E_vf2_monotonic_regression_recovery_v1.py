from __future__ import annotations
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BUILDER=ROOT/"scripts/analysis/build_step_3E_vf2_monotonic_regression_recovery_authority_v1.py"
RUNTIME=ROOT/"resolve_workspace/modules/step_3E_vf2_monotonic_regression_recovery_v1.py"
PREPARER=ROOT/"scripts/davinci/prepare_step_3E_vf2_monotonic_regression_recovery_v1.py"
AUTHORITY=ROOT/"artifacts/DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_AUTHORITY_V1/vf2_monotonic_regression_recovery_authority_v1.json"

def load_module(path:Path,name:str):
    spec=importlib.util.spec_from_file_location(name,path); assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod
builder=load_module(BUILDER,"vf2_monotonic_builder_test")
runtime=load_module(RUNTIME,"vf2_monotonic_runtime_test")
preparer=load_module(PREPARER,"vf2_monotonic_preparer_test")

class FakeBase:
    @staticmethod
    def normalize_point(value):
        try:
            if isinstance(value,dict):
                if "x" in value and "y" in value: return [float(value["x"]),float(value["y"])]
                if 1 in value and 2 in value: return [float(value[1]),float(value[2])]
            if isinstance(value,(list,tuple)) and len(value)>=2:
                return [float(value[0]),float(value[1])]
        except Exception:
            return None
        return None

    @staticmethod
    def point_matches(actual,expected,tolerance=0.003):
        raise AssertionError("legacy point_matches must not be used by monotonic runtime")

class VF2MonotonicRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        builder.build(ROOT,AUTHORITY)
        cls.a=json.loads(AUTHORITY.read_text(encoding="utf-8-sig"))
    def test_reference_canvas_is_inferred_from_evidence(self):
        c=self.a["reference_canvas"]
        self.assertEqual(c["width"],540.0); self.assertEqual(c["height"],960.0)
        self.assertGreaterEqual(c["evidence_rows"],5)
        self.assertLess(c["max_relative_width_deviation"],0.035)
        self.assertLess(c["max_relative_height_deviation"],0.035)
    def test_catastrophic_half_resolution_geometry_is_corrected(self):
        rows=self.a["center_corrections"]; self.assertEqual(len(rows),14)
        for row in rows:
            old=row["legacy_faulty_center_value"]; new=row["center_value"]
            self.assertLess(abs(new[0]-(old[0]*2.0)),0.01)
            self.assertLess(abs(new[1]-((old[1]*2.0)-1.0)),0.01)
            self.assertTrue(all(0.0<=v<=1.0 for v in new))
    def test_monotonic_scope_is_center_only_plus_quarantine(self):
        p=self.a["policy"]; s=self.a["summary"]
        self.assertTrue(p["monotonic_non_regression"])
        self.assertFalse(p["failed_v2_target_may_be_used_as_source"])
        for key in ("size_mutation_authorized","fill_mutation_authorized","case_mutation_authorized","font_mutation_authorized","opacity_mutation_authorized","clip_range_mutation_authorized","track_mutation_authorized","layout_mutation_authorized","occlusion_relocation_authorized"):
            self.assertFalse(p[key])
        self.assertEqual(s["recreated_textplus"],0)
        self.assertEqual(s["size_updates"],0); self.assertEqual(s["fill_updates"],0); self.assertEqual(s["opacity_updates"],0)
    def test_exact_partition(self):
        s=self.a["summary"]
        self.assertEqual(s["source_physical_textplus"],114); self.assertEqual(s["target_physical_textplus"],113)
        self.assertEqual(s["center_corrections"],14); self.assertEqual(s["protected_exit_updates"],3); self.assertEqual(s["quarantine_removed"],1)
        self.assertEqual(s["unchanged_structural"],82); self.assertEqual(s["unchanged_protected"],14)
    def test_center_quarantine_exit_scopes_are_disjoint(self):
        centers={x["target_name"] for x in self.a["center_corrections"]}
        quarantine={x["target_name"] for x in self.a["quarantine_remove"]}
        exits={x["target_name"] for x in self.a["protected_exit_updates"]}
        self.assertFalse(centers & quarantine); self.assertFalse(centers & exits); self.assertFalse(quarantine & exits)
    def test_snapshot_noncenter_excludes_only_center(self):
        snap={"target_name":"x","summary":{"start":1},"static_style":{"Font":"A"},"center":[[.1,.2]],"size":[1],"opacity1":[1],"opacity2":[None],"opacity3":[0]}
        nc=runtime.snapshot_noncenter(snap)
        self.assertNotIn("center",nc); self.assertEqual(nc["size"],[1]); self.assertEqual(nc["static_style"],{"Font":"A"})
    def test_point_matches_normalizes_actual_and_expected_shapes(self):
        base=FakeBase()
        self.assertTrue(runtime.point_matches(base,[0.5,0.4],{"x":0.5,"y":0.4},0.003))
        self.assertTrue(runtime.point_matches(base,{"x":0.5,"y":0.4},[0.5,0.4],0.003))
        self.assertTrue(runtime.point_matches(base,{"x":0.5,"y":0.4},{"x":0.5,"y":0.4},0.003))
        self.assertFalse(runtime.point_matches(base,[0.5,0.4],{"x":0.52,"y":0.4},0.003))
        self.assertFalse(runtime.point_matches(base,[0.5,0.4],{"bad":1},0.003))
        self.assertFalse(runtime.point_matches(base,None,[0.5,0.4],0.003))

    def test_single_failed_run_clean_cleanup_allows_one_patched_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); run_id="failed_run"
            artifacts=Path(".agent/reports")/preparer.TASK_ID/run_id
            cmd={"task_id":preparer.TASK_ID,"run_id":run_id,"artifacts_dir":str(artifacts)}
            cp=root/".agent/commands/failed"/f"{preparer.TASK_ID}_{run_id}.json"
            cp.parent.mkdir(parents=True,exist_ok=True); cp.write_text(json.dumps(cmd),encoding="utf-8")
            cleanup=root/artifacts/"failure_cleanup.json"; cleanup.parent.mkdir(parents=True,exist_ok=True)
            cleanup.write_text(json.dumps({"ok":True,"accepted_state_unchanged":True,"errors":[]}),encoding="utf-8")
            self.assertEqual(preparer.validate_retry_state(root),{"repair_retry":True,"prior_failed_run_id":run_id})

    def test_retry_gate_blocks_bad_cleanup_and_second_failed_run(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); d=root/".agent/commands/failed"; d.mkdir(parents=True)
            run_id="failed_run"; artifacts=Path(".agent/reports")/preparer.TASK_ID/run_id
            (d/f"{preparer.TASK_ID}_{run_id}.json").write_text(json.dumps({"task_id":preparer.TASK_ID,"run_id":run_id,"artifacts_dir":str(artifacts)}),encoding="utf-8")
            cleanup=root/artifacts/"failure_cleanup.json"; cleanup.parent.mkdir(parents=True,exist_ok=True)
            cleanup.write_text(json.dumps({"ok":False,"accepted_state_unchanged":True,"errors":["cleanup"]}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"prior_failure_cleanup"):
                preparer.validate_retry_state(root)
            run2="failed_run_2"; art2=Path(".agent/reports")/preparer.TASK_ID/run2
            (d/f"{preparer.TASK_ID}_{run2}.json").write_text(json.dumps({"task_id":preparer.TASK_ID,"run_id":run2,"artifacts_dir":str(art2)}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"repair_retry_limit:2"):
                preparer.validate_retry_state(root)

    def test_preparer_accepts_authority_and_forbids_recreation(self):
        preparer.validate_authority(self.a)
        self.assertEqual(self.a["summary"]["recreated_textplus"],0)
    def test_builder_semantic_hash_is_self_consistent(self):
        semantic=self.a["semantic_sha256"]
        self.assertEqual(semantic,builder.canonical_sha256({k:v for k,v in self.a.items() if k!="semantic_sha256"}))
    def test_all_center_rows_authorize_only_center(self):
        for row in self.a["center_corrections"]:
            self.assertEqual(row["authorized_properties"],["Center"])
            self.assertTrue(row["source_support_frames"])
    def test_failed_v2_target_is_not_an_input_authority(self):
        text=RUNTIME.read_text(encoding="utf-8-sig")
        self.assertIn("confirmed74_repair_metrics_v1",text)
        self.assertNotIn('SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_visual_fidelity_v2_v1"',text)

if __name__=="__main__": unittest.main()
