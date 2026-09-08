from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.davinci import validate_caption_source_geometry_probe_evidence_step_3B_6 as gate


class EvidenceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="vc_evidence_gate_")
        self.root = Path(self.temporary.name)
        self.plan_path = self.root / "plan.json"
        self.first_report = self.root / "first_report.json"
        self.first_validation = self.root / "first_validation.json"
        self.idempotency_report = self.root / "idempotency_report.json"
        self.idempotency_validation = self.root / "idempotency_validation.json"
        plan = {"ok": True, "schema": gate.PLAN_SCHEMA, "created_at_unix": 1}
        plan["plan_hash"] = gate.canonical_hash(plan, ignored=("created_at_unix",))
        self.write(self.plan_path, plan)
        self.write_pair(self.first_report, self.first_validation, "first_application", "first_application_pass", 1, 0)
        self.write_pair(self.idempotency_report, self.idempotency_validation, "idempotent_second_run", "idempotent_second_run", 0, 1)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def summary(modified: int, already_correct: int) -> dict:
        return {
            "modified_count": modified,
            "already_correct_count": already_correct,
            "non_probe_caption_count": 115,
            "non_probe_caption_verified_count": 115,
            "protected_animation_caption_count": 8,
            "protected_animation_verified_count": 8,
            "protected_animation_target_count": 16,
            "protected_animation_target_verified_count": 16,
            "opacity_proxy_applied_count": 0,
            "z_order_write_count": 0,
            "timeline_boundary_write_count": 0,
            "timeline_integrity_failure_count": 0,
            "protected_integrity_failure_count": 0,
            "failed_count": 0,
        }

    def write_pair(self, report_path: Path, validation_path: Path, report_mode: str, validation_mode: str, modified: int, already_correct: int) -> None:
        plan_hash = json.loads(self.plan_path.read_text(encoding="utf-8"))["plan_hash"]
        self.write(
            report_path,
            {
                "ok": True,
                "task_id": gate.ACCEPTED_IDEMPOTENCY_TASK_ID,
                "run_id": gate.ACCEPTED_IDEMPOTENCY_RUN_ID,
                "run_mode": report_mode,
                "plan_hash": plan_hash,
                "first_report_path": str(self.first_report),
                "timeline_modified": False,
                "setter_call_count": 0,
                "effective_mutation_count": 0,
                "blend_operation_count": 0,
                "failures": [],
                "summary": self.summary(modified, already_correct),
                "track_integrity": {"ok": True},
                "v3_track_integrity": {"ok": True},
            },
        )
        self.write(
            validation_path,
            {
                "ok": True,
                "task_id": gate.ACCEPTED_IDEMPOTENCY_TASK_ID,
                "run_id": gate.ACCEPTED_IDEMPOTENCY_RUN_ID,
                "validator_version": gate.REPORT_VALIDATOR_VERSION,
                "mode": validation_mode,
                "failures": [],
                "checks": {"all_required_checks": True},
                "plan": str(self.plan_path),
                "report": str(report_path),
            },
        )

    def assessment(self) -> dict:
        return gate.assess(
            self.plan_path,
            self.first_report,
            self.first_validation,
            self.idempotency_report,
            self.idempotency_validation,
        )

    def test_accepts_complete_matching_evidence(self) -> None:
        result = self.assessment()
        self.assertTrue(result["accepted"])
        self.assertTrue(result["next_step_permitted"])

    def test_audits_rejected_historical_first_pass_without_using_it_as_a_substitute(self) -> None:
        self.write_pair(self.first_report, self.first_validation, "first_application", "first_application_pass", 0, 1)
        result = self.assessment()
        self.assertTrue(result["accepted"])
        self.assertFalse(result["first_application"]["accepted"])
        self.assertFalse(result["first_application"]["required_for_acceptance"])
        self.assertIn("expected_modified_count", result["first_application"]["failures"])

    def test_rejects_missing_idempotency_evidence(self) -> None:
        self.idempotency_validation.unlink()
        result = self.assessment()
        self.assertFalse(result["accepted"])
        self.assertEqual(result["idempotency"]["failures"], ["validation_missing"])

    def test_rejects_invalid_canonical_idempotency_identity(self) -> None:
        report = json.loads(self.idempotency_report.read_text(encoding="utf-8"))
        report["run_id"] = "wrong"
        self.write(self.idempotency_report, report)
        result = self.assessment()
        self.assertFalse(result["accepted"])
        self.assertIn("report_run_id", result["idempotency"]["failures"])

    def test_rejects_validation_bound_to_another_report(self) -> None:
        validation = json.loads(self.idempotency_validation.read_text(encoding="utf-8"))
        validation["report"] = str(self.root / "other.json")
        self.write(self.idempotency_validation, validation)
        result = self.assessment()
        self.assertFalse(result["accepted"])
        self.assertIn("validation_report_path", result["idempotency"]["failures"])

    def test_rejects_false_or_absent_validation_checks(self) -> None:
        validation = json.loads(self.idempotency_validation.read_text(encoding="utf-8"))
        validation["checks"] = {"required": False}
        self.write(self.idempotency_validation, validation)
        result = self.assessment()
        self.assertFalse(result["accepted"])
        self.assertIn("validation_checks_all_true", result["idempotency"]["failures"])


if __name__ == "__main__":
    unittest.main()
