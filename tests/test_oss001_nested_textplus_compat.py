from __future__ import annotations

import json

import pytest

from resolve_workspace.modules import oss001_nested_textplus_compat as compat
from scripts.davinci import prepare_oss001_nested_textplus_compat as prepare


class Tool:
    def __init__(self, mismatch=False): self.text = ""; self.mismatch = mismatch
    def SetInput(self, name, value): assert name == "StyledText"; self.text = value; return True
    def GetInput(self, name): assert name == "StyledText"; return "wrong" if self.mismatch and self.text == compat.EDITED_TEXT else self.text


class Comp:
    def __init__(self, tool): self.tool = tool
    def FindTool(self, name): return self.tool if name == "Template" else None


class PoolItem:
    def __init__(self, timeline=None): self.timeline = timeline
    def GetTimeline(self): return self.timeline


class Item:
    def __init__(self, timeline=None, *, track=3, start=100, duration=90, textplus=False, mismatch=False, has_pool_item=None):
        self.timeline, self.track, self.start, self.duration = timeline, track, start, duration
        self.has_pool_item = timeline is not None if has_pool_item is None else has_pool_item
        self.tool = Tool(mismatch) if textplus else None
    def GetFusionCompCount(self): return 1 if self.tool else 0
    def GetFusionCompByIndex(self, index): return Comp(self.tool) if index == 1 and self.tool else None
    def GetTrackTypeAndIndex(self): return "video", self.track
    def GetStart(self): return self.start
    def GetDuration(self): return self.duration
    def GetMediaPoolItem(self): return PoolItem(self.timeline) if self.has_pool_item else None


class Timeline:
    counter = 0
    def __init__(self, name, *, start=0, textplus_missing=False, mismatch=False):
        Timeline.counter += 1
        self.name, self.uid, self.start = name, f"uid-{Timeline.counter}", start
        self.tracks, self.textplus_missing, self.mismatch = {1: []}, textplus_missing, mismatch
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetTrackCount(self, kind): return max(self.tracks) if kind == "video" else 0
    def GetItemListInTrack(self, kind, track): return list(self.tracks.get(track, [])) if kind == "video" else []
    def GetStartFrame(self): return self.start
    def AddTrack(self, kind): assert kind == "video"; self.tracks[max(self.tracks) + 1] = []; return True
    def InsertFusionTitleIntoTimeline(self, name):
        assert name == "Text+"
        if not self.textplus_missing: self.tracks[1].append(Item(textplus=True, mismatch=self.mismatch))
        return self.tracks[1][-1] if self.tracks[1] else None
    def GetMediaPoolItem(self): return PoolItem(self)


class Pool:
    def __init__(self, project, failure=None): self.project, self.failure = project, failure
    def CreateEmptyTimeline(self, name):
        timeline = Timeline(name, textplus_missing=self.failure == "textplus", mismatch=self.failure == "text_mismatch")
        self.project.timelines.append(timeline); return timeline
    def AppendToTimeline(self, rows):
        if self.failure == "append_empty": return []
        source = rows[0]["mediaPoolItem"].timeline
        if self.failure == "inner_missing": source = None
        item = Item(source, has_pool_item=True, track=2 if self.failure == "track" else rows[0]["trackIndex"],
                    start=rows[0]["recordFrame"] + (1 if self.failure == "start" else 0),
                    duration=(rows[0]["endFrame"] - rows[0]["startFrame"]) + (1 if self.failure == "duration" else 0))
        return [item]
    def DeleteTimelines(self, timelines):
        for timeline in timelines:
            if timeline in self.project.timelines: self.project.timelines.remove(timeline)
        return True


class Project:
    def __init__(self, failure=None):
        self.name = "New Project 1"; self.timelines = [Timeline("protected")]; self.current = self.timelines[0]
        self.pool = Pool(self, failure)
    def GetName(self): return self.name
    def GetMediaPool(self): return self.pool
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetCurrentTimeline(self): return self.current
    def SetCurrentTimeline(self, timeline): self.current = timeline; return True


class Manager:
    def __init__(self, project): self.project = project
    def GetCurrentProject(self): return self.project


class Resolve:
    def __init__(self, failure=None): self.project = Project(failure)
    def GetProjectManager(self): return Manager(self.project)
    def GetVersionString(self): return "21.0.1"


def command():
    return {"task": compat.TASK_ID, "mode": compat.MODE, "run_id": "run", "payload": {
        "expected_project": "New Project 1", "source_timeline": compat.SOURCE_TIMELINE,
        "target_timeline": compat.TARGET_TIMELINE, "requested_track": 3,
        "requested_offset": 100, "requested_duration": 90, "cleanup_required": True, "save_project": False}}


def test_exact_route_uses_exclusive_end_frame_and_cleans_up():
    resolve = Resolve()
    result = compat.run(resolve, {"run_id": "run", "command": command()})
    assert result["ok"] is True
    assert result["readback"]["actual"] == {"track_type": "video", "track": 3, "start": 100, "duration": 90}
    assert result["readback"]["end_frame_exclusive"] is True
    assert result["readback"]["edited_styled_text"] == compat.EDITED_TEXT
    assert result["cleanup"]["ok"] is True
    assert [row.GetName() for row in resolve.project.timelines] == ["protected"]


@pytest.mark.parametrize("failure,fragment", [
    ("append_empty", "append_result_count:0"), ("track", "placement_mismatch"),
    ("start", "placement_mismatch"), ("duration", "placement_mismatch"),
    ("inner_missing", "inner_timeline_missing"), ("textplus", "textplus_count:0"),
    ("text_mismatch", "post_placement_styled_text_mismatch"),
])
def test_required_readback_failures_fail_closed(failure, fragment):
    result = compat.run(Resolve(failure), {"run_id": "run", "command": command()})
    assert result["ok"] is False
    assert result["resolve_version"] == "21.0.1"
    assert fragment in result["failures"][0]


def test_missing_source_media_pool_item_fails():
    source, target = Timeline("source"), Timeline("target")
    while target.GetTrackCount("video") < 3: target.AddTrack("video")
    source.GetMediaPoolItem = lambda: None
    with pytest.raises(ValueError, match="source_timeline_media_pool_item_missing"):
        project = Project()
        compat.verify_route(project, Pool(project), source, target)


def test_publisher_creates_one_bounded_pending_command(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    receipt = prepare.publish(tmp_path)
    pending = tmp_path / receipt["command_path"]
    payload = json.loads(pending.read_text(encoding="utf-8"))
    assert payload["module"] == "resolve_workspace/modules/oss001_nested_textplus_compat.py"
    assert payload["payload"]["save_project"] is False
    assert payload["payload"]["cleanup_required"] is True
