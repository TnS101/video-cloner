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


prepare = load_module("scripts/davinci/prepare_advanced_transition_flash_neutral_rgba_v4.py", "flash_neutral_prepare_v4")
runtime = load_module("resolve_workspace/modules/advanced_transition_flash_neutral_rgba_v4.py", "flash_neutral_runtime_v4")
validator = load_module("scripts/davinci/validate_advanced_transition_flash_neutral_rgba_v4.py", "flash_neutral_validator_v4")


def authority_fixture():
    return {
        "transitions": [
            {
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
            }
            for cut in prepare.EXPECTED_FLASH_FRAMES
        ]
    }


def native_transition_fixture():
    return [
        {"name": "Cross Dissolve", "start_frame": 92, "end_frame": 100, "duration_frames": 8},
        {"name": "Cross Dissolve", "start_frame": 373, "end_frame": 382, "duration_frames": 9},
        {"name": "Cross Dissolve", "start_frame": 422, "end_frame": 431, "duration_frames": 9},
        {"name": "Cross Dissolve", "start_frame": 449, "end_frame": 459, "duration_frames": 10},
        {"name": "Cross Dissolve", "start_frame": 754, "end_frame": 762, "duration_frames": 8},
    ]


def plan_fixture():
    plan = prepare.build_plan(authority_fixture(), native_transition_fixture())
    plan["transition_authority_sha256"] = "a" * 64
    plan["fcpxml_authority_sha256"] = "b" * 64
    plan["plan_sha256"] = prepare.canonical_sha256(plan)
    return plan


def test_plan_closes_media_backed_carrier_and_restores_four_frame_source_authority():
    plan = prepare.build_plan(authority_fixture(), native_transition_fixture())
    assert plan["architecture_family"] == "advanced_transition_flash_neutral_rgba_carrier_v1"
    assert plan["attempt_number"] == 1
    assert plan["target_timeline_name"].endswith("_flash_transition_v4")
    assert plan["carrier"] == {
        "kind": "transparent_rgba_sequence",
        "asset_dir": "data/DZsqH7auhjt/davinci/flash_neutral_rgba_v4",
        "pattern": "rgba_%06d.png",
        "frame_count": 4,
        "source_start": 0,
        "source_end_exclusive": 4,
        "media_pool_item_name": "VC_FLASH_NEUTRAL_RGBA_V4",
        "png_sha256": runtime.NEUTRAL_PNG_SHA256,
        "source_video_pixels_possible": False,
    }
    assert plan["property_contract"]["source_video_carrier_forbidden"] is True
    assert plan["property_contract"]["speed_ramp_or_retime_writable"] is False
    assert [row["start_frame"] for row in plan["flashes"]] == [94, 375, 424, 452, 756]
    assert [row["duration_frames"] for row in plan["flashes"]] == [4] * 5
    assert all(row["alpha_keyframes"] == [[0, 0.0], [2, 0.75], [3, 0.0]] for row in plan["flashes"])


def test_runtime_validates_hashed_v4_plan():
    runtime.validate_plan(plan_fixture())


def test_all_four_repo_assets_are_exact_rgba8_and_fully_transparent():
    result = runtime.validate_neutral_assets(ROOT)
    assert result["ok"] is True
    assert result["source_video_pixels_possible"] is False
    assert len(result["rows"]) == 4
    assert all(row["sha256"] == runtime.NEUTRAL_PNG_SHA256 for row in result["rows"])
    assert all(row["all_rgba_zero"] is True for row in result["rows"])
    assert all((row["width"], row["height"], row["bit_depth"], row["color_type"]) == (1080, 1920, 8, 6) for row in result["rows"])


