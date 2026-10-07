from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from resolve_workspace.modules import video_cloner_step6a_flash_integration as runtime


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


prepare = load_script("step6a_prepare_test", "scripts/davinci/prepare_video_cloner_step6a_flash_integration.py")
validator = load_script("step6a_validator_test", "scripts/davinci/validate_video_cloner_step6a_flash_integration.py")


def authorities() -> tuple[dict, dict]:
    detector = json.loads((ROOT / runtime.DETECTOR_RELATIVE).read_text(encoding="utf-8-sig"))
    planning = json.loads((ROOT / runtime.PLANNING_RELATIVE).read_text(encoding="utf-8-sig"))
    return detector, planning


class Timeline:
    def __init__(self, name="gold", uid="u1"):
        self.name, self.uid = name, uid

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.uid


class Project:
    def __init__(self, timelines, current=None):
        self.timelines = timelines
        self.current = current or timelines[0]

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index):
        return self.timelines[index - 1]

    def SetCurrentTimeline(self, timeline):
        self.current = timeline
        return True

    def GetCurrentTimeline(self):
        return self.current


def geometry(monkeypatch, *, start=0, end=854, fps="24"):
    monkeypatch.setattr(runtime.P4B, "timeline_snapshot", lambda _: {"settings": {"timelineFrameRate": fps, "timelinePlaybackFrameRate": fps}, "start_frame": start, "end_frame": end})


def valid_report(mode: str) -> dict:
    apply = mode == "apply"
    return {"ok": True, "task_id": runtime.TASK_ID, "mode": runtime.MODE, "classification": "FIRST_APPLICATION" if apply else "ALREADY_VALID_REUSED", "authority_verification": {"ok": True}, "source_timeline_unchanged": True, "unrelated_timelines_unchanged": True, "target_after": {"ok": True, "persisted_fusion": {"ok": True}}, "visual_evidence": {"ok": apply}, "previous_timeline_restoration": {"ok": True}, "failures": [], "timeline_duplicate_count": 1 if apply else 0, "track_add_count": 1 if apply else 0, "flash_carrier_append_count": 1 if apply else 0, "media_import_count": 0, "save_project_count": 1 if apply else 0, "persistent_readback_ok": apply, "idempotent": not apply}


def test_accepted_reel2_plan_has_exactly_one_flash():
    plan = prepare.build_plan(*authorities())
    assert len(plan["flashes"]) == 1
    assert plan["flashes"][0]["transition_type"] == "flash_cut"
    runtime.validate_plan(plan)


def test_exact_half_open_594_598_mapping(monkeypatch):
    geometry(monkeypatch)
    mapping = runtime.frame_mapping(object())
    assert mapping["mapped_span"] == [594, 598]
    assert runtime.mapped_flash(mapping)[0]["start_frame"] == 594
    assert runtime.mapped_flash(mapping)[0]["duration_frames"] == 4


def test_nonzero_timeline_start_maps_by_offset(monkeypatch):
    geometry(monkeypatch, start=86400, end=87254)
    mapping = runtime.frame_mapping(object())
    assert mapping["mapped_frames"] == {"594": 86994, "596": 86996, "598": 86998}


def test_fps_mismatch_fails_closed(monkeypatch):
    geometry(monkeypatch, fps="23.976")
    with pytest.raises(runtime.FrameMappingError, match="STEP6A_GOLD_FRAME_MAPPING_MISMATCH:fps"):
        runtime.frame_mapping(object())


def test_gold_duration_mapping_mismatch_fails_closed(monkeypatch):
    geometry(monkeypatch, end=597)
    with pytest.raises(runtime.FrameMappingError, match="STEP6A_GOLD_FRAME_MAPPING_MISMATCH:range"):
        runtime.frame_mapping(object())


