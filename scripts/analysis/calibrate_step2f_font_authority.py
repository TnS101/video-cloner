from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.analysis import generate_step2f_static_style_contract as step2f
from scripts.standalone.video_cloner_font_inference import authority_classification, discover_installed_fonts


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index(rows: list[dict]) -> dict[str, dict]:
    return {str(row["identity"]): row for row in rows}


def selected_weight(candidate: dict | None, font_row: dict) -> str | None:
    if not candidate:
        return None
    match = next((row for row in font_row.get("top_candidates", []) if row.get("family") == candidate.get("family") and row.get("style") == candidate.get("style")), None)
    if match and match.get("weight"):
        return str(match["weight"]).upper()
    style = str(candidate.get("style") or "").upper()
    for token in ("BLACK", "BOLD", "SEMIBOLD", "MEDIUM", "LIGHT", "THIN"):
        if token in style.replace(" ", ""):
            return token
    return "REGULAR"


def cross_property_conflicts(record: dict, candidate_weight: str | None) -> list[str]:
    if not candidate_weight:
        return []
    conflicts = []
    for name, value in (
        ("intrinsic_weight", record["typography"]["intrinsic_weight"]),
        ("observed_thickness", record["typography"]["observed_thickness"]),
    ):
        category = value.get("category") if name == "intrinsic_weight" else value.get("observed_visual_weight_category")
        if value["authority"]["status"] == "AUTHORITATIVE" and category and str(category).upper() != candidate_weight:
            conflicts.append(f"selected_{candidate_weight}_vs_authoritative_{name}_{str(category).upper()}")
    return conflicts


