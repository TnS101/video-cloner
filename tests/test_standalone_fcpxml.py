from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from video_cloner.resolve import fcpxml as canonical
from video_cloner.captions.fcpxml import FcpxmlCompilationError, compile_fcpxml, main


ROOT = Path(__file__).parents[1]
REEL1_ID = "DZsqH7auhjt"
REEL1_GENERIC = ROOT / "data" / REEL1_ID / "planning" / f"{REEL1_ID}_generic_edit_commands.json"
REEL1_TRANSITIONS = ROOT / "data" / REEL1_ID / "analysis" / f"{REEL1_ID}_transition_authority_accepted_reel1_v1.json"
REEL1_TRANSITION_RUN_ID = "DZsqH7auhjt_accepted_reel1_transition_authority_v1"


def _command(index: int, start: int, end: int) -> dict:
    duration = end - start
    return {
        "command_id": f"cmd_{index:03d}",
        "shot_id": index,
        "source_start": start / 24,
        "source_end": end / 24,
        "source_duration": duration / 24,
        "source_start_frame": start,
        "source_end_frame": end,
        "source_duration_frames": duration,
        "timeline_start": start / 24,
        "timeline_end": end / 24,
        "timeline_duration": duration / 24,
        "timeline_start_frame": start,
        "timeline_end_frame": end,
        "timeline_duration_frames": duration,
        "action": {"type": "cut"},
        "observations": {
            "speed_ramp_candidate": {"candidate": True, "actionable": False},
            "zoom_candidate": {"candidate": True, "actionable": False},
        },
        "operations": [{"operation": "cut", "parameters": {"cut_policy": "use_compiled_timeline_range"}}],
    }


def _fixture(tmp_path: Path, count: int = 3) -> tuple[Path, Path, Path, Path]:
    video = tmp_path / "source proxy.mp4"
    video.write_bytes(b"video")
    boundaries = [0]
    for index in range(count):
        boundaries.append(boundaries[-1] + index + 5)
    commands = [_command(index, boundaries[index - 1], boundaries[index]) for index in range(1, count + 1)]
    commands[0]["operations"].append({"operation": "transition_hint", "parameters": {"transition_type": "flash_cut"}})
    generic = {
        "success": True,
        "schema": "generic_edit_commands",
        "schema_version": "2.0",
        "video_id": "fixture_video",
        "source": {"source_video": str(video), "fps": 24.0, "frame_count": boundaries[-1]},
        "timeline": commands,
        "summary": {"commands_count": count, "operation_counts": {"cut": count, "transition_hint": 1}},
    }
    generic_path = tmp_path / "planning" / "fixture_video_generic_edit_commands.json"
    generic_path.parent.mkdir()
    generic_path.write_text(json.dumps(generic), encoding="utf-8")
    output = tmp_path / "davinci" / "fixture.fcpxml"
    report = tmp_path / "davinci" / "fixture_report.json"
    return generic_path, video, output, report


def _reel1_safe_generic(tmp_path: Path) -> Path:
    generic = json.loads(REEL1_GENERIC.read_text(encoding="utf-8-sig"))
    for command in generic["timeline"]:
        command["action"] = {"type": "cut"}
        command["observations"] = {}
        command["operations"] = [{"operation": "cut", "parameters": {"cut_policy": "use_compiled_timeline_range"}}]
    generic["summary"]["operation_counts"] = {"cut": len(generic["timeline"])}
    path = tmp_path / "DZsqH7auhjt_safe_generic_edit_commands.json"
    path.write_text(json.dumps(generic), encoding="utf-8")
    return path


def test_generic_commands_compile_to_cut_only_fcpxml(tmp_path: Path):
    generic, video, output, report_path = _fixture(tmp_path)
    report = compile_fcpxml(generic, output, report_path)
    root = ET.parse(output).getroot()
    clips = root.findall("./library/event/project/sequence/spine/asset-clip")
    assert root.tag == "fcpxml"
    assert root.attrib["version"] == "1.10"
    assert len(clips) == 3
    assert report["structure"]["clip_count"] == 3
    assert report["generic_operation_counts"]["transition_hint_observations"] == 1
    assert all(value == 0 for value in report["compiled_operation_counts"].values())
    assert report["resolve_invoked"] is False
    assert report["timeline_mutated"] is False
    assert report["save_project_invoked"] is False
    assert report_path.is_file()
    asset = root.find("./resources/asset[@hasVideo='1']")
    assert asset is not None
    assert asset.attrib["src"] == canonical.path_to_file_url(str(video.resolve()))


def test_cut_only_audio_is_emitted_without_caption_titles(tmp_path: Path):
    generic, video, output, report_path = _fixture(tmp_path)
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"audio")
    data = json.loads(generic.read_text(encoding="utf-8"))
    data["source"]["source_audio"] = str(audio)
    generic.write_text(json.dumps(data), encoding="utf-8")

    report = compile_fcpxml(generic, output, report_path, audio_path=audio)
    root = ET.parse(output).getroot()
    assert report["structure"]["clip_count"] == 3
    assert report["structure"]["audio_asset_count"] == 1
    assert report["structure"]["caption_count"] == 0
    assert root.findall(".//title") == []
    assert len(root.findall(".//asset-clip")) == 4


