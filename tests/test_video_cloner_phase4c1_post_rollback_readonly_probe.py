from __future__ import annotations

import json
from pathlib import Path

import pytest

from resolve_workspace.modules import video_cloner_phase4c1_post_rollback_readonly_probe as runtime
from scripts.davinci import prepare_video_cloner_phase4c1_post_rollback_readonly_probe as prepare
from scripts.davinci.validate_video_cloner_phase4c1_post_rollback_readonly_probe import validate_report

TARGET = "DcJRJtUKScu_standalone_timeline"
REEL1 = runtime.REEL1_TIMELINE
NEUTRAL_PATH = "C:/repo/data/DZsqH7auhjt/davinci/flash_neutral_rgba_v4/rgba_[000000-000003].png"
IDENTITY = {"name": "VC_FLASH_001_frame_0596", "start": 594, "end": 598, "duration": 4, "media_pool_item_name": "VC_FLASH_NEUTRAL_RGBA_V4", "fusion_tool_name": "VC_FLASH_BG_001", "alpha_keyframes": [[0, 0.0], [2, 0.75], [3, 0.0]]}
DURATIONS = [38, 40, 152, 156, 48, 60, 19, 25, 58, 38, 28, 108, 80, 4]


class Media:
    def __init__(self, name="source.mp4", path="C:/repo/source.mp4", uid="source"):
        self.name, self.path, self.uid = name, path, uid
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetClipProperty(self, key=None):
        values = {"File Path": self.path, "Video Frame Rate": "24", "Alpha mode": "Straight"}
        return values if key is None else values.get(key, "")


class Item:
    def __init__(self, name, start, duration, media, source_start=None, fusion=0):
        self.name, self.start, self.duration, self.media = name, start, duration, media
        self.source_start, self.fusion = start if source_start is None else source_start, fusion
    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.start + self.duration
    def GetDuration(self): return self.duration
    def GetLeftOffset(self): return self.source_start
    def GetMediaPoolItem(self): return self.media
    def GetFusionCompCount(self): return self.fusion
    def GetFusionCompByIndex(self, index): return None
    def GetProperty(self): return {"ZoomX": 1.0, "ZoomY": 1.0, "PositionX": 0.0, "PositionY": 0.0, "RotationAngle": 0.0, "RetimeSpeed": 100.0}


class Timeline:
    def __init__(self, name, tracks=None, drift=None, audio_tracks=0):
        self.name, self.tracks, self.drift, self.audio_tracks = name, list(tracks or []), drift, audio_tracks
        self.reads, self.mutations = 0, 0
    def GetName(self): return self.name
    def GetTrackCount(self, kind): return len(self.tracks) if kind == "video" else self.audio_tracks
    def GetItemListInTrack(self, kind, index):
        if kind != "video" or not 0 < index <= len(self.tracks): return []
        self.reads += 1
        if self.reads == 2 and self.drift == "semantic": self.tracks[index - 1][0].duration += 1
        rows = list(self.tracks[index - 1])
        return list(reversed(rows)) if self.reads == 2 and self.drift == "order" else rows
    def GetStartFrame(self): return 0
    def GetEndFrame(self): return max((item.GetEnd() for track in self.tracks for item in track), default=0)
    def GetSetting(self, key): return "24"
    def __getattr__(self, name):
        if name.startswith(("Set", "Add", "Delete", "Create", "Import", "Append", "Save")):
            def mutate(*args, **kwargs): self.mutations += 1
            return mutate
        raise AttributeError(name)


class Folder:
    def __init__(self, clips=None, children=None, name="Root"):
        self.clips, self.children, self.name = list(clips or []), list(children or []), name
    def GetName(self): return self.name
    def GetClipList(self): return list(self.clips)
    def GetSubFolderList(self): return list(self.children)


class Pool:
    def __init__(self, media=None): self.root, self.mutations = Folder(media), 0
    def GetRootFolder(self): return self.root
    def __getattr__(self, name):
        if name.startswith(("Set", "Add", "Delete", "Create", "Import", "Append", "Save")):
            def mutate(*args, **kwargs): self.mutations += 1
            return mutate
        raise AttributeError(name)