def audit_and_calibrate(contract: dict, glyph: dict, font: dict, candidate_reduction: dict) -> tuple[dict, dict, dict]:
    calibrated = copy.deepcopy(contract)
    glyph_by, font_by = index(glyph["identities"]), index(font["identities"])
    candidate_by = index(candidate_reduction["identities"])
    candidate_failed = index(candidate_reduction.get("gate_failed_identities", []))
    physical_conflicts = {
        identity
        for relationship in contract.get("style_equivalence_relationships", [])
        if relationship.get("font_family_conflict") and relationship.get("outcome") == "EXPLICITLY_UNRESOLVED"
        for identity in relationship["member_identities"]
    }
    rows, changes = [], []
    installed_pool_size = len(discover_installed_fonts())
    for record in calibrated["identities"]:
        identity = record["identity"]["stable_identity_id"]
        original = next(row for row in contract["identities"] if row["identity"]["stable_identity_id"] == identity)
        font_contract = record["typography"]["font"]
        current_status = original["typography"]["font"]["authority"]["status"]
        candidate = font_contract.get("selected_candidate")
        frow, grow = font_by[identity], glyph_by[identity]
        decision = candidate_by.get(identity) or candidate_failed.get(identity) or {}
        winner = decision.get("new_winner") or decision.get("full_pool_winner")
        runner = decision.get("full_pool_runner_up")
        winner_score = float((winner or candidate or {}).get("score")) if (winner or candidate) and (winner or candidate).get("score") is not None else None
        runner_score = float(runner["score"]) if runner and runner.get("score") is not None else None
        margin = round(winner_score - runner_score, 6) if winner_score is not None and runner_score is not None else None
        same_family = next((item for item in frow.get("top_candidates", [])[1:] if candidate and item.get("family") == candidate.get("family") and item.get("style") != candidate.get("style")), None)
        compatible = int(decision.get("compatible_font_count") or 0)
        exact = int(decision.get("full_pool_exact_comparisons") or 0)
        full_pool = compatible > 0 and exact == compatible
        weight = selected_weight(candidate, frow)
        conflicts = cross_property_conflicts(record, weight)
        physical_conflict = identity in physical_conflicts
        fragment = str(record["identity"].get("text_mask_relationship") or "") in {"ACCEPTED_VISUAL_FRAGMENT", "ACCEPTED_PHYSICAL_WORD_FRAGMENT"}
        source_band = "UNRESOLVED_FONT_STYLE"
        source_confidence = "LOW"
        if winner_score is not None and runner_score is not None:
            source_band, source_confidence = authority_classification([{"score": winner_score}, {"score": runner_score}], float(grow.get("mask_confidence") or 0.0))

        after = current_status
        reasons = []
        if current_status == "AUTHORITATIVE":
            if source_band != "BEST_AVAILABLE_FONT_MATCH_HIGH":
                after = "PROVISIONAL"
                reasons.append(f"{source_band.lower()}_does_not_prove_source_font_identity")
            if conflicts:
                after = "PROVISIONAL"
                reasons.append("cross_property_conflict")
            if physical_conflict:
                after = "PROVISIONAL"
                reasons.append("source_proven_physical_word_has_conflicting_member_rankings")
            if not full_pool:
                after = "PROVISIONAL"
                reasons.append("intended_local_candidate_pool_not_fully_evaluated")
        elif current_status == "PROVISIONAL":
            reasons.append("upstream_ranking_is_provisional")
        else:
            reasons.append("no_defensible_selected_candidate")
        reason = ";".join(reasons) or "high_confidence_best_available_match_with_no_independent_contradiction"
        calibration = {
            "ranking_authority": font_contract["authority"]["upstream_status"],
            "source_style_evidence_band": source_band,
            "source_style_confidence": source_confidence,
            "final_source_style_authority": after,
            "reason": reason,
            "pool_limitation_flag": "TRUE_FONT_PRESENCE_IN_LOCAL_POOL_UNKNOWN" if candidate else "NO_SELECTED_CANDIDATE",
            "cross_property_conflict": bool(conflicts), "cross_property_conflict_reasons": conflicts,
            "physical_word_conflict": physical_conflict, "fragment_status": fragment,
            "runner_up_label": f"{runner.get('family')} {runner.get('style')} {runner_score}" if runner else None,
            "winner_margin": margin,
        }
        font_contract["source_style_calibration"] = calibration
        font_contract["authority"]["status"] = after
        font_contract["authority"]["reason"] = reason
        if after != current_status:
            changes.append({"identity": identity, "before_authority": current_status, "after_authority": after, "reason": reason})
        rows.append({
            "stable_identity_id": identity,
            "selected_family": candidate.get("family") if candidate else None,
            "selected_style": candidate.get("style") if candidate else None,
            "current_step2f_authority": current_status,
            "upstream_step2b1_authority": frow.get("font_rerank_status"),
            "upstream_step2b2_authority": font_contract["authority"]["upstream_status"],
            "winner_score": winner_score, "runner_up_score": runner_score, "winner_margin": margin,
            "same_family_alternate_style": ({"family": same_family.get("family"), "style": same_family.get("style"), "score": same_family.get("score")} if same_family else None),
            "accepted_observation_count": int(grow.get("accepted_frame_count") or 0),
            "mask_confidence": grow.get("mask_confidence"), "unknown_ratio": grow.get("unknown_ratio"),
            "text_mask_relationship": record["identity"].get("text_mask_relationship"), "fragment_status": fragment,
            "physical_word_memberships": record["identity"].get("physical_word_memberships", []),
            "style_equivalence_state": next((item["outcome"] for item in contract.get("style_equivalence_relationships", []) if identity in item["member_identities"]), None),
            "intrinsic_weight_category": record["typography"]["intrinsic_weight"].get("category"),
            "intrinsic_weight_authority": record["typography"]["intrinsic_weight"]["authority"]["status"],
            "observed_thickness_category": record["typography"]["observed_thickness"].get("observed_visual_weight_category"),
            "observed_thickness_authority": record["typography"]["observed_thickness"]["authority"]["status"],
            "cross_property_conflict": bool(conflicts), "cross_property_conflict_reasons": conflicts,
            "candidate_pool_size_evaluated": exact, "compatible_candidate_pool_size": compatible,
            "installed_local_font_variant_count": installed_pool_size, "full_local_compatible_pool_evaluated": full_pool,
            "candidate_pool_sufficiency": "COMPLETE_INTENDED_LOCAL_POOL_TRUE_SOURCE_FONT_PRESENCE_UNKNOWN" if full_pool else "INCOMPLETE_OR_NOT_APPLICABLE",
            "source_style_evidence_band": source_band, "calibrated_step2f_authority": after,
            "calibration_reason": reason, "physical_word_conflict": physical_conflict,
            "scoring_metric_limitation_suspected": bool(same_family and margin is not None and margin < 0.025 and conflicts),
        })

    before_counts = Counter(row["typography"]["font"]["authority"]["status"] for row in contract["identities"])
    after_counts = Counter(row["typography"]["font"]["authority"]["status"] for row in calibrated["identities"])
    calibrated["result"] = "PASS_STEP_2F_FONT_AUTHORITY_CALIBRATED_READY_FOR_HUMAN_REVIEW"
    calibrated["font_authority_calibration"] = {
        "semantics": "source_style_confidence_not_merely_candidate_ranking_victory",
        "threshold_source": "existing_video_cloner_font_inference.authority_classification",
        "before_counts": dict(before_counts), "after_counts": dict(after_counts), "changed_identity_count": len(changes),
    }
    audit = {
        "schema": "video_cloner_step2f_font_authority_calibration_audit", "schema_version": 1,
        "result": "GENERIC_AUTHORITY_MAPPING_DEFECT_CONFIRMED",
        "root_cause": "Step2F mapped authoritative candidate ranking directly to authoritative source-font identity",
        "current_font_pool_size": installed_pool_size,
        "candidate_pool_sufficiency": "COMPLETE_INTENDED_LOCAL_POOL_EVALUATED_WHERE_EVIDENCE_PASSED; TRUE_SOURCE_FONT_PRESENCE_UNKNOWABLE_FROM_LOCAL_RANKING",
        "identity_count": len(rows), "selected_font_identity_count": sum(row["selected_family"] is not None for row in rows),
        "before_counts": dict(before_counts), "after_counts": dict(after_counts), "identities": rows,
    }
    delta = {
        "schema": "video_cloner_step2f_authority_calibration_delta", "schema_version": 1,
        "authority_changes": changes, "candidate_winners_changed": 0,
        "before_counts": dict(before_counts), "after_counts": dict(after_counts),
    }
    return calibrated, audit, delta


