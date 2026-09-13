from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.davinci import compile_davinci_textplus_fcpxml as canonical
from scripts.standalone.video_cloner_textplus import (
    StandaloneTextplusError,
    derive_caption_authority,
    prepare_textplus_authority,
    validate_caption_authority,
)


ROOT = Path(__file__).parents[1]
VIDEO_ID = "DcJRJtUKScu"
GENERIC = ROOT / "data" / VIDEO_ID / "planning" / f"{VIDEO_ID}_generic_edit_commands.json"
STYLE = ROOT / "data" / VIDEO_ID / "analysis" / f"{VIDEO_ID}_caption_style.json"


def _reel2():
    generic = json.loads(GENERIC.read_text(encoding="utf-8-sig"))
    style = json.loads(STYLE.read_text(encoding="utf-8-sig"))
    prepared = prepare_textplus_authority(generic, style)
    return generic, prepared


def _cue(index: int, text: str) -> dict:
    start = index * 10
    return {
        "id": f"sub_{index:03d}", "index": index, "text": text,
        "start": start / 24, "end": (start + 5) / 24,
        "start_frame": start, "end_frame": start + 5, "duration_frames": 5,
        "raw": {"timeline_start_frame": start, "timeline_end_frame": start + 5},
    }


def test_reel2_source_corrections_and_coverage_are_exact():
    generic, prepared = _reel2()
    cues = prepared["caption_authority"]["cues"]
    launching = next(cue for cue in cues if cue["source_cue_ids"] == ["sub_088"])
    six_thousand = next(cue for cue in cues if cue["source_cue_ids"] == ["sub_065", "sub_066"])

    assert launching["text"] == "launching"
    assert launching["reconciliation"]["decision"] == "source_corrected"
    assert six_thousand["text"] == "6000"
    assert six_thousand["reconciliation"]["decision"] == "source_composite"
    assert [source for cue in cues for source in cue["source_cue_ids"]] == [
        row["subtitle_id"] for row in generic["subtitle_clips"]
    ]
    assert prepared["caption_authority"]["summary"]["source_coverage_exact"] is True


def test_ambiguous_ocr_falls_back_to_transcript():
    cues = [_cue(1, "correct")]
    style = {
        "caption_style_events": [{
            "event_id": "event_1", "cue_id": "sub_0001", "text": "correct",
            "observed_text": "collect", "observed_texts": ["collect", "connect"],
            "start": 10 / 24, "end": 15 / 24,
        }]
    }
    authority, _ = derive_caption_authority(cues, style, 24.0)
    assert authority[0]["text"] == "correct"
    assert authority[0]["reconciliation"] == {"decision": "transcript_fallback", "evidence": []}


def test_repeated_noise_without_supported_reconciliation_falls_back():
    cues = [_cue(1, "buyers")]
    style = {
        "caption_style_events": [{
            "event_id": "event_1", "cue_id": "sub_0001", "text": "buyers",
            "observed_text": ".bove's", "observed_texts": [".bove's", ".bove's"],
            "start": 10 / 24, "end": 15 / 24,
        }]
    }
    authority, _ = derive_caption_authority(cues, style, 24.0)
    assert authority[0]["text"] == "buyers"
    assert authority[0]["reconciliation"]["decision"] == "transcript_fallback"


@pytest.mark.parametrize("mutation", ["duplicate", "dropped", "non_adjacent"])
def test_invalid_source_coverage_fails_closed(mutation: str):
    source = ["sub_001", "sub_002", "sub_003"]
    cues = [
        {**_cue(1, "one"), "source_cue_ids": ["sub_001"], "reconciliation": {"decision": "transcript_fallback", "evidence": []}},
        {**_cue(2, "two"), "source_cue_ids": ["sub_002"], "reconciliation": {"decision": "transcript_fallback", "evidence": []}},
        {**_cue(3, "three"), "source_cue_ids": ["sub_003"], "reconciliation": {"decision": "transcript_fallback", "evidence": []}},
    ]
    candidate = copy.deepcopy(cues)
    if mutation == "duplicate":
        candidate[1]["source_cue_ids"] = ["sub_001"]
    elif mutation == "dropped":
        candidate.pop(1)
    else:
        candidate = [{**_cue(1, "one three"), "source_cue_ids": ["sub_001", "sub_003"], "reconciliation": {"decision": "source_composite", "evidence": [{"observed_text": "one three"}]}}, candidate[1]]
    with pytest.raises(StandaloneTextplusError):
        validate_caption_authority(candidate, source)


def test_semantic_correction_without_source_evidence_fails_closed():
    cue = {**_cue(1, "changed"), "source_cue_ids": ["sub_001"], "reconciliation": {"decision": "source_corrected", "evidence": []}}
    with pytest.raises(StandaloneTextplusError, match="no source evidence"):
        validate_caption_authority([cue], ["sub_001"])


def test_reel1_lifecycle_regression_remains_exact():
    video_id = "DZsqH7auhjt"
    generic = json.loads((ROOT / "data" / video_id / "planning" / f"{video_id}_generic_edit_commands.json").read_text(encoding="utf-8-sig"))
    style = json.loads((ROOT / "data" / video_id / "analysis" / f"{video_id}_caption_style.json").read_text(encoding="utf-8-sig"))
    lifecycle = json.loads((ROOT / "data" / video_id / "analysis" / f"{video_id}_caption_lifecycle_authority_step_3D_calibrated.json").read_text(encoding="utf-8-sig"))
    prepared = prepare_textplus_authority(generic, style, lifecycle)
    metrics = prepared["caption_metrics"]
    assert (metrics["semantic_cue_count"], metrics["casing_difference_count"], metrics["lifecycle_timing_change_count"]) == (116, 10, 48)
    assert (metrics["overlap_pair_count"], metrics["same_lane_overlap_count"], metrics["lane_usage"]) == (46, 0, {"1": 72, "2": 22, "3": 16, "4": 5, "5": 1})
    assert prepared["caption_authority"]["summary"]["source_coverage_exact"] is True
