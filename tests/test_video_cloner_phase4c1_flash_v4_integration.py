from __future__ import annotations

import json
from pathlib import Path

from resolve_workspace.modules import video_cloner_phase4c1_flash_v4_integration as runtime
from scripts.davinci import prepare_video_cloner_phase4c1_flash_v4_integration as prepare


def authority(cuts=runtime.EXPECTED_FLASH_FRAMES):
    return {"transitions": [{"transition_type": "flash_cut", "cut_frame": cut, "duration_frames": 4, "outgoing_frames": 2, "incoming_frames": 2, "editor_actionable": True, "confidence": "high", "placement": "at_cut", "handle_check": {"ok": True}} for cut in cuts]}


def contract(target=runtime.TARGET_TIMELINE_NAME, clip_count=22, duration=965):
    return {"timeline_name": target, "clips": [{}] * clip_count, "duration_frames": duration, "fps": 24, "source_path": "fixture"}


def test_plan_uses_exact_accepted_locations_and_four_frame_centering():
    plan = prepare.build_plan(authority())
    assert [row["cut_frame"] for row in plan["flashes"]] == [96, 377, 426, 454, 758]
    assert [row["start_frame"] for row in plan["flashes"]] == [94, 375, 424, 452, 756]
    assert [row["duration_frames"] for row in plan["flashes"]] == [4] * 5


def test_plan_preserves_historical_names_and_alpha_contract():
    rows = prepare.build_plan(authority())["flashes"]
    assert [row["name"] for row in rows] == [f"VC_FLASH_{index:03d}_frame_{cut:04d}" for index, cut in enumerate(runtime.EXPECTED_FLASH_FRAMES, 1)]
    assert all(row["alpha_keyframes"] == [[0, 0.0], [2, 0.75], [3, 0.0]] for row in rows)


def test_plan_uses_only_accepted_neutral_rgba_v4_carrier():
    carrier = prepare.build_plan(authority())["carrier"]
    assert carrier["kind"] == "transparent_rgba_sequence"
    assert carrier["source_video_pixels_possible"] is False
    assert carrier["media_pool_item_name"] == runtime.V4.NEUTRAL_MEDIA_POOL_ITEM_NAME
    assert carrier["png_sha256"] == runtime.V4.NEUTRAL_PNG_SHA256


def test_runtime_accepts_exact_hashed_plan():
    runtime.validate_plan(prepare.build_plan(authority()))


def test_runtime_rejects_non_standalone_target():
    plan = prepare.build_plan(authority())
    plan["target_timeline_name"] = runtime.PROTECTED_TIMELINE_NAME
    plan["plan_sha256"] = runtime.V1.canonical_sha256({key: value for key, value in plan.items() if key != "plan_sha256"})
    try:
        runtime.validate_plan(plan)
    except ValueError as exc:
        assert str(exc) == "plan_target_identity"
    else:
        raise AssertionError("protected target accepted")


def test_runtime_rejects_protected_signature_substitution():
    plan = prepare.build_plan(authority())
    plan["protected_timeline_name"] = "other"
    plan["plan_sha256"] = runtime.V1.canonical_sha256({key: value for key, value in plan.items() if key != "plan_sha256"})
    try:
        runtime.validate_plan(plan)
    except ValueError as exc:
        assert str(exc) == "plan_legacy_protection"
    else:
        raise AssertionError("protected identity weakened")


def test_authority_rejects_invalid_flash_duration():
    value = authority()
    value["transitions"][0]["duration_frames"] = 9
    try:
        prepare.build_plan(value)
    except ValueError as exc:
        assert str(exc) == "transition_authority"
    else:
        raise AssertionError("invalid duration accepted")


def test_source_rows_excludes_only_flash_overlay_items():
    snapshot = {"video_items": [{"name": "source", "start": 0, "track_index": 1}, {"name": "VC_FLASH_001_frame_0096", "start": 94, "track_index": 2}]}
    assert [row["name"] for row in runtime.source_rows(snapshot)] == ["source"]


def test_forbidden_counts_remain_zero_for_cut_only_base_and_neutral_flash():
    base = {"rows": [{"properties": {"ZoomX": 1.0, "ZoomY": 1.0, "RetimeSpeed": 100.0}, "fusion_comp_count": 0}]}
    counts = runtime.forbidden_counts(None, base, {"source_video_carrier_count": 0})
    assert counts and not any(counts.values())


class FakeTimeline:
    def __init__(self):
        self.deleted = []
        self.deleted_tracks = []

    def DeleteClips(self, items, ripple):
        self.deleted.extend(items)
        return ripple is False

    def DeleteTrack(self, kind, index):
        self.deleted_tracks.append((kind, index))
        return True


