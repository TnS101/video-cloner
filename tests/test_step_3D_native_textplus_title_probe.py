from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_native_textplus_title_probe.py"
PUBLISHER_PATH = ROOT / "scripts" / "davinci" / "prepare_step_3D_native_textplus_title_probe.py"
VALIDATOR_PATH = ROOT / "scripts" / "davinci" / "validate_step_3D_native_textplus_title_probe.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


probe = load(MODULE_PATH, "native_textplus_probe")
publisher = load(PUBLISHER_PATH, "native_textplus_publisher")
validator = load(VALIDATOR_PATH, "native_textplus_validator")


class FakeInput:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def __getitem__(self, frame):
        return self.values.get(frame)

    def __setitem__(self, frame, value):
        self.values[int(frame)] = value

    def GetAttrs(self):
        return {"INPS_ID": "Center", "INPS_Name": "Center"}


class FakeTextTool:
    def __init__(self):
        self.inputs = {
            "StyledText": FakeInput({0: ""}),
            "Center": FakeInput({0: [0.5, 0.5]}),
        }

    def GetAttrs(self):
        return {"TOOLS_RegID": "TextPlus"}

    def FindInput(self, name):
        return self.inputs.get(name)

    def GetInput(self, name, frame):
        item = self.inputs.get(name)
        return item[frame] if item is not None else None

    def SetInput(self, name, value, frame=0):
        self.inputs.setdefault(name, FakeInput())[int(frame)] = value
        return True

    def __setattr__(self, name, value):
        if name == "inputs":
            object.__setattr__(self, name, value)
        elif "inputs" in self.__dict__ and name in self.inputs:
            self.inputs[name][0] = value
        else:
            object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name in self.inputs:
            return self.inputs[name]
        raise AttributeError(name)


class FakeComp:
    def __init__(self):
        self.tool = FakeTextTool()

    def GetToolList(self, _selected=False, regid=None):
        if regid in (None, "TextPlus"):
            return {"Text1": self.tool}
        return {}


class FakeMediaPoolItem:
    def GetName(self):
        return "source.mov"


class FakeItem:
    counter = 0

    def __init__(self, name, start, end, track, textplus=False, media=False):
        FakeItem.counter += 1
        self.name = name
        self.start = start
        self.end = end
        self.track = track
        self.uid = f"uid-{FakeItem.counter}"
        self.comp = FakeComp() if textplus else None
        self.media = FakeMediaPoolItem() if media else None

    def GetName(self): return self.name
    def SetName(self, name): self.name = name; return True
    def GetUniqueId(self): return self.uid
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.end - self.start
    def GetFusionCompCount(self): return 1 if self.comp else 0
    def GetFusionCompByIndex(self, index): return self.comp if self.comp and index == 1 else None
    def GetFusionCompNameList(self): return ["Composition 1"] if self.comp else []
    def GetFusionCompByName(self, _name): return self.comp
    def GetMediaPoolItem(self): return self.media


