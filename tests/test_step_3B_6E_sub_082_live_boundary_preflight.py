from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "resolve_workspace/modules/step_3B_6E_sub_082_live_boundary_preflight.py"
PREPARER_PATH = ROOT / "scripts/davinci/prepare_step_3B_6E_sub_082_live_boundary_preflight_command.py"
VALIDATOR_PATH = ROOT / "scripts/davinci/validate_step_3B_6E_sub_082_live_boundary_preflight.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load_module("live_boundary_runtime", RUNTIME_PATH)
preparer = load_module("live_boundary_preparer", PREPARER_PATH)
validator = load_module("live_boundary_validator", VALIDATOR_PATH)


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeOutput:
    def GetAttrs(self):
        return {"OUTS_Name": "Position", "OUTS_DataType": "Point", "OUTS_ID": "Position"}


class FakeInput:
    def __init__(self, values: dict[int, Any], connected: bool = False, keyframes: dict[Any, Any] | None = None):
        self.values = dict(values)
        self.connected = connected
        self.keyframes = keyframes or {}

    def __getitem__(self, frame):
        return self.values.get(int(frame))

    def GetConnectedOutput(self):
        return FakeOutput() if self.connected else None

    def GetAttrs(self):
        return {"INPS_ID": "input", "INPB_Connected": self.connected}

    def GetKeyFrames(self):
        return dict(self.keyframes)


class FakeTool:
    def __init__(self, text: str, centers: dict[int, Any] | None = None, sizes: dict[int, Any] | None = None, center_connected: bool = False):
        self.values = {
            "StyledText": {0: text},
            "Center": centers or {0: [0.5, 0.5], 6: [0.5, 0.5]},
            "Size": sizes or {0: 0.05, 6: 0.05},
        }
        self.inputs = {
            "StyledText": FakeInput(self.values["StyledText"]),
            "Center": FakeInput(self.values["Center"], connected=center_connected, keyframes={1: 0.0, 2: 2.0} if center_connected else {}),
            "Size": FakeInput(self.values["Size"]),
        }

    def GetAttrs(self):
        return {"TOOLS_RegID": "TextPlus"}

    def FindInput(self, name):
        return self.inputs.get(name)

    def GetInput(self, name, frame):
        return self.values.get(name, {}).get(int(frame))


class FakeComp:
    def __init__(self, tool: FakeTool):
        self.tool = tool

    def GetToolList(self, _selected):
        return {"Template": self.tool}


class FakeItem:
    def __init__(self, name: str, start: int, end: int, tool: FakeTool | None = None, expose_setters: bool = True):
        self.name = name
        self.start = start
        self.end = end
        self.tool = tool
        self.setter_calls = 0
        if not expose_setters:
            self.SetStart = None
            self.SetEnd = None
            self.SetProperty = None

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetProperty(self):
        return {"Start": self.start, "End": self.end}

    def SetStart(self, *_args):
        self.setter_calls += 1
        raise AssertionError("SetStart was called")

    def SetEnd(self, *_args):
        self.setter_calls += 1
        raise AssertionError("SetEnd was called")

    def SetProperty(self, *_args):
        self.setter_calls += 1
        raise AssertionError("SetProperty was called")

    def GetFusionCompCount(self):
        return 1 if self.tool is not None else 0

    def GetFusionCompByIndex(self, _index):
        return FakeComp(self.tool) if self.tool is not None else None


class FakeTimeline:
    def __init__(self, items: list[FakeItem], name: str = "DZsqH7auhjt_textplus_full"):
        self.items = items
        self.name = name

    def GetName(self):
        return self.name

    def GetItemListInTrack(self, track_type, index):
        return list(self.items) if (track_type, index) == ("video", 3) else []


class FakeProject:
    def __init__(self, timeline: FakeTimeline, name: str = "New Project 1"):
        self.timeline = timeline
        self.name = name

    def GetName(self):
        return self.name

    def GetCurrentTimeline(self):
        return self.timeline


class FakeManager:
    def __init__(self, project: FakeProject):
        self.project = project

    def GetCurrentProject(self):
        return self.project


class FakeResolve:
    def __init__(self, project: FakeProject):
        self.manager = FakeManager(project)

    def GetProjectManager(self):
        return self.manager


def make_items(expose_setters: bool = True) -> list[FakeItem]:
    items: list[FakeItem] = []
    for index in range(1, 117):
        cue = f"sub_{index:03d}"
        name = f"VC_TEXTPLUS_{index:04d}_{cue}"
        if index == 81:
            tool = FakeTool(
                "the",
                centers={0: [0.6203000000000001, 0.6120000000000001], 2: [0.7023, 0.6125]},
                center_connected=True,
            )
            items.append(FakeItem(name, 646, 649, tool, expose_setters))
        elif index == 82:
            items.append(FakeItem(name, 649, 656, FakeTool("blocks."), expose_setters))
        elif index == 83:
            items.append(FakeItem(name, 659, 665, FakeTool("That's"), expose_setters))
        elif index < 81:
            start = index * 5
            items.append(FakeItem(name, start, start + 3))
        else:
            start = 700 + (index - 84) * 5
            items.append(FakeItem(name, start, start + 3))
    return items