class FakePool:
    def __init__(self):
        self.deleted = []

    def DeleteClips(self, items):
        self.deleted.extend(items)
        for item in items:
            if hasattr(item, "linked"):
                item.linked = False
        return True


class LinkedMedia:
    def __init__(self): self.linked = True


def test_failure_cleanup_removes_only_new_overlay_state_and_never_saves():
    timeline, pool, item, media = FakeTimeline(), FakePool(), object(), LinkedMedia()
    ownership = {"item": media, "ownership_classification": "NEWLY_CREATED", "rollback_delete_permitted": True}
    result = runtime.cleanup_unsaved(timeline, pool, [({}, item)], ownership, 2)
    assert result["ok"] is True and result["media_delete"]["deleted"] == 1
    assert timeline.deleted == [item]
    assert timeline.deleted_tracks == [("video", 2)]
    assert pool.deleted == [media]


def test_failure_cleanup_never_deletes_reused_shared_media():
    timeline, pool, item, media = FakeTimeline(), FakePool(), object(), LinkedMedia()
    ownership = {"item": media, "ownership_classification": "PREEXISTING_COMPATIBLE", "rollback_delete_permitted": False}
    result = runtime.cleanup_unsaved(timeline, pool, [({}, item)], ownership, 2)
    assert result["media_delete"] == {"permitted": False, "attempted": False, "ok": True, "deleted": 0}
    assert pool.deleted == [] and media.linked is True


class FakeManager:
    def __init__(self, project, order):
        self.project, self.order, self.saves = project, order, 0

    def GetCurrentProject(self): return self.project
    def SaveProject(self):
        self.order.append("save")
        self.saves += 1
        return True


class FakeProject:
    def __init__(self, pool=None): self.pool = pool or FakePool()
    def GetName(self): return runtime.PROJECT_NAME
    def GetMediaPool(self): return self.pool


class FakeResolve:
    def __init__(self, manager): self.manager = manager
    def GetProjectManager(self): return self.manager


def run_fixture(tmp_path: Path, monkeypatch, capture_fails=False, cuts=runtime.EXPECTED_FLASH_FRAMES, ownership_classification="NEWLY_CREATED", non_target_changes=False):
    plan = prepare.build_plan(authority(cuts), runtime.PROJECT_NAME, runtime.TARGET_TIMELINE_NAME, contract(), "fcpxml")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    fcpxml = tmp_path / "timeline.fcpxml"
    fcpxml.write_text("fixture", encoding="utf-8")
    report_rel = "reports/run"
    target, protected, item, media = FakeTimeline(), object(), object(), LinkedMedia()
    order = []
    pool = FakePool()
    project = FakeProject(pool)
    manager = FakeManager(project, order)
    empty = {"ok": False, "count": 0}
    valid_flash = {"ok": True, "count": len(plan["flashes"]), "neutral_carrier_count": len(plan["flashes"]), "source_video_carrier_count": 0, "rows": [{"name": row["name"], "start": row["start_frame"], "duration": 4, "track_index": 2, "fusion": {"ok": True, "alpha_keyframes": [{}, {}, {}]}} for row in plan["flashes"]]}
    calls = {"flash": 0}
    monkeypatch.setattr(runtime, "find_one", lambda project, name: target if name == runtime.TARGET_TIMELINE_NAME else protected)
    monkeypatch.setattr(runtime.P4B, "timeline_snapshot", lambda value: {"signature": runtime.PROTECTED_SIGNATURE} if value is protected else {})
    inventory_calls = {"count": 0}
    def inventory(project):
        inventory_calls["count"] += 1
        signature = "changed" if non_target_changes and inventory_calls["count"] > 1 else "frozen"
        return [{"name": runtime.TARGET_TIMELINE_NAME, "signature": "target"}, {"name": "arbitrary_non_target", "signature": signature}]
    monkeypatch.setattr(runtime.P4B, "timeline_inventory", inventory)
    monkeypatch.setattr(runtime, "validate_base_geometry", lambda value, contract: {"ok": True, "clip_count": 22, "duration_frames": 965, "fps": 24, "rows": [], "signature": "base", "snapshot": {"video_track_count": 1}})
    def flash_snapshot(*args):
        calls["flash"] += 1
        return empty if calls["flash"] == 1 else valid_flash
    monkeypatch.setattr(runtime.V4, "neutral_flash_snapshot", flash_snapshot)
    monkeypatch.setattr(runtime.V4, "validate_neutral_assets", lambda root: {"ok": True})
    monkeypatch.setattr(runtime.V4, "import_neutral_carrier", lambda pool, root, assets: {"ok": True, "item": media, "ownership_classification": ownership_classification, "rollback_delete_permitted": ownership_classification == "NEWLY_CREATED", "import_performed": ownership_classification == "NEWLY_CREATED", "property_write_count": 4 if ownership_classification == "NEWLY_CREATED" else 0})
    monkeypatch.setattr(runtime.V1, "ensure_extra_video_track", lambda timeline, count: {"ok": True, "target_track": 2})
    monkeypatch.setattr(runtime.V1, "append_flash_carriers", lambda pool, timeline, carrier, rows, track: {"ok": True, "assigned": [(row, item) for row in rows]})
    monkeypatch.setattr(runtime.V1, "configure_flash", lambda item, row, index: {"ok": True})
    monkeypatch.setattr(runtime, "forbidden_counts", lambda *args: {"speed_retime": 0})
    def capture(*args):
        order.append("capture")
        if capture_fails:
            raise RuntimeError("capture_failed")
        return {"ok": True, "total_frames": len(plan["flashes"]) * 4, "rows": []}
    monkeypatch.setattr(runtime, "capture_visual_evidence", capture)
    monkeypatch.setattr(runtime.P4B, "parse_fcpxml_contract", lambda path: contract())
    monkeypatch.setattr(runtime.P4B, "sha256", lambda path: "fcpxml")
    command = {"task": runtime.TASK_ID, "run_id": "run", "mode": runtime.MODE, "payload": {"repository_root": str(tmp_path), "report_dir": report_rel, "run_mode": "apply", "plan_path": str(plan_path), "plan_sha256": runtime.V4._sha256(plan_path), "fcpxml_path": str(fcpxml), "fcpxml_sha256": "fcpxml", "expected_project": runtime.PROJECT_NAME, "target_timeline_name": runtime.TARGET_TIMELINE_NAME}}
    result = runtime.run(FakeResolve(manager), {"run_id": "run", "command": command})
    return result, manager, order, target, pool, media