def test_clip_timing_and_order_match_generic_frames(tmp_path: Path):
    generic, _, output, report = _fixture(tmp_path)
    compile_fcpxml(generic, output, report)
    clips = ET.parse(output).getroot().findall("./library/event/project/sequence/spine/asset-clip")
    assert [(clip.attrib["offset"], clip.attrib["start"], clip.attrib["duration"]) for clip in clips] == [
        ("0/24s", "0/24s", "5/24s"),
        ("5/24s", "5/24s", "6/24s"),
        ("11/24s", "11/24s", "7/24s"),
    ]


def test_identical_compilation_is_byte_deterministic(tmp_path: Path):
    generic, _, output, report = _fixture(tmp_path)
    first = compile_fcpxml(generic, output, report)
    first_bytes = output.read_bytes()
    second = compile_fcpxml(generic, output, report)
    assert output.read_bytes() == first_bytes
    assert second["output"]["sha256"] == first["output"]["sha256"]


def test_default_outputs_use_davinci_run_directory(tmp_path: Path):
    generic, _, _, _ = _fixture(tmp_path)
    report = compile_fcpxml(generic)
    assert Path(report["output"]["fcpxml"]) == tmp_path / "davinci" / "fixture_video_standalone_timeline.fcpxml"
    assert Path(report["report_path"]) == tmp_path / "davinci" / "fixture_video_standalone_fcpxml_report.json"


@pytest.mark.parametrize("payload", [b"", b"[]", b"{broken"])
def test_missing_empty_or_malformed_generic_is_rejected(tmp_path: Path, payload: bytes):
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    with pytest.raises(FcpxmlCompilationError):
        compile_fcpxml(path)


@pytest.mark.parametrize(
    ("operation", "parameters"),
    [
        ("speed_ramp", {}),
        ("transform_zoom", {}),
        ("blur", {}),
        ("transition_hint", {"transition_type": "whip_pan"}),
        ("transition_hint", {"transition_type": "slide_transition"}),
        ("transition_hint", {"transition_type": "blur_transition"}),
    ],
)
def test_forbidden_executable_operations_are_rejected(tmp_path: Path, operation: str, parameters: dict):
    generic_path, _, _, _ = _fixture(tmp_path)
    data = json.loads(generic_path.read_text(encoding="utf-8"))
    data["timeline"][0]["operations"] = [{"operation": operation, "parameters": parameters}]
    generic_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FcpxmlCompilationError):
        compile_fcpxml(generic_path)


@pytest.mark.parametrize("candidate", ["speed_ramp_candidate", "zoom_candidate"])
def test_actionable_motion_candidate_is_rejected(tmp_path: Path, candidate: str):
    generic_path, _, _, _ = _fixture(tmp_path)
    data = json.loads(generic_path.read_text(encoding="utf-8"))
    data["timeline"][0]["observations"][candidate]["actionable"] = True
    generic_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FcpxmlCompilationError):
        compile_fcpxml(generic_path)


def test_missing_source_media_is_rejected(tmp_path: Path):
    generic_path, video, _, _ = _fixture(tmp_path)
    video.unlink()
    with pytest.raises(FcpxmlCompilationError, match="source video"):
        compile_fcpxml(generic_path)


def test_mismatched_video_override_is_rejected(tmp_path: Path):
    generic_path, _, _, _ = _fixture(tmp_path)
    other = tmp_path / "other.mp4"
    other.write_bytes(b"other")
    with pytest.raises(FcpxmlCompilationError, match="does not match"):
        compile_fcpxml(generic_path, video_path=other)


@pytest.mark.parametrize("field", ["timeline_start_frame", "timeline_end_frame", "source_end_frame", "timeline_duration_frames"])
def test_inconsistent_frame_mapping_is_rejected(tmp_path: Path, field: str):
    generic_path, _, _, _ = _fixture(tmp_path)
    data = json.loads(generic_path.read_text(encoding="utf-8"))
    data["timeline"][1][field] += 1
    generic_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FcpxmlCompilationError):
        compile_fcpxml(generic_path)


def test_fcpxml_contains_no_titles_transitions_retime_transform_or_filters(tmp_path: Path):
    generic, _, output, report = _fixture(tmp_path)
    result = compile_fcpxml(generic, output, report)
    counts = result["structure"]["forbidden_xml_construct_counts"]
    assert counts == {"transition": 0, "title": 0, "timeMap": 0, "timept": 0, "adjust-transform": 0, "filter-video": 0}
    assert b"DaVinciResolveScript" not in output.read_bytes()


