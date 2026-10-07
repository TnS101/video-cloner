from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping, Sequence

from video_cloner.resolve import fcpxml as canonical
from video_cloner.captions.textplus import StandaloneTextplusError, prepare_textplus_authority


REPORT_SCHEMA = "video_cloner.standalone_fcpxml.v1"
EXPECTED_GENERIC_SCHEMA = "generic_edit_commands"
EXPECTED_FCPXML_VERSION = "1.10"
TRANSITION_AUTHORITY_SCHEMA = "video_cloner.transition_authority.v1"


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


def _source_audio(generic: Mapping[str, object], override: str | Path | None) -> Path:
    source = generic.get("source")
    declared = source.get("source_audio") if isinstance(source, dict) else None
    if not isinstance(declared, str) or not declared.strip():
        raise FcpxmlCompilationError("generic source contract has no source_audio")
    declared_path = Path(declared).expanduser().resolve()
    selected = Path(override).expanduser().resolve() if override is not None else declared_path
    if selected != declared_path:
        raise FcpxmlCompilationError("audio override does not match the generic source_audio authority")
    if not _nonempty(selected):
        raise FcpxmlCompilationError(f"source audio is missing or empty: {selected}")
    return selected


def _read_json(path: str | Path, label: str) -> tuple[Path, dict[str, object]]:
    resolved = Path(path).expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise FcpxmlCompilationError(f"missing or malformed {label}: {resolved}") from error
    if not isinstance(value, dict):
        raise FcpxmlCompilationError(f"{label} must be a JSON object")
    return resolved, value


