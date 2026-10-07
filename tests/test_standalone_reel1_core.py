from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from video_cloner.resolve import fcpxml as canonical
from video_cloner.captions.fcpxml import FcpxmlCompilationError, compile_fcpxml


ROOT = Path(__file__).parents[1]
VIDEO_ID = "DZsqH7auhjt"
GENERIC = ROOT / "data" / VIDEO_ID / "planning" / f"{VIDEO_ID}_generic_edit_commands.json"
STYLE = ROOT / "data" / VIDEO_ID / "analysis" / f"{VIDEO_ID}_caption_style.json"
LIFECYCLE = ROOT / "data" / VIDEO_ID / "analysis" / f"{VIDEO_ID}_caption_lifecycle_authority_step_3D_calibrated.json"
TRANSITIONS = ROOT / "data" / VIDEO_ID / "analysis" / f"{VIDEO_ID}_transition_authority_accepted_reel1_v1.json"
RUN_ID = "DZsqH7auhjt_accepted_reel1_transition_authority_v1"


def _safe_generic(tmp_path: Path) -> tuple[Path, dict]:
    generic = json.loads(GENERIC.read_text(encoding="utf-8-sig"))
    for command in generic["timeline"]:
        command["action"] = {"type": "cut"}
        command["operations"] = [{"operation": "cut", "parameters": {"cut_policy": "use_compiled_timeline_range"}}]
    generic["summary"]["operation_counts"] = {"cut": len(generic["timeline"])}
    path = tmp_path / "DZsqH7auhjt_safe_generic_edit_commands.json"
    path.write_text(json.dumps(generic), encoding="utf-8")
    return path, generic


def _kwargs(generic: Path, output: Path, report: Path) -> dict:
    return {
        "generic_path": generic,
        "output_fcpxml": output,
        "report_path": report,
        "caption_style_path": STYLE,
        "caption_lifecycle_path": LIFECYCLE,
        "transition_authority_path": TRANSITIONS,
        "transition_run_id": RUN_ID,
        "parity_video_id": VIDEO_ID,
    }


def test_reel1_combined_core_timeline_is_exact_and_byte_deterministic(tmp_path: Path):
    generic_path, generic = _safe_generic(tmp_path)
    output = tmp_path / "DZsqH7auhjt_standalone_core.fcpxml"
    report_path = tmp_path / "DZsqH7auhjt_standalone_core_report.json"
    first = compile_fcpxml(**_kwargs(generic_path, output, report_path))
    first_xml = output.read_bytes()
    first_report = report_path.read_bytes()
    second = compile_fcpxml(**_kwargs(generic_path, output, report_path))
    root = ET.parse(output).getroot()

    clips = root.findall("./library/event/project/sequence/spine/asset-clip[@ref='r3']")
    caption_titles = [title for title in root.findall(".//title") if title.find("marker") is None]
    handoffs = [title for title in root.findall(".//title") if title.find("marker") is not None]
    native = root.findall(".//transition")
    expected_clip_timing = [
        (
            canonical.frames_to_fcpx_time(command["timeline_start_frame"], 24.0),
            canonical.frames_to_fcpx_time(command["source_start_frame"], 24.0),
            canonical.frames_to_fcpx_time(command["timeline_duration_frames"], 24.0),
        )
        for command in generic["timeline"]
    ]

    assert [(clip.get("offset"), clip.get("start"), clip.get("duration")) for clip in clips] == expected_clip_timing
    assert len(root.findall("./library/event/project/sequence/spine/asset-clip[@ref='r4'][@lane='-1']")) == 1
    assert first["structure"] == {
        "resource_count": 6,
        "video_asset_count": 1,
        "audio_asset_count": 1,
        "clip_count": 22,
        "caption_count": 116,
        "native_transition_count": 6,
        "flash_handoff_count": 5,
        "timeline_duration_frames": 965,
        "forbidden_xml_construct_counts": {
            "transition": 0, "title": 0, "timeMap": 0, "timept": 0,
            "adjust-transform": 0, "filter-video": 0,
        },
    }
    metrics = first["caption_authority"]["metrics"]
    assert {key: metrics[key] for key in (
        "semantic_cue_count", "dropped_semantic_words", "added_semantic_words",
        "casing_difference_count", "lifecycle_timing_change_count", "overlap_pair_count",
        "same_lane_overlap_count", "lane_usage",
    )} == {
        "semantic_cue_count": 116,
        "dropped_semantic_words": 0,
        "added_semantic_words": 0,
        "casing_difference_count": 10,
        "lifecycle_timing_change_count": 48,
        "overlap_pair_count": 46,
        "same_lane_overlap_count": 0,
        "lane_usage": {"1": 72, "2": 22, "3": 16, "4": 5, "5": 1},
    }
    assert first["transition_authority"]["decision_count"] == 11
    assert first["compiled_operation_counts"] == {
        "speed": 0, "animated_zoom": 0, "whip": 0, "slide": 0, "blur": 0,
        "transitions": 6, "slide_edge_wipe": 3, "cross_dissolve": 3,
        "flash_handoffs": 5, "captions": 116,
    }
    assert len(caption_titles) == 116
    assert {lane: sum(title.get("lane") == lane for title in caption_titles) for lane in "12345"} == {
        "1": 72, "2": 22, "3": 16, "4": 5, "5": 1,
    }
    assert [item.get("name") for item in native] == ["Slide", "Cross Dissolve", "Cross Dissolve", "Slide", "Slide", "Cross Dissolve"]
    assert len(handoffs) == 5
    assert {handoff.get("lane") for handoff in handoffs} == {"6"}
    assert root.findall(".//timeMap") == root.findall(".//asset-clip/adjust-transform") == root.findall(".//filter-video") == []
    assert first["resolve_invoked"] is first["timeline_mutated"] is first["save_project_invoked"] is False
    assert output.read_bytes() == first_xml
    assert report_path.read_bytes() == first_report
    assert second["output"]["sha256"] == first["output"]["sha256"]


@pytest.mark.parametrize("mutation", ["missing_lifecycle", "missing_transition", "video_id", "run_id", "historical_operations"])
def test_reel1_parity_contract_fails_closed(tmp_path: Path, mutation: str):
    generic, _ = _safe_generic(tmp_path)
    kwargs = _kwargs(generic, tmp_path / "out.fcpxml", tmp_path / "report.json")
    if mutation == "missing_lifecycle":
        kwargs["caption_lifecycle_path"] = None
    elif mutation == "missing_transition":
        kwargs["transition_authority_path"] = None
    elif mutation == "video_id":
        kwargs["parity_video_id"] = "DcJRJtUKScu"
    elif mutation == "run_id":
        kwargs["transition_run_id"] = "wrong_run"
    else:
        kwargs["generic_path"] = GENERIC
    with pytest.raises(FcpxmlCompilationError):
        compile_fcpxml(**kwargs)
