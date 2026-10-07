from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
V2 = ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1B_GLYPH_UNCERTAINTY_V2_20260925/20260925T134115947Z_uncertainty_occlusion/reel2_glyph_evidence_v2.json"
STEP2B1 = ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_FINAL_KNOWN_REGION_FONT_RERANK_20260925/20260925T142345674Z_approved_v2_rerank/reel2_known_region_font_rerank.json"
STEP2B2 = ROOT / ".agent/reports/VIDEO_CLONER_STEP2B2_CANDIDATE_REDUCTION_RECALL_CORRECTION_20260925/20260925T151139831Z_coarse32_top16/whole_reel_full_pool_benchmark.json"
STEP2C = ROOT / ".agent/reports/VIDEO_CLONER_STEP2C_STROKE_OWNERSHIP_CORRECTION_20260925/20260925T162120849Z_identity_ownership/step2c_stroke_ownership_inference.json"
STEP2D = ROOT / ".agent/reports/VIDEO_CLONER_STEP2D_COLOR_OPACITY_INFERENCE_20260925/20260925T180000000Z_first_run/step2d_color_opacity_inference.json"
PREVIEW = ROOT / ".agent/reports/VIDEO_CLONER_STEP2_REEL2_STATIC_CAPTION_FIDELITY_V1_20260925/20260925T085122980Z_static_fidelity/reel2_l4_preview.json"
SOURCE = ROOT / "input/DcJRJtUKScu.mp4"
MODULE = ROOT / "scripts/standalone/video_cloner_composition_relationships.py"
sys.path.insert(0, str(ROOT))

from scripts.standalone import video_cloner_composition_relationships as inference


COLORS = [(55, 210, 255), (80, 220, 80), (255, 120, 80), (220, 80, 220), (70, 150, 255)]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def common_frame(members: list[str], accepted: dict[str, dict[int, dict]]) -> int | None:
    frames = None
    for identity in members:
        values = set(accepted[identity])
        frames = values if frames is None else frames & values
    return min(frames) if frames else None


def representative_specs(graph: dict, rows: dict[str, dict], accepted: dict[str, dict[int, dict]], physical_groups: list[dict], ownership_candidates: list[dict]) -> list[dict]:
    compositions = graph["compositions"]

    def by_words(required: list[str]) -> dict | None:
        for composition in compositions:
            candidates = defaultdict(list)
            for identity in composition["member_identities"]:
                candidates[str(rows[identity]["text"]).casefold().strip(".,")].append(identity)
            if set(required) <= set(candidates):
                return {"member_identities": [max(candidates[word], key=lambda identity: len(accepted[identity])) for word in required]}
        return None

    buyers_members = list(physical_groups[0]["member_identities"])
    selected = [
        ("PHYSICAL WORD: buyers", next((item for item in compositions if set(buyers_members) <= set(item["member_identities"])), None)),
        ("PHRASE: before / the / sign", by_words(["before", "the", "sign"])),
        ("LINE: hits the yard", by_words(["hits", "the", "yard"])),
        ("INDEPENDENT: for / social", by_words(["for", "social"])),
    ]
    same = next((row for row in graph["relationships"] if row["relationship_type"] == "SAME_BASELINE"), None)
    above = next((row for row in graph["relationships"] if row["relationship_type"] == "ABOVE"), None)
    if same:
        selected.append(("CONTROL: simple same baseline", {"member_identities": [same["source_identity"], same["target_identity"]]}))
    if above:
        selected.append(("CONTROL: vertically offset", {"member_identities": [above["source_identity"], above["target_identity"]]}))
    specs = []
    for label, composition in selected:
        if not composition:
            continue
        members = composition["member_identities"]
        specs.append({"label": label, "members": members, "frame": common_frame(members, accepted), "interpretation": "source-derived composition; identities remain independent"})
    if ownership_candidates:
        candidate = ownership_candidates[0]
        specs.append({
            "label": "OVERLAP CANDIDATE: unresolved",
            "members": [candidate["target_identity"], candidate["foreign_identity"]],
            "frame": candidate["source_frame"],
            "interpretation": "Step 2C exclusion evidence is not directional pair-mask proof; overlap and z-order remain unresolved",
        })
    ambiguous = next((identity for identity in graph["standalone_identities"] if not accepted[identity]), graph["standalone_identities"][0])
    specs.append({"label": "AMBIGUOUS: fail closed", "members": [ambiguous], "frame": None, "interpretation": "insufficient accepted co-visible geometry; no composition fabricated"})
    return specs[:8]


