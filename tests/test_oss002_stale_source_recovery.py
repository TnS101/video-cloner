from __future__ import annotations

import json
from pathlib import Path

import pytest

from resolve_workspace.modules import oss002_stale_source_recovery as recovery
from scripts.davinci import prepare_oss002_stale_source_recovery as prepare


class Timeline:
    def __init__(self, name, uid): self.name, self.uid = name, uid
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid


class Pool:
    def __init__(self, project, delete=True): self.project, self.delete = project, delete
    def DeleteTimelines(self, timelines):
        if not self.delete: return False
        self.project.timelines = [row for row in self.project.timelines if row not in timelines]
        self.project.deleted.extend(timelines)
        return True


class Project:
    def __init__(self, stale_count=1, stale_uid="uid-stale", delete=True):
        self.name = recovery.PROJECT_NAME
        self.target = Timeline(recovery.TARGET_TIMELINE, "uid-production")
        self.timelines = [self.target, Timeline("other", "uid-other")]
        self.timelines.extend(Timeline(recovery.STALE_TIMELINE, stale_uid) for _ in range(stale_count))
        self.current = self.timelines[-1]
        self.deleted = []
        self.pool = Pool(self, delete=delete)
    def GetName(self): return self.name
    def GetMediaPool(self): return self.pool
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def SetCurrentTimeline(self, timeline): self.current = timeline; return True
    def GetCurrentTimeline(self): return self.current


class Manager:
    def __init__(self, project): self.project, self.save_count = project, 0
    def GetCurrentProject(self): return self.project
    def SaveProject(self): self.save_count += 1; return True


class Resolve:
    def __init__(self, project): self.manager = Manager(project)
    def GetVersionString(self): return recovery.EXPECTED_RESOLVE_VERSION
    def GetProjectManager(self): return self.manager


def command():
    return {
        "task": recovery.TASK_ID,
        "mode": recovery.MODE,
        "run_id": "run",
        "payload": {
            "expected_project": recovery.PROJECT_NAME,
            "target_timeline": recovery.TARGET_TIMELINE,
            "stale_timeline": recovery.STALE_TIMELINE,
            "save_after_verified_deletion": True,
        },
    }


def run(project):
    resolve = Resolve(project)
    return recovery.run(resolve, {"run_id": "run", "command": command()}), resolve


def test_deletes_only_unique_stale_timeline_and_saves_verified_inventory():
    project = Project()
    result, resolve = run(project)
    assert result["ok"] is True
    assert result["deleted_timeline"] == {"name": recovery.STALE_TIMELINE, "unique_id": "uid-stale"}
    assert [row.name for row in project.deleted] == [recovery.STALE_TIMELINE]
    assert [row.name for row in project.timelines] == [recovery.TARGET_TIMELINE, "other"]
    assert project.current is project.target
    assert resolve.manager.save_count == 1
    assert len(result["timeline_inventory_before"]) == 3
    assert len(result["timeline_inventory_after"]) == 2


@pytest.mark.parametrize("stale_count", [0, 2])
def test_rejects_missing_or_ambiguous_stale_timeline_without_mutation(stale_count):
    project = Project(stale_count=stale_count)
    result, resolve = run(project)
    assert result["ok"] is False
    assert result["failures"] == [f"ValueError: stale_timeline_count:{stale_count}"]
    assert project.deleted == []
    assert resolve.manager.save_count == 0


def test_rejects_stale_timeline_with_production_uid():
    project = Project(stale_uid="uid-production")
    result, resolve = run(project)
    assert result["ok"] is False
    assert result["failures"] == ["ValueError: stale_timeline_is_production"]
    assert project.deleted == []
    assert resolve.manager.save_count == 0


def test_failed_delete_is_not_saved():
    project = Project(delete=False)
    result, resolve = run(project)
    assert result["ok"] is False
    assert result["failures"] == ["RuntimeError: stale_timeline_delete"]
    assert resolve.manager.save_count == 0


def test_publisher_emits_one_bounded_recovery_command(tmp_path: Path):
    receipt = prepare.publish(tmp_path)
    payload = json.loads((tmp_path / receipt["command_path"]).read_text(encoding="utf-8"))
    assert payload["task"] == recovery.TASK_ID
    assert payload["payload"] == {
        "expected_project": recovery.PROJECT_NAME,
        "target_timeline": recovery.TARGET_TIMELINE,
        "stale_timeline": recovery.STALE_TIMELINE,
        "save_after_verified_deletion": True,
    }