class FakeTimeline:
    def __init__(
        self,
        name,
        items_by_track=None,
        start_frame=0,
        start_timecode="01:00:00:00",
        project=None,
        insert_returns_none=False,
    ):
        self.name = name
        self.uid = f"timeline-{name}"
        self.items_by_track = {int(k): list(v) for k, v in (items_by_track or {}).items()}
        self.start_frame = start_frame
        self.start_timecode = start_timecode
        self.current_timecode = start_timecode
        self.project = project
        self.insert_returns_none = insert_returns_none
        self.track_locks = {}

    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetTrackCount(self, kind): return max(self.items_by_track, default=0) if kind == "video" else 0
    def GetItemListInTrack(self, kind, index): return list(self.items_by_track.get(index, [])) if kind == "video" else []
    def GetStartFrame(self): return self.start_frame
    def GetStartTimecode(self): return self.start_timecode
    def GetCurrentTimecode(self): return self.current_timecode
    def GetSetting(self, name): return "24" if name == "timelineFrameRate" else ""
    def SetCurrentTimecode(self, value): self.current_timecode = value; return True
    def SetTrackLock(self, kind, index, locked):
        self.track_locks[(kind, index)] = bool(locked)
        return True
    def DeleteClips(self, items, _ripple):
        for track in self.items_by_track:
            self.items_by_track[track] = [item for item in self.items_by_track[track] if item not in items]
        return True
    def InsertFusionTitleIntoTimeline(self, name):
        assert name == "Text+"
        target = next(
            (
                index
                for index in range(1, max(self.GetTrackCount("video"), probe.TARGET_TRACK) + 1)
                if self.track_locks.get(("video", index), False) is False
            ),
            probe.TARGET_TRACK,
        )
        item = FakeItem(name, probe.TARGET_FRAME, probe.TARGET_FRAME + 120, target, textplus=True)
        self.items_by_track.setdefault(target, []).append(item)
        return None if self.insert_returns_none else item
    def DuplicateTimeline(self, name):
        cloned = {}
        for track, items in self.items_by_track.items():
            cloned[track] = [
                FakeItem(
                    item.name,
                    item.start,
                    item.end,
                    track,
                    textplus=item.comp is not None,
                    media=item.media is not None,
                )
                for item in items
            ]
        duplicate = FakeTimeline(
            name,
            cloned,
            self.start_frame,
            self.start_timecode,
            self.project,
            insert_returns_none=self.insert_returns_none,
        )
        if self.project is not None:
            self.project.timelines.append(duplicate)
        return duplicate


def test_timecode_addition_places_frame_430_at_24fps():
    assert probe.add_timecode_frames("01:00:00:00", 430, 24) == "01:00:17:22"


def test_timecode_addition_preserves_drop_delimiter_shape():
    assert probe.add_timecode_frames("01:00:00;00", 24, 24) == "01:00:01;00"


def test_set_playhead_requires_exact_readback():
    timeline = FakeTimeline("t")
    result = probe.set_playhead_to_frame(timeline, 430)
    assert result["ok"] is True
    assert result["requested_timecode"] == "01:00:17:22"
    assert result["actual_timecode"] == "01:00:17:22"


def test_native_title_exposes_one_textplus_tool_and_comp():
    timeline = FakeTimeline("t")
    item = timeline.InsertFusionTitleIntoTimeline("Text+")
    summary = probe.item_summary(timeline, item)
    assert summary["start"] == 430
    assert summary["track_index"] == 1
    assert summary["fusion_comp_count"] == 1
    assert len(probe.get_text_tools(probe.get_comp(item))) == 1


def test_text_and_two_center_keyframes_round_trip():
    timeline = FakeTimeline("t")
    item = timeline.InsertFusionTitleIntoTimeline("Text+")
    tool = probe.get_text_tools(probe.get_comp(item))[0]
    assert probe.set_static_input(tool, "StyledText", probe.PROBE_TEXT)["ok"] is True
    rows = [probe.set_keyframe(tool, "Center", frame, value) for frame, value in probe.CENTER_KEYFRAMES]
    assert all(row["ok"] for row in rows)
    assert probe.read_text(tool) == probe.PROBE_TEXT
    assert probe.point_matches(probe.read_input(tool, "Center", 0), [0.4324, 0.6292])
    assert probe.point_matches(probe.read_input(tool, "Center", 3), [0.5, 0.6276])


def test_edit_page_context_locks_only_target_track_and_detects_none_return_delta():
    source = FakeTimeline(
        "source",
        {1: [FakeItem("base", 0, 1000, 1, media=True)], 3: []},
        insert_returns_none=True,
    )
    project = FakeProject([source])
    resolve = FakeResolve(FakeProjectManager(project))
    context = probe.stabilize_native_title_context(
        resolve,
        project,
        source,
        probe.TARGET_FRAME,
        probe.TARGET_TRACK,
    )
    assert context["ok"] is True
    assert resolve.GetCurrentPage() == "edit"
    assert source.track_locks[("video", 1)] is True
    assert source.track_locks[("video", 3)] is False

    before = probe.video_item_snapshot(source)
    returned = source.InsertFusionTitleIntoTimeline("Text+")
    assert returned is None
    added = probe.find_new_video_items(source, before)
    assert len(added) == 1
    assert probe.item_summary(source, added[0])["track_index"] == probe.TARGET_TRACK