class FakeMediaPoolItem:
    def __init__(self, name="rgba_[000000-000003].png", path=None, uid="media-1", fps="24", alpha="Straight"):
        self.name = name
        self.uid = uid
        self.properties = {
            "File Path": path or str((ROOT / runtime.NEUTRAL_ASSET_DIR_RELATIVE / "rgba_[000000-000003].png").resolve()),
            "Video Frame Rate": fps,
            "Alpha mode": alpha,
        }
        self.rename_writes = 0
        self.property_writes = []

    def GetName(self):
        return self.name

    def SetName(self, name):
        self.rename_writes += 1
        self.name = name
        return True

    def SetClipProperty(self, key, value):
        self.property_writes.append((key, value))
        self.properties[key] = value
        return True

    def GetClipProperty(self):
        return dict(self.properties)

    def GetUniqueId(self):
        return self.uid


class FakeFolder:
    def __init__(self, items): self.items = items
    def GetName(self): return "Master"
    def GetClipList(self): return list(self.items)
    def GetSubFolderList(self): return []


class FakeMediaPool:
    def __init__(self, initial=None, imported=None):
        self.items = list(initial or [])
        self.item = imported or FakeMediaPoolItem()
        self.import_payload = None
        self.import_calls = 0
        self.deleted = []

    def GetRootFolder(self):
        return FakeFolder(self.items)

    def ImportMedia(self, payload):
        self.import_calls += 1
        self.import_payload = payload
        if self.item not in self.items:
            self.items.append(self.item)
        return [self.item]

    def DeleteClips(self, items):
        self.deleted.extend(items)
        return True


def test_import_uses_only_packaged_transparent_rgba_sequence():
    pool = FakeMediaPool()
    assets = runtime.validate_neutral_assets(ROOT)
    result = runtime.import_neutral_carrier(pool, ROOT, assets)
    assert result["ok"] is True
    assert result["kind"] == "transparent_rgba_sequence"
    assert result["source_video_pixels_possible"] is False
    assert result["ownership_classification"] == "NEWLY_CREATED"
    assert result["rollback_delete_permitted"] is True
    assert result["property_write_count"] == 4
    assert result["media_pool_item_name"] == runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME
    assert pool.import_payload == [{
        "FilePath": str((ROOT / runtime.NEUTRAL_ASSET_DIR_RELATIVE / runtime.NEUTRAL_PATTERN).resolve()),
        "StartIndex": 0,
        "EndIndex": 3,
    }]


def test_compatible_preexisting_media_is_reused_read_only_without_import_or_delete():
    shared = FakeMediaPoolItem(runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME)
    pool = FakeMediaPool([shared], shared)
    result = runtime.import_neutral_carrier(pool, ROOT, runtime.validate_neutral_assets(ROOT))
    assert result["ok"] is True
    assert result["ownership_classification"] == "PREEXISTING_COMPATIBLE"
    assert result["import_performed"] is False
    assert result["rename_write_count"] == result["property_write_count"] == 0
    assert pool.import_calls == shared.rename_writes == len(shared.property_writes) == 0
    deleted = runtime._delete_owned_media_pool_item(pool, result)
    assert deleted == {"permitted": False, "attempted": False, "ok": True, "deleted": 0}
    assert pool.deleted == []


def test_preexisting_incompatible_media_fails_before_mutation():
    shared = FakeMediaPoolItem(runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME, fps="25")
    pool = FakeMediaPool([shared], shared)
    result = runtime.import_neutral_carrier(pool, ROOT, runtime.validate_neutral_assets(ROOT))
    assert result["ok"] is False
    assert result["ownership_classification"] == "PREEXISTING_INCOMPATIBLE"
    assert pool.import_calls == shared.rename_writes == len(shared.property_writes) == 0
    assert runtime._delete_owned_media_pool_item(pool, result)["deleted"] == 0


def test_missing_properties_and_duplicate_source_paths_fail_ambiguous():
    unreadable = FakeMediaPoolItem(runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME, alpha="")
    result = runtime.import_neutral_carrier(FakeMediaPool([unreadable]), ROOT, runtime.validate_neutral_assets(ROOT))
    assert result["ownership_classification"] == "OWNERSHIP_AMBIGUOUS"
    first = FakeMediaPoolItem(runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME, uid="one")
    second = FakeMediaPoolItem(runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME, uid="two")
    pool = FakeMediaPool([first, second])
    result = runtime.import_neutral_carrier(pool, ROOT, runtime.validate_neutral_assets(ROOT))
    assert result["ownership_classification"] == "OWNERSHIP_AMBIGUOUS"
    assert result["error"] == "duplicate_preexisting_source"
    assert pool.import_calls == 0
    assert not first.property_writes and not second.property_writes


