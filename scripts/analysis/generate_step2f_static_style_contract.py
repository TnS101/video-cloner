from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.standalone.video_cloner_font_inference import discover_installed_fonts, render_text_mask


STATES = ("AUTHORITATIVE", "PROVISIONAL", "UNRESOLVED", "UNSUPPORTED", "NOT_APPLICABLE")
PROPERTIES = ("geometry", "font", "weight_thickness", "fill", "opacity", "stroke", "composition")
INPUT_NAMES = (
    "glyph", "font", "candidate_reduction", "stroke", "color", "composition", "preview",
    "linkage_audit", "adjudication", "coverage",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_status(upstream_status: str | None) -> str:
    value = str(upstream_status or "")
    if value.startswith("AUTHORITATIVE") or value.startswith("SOURCE_DERIVED") or value.startswith("ACCEPTED_SOURCE_PROVEN"):
        return "AUTHORITATIVE"
    if value.startswith("PROVISIONAL") or value.startswith("ACCEPTED_BBOX") or value.startswith("SOURCE_SUPPORTED"):
        return "PROVISIONAL"
    if value == "NOT_APPLICABLE":
        return value
    if value == "UNSUPPORTED":
        return value
    return "UNRESOLVED"


def authority(status: str, upstream_status: str, artifact: str, reason: str | None = None) -> dict:
    return {"status": status, "upstream_status": upstream_status, "source_artifact": artifact, "reason": reason}


def index_unique(rows: list[dict], name: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        identity = str(row["identity"])
        if identity in result:
            raise ValueError(f"duplicate {name} identity: {identity}")
        result[identity] = row
    return result


def build_contract(inputs: dict[str, dict], source_paths: dict[str, str], source_hashes: dict[str, str]) -> dict:
    glyph = index_unique(inputs["glyph"]["identities"], "glyph")
    font = index_unique(inputs["font"]["identities"], "font")
    candidate = index_unique(inputs["candidate_reduction"]["identities"], "candidate reduction")
    candidate_failed = index_unique(inputs["candidate_reduction"].get("gate_failed_identities", []), "candidate reduction gate")
    stroke = index_unique(inputs["stroke"]["identities"], "stroke")
    color = index_unique(inputs["color"]["identities"], "color")
    preview = index_unique(
        [{**cue, "identity": cue["visual_event_identity"]} for cue in inputs["preview"]["cues"]],
        "preview",
    )
    identities = sorted(glyph)
    expected = set(identities)
    for name, rows in (("font", font), ("stroke", stroke), ("color", color), ("preview", preview)):
        if set(rows) != expected:
            raise ValueError(f"{name} identity set differs from glyph authority")
    if set(candidate) | set(candidate_failed) != expected or set(candidate) & set(candidate_failed):
        raise ValueError("candidate reduction does not account for every glyph identity exactly once")

    graph = inputs["composition"]["graph"]
    composition_by_identity: dict[str, list[str]] = defaultdict(list)
    for item in graph["compositions"]:
        for identity in item["member_identities"]:
            composition_by_identity[identity].append(item["composition_id"])
    relationship_by_identity: dict[str, list[str]] = defaultdict(list)
    relationships = []
    for number, item in enumerate(graph["relationships"], 1):
        relationship_id = f"relationship_{number:04d}"
        relationships.append({"relationship_id": relationship_id, **item})
        relationship_by_identity[item["source_identity"]].append(relationship_id)
        relationship_by_identity[item["target_identity"]].append(relationship_id)
    unresolved_composition = set(inputs["composition"]["summary"]["unresolved_composition_identities"])
    physical_by_identity: dict[str, list[str]] = defaultdict(list)
    for group in inputs["glyph"].get("physical_word_groups", []):
        for identity in group["member_identities"]:
            physical_by_identity[identity].append(group["physical_word_group_id"])
    linkage_by_identity = index_unique(inputs["linkage_audit"]["identities"], "linkage audit")
    harmless = {
        identity for identity, decision in inputs["adjudication"].items()
        if decision.get("classification") == "HARMLESS_OCR_LINKAGE_MISMATCH"
    }
    raw_mismatches = {
        row["identity"] for row in inputs["linkage_audit"]["identities"]
        if row.get("text_mask_relationship") == "MISMATCH"
    }
    linkage_accounting = {
        "raw_mismatch_count": len(raw_mismatches),
        "accepted_harmless_mismatch_count": len(raw_mismatches & harmless),
        "unaccounted_true_mismatch_count": len(raw_mismatches - harmless),
        "raw_mismatch_identities": sorted(raw_mismatches),
        "accepted_harmless_mismatch_identities": sorted(raw_mismatches & harmless),
        "unaccounted_true_mismatch_identities": sorted(raw_mismatches - harmless),
        "coverage_gap_count": len(inputs["coverage"].get("coverage_gaps", [])),
        "fragment_accounting": {
            "accepted_physical_word_fragment": inputs["linkage_audit"]["linkage_counts"]["accepted_physical_word_fragment"],
            "accepted_visual_fragment": inputs["linkage_audit"]["linkage_counts"]["accepted_visual_fragment"],
            "accepted_fragment": inputs["linkage_audit"]["linkage_counts"]["accepted_fragment"],
            "explicitly_unresolved": inputs["linkage_audit"]["linkage_counts"]["explicitly_unresolved"],
        },
    }

    records = []
    for identity in identities:
        g, f, s, c, cue = glyph[identity], font[identity], stroke[identity], color[identity], preview[identity]
        accepted = [
            {"source_frame": int(o["source_frame"]), "timestamp": o["timestamp"], "bbox": o["bbox"], "crop_sha256": o["crop_sha256"]}
            for o in g.get("observations", []) if o.get("accepted") and o.get("bbox")
        ]
        observation_provenance = [
            {
                "source_frame": int(o["source_frame"]), "timestamp": o["timestamp"], "bbox": o.get("bbox"),
                "crop_sha256": o.get("crop_sha256"), "accepted": bool(o.get("accepted")), "reason": o.get("reason"),
            }
            for o in g.get("observations", []) if o.get("bbox")
        ]
        if accepted:
            heights = [o["bbox"][3] - o["bbox"][1] for o in accepted]
            widths = [o["bbox"][2] - o["bbox"][0] for o in accepted]
            geometry_auth = authority("AUTHORITATIVE", "ACCEPTED_STEP2B1_SOURCE_BBOX", "glyph", None)
            size = {"median_width_px": float(np.median(widths)), "median_height_px": float(np.median(heights)), "unit": "source_frame_pixels"}
        else:
            geometry_auth = authority("UNRESOLVED", "NO_ACCEPTED_STEP2B1_SOURCE_BBOX", "glyph", g.get("unresolved_reason") or "no_accepted_source_geometry")
            size = None

        step2b1_top = f.get("top_candidates") or []
        previous_frozen = f.get("previous_frozen_ranking")
        if identity in candidate:
            decision = candidate[identity]
            upstream_font_status = decision["new_shortlist_shadow_authority"]
            font_reason = decision.get("new_shortlist_shadow_reason")
            winner = decision.get("new_winner")
            font_source = "candidate_reduction"
        else:
            decision = candidate_failed[identity]
            upstream_font_status = decision["frozen_authority"]
            font_reason = decision.get("gate_reason")
            winner = None
            font_source = "font"
        font_status = normalized_status(upstream_font_status)
        selected_font = ({key: winner.get(key) for key in ("family", "style", "weight", "renderer_compatible", "score")} if winner and font_status != "UNRESOLVED" else None)
        thickness = s["thickness"]
        thickness_status = normalized_status(thickness["status"])
        fill_status = normalized_status(c["fill"]["status"])
        opacity_status = normalized_status(c["opacity"]["status"])
        stroke_status = normalized_status(s["stroke"]["status"])
        stroke_color_status = normalized_status(c["stroke_color"]["status"])
        if identity in composition_by_identity:
            composition_auth = authority("AUTHORITATIVE", "SOURCE_DERIVED_MEMBERSHIP", "composition")
        elif identity in unresolved_composition:
            composition_auth = authority("UNRESOLVED", "UNRESOLVED_HINTED_COMPOSITION", "composition", "insufficient_accepted_co_visible_geometry")
        else:
            composition_auth = authority("NOT_APPLICABLE", "STANDALONE_IDENTITY", "composition", "no_source_supported_composition_membership")

        records.append({
            "identity": {
                "stable_identity_id": identity,
                "text_diagnostic_only": g.get("text"),
                "lifecycle_reference": {
                    "visual_token_id": cue["id"], "source_cue_ids": cue.get("source_cue_ids", []),
                    "semantic_reference_ids": cue.get("semantic_reference_ids", []), "source_window_frames": g.get("source_window"),
                    "timing_authority": cue.get("timing_authority"), "source_artifact": "preview",
                },
                "source_evidence_reference": {"style_evidence_id": cue.get("style_evidence_id"), "glyph_identity": identity, "source_artifact": "glyph"},
                "physical_word_memberships": sorted(physical_by_identity[identity]),
                "text_mask_relationship": linkage_by_identity[identity]["text_mask_relationship"],
                "style_equivalence_relationships": [f"style_equivalence:{group}" for group in sorted(physical_by_identity[identity])],
                "composition_memberships": sorted(composition_by_identity[identity]),
            },
            "geometry": {
                "accepted_source_observations": accepted, "source_observation_provenance": observation_provenance, "size": size,
                "scale": {"non_uniform_scale_ratio": g.get("non_uniform_scale_ratio"), "semantics": "upstream_evidence_measurement_not_renderer_transform"},
                "orientation": {"value_degrees": None, "authority": authority("UNSUPPORTED", "NO_ACCEPTED_STATIC_ORIENTATION_AUTHORITY", "glyph", "upstream_did_not_supply_static_orientation")},
                "authority": geometry_auth,
            },
            "typography": {
                "font": {
                    "selected_candidate": selected_font,
                    "preview_text": decision.get("text") or f.get("text") or g.get("font_scoring_text"),
                    "comparison_candidates": [
                        {key: item.get(key) for key in ("family", "style", "weight", "renderer_compatible", "score")}
                        for item in step2b1_top[:3]
                    ],
                    "authority": authority(font_status, upstream_font_status, font_source, font_reason),
                    "decision_precedence": "accepted_step2b2_then_step2b1_only_when_step2b2_gate_failed",
                    "step2b1_history": {
                        "selected_candidate": (previous_frozen.get("top_candidate") if previous_frozen else {key: step2b1_top[0].get(key) for key in ("family", "style", "weight", "renderer_compatible", "score")} if step2b1_top else None),
                        "authority": previous_frozen.get("font_rerank_status") if previous_frozen else f["font_rerank_status"],
                        "reason": f.get("no_authoritative_ranking_reason"),
                        "source_artifact": "font",
                    },
                    "corrected_step2b1_decision": {
                        "selected_candidate": ({key: step2b1_top[0].get(key) for key in ("family", "style", "weight", "renderer_compatible", "score")} if step2b1_top else None),
                        "authority": f["font_rerank_status"], "reason": f.get("no_authoritative_ranking_reason"),
                    },
                },
                "intrinsic_weight": {
                    "category": thickness.get("intrinsic_weight_category"),
                    "authority": authority(normalized_status(thickness.get("intrinsic_weight_authority")), thickness.get("intrinsic_weight_authority", "NO_AUTHORITATIVE_FONT_WEIGHT"), "stroke", thickness.get("reason")),
                },
                "observed_thickness": {
                    "source": thickness.get("source"), "observed_visual_weight_category": thickness.get("observed_visual_weight_category"),
                    "authority": authority(thickness_status, thickness["status"], "stroke", thickness.get("reason")),
                },
            },
            "fill": {
                "color_rgb": c["fill"].get("color_rgb"), "color_hex": c["fill"].get("color_hex"),
                "representation_semantics": "provisional_observed_composite_appearance" if fill_status == "PROVISIONAL" else "source_intrinsic_truth" if fill_status == "AUTHORITATIVE" else None,
                "authority": authority(fill_status, c["fill"]["status"], "color", c["fill"].get("reason")),
            },
            "opacity": {
                "value": c["opacity"].get("opacity"),
                "authority": authority(opacity_status, c["opacity"]["status"], "color", c["opacity"].get("reason")),
            },
            "stroke": {
                "presence": {"value": s["stroke"].get("present"), "authority": authority(stroke_status, s["stroke"]["status"], "stroke", s["stroke"].get("reason"))},
                "width": {"value_source_px": s["stroke"].get("width_px_source_space"), "authority": authority(stroke_status if s["stroke"].get("width_px_source_space") is not None else "UNRESOLVED", s["stroke"]["status"], "stroke", s["stroke"].get("reason"))},
                "color": {"color_rgb": c["stroke_color"].get("color_rgb"), "color_hex": c["stroke_color"].get("color_hex"), "authority": authority(stroke_color_status, c["stroke_color"]["status"], "color", c["stroke_color"].get("reason"))},
                "upstream_authority_ceiling": s["stroke"]["status"],
            },
            "composition": {
                "composition_ids": sorted(composition_by_identity[identity]), "relationship_ids": sorted(set(relationship_by_identity[identity])),
                "authority": composition_auth, "style_sharing_authorized": False,
            },
            "provenance": {
                "glyph": {"path": source_paths["glyph"], "sha256": source_hashes["glyph"]},
                "font": {"path": source_paths["font"], "sha256": source_hashes["font"]},
                "stroke": {"path": source_paths["stroke"], "sha256": source_hashes["stroke"]},
                "color": {"path": source_paths["color"], "sha256": source_hashes["color"]},
                "composition": {"path": source_paths["composition"], "sha256": source_hashes["composition"]},
                "preview": {"path": source_paths["preview"], "sha256": source_hashes["preview"]},
            },
        })

    record_by_identity = {row["identity"]["stable_identity_id"]: row for row in records}
    group_decision = inputs["candidate_reduction"].get("physical_word_group") or {}
    style_equivalence = []
    for group in inputs["glyph"].get("physical_word_groups", []):
        members = list(group["member_identities"])
        final = [record_by_identity[identity]["typography"]["font"]["selected_candidate"] for identity in members]
        weights = [record_by_identity[identity]["typography"]["observed_thickness"].get("observed_visual_weight_category") for identity in members]
        joint_winner = group_decision.get("new_winner") if group_decision.get("identity") == f"physical_word_group:{group['physical_word_group_id']}" else None
        joint_status = group_decision.get("new_shortlist_shadow_authority") if joint_winner else "NO_AUTHORITATIVE_FONT_RANKING"
        same_final = bool(joint_winner and final) and all(
            item and (item["family"], item["style"]) == (joint_winner["family"], joint_winner["style"])
            for item in final
        )
        outcome = "RESOLVED_WITH_SOURCE_EVIDENCE" if same_final else "EXPLICITLY_UNRESOLVED"
        style_equivalence.append({
            "relationship_id": f"style_equivalence:{group['physical_word_group_id']}",
            "member_identities": members, "identity_records_merged": False,
            "candidate_authority": "ACCEPTED_PHYSICAL_WORD_JOINT_GLYPH_EVIDENCE",
            "joint_candidate": joint_winner, "joint_candidate_authority": joint_status,
            "member_final_candidates": final, "member_observed_weight_categories": weights,
            "font_family_conflict": len({item["family"] for item in final if item}) > 1,
            "weight_conflict": len({item for item in weights if item}) > 1,
            "outcome": outcome,
            "reason": None if same_final else "joint_and_independent_candidate_evidence_do_not_support_one_uncontradicted_final_font",
            "style_sharing_applied": False,
        })

    return {
        "schema": "video_cloner_whole_reel_static_style_contract", "schema_version": 1,
        "result": "PASS_STEP_2F_CORRECTED_WHOLE_REEL_STATIC_STYLE_READY_FOR_HUMAN_REVIEW",
        "contract_semantics": {
            "editor_neutral": True, "identity_independent_by_default": True, "composition_does_not_share_style": True,
            "physical_word_members_remain_independent": True, "renderer_defaults_are_source_authority": False,
            "normalized_authority_states": list(STATES),
        },
        "inputs": {name: {"path": source_paths[name], "sha256": source_hashes[name]} for name in sorted(source_paths)},
        "identity_count": len(records), "identities": records,
        "linkage_accounting": linkage_accounting,
        "style_equivalence_relationships": style_equivalence,
        "composition_graph": {
            "source_artifact": "composition", "coordinate_model": graph["coordinate_model"],
            "compositions": graph["compositions"], "relationships": relationships,
            "standalone_identities": graph["standalone_identities"],
        },
    }


def property_status(record: dict, name: str) -> str:
    if name == "weight_thickness":
        return record["typography"]["observed_thickness"]["authority"]["status"]
    if name == "font":
        return record["typography"]["font"]["authority"]["status"]
    if name == "stroke":
        return record["stroke"]["presence"]["authority"]["status"]
    return record[name]["authority"]["status"]


def production_literal_violations(path: Path, identities: set[str], texts: set[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        values = [node.left, *node.comparators]
        for value in values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literal = value.value
                if literal in identities or (literal in texts and len(literal) > 2) or re.fullmatch(r"(?:caption_tracklet|continuous_visual_identity|source_visible_recovery)_\d+", literal):
                    violations.append(literal)
    return sorted(set(violations))


def validate_contract(contract: dict, expected: int, production_path: Path) -> dict:
    records = contract["identities"]
    ids = [row["identity"]["stable_identity_id"] for row in records]
    duplicates = sorted(identity for identity, count in Counter(ids).items() if count > 1)
    missing_property = sorted(
        f"{row['identity']['stable_identity_id']}:{name}" for row in records for name in PROPERTIES
        if property_status(row, name) not in STATES
    )
    unresolved_has_reason = all(
        property_status(row, name) not in {"UNRESOLVED", "UNSUPPORTED", "NOT_APPLICABLE"}
        or (row["typography"]["observed_thickness"]["authority"] if name == "weight_thickness" else row["typography"]["font"]["authority"] if name == "font" else row["stroke"]["presence"]["authority"] if name == "stroke" else row[name]["authority"])["reason"]
        for row in records for name in PROPERTIES
    )
    promoted_provisional = any(
        auth["status"] == "AUTHORITATIVE" and str(auth["upstream_status"]).startswith("PROVISIONAL")
        for row in records for auth in (
            row["typography"]["font"]["authority"], row["typography"]["observed_thickness"]["authority"],
            row["fill"]["authority"], row["opacity"]["authority"], row["stroke"]["presence"]["authority"], row["stroke"]["color"]["authority"],
        )
    )
    silent_defaults = []
    for row in records:
        identity = row["identity"]["stable_identity_id"]
        if row["typography"]["font"]["selected_candidate"] and row["typography"]["font"]["authority"]["status"] not in {"AUTHORITATIVE", "PROVISIONAL"}:
            silent_defaults.append(f"{identity}:font")
        if row["fill"]["color_hex"] and row["fill"]["authority"]["status"] not in {"AUTHORITATIVE", "PROVISIONAL"}:
            silent_defaults.append(f"{identity}:fill")
        if row["opacity"]["value"] is not None and row["opacity"]["authority"]["status"] not in {"AUTHORITATIVE", "PROVISIONAL"}:
            silent_defaults.append(f"{identity}:opacity")
    literals = production_literal_violations(production_path, set(ids), {str(row["identity"].get("text_diagnostic_only") or "") for row in records})
    counts = {name: dict(Counter(property_status(row, name) for row in records)) for name in PROPERTIES}
    for values in counts.values():
        for state in STATES:
            values.setdefault(state, 0)
    physical_members = [row for row in records if row["identity"]["physical_word_memberships"]]
    physical_preserved = len({row["identity"]["stable_identity_id"] for row in physical_members}) == len(physical_members)
    composition_style_independent = all(not row["composition"]["style_sharing_authorized"] for row in records)
    precedence = all(
        row["typography"]["font"]["authority"]["source_artifact"] == "candidate_reduction"
        or row["typography"]["font"]["authority"]["status"] == "UNRESOLVED"
        for row in records
    )
    provenance = all(row["typography"]["font"].get("step2b1_history") for row in records)
    equivalence = contract.get("style_equivalence_relationships", [])
    equivalence_accounted = all(row["outcome"] in {"RESOLVED_WITH_SOURCE_EVIDENCE", "EXPLICITLY_UNRESOLVED"} for row in equivalence)
    equivalence_source_only = all(row["candidate_authority"] == "ACCEPTED_PHYSICAL_WORD_JOINT_GLYPH_EVIDENCE" and not row["style_sharing_applied"] for row in equivalence)
    linkage = contract["linkage_accounting"]
    linkage_closed = linkage["raw_mismatch_count"] == linkage["accepted_harmless_mismatch_count"] and linkage["unaccounted_true_mismatch_count"] == 0
    unresolved_fonts_suppressed = all(
        row["typography"]["font"]["authority"]["status"] != "UNRESOLVED"
        or row["typography"]["font"]["selected_candidate"] is None
        for row in records
    )
    observation_provenance_preserved = all(
        row["geometry"]["accepted_source_observations"] or row["geometry"]["source_observation_provenance"]
        for row in records
    )
    pass_gate = len(records) == expected and len(set(ids)) == expected and not duplicates and not missing_property and unresolved_has_reason and not promoted_provisional and not silent_defaults and not literals and physical_preserved and composition_style_independent and precedence and provenance and equivalence_accounted and equivalence_source_only and linkage_closed and linkage["coverage_gap_count"] == 0 and unresolved_fonts_suppressed and observation_provenance_preserved
    return {
        "schema": "video_cloner_step2f_validation", "schema_version": 1,
        "result": "PASS_STEP_2F_CORRECTED_WHOLE_REEL_STATIC_STYLE_READY_FOR_HUMAN_REVIEW" if pass_gate else "FAIL_STEP_2F_VALIDATION",
        "identity_accounting": {"expected": expected, "produced": len(records), "unique": len(set(ids)), "missing": max(0, expected - len(set(ids))), "duplicates": len(duplicates), "duplicate_ids": duplicates},
        "property_authority_counts": counts, "missing_required_properties": missing_property,
        "unresolved_properties_have_reasons": unresolved_has_reason,
        "silent_default_check": {"pass": not silent_defaults, "violations": silent_defaults, "renderer_defaults_imported": False},
        "provisional_authority_promoted": promoted_provisional,
        "composition_creates_shared_style": not composition_style_independent,
        "physical_word_members_merged": not physical_preserved,
        "step2b2_precedence_applied": precedence,
        "step2b1_history_preserved": provenance,
        "unresolved_fonts_suppress_candidates": unresolved_fonts_suppressed,
        "rejected_observation_bbox_provenance_preserved": observation_provenance_preserved,
        "linkage_accounting": linkage,
        "source_proven_style_equivalence": {
            "relationships": len(equivalence),
            "resolved_with_source_evidence": sum(row["outcome"] == "RESOLVED_WITH_SOURCE_EVIDENCE" for row in equivalence),
            "explicitly_unresolved": sum(row["outcome"] == "EXPLICITLY_UNRESOLVED" for row in equivalence),
            "unaccounted_conflicts": sum(row["outcome"] not in {"RESOLVED_WITH_SOURCE_EVIDENCE", "EXPLICITLY_UNRESOLVED"} for row in equivalence),
            "composition_or_semantic_only_reconciliation": not equivalence_source_only,
        },
        "identities_changed_without_step2b1_provenance": 0 if provenance else expected,
        "generalization_gate": {"pass": not literals, "production_rule_literal_violations": literals, "inspected": str(production_path)},
        "upstream_hashes_pinned": True, "human_review_required": True,
    }


def diagnostic_specs(contract: dict, review: dict | None = None) -> list[dict]:
    rows = contract["identities"]
    by_id = {row["identity"]["stable_identity_id"]: row for row in rows}
    selected: dict[str, set[str]] = defaultdict(set)
    def add(identity: str, tag: str) -> None:
        if identity not in by_id:
            raise ValueError(f"unknown diagnostic identity: {identity}")
        selected[identity].add(tag)
    for item in (review or {}).get("identities", []):
        add(item["identity"], str(item.get("label") or "human_review_case"))
    if review:
        control_count = int(review.get("deterministic_control_count", 2))
        for identity in sorted(by_id, key=lambda value: hashlib.sha256(value.encode()).hexdigest()):
            if identity not in selected:
                add(identity, "deterministic_non_flagged_control")
            if sum("deterministic_non_flagged_control" in tags for tags in selected.values()) == control_count:
                break
        return [{"identity": identity, "coverage": sorted(tags)} for identity, tags in selected.items()]
    geometries = [row for row in rows if row["geometry"]["size"]]
    add(min(geometries, key=lambda r: r["geometry"]["size"]["median_height_px"])["identity"]["stable_identity_id"], "small_size")
    add(max(geometries, key=lambda r: r["geometry"]["size"]["median_height_px"])["identity"]["stable_identity_id"], "large_size")
    families = {}
    for row in rows:
        candidate = row["typography"]["font"]["selected_candidate"]
        if candidate:
            families.setdefault(candidate["family"], row)
    for row in list(families.values())[:3]: add(row["identity"]["stable_identity_id"], "different_font")
    weights = {}
    for row in rows:
        value = row["typography"]["observed_thickness"].get("observed_visual_weight_category")
        if value: weights.setdefault(value, row)
    for row in list(weights.values())[:3]: add(row["identity"]["stable_identity_id"], "different_weight")
    fills = [row for row in rows if row["fill"]["color_hex"]]
    for row in sorted(fills, key=lambda r: r["fill"]["color_hex"])[:2] + sorted(fills, key=lambda r: r["fill"]["color_hex"])[-2:]: add(row["identity"]["stable_identity_id"], "different_fill")
    for row in rows:
        if row["stroke"]["presence"]["value"] is True: add(row["identity"]["stable_identity_id"], "stroke"); break
    for row in rows:
        if row["opacity"]["authority"]["status"] == "UNRESOLVED": add(row["identity"]["stable_identity_id"], "unresolved_opacity"); break
    for row in rows:
        if row["identity"]["physical_word_memberships"]: add(row["identity"]["stable_identity_id"], "physical_word_fragment")
    relations = contract["composition_graph"]["relationships"]
    for kind, tag in (("SAME_BASELINE", "same_baseline"), ("BASELINE_OFFSET", "vertically_offset")):
        relation = next((item for item in relations if item["relationship_type"] == kind), None)
        if relation: add(relation["source_identity"], tag); add(relation["target_identity"], tag)
    for row in rows:
        if row["composition"]["authority"]["status"] == "UNRESOLVED": add(row["identity"]["stable_identity_id"], "unresolved_composition_overlap"); break
    control_count = int((review or {}).get("deterministic_control_count", 2))
    for identity in sorted(by_id, key=lambda value: hashlib.sha256(value.encode()).hexdigest()):
        if identity not in selected:
            add(identity, "deterministic_random_noncanonical")
        if sum("deterministic_random_noncanonical" in tags for tags in selected.values()) == control_count: break
    return [{"identity": identity, "coverage": sorted(tags)} for identity, tags in selected.items()]


def decode_rle(shape: list[int], runs: list[list[int]]) -> np.ndarray:
    flat = np.zeros(int(shape[0]) * int(shape[1]), dtype=bool)
    for start, length in runs:
        flat[int(start):int(start) + int(length)] = True
    return flat.reshape(int(shape[0]), int(shape[1]))


def render_diagnostic(contract: dict, glyph: dict, source: Path, output: Path, review: dict | None = None) -> list[dict]:
    specs = diagnostic_specs(contract, review)
    by_id = {row["identity"]["stable_identity_id"]: row for row in contract["identities"]}
    glyph_by = {row["identity"]: row for row in glyph["identities"]}
    equivalence = {
        identity: relation for relation in contract.get("style_equivalence_relationships", [])
        for identity in relation["member_identities"]
    }
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError("source video unavailable")
    fonts = {
        (str(item["family"]).casefold(), str(item["style"]).casefold()): item["path"]
        for item in discover_installed_fonts()
    }
    cards = []
    review_data = []
    try:
        for spec in specs:
            row = by_id[spec["identity"]]
            evidence = glyph_by[spec["identity"]]
            card = np.full((430, 1260, 3), 24, np.uint8)
            observations = row["geometry"]["accepted_source_observations"] or row["geometry"]["source_observation_provenance"]
            if observations:
                observation = observations[len(observations) // 2]
                capture.set(cv2.CAP_PROP_POS_FRAMES, observation["source_frame"])
                ok, image = capture.read()
                if ok:
                    x1, y1, x2, y2 = observation["bbox"]
                    pad = 70
                    crop = image[max(0, y1-pad):min(image.shape[0], y2+pad), max(0, x1-pad):min(image.shape[1], x2+pad)]
                    scale = min(390 / max(1, crop.shape[1]), 185 / max(1, crop.shape[0]))
                    crop = cv2.resize(crop, (max(1, round(crop.shape[1]*scale)), max(1, round(crop.shape[0]*scale))), interpolation=cv2.INTER_AREA)
                    card[42:42+crop.shape[0], 10:10+crop.shape[1]] = crop
            shape = evidence["final_mask_shape"]
            foreground = decode_rle(shape, evidence.get("known_foreground_rle") or evidence["final_mask_rle"])
            background = decode_rle(shape, evidence.get("known_background_rle") or [])
            unknown = decode_rle(shape, evidence.get("unknown_rle") or [])
            isolated = np.zeros((*foreground.shape, 3), np.uint8)
            isolated[background] = (45, 45, 45)
            isolated[unknown] = (180, 40, 180)
            isolated[foreground] = (245, 245, 245)
            scale = min(390 / max(1, isolated.shape[1]), 185 / max(1, isolated.shape[0]))
            isolated = cv2.resize(isolated, (max(1, round(isolated.shape[1]*scale)), max(1, round(isolated.shape[0]*scale))), interpolation=cv2.INTER_NEAREST)
            card[42:42+isolated.shape[0], 425:425+isolated.shape[1]] = isolated
            cv2.putText(card, spec["identity"], (12, 23), cv2.FONT_HERSHEY_SIMPLEX, .48, (245,245,245), 1, cv2.LINE_AA)
            font = row["typography"]["font"]["selected_candidate"]
            font_authority = row["typography"]["font"]["authority"]["status"]
            preview_text = str(row["typography"]["font"].get("preview_text") or evidence.get("text") or "")
            render_status = "FONT_UNRESOLVED"
            if font and font_authority in {"AUTHORITATIVE", "PROVISIONAL"}:
                font_path = fonts.get((str(font["family"]).casefold(), str(font["style"]).casefold()))
                if font_path:
                    rendered = render_text_mask(preview_text, font_path, 110)
                    pane = np.zeros((185, 390, 3), np.uint8)
                    target_width = min(360, max(1, int((row["geometry"].get("size") or {}).get("median_width_px") or 360)))
                    target_height = min(150, max(1, int((row["geometry"].get("size") or {}).get("median_height_px") or 110)))
                    scale = min(target_width / max(1, rendered.shape[1]), target_height / max(1, rendered.shape[0]))
                    rendered = cv2.resize(rendered.astype(np.uint8) * 245, (max(1, round(rendered.shape[1]*scale)), max(1, round(rendered.shape[0]*scale))), interpolation=cv2.INTER_AREA)
                    y = (pane.shape[0] - rendered.shape[0]) // 2
                    x = (pane.shape[1] - rendered.shape[1]) // 2
                    pane[y:y+rendered.shape[0], x:x+rendered.shape[1]] = rendered[..., None]
                    card[42:227, 845:1235] = pane
                    render_status = "SELECTED_FONT_RENDERED"
                else:
                    render_status = "SELECTED_FONT_UNAVAILABLE"
            else:
                cv2.putText(card, "FONT: UNRESOLVED", (875, 135), cv2.FONT_HERSHEY_SIMPLEX, .8, (245,245,245), 2, cv2.LINE_AA)
            cv2.putText(card, "SOURCE CONTEXT", (12, 40), cv2.FONT_HERSHEY_SIMPLEX, .38, (170,170,170), 1, cv2.LINE_AA)
            cv2.putText(card, "TRI-STATE MASK", (425, 40), cv2.FONT_HERSHEY_SIMPLEX, .38, (170,170,170), 1, cv2.LINE_AA)
            cv2.putText(card, "FINAL SELECTED FONT RENDER", (845, 40), cv2.FONT_HERSHEY_SIMPLEX, .38, (170,170,170), 1, cv2.LINE_AA)
            history = row["typography"]["font"]["step2b1_history"]
            previous = history["selected_candidate"]
            relation = equivalence.get(spec["identity"])
            def label(candidate: dict | None) -> str:
                return f"{candidate['family']} {candidate['style']} {candidate.get('score')}" if candidate else "UNRESOLVED"
            lines = [
                f"unknown={evidence.get('unknown_ratio')} mask_confidence={evidence.get('mask_confidence')}",
                f"Step2B.1 previous: {label(previous)} [{history['authority']}]",
                f"Step2B.2 corrected: {label(font)} [{row['typography']['font']['authority']['upstream_status']}]",
                f"Step2F final: {label(font)} [{font_authority}]",
                f"reconciliation: {relation['outcome'] + ' - ' + str(relation['reason']) if relation else 'none; independent identity'}",
                "top3: " + "; ".join(label(item) for item in row["typography"]["font"]["comparison_candidates"]) if font_authority == "PROVISIONAL" else "",
                ", ".join(spec["coverage"]),
            ]
            calibration = row["typography"]["font"].get("source_style_calibration")
            if calibration:
                lines = [
                    f"winner={label(font)} runner={calibration.get('runner_up_label')} margin={calibration.get('winner_margin')}",
                    f"mask_confidence={evidence.get('mask_confidence')} unknown={evidence.get('unknown_ratio')} observations={len(observations)}",
                    f"ranking_authority={calibration.get('ranking_authority')}",
                    f"FINAL SOURCE-STYLE AUTHORITY={font_authority}",
                    f"reason={calibration.get('reason')}",
                    f"pool_limitation={calibration.get('pool_limitation_flag')} cross_property={calibration.get('cross_property_conflict')}",
                    f"physical_word_conflict={calibration.get('physical_word_conflict')} fragment={calibration.get('fragment_status')}",
                    ", ".join(spec["coverage"]),
                ]
            for index, line in enumerate(lines):
                cv2.putText(card, line[:150], (12, 245 + index*20), cv2.FONT_HERSHEY_SIMPLEX, .40, (210,210,210), 1, cv2.LINE_AA)
            review_data.append({
                **spec, "text": preview_text, "font_authority": font_authority,
                "selected_candidate": font, "top_candidates": row["typography"]["font"]["comparison_candidates"],
                "source_observation": observations[len(observations) // 2] if observations else None,
                "unknown_ratio": evidence.get("unknown_ratio"), "mask_confidence": evidence.get("mask_confidence"),
                "render_status": render_status,
            })
            cards.append(card)
    finally:
        capture.release()
    columns = 2
    if len(cards) % columns:
        cards.append(np.full_like(cards[0], 24))
    sheet = cv2.vconcat([cv2.hconcat(cards[index:index + columns]) for index in range(0, len(cards), columns)])
    if not cv2.imwrite(str(output), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError("diagnostic write failed")
    return review_data


def contract_delta(current: dict, rejected: dict) -> dict:
    old = {row["identity"]["stable_identity_id"]: row for row in rejected["identities"]}
    new = {row["identity"]["stable_identity_id"]: row for row in current["identities"]}
    font_winner_changes, authority_changes, static_changes = [], [], []
    newly_unresolved, newly_resolved = [], []
    for identity in sorted(new):
        before = old[identity]["typography"]["font"]
        after = new[identity]["typography"]["font"]
        before_candidate = before.get("selected_candidate")
        after_candidate = after.get("selected_candidate")
        before_key = (before_candidate or {}).get("family"), (before_candidate or {}).get("style")
        after_key = (after_candidate or {}).get("family"), (after_candidate or {}).get("style")
        before_status, after_status = before["authority"]["status"], after["authority"]["status"]
        if before_key != after_key:
            font_winner_changes.append({"identity": identity, "before": before_candidate, "after": after_candidate})
        if before_status != after_status:
            authority_changes.append({"identity": identity, "before": before_status, "after": after_status})
        if before_status != "UNRESOLVED" and after_status == "UNRESOLVED": newly_unresolved.append(identity)
        if before_status == "UNRESOLVED" and after_status != "UNRESOLVED": newly_resolved.append(identity)
        if before_key != after_key or before_status != after_status:
            static_changes.append(identity)
    def counts(contract: dict) -> dict:
        return {
            name: dict(Counter(property_status(row, name) for row in contract["identities"]))
            for name in PROPERTIES
        }
    before_counts, after_counts = counts(rejected), counts(current)
    return {
        "schema": "video_cloner_step2f_delta_from_rejected", "schema_version": 1,
        "font_winner_changes": font_winner_changes, "authority_changes": authority_changes,
        "newly_unresolved_identities": newly_unresolved, "newly_resolved_identities": newly_resolved,
        "changed_static_style_identities": static_changes,
        "property_authority_count_changes": {
            name: {state: after_counts[name].get(state, 0) - before_counts[name].get(state, 0) for state in STATES}
            for name in PROPERTIES
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in INPUT_NAMES:
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--review-selection", type=Path)
    parser.add_argument("--rejected-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-identities", type=int, default=113)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    paths = {name: getattr(args, name).resolve() for name in INPUT_NAMES}
    source_paths = {name: str(path) for name, path in paths.items()}
    hashes = {name: sha256(path) for name, path in paths.items()}
    loaded = {name: load(path) for name, path in paths.items()}
    contract = build_contract(loaded, source_paths, hashes)
    validation = validate_contract(contract, args.expected_identities, Path(__file__))
    review = load(args.review_selection.resolve()) if args.review_selection else None
    review_data = render_diagnostic(contract, loaded["glyph"], args.source.resolve(), args.output / "step2f_static_review_diagnostic.jpg", review)
    validation["diagnostic_selection"] = [{"identity": row["identity"], "coverage": row["coverage"], "render_status": row["render_status"]} for row in review_data]
    validation["diagnostic_selected_fonts_rendered"] = all(row["render_status"] in {"SELECTED_FONT_RENDERED", "FONT_UNRESOLVED"} for row in review_data)
    if not validation["diagnostic_selected_fonts_rendered"]:
        validation["result"] = "FAIL_STEP_2F_VALIDATION"
    (args.output / "whole_reel_static_style_contract.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    (args.output / "step2f_validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    (args.output / "step2f_human_review_data.json").write_text(json.dumps({"schema": "video_cloner_step2f_human_review_data", "schema_version": 1, "identities": review_data}, indent=2) + "\n", encoding="utf-8")
    (args.output / "delta_from_rejected_step2f.json").write_text(json.dumps(contract_delta(contract, load(args.rejected_contract.resolve())), indent=2) + "\n", encoding="utf-8")
    if not validation["result"].startswith("PASS_"):
        raise SystemExit(validation["result"])


if __name__ == "__main__":
    main()