class Project:
    def __init__(self, timelines, media=None): self.timelines, self.pool, self.mutations = list(timelines), Pool(media), 0
    def GetName(self): return "New Project 1"
    def GetCurrentTimeline(self): return self.timelines[0] if self.timelines else None
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetMediaPool(self): return self.pool
    def __getattr__(self, name):
        if name.startswith(("Set", "Add", "Delete", "Create", "Import", "Append", "Save")):
            def mutate(*args, **kwargs): self.mutations += 1
            return mutate
        raise AttributeError(name)


class Manager:
    def __init__(self, project): self.project, self.mutations = project, 0
    def GetCurrentProject(self): return self.project


class Resolve:
    def __init__(self, project): self.manager = Manager(project)
    def GetProjectManager(self): return self.manager


def base_items():
    media, rows, start = Media(), [], 0
    for duration in DURATIONS:
        rows.append(Item("source.mp4", start, duration, media, source_start=start))
        start += duration
    return rows


def baseline():
    start, clips = 0, []
    for index, duration in enumerate(DURATIONS, 1):
        clips.append({"index": index, "name": str(index), "timeline_start": start, "source_start": start, "duration": duration})
        start += duration
    return {"timeline_name": TARGET, "clip_count": 14, "duration_frames": 854, "fps": 24, "audio_track_count": 1, "source_path": "C:/repo/source.mp4", "clips": clips, "fcpxml_sha256": "f" * 64}


def command():
    return {"task": runtime.TASK_ID, "run_id": "run", "module": prepare.MODULE, "mode": runtime.MODE, "payload": {"action": runtime.ACTION, "operation_id": "operation", "read_only": True, "mutation_permitted": False, "expected_project_name": "New Project 1", "expected_target_timeline_name": TARGET, "accepted_baseline": baseline(), "expected_flash_identity": IDENTITY, "expected_flash_identity_sha256": runtime.LOCATION.canonical_sha256(IDENTITY), "expected_neutral_paths": {"historical_reel1": NEUTRAL_PATH, "portable_reel2": NEUTRAL_PATH}, "neutral_media_search_tokens": ["VC_FLASH_NEUTRAL_RGBA_V4", "flash_neutral_rgba_v4"]}}


def reel1_command():
    return {"task": runtime.TASK_ID, "run_id": "run", "module": prepare.MODULE, "mode": runtime.MODE, "payload": {"action": runtime.ACTION, "operation_id": "operation", "diagnostic_profile": runtime.PROFILE_REEL1, "read_only": True, "mutation_permitted": False, "expected_project_name": "New Project 1", "expected_target_timeline_name": REEL1, "target_contract": {"timeline_name": REEL1, "occurrence_count": 1, "expected_track_index": 26, "expected_orphan_item_name": runtime.REEL1_ORPHAN_ITEM_NAME, "expected_spans": [{"start": start, "end": end} for start, end in runtime.REEL1_SPANS], "accepted_historical_timeline_name": REEL1}, "reel2_protection_contract": dict(prepare.REEL2_PROTECTION), "expected_neutral_paths": {"historical_reel1": NEUTRAL_PATH, "portable_reel2": NEUTRAL_PATH}, "neutral_media_search_tokens": ["VC_FLASH_NEUTRAL_RGBA_V4", "flash_neutral_rgba_v4"]}}


def run(project, cmd=None):
    result = runtime.run(Resolve(project), {"run_id": "run", "command": cmd or command()})
    assert project.mutations == project.pool.mutations == 0
    assert all(timeline.mutations == 0 for timeline in project.timelines)
    assert result["mutation_counts"] == runtime.ZERO_MUTATIONS
    return result


def clean_target(drift=None): return Timeline(TARGET, [base_items()], drift=drift, audio_tracks=1)


def neutral(uid="neutral"): return Media("VC_FLASH_NEUTRAL_RGBA_V4", NEUTRAL_PATH, uid)