def test_source_snapshot_is_semantic_and_sorted():
    a = FakeItem("VC_TEXTPLUS_0002_sub_002", 20, 24, 3, textplus=True)
    b = FakeItem("VC_TEXTPLUS_0001_sub_001", 10, 14, 3, textplus=True)
    timeline = FakeTimeline(probe.SOURCE_TIMELINE_NAME, {3: [a, b]})
    snapshot = probe.source_timeline_snapshot(timeline)
    assert [row["name"] for row in snapshot["captions"]] == [
        "VC_TEXTPLUS_0001_sub_001",
        "VC_TEXTPLUS_0002_sub_002",
    ]


def test_publisher_uses_canonical_accepted_state_hash(tmp_path, monkeypatch):
    root = tmp_path
    (root / "AGENTS.md").write_text("rules", encoding="utf-8")
    for relative in publisher.SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    accepted = root / publisher.ACCEPTED_STATE
    accepted.parent.mkdir(parents=True, exist_ok=True)
    accepted.write_text('{\n  "b": 2,\n  "a": 1\n}\n', encoding="utf-8")
    monkeypatch.setattr(publisher, "run_id_now", lambda: "RUN_123456789012")
    receipt = publisher.publish(root)
    command = json.loads(Path(receipt["command_path"]).read_text(encoding="utf-8"))
    assert command["accepted_state_hash_algorithm"] == "sha256_canonical_json"
    assert command["accepted_state_sha256"] == publisher.canonical_json_sha256(accepted)
    assert command["probe"]["workspace_invocations"] == 1
    assert command["probe"]["cleanup_after_result"] is True
    assert command["probe"]["target_track"] == 3
    assert command["probe"]["required_page"] == "edit"


def test_validator_waits_for_terminal_state(tmp_path, monkeypatch):
    root = tmp_path
    run_id = "run"
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    name = validator.command_name(run_id)
    pending = queue / "pending" / name
    pending.write_text("{}", encoding="utf-8")
    calls = {"count": 0}

    def fake_sleep(_seconds):
        calls["count"] += 1
        pending.rename(queue / "completed" / name)

    monkeypatch.setattr(validator.time, "sleep", fake_sleep)
    state, path, evidence = validator.wait_for_terminal(root, run_id, 2, 0.01)
    assert state == "completed"
    assert path.name == name
    assert calls["count"] == 1
    assert evidence["timed_out"] is False


def test_required_artifacts_cover_insertion_mutation_persistence_and_cleanup():
    assert "native_title_insertion.json" in validator.REQUIRED_SUCCESS_ARTIFACTS
    assert "native_textplus_mutation.json" in validator.REQUIRED_SUCCESS_ARTIFACTS
    assert "persistent_readback.json" in validator.REQUIRED_SUCCESS_ARTIFACTS
    assert "probe_cleanup.json" in validator.REQUIRED_SUCCESS_ARTIFACTS


def test_source_contract_has_only_runtime_module_and_bridge():
    assert publisher.SOURCE_PATHS == (
        "resolve_workspace/modules/step_3D_native_textplus_title_probe.py",
        "resolve_workspace/VC_Agent_Bridge.py",
    )


class FakeMediaPool:
    def __init__(self, project):
        self.project = project

    def DeleteTimelines(self, timelines):
        self.project.timelines = [timeline for timeline in self.project.timelines if timeline not in timelines]
        return True


