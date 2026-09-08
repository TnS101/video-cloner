from __future__ import annotations

import json
from pathlib import Path

from resolve_workspace.modules import video_cloner_phase4b_readonly_preflight as preflight
from resolve_workspace.modules import video_cloner_phase4b_timeline_application as phase4b
from scripts.davinci import prepare_video_cloner_phase4b_readonly_preflight as prepare
from scripts.davinci.validate_video_cloner_phase4b_readonly_preflight import validate

TARGET = "DcJRJtUKScu_standalone_timeline"


def write_fcpxml(root: Path) -> Path:
    video = root / "proxy.mp4"
    video.write_bytes(b"video")
    clips = "".join(f'<asset-clip name="{index}" ref="r2" offset="{start}/24s" start="{start}/24s" duration="{duration}/24s"/>' for index, (start, duration) in enumerate([(index * 61, 61) for index in range(13)] + [(793, 61)], 1))
    path = root / "fixture.fcpxml"
    path.write_text(f'<?xml version="1.0"?><fcpxml version="1.10"><resources><format id="r1" frameDuration="1/24s"/><asset id="r2" hasVideo="1" src="{video.as_uri()}"/></resources><library><event><project name="{TARGET}"><sequence duration="854/24s" format="r1"><spine>{clips}</spine></sequence></project></event></library></fcpxml>', encoding="utf-8")
    return path


class Media:
    def __init__(self, path: Path): self.path = path
    def GetClipProperty(self): return {"File Path": str(self.path)}


class Item:
    def __init__(self, start: int, duration: int, path: Path, zoom: float = 1.0): self.start, self.duration, self.path, self.zoom = start, duration, path, zoom
    def GetName(self): return self.path.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.start + self.duration
    def GetDuration(self): return self.duration
    def GetLeftOffset(self): return self.start
    def GetMediaPoolItem(self): return Media(self.path)
    def GetFusionCompCount(self): return 0
    def GetProperty(self): return {"ZoomX": self.zoom, "ZoomY": 1.0, "PositionX": 0.0, "PositionY": 0.0, "RotationAngle": 0.0, "RetimeSpeed": 100.0}


class Timeline:
    def __init__(self, name: str, items=None): self.name, self.items = name, list(items or [])
    def GetName(self): return self.name
    def GetTrackCount(self, kind: str): return 1 if kind == "video" and self.items else 0
    def GetItemListInTrack(self, kind: str, index: int): return list(self.items) if kind == "video" and index == 1 else []
    def GetStartFrame(self): return 0
    def GetEndFrame(self): return max((item.GetEnd() for item in self.items), default=0)
    def GetSetting(self, key: str): return "24"


def valid_target(fcpxml: Path, zoom: float = 1.0) -> Timeline:
    contract = phase4b.parse_fcpxml_contract(fcpxml)
    source = Path(contract["source_path"])
    return Timeline(TARGET, [Item(row["timeline_start"], row["duration"], source, zoom) for row in contract["clips"]])


class Pool:
    def __init__(self): self.mutation_calls = 0
    def __getattr__(self, name):
        if name.startswith(("Import", "Create", "Delete")):
            def mutate(*args): self.mutation_calls += 1
            return mutate
        raise AttributeError(name)


class Project:
    def __init__(self, timelines): self.timelines, self.pool, self.mutation_calls = list(timelines), Pool(), 0
    def GetName(self): return "Authoritative Project"
    def GetCurrentTimeline(self): return self.timelines[0] if self.timelines else None
    def GetMediaPool(self): return self.pool
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index: int): return self.timelines[index - 1]
    def __getattr__(self, name):
        if name.startswith(("Set", "Create", "Delete", "Import", "Save")):
            def mutate(*args): self.mutation_calls += 1
            return mutate
        raise AttributeError(name)


class Manager:
    def __init__(self, project): self.project = project
    def GetCurrentProject(self): return self.project


class Resolve:
    def __init__(self, project): self.project = project
    def GetProjectManager(self): return Manager(self.project)


def command(fcpxml: Path, run_id="run") -> dict:
    contract = phase4b.parse_fcpxml_contract(fcpxml)
    return {"task": preflight.TASK_ID, "run_id": run_id, "mode": preflight.MODE, "payload": {"action": preflight.ACTION, "read_only": True, "mutation_permitted": False, "fcpxml_path": str(fcpxml), "fcpxml_sha256": phase4b.sha256(fcpxml), "target_timeline_name": TARGET, "expected_clip_count": len(contract["clips"]), "expected_duration_frames": contract["duration_frames"], "expected_fps": contract["fps"]}}


