"""Assemble canonical editor-neutral analysis authorities without re-detecting media."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected(value: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: value[name] for name in names if name in value}


def build(args: argparse.Namespace) -> dict[str, Any]:
    shots = load(args.shots)
    transcript = load(args.transcript)
    rhythm = load(args.rhythm)
    style = load(args.caption_style)
    lifecycle = load(args.caption_lifecycle)
    fonts = load(args.font_candidates)
    compositions = load(args.caption_compositions)
    motion = load(args.motion)
    transitions = load(args.transitions)
    occlusion = load(args.caption_occlusion)
    if not isinstance(shots, list) or lifecycle.get("ok") is not True or compositions.get("schema") != "video_cloner.caption_compositions":
        raise ValueError("canonical shots, caption lifecycle, and caption compositions are required")

    identities = sorted({
        str(identity)
        for composition in compositions.get("compositions") or []
        for identity in composition.get("visual_member_identities") or []
    })
    sources = {
        name: path
        for name, path in (
            ("source_video", args.source_video),
            ("shots", args.shots),
            ("transcript", args.transcript),
            ("rhythm", args.rhythm),
            ("caption_style", args.caption_style),
            ("caption_lifecycle", args.caption_lifecycle),
            ("font_candidates", args.font_candidates),
            ("caption_compositions", args.caption_compositions),
            ("motion", args.motion),
            ("transitions", args.transitions),
            ("caption_occlusion", args.caption_occlusion),
        )
    }
    return {
        "schema": "video_cloner.editing_dna",
        "schema_version": 1,
        "video_id": args.video_id,
        "source": {
            "path": str(args.source_video),
            "sha256": sha256(args.source_video),
            "video_info": style.get("video_info"),
        },
        "timebases": compositions.get("coordinate_spaces"),
        "shots_and_rhythm": {
            "shots": shots,
            "rhythm": selected(rhythm, ("duration", "bpm", "rhythm_confidence", "beat_source", "bar_position_source", "rhythm_summary", "summary", "beats", "downbeats", "bar_positions", "strong_onsets", "major_energy_peaks")),
        },
        "captions": {
            "transcript": selected(transcript, ("language", "language_probability", "duration", "summary", "captioning", "segments", "words", "subtitle_clips", "text")),
            "style": selected(style, ("analysis_version", "subtitle_style_summary", "summary", "caption_style_resolved", "caption_style_profiles")),
            "font_candidates": selected(fonts, ("analysis_version", "video_info", "inventory", "primary_style_id", "profiles", "global_consensus", "resolve_probe_candidates", "policy", "warnings")),
            "visual_identities": {"count": len(identities), "ids": identities, "detail_location": "captions.compositions.compositions[].members"},
            "compositions": compositions,
            "lifecycle": lifecycle,
            "animation": {"detail_location": "captions.compositions.compositions[].members[].accepted_animation", "link_rule": "direct_unique_localization_event_id_only"},
        },
        "transitions": selected(transitions, ("fps", "frame_count", "video_info", "shot_count", "transition_count", "summary", "transition_summary", "transitions", "quality_flags", "planner_ready")),
        "motion_vfx": selected(motion, ("video_info", "motion_summary", "segments", "zoom_candidates", "errors")),
        "occlusion_and_masks": selected(occlusion, ("video_info", "normalization", "summary", "partial", "occlusion_events", "mask_assets", "warnings", "errors")),
        "retiming": {
            "authority": "MOTION_HEURISTIC_ONLY",
            "actionable": False,
            "reason": "source-backed retiming authority is absent",
            "candidates": motion.get("speed_change_candidates") or [],
        },
        "unresolved": {
            "caption_identity_assignments": compositions.get("unresolved_identity_assignments") or [],
            "retiming": "candidates remain non-actionable until source-backed timing authority exists",
        },
        "provenance": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in sources.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--shots", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--rhythm", type=Path, required=True)
    parser.add_argument("--caption-style", type=Path, required=True)
    parser.add_argument("--caption-lifecycle", type=Path, required=True)
    parser.add_argument("--font-candidates", type=Path, required=True)
    parser.add_argument("--caption-compositions", type=Path, required=True)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--transitions", type=Path, required=True)
    parser.add_argument("--caption-occlusion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output), "schema": payload["schema"], "video_id": args.video_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
