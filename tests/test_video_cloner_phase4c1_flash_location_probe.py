from __future__ import annotations

import json
from pathlib import Path

from resolve_workspace.modules import video_cloner_phase4c1_flash_location_probe as runtime
from scripts.davinci import prepare_video_cloner_phase4c1_flash_location_probe as prepare
from scripts.davinci.validate_video_cloner_phase4c1_flash_location_probe import validate

TARGET = "DcJRJtUKScu_standalone_timeline"
IDENTITY = {"name": "VC_FLASH_001_frame_0596", "start": 594, "end": 598, "duration": 4, "media_pool_item_name": "VC_FLASH_NEUTRAL_RGBA_V4", "fusion_tool_name": "VC_FLASH_BG_001", "alpha_keyframes": [[0, 0.0], [2, 0.75], [3, 0.0]]}


class Tool:
    def __init__(self, name="VC_FLASH_BG_001", policy=True): self.Name, self.policy = name, policy
    def GetAttrs(self): return {"TOOLS_Name": self.Name}
    def GetInput(self, name, frame=None):
        if name in {"TopLeftRed", "TopLeftGreen", "TopLeftBlue"}: return 1.0 if self.policy else 0.5
        return {0: 0.0, 2: 0.75, 3: 0.0}.get(frame) if self.policy else 0.2


class Comp:
    def __init__(self, tool): self.tool = tool
    def GetToolList(self, selected=False): return {self.tool.Name: self.tool}


class Media:
    def __init__(self, name="VC_FLASH_NEUTRAL_RGBA_V4", source="neutral/rgba_%06d.png"): self.name, self.source = name, source
    def GetName(self): return self.name
    def GetClipProperty(self, key=None):
        values = {"File Path": self.source}
        return values if key is None else values.get(key, "")


class Item:
    def __init__(self, name="source.mp4", start=0, duration=10, media="source.mp4", tool=None): self.name, self.start, self.duration, self.media, self.tool = name, start, duration, Media(media, media), tool
    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.start + self.duration
    def GetDuration(self): return self.duration
    def GetMediaPoolItem(self): return self.media
    def GetFusionCompCount(self): return int(self.tool is not None)
    def GetFusionCompByIndex(self, index): return Comp(self.tool) if index == 1 and self.tool is not None else None


class Timeline:
    def __init__(self, name, tracks=None): self.name, self.tracks, self.mutations = name, list(tracks or []), 0
    def GetName(self): return self.name
    def GetTrackCount(self, kind): return len(self.tracks) if kind == "video" else 0
    def GetItemListInTrack(self, kind, index): return list(self.tracks[index - 1]) if kind == "video" and 0 < index <= len(self.tracks) else []
    def __getattr__(self, name):
        if name.startswith(("Set", "Add", "Delete", "Create", "Import", "Append")):
            def mutate(*args, **kwargs): self.mutations += 1
            return mutate
        raise AttributeError(name)


class Project:
    def __init__(self, timelines): self.timelines, self.mutations = list(timelines), 0
    def GetName(self): return "New Project 1"
    def GetCurrentTimeline(self): return self.timelines[0] if self.timelines else None
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def __getattr__(self, name):
        if name.startswith(("Set", "Add", "Delete", "Create", "Import", "Append", "Save")):
            def mutate(*args, **kwargs): self.mutations += 1
            return mutate
        raise AttributeError(name)


class Manager:
    def __init__(self, project): self.project, self.mutations = project, 0
    def GetCurrentProject(self): return self.project
    def __getattr__(self, name):
        if name.startswith(("Set", "Add", "Delete", "Create", "Import", "Append", "Save")):
            def mutate(*args, **kwargs): self.mutations += 1
            return mutate
        raise AttributeError(name)


class Resolve:
    def __init__(self, project): self.manager = Manager(project)
    def GetProjectManager(self): return self.manager


def exact_item(**changes):
    values = {"name": IDENTITY["name"], "start": 594, "duration": 4, "media": IDENTITY["media_pool_item_name"], "tool": Tool()}
    values.update(changes)
    return Item(**values)