def source_artifacts(root: Path) -> None:
    report_dir = root / runtime.SOURCE_REPORT_REL
    dump(report_dir / "status.json", {"ok": True, "stage": "completed", "run_id": runtime.SOURCE_RUN_ID})
    candidate = {
        "cue_id": "sub_082",
        "name": "VC_TEXTPLUS_0082_sub_082",
        "text": "blocks.",
        "current_range": [649, 656],
        "proposed_range": [649, 657],
        "boundary_operations": [runtime.PROPOSED_OPERATION],
        "live_read_only_preflight_required": True,
        "mutation_command_permitted": False,
    }
    dump(report_dir / "report.json", {
        "ok": True,
        "task_id": runtime.SOURCE_TASK_ID,
        "run_id": runtime.SOURCE_RUN_ID,
        "classification": "ONE_STRUCTURALLY_ISOLATED_BOUNDARY_EXTENSION_CANDIDATE",
    })
    dump(report_dir / "strategy_summary.json", {
        "ok": True,
        "summary": {
            "remaining_accepted_boundary_cue_count": 41,
            "structurally_isolated_candidate_count": 1,
            "neighbor_collision_count": 40,
            "self_step_3C_protected_count": 4,
        },
    })
    dump(report_dir / "boundary_probe_candidate_allowlist.json", {
        "ok": True,
        "candidate_count": 1,
        "candidates": [candidate],
        "production_mutation_authorized": False,
    })
    dump(report_dir / "state_protection_audit.json", {
        "ok": True,
        "accepted_state_unchanged": True,
        "command_inventory_unchanged": True,
        "timeline_modified": False,
    })
    (report_dir / "FINAL_REPORT.md").write_text(
        "PASS — STEP_3B.6E_V3_BOUNDARY_TIMING_STRATEGY_ASSESSED\n",
        encoding="utf-8",
    )


def make_runtime_fixture(expose_setters: bool = True):
    temporary = tempfile.TemporaryDirectory(prefix="vc_live_boundary_")
    root = Path(temporary.name)
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    latest = root / ".agent/state/latest_accepted.json"
    dump(latest, {"accepted_step": "Step 3B.6D"})
    source_artifacts(root)
    dump(root / runtime.ANIMATION_TARGETS_REL, {
        "ok": True,
        "items": [{
            "cue_id": "sub_081",
            "name": "VC_TEXTPLUS_0081_sub_081",
            "targets": [
                {"input": "Center", "local_frame": 0, "expected": [0.6203000000000001, 0.6120000000000001]},
                {"input": "Center", "local_frame": 2, "expected": [0.7023, 0.6125]},
            ],
        }],
    })
    run_id = "20260803T150000123Z_0123456789abcdef0123456789abcdef"
    report_dir = root / ".agent/reports" / runtime.TASK_ID / run_id
    report_dir.mkdir(parents=True)
    command = {
        "schema_version": 1,
        "task": runtime.TASK_ID,
        "run_id": run_id,
        "module": "resolve_workspace/modules/step_3B_6E_sub_082_live_boundary_preflight.py",
        "mode": "live_read_only_boundary_preflight",
        "payload": {
            "repository_root": str(root),
            "report_dir": str(report_dir.relative_to(root)).replace("\\", "/"),
            "source_task_id": runtime.SOURCE_TASK_ID,
            "source_run_id": runtime.SOURCE_RUN_ID,
            "mutation_permitted": False,
            "proposed_operation": runtime.PROPOSED_OPERATION,
            "accepted_state_sha256": file_hash(latest),
            "command_inventory_before_publication": [],
        },
    }
    running = root / ".agent/commands/running" / f"{runtime.TASK_ID}_{run_id}.json"
    dump(running, command)
    dump(report_dir / "preflight_command.json", command)
    dump(report_dir / "publication_receipt.json", {
        "pending_observed": True,
        "command_sha256": file_hash(running),
    })
    items = make_items(expose_setters)
    resolve = FakeResolve(FakeProject(FakeTimeline(items)))
    return temporary, root, run_id, report_dir, running, command, items, resolve


def execute_fixture(expose_setters: bool = True):
    fixture = make_runtime_fixture(expose_setters)
    temporary, root, run_id, report_dir, running, command, items, resolve = fixture
    report = runtime.run(resolve, {"run_id": run_id, "command": command})
    return fixture, report


def test_runtime_is_read_only_with_exposed_setters() -> None:
    fixture, report = execute_fixture(True)
    temporary, _root, _run_id, report_dir, _running, _command, items, _resolve = fixture
    try:
        assert report["ok"], report["failures"]
        assert report["classification"] == "DIRECT_END_SETTER_EXPOSED_PERSISTENCE_ROLLBACK_UNPROVEN"
        assert report["effective_mutation_count"] == 0
        assert report["timeline_modified"] is False
        assert sum(item.setter_calls for item in items) == 0
        capability = json.loads((report_dir / "boundary_api_capability_inventory.json").read_text(encoding="utf-8"))
        assert capability["mutation_method_invocation_count"] == 0
    finally:
        temporary.cleanup()