def test_save_occurs_exactly_once_and_only_after_visual_validation(tmp_path, monkeypatch):
    result, manager, order, _, _, _ = run_fixture(tmp_path, monkeypatch)
    assert result["ok"] is True
    assert result["save_project_count"] == 1
    assert manager.saves == 1
    assert order == ["capture", "save"]


def test_reel2_like_one_flash_applies_exactly_one_carrier(tmp_path, monkeypatch):
    result, manager, order, _, _, _ = run_fixture(tmp_path, monkeypatch, cuts=(596,))
    assert result["ok"] is True
    assert result["created_carriers"] == result["configured_fusion"] == 1
    assert result["flash_after"]["rows"][0]["start"] == 594
    assert result["visual_evidence"]["total_frames"] == 4
    assert result["protected_timeline_unchanged"] is True
    assert manager.saves == 1 and order == ["capture", "save"]


def test_visual_failure_stops_before_save_and_reports_unsaved_rollback(tmp_path, monkeypatch):
    result, manager, order, _, pool, media = run_fixture(tmp_path, monkeypatch, capture_fails=True)
    assert result["ok"] is False
    assert manager.saves == 0
    assert order == ["capture"]
    assert result["rollback"]["media_delete"]["deleted"] == 1
    assert pool.deleted == [media]


def test_non_target_guard_failure_rolls_back_target_but_preserves_reused_media(tmp_path, monkeypatch):
    result, manager, _, target, pool, media = run_fixture(tmp_path, monkeypatch, ownership_classification="PREEXISTING_COMPATIBLE", non_target_changes=True)
    assert result["failures"] == ["RuntimeError: non_target_timeline_changed"]
    assert manager.saves == 0
    assert target.deleted and target.deleted_tracks == [("video", 2)]
    assert result["rollback"]["media_delete"]["deleted"] == 0
    assert pool.deleted == [] and media.linked is True


def test_non_target_guard_failure_deletes_proven_new_media(tmp_path, monkeypatch):
    result, manager, _, target, pool, media = run_fixture(tmp_path, monkeypatch, ownership_classification="NEWLY_CREATED", non_target_changes=True)
    assert result["failures"] == ["RuntimeError: non_target_timeline_changed"]
    assert manager.saves == 0
    assert target.deleted and target.deleted_tracks == [("video", 2)]
    assert result["rollback"]["media_delete"]["deleted"] == 1
    assert pool.deleted == [media] and media.linked is False


