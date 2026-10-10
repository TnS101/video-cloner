from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from resolve_workspace.modules import oss002_sub008_production_canary as canary
from resolve_workspace.modules import oss002_16_caption_batch_rollout as batch
from resolve_workspace.modules import oss002_oss_animation_representative_batch as oss_adapter
from scripts.davinci import prepare_oss002_sub008_production_canary as prepare
from scripts.davinci import prepare_oss002_16_caption_batch_rollout as prepare_batch
from scripts.davinci import prepare_oss002_oss_animation_representative_batch as prepare_oss_batch
from video_cloner.animation_recipe import validate_recipe
from video_cloner.caption_motion_oss import ROUTE_TEMPLATE, _template_transforms


ROOT = Path(__file__).resolve().parents[1]


class Input:
    def __init__(self, value=None): self.values = {0: value}; self.connected = None
    def __getitem__(self, frame): return self.values.get(frame, self.values.get(0))
    def __setitem__(self, frame, value): self.values[int(frame)] = value
    def GetConnectedOutput(self): return self.connected


class Tool:
    def __init__(self): self.inputs = {}; self.modifiers = []
    def FindInput(self, name): return self.inputs.get(name)
    def SetInput(self, name, value, frame=0): self.inputs.setdefault(name, Input())[int(frame)] = value; return True
    def GetInput(self, name, frame=0): return self.inputs.get(name, Input())[int(frame)]
    def AddModifier(self, name, modifier):
        self.inputs.setdefault(name, Input()).connected = object(); self.modifiers.append((name, modifier)); return True
    def GetAttrs(self): return {"TOOLS_RegID": "TextPlus"}


class Comp:
    def __init__(self): self.tool = Tool()
    def FindTool(self, name): return self.tool if name == "Template" else None
    def GetToolList(self, _selected=False, regid=None): return {"Template": self.tool} if regid in (None, "TextPlus") else {}
    def Lock(self): return True
    def Unlock(self): return True


class PoolItem:
    def __init__(self, timeline): self.timeline = timeline
    def GetTimeline(self): return self.timeline


class Item:
    def __init__(self, *, start, duration, track, basic=False, text=None, timeline=None, events=None):
        self.start, self.duration, self.track, self.basic, self.timeline = start, duration, track, basic, timeline
        self.properties = {}
        self.enabled = True
        self.fail_on_disable_readback = False
        self.enabled_readback_failures = 0
        if text is not None: self.properties["Text"] = text
        self.comp = None if basic or timeline is not None else Comp()
        self.events = events if events is not None else []
    def GetName(self): return "Basic Title" if self.basic else "Text+"
    def GetStart(self): return self.start
    def GetDuration(self): return self.duration
    def GetEnd(self): return self.start + self.duration
    def GetMediaPoolItem(self): return PoolItem(self.timeline) if self.timeline is not None else None
    def GetFusionCompCount(self): return 1 if self.comp else 0
    def GetFusionCompByIndex(self, index): return self.comp if index == 1 else None
    def GetTrackTypeAndIndex(self): return "video", self.track
    def GetProperty(self, name=None): return dict(self.properties) if name is None else self.properties.get(name)
    def SetProperty(self, name, value): self.events.append(("hide" if value == 0 else "restore", name, value)); self.properties[name] = value; return True
    def GetClipEnabled(self):
        if self.enabled_readback_failures:
            self.enabled_readback_failures -= 1
            raise RuntimeError("enabled readback unavailable")
        return self.enabled
    def SetClipEnabled(self, value):
        self.enabled = bool(value)
        self.events.append(("restore" if value else "hide", "ClipEnabled", bool(value)))
        if not value and self.fail_on_disable_readback:
            self.enabled_readback_failures = 1
        return True


class FreshProxy:
    def __init__(self, item): self.item = item
    def __getattr__(self, name): return getattr(self.item, name)


