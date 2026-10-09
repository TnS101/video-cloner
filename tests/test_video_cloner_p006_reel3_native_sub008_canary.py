import ast
import json
from pathlib import Path

import pytest

from resolve_workspace.modules import video_cloner_p006_reel3_native_sub008_canary as canary


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "resolve_workspace/modules/video_cloner_p006_reel3_native_sub008_canary.py"


class Input:
    def __init__(self, value): self.base, self.values, self.connected = value, {}, None
    def __getitem__(self, frame): return self.values.get(frame, self.base)
    def __setitem__(self, frame, value): self.values[frame] = value
    def GetConnectedOutput(self): return self.connected


class Tool:
    def __init__(self): self.inputs = {"Center": Input([0.5, 0.5])}
    def GetAttrs(self): return {"TOOLS_RegID": "TextPlus"}
    def SetInput(self, name, value, frame=None):
        target = self.inputs.setdefault(name, Input(value))
        if frame is None: target.base = value
        else: target[frame] = value
        return True
    def GetInput(self, name, frame=0): return self.inputs.get(name, Input(None))[frame]
    def FindInput(self, name): return self.inputs.get(name)
    def GetInputList(self): return self.inputs
    def AddModifier(self, name, modifier): self.inputs[name].connected = object(); return modifier == "Path"


class Comp:
    def __init__(self): self.tool = Tool()
    def GetToolList(self, *_args): return {"Text1": self.tool}


class Item:
    def __init__(self, name, start, end, fusion=False):
        self.name, self.start, self.end, self.enabled = name, start, end, True
        self.comp = Comp() if fusion else None
    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.end - self.start
    def GetFusionCompCount(self): return 1 if self.comp else 0
    def GetFusionCompByIndex(self, index): return self.comp if index == 1 else None
    def GetClipEnabled(self): return self.enabled
    def SetClipEnabled(self, value): self.enabled = value; return True


class Timeline:
    def __init__(self):
        self.name, self.uid = "TARGET", "target-uid"
        self.start_frame = 86400
        self.base = [Item("base", self.start_frame, self.start_frame + 600)]
        contract = json.loads((ROOT / ".project_ops/artifacts/P001_LIVE_RESOLVE_ACCEPTANCE/T001/P001_acceptance_fresh_4CE37F9BC61B_import_report.json").read_text(encoding="utf-8"))["structure"]["caption_contract"]
        self.captions = [
            Item("Text", self.start_frame + row["timeline_start_frame"], self.start_frame + row["timeline_end_frame"])
            for row in contract
        ]
        self.titles = []
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetStartFrame(self): return self.start_frame
    def GetTrackCount(self, kind): return 3 if kind == "video" and self.titles else (2 if kind == "video" else 0)
    def GetItemListInTrack(self, kind, track):
        return {1: self.base, 2: self.captions, 3: self.titles}.get(track, []) if kind == "video" else []
    def SetCurrentTimecode(self, value): self.timecode = value; return value == "01:00:01:15"
    def SetMarkInOut(self, start, end, kind): self.marks = (start, end, kind); return self.marks == (39, 43, "video")
    def ClearMarkInOut(self, kind): self.marks = None; return True
    def InsertFusionTitleIntoTimeline(self, name):
        item = Item(name, self.start_frame + 39, self.start_frame + 44, fusion=True); self.titles.append(item); return item
    def DeleteClips(self, items, ripple):
        self.titles = [item for item in self.titles if item not in items]; return True


class Project:
    def __init__(self): self.timeline = Timeline()
    def GetName(self): return "Project"
    def GetTimelineCount(self): return 1
    def GetTimelineByIndex(self, index): return self.timeline
    def GetCurrentTimeline(self): return self.timeline
    def SetCurrentTimeline(self, timeline): return timeline is self.timeline


class Manager:
    def __init__(self): self.project, self.saves = Project(), 0
    def GetCurrentProject(self): return self.project
    def SaveProject(self): self.saves += 1; return True


class Resolve:
    def __init__(self): self.manager = Manager()
    def GetProjectManager(self): return self.manager
    def OpenPage(self, page): return page == "edit"


def command():
    payload = {
        "action": canary.ACTION,
        "caption_cue_ids": ["sub_008"],
        "expected_caption_count": 112,
        "expected_untouched_caption_count": 111,
        "expected_structural_caption_count": 112,
        "target_timeline_only": True,
        "native_textplus_only": True,
        "hide_original_after_verification": True,
        "save_project": False,
        "expected_project": "Project",
        "target_timeline_name": "TARGET",
        "target_timeline_uid": "target-uid",
        "animation_plan_path": "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_animation_plan_step_3C.json",
        "static_fcpxml_path": ".project_ops/artifacts/P001_LIVE_RESOLVE_ACCEPTANCE/T001/P001_acceptance_fresh_4CE37F9BC61B.fcpxml",
        "caption_contract_path": ".project_ops/artifacts/P001_LIVE_RESOLVE_ACCEPTANCE/T001/P001_acceptance_fresh_4CE37F9BC61B_import_report.json",
        "caption_track_index": 2,
        "frame_width": 1080,
        "frame_rate": 24,
    }
    return {"task": canary.TASK_ID, "run_id": "run", "mode": canary.MODE, "payload": payload}


