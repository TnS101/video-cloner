from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_media_backed_fusion_clone.py"
PUBLISHER_PATH = ROOT / "scripts" / "davinci" / "prepare_step_3D_media_backed_fusion_clone.py"
VALIDATOR_PATH = ROOT / "scripts" / "davinci" / "validate_step_3D_media_backed_fusion_clone.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load(MODULE_PATH, "media_fusion_probe")
publisher = load(PUBLISHER_PATH, "media_fusion_publisher")
validator = load(VALIDATOR_PATH, "media_fusion_validator")
base = probe.base


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


class FakeMediaPoolItem:
    def __init__(self, name="proxy.mp4"):
        self.name = name

    def GetName(self):
        return self.name


class FakeItem:
    def __init__(self, name, start, end, track, duration=None, comp=None, media=True):
        self.name = name
        self.start = start
        self.end = end
        self.track = track
        self.duration = duration if duration is not None else end - start
        self.uid = f"uid-{track}-{start}-{name}"
        self.comp = comp
        self.media = FakeMediaPoolItem() if media else None

    def GetName(self): return self.name
    def SetName(self, name): self.name = name; return True
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.duration
    def GetUniqueId(self): return self.uid
    def GetMediaPoolItem(self): return self.media
    def GetFusionCompCount(self): return 1 if self.comp else 0
    def GetFusionCompByIndex(self, index): return self.comp if index == 1 else None
    def GetFusionCompNameList(self): return ["Composition 1"] if self.comp else []
    def ImportFusionComp(self, _path): return self.comp


class FakeTimeline:
    def __init__(self, items_by_track):
        self.items_by_track = {int(key): list(value) for key, value in items_by_track.items()}

    def GetTrackCount(self, kind):
        return max(self.items_by_track, default=0) if kind == "video" else 0

    def GetItemListInTrack(self, kind, index):
        return list(self.items_by_track.get(index, [])) if kind == "video" else []


class FakeMediaPool:
    def __init__(self, timeline, returned_items):
        self.timeline = timeline
        self.returned_items = list(returned_items)
        self.received = None

    def AppendToTimeline(self, clip_infos):
        self.received = clip_infos
        for item in self.returned_items:
            self.timeline.items_by_track.setdefault(item.track, []).append(item)
        return list(self.returned_items)


def test_contract_uses_media_append_and_import_only():
    assert probe.TASK_ID == "DZSQH7AUHJT_STEP_3D_MEDIA_BACKED_FUSION_CLONE_V1"
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert '"AppendToTimeline"' in source
    assert '"ImportFusionComp"' in source
    assert '"AddFusionComp"' not in source
    assert "InsertFusionCompositionIntoTimeline" not in source
    assert "InsertFusionTitleIntoTimeline" not in source


def test_placement_accepts_exclusive_end_even_with_inconsistent_duration():
    summary = {"track_index": 3, "start": 430, "end": 452, "duration": 999}
    assert probe.placement_ok(summary, probe.TARGETS[0]) is True


def test_placement_accepts_inclusive_end():
    summary = {"track_index": 5, "start": 437, "end": 451, "duration": 15}
    assert probe.placement_ok(summary, probe.TARGETS[1]) is True


def test_placement_rejects_wrong_track_or_start():
    spec = probe.TARGETS[0]
    assert probe.placement_ok({"track_index": 4, "start": 430, "end": 452}, spec) is False
    assert probe.placement_ok({"track_index": 3, "start": 431, "end": 452}, spec) is False


def test_append_assigns_returned_items_by_order_and_names_them():
    timeline = FakeTimeline({1: []})
    first = FakeItem("proxy", 430, 452, 3, duration=23)
    second = FakeItem("proxy", 437, 451, 5, duration=14)
    media_pool = FakeMediaPool(timeline, [first, second])
    source = {"media_pool_item": FakeMediaPoolItem(), "source_start": 0}

    result = probe.append_carriers_by_return_order(media_pool, timeline, source, probe.TARGETS)

    assert result["ok"] is True
    assert result["detection_method"] == "return_value_order"
    assert result["returned_count"] == 2
    assert result["assigned_count"] == 2
    assert first.GetName() == probe.TARGETS[0]["name"]
    assert second.GetName() == probe.TARGETS[1]["name"]


