from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping, Sequence

from scripts.davinci import compile_davinci_textplus_fcpxml as canonical


REPORT_SCHEMA = "video_cloner.standalone_fcpxml.v1"
EXPECTED_GENERIC_SCHEMA = "generic_edit_commands"
EXPECTED_FCPXML_VERSION = "1.10"


class FcpxmlCompilationError(RuntimeError):
    pass


def _nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_generic(path: Path) -> dict[str, object]:
    if not _nonempty(path):
        raise FcpxmlCompilationError(f"missing or empty generic command artifact: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise FcpxmlCompilationError(f"malformed generic command JSON: {path}") from error
    if not isinstance(value, dict):
        raise FcpxmlCompilationError("generic command artifact must be a JSON object")
    if value.get("success") is not True or value.get("schema") != EXPECTED_GENERIC_SCHEMA:
        raise FcpxmlCompilationError("generic command artifact is not a successful canonical generic_edit_commands document")
    if value.get("schema_version") != "2.0":
        raise FcpxmlCompilationError(f"unsupported generic command schema version: {value.get('schema_version')!r}")
    if not isinstance(value.get("video_id"), str) or not str(value["video_id"]).strip():
        raise FcpxmlCompilationError("generic command artifact has no video_id")
    if not isinstance(value.get("timeline"), list) or not value["timeline"]:
        raise FcpxmlCompilationError("generic command artifact has no timeline commands")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FcpxmlCompilationError(f"{label} must be an integer frame number")
    return value


def _operation_authority(generic: Mapping[str, object]) -> dict[str, int]:
    counts = {
        "cut": 0,
        "transition_hint_observations": 0,
        "speed": 0,
        "animated_zoom": 0,
        "whip": 0,
        "slide": 0,
        "blur": 0,
        "other": 0,
    }
    timeline = generic.get("timeline")
    assert isinstance(timeline, list)
    expected_start = 0
    for index, command in enumerate(timeline, start=1):
        if not isinstance(command, dict):
            raise FcpxmlCompilationError(f"timeline command {index} is malformed")
        action = command.get("action")
        if not isinstance(action, dict) or action.get("type") != "cut":
            raise FcpxmlCompilationError(f"timeline command {index} is not a cut-only action")
        timeline_start = _integer(command.get("timeline_start_frame"), f"timeline command {index} start")
        timeline_end = _integer(command.get("timeline_end_frame"), f"timeline command {index} end")
        timeline_duration = _integer(command.get("timeline_duration_frames"), f"timeline command {index} duration")
        source_start = _integer(command.get("source_start_frame"), f"timeline command {index} source start")
        source_end = _integer(command.get("source_end_frame"), f"timeline command {index} source end")
        source_duration = _integer(command.get("source_duration_frames"), f"timeline command {index} source duration")
        if timeline_start != expected_start or timeline_end <= timeline_start:
            raise FcpxmlCompilationError(f"timeline command {index} is not positive and contiguous")
        if timeline_end - timeline_start != timeline_duration:
            raise FcpxmlCompilationError(f"timeline command {index} timeline duration is inconsistent")
        if source_end <= source_start or source_end - source_start != source_duration:
            raise FcpxmlCompilationError(f"timeline command {index} source duration is inconsistent")
        if timeline_duration != source_duration:
            raise FcpxmlCompilationError(f"timeline command {index} would require retiming")
        expected_start = timeline_end

        observations = command.get("observations") or {}
        if not isinstance(observations, dict):
            raise FcpxmlCompilationError(f"timeline command {index} observations are malformed")
        for candidate_name in ("speed_ramp_candidate", "zoom_candidate"):
            candidate = observations.get(candidate_name)
            if candidate is not None and (not isinstance(candidate, dict) or candidate.get("actionable") is not False):
                raise FcpxmlCompilationError(f"timeline command {index} has executable {candidate_name} authority")

        operations = command.get("operations")
        if not isinstance(operations, list) or not operations:
            raise FcpxmlCompilationError(f"timeline command {index} has no operations")
        command_cut_count = 0
        for operation in operations:
            if not isinstance(operation, dict):
                raise FcpxmlCompilationError(f"timeline command {index} contains a malformed operation")
            name = str(operation.get("operation") or "").strip().lower()
            parameters = operation.get("parameters") or {}
            if not isinstance(parameters, dict):
                raise FcpxmlCompilationError(f"timeline command {index} operation parameters are malformed")
            if name == "cut":
                counts["cut"] += 1
                command_cut_count += 1
                continue
            if name == "transition_hint":
                transition_type = str(parameters.get("transition_type") or "").strip().lower()
                if transition_type != "flash_cut":
                    if "whip" in transition_type:
                        counts["whip"] += 1
                    elif "slide" in transition_type:
                        counts["slide"] += 1
                    elif "blur" in transition_type:
                        counts["blur"] += 1
                    else:
                        counts["other"] += 1
                    raise FcpxmlCompilationError(f"forbidden executable transition authority: {transition_type or 'unknown'}")
                counts["transition_hint_observations"] += 1
                continue
            if "speed" in name or "retime" in name:
                counts["speed"] += 1
            elif "zoom" in name or "transform" in name:
                counts["animated_zoom"] += 1
            elif "whip" in name:
                counts["whip"] += 1
            elif "slide" in name:
                counts["slide"] += 1
            elif "blur" in name:
                counts["blur"] += 1
            else:
                counts["other"] += 1
            raise FcpxmlCompilationError(f"unsupported executable generic operation: {name or 'unknown'}")
        if command_cut_count != 1:
            raise FcpxmlCompilationError(f"timeline command {index} must contain exactly one cut operation")
    if counts["cut"] != len(timeline):
        raise FcpxmlCompilationError("each timeline command must contain exactly one cut operation")
    summary = generic.get("summary")
    if not isinstance(summary, dict) or summary.get("commands_count") != len(timeline):
        raise FcpxmlCompilationError("generic summary command count does not match timeline")
    return counts


def _source_media(generic: Mapping[str, object], override: str | Path | None) -> Path:
    source = generic.get("source")
    if not isinstance(source, dict):
        raise FcpxmlCompilationError("generic command artifact has no source contract")
    declared = source.get("source_video")
    if not isinstance(declared, str) or not declared.strip():
        raise FcpxmlCompilationError("generic source contract has no source_video")
    declared_path = Path(declared).expanduser().resolve()
    selected = Path(override).expanduser().resolve() if override is not None else declared_path
    if selected != declared_path:
        raise FcpxmlCompilationError("video override does not match the generic source_video authority")
    if not _nonempty(selected):
        raise FcpxmlCompilationError(f"source video is missing or empty: {selected}")
    return selected


def _validate_xml(
    xml_text: str,
    clips: Sequence[Mapping[str, object]],
    source_video: Path,
    fps: float,
    version: str,
) -> dict[str, object]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise FcpxmlCompilationError("canonical compiler produced malformed FCPXML") from error
    if root.tag != "fcpxml" or root.get("version") != version:
        raise FcpxmlCompilationError("canonical compiler produced an unexpected FCPXML root/version")
    resources = root.find("resources")
    sequence = root.find("./library/event/project/sequence")
    spine = root.find("./library/event/project/sequence/spine")
    if resources is None or sequence is None or spine is None:
        raise FcpxmlCompilationError("FCPXML is missing resources, sequence, or spine")
    video_assets = [element for element in resources.findall("asset") if element.get("hasVideo") == "1"]
    if len(video_assets) != 1 or video_assets[0].get("src") != canonical.path_to_file_url(str(source_video)):
        raise FcpxmlCompilationError("FCPXML source media reference does not match the expected video")
    asset_clips = spine.findall("asset-clip")
    if len(asset_clips) != len(clips):
        raise FcpxmlCompilationError("FCPXML clip count does not match generic timeline")
    for index, (element, clip) in enumerate(zip(asset_clips, clips), start=1):
        expected = {
            "offset": canonical.frames_to_fcpx_time(int(clip["timeline_start_frame"]), fps),
            "start": canonical.frames_to_fcpx_time(int(clip["source_start_frame"]), fps),
            "duration": canonical.frames_to_fcpx_time(int(clip["timeline_duration_frames"]), fps),
        }
        if any(element.get(key) != value for key, value in expected.items()):
            raise FcpxmlCompilationError(f"FCPXML clip {index} timing does not match generic authority")
    forbidden_tags = {
        "transition": len(root.findall(".//transition")),
        "title": len(root.findall(".//title")),
        "timeMap": len(root.findall(".//timeMap")),
        "timept": len(root.findall(".//timept")),
        "adjust-transform": len(root.findall(".//adjust-transform")),
        "filter-video": len(root.findall(".//filter-video")),
    }
    if any(forbidden_tags.values()):
        raise FcpxmlCompilationError(f"FCPXML contains forbidden executable constructs: {forbidden_tags}")
    duration_frames = int(clips[-1]["timeline_end_frame"])
    if sequence.get("duration") != canonical.frames_to_fcpx_time(duration_frames, fps):
        raise FcpxmlCompilationError("FCPXML sequence duration does not match the generic timeline")
    return {
        "resource_count": len(list(resources)),
        "video_asset_count": len(video_assets),
        "clip_count": len(asset_clips),
        "timeline_duration_frames": duration_frames,
        "forbidden_xml_construct_counts": forbidden_tags,
    }


def compile_fcpxml(
    generic_path: str | Path,
    output_fcpxml: str | Path | None = None,
    report_path: str | Path | None = None,
    video_path: str | Path | None = None,
    timeline_name: str | None = None,
    width: int = 1080,
    height: int = 1920,
) -> dict[str, object]:
    generic_file = Path(generic_path).expanduser().resolve()
    generic = _read_generic(generic_file)
    operation_counts = _operation_authority(generic)
    source_video = _source_media(generic, video_path)
    fps = float(canonical.extract_fps(generic, fallback=24.0))
    if fps <= 0 or fps > 120 or abs(fps - round(fps)) > 1e-9:
        raise FcpxmlCompilationError(f"unsupported non-integral or invalid FCPXML timebase: {fps}")
    clips, clip_info = canonical.extract_video_clips(generic, fps=fps, total_duration_hint=0.0)
    if clip_info.get("fallback_continuous_clip") or len(clips) != len(generic["timeline"]):
        raise FcpxmlCompilationError("canonical compiler did not recover the exact generic cut list")
    for index, (clip, command) in enumerate(zip(clips, generic["timeline"]), start=1):
        assert isinstance(command, dict)
        for field in ("timeline_start_frame", "timeline_end_frame", "timeline_duration_frames", "source_start_frame"):
            if clip.get(field) != command.get(field):
                raise FcpxmlCompilationError(f"canonical compiler changed timeline command {index} field {field}")
        if clip.get("source_duration_frames") != command.get("source_duration_frames"):
            raise FcpxmlCompilationError(f"canonical compiler changed timeline command {index} source duration")
    if width <= 0 or height <= 0:
        raise FcpxmlCompilationError("FCPXML dimensions must be positive")

    video_id = str(generic["video_id"])
    default_dir = generic_file.parent.parent / "davinci"
    output = Path(output_fcpxml).expanduser().resolve() if output_fcpxml is not None else (default_dir / f"{video_id}_standalone_timeline.fcpxml").resolve()
    report_file = Path(report_path).expanduser().resolve() if report_path is not None else (default_dir / f"{video_id}_standalone_fcpxml_report.json").resolve()
    if output.suffix.lower() != ".fcpxml":
        raise FcpxmlCompilationError("output path must use the .fcpxml extension")
    name = timeline_name or f"{video_id}_standalone_timeline"
    xml_text = canonical.build_full_timeline_fcpxml(
        cues=[],
        video_clips=clips,
        style={},
        cue_styles=None,
        fps=fps,
        width=width,
        height=height,
        timeline_name=name,
        title_prefix="VC Caption",
        fcpxml_version=EXPECTED_FCPXML_VERSION,
        effect_uid=canonical.DEFAULT_BASIC_TITLE_UID,
        title_lane=1,
        position_mode="reset",
        position_x=0.0,
        position_y=0.0,
        video_path=str(source_video),
        audio_path="",
        include_audio=False,
        transitions=[],
        transition_mode="none",
    )
    structure = _validate_xml(xml_text, clips, source_video, fps, EXPECTED_FCPXML_VERSION)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(xml_text, encoding="utf-8")
    temporary.replace(output)
    output_sha = _sha256(output)
    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "success": True,
        "video_id": video_id,
        "inputs": {
            "generic": str(generic_file),
            "generic_bytes": generic_file.stat().st_size,
            "generic_sha256": _sha256(generic_file),
            "source_video": str(source_video),
            "source_video_bytes": source_video.stat().st_size,
            "source_video_sha256": _sha256(source_video),
            "canonical_compiler": str(Path(canonical.__file__).resolve()),
            "canonical_compiler_sha256": _sha256(Path(canonical.__file__).resolve()),
        },
        "output": {
            "fcpxml": str(output),
            "bytes": output.stat().st_size,
            "sha256": output_sha,
            "version": EXPECTED_FCPXML_VERSION,
            "timeline_name": name,
            "fps": fps,
            "width": width,
            "height": height,
        },
        "structure": structure,
        "generic_operation_counts": operation_counts,
        "compiled_operation_counts": {
            "speed": 0,
            "animated_zoom": 0,
            "whip": 0,
            "slide": 0,
            "blur": 0,
            "transitions": 0,
            "captions": 0,
        },
        "phase2_analyzers_invoked": False,
        "phase3_regenerated": False,
        "resolve_invoked": False,
        "timeline_mutated": False,
        "save_project_invoked": False,
        "report_path": str(report_file),
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_temp = report_file.with_suffix(report_file.suffix + ".tmp")
    report_temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_temp.replace(report_file)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile validated Video Cloner generic commands into cut-only standalone FCPXML without Resolve.")
    parser.add_argument("--generic", required=True)
    parser.add_argument("--video")
    parser.add_argument("--output-fcpxml")
    parser.add_argument("--report")
    parser.add_argument("--timeline-name")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = compile_fcpxml(
            generic_path=args.generic,
            output_fcpxml=args.output_fcpxml,
            report_path=args.report,
            video_path=args.video,
            timeline_name=args.timeline_name,
            width=args.width,
            height=args.height,
        )
    except FcpxmlCompilationError as error:
        print(json.dumps({"success": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