class Timeline:
    counter = 0
    def __init__(self, name, *, base=86400, target=False, events=None, caption_count=112, bad_ordinal=False, uid=None):
        Timeline.counter += 1
        self.name, self.uid, self.base = name, uid or f"uid-{Timeline.counter}", base
        self.events = events if events is not None else []
        self.tracks = {1: [], 2: []} if target else {1: []}
        self.fresh_proxies = False
        if target:
            starts = [0, 5, 8, 11, 27, 32, 35, 39] + list(range(44, 44 + caption_count - 8))
            durations = [5, 3, 3, 10, 5, 3, 4, 6 if bad_ordinal else 5] + [1] * (caption_count - 8)
            for index in range(caption_count):
                self.tracks[2].append(Item(start=base + starts[index], duration=durations[index], track=2, basic=True, text="this" if index == 7 else None, events=self.events))
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetStartFrame(self): return self.base
    def GetTrackCount(self, kind): return max(self.tracks) if kind == "video" else 0
    def GetItemListInTrack(self, kind, track):
        items = list(self.tracks.get(track, [])) if kind == "video" else []
        return [FreshProxy(item) for item in items] if self.fresh_proxies else items
    def AddTrack(self, kind): assert kind == "video"; self.tracks[max(self.tracks) + 1] = []; self.events.append(("add_track", max(self.tracks))); return True
    def DeleteTrack(self, kind, track): assert kind == "video"; self.tracks.pop(track, None); self.events.append(("delete_track", track)); return True
    def InsertFusionTitleIntoTimeline(self, name):
        assert name == "Text+"; item = Item(start=0, duration=120, track=1); self.tracks[1].append(item); return item
    def GetMediaPoolItem(self): return PoolItem(self)
    def DeleteClips(self, items, _ripple):
        for track in self.tracks:
            self.tracks[track] = [row for row in self.tracks[track] if row not in items]
        self.events.append(("delete_replacement",)); return True


class Pool:
    def __init__(self, project, *, inner_missing=False, append_fail_at=None): self.project, self.inner_missing, self.append_fail_at, self.append_count = project, inner_missing, append_fail_at, 0
    def CreateEmptyTimeline(self, name):
        timeline = Timeline(name, events=self.project.events); self.project.timelines.append(timeline); return timeline
    def AppendToTimeline(self, rows):
        self.append_count += 1
        if self.append_fail_at == self.append_count: return []
        row = rows[0]; self.project.events.append(("append", dict(row)))
        source = None if self.inner_missing else row["mediaPoolItem"].timeline
        item = Item(start=row["recordFrame"], duration=row["endFrame"] - row["startFrame"], track=row["trackIndex"], timeline=source, events=self.project.events)
        if self.inner_missing: item.timeline = None; item.GetMediaPoolItem = lambda: PoolItem(None)
        self.project.current.tracks[row["trackIndex"]].append(item); return [item]
    def DeleteTimelines(self, timelines):
        self.project.timelines = [row for row in self.project.timelines if row not in timelines]; self.project.events.append(("delete_source",)); return True


class Project:
    def __init__(self, *, name=canary.PROJECT_NAME, timeline_name=canary.TARGET_TIMELINE, caption_count=112, bad_ordinal=False, inner_missing=False, fresh_proxies=False, preexisting_v3=False, hide_readback_failure=False, stale_count=0, append_fail_at=None):
        self.name, self.events = name, []
        self.save_failure_entered_from_source = False
        self.target = Timeline(timeline_name, target=True, events=self.events, caption_count=caption_count, bad_ordinal=bad_ordinal)
        self.target.fresh_proxies = fresh_proxies
        if preexisting_v3:
            self.target.tracks[3] = []
        if hide_readback_failure:
            self.target.tracks[2][7].fail_on_disable_readback = True
        stale = [Timeline(canary.STALE_SOURCE_TIMELINE, events=self.events) for _ in range(stale_count)]
        self.timelines, self.current = [self.target, *stale], self.target
        self.pool = Pool(self, inner_missing=inner_missing, append_fail_at=append_fail_at)
    def GetName(self): return self.name
    def GetMediaPool(self): return self.pool
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def SetCurrentTimeline(self, timeline): self.current = timeline; return True
    def GetCurrentTimeline(self): return self.current


