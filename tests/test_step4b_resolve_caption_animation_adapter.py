from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "resolve_apply_caption_animation_step_3C.py"
PREVIOUS_AUTORUN = os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN")
os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = "1"
SPEC = importlib.util.spec_from_file_location("step4b_caption_animation", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
try:
    SPEC.loader.exec_module(MODULE)
finally:
    if PREVIOUS_AUTORUN is None:
        os.environ.pop("VC_DISABLE_WORKSPACE_AUTORUN", None)
    else:
        os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = PREVIOUS_AUTORUN


class FakeInput:
    def __init__(self):
        self.connected = None
        self.values = {}

    def GetConnectedOutput(self):
        return self.connected

    def __setitem__(self, frame, value):
        self.values[frame] = value

    def __getitem__(self, frame):
        return self.values.get(frame)


class FakeTool:
    def __init__(self, names=("Center", "Size")):
        self.inputs = {name: FakeInput() for name in names}
        self.modifier_calls = []

    def FindInput(self, name):
        return self.inputs.get(name)

    def AddModifier(self, name, modifier):
        self.modifier_calls.append((name, modifier))
        self.inputs[name].connected = object()
        return True

    def GetInput(self, name, frame):
        return self.inputs[name][frame]


class FakeComp:
    def __init__(self):
        self.locks = 0

    def Lock(self):
        self.locks += 1

    def Unlock(self):
        self.locks -= 1


def payload(prop, source_type, keyframes):
    return {
        "authority": "visual_observed",
        "source_evidence_id": "style_event",
        "source_type": source_type,
        "property": prop,
        "keyframes": keyframes,
    }


def test_we_center_uses_path_and_temporal_modifier_readback():
    tool = FakeTool()
    result = MODULE.apply_authorized_animation(
        FakeComp(), tool,
        payload("Center", "slide", [
            {"frame": 0, "relative_time": 0.0, "value": [-0.0106, 0.0565]},
            {"frame": 2, "relative_time": 1.0, "value": [0.0, 0.0]},
        ]),
        3,
    )
    assert tool.modifier_calls == [("Center", "Path")]
    assert [(row["local_frame"], row["actual"], row["modifier_connected"], row["matched"]) for row in result["readback"]] == [
        (0, [-0.0106, 0.0565], True, True),
        (2, [0.0, 0.0], True, True),
    ]


def test_selling_size_uses_bezier_spline_and_temporal_modifier_readback():
    tool = FakeTool()
    result = MODULE.apply_authorized_animation(
        FakeComp(), tool,
        payload("Size", "scale", [
            {"frame": 0, "relative_time": 0.0, "value": 1.30217657},
            {"frame": 7, "relative_time": 1.0, "value": 1.0},
        ]),
        8,
    )
    assert tool.modifier_calls == [("Size", "BezierSpline")]
    assert [(row["local_frame"], row["actual"], row["modifier_connected"], row["matched"]) for row in result["readback"]] == [
        (0, 1.30217657, True, True),
        (7, 1.0, True, True),
    ]


def test_second_application_is_temporally_verified_without_mutation():
    tool = FakeTool()
    animation = payload("Size", "scale", [
        {"frame": 0, "relative_time": 0.0, "value": 1.30217657},
        {"frame": 7, "relative_time": 1.0, "value": 1.0},
    ])
    MODULE.apply_authorized_animation(FakeComp(), tool, animation, 8)
    second = MODULE.apply_authorized_animation(FakeComp(), tool, animation, 8)
    assert second["already_correct"] is True
    assert second["modified"] is False
    assert second["keyframes_written"] == 0
    assert tool.modifier_calls == [("Size", "BezierSpline")]


def test_static_caption_is_a_zero_mutation_noop():
    tool = FakeTool()
    result = MODULE.apply_authorized_animation(FakeComp(), tool, None, 8)
    assert result == {"ok": True, "selected": False, "modified": False, "keyframes_written": 0, "readback": []}
    assert tool.modifier_calls == []


@pytest.mark.parametrize(
    ("candidate", "duration", "message"),
    [
        (payload("Blend", "fade", [{"frame": 0, "relative_time": 0.0, "value": 0.0}]), 2, "property_or_type"),
        (payload("Size", "scale", []), 2, "keyframes"),
        (payload("Size", "scale", [{"frame": 2, "relative_time": 1.0, "value": 1.0}]), 2, "out_of_range"),
        (payload("Size", "scale", [
            {"frame": 1, "relative_time": 0.0, "value": 1.2},
            {"frame": 0, "relative_time": 1.0, "value": 1.0},
        ]), 2, "keyframe_order"),
        (payload("Size", "scale", [
            {"frame": 0, "relative_time": 0.0, "value": 1.2},
            {"frame": 0, "relative_time": 1.0, "value": 1.0},
        ]), 2, "duplicate_frame_conflict"),
        (payload("Size", "scale", [{"frame": 0, "value": 1.0}]), 2, "keyframe_shape"),
        ({**payload("Size", "scale", [{"frame": 0, "relative_time": 0.0, "value": 1.0}]), "authority": "unresolved"}, 2, "authority"),
    ],
)
def test_invalid_or_unresolved_payload_fails_before_mutation(candidate, duration, message):
    tool = FakeTool()
    with pytest.raises(ValueError, match=message):
        MODULE.apply_authorized_animation(FakeComp(), tool, candidate, duration)
    assert tool.modifier_calls == []


def test_missing_textplus_input_fails_without_modifier_mutation():
    tool = FakeTool(names=("Center",))
    with pytest.raises(RuntimeError, match="input_not_found:Size"):
        MODULE.apply_authorized_animation(
            FakeComp(), tool,
            payload("Size", "scale", [{"frame": 0, "relative_time": 0.0, "value": 1.0}]),
            2,
        )
    assert tool.modifier_calls == []


def test_modifier_connection_failure_fails_without_keyframe_writes():
    class NoConnectTool(FakeTool):
        def AddModifier(self, name, modifier):
            self.modifier_calls.append((name, modifier))
            return False

    tool = NoConnectTool()
    with pytest.raises(RuntimeError, match="modifier_not_connected:Size"):
        MODULE.apply_authorized_animation(
            FakeComp(), tool,
            payload("Size", "scale", [{"frame": 0, "relative_time": 0.0, "value": 1.0}]),
            2,
        )
    assert tool.inputs["Size"].values == {}
