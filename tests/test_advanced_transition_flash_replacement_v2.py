from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_module("scripts/davinci/prepare_advanced_transition_flash_replacement_v2.py", "flash_replace_prepare")
runtime = load_module("resolve_workspace/modules/advanced_transition_flash_replacement_v2.py", "flash_replace_runtime")
validator = load_module("scripts/davinci/validate_advanced_transition_flash_replacement_v2.py", "flash_replace_validator")


def authority_fixture():
    rows = []
    for cut in prepare.EXPECTED_FLASH_FRAMES:
        rows.append({
            "transition_type": "flash_cut",
            "confidence": "high",
            "editor_actionable": True,
            "cut_frame": cut,
            "duration_frames": 4,
            "outgoing_frames": 2,
            "incoming_frames": 2,
            "placement": "at_cut",
            "handle_check": {"ok": True},
            "reasons": ["white-frame/luma spike near boundary"],
            "transition_strength": 0.75,
            "scores": {"white_ratio_max": 0.6, "luma_delta": 0.2},
        })
    return {"transitions": rows}


def native_transition_fixture():
    return [
        {"name": "Cross Dissolve", "start_frame": 92, "end_frame": 100, "duration_frames": 8},
        {"name": "Cross Dissolve", "start_frame": 373, "end_frame": 382, "duration_frames": 9},
        {"name": "Cross Dissolve", "start_frame": 422, "end_frame": 431, "duration_frames": 9},
        {"name": "Cross Dissolve", "start_frame": 449, "end_frame": 459, "duration_frames": 10},
        {"name": "Slide", "start_frame": 488, "end_frame": 496, "duration_frames": 8},
        {"name": "Cross Dissolve", "start_frame": 522, "end_frame": 530, "duration_frames": 8},
        {"name": "Cross Dissolve", "start_frame": 552, "end_frame": 560, "duration_frames": 8},
        {"name": "Slide", "start_frame": 583, "end_frame": 591, "duration_frames": 8},
        {"name": "Slide", "start_frame": 614, "end_frame": 622, "duration_frames": 8},
        {"name": "Cross Dissolve", "start_frame": 754, "end_frame": 762, "duration_frames": 8},
        {"name": "Cross Dissolve", "start_frame": 829, "end_frame": 837, "duration_frames": 8},
    ]


def plan_fixture():
    plan = prepare.build_plan(authority_fixture(), native_transition_fixture())
    plan["transition_authority_sha256"] = "a" * 64
    plan["fcpxml_authority_sha256"] = "b" * 64
    plan["plan_sha256"] = prepare.canonical_sha256(plan)
    return plan


def test_parse_real_lifecycle_fcpxml_recovers_exact_five_stale_substitutes():
    rows = prepare.parse_native_transitions(
        ROOT / "data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_step_3D_lifecycle.fcpxml"
    )
    assert len(rows) == 11
    plan = prepare.build_plan(authority_fixture(), rows)
    assert [row["stale_native_transition"] for row in plan["flashes"]] == [
        {"name": "Cross Dissolve", "start_frame": 92, "end_frame": 100, "duration_frames": 8},
        {"name": "Cross Dissolve", "start_frame": 373, "end_frame": 382, "duration_frames": 9},
        {"name": "Cross Dissolve", "start_frame": 422, "end_frame": 431, "duration_frames": 9},
        {"name": "Cross Dissolve", "start_frame": 449, "end_frame": 459, "duration_frames": 10},
        {"name": "Cross Dissolve", "start_frame": 754, "end_frame": 762, "duration_frames": 8},
    ]


def test_plan_preserves_r5_flash_contract_while_authorizing_only_stale_transition_deletion():
    plan = prepare.build_plan(authority_fixture(), native_transition_fixture())
    assert plan["architecture_family"] == "advanced_transition_flash_replacement_v2"
    assert plan["attempt_number"] == 2
    assert plan["target_timeline_name"].endswith("_flash_transition_v2")
    assert plan["property_contract"]["clip_boundaries_writable"] is False
    assert plan["property_contract"]["unrelated_transitions_writable"] is False
    assert plan["property_contract"]["existing_timeline_items_writable"] == "only_exact_five_stale_cross_dissolve_items_on_isolated_duplicate"
    for row in plan["flashes"]:
        assert row["duration_frames"] == 4
        assert row["start_frame"] == row["cut_frame"] - 2
        assert row["flash_color"] == [1.0, 1.0, 1.0]
        assert row["alpha_keyframes"] == [[0, 0.0], [2, 0.75], [3, 0.0]]


def test_plan_rejects_when_stale_cross_dissolve_is_not_unique():
    native = native_transition_fixture()
    native.append(dict(native[0]))
    try:
        prepare.build_plan(authority_fixture(), native)
    except ValueError as exc:
        assert "stale_transition_authority:96:2" in str(exc)
    else:
        raise AssertionError("duplicate stale transition accepted")


def test_runtime_validates_hashed_v2_plan():
    runtime.validate_plan(plan_fixture())


class FakeMediaPoolItem:
    def __init__(self, name: str):
        self.name = name

    def GetName(self):
        return self.name


class FakeItem:
    def __init__(self, name: str, start: int, end: int, media_name: str | None = None):
        self.name = name
        self.start = start
        self.end = end
        self.media = FakeMediaPoolItem(media_name) if media_name else None

    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.end - self.start
    def GetMediaPoolItem(self): return self.media


