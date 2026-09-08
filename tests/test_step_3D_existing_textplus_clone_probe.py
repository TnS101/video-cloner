from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_existing_textplus_clone_probe.py"
PUBLISHER_PATH = ROOT / "scripts" / "davinci" / "prepare_step_3D_existing_textplus_clone_probe.py"
VALIDATOR_PATH = ROOT / "scripts" / "davinci" / "validate_step_3D_existing_textplus_clone_probe.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load(MODULE_PATH, "probe_module")
publisher = load(PUBLISHER_PATH, "probe_publisher")
validator = load(VALIDATOR_PATH, "probe_validator")


class FakeInput:
    def __init__(self, values):
        self.values = dict(values)

    def __getitem__(self, frame):
        return self.values.get(frame)

    def GetAttrs(self):
        return {"INPS_ID": "Center", "INPS_Name": "Center"}


class FakeTextTool:
    def __init__(self, text, centers):
        self.text = text
        self.center = FakeInput(centers)

    def GetAttrs(self):
        return {"TOOLS_RegID": "TextPlus"}

    def FindInput(self, name):
        return self.center if name == "Center" else None

    def GetInput(self, name, frame):
        if name == "StyledText":
            return self.text
        if name == "Center":
            return self.center[frame]
        return None


class FakeComp:
    def __init__(self, text, centers):
        self.tool = FakeTextTool(text, centers)

    def GetToolList(self, _selected=False, regid=None):
        if regid in (None, "TextPlus"):
            return {"Text1": self.tool}
        return {}

    def CopySettings(self):
        return {"text": self.tool.text, "centers": dict(self.tool.center.values)}

    def Paste(self, settings):
        self.tool = FakeTextTool(settings["text"], settings["centers"])
        return True


class FakeMediaPoolItem:
    def GetName(self):
        return "source.mov"


class FakeItem:
    def __init__(self, name, start, end, track, text="", centers=None, media=True):
        self.name = name
        self.start = start
        self.end = end
        self.track = track
        self.uid = f"uid-{name}-{start}-{track}"
        self.media = FakeMediaPoolItem() if media else None
        self.comp = FakeComp(text, centers or {}) if text else None

    def GetName(self): return self.name
    def SetName(self, name): self.name = name; return True
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.end - self.start
    def GetUniqueId(self): return self.uid
    def GetMediaPoolItem(self): return self.media
    def GetLeftOffset(self): return 0
    def GetFusionCompCount(self): return 1 if self.comp else 0
    def GetFusionCompByIndex(self, index): return self.comp if index == 1 else None
    def GetFusionCompNameList(self): return ["Composition 1"] if self.comp else []
    def ExportFusionComp(self, path, index): Path(path).write_text("comp"); return index == 1
    def ImportFusionComp(self, _path):
        return self.comp
    def AddFusionComp(self):
        self.comp = FakeComp("", {})
        return self.comp


class FakeTimeline:
    def __init__(self, name, items_by_track):
        self.name = name
        self.items_by_track = {int(k): list(v) for k, v in items_by_track.items()}
        self.uid = f"timeline-{name}"

    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetTrackCount(self, kind): return max(self.items_by_track, default=0) if kind == "video" else 0
    def GetItemListInTrack(self, kind, index): return list(self.items_by_track.get(index, [])) if kind == "video" else []
    def AddTrack(self, kind):
        assert kind == "video"
        self.items_by_track[self.GetTrackCount("video") + 1] = []
        return True
    def DeleteClips(self, items, _ripple):
        for track in self.items_by_track:
            self.items_by_track[track] = [item for item in self.items_by_track[track] if item not in items]
        return True


def test_target_contract_matches_calibrated_windows_and_lanes():
    come, they = probe.TARGETS
    assert come["target_range"] == [430, 452]
    assert come["target_track"] == 3
    assert come["center_targets"] == [
        {"frame": 0, "value": [0.4324, 0.6292]},
        {"frame": 3, "value": [0.5, 0.6276]},
    ]
    assert they["target_range"] == [437, 452]
    assert they["target_track"] == 5
    assert they["center_targets"] == [{"frame": 0, "value": [0.494, 0.532]}]


def test_visual_readback_accepts_expected_text_and_center_targets():
    item = FakeItem("x", 430, 452, 3, "COME", {0: {1: 0.4324, 2: 0.6292}, 3: [0.5, 0.6276]})
    result = probe.visual_readback(item, probe.TARGETS[0])
    assert result["text_matched"] is True
    assert result["center_targets_matched"] is True


def test_visual_readback_rejects_missing_animation_target():
    item = FakeItem("x", 430, 452, 3, "COME", {0: [0.4324, 0.6292]})
    result = probe.visual_readback(item, probe.TARGETS[0])
    assert result["center_targets_matched"] is False


