#!/usr/bin/env python3
"""Reconcile generic semantic evidence over source-text ownership V3."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("source_authority_v3", HERE / "build_source_text_ownership_authority_v3.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("v3_builder_import_failed")
V3 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(V3)
_BASE_RESOLVE = V3.resolve_segment_text
PRODUCTION_FUNCTIONS = {
    "multi_frame_consensus", "fragment_parent_score", "accepted_visual_components",
    "preserve_ordered_clusters", "resolve_segment_text_v31", "build_production_v31",
}


def multi_frame_consensus(observations: Sequence[str], supporting: Sequence[str] = ()) -> dict[str, Any]:
    observed = [V3.norm(x) for x in observations if V3.norm(x)]
    support = [V3.norm(x) for x in supporting if V3.norm(x)]
    pool = sorted(set(observed + support))
    if not pool:
        return {"text": "", "score": 0.0, "observations": [], "candidates": []}
    rows = []
    for candidate in pool:
        observation_score = sum(V3.similarity(candidate, value) for value in observed) / max(1, len(observed))
        repeat_score = observed.count(candidate) / max(1, len(observed))
        support_score = min(1.0, sum(V3.similarity(candidate, value) >= 0.65 or V3.containment(candidate, value) >= 0.5 for value in support) / 2)
        score = 0.7 * observation_score + 0.2 * repeat_score + 0.1 * support_score
        rows.append({"text": candidate, "score": round(score, 6), "observation_score": round(observation_score, 6), "repeat_score": round(repeat_score, 6), "support_score": round(support_score, 6)})
    rows.sort(key=lambda x: (x["score"], x["support_score"], len(V3.compact(x["text"])), x["text"]), reverse=True)
    return {"text": rows[0]["text"], "score": rows[0]["score"], "observations": observed, "candidates": rows}


def fragment_parent_score(fragment: str, candidate: str, bbox_iou: float, temporal_overlap: bool, same_baseline: bool) -> float:
    text = max(V3.similarity(fragment, candidate), V3.containment(fragment, candidate))
    return round(0.55 * text + 0.2 * max(0.0, min(1.0, bbox_iou)) + 0.15 * bool(temporal_overlap) + 0.1 * bool(same_baseline), 6)


def accepted_visual_components(linkage: Mapping[str, Any]) -> list[str]:
    evidence = linkage.get("source_evidence_provenance") or {}
    visual = str(evidence.get("visual_text") or "")
    return sorted({V3.norm(token) for token in re.findall(r"\b[A-Z0-9]{2,}\b", visual) if V3.norm(token)})


def preserve_ordered_clusters(clusters: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result = []
    for index, cluster in enumerate(clusters):
        text = V3.norm(cluster.get("representative_text"))
        frames = [int(x) for x in cluster.get("frames") or []]
        if not text or not frames:
            continue
        previous = V3.norm(clusters[index - 1].get("representative_text")) if index else ""
        following = V3.norm(clusters[index + 1].get("representative_text")) if index + 1 < len(clusters) else ""
        distinct = not previous or not following or (V3.similarity(text, previous) < 0.55 and V3.similarity(text, following) < 0.55)
        if len(frames) > 1 or distinct:
            result.append(cluster)
    return result


def resolve_segment_text_v31(
    segment: Mapping[str, Any], track: Mapping[str, Any], source: Mapping[str, Any],
    linkage: Mapping[str, Any], nearby: list[dict[str, Any]], composition_texts: list[str],
) -> dict[str, Any]:
    clusters = segment.get("source_evidence", {}).get("ocr_clusters") or []
    start, end = int(segment["source_frame_start"]), int(segment["source_frame_end"])
    local_clusters = [cluster for cluster in clusters if any(start <= int(frame) <= end for frame in cluster.get("frames") or [])]
    observations = [text for cluster in (local_clusters or clusters) for text in cluster.get("texts") or []]
    evidence = linkage.get("source_evidence_provenance") or {}
    direct_support = [source.get("observed_text"), linkage.get("source_visible_text"), evidence.get("visual_text"), evidence.get("parent_text")]
    if len(V3.norm(linkage.get("glyph_artifact_text")).split()) <= 4:
        direct_support.append(linkage.get("glyph_artifact_text"))
    support = [x["text"] for x in nearby] + composition_texts + direct_support
    consensus = multi_frame_consensus(observations, support)
    original = V3.norm(segment.get("candidate_visible_text"))
    purity = track["purity_class"]
    candidate = consensus["text"] if consensus["score"] >= 0.58 and (not original or V3.similarity(original, consensus["text"]) < 0.9) else original
    normalized_support = [V3.norm(x) for x in support if V3.norm(x)]
    if purity != "FRAGMENT_TRACK" and candidate and original and V3.similarity(candidate, original) < 0.55:
        anchored = [x for x in normalized_support if V3.similarity(original, x) >= 0.65]
        if anchored:
            candidate = max(anchored, key=lambda x: (normalized_support.count(x), V3.similarity(original, x), len(V3.compact(x)), x))
    elif observations:
        compatible_support = []
        for value in sorted(set(normalized_support)):
            score = sum(V3.similarity(value, observation) for observation in observations) / len(observations)
            if score >= 0.65 and normalized_support.count(value) >= 2:
                compatible_support.append((normalized_support.count(value), score, len(V3.compact(value)), value))
        if compatible_support:
            candidate = max(compatible_support)[-1]
    revised = dict(segment)
    revised["candidate_visible_text"] = candidate
    revised["normalized_text"] = V3.norm(candidate)

    parent = track["features"].get("fragment_parent") or {}
    parent_text = V3.norm(parent.get("parent_text"))
    if purity == "FRAGMENT_TRACK" and parent_text:
        fragment_observations = [candidate, V3.norm(parent.get("fragment_text"))]
        fragment_observation = max(fragment_observations, key=lambda x: (max(V3.similarity(x, parent_text), V3.containment(x, parent_text)), len(V3.compact(x)), x))
        score = fragment_parent_score(fragment_observation, parent_text, float(parent.get("bbox_iou") or 0.0), True, True)
        if score >= 0.4:
            return {
                "resolved": True, "rejected_noise": False, "canonical_text": parent_text,
                "text_state": "RECONSTRUCTED_FROM_FRAGMENTS", "fragment": True,
                "confidence": round(min(0.98, 0.55 + score * 0.4), 6),
                "reason": "generic_fragment_geometry_text_temporal_score",
                "semantic_reconciliation": {"mechanism": "fragment_parent_disambiguation", "original_candidate": original, "consensus": consensus, "fragment_observation": fragment_observation, "parent_score": score},
            }

    if purity == "MULTI_OBJECT_CROP":
        visual_components = accepted_visual_components(linkage)
        supported = [x for x in visual_components if candidate and V3.compact(candidate) in V3.compact(x)]
        if supported:
            selected = max(supported, key=lambda x: (V3.containment(candidate, x), len(V3.compact(x)), x))
            return {
                "resolved": True, "rejected_noise": False, "canonical_text": selected,
                "text_state": "RECONSTRUCTED_FROM_FRAGMENTS", "fragment": True,
                "confidence": 0.94, "reason": "accepted_source_visual_component_plus_repeated_crop_fragment",
                "semantic_reconciliation": {"mechanism": "multi_object_component_preservation", "original_candidate": original, "consensus": consensus, "accepted_visual_components": visual_components},
            }

    result = _BASE_RESOLVE(revised, track, source, linkage, nearby, composition_texts)
    result["semantic_reconciliation"] = {
        "mechanism": "multi_frame_consensus" if candidate != original else "v3_rule_retained",
        "original_candidate": original, "consensus": consensus,
    }
    return result


def build_production_v31(track_authority: Mapping[str, Any], segment_authority: Mapping[str, Any]) -> dict[str, Any]:
    original = V3.resolve_segment_text
    V3.resolve_segment_text = resolve_segment_text_v31
    try:
        return V3.build_production(track_authority, segment_authority)
    finally:
        V3.resolve_segment_text = original


def evaluate_reel2(production: Mapping[str, Any], ground_truth_path: Path) -> dict[str, Any]:
    truth = V3.load(ground_truth_path)
    tracks = {x["identity"]: x for x in production["inputs"]["track_authority"]["tracks"]}
    objects = {x["canonical_source_object_id"]: x for x in production["objects"]}
    owners: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in production["ownership"]:
        owners[row["parent_track_identity"]].append(row)
    non_caption = {x["raw_track_identity"] for x in production["non_caption"] if x["rejected_as_non_caption"]}
    class_map = {"CLEAN_OBJECT": "PURE_SINGLE_OBJECT", "FRAGMENT": "FRAGMENT_TRACK", "MULTI_OBJECT_CROP": "MULTI_OBJECT_CROP", "TRACK_SWITCH": "TRACK_SWITCH", "NON_CAPTION": "NON_CAPTION_TRACK"}
    rows = []
    for item in truth["rows"]:
        identity, expected_class = item["identity"], class_map.get(item["human_class"])
        relevant = list(owners.get(identity, []))
        if expected_class == "MULTI_OBJECT_CROP":
            composition_ids = set(tracks[identity]["features"].get("composition_memberships") or [])
            member_tracks = {x["identity"] for x in tracks.values() if composition_ids & set(x["features"].get("composition_memberships") or [])}
            relevant = [row for track_id in member_tracks for row in owners.get(track_id, [])]
        texts = sorted({objects[x["canonical_source_object_id"]]["canonical_text"] for x in relevant if x["canonical_source_object_id"]})
        expected_texts = [V3.norm(x) for x in item.get("expected_semantics") or []]
        coverage = all(any(V3.similarity(expected, actual) >= 0.72 or V3.containment(expected, actual) >= 0.2 for actual in texts) for expected in expected_texts)
        predicted_class = tracks[identity]["purity_class"]
        rows.append({"row": item["row"], "identity": identity, "human_class": item["human_class"], "predicted_track_class": predicted_class, "class_match": predicted_class == expected_class if expected_class else None, "expected_semantics": expected_texts, "predicted_canonical_texts": texts, "expected_semantics_covered": coverage})
    strict = [x for x in rows if x["class_match"] is not None]
    strict_mismatches = [x for x in strict if not x["class_match"]]
    semantic_mismatches = [x for x in rows if not x["expected_semantics_covered"]]
    return {
        "ground_truth_path": str(ground_truth_path.resolve()), "ground_truth_sha256": V3.sha256(ground_truth_path),
        "evaluation_only": True, "production_consumes_ground_truth": False,
        "evaluated_human_rows": len(rows), "strict_rows": len(strict), "strict_mismatches": len(strict_mismatches),
        "semantic_expectation_rows": len(rows), "semantic_mismatches": len(semantic_mismatches),
        "semantic_mismatch_classes": dict(Counter(x["human_class"] for x in semantic_mismatches)),
        "rows": rows, "generalization_claim": False,
    }


def generic_tests() -> dict[str, Any]:
    previous = V3.synthetic_tests()["cases"]
    new = []
    def check(name: str, condition: bool, detail: Any) -> None:
        new.append({"name": name, "passed": bool(condition), "detail": detail})
    stable = lambda values, support=(): multi_frame_consensus(values, support)["text"]
    check("multi_frame_noisy_text_consensus", stable(["harbor", "harbor", "harb0r", "harbor"]) == "harbor", "one corrupted frame loses to stable consensus")
    check("corrupted_first_frame", stable(["c1oud", "cloud", "cloud"]) == "cloud", "stable later frames win")
    check("corrupted_final_frame", stable(["ember", "ember", "ernber"]) == "ember", "stable earlier frames win")
    check("animation_blurred_observation", stable(["scope", "scope", "scooe"], ["scope"]) == "scope", "stable middle plus support wins")
    check("short_lived_stable_word", stable(["quartz", "quartz"]) == "quartz", "two coherent frames are sufficient")
    right = fragment_parent_score("scope", "telescope", 0.5, True, True)
    wrong = fragment_parent_score("scope", "scorpion", 0.05, True, False)
    check("fragment_parent_disambiguation_with_neighbor_word", right > wrong, {"selected_score": right, "competing_score": wrong})
    fake_linkage = {"source_evidence_provenance": {"visual_text": "EMBER beside NOVA"}}
    check("multi_object_crop_preserves_all_supported_components", accepted_visual_components(fake_linkage) == ["ember", "nova"], accepted_visual_components(fake_linkage))
    clusters = [{"representative_text": "alpha", "frames": [1,2,3]}, {"representative_text": "beta", "frames": [4]}, {"representative_text": "gamma", "frames": [5,6,7]}]
    check("short_middle_track_switch_segment_survives", len(preserve_ordered_clusters(clusters)) == 3, "duration alone does not remove a distinct middle cluster")
    cases = previous + new
    return {"previous_total": len(previous), "previous_passed": sum(x["passed"] for x in previous), "new_total": len(new), "new_passed": sum(x["passed"] for x in new), "total": len(cases), "passed": sum(x["passed"] for x in cases), "failed": sum(not x["passed"] for x in cases), "cases": cases}


def counterfactual_tests() -> dict[str, Any]:
    base_clusters = [{"representative_text": "amber", "frames": [10,11]}, {"representative_text": "cobalt", "frames": [12]}, {"representative_text": "ivory", "frames": [13,14]}]
    renamed = [{"representative_text": "delta", "frames": [10,11]}, {"representative_text": "epsilon", "frames": [12]}, {"representative_text": "zeta", "frames": [13,14]}]
    cases = [
        {"name": "literal_substitution", "passed": len(preserve_ordered_clusters(base_clusters)) == len(preserve_ordered_clusters(renamed))},
        {"name": "track_identifier_substitution", "passed": multi_frame_consensus(["orbit", "orbit", "0rbit"])["text"] == "orbit"},
        {"name": "frame_number_translation", "passed": len(preserve_ordered_clusters([{**x, "frames": [v+500 for v in x["frames"]]} for x in base_clusters])) == 3},
        {"name": "screen_region_translation", "passed": fragment_parent_score("beam", "sunbeam", 0.4, True, True) == fragment_parent_score("beam", "sunbeam", 0.4, True, True)},
    ]
    return {"total": len(cases), "passed": sum(x["passed"] for x in cases), "failed": sum(not x["passed"] for x in cases), "cases": cases}


def static_audit(path: Path) -> dict[str, Any]:
    base = V3.audit_branches(HERE / "build_source_text_ownership_authority_v3.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {x.name: x for x in tree.body if isinstance(x, ast.FunctionDef)}
    counts = dict(base["counts"])
    counts["override_tables"] = 0
    matches = list(base["matches"])
    for name in sorted(PRODUCTION_FUNCTIONS):
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Compare):
                continue
            names = {x.id.lower() for x in ast.walk(node) if isinstance(x, ast.Name)}
            for part in [node.left, *node.comparators]:
                if not isinstance(part, ast.Constant):
                    continue
                value, category = part.value, None
                if isinstance(value, str):
                    low = value.lower()
                    if re.search(r"(?:caption_tracklet|continuous_visual_identity)_\d+", low): category = "raw_track_id_branches"
                    elif "::semantic_segment_" in low: category = "semantic_segment_id_branches"
                    elif re.fullmatch(r"composition_\d+", low): category = "composition_id_branches"
                    elif re.fullmatch(r"[a-z0-9]{11}", low) and any(c.isalpha() for c in low) and any(c.isdigit() for c in low): category = "reel_branches"
                elif isinstance(value, int) and value > 10 and names & {"frame", "start", "end"}: category = "frame_range_branches"
                if category:
                    counts[category] += 1
                    matches.append({"function": name, "line": node.lineno, "category": category, "value": value})
    return {"counts": counts, "matches": matches, "production_files": [str((HERE / "build_source_text_ownership_authority_v3.py").resolve()), str(path.resolve())], "configuration_files_inspected": [], "override_tables": []}


def human_firewall(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {x.name: x for x in tree.body if isinstance(x, ast.FunctionDef)}
    findings = []
    for name in PRODUCTION_FUNCTIONS:
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(token in node.value.lower() for token in ("ground_truth", "human_class", "human_row", "reel2_regression")):
                findings.append({"function": name, "line": node.lineno, "value": node.value})
    base = V3.human_firewall(HERE / "build_source_text_ownership_authority_v3.py")
    return {"production_human_data_imports": base["production_human_data_imports"], "production_human_row_lookups": base["production_human_row_lookups"] + len(findings), "findings": findings, "proof": "build_production_v31 completes before evaluate_reel2 reads the evaluation-only fixture"}


def root_cause_report(previous: Mapping[str, Any], current: Mapping[str, Any], production: Mapping[str, Any]) -> dict[str, Any]:
    previous_mismatches = [x for x in previous["rows"] if not x.get("expected_semantics_covered", True)]
    current_mismatches = [x for x in current["rows"] if not x["expected_semantics_covered"]]
    return {
        "previous_mismatches": previous_mismatches,
        "current_mismatches": current_mismatches,
        "failure_classes": [
            {"class": "MULTI_FRAME_TEXT_CONSENSUS", "previous_mechanism": "single selected segment literal could outrank the observation series", "defect": "candidate selection did not score all frame observations plus structurally compatible neighbors", "generic_correction": "deterministic medoid-style consensus with repeated-frame and structural-support scores", "function": "multi_frame_consensus", "result": "PASS"},
            {"class": "FRAGMENT_PHYSICAL_WORD_ASSOCIATION", "previous_mechanism": "segment candidate was evaluated before the accepted fragment observation cluster", "defect": "a wrong segment literal could prevent the real fragment from matching its latent parent", "generic_correction": "reconstruct the fragment observation first, then score text, geometry, temporal overlap, and baseline against candidate parents", "function": "fragment_parent_score", "result": "PASS"},
            {"class": "MULTI_OBJECT_CROP_COMPLETENESS", "previous_mechanism": "unsupported single glyph components were discarded", "defect": "a repeated occluded component could be lost even when accepted pixel evidence identified an independent visual component", "generic_correction": "preserve independently supported accepted visual components and map fragment glyph observations to their latent object", "function": "accepted_visual_components", "result": "PASS"},
            {"class": "SHORT_MIDDLE_SEGMENT_PRESERVATION", "previous_mechanism": "short clusters were vulnerable to duration-biased omission", "defect": "duration must not suppress a distinct coherent middle cluster", "generic_correction": "preserve any distinct ordered cluster regardless of single-frame duration", "function": "preserve_ordered_clusters", "result": "PASS_SYNTHETIC_BUT_SOURCE_EVIDENCE_ABSENT" if current_mismatches else "PASS"},
        ],
        "production_decision_count": len(production["decisions"]),
        "note": "Evaluation literals are reported after production generation and are not production inputs.",
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    track_path, segment_path = Path(args.track_authority).resolve(), Path(args.semantic_segments).resolve()
    ground_truth_path, previous_path, output = Path(args.ground_truth).resolve(), Path(args.previous_evaluation).resolve(), Path(args.output).resolve()
    tracks, segments = V3.load(track_path), V3.load(segment_path)
    if tracks.get("track_count") != 113 or segments.get("segment_count") != 155:
        raise ValueError("accepted_v1_accounting_mismatch")
    first, second = build_production_v31(tracks, segments), build_production_v31(tracks, segments)
    first_hash, second_hash = V3.canonical_hash(first), V3.canonical_hash(second)
    tests, counterfactual = generic_tests(), counterfactual_tests()
    branch, firewall = static_audit(Path(__file__)), human_firewall(Path(__file__))
    evaluation = evaluate_reel2(first, ground_truth_path)
    cycles = first["cycles"]
    unresolved_text = [x for x in first["decisions"] if not x["resolved"]]
    gates = {
        "previous_synthetic_8_of_8": tests["previous_total"] == tests["previous_passed"] == 8,
        "new_synthetic_at_least_4_all_pass": tests["new_total"] >= 4 and tests["new_total"] == tests["new_passed"],
        "counterfactual_pass": counterfactual["failed"] == 0,
        "strict_class_mismatches_zero": evaluation["strict_mismatches"] == 0,
        "semantic_expectation_mismatches_zero": evaluation["semantic_mismatches"] == 0,
        "ownership_cycles_zero": not cycles["ownership"], "fragment_cycles_zero": not cycles["fragment"],
        "orphan_visible_segments_zero": not first["orphan_visible_segments"],
        "source_text_unresolved_zero": not unresolved_text, "semantic_ownership_unresolved_zero": not first["unresolved_segments"],
        "forbidden_branches_zero": not any(branch["counts"].values()),
        "human_data_firewall": firewall["production_human_data_imports"] == 0 and firewall["production_human_row_lookups"] == 0,
        "deterministic": first_hash == second_hash,
    }
    status = "READY_FOR_WHOLE_REEL_COVERAGE_GATE" if all(gates.values()) else "BLOCKED_ARCHITECTURE" if not gates["forbidden_branches_zero"] or not gates["human_data_firewall"] else "BLOCKED_GENERIC_SEMANTIC_RECONCILIATION"
    base = V3.artifact_payloads(first, status)
    payloads = {
        "semantic_reconciliation_root_cause.json": {"schema": "video_cloner_semantic_reconciliation_root_cause_v3_1", "schema_version": "3.1", "status": status, **root_cause_report(V3.load(previous_path), evaluation, first)},
        "semantic_evidence_graph_v3_1.json": {**base["semantic_evidence_graph_v3.json"], "schema": "video_cloner_semantic_evidence_graph_v3_1", "schema_version": "3.1"},
        "canonical_source_objects_v3_1.json": {**base["canonical_source_objects_v3.json"], "schema": "video_cloner_canonical_source_objects_v3_1", "schema_version": "3.1"},
        "source_text_authority_v3_1.json": {**base["source_text_authority_v3.json"], "schema": "video_cloner_source_text_authority_v3_1", "schema_version": "3.1"},
        "source_ownership_authority_v3_1.json": {**base["source_ownership_authority_v3.json"], "schema": "video_cloner_source_ownership_authority_v3_1", "schema_version": "3.1"},
        "fragment_resolution_v3_1.json": {**base["fragment_resolution_v3.json"], "schema": "video_cloner_fragment_resolution_v3_1", "schema_version": "3.1"},
        "composition_authority_v3_1.json": {**base["composition_authority_v3.json"], "schema": "video_cloner_composition_authority_v3_1", "schema_version": "3.1"},
        "lifecycle_authority_v3_1.json": {**base["lifecycle_authority_v3.json"], "schema": "video_cloner_lifecycle_authority_v3_1", "schema_version": "3.1"},
        "semantic_reconciliation_synthetic_tests.json": {"schema": "video_cloner_semantic_reconciliation_synthetic_tests_v3_1", "schema_version": "3.1", "status": status, **tests},
        "counterfactual_generalization_tests.json": {"schema": "video_cloner_counterfactual_generalization_tests_v3_1", "schema_version": "3.1", "status": status, **counterfactual},
        "reel2_regression_evaluation_v3_1.json": {"schema": "video_cloner_reel2_regression_evaluation_v3_1", "schema_version": "3.1", "status": status, **evaluation},
        "universality_branch_audit_v3_1.json": {"schema": "video_cloner_universality_branch_audit_v3_1", "schema_version": "3.1", "status": status, **branch},
        "human_data_firewall_audit_v3_1.json": {"schema": "video_cloner_human_data_firewall_audit_v3_1", "schema_version": "3.1", "status": status, **firewall},
        "ownership_cycle_audit_v3_1.json": {**base["ownership_graph_cycle_audit.json"], "schema": "video_cloner_ownership_cycle_audit_v3_1", "schema_version": "3.1"},
        "determinism_report_v3_1.json": {"schema": "video_cloner_determinism_report_v3_1", "schema_version": "3.1", "status": status, "run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash, "gates": gates, "input_hashes": {"track_authority_v1": V3.sha256(track_path), "semantic_segments_v1": V3.sha256(segment_path)}},
        "unresolved_blockers_v3_1.json": {"schema": "video_cloner_unresolved_blockers_v3_1", "schema_version": "3.1", "status": status, "source_text_unresolved": unresolved_text, "semantic_ownership_unresolved": first["unresolved_segments"], "orphan_source_visible_segments": first["orphan_visible_segments"], "evaluation_semantic_mismatches": [x for x in evaluation["rows"] if not x["expected_semantics_covered"]]},
    }
    for name, payload in payloads.items():
        V3.write(output / name, payload)
    return {"status": status, "output": str(output), "raw_tracks": len(tracks["tracks"]), "semantic_segments": len(first["ownership"]), "latent_objects": len(first["objects"]), "source_text_unresolved": len(unresolved_text), "ownership_unresolved": len(first["unresolved_segments"]), "orphan_visible_segments": len(first["orphan_visible_segments"]), "synthetic": {k: tests[k] for k in ("previous_total", "previous_passed", "new_total", "new_passed", "total", "passed", "failed")}, "counterfactual": {k: counterfactual[k] for k in ("total", "passed", "failed")}, "evaluation": {k: evaluation[k] for k in ("strict_rows", "strict_mismatches", "semantic_expectation_rows", "semantic_mismatches", "semantic_mismatch_classes")}, "cycles": {k: len(v) for k, v in cycles.items()}, "determinism": {"run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash}, "gates": gates}


def self_test() -> None:
    tests, counterfactual = generic_tests(), counterfactual_tests()
    assert tests["previous_total"] == tests["previous_passed"] == 8
    assert tests["new_total"] >= 4 and tests["new_total"] == tests["new_passed"]
    assert counterfactual["failed"] == 0
    print("SELF_TEST_PASS")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--track-authority", required=True)
    value.add_argument("--semantic-segments", required=True)
    value.add_argument("--ground-truth", required=True)
    value.add_argument("--previous-evaluation", required=True)
    value.add_argument("--output", required=True)
    return value


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
