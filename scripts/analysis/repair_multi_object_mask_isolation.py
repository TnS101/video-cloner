from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path


MASK_FIELDS = ("final_mask_shape", "final_mask_rle", "known_foreground_rle", "known_background_rle", "unknown_rle")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def unresolved_mask_fields(row: dict, reason: str) -> dict:
    height, width = (int(value) for value in row["final_mask_shape"])
    observations = [{**item, "accepted": False, "reason": reason} for item in row["observations"]]
    return {
        "accepted_frame_count": 0,
        "rejected_frame_count": len(observations),
        "rejection_reasons": {reason: len(observations)},
        "aggregation_method": "foreign_object_ownership_exclusion_fail_closed",
        "mask_confidence": 0.0,
        "known_foreground_pixel_count": 0,
        "known_background_pixel_count": 0,
        "unknown_pixel_count": height * width,
        "unknown_ratio": 1.0,
        "contamination_score": 1.0,
        "evidence_classification": "CONTAMINATED_EVIDENCE",
        "unresolved_reason": reason,
        "final_mask_rle": [],
        "known_foreground_rle": [],
        "known_background_rle": [],
        "unknown_rle": [[0, height * width]],
        "observations": observations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("glyph", "font", "candidate_reduction", "step2c", "adjudication", "decisions"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    decisions, adjudication = load(args.decisions), load(args.adjudication)
    for name, path in (("glyph", args.glyph), ("font", args.font), ("candidate_reduction", args.candidate_reduction), ("step2c", args.step2c), ("adjudication", args.adjudication)):
        if decisions["input_hashes"][name] != sha256(path):
            raise RuntimeError(f"stale bounded decision input: {name}")

    original_glyph, original_font = load(args.glyph), load(args.font)
    original_reduction, step2c = load(args.candidate_reduction), load(args.step2c)
    glyph, font, reduction = copy.deepcopy(original_glyph), copy.deepcopy(original_font), copy.deepcopy(original_reduction)
    glyph_by = {row["identity"]: row for row in glyph["identities"]}
    font_by = {row["identity"]: row for row in font["identities"]}
    reduction_by = {row["identity"]: row for row in reduction["identities"]}
    step2c_by = {row["identity"]: row for row in step2c["identities"]}
    original_font_by = {row["identity"]: row for row in original_font["identities"]}
    original_reduction_by = {row["identity"]: row for row in original_reduction["identities"]}
    scoped = [row["identity"] for row in decisions["identities"]]
    if len(scoped) != len(set(scoped)) or set(scoped) - set(glyph_by):
        raise RuntimeError("bounded decision identities are duplicated or absent")

    results = []
    reason = "foreign_object_contamination_cannot_be_isolated_without_new_segmentation"
    for decision in decisions["identities"]:
        identity = decision["identity"]
        accepted = adjudication[identity]
        if accepted["classification"] != "TRUE_MISMATCH" or accepted["layer"] != "glyph_mask_object_isolation":
            raise RuntimeError(f"identity is not an accepted mask-isolation defect: {identity}")
        row, step2c_row = glyph_by[identity], step2c_by[identity]
        before_mask = {key: copy.deepcopy(row[key]) for key in MASK_FIELDS}
        before_observations = copy.deepcopy(row["observations"])
        ownership = {int(item["source_frame"]): item["ownership"] for item in step2c_row["stroke_observations"]}
        accepted_frames = [int(item["source_frame"]) for item in before_observations if item.get("accepted")]
        if set(accepted_frames) - set(ownership):
            raise RuntimeError(f"missing ownership evidence: {identity}")
        if any(int(ownership[frame]["foreign_identity_pixel_count"]) <= 0 or int(ownership[frame]["target_owned_pixel_count"]) != 0 for frame in accepted_frames):
            raise RuntimeError(f"existing ownership evidence does not support fail-closed isolation: {identity}")

        row.update(unresolved_mask_fields(row, reason))
        authority = {
            "text": None,
            "visual_text": decision["visual_text"],
            "authority": "SOURCE_VISIBLE_PIXELS_BOUNDED_MASK_ISOLATION_DECISION",
            "reason": reason,
            "relationship": "EXPLICITLY_UNRESOLVED",
            "source_adjudication_sha256": sha256(args.adjudication),
            "source_ownership_sha256": sha256(args.step2c),
        }
        row["font_scoring_text"] = None
        row["font_scoring_text_authority"] = authority
        row["accepted_mask_text_relationship"] = "EXPLICITLY_UNRESOLVED"
        old_font, font_row = original_font_by[identity], font_by[identity]
        font_row.update({
            "text": "", "font_scoring_text_authority": authority, "candidate_fonts_compared": 0,
            "minimum_evidence_gate_passed": False, "font_rerank_status": "NO_AUTHORITATIVE_FONT_RANKING",
            "no_authoritative_ranking_reason": reason, "top_score": None, "top_score_margin": None,
            "top_candidates": [],
            "previous_frozen_ranking": {
                "text": old_font["text"], "font_rerank_status": old_font["font_rerank_status"],
                "top_score": old_font["top_score"], "top_score_margin": old_font["top_score_margin"],
                "top_candidate": old_font["top_candidates"][0] if old_font.get("top_candidates") else None,
                "source_artifact_sha256": sha256(args.font),
            },
        })
        old_reduction, reduction_row = original_reduction_by[identity], reduction_by[identity]
        reduction_row.update({
            "text": "", "compatible_font_count": 0, "full_pool_exact_comparisons": 0,
            "full_pool_winner": None, "full_pool_runner_up": None, "full_pool_score_margin": None,
            "old_aspect_top40_winner": None, "old_winner_retained": None, "new_exact_comparisons": 0,
            "new_winner": None, "new_winner_retained": None, "new_full_pool_runner_up_retained": None,
            "frozen_authority": "NO_AUTHORITATIVE_FONT_RANKING",
            "full_pool_shadow_authority": "NO_AUTHORITATIVE_FONT_RANKING", "full_pool_shadow_reason": reason,
            "new_shortlist_shadow_authority": "NO_AUTHORITATIVE_FONT_RANKING", "new_shortlist_shadow_reason": reason,
            "font_scoring_text_authority": authority,
            "previous_step2b2_decision": {**old_reduction, "source_artifact_sha256": sha256(args.candidate_reduction)},
        })
        after_mask = {key: row[key] for key in MASK_FIELDS}
        results.append({
            "identity": identity, "outcome": "EXPLICITLY_UNRESOLVED",
            "accepted_source_frames_before": accepted_frames,
            "accepted_source_frames_after": [],
            "bboxes_unchanged": [item["bbox"] for item in before_observations] == [item["bbox"] for item in row["observations"]],
            "mask_before_sha256": value_hash(before_mask), "mask_after_sha256": value_hash(after_mask),
            "known_foreground_before": int(original_glyph["identities"][list(glyph_by).index(identity)]["known_foreground_pixel_count"]),
            "known_foreground_after": 0,
            "known_background_before": int(original_glyph["identities"][list(glyph_by).index(identity)]["known_background_pixel_count"]),
            "known_background_after": 0,
            "unknown_pixels_before": int(original_glyph["identities"][list(glyph_by).index(identity)]["unknown_pixel_count"]),
            "unknown_pixels_after": int(row["unknown_pixel_count"]),
            "foreign_pixels_excluded_by_frame": {str(frame): int(ownership[frame]["foreign_identity_pixel_count"]) for frame in accepted_frames},
            "target_owned_pixels_available_by_frame": {str(frame): int(ownership[frame]["target_owned_pixel_count"]) for frame in accepted_frames},
            "observations_rejected": len(accepted_frames), "font_reranked": False, "step2b2_updated": True,
        })

    glyph.setdefault("mask_isolation_corrections", []).extend({
        "identity": row["identity"], "outcome": row["outcome"],
        "mask_before_sha256": row["mask_before_sha256"], "mask_after_sha256": row["mask_after_sha256"],
    } for row in results)
    output_glyph = args.output / "reel2_glyph_evidence_v2_mask_isolation_corrected.json"
    write(output_glyph, glyph)
    font["summary"] = dict(Counter(row["font_rerank_status"] for row in font["identities"]))
    font["approved_v2_authority"] = {**font["approved_v2_authority"], "mask_isolation_corrected_evidence_sha256": sha256(output_glyph)}
    output_font = args.output / "reel2_known_region_font_rerank_mask_isolation_corrected.json"
    write(output_font, font)
    reduction["frozen_inputs"] = {
        **reduction["frozen_inputs"], "mask_isolation_corrected_v2_sha256": sha256(output_glyph),
        "mask_isolation_corrected_step2b1_sha256": sha256(output_font),
    }
    output_reduction = args.output / "whole_reel_full_pool_benchmark_mask_isolation_corrected.json"
    write(output_reduction, reduction)

    original_glyph_by = {row["identity"]: row for row in original_glyph["identities"]}
    masks_changed = [identity for identity in glyph_by if any(glyph_by[identity][key] != original_glyph_by[identity][key] for key in MASK_FIELDS)]
    non_target_glyph_unchanged = all(original_glyph_by[i] == glyph_by[i] for i in glyph_by if i not in scoped)
    non_target_font_unchanged = all(a == b for a, b in zip(original_font["identities"], font["identities"]) if a["identity"] not in scoped)
    non_target_reduction_unchanged = all(a == b for a, b in zip(original_reduction["identities"], reduction["identities"]) if a["identity"] not in scoped)
    passed = set(masks_changed) == set(scoped) and non_target_glyph_unchanged and non_target_font_unchanged and non_target_reduction_unchanged and len(glyph["identities"]) == 113
    validation = {
        "schema": "video_cloner_bounded_multi_object_mask_isolation_validation", "schema_version": 1,
        "result": "PASS_STEP_2B1_BOUNDED_MULTI_OBJECT_MASK_ISOLATION_REPAIR" if passed else "FAIL",
        "identity_count": len(glyph["identities"]), "bounded_identity_count": len(scoped), "identities": results,
        "masks_changed_identities": masks_changed, "font_reranked_identities": [], "step2b2_updated_identities": scoped,
        "non_target_glyph_rows_unchanged": non_target_glyph_unchanged,
        "non_target_font_rankings_unchanged": non_target_font_unchanged,
        "non_target_candidate_reduction_rows_unchanged": non_target_reduction_unchanged,
        "input_hashes": {name: sha256(path) for name, path in (("glyph", args.glyph), ("font", args.font), ("candidate_reduction", args.candidate_reduction), ("step2c", args.step2c), ("adjudication", args.adjudication))},
        "output_hashes": {"glyph": sha256(output_glyph), "font": sha256(output_font), "candidate_reduction": sha256(output_reduction)},
    }
    write(args.output / "bounded_multi_object_mask_isolation_validation.json", validation)
    if not passed:
        raise SystemExit("bounded mask-isolation validation failed")


if __name__ == "__main__":
    main()
