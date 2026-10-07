from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.standalone import video_cloner_font_inference as inference


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def decode(shape: list[int], runs: list[list[int]]) -> np.ndarray:
    flat = np.zeros(int(shape[0]) * int(shape[1]), dtype=bool)
    for start, length in runs:
        flat[int(start):int(start) + int(length)] = True
    return flat.reshape(int(shape[0]), int(shape[1]))


def masks(row: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    shape = row["final_mask_shape"]
    foreground = decode(shape, row.get("known_foreground_rle") or row["final_mask_rle"])
    unknown = decode(shape, row.get("unknown_rle") or [])
    background = decode(shape, row.get("known_background_rle") or [])
    return foreground, background if background.any() else ~(foreground | unknown), unknown


def exact_pool(text: str, row: dict, fonts: list[dict]) -> list[dict]:
    foreground, background, unknown = masks(row)
    ranking = []
    for font in fonts:
        if not inference.font_supports_text(font["path"], text):
            continue
        try:
            candidate = inference.render_text_mask(text, font["path"])
        except OSError:
            continue
        ranking.append({
            "family": font["family"], "style": font["style"], "weight": font["weight"],
            "renderer_compatible": font["renderer_compatible"],
            **inference.compare_known_regions(foreground, background, unknown, candidate),
        })
    return sorted(ranking, key=lambda item: (-item["score"], item["family"].casefold(), item["style"].casefold()))


def _bounded_batch(args: argparse.Namespace) -> None:
    original_glyph, original_font = load(args.glyph), load(args.font)
    original_reduction, style = load(args.candidate_reduction), load(args.style_events)
    decisions, adjudication = load(args.decisions), load(args.adjudication)
    lifecycle, coverage = load(args.lifecycle), load(args.coverage_audit)
    glyph, font, reduction = copy.deepcopy(original_glyph), copy.deepcopy(original_font), copy.deepcopy(original_reduction)
    glyph_by = {row["identity"]: row for row in glyph["identities"]}
    font_by = {row["identity"]: row for row in font["identities"]}
    reduction_by = {row["identity"]: row for row in reduction["identities"]}
    old_font_by = {row["identity"]: row for row in original_font["identities"]}
    old_reduction_by = {row["identity"]: row for row in original_reduction["identities"]}
    adjudicated = adjudication
    scoped = [row["identity"] for row in decisions["identities"]]
    if len(scoped) != len(set(scoped)) or set(scoped) - set(glyph_by):
        raise RuntimeError("bounded decision identities are duplicated or absent")
    if coverage.get("result") != "PASS_REJECTED_OBSERVATION_COVERAGE_AUDIT_NO_SOURCE_LOSS":
        raise RuntimeError("rejected-observation coverage audit is not accepted")
    for name, path in (("glyph", args.glyph), ("font", args.font), ("candidate_reduction", args.candidate_reduction), ("adjudication", args.adjudication), ("coverage_audit", args.coverage_audit)):
        if decisions["input_hashes"].get(name) != sha256(path):
            raise RuntimeError(f"stale bounded decision input: {name}")

    fonts = inference.discover_installed_fonts()
    lifecycle_rows = lifecycle["layers"]
    results = []
    reranked = []
    for decision in decisions["identities"]:
        identity = decision["identity"]
        source_decision = adjudicated[identity]
        if source_decision["classification"] != "TRUE_MISMATCH" or source_decision["visual_text"] != decision["visual_text"]:
            raise RuntimeError(f"bounded decision does not match accepted adjudication: {identity}")
        target, font_row, reduction_row = glyph_by[identity], font_by[identity], reduction_by[identity]
        old_font_row, old_reduction_row = old_font_by[identity], old_reduction_by[identity]
        scoring_text = decision.get("scoring_text")
        linkage = {
            "text": scoring_text,
            "visual_text": decision["visual_text"],
            "authority": "SOURCE_VISIBLE_PIXELS_BOUNDED_LINKAGE_DECISION",
            "reason": decision.get("reason"),
            "relationship": decision["relationship"],
            "parent_text": decision.get("parent_text"),
            "source_adjudication_sha256": sha256(args.adjudication),
        }
        target["font_scoring_text"] = scoring_text
        target["font_scoring_text_authority"] = linkage
        target["accepted_mask_text_relationship"] = decision["relationship"]
        if inference.source_visible_scoring_text(target, style["caption_style_events"]) != linkage:
            raise RuntimeError(f"source-pixel authority precedence failed: {identity}")
        glyph.setdefault("linkage_corrections", []).append({
            "identity": identity, "previous_scoring_text": old_font_row["text"], **linkage,
        })
        previous_font = {
            "text": old_font_row["text"], "font_rerank_status": old_font_row["font_rerank_status"],
            "top_score": old_font_row["top_score"], "top_score_margin": old_font_row["top_score_margin"],
            "top_candidate": old_font_row["top_candidates"][0] if old_font_row.get("top_candidates") else None,
            "source_artifact_sha256": sha256(args.font),
        }
        previous_reduction = {**old_reduction_row, "source_artifact_sha256": sha256(args.candidate_reduction)}
        if scoring_text:
            full = exact_pool(scoring_text, target, fonts)
            if len(full) < 2:
                raise RuntimeError(f"insufficient compatible fonts: {identity}")
            foreground, background, unknown = masks(target)
            passed, gate_reason = inference.known_region_evidence_gate(
                foreground, background, unknown, usable_frame_count=int(target["accepted_frame_count"]),
            )
            status, reason = inference.known_region_ranking_authority(
                full[:8], evidence_gate_passed=passed, evidence_gate_reason=gate_reason,
                evidence_classification=target["evidence_classification"], unknown_ratio=float(target["unknown_ratio"]),
            )
            shortlist, compared = inference.rank_font_candidates_known_regions(scoring_text, foreground, background, unknown, fonts, limit=8)
            shortlist_status, shortlist_reason = inference.known_region_ranking_authority(
                shortlist, evidence_gate_passed=passed, evidence_gate_reason=gate_reason,
                evidence_classification=target["evidence_classification"], unknown_ratio=float(target["unknown_ratio"]),
            )
            margin = round(float(full[0]["score"]) - float(full[1]["score"]), 6)
            full_key, runner_key = (full[0]["family"], full[0]["style"]), (full[1]["family"], full[1]["style"])
            retained = {(row["family"], row["style"]) for row in shortlist}
            font_row.update({
                "text": scoring_text, "font_scoring_text_authority": linkage,
                "candidate_fonts_compared": len(full), "minimum_evidence_gate_passed": passed,
                "font_rerank_status": status, "no_authoritative_ranking_reason": reason,
                "top_score": full[0]["score"], "top_score_margin": margin, "top_candidates": full[:8],
                "previous_frozen_ranking": previous_font,
            })
            reduction_row.update({
                "text": scoring_text, "compatible_font_count": len(full), "full_pool_exact_comparisons": len(full),
                "full_pool_winner": {"family": full[0]["family"], "style": full[0]["style"], "score": full[0]["score"]},
                "full_pool_runner_up": {"family": full[1]["family"], "style": full[1]["style"], "score": full[1]["score"]},
                "full_pool_score_margin": margin, "old_aspect_top40_winner": None, "old_winner_retained": None,
                "new_exact_comparisons": compared,
                "new_winner": {"family": shortlist[0]["family"], "style": shortlist[0]["style"], "score": shortlist[0]["score"]},
                "new_winner_retained": (shortlist[0]["family"], shortlist[0]["style"]) == full_key,
                "new_full_pool_runner_up_retained": runner_key in retained,
                "frozen_authority": status, "full_pool_shadow_authority": status, "full_pool_shadow_reason": reason,
                "new_shortlist_shadow_authority": shortlist_status, "new_shortlist_shadow_reason": shortlist_reason,
                "font_scoring_text_authority": linkage, "previous_step2b2_decision": previous_reduction,
            })
            reranked.append(identity)
        else:
            reason = decision["reason"]
            font_row.update({
                "text": "", "font_scoring_text_authority": linkage, "candidate_fonts_compared": 0,
                "minimum_evidence_gate_passed": False, "font_rerank_status": "NO_AUTHORITATIVE_FONT_RANKING",
                "no_authoritative_ranking_reason": reason, "top_score": None, "top_score_margin": None,
                "top_candidates": [], "previous_frozen_ranking": previous_font,
            })
            reduction_row.update({
                "text": "", "compatible_font_count": 0, "full_pool_exact_comparisons": 0,
                "full_pool_winner": None, "full_pool_runner_up": None, "full_pool_score_margin": None,
                "old_aspect_top40_winner": None, "old_winner_retained": None, "new_exact_comparisons": 0,
                "new_winner": None, "new_winner_retained": None, "new_full_pool_runner_up_retained": None,
                "frozen_authority": "NO_AUTHORITATIVE_FONT_RANKING",
                "full_pool_shadow_authority": "NO_AUTHORITATIVE_FONT_RANKING", "full_pool_shadow_reason": reason,
                "new_shortlist_shadow_authority": "NO_AUTHORITATIVE_FONT_RANKING", "new_shortlist_shadow_reason": reason,
                "font_scoring_text_authority": linkage, "previous_step2b2_decision": previous_reduction,
            })
        window = target["source_window"]
        lifecycle_links = [
            {"layer_id": row["layer_id"], "text": row["text"], "lifecycle_window": row["lifecycle_window"], "status": row["lifecycle_status"]}
            for row in lifecycle_rows if max(window[0], row["lifecycle_window"][0]) <= min(window[1], row["lifecycle_window"][1])
        ]
        results.append({
            "identity": identity, "visual_classification": decision["visual_classification"],
            "visual_text": decision["visual_text"], "scoring_text_before": old_font_row["text"],
            "scoring_text_after": scoring_text, "relationship": decision["relationship"],
            "accepted_source_frames": [row["source_frame"] for row in target["observations"] if row.get("accepted")],
            "accepted_bboxes": [row["bbox"] for row in target["observations"] if row.get("accepted")],
            "mask_evidence": {key: target[key] for key in ("final_mask_shape", "mask_confidence", "unknown_ratio", "accepted_frame_count", "evidence_classification")},
            "scoring_text_authority_before": old_font_row.get("font_scoring_text_authority") or {"authority": "ACTUAL_STEP2B2_GLYPH_TEXT_FIELD"},
            "scoring_text_authority_after": linkage, "exact_string_passed_to_font_scorer": scoring_text,
            "lifecycle_linkage": lifecycle_links, "font_reranked": bool(scoring_text), "step2b2_updated": True,
        })

    bounded = sorted(set(scoped))
    corrected_glyph_path = args.output / "reel2_glyph_evidence_v2_visual_identity_linkage_corrected.json"
    write(corrected_glyph_path, glyph)
    font["approved_v2_authority"] = {
        **font["approved_v2_authority"], "linkage_corrected_evidence_sha256": sha256(corrected_glyph_path),
        "bounded_identities": sorted(set(font["approved_v2_authority"].get("bounded_identities", [])) | set(bounded)),
    }
    font["summary"] = dict(Counter(row["font_rerank_status"] for row in font["identities"]))
    corrected_font_path = args.output / "reel2_known_region_font_rerank_visual_identity_linkage_corrected.json"
    write(corrected_font_path, font)
    reduction["frozen_inputs"] = {
        **reduction["frozen_inputs"], "linkage_corrected_v2_sha256": sha256(corrected_glyph_path),
        "linkage_corrected_step2b1_rerank_sha256": sha256(corrected_font_path),
        "bounded_identities": sorted(set(reduction["frozen_inputs"].get("bounded_identities", [])) | set(bounded)),
    }
    corrected_reduction_path = args.output / "whole_reel_full_pool_benchmark_visual_identity_linkage_corrected.json"
    write(corrected_reduction_path, reduction)

    protected = ("final_mask_shape", "final_mask_rle", "known_foreground_rle", "known_background_rle", "unknown_rle", "observations")
    masks_unchanged = all(all(before[key] == after[key] for key in protected) for before, after in zip(original_glyph["identities"], glyph["identities"]))
    non_target_glyph_unchanged = all(before == after for before, after in zip(original_glyph["identities"], glyph["identities"]) if before["identity"] not in scoped)
    non_target_font_unchanged = all(before == after for before, after in zip(original_font["identities"], font["identities"]) if before["identity"] not in scoped)
    non_target_reduction_unchanged = all(before == after for before, after in zip(original_reduction["identities"], reduction["identities"]) if before["identity"] not in scoped)
    shortlist_valid = all(row["new_winner_retained"] and row["new_full_pool_runner_up_retained"] for row in reduction["identities"] if row["identity"] in reranked)
    passed = masks_unchanged and non_target_glyph_unchanged and non_target_font_unchanged and non_target_reduction_unchanged and shortlist_valid
    validation = {
        "schema": "video_cloner_bounded_visual_identity_scoring_text_linkage_validation", "schema_version": 1,
        "result": "PASS_STEP_2B1_BOUNDED_VISUAL_IDENTITY_SCORING_TEXT_LINKAGE_REPAIR" if passed else "FAIL",
        "identity_count": len(glyph["identities"]), "bounded_identity_count": len(scoped), "identities": results,
        "font_reranked_identities": reranked, "step2b2_updated_identities": scoped,
        "masks_bboxes_observations_unchanged": masks_unchanged,
        "non_target_glyph_rows_unchanged": non_target_glyph_unchanged,
        "non_target_font_rankings_unchanged": non_target_font_unchanged,
        "non_target_candidate_reduction_rows_unchanged": non_target_reduction_unchanged,
        "input_hashes": {name: sha256(path) for name, path in (("glyph", args.glyph), ("font", args.font), ("candidate_reduction", args.candidate_reduction), ("style_events", args.style_events), ("adjudication", args.adjudication), ("lifecycle", args.lifecycle), ("coverage_audit", args.coverage_audit))},
        "output_hashes": {"glyph": sha256(corrected_glyph_path), "font": sha256(corrected_font_path), "candidate_reduction": sha256(corrected_reduction_path)},
    }
    write(args.output / "bounded_visual_identity_scoring_text_linkage_validation.json", validation)
    if not passed:
        raise SystemExit("bounded visual-identity scoring-text linkage validation failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity")
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--lifecycle", type=Path)
    parser.add_argument("--coverage-audit", type=Path)
    parser.add_argument("--glyph", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--candidate-reduction", type=Path, required=True)
    parser.add_argument("--style-events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    if args.decisions:
        if not all((args.adjudication, args.lifecycle, args.coverage_audit)):
            parser.error("--decisions requires --adjudication, --lifecycle, and --coverage-audit")
        _bounded_batch(args)
        return
    if not args.identity:
        parser.error("--identity or --decisions is required")

    original_glyph, original_font = load(args.glyph), load(args.font)
    original_reduction, style = load(args.candidate_reduction), load(args.style_events)
    glyph = copy.deepcopy(original_glyph)
    target = next(row for row in glyph["identities"] if row["identity"] == args.identity)
    linkage = inference.source_visible_scoring_text(target, style["caption_style_events"])
    if linkage["authority"] != "SOURCE_VISIBLE_OBSERVED_TEXT_BBOX_MATCH":
        raise RuntimeError(f"source-visible text linkage unresolved: {linkage}")
    target["font_scoring_text"] = linkage["text"]
    target["font_scoring_text_authority"] = linkage
    glyph.setdefault("linkage_corrections", []).append({"identity": args.identity, "previous_scoring_text": target["text"], **linkage})
    corrected_glyph_path = args.output / "reel2_glyph_evidence_v2_linkage_corrected.json"
    write(corrected_glyph_path, glyph)

    fonts = inference.discover_installed_fonts()
    ranking = exact_pool(linkage["text"], target, fonts)
    foreground, background, unknown = masks(target)
    passed, gate_reason = inference.known_region_evidence_gate(
        foreground, background, unknown, usable_frame_count=int(target["accepted_frame_count"]),
    )
    status, reason = inference.known_region_ranking_authority(
        ranking[:8], evidence_gate_passed=passed, evidence_gate_reason=gate_reason,
        evidence_classification=target["evidence_classification"], unknown_ratio=float(target["unknown_ratio"]),
    )
    margin = round(float(ranking[0]["score"]) - float(ranking[1]["score"]), 6)
    font = copy.deepcopy(original_font)
    old_font_row = next(row for row in original_font["identities"] if row["identity"] == args.identity)
    new_font_row = next(row for row in font["identities"] if row["identity"] == args.identity)
    new_font_row.update({
        "text": linkage["text"], "font_scoring_text_authority": linkage,
        "candidate_fonts_compared": len(ranking), "minimum_evidence_gate_passed": passed,
        "font_rerank_status": status, "no_authoritative_ranking_reason": reason,
        "top_score": ranking[0]["score"], "top_score_margin": margin, "top_candidates": ranking[:8],
        "previous_frozen_ranking": {
            "text": old_font_row["text"], "font_rerank_status": old_font_row["font_rerank_status"],
            "top_score": old_font_row["top_score"], "top_score_margin": old_font_row["top_score_margin"],
            "top_candidate": old_font_row["top_candidates"][0], "source_artifact_sha256": sha256(args.font),
        },
    })
    corrected_identities = [*font["approved_v2_authority"].get("bounded_identities", []), args.identity]
    font["approved_v2_authority"] = {
        **font["approved_v2_authority"], "linkage_corrected_evidence_sha256": sha256(corrected_glyph_path),
        "bounded_identity": args.identity, "bounded_identities": sorted(set(corrected_identities)),
    }
    font["summary"] = dict(Counter(row["font_rerank_status"] for row in font["identities"]))
    corrected_font_path = args.output / "reel2_known_region_font_rerank_linkage_corrected.json"
    write(corrected_font_path, font)

    new_ranking, compared = inference.rank_font_candidates_known_regions(
        linkage["text"], foreground, background, unknown, fonts, limit=8,
    )
    new_status, new_reason = inference.known_region_ranking_authority(
        new_ranking, evidence_gate_passed=passed, evidence_gate_reason=gate_reason,
        evidence_classification=target["evidence_classification"], unknown_ratio=float(target["unknown_ratio"]),
    )
    full_key = (ranking[0]["family"], ranking[0]["style"])
    runner_key = (ranking[1]["family"], ranking[1]["style"])
    retained = {(row["family"], row["style"]) for row in new_ranking}
    reduction = copy.deepcopy(original_reduction)
    old_reduction_row = next(row for row in original_reduction["identities"] if row["identity"] == args.identity)
    new_reduction_row = next(row for row in reduction["identities"] if row["identity"] == args.identity)
    new_reduction_row.update({
        "text": linkage["text"], "compatible_font_count": len(ranking), "full_pool_exact_comparisons": len(ranking),
        "full_pool_winner": {"family": ranking[0]["family"], "style": ranking[0]["style"], "score": ranking[0]["score"]},
        "full_pool_runner_up": {"family": ranking[1]["family"], "style": ranking[1]["style"], "score": ranking[1]["score"]},
        "full_pool_score_margin": margin, "old_aspect_top40_winner": None, "old_winner_retained": None,
        "new_exact_comparisons": compared,
        "new_winner": {"family": new_ranking[0]["family"], "style": new_ranking[0]["style"], "score": new_ranking[0]["score"]},
        "new_winner_retained": (new_ranking[0]["family"], new_ranking[0]["style"]) == full_key,
        "new_full_pool_runner_up_retained": runner_key in retained,
        "frozen_authority": status, "full_pool_shadow_authority": status, "full_pool_shadow_reason": reason,
        "new_shortlist_shadow_authority": new_status, "new_shortlist_shadow_reason": new_reason,
        "font_scoring_text_authority": linkage,
        "previous_step2b2_decision": {**old_reduction_row, "source_artifact_sha256": sha256(args.candidate_reduction)},
    })
    corrected_identities = [*reduction["frozen_inputs"].get("bounded_identities", []), args.identity]
    reduction["frozen_inputs"] = {
        **reduction["frozen_inputs"], "linkage_corrected_v2_sha256": sha256(corrected_glyph_path),
        "linkage_corrected_step2b1_rerank_sha256": sha256(corrected_font_path), "bounded_identity": args.identity,
        "bounded_identities": sorted(set(corrected_identities)),
    }
    corrected_reduction_path = args.output / "whole_reel_full_pool_benchmark_linkage_corrected.json"
    write(corrected_reduction_path, reduction)

    protected = ("final_mask_shape", "final_mask_rle", "known_foreground_rle", "known_background_rle", "unknown_rle", "observations")
    masks_unchanged = all(
        all(before[key] == after[key] for key in protected)
        for before, after in zip(original_glyph["identities"], glyph["identities"])
    )
    non_target_font_unchanged = all(
        left == right for left, right in zip(original_font["identities"], font["identities"])
        if left["identity"] != args.identity
    )
    non_target_reduction_unchanged = all(
        left == right for left, right in zip(original_reduction["identities"], reduction["identities"])
        if left["identity"] != args.identity
    )
    validation = {
        "schema": "video_cloner_bounded_font_text_linkage_repair_validation", "schema_version": 1,
        "result": "PASS_BOUNDED_FONT_TEXT_LINKAGE_REPAIR" if masks_unchanged and non_target_font_unchanged and non_target_reduction_unchanged and new_reduction_row["new_winner_retained"] and new_reduction_row["new_full_pool_runner_up_retained"] else "FAIL",
        "identity": args.identity, "linkage": linkage, "previous_scoring_text": old_font_row["text"],
        "corrected_scoring_text": linkage["text"], "masks_bboxes_observations_unchanged": masks_unchanged,
        "non_target_font_rankings_unchanged": non_target_font_unchanged,
        "non_target_candidate_reduction_rows_unchanged": non_target_reduction_unchanged,
        "step2b1": {"winner": ranking[0], "runner_up": ranking[1], "authority": status, "reason": reason, "full_pool_comparisons": len(ranking)},
        "step2b2": {"winner": new_reduction_row["new_winner"], "authority": new_status, "reason": new_reason, "exact_comparisons": compared, "full_pool_winner_retained": new_reduction_row["new_winner_retained"], "full_pool_runner_up_retained": new_reduction_row["new_full_pool_runner_up_retained"]},
        "input_hashes": {"glyph": sha256(args.glyph), "font": sha256(args.font), "candidate_reduction": sha256(args.candidate_reduction), "style_events": sha256(args.style_events)},
        "output_hashes": {"glyph": sha256(corrected_glyph_path), "font": sha256(corrected_font_path), "candidate_reduction": sha256(corrected_reduction_path)},
    }
    write(args.output / "bounded_linkage_repair_validation.json", validation)
    if validation["result"] != "PASS_BOUNDED_FONT_TEXT_LINKAGE_REPAIR":
        raise SystemExit(validation["result"])


if __name__ == "__main__":
    main()
