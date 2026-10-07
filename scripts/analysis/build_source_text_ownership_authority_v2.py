#!/usr/bin/env python3
"""Build bounded source text/ownership authority from accepted Reel evidence."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np


TEXT_STATES = {
    "SOURCE_TEXT_EXACT", "SOURCE_TEXT_FRAGMENT", "SOURCE_TEXT_COMPOSITION_MEMBER",
    "SOURCE_TEXT_TEMPORAL_ALIAS", "SOURCE_TEXT_NOT_INDEPENDENTLY_VISIBLE",
    "SOURCE_TEXT_REJECTED_NOISE", "SOURCE_TEXT_UNRESOLVED_BLOCKER",
}
OWNERSHIP_ROLES = {
    "CANONICAL_SOURCE_OBJECT", "DISTINCT_SIMULTANEOUS_MEMBER",
    "PHYSICAL_WORD_FRAGMENT_NON_OWNER", "TEMPORAL_ALIAS_NON_OWNER",
    "NON_VISIBLE_OR_REJECTED", "UNRESOLVED_BLOCKER",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", str(value or "").lower()))


def compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def similarity(a: Any, b: Any) -> float:
    aa, bb = compact(a), compact(b)
    return round(SequenceMatcher(None, aa, bb).ratio(), 6) if aa and bb else 0.0


def bbox_iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = max(1.0, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return round(inter / union, 6)


def direct_f9_role(row: Mapping[str, Any]) -> str | None:
    ownership = row.get("canonical_display_ownership") or {}
    if ownership.get("reason") == "UNCHANGED_ACCEPTED_F7_AUTHORITY":
        return None
    return ownership.get("role")


def classify_text(link: Mapping[str, Any], source: Mapping[str, Any], style: Mapping[str, Any], f9: Mapping[str, Any]) -> dict[str, Any]:
    observed = str(source.get("observed_text") or "")
    contract = str(link.get("contract_text") or "")
    relationship = str(link.get("text_mask_relationship") or "")
    observations = style["geometry"].get("accepted_source_observations") or []
    memberships = style["identity"].get("composition_memberships") or []
    score = similarity(observed, contract)
    role = direct_f9_role(f9)

    if role == "TEMPORAL_ALIAS_NON_RENDERING":
        state, selected, confidence, rule = "SOURCE_TEXT_TEMPORAL_ALIAS", observed or contract, 0.98, "accepted_direct_temporal_continuity"
    elif relationship == "ACCEPTED_PHYSICAL_WORD_FRAGMENT":
        state, selected, confidence, rule = "SOURCE_TEXT_FRAGMENT", observed or contract, 0.98, "accepted_physical_word_fragment"
    elif norm(observed) == norm(contract) and norm(observed):
        state, selected, confidence, rule = "SOURCE_TEXT_EXACT", observed, 1.0, "accepted_direct_source_text_exact"
    elif memberships and (compact(contract) in compact(observed) or compact(observed) in compact(contract)) and compact(observed):
        state, selected, confidence, rule = "SOURCE_TEXT_COMPOSITION_MEMBER", contract, 0.9, "source_text_containment_plus_composition_geometry"
    elif score >= 0.72 and len(observations) >= 2 and compact(link.get("glyph_artifact_text")) == compact(contract):
        state, selected, confidence, rule = "SOURCE_TEXT_EXACT", contract, round(min(0.95, 0.65 + score * 0.3), 3), "multi_frame_bbox_mask_plus_glyph_consensus_corrects_noisy_ocr"
    else:
        state, selected, confidence, rule = "SOURCE_TEXT_UNRESOLVED_BLOCKER", None, round(score, 3), "accepted_source_text_conflicts_with_existing_text_and_bounded_evidence_is_not_decisive"

    frames = sorted({int(x["source_frame"]) for x in observations if x.get("source_frame") is not None})
    if not frames:
        first, last = int(source["first_visible_frame"]), int(source["last_visible_frame"])
        frames = sorted({first, (first + last) // 2, last})
    return {
        "state": state,
        "selected_source_visible_text": selected,
        "normalized_text": norm(selected),
        "confidence": confidence,
        "generic_rule": rule,
        "evidence": {
            "accepted_direct_observed_text": observed,
            "contract_text_diagnostic": contract,
            "text_similarity": score,
            "source_frames": frames,
            "source_visible_range": [int(source["first_visible_frame"]), int(source["last_visible_frame"])],
            "representative_bbox": source["bbox"],
            "accepted_bbox_observation_count": len(observations),
            "mask_relationship": relationship,
            "source_provenance": source.get("source_evidence_provenance") or [],
        },
    }


def ownership_for(text: Mapping[str, Any], style: Mapping[str, Any], f9: Mapping[str, Any]) -> tuple[str, str]:
    if text["state"] == "SOURCE_TEXT_UNRESOLVED_BLOCKER":
        return "UNRESOLVED_BLOCKER", "text_authority_unresolved"
    direct = direct_f9_role(f9)
    if direct == "TEMPORAL_ALIAS_NON_RENDERING":
        return "TEMPORAL_ALIAS_NON_OWNER", "accepted_direct_temporal_continuity"
    if direct == "FRAGMENT_MEMBER_NON_RENDERING" or text["state"] == "SOURCE_TEXT_FRAGMENT":
        return "PHYSICAL_WORD_FRAGMENT_NON_OWNER", "accepted_physical_word_ownership"
    if text["state"] == "SOURCE_TEXT_NOT_INDEPENDENTLY_VISIBLE":
        return "NON_VISIBLE_OR_REJECTED", "source_not_independently_visible"
    if style["identity"].get("composition_memberships"):
        return "DISTINCT_SIMULTANEOUS_MEMBER", "source_composition_co_visibility"
    return "CANONICAL_SOURCE_OBJECT", "independent_source_visible_identity"


def composition_type(comp: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]], relations: list[Mapping[str, Any]]) -> dict[str, Any]:
    members = list(comp["member_identities"])
    member_rows = [rows[x] for x in members]
    physical = [x for x in member_rows if x["ownership_role"] == "PHYSICAL_WORD_FRAGMENT_NON_OWNER"]
    unresolved = [x["identity"] for x in member_rows if x["ownership_role"] == "UNRESOLVED_BLOCKER"]
    co_visible = [x for x in relations if x.get("relationship_type") == "CO_VISIBLE" and x.get("source_identity") in members and x.get("target_identity") in members]
    if unresolved:
        selected, confidence, reason = "UNRESOLVED_BLOCKER", 0.0, "one_or_more_member_text_or_ownership_decisions_remain_unresolved"
    elif physical and len(physical) < len(member_rows) and len(member_rows) > 2:
        selected, confidence, reason = "MIXED_COMPOSITION", 0.95, "physical_or_duplicate_fragment_and_distinct_co_visible_members"
    elif physical:
        selected, confidence, reason = "ONE_PHYSICAL_WORD_FROM_MULTIPLE_FRAGMENTS", 0.98, "accepted_physical_word_fragment_evidence"
    elif co_visible:
        selected, confidence, reason = "MULTIPLE_DISTINCT_SIMULTANEOUS_OBJECTS", 0.95, "accepted_multi_frame_co_visibility_and_independent_member_geometry"
    else:
        selected, confidence, reason = "UNRESOLVED_BLOCKER", 0.0, "membership_exists_without_decisive_co_visibility_or_fragment_authority"
    return {
        "composition_id": comp["composition_id"], "members": members,
        "supporting_frames": comp.get("supporting_frames") or [],
        "member_bboxes": {x["identity"]: x["text_authority"]["evidence"]["representative_bbox"] for x in member_rows},
        "co_visibility": {"proven": bool(co_visible), "relationship_count": len(co_visible)},
        "spatial_relationships": [x for x in relations if x.get("source_identity") in members and x.get("target_identity") in members],
        "selected_type": selected, "reason": reason, "confidence": confidence,
        "unresolved_members": unresolved,
    }


def continuity(rows: Mapping[str, Mapping[str, Any]], candidates: set[str], f9: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted((rows[x] for x in candidates), key=lambda x: (x["source_visible_range"][0], x["identity"]))
    result: list[dict[str, Any]] = []
    for i, left in enumerate(ordered):
        for right in ordered[i + 1:]:
            gap = right["source_visible_range"][0] - left["source_visible_range"][1] - 1
            if gap > 4:
                break
            text_score = similarity(left["contract_text_diagnostic"], right["contract_text_diagnostic"])
            overlap = bbox_iou(left["text_authority"]["evidence"]["representative_bbox"], right["text_authority"]["evidence"]["representative_bbox"])
            if text_score < 0.6 and overlap < 0.35:
                continue
            direct_left, direct_right = direct_f9_role(f9[left["identity"]]), direct_f9_role(f9[right["identity"]])
            if "TEMPORAL_ALIAS_NON_RENDERING" in {direct_left, direct_right} and text_score >= 0.6:
                decision, reason, confidence = "SAME_SOURCE_VISUAL_OBJECT", "accepted_direct_continuity_authority", 0.98
            elif gap < 0:
                decision, reason, confidence = "DISTINCT_REPEATED_OBJECT", "source_intervals_overlap", 0.95
            elif gap <= 1 and text_score >= 0.9 and overlap >= 0.45:
                decision, reason, confidence = "UNRESOLVED_BLOCKER", "adjacent_similar_tracks_need_owner_adjudication", 0.0
            else:
                decision, reason, confidence = "NO_CONTINUITY", "insufficient_joint_text_geometry_continuity", 0.9
            result.append({
                "left_identity": left["identity"], "right_identity": right["identity"],
                "decision": decision, "reason": reason, "confidence": confidence,
                "evidence": {"frame_gap": gap, "text_similarity": text_score, "representative_bbox_iou": overlap},
            })
    return result


def branch_audit(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    counts = {"literal": 0, "identity": 0, "reel": 0}
    schema_values = TEXT_STATES | OWNERSHIP_ROLES | {
        "UNCHANGED_ACCEPTED_F7_AUTHORITY", "TEMPORAL_ALIAS_NON_RENDERING", "FRAGMENT_MEMBER_NON_RENDERING",
        "ACCEPTED_PHYSICAL_WORD_FRAGMENT", "EXACT_MATCH", "MATCHED", "CO_VISIBLE",
    }
    production_functions = {"classify_text", "ownership_for", "composition_type", "continuity", "build"}
    roots = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in production_functions]
    for root in roots:
      for node in ast.walk(root):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        values = [x.value for x in operands if isinstance(x, ast.Constant) and isinstance(x.value, str)]
        names = {x.id.lower() for x in ast.walk(node) if isinstance(x, ast.Name)}
        for value in values:
            low = value.lower()
            if "caption_tracklet_" in low or "continuous_visual_identity_" in low or "source_visible_recovery_" in low:
                counts["identity"] += 1
            elif "composition_" in low:
                counts["identity"] += 1
            elif re.fullmatch(r"[a-z0-9]{11}", low) and any(x.isalpha() for x in low) and any(x.isdigit() for x in low):
                counts["reel"] += 1
            elif value not in schema_values and names & {"text", "observed", "contract", "selected", "literal"}:
                counts["literal"] += 1
    return counts


def previous_v2_states(f9: Mapping[str, Any]) -> tuple[str, str]:
    text = str((f9.get("display_text_decision") or {}).get("display_text_authority") or "")
    role = str((f9.get("canonical_display_ownership") or {}).get("role") or "")
    text_map = {
        "UNRESOLVED": "SOURCE_TEXT_UNRESOLVED_BLOCKER",
        "UNSAFE_OR_INCONSISTENT_TEXT_AUTHORITY": "SOURCE_TEXT_UNRESOLVED_BLOCKER",
        "ACCEPTED_VISUAL_FRAGMENT": "SOURCE_TEXT_COMPOSITION_MEMBER",
    }
    role_map = {
        "UNRESOLVED_NON_RENDERING": "UNRESOLVED_BLOCKER",
        "CANONICAL_DISPLAY_OWNER": "CANONICAL_SOURCE_OBJECT",
        "DISTINCT_VISUAL_MEMBER": "DISTINCT_SIMULTANEOUS_MEMBER",
        "FRAGMENT_MEMBER_NON_RENDERING": "PHYSICAL_WORD_FRAGMENT_NON_OWNER",
        "TEMPORAL_ALIAS_NON_RENDERING": "TEMPORAL_ALIAS_NON_OWNER",
    }
    return text_map.get(text, "SOURCE_TEXT_EXACT"), role_map.get(role, "UNRESOLVED_BLOCKER")


def contact_sheet(video: Path, blockers: list[Mapping[str, Any]], output: Path) -> None:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"video_open_failed:{video}")
    width, panel_h, label_h = 320, 190, 58
    sheet = np.full((max(1, len(blockers)) * (panel_h + label_h), width * 3, 3), 28, np.uint8)
    for row_index, row in enumerate(blockers):
        evidence = row["text_authority"]["evidence"]
        start, end = evidence["source_visible_range"]
        frames = [start, (start + end) // 2, end]
        bbox = evidence["representative_bbox"]
        y0 = row_index * (panel_h + label_h)
        cv2.putText(sheet, f"{row['identity']}  observed={evidence['accepted_direct_observed_text']!r}", (8, y0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.47, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(sheet, f"contract={row['contract_text_diagnostic']!r}", (8, y0 + 43), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (200, 210, 255), 1, cv2.LINE_AA)
        for col, frame_no in enumerate(frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ok, frame = cap.read()
            if not ok:
                continue
            x1, y1, x2, y2 = [int(v) for v in bbox]
            pad_x, pad_y = max(30, (x2 - x1) // 3), max(24, (y2 - y1) // 2)
            crop = frame[max(0, y1-pad_y):min(frame.shape[0], y2+pad_y), max(0, x1-pad_x):min(frame.shape[1], x2+pad_x)]
            if crop.size:
                crop = cv2.resize(crop, (width, panel_h), interpolation=cv2.INTER_AREA)
                sheet[y0 + label_h:y0 + label_h + panel_h, col * width:(col + 1) * width] = crop
                cv2.putText(sheet, f"frame {frame_no}", (col * width + 8, y0 + label_h + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    cap.release()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet):
        raise ValueError(f"contact_sheet_write_failed:{output}")


def build(args: argparse.Namespace) -> dict[str, Any]:
    paths = {name: Path(getattr(args, name)).resolve() for name in ("source", "linkage", "composition", "style", "f9", "video")}
    source, linkage, composition, style, f9 = (load(paths[x]) for x in ("source", "linkage", "composition", "style", "f9"))
    source_by_id = {x["mapped_visual_identity"]: x for x in source["objects"] if x.get("status") == "MATCHED"}
    link_by_id = {x["identity"]: x for x in linkage["identities"]}
    style_by_id = {x["identity"]["stable_identity_id"]: x for x in style["identities"]}
    f9_by_id = {x["source_identity"]: x for x in f9["identity_records"]}
    identities = set(link_by_id)
    if identities != set(source_by_id) or identities != set(style_by_id) or identities != set(f9_by_id) or len(identities) != 113:
        raise ValueError("identity_accounting_mismatch")

    comp_members = {x for c in composition["graph"]["compositions"] for x in c["member_identities"]}
    candidates = {
        identity for identity in identities
        if link_by_id[identity]["text_mask_relationship"] != "EXACT_MATCH"
        or norm(source_by_id[identity].get("observed_text")) != norm(link_by_id[identity].get("contract_text"))
        or identity in comp_members
        or not f9_by_id[identity].get("renderable")
    }
    controls = identities - candidates
    rows: dict[str, dict[str, Any]] = {}
    for identity in sorted(identities):
        text = classify_text(link_by_id[identity], source_by_id[identity], style_by_id[identity], f9_by_id[identity])
        role, reason = ownership_for(text, style_by_id[identity], f9_by_id[identity])
        previous_text, previous_owner = previous_v2_states(f9_by_id[identity])
        rows[identity] = {
            "identity": identity, "candidate": identity in candidates,
            "previous_text_state": previous_text,
            "previous_ownership_state": previous_owner,
            "contract_text_diagnostic": link_by_id[identity].get("contract_text"),
            "source_visible_range": [source_by_id[identity]["first_visible_frame"], source_by_id[identity]["last_visible_frame"]],
            "composition_memberships": style_by_id[identity]["identity"].get("composition_memberships") or [],
            "text_authority": text, "ownership_role": role, "ownership_reason": reason,
        }

    compositions = [composition_type(x, rows, composition["graph"]["relationships"]) for x in composition["graph"]["compositions"]]
    continuity_rows = continuity(rows, candidates, f9_by_id)
    unresolved_ids = sorted(x for x, row in rows.items() if row["text_authority"]["state"] == "SOURCE_TEXT_UNRESOLVED_BLOCKER" or row["ownership_role"] == "UNRESOLVED_BLOCKER")
    unresolved_comps = [x["composition_id"] for x in compositions if x["selected_type"] == "UNRESOLVED_BLOCKER"]
    unresolved_links = [x for x in continuity_rows if x["decision"] == "UNRESOLVED_BLOCKER"]
    blockers = [rows[x] for x in unresolved_ids]
    out = Path(args.output).resolve()
    inputs = {name: {"path": str(path), "sha256": sha256(path)} for name, path in paths.items()}
    text_counts = Counter(x["text_authority"]["state"] for x in rows.values())
    ownership_counts = Counter(x["ownership_role"] for x in rows.values())
    composition_counts = Counter(x["selected_type"] for x in compositions)
    audit = branch_audit(Path(__file__))
    status = "READY_FOR_WHOLE_REEL_COVERAGE_GATE" if not unresolved_ids and not unresolved_comps and not unresolved_links and not any(audit.values()) else "BLOCKED_SOURCE_AUTHORITY"
    authority = {
        "schema": "video_cloner_source_text_ownership_authority_v2", "schema_version": 2, "status": status,
        "inputs": inputs, "scope": {"base_identities_inspected": 113, "repair_candidates": len(candidates), "accepted_controls": len(controls)},
        "candidate_derivation": ["non_exact_linkage", "source_text_contract_disagreement", "composition_member", "no_current_generated_owner"],
        "counts": {"text": dict(text_counts), "ownership": dict(ownership_counts)},
        "production_branch_audit": audit, "identities": [rows[x] for x in sorted(rows)],
    }
    comp_artifact = {"schema": "video_cloner_composition_type_authority_v2", "schema_version": 2, "status": status, "count": len(compositions), "counts": dict(composition_counts), "compositions": compositions}
    continuity_artifact = {"schema": "video_cloner_continuity_authority_v2", "schema_version": 2, "status": status, "count": len(continuity_rows), "counts": dict(Counter(x["decision"] for x in continuity_rows)), "relationships": continuity_rows}
    changes = []
    for row in rows.values():
        new_text, new_owner = row["text_authority"]["state"], row["ownership_role"]
        if row["previous_text_state"] != new_text or row["previous_ownership_state"] != new_owner:
            changes.append({
                "identity": row["identity"], "previous_text_state": row["previous_text_state"], "new_text_state": new_text,
                "previous_ownership_state": row["previous_ownership_state"], "new_ownership_state": new_owner,
                "source_evidence": row["text_authority"]["evidence"], "generic_rule": row["text_authority"]["generic_rule"],
                "confidence": row["text_authority"]["confidence"],
            })
    change_artifact = {"schema": "video_cloner_authority_change_report_v2", "schema_version": 2, "changed_identity_count": len(changes), "unchanged_control_count": sum(1 for x in controls if not any(c["identity"] == x for c in changes)), "changes": changes}
    blocker_artifact = {
        "schema": "video_cloner_source_authority_blockers_v2", "schema_version": 2, "status": status,
        "identity_blocker_count": len(unresolved_ids), "composition_blocker_count": len(unresolved_comps), "continuity_blocker_count": len(unresolved_links),
        "identity_blockers": blockers, "composition_blockers": unresolved_comps, "continuity_blockers": unresolved_links,
        "human_review_instruction": "Review all rows in the single consolidated contact sheet; adjudicate observed source text and whether each track is an independent object, fragment, alias, or noise." if blockers else None,
    }
    write(out / "source_text_ownership_authority_v2.json", authority)
    write(out / "composition_type_authority_v2.json", comp_artifact)
    write(out / "continuity_authority_v2.json", continuity_artifact)
    write(out / "authority_change_report.json", change_artifact)
    write(out / "unresolved_blockers.json", blocker_artifact)
    if blockers:
        contact_sheet(paths["video"], blockers, out / "unresolved_blockers_contact_sheet.png")
    return {"status": status, "output": str(out), "scope": authority["scope"], "text": dict(text_counts), "ownership": dict(ownership_counts), "compositions": dict(composition_counts), "continuity": continuity_artifact["counts"], "changes": len(changes), "branch_audit": audit}


def self_test() -> None:
    assert norm("We don't!") == "we don't"
    assert compact("social,") == "social"
    assert similarity("launcn", "launch") > 0.8
    assert bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert TEXT_STATES.isdisjoint(OWNERSHIP_ROLES)
    print("SELF_TEST_PASS")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--source")
    p.add_argument("--linkage")
    p.add_argument("--composition")
    p.add_argument("--style")
    p.add_argument("--f9")
    p.add_argument("--video")
    p.add_argument("--output")
    p.add_argument("--self-test", action="store_true")
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    if args.self_test:
        self_test()
    else:
        missing = [x for x in ("source", "linkage", "composition", "style", "f9", "video", "output") if not getattr(args, x)]
        if missing:
            raise SystemExit("missing arguments: " + ", ".join(missing))
        print(json.dumps(build(args), indent=2, sort_keys=True))
