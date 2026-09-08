from __future__ import annotations

import importlib.util
from pathlib import Path
from xml.sax.saxutils import escape

RUNTIME_PATH = Path(__file__).parents[1] / "resolve_workspace/modules/step_3D_import_lifecycle_timeline.py"
SPEC = importlib.util.spec_from_file_location("runtime", RUNTIME_PATH)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class FakeItem:
    def __init__(self, name, start, end):
        self.name = name
        self.start = start
        self.end = end

    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.end


class FakeTimeline:
    def __init__(self, name, video_tracks, audio_tracks=None):
        self.name = name
        self.video_tracks = video_tracks
        self.audio_tracks = audio_tracks or {1: [FakeItem("audio", 0, 965)]}

    def GetName(self): return self.name
    def GetTrackCount(self, kind):
        return len(self.video_tracks if kind == "video" else self.audio_tracks)

    def GetItemListInTrack(self, kind, index):
        return list((self.video_tracks if kind == "video" else self.audio_tracks).get(index, []))


TRANSITIONS = [
    (92, 100, "Cross Dissolve"),
    (373, 382, "Cross Dissolve"),
    (422, 431, "Cross Dissolve"),
    (449, 459, "Cross Dissolve"),
    (488, 496, "Slide"),
    (522, 530, "Cross Dissolve"),
    (552, 560, "Cross Dissolve"),
    (583, 591, "Slide"),
    (614, 622, "Slide"),
    (754, 762, "Cross Dissolve"),
    (829, 837, "Cross Dissolve"),
]


TARGETS = {
    52: (430, 452, "COME"),
    57: (454, 493, "that"),
    58: (456, 492, "KNOWS"),
    81: (628, 656, "the"),
}


def caption_spec(index):
    if index in TARGETS:
        start, end, text = TARGETS[index]
    else:
        start = 1000 + index * 3
        end = start + 2
        text = f"word{index}"
    lane = 1 + ((index - 1) % 5)
    return start, end, text, lane


def make_imported():
    # Simulate Resolve's observed track ordering: caption lanes are V1-V5 and
    # the primary video spine is V6. The V1 package incorrectly assumed V1.
    tracks = {lane: [] for lane in range(1, 7)}
    tracks[6] = [FakeItem(str(i), i * 10, i * 10 + 5) for i in range(22)]
    tracks[6].extend(FakeItem(name, start, end) for start, end, name in TRANSITIONS)
    for index in range(1, 117):
        start, end, text, lane = caption_spec(index)
        tracks[lane].append(FakeItem(f"VC Caption {index:04d} - {text}", start, end))
    return FakeTimeline(runtime.IMPORTED_TIMELINE_NAME, tracks)


def make_fcpxml():
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<fcpxml version="1.10"><library><event><project><sequence><spine>',
    ]
    for i in range(22):
        parts.append(
            f'<asset-clip name="{i}" offset="{i * 10}/24s" '
            f'duration="5/24s"/>'
        )
    for start, end, name in TRANSITIONS:
        parts.append(
            f'<transition name="{escape(name)}" offset="{start}/24s" '
            f'duration="{end-start}/24s"/>'
        )
    for index in range(1, 117):
        start, end, text, lane = caption_spec(index)
        parts.append(
            f'<title name="VC Caption {index:04d} - {escape(text)}" '
            f'lane="{lane}" offset="{start}/24s" duration="{end-start}/24s"/>'
        )
    parts.append('</spine></sequence></project></event></library></fcpxml>')
    return "".join(parts).encode("utf-8")


class FakeMediaPool:
    def __init__(self, project, imported):
        self.project = project
        self.imported = imported
        self.calls = 0

    def ImportTimelineFromFile(self, path):
        self.calls += 1
        self.project.timelines.append(self.imported)
        return self.imported


class FakeProject:
    def __init__(self, timelines, imported):
        self.timelines = list(timelines)
        self.current = self.timelines[0]
        self.media_pool = FakeMediaPool(self, imported)

    def GetName(self): return runtime.EXPECTED_PROJECT
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetCurrentTimeline(self): return self.current
    def SetCurrentTimeline(self, timeline):
        self.current = timeline
        return True
    def GetMediaPool(self): return self.media_pool


class FakeManager:
    def __init__(self, project): self.project = project
    def GetCurrentProject(self): return self.project


