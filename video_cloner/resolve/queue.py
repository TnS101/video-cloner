from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resolve_workspace.modules.video_cloner_phase6_textplus_application import (
    MODE,
    NODE,
    NODE_CONTRACT,
    TASK_ID,
    _fingerprint,
    load_phase5_contract,
    parse_textplus_fcpxml,
)


MODULE = "resolve_workspace/modules/video_cloner_phase6_textplus_application.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label}_object")
    return value


def inside(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}_outside_repository") from exc
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ValueError(f"{label}_missing")
    return resolved


def identity(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def _caption_ordinal(value: object) -> int | None:
    match = re.search(r"(\d+)$", str(value or ""))
    return int(match.group(1)) if match else None


def compile_caption_animation_recipes(
    style: Mapping[str, Any], captions: Sequence[Mapping[str, Any]], fps: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Translate unambiguous source-observed motion into the accepted generic recipe contract."""
    targets = {
        _caption_ordinal(row.get("subtitle_id")): (index, row)
        for index, row in enumerate(captions, start=1)
        if str(row.get("subtitle_id") or "").lower().startswith("sub_")
    }
    identity_targets = {
        str(row["visual_event_identity"]): (index, row)
        for index, row in enumerate(captions, start=1)
        if row.get("visual_event_identity")
    }
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for event in style.get("style_events") or []:
        if not isinstance(event, Mapping) or event.get("role") != "spoken_caption":
            continue
        ordinal = _caption_ordinal((event.get("semantic_reference") or {}).get("cue_id"))
        if ordinal is not None:
            grouped.setdefault(ordinal, []).append(event)

    recipes: list[dict[str, Any]] = []
    unresolved = {"ambiguous_title_mapping": 0, "missing_target_title": 0, "insufficient_in_target_samples": 0, "unsupported_channel": 0, "source_visibility_conflict": 0}
    for ordinal, events in sorted(grouped.items()):
        detected = [event for event in events if (event.get("animation") or {}).get("detected") is True]
        if not detected:
            continue
        if len(events) != 1:
            unresolved["ambiguous_title_mapping"] += len(detected)
            continue
        event = detected[0]
        visual_identity = str(event.get("visual_event_identity") or "")
        # A source-linked animation may never silently retarget another
        # semantic caption when its visual identity is no longer emitted.
        target = identity_targets.get(visual_identity) if visual_identity else targets.get(ordinal)
        if target is None:
            unresolved["missing_target_title"] += 1
            continue
        title_index, caption = target
        # An animation is a permitted presentation of a visual identity, never
        # authority to extend its source-backed visibility. Keep the recipe in
        # the intelligence input, but use the unchanged static title in Resolve.
        if caption.get("animation_application_skip_reason"):
            unresolved["source_visibility_conflict"] += 1
            continue
        animation = event.get("animation") or {}
        duration = int(caption["timeline_end_frame"]) - int(caption["timeline_start_frame"])
        measured: dict[int, Mapping[str, Any]] = {}
        out_of_window = False
        for key in animation.get("keyframes") or []:
            if not isinstance(key, Mapping) or key.get("timestamp") is None:
                continue
            frame = int(round(float(key["timestamp"]) * fps)) - int(caption["timeline_start_frame"])
            if 0 <= frame < duration:
                measured[frame] = key
            else:
                out_of_window = True
        if out_of_window:
            # Do not build a partial motion from incompatible keyframes.
            unresolved["source_visibility_conflict"] += 1
            continue
        if len(measured) < 2:
            unresolved["insufficient_in_target_samples"] += 1
            continue
        ordered = sorted(measured.items())
        animation_type = str(animation.get("type") or "")
        channels: dict[str, list[dict[str, Any]]] = {}
        if "slide" in animation_type:
            reference = ordered[-1][1].get("position") or {}
            if reference.get("x") is not None and reference.get("y") is not None:
                channels["position"] = [
                    {"frame": frame, "interpolation": "linear", "value": [
                        round(float((key.get("position") or {})["x"]) - float(reference["x"]), 6),
                        round(float((key.get("position") or {})["y"]) - float(reference["y"]), 6),
                    ]}
                    for frame, key in ordered
                    if (key.get("position") or {}).get("x") is not None and (key.get("position") or {}).get("y") is not None
                ]
        if "scale" in animation_type or "pop" in animation_type:
            channels["scale"] = [
                {"frame": frame, "interpolation": "linear", "value": [float(key["scale"]), float(key["scale"])]}
                for frame, key in ordered if key.get("scale") is not None and float(key["scale"]) > 0
            ]
        channels = {name: keys for name, keys in channels.items() if len(keys) >= 2}
        if not channels:
            unresolved["unsupported_channel"] += 1
            continue
        for name, keys in channels.items():
            if keys[0]["frame"] > 0:
                keys.insert(0, {"frame": 0, "interpolation": "hold", "value": [0.0, 0.0] if name == "position" else [1.0, 1.0]})
        recipes.append({
            "schema": "video_cloner.caption_animation_recipe", "schema_version": 1,
            "caption_id": str(caption["subtitle_id"]), "title_index": title_index,
            "text": str(caption["text"]), "start_frame": int(caption["timeline_start_frame"]),
            "duration": duration, "lane": int(caption["lane"]),
            "channels": channels, "confidence": animation.get("confidence"),
            "provenance": {
                "route": "caption_style_adjacent_source_observations", "component": "opencv",
                "localization_event_id": str(event.get("event_id") or ""),
                "visual_event_identity": str(event.get("visual_event_identity") or ""),
                "sample_timestamps": [key.get("timestamp") for _, key in ordered],
                "animation_classification_used": True,
            },
        })
    return recipes, {name: count for name, count in unresolved.items() if count}


def application_plan(
    dna: Mapping[str, Any], compiler_report: Mapping[str, Any], xml: Mapping[str, Any],
    style: Mapping[str, Any] | None = None, caption_contract: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    captions = dna.get("captions") if isinstance(dna.get("captions"), Mapping) else {}
    compositions = captions.get("compositions") if isinstance(captions.get("compositions"), Mapping) else {}
    animations = [
        member.get("accepted_animation")
        for composition in compositions.get("compositions") or []
        if isinstance(composition, Mapping)
        for member in composition.get("members") or []
        if isinstance(member, Mapping) and isinstance(member.get("accepted_animation"), Mapping)
    ]
    linked_animations = [row for row in animations if row.get("status") == "linked"]
    fps = float(
        (compiler_report.get("timing") or {}).get("fps")
        or (compiler_report.get("output") or {}).get("fps")
        or 24.0
    )
    animation_recipes, animation_unresolved = compile_caption_animation_recipes(style or {}, caption_contract, fps)
    transitions = dna.get("transitions") if isinstance(dna.get("transitions"), Mapping) else {}
    transition_rows = transitions.get("transitions") if isinstance(transitions.get("transitions"), list) else []
    occlusion = dna.get("occlusion_and_masks") if isinstance(dna.get("occlusion_and_masks"), Mapping) else {}
    occlusion_rows = occlusion.get("occlusion_events") if isinstance(occlusion.get("occlusion_events"), list) else []
    motion = dna.get("motion_vfx") if isinstance(dna.get("motion_vfx"), Mapping) else {}
    motion_rows = motion.get("segments") if isinstance(motion.get("segments"), list) else []
    native_transition_recipes = [
        {
            "type": "Blur Dissolve", "cut_frame": int(row["timeline_cut_frame"]),
            "duration_frames": int(row["duration_frames"]),
        }
        for row in transition_rows
        if isinstance(row, Mapping) and row.get("editor_actionable") is True
        and row.get("transition_type") == "blur_transition" and int(row.get("duration_frames") or 0) > 0
    ]
    flash_recipes = [
        {
            "type": "flash_cut", "cut_frame": int(row["timeline_cut_frame"]),
            "duration_frames": int(row["duration_frames"]),
            "outgoing_frames": int(row["outgoing_frames"]), "incoming_frames": int(row["incoming_frames"]),
        }
        for row in transition_rows
        if isinstance(row, Mapping) and row.get("editor_actionable") is True
        and row.get("transition_type") == "flash_cut" and int(row.get("duration_frames") or 0) > 0
    ]
    motion_recipes = []
    for row in motion_rows:
        contract = row.get("editor_contract") if isinstance(row, Mapping) and isinstance(row.get("editor_contract"), Mapping) else {}
        controller = contract.get("resolve_controller") if isinstance(contract.get("resolve_controller"), Mapping) else {}
        zoom = row.get("motion_based_zoom") if isinstance(row, Mapping) and isinstance(row.get("motion_based_zoom"), Mapping) else {}
        keys = zoom.get("keyframes") if isinstance(zoom.get("keyframes"), list) else []
        if controller.get("animated_zoom_ready") is True and contract.get("recommended_operations") == ["transform_zoom"] and keys:
            motion_recipes.append({
                "shot": int(row["shot_id"]), "operation": "transform_zoom", "confidence": row.get("confidence"),
                "scale": [[int(key["relative_frame"]), float(key["scale"])] for key in keys],
            })
    editor_ready_masks = [
        row for row in occlusion_rows if isinstance(row, Mapping)
        and isinstance(row.get("occlusion"), Mapping)
        and row["occlusion"].get("ready_for_editor_compositing") is True
        and isinstance(row.get("mask_asset"), Mapping)
    ]
    if compiler_report.get("schema") == "video_cloner.standalone_fcpxml.v1":
        caption_authority = compiler_report.get("caption_authority") if isinstance(compiler_report.get("caption_authority"), Mapping) else {}
        lifecycle = caption_authority.get("lifecycle") if isinstance(caption_authority.get("lifecycle"), Mapping) else {}
        metrics = caption_authority.get("metrics") if isinstance(caption_authority.get("metrics"), Mapping) else {}
        matched_styles = int(caption_authority.get("style_event_matches") or 0)
        fallback_styles = max(0, len(xml["titles"]) - matched_styles)
        position_mode = "source_visual_composition" if metrics.get("composition_count") else None
        style_geometry_ready = matched_styles > 0 and position_mode is not None
    else:
        style_report = compiler_report.get("style") if isinstance(compiler_report.get("style"), Mapping) else {}
        style_events = style_report.get("per_cue_style_events") if isinstance(style_report.get("per_cue_style_events"), Mapping) else {}
        lifecycle = compiler_report.get("caption_lifecycle") if isinstance(compiler_report.get("caption_lifecycle"), Mapping) else {}
        fcpxml_report = compiler_report.get("fcpxml") if isinstance(compiler_report.get("fcpxml"), Mapping) else {}
        matched_styles = int(style_events.get("matched_cue_count") or 0)
        fallback_styles = int(style_events.get("fallback_cue_count") or 0)
        position_mode = fcpxml_report.get("position_mode")
        style_geometry_ready = matched_styles > 0 and position_mode == "detected_fcpx"
    return {
        "cuts_shot_structure_audio": {"disposition": "apply", "video_clip_count": len(xml["cuts"]), "audio_clip_count": len(xml["audio_rows"])},
        "caption_timing_lifecycle": {
            "disposition": "apply" if lifecycle.get("enabled") is True else "unresolved",
            "caption_count": len(xml["titles"]),
            "reason": None if lifecycle.get("enabled") is True else "visual lifecycle authority is incomplete; transcript timing is preserved",
        },
        "caption_font_style_geometry": {
            "disposition": "apply" if style_geometry_ready else "unresolved",
            "matched_style_event_count": matched_styles,
            "fallback_style_count": fallback_styles,
            "position_mode": position_mode,
            "font_authority": "candidate_or_fallback; exact Resolve font authority is absent",
            "reason": None if style_geometry_ready else "verified per-cue style and detected geometry are both required",
        },
        "caption_animations": {
            "disposition": "apply" if animation_recipes else ("unresolved" if animations else "not_applicable"),
            "source_associated_link_count": len(animations),
            "previously_linked_recipe_count": len(linked_animations),
            "accepted_recipe_count": len(animation_recipes),
            "recipes": animation_recipes,
            "unresolved": animation_unresolved,
            "reason": None if animation_recipes else "no unambiguous source-observed animation maps to an emitted title",
        },
        "native_transitions": {
            "disposition": "apply" if native_transition_recipes or flash_recipes else ("unresolved" if transition_rows else "not_applicable"),
            "source_transition_count": len(transition_rows),
            "accepted_recipe_count": len(native_transition_recipes) + len(flash_recipes),
            "native_blur_recipes": native_transition_recipes,
            "flash_recipes": flash_recipes,
            "reason": None if native_transition_recipes or flash_recipes else ("no source-backed transition is safely executable" if transition_rows else None),
        },
        "occlusion_compositing": {
            "disposition": "unresolved" if occlusion_rows else "not_applicable",
            "source_event_count": len(occlusion_rows),
            "editor_ready_mask_count": len(editor_ready_masks),
            "reason": "grayscale masks exist, but source-colored foreground plates required by the proven compositor are absent" if occlusion_rows else None,
        },
        "motion_vfx": {
            "disposition": "apply" if motion_recipes else ("unresolved" if motion_rows else "not_applicable"),
            "source_segment_count": len(motion_rows),
            "accepted_recipe_count": len(motion_recipes),
            "recipes": motion_recipes,
            "reason": None if motion_recipes else ("no motion segment has an executable Resolve controller contract" if motion_rows else None),
        },
        "speed_ramps": {"disposition": "unsupported", "reason": "OSS-005 is frozen; retiming authority is non-actionable"},
    }


def allocate_run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def build_package(
    root: Path,
    generic: Path,
    proxy: Path,
    style: Path,
    audio: Path,
    fcpxml: Path,
    compiler_report_path: Path,
    target: str,
    editing_dna: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    root = root.resolve()
    generic, proxy, style, audio, fcpxml, compiler_report_path = (
        inside(root, path, label)
        for path, label in (
            (generic, "generic"), (proxy, "proxy"), (style, "caption_style"),
            (audio, "audio"), (fcpxml, "fcpxml"), (compiler_report_path, "compiler_report"),
        )
    )
    generic_value = read_json(generic, "generic")
    style_value = read_json(style, "caption_style")
    compiler_report = read_json(compiler_report_path, "compiler_report")
    dna_path = inside(root, editing_dna, "editing_dna") if editing_dna else None
    dna = read_json(dna_path, "editing_dna") if dna_path else None
    if generic_value.get("success") is not True or generic_value.get("schema") != "generic_edit_commands":
        raise ValueError("generic_contract")
    if dna is not None and (dna.get("schema") != "video_cloner.editing_dna" or dna.get("video_id") != generic_value.get("video_id")):
        raise ValueError("editing_dna_contract")
    compiler_schema = compiler_report.get("schema")
    if compiler_report.get("success") is not True or compiler_schema not in {
        "video_cloner_davinci_textplus_fcpxml", "video_cloner.standalone_fcpxml.v1",
    }:
        raise ValueError("compiler_report_contract")
    xml = parse_textplus_fcpxml(fcpxml, proxy, audio)
    if xml["timeline_name"] != target:
        raise ValueError("target_timeline_contract")
    subtitles = generic_value.get("subtitle_clips")
    if not isinstance(subtitles, list):
        raise ValueError("caption_count")
    caption_contract = []
    if compiler_schema == "video_cloner.standalone_fcpxml.v1":
        report_inputs = compiler_report.get("inputs")
        report_output = compiler_report.get("output")
        authority = compiler_report.get("caption_authority")
        metrics = authority.get("metrics") if isinstance(authority, Mapping) else None
        semantic = authority.get("semantic") if isinstance(authority, Mapping) else None
        execution = authority.get("execution") if isinstance(authority, Mapping) else None
        summary = semantic.get("summary") if isinstance(semantic, Mapping) else None
        structure = compiler_report.get("structure")
        if (
            not isinstance(report_inputs, Mapping) or not isinstance(report_output, Mapping)
            or report_inputs.get("generic_sha256") != sha256(generic)
            or report_inputs.get("caption_style_sha256") != sha256(style)
            or report_inputs.get("source_video_sha256") != sha256(proxy)
            or report_inputs.get("source_audio_sha256") != sha256(audio)
            or report_output.get("sha256") != sha256(fcpxml)
            or report_output.get("timeline_name") != target
            or not isinstance(metrics, Mapping) or not isinstance(summary, Mapping) or not isinstance(structure, Mapping)
            or not isinstance(execution, list) or len(execution) != len(xml["titles"])
            or metrics.get("semantic_ledger_count") != len(subtitles)
            or metrics.get("semantic_ledger_exactly_once") is not True
            or summary.get("source_cue_count") != len(subtitles)
            or summary.get("source_coverage_exact") is not True
            or structure.get("caption_count") != len(xml["titles"])
        ):
            raise ValueError("caption_semantic_authority")
        caption_pairs = []
        for cue, title in zip(execution, xml["titles"]):
            if (
                not isinstance(cue, Mapping) or not cue.get("id")
                or cue.get("text") != title["text"]
                or int(cue.get("start_frame") or -1) != title["timeline_start"]
                or int(cue.get("end_frame") or -1) != title["timeline_start"] + title["duration"]
                or int(cue.get("lane") or 0) != title["lane"]
            ):
                raise ValueError("caption_execution_authority")
            caption_pairs.append((str(cue["id"]), title, cue))
    else:
        caption_pairs = []
        lifecycle = compiler_report.get("caption_lifecycle") if isinstance(compiler_report.get("caption_lifecycle"), Mapping) else {}
        if lifecycle.get("enabled") is True:
            if lifecycle.get("layer_count") != len(xml["titles"]):
                raise ValueError("caption_count")
            for title in xml["titles"]:
                match = re.match(r"^VC Caption (\d{4}) - ", str(title.get("name") or ""))
                index = int(match.group(1)) - 1 if match else -1
                subtitle = subtitles[index] if 0 <= index < len(subtitles) else None
                if not isinstance(subtitle, Mapping) or not subtitle.get("subtitle_id"):
                    raise ValueError("caption_identity")
                caption_pairs.append((str(subtitle["subtitle_id"]), title, {}))
        else:
            if len(subtitles) != len(xml["titles"]):
                raise ValueError("caption_count")
            for subtitle, title in zip(subtitles, xml["titles"]):
                if not isinstance(subtitle, Mapping) or not subtitle.get("subtitle_id") or subtitle.get("text") != title["text"]:
                    raise ValueError("caption_identity")
                caption_pairs.append((str(subtitle["subtitle_id"]), title, {}))
    for caption_id, title, execution_cue in caption_pairs:
        caption_contract.append({
            "subtitle_id": caption_id, "text": title["text"],
            "timeline_start_frame": title["timeline_start"],
            "timeline_end_frame": title["timeline_start"] + title["duration"],
            "lane": title["lane"],
            "semantic_reference_ids": list(execution_cue.get("semantic_reference_ids") or []),
            "visual_event_identity": execution_cue.get("visual_event_identity"),
            "animation_application_skip_reason": execution_cue.get("animation_application_skip_reason"),
        })

    report_path = fcpxml.with_name(fcpxml.stem + "_import_report.json")
    report = {
        "success": True,
        "schema": "video_cloner.standalone_textplus_fcpxml_report.v1",
        "inputs": {
            "generic": identity(generic), "caption_style": identity(style),
            "source_video": identity(proxy), "source_audio": identity(audio),
        },
        "output": identity(fcpxml) | {"fcpxml": str(fcpxml)},
        "structure": {
            "v1_clip_count": len(xml["cuts"]), "a1_clip_count": len(xml["audio_rows"]),
            "v2_title_count": len(xml["titles"]), "timeline_duration_frames": xml["duration_frames"],
            "caption_contract": caption_contract, "caption_lane_count": len(xml["title_lanes"]),
            "max_caption_lane": xml["title_lanes"][-1], "same_lane_overlap_count": 0,
            "overlap_preserved": True,
        },
        "source_compiler_report": identity(compiler_report_path),
    }
    write_json(report_path, report)

    inputs = {"generic": identity(generic), "proxy": identity(proxy), "caption_style": identity(style), "audio": identity(audio)}
    if dna_path is not None:
        inputs["editing_dna"] = identity(dna_path)
    producer = {"adapter": "prepare_video_cloner_fresh_mvp_timeline.v1", "compiler_version": compiler_report.get("version") or compiler_schema}
    node_identity = {"node": NODE, "inputs": inputs, "producer": producer}
    node = {
        "contract": NODE_CONTRACT, "producer": producer, "fingerprint": _fingerprint(node_identity),
        "outputs": {"fcpxml": identity(fcpxml), "report": identity(report_path)},
    }
    manifest = {
        "schema": "video_cloner.standalone_phase5_manifest.v1", "version": 1,
        "video_id": generic_value.get("video_id"),
        "artifact_set_contract": "unified_editing_dna_application_v2" if dna is not None else "offline_fcpxml_only_no_resolve",
        "application_plan": application_plan(dna, compiler_report, xml, style_value, caption_contract) if dna is not None else {},
        "available_assets": {
            "occlusion_masks": ((dna.get("occlusion_and_masks") or {}).get("mask_assets") or {}) if dna is not None else {},
            "caption_animation_recipes": ((dna.get("captions") or {}).get("animation") or {}) if dna is not None else {},
        },
        "limitations": {"baked_reference_effects_preserved": True, "editable_overlays_may_visually_duplicate_baked_effects": True},
        "inputs": inputs, "nodes": {NODE: node},
    }
    manifest["artifact_set_sha256"] = _fingerprint(manifest)
    manifest_path = fcpxml.with_name(fcpxml.stem + "_manifest.json")
    write_json(manifest_path, manifest)
    contract = load_phase5_contract(root, manifest_path)
    return manifest_path, contract


def publish(
    root: Path,
    manifest_path: Path,
    contract: Mapping[str, Any],
    project: str,
    target: str,
    state_root: Path | None = None,
) -> dict[str, Any]:
    if not project or not target:
        raise ValueError("explicit_target_identity")
    state = (state_root or root / ".agent").resolve()
    try:
        state_relative = state.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("state_root_outside_repository") from exc
    queue = state / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    active = [(state, path) for state in ("pending", "running") for path in sorted((queue / state).glob("*.json"))]
    if active:
        raise ValueError(f"active_command:{active[0][0]}:{active[0][1].name}")
    run_id = allocate_run_id()
    if re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", run_id) is None:
        raise ValueError("run_id")
    relative_report = f"{state_relative}/reports/{TASK_ID}/{run_id}"
    report_dir = root / relative_report
    report_dir.mkdir(parents=True, exist_ok=False)
    command = {
        "schema_version": 1, "task": TASK_ID, "run_id": run_id, "module": MODULE, "mode": MODE,
        "status_path": f"{relative_report}/status.json", "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root), "manifest_path": str(manifest_path), "selected_node": NODE,
            "artifact_set_sha256": contract["artifact_set_sha256"], "textplus_fingerprint": contract["textplus_fingerprint"],
            "fcpxml_sha256": contract["fcpxml_sha256"], "report_sha256": contract["report_sha256"],
            "expected_project": project, "target_timeline_name": target, "require_target_absent": False,
            "import_permitted": True, "replace_existing_timeline": False, "save_project": True,
            "delete_permitted": False, "relink_permitted": False, "metadata_controller_permitted": False,
        },
    }
    pending = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(report_dir / "import_command.json", command)
    write_json(pending, command)
    receipt = {
        "ok": True, "task_id": TASK_ID, "run_id": run_id,
        "command_path": str(pending.relative_to(root)).replace("\\", "/"),
        "command_sha256": sha256(pending), "pending_queue_count": len(list((queue / "pending").glob("*.json"))),
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--generic", type=Path, required=True)
    parser.add_argument("--proxy", type=Path, required=True)
    parser.add_argument("--caption-style", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--fcpxml", type=Path, required=True)
    parser.add_argument("--compiler-report", type=Path, required=True)
    parser.add_argument("--editing-dna", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--target-timeline", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        manifest, contract = build_package(root, args.generic, args.proxy, args.caption_style, args.audio, args.fcpxml, args.compiler_report, args.target_timeline, args.editing_dna)
        receipt = publish(root, manifest, contract, args.project, args.target_timeline)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
