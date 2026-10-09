from __future__ import annotations

import importlib.util
import json
import os
import re
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
        value = self.inputs[name][frame]
        if value is None and self.inputs[name].connected is None:
            return self.inputs[name][0]
        return value


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


def test_scale_pop_uses_the_persistent_size_modifier():
    tool = FakeTool()
    result = MODULE.apply_authorized_animation(
        FakeComp(), tool,
        payload("Size", "scale_pop", [
            {"frame": 0, "relative_time": 0.0, "value": 0.2},
            {"frame": 1, "relative_time": 0.5, "value": 0.3},
            {"frame": 2, "relative_time": 1.0, "value": 0.25},
        ]),
        3,
    )
    assert result["modified"] is True
    assert tool.modifier_calls == [("Size", "BezierSpline")]


def test_command_bound_reel3_run_accepts_112_geometry_bound_captions(tmp_path, monkeypatch):
    class Item:
        def __init__(self, start, end):
            self.start, self.end = start, end
            self.comp = FakeComp()
            self.tool = FakeTool(names=("Center", "Size", "StyledText", "Font", "Style"))
            self.tool.inputs["Size"].values[0] = 0.25
            self.tool.inputs["Center"].values[0] = [0.5, 0.5]
            self.tool.inputs["StyledText"].values[0] = f"caption-{start}"
            self.tool.inputs["Font"].values[0] = "Arial"
            self.tool.inputs["Style"].values[0] = "Bold"
            self.comp.GetToolList = lambda *args: {1: self.tool}

        def GetName(self): return "Text"
        def GetStart(self): return self.start
        def GetEnd(self): return self.end
        def GetFusionCompByIndex(self, index): return self.comp

    class Timeline:
        def __init__(self):
            self.items = [Item(i * 5, i * 5 + 5) for i in range(112)]

        def GetName(self): return "REEL3_TARGET"
        def GetUniqueId(self): return "reel3-uid"
        def GetTrackCount(self, kind): return 2 if kind == "video" else 1
        def GetItemListInTrack(self, kind, index):
            return self.items if kind == "video" and index == 2 else []

    class Project:
        def __init__(self, timeline): self.timeline = timeline
        def GetName(self): return "Project"
        def GetCurrentTimeline(self): return self.timeline

    class Manager:
        def __init__(self, project): self.project = project; self.saves = 0
        def GetCurrentProject(self): return self.project
        def SaveProject(self): self.saves += 1; return True

    class Resolve:
        def __init__(self, manager): self.manager = manager
        def GetProjectManager(self): return self.manager

    plan = {
        "ok": True,
        "plan_hash": "hash",
        "summary": {"v3_item_count": 112},
        "items": [{
            "cue_id": "sub_001",
            "name": "VC_TEXTPLUS_0001_sub_001",
            "start_frame": 0,
            "end_frame": 5,
            "duration_frames": 5,
            "selected": True,
            "animation": {
                "source_event_id": "style_event_1",
                "animation_type": "scale",
                "keyframes": [
                    {"frame": 0, "relative_time": 0.0, "size_multiplier": 0.8},
                    {"frame": 4, "relative_time": 1.0, "size_multiplier": 1.0},
                ],
            },
        }],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(MODULE, "PROJECT_ROOT", tmp_path)
    timeline = Timeline()
    manager = Manager(Project(timeline))
    context = {"command": {"payload": {
        "video_id": "DZatr0EJt4B",
        "expected_project": "Project",
        "target_timeline_name": "REEL3_TARGET",
        "target_timeline_uid": "reel3-uid",
        "animation_plan_path": "plan.json",
        "expected_caption_count": 112,
        "caption_track_index": 2,
        "apply_caption_animation": True,
        "regenerate_captions": False,
        "save_project": True,
    }}}
    resolve = Resolve(manager)
    result = MODULE.run(resolve, context)
    assert result["selected_caption_count"] == 1
    assert result["animation_family_counts"] == {"scale": 1}
    assert result["static_untouched_count"] == 111
    assert result["caption_identity_preserved"] is True
    assert manager.saves == 1
    assert timeline.items[0].tool.modifier_calls == [("Size", "BezierSpline")]
    assert all(item.tool.modifier_calls == [] for item in timeline.items[1:])
    second = MODULE.run(resolve, context)
    assert second["modified_count"] == 0
    assert second["already_correct_count"] == 1
    assert manager.saves == 2
    assert timeline.items[0].tool.modifier_calls == [("Size", "BezierSpline")]


def test_runtime_has_no_reel1_or_fixed_116_execution_assumption():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "DZsqH7auhjt" not in source
    assert "EXPECTED_V3_COUNT" not in source


def test_basic_title_static_contract_maps_to_textplus_without_changing_text_or_timing(tmp_path):
    fcpxml = tmp_path / "captions.fcpxml"
    fcpxml.write_text(
        '<fcpxml><library><event><project><sequence><spine>'
        '<title name="VC Caption 0008 - this"><text><text-style ref="ts8">this</text-style></text>'
        '<text-style-def id="ts8"><text-style font="Arial" fontSize="74" '
        'fontColor="0.98 0.97 0.96 1" bold="1" strokeColor="0 0 0 1" '
        'strokeWidth="4" shadowColor="0 0 0 0.625" shadowOffset="2"/>'
        '</text-style-def></title></spine></sequence></project></event></library></fcpxml>',
        encoding="utf-8",
    )
    selected = [{"cue_id": "sub_008", "text": "this", "start_frame": 39, "end_frame": 44}]
    style = MODULE._carrier_static_styles(fcpxml, selected, 1080)["sub_008"]
    assert style["text"] == "this"
    assert style["Font"] == "Arial" and style["Style"] == "Bold"
    assert style["Size"] == pytest.approx(74 / 1080 * 1.5)
    assert style["Center"] == [0.5, 0.5]
    assert style["Enabled2"] == 1.0 and style["Enabled3"] == 1.0
    assert selected[0]["start_frame"] == 39 and selected[0]["end_frame"] == 44


def test_carrier_fallback_requires_explicit_owned_rollback_authority():
    with pytest.raises(ValueError, match="carrier_rollback_not_authorized"):
        MODULE._required_payload({"command": {"payload": {
            "video_id": "DZatr0EJt4B", "target_timeline_name": "target",
            "target_timeline_uid": "uid", "animation_plan_path": "plan.json",
            "expected_caption_count": 112, "caption_track_index": 2,
            "apply_caption_animation": True, "regenerate_captions": False,
            "carrier_fallback": True, "static_fcpxml_path": "captions.fcpxml",
            "frame_width": 1080, "carrier_track_index": 3,
        }}})


class VisibilityGatedTextPlus:
    def __init__(self):
        self.values = {
            "StyledText": "", "Font": "", "Style": "", "Size": 0.1, "Center": [0.5, 0.5],
            "Enabled1": 0.0, "Red1": 0.0, "Green1": 0.0, "Blue1": 0.0, "Alpha1": 0.0,
            "Enabled2": 0.0, "Enabled3": 0.0,
        }
        self.writes = []

    @staticmethod
    def element(name):
        match = re.search(r"([23])$", name)
        return int(match.group(1)) if match else None

    def SetInput(self, name, value):
        element = self.element(name)
        if element and not name.startswith("Enabled") and not self.values[f"Enabled{element}"]:
            return False
        self.values[name] = value
        self.writes.append((name, value))
        return True

    def GetInput(self, name, *_args):
        element = self.element(name)
        if element and not name.startswith("Enabled") and not self.values[f"Enabled{element}"]:
            return None
        return self.values.get(name)


def static_style():
    return {
        "text": "this", "Font": "Arial", "Style": "Bold", "Size": 0.1, "Center": [0.5, 0.5],
        "Enabled1": 1.0, "Red1": 1.0, "Green1": 1.0, "Blue1": 1.0, "Alpha1": 1.0,
        "Enabled2": 1.0, "ElementShape2": 1.0, "Red2": 0.0, "Green2": 0.0, "Blue2": 0.0,
        "Alpha2": 1.0, "Thickness2": 0.05, "OutsideOnly2": 1.0,
        "Enabled3": 1.0, "ElementShape3": 0.0, "Red3": 0.0, "Green3": 0.0, "Blue3": 0.0,
        "Alpha3": 0.625, "Offset3": [0.003, 0.003],
    }


def test_visibility_gated_element_shape_is_enabled_then_strictly_verified():
    tool = VisibilityGatedTextPlus()
    MODULE._apply_static_style(tool, static_style())
    assert tool.writes.index(("Enabled2", 1.0)) < tool.writes.index(("ElementShape2", 1.0))
    assert tool.values["ElementShape2"] == 1.0


def test_static_scalar_mismatch_and_unknown_input_remain_fatal():
    class Mismatch(VisibilityGatedTextPlus):
        def GetInput(self, name, *_args):
            return 0.25 if name == "Red1" else super().GetInput(name, *_args)

    with pytest.raises(RuntimeError, match="caption_static_readback:Red1"):
        MODULE._apply_static_style(Mismatch(), static_style())
    class RejectUnknown(VisibilityGatedTextPlus):
        def SetInput(self, name, value):
            return False if name == "Unknown" else super().SetInput(name, value)
    with pytest.raises(RuntimeError, match="caption_static_readback:Unknown"):
        MODULE._set_static_input(RejectUnknown(), "Unknown", 1.0)


def test_carrier_failure_rolls_back_owned_item_and_track(monkeypatch):
    class Timeline:
        def __init__(self): self.carriers = []; self.deleted = []; self.deleted_track = None
        def GetTrackCount(self, _kind): return 2
        def DeleteClips(self, items, _ripple): self.deleted.extend(items); self.carriers.clear(); return True
        def DeleteTrack(self, _kind, track): self.deleted_track = track; return True

    class Project:
        def GetMediaPool(self): return object()

    timeline, source_item, carrier = Timeline(), object(), object()
    monkeypatch.setattr(MODULE, "get_fusion_comp", lambda _item: None)
    monkeypatch.setattr(MODULE, "_repository_path", lambda _path: Path("x"))
    monkeypatch.setattr(MODULE, "_carrier_static_styles", lambda *_: {"sub_008": static_style()})
    monkeypatch.setattr(MODULE, "_item_opacity", lambda _item: 100.0)
    monkeypatch.setattr(MODULE, "_find_carrier_source", lambda *_: {"media_pool_item": object(), "source_start": 0})
    monkeypatch.setattr(MODULE, "_ensure_carrier_track", lambda *_: True)
    monkeypatch.setattr(MODULE, "_append_carrier", lambda *_: timeline.carriers.append(carrier) or carrier)
    monkeypatch.setattr(MODULE, "_create_textplus", lambda _item: (object(), object()))
    monkeypatch.setattr(MODULE, "_apply_static_style", lambda *_: (_ for _ in ()).throw(RuntimeError("style")))
    monkeypatch.setattr(MODULE, "_caption_items", lambda _timeline, track: timeline.carriers if track == 3 else [])
    monkeypatch.setattr(MODULE, "_set_item_opacity", lambda *_: None)
    row = {"cue_id": "sub_008", "text": "this", "name": "VC_TEXTPLUS_0008_sub_008", "duration_frames": 5, "start_frame": 39, "end_frame": 44}
    payload = {"static_fcpxml_path": "x", "frame_width": 1080, "carrier_track_index": 3}
    with pytest.raises(RuntimeError, match="style"):
        MODULE._run_carrier_fallback(Project(), timeline, payload, [row], [(row, source_item)])
    assert timeline.deleted == [carrier]
    assert timeline.deleted_track == 3


def test_carrier_preflight_failure_occurs_before_track_or_item_mutation(monkeypatch):
    mutations = []
    monkeypatch.setattr(MODULE, "get_fusion_comp", lambda _item: None)
    monkeypatch.setattr(MODULE, "_repository_path", lambda _path: Path("x"))
    monkeypatch.setattr(MODULE, "_carrier_static_styles", lambda *_: (_ for _ in ()).throw(ValueError("static_contract")))
    monkeypatch.setattr(MODULE, "_ensure_carrier_track", lambda *_: mutations.append("track"))
    row = {"cue_id": "sub_008", "text": "this", "duration_frames": 5}
    with pytest.raises(ValueError, match="static_contract"):
        MODULE._run_carrier_fallback(
            object(), object(),
            {"static_fcpxml_path": "x", "frame_width": 1080, "carrier_track_index": 3},
            [row], [(row, object())],
        )
    assert mutations == []