def run(fcpxml: Path, project) -> dict:
    return preflight.run(Resolve(project), {"run_id": "run", "command": command(fcpxml)})


def test_first_import_and_arbitrary_non_target_inventory_are_read_only(tmp_path: Path):
    fcpxml = write_fcpxml(tmp_path)
    project = Project([Timeline("Reel #1"), Timeline("anything"), Timeline("Reel #1")])
    result = run(fcpxml, project)
    assert result["readiness"] == "READY_PHASE4B_FIRST_IMPORT"
    assert result["timeline_names"] == ["Reel #1", "anything", "Reel #1"]
    assert result["duplicate_name_counts"] == {"Reel #1": 2, "anything": 1}
    assert result["non_target_timeline_inventory"] == phase4b.timeline_inventory(project)
    assert project.mutation_calls == project.pool.mutation_calls == 0


def test_one_valid_target_is_ready_for_idempotent_reuse(tmp_path: Path):
    fcpxml = write_fcpxml(tmp_path)
    project = Project([Timeline("arbitrary"), valid_target(fcpxml)])
    result = run(fcpxml, project)
    assert result["readiness"] == "READY_PHASE4B_IDEMPOTENT_REUSE"
    assert result["target_validation"]["ok"] is True
    assert result["target_occurrence_count"] == 1
    assert project.mutation_calls == project.pool.mutation_calls == 0


def test_duplicate_target_is_blocked(tmp_path: Path):
    fcpxml = write_fcpxml(tmp_path)
    result = run(fcpxml, Project([valid_target(fcpxml), valid_target(fcpxml)]))
    assert result["readiness"] == "BLOCKED_PHASE4B_DUPLICATE_TARGET"
    assert result["target_occurrence_count"] == 2


def test_invalid_target_is_blocked(tmp_path: Path):
    fcpxml = write_fcpxml(tmp_path)
    result = run(fcpxml, Project([valid_target(fcpxml, zoom=1.1)]))
    assert result["readiness"] == "BLOCKED_PHASE4B_TARGET_CONTRACT_MISMATCH"
    assert result["target_validation"]["ok"] is False


def test_no_current_project_is_blocked(tmp_path: Path):
    fcpxml = write_fcpxml(tmp_path)
    result = preflight.run(Resolve(None), {"run_id": "run", "command": command(fcpxml)})
    assert result["readiness"] == "BLOCKED_PHASE4B_NO_CURRENT_PROJECT"


def test_prepare_publishes_one_read_only_command_and_validator_accepts_evidence(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    artifact = root / prepare.ARTIFACT
    artifact.parent.mkdir(parents=True)
    fixture = write_fcpxml(tmp_path)
    artifact.write_bytes(fixture.read_bytes())
    source = Path(phase4b.parse_fcpxml_contract(artifact)["source_path"])
    assert source.is_file()
    (root / "AGENTS.md").write_text("test", encoding="utf-8")
    module_path = root / prepare.MODULE
    module_path.parent.mkdir(parents=True)
    module_path.write_text("test", encoding="utf-8")
    monkeypatch.setattr(prepare, "ARTIFACT_SHA256", phase4b.sha256(artifact))
    run_id = "20260902T010203004Z_0123456789abcdef0123456789abcdef"
    receipt = prepare.publish(root, run_id)
    pending = root / receipt["command_path"]
    cmd = json.loads(pending.read_text(encoding="utf-8"))
    assert cmd["payload"]["read_only"] is True and cmd["payload"]["mutation_permitted"] is False
    assert len(list((root / ".agent/commands/pending").glob("*.json"))) == 1
    project = Project([Timeline("Reel #1")])
    report = preflight.run(Resolve(project), {"run_id": run_id, "command": cmd})
    run_dir = root / cmd["payload"]["report_dir"]
    phase4b.write_json(run_dir / "report.json", report)
    phase4b.write_json(run_dir / "status.json", {"ok": True})
    (run_dir / "run.log").write_text("offline fake\n", encoding="utf-8")
    completed = root / ".agent/commands/completed" / pending.name
    pending.replace(completed)
    summary, failures = validate(root, run_id)
    assert failures == []
    assert summary["readiness"] == "READY_PHASE4B_FIRST_IMPORT"
