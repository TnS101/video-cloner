from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


STAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = STAGE_ROOT
RUN_ID = "20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379"
REL_DIR = Path(".agent/reports/DZSQH7AUHJT_STEP_3B_6D_RUNTIME_EXECUTION_V1") / RUN_ID
REL_COMMAND = Path(".agent/commands/failed") / f"DZSQH7AUHJT_STEP_3B_6D_RUNTIME_EXECUTION_V1_{RUN_ID}.json"
REL_PLAN = Path(".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prepared_plan_one.json")


def load_module():
    path = STAGE_ROOT / "scripts/davinci/investigate_step_3B_6D_runtime_failure.py"
    spec = importlib.util.spec_from_file_location("runtime_failure_forensics", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


forensics = load_module()


class RuntimeFailureForensicsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(SOURCE_ROOT / REL_DIR, self.root / REL_DIR)
        (self.root / REL_COMMAND).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_ROOT / REL_COMMAND, self.root / REL_COMMAND)
        (self.root / REL_PLAN).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_ROOT / REL_PLAN, self.root / REL_PLAN)
        command_path = self.root / REL_COMMAND
        command = json.loads(command_path.read_text(encoding="utf-8"))
        command["payload"]["repository_root"] = str(self.root)
        command_path.write_text(json.dumps(command), encoding="utf-8")
        self.output = self.root / "output"

    def tearDown(self): self.temp.cleanup()

    def call(self, run_id=RUN_ID):
        return forensics.inspect(self.root, self.root / REL_DIR, self.root / REL_COMMAND, self.root / REL_PLAN, self.output, run_id)

    def test_reconstructs_all_operations_mutations_mismatches_rollback_and_route_b(self):
        artifacts = self.call()
        forward = artifacts["forward_operation_ledger.json"]
        self.assertEqual(len(forward["operations"]), 36)
        self.assertEqual(forward["setter_call_count"], 20)
        self.assertEqual(forward["effective_mutation_count"], 20)
        mismatch = artifacts["persistent_readback_mismatch_analysis.json"]
        self.assertEqual(mismatch["first_mismatch"]["cue_id"], "sub_013")
        self.assertEqual(mismatch["first_mismatch"]["local_frame"], 2)
        self.assertEqual(len(mismatch["all_mismatches"]), 2)
        self.assertEqual(artifacts["runtime_root_cause_classification.json"]["readback_classification"], "R2 â€” FRAME_OR_KEY_ADDRESSING_MISMATCH")
        self.assertEqual(artifacts["runtime_root_cause_classification.json"]["rollback_classification"], "B3 â€” KEY_REMOVAL_OR_RESTORATION_UNSUPPORTED")
        self.assertEqual(artifacts["recovery_route_recommendation.json"]["route"], "ROUTE B â€” READ-ONLY RESOLVE STATE CAPTURE REQUIRED")
        self.assertTrue(all((self.output / name).is_file() for name in artifacts))

    def test_exact_run_and_plan_identity_required(self):
        with self.assertRaisesRegex(ValueError, "failed_run_id"):
            self.call("wrong")
        plan = json.loads((self.root / REL_PLAN).read_text(encoding="utf-8")); plan["plan_hash"] = "wrong"
        (self.root / REL_PLAN).write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "accepted_plan_hash"):
            self.call()

    def test_missing_or_duplicate_operation_journal_fails_closed(self):
        phase = self.root / REL_DIR / "phase_1_mutation_manifest.json"
        value = json.loads(phase.read_text(encoding="utf-8")); value["operations"] = value["operations"][:-1]
        phase.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mutation_journal"):
            self.call()
        self.temp.cleanup(); self.setUp(); phase = self.root / REL_DIR / "phase_1_mutation_manifest.json"
        value = json.loads(phase.read_text(encoding="utf-8")); value["operations"].append(value["operations"][0])
        phase.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate_or_invalid_mutation_journal"):
            self.call()

    def test_no_queue_or_source_artifact_mutation(self):
        command_before = (self.root / REL_COMMAND).read_bytes()
        report_before = (self.root / REL_DIR / "report.json").read_bytes()
        self.call()
        self.assertEqual((self.root / REL_COMMAND).read_bytes(), command_before)
        self.assertEqual((self.root / REL_DIR / "report.json").read_bytes(), report_before)
        self.assertFalse((self.root / ".agent/commands/pending").exists())


if __name__ == "__main__": unittest.main()
