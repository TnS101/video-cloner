from __future__ import annotations

import json
from pathlib import Path

import pytest

from resolve_workspace.modules import video_cloner_phase4b_timeline_application as module
from scripts.davinci.prepare_video_cloner_phase4b_timeline_application import publish
from scripts.davinci.validate_video_cloner_phase4b_timeline_application import validate as validate_evidence
from video_cloner.resolve import fcpxml as canonical


TARGET = "fixture_standalone_timeline"
PROTECTED = "accepted_reel_timeline"
PROJECT = "Fixture Project"


def write_fcpxml(tmp_path: Path, *, clip_count: int = 22, duration: int = 965, target: str = TARGET) -> tuple[Path, Path]:
    video = tmp_path / "fixture proxy.mp4"
    video.write_bytes(b"video")
    boundaries = [0]
    for index in range(1, clip_count + 1):
        boundaries.append(duration if index == clip_count else index * (duration // clip_count))
    clips = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
        clips.append({"index": index, "id": index, "name": str(index), "timeline_start_frame": start, "timeline_end_frame": end, "timeline_duration_frames": end - start, "source_start_frame": start, "source_duration_frames": end - start})
    xml = canonical.build_full_timeline_fcpxml(cues=[], video_clips=clips, style={}, cue_styles=None, fps=24, width=1080, height=1920, timeline_name=target, title_prefix="VC Caption", fcpxml_version="1.10", effect_uid=canonical.DEFAULT_BASIC_TITLE_UID, title_lane=1, position_mode="reset", position_x=0, position_y=0, video_path=str(video), audio_path="", include_audio=False, transitions=[], transition_mode="none")
    path = tmp_path / "fixture.fcpxml"
    path.write_text(xml, encoding="utf-8")
    return path, video


class FakeMedia:
    def __init__(self, path: Path): self.path = path
    def GetClipProperty(self): return {"File Path": str(self.path)}


class FakeItem:
    def __init__(self, start: int, duration: int, source_start: int, path: Path, *, fusion: int = 0, zoom: float = 1.0):
        self.start, self.duration, self.source_start, self.path, self.fusion, self.zoom = start, duration, source_start, path, fusion, zoom
    def GetName(self): return self.path.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.start + self.duration
    def GetDuration(self): return self.duration
    def GetLeftOffset(self): return self.source_start
    def GetMediaPoolItem(self): return FakeMedia(self.path)
    def GetFusionCompCount(self): return self.fusion
    def GetProperty(self): return {"ZoomX": self.zoom, "ZoomY": 1.0, "PositionX": 0.0, "PositionY": 0.0, "RotationAngle": 0.0, "RetimeSpeed": 100.0}


class FakeTimeline:
    def __init__(self, name: str, items: list[FakeItem] | None = None): self.name, self.items = name, list(items or [])
    def GetName(self): return self.name
    def GetTrackCount(self, kind: str): return 1 if kind == "video" and self.items else 0
    def GetItemListInTrack(self, kind: str, index: int): return list(self.items) if kind == "video" and index == 1 else []
    def GetStartFrame(self): return 0
    def GetEndFrame(self): return max((item.GetEnd() for item in self.items), default=0)
    def GetSetting(self, key: str): return "24"


def target_timeline(path: Path, name: str | None = None, *, fusion: int = 0, zoom: float = 1.0) -> FakeTimeline:
    contract = module.parse_fcpxml_contract(path)
    source = Path(contract["source_path"])
    return FakeTimeline(name or contract["timeline_name"], [FakeItem(row["timeline_start"], row["duration"], row["source_start"], source, fusion=fusion, zoom=zoom) for row in contract["clips"]])


class FakePool:
    def __init__(self, project: "FakeProject", fcpxml: Path): self.project, self.fcpxml, self.import_calls = project, fcpxml, 0
    def ImportTimelineFromFile(self, path: str):
        self.import_calls += 1
        timeline = target_timeline(Path(path))
        self.project.timelines.append(timeline)
        return timeline


class FakeProject:
    def __init__(self, fcpxml: Path, timelines: list[FakeTimeline] | None = None, name: str = PROJECT, mutate_on_select=None):
        self.name, self.timelines = name, list([FakeTimeline(PROTECTED)] if timelines is None else timelines)
        self.mutate_on_select = mutate_on_select
        self.pool, self.current = FakePool(self, fcpxml), (self.timelines[0] if self.timelines else None)
    def GetName(self): return self.name
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index: int): return self.timelines[index - 1]
    def GetMediaPool(self): return self.pool
    def GetCurrentTimeline(self): return self.current
    def SetCurrentTimeline(self, timeline):
        self.current = timeline
        if self.mutate_on_select: self.mutate_on_select(self)
        return True


class FakeManager:
    def __init__(self, project): self.project = project
    def GetCurrentProject(self): return self.project


class FakeResolve:
    def __init__(self, project): self.project = project
    def GetProjectManager(self): return FakeManager(self.project)


def command(tmp_path: Path, fcpxml: Path, run_id: str = "run", *, target: str | None = None, protected: str | None = PROTECTED) -> tuple[dict, Path]:
    report = tmp_path / "reports" / run_id
    contract = module.parse_fcpxml_contract(fcpxml)
    payload = {"repository_root": str(tmp_path), "report_dir": str(report.relative_to(tmp_path)), "fcpxml_path": str(fcpxml), "fcpxml_sha256": module.sha256(fcpxml), "operation_id": "operation", "expected_project": PROJECT, "target_timeline_name": target or contract["timeline_name"], "protected_timeline_name": protected, "import_permitted": True, "replace_existing_timeline": False, "save_project": False, "expected_clip_count": len(contract["clips"]), "expected_duration_frames": contract["duration_frames"], "expected_fps": contract["fps"]}
    return {"task": module.TASK_ID, "run_id": run_id, "mode": module.MODE, "payload": payload}, report


def run_module(tmp_path: Path, project: FakeProject, fcpxml: Path, run_id: str = "run", **kwargs) -> dict:
    cmd, _ = command(tmp_path, fcpxml, run_id, **kwargs)
    return module.run(FakeResolve(project), {"run_id": run_id, "command": cmd})


def test_new_import_creates_and_selects_one_isolated_cut_timeline(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    project = FakeProject(fcpxml)
    report = run_module(tmp_path, project, fcpxml)
    assert report["ok"] is True
    assert report["classification"] == "NEW_ISOLATED_TIMELINE_IMPORTED"
    assert report["import_call_count"] == 1
    assert project.current.GetName() == TARGET
    assert report["target"]["clip_count"] == 22
    assert report["target"]["duration_frames"] == 965
    assert all(value == 0 for value in report["target"]["forbidden_operation_counts"].values())
    assert report["protected_timeline_unchanged"] is True
    assert report["save_project_count"] == 0


def test_second_invocation_reuses_valid_target_without_import(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    existing = target_timeline(fcpxml)
    project = FakeProject(fcpxml, [FakeTimeline(PROTECTED), existing])
    report = run_module(tmp_path, project, fcpxml, "repeat")
    assert report["ok"] is True
    assert report["classification"] == "ALREADY_VALID_REUSED"
    assert report["import_call_count"] == 0
    assert project.pool.import_calls == 0
    assert len(project.timelines) == 2


def test_duplicate_target_collision_fails_without_import(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    project = FakeProject(fcpxml, [FakeTimeline(PROTECTED), target_timeline(fcpxml), target_timeline(fcpxml)])
    report = run_module(tmp_path, project, fcpxml)
    assert report["ok"] is False
    assert "duplicate_collision" in report["failures"][0]
    assert project.pool.import_calls == 0


@pytest.mark.parametrize(("fusion", "zoom"), [(1, 1.0), (0, 1.1)])
def test_existing_target_with_forbidden_effect_fails_without_replacement(tmp_path: Path, fusion: int, zoom: float):
    fcpxml, _ = write_fcpxml(tmp_path)
    project = FakeProject(fcpxml, [FakeTimeline(PROTECTED), target_timeline(fcpxml, fusion=fusion, zoom=zoom)])
    report = run_module(tmp_path, project, fcpxml)
    assert report["ok"] is False
    assert "target_forbidden" in report["failures"][0]
    assert project.pool.import_calls == 0
    assert len(project.timelines) == 2


def test_wrong_project_fails_before_import(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    project = FakeProject(fcpxml, name="Wrong")
    report = run_module(tmp_path, project, fcpxml)
    assert report["ok"] is False
    assert "project_identity" in report["failures"][0]
    assert project.pool.import_calls == 0


def test_protected_name_is_optional(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    project = FakeProject(fcpxml, [])
    report = run_module(tmp_path, project, fcpxml, protected=None)
    assert report["ok"] is True
    assert project.pool.import_calls == 1


def test_arbitrary_14_clip_854_frame_first_import_and_offline_evidence(tmp_path: Path):
    target = "arbitrary_video_standalone_timeline"
    fcpxml, _ = write_fcpxml(tmp_path, clip_count=14, duration=854, target=target)
    root = tmp_path / "repo"
    (root / "resolve_workspace/modules").mkdir(parents=True)
    (root / "AGENTS.md").write_text("test", encoding="utf-8")
    (root / "resolve_workspace/modules/video_cloner_phase4b_timeline_application.py").write_text("test", encoding="utf-8")
    run_id = "20260818T180000000Z_0123456789abcdef0123456789abcdef"
    receipt = publish(root, fcpxml, module.sha256(fcpxml), PROJECT, target, run_id=run_id)
    pending = root / receipt["command_path"]
    cmd = json.loads(pending.read_text(encoding="utf-8"))
    payload = cmd["payload"]
    assert (payload["expected_clip_count"], payload["expected_duration_frames"], payload["expected_fps"]) == (14, 854, 24)
    non_targets = [FakeTimeline("existing_a"), FakeTimeline("existing_b")]
    project = FakeProject(fcpxml, non_targets)
    before = [module.timeline_snapshot(row)["signature"] for row in non_targets]
    report = module.run(FakeResolve(project), {"run_id": run_id, "command": cmd})
    assert report["ok"] is True
    assert report["classification"] == "NEW_ISOLATED_TIMELINE_IMPORTED"
    assert report["import_call_count"] == 1
    assert (report["target"]["clip_count"], report["target"]["duration_frames"]) == (14, 854)
    assert before == [module.timeline_snapshot(row)["signature"] for row in non_targets]
    assert report["save_project_count"] == 0
    report_dir = root / payload["report_dir"]
    module.write_json(report_dir / "report.json", report)
    module.write_json(report_dir / "status.json", {"ok": True})
    (report_dir / "run.log").write_text("offline fake runtime\n", encoding="utf-8")
    completed = root / ".agent/commands/completed" / pending.name
    completed.parent.mkdir(parents=True, exist_ok=True)
    pending.replace(completed)
    summary, failures = validate_evidence(root, run_id, "NEW_ISOLATED_TIMELINE_IMPORTED")
    assert failures == []
    assert (summary["clip_count"], summary["duration_frames"]) == (14, 854)


def test_arbitrary_14_clip_854_frame_reuse_is_idempotent(tmp_path: Path):
    target = "arbitrary_video_standalone_timeline"
    fcpxml, _ = write_fcpxml(tmp_path, clip_count=14, duration=854, target=target)
    existing = target_timeline(fcpxml)
    non_target = FakeTimeline("existing")
    project = FakeProject(fcpxml, [non_target, existing])
    signature = module.timeline_snapshot(non_target)["signature"]
    report = run_module(tmp_path, project, fcpxml, target=target, protected=None)
    assert report["ok"] is True
    assert report["classification"] == "ALREADY_VALID_REUSED"
    assert report["import_call_count"] == project.pool.import_calls == 0
    assert sum(row.GetName() == target for row in project.timelines) == 1
    assert module.timeline_snapshot(non_target)["signature"] == signature
    assert report["save_project_count"] == 0


def test_non_target_signature_change_is_rejected(tmp_path: Path):
    fcpxml, video = write_fcpxml(tmp_path)
    non_target = FakeTimeline("existing", [FakeItem(0, 1, 0, video)])
    project = FakeProject(fcpxml, [non_target], mutate_on_select=lambda _: setattr(non_target.items[0], "zoom", 1.1))
    report = run_module(tmp_path, project, fcpxml, protected=None)
    assert report["ok"] is False
    assert "non_target_timeline_changed" in report["failures"][0]


def test_unexpected_non_target_addition_is_rejected(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    project = FakeProject(fcpxml, mutate_on_select=lambda value: value.timelines.append(FakeTimeline("surprise")))
    report = run_module(tmp_path, project, fcpxml)
    assert report["ok"] is False
    assert "timeline_inventory_delta" in report["failures"][0]


@pytest.mark.parametrize("content", ["", "<broken>", "<fcpxml version='1.10'/>"])
def test_malformed_or_empty_fcpxml_is_rejected(tmp_path: Path, content: str):
    path = tmp_path / "bad.fcpxml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        module.parse_fcpxml_contract(path)


@pytest.mark.parametrize("mutation", ["gap", "wrong_source", "transition"])
def test_generic_fcpxml_structural_guards_remain_enforced(tmp_path: Path, mutation: str):
    path, _ = write_fcpxml(tmp_path)
    root = module.ET.parse(path).getroot()
    spine = root.find("./library/event/project/sequence/spine")
    assert spine is not None
    if mutation == "gap":
        list(spine)[0].set("offset", "1/24s")
    elif mutation == "wrong_source":
        list(spine)[0].set("ref", "missing")
    else:
        module.ET.SubElement(spine, "transition")
    module.ET.ElementTree(root).write(path, encoding="unicode")
    with pytest.raises(ValueError):
        module.parse_fcpxml_contract(path)


def test_prepare_requires_exact_hash_and_explicit_isolated_identity(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    root = tmp_path / "repo"
    (root / "resolve_workspace/modules").mkdir(parents=True)
    (root / "AGENTS.md").write_text("test", encoding="utf-8")
    (root / "resolve_workspace/modules/video_cloner_phase4b_timeline_application.py").write_text("test", encoding="utf-8")
    receipt = publish(root, fcpxml, module.sha256(fcpxml), PROJECT, TARGET, PROTECTED, "20260818T180000000Z_0123456789abcdef0123456789abcdef")
    assert receipt["ok"] is True
    pending = root / receipt["command_path"]
    payload = json.loads(pending.read_text(encoding="utf-8"))["payload"]
    assert payload["replace_existing_timeline"] is False
    assert payload["save_project"] is False
    assert payload["target_timeline_name"] == TARGET
    assert (payload["expected_clip_count"], payload["expected_duration_frames"], payload["expected_fps"]) == (22, 965, 24)


def test_runtime_rejects_tampered_artifact_expectations_before_import(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    project = FakeProject(fcpxml)
    cmd, _ = command(tmp_path, fcpxml)
    cmd["payload"]["expected_clip_count"] = 14
    report = module.run(FakeResolve(project), {"run_id": "run", "command": cmd})
    assert report["ok"] is False
    assert "fcpxml_payload_expectations" in report["failures"][0]
    assert project.pool.import_calls == 0


def test_prepare_rejects_hash_mismatch(tmp_path: Path):
    fcpxml, _ = write_fcpxml(tmp_path)
    root = tmp_path / "repo"
    (root / "resolve_workspace/modules").mkdir(parents=True)
    (root / "AGENTS.md").write_text("test", encoding="utf-8")
    (root / "resolve_workspace/modules/video_cloner_phase4b_timeline_application.py").write_text("test", encoding="utf-8")
    with pytest.raises(ValueError, match="fcpxml_hash"):
        publish(root, fcpxml, "0" * 64, PROJECT, TARGET, PROTECTED)


def test_module_contains_no_delete_or_save_api_call():
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "DeleteTimelines(" not in source
    assert ".SaveProject(" not in source