def _transition_authority(
    path: str | Path | None,
    run_id: str | None,
    generic: Mapping[str, object],
    clips: Sequence[Mapping[str, object]],
) -> tuple[Path | None, list[dict[str, object]], dict[str, object]]:
    if path is None:
        if run_id is not None:
            raise FcpxmlCompilationError("transition run identity was supplied without transition authority")
        return None, [], {"enabled": False, "native_count": 0, "flash_handoff_count": 0, "decision_count": 0}
    if not isinstance(run_id, str) or not run_id.strip():
        raise FcpxmlCompilationError("explicit transition authority requires a transition run identity")

    authority_file = Path(path).expanduser().resolve()
    if not _nonempty(authority_file):
        raise FcpxmlCompilationError(f"missing or empty transition authority: {authority_file}")
    try:
        authority = json.loads(authority_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise FcpxmlCompilationError(f"malformed transition authority JSON: {authority_file}") from error
    if not isinstance(authority, dict) or authority.get("success") is not True:
        raise FcpxmlCompilationError("transition authority is not a successful JSON object")
    if authority.get("schema") != TRANSITION_AUTHORITY_SCHEMA or authority.get("schema_version") != "1.0":
        raise FcpxmlCompilationError("transition authority schema/version mismatch")
    if authority.get("video_id") != generic.get("video_id"):
        raise FcpxmlCompilationError("transition authority video identity mismatch")
    if authority.get("run_id") != run_id:
        raise FcpxmlCompilationError("transition authority run identity mismatch")

    native_rows = authority.get("native_transitions")
    flash_rows = authority.get("flash_handoffs")
    if not isinstance(native_rows, list) or not isinstance(flash_rows, list):
        raise FcpxmlCompilationError("transition authority must contain native_transitions and flash_handoffs lists")
    cut_boundaries = {int(clip["timeline_end_frame"]) for clip in clips[:-1]}
    seen_ids: set[str] = set()
    seen_boundaries: set[int] = set()
    transitions: list[dict[str, object]] = []

    def common(row: object, kind: str) -> tuple[dict[str, object], str, int, int]:
        if not isinstance(row, dict):
            raise FcpxmlCompilationError(f"malformed {kind} transition authority")
        transition_id = row.get("id")
        if not isinstance(transition_id, str) or not transition_id.strip() or transition_id in seen_ids:
            raise FcpxmlCompilationError("transition authority contains a missing or duplicate ID")
        boundary = _integer(row.get("boundary_frame"), f"{transition_id} boundary")
        duration = _integer(row.get("duration_frames"), f"{transition_id} duration")
        if duration <= 0 or row.get("alignment") != "centered_on_cut":
            raise FcpxmlCompilationError(f"{transition_id} has malformed duration/alignment authority")
        if boundary not in cut_boundaries:
            raise FcpxmlCompilationError(f"{transition_id} references a non-existent cut boundary")
        if boundary in seen_boundaries:
            raise FcpxmlCompilationError(f"duplicate transition boundary authority: {boundary}")
        seen_ids.add(transition_id)
        seen_boundaries.add(boundary)
        return row, transition_id, boundary, duration

    native_effects = {"slide_edge_wipe": "slide", "cross_dissolve": "cross_dissolve"}
    for row_value in native_rows:
        row, transition_id, boundary, duration = common(row_value, "native")
        transition_type = row.get("transition_type")
        if not isinstance(transition_type, str) or transition_type not in native_effects:
            raise FcpxmlCompilationError(f"unknown native transition type: {transition_type!r}")
        effect_key = native_effects[str(transition_type)]
        effect = canonical.TRANSITION_EFFECTS[effect_key]
        transitions.append({
            "id": transition_id, "transition_type": transition_type, "backend": "native",
            "effect_profile": {"effect_family": effect_key, "needs_resolve_controller": False},
            "confidence": "accepted", "strength": 1.0, "requested_cut_frame": boundary,
            "boundary_frame": boundary, "boundary_delta_frames": 0,
            "offset_frame": boundary - duration // 2, "duration_frames": duration,
            "outgoing_frames": duration // 2, "incoming_frames": duration - duration // 2,
            "effect_key": effect_key, "effect_name": effect["name"], "effect_uid": effect["uid"],
            "raw_parameters": dict(row),
        })

    for row_value in flash_rows:
        row, transition_id, boundary, duration = common(row_value, "Flash handoff")
        if row.get("transition_type") != "flash_cut" or row.get("handoff_type") != "flash_v4_visual_carrier":
            raise FcpxmlCompilationError(f"malformed Flash handoff authority: {transition_id}")
        params = dict(row)
        effect = canonical.TRANSITION_EFFECTS["cross_dissolve"]
        transitions.append({
            "id": transition_id, "transition_type": "flash_cut", "backend": "vfx_placeholder",
            "effect_profile": canonical.build_transition_effect_profile("flash_cut", params),
            "confidence": "accepted", "strength": 1.0, "requested_cut_frame": boundary,
            "boundary_frame": boundary, "boundary_delta_frames": 0,
            "offset_frame": boundary - duration // 2, "duration_frames": duration,
            "outgoing_frames": duration // 2, "incoming_frames": duration - duration // 2,
            "effect_key": "cross_dissolve", "effect_name": effect["name"], "effect_uid": effect["uid"],
            "raw_parameters": params,
        })

    transitions.sort(key=lambda row: int(row["boundary_frame"]))
    for index, transition in enumerate(transitions, start=1):
        transition["index"] = index
    native = [row for row in transitions if row["backend"] == "native"]
    flash = [row for row in transitions if row["backend"] == "vfx_placeholder"]
    expected_summary = {"native_count": len(native), "flash_handoff_count": len(flash), "decision_count": len(transitions)}
    summary = authority.get("summary")
    if not isinstance(summary, dict) or any(summary.get(key) != value for key, value in expected_summary.items()):
        raise FcpxmlCompilationError("transition authority summary does not match its decisions")
    info: dict[str, object] = {
        "enabled": True, "schema": TRANSITION_AUTHORITY_SCHEMA, "run_id": run_id, **expected_summary,
        "native_boundaries": [row["boundary_frame"] for row in native],
        "flash_handoff_boundaries": [row["boundary_frame"] for row in flash],
        "decision_boundaries": [row["boundary_frame"] for row in transitions],
    }
    return authority_file, transitions, info


def _validate_xml(
    xml_text: str,
    clips: Sequence[Mapping[str, object]],
    source_video: Path,
    fps: float,
    version: str,
    transitions: Sequence[Mapping[str, object]],
    cues: Sequence[Mapping[str, object]],
    source_audio: Path | None,
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
    audio_assets = [element for element in resources.findall("asset") if element.get("hasAudio") == "1"]
    if source_audio is not None and (len(audio_assets) != 1 or audio_assets[0].get("src") != canonical.path_to_file_url(str(source_audio))):
        raise FcpxmlCompilationError("FCPXML source audio reference does not match the expected audio")
    if source_audio is None and audio_assets:
        raise FcpxmlCompilationError("FCPXML unexpectedly contains source audio")
    asset_clips = [element for element in spine.findall("asset-clip") if element.get("ref") == video_assets[0].get("id")]
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
    expected_native = [row for row in transitions if row.get("backend") == "native"]
    expected_flash = [row for row in transitions if row.get("backend") == "vfx_placeholder"]
    native_elements = root.findall(".//transition")
    title_elements = root.findall(".//title")
    flash_elements = [element for element in title_elements if element.find("marker") is not None]
    caption_elements = [element for element in title_elements if element.find("marker") is None]
    if len(native_elements) != len(expected_native) or len(flash_elements) != len(expected_flash):
        raise FcpxmlCompilationError("FCPXML transition/handoff counts do not match transition authority")
    if len(caption_elements) != len(cues):
        raise FcpxmlCompilationError("FCPXML caption count does not match caption authority")
    for element, transition in zip(native_elements, expected_native):
        expected = {
            "name": str(transition["effect_name"]),
            "offset": canonical.frames_to_fcpx_time(int(transition["offset_frame"]), fps),
            "duration": canonical.frames_to_fcpx_time(int(transition["duration_frames"]), fps),
        }
        if any(element.get(key) != value for key, value in expected.items()):
            raise FcpxmlCompilationError("native FCPXML transition does not match transition authority")
    for element, transition in zip(flash_elements, expected_flash):
        marker = element.find("marker")
        try:
            note = json.loads(marker.get("note") if marker is not None else "")
        except (TypeError, json.JSONDecodeError) as error:
            raise FcpxmlCompilationError("malformed Flash handoff marker") from error
        if note.get("transition_id") != transition["id"] or note.get("boundary_frame") != transition["boundary_frame"]:
            raise FcpxmlCompilationError("Flash handoff marker does not match transition authority")
    for element, cue in zip(caption_elements, cues):
        expected = {
            "offset": canonical.frames_to_fcpx_time(int(cue["start_frame"]), fps),
            "duration": canonical.frames_to_fcpx_time(int(cue["duration_frames"]), fps),
            "lane": str(int(cue.get("lane") or 1)),
        }
        if any(element.get(key) != value for key, value in expected.items()):
            raise FcpxmlCompilationError("FCPXML caption timing/lane does not match caption authority")
    forbidden_tags = {
        "transition": 0,
        "title": 0,
        "timeMap": len(root.findall(".//timeMap")),
        "timept": len(root.findall(".//timept")),
        "adjust-transform": len(root.findall(".//asset-clip/adjust-transform")),
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
        "audio_asset_count": len(audio_assets),
        "clip_count": len(asset_clips),
        "caption_count": len(caption_elements),
        "native_transition_count": len(native_elements),
        "flash_handoff_count": len(flash_elements),
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
    transition_authority_path: str | Path | None = None,
    transition_run_id: str | None = None,
    caption_style_path: str | Path | None = None,
    caption_lifecycle_path: str | Path | None = None,
    audio_path: str | Path | None = None,
    parity_video_id: str | None = None,
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
    transition_file, transitions, transition_info = _transition_authority(
        transition_authority_path, transition_run_id, generic, clips
    )
    caption_style_file: Path | None = None
    lifecycle_file: Path | None = None
    caption_info: dict[str, object] = {"enabled": False}
    cues: list[dict[str, object]] = []
    style: dict[str, object] = {}
    cue_styles: dict[int, dict[str, object]] | None = None
    source_audio: Path | None = None
    if parity_video_id is not None:
        if parity_video_id != generic.get("video_id"):
            raise FcpxmlCompilationError("parity video identity mismatch")
        if caption_style_path is None or caption_lifecycle_path is None:
            raise FcpxmlCompilationError("parity mode requires caption style and lifecycle authority")
        if transition_authority_path is None or transition_run_id is None:
            raise FcpxmlCompilationError("parity mode requires transition authority and run identity")
    if (caption_style_path is None) != (caption_lifecycle_path is None):
        raise FcpxmlCompilationError("caption style and lifecycle authority must be supplied together")
    if audio_path is not None:
        source_audio = _source_audio(generic, audio_path)
    if caption_style_path is not None and caption_lifecycle_path is not None:
        caption_style_file, style_data = _read_json(caption_style_path, "caption style")
        lifecycle_file, lifecycle = _read_json(caption_lifecycle_path, "caption lifecycle authority")
        try:
            prepared = prepare_textplus_authority(generic, style_data, lifecycle)
        except StandaloneTextplusError as error:
            raise FcpxmlCompilationError(str(error)) from error
        cues = prepared["cues"]
        style = prepared["style"]
        cue_styles = prepared["cue_styles"]
        caption_info = {
            "enabled": True,
            "source": prepared["caption_source"],
            "semantic": prepared["caption_authority"],
            "lifecycle": prepared["caption_lifecycle"],
            "metrics": prepared["caption_metrics"],
            "style_event_matches": prepared["style_event_matches"],
        }

    video_id = str(generic["video_id"])
    default_dir = generic_file.parent.parent / "davinci"
    output = Path(output_fcpxml).expanduser().resolve() if output_fcpxml is not None else (default_dir / f"{video_id}_standalone_timeline.fcpxml").resolve()
    report_file = Path(report_path).expanduser().resolve() if report_path is not None else (default_dir / f"{video_id}_standalone_fcpxml_report.json").resolve()
    if output.suffix.lower() != ".fcpxml":
        raise FcpxmlCompilationError("output path must use the .fcpxml extension")
    name = timeline_name or f"{video_id}_standalone_timeline"
    xml_text = canonical.build_full_timeline_fcpxml(
        cues=cues,
        video_clips=clips,
        style=style,
        cue_styles=cue_styles,
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
        audio_path=str(source_audio or ""),
        include_audio=source_audio is not None,
        transitions=transitions,
        transition_mode="hybrid" if transitions else "none",
        vfx_placeholder_lane=max([int(cue.get("lane") or 1) for cue in cues] or [1]) + 1,
        vfx_placeholder_visible=False,
    )
    structure = _validate_xml(xml_text, clips, source_video, fps, EXPECTED_FCPXML_VERSION, transitions, cues, source_audio)
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
            "transition_authority": str(transition_file) if transition_file else None,
            "transition_authority_sha256": _sha256(transition_file) if transition_file else None,
            "transition_run_id": transition_run_id,
            "caption_style": str(caption_style_file) if caption_style_file else None,
            "caption_style_sha256": _sha256(caption_style_file) if caption_style_file else None,
            "caption_lifecycle": str(lifecycle_file) if lifecycle_file else None,
            "caption_lifecycle_sha256": _sha256(lifecycle_file) if lifecycle_file else None,
            "source_audio": str(source_audio) if source_audio else None,
            "source_audio_sha256": _sha256(source_audio) if source_audio else None,
            "parity_video_id": parity_video_id,
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
            "transitions": sum(row["backend"] == "native" for row in transitions),
            "slide_edge_wipe": sum(row.get("transition_type") == "slide_edge_wipe" for row in transitions),
            "cross_dissolve": sum(row.get("transition_type") == "cross_dissolve" for row in transitions),
            "flash_handoffs": sum(row["backend"] == "vfx_placeholder" for row in transitions),
            "captions": len(cues),
        },
        "transition_authority": transition_info,
        "caption_authority": caption_info,
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
    parser.add_argument("--transition-authority")
    parser.add_argument("--transition-run-id")
    parser.add_argument("--caption-style")
    parser.add_argument("--caption-lifecycle")
    parser.add_argument("--audio")
    parser.add_argument("--parity-video-id")
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
            transition_authority_path=args.transition_authority,
            transition_run_id=args.transition_run_id,
            caption_style_path=args.caption_style,
            caption_lifecycle_path=args.caption_lifecycle,
            audio_path=args.audio,
            parity_video_id=args.parity_video_id,
        )
    except FcpxmlCompilationError as error:
        print(json.dumps({"success": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
