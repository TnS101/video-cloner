from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("inplace_restore", ROOT / "resolve_workspace/modules/video_cloner_phase5_reel1_flash_v4_orphan_restoration.py")
runtime = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(runtime)


class Media:
    def __init__(self, uid=runtime.EXPECTED_MEDIA_UID, path=runtime.EXPECTED_MEDIA_PATH):
        self.uid, self.path = uid, path

    def GetUniqueId(self): return self.uid
    def GetName(self): return runtime.EXPECTED_MEDIA_NAME
    def GetClipProperty(self): return {"File Path": self.path, "Video Frame Rate": "24", "Alpha mode": "Straight"}


class Item:
    def __init__(self, start, end, *, name=runtime.EXPECTED_MEDIA_NAME, media=None, uid=None):
        self.start, self.end, self.name = start, end, name
        self.media, self.uid, self.comps = media or Media(), uid or f"item:{start}", []

    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.end - self.start
    def GetLeftOffset(self): return 0
    def GetName(self): return self.name
    def SetName(self, name): self.name = name; return True
    def GetMediaPoolItem(self): return self.media
    def GetFusionCompCount(self): return len(self.comps)
    def GetFusionCompNameList(self): return list(self.comps)
    def GetUniqueId(self): return self.uid
    def GetProperty(self): return {}
    def AddFusionComp(self): self.comps.append(f"Composition {len(self.comps) + 1}"); return object()
    def DeleteFusionCompByName(self, name): self.comps.remove(name); return True


class Timeline:
    def __init__(self, name, items): self.name, self.items = name, list(items)
    def GetName(self): return self.name
    def GetTrackCount(self, kind): return 26 if kind == "video" else 0
    def GetItemListInTrack(self, kind, index): return self.items if kind == "video" and index == 26 else []


class Project:
    def __init__(self, target, historical, reel2, switch_ok=True):
        self.timelines = [historical, target, reel2]
        self.target, self.current, self.switch_ok, self.set_calls = target, reel2, switch_ok, []

    def GetName(self): return runtime.PROJECT_NAME
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetCurrentTimeline(self): return self.current
    def GetMediaPool(self): return object()
    def SetCurrentTimeline(self, timeline):
        self.set_calls.append(timeline)
        if timeline is self.target and not self.switch_ok: return False
        self.current = timeline
        return True


class Manager:
    def __init__(self, project): self.project, self.save_count = project, 0
    def GetCurrentProject(self): return self.project
    def SaveProject(self): self.save_count += 1; return True


class Resolve:
    def __init__(self, manager): self.manager = manager
    def GetProjectManager(self): return self.manager


def carriers():
    return [Item(start, end) for start, end in runtime.EXPECTED_SPANS]


def plan():
    return {"flashes": [{"name": f"VC_FLASH_{index:03d}_frame_{start + 2:04d}", "start_frame": start, "duration_frames": 4}
                        for index, (start, _) in enumerate(runtime.EXPECTED_SPANS, 1)]}


def command():
    return {"run_id": "test-run", "command": {"task": runtime.TASK_ID, "mode": runtime.MODE, "run_id": "test-run",
            "payload": {"expected_project": runtime.PROJECT_NAME, "target_timeline_name": runtime.TARGET_TIMELINE_NAME,
                        "repository_root": str(ROOT), "accepted_plan": plan(), "accepted_plan_file_sha256": runtime.EXPECTED_PLAN_SHA256,
                        "prerequisite_report": {"path": "proof.json", "sha256": runtime.EXPECTED_PREREQUISITE_SHA256}, "read_only": False}}}


