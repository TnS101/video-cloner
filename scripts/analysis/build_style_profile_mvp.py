#!/usr/bin/env python3
"""Compile the accepted Reel #2 editing evidence into the minimal MVP profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median, quantiles
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REEL_ID = "DcJRJtUKScu"
ANALYSIS = ROOT / "data" / REEL_ID / "analysis"
ACCEPTED = ROOT / "data" / REEL_ID / "accepted" / "step6a"
CAMERA = ANALYSIS / f"{REEL_ID}_camera_style_profile.json"
CAPTIONS = ANALYSIS / f"{REEL_ID}_caption_style_grammar.json"
CUTS = ACCEPTED / f"{REEL_ID}_generic_edit_commands.json"
TRANSITIONS = ACCEPTED / f"{REEL_ID}_transitions.json"
PROVENANCE = ACCEPTED / "AUTHORITY_PROVENANCE.json"
GOLD = ROOT / ".agent/gold/video_cloner/reel2/captions/VIDEO_CLONER_REEL2_CAPTIONS_GOLD_HUMAN_ACCEPTED.drt"
DEFAULT_JSON = ANALYSIS / f"{REEL_ID}_style_profile_mvp.json"
DEFAULT_MD = ANALYSIS / f"{REEL_ID}_style_profile_mvp.md"
DEFERRED = ["flash_execution", "generic_vfx", "occlusion", "sfx", "graphics"]


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}


def _validate_accepted_inputs(root: Path, provenance: dict[str, Any], captions: dict[str, Any]) -> None:
    declared = {row["repository_path"]: row["sha256"] for row in provenance["artifacts"]}
    for path in (root / CUTS.relative_to(ROOT), root / TRANSITIONS.relative_to(ROOT)):
        relative = path.relative_to(root).as_posix()
        if declared.get(relative) != _sha256(path):
            raise ValueError(f"Accepted Step 6A artifact hash mismatch: {relative}")
    gold = root / GOLD.relative_to(ROOT)
    if captions["gold_authority"]["sha256"] != _sha256(gold):
        raise ValueError("Frozen Reel #2 caption GOLD hash mismatch")


def _compact_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "from_shot": row["from_shot"],
        "to_shot": row["to_shot"],
        "cut_frame": row["cut_frame"],
        "cut_time_seconds": row["cut_time"],
        "family": row["transition_type"],
        "duration_frames": row["duration_frames"],
        "confidence": row["confidence"],
    }


def build_profile(root: Path = ROOT) -> dict[str, Any]:
    camera_path = root / CAMERA.relative_to(ROOT)
    captions_path = root / CAPTIONS.relative_to(ROOT)
    cuts_path = root / CUTS.relative_to(ROOT)
    transitions_path = root / TRANSITIONS.relative_to(ROOT)
    provenance_path = root / PROVENANCE.relative_to(ROOT)
    camera = _load(camera_path)
    captions = _load(captions_path)
    cuts = _load(cuts_path)
    transitions = _load(transitions_path)
    provenance = _load(provenance_path)
    _validate_accepted_inputs(root, provenance, captions)

    shots = cuts["timeline"]
    durations = [row["timeline_duration"] for row in shots]
    quartiles = quantiles(durations, n=4, method="inclusive")
    sync_count = sum(bool(row["compiler_hints"]["sync_to_beat"]) for row in shots)

    transition_rows = transitions["transitions"]
    family_counts = dict(sorted(Counter(row["transition_type"] for row in transition_rows).items()))
    candidate_rows = [row for row in transition_rows if not row["editor_actionable"]]
    detector_actionable = [row for row in transition_rows if row["editor_actionable"]]
    accepted_transition = provenance["executable_authority"]
    accepted_matches = [
        row for row in transition_rows
        if row["transition_type"] == accepted_transition["transition_type"]
        and row["cut_frame"] == accepted_transition["cut_frame"]
    ]
    if len(accepted_matches) != 1 or accepted_matches[0] in candidate_rows:
        raise ValueError("Step 6A executable authority does not resolve to one non-candidate event")

    keyframes = camera["editor_transform"]["keyframes"]
    zooms = [row["zoom"] for row in keyframes]
    color = captions["color_opacity_rules"]
    fill_counts = color["identity_fill_colors"]
    unresolved_fill = fill_counts.get("UNKNOWN", 0)
    caption_count = captions["persistence_rules"]["caption_count"]
    common_combos = [row for row in captions["enter_exit_combos"] if row["caption_count"] >= 3]
    rare_combo_count = sum(row["caption_count"] for row in captions["enter_exit_combos"] if row["caption_count"] < 3)

    return {
        "schema": "video_cloner.style_profile.mvp.v1",
        "reel_id": REEL_ID,
        "cuts_pacing": {
            "observed": {
                "duration_sec": cuts["summary"]["timeline_duration"],
                "fps": cuts["source"]["fps"],
                "cut_count": len(shots) - 1,
                "shot_count": len(shots),
                "shot_duration_distribution_sec": {
                    "min": min(durations),
                    "p25": round(quartiles[0], 4),
                    "median": round(median(durations), 4),
                    "mean": round(mean(durations), 4),
                    "p75": round(quartiles[2], 4),
                    "max": max(durations),
                },
                "source_pace_label": cuts["global_style"]["pace"],
                "music_sync": cuts["global_style"]["music_sync"],
                "beat_sync_shot_count": sync_count,
            },
            "recommended": {
                "pacing_summary": "medium overall with a mixed rhythm: mostly 0.8-2.5 second cuts, punctuated by 3.3-6.5 second holds",
                "cut_rules": [
                    "prefer source-backed shot boundaries",
                    "sync cuts to beat where supported",
                    "preserve source timing when speed-ramp evidence is candidate-only",
                ],
            },
            "unresolved": ["exact beat map is not included in this MVP profile", "retime execution is not authoritative"],
        },
        "transitions": {
            "observed": {
                "families_present": family_counts,
                "detector_actionable_events": [_compact_event(row) for row in detector_actionable],
                "candidate_only_events": [_compact_event(row) for row in candidate_rows],
            },
            "recommended": {
                "step6a_authoritative_event": _compact_event(accepted_matches[0]),
                "timing_rules": {
                    "flash_cut": "4 frames centered at the cut (2 outgoing, 2 incoming)",
                    "blur_transition": "11 frames centered on the cut in observed detector output; not Step 6A execution authority",
                    "candidate_families": "marker/analysis only; never promote without new accepted authority",
                },
            },
            "deferred_unknown": {
                "execution_support": {"flash": "deferred"},
                "candidate_execution": "unsupported",
                "physical_effect_reconstruction": "unknown",
            },
        },
        "camera": {
            "observed": {
                "framing": camera["framing"],
                "subject_lock": camera["subject_lock"],
                "subject_observation": camera["subject_observation"],
                "camera_motion": camera["camera_motion"],
                "punch_in_events": camera["punch_in_events"],
                "punch_out_events": camera["punch_out_events"],
                "pan_events": camera["pan_events"],
                "stabilization": camera["stabilization"],
            },
            "recommended": {
                "reframe_strategy": camera["reframe_strategy"],
                "editor_transform": {
                    "operation": camera["editor_transform"]["operation"],
                    "authority": camera["editor_transform"]["authority"],
                    "sample_count": len(keyframes),
                    "zoom_range": [min(zooms), max(zooms)],
                    "rule": "reframe toward the sampled primary face center; do not claim physical camera provenance",
                },
            },
            "unresolved": ["physical camera motion versus baked editor transform"],
            "confidence": camera["confidence"],
        },
        "captions": {
            "observed": {
                "style_families": captions["caption_style_families"],
                "persistence_rules": captions["persistence_rules"],
                "font_rules": captions["font_rules"],
                "color_rules": {
                    "known_identity_fill_count": caption_count - unresolved_fill,
                    "unresolved_identity_fill_count": unresolved_fill,
                    "median_text_color": color["measured_reel_median_text_color"],
                    "median_stroke_color": color["measured_reel_median_stroke_color"],
                    "dark_stroke_ratio": color["measured_dark_stroke_ratio"],
                    "shadow_rule": color["shadow_rule"],
                },
                "opacity_rules": {
                    "rule": color["opacity_rule"],
                    "unresolved_count": captions["unresolved"]["opacity_count"],
                },
                "layout_rules": captions["layout_rules"],
                "animation_families": captions["animation_families"],
                "enter_exit_combos": {"common": common_combos, "rare_caption_count": rare_combo_count},
            },
            "recommended": {
                "transfer_rule": "reuse weight/layout/persistence and nearest supported animation family; retain per-caption variation",
            },
            "unresolved": captions["unresolved"],
            "confidence": captions["confidence"],
        },
        "deferred": DEFERRED,
        "source_artifacts": {
            "cuts_pacing": _source(root, cuts_path),
            "transitions": _source(root, transitions_path),
            "transition_provenance": _source(root, provenance_path),
            "camera": _source(root, camera_path),
            "captions": _source(root, captions_path),
            "caption_gold": _source(root, root / GOLD.relative_to(ROOT)),
        },
        "confidence": {
            "status": "MVP_READY_WITH_EXPLICIT_LIMITATIONS",
            "cuts_pacing": "accepted",
            "transitions": "accepted_understanding_execution_partly_deferred",
            "camera": camera["confidence"],
            "captions": captions["confidence"]["overall"],
            "overall": "medium_high",
        },
    }


def render_summary(profile: dict[str, Any]) -> str:
    pacing = profile["cuts_pacing"]["recommended"]["pacing_summary"]
    transitions = profile["transitions"]
    camera = profile["camera"]
    captions = profile["captions"]
    families = ", ".join(item["family"] for item in captions["observed"]["animation_families"])
    return f"""# Reel #2 MVP Style Profile