def test_runtime_classifies_absent_setter_surface_without_mutation() -> None:
    fixture, report = execute_fixture(False)
    temporary = fixture[0]
    try:
        assert report["ok"], report["failures"]
        assert report["classification"] == "NO_BOUNDARY_MUTATION_API_SURFACE_EXPOSED"
        assert report["api_candidate_surface"] is None
    finally:
        temporary.cleanup()


def test_runtime_rejects_live_adjacency_drift() -> None:
    fixture = make_runtime_fixture(True)
    temporary, _root, run_id, _report_dir, _running, command, items, resolve = fixture
    try:
        target = next(item for item in items if item.name == "VC_TEXTPLUS_0083_sub_083")
        target.start = 657
        report = runtime.run(resolve, {"run_id": run_id, "command": command})
        assert not report["ok"]
        assert "item_identity:sub_083" in report["failures"][0]
        assert sum(item.setter_calls for item in items) == 0
    finally:
        temporary.cleanup()


def test_runtime_rejects_protected_neighbor_value_drift() -> None:
    fixture = make_runtime_fixture(True)
    temporary, _root, run_id, _report_dir, _running, command, items, resolve = fixture
    try:
        previous = next(item for item in items if item.name == "VC_TEXTPLUS_0081_sub_081")
        previous.tool.values["Center"][0] = [0.1, 0.1]
        previous.tool.inputs["Center"].values[0] = [0.1, 0.1]
        report = runtime.run(resolve, {"run_id": run_id, "command": command})
        assert not report["ok"]
        assert "sub_081_live_protected_target_mismatch" in report["failures"][0]
    finally:
        temporary.cleanup()


def test_source_assessment_contract_fails_closed() -> None:
    fixture = make_runtime_fixture(True)
    temporary, root, _run_id, _report_dir, _running, _command, _items, _resolve = fixture
    try:
        path = root / runtime.SOURCE_REPORT_REL / "boundary_probe_candidate_allowlist.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["candidates"][0]["mutation_command_permitted"] = True
        dump(path, value)
        with pytest.raises(ValueError, match="source_assessment_contract"):
            runtime.validate_source_assessment(root)
    finally:
        temporary.cleanup()


def test_runtime_ast_contains_no_forbidden_mutation_calls() -> None:
    tree = ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))
    forbidden = {"SetStart", "SetEnd", "SetProperty", "SetInput", "SaveProject", "DeleteModifier", "AddModifier", "ConnectTo", "Disconnect"}
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            calls.append(node.func.attr)
        elif isinstance(node.func, ast.Name):
            calls.append(node.func.id)
    assert not (set(calls) & forbidden)


def test_preparer_conflict_detection_rejects_any_active_command() -> None:
    with tempfile.TemporaryDirectory(prefix="vc_preparer_conflict_") as temp:
        root = Path(temp)
        for state in ("pending", "running", "completed", "failed"):
            (root / ".agent/commands" / state).mkdir(parents=True)
        dump(root / ".agent/commands/pending/OTHER.json", {})
        with pytest.raises(ValueError, match="active_command:pending"):
            preparer.validate_no_conflicts(root)


def test_preparer_run_id_contract() -> None:
    assert preparer.re_run_id("20260803T150000123Z_0123456789abcdef0123456789abcdef")
    assert not preparer.re_run_id("bad")


def complete_for_validator(fixture, report):
    temporary, root, run_id, report_dir, running, _command, _items, _resolve = fixture
    completed = root / ".agent/commands/completed" / running.name
    completed.parent.mkdir(parents=True, exist_ok=True)
    running.replace(completed)
    dump(report_dir / "status.json", {"ok": True, "running": False, "run_id": run_id})
    dump(report_dir / "report.json", report)
    (report_dir / "run.log").write_text("bridge_started\nbridge_finished ok=True\n", encoding="utf-8")
    return temporary, root, run_id, report_dir


def test_validator_accepts_complete_read_only_runtime_evidence() -> None:
    fixture, report = execute_fixture(True)
    temporary, root, run_id, report_dir = complete_for_validator(fixture, report)
    try:
        result, failures = validator.validate(root, run_id)
        assert not failures, failures
        assert result["ok"]
        assert result["classification"] == "DIRECT_END_SETTER_EXPOSED_PERSISTENCE_ROLLBACK_UNPROVEN"
        assert result["mutation_authorized"] is False
    finally:
        temporary.cleanup()


def test_validator_rejects_any_reported_mutation() -> None:
    fixture, report = execute_fixture(True)
    report["effective_mutation_count"] = 1
    temporary, root, run_id, _report_dir = complete_for_validator(fixture, report)
    try:
        result, failures = validator.validate(root, run_id)
        assert failures
        assert "report_contract" in failures
        assert not result["ok"]
    finally:
        temporary.cleanup()
