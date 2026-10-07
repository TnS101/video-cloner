from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from video_cloner.captions.textplus import (
    StandaloneTextplusError,
    compile_textplus,
    validate_caption_cues,
)


ROOT = Path(__file__).parents[1]
VIDEO_ID = "DZsqH7auhjt"
GENERIC = ROOT / "data" / VIDEO_ID / "planning" / f"{VIDEO_ID}_generic_edit_commands.json"
STYLE = ROOT / "data" / VIDEO_ID / "analysis" / f"{VIDEO_ID}_caption_style.json"
LIFECYCLE = ROOT / "data" / VIDEO_ID / "analysis" / f"{VIDEO_ID}_caption_lifecycle_authority_step_3D_calibrated.json"


def _compile(tmp_path: Path) -> tuple[dict, Path]:
    output = tmp_path / "reel1_textplus.fcpxml"
    report = compile_textplus(GENERIC, STYLE, output, tmp_path / "report.json", LIFECYCLE)
    return report, output


def test_reel1_real_authority_reaches_deterministic_standalone_textplus(tmp_path: Path):
    first, output = _compile(tmp_path)
    first_bytes = output.read_bytes()
    second, _ = _compile(tmp_path)
    metrics = first["caption_metrics"]
    lifecycle = first["caption_lifecycle"]

    assert {key: value for key, value in metrics.items() if key != "casing_differences"} == {
        "semantic_cue_count": 116,
        "overlap_pair_count": 46,
        "all_interval_overlap_pair_count": 88,
        "same_lane_overlap_count": 0,
        "lane_usage": {"1": 72, "2": 22, "3": 16, "4": 5, "5": 1},
        "dropped_semantic_words": 0,
        "added_semantic_words": 0,
        "casing_difference_count": 10,
        "lifecycle_timing_change_count": 48,
    }
    assert metrics["casing_differences"] == [
        {"cue_id": "sub_051", "generic": "They", "output": "THEY"},
        {"cue_id": "sub_052", "generic": "come", "output": "COME"},
        {"cue_id": "sub_058", "generic": "knows", "output": "KNOWS"},
        {"cue_id": "sub_086", "generic": "that", "output": "THAT"},
        {"cue_id": "sub_087", "generic": "you", "output": "YOU"},
        {"cue_id": "sub_089", "generic": "overnight.", "output": "OVERNIGHT."},
        {"cue_id": "sub_090", "generic": "I've", "output": "I'VE"},
        {"cue_id": "sub_093", "generic": "in", "output": "IN"},
        {"cue_id": "sub_095", "generic": "since", "output": "SINCE"},
        {"cue_id": "sub_114", "generic": "and", "output": "AND"},
    ]
    assert lifecycle["lane_allocation"]["lane_count"] == 5
    assert len(ET.parse(output).getroot().findall(".//title")) == 116
    assert output.read_bytes() == first_bytes
    assert second["output"]["sha256"] == first["output"]["sha256"]
    assert first["edit_operations_compiled"] is False
    assert first["resolve_invoked"] is False


def test_explicit_missing_lifecycle_fails_closed(tmp_path: Path):
    with pytest.raises(StandaloneTextplusError, match="caption lifecycle authority"):
        compile_textplus(GENERIC, STYLE, tmp_path / "out.fcpxml", tmp_path / "report.json", tmp_path / "missing.json")


def test_lifecycle_is_optional_only_when_not_requested(tmp_path: Path):
    report = compile_textplus(GENERIC, STYLE, tmp_path / "out.fcpxml", tmp_path / "report.json")
    assert report["caption_lifecycle"] == {"enabled": False}
    assert report["output"]["title_count"] == 116


@pytest.mark.parametrize("mutation", ["mismatched", "duplicate", "dropped_lifecycle", "dropped_generic", "duplicate_generic"])
def test_lifecycle_and_generic_cue_identity_fail_closed(tmp_path: Path, mutation: str):
    generic = json.loads(GENERIC.read_text(encoding="utf-8-sig"))
    lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8-sig"))
    if mutation == "mismatched":
        lifecycle["layers"][0]["cue_id"] = "sub_999"
    elif mutation == "duplicate":
        lifecycle["layers"][1]["cue_id"] = lifecycle["layers"][0]["cue_id"]
    elif mutation == "dropped_lifecycle":
        lifecycle["layers"].pop()
    elif mutation == "dropped_generic":
        generic["subtitle_clips"].pop()
    else:
        generic["subtitle_clips"][1] = copy.deepcopy(generic["subtitle_clips"][0])
    generic_path = tmp_path / "generic.json"
    lifecycle_path = tmp_path / "lifecycle.json"
    generic_path.write_text(json.dumps(generic), encoding="utf-8")
    lifecycle_path.write_text(json.dumps(lifecycle), encoding="utf-8")
    with pytest.raises(StandaloneTextplusError):
        compile_textplus(generic_path, STYLE, tmp_path / "out.fcpxml", tmp_path / "report.json", lifecycle_path)


def test_same_lane_overlap_fails_closed():
    cues = [
        {"id": "sub_001", "start_frame": 0, "end_frame": 5, "lane": 1},
        {"id": "sub_002", "start_frame": 2, "end_frame": 6, "lane": 1},
    ]
    with pytest.raises(StandaloneTextplusError, match="same-lane"):
        validate_caption_cues(cues, ["sub_001", "sub_002"])