def test_incomplete_pre_import_inventory_fails_before_import():
    class IncompletePool:
        def ImportMedia(self, payload):
            raise AssertionError("import must not run without complete inventory")
    result = runtime.import_neutral_carrier(IncompletePool(), ROOT, runtime.validate_neutral_assets(ROOT))
    assert result["ownership_classification"] == "OWNERSHIP_AMBIGUOUS"
    assert result["error"] == "pre_import_inventory_incomplete"
    assert result["import_performed"] is False


def test_new_media_without_unique_id_is_proven_by_complete_inventory_delta():
    item = FakeMediaPoolItem(uid="")
    pool = FakeMediaPool(imported=item)
    result = runtime.import_neutral_carrier(pool, ROOT, runtime.validate_neutral_assets(ROOT))
    assert result["ok"] is True
    assert result["ownership_classification"] == "NEWLY_CREATED"


def test_same_display_name_with_different_source_is_not_reused_as_compatible():
    other = FakeMediaPoolItem(runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME, path=str((ROOT / "other.png").resolve()), uid="other")
    created = FakeMediaPoolItem(uid="new")
    pool = FakeMediaPool([other], created)
    result = runtime.import_neutral_carrier(pool, ROOT, runtime.validate_neutral_assets(ROOT))
    assert result["ownership_classification"] == "NEWLY_CREATED"
    assert pool.import_calls == 1
    assert other.rename_writes == 0 and not other.property_writes


def test_import_returning_preexisting_object_with_changed_source_fails_ambiguous():
    other = FakeMediaPoolItem(runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME, path=str((ROOT / "other.png").resolve()), uid="shared")
    pool = FakeMediaPool([other], other)
    original_import = pool.ImportMedia
    def import_existing(payload):
        other.properties["File Path"] = str((ROOT / runtime.NEUTRAL_ASSET_DIR_RELATIVE / "rgba_[000000-000003].png").resolve())
        return original_import(payload)
    pool.ImportMedia = import_existing
    result = runtime.import_neutral_carrier(pool, ROOT, runtime.validate_neutral_assets(ROOT))
    assert result["ownership_classification"] == "OWNERSHIP_AMBIGUOUS"
    assert result["error"] == "returned_media_ownership_ambiguous"
    assert other.rename_writes == 0 and not other.property_writes
    assert runtime._delete_owned_media_pool_item(pool, result)["deleted"] == 0


class FakeTimelineItem:
    def __init__(self, name, media_name):
        self._name = name
        self._media = FakeMediaPoolItem(media_name)

    def GetName(self): return self._name
    def GetMediaPoolItem(self): return self._media
    def GetStart(self): return 0
    def GetEnd(self): return 4
    def GetDuration(self): return 4


class FakeTimeline:
    def __init__(self, items):
        self.items = items

    def GetTrackCount(self, kind):
        return 26 if kind == "video" else 0

    def GetItemListInTrack(self, kind, index):
        if kind == "video" and index == 26:
            return list(self.items)
        return []


def _base_flash_snapshot(flashes, expected_track):
    rows = []
    for row in flashes:
        rows.append({
            "name": row["name"],
            "track_index": expected_track,
            "start": row["start_frame"],
            "end": row["start_frame"] + row["duration_frames"],
            "duration": row["duration_frames"],
            "fusion": {"ok": True},
            "contract_ok": True,
        })
    return {"count": len(rows), "expected_count": len(rows), "track_index": expected_track, "rows": rows, "ok": True}


