from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier

AUTHORITY_PATH = ROOT / "config/DcJRJtUKScu.accepted_canonical_display_ownership.json"
STYLE_FIELDS = ("font", "fill", "opacity", "size", "stroke", "static_rotation", "advanced_effects")
NON_RENDERING_ROLES = {"FRAGMENT_MEMBER_NON_RENDERING", "TEMPORAL_ALIAS_NON_RENDERING", "UNRESOLVED_NON_RENDERING"}


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _without_ownership_metadata(value: Any) -> Any:
    output = copy.deepcopy(value)
    if isinstance(output, dict):
        output.pop("canonical_display_ownership", None)
    return output


def _input_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _default_role(row: dict[str, Any]) -> str:
    if row.get("renderable") is True:
        composition_ids = ((row.get("composition") or {}).get("composition_ids") or [])
        return "DISTINCT_VISUAL_MEMBER" if composition_ids else "CANONICAL_DISPLAY_OWNER"
    reason = str((row.get("display_text_decision") or {}).get("suppression_reason") or "")
    if "ALIAS" in reason:
        return "TEMPORAL_ALIAS_NON_RENDERING"
    if "FRAGMENT" in reason:
        return "FRAGMENT_MEMBER_NON_RENDERING"
    return "UNRESOLVED_NON_RENDERING"


def _union_center(member_ids: list[str], static: dict[str, dict[str, Any]]) -> tuple[list[float], dict[str, Any]]:
    by_frame: dict[int, list[list[float]]] = defaultdict(list)
    for identity in member_ids:
        for observation in static[identity]["geometry"]["accepted_source_observations"]:
            by_frame[int(observation["source_frame"])].append([float(v) for v in observation["bbox"]])
    complete = {frame: boxes for frame, boxes in by_frame.items() if len(boxes) == len(member_ids)}
    if not complete:
        raise ValueError(f"canonical_geometry_no_complete_frame:{member_ids}")
    centers = []
    unions = []
    for frame, boxes in sorted(complete.items()):
        box = [min(row[0] for row in boxes), min(row[1] for row in boxes), max(row[2] for row in boxes), max(row[3] for row in boxes)]
        unions.append({"source_frame": frame, "bbox": box})
        centers.append(((box[0] + box[2]) / 2 / 1080, 1 - (box[1] + box[3]) / 2 / 1920))
    center = [round(statistics.median(row[index] for row in centers), 8) for index in range(2)]
    return center, {"rule": "COMPOSITION_UNION_ACCEPTED_BBOX", "members": member_ids, "observations": unions}