def test_cli_compiles_without_resolve(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    generic, _, output, report = _fixture(tmp_path)
    assert main(["--generic", str(generic), "--output-fcpxml", str(output), "--report", str(report)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["resolve_invoked"] is False


def test_accepted_reel_shape_preserves_twenty_two_cuts(tmp_path: Path):
    generic, _, output, report = _fixture(tmp_path, count=22)
    result = compile_fcpxml(generic, output, report)
    assert result["structure"]["clip_count"] == 22
    assert len(ET.parse(output).getroot().findall("./library/event/project/sequence/spine/asset-clip")) == 22


def test_reel1_real_transition_authority_is_exact_and_deterministic(tmp_path: Path):
    generic = _reel1_safe_generic(tmp_path)
    output = tmp_path / "reel1.fcpxml"
    report_path = tmp_path / "reel1_report.json"
    first = compile_fcpxml(
        generic, output, report_path,
        transition_authority_path=REEL1_TRANSITIONS,
        transition_run_id=REEL1_TRANSITION_RUN_ID,
    )
    first_bytes = output.read_bytes()
    second = compile_fcpxml(
        generic, output, report_path,
        transition_authority_path=REEL1_TRANSITIONS,
        transition_run_id=REEL1_TRANSITION_RUN_ID,
    )
    root = ET.parse(output).getroot()
    native = root.findall(".//transition")
    handoffs = root.findall(".//title")
    flash_boundaries = [json.loads(title.find("marker").get("note"))["boundary_frame"] for title in handoffs]

    assert first["structure"]["clip_count"] == 22
    assert first["compiled_operation_counts"] == {
        "speed": 0, "animated_zoom": 0, "whip": 0, "slide": 0, "blur": 0,
        "transitions": 6, "slide_edge_wipe": 3, "cross_dissolve": 3,
        "flash_handoffs": 5, "captions": 0,
    }
    assert first["transition_authority"] == {
        "enabled": True,
        "schema": "video_cloner.transition_authority.v1",
        "run_id": REEL1_TRANSITION_RUN_ID,
        "native_count": 6,
        "flash_handoff_count": 5,
        "decision_count": 11,
        "native_boundaries": [492, 526, 556, 587, 618, 833],
        "flash_handoff_boundaries": [96, 377, 426, 454, 758],
        "decision_boundaries": [96, 377, 426, 454, 492, 526, 556, 587, 618, 758, 833],
    }
    assert [item.get("name") for item in native] == ["Slide", "Cross Dissolve", "Cross Dissolve", "Slide", "Slide", "Cross Dissolve"]
    assert [item.get("offset") for item in native] == [f"{frame}/24s" for frame in [488, 522, 552, 583, 614, 829]]
    assert flash_boundaries == [96, 377, 426, 454, 758]
    assert output.read_bytes() == first_bytes
    assert second["output"]["sha256"] == first["output"]["sha256"]


@pytest.mark.parametrize("mutation", ["duplicate_boundary", "unknown_type", "bad_boundary", "video_id", "run_id", "malformed_flash"])
def test_transition_authority_fails_closed(tmp_path: Path, mutation: str):
    generic = _reel1_safe_generic(tmp_path)
    authority = json.loads(REEL1_TRANSITIONS.read_text(encoding="utf-8"))
    supplied_run_id = REEL1_TRANSITION_RUN_ID
    if mutation == "duplicate_boundary":
        authority["flash_handoffs"][0]["boundary_frame"] = 492
    elif mutation == "unknown_type":
        authority["native_transitions"][0]["transition_type"] = "spin"
    elif mutation == "bad_boundary":
        authority["native_transitions"][0]["boundary_frame"] = 491
    elif mutation == "video_id":
        authority["video_id"] = "DcJRJtUKScu"
    elif mutation == "run_id":
        supplied_run_id = "wrong_run"
    else:
        authority["flash_handoffs"][0].pop("handoff_type")
    authority_path = tmp_path / "transition_authority.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    with pytest.raises(FcpxmlCompilationError):
        compile_fcpxml(
            generic, tmp_path / "out.fcpxml", tmp_path / "report.json",
            transition_authority_path=authority_path,
            transition_run_id=supplied_run_id,
        )


def test_transition_authority_is_optional_and_requires_explicit_run_identity(tmp_path: Path):
    generic = _reel1_safe_generic(tmp_path)
    report = compile_fcpxml(generic, tmp_path / "none.fcpxml", tmp_path / "none.json")
    assert report["transition_authority"] == {"enabled": False, "native_count": 0, "flash_handoff_count": 0, "decision_count": 0}
    with pytest.raises(FcpxmlCompilationError, match="run identity"):
        compile_fcpxml(generic, transition_authority_path=REEL1_TRANSITIONS)


def test_historical_reel1_speed_zoom_authority_remains_rejected():
    with pytest.raises(FcpxmlCompilationError):
        compile_fcpxml(REEL1_GENERIC)