def test_idempotency_branch_performs_no_mutation_or_save(tmp_path, monkeypatch):
    plan = prepare.build_plan(authority((596,)), runtime.PROJECT_NAME, runtime.TARGET_TIMELINE_NAME, contract(), "fcpxml")
    plan_path = tmp_path / "plan.json"; plan_path.write_text(json.dumps(plan), encoding="utf-8")
    fcpxml = tmp_path / "timeline.fcpxml"; fcpxml.write_text("fixture", encoding="utf-8")
    target, protected = object(), object()
    project = FakeProject(); manager = FakeManager(project, [])
    valid = {"ok": True, "count": len(plan["flashes"]), "neutral_carrier_count": len(plan["flashes"]), "source_video_carrier_count": 0, "rows": []}
    monkeypatch.setattr(runtime, "find_one", lambda project, name: target if name == runtime.TARGET_TIMELINE_NAME else protected)
    monkeypatch.setattr(runtime.P4B, "timeline_snapshot", lambda value: {"signature": runtime.PROTECTED_SIGNATURE})
    monkeypatch.setattr(runtime.P4B, "timeline_inventory", lambda project: [{"name": runtime.TARGET_TIMELINE_NAME, "signature": "target"}, {"name": "arbitrary_non_target", "signature": "frozen"}])
    monkeypatch.setattr(runtime, "validate_base_geometry", lambda *args: {"ok": True, "clip_count": 22, "duration_frames": 965, "rows": [], "signature": "base", "snapshot": {"video_track_count": 2}})
    monkeypatch.setattr(runtime.V4, "neutral_flash_snapshot", lambda *args: valid)
    monkeypatch.setattr(runtime, "forbidden_counts", lambda *args: {"speed_retime": 0})
    monkeypatch.setattr(runtime.P4B, "parse_fcpxml_contract", lambda path: contract())
    monkeypatch.setattr(runtime.P4B, "sha256", lambda path: "fcpxml")
    command = {"task": runtime.TASK_ID, "run_id": "run", "mode": runtime.MODE, "payload": {"repository_root": str(tmp_path), "report_dir": "reports/run", "run_mode": "idempotency", "plan_path": str(plan_path), "plan_sha256": runtime.V4._sha256(plan_path), "fcpxml_path": str(fcpxml), "fcpxml_sha256": "fcpxml", "expected_project": runtime.PROJECT_NAME, "target_timeline_name": runtime.TARGET_TIMELINE_NAME}}
    result = runtime.run(FakeResolve(manager), {"run_id": "run", "command": command})
    assert result["ok"] is True and result["idempotent"] is True
    assert result["created_carriers"] == result["configured_fusion"] == result["media_import_count"] == result["track_add_count"] == 0
    assert manager.saves == 0


def test_generic_plan_filters_candidates_and_uses_authority_frame():
    value = authority((596,))
    value["transitions"] += [
        {"transition_type": "whip_pan_candidate", "cut_frame": 434, "editor_actionable": False},
        {"transition_type": "flash_cut", "cut_frame": 700, "editor_actionable": False},
    ]
    plan = prepare.build_plan(value, "Project", "arbitrary_standalone", contract("arbitrary_standalone", 14, 854), "hash")
    assert [(row["cut_frame"], row["start_frame"], row["duration_frames"]) for row in plan["flashes"]] == [(596, 594, 4)]
    assert plan["artifact"] == {"timeline_name": "arbitrary_standalone", "clip_count": 14, "duration_frames": 854, "fps": 24, "fcpxml_sha256": "hash"}


def test_arbitrary_five_flash_shape_is_plan_driven():
    cuts = (12, 120, 240, 480, 800)
    plan = prepare.build_plan(authority(cuts), "Project", "arbitrary_standalone", contract("arbitrary_standalone", 14, 854), "hash")
    assert [row["cut_frame"] for row in plan["flashes"]] == list(cuts)
    assert [row["start_frame"] for row in plan["flashes"]] == [cut - 2 for cut in cuts]
    runtime.validate_plan(plan)


def test_non_target_signature_change_is_rejected():
    try:
        runtime.require_same_non_targets([{"name": "kept", "signature": "before"}], [{"name": "kept", "signature": "after"}])
    except RuntimeError as exc:
        assert str(exc) == "non_target_timeline_changed"
    else:
        raise AssertionError("changed non-target accepted")


def test_base_mapping_regression_is_rejected(monkeypatch):
    snapshot = {"start_frame": 0, "audio_items": [], "settings": {"timelineFrameRate": 24}, "video_items": [{"name": "source", "track_index": 1, "start": 0, "duration": 9, "left_offset": 0, "has_media_pool_item": True, "media_path": "fixture", "fusion_comp_count": 0, "properties": {}}]}
    monkeypatch.setattr(runtime.P4B, "timeline_snapshot", lambda timeline: snapshot)
    broken = {"clips": [{"index": 1, "timeline_start": 0, "source_start": 0, "duration": 10}], "duration_frames": 10, "fps": 24, "source_path": "fixture"}
    try:
        runtime.validate_base_geometry(object(), broken)
    except RuntimeError as exc:
        assert str(exc) == "base_geometry:1"
    else:
        raise AssertionError("mutated V1 mapping accepted")