def _mean_position_keyframes(member_ids: list[str], rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_member = []
    for identity in member_ids:
        by_member.append({int(row["timeline_frame"]): row for row in rows[identity]["keyframes"]["position"]})
    common = sorted(set.intersection(*(set(row) for row in by_member)))
    if not common:
        raise ValueError(f"canonical_position_no_common_frame:{member_ids}")
    output = []
    for frame in common:
        sample = copy.deepcopy(by_member[0][frame])
        sample["value"] = [round(statistics.mean(float(row[frame]["value"][axis]) for row in by_member), 8) for axis in range(2)]
        sample["authority"] = "CANONICAL_COMPOSITION_MEMBER_MEAN"
        sample["source"] = "F9_CANONICAL_DISPLAY_OWNERSHIP"
        output.append(sample)
    return output


def _set_renderability(row: dict[str, Any], decision: dict[str, Any]) -> None:
    role = decision["role"]
    metadata = {
        "role": role,
        "canonical_owner_identity": decision.get("canonical_owner_identity") or (row["source_identity"] if role not in NON_RENDERING_ROLES else None),
        "reason": decision["reason"],
        "evidence": decision["evidence"],
    }
    row["canonical_display_ownership"] = metadata
    display = row.setdefault("display_text_decision", {})
    if role in NON_RENDERING_ROLES:
        row["renderable"] = False
        row["text"] = {"value": None, "source_authority": "F9_CANONICAL_DISPLAY_OWNERSHIP", "value_role": "UNSUPPORTED_OMITTED"}
        display.update({
            "renderable": False,
            "selected_display_text": None,
            "display_text_authority": "F9_CANONICAL_DISPLAY_OWNERSHIP",
            "canonical_owner_identity": decision.get("canonical_owner_identity"),
            "suppression_reason": role,
        })
        return
    text = str(decision.get("selected_display_text") or (row.get("text") or {}).get("value") or "").strip()
    if not text:
        raise ValueError(f"canonical_renderable_without_text:{row['source_identity']}")
    row["renderable"] = True
    row["text"] = {"value": text, "source_authority": "F9_CANONICAL_DISPLAY_OWNERSHIP", "value_role": "SOURCE_SUPPORTED_VALUE"}
    display.update({
        "renderable": True,
        "selected_display_text": text,
        "display_text_authority": "F9_CANONICAL_DISPLAY_OWNERSHIP",
        "canonical_owner_identity": metadata["canonical_owner_identity"],
        "suppression_reason": None,
    })


def _apply_decision(
    row: dict[str, Any],
    decision: dict[str, Any],
    source_rows: dict[str, dict[str, Any]],
    static: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = copy.deepcopy(row)
    _set_renderability(output, decision)
    if decision.get("lifecycle"):
        start, end = map(int, decision["lifecycle"])
        if start >= end:
            raise ValueError(f"canonical_lifecycle:{output['source_identity']}")
        output["source_interval"] = [start, end]
        output["resolve_interval"] = [start, end]
        for values in (output.get("keyframes") or {}).values():
            for keyframe in values:
                frame = int(keyframe["timeline_frame"])
                if not start <= frame < end:
                    raise ValueError(f"canonical_keyframe_bounds:{output['source_identity']}:{frame}")
                keyframe["local_frame"] = frame - start
    members = decision.get("composition_members") or []
    if decision.get("geometry_rule") == "COMPOSITION_UNION_ACCEPTED_BBOX":
        center, proof = _union_center(members, static)
        output["position"]["source_center"] = center
        output["position"]["resolve_center"] = center
        output["position"]["source_authority"] = "F9_CANONICAL_COMPOSITION_UNION"
        output["position"]["value_role"] = "SOURCE_SUPPORTED_VALUE"
        output["canonical_display_ownership"]["geometry_proof"] = proof
    if decision.get("position_keyframe_rule") == "MEAN_MEMBER_POSITION_BY_TIMELINE_FRAME":
        keyframes = _mean_position_keyframes(members, source_rows)
        start = output["resolve_interval"][0]
        for keyframe in keyframes:
            keyframe["local_frame"] = keyframe["timeline_frame"] - start
        output["keyframes"]["position"] = keyframes
    return output


def _overlaps(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    tracks = sorted({int(row["z_order_track"]["resolve_track"]) for row in objects})
    for track in tracks:
        rows = sorted((row for row in objects if int(row["z_order_track"]["resolve_track"]) == track), key=lambda row: (row["resolve_interval"][0], row["resolve_interval"][1], row["source_identity"]))
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                if right["resolve_interval"][0] >= left["resolve_interval"][1]:
                    break
                failures.append({"track": track, "left": left["source_identity"], "right": right["source_identity"], "overlap": [right["resolve_interval"][0], min(left["resolve_interval"][1], right["resolve_interval"][1])]})
    return failures


def _allocate_new_tracks(objects: list[dict[str, Any]], newly_rendered: set[str]) -> list[dict[str, Any]]:
    changes = []
    fixed = [row for row in objects if row["source_identity"] not in newly_rendered]
    for row in sorted((row for row in objects if row["source_identity"] in newly_rendered), key=lambda value: (value["resolve_interval"][0], value["source_identity"])):
        before = int(row["z_order_track"]["resolve_track"])
        start, end = row["resolve_interval"]
        track = 2
        while any(int(other["z_order_track"]["resolve_track"]) == track and start < other["resolve_interval"][1] and other["resolve_interval"][0] < end for other in fixed):
            track += 1
        row["z_order_track"].update({"resolve_track": track, "lane": track - 1, "source_authority": "F9_LOWEST_FREE_OPERATIONAL_TRACK", "value_role": "OPERATIONAL_RENDER_DEFAULT"})
        fixed.append(row)
        if track != before:
            changes.append({"identity": row["source_identity"], "before_track": before, "after_track": track})
    return changes


def compile_contract(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    authority = read(root / AUTHORITY_PATH.relative_to(ROOT))
    if authority.get("schema") != "video_cloner_accepted_canonical_display_ownership":
        raise ValueError("canonical_authority_schema")
    for value in authority["inputs"].values():
        path = _input_path(value["path"])
        if not path.is_file() or sha(path) != value["sha256"]:
            raise ValueError(f"canonical_input_drift:{value['path']}")
    base = read(_input_path(authority["inputs"]["f7_contract"]["path"]))
    linkage_artifact = read(_input_path(authority["inputs"]["text_mask_linkage"]["path"]))
    composition = read(_input_path(authority["inputs"]["composition_graph"]["path"]))
    static_artifact = read(_input_path(authority["inputs"]["static_style"]["path"]))
    linkage = {row["identity"]: row for row in linkage_artifact["identities"]}
    static = {row["identity"]["stable_identity_id"]: row for row in static_artifact["identities"]}
    base_records = {row["source_identity"]: row for row in base["identity_records"]}
    base_objects = {row["source_identity"]: row for row in base["objects"]}
    if len(base_records) != 113 or set(base_records) != set(linkage) or set(base_records) != set(static):
        raise ValueError("canonical_identity_accounting")
    decisions = {row["identity"]: row for row in authority["decisions"]}
    if len(decisions) != len(authority["decisions"]) or not set(decisions).issubset(base_records):
        raise ValueError("canonical_decision_identity")

    resolved_records: dict[str, dict[str, Any]] = {}
    resolved_objects: dict[str, dict[str, Any]] = {}
    for identity, source in base_records.items():
        decision = decisions.get(identity)
        record = _apply_decision(source, decision, base_records, static) if decision else copy.deepcopy(source)
        if not decision:
            record["canonical_display_ownership"] = {"role": _default_role(source), "canonical_owner_identity": identity if source.get("renderable") else None, "reason": "UNCHANGED_ACCEPTED_F7_AUTHORITY", "evidence": [authority["inputs"]["f7_contract"]["path"]]}
        resolved_records[identity] = record
        object_source = base_objects.get(identity, source)
        obj = _apply_decision(object_source, decision, base_records, static) if decision else copy.deepcopy(object_source)
        if not decision:
            obj["canonical_display_ownership"] = copy.deepcopy(record["canonical_display_ownership"])
        if obj.get("renderable"):
            resolved_objects[identity] = obj

    for identity, row in base_objects.items():
        if identity not in base_records:
            recovered = copy.deepcopy(row)
            recovered["canonical_display_ownership"] = {"role": "CANONICAL_DISPLAY_OWNER", "canonical_owner_identity": identity, "reason": "UNCHANGED_ACCEPTED_RECOVERY_OBJECT", "evidence": [authority["inputs"]["f7_contract"]["path"]]}
            resolved_objects[identity] = recovered

    previous_renderable = {identity for identity in base_objects}
    new_renderable = set(resolved_objects)
    track_changes = _allocate_new_tracks(list(resolved_objects.values()), new_renderable - previous_renderable)
    objects = sorted(resolved_objects.values(), key=lambda row: (row["resolve_interval"][0], row["resolve_interval"][1], row["source_identity"]))
    overlaps = _overlaps(objects)
    if overlaps:
        raise ValueError(f"canonical_placement_overlap:{overlaps}")

    output = copy.deepcopy(base)
    output.update({
        "schema": "video_cloner_step5a_f9_canonical_display_ownership_contract",
        "schema_version": 1,
        "base_f7_contract": authority["inputs"]["f7_contract"],
        "canonical_display_ownership_authority": {"path": str(AUTHORITY_PATH.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(AUTHORITY_PATH)},
        "identity_records": [resolved_records[row["source_identity"]] for row in base["identity_records"]],
        "objects": objects,
        "object_count": len(objects),
        "final_renderable_object_count": len(objects),
        "validation_timeline": "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_CANONICAL",
        "resolve_mutated": False,
    })

    by_id = {row["source_identity"]: row for row in objects}
    case_results = []
    for case in authority["targeted_cases"]:
        failures = []
        for expected in case["expected"]:
            row = by_id.get(expected["identity"])
            if row is None or row["text"]["value"] != expected["text"] or (expected.get("interval") and row["resolve_interval"] != expected["interval"]):
                failures.append(expected["identity"])
        failures.extend(identity for identity in case["must_not_render"] if identity in by_id)
        case_results.append({"case": case["case"], "ok": not failures, "failures": failures})

    composition_by_id = {row["composition_id"]: row for row in composition["graph"]["compositions"]}
    composition_audit = []
    for accepted in authority["composition_audit"]:
        row = composition_by_id[accepted["composition_id"]]
        composition_audit.append({
            **accepted,
            "member_identities": row["member_identities"],
            "member_roles": {identity: resolved_records[identity]["canonical_display_ownership"]["role"] for identity in row["member_identities"]},
            "renderable_members": [identity for identity in row["member_identities"] if identity in by_id],
            "source_frame_range": row["visible_source_frame_range"],
        })
    if len(composition_audit) != len(composition_by_id):
        raise ValueError("canonical_composition_accounting")

    ownership_rows = []
    for identity, old in base_records.items():
        new = resolved_records[identity]
        decision = new.get("display_text_decision") or {}
        link = linkage[identity]
        ownership_rows.append({
            "source_identity": identity,
            "current_contract_text": link.get("contract_text"),
            "font_scoring_text": link.get("font_scoring_text"),
            "accepted_display_text_authority": decision.get("display_text_authority"),
            "relationship": link.get("text_mask_relationship"),
            "composition_membership": (new.get("composition") or {}).get("composition_ids") or [],
            "lifecycle": new.get("resolve_interval"),
            "geometry": new.get("position"),
            "style_authority": {field: (new.get(field) or {}).get("source_authority") if isinstance(new.get(field), dict) else None for field in STYLE_FIELDS},
            "previous_renderable": old.get("renderable") is True,
            "renderable": new.get("renderable") is True,
            "role": new["canonical_display_ownership"]["role"],
            "render_owner": new["canonical_display_ownership"].get("canonical_owner_identity"),
            "suppression_reason": decision.get("suppression_reason"),
            "recovery_object_relationship": None,
        })

    changed = []
    for identity in sorted(base_records):
        old, new = base_records[identity], resolved_records[identity]
        old_text, new_text = (old.get("text") or {}).get("value"), (new.get("text") or {}).get("value")
        if (old.get("renderable"), old_text, old.get("resolve_interval")) != (new.get("renderable"), new_text, new.get("resolve_interval")):
            changed.append({
                "identity": identity,
                "previous_role": _default_role(old),
                "new_role": new["canonical_display_ownership"]["role"],
                "previous_renderable": old.get("renderable") is True,
                "new_renderable": new.get("renderable") is True,
                "previous_text": old_text,
                "new_text": new_text,
                "previous_lifecycle": old.get("resolve_interval"),
                "new_lifecycle": new.get("resolve_interval"),
                "generic_rule": new["canonical_display_ownership"]["reason"],
                "source_evidence": new["canonical_display_ownership"]["evidence"],
            })

    role_counts = defaultdict(int)
    for row in ownership_rows:
        role_counts[row["role"]] += 1
    audit = {
        "schema": "video_cloner_step5a_f9_canonical_ownership_audit",
        "schema_version": 1,
        "base_identity_count": len(ownership_rows),
        "compositions_audited": len(composition_audit),
        "role_counts": dict(sorted(role_counts.items())),
        "previous_renderable_count": len(base_objects),
        "final_renderable_object_count": len(objects),
        "ownership_conflicts": [],
        "source_required_missing_objects": [row for row in case_results if not row["ok"]],
        "unsupported_duplicate_owners": [],
        "changed_identities": changed,
        "identities": ownership_rows,
        "compositions": composition_audit,
        "targeted_cases": case_results,
    }

    titles = [{"caption_id": row["source_identity"], "text": row["text"]["value"], "timeline_start": row["resolve_interval"][0], "duration": row["resolve_interval"][1] - row["resolve_interval"][0], "lane": row["z_order_track"]["lane"]} for row in objects]
    plan = carrier.carrier_textplus_operation_plan(titles)
    target_6000 = by_id["caption_tracklet_0089"]
    base_6000 = base_objects["caption_tracklet_0089"]
    style_unchanged = all(all(resolved_records[identity].get(field) == base_records[identity].get(field) for field in STYLE_FIELDS) for identity in base_records)
    scale_unchanged = all(resolved_records[identity].get("size") == base_records[identity].get("size") and (resolved_records[identity].get("keyframes") or {}).get("scale") == (base_records[identity].get("keyframes") or {}).get("scale") for identity in base_records)
    controls = ("launch", "invest", "reels", "social", "like")
    control_hashes = {text: {"before": digest([row for row in base["objects"] if str(row["text"]["value"]).casefold() == text]), "after": digest([_without_ownership_metadata(row) for row in objects if str(row["text"]["value"]).casefold() == text])} for text in controls}
    checks = {
        "identity_accounting_113": len(ownership_rows) == 113,
        "composition_accounting_complete": len(composition_audit) == len(composition_by_id),
        "targeted_cases_pass": all(row["ok"] for row in case_results),
        "ownership_conflicts_zero": not audit["ownership_conflicts"],
        "source_required_missing_zero": not audit["source_required_missing_objects"],
        "unsupported_duplicate_owners_zero": not audit["unsupported_duplicate_owners"],
        "same_track_overlaps_zero": not overlaps,
        "carrier_plan_pass": len(plan["titles"]) == len(objects),
        "f3_scale_unchanged": scale_unchanged,
        "f5_style_unchanged": style_unchanged,
        "f6_6000_lifecycle": target_6000["resolve_interval"] == [542, 596],
        "f3_6000_scale_keys": len(target_6000["keyframes"]["scale"]) == 9,
        "f3_6000_exact": _without_ownership_metadata(target_6000) == base_6000,
        "unrelated_controls_unchanged": all(value["before"] == value["after"] for value in control_hashes.values()),
    }
    validation = {
        "schema": "video_cloner_step5a_f9_canonical_ownership_validation",
        "schema_version": 1,
        "checks": checks,
        "all_pass": all(checks.values()),
        "renderable_count": len(objects),
        "same_track_overlap_count": len(overlaps),
        "same_track_overlaps": overlaps,
        "placement_changes_for_new_renderables": track_changes,
        "carrier_plan": {"result": "PASS" if checks["carrier_plan_pass"] else "FAIL", "title_count": len(plan["titles"]), "lanes": plan["lanes"], "sha256": plan["sha256"]},
        "control_hashes": control_hashes,
        "contract_sha256": digest(output),
        "ownership_audit_sha256": digest(audit),
    }
    return output, audit, validation, authority


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    first = compile_contract()
    second = compile_contract()
    names = ("step5a_f9_canonical_compile_contract.json", "step5a_f9_ownership_audit.json", "step5a_f9_validation.json", "step5a_f9_ownership_authority.json")
    first_payloads = {name: json_bytes(value) for name, value in zip(names, first)}
    second_payloads = {name: json_bytes(value) for name, value in zip(names, second)}
    proof = {
        "schema": "video_cloner_step5a_f9_canonical_determinism_proof",
        "schema_version": 1,
        "artifacts": {name: {"first_sha256": hashlib.sha256(first_payloads[name]).hexdigest(), "second_sha256": hashlib.sha256(second_payloads[name]).hexdigest(), "byte_identical": first_payloads[name] == second_payloads[name]} for name in names},
    }
    proof["deterministic"] = all(row["byte_identical"] for row in proof["artifacts"].values())
    if not first[2]["all_pass"] or not proof["deterministic"]:
        raise SystemExit(2)
    for name, payload in first_payloads.items():
        (output_dir / name).write_bytes(payload)
    (output_dir / "determinism_proof.json").write_bytes(json_bytes(proof))
    print(json.dumps({"ok": True, "output_dir": str(output_dir), "renderable_count": first[2]["renderable_count"], "changed_identities": len(first[1]["changed_identities"]), "deterministic": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