class FakeResolve:
    def __init__(self, project): self.manager = FakeManager(project)
    def GetProjectManager(self): return self.manager


def source_timeline():
    return FakeTimeline(
        runtime.SOURCE_TIMELINE_NAME,
        {1: [FakeItem(str(i), i * 10, i * 10 + 5) for i in range(22)],
         2: [FakeItem(f"source-{i}", i, i + 1) for i in range(116)]},
    )


def context(tmp_path):
    root = tmp_path
    fcpxml = root / runtime.FCPXML_REL
    fcpxml.parent.mkdir(parents=True, exist_ok=True)
    fcpxml.write_bytes(make_fcpxml())
    runtime.FCPXML_SHA256 = runtime.sha256(fcpxml)
    report_dir = ".agent/reports/test/run"
    return {
        "run_id": "run",
        "command": {
            "task": runtime.TASK_ID,
            "run_id": "run",
            "mode": runtime.MODE,
            "payload": {
                "repository_root": str(root),
                "report_dir": report_dir,
                "fcpxml_path": runtime.FCPXML_REL,
                "import_permitted": True,
            },
        },
    }


def test_imports_new_timeline_with_resolve_reordered_tracks(tmp_path):
    imported = make_imported()
    source = source_timeline()
    project = FakeProject([source], imported)
    before = runtime.timeline_snapshot(source)
    result = runtime.run(FakeResolve(project), context(tmp_path))
    assert result["ok"], result["failures"]
    assert result["classification"] == "NEW_TIMELINE_IMPORTED"
    assert result["import_call_count"] == 1
    assert result["base_video_item_count"] == 22
    assert result["base_video_track_indices"] == [6]
    assert result["transition_item_count"] == 11
    assert result["transition_track_indices"] == [6]
    assert result["caption_track_indices"] == [1, 2, 3, 4, 5]
    assert result["caption_item_count"] == 116
    assert runtime.timeline_snapshot(source) == before
    assert project.current is imported


def test_existing_matching_timeline_is_reused_without_second_import(tmp_path):
    imported = make_imported()
    project = FakeProject([source_timeline(), imported], imported)
    result = runtime.run(FakeResolve(project), context(tmp_path))
    assert result["ok"], result["failures"]
    assert result["classification"] == "ALREADY_IMPORTED_MATCHED"
    assert result["import_call_count"] == 0
    assert project.media_pool.calls == 0
    assert project.current is imported


def test_rejects_duplicate_imported_timeline(tmp_path):
    imported = make_imported()
    project = FakeProject([source_timeline(), imported, make_imported()], imported)
    result = runtime.run(FakeResolve(project), context(tmp_path))
    assert not result["ok"]
    assert "duplicate_imported_timeline" in result["failures"][0]


def test_rejects_missing_caption_window(tmp_path):
    imported = make_imported()
    imported.video_tracks[1].pop()
    project = FakeProject([source_timeline()], imported)
    result = runtime.run(FakeResolve(project), context(tmp_path))
    assert not result["ok"]
    assert "caption_window_match" in result["failures"][0]


def test_rejects_wrong_target_window(tmp_path):
    imported = make_imported()
    target = next(
        item for track in imported.video_tracks.values()
        for item in track if "0052" in item.name
    )
    target.end = 451
    project = FakeProject([source_timeline()], imported)
    result = runtime.run(FakeResolve(project), context(tmp_path))
    assert not result["ok"]
    assert "caption_window_match:430:452:0" in result["failures"][0]


def test_rejects_missing_transition_item(tmp_path):
    imported = make_imported()
    imported.video_tracks[6] = [
        item for item in imported.video_tracks[6]
        if not (item.name == "Cross Dissolve" and item.start == 92)
    ]
    project = FakeProject([source_timeline()], imported)
    result = runtime.run(FakeResolve(project), context(tmp_path))
    assert not result["ok"]
    assert "transition_window_match:92:100:0" in result["failures"][0]


def test_rejects_unexpected_video_item(tmp_path):
    imported = make_imported()
    imported.video_tracks[6].append(FakeItem("unexpected", 9000, 9001))
    project = FakeProject([source_timeline()], imported)
    result = runtime.run(FakeResolve(project), context(tmp_path))
    assert not result["ok"]
    assert "unexpected_video_items:1" in result["failures"][0]
