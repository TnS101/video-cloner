from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts/analysis/build_step_3E_confirmed74_repair_authority_v1.py"
RUNTIME_PATH = ROOT / "resolve_workspace/modules/step_3E_confirmed74_isolated_repair_rollout_v1.py"
PREFLIGHT = ROOT / ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/polish_preflight.json"
def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = load_module(BUILDER_PATH, "confirmed74_builder_under_test")
runtime = load_module(RUNTIME_PATH, "confirmed74_runtime_under_test")
AUTHORITY = ROOT / builder.OUTPUT


class Confirmed74IsolatedRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not AUTHORITY.is_file():
            raise RuntimeError(f"build confirmed74 authority before tests: {AUTHORITY}")
        cls.authority = json.loads(AUTHORITY.read_text(encoding="utf-8-sig"))
        cls.partition = runtime.authority_partition(cls.authority)
        cls.unassigned = runtime.build_unassigned_plans(cls.authority)
        cls.preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8-sig"))
        deletion_names = {row["target_name"] for row in cls.partition["repair"] + cls.partition["composite"]}
        cls.occupied = [row for row in cls.preflight["source_inventory"] if row.get("name") not in deletion_names]
        old = runtime.load_old()
        cls.plans = old.assign_tracks(cls.unassigned, cls.occupied)

    def test_exact_structural_partition(self):
        self.assertEqual(len(self.partition["repair"]), 74)
        self.assertEqual(len(self.partition["unresolved"]), 23)
        self.assertEqual(len(self.partition["composite"]), 3)
        self.assertEqual(len(self.partition["protected"]), 17)
        self.assertEqual(74 + 23 + 3, 100)

    def test_existing_and_new_confirmed_are_both_present(self):
        sources = [row["authority_source"] for row in self.authority["repair_instances"]]
        self.assertEqual(sources.count("universal_source_confirmed"), 47)
        self.assertEqual(sources.count("semantic_source_confirmed_plus_source_pixel_visibility"), 27)

    def test_unresolved_rows_never_receive_repair_geometry(self):
        repair_names = {row["target_name"] for row in self.authority["repair_instances"]}
        unresolved_names = {row["target_name"] for row in self.authority["preserve_unresolved"]}
        self.assertFalse(repair_names & unresolved_names)
        self.assertFalse(self.authority["policy"]["unresolved_rows_receive_repair_geometry"])

    def test_composite_structural_rows_are_removed_not_recreated(self):
        repair_names = {row["target_name"] for row in self.authority["repair_instances"]}
        composite_names = {row["target_name"] for row in self.authority["remove_composite_structural"]}
        self.assertEqual(len(composite_names), 3)
        self.assertFalse(repair_names & composite_names)
        self.assertFalse(self.authority["policy"]["composite_structural_rows_recreated"])
        self.assertTrue(all((row.get("protected_composite") or {}).get("protected_target_name") for row in self.authority["remove_composite_structural"]))

    def test_physical_target_count_is_114_not_forced_117(self):
        self.assertEqual(self.authority["summary"]["expected_physical_textplus_count"], 114)
        self.assertEqual(74 + 23 + 17, 114)

    def test_new_semantic_paths_are_dense_and_stabilized(self):
        rows = [row for row in self.authority["repair_instances"] if row["authority_source"].startswith("semantic_")]
        self.assertEqual(len(rows), 27)
        self.assertTrue(any((row.get("motion") or {}).get("position_model") == "source_linear_motion" for row in rows))
        self.assertTrue(any((row.get("motion") or {}).get("position_model") == "source_static_hold" for row in rows))
        for row in rows:
            frames = [frame["timeline_frame"] for frame in row["frame_path"]]
            self.assertEqual(frames, list(range(row["visual_window"][0], row["visual_window"][1])))
            self.assertTrue(all(frame["opacity_factor"] == 1.0 for frame in row["frame_path"]))

    def test_detector_score_never_becomes_opacity(self):
        self.assertFalse(self.authority["policy"]["detector_score_used_as_opacity"])
        self.assertTrue(all(all(frame["opacity_factor"] == 1.0 for frame in row["frame_path"]) for row in self.authority["repair_instances"]))

    def test_source_fill_repair_is_generic_and_evidence_gated(self):
        overrides = [row for row in self.authority["repair_instances"] if (row.get("fill_repair") or {}).get("apply") is True]
        self.assertGreater(len(overrides), 0)
        self.assertTrue(all((row["fill_repair"].get("source") in {"universal_source_pixel_fill_sample", "semantic_ocr_bbox_source_glyph_pixels"}) for row in overrides))
        self.assertTrue(self.authority["policy"]["source_fill_override_requires_generic_evidence_gate"])

    def test_track_allocator_respects_unresolved_and_non_caption_occupancy(self):
        old = runtime.load_old()
        by_track = {track: [] for track in range(3, 8)}
        for row in self.occupied:
            track = int(row.get("track_index") or 0)
            if track in by_track:
                by_track[track].append((int(row["start"]), int(row["end"]), str(row["name"])))
        for row in self.plans:
            start, end = row["target_range"]
            track = row["target_track"]
            self.assertGreaterEqual(track, 3)
            self.assertLessEqual(track, 7)
            self.assertTrue(all(not old.intervals_overlap(start, end, a, b) for a, b, _ in by_track[track]))
            by_track[track].append((start, end, row["target_name"]))

    def test_plan_scope_is_exactly_74_unique_items(self):
        self.assertEqual(len(self.plans), 74)
        self.assertEqual(len({row["target_name"] for row in self.plans}), 74)
        self.assertEqual(len({row["instance_id"] for row in self.plans}), 74)
        self.assertGreater(sum(len(row["position_keys"]) for row in self.plans), 0)

    def test_source_and_target_timelines_are_isolated(self):
        self.assertNotEqual(runtime.SOURCE_TIMELINE_NAME, runtime.TARGET_TIMELINE_NAME)
        self.assertIn("v4_17tokens_v1", runtime.SOURCE_TIMELINE_NAME)
        self.assertIn("confirmed74_repair_v1", runtime.TARGET_TIMELINE_NAME)

    def test_fade_remains_deferred(self):
        self.assertTrue(self.authority["policy"]["fade_polish_deferred"])
        self.assertIn("Fade refinement remains explicitly deferred", runtime.__doc__)

    def test_no_transcript_timing_authority(self):
        self.assertFalse(self.authority["policy"]["transcript_timing_authority"])
        self.assertTrue(all(row["transcript_timing_authority"] is False for row in self.plans))

    def test_authority_semantic_hash_validates(self):
        expected = builder.canonical_sha256({key: value for key, value in self.authority.items() if key != "semantic_sha256"})
        self.assertEqual(self.authority["semantic_sha256"], expected)
        validation = builder.validate_document(self.authority)
        self.assertTrue(validation["ok"], validation)


if __name__ == "__main__":
    unittest.main()