def test_many_existing_tracks_map_flash_to_top_plus_one(monkeypatch):
    source = {"video_track_count": 11, "audio_track_count": 2, "captions": {"x": 1}, "non_caption": {"x": 2}, "geometry": {"x": 3}}
    monkeypatch.setattr(runtime, "caption_snapshot", lambda _: {"x": 1})
    monkeypatch.setattr(runtime, "non_caption_snapshot", lambda _: {"x": 2})
    monkeypatch.setattr(runtime, "frame_mapping", lambda _: {"x": 3})
    monkeypatch.setattr(runtime.V1, "track_count", lambda _, kind: 12 if kind == "video" else 2)
    monkeypatch.setattr(runtime.V4, "neutral_flash_snapshot", lambda *_: {"ok": True, "count": 1, "neutral_carrier_count": 1, "source_video_carrier_count": 0, "rows": [{"track_index": 12}]})
    result = runtime.target_contract(source, object(), [{}])
    assert result["ok"] and result["expected_flash_track"] == 12


def test_wrong_overlay_track_fails_contract(monkeypatch):
    source = {"video_track_count": 11, "audio_track_count": 2, "captions": {}, "non_caption": {}, "geometry": {}}
    monkeypatch.setattr(runtime, "caption_snapshot", lambda _: {})
    monkeypatch.setattr(runtime, "non_caption_snapshot", lambda _: {})
    monkeypatch.setattr(runtime, "frame_mapping", lambda _: {})
    monkeypatch.setattr(runtime.V1, "track_count", lambda _, kind: 12 if kind == "video" else 2)
    monkeypatch.setattr(runtime.V4, "neutral_flash_snapshot", lambda *_: {"ok": True, "count": 1, "neutral_carrier_count": 1, "source_video_carrier_count": 0, "rows": [{"track_index": 2}]})
    assert not runtime.target_contract(source, object(), [{}])["ok"]


def test_exact_current_timeline_selection_and_readback():
    target = Timeline("target", "target-uid")
    assert runtime.select_and_prove(Project([target]), target)["ok"]


def test_current_timeline_readback_mismatch_fails():
    target, other = Timeline("target", "target-uid"), Timeline("other", "other-uid")
    project = Project([target, other], current=other)
    project.SetCurrentTimeline = lambda _: True
    assert not runtime.select_and_prove(project, target)["ok"]


def test_runtime_restores_previous_timeline_in_finally():
    text = Path(runtime.__file__).read_text(encoding="utf-8")
    assert "finally:" in text and "previous_timeline_restoration" in text and "select_and_prove(project, previous)" in text


def test_caption_snapshot_is_dense_and_structural():
    text = Path(runtime.__file__).read_text(encoding="utf-8")
    for token in ("CAPTION_PROPERTIES", "_property_snapshot", "clip_enabled", "STABLE_INVENTORY_FIELDS"):
        assert token in text


def test_unrelated_inventory_comparison_is_multiset_safe():
    left = [{"name": "a", "signature": "1"}, {"name": "a", "signature": "1"}]
    assert runtime.same_inventory(left, list(reversed(left)))
    assert not runtime.same_inventory(left, left[:1])


def test_v4_media_ownership_helper_is_reused():
    text = Path(runtime.__file__).read_text(encoding="utf-8")
    assert "V4.import_neutral_carrier" in text
    assert "V4._delete_owned_media_pool_item" in text


def test_ambiguous_and_incompatible_media_are_fail_closed():
    text = Path(runtime.V4.__file__).read_text(encoding="utf-8")
    assert "PREEXISTING_INCOMPATIBLE" in text
    assert "OWNERSHIP_AMBIGUOUS" in text


def test_partial_mutation_rollback_deletes_only_owned_resources():
    text = Path(runtime.__file__).read_text(encoding="utf-8")
    assert "not saved and media_pool is not None and (target_created or gold_imported)" in text
    assert 'DeleteTimelines", owned_timelines' in text
    assert '"owned_only": True' in text


def test_successful_second_run_validator_requires_zero_mutations():
    result = validator.validate(valid_report("idempotency"), "idempotency")
    assert result["ok"]
    bad = valid_report("idempotency")
    bad["flash_carrier_append_count"] = 1
    assert not validator.validate(bad, "idempotency")["ok"]


def test_slide_whip_blur_and_crossfade_are_non_executable():
    plan = prepare.build_plan(*authorities())
    assert set(plan["non_executable_transition_types"]) == {"slide_transition_candidate", "whip_pan_candidate", "blur_transition", "crossfade_candidate"}
    assert {row["transition_type"] for row in plan["flashes"]} == {"flash_cut"}