def test_append_payload_uses_exact_tracks_ranges_and_inclusive_source_end():
    timeline = FakeTimeline({1: []})
    returned = [
        FakeItem("a", 430, 452, 3),
        FakeItem("b", 437, 452, 5),
    ]
    media_pool = FakeMediaPool(timeline, returned)
    source_item = FakeMediaPoolItem()
    result = probe.append_carriers_by_return_order(
        media_pool,
        timeline,
        {"media_pool_item": source_item, "source_start": 10},
        probe.TARGETS,
    )
    assert result["ok"] is True
    assert media_pool.received == [
        {
            "mediaPoolItem": source_item,
            "startFrame": 10,
            "endFrame": 31,
            "mediaType": 1,
            "trackIndex": 3,
            "recordFrame": 430,
        },
        {
            "mediaPoolItem": source_item,
            "startFrame": 10,
            "endFrame": 24,
            "mediaType": 1,
            "trackIndex": 5,
            "recordFrame": 437,
        },
    ]


def test_append_records_candidates_when_placement_fails():
    timeline = FakeTimeline({1: []})
    wrong = [FakeItem("a", 500, 522, 3), FakeItem("b", 437, 452, 5)]
    result = probe.append_carriers_by_return_order(
        FakeMediaPool(timeline, wrong),
        timeline,
        {"media_pool_item": FakeMediaPoolItem(), "source_start": 0},
        probe.TARGETS,
    )
    assert result["ok"] is False
    assert result["returned_count"] == 2
    assert result["rows"][0]["placement_ok"] is False
    assert result["returned_candidates"][0]["summary"]["start"] == 500


def test_import_source_comp_accepts_real_comp_handle(tmp_path):
    comp = FakeComp("COME", {0: [0.4324, 0.6292], 3: [0.5, 0.6276]})
    item = FakeItem("carrier", 430, 452, 3, comp=comp)
    path = tmp_path / "come.comp"
    path.write_text("composition", encoding="utf-8")
    result = probe.import_source_comp(item, path)
    assert result["ok"] is True
    assert result["strategy"] == "ImportFusionComp_only"
    assert result["after_count"] == 1


def test_import_source_comp_rejects_missing_comp(tmp_path, monkeypatch):
    item = FakeItem("carrier", 430, 452, 3, comp=None)
    path = tmp_path / "come.comp"
    path.write_text("composition", encoding="utf-8")
    monkeypatch.setattr(base.time, "sleep", lambda _seconds: None)
    result = probe.import_source_comp(item, path)
    assert result["ok"] is False
    assert result["after_count"] == 0


def test_publisher_has_complete_seven_file_contract(tmp_path, monkeypatch):
    root = tmp_path
    (root / "AGENTS.md").write_text("rules", encoding="utf-8")
    for relative in publisher.SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    accepted = root / publisher.ACCEPTED_STATE
    accepted.parent.mkdir(parents=True, exist_ok=True)
    accepted.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(publisher, "run_id_now", lambda: "RUN_123456789012")

    receipt = publisher.publish(root)
    command = json.loads(Path(receipt["command_path"]).read_text(encoding="utf-8"))

    assert len(command["source_contract"]["hashes"]) == 7
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
    pending.write_text("{}", encoding="utf-8")

    def fake_sleep(_seconds):
        pending.rename(queue / "completed" / name)

    monkeypatch.setattr(validator.time, "sleep", fake_sleep)
    state, path, evidence = validator.wait_for_terminal(root, run_id, 2, 0.01)
    assert state == "completed"
    assert path.name == name
    assert evidence["timed_out"] is False


def test_required_success_artifacts_cover_append_import_and_persistence():
    assert "carrier_append.json" in validator.REQUIRED_SUCCESS_ARTIFACTS
    assert "comp_clone_application.json" in validator.REQUIRED_SUCCESS_ARTIFACTS
    assert "persistent_readback.json" in validator.REQUIRED_SUCCESS_ARTIFACTS