def test_sub008_native_replacement_is_exact_isolated_and_unsaved():
    resolve = Resolve()
    result = canary.run(resolve, {"run_id": "run", "command": command()})
    timeline = resolve.manager.project.timeline
    assert result["ok"] and result["untouched_caption_count"] == 111
    assert result["timeline_item"] == {"name": "Text+", "relative_start": 39, "relative_end": 44, "duration": 5, "fusion_comp_count": 1}
    assert result["textplus"]["styled_text"] == "this"
    assert result["animation"]["keyframes_written"] == 3
    assert timeline.captions[7].enabled is False
    assert all(item.name == "Text" for item in timeline.captions)
    assert timeline.timecode == "01:00:01:15"
    assert all(item.enabled for index, item in enumerate(timeline.captions) if index != 7)
    assert resolve.manager.saves == 0


def test_authority_rejects_broader_scope_before_resolve_access():
    for key, value in (("caption_cue_ids", ["sub_008", "sub_009"]), ("save_project", True), ("target_timeline_only", False)):
        cmd = command(); cmd["payload"][key] = value
        with pytest.raises(ValueError, match="sub008_canary_authority"):
            canary.run(object(), {"run_id": "run", "command": cmd})


def test_returned_item_remains_authoritative_when_diagnostic_lookup_misses(monkeypatch):
    monkeypatch.setattr(canary, "_inventory_tracks_for_item", lambda *_: [])
    result = canary.run(Resolve(), {"run_id": "run", "command": command()})
    assert result["ok"]
    assert result["diagnostic_track_indexes"] == []


def test_successful_rollback_checks_delete_and_proves_item_disappeared():
    timeline = Timeline()
    item = timeline.InsertFusionTitleIntoTimeline("Text+")
    result = canary._rollback_inserted_item(timeline, item)
    assert result["delete_returned"] is True
    assert result["gone"] is True and result["ok"] is True
    assert timeline.titles == []


def test_failed_rollback_is_surfaced(monkeypatch):
    resolve = Resolve()
    timeline = resolve.manager.project.timeline
    timeline.DeleteClips = lambda *_: False
    monkeypatch.setattr(canary.adapter, "_apply_static_style", lambda *_: (_ for _ in ()).throw(RuntimeError("forced")))
    with pytest.raises(RuntimeError, match="sub008_rollback_failed"):
        canary.run(resolve, {"run_id": "run", "command": command()})
    assert len(timeline.titles) == 1


def test_successful_cleanup_is_explicit_after_later_failure(monkeypatch):
    resolve = Resolve()
    timeline = resolve.manager.project.timeline
    monkeypatch.setattr(canary.adapter, "_apply_static_style", lambda *_: (_ for _ in ()).throw(RuntimeError("forced")))
    with pytest.raises(RuntimeError, match="sub008_canary_failed_rollback_verified"):
        canary.run(resolve, {"run_id": "run", "command": command()})
    assert timeline.titles == []


@pytest.mark.parametrize("duplicate", [False, True])
def test_structural_mapping_zero_or_multiple_matches_fails_before_mutation(duplicate):
    resolve = Resolve()
    captions = resolve.manager.project.timeline.captions
    original = captions[7]
    if duplicate:
        captions.append(Item("anything", original.start, original.end))
    else:
        captions.pop(7)
    with pytest.raises(ValueError, match="caption_structural_match:sub_008"):
        canary.run(resolve, {"run_id": "run", "command": command()})
    assert resolve.manager.project.timeline.titles == []


def test_all_112_structural_mappings_are_required_before_mutation():
    resolve = Resolve()
    resolve.manager.project.timeline.captions.pop(50)
    with pytest.raises(ValueError, match="caption_structural_match:sub_051"):
        canary.run(resolve, {"run_id": "run", "command": command()})
    assert resolve.manager.project.timeline.titles == []


def test_rollback_restores_original_visibility_after_post_hide_failure(monkeypatch):
    resolve = Resolve()
    original = resolve.manager.project.timeline.captions[7]
    real_map = canary._structural_caption_map
    calls = {"count": 0}
    def fail_after_hide(*args):
        calls["count"] += 1
        if calls["count"] == 3:
            raise RuntimeError("forced_post_hide")
        return real_map(*args)
    monkeypatch.setattr(canary, "_structural_caption_map", fail_after_hide)
    with pytest.raises(RuntimeError, match="rollback_verified"):
        canary.run(resolve, {"run_id": "run", "command": command()})
    assert original.enabled is True
    assert resolve.manager.project.timeline.titles == []


def test_rollback_surfaces_unrestored_semantic_caption_state(monkeypatch):
    resolve = Resolve()
    changed = resolve.manager.project.timeline.captions[20]
    def mutate_then_fail(*_args):
        changed.start += 1
        changed.end += 1
        raise RuntimeError("forced")
    monkeypatch.setattr(canary.adapter, "_apply_static_style", mutate_then_fail)
    with pytest.raises(RuntimeError, match="semantic_state_restored=False"):
        canary.run(resolve, {"run_id": "run", "command": command()})
    assert resolve.manager.project.timeline.titles == []


def test_source_uses_native_title_and_excludes_killed_or_persistent_routes():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    prohibited = {"AppendToTimeline", "AddFusionComp", "AddTool", "SaveProject", "SetProperty"}
    assert not prohibited & literals
    assert "InsertFusionTitleIntoTimeline" in literals
    assert "SetClipEnabled" in literals
