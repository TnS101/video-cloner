import ast
from pathlib import Path

from resolve_workspace.modules import video_cloner_p006_caption_carrier_probe as probe


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "resolve_workspace/modules/video_cloner_p006_caption_carrier_probe.py"


class Input:
    def __init__(self, identifier, name): self.identifier, self.name = identifier, name
    def GetAttrs(self): return {"INPS_ID": self.identifier, "INPS_Name": self.name, "INPS_DataType": "Number"}


class Tool:
    def __init__(self, reg_id="TextPlus"): self.reg_id = reg_id
    def GetAttrs(self): return {"TOOLS_RegID": self.reg_id, "TOOLS_Name": "Text1"}
    def GetInputList(self): return [Input("StyledText", "Styled Text"), Input("Size", "Size"), Input("Center", "Center")]


class Comp:
    def __init__(self, shape): self.shape = shape
    def GetToolList(self, _selected):
        tool = Tool("TextPlus" if self.shape != "other" else "Text3D")
        return {"Text1": tool} if self.shape == "dict" else [tool]


class Item:
    def __init__(self, shape): self.shape, self.comp = shape, None if shape == "none" else Comp(shape)
    def GetName(self): return "Basic Title"
    def GetStart(self): return 39
    def GetEnd(self): return 44
    def GetDuration(self): return 5
    def GetProperty(self): return {"CompositeMode": 0, "Opacity": 100.0}
    def GetFusionCompCount(self): return 0 if self.comp is None else 1
    def GetFusionCompByIndex(self, index): return self.comp if index == 1 else None
    def GetFusionCompNameList(self): return [] if self.comp is None else ["Composition 1"]
    def GetFusionCompNames(self): return {} if self.comp is None else {"Composition 1": "Composition 1"}
    def GetFusionCompByName(self, name): return self.comp if name == "Composition 1" else None


class Timeline:
    def __init__(self, shape): self.items = [Item(shape)] + [StaticItem(index) for index in range(111)]
    def GetName(self): return "VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B"
    def GetUniqueId(self): return "4aaa91c0-c434-4439-a15a-92ce86e80256"
    def GetTrackCount(self, kind): return 2 if kind == "video" else 1
    def GetItemListInTrack(self, kind, track): return self.items if kind == "video" and track == 2 else []


class StaticItem:
    def __init__(self, index): self.start = 100 + index * 10
    def GetStart(self): return self.start
    def GetEnd(self): return self.start + 5
    def GetDuration(self): return 5


class Project:
    def __init__(self, shape): self.timeline = Timeline(shape)
    def GetName(self): return "New Project 1"
    def GetCurrentTimeline(self): return self.timeline


class Manager:
    def __init__(self, shape): self.project = Project(shape)
    def GetCurrentProject(self): return self.project


class Resolve:
    def __init__(self, shape): self.manager = Manager(shape)
    def GetProjectManager(self): return self.manager


def command():
    payload = {
        "action": probe.ACTION, "read_only": True, "zero_mutation": True,
        "project_mutation_permitted": False, "timeline_mutation_permitted": False,
        "caption_mutation_permitted": False, "fusion_mutation_permitted": False,
        "save_project": False, "delete_permitted": False, "replace_permitted": False,
        "retry_permitted": False, "expected_project": "New Project 1",
        "target_timeline_name": "VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B",
        "target_timeline_uid": "4aaa91c0-c434-4439-a15a-92ce86e80256",
        "expected_caption_count": 112, "caption_track_index": 2,
        "caption_start": 39, "caption_end": 44, "caption_duration": 5,
    }
    return {"task": probe.TASK_ID, "run_id": "run", "mode": probe.MODE, "payload": payload}


def execute(shape):
    return probe.run(Resolve(shape), {"run_id": "run", "command": command()})


def test_classifies_no_fusion_comp_without_mutation():
    result = execute("none")
    assert result["ok"] is True
    assert result["classification"] == "CASE_A_NO_FUSION_COMP"
    assert result["caption_geometry_unchanged"] is True
    assert result["mutation_counts"] == probe.MUTATION_COUNTS


def test_inventories_dict_textplus_and_list_other_carriers():
    textplus = execute("dict")
    assert textplus["classification"] == "CASE_B_FUSION_COMP_TEXTPLUS_DISCOVERED"
    assert textplus["compositions"][0]["tool_collection"]["type"] == "dict"
    assert [row["id"] for row in textplus["compositions"][0]["tools"][0]["inputs"]] == ["StyledText", "Size", "Center"]
    other = execute("other")
    assert other["classification"] == "CASE_C_DIFFERENT_CARRIER"
    assert other["compositions"][0]["tool_collection"]["type"] == "list"


def test_read_only_authority_fails_closed_before_resolve_access():
    bad = command()
    bad["payload"]["save_project"] = True
    result = probe.run(object(), {"run_id": "run", "command": bad})
    assert result["failures"] == ["ValueError: read_only_authority"]


def test_crash_state_check_proves_clean_baseline_read_only():
    cmd = command()
    cmd["payload"].update({
        "crash_state_check": True,
        "expected_video_track_count": 2,
        "expected_selected_caption_count": 1,
        "selected_geometries": [[39, 44, 5]],
    })
    result = probe.run(Resolve("none"), {"run_id": "run", "command": cmd})
    assert result["crash_state"]["classification"] == "CRASH_STATE_CLEAN"
    assert result["crash_state"]["selected_captions"][0]["opacity"] == 100.0
    assert result["mutation_counts"] == probe.MUTATION_COUNTS


def test_source_has_no_prohibited_mutation_surface():
    prohibited = {"AddFusionComp", "AddTool", "AddModifier", "SetInput", "SetProperty", "DeleteClips", "SaveProject", "SetCurrentTimeline"}
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not prohibited & (called | literals)
