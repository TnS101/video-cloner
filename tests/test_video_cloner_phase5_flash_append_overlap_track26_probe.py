from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

SOURCE_ROOT = Path.cwd()
ROOT = Path(os.environ.get("VC_STAGED_ROOT", Path(__file__).resolve().parents[1]))


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runtime = load(ROOT / "resolve_workspace/modules/video_cloner_phase5_flash_append_overlap_track26_probe.py", "track26_probe")
prepare = load(ROOT / "scripts/davinci/prepare_video_cloner_phase5_flash_append_overlap_track26_probe.py", "track26_prepare")
validate = load(ROOT / "scripts/davinci/validate_video_cloner_phase5_flash_append_overlap_track26_probe.py", "track26_validate")
v1 = load(SOURCE_ROOT / "resolve_workspace/modules/advanced_transition_flash_application_v1.py", "track26_v1")


class Media:
    def __init__(self, name="VC_FLASH_NEUTRAL_RGBA_V4"):
        self.name = name

    def GetName(self):
        return self.name


class Item:
    serial = 0

    def __init__(self, start, end, track, media=None, name="", rename_ok=True, uid=None):
        Item.serial += 1
        self.start, self.end, self.track = start, end, track
        self.media, self.name, self.rename_ok = media, name, rename_ok
        self.uid = uid or f"item-{Item.serial}"

    def GetUniqueId(self): return self.uid
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.end - self.start
    def GetName(self): return self.name
    def GetMediaPoolItem(self): return self.media
    def SetName(self, name):
        if self.rename_ok: self.name = name
        return self.rename_ok
    def SetClipName(self, name): return self.SetName(name)
    def SetProperty(self, key, value): return self.SetName(value) if key == "Name" else False


class Timeline:
    serial = 0

    def __init__(self, name, items=None, tracks=1):
        Timeline.serial += 1
        self.name, self.items, self.tracks = name, list(items or []), tracks
        self.uid = f"timeline-{Timeline.serial}"

    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetTrackCount(self, kind): return self.tracks if kind == "video" else 0
    def GetItemListInTrack(self, kind, index):
        return [item for item in self.items if kind == "video" and item.track == index]
    def AddTrack(self, kind):
        if kind != "video": return False
        self.tracks += 1
        return True


class Project:
    def __init__(self, timelines):
        self.timelines = timelines
        self.current = timelines[-1]

    def GetName(self): return runtime.PROJECT_NAME
    def GetMediaPool(self): return self.pool
    def GetCurrentTimeline(self): return self.current
    def SetCurrentTimeline(self, timeline): self.current = timeline; return True
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]


class Pool:
    def __init__(self, project, behavior="overlap_reject", delete_timeline_ok=True):
        self.project, self.behavior = project, behavior
        self.delete_timeline_ok = delete_timeline_ok
        self.deleted_media = []

    def CreateEmptyTimeline(self, name):
        timeline = Timeline(name)
        self.project.timelines.append(timeline)
        return timeline

    def DeleteTimelines(self, timelines):
        if not self.delete_timeline_ok: return False
        self.project.timelines = [row for row in self.project.timelines if row not in timelines]
        return True

    def DeleteClips(self, items):
        self.deleted_media.extend(items)
        return True

    def AppendToTimeline(self, rows):
        timeline = self.project.current
        returned = []
        for row in rows:
            start = int(row["recordFrame"])
            duration = int(row["endFrame"]) - int(row["startFrame"])
            occupied = any(item.track == row["trackIndex"] and item.start < start + duration and start < item.end for item in timeline.items)
            if self.behavior == "empty_fail" or (self.behavior == "overlap_reject" and occupied):
                return None
            rename_ok = self.behavior != "helper_defect"
            item = Item(start, start + duration, row["trackIndex"], row["mediaPoolItem"], rename_ok=rename_ok)
            timeline.items.append(item)
            returned.append(item)
        return returned


class Manager:
    def __init__(self, project): self.project, self.saved = project, 0
    def GetCurrentProject(self): return self.project
    def SaveProject(self): self.saved += 1; return True


class Resolve:
    def __init__(self, manager): self.manager = manager
    def GetProjectManager(self): return self.manager