class FakeProject:
    def __init__(self, timelines):
        self.timelines = list(timelines)
        for timeline in self.timelines:
            timeline.project = self
        self.current = self.timelines[0]
        self.media_pool = FakeMediaPool(self)

    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetCurrentTimeline(self): return self.current
    def SetCurrentTimeline(self, timeline): self.current = timeline; return True
    def GetMediaPool(self): return self.media_pool


class FakeProjectManager:
    def __init__(self, project):
        self.project = project
        self.save_calls = 0

    def GetCurrentProject(self): return self.project
    def SaveProject(self): self.save_calls += 1; return True


class FakeResolve:
    def __init__(self, project_manager):
        self.project_manager = project_manager
        self.page = "fusion"

    def GetProjectManager(self): return self.project_manager
    def GetCurrentPage(self): return self.page
    def OpenPage(self, page): self.page = page; return True


def test_full_run_proves_persistence_and_cleanup(tmp_path, monkeypatch):
    source_items = {1: [FakeItem("base", 0, 1000, 1, media=True)], 3: []}
    for index in range(1, probe.EXPECTED_SOURCE_CAPTION_COUNT + 1):
        source_items[3].append(
            FakeItem(f"VC_TEXTPLUS_{index:04d}_sub_{index:03d}", index * 5, index * 5 + 4, 3, textplus=True)
        )
    source = FakeTimeline(
        probe.SOURCE_TIMELINE_NAME,
        source_items,
        insert_returns_none=True,
    )
    project = FakeProject([source])
    manager = FakeProjectManager(project)
    resolve = FakeResolve(manager)

    module_path = tmp_path / probe.MODULE_RELATIVE_PATH
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("module", encoding="utf-8")
    bridge_path = tmp_path / probe.BRIDGE_RELATIVE_PATH
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text("bridge", encoding="utf-8")
    accepted_path = tmp_path / probe.ACCEPTED_STATE_RELATIVE_PATH
    accepted_path.parent.mkdir(parents=True, exist_ok=True)
    accepted_path.write_text('{"accepted": true}\n', encoding="utf-8")

    report_dir = tmp_path / ".agent" / "reports" / probe.TASK_ID / "run"
    command = {
        "task_id": probe.TASK_ID,
        "mode": probe.MODE,
        "run_id": "run",
        "artifacts_dir": str(report_dir.relative_to(tmp_path)),
        "accepted_state_path": probe.ACCEPTED_STATE_RELATIVE_PATH,
        "accepted_state_hash_algorithm": probe.ACCEPTED_HASH_ALGORITHM,
        "accepted_state_sha256": probe.canonical_json_sha256(accepted_path),
        "source_contract": {
            "version": 1,
            "algorithm": probe.SOURCE_HASH_ALGORITHM,
            "hashes": {
                probe.MODULE_RELATIVE_PATH: probe.normalized_sha256(module_path),
                probe.BRIDGE_RELATIVE_PATH: probe.normalized_sha256(bridge_path),
            },
        },
        "probe": {"timeline_name": "VC_NATIVE_TEST"},
    }
    monkeypatch.setattr(probe, "repository_root", lambda: tmp_path)
    result = probe.run(resolve, {"command": command, "run_id": "run"})

    assert result["ok"] is True
    assert result["architecture_viable"] is True
    assert result["inserted_item"]["start"] == probe.TARGET_FRAME
    assert result["inserted_item"]["track_index"] == probe.TARGET_TRACK
    assert result["insertion_detected_by"] == "timeline_delta"
    assert result["text_readback"] == probe.PROBE_TEXT
    assert result["center_readback_count"] == 2
    assert result["persistent_readback_ok"] is True
    assert result["probe_timeline_deleted"] is True
    assert result["original_timeline_restored"] is True
    assert result["original_page_restored"] is True
    assert resolve.GetCurrentPage() == "fusion"
    assert result["source_timeline_unchanged"] is True
    assert result["accepted_state_unchanged"] is True
    assert result["save_call_count"] == 2
    assert manager.save_calls == 2
    assert [timeline.GetName() for timeline in project.timelines] == [probe.SOURCE_TIMELINE_NAME]
