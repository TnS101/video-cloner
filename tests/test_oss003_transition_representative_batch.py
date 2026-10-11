from pathlib import Path

import pytest

from resolve_workspace.modules import oss003_transition_representative_batch as runtime


class Input:
    def __init__(self):
        self.connected = None
        self.keys = {}

    def GetConnectedOutput(self): return self.connected
    def __setitem__(self, frame, value): self.keys[int(frame)] = float(value)
    def __getitem__(self, frame): return self.keys.get(int(frame), 0.0)


class Tool:
    def __init__(self, regid, name):
        self.regid, self.name = regid, name
        self.inputs = {key: Input() for key in ("Input", "XBlurSize", "YBlurSize")}

    def GetAttrs(self): return {"TOOLS_RegID": self.regid, "TOOLS_Name": self.name}
    def SetAttrs(self, attrs): self.name = attrs["TOOLS_Name"]
    def FindInput(self, name): return self.inputs.get(name)
    def FindMainOutput(self, _index): return self
    def ConnectInput(self, name, output): self.inputs[name].connected = output; return True
    def AddModifier(self, name, _kind): self.inputs[name].connected = object(); return True
    def GetInput(self, name, frame=None): return self.inputs[name][frame or 0]


class Comp:
    def __init__(self, fail_blur=False):
        self.fail_blur = fail_blur
        self.tools = {1: Tool("MediaIn", "MediaIn1"), 2: Tool("MediaOut", "MediaOut1")}

    def GetToolList(self, _selected): return self.tools
    def AddTool(self, kind, *_args):
        if self.fail_blur: return None
        tool = Tool(kind, kind); self.tools[3] = tool; return tool


class Item:
    def __init__(self, fail_blur=False):
        self.names = []
        self.comp = Comp(fail_blur)

    def GetFusionCompNameList(self): return list(self.names)
    def AddFusionComp(self): self.names.append("Composition 1"); return self.comp
    def RenameFusionCompByName(self, old, new): self.names[self.names.index(old)] = new; return True
    def DeleteFusionCompByName(self, name): self.names.remove(name); return True


def recipes():
    return [
        {"from_shot": 1, "to_shot": 2, "outgoing_frames": 5, "incoming_frames": 6, "intensity": .6474},
        {"from_shot": 3, "to_shot": 4, "outgoing_frames": 5, "incoming_frames": 6, "intensity": .4298},
        {"from_shot": 4, "to_shot": 5, "outgoing_frames": 5, "incoming_frames": 6, "intensity": .2806},
    ]


def test_exact_representative_scope_duration_mapping_and_editable_readback():
    plan = runtime.build_clip_plan(recipes())
    assert list(plan) == [0, 1, 2, 3, 4]
    assert [frame for frame, _ in plan[0]] == [75, 79]
    assert [frame for frame, _ in plan[1]] == [0, 5]
    assert [frame for frame, _ in plan[3]] == [0, 5, 85, 89]
    item, owned = Item(), {}
    stable_timeline = ("cuts", (0, 80, 211, 286, 376, 461, 558, 629), "captions", 112, "audio", "unchanged")
    applied = runtime._apply_comp(item, plan[3], "VC_OSS003_BLUR_SHOT_004_test", owned)
    assert applied["readback"]["XBlurSize"] == applied["readback"]["YBlurSize"]
    assert item.names == ["VC_OSS003_BLUR_SHOT_004_test"]
    assert stable_timeline == ("cuts", (0, 80, 211, 286, 376, 461, 558, 629), "captions", 112, "audio", "unchanged")


def test_failure_rolls_back_only_the_owned_fusion_comp(monkeypatch):
    item, owned = Item(fail_blur=True), {}
    with pytest.raises(RuntimeError, match="blur_graph"):
        runtime._apply_comp(item, [(0, .01), (5, 0)], "VC_OSS003_BLUR_SHOT_001_test", owned)
    monkeypatch.setattr(runtime.canary, "_activate_target", lambda project: project)
    monkeypatch.setattr(runtime, "_v1_rows", lambda timeline: [{"item": item}])
    result = runtime._rollback(object(), [owned])
    assert result == {"attempted": 1, "deleted": 1, "remaining_owned": 0, "ok": True}