class P4B:
    @staticmethod
    def timeline_name(timeline): return timeline.GetName() if timeline else ""

    @staticmethod
    def timeline_inventory(project):
        return [
            {
                "name": timeline.name,
                "signature": tuple((item.track, item.start, item.end, item.name, item.media is not None) for item in timeline.items),
            }
            for timeline in project.timelines
        ]


class V4:
    def __init__(self, ownership): self.ownership = ownership
    def validate_neutral_assets(self, root): return {"ok": True}
    def import_neutral_carrier(self, pool, root, assets):
        return {"ok": True, "item": self.ownership, "ownership_classification": self.kind,
                "rollback_delete_permitted": self.kind == "NEWLY_CREATED"}
    def _delete_owned_media_pool_item(self, pool, ownership):
        permitted = ownership and ownership.get("ownership_classification") == "NEWLY_CREATED" and ownership.get("rollback_delete_permitted") is True
        if not permitted: return {"permitted": False, "attempted": False, "ok": True, "deleted": 0}
        ok = pool.DeleteClips([ownership["item"]])
        return {"permitted": True, "attempted": True, "ok": ok, "deleted": int(ok)}


def command(tmp_path):
    rid = "probe-run"
    return {
        "task_id": runtime.TASK_ID,
        "run_id": rid,
        "mode": runtime.MODE,
        "report_path": f".agent/reports/{runtime.TASK_ID}/{rid}/report.json",
        "source_contract": {"algorithm": "sha256_text_lf_normalized", "hashes": {"unused": "unused"}},
        "payload": {"expected_project": runtime.PROJECT_NAME, "disposable_timeline_name": "VC_PHASE5_TRACK26_PROBE_fixture",
                    "track_index": 26, "record_frame": 94, "duration_frames": 4},
    }