def test_neutral_flash_snapshot_rejects_any_source_proxy_carrier(monkeypatch):
    flashes = plan_fixture()["flashes"]
    monkeypatch.setattr(runtime.V1, "flash_snapshot", lambda timeline, rows, track: _base_flash_snapshot(rows, track))
    items = [FakeTimelineItem(row["name"], "DZsqH7auhjt_proxy.mp4") for row in flashes]
    result = runtime.neutral_flash_snapshot(FakeTimeline(items), flashes, 26)
    assert result["ok"] is False
    assert result["source_video_carrier_count"] == 5
    assert result["neutral_carrier_count"] == 0


def test_neutral_flash_snapshot_accepts_only_named_transparent_carrier(monkeypatch):
    flashes = plan_fixture()["flashes"]
    monkeypatch.setattr(runtime.V1, "flash_snapshot", lambda timeline, rows, track: _base_flash_snapshot(rows, track))
    items = [FakeTimelineItem(row["name"], runtime.NEUTRAL_MEDIA_POOL_ITEM_NAME) for row in flashes]
    result = runtime.neutral_flash_snapshot(FakeTimeline(items), flashes, 26)
    assert result["ok"] is True
    assert result["source_video_carrier_count"] == 0
    assert result["neutral_carrier_count"] == 5
    assert all(row["carrier"]["source_video_pixels_possible"] is False for row in result["rows"])


def synthetic_target():
    rows = []
    for index, cut in enumerate(validator.EXPECTED_FLASH_FRAMES, start=1):
        rows.append({
            "name": f"VC_FLASH_{index:03d}_frame_{cut:04d}",
            "track_index": 26,
            "start": cut - 2,
            "end": cut + 2,
            "duration": 4,
            "fusion": {"ok": True},
            "carrier": {
                "media_pool_item_name": validator.EXPECTED_NEUTRAL_MEDIA_NAME,
                "neutral_carrier_ok": True,
                "source_video_pixels_possible": False,
            },
            "contract_ok": True,
        })
    return {
        "caption_snapshot": {"count": 114, "sha256": "captions", "video_track_count": 26},
        "native_transition_snapshot": {"count": 6, "rows": [], "sha256": "native"},
        "media_geometry_snapshot": {"count": 3, "rows": [], "sha256": "media"},
        "stale_transition_snapshot": {"count": 0, "rows": [], "sha256": "empty"},
        "flash_snapshot": {
            "count": 5,
            "expected_count": 5,
            "track_index": 26,
            "rows": rows,
            "neutral_carrier_count": 5,
            "source_video_carrier_count": 0,
            "ok": True,
        },
        "caption_count_ok": True,
        "caption_geometry_unchanged": True,
        "media_geometry_unchanged": True,
        "unrelated_transitions_unchanged": True,
        "stale_transitions_absent": True,
        "track_count_ok": True,
        "neutral_carrier_only": True,
        "ok": True,
    }


def synthetic_report(mode):
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
        "neutral_media_import_count": 1 if mode == "apply" else 0,
        "carrier_architecture": "transparent_rgba_sequence_no_source_video_pixels",
        "neutral_asset_verification": {"ok": True, "source_video_pixels_possible": False},
        "carrier_source": {
            "ok": True,
            "kind": "transparent_rgba_sequence",
            "source_video_pixels_possible": False,
            "media_pool_item_name": validator.EXPECTED_NEUTRAL_MEDIA_NAME,
        },
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


def test_validator_accepts_neutral_apply_and_idempotency_contracts():
    assert validator.validate_report(synthetic_report("apply"), "apply")["ok"] is True
    assert validator.validate_report(synthetic_report("idempotency"), "idempotency")["ok"] is True


def test_validator_rejects_proxy_carrier_even_when_fusion_and_geometry_pass():
    report = synthetic_report("apply")
    row = report["target_after"]["flash_snapshot"]["rows"][0]
    row["carrier"]["media_pool_item_name"] = "DZsqH7auhjt_proxy.mp4"
    row["carrier"]["source_video_pixels_possible"] = True
    report["target_after"]["flash_snapshot"]["source_video_carrier_count"] = 1
    report["target_after"]["neutral_carrier_only"] = False
    result = validator.validate_report(report, "apply")
    assert result["ok"] is False
    assert result["checks"]["zero_source_video_carriers"] is False
