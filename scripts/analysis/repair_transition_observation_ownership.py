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

from scripts.analysis import repair_font_text_linkage as font_repair
from scripts.standalone import video_cloner_font_inference as inference


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(shape: list[int], runs: list[list[int]]) -> np.ndarray:
    flat = np.zeros(shape[0] * shape[1], dtype=bool)
    for start, length in runs:
        flat[start:start + length] = True
    return flat.reshape(shape)


def encode(mask: np.ndarray) -> list[list[int]]:
    indexes = np.flatnonzero(np.asarray(mask, dtype=bool).ravel())
    if not len(indexes):
        return []
    runs, start, previous = [], int(indexes[0]), int(indexes[0])
    for value in map(int, indexes[1:]):
        if value != previous + 1:
            runs.append([start, previous - start + 1])
            start = value
        previous = value
    runs.append([start, previous - start + 1])
    return runs


def rebuild_mask(row: dict) -> None:
    accepted = [item for item in row["observations"] if item.get("accepted")]
    row["accepted_frame_count"] = len(accepted)
    row["rejected_frame_count"] = len(row["observations"]) - len(accepted)
    row["rejection_reasons"] = dict(Counter(item["reason"] for item in row["observations"] if not item.get("accepted")))
    if not accepted:
        row.update({
            "mask_confidence": 0.0, "known_foreground_pixel_count": 0, "known_background_pixel_count": 0,
            "unknown_pixel_count": 1, "unknown_ratio": 1.0, "overlap_occlusion_ratio": 0.0,
            "artifact_penalty": 0.0, "temporal_agreement": 0.0, "contour_stability": 0.0,
            "foreground_separation": 0.0, "contamination_score": 0.0, "overlap_risk": 0.0,
            "evidence_classification": "CONTAMINATED_EVIDENCE",
            "unresolved_reason": "no_usable_source_observations_after_transition_boundary_repair",
            "final_mask_shape": [1, 1], "final_mask_rle": [], "known_foreground_rle": [],
            "known_background_rle": [], "unknown_rle": [[0, 1]],
            "shape_metrics": {"aspect_ratio": 1.0, "foreground_density": 0.0, "vertical_slant_proxy": 0.0},
            "non_uniform_scale_ratio": 1.0,
        })
        return
    source = []
    for item in accepted:
        shape = item["estimated_mask_shape"]
        source.append({
            "frame": item["source_frame"], "timestamp": item["timestamp"], "bbox": item["bbox"],
            "mask": decode(shape, item["estimated_mask_rle"]),
            "unknown_mask": decode(shape, item.get("unknown_mask_rle") or []),
            "foreground_confidence": item["foreground_confidence"],
            "contamination_score": item["background_contamination"], "overlap_risk": item["overlap_risk"],
            "blur_quality": item["blur_quality"], "accepted": True,
        })
    aggregate = inference.aggregate_source_masks(source)
    foreground, background, unknown = aggregate["foreground_mask"], aggregate["background_mask"], aggregate["unknown_mask"]
    rows, columns = np.where(foreground)
    slant = float(np.corrcoef(rows, columns)[0, 1]) if len(rows) > 1 and np.std(rows) and np.std(columns) else 0.0
    row.update({
        "mask_confidence": aggregate["confidence"], "known_foreground_pixel_count": int(foreground.sum()),
        "known_background_pixel_count": int(background.sum()), "unknown_pixel_count": int(unknown.sum()),
        "unknown_ratio": aggregate["unknown_ratio"], "overlap_occlusion_ratio": aggregate.get("mean_overlap_risk", 0.0),
        "artifact_penalty": aggregate["artifact_penalty"], "temporal_agreement": aggregate["temporal_agreement"],
        "contour_stability": aggregate["contour_stability"], "foreground_separation": aggregate["separation_score"],
        "contamination_score": round(float(np.mean([item["background_contamination"] for item in accepted])), 6),
        "overlap_risk": aggregate.get("mean_overlap_risk", 0.0), "evidence_classification": aggregate["status"],
        "unresolved_reason": None, "final_mask_shape": list(foreground.shape), "final_mask_rle": encode(foreground),
        "known_foreground_rle": encode(foreground), "known_background_rle": encode(background), "unknown_rle": encode(unknown),
        "shape_metrics": {"aspect_ratio": round(foreground.shape[1] / max(1, foreground.shape[0]), 6), "foreground_density": round(float(foreground.mean()), 6), "vertical_slant_proxy": round(slant, 6)},
        "non_uniform_scale_ratio": aggregate["non_uniform_scale_ratio"],
    })