def simulate(monkeypatch, fail_at=None, switch_ok=True):
    target_items = carriers()
    historical_item = Item(426, 454, uid="historical")
    historical = Timeline(runtime.HISTORICAL_TIMELINE_NAME, [historical_item])
    target = Timeline(runtime.TARGET_TIMELINE_NAME, target_items)
    reel2 = Timeline(runtime.REEL2_TIMELINE_NAME, [Item(0, 854, name="reel2", media=Media(uid="reel2"), uid="reel2")])
    project = Project(target, historical, reel2, switch_ok=switch_ok)
    manager = Manager(project)
    configure_calls = []

    def snapshot(timeline):
        pristine = timeline is target and all(item.name == runtime.EXPECTED_MEDIA_NAME and not item.comps for item in target_items)
        return {"signature": runtime.EXPECTED_PRESTATE_SIGNATURE if pristine else f"signature:{timeline.name}"}

    def inventory(project_arg, target_name):
        rows = [{"name": timeline.name, "signature": snapshot(timeline)["signature"]} for timeline in project_arg.timelines]
        return rows, [row for row in rows if row["name"] != target_name]

    def configure(item, row, index):
        configure_calls.append(item.uid)
        item.AddFusionComp()
        return {"ok": index != fail_at}

    monkeypatch.setattr(runtime.BASE, "validate_plan", lambda value: None)
    monkeypatch.setattr(runtime, "_load_prerequisite", lambda *args: ({}, inventory(project, runtime.TARGET_TIMELINE_NAME)[0]))
    monkeypatch.setattr(runtime.BASE, "non_target_inventory", inventory)
    monkeypatch.setattr(runtime.P4B, "timeline_snapshot", snapshot)
    monkeypatch.setattr(runtime, "_media_and_references", lambda *args, **kwargs: ({"unique_id": runtime.EXPECTED_MEDIA_UID}, [{"id": index} for index in range(6)]))
    monkeypatch.setattr(runtime, "_unaffected_signature", lambda *args: "unaffected")
    monkeypatch.setattr(runtime.BASE.V1, "configure_flash", configure)
    monkeypatch.setattr(runtime.V4, "neutral_flash_snapshot", lambda *args: {"ok": True, "neutral_carrier_count": 5, "source_video_carrier_count": 0})
    for forbidden in ("import_neutral_carrier", "_delete_owned_media_pool_item"):
        monkeypatch.setattr(runtime.V4, forbidden, lambda *args, _name=forbidden, **kwargs: (_ for _ in ()).throw(AssertionError(_name)))
    monkeypatch.setattr(runtime.BASE.V1, "append_flash_carriers", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("append")))
    result = runtime.restore(Resolve(manager), command())
    return result, project, manager, target_items, historical_item, reel2, configure_calls


def test_exact_relinked_zero_fusion_prestate_is_accepted():
    result = runtime.validate_relinked_prestate(Timeline(runtime.TARGET_TIMELINE_NAME, carriers()))
    assert result["ok"] is True
    assert result["classification"] == "RELINKED_ZERO_FUSION_PRESTATE"
    assert result["count"] == 5


def test_missing_extra_wrong_media_and_partial_fusion_fail_closed():
    rows = carriers()
    assert runtime.validate_relinked_prestate(Timeline("target", rows[:-1]))["ok"] is False
    assert runtime.validate_relinked_prestate(Timeline("target", rows + [Item(800, 804)]))["ok"] is False
    rows = carriers(); rows[0].media = Media(uid="wrong")
    assert "carrier_media:94" in runtime.validate_relinked_prestate(Timeline("target", rows))["errors"]
    rows = carriers(); rows[0].comps.append("Composition 1")
    assert "carrier_fusion:94" in runtime.validate_relinked_prestate(Timeline("target", rows))["errors"]


def test_restore_reuses_only_five_target_items_and_protects_other_timelines(monkeypatch):
    result, project, manager, items, historical, reel2, calls = simulate(monkeypatch)
    assert result["ok"] is True
    assert result["classification"] == "RELINKED_INPLACE_FLASH_RESTORED"
    assert calls == [item.uid for item in items]
    assert [item.uid for item in items] == [f"item:{start}" for start, _ in runtime.EXPECTED_SPANS]
    assert [(item.start, item.end, item.media.uid, len(item.comps)) for item in items] == [(start, end, runtime.EXPECTED_MEDIA_UID, 1) for start, end in runtime.EXPECTED_SPANS]
    assert historical.name == runtime.EXPECTED_MEDIA_NAME and historical.comps == []
    assert reel2.items[0].uid == "reel2" and reel2.items[0].comps == []
    assert project.current is reel2 and project.set_calls == [project.target, reel2]
    assert manager.save_count == 1
    assert result["mutation_counts"] == {"media_imports": 0, "timeline_appends": 0, "timeline_item_deletes": 0,
                                         "media_pool_deletes": 0, "video_track_creates": 0, "fusion_configures": 5,
                                         "item_renames": 5, "project_saves": 1}


def test_partial_fusion_failure_rolls_back_only_created_fusion_and_names(monkeypatch):
    result, project, manager, items, historical, reel2, calls = simulate(monkeypatch, fail_at=3)
    assert result["ok"] is False
    assert result["failures"] == ["RuntimeError: fusion_configure:3"]
    assert calls == ["item:94", "item:375", "item:424"]
    assert all(item.name == runtime.EXPECTED_MEDIA_NAME and item.comps == [] for item in items)
    assert [item.uid for item in items] == [f"item:{start}" for start, _ in runtime.EXPECTED_SPANS]
    assert historical.comps == [] and reel2.items[0].comps == []
    assert result["rollback"]["safe"] is True and result["rollback"]["deleted_fusion_comp_count"] == 3
    assert manager.save_count == 0 and project.current is reel2


def test_current_timeline_selection_failure_is_unmutated(monkeypatch):
    result, project, manager, items, historical, reel2, calls = simulate(monkeypatch, switch_ok=False)
    assert result["ok"] is False
    assert result["failures"] == ["RuntimeError: target_timeline_selection"]
    assert calls == [] and all(not item.comps for item in items)
    assert result["rollback"] == {"safe": True, "state": "unmutated_prestate", "attempted": False}
    assert manager.save_count == 0 and project.current is reel2
