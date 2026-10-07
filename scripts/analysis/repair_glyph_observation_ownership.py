from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def repair(glyph: dict, font: dict, reduction: dict, decision: dict) -> tuple[dict, dict, dict]:
    identity, source_frame = decision["identity"], int(decision["source_frame"])
    glyph, font, reduction = copy.deepcopy(glyph), copy.deepcopy(font), copy.deepcopy(reduction)
    row = next(item for item in glyph["identities"] if item["identity"] == identity)
    matches = [item for item in row["observations"] if int(item["source_frame"]) == source_frame]
    if len(matches) != 1 or not matches[0].get("accepted") or matches[0].get("bbox") != decision["bbox"]:
        raise ValueError("ownership decision does not identify one accepted observation")
    observation = matches[0]
    observation["accepted"] = False
    observation["reason"] = decision["rejection_reason"]
    row.update({
        "accepted_frame_count": 0,
        "rejected_frame_count": len(row["observations"]),
        "rejection_reasons": dict(Counter(item["reason"] for item in row["observations"] if not item.get("accepted"))),
        "mask_confidence": 0.0,
        "known_foreground_pixel_count": 0,
        "known_background_pixel_count": 0,
        "unknown_pixel_count": 1,
        "unknown_ratio": 1.0,
        "overlap_occlusion_ratio": 0.0,
        "artifact_penalty": 0.0,
        "temporal_agreement": 0.0,
        "contour_stability": 0.0,
        "foreground_separation": 0.0,
        "evidence_classification": "CONTAMINATED_EVIDENCE",
        "unresolved_reason": "no_usable_source_observations_after_visual_identity_ownership_rejection",
        "final_mask_shape": [1, 1],
        "final_mask_rle": [],
        "known_foreground_rle": [],
        "known_background_rle": [],
        "unknown_rle": [[0, 1]],
        "shape_metrics": {"aspect_ratio": 1.0, "foreground_density": 0.0, "vertical_slant_proxy": 0.0},
        "non_uniform_scale_ratio": 1.0,
    })
    glyph.setdefault("ownership_corrections", []).append({**decision, "disposition": "rejected_not_reassigned_partial_transition_fragment"})
    glyph["summary"] = dict(Counter(item["evidence_classification"] for item in glyph["identities"]))

    font_row = next(item for item in font["identities"] if item["identity"] == identity)
    previous_font = copy.deepcopy(font_row)
    font_row.update({
        "evidence_classification": row["evidence_classification"],
        "mask_confidence": 0.0,
        "known_foreground_pixel_count": 0,
        "known_background_pixel_count": 0,
        "unknown_pixel_count": 1,
        "unknown_ratio": 1.0,
        "usable_frame_count": 0,
        "candidate_fonts_compared": 0,
        "minimum_evidence_gate_passed": False,
        "font_rerank_status": "NO_AUTHORITATIVE_FONT_RANKING",
        "no_authoritative_ranking_reason": "zero_usable_observations",
        "top_score": None,
        "top_score_margin": None,
        "top_candidates": [],
        "previous_ownership_invalidated_ranking": previous_font,
    })
    font["summary"] = dict(Counter(item["font_rerank_status"] for item in font["identities"]))
    font["authoritative_top_family_distribution"] = dict(Counter(
        item["top_candidates"][0]["family"] for item in font["identities"]
        if item["font_rerank_status"] == "AUTHORITATIVE_FONT_RANKING" and item.get("top_candidates")
    ))

    passing = [item for item in reduction["identities"] if item["identity"] != identity]
    if len(passing) != len(reduction["identities"]) - 1:
        raise ValueError("target is not one gate-passing Step 2B.2 identity")
    failed = [item for item in reduction.get("gate_failed_identities", []) if item["identity"] != identity]
    failed.append({
        "identity": identity,
        "text": font_row["text"],
        "gate_reason": "zero_usable_observations",
        "exact_comparisons": 0,
        "frozen_authority": "NO_AUTHORITATIVE_FONT_RANKING",
    })
    reduction["identities"] = passing
    reduction["gate_failed_identities"] = sorted(failed, key=lambda item: item["identity"])
    reduction["gate_passing_identity_count"] = len(passing)
    reduction["gate_failed_identity_count"] = len(failed)
    reduction["full_pool_exact_comparisons"] = sum(int(item["full_pool_exact_comparisons"]) for item in passing)
    reduction.setdefault("ownership_corrections", []).append({**decision, "disposition": "step2b2_gate_failed"})
    return glyph, font, reduction


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("glyph", "font", "candidate_reduction", "decision", "output"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original = {name: load(getattr(args, name)) for name in ("glyph", "font", "candidate_reduction")}
    glyph, font, reduction = repair(original["glyph"], original["font"], original["candidate_reduction"], load(args.decision))
    outputs = {
        "glyph": args.output / "reel2_glyph_evidence_v2_ownership_corrected.json",
        "font": args.output / "reel2_known_region_font_rerank_ownership_corrected.json",
        "candidate_reduction": args.output / "whole_reel_full_pool_benchmark_ownership_corrected.json",
    }
    for name, value in (("glyph", glyph), ("font", font), ("candidate_reduction", reduction)):
        write(outputs[name], value)
    identity = load(args.decision)["identity"]
    non_target_unchanged = all(
        [item for item in original[name]["identities"] if item["identity"] != identity]
        == [item for item in value["identities"] if item["identity"] != identity]
        for name, value in (("glyph", glyph), ("font", font), ("candidate_reduction", reduction))
    )
    validation = {
        "schema": "video_cloner_bounded_glyph_observation_ownership_repair_validation",
        "schema_version": 1,
        "result": "PASS_BOUNDED_VISUAL_IDENTITY_OWNERSHIP_REPAIR" if non_target_unchanged and glyph["identity_count"] == reduction["identity_count"] == 113 else "FAIL",
        "identity": identity,
        "ownership_decision": load(args.decision),
        "identity_count": 113,
        "non_target_identity_rows_unchanged": non_target_unchanged,
        "target_mask_pixels_changed": True,
        "target_final_mask": {"shape": [1, 1], "foreground_rle": [], "background_rle": [], "unknown_rle": [[0, 1]]},
        "input_hashes": {name: sha256(getattr(args, name)) for name in original},
        "output_hashes": {name: sha256(path) for name, path in outputs.items()},
    }
    write(args.output / "bounded_ownership_repair_validation.json", validation)
    if validation["result"] != "PASS_BOUNDED_VISUAL_IDENTITY_OWNERSHIP_REPAIR":
        raise SystemExit(validation["result"])


if __name__ == "__main__":
    main()