def run(timelines):
    project = Project(timelines)
    resolve = Resolve(project)
    command = {"task": runtime.TASK_ID, "run_id": "run", "mode": runtime.MODE, "payload": {"action": runtime.ACTION, "operation_id": "operation", "read_only": True, "mutation_permitted": False, "expected_project_name": "New Project 1", "expected_target_timeline_name": TARGET, "expected_flash_identity": IDENTITY, "expected_flash_identity_sha256": runtime.canonical_sha256(IDENTITY)}}
    result = runtime.run(resolve, {"run_id": "run", "command": command})
    assert project.mutations == resolve.manager.mutations == 0
    assert all(timeline.mutations == 0 for timeline in timelines)
    assert result["mutation_counts"] == runtime.ZERO_MUTATIONS
    return result


def test_exact_carrier_on_expected_target():
    result = run([Timeline(TARGET, [[exact_item()]])])
    assert result["classification"] == "FLASH_EXACT_MATCH_EXPECTED_TARGET"
    assert result["matches"][0]["classification"] == "EXACT_FLASH_MATCH"


def test_exact_carrier_on_other_timeline():
    result = run([Timeline(TARGET), Timeline("other", [[exact_item()]])])
    assert result["classification"] == "FLASH_EXACT_MATCH_OTHER_TIMELINE"


def test_partial_matches_are_not_discarded():
    timelines = [Timeline(TARGET, [[exact_item(name="renamed"), exact_item(start=500), exact_item(media="other"), exact_item(tool=Tool("VC_FLASH_BG_OTHER", False))]])]
    result = run(timelines)
    assert result["classification"] == "FLASH_PARTIAL_MATCH_ONLY"
    assert len(result["matches"]) == 4
    assert all(row["classification"] == "PARTIAL_FLASH_MATCH" for row in result["matches"])


def test_complete_absence_ignores_duration_only():
    result = run([Timeline(TARGET, [[Item(duration=4)]])])
    assert result["classification"] == "FLASH_ABSENT_PROJECT_WIDE"
    assert result["matches"] == []


def test_duplicate_exact_carriers():
    result = run([Timeline(TARGET, [[exact_item()]]), Timeline("other", [[exact_item()]])])
    assert result["classification"] == "FLASH_MULTIPLE_EXACT_MATCHES"


def test_arbitrary_29_like_inventory_and_zero_mutations():
    timelines = [Timeline(TARGET)] + [Timeline(f"protected_{index}") for index in range(28)]
    result = run(timelines)
    assert result["ok"] is True
    assert result["timeline_count"] == len(result["timeline_inventory"]) == 29
    assert result["classification"] == "FLASH_ABSENT_PROJECT_WIDE"


def test_preparer_publishes_exactly_one_read_only_command(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    module = tmp_path / prepare.MODULE
    module.parent.mkdir(parents=True)
    module.write_text("test", encoding="utf-8")
    run_id = "20260902T130000000Z_" + "a" * 32
    receipt = prepare.publish(tmp_path, "New Project 1", TARGET, IDENTITY, run_id)
    pending = list((tmp_path / ".agent" / "commands" / "pending").glob("*.json"))
    assert receipt["command_count"] == len(pending) == 1
    command = json.loads(pending[0].read_text(encoding="utf-8"))
    assert command["payload"]["read_only"] is True
    assert command["payload"]["mutation_permitted"] is False


def test_offline_validator_accepts_completed_exact_match_evidence(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    module = tmp_path / prepare.MODULE
    module.parent.mkdir(parents=True)
    module.write_text("test", encoding="utf-8")
    run_id = "20260902T130100000Z_" + "b" * 32
    receipt = prepare.publish(tmp_path, "New Project 1", TARGET, IDENTITY, run_id)
    pending = tmp_path / receipt["command_path"]
    command = json.loads(pending.read_text(encoding="utf-8"))
    report = runtime.run(Resolve(Project([Timeline(TARGET, [[exact_item()]])])), {"run_id": run_id, "command": command})
    completed = tmp_path / ".agent" / "commands" / "completed" / pending.name
    pending.replace(completed)
    run_dir = tmp_path / ".agent" / "reports" / runtime.TASK_ID / run_id
    (run_dir / "status.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (run_dir / "run.log").write_text("completed", encoding="utf-8")
    summary, failures = validate(tmp_path, run_id)
    assert failures == []
    assert summary["ok"] is True
    assert summary["classification"] == "FLASH_EXACT_MATCH_EXPECTED_TARGET"