class Manager:
    def __init__(self, project, save=True): self.project, self.save = project, save
    def GetCurrentProject(self): return self.project
    def SaveProject(self):
        self.project.events.append(("save",))
        if not self.save:
            self.project.current = self.project.timelines[-1]
            self.project.save_failure_entered_from_source = self.project.current is not self.project.target
        return self.save


class Resolve:
    def __init__(self, project=None, save=True): self.project = project or Project(); self.manager = Manager(self.project, save)
    def GetVersionString(self): return canary.EXPECTED_RESOLVE_VERSION
    def GetProjectManager(self): return self.manager


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def command():
    fcpxml = ROOT / prepare.FCPXML; plan = ROOT / prepare.ANIMATION_PLAN
    return {"task": canary.TASK_ID, "mode": canary.MODE, "run_id": "run", "payload": {
        "repository_root": str(ROOT), "expected_project": canary.PROJECT_NAME,
        "target_timeline": canary.TARGET_TIMELINE, "source_timeline": canary._source_timeline_name("run"),
        "expected_caption_count": 112, "source_ordinal": 8, "expected_text": "this",
        "relative_start": 39, "duration": 5, "hide_property": "ClipEnabled", "save_after_verification": True,
        "fcpxml_path": prepare.FCPXML, "fcpxml_sha256": sha(fcpxml),
        "animation_plan_path": prepare.ANIMATION_PLAN, "animation_plan_sha256": sha(plan)}}


def run(resolve): return canary.run(resolve, {"run_id": "run", "command": command()})


def batch_project(**kwargs):
    project = Project(**kwargs)
    plan = json.loads((ROOT / prepare_batch.ANIMATION_PLAN).read_text(encoding="utf-8"))
    for item, authority in zip(project.target.tracks[2], plan["items"]):
        item.start = project.target.base + int(authority["start_frame"])
        item.duration = int(authority["duration_frames"])
        item.properties["Text"] = str(authority["text"])
    source = Timeline(batch.ACCEPTED_SOURCE_NAME, events=project.events, uid=batch.ACCEPTED_SOURCE_UID)
    project.timelines.append(source)
    project.target.tracks[3] = [Item(start=project.target.base + 39, duration=5, track=3, timeline=source, events=project.events)]
    project.target.tracks[2][7].enabled = False
    return project


def batch_command():
    plan = ROOT / prepare_batch.ANIMATION_PLAN
    fcpxml = ROOT / prepare_batch.FCPXML
    return {"task": batch.TASK_ID, "mode": batch.MODE, "run_id": "batchrun_abcdef123456", "payload": {
        "repository_root": str(ROOT), "expected_project": batch.PROJECT_NAME, "target_timeline": batch.TARGET_TIMELINE,
        "accepted_sub008_source_name": batch.ACCEPTED_SOURCE_NAME, "accepted_sub008_source_uid": batch.ACCEPTED_SOURCE_UID,
        "expected_selected_count": 16, "remaining_target_count": 15,
        "fcpxml_path": prepare_batch.FCPXML, "fcpxml_sha256": sha(fcpxml),
        "animation_plan_path": prepare_batch.ANIMATION_PLAN, "animation_plan_sha256": sha(plan),
        "review_manifest_path": ".agent/reports/test_oss002_batch/batch_human_review_manifest.json",
        "save_after_batch_verification": True,
    }}


def run_batch(resolve):
    return batch.run(resolve, {"run_id": "batchrun_abcdef123456", "command": batch_command()})