def historical(media):
    starts = [94, 375, 424, 452, 756]
    return Timeline(REEL1, [[Item(f"VC_FLASH_{index:03d}_frame_{start + 2:04d}", start, 4, media) for index, start in enumerate(starts, 1)]])


def reel1_orphans(items=None):
    tracks = [[] for _ in range(26)]
    tracks[25] = items if items is not None else [Item(runtime.REEL1_ORPHAN_ITEM_NAME, start, end - start, None) for start, end in runtime.REEL1_SPANS]
    return Timeline(REEL1, tracks)


def test_all_timelines_stable_across_two_reads():
    result = run(Project([clean_target(), Timeline("other")]))
    assert result["read_determinism_classification"] == "TIMELINE_SIGNATURES_STABLE_TWO_PASS"
    assert result["signature_mismatches"] == []


def test_item_order_only_drift_is_exposed_not_normalized():
    items = [Item("a", 0, 1, Media()), Item("b", 1, 1, Media())]
    result = run(Project([Timeline("other", [items], drift="order")]))
    assert result["read_determinism_classification"] == "TIMELINE_SIGNATURE_HASH_DRIFT_SEMANTICS_STABLE"
    assert result["signature_mismatches"][0]["differences"][0]["kind"] == "ORDER_ONLY"


def test_genuine_semantic_drift_includes_exact_field_diff():
    result = run(Project([Timeline("other", [[Item("a", 0, 1, Media())]], drift="semantic")]))
    assert result["read_determinism_classification"] == "TIMELINE_SIGNATURE_SEMANTIC_DRIFT"
    assert any(row["path"].endswith(".duration") for row in result["signature_mismatches"][0]["differences"])


def test_reel2_clean_rollback_baseline():
    result = run(Project([clean_target()]))
    assert result["target_rollback_state"]["classification"] == "ROLLBACK_TARGET_BASELINE_RESTORED"
    assert all(result["target_rollback_state"]["checks"].values())


def test_reel2_residual_v2_and_flash_state():
    flash = Item(IDENTITY["name"], 594, 4, neutral())
    result = run(Project([Timeline(TARGET, [base_items(), [flash]], audio_tracks=1)], [flash.media]))
    assert result["target_rollback_state"]["classification"] == "ROLLBACK_TARGET_RESIDUAL_FLASH_STATE"
    assert result["target_rollback_state"]["exact_expected_flash_count"] == 0
    assert result["target_rollback_state"]["partial_flash_count"] == 1


def test_single_shared_neutral_media_and_historical_linkage_intact():
    media = neutral()
    result = run(Project([clean_target(), historical(media)], [media]))
    assert result["neutral_media"]["classification"] == "NEUTRAL_MEDIA_SINGLE_SHARED_OBJECT"
    assert result["reel1_flash_carriers"]["classification"] == "REEL1_FLASH_MEDIA_LINKAGE_INTACT"
    assert result["reel1_flash_carriers"]["count"] == 5


def test_duplicated_neutral_media_objects_are_classified():
    first, second = neutral("one"), neutral("two")
    result = run(Project([clean_target(), historical(first)], [first, second]))
    assert result["neutral_media"]["classification"] == "NEUTRAL_MEDIA_DUPLICATED_OBJECTS"


def test_historical_carrier_broken_linkage_is_classified():
    result = run(Project([clean_target(), historical(neutral())], []))
    assert result["reel1_flash_carriers"]["classification"] == "REEL1_FLASH_MEDIA_LINKAGE_BROKEN"


def test_validator_accepts_complete_zero_mutation_report():
    cmd = command()
    report = run(Project([clean_target()]))
    assert validate_report(cmd, report) == []


