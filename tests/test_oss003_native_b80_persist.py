import hashlib
import inspect
from pathlib import Path

from resolve_workspace.modules import oss003_native_b80_persist as persist


PATCHED = Path(".agent/reports/OSS003_NATIVE_BOUNDARY80_TRANSITION_V1/20261011T122841727Z_865b583a4be84ab69e7e9ab6955d0ce3/native_b80_patched.drt")


def test_reuses_exact_patched_native_transition():
    result = persist.validate_patched_drt(PATCHED)
    assert hashlib.sha256(PATCHED.read_bytes()).hexdigest() == persist.PATCHED_SHA256
    assert result == {
        "sha256": persist.PATCHED_SHA256,
        "entry": "SeqContainer/12d104aa-23eb-4780-bf08-f844b1cfa86b.xml",
        "container_uuid": "12d104aa-23eb-4780-bf08-f844b1cfa86b",
        "name": "Cross Dissolve", "start": 75, "end": 86, "duration": 11, "cut": 80, "count": 1,
    }


def test_execution_path_has_no_fusion_or_timeline_deletion():
    source = inspect.getsource(persist)
    assert "DeleteFusionCompByName" not in source
    assert "DeleteTool" not in source
    assert "DeleteTimelines" not in source


class Timeline:
    def __init__(self, name, uid, items=()): self.name, self.uid, self.items = name, uid, list(items)
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetStartFrame(self): return 0
    def GetItemListInTrack(self, *_): return self.items


class Pool:
    def __init__(self, proof): self.proof = proof
    def ImportTimelineFromFile(self, _): return self.proof


class Project:
    def __init__(self, production, proof): self.timelines, self.current, self.pool = [production], production, Pool(proof)
    def GetName(self): return persist.rep.EXPECTED_PROJECT
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetMediaPool(self): return self.pool
    def SetCurrentTimeline(self, timeline):
        if timeline not in self.timelines: self.timelines.append(timeline)
        self.current = timeline
        return True
    def GetCurrentTimeline(self): return self.current


class Manager:
    def __init__(self, project): self.project, self.save_calls = project, 0
    def GetCurrentProject(self): return self.project
    def SaveProject(self): self.save_calls += 1; return True


class Resolve:
    def __init__(self, manager): self.manager = manager
    def GetVersionString(self): return persist.rep.EXPECTED_RESOLVE_VERSION
    def GetProjectManager(self): return self.manager


def test_readback_failure_retains_import_and_leaves_it_current():
    production = Timeline(persist.rep.EXPECTED_TIMELINE, persist.rep.EXPECTED_TIMELINE_UID)
    proof = Timeline(persist.PROOF_NAME, "proof-uid")
    project = Project(production, proof)
    manager = Manager(project)
    module_path = Path(persist.__file__).resolve()
    command = {
        "task": persist.TASK_ID, "mode": persist.MODE, "run_id": "test-run", "report_path": "unused/report.json",
        "payload": {
            "repository_root": str(Path.cwd()),
            "expected_project": persist.rep.EXPECTED_PROJECT, "production_timeline": persist.rep.EXPECTED_TIMELINE,
            "production_uid": persist.rep.EXPECTED_TIMELINE_UID, "proof_timeline": persist.PROOF_NAME,
            "boundary_relative": 80, "duration_frames": 11, "patched_drt_path": str(PATCHED.resolve()),
            "patched_drt_sha256": persist.PATCHED_SHA256, "top_level_container": persist.TOP_LEVEL_CONTAINER,
            "retain_after_import": True, "save_after_readback": True,
            "module_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
        },
    }
    result = persist.run(Resolve(manager), {"run_id": "test-run", "command": command})
    assert result["outcome"] == "OSS003_NATIVE_B80_IMPORTED_NEEDS_HUMAN_REVIEW"
    assert result["proof_retained"] is True
    assert project.current is proof and proof in project.timelines
    assert manager.save_calls == 0