def test_production_canary_binds_new_uid_and_applies_exact_nested_replacement():
    resolve = Resolve(); result = run(resolve)
    assert result["ok"] is True
    assert result["inline_recovery"]["match_count"] == 0
    assert result["inline_recovery"]["deleted"] is False
    assert result["target"]["unique_id"] == resolve.project.target.uid
    assert result["source_caption"] == {"ordinal": 8, "text": "this", "text_readback": "this", "relative_start": 39, "actual_start": 86439, "duration": 5, "track": 2, "timeline_base_frame": 86400}
    assert result["carrier"]["placement"] == {"track_type": "video", "track": 3, "start": 86439, "duration": 5}
    assert result["run_source_timeline"]["name"] == canary._source_timeline_name("run")
    assert result["run_source_timeline"]["name"] != canary.STALE_SOURCE_TIMELINE
    assert result["animation"]["property"] == "Center"
    assert result["animation"]["modifier"]["modifier"] == "Path"
    assert all(
        actual == pytest.approx(expected)
        for actual, expected in zip(
            [row["actual"] for row in result["animation"]["readback"]],
            [[0.4486, 0.5005], [0.5, 0.5], [0.5, 0.5]],
        )
    )
    assert result["original_sub008"] == {"clip_enabled_before": True, "clip_enabled_after": False, "hidden_after_replacement_verification": True}
    assert result["other_111_untouched"] is True
    events = [row[0] for row in resolve.project.events]
    assert events.index("append") < events.index("hide") < events.index("save")
    assert events.count("save") == 1


@pytest.mark.parametrize("project", [
    Project(name="wrong"), Project(timeline_name="wrong"), Project(caption_count=111), Project(bad_ordinal=True),
])
def test_pre_mutation_identity_and_caption_gates(project):
    result = run(Resolve(project))
    assert result["ok"] is False
    assert not any(event[0] in {"append", "hide", "save"} for event in project.events)


def test_replacement_is_verified_before_original_hide():
    project = Project(inner_missing=True); result = run(Resolve(project))
    assert result["ok"] is False
    assert not any(event[0] == "hide" for event in project.events)
    assert result["rollback"]["replacement_deleted"] is True
    assert result["rollback"]["source_timeline_deleted"] is True
    assert result["rollback"]["created_track_removed"] is True
    assert project.target.tracks[2][7].enabled is True
    assert len(project.timelines) == 1 and set(project.target.tracks) == {1, 2}


def test_post_hide_failure_rolls_back_every_canary_mutation():
    project = Project(); result = run(Resolve(project, save=False))
    assert result["ok"] is False
    assert result["save_project_called"] is False
    assert result["rollback"] == {"original_restored": True, "replacement_deleted": True, "source_timeline_deleted": True, "created_track_removed": True, "other_111_unchanged": True, "ok": True}
    assert project.save_failure_entered_from_source is True
    assert project.target.tracks[2][7].enabled is True
    assert len(project.timelines) == 1 and set(project.target.tracks) == {1, 2}
    assert project.GetCurrentTimeline() is project.target
    assert len(canary.basic_title_rows(project.target)) == 112
    assert ("hide", "ClipEnabled", False) in project.events
    assert ("restore", "ClipEnabled", True) in project.events


def test_other_caption_snapshot_uses_ordinal_with_fresh_proxies_and_detects_mutation():
    project = Project(fresh_proxies=True)
    first = canary.basic_title_rows(project.target)
    second = canary.basic_title_rows(project.target)
    assert all(left["item"] is not right["item"] for left, right in zip(first, second))
    expected = canary._other_caption_snapshot(first, project.target.base)
    assert canary._other_caption_snapshot(second, project.target.base) == expected
    project.target.tracks[2][7].start += 1
    assert canary._other_caption_snapshot(canary.basic_title_rows(project.target), project.target.base) == expected
    project.target.tracks[2][7].start -= 1
    project.target.tracks[2][8].duration += 1
    assert canary._other_caption_snapshot(canary.basic_title_rows(project.target), project.target.base) != expected


def test_rollback_verification_accepts_fresh_proxy_wrappers():
    project = Project(fresh_proxies=True)
    result = run(Resolve(project, save=False))
    assert result["ok"] is False
    assert result["rollback"]["other_111_unchanged"] is True
    assert result["rollback"]["ok"] is True


def test_hide_readback_failure_still_restores_original_and_exact_baseline():
    project = Project(hide_readback_failure=True)
    result = run(Resolve(project))
    assert result["ok"] is False
    assert result["failures"][0] == "ValueError: caption_enabled_readback"
    assert result["rollback"]["ok"] is True
    assert project.target.tracks[2][7].enabled is True
    assert len(project.timelines) == 1 and set(project.target.tracks) == {1, 2}