def rerank(glyph_row: dict, font_row: dict, reduction: dict, text: str | None, fonts: list[dict]) -> None:
    identity = glyph_row["identity"]
    reduction["identities"] = [item for item in reduction["identities"] if item["identity"] != identity]
    reduction["gate_failed_identities"] = [item for item in reduction.get("gate_failed_identities", []) if item["identity"] != identity]
    if not text or not glyph_row["accepted_frame_count"]:
        font_row.update({
            "evidence_classification": glyph_row["evidence_classification"], "mask_confidence": glyph_row["mask_confidence"],
            "known_foreground_pixel_count": 0, "known_background_pixel_count": 0, "unknown_pixel_count": 1,
            "unknown_ratio": 1.0, "usable_frame_count": 0, "candidate_fonts_compared": 0,
            "minimum_evidence_gate_passed": False, "font_rerank_status": "NO_AUTHORITATIVE_FONT_RANKING",
            "no_authoritative_ranking_reason": "zero_usable_observations", "top_score": None,
            "top_score_margin": None, "top_candidates": [],
        })
        reduction["gate_failed_identities"].append({"identity": identity, "text": font_row["text"], "gate_reason": "zero_usable_observations", "exact_comparisons": 0, "frozen_authority": "NO_AUTHORITATIVE_FONT_RANKING"})
        return
    foreground, background, unknown = font_repair.masks(glyph_row)
    full = font_repair.exact_pool(text, glyph_row, fonts)
    passed, gate_reason = inference.known_region_evidence_gate(foreground, background, unknown, usable_frame_count=glyph_row["accepted_frame_count"])
    status, reason = inference.known_region_ranking_authority(full[:8], evidence_gate_passed=passed, evidence_gate_reason=gate_reason, evidence_classification=glyph_row["evidence_classification"], unknown_ratio=glyph_row["unknown_ratio"])
    shortlist, compared = inference.rank_font_candidates_known_regions(text, foreground, background, unknown, fonts, limit=8)
    shortlist_status, shortlist_reason = inference.known_region_ranking_authority(shortlist, evidence_gate_passed=passed, evidence_gate_reason=gate_reason, evidence_classification=glyph_row["evidence_classification"], unknown_ratio=glyph_row["unknown_ratio"])
    margin = round(float(full[0]["score"]) - float(full[1]["score"]), 6)
    font_row.update({
        "text": text, "evidence_classification": glyph_row["evidence_classification"], "mask_confidence": glyph_row["mask_confidence"],
        "known_foreground_pixel_count": int(foreground.sum()), "known_background_pixel_count": int(background.sum()),
        "unknown_pixel_count": int(unknown.sum()), "unknown_ratio": glyph_row["unknown_ratio"],
        "usable_frame_count": glyph_row["accepted_frame_count"], "candidate_fonts_compared": len(full),
        "minimum_evidence_gate_passed": passed, "font_rerank_status": status,
        "no_authoritative_ranking_reason": reason, "top_score": full[0]["score"], "top_score_margin": margin, "top_candidates": full[:8],
        "font_scoring_text_authority": glyph_row["font_scoring_text_authority"],
    })
    full_key = (full[0]["family"], full[0]["style"])
    runner_key = (full[1]["family"], full[1]["style"])
    retained = {(item["family"], item["style"]) for item in shortlist}
    reduction["identities"].append({
        "identity": identity, "text": text, "compatible_font_count": len(full), "full_pool_exact_comparisons": len(full),
        "full_pool_winner": {"family": full[0]["family"], "style": full[0]["style"], "score": full[0]["score"]},
        "full_pool_runner_up": {"family": full[1]["family"], "style": full[1]["style"], "score": full[1]["score"]},
        "full_pool_score_margin": margin, "old_aspect_top40_winner": None, "old_winner_retained": None,
        "new_exact_comparisons": compared, "new_winner": {"family": shortlist[0]["family"], "style": shortlist[0]["style"], "score": shortlist[0]["score"]},
        "new_winner_retained": (shortlist[0]["family"], shortlist[0]["style"]) == full_key,
        "new_full_pool_runner_up_retained": runner_key in retained, "frozen_authority": status,
        "full_pool_shadow_authority": status, "full_pool_shadow_reason": reason,
        "new_shortlist_shadow_authority": shortlist_status, "new_shortlist_shadow_reason": shortlist_reason,
        "font_scoring_text_authority": glyph_row["font_scoring_text_authority"],
    })


