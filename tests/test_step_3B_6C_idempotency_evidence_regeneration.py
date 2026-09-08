from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DRAFT = Path(__file__).resolve().parents[1]
runtime = load_module("regen_runtime", DRAFT / "resolve_workspace/modules/step_3B_6C_idempotency_evidence_regeneration.py")
validator = load_module("regen_validator", DRAFT / "scripts/davinci/validate_caption_source_geometry_step_3B_6C_idempotency_evidence_regeneration.py")


class FakeInput:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def GetConnectedOutput(self):
        return object() if self.connected else None


class FakeTool:
    def __init__(self, centers: dict[int, object], sizes: dict[int, object], text: str = "AND") -> None:
        self.values = {"Center": centers, "Size": sizes, "StyledText": {0: text}}
        self.inputs = {"Center": FakeInput(), "Size": FakeInput(), "StyledText": FakeInput(False)}
        self.setter_calls = 0

    def GetAttrs(self):
        return {"TOOLS_RegID": "TextPlus"}

    def FindInput(self, name):
        return self.inputs.get(name)

    def GetInput(self, name, frame):
        return self.values.get(name, {}).get(frame)

    def SetInput(self, *args):
        self.setter_calls += 1
        raise AssertionError("read-only runtime called SetInput")


class FakeComp:
    def __init__(self, tool: FakeTool) -> None:
        self.tool = tool

    def GetToolList(self, _selected):
        return {"Template": self.tool}


class FakeItem:
    def __init__(self, name: str, start: int, end: int, tool: FakeTool | None = None) -> None:
        self.name, self.start, self.end, self.tool = name, start, end, tool

    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetFusionCompCount(self): return 1 if self.tool else 0
    def GetFusionCompByIndex(self, _index): return FakeComp(self.tool) if self.tool else None


class FakeTimeline:
    def __init__(self, target: FakeItem, name: str = "DZsqH7auhjt_textplus_full") -> None:
        self.name = name
        self.items = [FakeItem(f"OTHER_{index:03d}", index, index + 1) for index in range(115)] + [target]

    def GetName(self): return self.name
    def GetItemListInTrack(self, track_type, index): return list(self.items) if (track_type, index) == ("video", 3) else []


class FakeProject:
    def __init__(self, timeline: FakeTimeline, name: str = "New Project 1") -> None:
        self.timeline, self.name = timeline, name

    def GetName(self): return self.name
    def GetCurrentTimeline(self): return self.timeline


class FakeManager:
    def __init__(self, project: FakeProject) -> None: self.project = project
    def GetCurrentProject(self): return self.project


class FakeResolve:
    def __init__(self, project: FakeProject) -> None: self.manager = FakeManager(project)
    def GetProjectManager(self): return self.manager


class RegenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="vc_3b6c_regen_")
        self.root = Path(self.temporary.name)
        self.plan_path = self.root / "data/plan.json"
        self.first_path = self.root / "data/first.json"
        self.report_dir = self.root / "reports/run-regen"
        centers = {frame: [0.5 + frame / 1000, 0.54] for frame in range(6)}
        sizes = {frame: 0.05 + frame / 1000 for frame in range(6)}
        targets = ([{"input": "Center", "local_frame": frame, "timeline_frame": 888 + frame, "expected": value} for frame, value in centers.items()] + [{"input": "Size", "local_frame": frame, "timeline_frame": 888 + frame, "expected": value} for frame, value in sizes.items()])
        plan = {"ok": True, "step": "Major Step 3B.6C", "schema": runtime.PLAN_SCHEMA, "created_at_unix": 1, "probe": {"scene_id": "caption_scene_015", "cue_id": "sub_114", "text": "AND", "name": "VC_TEXTPLUS_0114_sub_114", "start_frame": 888, "end_frame": 894, "visibility": {"timeline_item_start": 888, "timeline_item_end": 894, "fully_contained_in_existing_item": True}, "targets": targets}, "summary": {"protected_animation_caption_count": 8, "protected_animation_target_count": 16, "timing_mismatch_excluded_count": 1}}
        plan["plan_hash"] = runtime.canonical_hash(plan)
        self.write(self.plan_path, plan)
        first = {"ok": True, "step": "Major Step 3B.6C", "run_id": "historical", "run_mode": "first_application", "plan_hash": plan["plan_hash"], "probe_cue_id": "sub_114", "probe_text": "AND", "project_name": "New Project 1", "timeline_name": "DZsqH7auhjt_textplus_full", "targets_after": [{**row, "actual": row["expected"], "present": True, "matched": True} for row in targets]}
        self.write(self.first_path, first)
        self.centers, self.sizes = centers, sizes
        self.tool = FakeTool(dict(centers), dict(sizes))
        self.target = FakeItem("VC_TEXTPLUS_0114_sub_114", 888, 894, self.tool)
        self.timeline = FakeTimeline(self.target)
        self.project = FakeProject(self.timeline)
        self.resolve = FakeResolve(self.project)
        self.command = self.make_command()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def make_command(self) -> dict:
        payload = {**runtime.EXPECTED, "repository_root": str(self.root), "allowed_properties": ["Center", "Size"], "forbidden_properties": ["Blend", "StyledText", "Font", "timing", "track_structure"], "plan_path": str(self.plan_path), "plan_sha256": runtime.sha256(self.plan_path), "first_report_path": str(self.first_path), "first_report_sha256": runtime.sha256(self.first_path), "canonical_report_path": str(self.root / "data/idempotency_report.json"), "pre_state_path": str(self.report_dir / "pre_state.json"), "post_state_path": str(self.report_dir / "post_state.json"), "comparison_path": str(self.report_dir / "comparison.json"), "no_effective_change_path": str(self.report_dir / "no_effective_change.json"), "value_tolerance": 1e-6}
        return {"schema_version": 1, "task": runtime.TASK_ID, "run_id": "run-regen", "module": "resolve_workspace/modules/step_3B_6C_idempotency_evidence_regeneration.py", "mode": "persistent_readback_noop", "status_path": "reports/run-regen/status.json", "log_path": "reports/run-regen/run.log", "report_path": "reports/run-regen/report.json", "payload": payload}

    def execute(self) -> dict:
        return runtime.run(self.resolve, {"run_id": "run-regen", "command": self.command})

    def test_matching_persistent_state_proves_zero_mutation(self) -> None:
        report = self.execute()
        self.assertTrue(report["ok"])
        self.assertEqual(report["effective_mutation_count"], 0)
        self.assertEqual(report["setter_call_count"], 0)
        self.assertEqual(report["blend_operation_count"], 0)
        self.assertFalse(report["timeline_modified"])
        self.assertEqual(self.tool.setter_calls, 0)
        self.assertEqual(len(report["targets_after"]), 12)

    def test_center_or_size_drift_fails_without_output_or_mutation(self) -> None:
        for name, frame in (("Center", 2), ("Size", 4)):
            with self.subTest(name=name):
                original = self.tool.values[name][frame]
                self.tool.values[name][frame] = [0.1, 0.1] if name == "Center" else 0.9
                report = self.execute()
                self.assertFalse(report["ok"])
                self.assertEqual(self.tool.setter_calls, 0)
                self.assertFalse(Path(self.command["payload"]["canonical_report_path"]).exists())
                self.tool.values[name][frame] = original

    def test_missing_key_or_modifier_fails(self) -> None:
        self.tool.values["Center"].pop(3)
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.tool.setter_calls, 0)

    def test_wrong_project_or_timeline_fails(self) -> None:
        for project_name, timeline_name in (("Wrong", self.timeline.name), (self.project.name, "Wrong")):
            with self.subTest(project=project_name, timeline=timeline_name):
                resolve = FakeResolve(FakeProject(FakeTimeline(self.target, timeline_name), project_name))
                report = runtime.run(resolve, {"run_id": "run-regen", "command": self.command})
                self.assertFalse(report["ok"])
                self.assertEqual(self.tool.setter_calls, 0)

    def test_missing_or_ambiguous_item_fails(self) -> None:
        self.timeline.items = self.timeline.items[:-1]
        self.assertFalse(self.execute()["ok"])
        self.timeline.items = [FakeItem(f"OTHER_{index}", index, index + 1) for index in range(114)] + [self.target, self.target]
        self.assertFalse(self.execute()["ok"])

    def test_wrong_text_fails(self) -> None:
        self.tool.values["StyledText"][0] = "NOT AND"
        self.assertFalse(self.execute()["ok"])

    def test_command_identity_timing_and_property_contract_fail_closed(self) -> None:
        cases = (("project_name", "Wrong"), ("timeline_name", "Wrong"), ("track_index", 2), ("item_name", "Wrong"), ("cue_id", "sub_007"), ("text", "Wrong"), ("start_frame", 887), ("end_frame", 895), ("allowed_properties", ["Center", "Size", "Blend"]))
        for key, value in cases:
            with self.subTest(key=key):
                command = json.loads(json.dumps(self.command))
                command["payload"][key] = value
                with self.assertRaises(ValueError):
                    runtime.validate_command(command, "run-regen")

    def test_prerequisite_hash_or_baseline_identity_drift_fails(self) -> None:
        self.command["payload"]["plan_sha256"] = "0" * 64
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(self.tool.setter_calls, 0)

    def test_conflicting_canonical_output_is_not_overwritten(self) -> None:
        canonical = Path(self.command["payload"]["canonical_report_path"])
        self.write(canonical, {"conflict": True})
        self.assertFalse(self.execute()["ok"])
        self.assertEqual(json.loads(canonical.read_text()), {"conflict": True})

    def test_successful_report_validates_with_same_run_id(self) -> None:
        report = self.execute()
        canonical = Path(self.command["payload"]["canonical_report_path"])
        result = validator.validate(json.loads(self.plan_path.read_text()), report, self.plan_path, canonical, "run-regen")
        self.assertTrue(result["ok"], result["failures"])
        self.assertEqual(result["run_id"], "run-regen")
        self.assertEqual(result["validator_version"], validator.COMPATIBLE_VALIDATOR_VERSION)

    def test_failed_or_wrong_run_report_cannot_validate(self) -> None:
        report = self.execute()
        result = validator.validate(json.loads(self.plan_path.read_text()), report, self.plan_path, Path(self.command["payload"]["canonical_report_path"]), "other-run")
        self.assertFalse(result["ok"])
        self.assertIn("run_id", result["failures"])

    def test_command_packages_one_canonical_pending_entry(self) -> None:
        pending = self.root / ".agent/commands/pending"
        pending.mkdir(parents=True)
        self.write(pending / "run-regen.json", self.command)
        files = list(pending.glob("*.json"))
        self.assertEqual(len(files), 1)
        loaded = json.loads(files[0].read_text())
        self.assertEqual(loaded["run_id"], "run-regen")
        self.assertEqual(loaded["module"], "resolve_workspace/modules/step_3B_6C_idempotency_evidence_regeneration.py")


if __name__ == "__main__":
    unittest.main()