def test_preexisting_v3_is_not_deleted_during_rollback():
    project = Project(preexisting_v3=True)
    result = run(Resolve(project, save=False))
    assert result["ok"] is False
    assert result["rollback"]["replacement_deleted"] is True
    assert result["rollback"]["created_track_removed"] is True
    assert set(project.target.tracks) == {1, 2, 3}
    assert project.target.tracks[3] == []


def test_inline_recovery_deletes_one_stale_source_then_runs_canary():
    project = Project(stale_count=1)
    result = run(Resolve(project))
    assert result["ok"] is True
    assert result["inline_recovery"]["match_count"] == 1
    assert result["inline_recovery"]["deleted"] is True
    assert all(row.name != canary.STALE_SOURCE_TIMELINE for row in project.timelines)
    assert [row[0] for row in project.events].index("delete_source") < [row[0] for row in project.events].index("append")


def test_duplicate_stale_sources_fail_before_production_mutation():
    project = Project(stale_count=2)
    result = run(Resolve(project))
    assert result["ok"] is False
    assert result["failures"] == ["ValueError: stale_source_count:2"]
    assert not any(event[0] in {"delete_source", "append", "hide", "save"} for event in project.events)


def test_bridge_equivalent_file_loader_without_repository_on_sys_path(tmp_path):
    module_path = ROOT / "resolve_workspace/modules/oss002_sub008_production_canary.py"
    code = f'''\
import importlib.util, pathlib, sys
root = pathlib.Path({str(ROOT)!r}).resolve()
sys.path = [entry for entry in sys.path if pathlib.Path(entry or ".").resolve() != root]
assert root not in [pathlib.Path(entry or ".").resolve() for entry in sys.path]
spec = importlib.util.spec_from_file_location("vc_agent_command_module", {str(module_path)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(module.run)
'''
    completed = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_publisher_emits_one_bounded_command(tmp_path):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    for relative in (prepare.FCPXML, prepare.ANIMATION_PLAN):
        destination = tmp_path / relative; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    receipt = prepare.publish(tmp_path)
    payload = json.loads((tmp_path / receipt["command_path"]).read_text(encoding="utf-8"))
    assert payload["payload"]["expected_project"] == canary.PROJECT_NAME
    assert payload["payload"]["target_timeline"] == canary.TARGET_TIMELINE
    assert payload["payload"]["source_timeline"] == canary._source_timeline_name(payload["run_id"])
    assert payload["payload"]["source_timeline"] != canary.STALE_SOURCE_TIMELINE
    assert payload["payload"]["hide_property"] == "ClipEnabled"
    assert payload["payload"]["save_after_verification"] is True


def test_batch_selects_exact_remaining_targets_and_allocates_shared_v3():
    targets = batch.selected_targets(ROOT / prepare_batch.ANIMATION_PLAN)
    remaining = [row for row in targets if row["ordinal"] != 8]
    assert len(targets) == 16 and len(remaining) == 15
    assert {row["family"] for row in remaining} == {"slide", "scale"}
    allocation = batch.allocate_tracks(remaining, {3: [(39, 44)]})
    assert set(allocation.values()) == {3}
    overlap = [dict(remaining[0]), dict(remaining[1])]
    overlap[1]["start"], overlap[1]["end"] = overlap[0]["start"], overlap[0]["end"]
    assert set(batch.allocate_tracks(overlap, {3: [(39, 44)]}).values()) == {3, 4}


def test_batch_rollout_applies_15_without_reprocessing_accepted_sub008():
    project = batch_project()
    result = run_batch(Resolve(project))
    assert result["ok"] is True
    assert result["remaining_target_count"] == 15
    assert result["created_source_timeline_count"] == 15
    assert result["created_track_count"] == 0
    assert set(result["track_allocation"].values()) == {3}
    assert {row["family"] for row in result["technical_rows"]} == {"slide", "scale"}
    assert all(row["placement"]["track"] == 3 for row in result["technical_rows"])
    assert project.target.tracks[2][7].enabled is False
    assert sum(row.timeline is not None and row.timeline.uid == batch.ACCEPTED_SOURCE_UID for row in project.target.tracks[3]) == 1
    assert all(project.target.tracks[2][ordinal - 1].enabled is False for ordinal in {row["ordinal"] for row in batch.selected_targets(ROOT / prepare_batch.ANIMATION_PLAN)})
    assert [event[0] for event in project.events].count("save") == 1
    assert result["save_project_returned"] is True


