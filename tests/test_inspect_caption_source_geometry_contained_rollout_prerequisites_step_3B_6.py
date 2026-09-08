from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.davinci import inspect_caption_source_geometry_contained_rollout_prerequisites_step_3B_6 as investigator


class PrerequisiteInvestigatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="vc_3b6d_prereq_")
        self.root = Path(self.temporary.name)
        self.paths = {name: self.root / f"{name}.json" for name in (
            "tracks", "redetection", "animation", "probe_plan", "probe_report", "probe_validation"
        )}
        self.preparer = self.root / "preparer.py"
        self.preparer.write_text(
            'ALLOWED_OPERATION_PROPERTIES = ("Center", "Size")\n'
            'KNOWN_EXCLUDED_SOURCE_PROPERTIES = ("Blend",)\n',
            encoding="utf-8",
        )
        tracks = []
        items = []
        for cue_id, (text, start, end) in investigator.EXPECTED.items():
            first, last = start, end - 1
            observations = [
                {"timeline_frame": frame, "source_frame": frame + 10, "position": [0.5, 0.5], "scale_proxy": 1.0}
                for frame in range(first, last + 1)
            ]
            tracks.append({
                "cue_id": cue_id, "text": text, "cue_start_frame": start, "cue_end_frame": end,
                "accepted_source_instance": True, "source_exactness": "source_redetected_dense_word_instance",
                "fallback_reasons": [], "geometry": {"first_visible_frame": first, "last_visible_frame": last},
                "frame_observations": observations,
            })
            items.append({
                "cue_id": cue_id, "text": text, "start_frame": start, "end_frame": end,
                "name": f"VC_TEXTPLUS_{int(cue_id[-3:]):04d}_{cue_id}",
            })
        self.write(self.paths["tracks"], {
            "ok": True, "schema": investigator.TRACK_SCHEMA, "summary": {"v3_item_count": 116},
            "scenes": [{"tracks": tracks}],
        })
        self.write(self.paths["redetection"], {"ok": True, "failures": []})
        self.write(self.paths["animation"], {"ok": True, "items": items + [{"cue_id": f"other_{index}"} for index in range(112)]})
        probe_plan = {"ok": True, "schema": investigator.PROBE_PLAN_SCHEMA}
        probe_plan["plan_hash"] = investigator.canonical_hash(probe_plan, ignored=("created_at_unix",))
        self.write(self.paths["probe_plan"], probe_plan)
        self.write(self.paths["probe_report"], {
            "ok": True, "run_mode": "idempotent_second_run", "plan_hash": probe_plan["plan_hash"],
            "task_id": investigator.ACCEPTED_PROBE_TASK_ID, "run_id": investigator.ACCEPTED_PROBE_RUN_ID,
            "timeline_modified": False, "setter_call_count": 0, "effective_mutation_count": 0, "blend_operation_count": 0,
            "probe_cue_id": "sub_114", "summary": {"target_key_verified_count": 12, "modified_count": 0, "already_correct_count": 1},
        })
        self.write(self.paths["probe_validation"], {
            "ok": True, "mode": "idempotent_second_run", "failures": [], "checks": {"required": True},
            "task_id": investigator.ACCEPTED_PROBE_TASK_ID, "run_id": investigator.ACCEPTED_PROBE_RUN_ID,
            "plan": str(self.paths["probe_plan"]), "report": str(self.paths["probe_report"]),
        })

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def assess(self) -> dict:
        return investigator.assess(
            self.paths["tracks"], self.paths["redetection"], self.paths["animation"],
            self.paths["probe_plan"], self.paths["probe_report"], self.paths["probe_validation"],
            self.preparer,
        )

    def test_accepts_complete_four_cue_prerequisites(self) -> None:
        result = self.assess()
        self.assertTrue(result["eligible_for_build"])
        self.assertTrue(result["preparation_permitted"])
        self.assertFalse(result["runtime_command_permitted"])
        self.assertEqual(set(result["targets"]), set(investigator.EXPECTED))

    def test_rejects_missing_probe_idempotency_pair(self) -> None:
        self.paths["probe_report"].unlink()
        self.paths["probe_validation"].unlink()
        result = self.assess()
        self.assertFalse(result["runtime_command_permitted"])
        self.assertIn("missing:probe_report", result["blockers"])
        self.assertIn("missing:probe_validation", result["blockers"])

    def test_rejects_group_inferred_source_record(self) -> None:
        tracks = json.loads(self.paths["tracks"].read_text(encoding="utf-8"))
        tracks["scenes"][0]["tracks"][0]["source_exactness"] = "group_inferred_not_source_exact"
        self.write(self.paths["tracks"], tracks)
        result = self.assess()
        self.assertFalse(result["eligible_for_build"])
        self.assertIn("target:sub_007", result["blockers"])

    def test_rejects_duplicate_cue_identity(self) -> None:
        tracks = json.loads(self.paths["tracks"].read_text(encoding="utf-8"))
        tracks["scenes"][0]["tracks"].append(dict(tracks["scenes"][0]["tracks"][0]))
        self.write(self.paths["tracks"], tracks)
        result = self.assess()
        self.assertFalse(result["eligible_for_build"])
        self.assertFalse(result["targets"]["sub_007"]["checks"]["one_source_record"])

    def test_rejects_ambiguous_timeline_item_identity(self) -> None:
        animation = json.loads(self.paths["animation"].read_text(encoding="utf-8"))
        animation["items"].append(dict(animation["items"][0]))
        self.write(self.paths["animation"], animation)
        result = self.assess()
        self.assertFalse(result["eligible_for_build"])
        self.assertFalse(result["targets"]["sub_007"]["checks"]["one_timeline_item"])

    def test_rejects_blend_in_executable_property_allowlist(self) -> None:
        self.preparer.write_text(
            'ALLOWED_OPERATION_PROPERTIES = ("Blend", "Center", "Size")\n'
            'KNOWN_EXCLUDED_SOURCE_PROPERTIES = ("Blend",)\n',
            encoding="utf-8",
        )
        result = self.assess()
        self.assertFalse(result["eligible_for_build"])
        self.assertIn("global:center_size_only_preparer", result["blockers"])


if __name__ == "__main__":
    unittest.main()