def test_duplicate_step6a_target_fails_closed():
    project = Project([Timeline(runtime.TARGET_TIMELINE_NAME, "1"), Timeline(runtime.TARGET_TIMELINE_NAME, "2")])
    with pytest.raises(RuntimeError, match="timeline_identity"):
        runtime.find_exact(project, runtime.TARGET_TIMELINE_NAME)


def test_first_application_validator_requires_one_bounded_delta():
    assert validator.validate(valid_report("apply"), "apply")["ok"]
    bad = valid_report("apply")
    bad["track_add_count"] = 2
    assert not validator.validate(bad, "apply")["ok"]


def command_context(tmp_path, monkeypatch, *, project=runtime.PROJECT_NAME, payload_project=None):
    plan = prepare.build_plan(*authorities())
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(runtime, "sha256", lambda _: "plan-hash")
    monkeypatch.setattr(runtime, "verify_input_hashes", lambda _: {"ok": True, "rows": []})
    run_id = "20261005T000000000Z_" + "0" * 32
    payload = {
        "repository_root": str(tmp_path),
        "report_dir": "report",
        "run_mode": "apply",
        "plan_path": str(plan_path),
        "plan_sha256": "plan-hash",
        "expected_project": project if payload_project is None else payload_project,
    }
    return {"run_id": run_id, "command": {"task": runtime.TASK_ID, "mode": runtime.MODE, "run_id": run_id, "payload": payload}}


class GuardedMediaPool:
    def __init__(self, events):
        self.events = events

    def ImportTimelineFromFile(self, *_):
        self.events.append("gold_import")
        return object()

    def DeleteTimelines(self, timelines):
        self.events.append("delete_owned_target")
        return bool(timelines)

    def DeleteClips(self, *_):
        self.events.append("delete_shared_media")
        return True


class GuardedProject:
    def __init__(self, name, events, source=None):
        self.name, self.events, self.source = name, events, source or Timeline(runtime.GOLD_TIMELINE_NAME, "gold-uid")
        self.current, self.target = self.source, None
        self.media_pool = GuardedMediaPool(events)

    def GetName(self):
        return self.name

    def GetMediaPool(self):
        return self.media_pool

    def GetCurrentTimeline(self):
        return self.current

    def SetCurrentTimeline(self, timeline):
        self.current = timeline
        self.events.append("select_timeline")
        return True


class GuardedManager:
    def __init__(self, project, events):
        self.project, self.events = project, events

    def GetCurrentProject(self):
        return self.project

    def SaveProject(self):
        self.events.append("save")
        return True


class GuardedResolve:
    def __init__(self, project, events):
        self.manager = GuardedManager(project, events)

    def GetProjectManager(self):
        return self.manager