def test_batch_failure_rolls_back_only_batch_owned_mutations():
    project = batch_project(append_fail_at=3)
    result = run_batch(Resolve(project))
    assert result["ok"] is False
    assert result["rollback"]["ok"] is True
    assert project.target.tracks[2][7].enabled is False
    assert all(project.target.tracks[2][index].enabled is True for index in range(112) if index != 7)
    assert len(project.target.tracks[3]) == 1
    assert project.target.tracks[3][0].timeline.uid == batch.ACCEPTED_SOURCE_UID
    assert len(project.timelines) == 2
    assert not any(event[0] == "save" for event in project.events)


def test_batch_module_loads_with_bridge_file_loader_and_no_repo_sys_path(tmp_path):
    module_path = ROOT / "resolve_workspace/modules/oss002_16_caption_batch_rollout.py"
    code = f'''\
import importlib.util, pathlib, sys
root = pathlib.Path({str(ROOT)!r}).resolve()
sys.path = [entry for entry in sys.path if pathlib.Path(entry or ".").resolve() != root]
spec = importlib.util.spec_from_file_location("vc_agent_command_module", {str(module_path)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(module.run)
'''
    completed = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_batch_publisher_emits_one_command_and_review_template(tmp_path):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    for relative in (prepare_batch.FCPXML, prepare_batch.ANIMATION_PLAN):
        destination = tmp_path / relative; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    receipt = prepare_batch.publish(tmp_path)
    payload = json.loads((tmp_path / receipt["command_path"]).read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / receipt["review_manifest_path"]).read_text(encoding="utf-8"))
    assert payload["task"] == batch.TASK_ID
    assert payload["payload"]["remaining_target_count"] == 15
    assert len(manifest["targets"]) == 16
    accepted = next(row for row in manifest["targets"] if row["ordinal"] == 8)
    assert accepted["technical_status"] == "HUMAN_ACCEPTED_FIDELITY_APPROXIMATE"


def _oss_recipe(position=None, scale=None):
    channels = {}
    if position is not None:
        channels["position"] = [{"frame": 0, "value": position, "interpolation": "linear"}]
    if scale is not None:
        channels["scale"] = [{"frame": 0, "value": scale, "interpolation": "linear"}]
    return {"schema": "video_cloner.caption_animation_recipe", "schema_version": 1, "caption_id": "sub_009", "text": "business,", "start_frame": 44, "duration": 9, "channels": channels}


def test_oss_recipe_validates_compound_position_and_scale_without_mutating_authority():
    recipe = _oss_recipe([0.1, -0.2], [0.8, 0.8])
    before = json.loads(json.dumps(recipe))
    assert validate_recipe(recipe) is recipe
    assert recipe == before
    with pytest.raises(ValueError, match="recipe_scale"):
        validate_recipe(_oss_recipe([0.1, 0.2], [0.0, 0.0]))


def test_oss_template_transform_extraction_is_temporally_stable():
    import cv2
    import numpy as np

    frames = []
    for x, size in ((36, 20), (40, 22), (44, 24)):
        frame = np.zeros((100, 140, 3), dtype=np.uint8)
        cv2.rectangle(frame, (x, 35), (x + size, 55), (255, 255, 255), 2)
        cv2.line(frame, (x + 3, 39), (x + size - 3, 51), (255, 255, 255), 2)
        frames.append(frame)
    first, _ = _template_transforms(frames, (44, 35, 68, 56), None)
    second, _ = _template_transforms(frames, (44, 35, 68, 56), None)
    assert first == second
    assert first[-1][2] == pytest.approx(1.0, abs=0.05)
    assert first[0][0] < first[-1][0]