- **Editing pace:** {pacing}. Thirteen cuts divide 35.58 seconds into 14 shots; most boundaries are beat-synced.
- **Cuts and transitions:** Preserve source-backed shot boundaries. Observed families are blur, flash, slide-candidate, whip-pan-candidate, and crossfade-candidate. Only the frame-596 flash is Step 6A authority, and its execution remains deferred.
- **Person framing:** A person is present, but strict subject lock is not proven. Reframe recommendations follow sampled primary-face centers; the flattened source cannot distinguish physical camera motion from baked transforms.
- **Caption look:** Center-led vertical captions use regular, bold, and black weight families with closest-font candidates. Median measured text/stroke colors are {captions['observed']['color_rules']['median_text_color']} / {captions['observed']['color_rules']['median_stroke_color']}; opacity remains unresolved.
- **Caption timing and animation:** Captions persist continuously for a median {captions['observed']['persistence_rules']['duration_frames']['median']} frames. Reusable animation families are {families}; static → hold → static is dominant.
- **Transfer to another Reel:** Reuse the mixed cut rhythm, source-backed transition family/timing rules, face-centered reframe strategy, and caption weight/layout/persistence grammar. Re-measure events rather than copying Reel #2 timestamps.
- **Unsupported/deferred:** {', '.join(profile['deferred'])}; candidate transitions and physical camera provenance remain non-executable/unknown.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--summary", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    profile = build_profile()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.summary.write_text(render_summary(profile), encoding="utf-8")
    print(args.output)
    print(args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
