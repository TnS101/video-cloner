from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.davinci import compile_davinci_textplus_fcpxml as canonical
from scripts.standalone.video_cloner_fcpxml import FcpxmlCompilationError, compile_fcpxml, main


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
