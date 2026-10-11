from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.analysis import benchmark_oss002c_cross_authority_association as benchmark
from video_cloner.text_localization_oss import associate_caption, lifecycle_proposals, phrase_lattice


ROOT = Path(__file__).resolve().parents[1]


CAPTIONS = [
    {"ordinal": index, "caption_id": f"sub_{index:03d}", "text": text, "start_frame": 10 + index * 3, "duration": 3}
    for index, text in enumerate(("previous", "current", "next", "later"), 1)
]
BOX = [30, 40, 70, 60]
PRIORS = [{"bbox": BOX}]


def _associate(text: str, *, candidates: list[dict] | None = None):
    rows = candidates or [{"bbox": BOX, "text": text, "confidence": 0.95}]
    return associate_caption(CAPTIONS, CAPTIONS[1], 24.0, (100, 100), {frame: copy.deepcopy(rows) for frame in (16, 17, 18)}, "paddleocr_fallback", PRIORS)


@pytest.mark.parametrize("phrase", ["CURRENT headline", "previous current", "current next", "previous\ncurrent\nnext", "curent next"])
def test_phrase_lattice_accepts_contained_neighbor_stacked_and_fuzzy_text(phrase):
    event = _associate(phrase)
    assert event["localization_confidence"] >= 0.62
    assert event["localization_evidence"]["first_visible_frame"] == 16
    assert phrase_lattice(CAPTIONS, 2)


def test_spatial_continuity_selects_the_caption_region():
    event = _associate(
        "current next",
        candidates=[
            {"bbox": BOX, "text": "current next", "confidence": 0.80},
            {"bbox": [2, 2, 28, 18], "text": "current", "confidence": 0.99},
        ],
    )
    assert event["placement"]["bbox"] == pytest.approx(BOX)


def test_caption_timing_bounds_the_detection_window():
    detections = {frame: [{"bbox": BOX, "text": "current next", "confidence": 0.95}] for frame in (16, 17, 18)}
    detections[99] = [{"bbox": [1, 1, 20, 20], "text": "current", "confidence": 1.0}]
    event = associate_caption(CAPTIONS, CAPTIONS[1], 24.0, (100, 100), detections, "paddleocr_fallback", PRIORS)
    assert [row["frame"] for row in event["localization_evidence"]["frames"]] == [16, 17, 18]


def test_ambiguous_regions_fail_closed():
    with pytest.raises(ValueError, match="association_missing"):
        _associate(
            "current",
            candidates=[
                {"bbox": [5, 40, 25, 60], "text": "current", "confidence": 0.95},
                {"bbox": [75, 40, 95, 60], "text": "current", "confidence": 0.95},
            ],
        )


def test_one_composition_maps_multiple_ordinals_and_preserves_lifecycle():
    first = _associate("previous current")
    second = copy.deepcopy(first)
    second["source_caption_ordinals"] = [2, 3]
    second["localization_evidence"]["first_visible_frame"] = 19
    second["localization_evidence"]["last_visible_frame"] = 21
    for row, frame in zip(second["localization_evidence"]["frames"], (19, 20, 21)):
        row["frame"] = frame
    proposals = lifecycle_proposals([first, second], (100, 100))
    assert len(proposals) == 1
    assert proposals[0]["token_ordinals"] == [1, 2, 3]
    assert (proposals[0]["visible_start"], proposals[0]["visible_end"]) == (16, 21)
    assert proposals[0]["token_visibility"]["3"]["joins_previous_composition"] is True


def test_existing_56_recipe_authority_is_unchanged():
    path = ROOT / "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_animation_recipes_oss002_full.json"
    recovery = json.loads((ROOT / "data/DZatr0EJt4B/analysis/DZatr0EJt4B_oss002c_cross_authority_recovery.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == recovery["existing_56_recipe_authority"]["sha256"]
    assert recovery["existing_56_recipe_authority"]["modified"] is False


def test_successful_association_is_passed_to_existing_tracker(tmp_path, monkeypatch):
    class Capture:
        def get(self, prop):
            return {benchmark.cv2.CAP_PROP_FPS: 24.0, benchmark.cv2.CAP_PROP_FRAME_HEIGHT: 100, benchmark.cv2.CAP_PROP_FRAME_WIDTH: 100}[prop]

        def release(self):
            pass

    seen = []
    monkeypatch.setattr(benchmark.cv2, "VideoCapture", lambda _: Capture())
    monkeypatch.setattr(benchmark, "derive_recipe", lambda video, caption, event, route: seen.append(event) or {"confidence": 0.9})
    manifest = tmp_path / "manifest.json"
    raw = tmp_path / "raw.json"
    style = tmp_path / "style.json"
    manifest.write_text(json.dumps({"captions": CAPTIONS}), encoding="utf-8")
    raw.write_text(json.dumps({"results": [{"ordinal": 2, "anchor_candidates": {str(frame): [{"bbox": BOX, "text": "previous current", "confidence": 0.95}] for frame in (16, 17, 18)}}]}), encoding="utf-8")
    style.write_text(json.dumps({"style_events": [{"role": "spoken_caption", "start": 0.0, "end": 2.0, "placement": {"bbox": BOX}}]}), encoding="utf-8")
    result = benchmark.build(tmp_path / "video.mp4", manifest, style, raw, "paddleocr_fallback")
    assert result["associated"] == 1 and seen[0]["observations"]
