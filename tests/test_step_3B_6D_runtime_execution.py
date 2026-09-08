from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load_module("resolve_workspace/modules/step_3B_6D_runtime_execution.py", "step_3B_6D_runtime")
prepare = load_module("scripts/davinci/prepare_step_3B_6D_runtime_command.py", "prepare_step_3B_6D")
validator = load_module("scripts/davinci/validate_step_3B_6D_runtime_evidence.py", "validate_step_3B_6D")


def dump(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


class CommandContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.report = self.root / ".agent" / "reports" / runtime.TASK_ID / "run"
        self.plan = self.root / "plan.json"
        dump(self.plan, {})
        self.command = {
            "task": runtime.TASK_ID, "run_id": "run",
            "mode": "contained_geometry_first_application_and_in_run_idempotency",
            "payload": {"repository_root": str(self.root), "report_dir": str(self.report.relative_to(self.root)), "plan_path": "plan.json", "allowed_properties": ["Center", "Size"], "forbidden_properties": ["Blend", "unknown_or_other"], **runtime.EXPECTED},
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_command_accepted(self):
        root, plan, payload = runtime._command(self.command, "run")
        self.assertEqual((root, plan), (self.root, self.plan))
        self.assertEqual(payload["expected_v3_count"], 116)

    def test_wrong_command_identity_mode_and_resolve_identity_rejected(self):
        cases = (("task", "WRONG"), ("run_id", "other"), ("mode", "other"))
        for key, value in cases:
            with self.subTest(key=key), mock.patch.dict(self.command, {key: value}):
                with self.assertRaises(ValueError): runtime._command(self.command, "run")
        for key in runtime.EXPECTED:
            changed = json.loads(json.dumps(self.command))
            changed["payload"][key] = "wrong"
            with self.subTest(payload=key), self.assertRaises(ValueError): runtime._command(changed, "run")

    def test_property_contamination_and_path_escape_rejected(self):
        for properties in (["Center", "Size", "Blend"], ["Center", "Other"]):
            changed = json.loads(json.dumps(self.command))
            changed["payload"]["allowed_properties"] = properties
            with self.assertRaises(ValueError): runtime._command(changed, "run")
        changed = json.loads(json.dumps(self.command)); changed["payload"]["plan_path"] = "../escape.json"
        with self.assertRaises(ValueError): runtime._command(changed, "run")


class BaselineAndRollbackTests(unittest.TestCase):
    class Input:
        def __init__(self, connected=None): self.connected = connected
        def GetConnectedOutput(self): return self.connected

    class Tool:
        def __init__(self):
            self.values = {"Center": [0.4912565217, 0.5481043478], "Size": 0.070191107611}
            self.inputs = {"Center": BaselineAndRollbackTests.Input(), "Size": BaselineAndRollbackTests.Input()}
        def DeleteModifier(self, name): self.inputs[name].connected = None; return True
        def SetInput(self, name, value): self.values[name] = value; return True

    class Legacy:
        @staticmethod
        def connected_output(value): return value.connected
        @staticmethod
        def find_input(tool, name): return tool.inputs[name]
        @staticmethod
        def values_match(name, actual, expected, tolerance):
            if name == "Center": return all(abs(float(a)-float(b)) <= tolerance for a, b in zip(actual, expected))
            return abs(float(actual)-float(expected)) <= tolerance
        @staticmethod
        def safe_call(obj, method, *args, default=None):
            try: return getattr(obj, method)(*args)
            except Exception: return default
        @staticmethod
        def fusion_variants(name, value): return [value]
        @staticmethod
        def read_input(tool, name, frame=0): return tool.values[name]
        @staticmethod
        def json_safe(value): return value

    def test_timeline_timecode_is_deterministic(self):
        self.assertEqual(runtime._timecode(196, 24), "00:00:08:04")
        self.assertEqual(runtime._timecode(199, 24), "00:00:08:07")

    def test_exact_static_baseline_accepted_but_connected_or_partial_rejected(self):
        tool = self.Tool()
        rows = [{"input": "Center", "actual": tool.values["Center"]}, {"input": "Size", "actual": tool.values["Size"]}]
        self.assertTrue(runtime._accepted_static(self.Legacy, "sub_007", tool, rows, 1e-5))
        tool.inputs["Center"].connected = object()
        self.assertFalse(runtime._accepted_static(self.Legacy, "sub_007", tool, rows, 1e-5))
        tool.inputs["Center"].connected = None; rows[0]["actual"] = [0.4, 0.4]
        self.assertFalse(runtime._accepted_static(self.Legacy, "sub_007", tool, rows, 1e-5))
        self.assertFalse(runtime._accepted_static(self.Legacy, "sub_114", tool, rows, 1e-5))

    def test_created_modifiers_are_removed_and_static_values_persistently_verified(self):
        tool = self.Tool(); tool.inputs["Center"].connected = object(); tool.values["Center"] = [0.2, 0.2]
        manager = type("Manager", (), {"SaveProject": lambda self: True})()
        acquired = {"item": (object(), object(), tool)}
        snapshot = {"item": {"Center": [0.4912565217, 0.5481043478], "Size": 0.070191107611}}
        result = runtime._rollback(self.Legacy, manager, acquired, snapshot, [("item", "Center")], 1e-5, 0)
        self.assertTrue(result["attempted"])
        self.assertTrue(result["ok"])
        self.assertIsNone(tool.inputs["Center"].connected)


class PublisherTests(unittest.TestCase):
    def setUp(self): self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
    def tearDown(self): self.temp.cleanup()

    def fixture(self):
        plan = {"ok": True, "summary": {"center_target_count": 18, "size_target_count": 18, "blend_target_count": 0, "other_property_target_count": 0, "total_target_count": 36}, "rollout_items": [{"cue_id": cue} for cue in ("sub_007", "sub_013", "sub_110", "sub_114")]}
        semantic = prepare.canonical_hash(plan); plan["plan_hash"] = semantic
        plan_path = self.root / "accepted.json"; dump(plan_path, plan)
        prerequisite = self.root / "gate.json"; dump(prerequisite, {"ok": True})
        return plan_path, semantic, hashlib.sha256(plan_path.read_bytes()).hexdigest(), prerequisite, hashlib.sha256(prerequisite.read_bytes()).hexdigest()

    def test_exactly_one_canonical_command_is_published_atomically(self):
        plan, semantic, file_hash, prerequisite, prerequisite_hash = self.fixture()
        run_id = "20260802T150000000Z_0123456789abcdef0123456789abcdef"
        with mock.patch.object(prepare, "PLAN_PATH", "accepted.json"), mock.patch.object(prepare, "PLAN_HASH", semantic), mock.patch.object(prepare, "PLAN_FILE_SHA256", file_hash), mock.patch.object(prepare, "PREREQUISITES", [{"path": "gate.json", "sha256": prerequisite_hash}]):
            destination = prepare.publish(self.root, run_id)
        self.assertTrue(destination.is_file())
        self.assertEqual(len(list((self.root / ".agent/commands/pending").glob("*.json"))), 1)
        self.assertEqual(json.loads(destination.read_text())["run_id"], run_id)
        self.assertTrue((self.root / f".agent/reports/{prepare.TASK_ID}/{run_id}/runtime_command.json").is_file())

    def test_invalid_run_id_and_active_command_stop_before_publication(self):
        with self.assertRaises(ValueError): prepare.publish(self.root, "bad")
        (self.root / ".agent/commands/pending").mkdir(parents=True); dump(self.root / ".agent/commands/pending/existing.json", {})
        run_id = "20260802T150000000Z_0123456789abcdef0123456789abcdef"
        with self.assertRaises(ValueError): prepare.publish(self.root, run_id)


class EvidenceValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.run_id = "20260802T150000000Z_0123456789abcdef0123456789abcdef"
        self.report = self.root / ".agent/reports" / validator.TASK_ID / self.run_id
        self.build_success()
    def tearDown(self): self.temp.cleanup()

    def identity(self, **extra): return {"ok": True, "task_id": validator.TASK_ID, "run_id": self.run_id, **extra}

    def build_success(self):
        command = {"schema_version": 1, "task": validator.TASK_ID, "run_id": self.run_id, "module": "resolve_workspace/modules/step_3B_6D_runtime_execution.py", "payload": {"plan_hash": validator.PLAN_HASH, "allowed_properties": ["Center", "Size"], "forbidden_properties": ["Blend", "unknown_or_other"]}}
        values = {
            "runtime_command.json": command,
            "prerequisite_hash_validation.json": self.identity(plan_hash=validator.PLAN_HASH),
            "status.json": {"ok": True, "running": False, "run_id": self.run_id},
            "report.json": self.identity(plan_hash=validator.PLAN_HASH, blend_operation_count=0, persistent_readback_matched=True, non_target_preserved=True),
            "accepted_plan_identity_report.json": self.identity(plan_hash=validator.PLAN_HASH, cue_ids=list(validator.TARGETS), operation_counts={"Center": 18, "Size": 18, "Blend": 0, "other": 0, "total": 36}),
            "preflight_report.json": self.identity(all_targets_validated_before_first_setter=True, target_count=4, non_target_count=112, caption_count=116),
            "four_target_pre_state_snapshot.json": self.identity(items=[{"cue_id": cue, "text": text, "state": "already_correct" if cue == "sub_114" else "accepted_static_pre_state"} for cue, text in validator.TARGETS.items()]),
            "phase_1_mutation_manifest.json": self.identity(blend_operation_count=0, setter_call_count=0, effective_mutation_count=0, operations=[]),
            "phase_1_persistent_post_state.json": self.identity(),
            "readback_comparison.json": self.identity(expected_operation_count=36, matched_operation_count=36, Center=18, Size=18, Blend=0, other=0, targets=[{"present": True} for _ in range(36)]),
            "phase_2_idempotency_report.json": self.identity(same_runtime_boundary=True, evaluated_operation_count=36, setter_call_count=0, effective_mutation_count=0, blend_operation_count=0, timeline_modified=False, operations=[{"operation": "compared_and_skipped"} for _ in range(36)]),
            "non_target_mutation_audit.json": self.identity(non_target_expected=112, non_target_changes=[], target_forbidden_changes=[], track_before={"same": True}, track_after={"same": True}),
            "protected_inventory_comparison.json": self.identity(protected_animation_before=[], protected_animation_after=[]),
            "four_cue_visual_review_checklist.json": self.identity(visual_approval_pending=True, cues=[{"cue_id": cue, "text": text} for cue, text in validator.TARGETS.items()]),
        }
        for name, value in values.items(): dump(self.report / name, value)
        (self.report / "run.log").write_text("bridge_started\nbridge_finished ok=True\n", encoding="utf-8")
        dump(self.root / f".agent/commands/completed/{validator.TASK_ID}_{self.run_id}.json", command)

    def test_complete_persistent_same_run_evidence_passes_and_emits_validations(self):
        result, failures = validator.validate(self.root, self.run_id)
        self.assertFalse(failures); self.assertTrue(result["ok"])
        for name in ("command_lifecycle_inventory.json", "runtime_artifact_validation.json", "phase_2_idempotency_validation.json"):
            self.assertTrue((self.report / name).is_file())

    def test_phase2_mutation_sub114_setter_non_target_change_and_failed_queue_are_rejected(self):
        mutations = (
            ("phase_2_idempotency_report.json", lambda value: value.update(setter_call_count=1)),
            ("phase_1_mutation_manifest.json", lambda value: value.update(setter_call_count=1, effective_mutation_count=1, operations=[{"cue_id": "sub_114", "input": "Center", "ok": True}])),
            ("non_target_mutation_audit.json", lambda value: value.update(non_target_changes=["other"])),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                self.build_success(); value = json.loads((self.report / name).read_text()); mutate(value); dump(self.report / name, value)
                _, failures = validator.validate(self.root, self.run_id); self.assertTrue(failures)
        completed = self.root / f".agent/commands/completed/{validator.TASK_ID}_{self.run_id}.json"
        failed = self.root / f".agent/commands/failed/{completed.name}"; failed.parent.mkdir(parents=True, exist_ok=True); completed.replace(failed)
        _, failures = validator.validate(self.root, self.run_id); self.assertIn("command_lifecycle", failures)

    def test_missing_or_zero_artifact_and_rollback_on_success_rejected(self):
        (self.report / "readback_comparison.json").unlink()
        _, failures = validator.validate(self.root, self.run_id); self.assertTrue(any("readback" in row for row in failures))
        self.build_success(); dump(self.report / "rollback_evidence.json", {"ok": True})
        _, failures = validator.validate(self.root, self.run_id); self.assertIn("rollback_invoked_on_success", failures)


if __name__ == "__main__": unittest.main()
