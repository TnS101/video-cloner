"""Apply one accepted Phase 5 ``textplus_full`` artifact through the Resolve bridge."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import zlib
import xml.etree.ElementTree as ET
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse


TASK_ID = "VIDEO_CLONER_PHASE6_TEXTPLUS_APPLICATION_V1"
MODE = "phase6_import_textplus_full_fcpxml"
MANIFEST_SCHEMA = "video_cloner.standalone_phase5_manifest.v1"
COMBINED_MANIFEST_SCHEMA = "video_cloner.offline_timeline_v1_manifest.v1"
COMBINED_ARTIFACT_CONTRACT = "accepted_combined_offline_timeline_v1_no_resolve"
NODE = "textplus_full"
NODE_CONTRACT = "standalone_textplus_full_timeline_v1"


class TargetMismatch(ValueError):
    def __init__(self, code: str, **details: Any):
        self.code = code
        self.details = details
        super().__init__(f"{code}: {json.dumps(details, ensure_ascii=False, sort_keys=True)}")


def _safe(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception:
        return default


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_json") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}_object")
    return value


def _repository_path(root: Path, value: object, label: str) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}_outside_repository") from exc
    return path


def _identity_file(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}_identity")
    path = _repository_path(root, value.get("path"), label)
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label}_missing")
    if value.get("bytes") != path.stat().st_size or value.get("sha256") != _sha256(path):
        raise ValueError(f"{label}_hash")
    return path


def _file_url_path(value: object) -> Path:
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "file":
        raise ValueError("fcpxml_media_scheme")
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return Path(path).resolve()


def _frames(value: object, fps: int, label: str) -> int:
    token = str(value or "").strip()
    if token.endswith("s"):
        token = token[:-1]
    try:
        frames = Fraction(token) * fps
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{label}_time") from exc
    if frames.denominator != 1:
        raise ValueError(f"{label}_subframe")
    return int(frames)


def _same_path(left: object, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left or ""))) == os.path.normcase(os.path.normpath(str(right)))


def parse_textplus_fcpxml(path: Path, proxy: Path, audio: Path | None) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("fcpxml_parse") from exc
    if root.tag != "fcpxml" or root.get("version") != "1.10":
        raise ValueError("fcpxml_version")
    project = root.find("./library/event/project")
    sequence = root.find("./library/event/project/sequence")
    spine = root.find("./library/event/project/sequence/spine")
    fmt = root.find("./resources/format")
    if project is None or sequence is None or spine is None or fmt is None:
        raise ValueError("fcpxml_structure")
    duration = str(fmt.get("frameDuration") or "")
    try:
        rate = Fraction(duration[:-1] if duration.endswith("s") else duration)
        fps_fraction = 1 / rate
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("fcpxml_timebase") from exc
    if fps_fraction.denominator != 1 or not 1 <= fps_fraction <= 120:
        raise ValueError("fcpxml_timebase")
    fps = int(fps_fraction)

    video_assets = [row for row in root.findall("./resources/asset") if row.get("hasVideo") == "1"]
    audio_assets = [row for row in root.findall("./resources/asset") if row.get("hasAudio") == "1"]
    if len(video_assets) != 1 or not _same_path(_file_url_path(video_assets[0].get("src")), proxy):
        raise ValueError("fcpxml_proxy")
    if audio is None:
        if audio_assets:
            raise ValueError("fcpxml_undeclared_audio")
    elif len(audio_assets) != 1 or not _same_path(_file_url_path(audio_assets[0].get("src")), audio):
        raise ValueError("fcpxml_audio")

    video_id = str(video_assets[0].get("id") or "")
    audio_id = str(audio_assets[0].get("id") or "") if audio_assets else ""
    cuts: list[dict[str, Any]] = []
    audio_rows: list[dict[str, Any]] = []
    titles: list[dict[str, Any]] = []
    flash_handoffs: list[dict[str, Any]] = []
    for index, element in enumerate(list(spine), start=1):
        if element.tag == "asset-clip" and element.get("ref") == video_id and element.get("lane") is None:
            cuts.append({
                "name": str(element.get("name") or ""),
                "timeline_start": _frames(element.get("offset"), fps, f"cut_{index}_offset"),
                "source_start": _frames(element.get("start"), fps, f"cut_{index}_start"),
                "duration": _frames(element.get("duration"), fps, f"cut_{index}_duration"),
            })
        elif element.tag == "asset-clip" and audio_id and element.get("ref") == audio_id and element.get("lane") == "-1":
            audio_rows.append({
                "name": str(element.get("name") or ""),
                "timeline_start": _frames(element.get("offset"), fps, "audio_offset"),
                "source_start": _frames(element.get("start"), fps, "audio_start"),
                "duration": _frames(element.get("duration"), fps, "audio_duration"),
            })
        elif element.tag == "title":
            lane_text = str(element.get("lane") or "")
            try:
                lane = int(lane_text)
            except ValueError:
                raise ValueError(f"fcpxml_title_lane_{index}") from None
            if lane <= 0 or lane_text != str(lane):
                raise ValueError(f"fcpxml_title_lane_{index}")
            text = element.find("./text/text-style")
            if text is None or not element.get("ref") or element.find("./text-style-def") is None:
                raise ValueError(f"fcpxml_title_{index}")
            title = {
                "name": str(element.get("name") or ""),
                "text": str(text.text or ""),
                "timeline_start": _frames(element.get("offset"), fps, f"title_{index}_offset"),
                "duration": _frames(element.get("duration"), fps, f"title_{index}_duration"),
                "lane": lane,
            }
            if title["name"].startswith("VC_VFX_"):
                marker = element.find("./marker")
                try:
                    note = json.loads(str(marker.get("note") if marker is not None else ""))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"fcpxml_flash_{index}") from exc
                if (
                    not isinstance(note, Mapping)
                    or note.get("schema") != "video_cloner_transition_vfx_placeholder"
                    or note.get("transition_type") != "flash_cut"
                    or note.get("backend") != "vfx_placeholder"
                    or note.get("offset_frame") != title["timeline_start"]
                    or note.get("duration_frames") != title["duration"]
                ):
                    raise ValueError(f"fcpxml_flash_{index}")
                title["transition_id"] = str(note.get("transition_id") or "")
                title["boundary_frame"] = note.get("boundary_frame")
                title["transition_type"] = note.get("transition_type")
                flash_handoffs.append(title)
            else:
                titles.append(title)
        else:
            raise ValueError(f"fcpxml_spine_item_{index}")
    if not cuts or not titles or len(audio_rows) != (1 if audio else 0):
        raise ValueError("fcpxml_track_counts")
    expected_start = 0
    for row in cuts:
        if row["timeline_start"] != expected_start or row["source_start"] != expected_start or row["duration"] <= 0:
            raise ValueError("fcpxml_cut_mapping")
        expected_start += row["duration"]
    total = _frames(sequence.get("duration"), fps, "sequence_duration")
    if expected_start != total or any(row["duration"] <= 0 or row["timeline_start"] < 0 or row["timeline_start"] + row["duration"] > total for row in titles):
        raise ValueError("fcpxml_timeline_mapping")
    title_lanes = sorted({row["lane"] for row in titles})
    if title_lanes != list(range(1, title_lanes[-1] + 1)):
        raise ValueError("fcpxml_title_lanes")
    for lane in title_lanes:
        lane_titles = sorted((row for row in titles if row["lane"] == lane), key=lambda row: row["timeline_start"])
        if any(current["timeline_start"] < previous["timeline_start"] + previous["duration"] for previous, current in zip(lane_titles, lane_titles[1:])):
            raise ValueError("fcpxml_same_lane_overlap")
    if audio_rows and audio_rows[0] != {"name": audio_rows[0]["name"], "timeline_start": 0, "source_start": 0, "duration": total}:
        raise ValueError("fcpxml_audio_mapping")
    if any(root.findall(f".//{tag}") for tag in ("gap", "transition", "timeMap", "timept", "filter-video")):
        raise ValueError("fcpxml_forbidden")
    return {
        "timeline_name": str(project.get("name") or ""),
        "fps": fps,
        "duration_frames": total,
        "proxy": proxy,
        "audio": audio,
        "cuts": cuts,
        "audio_rows": audio_rows,
        "titles": titles,
        "title_lanes": title_lanes,
        "flash_handoffs": flash_handoffs,
    }


def _load_combined_contract(root: Path, manifest_path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    stored_set_hash = manifest.get("artifact_set_sha256")
    unsigned = dict(manifest)
    unsigned.pop("artifact_set_sha256", None)
    if (
        manifest.get("version") != 1
        or manifest.get("artifact_contract") != COMBINED_ARTIFACT_CONTRACT
        or not isinstance(stored_set_hash, str)
        or stored_set_hash != _fingerprint(unsigned)
    ):
        raise ValueError("combined_manifest_identity")
    inputs = manifest.get("inputs")
    authorities = manifest.get("authorities")
    outputs = manifest.get("outputs")
    invariants = manifest.get("invariants")
    if not all(isinstance(value, Mapping) for value in (inputs, authorities, outputs, invariants)):
        raise ValueError("combined_manifest_contract")
    generic = _identity_file(root, inputs.get("generic"), "generic")
    proxy = _identity_file(root, inputs.get("proxy"), "proxy")
    audio = _identity_file(root, inputs.get("audio"), "audio")
    _identity_file(root, inputs.get("caption_style"), "caption_style")
    lifecycle_path = _identity_file(root, authorities.get("caption_lifecycle"), "caption_lifecycle")
    transition_path = _identity_file(root, authorities.get("transition"), "transition_authority")
    fcpxml = _identity_file(root, outputs.get("fcpxml"), "fcpxml")
    report_path = _identity_file(root, outputs.get("report"), "report")
    generic_value = _read_json(generic, "generic")
    lifecycle = _read_json(lifecycle_path, "caption_lifecycle")
    transition = _read_json(transition_path, "transition_authority")
    report = _read_json(report_path, "report")
    video_id = manifest.get("video_id")
    if video_id != generic_value.get("video_id") or video_id != report.get("video_id") or video_id != transition.get("video_id"):
        raise ValueError("combined_video_identity")
    if lifecycle.get("ok") is not True or lifecycle.get("schema") != "video_cloner_caption_lifecycle_authority_plan":
        raise ValueError("combined_lifecycle_contract")
    flash_rows = transition.get("flash_handoffs")
    if transition.get("success") is not True or transition.get("schema") != "video_cloner.transition_authority.v1" or not isinstance(flash_rows, list) or len(flash_rows) != 1:
        raise ValueError("combined_transition_contract")
    flash = flash_rows[0]
    if not isinstance(flash, Mapping) or (flash.get("transition_type"), flash.get("handoff_type")) != ("flash_cut", "flash_v4_visual_carrier"):
        raise ValueError("combined_transition_contract")
    if report.get("success") is not True or report.get("schema") != "video_cloner.standalone_fcpxml.v1":
        raise ValueError("combined_report_contract")
    report_inputs = report.get("inputs")
    report_output = report.get("output")
    if not isinstance(report_inputs, Mapping) or not isinstance(report_output, Mapping):
        raise ValueError("combined_report_contract")
    expected_input_hashes = {
        "generic_sha256": _sha256(generic), "source_video_sha256": _sha256(proxy),
        "source_audio_sha256": _sha256(audio), "caption_lifecycle_sha256": _sha256(lifecycle_path),
        "transition_authority_sha256": _sha256(transition_path),
    }
    if any(report_inputs.get(key) != value for key, value in expected_input_hashes.items()) or report_output.get("sha256") != _sha256(fcpxml):
        raise ValueError("combined_report_identity")
    xml = parse_textplus_fcpxml(fcpxml, proxy, audio)
    structure = report.get("structure")
    caption_authority = report.get("caption_authority")
    compiled = report.get("compiled_operation_counts")
    semantic = caption_authority.get("semantic") if isinstance(caption_authority, Mapping) else None
    summary = semantic.get("summary") if isinstance(semantic, Mapping) else None
    cues = semantic.get("cues") if isinstance(semantic, Mapping) else None
    lifecycle_report = caption_authority.get("lifecycle") if isinstance(caption_authority, Mapping) else None
    source_summary = lifecycle_report.get("source_summary") if isinstance(lifecycle_report, Mapping) else None
    metrics = caption_authority.get("metrics") if isinstance(caption_authority, Mapping) else None
    if not isinstance(structure, Mapping) or (
        structure.get("clip_count"), structure.get("audio_asset_count"), structure.get("caption_count"),
        structure.get("flash_handoff_count"), structure.get("timeline_duration_frames")
    ) != (len(xml["cuts"]), len(xml["audio_rows"]), len(xml["titles"]), len(xml["flash_handoffs"]), xml["duration_frames"]):
        raise ValueError("combined_report_structure")
    expected_compiled = {
        "animated_zoom": 0, "blur": 0, "captions": 92, "cross_dissolve": 0,
        "flash_handoffs": 1, "slide": 0, "slide_edge_wipe": 0, "speed": 0,
        "transitions": 0, "whip": 0,
    }
    if dict(compiled) != expected_compiled:
        raise ValueError("combined_executable_operations")
    if not isinstance(summary, Mapping) or summary.get("source_coverage_exact") is not True or not isinstance(metrics, Mapping) or metrics.get("dropped_semantic_words") != 0 or metrics.get("added_semantic_words") != 0:
        raise ValueError("combined_semantic_coverage")
    required = {
        "timeline_duration_frames": xml["duration_frames"], "video_clip_count": len(xml["cuts"]),
        "a1_clip_count": len(xml["audio_rows"]), "caption_count": len(xml["titles"]),
        "source_cue_count": summary.get("source_cue_count") if isinstance(summary, Mapping) else None,
        "source_coverage_count": summary.get("source_coverage_count") if isinstance(summary, Mapping) else None,
        "visual_primary_count": source_summary.get("visual_primary_count") if isinstance(source_summary, Mapping) else None,
        "transcript_fallback_count": source_summary.get("transcript_fallback_count") if isinstance(source_summary, Mapping) else None,
        "caption_lane_usage": metrics.get("lane_usage") if isinstance(metrics, Mapping) else None,
        "same_lane_overlap_count": metrics.get("same_lane_overlap_count") if isinstance(metrics, Mapping) else None,
        "flash_handoff_count": len(xml["flash_handoffs"]), "flash_transition_type": flash.get("transition_type"),
        "flash_handoff_type": flash.get("handoff_type"), "flash_boundary_frame": flash.get("boundary_frame"),
        "flash_duration_frames": flash.get("duration_frames"), "speed_count": compiled.get("speed") if isinstance(compiled, Mapping) else None,
        "zoom_count": compiled.get("animated_zoom") if isinstance(compiled, Mapping) else None,
        "blur_count": compiled.get("blur") if isinstance(compiled, Mapping) else None,
        "native_transition_count": structure.get("native_transition_count") if isinstance(structure, Mapping) else None,
    }
    if dict(invariants) != required or required != {
        "timeline_duration_frames": 854, "video_clip_count": 14, "a1_clip_count": 1, "caption_count": 92,
        "source_cue_count": 93, "source_coverage_count": 93, "visual_primary_count": 17,
        "transcript_fallback_count": 75, "caption_lane_usage": {"1": 77, "2": 14, "3": 1},
        "same_lane_overlap_count": 0, "flash_handoff_count": 1, "flash_transition_type": "flash_cut",
        "flash_handoff_type": "flash_v4_visual_carrier", "flash_boundary_frame": 596,
        "flash_duration_frames": 9, "speed_count": 0, "zoom_count": 0, "blur_count": 0,
        "native_transition_count": 0,
    }:
        raise ValueError("combined_invariants")
    lifecycle_layers = lifecycle.get("layers")
    if not isinstance(cues, list) or not isinstance(lifecycle_layers, list) or len(cues) != len(xml["titles"]) or len(lifecycle_layers) != len(cues):
        raise ValueError("combined_caption_contract")
    for title, cue, layer in zip(xml["titles"], cues, lifecycle_layers):
        window = layer.get("lifecycle_window") if isinstance(layer, Mapping) else None
        if (
            not isinstance(cue, Mapping) or not isinstance(window, list) or len(window) != 2
            or layer.get("cue_id") != cue.get("id")
            or (title["text"], title["timeline_start"], title["duration"]) != (cue.get("text"), window[0], window[1] - window[0])
        ):
            raise ValueError("combined_caption_contract")
        title["caption_id"] = str(cue.get("id") or "")
    xml_flash = xml["flash_handoffs"][0]
    if (xml_flash.get("transition_id"), xml_flash.get("boundary_frame"), xml_flash.get("duration")) != (flash.get("id"), flash.get("boundary_frame"), flash.get("duration_frames")):
        raise ValueError("combined_flash_contract")
    return {
        "manifest_path": manifest_path, "artifact_set_sha256": stored_set_hash,
        "textplus_fingerprint": stored_set_hash, "fcpxml": fcpxml, "fcpxml_sha256": _sha256(fcpxml),
        "report": report_path, "report_sha256": _sha256(report_path), "xml": xml,
        "editing_dna": None, "application_plan": {}, "limitations": {},
    }


def load_phase5_contract(root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest_path = _repository_path(root, manifest_path, "manifest")
    manifest = _read_json(manifest_path, "manifest")
    if manifest.get("schema") == COMBINED_MANIFEST_SCHEMA:
        return _load_combined_contract(root, manifest_path, manifest)
    stored_set_hash = manifest.get("artifact_set_sha256")
    unsigned = dict(manifest)
    unsigned.pop("artifact_set_sha256", None)
    artifact_contract = manifest.get("artifact_set_contract")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("version") != 1 or artifact_contract not in {"offline_fcpxml_only_no_resolve", "unified_editing_dna_application_v2"}:
        raise ValueError("manifest_contract")
    if not isinstance(stored_set_hash, str) or stored_set_hash != _fingerprint(unsigned):
        raise ValueError("manifest_self_identity")
    inputs = manifest.get("inputs")
    nodes = manifest.get("nodes")
    if not isinstance(inputs, Mapping) or not isinstance(nodes, Mapping) or not isinstance(nodes.get(NODE), Mapping):
        raise ValueError("manifest_nodes")
    node = nodes[NODE]
    if node.get("contract") != NODE_CONTRACT:
        raise ValueError("textplus_contract")
    node_inputs = {"generic": inputs.get("generic"), "proxy": inputs.get("proxy"), "caption_style": inputs.get("caption_style"), "audio": inputs.get("audio")}
    if inputs.get("editing_dna") is not None:
        node_inputs["editing_dna"] = inputs.get("editing_dna")
    node_identity = {"node": NODE, "inputs": node_inputs, "producer": node.get("producer")}
    if node.get("fingerprint") != _fingerprint(node_identity):
        raise ValueError("textplus_fingerprint")
    generic = _identity_file(root, inputs.get("generic"), "generic")
    proxy = _identity_file(root, inputs.get("proxy"), "proxy")
    style = _identity_file(root, inputs.get("caption_style"), "caption_style")
    audio = _identity_file(root, inputs.get("audio"), "audio") if inputs.get("audio") is not None else None
    editing_dna = _identity_file(root, inputs.get("editing_dna"), "editing_dna") if inputs.get("editing_dna") is not None else None
    application_plan = manifest.get("application_plan") or {}
    available_assets = manifest.get("available_assets") or {}
    limitations = manifest.get("limitations") or {}
    if artifact_contract == "unified_editing_dna_application_v2":
        dna = _read_json(editing_dna, "editing_dna") if editing_dna is not None else {}
        if dna.get("schema") != "video_cloner.editing_dna" or manifest.get("video_id") != dna.get("video_id") or not isinstance(application_plan, Mapping) or not isinstance(available_assets, Mapping):
            raise ValueError("unified_application_contract")
        if set(application_plan) != {"cuts_shot_structure_audio", "caption_timing_lifecycle", "caption_font_style_geometry", "caption_animations", "native_transitions", "occlusion_compositing", "motion_vfx", "speed_ramps"}:
            raise ValueError("unified_application_layers")
    outputs = node.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("textplus_outputs")
    fcpxml = _identity_file(root, outputs.get("fcpxml"), "textplus_fcpxml")
    report_path = _identity_file(root, outputs.get("report"), "textplus_report")
    report = _read_json(report_path, "textplus_report")
    report_inputs = report.get("inputs")
    report_output = report.get("output")
    if report.get("success") is not True or report.get("schema") != "video_cloner.standalone_textplus_fcpxml_report.v1" or not isinstance(report_inputs, Mapping) or not isinstance(report_output, Mapping):
        raise ValueError("textplus_report_contract")
    expected_inputs = {"generic": generic, "caption_style": style, "source_video": proxy, "source_audio": audio}
    for key, expected in expected_inputs.items():
        identity = report_inputs.get(key)
        if expected is None:
            if identity is not None:
                raise ValueError(f"textplus_report_{key}")
        elif not isinstance(identity, Mapping) or identity.get("sha256") != _sha256(expected) or not _same_path(identity.get("path"), expected):
            raise ValueError(f"textplus_report_{key}")
    if report_output.get("sha256") != _sha256(fcpxml) or not _same_path(report_output.get("fcpxml"), fcpxml):
        raise ValueError("textplus_report_output")
    xml = parse_textplus_fcpxml(fcpxml, proxy, audio)
    structure = report.get("structure")
    if not isinstance(structure, Mapping) or (structure.get("v1_clip_count"), structure.get("a1_clip_count"), structure.get("v2_title_count"), structure.get("timeline_duration_frames")) != (len(xml["cuts"]), len(xml["audio_rows"]), len(xml["titles"]), xml["duration_frames"]):
        raise ValueError("textplus_report_structure")
    captions = structure.get("caption_contract")
    if not isinstance(captions, list) or len(captions) != len(xml["titles"]):
        raise ValueError("textplus_report_captions")
    caption_ids: set[str] = set()
    for title, caption in zip(xml["titles"], captions):
        if not isinstance(caption, Mapping):
            raise ValueError("textplus_report_captions")
        caption_id = str(caption.get("subtitle_id") or "")
        expected = (title["text"], title["timeline_start"], title["timeline_start"] + title["duration"], title["lane"])
        actual = (caption.get("text"), caption.get("timeline_start_frame"), caption.get("timeline_end_frame"), caption.get("lane"))
        if not caption_id or caption_id in caption_ids or actual != expected:
            raise ValueError("textplus_report_captions")
        caption_ids.add(caption_id)
        title["caption_id"] = caption_id
    if (structure.get("caption_lane_count"), structure.get("max_caption_lane"), structure.get("same_lane_overlap_count"), structure.get("overlap_preserved")) != (len(xml["title_lanes"]), xml["title_lanes"][-1], 0, True):
        raise ValueError("textplus_report_lanes")
    return {
        "manifest_path": manifest_path,
        "artifact_set_sha256": stored_set_hash,
        "textplus_fingerprint": node["fingerprint"],
        "fcpxml": fcpxml,
        "fcpxml_sha256": _sha256(fcpxml),
        "report": report_path,
        "report_sha256": _sha256(report_path),
        "xml": xml,
        "editing_dna": editing_dna,
        "application_plan": dict(application_plan),
        "available_assets": dict(available_assets) if isinstance(available_assets, Mapping) else {},
        "limitations": dict(limitations) if isinstance(limitations, Mapping) else {},
    }


def verified_layer_report(plan: Mapping[str, Any], target_validation: Mapping[str, Any], applied: Mapping[str, Any] | None = None) -> dict[str, Any]:
    applied = applied or {}
    runtime_layers = {"caption_animations", "native_transitions", "occlusion_compositing", "motion_vfx"}
    layers: dict[str, Any] = {}
    for name, raw in plan.items():
        row = dict(raw) if isinstance(raw, Mapping) else {"disposition": "unsupported", "reason": "invalid application plan row"}
        disposition = str(row.pop("disposition", "unsupported"))
        status = "applied" if disposition == "apply" and (name not in runtime_layers or name in applied) else ("not_applied" if disposition == "apply" else disposition)
        if status == "applied" and name in applied and row.get("accepted_recipe_count") is not None and applied[name].get("applied_count") != row.get("accepted_recipe_count"):
            status = "partially_applied"
        row["status"] = status
        if status in {"applied", "partially_applied"}:
            row["resolve_verification"] = {
                "timeline_identity_and_structure": True,
                "verified_title_count": target_validation.get("v2_title_count"),
                "verified_video_clip_count": target_validation.get("v1_clip_count"),
                "verified_audio_clip_count": target_validation.get("a1_clip_count"),
            }
            if name in applied:
                row["resolve_verification"]["operations"] = applied[name]
        layers[name] = row
    return layers


def _load_workspace_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_motion_vfx(target: Any, contract: Mapping[str, Any]) -> dict[str, Any]:
    layer = (contract.get("application_plan") or {}).get("motion_vfx") or {}
    recipes = layer.get("recipes") if isinstance(layer, Mapping) else None
    if not isinstance(recipes, list) or not recipes:
        return {"status": "not_applicable", "applied_count": 0}
    base = _as_int(_safe(target, "GetStartFrame", default=0)) or 0
    items = [item for item in (_safe(target, "GetItemListInTrack", "video", 1, default=[]) or []) if _safe(item, "GetMediaPoolItem") is not None]
    items.sort(key=lambda item: _as_int(_safe(item, "GetStart")) or -1)
    expected = contract["xml"]["cuts"]
    actual = [((_as_int(_safe(item, "GetStart")) or 0) - base, _as_int(_safe(item, "GetDuration"))) for item in items]
    wanted = [(row["timeline_start"], row["duration"]) for row in expected]
    if actual != wanted:
        raise ValueError(f"motion_v1_contract:{actual!r}")

    token = str(contract["artifact_set_sha256"])[:12]
    names = {int(row["shot"]): f"VC_DNA_MOTION_SHOT_{int(row['shot']):03d}_{token}" for row in recipes}
    present = {
        shot: name in [str(value) for value in (_safe(items[shot - 1], "GetFusionCompNameList", default=[]) or [])]
        for shot, name in names.items()
    }
    if any(present.values()):
        if not all(present.values()):
            raise ValueError(f"motion_partial_application:{present!r}")
        if any(_safe(items[shot - 1], "LoadFusionCompByName", name) is None for shot, name in names.items()):
            raise ValueError("motion_owned_comp_readback")
        return {"status": "reused", "applied_count": len(names), "comp_names": list(names.values())}
    for shot in names:
        existing = [str(value) for value in (_safe(items[shot - 1], "GetFusionCompNameList", default=[]) or [])]
        if existing:
            raise ValueError(f"motion_unowned_fusion_collision:shot_{shot}:{existing!r}")

    module = _load_workspace_module("vc_unified_motion", Path(__file__).resolve().with_name("oss004_motion_vfx_representative_batch.py"))
    module.oss003.EXPECTED_V1 = tuple(wanted)
    created: list[tuple[Any, str]] = []
    evidence = []
    try:
        for source in recipes:
            shot = int(source["shot"])
            scale = [[int(frame), float(value)] for frame, value in source["scale"]]
            recipe = {
                "id": f"shot_{shot:03d}_transform_zoom", "shot": shot,
                "window": [scale[0][0], scale[-1][0]], "behavior": "source-backed transform zoom",
                "position": [], "scale": scale, "blur": [], "confidence": source.get("confidence"),
                "provenance": ["editing_dna.motion_vfx.editor_contract"],
            }
            created.append((items[shot - 1], names[shot]))
            evidence.append(module._apply_recipe(items[shot - 1], recipe, names[shot], allow_source_handles=True))
    except Exception:
        for item, name in reversed(created):
            _safe(item, "DeleteFusionCompByName", name, default=False)
        raise
    return {"status": "applied", "applied_count": len(evidence), "comp_names": list(names.values()), "readback": evidence}


def apply_caption_animations(resolve: Any, project: Any, pool: Any, target: Any, contract: Mapping[str, Any]) -> dict[str, Any]:
    layer = (contract.get("application_plan") or {}).get("caption_animations") or {}
    recipes = layer.get("recipes") if isinstance(layer, Mapping) else None
    if not isinstance(recipes, list) or not recipes:
        return {"status": "not_applicable", "applied_count": 0, "created_timeline_count": 0}

    rep = _load_workspace_module("vc_unified_caption_animation", Path(__file__).resolve().with_name("oss002_oss_animation_representative_batch.py"))
    recipes = [rep.recipe_contract.validate_recipe(dict(row)) for row in recipes]
    root = ET.parse(contract["fcpxml"]).getroot()
    title_nodes = list(root.findall("./library/event/project/sequence/spine/title"))
    formats = list(root.findall("./resources/format"))
    if len(title_nodes) != len(contract["xml"]["titles"]) or len(formats) != 1:
        raise ValueError("caption_animation_fcpxml")
    rep.batch.EXPECTED_CAPTIONS = len(title_nodes)
    styles = rep.batch._styles_by_ordinal(contract["fcpxml"])
    width, height = int(formats[0].get("width") or 0), int(formats[0].get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("caption_animation_format")
    for index, node in enumerate(title_nodes, start=1):
        transform = node.find("./adjust-transform")
        values = str(transform.get("position") if transform is not None else "0 0").split()
        if len(values) != 2:
            raise ValueError(f"caption_animation_position:{index}")
        # FCPXML adjust-transform coordinates are in percent of frame HEIGHT.
        # Fusion Center is normalized per axis (0,0 bottom-left; 1,1 top-right).
        # Convert both axes to Fusion units; the FCPXML Y sign is already up.
        styles[index]["Center"] = [
            0.5 + float(values[0]) * height / (100.0 * width),
            0.5 + float(values[1]) / 100.0,
        ]

    base = _as_int(_safe(target, "GetStartFrame", default=0)) or 0
    originals = rep.canary.basic_title_rows(target)
    selected: dict[str, dict[str, Any]] = {}
    for recipe in recipes:
        matches = [
            row for row in originals
            if row["track"] == int(recipe["lane"]) + 1
            and row["start"] - base == int(recipe["start_frame"])
            and row["duration"] == int(recipe["duration"])
            and row["text_readback"] in (None, recipe["text"])
        ]
        if len(matches) != 1:
            raise ValueError(f"caption_animation_target:{recipe['caption_id']}:{len(matches)}")
        selected[str(recipe["caption_id"])] = matches[0]

    token = str(contract["artifact_set_sha256"])[:12]
    names = {caption_id: f"_VC_DNA_ANIM_{caption_id}_{token}" for caption_id in selected}
    nested = {row["source"]["name"]: row for row in rep.batch._nested_items(target) if row["source"]["name"] in set(names.values())}
    present = {caption_id: names[caption_id] in nested for caption_id in names}
    if any(present.values()):
        if not all(present.values()):
            raise ValueError(f"caption_animation_partial_application:{present!r}")
        readback = []
        for recipe in recipes:
            caption_id = str(recipe["caption_id"])
            row = nested[names[caption_id]]
            if row["start"] - base != recipe["start_frame"] or row["duration"] != recipe["duration"] or selected[caption_id]["enabled"] is not False:
                raise ValueError(f"caption_animation_reuse_contract:{caption_id}")
            _, tool = rep.canary.carrier._find_textplus(row["inner"])
            targets = rep._channel_targets(recipe, styles[int(recipe["title_index"])])
            if any(not rep.canary.animation.input_targets_are_correct(tool, name, values) for name, values in targets.items()):
                raise ValueError(f"caption_animation_reuse_readback:{caption_id}")
            readback.append({"caption_id": caption_id, "channels": sorted(recipe["channels"])})
        return {"status": "reused", "applied_count": len(readback), "created_timeline_count": 0, "readback": readback}

    occupied: dict[int, list[tuple[int, int]]] = {}
    first_track = max((row["track"] for row in originals), default=1) + 1
    allocation: dict[str, int] = {}
    for recipe in sorted(recipes, key=lambda row: (int(row["start_frame"]), str(row["caption_id"]))):
        interval = (int(recipe["start_frame"]), int(recipe["start_frame"]) + int(recipe["duration"]))
        track = first_track
        while any(interval[0] < end and start < interval[1] for start, end in occupied.setdefault(track, [])):
            track += 1
        occupied[track].append(interval)
        allocation[str(recipe["caption_id"])] = track
    created_tracks: list[int] = []
    while int(_safe(target, "GetTrackCount", "video", default=0) or 0) < max(allocation.values()):
        if _safe(target, "AddTrack", "video", default=False) is not True:
            raise RuntimeError("caption_animation_track_create")
        created_tracks.append(int(_safe(target, "GetTrackCount", "video", default=0) or 0))

    created_sources: list[Any] = []
    placed: list[Any] = []
    disabled: list[Any] = []
    evidence = []
    try:
        for recipe in recipes:
            caption_id = str(recipe["caption_id"])
            source = rep.canary.carrier._call(pool, "CreateEmptyTimeline", names[caption_id])
            created_sources.append(source)
            identity = rep.canary._timeline_identity(source)
            if source is None or identity["name"] != names[caption_id] or not identity["unique_id"] or rep.canary.carrier._call(project, "SetCurrentTimeline", source) is not True:
                raise RuntimeError(f"caption_animation_source:{caption_id}")
            rep.canary.carrier._call(source, "InsertFusionTitleIntoTimeline", "Text+")
            item, tool = rep.canary.carrier._find_textplus(source)
            style = styles[int(recipe["title_index"])]
            static = rep.canary._set_static_style(tool, style)
            comp = rep.canary.carrier._call(item, "GetFusionCompByIndex", 1)
            applied = rep.apply_recipe_channels(comp, tool, recipe, style)
            rep.canary.carrier._call(project, "SetCurrentTimeline", target)
            returned = rep.canary.carrier._call(pool, "AppendToTimeline", [{
                "mediaPoolItem": rep.canary.carrier._call(source, "GetMediaPoolItem"), "startFrame": 0,
                "endFrame": int(recipe["duration"]), "trackIndex": allocation[caption_id],
                "recordFrame": base + int(recipe["start_frame"]),
            }])
            if not isinstance(returned, (list, tuple)) or len(returned) != 1 or returned[0] is None:
                raise RuntimeError(f"caption_animation_append:{caption_id}")
            placed.append(returned[0])
            original = selected[caption_id]["item"]
            if rep.canary.carrier._call(original, "SetClipEnabled", False) is False or rep.canary._clip_enabled(original) is not False:
                raise RuntimeError(f"caption_animation_original_disable:{caption_id}")
            disabled.append(original)
            _, inner_tool = rep.canary.carrier._find_textplus(source)
            targets = rep._channel_targets(recipe, style)
            if any(not rep.canary.animation.input_targets_are_correct(inner_tool, name, values) for name, values in targets.items()):
                raise RuntimeError(f"caption_animation_readback:{caption_id}")
            evidence.append({"caption_id": caption_id, "channels": sorted(recipe["channels"]), "static": static, "animation": applied})
    except Exception:
        rep.canary.carrier._call(project, "SetCurrentTimeline", target)
        for original in disabled:
            rep.canary._optional(original, "SetClipEnabled", True, default=False)
        if placed:
            rep.canary._optional(target, "DeleteClips", placed, False, default=False)
        if created_sources:
            rep.canary._optional(pool, "DeleteTimelines", created_sources, default=False)
        for track in reversed(created_tracks):
            rep.canary._optional(target, "DeleteTrack", "video", track, default=False)
        raise
    return {"status": "applied", "applied_count": len(evidence), "created_timeline_count": len(created_sources), "readback": evidence}


def apply_native_blur_transitions(resolve: Any, project: Any, pool: Any, target: Any, target_name: str, contract: Mapping[str, Any], report_dir: Path) -> tuple[Any, str, dict[str, Any], bool]:
    layer = (contract.get("application_plan") or {}).get("native_transitions") or {}
    recipes = layer.get("native_blur_recipes") if isinstance(layer, Mapping) else None
    if not isinstance(recipes, list) or not recipes:
        return target, target_name, {"status": "not_applicable", "applied_count": 0}, False
    expected = sorted((int(row["cut_frame"]), int(row["duration_frames"])) for row in recipes)

    def readback(timeline: Any) -> list[dict[str, Any]]:
        base = _as_int(_safe(timeline, "GetStartFrame", default=0)) or 0
        rows = []
        for item in _safe(timeline, "GetItemListInTrack", "video", 1, default=[]) or []:
            if _safe(item, "GetMediaPoolItem") is not None:
                continue
            start = (_as_int(_safe(item, "GetStart")) or 0) - base
            duration = _as_int(_safe(item, "GetDuration")) or 0
            rows.append({"name": str(_safe(item, "GetName", default="") or ""), "start": start, "duration": duration, "cut_frame": start + duration // 2})
        rows.sort(key=lambda row: row["start"])
        return rows

    existing = readback(target)
    if existing:
        actual = sorted((row["cut_frame"], row["duration"]) for row in existing if row["name"] == "Blur Dissolve")
        if actual != expected or len(existing) != len(expected):
            raise ValueError(f"native_blur_collision:{existing!r}")
        return target, target_name, {"status": "reused", "applied_count": len(existing), "readback": existing}, False

    layer_hash = _fingerprint({"artifact": contract["artifact_set_sha256"], "layer": "native_blur"})
    derivative_name = _content_addressed_target_name(target_name, layer_hash)
    matches = [row for row in _timelines(project) if str(_safe(row, "GetName", default="") or "") == derivative_name]
    if len(matches) > 1:
        raise ValueError("native_blur_derivative_collision")
    if matches:
        derivative = matches[0]
        _validate_authoritative_import(derivative, _timeline_contract(contract["xml"], derivative_name), True)
        rows = readback(derivative)
        if sorted((row["cut_frame"], row["duration"]) for row in rows if row["name"] == "Blur Dissolve") != expected:
            raise ValueError(f"native_blur_derivative_readback:{rows!r}")
        return derivative, derivative_name, {"status": "reused", "applied_count": len(rows), "readback": rows}, False

    staging_name = f"_VC_NATIVE_BLUR_STAGE_{layer_hash[:12]}"
    if any(str(_safe(row, "GetName", default="") or "") == staging_name for row in _timelines(project)):
        raise ValueError("native_blur_staging_collision")
    duplicate = _safe(target, "DuplicateTimeline", staging_name)
    duplicate_uid = _unique_id(duplicate)
    if duplicate is None or not duplicate_uid:
        raise ValueError("native_blur_derivative_create")
    report_dir.mkdir(parents=True, exist_ok=True)
    unpatched = report_dir / "unified_native_blur_unpatched.drt"
    # Resolve can choose the DRT filename as its imported timeline name, even
    # when the internal MpFolder timeline name has been rewritten.
    patched = report_dir / f"{derivative_name}.drt"
    export_type = getattr(resolve, "EXPORT_DRT", None)
    try:
        if export_type is None or _safe(duplicate, "Export", str(unpatched), export_type, default=False) is not True:
            raise ValueError("native_blur_export")
        module = _load_workspace_module("vc_unified_native_blur", Path(__file__).resolve().with_name("oss003_native_blur_drt.py"))
        donor = Path(__file__).resolve().parents[2] / ".agent/reports/OSS003_NATIVE_BLUR_AUTO_B80_V1/20261011T130946582Z_0d071b6f8542403d8a51b0ac8d669580/blur_dissolve_template.xml"
        if not donor.is_file() or _sha256(donor) != "2b57d7e86794046bb72b32d0e76ac0ddc791c661a0ee88af6d6352ace3bdc326":
            raise ValueError("native_blur_donor_missing")
        selected = module.base.select_top_level(unpatched, staging_name)
        base = _as_int(_safe(duplicate, "GetStartFrame", default=0)) or 0
        module.place_blur_transitions(
            unpatched, patched, timeline_name=staging_name, timeline_uuid=selected["id"],
            donor_element=donor.read_text(encoding="utf-8-sig"), track=1,
            boundaries=[(base + cut, duration) for cut, duration in expected],
            output_timeline_name=derivative_name,
        )
        if _safe(project, "SetCurrentTimeline", target, default=False) is not True or _safe(pool, "DeleteTimelines", [duplicate], default=False) is not True:
            raise ValueError("native_blur_temporary_cleanup")
        duplicate = None
        before_import_ids = {_unique_id(row) for row in _timelines(project)}
        returned = _safe(pool, "ImportTimelineFromFile", str(patched), {"timelineName": derivative_name}, default=None)
        imported_matches = [row for row in _timelines(project) if str(_safe(row, "GetName", default="") or "") == derivative_name]
        if len(imported_matches) != 1:
            actual_name = str(_safe(returned, "GetName", default="") or "") if returned not in (None, False, True) else ""
            raise ValueError(f"native_blur_import_identity:{len(imported_matches)}:{actual_name}")
        derivative = imported_matches[0]
        if not _unique_id(derivative) or _unique_id(derivative) in before_import_ids or (returned not in (None, False, True) and not _same_timeline(returned, derivative)):
            raise ValueError("native_blur_import_returned_identity")
        _validate_authoritative_import(derivative, _timeline_contract(contract["xml"], derivative_name), True)
        rows = readback(derivative)
        if sorted((row["cut_frame"], row["duration"]) for row in rows if row["name"] == "Blur Dissolve") != expected:
            raise ValueError(f"native_blur_live_readback:{rows!r}")
        return derivative, derivative_name, {"status": "applied", "applied_count": len(rows), "readback": rows}, True
    except Exception:
        if duplicate is not None and _unique_id(duplicate) == duplicate_uid:
            _safe(project, "SetCurrentTimeline", target, default=False)
            _safe(pool, "DeleteTimelines", [duplicate], default=False)
        raise


def _neutral_flash_carrier(pool: Any, target: Any, frame_count: int) -> dict[str, Any]:
    """Use a transparent image sequence, never source-video pixels, beneath Fusion flashes.

    Reuses the proven transparent-RGBA carrier approach from the existing
    advanced_transition_flash_neutral_rgba_v4 adapter. The frames remain on
    disk because Resolve references this media after the import completes.
    """
    fps = int(round(float(_safe(target, "GetSetting", "timelineFrameRate", default=24) or 24)))
    width = int(_safe(target, "GetSetting", "timelineResolutionWidth", default=1080) or 1080)
    height = int(_safe(target, "GetSetting", "timelineResolutionHeight", default=1920) or 1920)
    if not (1 <= frame_count <= 240 and 1 <= fps <= 120 and 16 <= width <= 8192 and 16 <= height <= 8192):
        raise ValueError("flash_neutral_carrier_dimensions")
    root = Path(__file__).resolve().parents[2]
    folder = root / "data" / "_shared" / f"flash_neutral_rgba_{fps}fps_{width}x{height}_{frame_count}f"
    folder.mkdir(parents=True, exist_ok=True)

    # Valid, entirely transparent RGBA8 PNG (one zero-alpha scanline per row).
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    raw = (b"\x00" + b"\x00" * (width * 4)) * height
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    for index in range(frame_count):
        path = folder / f"rgba_{index:06d}.png"
        if path.exists():
            if path.read_bytes() != png:
                raise ValueError(f"flash_neutral_carrier_mismatch:{path}")
        else:
            path.write_bytes(png)

    pattern = str(folder / "rgba_%06d.png")
    # This is the proven image-sequence import API, NOT a frame from V1.
    imported = _safe(pool, "ImportMedia", [{"FilePath": pattern, "StartIndex": 0, "EndIndex": frame_count - 1}])
    items = list(imported) if isinstance(imported, (tuple, list)) else ([imported] if imported is not None else [])
    if len(items) != 1:
        raise ValueError(f"flash_neutral_carrier_import:{len(items)}")
    item = items[0]
    _safe(item, "SetClipProperty", "Video Frame Rate", str(fps))
    _safe(item, "SetClipProperty", "Alpha mode", "Straight")
    properties = _safe(item, "GetClipProperty", default={}) or {}
    source_path = str(next((properties.get(key) for key in ("File Path", "FilePath", "Path") if properties.get(key)), ""))
    if not source_path or str(folder).lower().replace("\\", "/") not in source_path.lower().replace("\\", "/"):
        raise ValueError(f"flash_neutral_carrier_source_unverified:{source_path}")
    return {"ok": True, "media_pool_item": item, "source_start": 0, "kind": "transparent_rgba_sequence", "source_video_pixels_possible": False}


def apply_flash_transitions(pool: Any, target: Any, contract: Mapping[str, Any]) -> dict[str, Any]:
    layer = (contract.get("application_plan") or {}).get("native_transitions") or {}
    rows = layer.get("flash_recipes") if isinstance(layer, Mapping) else None
    if not isinstance(rows, list) or not rows:
        return {"status": "not_applicable", "applied_count": 0}
    flash = _load_workspace_module("vc_unified_flash", Path(__file__).resolve().with_name("advanced_transition_flash_application_v1.py"))
    base = _as_int(_safe(target, "GetStartFrame", default=0)) or 0
    specs = [{
        **row,
        "name": f"VC_FLASH_{index:03d}_frame_{int(row['cut_frame']):04d}",
        "start_frame": base + int(row["cut_frame"]) - int(row["outgoing_frames"]),
        "alpha_keyframes": [[0, 0.0], [int(row["outgoing_frames"]), 0.75], [int(row["duration_frames"]) - 1, 0.0]],
    } for index, row in enumerate(rows, start=1)]
    existing = [(track, item) for track, item in flash.all_video_items(target) if flash.item_name(item).startswith("VC_FLASH_")]
    if existing:
        # Old runs used the first frames of V1 as flash media. Never silently
        # reuse those clips just because their timing and Fusion graph match.
        for _, item in existing:
            media = flash.safe_call(item, "GetMediaPoolItem", default=None)
            properties = flash.safe_call(media, "GetClipProperty", default={}) if media is not None else {}
            properties = properties if isinstance(properties, Mapping) else {}
            path = str(next((properties[key] for key in ("File Path", "FilePath", "Path") if properties.get(key)), ""))
            if "flash_neutral_rgba_" not in path.lower():
                raise ValueError("legacy_source_video_flash_carrier: create a fresh review timeline")
        tracks = {track for track, _ in existing}
        if len(tracks) != 1:
            raise ValueError("flash_owned_track_identity")
        snapshot = flash.flash_snapshot(target, specs, next(iter(tracks)))
        if snapshot.get("ok") is not True:
            raise ValueError(f"flash_owned_readback:{snapshot!r}")
        return {"status": "reused", "applied_count": len(specs), "snapshot": snapshot}

    track_info = flash.ensure_extra_video_track(target, flash.track_count(target, "video"))
    if track_info.get("ok") is not True:
        raise ValueError(f"flash_track:{track_info!r}")
    target_track = int(track_info["target_track"])
    carrier = _neutral_flash_carrier(pool, target, max(int(row["duration_frames"]) for row in specs))
    if carrier.get("ok") is not True or carrier.get("source_video_pixels_possible") is not False:
        raise ValueError(f"flash_carrier:{carrier!r}")
    appended = flash.append_flash_carriers(pool, target, carrier, specs, target_track)
    try:
        if appended.get("ok") is not True:
            raise ValueError(f"flash_append:{appended!r}")
        configured = [flash.configure_flash(item, spec, index) for index, (spec, item) in enumerate(appended["assigned"], start=1)]
        snapshot = flash.flash_snapshot(target, specs, target_track)
        if not all(row.get("ok") for row in configured) or snapshot.get("ok") is not True:
            raise ValueError(f"flash_readback:{snapshot!r}")
        return {"status": "applied", "applied_count": len(specs), "track_index": target_track, "snapshot": snapshot}
    except Exception:
        assigned = [item for _, item in appended.get("assigned", [])]
        if assigned:
            _safe(target, "DeleteClips", assigned, False, default=False)
        _safe(target, "DeleteTrack", "video", target_track, default=False)
        raise


def _as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _media_path(item: Any) -> str:
    media = _safe(item, "GetMediaPoolItem")
    properties = _safe(media, "GetClipProperty", default={}) if media is not None else {}
    if isinstance(properties, Mapping):
        for key in ("File Path", "FilePath", "Path"):
            if properties.get(key):
                return str(Path(str(properties[key])).resolve())
    return ""


def _title_text(item: Any) -> str | None:
    properties = _safe(item, "GetProperty", default={})
    if isinstance(properties, Mapping):
        for key in ("StyledText", "InputStyledText", "Text", "Title"):
            if properties.get(key) not in (None, ""):
                return str(properties[key])
    comps: list[Any] = []
    count = _as_int(_safe(item, "GetFusionCompCount", default=0)) or 0
    comps.extend(_safe(item, "GetFusionCompByIndex", index) for index in range(1, count + 1))
    for name in list(_safe(item, "GetFusionCompNameList", default=[]) or []):
        comps.append(_safe(item, "GetFusionCompByName", name))
    for comp in comps:
        if comp is None:
            continue
        tools = _safe(comp, "GetToolList", False, "TextPlus", default=None)
        if not isinstance(tools, Mapping):
            tools = _safe(comp, "GetToolList", default={})
        if isinstance(tools, Mapping):
            for tool in tools.values():
                attrs = _safe(tool, "GetAttrs", default={})
                if isinstance(attrs, Mapping) and str(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID") or "") not in {"TextPlus", "Text3D", ""}:
                    continue
                for key in ("StyledText", "InputStyledText", "Text"):
                    for args in ((key, 0), (key,)):
                        value = _safe(tool, "GetInput", *args)
                        if value not in (None, ""):
                            return str(value)
    return None


def _item_snapshot(item: Any, track_type: str, track_index: int) -> dict[str, Any]:
    media_pool_item = _safe(item, "GetMediaPoolItem")
    nested = _safe(media_pool_item, "GetTimeline") if media_pool_item is not None else None
    return {
        "track_type": track_type,
        "track_index": track_index,
        "name": str(_safe(item, "GetName", default="") or ""),
        "start": _as_int(_safe(item, "GetStart")),
        "end": _as_int(_safe(item, "GetEnd")),
        "duration": _as_int(_safe(item, "GetDuration")),
        "left_offset": _as_int(_safe(item, "GetLeftOffset")),
        "media_path": _media_path(item),
        "nested_timeline_name": str(_safe(nested, "GetName", default="") or ""),
        "title_text": _title_text(item) if track_type == "video" and track_index > 1 else None,
    }


def timeline_snapshot(timeline: Any) -> dict[str, Any]:
    video_count = _as_int(_safe(timeline, "GetTrackCount", "video", default=0)) or 0
    audio_count = _as_int(_safe(timeline, "GetTrackCount", "audio", default=0)) or 0
    items: list[dict[str, Any]] = []
    for track_type, count in (("video", video_count), ("audio", audio_count)):
        for track in range(1, count + 1):
            rows = list(_safe(timeline, "GetItemListInTrack", track_type, track, default=[]) or [])
            items.extend(_item_snapshot(item, track_type, track) for item in rows)
    snapshot = {
        "name": str(_safe(timeline, "GetName", default="") or ""),
        "unique_id": str(_safe(timeline, "GetUniqueId", default="") or "") or None,
        "start_frame": _as_int(_safe(timeline, "GetStartFrame", default=0)) or 0,
        "end_frame": _as_int(_safe(timeline, "GetEndFrame")),
        "settings": {
            "timelineFrameRate": _safe(timeline, "GetSetting", "timelineFrameRate"),
            "timelinePlaybackFrameRate": _safe(timeline, "GetSetting", "timelinePlaybackFrameRate"),
        },
        "video_track_count": video_count,
        "audio_track_count": audio_count,
        "items": items,
    }
    snapshot["signature"] = _fingerprint(snapshot)
    return snapshot


def _timelines(project: Any) -> list[Any]:
    count = _as_int(_safe(project, "GetTimelineCount", default=0)) or 0
    rows = [_safe(project, "GetTimelineByIndex", index) for index in range(1, count + 1)]
    if any(row is None for row in rows):
        raise ValueError("timeline_inventory_incomplete")
    return rows


def _timeline_inventory(project: Any) -> list[dict[str, Any]]:
    return [timeline_snapshot(row) for row in _timelines(project)]


def _folder_values(value: Any) -> list[Any]:
    if isinstance(value, Mapping):
        return list(value.values())
    return list(value or []) if isinstance(value, (list, tuple)) else []


def _media_pool_inventory(pool: Any) -> list[dict[str, Any]]:
    root = _safe(pool, "GetRootFolder")
    if root is None:
        raise ValueError("media_pool_root")
    rows: list[dict[str, Any]] = []

    def visit(folder: Any, parent: str) -> None:
        name = str(_safe(folder, "GetName", default="") or "")
        folder_path = f"{parent}/{name}" if parent else name
        clips = _folder_values(_safe(folder, "GetClipList", default=[]))
        for clip in clips:
            properties = _safe(clip, "GetClipProperty", default={})
            if not isinstance(properties, Mapping):
                properties = {}
            selected = {key: properties.get(key) for key in ("File Path", "FilePath", "Path", "Clip Name", "Type", "Duration", "Start", "End", "FPS") if key in properties}
            row = {"folder": folder_path, "name": str(_safe(clip, "GetName", default="") or ""), "properties": selected}
            row["signature"] = _fingerprint(row)
            rows.append(row)
        for child in _folder_values(_safe(folder, "GetSubFolderList", default=[])):
            visit(child, folder_path)

    visit(root, "")
    return rows


def _validate_item(actual: Mapping[str, Any], expected: Mapping[str, Any], base: int, media: Path | None, title: bool = False, require_title_text: bool = True, expected_title_texts: set[str] | None = None) -> None:
    identity = {
        "caption_id": expected.get("caption_id"),
        "expected_name": expected.get("name"),
        "lane": expected.get("lane"),
        "track_index": actual.get("track_index"),
    }
    if actual.get("start") is None or actual.get("duration") is None:
        raise TargetMismatch("target_item_readback", **identity, actual_start=actual.get("start"), actual_duration=actual.get("duration"))
    if actual["start"] - base != expected["timeline_start"] or actual["duration"] != expected["duration"]:
        raise TargetMismatch("target_timing", **identity, expected_start=expected["timeline_start"], actual_start=actual["start"] - base, expected_duration=expected["duration"], actual_duration=actual["duration"])
    if actual.get("end") is None or actual["end"] - actual["start"] not in {expected["duration"], expected["duration"] - 1}:
        raise TargetMismatch("target_end", **identity, expected_duration=expected["duration"], actual_start=actual.get("start"), actual_end=actual.get("end"))
    if title:
        actual_text = actual.get("title_text")
        if actual.get("media_path"):
            raise TargetMismatch("target_title", **identity, reason="media_backed_title", media_type="media_clip", media_path=actual.get("media_path"), expected_text=expected["text"], actual_text=actual_text)
        if require_title_text and actual_text != expected["text"]:
            reason = "resolve_title_readback_unavailable" if actual_text is None else "incorrect_title_to_caption_mapping" if actual_text in (expected_title_texts or set()) else "genuine_content_mismatch"
            raise TargetMismatch("target_title", **identity, reason=reason, media_type="title_generator", media_path="", expected_text=expected["text"], actual_text=actual_text, actual_name=actual.get("name"), expected_start=expected["timeline_start"], actual_start=actual["start"] - base, expected_duration=expected["duration"], actual_duration=actual["duration"])
    else:
        if actual.get("left_offset") != expected["source_start"] or media is None or not _same_path(actual.get("media_path"), media):
            raise TargetMismatch("target_media", **identity, expected_source_start=expected["source_start"], actual_source_start=actual.get("left_offset"), expected_media=str(media) if media else None, actual_media=actual.get("media_path"))


def validate_target(timeline: Any, contract: Mapping[str, Any], require_title_text: bool = True) -> dict[str, Any]:
    snapshot = timeline_snapshot(timeline)
    if snapshot["name"] != contract["timeline_name"]:
        raise ValueError("target_name")
    fps_values = [value for value in snapshot["settings"].values() if value not in (None, "")]
    if not fps_values or any(abs(float(value) - contract["fps"]) > 1e-6 for value in fps_values):
        raise ValueError("target_timebase")
    base = snapshot["start_frame"]
    owned_items = [
        row for row in snapshot["items"]
        if row["track_type"] == "video" and (
            str(row.get("name") or "").startswith("VC_FLASH_")
            or str(row.get("name") or "").startswith("_VC_DNA_ANIM_")
            or str(row.get("nested_timeline_name") or "").startswith("_VC_DNA_ANIM_")
            or (row["track_index"] == 1 and row.get("media_path") == "" and row.get("name") == "Blur Dissolve")
        )
    ]
    validation_items = [row for row in snapshot["items"] if row not in owned_items]
    by_track = {(kind, track): sorted([row for row in validation_items if row["track_type"] == kind and row["track_index"] == track], key=lambda row: row["start"] if row["start"] is not None else -1) for kind in ("video", "audio") for track in range(1, (snapshot[f"{kind}_track_count"] or 0) + 1)}
    cuts = by_track.get(("video", 1), [])
    flash_handoffs = contract.get("flash_handoffs") or []
    overlay_rows = list(contract["titles"]) + list(flash_handoffs)
    expected_title_texts = {row["text"] for row in overlay_rows}
    overlay_lanes = sorted({row["lane"] for row in overlay_rows})
    title_tracks = {lane + 1 for lane in overlay_lanes}
    titles = [row for track in sorted(title_tracks) for row in by_track.get(("video", track), [])]
    audio_rows = by_track.get(("audio", 1), [])
    for track in title_tracks:
        rows = by_track.get(("video", track), [])
        if any(current["start"] is None or previous["start"] is None or previous["duration"] is None or current["start"] < previous["start"] + previous["duration"] for previous, current in zip(rows, rows[1:])):
            raise ValueError("target_same_lane_overlap")
    if len(cuts) != len(contract["cuts"]) or len(titles) != len(overlay_rows) or len(audio_rows) != len(contract["audio_rows"]):
        raise TargetMismatch(
            "target_track_counts",
            reason="structure_mismatch_or_older_fcpxml",
            timeline_name=snapshot["name"],
            timeline_unique_id=snapshot["unique_id"],
            expected_video_clips=len(contract["cuts"]),
            actual_video_clips=len(cuts),
            expected_titles=len(overlay_rows),
            actual_titles=len(titles),
            expected_audio_clips=len(contract["audio_rows"]),
            actual_audio_clips=len(audio_rows),
        )
    allowed_tracks = {("video", 1), ("audio", 1)} | {("video", track) for track in title_tracks}
    if any(rows for key, rows in by_track.items() if key not in allowed_tracks):
        raise ValueError("target_extra_tracks")
    for actual, expected in zip(cuts, contract["cuts"]):
        _validate_item(actual, expected, base, contract["proxy"])
    for actual, expected in zip(audio_rows, contract["audio_rows"]):
        _validate_item(actual, expected, base, contract["audio"])
    for lane in overlay_lanes:
        actual_titles = by_track.get(("video", lane + 1), [])
        expected_titles = sorted((row for row in overlay_rows if row["lane"] == lane), key=lambda row: row["timeline_start"])
        if len(actual_titles) != len(expected_titles):
            raise ValueError("target_title_lanes")
        for actual, expected in zip(actual_titles, expected_titles):
            try:
                _validate_item(actual, expected, base, None, title=True, require_title_text=require_title_text, expected_title_texts=expected_title_texts)
            except TargetMismatch as exc:
                exc.details["timeline_name"] = snapshot["name"]
                exc.details["timeline_unique_id"] = snapshot["unique_id"]
                exc.args = (f"{exc.code}: {json.dumps(exc.details, ensure_ascii=False, sort_keys=True)}",)
                raise
    end = max((row["start"] - base + row["duration"] for row in cuts), default=0)
    if end != contract["duration_frames"]:
        raise ValueError("target_duration")
    return {"ok": True, "v1_clip_count": len(cuts), "a1_clip_count": len(audio_rows), "v2_title_count": len(contract["titles"]), "v2_title_lanes": contract["title_lanes"], "flash_handoff_count": len(flash_handoffs), "owned_application_item_count": len(owned_items), "duration_frames": end, "snapshot": snapshot}


def _content_addressed_target_name(target_name: str, artifact_set_sha256: str) -> str:
    return f"{target_name}__VC_{artifact_set_sha256[:12]}"


def _timeline_contract(contract: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = dict(contract)
    value["timeline_name"] = name
    return value


def _validate_authoritative_import(timeline: Any, contract: Mapping[str, Any], allow_unobservable_text: bool) -> dict[str, Any]:
    try:
        result = validate_target(timeline, contract)
        result["caption_text_authority"] = "DIRECT_RESOLVE_TEXT_READBACK"
        return result
    except TargetMismatch as exc:
        if not allow_unobservable_text or exc.code != "target_title" or exc.details.get("reason") != "resolve_title_readback_unavailable":
            raise
    result = validate_target(timeline, contract, require_title_text=False)
    title_rows = [row for row in result["snapshot"]["items"] if row["track_type"] == "video" and row["track_index"] > 1]
    if any(row.get("title_text") is not None for row in title_rows):
        raise TargetMismatch("target_title", reason="partial_title_readback", timeline_name=result["snapshot"]["name"], timeline_unique_id=result["snapshot"]["unique_id"])
    result["caption_text_authority"] = "CONTENT_ADDRESSED_FCPXML_WITH_STRUCTURAL_READBACK"
    return result


CARRIER_OWNERSHIP = "PREEXISTING_SHARED_NOT_OWNED"


def _unique_id(value: Any) -> str:
    return str(_safe(value, "GetUniqueId", default="") or "")


def _same_timeline(left: Any, right: Any) -> bool:
    left_id, right_id = _unique_id(left), _unique_id(right)
    return bool(left_id and left_id == right_id) or (not left_id and not right_id and left is right)


def _tool_regid(tool: Any) -> str:
    attrs = _safe(tool, "GetAttrs", default={})
    return str(attrs.get("TOOLS_RegID") or "") if isinstance(attrs, Mapping) else ""


def _media_pool_matches(pool: Any, carrier: Any) -> list[Any]:
    root = _safe(pool, "GetRootFolder")
    if root is None:
        return []
    wanted = _unique_id(carrier)
    matches: list[Any] = []

    def visit(folder: Any) -> None:
        for item in _folder_values(_safe(folder, "GetClipList", default=[])):
            if item is carrier or (wanted and _unique_id(item) == wanted):
                matches.append(item)
        for child in _folder_values(_safe(folder, "GetSubFolderList", default=[])):
            visit(child)

    visit(root)
    return matches


def carrier_textplus_operation_plan(titles: list[Mapping[str, Any]], timeline_start: int = 0) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    caption_ids: set[str] = set()
    for title in titles:
        caption_id = str(title.get("caption_id") or "")
        text = title.get("text")
        start = _as_int(title.get("timeline_start"))
        duration = _as_int(title.get("duration"))
        lane = _as_int(title.get("lane"))
        if not caption_id or caption_id in caption_ids or not isinstance(text, str) or text == "" or start is None or start < 0 or duration is None or duration <= 0 or lane is None or lane <= 0:
            raise ValueError("carrier_title_authority")
        caption_ids.add(caption_id)
        rows.append({
            "caption_id": caption_id,
            "text": text,
            "lane": lane,
            "track_index": lane + 1,
            "record_frame": timeline_start + start,
            "duration": duration,
            "end_frame": timeline_start + start + duration,
        })
    rows.sort(key=lambda row: (row["record_frame"], row["lane"], row["caption_id"]))
    lanes = sorted({row["lane"] for row in rows})
    if not rows or lanes != list(range(1, lanes[-1] + 1)):
        raise ValueError("carrier_title_lanes")
    for lane in lanes:
        lane_rows = [row for row in rows if row["lane"] == lane]
        if any(current["record_frame"] < previous["end_frame"] for previous, current in zip(lane_rows, lane_rows[1:])):
            raise ValueError("carrier_same_lane_overlap")
    return {"titles": rows, "lanes": lanes, "sha256": _fingerprint(rows)}


def apply_carrier_textplus_v2(
    project: Any,
    timeline: Any,
    titles: list[Mapping[str, Any]],
    carrier: Any,
    carrier_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Create only V2 as carrier-backed TextPlus after the V1/A1 boundary."""
    result: dict[str, Any] = {
        "ok": False,
        "classification": "CARRIER_TEXTPLUS_V2_BLOCKED",
        "created_count": 0,
        "rows": [],
        "failures": [],
        "mutation_counts": {"carrier_appends": 0, "fusion_comps": 0, "textplus_tools": 0, "styled_text_writes": 0, "media_imports": 0, "saves": 0, "deletes": 0, "relinks": 0, "replaces": 0},
    }
    current_before = _safe(project, "GetCurrentTimeline")
    changed_current = False
    protected_before = media_before = None
    try:
        pool = _safe(project, "GetMediaPool")
        if pool is None or timeline is None or carrier is None:
            raise ValueError("carrier_context")
        carrier_id = _unique_id(carrier)
        if (
            carrier_contract.get("ownership") != CARRIER_OWNERSHIP
            or carrier_contract.get("preexisting") is not True
            or carrier_contract.get("deletion_permitted") is not False
            or not carrier_id
            or carrier_contract.get("unique_id") != carrier_id
            or len(_media_pool_matches(pool, carrier)) != 1
        ):
            raise ValueError("carrier_ownership")
        source_start = _as_int(carrier_contract.get("source_start"))
        if source_start is None or source_start < 0:
            raise ValueError("carrier_source_range")

        all_timelines = _timelines(project)
        if not any(_same_timeline(row, timeline) for row in all_timelines):
            raise ValueError("carrier_target_timeline")
        protected_before = [timeline_snapshot(row) for row in all_timelines if not _same_timeline(row, timeline)]
        media_before = _media_pool_inventory(pool)
        timeline_start = _as_int(_safe(timeline, "GetStartFrame", default=0)) or 0
        plan = carrier_textplus_operation_plan(titles, timeline_start)
        result["operation_plan"] = plan
        required_tracks = {row["track_index"] for row in plan["titles"]}
        video_tracks = _as_int(_safe(timeline, "GetTrackCount", "video", default=0)) or 0
        if not required_tracks or max(required_tracks) > video_tracks:
            raise ValueError("carrier_target_tracks")
        if any(_safe(timeline, "GetItemListInTrack", "video", track, default=[]) for track in required_tracks):
            raise ValueError("carrier_target_not_empty")

        if not _same_timeline(current_before, timeline):
            if not _safe(project, "SetCurrentTimeline", timeline, default=False) or not _same_timeline(_safe(project, "GetCurrentTimeline"), timeline):
                raise ValueError("carrier_target_activation")
            changed_current = True

        known_ids = {_unique_id(item) for track in range(1, video_tracks + 1) for item in (_safe(timeline, "GetItemListInTrack", "video", track, default=[]) or []) if _unique_id(item)}
        for spec in plan["titles"]:
            clip_info = {
                "mediaPoolItem": carrier,
                "startFrame": source_start,
                "endFrame": source_start + spec["duration"],
                "mediaType": 1,
                "trackIndex": spec["track_index"],
                "recordFrame": spec["record_frame"],
            }
            _safe(pool, "AppendToTimeline", [clip_info])
            result["mutation_counts"]["carrier_appends"] += 1
            detected = [(track, item) for track in range(1, video_tracks + 1) for item in (_safe(timeline, "GetItemListInTrack", "video", track, default=[]) or []) if _unique_id(item) and _unique_id(item) not in known_ids]
            if len(detected) != 1:
                raise ValueError("carrier_item_identity")
            track, item = detected[0]
            item_id = _unique_id(item)
            known_ids.add(item_id)
            actual = {
                "track_index": track,
                "record_frame": _as_int(_safe(item, "GetStart")),
                "end_frame": _as_int(_safe(item, "GetEnd")),
                "duration": _as_int(_safe(item, "GetDuration")),
            }
            if actual != {key: spec[key] for key in actual}:
                raise ValueError("carrier_item_geometry")
            if (_as_int(_safe(item, "GetFusionCompCount", default=0)) or 0) != 0:
                raise ValueError("carrier_existing_fusion")
            comp = _safe(item, "AddFusionComp")
            result["mutation_counts"]["fusion_comps"] += 1
            if comp is None or (_as_int(_safe(item, "GetFusionCompCount", default=0)) or 0) != 1:
                raise ValueError("carrier_fusion_comp")
            tools = _safe(comp, "GetToolList", default={})
            media_out = next((tool for tool in tools.values() if _tool_regid(tool) == "MediaOut"), None) if isinstance(tools, Mapping) else None
            if media_out is None:
                raise ValueError("carrier_media_out")
            textplus = _safe(comp, "AddTool", "TextPlus", -32768, -32768)
            result["mutation_counts"]["textplus_tools"] += 1
            if textplus is None or _tool_regid(textplus) != "TextPlus":
                raise ValueError("carrier_textplus")
            if not _safe(media_out, "ConnectInput", "Input", _safe(textplus, "FindMainOutput", 1), default=False):
                raise ValueError("carrier_textplus_connection")
            set_return = _safe(textplus, "SetInput", "StyledText", spec["text"])
            result["mutation_counts"]["styled_text_writes"] += 1
            text_readback = _safe(textplus, "GetInput", "StyledText")
            if text_readback is None or str(text_readback) != spec["text"]:
                raise ValueError("carrier_styled_text")
            result["rows"].append({**spec, **actual, "item_unique_id": item_id, "textplus_regid": _tool_regid(textplus), "styled_text": str(text_readback), "set_input_return": set_return, "carrier_unique_id": carrier_id})
            result["created_count"] += 1

        result["ok"] = True
        result["classification"] = "CARRIER_TEXTPLUS_V2_APPLIED"
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
    finally:
        if changed_current and (not _safe(project, "SetCurrentTimeline", current_before, default=False) or not _same_timeline(_safe(project, "GetCurrentTimeline"), current_before)):
            result["ok"] = False
            result["failures"].append("ValueError: current_timeline_restore")
        result["current_timeline_restored"] = _same_timeline(_safe(project, "GetCurrentTimeline"), current_before)
        if protected_before is not None:
            result["protected_state_unchanged"] = protected_before == [timeline_snapshot(row) for row in _timelines(project) if not _same_timeline(row, timeline)]
            result["media_inventory_unchanged"] = media_before == _media_pool_inventory(_safe(project, "GetMediaPool"))
            if not result["current_timeline_restored"] or not result["protected_state_unchanged"] or not result["media_inventory_unchanged"]:
                result["ok"] = False
                result["failures"].append("ValueError: carrier_protected_state")
        result["carrier_ownership"] = {"classification": carrier_contract.get("ownership"), "unique_id": _unique_id(carrier), "deletion_ownership_claimed": False}
    return result


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    last_verified_step = "command_received"
    current_layer = "package_validation"
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "classification": None, "selected_node": NODE, "import_call_count": 0, "current_timeline_restore_count": 0, "save_project_count": 0, "delete_call_count": 0, "relink_call_count": 0, "metadata_controller_call_count": 0, "failures": []}
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE:
            raise ValueError("command_identity")
        if payload.get("selected_node") != NODE or payload.get("import_permitted") is not True or payload.get("replace_existing_timeline") is not False or payload.get("save_project") is not True or payload.get("delete_permitted") is not False or payload.get("relink_permitted") is not False or payload.get("metadata_controller_permitted") is not False:
            raise ValueError("mutation_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        contract = load_phase5_contract(root, Path(str(payload.get("manifest_path") or "")))
        last_verified_step = "application_package_validated"
        declared = {
            "artifact_set_sha256": contract["artifact_set_sha256"],
            "textplus_fingerprint": contract["textplus_fingerprint"],
            "fcpxml_sha256": contract["fcpxml_sha256"],
            "report_sha256": contract["report_sha256"],
        }
        if any(payload.get(key) != value for key, value in declared.items()):
            raise ValueError("declared_artifact_identity")
        expected_project = str(payload.get("expected_project") or "").strip()
        target_name = str(payload.get("target_timeline_name") or "").strip()
        if not expected_project or not target_name or target_name != contract["xml"]["timeline_name"]:
            raise ValueError("explicit_target_identity")

        manager = _safe(resolve, "GetProjectManager")
        project = _safe(manager, "GetCurrentProject")
        project_name = str(_safe(project, "GetName", default="") or "") if project is not None else ""
        if project is None or project_name != expected_project:
            raise ValueError(f"project_identity:{project_name}")
        last_verified_step = "resolve_project_identity_validated"
        pool = _safe(project, "GetMediaPool")
        if pool is None:
            raise ValueError("media_pool_missing")
        current_before = _safe(project, "GetCurrentTimeline")
        current_before_identity = timeline_snapshot(current_before) if current_before is not None else None
        timelines_before = _timeline_inventory(project)
        media_before = _media_pool_inventory(pool)
        matches = [row for row in _timelines(project) if str(_safe(row, "GetName", default="") or "") == target_name]
        if len(matches) > 1:
            raise ValueError("target_duplicate_collision")
        if matches and payload.get("require_target_absent") is True:
            raise ValueError("target_already_exists")
        current_layer = "cuts_shot_structure_audio"
        occupied_target_mismatch = None
        imported = False
        created_timeline_count = 0
        if matches:
            target = matches[0]
            try:
                target_validation = _validate_authoritative_import(target, contract["xml"], False)
                classification = "EXACT_TEXTPLUS_FULL_TIMELINE_REUSED"
            except Exception as exc:
                occupied_target_mismatch = {
                    "classification": "INCOMPATIBLE_EXISTING_TARGET",
                    "failure": f"{type(exc).__name__}: {exc}",
                    "details": exc.details if isinstance(exc, TargetMismatch) else None,
                    "timeline_name": target_name,
                    "timeline_unique_id": _unique_id(target) or None,
                }
                result["occupied_target_mismatch"] = occupied_target_mismatch
                derivative_name = _content_addressed_target_name(target_name, contract["artifact_set_sha256"])
                derivative_contract = _timeline_contract(contract["xml"], derivative_name)
                derivative_matches = [row for row in _timelines(project) if str(_safe(row, "GetName", default="") or "") == derivative_name]
                if len(derivative_matches) > 1:
                    raise ValueError("derivative_target_duplicate_collision")
                if derivative_matches:
                    target = derivative_matches[0]
                    if not _unique_id(target):
                        raise ValueError("derivative_target_unique_id")
                    target_validation = _validate_authoritative_import(target, derivative_contract, True)
                    classification = "CONTENT_ADDRESSED_TEXTPLUS_FULL_TIMELINE_REUSED"
                else:
                    before_ids = {_unique_id(row) for row in _timelines(project)}
                    returned = _safe(pool, "ImportTimelineFromFile", str(contract["fcpxml"]), {"timelineName": derivative_name}, default=None)
                    result["import_call_count"] = 1
                    derivative_matches = [row for row in _timelines(project) if str(_safe(row, "GetName", default="") or "") == derivative_name]
                    if len(derivative_matches) != 1:
                        raise ValueError(f"import_derivative_identity:{len(derivative_matches)}")
                    target = derivative_matches[0]
                    if not _unique_id(target) or _unique_id(target) in before_ids or (returned not in (None, False, True) and not _same_timeline(returned, target)):
                        raise ValueError("import_returned_identity")
                    target_validation = _validate_authoritative_import(target, derivative_contract, True)
                    classification = "NEW_CONTENT_ADDRESSED_TEXTPLUS_FULL_TIMELINE_IMPORTED"
                    imported = True
                    created_timeline_count += 1
                target_name = derivative_name
        else:
            before_ids = {_unique_id(row) for row in _timelines(project)}
            returned = _safe(pool, "ImportTimelineFromFile", str(contract["fcpxml"]), {"timelineName": target_name}, default=None)
            result["import_call_count"] = 1
            matches = [row for row in _timelines(project) if str(_safe(row, "GetName", default="") or "") == target_name]
            if len(matches) != 1:
                raise ValueError(f"import_target_identity:{len(matches)}")
            target = matches[0]
            if not _unique_id(target) or _unique_id(target) in before_ids or (returned not in (None, False, True) and not _same_timeline(returned, target)):
                raise ValueError("import_returned_identity")
            target_validation = _validate_authoritative_import(target, contract["xml"], True)
            classification = "NEW_TEXTPLUS_FULL_TIMELINE_IMPORTED"
            imported = True
            created_timeline_count += 1

        layer_evidence: dict[str, Any] = {}
        plan = contract.get("application_plan") or {}
        motion_layer = plan.get("motion_vfx") or {}
        animation_layer = plan.get("caption_animations") or {}
        needs_derivative = any(isinstance(row, Mapping) and row.get("disposition") == "apply" for row in (motion_layer, animation_layer))
        if classification == "EXACT_TEXTPLUS_FULL_TIMELINE_REUSED" and needs_derivative:
            derivative_name = _content_addressed_target_name(target_name, contract["artifact_set_sha256"])
            derivative_contract = _timeline_contract(contract["xml"], derivative_name)
            derivative_matches = [row for row in _timelines(project) if str(_safe(row, "GetName", default="") or "") == derivative_name]
            if len(derivative_matches) > 1:
                raise ValueError("application_derivative_duplicate_collision")
            if derivative_matches:
                target = derivative_matches[0]
                target_validation = _validate_authoritative_import(target, derivative_contract, True)
                classification = "CONTENT_ADDRESSED_DNA_TIMELINE_REUSED"
            else:
                before_ids = {_unique_id(row) for row in _timelines(project)}
                target = _safe(target, "DuplicateTimeline", derivative_name)
                if target is None or not _unique_id(target) or _unique_id(target) in before_ids:
                    raise ValueError("application_derivative_create")
                target_validation = _validate_authoritative_import(target, derivative_contract, True)
                classification = "NEW_CONTENT_ADDRESSED_DNA_TIMELINE_CREATED"
                imported = True
                created_timeline_count += 1
            target_name = derivative_name

        current_layer = "native_transitions"
        report_dir = root / str(command.get("report_path") or "").replace("/report.json", "")
        target, target_name, blur_result, blur_created = apply_native_blur_transitions(resolve, project, pool, target, target_name, contract, report_dir)
        if blur_created:
            created_timeline_count += 1
            result["import_call_count"] += 1
            result["delete_call_count"] += 1  # The run-owned export duplicate only; no pre-existing timeline is deleted.
        if blur_result.get("applied_count"):
            layer_evidence["native_transitions"] = blur_result
        target_validation = _validate_authoritative_import(target, _timeline_contract(contract["xml"], target_name), True)

        current_layer = "caption_animations"
        animation_result = apply_caption_animations(resolve, project, pool, target, contract)
        created_timeline_count += int(animation_result.get("created_timeline_count") or 0)
        if animation_result.get("applied_count"):
            layer_evidence["caption_animations"] = animation_result

        current_layer = "motion_vfx"
        motion_result = apply_motion_vfx(target, contract)
        if motion_result.get("applied_count"):
            layer_evidence["motion_vfx"] = motion_result
        current_layer = "native_transitions"
        flash_result = apply_flash_transitions(pool, target, contract)
        if flash_result.get("applied_count"):
            native_evidence = layer_evidence.get("native_transitions") or {"applied_count": 0}
            layer_evidence["native_transitions"] = {
                "status": "applied" if native_evidence.get("applied_count", 0) + flash_result.get("applied_count", 0) == ((contract.get("application_plan") or {}).get("native_transitions") or {}).get("accepted_recipe_count") else "partial",
                "applied_count": native_evidence.get("applied_count", 0) + flash_result.get("applied_count", 0),
                "native_blur": native_evidence,
                "flash": flash_result,
            }
        target_validation = _validate_authoritative_import(target, _timeline_contract(contract["xml"], target_name), True)
        last_verified_step = "editable_timeline_structure_and_captions_verified"
        current_layer = "protected_timeline_verification"

        current_after_import = _safe(project, "GetCurrentTimeline")
        if current_before is not None and not _same_timeline(current_after_import, current_before):
            if not bool(_safe(project, "SetCurrentTimeline", current_before, default=False)) and not _same_timeline(_safe(project, "GetCurrentTimeline"), current_before):
                raise ValueError("current_timeline_restore")
            result["current_timeline_restore_count"] = 1
        current_after = _safe(project, "GetCurrentTimeline")
        if current_before is not None and not _same_timeline(current_after, current_before):
            raise ValueError("current_timeline_changed")

        timelines_after = _timeline_inventory(project)
        target_uid = _unique_id(target)
        after_by_uid = {row["unique_id"]: row for row in timelines_after}
        protected_changed = any(
            row["unique_id"] != target_uid
            and (row["unique_id"] not in after_by_uid or after_by_uid[row["unique_id"]]["name"] != row["name"] or after_by_uid[row["unique_id"]]["signature"] != row["signature"])
            for row in timelines_before
        )
        expected_delta = created_timeline_count
        if len(timelines_after) - len(timelines_before) != expected_delta or sum(row["name"] == target_name for row in timelines_after) != 1 or protected_changed:
            raise ValueError("protected_timeline_changed")
        media_after = _media_pool_inventory(pool)
        media_key = lambda row: row["signature"]
        before_counter = Counter(map(media_key, media_before))
        after_counter = Counter(map(media_key, media_after))
        if before_counter - after_counter:
            raise ValueError("preexisting_media_changed")
        additions = list((after_counter - before_counter).elements())
        last_verified_step = "protected_original_timelines_verified_unchanged"
        current_layer = "project_save"
        saved = _safe(manager, "SaveProject", default=False)
        result.update({"save_project_count": 1, "save_project_return": saved})
        if saved is not True:
            raise ValueError("save_project")
        last_verified_step = "project_saved"
        current_layer = "complete"
        result.update({
            "ok": True,
            "classification": classification,
            "project_name": project_name,
            "target_timeline_name": target_name,
            "requested_target_timeline_name": str(payload.get("target_timeline_name") or "").strip(),
            "occupied_target_mismatch": occupied_target_mismatch,
            "manifest_path": str(contract["manifest_path"]),
            **declared,
            "target": target_validation,
            "current_timeline_before": current_before_identity,
            "current_timeline_after": timeline_snapshot(current_after) if current_after is not None else None,
            "timeline_inventory_before": timelines_before,
            "timeline_inventory_after": timelines_after,
            "protected_timelines_unchanged": True,
            "media_pool_before": media_before,
            "media_pool_after": media_after,
            "media_pool_delta": {"added_signatures": additions, "removed_signatures": [], "deletion_ownership_claimed": False},
            "layers": verified_layer_report(contract.get("application_plan") or {}, target_validation, layer_evidence),
            "available_assets": contract.get("available_assets") or {},
            "limitations": contract.get("limitations") or {},
            "editing_dna_path": str(contract["editing_dna"]) if contract.get("editing_dna") else None,
            "last_verified_step": last_verified_step,
            "failed_layer": None,
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
        if isinstance(exc, TargetMismatch):
            result["target_mismatch"] = {"code": exc.code, **exc.details}
        result["last_verified_step"] = last_verified_step
        result["failed_layer"] = current_layer
    return result