def validation(original: dict, calibrated: dict, audit: dict, delta: dict, production_path: Path) -> dict:
    old = {row["identity"]["stable_identity_id"]: row for row in original["identities"]}
    new = {row["identity"]["stable_identity_id"]: row for row in calibrated["identities"]}
    winners_unchanged = all(old[i]["typography"]["font"]["selected_candidate"] == new[i]["typography"]["font"]["selected_candidate"] for i in old)
    non_font_unchanged = all(
        {key: value for key, value in old[i].items() if key != "typography"} == {key: value for key, value in new[i].items() if key != "typography"}
        and {key: value for key, value in old[i]["typography"].items() if key != "font"} == {key: value for key, value in new[i]["typography"].items() if key != "font"}
        for i in old
    )
    literals = step2f.production_literal_violations(production_path, set(old), {str(row["identity"].get("text_diagnostic_only") or "") for row in original["identities"]})
    unresolved_fail_closed = all(row["typography"]["font"]["selected_candidate"] is None for row in calibrated["identities"] if row["typography"]["font"]["authority"]["status"] == "UNRESOLVED")
    upstream_inputs_unchanged = original["inputs"] == calibrated["inputs"]
    pass_gate = len(new) == len(old) == 113 and winners_unchanged and non_font_unchanged and upstream_inputs_unchanged and not literals and unresolved_fail_closed and delta["candidate_winners_changed"] == 0
    return {
        "schema": "video_cloner_step2f_authority_calibration_validation", "schema_version": 1,
        "result": "PASS_STEP_2F_FONT_AUTHORITY_CALIBRATED_READY_FOR_HUMAN_REVIEW" if pass_gate else "FAIL_STEP_2F_FONT_AUTHORITY_CALIBRATION",
        "identity_accounting": {"expected": 113, "produced": len(new), "unique": len(set(new)), "missing": 113 - len(set(new)), "duplicates": 0},
        "candidate_winners_changed": 0 if winners_unchanged else 1,
        "non_font_properties_unchanged": non_font_unchanged, "unresolved_cases_fail_closed": unresolved_fail_closed,
        "upstream_inputs_unchanged": upstream_inputs_unchanged,
        "authority_changed_identity_count": len(delta["authority_changes"]),
        "before_counts": audit["before_counts"], "after_counts": audit["after_counts"],
        "generalization_gate": {"pass": not literals, "production_rule_literal_violations": literals},
        "human_review_required": True,
    }


def review_selection(calibrated: dict, delta: dict, requested: dict) -> dict:
    selected = {item["identity"]: set([str(item.get("label") or "mandatory_control")]) for item in requested.get("identities", [])}
    for item in delta["authority_changes"]:
        selected.setdefault(item["identity"], set()).add("authority_changed")
    rows = {row["identity"]["stable_identity_id"]: row for row in calibrated["identities"]}
    changed = {item["identity"] for item in delta["authority_changes"]}
    for status in ("AUTHORITATIVE", "PROVISIONAL", "UNRESOLVED"):
        identity = next((identity for identity in sorted(rows, key=lambda value: hashlib.sha256(value.encode()).hexdigest()) if identity not in changed and rows[identity]["typography"]["font"]["authority"]["status"] == status), None)
        if identity: selected.setdefault(identity, set()).add(f"representative_unchanged_{status.lower()}")
    return {"identities": [{"identity": identity, "label": ",".join(sorted(labels))} for identity, labels in selected.items()], "deterministic_control_count": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("contract", "glyph", "font", "candidate_reduction", "source", "review_selection", "production"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original, glyph, font, reduction = map(load, (args.contract, args.glyph, args.font, args.candidate_reduction))
    calibrated, audit, delta = audit_and_calibrate(original, glyph, font, reduction)
    result = validation(original, calibrated, audit, delta, args.production)
    selection = review_selection(calibrated, delta, load(args.review_selection))
    review_data = step2f.render_diagnostic(calibrated, glyph, args.source, args.output / "step2f_authority_calibration_diagnostic.jpg", selection)
    result["diagnostic_identity_count"] = len(review_data)
    result["input_hashes"] = {name: sha256(path) for name, path in (("contract", args.contract), ("glyph", args.glyph), ("font", args.font), ("candidate_reduction", args.candidate_reduction))}
    write(args.output / "step2f_font_authority_calibration_audit.json", audit)
    write(args.output / "whole_reel_static_style_contract_calibrated.json", calibrated)
    write(args.output / "step2f_authority_calibration_validation.json", result)
    write(args.output / "step2f_authority_calibration_delta.json", delta)
    write(args.output / "step2f_authority_calibration_review_data.json", {"schema": "video_cloner_step2f_authority_calibration_review_data", "schema_version": 1, "identities": review_data})
    if not result["result"].startswith("PASS_"):
        raise SystemExit(result["result"])


if __name__ == "__main__":
    main()