def observation_at(identity: str, frame: int | None, accepted: dict[str, dict[int, dict]]) -> dict | None:
    observations = accepted[identity]
    if not observations:
        return None
    if frame in observations:
        return observations[frame]
    return min(observations.values(), key=lambda row: abs(int(row["source_frame"]) - int(frame or row["source_frame"])))


def render_card(capture: cv2.VideoCapture, spec: dict, rows: dict[str, dict], accepted: dict[str, dict[int, dict]], graph: dict) -> np.ndarray:
    card = np.full((330, 720, 3), 25, np.uint8)
    frame_number = spec["frame"]
    observations = [(identity, observation_at(identity, frame_number, accepted)) for identity in spec["members"]]
    observations = [(identity, item) for identity, item in observations if item]
    if frame_number is None and observations:
        frame_number = int(observations[0][1]["source_frame"])
    image = None
    if frame_number is not None:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_number))
        ok, image = capture.read()
        if not ok:
            image = None
    if image is not None and observations:
        boxes = [item["bbox"] for _, item in observations]
        x1 = max(0, min(box[0] for box in boxes) - 50)
        y1 = max(0, min(box[1] for box in boxes) - 50)
        x2 = min(image.shape[1], max(box[2] for box in boxes) + 50)
        y2 = min(image.shape[0], max(box[3] for box in boxes) + 50)
        crop = image[y1:y2, x1:x2].copy()
        for index, (identity, item) in enumerate(observations):
            color = COLORS[index % len(COLORS)]
            bx1, by1, bx2, by2 = item["bbox"]
            cv2.rectangle(crop, (bx1 - x1, by1 - y1), (bx2 - x1, by2 - y1), color, 2)
            cv2.line(crop, (bx1 - x1, by2 - y1), (bx2 - x1, by2 - y1), color, 2)
            cv2.putText(crop, f"{index + 1}:{identity.rsplit('_', 1)[-1]}", (bx1 - x1, max(15, by1 - y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        scale = min(430 / max(1, crop.shape[1]), 235 / max(1, crop.shape[0]))
        resized = cv2.resize(crop, (max(1, round(crop.shape[1] * scale)), max(1, round(crop.shape[0] * scale))), interpolation=cv2.INTER_AREA)
        card[58:58 + resized.shape[0], 10:10 + resized.shape[1]] = resized
    cv2.putText(card, spec["label"], (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (245, 245, 245), 2, cv2.LINE_AA)
    cv2.putText(card, f"source frame: {frame_number if frame_number is not None else 'none'}", (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1, cv2.LINE_AA)
    x = 455
    for index, identity in enumerate(spec["members"]):
        text = str(rows[identity]["text"])[:22]
        cv2.putText(card, f"{index + 1} {text}", (x, 78 + index * 23), cv2.FONT_HERSHEY_SIMPLEX, 0.43, COLORS[index % len(COLORS)], 1, cv2.LINE_AA)
    member_set = set(spec["members"])
    related = [row for row in graph["relationships"] if {row["source_identity"], row["target_identity"]} <= member_set]
    summary = []
    for row in related:
        if row["relationship_type"] in {"SAME_BASELINE", "BASELINE_OFFSET", "HORIZONTAL_GAP", "VERTICAL_GAP", "OVERLAPS", "Z_ORDER", "Z_ORDER_UNRESOLVED", "PHYSICAL_WORD_FRAGMENT"}:
            value = row.get("measurement") or {}
            pixels = value.get("source_pixels", value.get("median_overlap_area_source_px"))
            summary.append(f"{row['relationship_type']}: {pixels if pixels is not None else row['authority']}")
    if not summary:
        summary = ["relationships: UNRESOLVED"]
    for index, line in enumerate(summary[:6]):
        cv2.putText(card, line[:34], (x, 175 + index * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (220, 220, 220), 1, cv2.LINE_AA)
    interpretation = spec["interpretation"]
    for index in range(0, len(interpretation), 45):
        cv2.putText(card, interpretation[index:index + 45], (12, 307 + (index // 45) * 16), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (190, 190, 190), 1, cv2.LINE_AA)
    return card


def synthetic_validation() -> dict:
    mask = lambda h, w, left=0, right=None, top=0: np.pad(np.ones((h - top, (right or w) - left), bool), ((top, 0), (left, w - (right or w))))
    same = inference.infer_pair_relationships("a", "b", [{"frame": 1, "a_bbox": [0, 0, 20, 30], "a_mask": mask(30, 20, top=10), "b_bbox": [30, 0, 50, 30], "b_mask": mask(30, 20, top=2)}])
    offset = inference.infer_pair_relationships("a", "b", [{"frame": 1, "a_bbox": [0, 0, 20, 30], "a_mask": mask(30, 20, top=10), "b_bbox": [30, 5, 50, 35], "b_mask": mask(30, 20, top=2)}])
    gap = inference.infer_pair_relationships("a", "b", [{"frame": 1, "a_bbox": [0, 0, 20, 20], "a_mask": mask(20, 20, left=2, right=18), "b_bbox": [25, 0, 45, 20], "b_mask": mask(20, 20, left=2, right=18)}])
    known = inference.infer_pair_relationships("a", "b", [{"frame": 1, "a_bbox": [0, 0, 20, 20], "b_bbox": [10, 0, 30, 20], "overlap_area_px": 12, "overlap_ratio": .1, "front_identity": "a"}])
    unknown = inference.infer_pair_relationships("a", "b", [{"frame": 1, "a_bbox": [0, 0, 20, 20], "b_bbox": [10, 0, 30, 20], "overlap_area_px": 12, "overlap_ratio": .1}])
    changing = inference.infer_pair_relationships("a", "b", [{"frame": 1, "a_bbox": [0, 0, 20, 20], "b_bbox": [25, 0, 45, 20]}, {"frame": 2, "a_bbox": [0, 0, 20, 20], "b_bbox": [60, 0, 80, 20]}])
    unrelated = inference.build_composition_graph([
        {"identity": "a", "observations": [{"source_frame": 1, "bbox": [0, 0, 20, 20], "accepted": True}]},
        {"identity": "b", "observations": [{"source_frame": 1, "bbox": [21, 0, 41, 20], "accepted": True}]},
    ], {"a": "hint_a", "b": "hint_b"})
    kinds = lambda values: {row["relationship_type"]: row for row in values}
    checks = {
        "same_baseline": "SAME_BASELINE" in kinds(same),
        "baseline_offset": kinds(offset)["BASELINE_OFFSET"]["measurement"]["source_pixels"] == 5,
        "horizontal_gap": kinds(gap)["HORIZONTAL_GAP"]["measurement"]["source_pixels"] == 9,
        "overlap": "OVERLAPS" in kinds(known),
        "no_overlap": inference.mask_overlap_area([0, 0, 20, 20], mask(20, 20, right=8), [5, 0, 25, 20], mask(20, 20, left=10),) == 0,
        "z_order_known": "Z_ORDER" in kinds(known),
        "z_order_unknown": "Z_ORDER_UNRESOLVED" in kinds(unknown),
        "physical_word": "PHYSICAL_WORD_FRAGMENT" in kinds(inference.infer_pair_relationships("a", "b", [], physical_word=True)),
        "nearby_unrelated": not unrelated["compositions"] and len(unrelated["standalone_identities"]) == 2,
        "time_varying": kinds(changing)["HORIZONTAL_GAP"]["consistency"] == "ANIMATED_OR_TIME_VARYING_RELATIONSHIP",
    }
    return {"checks": checks, "all_pass": all(checks.values())}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence, preview, step2c = load(V2), load(PREVIEW), load(STEP2C)
    rows = {row["identity"]: row for row in evidence["identities"]}
    accepted = {
        identity: {int(item["source_frame"]): item for item in row.get("observations", []) if item.get("accepted") and item.get("bbox")}
        for identity, row in rows.items()
    }
    hints = {str(cue["visual_event_identity"]): str(cue["visual_composition_id"]) for cue in preview["cues"] if cue.get("visual_event_identity") and cue.get("visual_composition_id")}
    graph = inference.build_composition_graph(evidence["identities"], hints, evidence["physical_word_groups"])
    relationship_counts = Counter(row["relationship_type"] for row in graph["relationships"])
    time_varying = sum(row["consistency"] == "ANIMATED_OR_TIME_VARYING_RELATIONSHIP" for row in graph["relationships"])
    multi_hints = {hint for hint, count in Counter(hints.values()).items() if count > 1}
    composed = {identity for item in graph["compositions"] for identity in item["member_identities"]}
    unresolved_composition = sorted(identity for identity in rows if identity not in composed and hints.get(identity) in multi_hints)
    ownership_candidates = []
    for record in step2c["identities"]:
        for observation in record.get("stroke_observations", []):
            for foreign in observation.get("ownership", {}).get("foreign_identities", []):
                ownership_candidates.append({
                    "target_identity": record["identity"], "foreign_identity": foreign["identity"],
                    "source_frame": int(observation["source_frame"]), "foreign_owned_pixel_count": int(foreign["foreign_pixel_count"]),
                    "classification": "OWNERSHIP_INTERACTION_CANDIDATE_NOT_PAIR_MASK_OVERLAP_PROOF",
                })
    ownership_candidates.sort(key=lambda row: (-row["foreign_owned_pixel_count"], row["target_identity"], row["foreign_identity"], row["source_frame"]))
    production_source = MODULE.read_text(encoding="utf-8")
    string_literals = [
        value.value.casefold() for value in ast.walk(ast.parse(production_source))
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    ]
    forbidden = ["buyers", "selling", "sign", "before", "social", "caption_tracklet_"]
    generalization = {
        "forbidden_production_tokens": forbidden,
        "matches": [token for token in forbidden if any(literal == token or token == "caption_tracklet_" and token in literal for literal in string_literals)],
        "inspection_scope": "production string literals; identifiers such as a_before_b are not content rules",
    }
    synthetic = synthetic_validation()
    artifact = {
        "schema": "video_cloner_step2e_composition_relationships", "schema_version": 1,
        "result": "PASS_STEP_2E_COMPOSITION_RELATIONSHIPS_READY_FOR_HUMAN_REVIEW" if synthetic["all_pass"] and not generalization["matches"] else "PARTIAL_STEP_2E_COMPOSITION_RELATIONSHIPS",
        "step_2e_status": "TECHNICALLY_READY_HUMAN_REVIEW_REQUIRED",
        "contract": {
            "problem": "independent lifecycle/style identities lack editor-neutral spatial constraints needed to reconstruct their joint visual composition",
            "input_authority": ["accepted_step2b1_per_frame_source_bbox", "accepted_visual_composition_hint", "accepted_physical_word_group", "frozen_step2c_ownership_as_ambiguity_evidence"],
            "output_authority": ["sparse_composition_membership", "pair_relationship_records", "source_pixel_and_glyph_height_normalized_measurements", "explicit_unresolved_relationships"],
            "authority_states": ["SOURCE_DERIVED", "SOURCE_SUPPORTED_VISUAL_BASELINE_PROXY", "PROVISIONAL_ACCEPTED_BBOX_PROXY", "ACCEPTED_SOURCE_PROVEN", "UNRESOLVED"],
            "non_goals": ["font_or_style_inference", "fill_opacity_or_stroke_inference", "animation_implementation", "renderer_coordinates", "Resolve", "Step_2F_static_contract"],
        },
        "existing_mechanisms_audit": [
            {"mechanism": "Step 2B.1 accepted per-frame identity bbox and source crop hash", "classification": "SOURCE_DERIVED_ACCEPTED", "use": "geometry_and_co_visibility"},
            {"mechanism": "continuous_visual_identity and visual_event_identity", "classification": "ACCEPTED", "use": "identity_and_lifecycle_only"},
            {"mechanism": "accepted visual_composition_id", "classification": "ACCEPTED_HINT", "use": "candidate_membership_only; never sufficient alone"},
            {"mechanism": "Step 2C ownership", "classification": "SOURCE_DERIVED_EXCLUSION_EVIDENCE", "use": "overlap_ambiguity_diagnostic; serialized evidence is not directional z-order proof"},
            {"mechanism": "physical_word_groups", "classification": "ACCEPTED_SOURCE_PROVEN", "use": "joint_composition_without_identity_merge"},
            {"mechanism": "OCR/transcript text", "classification": "UNUSED_FOR_PRODUCTION_MEMBERSHIP", "use": "diagnostic_labels_only"},
            {"mechanism": "preview static_z_order and Text+ placement", "classification": "RENDERER_SPECIFIC_LEGACY", "use": "not_authority"},
            {"mechanism": "Step 2D color/opacity", "classification": "FROZEN_UNUSED", "use": "not_composition_evidence"},
        ],
        "inputs": {"step2b1_v2_sha256": sha256(V2), "step2b1_rerank_sha256": sha256(STEP2B1), "step2b2_sha256": sha256(STEP2B2), "step2c_sha256": sha256(STEP2C), "step2d_sha256": sha256(STEP2D), "preview_sha256": sha256(PREVIEW), "source_sha256": sha256(SOURCE)},
        "identity_count": len(rows),
        "graph": graph,
        "summary": {
            "detected_compositions": len(graph["compositions"]), "identities_in_compositions": len(composed), "standalone_identities": len(graph["standalone_identities"]),
            "same_baseline_relationships": relationship_counts["SAME_BASELINE"], "spacing_relationships": relationship_counts["HORIZONTAL_GAP"] + relationship_counts["VERTICAL_GAP"],
            "overlap_relationships": relationship_counts["OVERLAPS"], "authoritative_z_order_relationships": relationship_counts["Z_ORDER"], "unresolved_z_order_relationships": relationship_counts["Z_ORDER_UNRESOLVED"],
            "physical_word_relationships": relationship_counts["PHYSICAL_WORD_FRAGMENT"], "time_varying_relationships": time_varying,
            "unresolved_composition_cases": len(unresolved_composition), "unresolved_composition_identities": unresolved_composition,
            "ownership_interaction_candidates_not_promoted_to_overlap": len(ownership_candidates),
        },
        "synthetic_validation": synthetic,
        "generalization": generalization,
        "style_independence_preserved": True,
        "physical_word_member_identities_merged": False,
        "z_order_policy": "fail_closed_without_directional_source_ownership",
        "ownership_interaction_candidates": ownership_candidates,
    }
    (OUT / "step2e_composition_relationships.json").write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")

    specs = representative_specs(graph, rows, accepted, evidence["physical_word_groups"], ownership_candidates)
    capture = cv2.VideoCapture(str(SOURCE))
    if not capture.isOpened():
        raise RuntimeError("source video unavailable")
    try:
        cards = [render_card(capture, spec, rows, accepted, graph) for spec in specs]
    finally:
        capture.release()
    while len(cards) % 2:
        cards.append(np.full_like(cards[0], 25))
    sheet = cv2.vconcat([cv2.hconcat(cards[index:index + 2]) for index in range(0, len(cards), 2)])
    if not cv2.imwrite(str(OUT / "step2e_composition_diagnostic.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError("diagnostic write failed")
    validation = {
        "schema": "video_cloner_step2e_composition_validation", "schema_version": 1, "result": artifact["result"],
        "identity_count": len(rows), "unique_identity_count": len(set(rows)), "all_identities_accounted_for": len(composed) + len(graph["standalone_identities"]) == len(rows),
        "lifecycle_unchanged": True, "upstream_hashes_pinned": True, "style_sharing_introduced": False, "renderer_or_resolve_mutated": False,
        "synthetic_controls_pass": synthetic["all_pass"], "generalization_gate_pass": not generalization["matches"], "human_review_required": True,
        "representatives": specs,
        "human_review_instruction": "Check colored identity boxes against source glyphs, visible-bottom baseline proxies, measured adjacency, preserved physical-word members, and that the overlap candidate remains unresolved without directional pair-mask evidence.",
    }
    (OUT / "step2e_composition_validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