def test_oss_resolve_mapping_supports_independent_and_simultaneous_channels():
    style = {"Center": [0.5, 0.5], "Size": 0.1}
    position = oss_adapter._channel_targets(_oss_recipe([0.1, -0.2]), style)
    scale = oss_adapter._channel_targets(_oss_recipe(scale=[0.8, 0.8]), style)
    compound = oss_adapter._channel_targets(_oss_recipe([0.1, -0.2], [0.8, 0.8]), style)
    assert position["Center"][0]["expected"] == [0.6, 0.3]
    assert scale["Size"][0]["expected"] == pytest.approx(0.08)
    assert set(compound) == {"Center", "Size"}


def _oss_project():
    project = batch_project()
    assert run_batch(Resolve(project))["ok"] is True
    project.target.uid = oss_adapter.EXPECTED_TIMELINE_UID
    return project


def _oss_command():
    recipes, fcpxml = ROOT / prepare_oss_batch.RECIPES, ROOT / prepare_oss_batch.FCPXML
    return {"task": oss_adapter.TASK_ID, "mode": oss_adapter.MODE, "run_id": "ossrun_abcdef123456", "payload": {
        "repository_root": str(ROOT), "expected_project": oss_adapter.EXPECTED_PROJECT,
        "target_timeline": oss_adapter.EXPECTED_TIMELINE, "target_timeline_uid": oss_adapter.EXPECTED_TIMELINE_UID,
        "expected_caption_count": 112, "expected_video_track_count": 3, "expected_existing_nested_count": 16,
        "target_ordinals": [9, 12, 15, 26], "recipe_path": prepare_oss_batch.RECIPES,
        "recipe_sha256": sha(recipes), "fcpxml_path": prepare_oss_batch.FCPXML,
        "fcpxml_sha256": sha(fcpxml), "save_after_verification": True,
    }}


def test_oss_representative_batch_is_bounded_and_preserves_accepted_sub008():
    project = _oss_project()
    accepted_before = batch._accepted_sub008(project.target, project.target.base)
    result = oss_adapter.run(Resolve(project), {"run_id": "ossrun_abcdef123456", "command": _oss_command()})
    assert result["ok"] is True
    assert {row["caption_id"] for row in result["technical_rows"]} == {"sub_009", "sub_012", "sub_015", "sub_026"}
    assert all(set(row["channels"]) == {"position", "scale"} for row in result["technical_rows"])
    accepted_after = batch._accepted_sub008(project.target, project.target.base)
    assert accepted_after["source"] == accepted_before["source"]
    assert project.target.tracks[2][7].enabled is False
    assert [event[0] for event in project.events].count("save") == 2
    json.dumps(result)


def test_oss_representative_failure_restores_exact_existing_batch():
    project = _oss_project()
    baseline = oss_adapter._stable_nested(project.target, project.target.base)
    project.pool.append_fail_at = project.pool.append_count + 2
    result = oss_adapter.run(Resolve(project), {"run_id": "ossrun_abcdef123456", "command": _oss_command()})
    assert result["ok"] is False and result["rollback"]["ok"] is True
    assert oss_adapter._stable_nested(project.target, project.target.base) == baseline
    assert all(project.target.tracks[2][ordinal - 1].enabled is True for ordinal in oss_adapter.EXPECTED_ORDINALS)


def test_oss_representative_publisher_emits_one_exact_command(tmp_path):
    (tmp_path / "AGENTS.md").write_text("test", encoding="utf-8")
    for relative in (prepare_oss_batch.FCPXML, prepare_oss_batch.RECIPES):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    receipt = prepare_oss_batch.publish(tmp_path)
    payload = json.loads((tmp_path / receipt["command_path"]).read_text(encoding="utf-8"))
    assert payload["task"] == oss_adapter.TASK_ID
    assert payload["payload"]["target_ordinals"] == [9, 12, 15, 26]
    assert payload["payload"]["target_timeline_uid"] == oss_adapter.EXPECTED_TIMELINE_UID
