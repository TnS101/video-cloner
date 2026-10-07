from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_preflight_preserves_accepted_f7_contract() -> None:
    module = _load(ROOT / "scripts/davinci/prepare_video_cloner_step5_f8_generated_only_review.py", "f8_review_prepare")
    result = module.preflight(ROOT)
    assert result["pass"] is True
    assert result["renderables"] == 65
    assert result["same_track_conflicts"] == 0
    assert result["f2_f7_invariants_unchanged"] is True
    assert result["f6_6000_interval"] == [542, 596]
    assert result["f3_6000_scale_keys"] == 9
    assert result["protected_timeline_mutation_planned"] is False
    assert result["f7_timeline_mutation_planned"] is False


def test_underlay_deletion_targets_only_non_fusion_and_non_video_items() -> None:
    module = _load(ROOT / "resolve_workspace/modules/video_cloner_step5_f8_generated_only_review.py", "f8_review_runtime")

    class Item:
        def __init__(self, fusion): self.fusion = fusion
        def GetFusionCompCount(self): return self.fusion

    captions = [Item(1), Item(1)]
    source, audio = Item(0), Item(0)

    class Timeline:
        def GetTrackCount(self, kind): return {"video": 2, "audio": 1, "subtitle": 0}[kind]
        def GetItemListInTrack(self, kind, track):
            return source if False else ({("video", 1): [source], ("video", 2): captions, ("audio", 1): [audio]}.get((kind, track), []))
        def DeleteClips(self, items, ripple):
            assert items == [source, audio]
            assert ripple is False
            return True

    assert module._delete_underlay(Timeline()) == {"ok": True, "video_items": 1, "audio_items": 1, "subtitle_items": 0, "total": 2}
