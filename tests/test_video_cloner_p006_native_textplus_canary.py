import ast
from pathlib import Path

import pytest

from resolve_workspace.modules import video_cloner_p006_native_textplus_canary as canary


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "resolve_workspace/modules/video_cloner_p006_native_textplus_canary.py"


class Input:
    def __init__(self): self.values = {0: [0.5, 0.5]}; self.connected = None
    def __getitem__(self, frame): return self.values.get(frame)
    def __setitem__(self, frame, value): self.values[frame] = value
    def GetConnectedOutput(self): return self.connected


class Tool:
    def __init__(self): self.text = ""; self.center = Input(); self.modifiers = []
    def GetAttrs(self): return {"TOOLS_RegID": "TextPlus"}
    def SetInput(self, name, value, frame=None):
        if name == "StyledText": self.text = value
        elif frame is not None: self.center[frame] = value
        return True
    def GetInput(self, name, frame=0): return self.text if name == "StyledText" else self.center[frame]
    def FindInput(self, name): return self.center if name == "Center" else None
    def GetInputList(self): return {"Center": self.center}
    def AddModifier(self, name, modifier): self.modifiers.append((name, modifier)); self.center.connected = object(); return True


class Comp:
    def __init__(self): self.tool = Tool()
    def GetToolList(self, *_args): return {"Text1": self.tool}


class Item:
    def __init__(self): self.comp = Comp()
    def GetName(self): return "Text+"
    def GetStart(self): return 0
    def GetEnd(self): return 120
    def GetDuration(self): return 120
    def GetProperty(self): return {"Opacity": 100.0}
    def GetFusionCompCount(self): return 1
    def GetFusionCompByIndex(self, index): return self.comp if index == 1 else None


class Timeline:
    def __init__(self, name, uid, insert=True): self.name, self.uid, self.insert = name, uid, insert; self.items = []
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetTrackCount(self, kind): return 1 if kind == "video" else 0
    def GetItemListInTrack(self, kind, track): return list(self.items) if kind == "video" and track == 1 else []
    def SetCurrentTimecode(self, value): self.timecode = value; return True
    def InsertFusionTitleIntoTimeline(self, name):
        if not self.insert: return None
        item = Item(); self.items.append(item); return item


class Pool:
    def __init__(self, project): self.project = project
    def CreateEmptyTimeline(self, name):
        timeline = Timeline(name, "canary-uid", insert=self.project.insert); self.project.timelines.append(timeline); return timeline


class Project:
    def __init__(self, insert=True):
        self.insert = insert; self.target = Timeline("TARGET", "target-uid"); self.timelines = [self.target]; self.current = self.target; self.pool = Pool(self)
    def GetName(self): return "Project"
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetCurrentTimeline(self): return self.current
    def SetCurrentTimeline(self, timeline): self.current = timeline; return True
    def GetMediaPool(self): return self.pool


class Manager:
    def __init__(self, project): self.project = project; self.saves = 0
    def GetCurrentProject(self): return self.project
    def SaveProject(self): self.saves += 1; return True


class Resolve:
    def __init__(self, insert=True): self.project = Project(insert); self.manager = Manager(self.project)
    def GetProjectManager(self): return self.manager
    def OpenPage(self, page): self.page = page; return True


def command():
    payload = {
        "action": canary.ACTION, "temporary_timeline_only": True,
        "target_timeline_mutation_permitted": False, "custom_media_carrier_permitted": False,
        "save_project": False, "cleanup_temporary_timeline": False,
        "expected_project": "Project", "target_timeline_name": "TARGET", "target_timeline_uid": "target-uid",
        "temporary_timeline_name": "_VC_NATIVE_TEXTPLUS_CANARY", "playhead_timecode": "01:00:00:00",
        "styled_text": "VC_NATIVE_TEXTPLUS_CANARY",
    }
    return {"task": canary.TASK_ID, "run_id": "run", "mode": canary.MODE, "payload": payload}


def test_native_title_canary_returns_textplus_and_path_without_save_or_target_change():
    resolve = Resolve()
    result = canary.run(resolve, {"run_id": "run", "command": command()})
    assert result["ok"] and result["target_untouched"]
    assert result["timeline_item"]["fusion_comp_count"] == 1
    assert result["textplus"]["styled_text"] == "VC_NATIVE_TEXTPLUS_CANARY"
    assert result["animation_property"] == "Center" and result["modifier"] == "Path"
    assert resolve.manager.saves == 0
    assert resolve.project.target.items == []


def test_missing_returned_timeline_item_fails_closed_without_save():
    resolve = Resolve(insert=False)
    with pytest.raises(RuntimeError, match="native_textplus_no_returned_timeline_item"):
        canary.run(resolve, {"run_id": "run", "command": command()})
    assert resolve.manager.saves == 0
    assert resolve.project.target.items == []


def test_authority_rejects_save_or_custom_carrier_before_resolve_access():
    for key in ("save_project", "custom_media_carrier_permitted"):
        cmd = command(); cmd["payload"][key] = True
        with pytest.raises(ValueError, match="native_canary_authority"):
            canary.run(object(), {"run_id": "run", "command": cmd})


def test_source_excludes_killed_carrier_and_save_apis():
    prohibited = {"AppendToTimeline", "AddFusionComp", "AddTool", "SaveProject", "SetProperty"}
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not prohibited & (called | literals)
    assert "InsertFusionTitleIntoTimeline" in literals
