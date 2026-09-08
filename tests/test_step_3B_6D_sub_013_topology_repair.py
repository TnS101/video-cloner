from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace/modules/step_3B_6D_sub_013_topology_repair.py"
PREPARER = ROOT / "scripts/davinci/prepare_step_3B_6D_sub_013_topology_repair_command.py"
VALIDATOR = ROOT / "scripts/davinci/validate_step_3B_6D_sub_013_topology_repair.py"


def load_module():
    spec = importlib.util.spec_from_file_location("topology_repair", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeOutput:
    def __init__(self, property_name: str):
        self.property_name = property_name

    def GetAttrs(self) -> dict[str, Any]:
        if self.property_name == "Center":
            return {"OUTS_Name": "Position", "OUTS_DataType": "Point", "OUTS_ID": "Position"}
        return {"OUTS_Name": "Value", "OUTS_DataType": "Number", "OUTS_ID": "Value"}


class FakeInput:
    def __init__(self, property_name: str, values: dict[float, Any]):
        self.property_name = property_name
        self.values = dict(values)
        self.assignments: list[tuple[float, Any]] = []

    def GetAttrs(self) -> dict[str, Any]:
        return {
            "INPS_ID": self.property_name,
            "INPS_DataType": "Point" if self.property_name == "Center" else "Number",
            "INPB_Connected": True,
        }

    def GetConnectedOutput(self) -> FakeOutput:
        return FakeOutput(self.property_name)

    def GetKeyFrames(self) -> dict[int, float]:
        return {index: time for index, time in enumerate(sorted(self.values), start=1)}

    def __getitem__(self, time: float | int) -> Any:
        return self.values[float(time)]

    def __setitem__(self, time: float | int, value: Any) -> None:
        normalized = float(time)
        self.assignments.append((normalized, value))
        if value is None:
            del self.values[normalized]
        else:
            self.values[normalized] = value


class FakeTool:
    def __init__(self, inputs: dict[str, FakeInput]):
        self.inputs = inputs

    def FindInput(self, property_name: str) -> FakeInput | None:
        return self.inputs.get(property_name)


def topology(property_name: str, keys: dict[str, float]) -> dict[str, Any]:
    return {
        "input": {
            "INPS_ID": property_name,
            "INPS_DataType": "Point" if property_name == "Center" else "Number",
            "INPB_Connected": True,
        },
        "modifier_connected": True,
        "modifier": {
            "OUTS_Name": "Position" if property_name == "Center" else "Value",
            "OUTS_DataType": "Point" if property_name == "Center" else "Number",
            "OUTS_ID": "Position" if property_name == "Center" else "Value",
        },
        "raw_keyframe_structure": keys,
    }


def test_runtime_authorizes_only_two_time_two_key_deletions():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "input_obj[EXTRA_KEY_TIME] = None" in source
    assert 'REPAIR_PROPERTIES = ("Center", "Size")' in source
    assert 'EXTRA_KEY_TIME = 2.0' in source
    for forbidden in (
        "SaveProject",
        "DeleteModifier",
        "AddModifier",
        "Disconnect",
        "ConnectTo",
        "SetInput",
    ):
        assert forbidden not in source
    assert '"value_setter_call_count": 0' in source
    assert '"key_delete_call_count": 0' in source


def test_delete_extra_key_removes_only_time_two_and_preserves_retained_values():
    module = load_module()
    values = {
        0.0: 0.1,
        1.0: 0.2,
        2.0: 0.25,
        3.0: 0.3,
        4.0: 0.4,
    }
    fake_input = FakeInput("Size", values)
    tool = FakeTool({"Size": fake_input})
    before = topology("Size", {"1": 0.0, "2": 1.0, "3": 2.0, "4": 3.0, "5": 4.0})
    after = topology("Size", {"1": 0.0, "2": 1.0, "3": 3.0, "4": 4.0})

    journal = module.delete_extra_key(tool, "Size", before, after)

    assert fake_input.assignments == [(2.0, None)]
    assert sorted(fake_input.values) == [0.0, 1.0, 3.0, 4.0]
    assert journal["deleted_time"] == 2.0
    assert journal["retained_values_unchanged"] is True
    assert journal["before_topology"] == before
    assert journal["after_topology"] == after


def test_topology_evidence_requires_exact_two_extra_sub_013_keys_only():
    module = load_module()
    expected: dict[str, Any] = {}
    current: dict[str, Any] = {}
    for cue_id in module.TARGETS:
        expected[cue_id] = {}
        current[cue_id] = {}
        for property_name in module.REPAIR_PROPERTIES:
            normal = topology(property_name, {"1": 0.0, "2": 1.0, "3": 3.0, "4": 4.0})
            expected[cue_id][property_name] = normal
            if cue_id == "sub_013":
                current[cue_id][property_name] = topology(
                    property_name,
                    {"1": 0.0, "2": 1.0, "3": 2.0, "4": 3.0, "5": 4.0},
                )
            else:
                current[cue_id][property_name] = normal
    document = {"ok": False, "v3_candidate_count": 116, "current": current, "expected": expected}

    actual_current, actual_expected = module.validate_topology_evidence(document)

    assert actual_current == current
    assert actual_expected == expected


def test_address_resolved_classification_uses_raw_identifier_two_at_time_one():
    module = load_module()
    center = FakeInput(
        "Center",
        {
            1.0: {1: 0.50611111, 2: 0.5284375, 3: 0.0},
            2.0: {1: 0.506203705, 2: 0.52842448, 3: 0.0},
        },
    )
    size = FakeInput("Size", {1.0: 0.087467395905, 2.0: 0.08768857685550001})
    tools = {"sub_013": FakeTool({"Center": center, "Size": size})}
    rows = [
        {
            "plan_operation_index": 6,
            "cue_id": "sub_013",
            "property": "Center",
            "local_frame": 2,
            "timeline_frame": 226,
            "target_value": [0.50611111, 0.5284375],
        },
        {
            "plan_operation_index": 11,
            "cue_id": "sub_013",
            "property": "Size",
            "local_frame": 2,
            "timeline_frame": 226,
            "target_value": 0.087467395905,
        },
    ]
    addresses = {
        ("sub_013", "Center", 2): {
            "raw_key_identifier": 2,
            "raw_value": 1.0,
            "modifier_local_frame": 2,
            "mapping_ambiguous": False,
        },
        ("sub_013", "Size", 2): {
            "raw_key_identifier": 2,
            "raw_value": 1.0,
            "modifier_local_frame": 2,
            "mapping_ambiguous": False,
        },
    }

    result = module.classify_address_resolved(tools, rows, addresses)

    assert all(item["classification"] == "CURRENT_TARGET" for item in result)
    assert all(item["addressing"] == "capture_raw_key_identity" for item in result)
    assert {(item["raw_key_identifier"], item["raw_time"]) for item in result} == {(2, 1.0)}


def test_preparer_allocates_after_hash_lifecycle_and_conflict_checks():
    source = PREPARER.read_text(encoding="utf-8")
    allocation = source.index("run_id = allocate_run_id()")
    assert source.index("validate_hashes(root)") < allocation
    assert source.index("validate_resume_failure(root, queue_root)") < allocation
    assert source.index("validate_no_conflicts(root, queue_root)") < allocation
    assert "7273e9cd9f2353de299550fb514bbdaa35135541ae93db1b1155f9b5b6be8e42" in source
    assert "MANUAL_ACTION_REQUIRED: run Workspace > Scripts > VC_Agent_Bridge exactly once" in source


def test_validator_requires_restored_topology_and_blocks_step_3B_6D_acceptance():
    source = VALIDATOR.read_text(encoding="utf-8")
    assert 'report.get("key_delete_call_count") != 2' in source
    assert 'direct.get("current_target") != 34' in source
    assert 'resolved.get("current_target") != 36' in source
    assert '"BLOCKED_PENDING_CLOUD_REVIEW"' in source
    assert "TOPOLOGY_RESTORED — STEP_3B_6D_DIRECT_FRAME_ACCEPTANCE_REQUIRES_CLOUD_REVIEW" in source