def test_ensure_video_tracks_adds_only_required_tracks():
    timeline = FakeTimeline("t", {1: [], 2: [], 3: []})
    result = probe.ensure_video_tracks(timeline, 5)
    assert result["ok"] is True
    assert result["final_count"] == 5
    assert len(result["attempts"]) == 2


def test_delete_items_removes_only_requested_items():
    keep = FakeItem("keep", 0, 1, 3)
    remove = FakeItem("VC_TEXTPLUS_0001_sub_001", 1, 2, 3)
    timeline = FakeTimeline("t", {3: [keep, remove]})
    result = probe.delete_items(timeline, [remove])
    assert result["ok"] is True
    assert timeline.GetItemListInTrack("video", 3) == [keep]


def test_choose_carrier_source_uses_media_backed_v1_item():
    short = FakeItem("short", 0, 10, 1)
    long = FakeItem("long", 10, 50, 1)
    timeline = FakeTimeline("t", {1: [short, long]})
    result = probe.choose_carrier_source(timeline, 22)
    assert result["ok"] is True
    assert result["item"] is long


def test_source_snapshot_requires_exact_named_items():
    come = FakeItem(probe.TARGETS[0]["name"], 430, 434, 3, "COME", {0: [0.4324, 0.6292], 3: [0.5, 0.6276]})
    they = FakeItem(probe.TARGETS[1]["name"], 439, 443, 3, "they", {0: [0.494, 0.532]})
    timeline = FakeTimeline("source", {3: [come, they]})
    snapshot = probe.source_item_snapshot(timeline, probe.TARGETS)
    assert [row["found"] for row in snapshot["rows"]] == [True, True]
    assert all(row["visual"]["center_targets_matched"] for row in snapshot["rows"])


def test_apply_source_comp_prefers_imported_comp(tmp_path):
    source = FakeItem("source", 0, 1, 3, "COME", {0: [0.5, 0.5]})
    target = FakeItem("target", 0, 1, 3, "COME", {0: [0.5, 0.5]})
    path = tmp_path / "source.comp"
    path.write_text("comp")
    result = probe.apply_source_comp(source, target, path)
    assert result["ok"] is True
    assert result["strategy"] == "ImportFusionComp"


def test_publisher_targets_fresh_probe_timeline(tmp_path, monkeypatch):
    root = tmp_path
    (root / "AGENTS.md").write_text("rules")
    for relative in publisher.SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    accepted = root / publisher.ACCEPTED_STATE
    accepted.parent.mkdir(parents=True, exist_ok=True)
    accepted.write_text("{}")
    monkeypatch.setattr(publisher, "run_id_now", lambda: "RUN_123456789012")
    receipt = publisher.publish(root)
    command = json.loads(Path(receipt["command_path"]).read_text())
    assert command["probe"]["keep_on_success"] is True
    assert command["probe"]["cleanup_on_failure"] is True
    assert command["probe"]["timeline_name"].endswith("123456789012")


def test_validator_waits_for_terminal_state(tmp_path, monkeypatch):
    root = tmp_path
    run_id = "run"
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    name = validator.command_name(run_id)
    pending = queue / "pending" / name
    pending.write_text("{}")
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


def test_required_success_artifacts_include_persistent_readback():
    assert "persistent_readback.json" in validator.REQUIRED_SUCCESS_ARTIFACTS
    assert "comp_clone_application.json" in validator.REQUIRED_SUCCESS_ARTIFACTS


def test_source_contract_has_six_runtime_dependencies():
    assert len(publisher.SOURCE_PATHS) == 6
    assert probe.BRIDGE_RELATIVE_PATH in publisher.SOURCE_PATHS
    assert probe.LIFECYCLE_PLAN_RELATIVE_PATH in publisher.SOURCE_PATHS


def test_item_track_index_uses_unique_id_across_rewrapped_handles():
    original = FakeItem("x", 0, 10, 4)
    wrapped = FakeItem("x", 0, 10, 4)
    wrapped.uid = original.uid
    timeline = FakeTimeline("t", {4: [wrapped]})
    assert probe.item_track_index(timeline, original) == 4


def test_source_unchanged_ignores_raw_point_representation_when_contract_matches():
    before = {
        "rows": [{
            "name": "VC_TEXTPLUS_0052_sub_052",
            "found": True,
            "summary": {"unique_id": "u", "track_index": 3, "start": 430, "end": 434, "duration": 4, "fusion_comp_count": 1},
            "visual": {"text_matched": True, "center_targets_matched": True, "center_targets": [{"actual": [0.5, 0.6]}]},
        }]
    }
    after = {
        "rows": [{
            "name": "VC_TEXTPLUS_0052_sub_052",
            "found": True,
            "summary": {"unique_id": "u", "track_index": 3, "start": 430, "end": 434, "duration": 4, "fusion_comp_count": 1},
            "visual": {"text_matched": True, "center_targets_matched": True, "center_targets": [{"actual": {1: 0.5, 2: 0.6}}]},
        }]
    }
    assert probe.source_unchanged(before, after) is True