def run_case(tmp_path, monkeypatch, behavior="overlap_reject", ownership="NEWLY_CREATED", delete_timeline_ok=True):
    media = Media()
    orphans = [Item(start, end, 26, None, "VC_FLASH_NEUTRAL_RGBA_V4", uid=f"orphan-{start}") for start, end in ((94, 98), (375, 379), (424, 428), (452, 456), (756, 760))]
    reel1 = Timeline(runtime.REEL1, orphans, tracks=26)
    unrelated = Timeline("unrelated", [Item(10, 20, 1, Media("other"), "other")])
    reel2 = Timeline(runtime.REEL2, [Item(0, 854, 1, Media("reel2"), "Reel2")])
    project = Project([reel1, unrelated, reel2])
    pool = Pool(project, behavior, delete_timeline_ok)
    project.pool = pool
    manager = Manager(project)
    fake_v4 = V4(media)
    fake_v4.kind = ownership
    monkeypatch.setattr(runtime, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(v1, "verify_source_contract", lambda root, value: {"ok": True, "verified_count": 5})
    before = P4B.timeline_inventory(project)
    result = runtime.execute(Resolve(manager), {"command": command(tmp_path), "run_id": "probe-run"}, (v1, fake_v4, P4B))
    return result, project, pool, manager, media, before


def test_empty_track26_succeeds_and_identical_overlap_is_rejected(tmp_path, monkeypatch):
    result, *_ = run_case(tmp_path, monkeypatch)
    assert result["ok"] is True
    assert result["classification"] == "SAME_TRACK_DESTINATION_OVERLAP_CONFIRMED"
    assert result["append_evidence"]["first_append"]["ok"] is True
    assert result["append_evidence"]["second_append"]["ok"] is False


def test_empty_track26_failure_is_decisive(tmp_path, monkeypatch):
    result, *_ = run_case(tmp_path, monkeypatch, behavior="empty_fail")
    assert result["ok"] is True
    assert result["classification"] == "TRACK26_EMPTY_APPEND_FAILED"
    assert "second_append" not in result["append_evidence"]


def test_api_creation_with_helper_rename_failure_is_classified(tmp_path, monkeypatch):
    result, *_ = run_case(tmp_path, monkeypatch, behavior="helper_defect")
    assert result["ok"] is True
    assert result["classification"] == "APPEND_HELPER_POST_API_CLASSIFICATION_DEFECT"
    assert result["append_evidence"]["first_append"]["call"]["ok"] is True
    assert len(result["append_evidence"]["after_first"]) == 1


def test_both_overlapping_appends_succeed(tmp_path, monkeypatch):
    result, *_ = run_case(tmp_path, monkeypatch, behavior="both_succeed")
    assert result["ok"] is True
    assert result["classification"] == "OVERLAP_APPEND_SUCCEEDED"
    assert len(result["append_evidence"]["after_second"]) == 2


def test_disposable_timeline_is_removed(tmp_path, monkeypatch):
    result, project, _, manager, *_ = run_case(tmp_path, monkeypatch)
    assert result["cleanup"]["disposable_timeline_deleted"] is True
    assert all(not timeline.name.startswith("VC_PHASE5_TRACK26_PROBE_") for timeline in project.timelines)
    assert result["save_project_count"] == manager.saved == 0


def test_previous_current_timeline_is_restored(tmp_path, monkeypatch):
    result, project, *_ = run_case(tmp_path, monkeypatch)
    assert result["cleanup"]["previous_current_timeline_restored"] is True
    assert project.current.name == runtime.REEL2


def test_newly_created_media_is_deleted_after_timeline_cleanup(tmp_path, monkeypatch):
    result, _, pool, _, media, _ = run_case(tmp_path, monkeypatch)
    assert result["cleanup"]["media_delete"]["attempted"] is True
    assert pool.deleted_media == [media]


def test_preexisting_compatible_media_is_preserved(tmp_path, monkeypatch):
    result, _, pool, *_ = run_case(tmp_path, monkeypatch, ownership="PREEXISTING_COMPATIBLE")
    assert result["ok"] is True
    assert result["cleanup"]["media_delete"]["attempted"] is False
    assert pool.deleted_media == []


def test_all_non_probe_timelines_are_unchanged(tmp_path, monkeypatch):
    result, project, _, _, _, before = run_case(tmp_path, monkeypatch)
    assert result["cleanup"]["protected_timelines_unchanged"] is True
    assert P4B.timeline_inventory(project) == before


def test_reel1_orphans_and_reel2_are_unchanged(tmp_path, monkeypatch):
    _, project, _, _, _, before = run_case(tmp_path, monkeypatch)
    after = P4B.timeline_inventory(project)
    for name in (runtime.REEL1, runtime.REEL2):
        assert next(row for row in before if row["name"] == name) == next(row for row in after if row["name"] == name)


def test_ambiguous_cleanup_fails_closed_without_media_delete_or_save(tmp_path, monkeypatch):
    result, _, pool, manager, _, _ = run_case(tmp_path, monkeypatch, delete_timeline_ok=False)
    assert result["ok"] is False
    assert result["classification"] == "AMBIGUOUS_CLEANUP_STATE"
    assert pool.deleted_media == []
    assert manager.saved == 0


def test_preparer_publishes_one_bounded_command(tmp_path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("test\n", encoding="utf-8")
    for relative in prepare.SOURCE_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    receipt = prepare.prepare(tmp_path, "fixed-run")
    queued = tmp_path / receipt["command_path"]
    payload = json.loads(queued.read_text(encoding="utf-8"))
    assert payload["payload"]["track_index"] == 26
    assert payload["payload"]["record_frame"] == 94
    assert payload["payload"]["cleanup_required"] is True
    assert receipt["resolve_executions"] == 0


def test_validator_accepts_each_decisive_clean_result(tmp_path):
    run_id = "validated"
    directory = tmp_path / ".agent/reports" / validate.TASK_ID / run_id
    directory.mkdir(parents=True)
    report = {"ok": True, "task_id": validate.TASK_ID, "mode": validate.MODE, "run_id": run_id,
              "classification": "SAME_TRACK_DESTINATION_OVERLAP_CONFIRMED",
              "probe_classification": "SAME_TRACK_DESTINATION_OVERLAP_CONFIRMED", "save_project_count": 0,
              "append_evidence": {"first_append": {}, "track_provisioning": {"final_video_track_count": 26}},
              "cleanup": {"disposable_timeline_deleted": True, "previous_current_timeline_restored": True,
                          "protected_timelines_unchanged": True, "media_delete": {"ok": True}, "safe": True}}
    for name in validate.REQUIRED:
        (directory / name).write_text(json.dumps(report) if name.endswith(".json") else "evidence", encoding="utf-8")
    assert validate.validate(tmp_path, run_id)["ok"] is True