def test_preparer_publishes_one_read_only_command_in_isolated_fixture(tmp_path: Path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    module = tmp_path / prepare.MODULE
    module.parent.mkdir(parents=True)
    module.write_text("test", encoding="utf-8")
    authority, fcpxml = tmp_path / "authority.json", tmp_path / "timeline.fcpxml"
    authority.write_text("{}", encoding="utf-8")
    fcpxml.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(prepare, "build_baseline", lambda *args: baseline())
    monkeypatch.setattr(prepare, "identity_from_authority", lambda *args: IDENTITY)
    run_id = "20260902T180000000Z_" + "a" * 32
    receipt = prepare.publish(tmp_path, "New Project 1", TARGET, authority, fcpxml, "f" * 64, run_id)
    pending = list((tmp_path / ".agent/commands/pending").glob("*.json"))
    assert receipt["command_count"] == len(pending) == 1
    payload = json.loads(pending[0].read_text(encoding="utf-8"))["payload"]
    assert payload["read_only"] is True and payload["mutation_permitted"] is False


def test_reel1_preparer_publishes_one_command_without_fcpxml(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    module = tmp_path / prepare.MODULE
    module.parent.mkdir(parents=True)
    module.write_text("test", encoding="utf-8")
    run_id = "20260907T010000000Z_" + "b" * 32
    receipt = prepare.publish(tmp_path, "New Project 1", REEL1, run_id=run_id, diagnostic_profile=runtime.PROFILE_REEL1)
    pending = list((tmp_path / ".agent/commands/pending").glob("*.json"))
    payload = json.loads(pending[0].read_text(encoding="utf-8"))["payload"]
    assert receipt["command_count"] == len(pending) == 1
    assert "accepted_baseline" not in payload and payload["target_contract"]["expected_track_index"] == 26


def test_reel1_exact_orphans_validate_with_reel2_current_and_protected():
    cmd = reel1_command()
    result = run(Project([clean_target(), reel1_orphans()]), cmd)
    assert result["current_timeline_name"] == TARGET
    assert [row["classification"] for row in result["reel1_restoration_state"]["spans"]] == ["ORIGINAL_ORPHAN_PRESENT"] * 5
    assert result["reel2_protection_state"]["ok"] is True
    assert validate_report(cmd, result) == []


def test_reel1_missing_orphan_is_valid_diagnostic_evidence():
    cmd = reel1_command()
    result = run(Project([clean_target(), reel1_orphans([])]), cmd)
    assert [row["classification"] for row in result["reel1_restoration_state"]["spans"]] == ["MISSING"] * 5
    assert validate_report(cmd, result) == []


def test_reel1_partial_replacement_is_represented():
    cmd = reel1_command()
    items = [Item("VC_FLASH_partial", 94, 3, neutral(), fusion=1)]
    result = run(Project([clean_target(), reel1_orphans(items)], [items[0].media]), cmd)
    first = result["reel1_restoration_state"]["spans"][0]
    assert first["classification"] == "UNEXPECTED_OR_PARTIAL_ITEM"
    assert first["items"][0]["resolved_path"] == NEUTRAL_PATH
    assert result["reel1_restoration_state"]["unexpected_items"]


def test_reel1_valid_replacement_is_distinguished():
    cmd = reel1_command()
    media = neutral()
    items = [Item("VC_FLASH_001_frame_0096", 94, 4, media, fusion=1)]
    result = run(Project([clean_target(), reel1_orphans(items)], [media]), cmd)
    assert result["reel1_restoration_state"]["spans"][0]["classification"] == "VALID_REPLACEMENT_PRESENT"


def test_malformed_reel1_request_fails_closed(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    module = tmp_path / prepare.MODULE
    module.parent.mkdir(parents=True)
    module.write_text("test", encoding="utf-8")
    with pytest.raises(ValueError, match="reel1_target_contract"):
        prepare.publish(tmp_path, "New Project 1", TARGET, run_id="20260907T010000000Z_" + "c" * 32, diagnostic_profile=runtime.PROFILE_REEL1)


def test_runtime_source_contains_no_mutation_api():
    source = Path(runtime.__file__).read_text(encoding="utf-8")
    forbidden = ("SetCurrentTimeline", "AppendToTimeline", "ImportMedia", "SaveProject", "AddTrack", "DeleteTrack", "DeleteClips", "CreateTimeline", "DeleteTimeline", "RenameTimeline", "SetProperty", "SetInput", "AddTool")
    assert not [name for name in forbidden if name in source]