def test_plan_and_payload_contain_exact_expected_project(tmp_path, monkeypatch):
    detector, planning = authorities()
    plan = prepare.build_plan(detector, planning)
    assert plan["project_name"] == runtime.PROJECT_NAME == "New Project 1"
    for relative, value in ((runtime.DETECTOR_RELATIVE, detector), (runtime.PLANNING_RELATIVE, planning)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(prepare.runtime, "verify_input_hashes", lambda _: {"ok": True})
    receipt = prepare.publish(tmp_path, "apply", "20261005T000000000Z_" + "1" * 32)
    command = json.loads((tmp_path / receipt["command_path"]).read_text(encoding="utf-8"))
    assert command["payload"]["expected_project"] == plan["project_name"]


def test_altered_plan_project_fails_validation():
    plan = prepare.build_plan(*authorities())
    plan["project_name"] = "Other Project"
    plan["plan_sha256"] = runtime.V1.canonical_sha256({key: value for key, value in plan.items() if key != "plan_sha256"})
    with pytest.raises(ValueError, match="plan_project"):
        runtime.validate_plan(plan)


def test_stale_payload_project_fails_before_resolve_access(tmp_path, monkeypatch):
    context = command_context(tmp_path, monkeypatch, payload_project="Other Project")

    class UntouchedResolve:
        def GetProjectManager(self):
            raise AssertionError("Resolve must not be accessed")

    report = runtime.run(UntouchedResolve(), context)
    assert report["failures"] == ["ValueError: payload_identity"]


def test_wrong_project_fails_before_any_resolve_content_mutation(tmp_path, monkeypatch):
    events = []
    project = GuardedProject("Other Project", events)
    context = command_context(tmp_path, monkeypatch)
    report = runtime.run(GuardedResolve(project, events), context)
    assert report["failures"] == ["RuntimeError: project_identity"]
    assert not set(events) & {"gold_import", "duplicate", "select_timeline", "track", "media_import", "append", "fusion", "save"}


def test_correct_project_passes_identity_gate(tmp_path, monkeypatch):
    events = []
    project = GuardedProject(runtime.PROJECT_NAME, events)
    context = command_context(tmp_path, monkeypatch)

    def stop_after_gate(*_):
        events.append("gold_resolution")
        raise RuntimeError("stop_after_identity_gate")

    monkeypatch.setattr(runtime, "resolve_gold_source", stop_after_gate)
    report = runtime.run(GuardedResolve(project, events), context)
    assert events == ["gold_resolution", "select_timeline"]
    assert report["project_name"] == runtime.PROJECT_NAME


def run_first_application(tmp_path, monkeypatch, *, changed_inventory):
    events = []
    source = Timeline(runtime.GOLD_TIMELINE_NAME, "gold-uid")
    project = GuardedProject(runtime.PROJECT_NAME, events, source)
    context = command_context(tmp_path, monkeypatch)
    source_state = {"timeline_name": runtime.GOLD_TIMELINE_NAME, "timeline_uid": "gold-uid", "video_track_count": 3, "audio_track_count": 2, "geometry": {"mapped_frames": {"594": 594, "596": 596, "598": 598}}, "captions": {"sha256": "captions"}, "non_caption": {"sha256": "base"}}
    baseline = [{"name": runtime.GOLD_TIMELINE_NAME, "signature": "gold"}, {"name": "unrelated", "signature": "safe"}]
    changed = [{"name": runtime.GOLD_TIMELINE_NAME, "signature": "gold"}, {"name": "unrelated", "signature": "changed"}]
    inventory_calls = 0

    def duplicate(name):
        events.append("duplicate")
        project.target = Timeline(name, "target-uid")
        return project.target

    source.DuplicateTimeline = duplicate
    monkeypatch.setattr(runtime, "resolve_gold_source", lambda *_: (source, {"route": "EXACT_EXISTING_GOLD_TIMELINE", "imported": False}))
    monkeypatch.setattr(runtime, "source_state", lambda _: dict(source_state))
    monkeypatch.setattr(runtime, "target_contract", lambda *_: {"ok": True})

    def find_exact(_, name, *, allow_missing=False):
        if name == runtime.TARGET_TIMELINE_NAME:
            return project.target
        return source

    monkeypatch.setattr(runtime, "find_exact", find_exact)

    def inventory(_):
        nonlocal inventory_calls
        inventory_calls += 1
        if inventory_calls == 2:
            events.append("inventory_pre_save")
            return changed if changed_inventory else baseline
        return baseline

    monkeypatch.setattr(runtime, "inventory_without_target", inventory)
    monkeypatch.setattr(runtime.V1, "ensure_extra_video_track", lambda *_: events.append("track") or {"ok": True, "target_track": 4})
    monkeypatch.setattr(runtime.V4, "validate_neutral_assets", lambda _: {"ok": True})
    monkeypatch.setattr(runtime.V4, "import_neutral_carrier", lambda *_: {"ok": True, "item": object(), "import_performed": False, "ownership_classification": "PREEXISTING_COMPATIBLE", "rollback_delete_permitted": False})
    monkeypatch.setattr(runtime.V1, "append_flash_carriers", lambda *args: events.append("append") or {"ok": True, "assigned": [(args[3][0], object())]})
    monkeypatch.setattr(runtime, "exact_flash_item", lambda *_: events.append("reacquire_flash") or object())
    monkeypatch.setattr(runtime.V1, "configure_flash", lambda *_: events.append("fusion") or {"ok": True})
    monkeypatch.setattr(runtime.C1, "capture_visual_evidence", lambda *_: events.append("visual_render") or {"ok": True, "total_frames": 4})
    monkeypatch.setattr(runtime, "persisted_target_contract", lambda *_: {"ok": True, "checks": {"flash_fusion_persisted": True}, "persisted_fusion": {"ok": True, "fusion_comp_count": 1}})
    report = runtime.run(GuardedResolve(project, events), context)
    return report, events


def test_unchanged_non_target_inventory_allows_save_in_order(tmp_path, monkeypatch):
    report, events = run_first_application(tmp_path, monkeypatch, changed_inventory=False)
    assert report["ok"] and report["save_project_count"] == 1
    assert events.index("reacquire_flash") < events.index("fusion") < events.index("inventory_pre_save") < events.index("visual_render") < events.index("save")


def test_changed_non_target_inventory_fails_before_application_save_and_rolls_back_owned_only(tmp_path, monkeypatch):
    report, events = run_first_application(tmp_path, monkeypatch, changed_inventory=True)
    assert report["failures"] == ["RuntimeError: pre_save_non_target_regression"]
    assert report["save_project_count"] == 0
    assert events.index("inventory_pre_save") < events.index("delete_owned_target") < events.index("save")
    assert "delete_shared_media" not in events
    assert report["rollback"]["media_delete"]["attempted"] is False


class FusionCarrier:
    def __init__(self, count):
        self.count = count

    def GetFusionCompCount(self):
        return self.count

    def GetFusionCompByIndex(self, index):
        return object() if self.count and index == 1 else None


def persistence_contract(monkeypatch, count):
    item = FusionCarrier(count)
    monkeypatch.setattr(runtime, "target_contract", lambda *_: {"ok": True, "checks": {"base": True}, "flash": {"ok": True}, "expected_flash_track": 9})
    monkeypatch.setattr(runtime, "exact_flash_item", lambda *_: item)
    return runtime.persisted_target_contract({}, object(), [{}])


def test_persisted_fusion_count_zero_fails_even_when_live_snapshot_passes(monkeypatch):
    result = persistence_contract(monkeypatch, 0)
    assert not result["ok"]
    assert result["persisted_fusion"] == {"ok": False, "fusion_comp_count": 0, "reacquired_carrier": True}


def test_persisted_fusion_reacquired_carrier_with_comp_passes(monkeypatch):
    result = persistence_contract(monkeypatch, 1)
    assert result["ok"]
    assert result["persisted_fusion"]["fusion_comp_count"] == 1


def test_partial_target_with_one_neutral_carrier_is_repairable_without_append(monkeypatch):
    item = FusionCarrier(0)
    contract = {
        "ok": False,
        "checks": {"caption_structural_snapshot_unchanged": True, "non_caption_inventory_unchanged": True, "timeline_geometry_unchanged": True, "audio_track_count_unchanged": True, "top_overlay_track_exact": True, "one_authorized_flash": False},
        "expected_flash_track": 9,
        "flash": {"count": 1, "source_video_carrier_count": 0, "rows": [{"name": "flash", "track_index": 9, "start": 594, "duration": 4, "carrier": {"neutral_carrier_ok": True}}]},
    }
    monkeypatch.setattr(runtime, "target_contract", lambda *_: contract)
    monkeypatch.setattr(runtime, "exact_flash_item", lambda *_: item)
    result = runtime.repairable_partial_target({}, object(), [{"name": "flash", "start_frame": 594, "duration_frames": 4}])
    assert result["ok"] and result["item"] is item and result["fusion_comp_count"] == 0


def test_partial_target_repair_validator_requires_zero_new_carriers():
    report = valid_report("apply")
    report.update({"classification": "PARTIAL_TARGET_REPAIRED", "timeline_duplicate_count": 0, "track_add_count": 0, "flash_carrier_append_count": 0})
    assert validator.validate(report, "apply")["ok"]
    report["flash_carrier_append_count"] = 1
    assert not validator.validate(report, "apply")["ok"]


def test_validator_rejects_missing_persisted_fusion():
    report = valid_report("apply")
    report["target_after"]["persisted_fusion"] = {"ok": False, "fusion_comp_count": 0}
    assert not validator.validate(report, "apply")["ok"]