class FakeTimeline:
    def __init__(self, tracks):
        self.tracks = tracks
        self.delete_calls = 0

    def GetTrackCount(self, kind):
        return max(self.tracks) if kind == "video" else 0

    def GetItemListInTrack(self, kind, index):
        return list(self.tracks.get(index, [])) if kind == "video" else []

    def DeleteClips(self, items, ripple=False):
        assert ripple is False
        self.delete_calls += 1
        wanted = set(map(id, items))
        for index in list(self.tracks):
            self.tracks[index] = [item for item in self.tracks[index] if id(item) not in wanted]
        return True


def make_timeline(duplicate_first=False):
    transitions = [
        FakeItem(row["name"], row["start_frame"], row["end_frame"])
        for row in native_transition_fixture()
    ]
    if duplicate_first:
        transitions.append(FakeItem("Cross Dissolve", 92, 100))
    tracks = {
        1: [FakeItem("base-1", 0, 400, "proxy.mp4"), FakeItem("base-2", 400, 965, "proxy.mp4")] + transitions,
        2: [FakeItem("foreground", 430, 452, "foreground.mov")],
        3: [FakeItem("VC_TEXTPLUS_0001_sub_001", 139, 148)],
    }
    return FakeTimeline(tracks)


def test_removal_deletes_exact_five_and_preserves_media_and_unrelated_transitions():
    timeline = make_timeline()
    flashes = plan_fixture()["flashes"]
    before_native = runtime.native_transition_snapshot(timeline)
    before_media = runtime.media_geometry_snapshot(timeline)
    result = runtime.remove_stale_native_transitions(timeline, flashes)
    assert result["ok"] is True
    assert result["delete_count"] == 5
    assert timeline.delete_calls == 1
    assert result["stale_after"]["count"] == 0
    assert result["media_geometry_unchanged"] is True
    assert result["unrelated_transitions_unchanged"] is True
    assert runtime.media_geometry_snapshot(timeline)["sha256"] == before_media["sha256"]
    assert runtime.native_transition_snapshot(timeline)["count"] == before_native["count"] - 5
    assert [(row["name"], row["start"], row["end"]) for row in runtime.native_transition_snapshot(timeline)["rows"]] == [
        ("Slide", 488, 496),
        ("Cross Dissolve", 522, 530),
        ("Cross Dissolve", 552, 560),
        ("Slide", 583, 591),
        ("Slide", 614, 622),
        ("Cross Dissolve", 829, 837),
    ]


def test_removal_stops_before_mutation_when_targeted_transition_is_ambiguous():
    timeline = make_timeline(duplicate_first=True)
    result = runtime.remove_stale_native_transitions(timeline, plan_fixture()["flashes"])
    assert result["ok"] is False
    assert result["delete_count"] == 0
    assert timeline.delete_calls == 0
    assert any(error.startswith("stale_transition_match:96:2") for error in result["errors"])


def synthetic_target():
    rows = []
    for index, cut in enumerate([96, 377, 426, 454, 758], start=1):
        rows.append({
            "name": f"VC_FLASH_{index:03d}_frame_{cut:04d}",
            "track_index": 26,
            "start": cut - 2,
            "end": cut + 2,
            "duration": 4,
            "fusion": {"ok": True},
            "contract_ok": True,
        })
    return {
        "caption_snapshot": {"count": 114, "sha256": "captions", "video_track_count": 26},
        "native_transition_snapshot": {"count": 6, "rows": [], "sha256": "native"},
        "media_geometry_snapshot": {"count": 3, "rows": [], "sha256": "media"},
        "stale_transition_snapshot": {"count": 0, "rows": [], "sha256": "empty"},
        "flash_snapshot": {"count": 5, "expected_count": 5, "track_index": 26, "rows": rows, "ok": True},
        "caption_count_ok": True,
        "caption_geometry_unchanged": True,
        "media_geometry_unchanged": True,
        "unrelated_transitions_unchanged": True,
        "stale_transitions_absent": True,
        "track_count_ok": True,
        "ok": True,
    }


def synthetic_report(mode: str):
    report = {
        "ok": True,
        "task_id": validator.TASK_ID,
        "run_id": "run",
        "run_mode": mode,
        "expected_textplus_count": 114,
        "expected_flash_count": 5,
        "expected_stale_transition_delete_count": 5,
        "source_timeline_unchanged": True,
        "target_after": synthetic_target(),
        "save_call_count": 1 if mode == "apply" else 0,
        "timeline_duplicate_count": 1 if mode == "apply" else 0,
        "stale_transition_delete_count": 5 if mode == "apply" else 0,
        "video_track_add_count": 1 if mode == "apply" else 0,
        "flash_carrier_append_count": 5 if mode == "apply" else 0,
        "fusion_flash_configure_count": 5 if mode == "apply" else 0,
    }
    if mode == "apply":
        report.update({
            "persistent_readback_ok": True,
            "visual_approval_required": True,
            "stale_transition_removal": {
                "ok": True,
                "media_geometry_unchanged": True,
                "unrelated_transitions_unchanged": True,
            },
        })
    else:
        report.update({"idempotent": True, "visual_approval_required": False})
    return report


def test_validator_accepts_apply_and_idempotency_contracts():
    apply_result = validator.validate_report(synthetic_report("apply"), "apply")
    idem_result = validator.validate_report(synthetic_report("idempotency"), "idempotency")
    assert apply_result["ok"] is True
    assert idem_result["ok"] is True


def test_validator_rejects_any_remaining_stale_cross_dissolve():
    report = synthetic_report("apply")
    report["target_after"]["stale_transition_snapshot"]["count"] = 1
    report["target_after"]["stale_transitions_absent"] = False
    result = validator.validate_report(report, "apply")
    assert result["ok"] is False
    assert result["checks"]["stale_transitions_absent"] is False