def repair(glyph: dict, font: dict, reduction: dict, decisions: dict) -> tuple[dict, dict, dict, dict]:
    glyph, font, reduction = copy.deepcopy(glyph), copy.deepcopy(font), copy.deepcopy(reduction)
    glyph_by = {item["identity"]: item for item in glyph["identities"]}
    font_by = {item["identity"]: item for item in font["identities"]}
    fonts = inference.discover_installed_fonts()
    results = []
    for decision in decisions["identities"]:
        row, keep = glyph_by[decision["identity"]], set(decision["keep_frames"])
        before = [int(item["source_frame"]) for item in row["observations"] if item.get("accepted")]
        if not keep <= set(before):
            raise ValueError(f"keep_frames are not accepted observations: {decision['identity']}")
        for observation in row["observations"]:
            if observation.get("accepted") and int(observation["source_frame"]) not in keep:
                observation["accepted"], observation["reason"] = False, "incompatible_visible_text_transition_state"
        old_font = copy.deepcopy(font_by[decision["identity"]])
        rebuild_mask(row)
        authority = {
            "text": decision.get("scoring_text_after"), "authority": "SOURCE_VISIBLE_PIXELS_BOUNDED_OWNERSHIP_DECISION",
            "reason": None, "source_frames": sorted(keep), "decision": decision["decision"],
        }
        row["font_scoring_text"] = decision.get("scoring_text_after")
        row["font_scoring_text_authority"] = authority
        row["accepted_mask_text_relationship"] = decision["relationship"]
        if decision.get("parent_text"):
            row["transition_fragment_parent_text"] = decision["parent_text"]
        font_by[decision["identity"]]["previous_transition_invalidated_ranking"] = old_font
        rerank(row, font_by[decision["identity"]], reduction, decision.get("scoring_text_after"), fonts)
        results.append({
            "identity": decision["identity"], "before_observations": before,
            "after_observations": [int(item["source_frame"]) for item in row["observations"] if item.get("accepted")],
            "rejected_observations": sorted(set(before) - keep), "ownership_decision": decision["decision"],
            "text_authority": authority, "mask_status": row["evidence_classification"],
            "font_rerank_required": bool(decision.get("scoring_text_after")),
            "final_state": decision["relationship"],
        })
    glyph["summary"] = dict(Counter(item["evidence_classification"] for item in glyph["identities"]))
    glyph.setdefault("ownership_corrections", []).extend(copy.deepcopy(decisions["identities"]))
    font["summary"] = dict(Counter(item["font_rerank_status"] for item in font["identities"]))
    font["authoritative_top_family_distribution"] = dict(Counter(item["top_candidates"][0]["family"] for item in font["identities"] if item["font_rerank_status"] == "AUTHORITATIVE_FONT_RANKING" and item.get("top_candidates")))
    reduction["identities"] = sorted(reduction["identities"], key=lambda item: item["identity"])
    reduction["gate_failed_identities"] = sorted(reduction["gate_failed_identities"], key=lambda item: item["identity"])
    reduction["gate_passing_identity_count"] = len(reduction["identities"])
    reduction["gate_failed_identity_count"] = len(reduction["gate_failed_identities"])
    reduction["full_pool_exact_comparisons"] = sum(int(item["full_pool_exact_comparisons"]) for item in reduction["identities"])
    reduction.setdefault("ownership_corrections", []).extend(copy.deepcopy(decisions["identities"]))
    return glyph, font, reduction, {"identities": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("glyph", "font", "candidate_reduction", "decisions", "output"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original = {name: load(getattr(args, name)) for name in ("glyph", "font", "candidate_reduction")}
    decisions = load(args.decisions)
    glyph, font, reduction, details = repair(original["glyph"], original["font"], original["candidate_reduction"], decisions)
    outputs = {
        "glyph": args.output / "reel2_glyph_evidence_v2_transition_corrected.json",
        "font": args.output / "reel2_known_region_font_rerank_transition_corrected.json",
        "candidate_reduction": args.output / "whole_reel_full_pool_benchmark_transition_corrected.json",
    }
    for name, value in (("glyph", glyph), ("font", font), ("candidate_reduction", reduction)):
        write(outputs[name], value)
    targets = {item["identity"] for item in decisions["identities"]}
    unchanged = all(
        [item for item in original[name]["identities"] if item["identity"] not in targets] == [item for item in value["identities"] if item["identity"] not in targets]
        for name, value in (("glyph", glyph), ("font", font), ("candidate_reduction", reduction))
    )
    validation = {
        "schema": "video_cloner_bounded_transition_observation_ownership_validation", "schema_version": 1,
        "result": "PASS_STEP_2B1_BOUNDED_OBSERVATION_OWNERSHIP_TRANSITION_REPAIR" if unchanged and len(glyph["identities"]) == 113 else "FAIL",
        "identity_count": len(glyph["identities"]), "bounded_identity_count": len(targets),
        "unrelated_identity_rows_unchanged": unchanged, **details,
        "input_hashes": {name: sha256(getattr(args, name)) for name in original},
        "output_hashes": {name: sha256(path) for name, path in outputs.items()},
    }
    write(args.output / "bounded_transition_ownership_validation.json", validation)
    if not validation["result"].startswith("PASS_"):
        raise SystemExit(validation["result"])


if __name__ == "__main__":
    main()
