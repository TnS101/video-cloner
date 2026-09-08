from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_v6_legacy_basic_title_cleanup.py"
SPEC = importlib.util.spec_from_file_location("cleanup_module_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cleanup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cleanup
SPEC.loader.exec_module(cleanup)


class FakeMediaPoolItem:
    def __init__(self, name: str):
        self.name = name

    def GetName(self):
        return self.name


class FakeItem:
    def __init__(
        self,
        name: str,
        track: int,
        start: int,
        end: int,
        fusion_comp_count: int = 0,
        media_pool_item_name: str | None = None,
    ):
        self.name = name
        self.track = track
        self.start = start
        self.end = end
        self.fusion_comp_count = fusion_comp_count
        self.media_pool_item = FakeMediaPoolItem(media_pool_item_name) if media_pool_item_name else None

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetFusionCompCount(self):
        return self.fusion_comp_count

    def GetMediaPoolItem(self):
        return self.media_pool_item

    def GetUniqueId(self):
        return f"{self.track}:{self.name}:{self.start}:{self.end}"


class FakeTimeline:
    def __init__(self, items):
        self.items = list(items)

    def GetTrackCount(self, kind):
        return max((item.track for item in self.items), default=0) if kind == "video" else 0

    def GetItemListInTrack(self, kind, track):
        if kind != "video":
            return []
        return [item for item in self.items if item.track == track]


class CleanupTests(unittest.TestCase):
    def legacy_item(self, index: int = 0):
        return FakeItem("Text", 2, index * 3, index * 3 + 3)

    def textplus_item(self, track: int, index: int):
        return FakeItem(
            f"VC_TEXTPLUS_{index:04d}_sub_{index:03d}",
            track,
            index * 4,
            index * 4 + 4,
            fusion_comp_count=1,
            media_pool_item_name="DZsqH7auhjt_proxy.mp4",
        )

    def test_legacy_classifier_is_exact_to_v2_text_without_media_pool_item(self):
        self.assertTrue(cleanup.is_legacy_basic_title(2, self.legacy_item()))
        self.assertFalse(cleanup.is_legacy_basic_title(3, FakeItem("Text", 3, 0, 3)))
        self.assertFalse(cleanup.is_legacy_basic_title(2, FakeItem("Other", 2, 0, 3)))
        self.assertFalse(cleanup.is_legacy_basic_title(2, FakeItem("Text", 2, 0, 3, media_pool_item_name="clip.mp4")))

    def test_rows_without_legacy_removes_only_the_exact_v2_basic_title_rows(self):
        rows = [
            {"name": "Text", "track_index": 2, "media_pool_item_name": None},
            {"name": "Text", "track_index": 3, "media_pool_item_name": None},
            {"name": "Other", "track_index": 2, "media_pool_item_name": None},
            {"name": "Text", "track_index": 2, "media_pool_item_name": "clip.mp4"},
        ]
        result = cleanup.rows_without_legacy(rows)
        self.assertEqual(len(result), 3)
        self.assertNotIn(rows[0], result)
        self.assertIn(rows[1], result)
        self.assertIn(rows[2], result)
        self.assertIn(rows[3], result)

    def test_textplus_inventory_requires_exact_v6_track_usage(self):
        items = []
        index = 1
        for track, count in cleanup.EXPECTED_TEXTPLUS_TRACK_USAGE.items():
            for _ in range(count):
                items.append(self.textplus_item(track, index))
                index += 1
        result = cleanup.textplus_inventory(FakeTimeline(items))
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 115)
        self.assertEqual(result["track_usage"], {"3": 71, "4": 21, "5": 16, "6": 5, "7": 2})

    def test_textplus_inventory_rejects_missing_fusion_comp(self):
        items = []
        index = 1
        for track, count in cleanup.EXPECTED_TEXTPLUS_TRACK_USAGE.items():
            for _ in range(count):
                item = self.textplus_item(track, index)
                items.append(item)
                index += 1
        items[0].fusion_comp_count = 0
        result = cleanup.textplus_inventory(FakeTimeline(items))
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["fusion_comp_count"])

    def test_matte_inventory_requires_exact_preserved_matte(self):
        matte = FakeItem(
            cleanup.EXPECTED_MATTE["name"],
            4,
            429,
            434,
            media_pool_item_name=cleanup.EXPECTED_MATTE["media_pool_item_name"],
        )
        result = cleanup.matte_inventory(FakeTimeline([matte]))
        self.assertTrue(result["ok"])

    def test_partition_rejects_nonlegacy_item_on_v2(self):
        items = [self.legacy_item(index) for index in range(116)]
        items.append(FakeItem("Unexpected", 2, 500, 505))
        result = cleanup.partition_inventory(FakeTimeline(items))
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["track_two_contains_only_legacy"])

    def test_constants_target_a_new_cleanup_timeline_and_preserve_v6(self):
        self.assertEqual(cleanup.SOURCE_TIMELINE_NAME, "DZsqH7auhjt_textplus_full_step_3D_complete_v6_exact_lifecycles")
        self.assertEqual(cleanup.TARGET_TIMELINE_NAME, "DZsqH7auhjt_textplus_full_step_3D_complete_v6_textplus_only")
        self.assertNotEqual(cleanup.SOURCE_TIMELINE_NAME, cleanup.TARGET_TIMELINE_NAME)
        self.assertEqual(cleanup.LEGACY_TRACK_INDEX, 2)
        self.assertEqual(cleanup.EXPECTED_LEGACY_COUNT, 116)
        self.assertEqual(cleanup.EXPECTED_TEXTPLUS_COUNT, 115)


if __name__ == "__main__":
    unittest.main()
