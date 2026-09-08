from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.davinci import investigate_caption_source_geometry_step_3B_6C_evidence_lineage as investigator
from scripts.davinci import validate_caption_source_geometry_probe_evidence_step_3B_6 as gate


class EvidenceLineageInvestigatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="vc_3b6c_lineage_")
        self.root = Path(self.temporary.name)
        self.analysis = self.root / "data" / investigator.VIDEO_ID / "analysis"
        self.davinci = self.root / "data" / investigator.VIDEO_ID / "davinci"
        self.reports = self.root / ".agent" / "reports"
        self.output = self.root / "output"
        self.analysis.mkdir(parents=True)
        self.davinci.mkdir(parents=True)
        (self.root / ".agent" / "state").mkdir(parents=True)
        self.plan_path = self.analysis / f"{investigator.VIDEO_ID}_caption_source_geometry_probe_plan_step_3B_6C.json"
        plan = {"ok": True, "step": investigator.STEP, "schema": gate.PLAN_SCHEMA, "created_at_unix": 1, "probe": {"cue_id": investigator.PROBE_CUE, "text": investigator.PROBE_TEXT, "start_frame": 888, "end_frame": 894}}
        plan["plan_hash"] = gate.canonical_hash(plan, ignored=("created_at_unix",))
        self.write(self.plan_path, plan)
        self.plan_hash = plan["plan_hash"]
        self.first_report = self.davinci / f"{investigator.VIDEO_ID}_resolve_source_geometry_step_3B_6C_first_application_report.json"
        self.first_validation = self.davinci / f"{investigator.VIDEO_ID}_resolve_source_geometry_step_3B_6C_first_application_validation.json"
        self.write(self.first_report, self.report("first_application", 0, 1))
        self.write(self.first_validation, self.validation("first_application_pass", False, self.first_report))
        self.write(self.root / ".agent" / "state" / "latest_accepted.json", {"accepted_task": "BRIDGE_SMOKE_TEST_V1"})
        log = self.davinci / f"{investigator.VIDEO_ID}_resolve_source_geometry_step_3B_6C_workspace.log"
        log.write_text(json.dumps({"event": "workspace_finished", "run_id": "first", "run_mode": "first_application"}) + "\n", encoding="utf-8")
        self.gate_output = self.root / "gate.json"
        self.write(self.gate_output, {"accepted": False})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def summary(self, modified: int, already: int) -> dict:
        return {"modified_count": modified, "already_correct_count": already, "non_probe_caption_count": 115, "non_probe_caption_verified_count": 115, "protected_animation_caption_count": 8, "protected_animation_verified_count": 8, "protected_animation_target_count": 16, "protected_animation_target_verified_count": 16, "opacity_proxy_applied_count": 0, "z_order_write_count": 0, "timeline_boundary_write_count": 0, "timeline_integrity_failure_count": 0, "protected_integrity_failure_count": 0, "failed_count": 0}

    def report(self, mode: str, modified: int, already: int) -> dict:
        return {"ok": True, "step": investigator.STEP, "run_id": mode, "run_mode": mode, "plan_hash": self.plan_hash if hasattr(self, "plan_hash") else None, "probe_cue_id": investigator.PROBE_CUE, "probe_text": investigator.PROBE_TEXT, "probe_name": "VC_TEXTPLUS_0114_sub_114", "project_name": "New Project 1", "timeline_name": "DZsqH7auhjt_textplus_full", "failures": [], "summary": self.summary(modified, already), "track_integrity": {"ok": True}, "v3_track_integrity": {"ok": True}}

    def validation(self, mode: str, ok: bool, report: Path) -> dict:
        return {"ok": ok, "step": investigator.STEP, "validator_version": gate.REPORT_VALIDATOR_VERSION, "mode": mode, "failures": [] if ok else ["rejected"], "checks": {"required": ok}, "plan": str(self.plan_path), "report": str(report)}

    def inspect(self) -> dict:
        return investigator.inspect(self.root, self.gate_output, self.output)

    def test_classifies_missing_second_pass_as_class_d(self) -> None:
        result = self.inspect()
        self.assertTrue(result["ok"])
        self.assertIn("CLASS D", result["classification"])
        assessment = json.loads((self.output / "step_3B_6C_acceptance_assessment.json").read_text())
        self.assertFalse(assessment["historical_idempotency_claim_substantiated"])
        self.assertEqual(json.loads((self.output / "next_task_recommendation.json").read_text())["next_mode"], "BUILD")

    def test_classifies_relocated_valid_second_pass_as_class_a(self) -> None:
        report = self.reports / "historic" / "second.json"
        validation = self.reports / "historic" / "validation.json"
        self.write(report, self.report("idempotent_second_run", 0, 1))
        self.write(validation, self.validation("idempotent_second_run", True, report))
        result = self.inspect()
        self.assertIn("CLASS A", result["classification"])

    def test_classifies_invalid_second_pass_as_class_c(self) -> None:
        report = self.reports / "historic" / "second.json"
        self.write(report, self.report("idempotent_second_run", 1, 0))
        result = self.inspect()
        self.assertIn("CLASS C", result["classification"])

    def test_inventory_records_hash_size_and_identity(self) -> None:
        self.inspect()
        inventory = json.loads((self.output / "step_3B_6C_artifact_inventory.json").read_text())
        row = next(row for row in inventory["artifacts"] if row["path"].endswith("first_application_report.json"))
        self.assertGreater(row["size"], 0)
        self.assertEqual(len(row["sha256"]), 64)
        self.assertEqual(row["cue_id"], investigator.PROBE_CUE)

    def test_writes_only_six_required_json_outputs(self) -> None:
        result = self.inspect()
        self.assertEqual(len(result["outputs"]), 6)
        self.assertEqual(sorted(path.name for path in self.output.iterdir()), result["outputs"])


if __name__ == "__main__":
    unittest.main()
