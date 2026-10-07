from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("VIDEO_CLONER_ROOT", Path(__file__).resolve().parents[2])).resolve()
F5_CONTRACT = Path(
    ".agent/reports/VIDEO_CLONER_STEP5_F5D_HUMAN_APPROVED_STATIC_STYLE_20261001_V1/"
    "20261001T080530587Z/first/step5_f5_compile_contract.json"
)
F5_SHA256 = "2b7233d6392cae19bc5ea76446661a7be5fc23b67de0eff0d52c940fd9ab24e6"
LIFECYCLE_AUTHORITY = Path("config/DcJRJtUKScu.accepted_lifecycle_end_correction.json")
LIFECYCLE_AUTHORITY_SHA256 = "368092b4723021743e4f43784693f4bfbdce5645c7bdae25cbf761601214b047"
AUTHORITY = "ACCEPTED_LIFECYCLE_END_CORRECTION"


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pinned(root: Path, path: Path, expected: str) -> dict[str, Any]:
    actual = _sha256(root / path)
    if actual != expected:
        raise ValueError(f"pinned_hash_mismatch:{path.as_posix()}:{actual}")
    return json.loads((root / path).read_text(encoding="utf-8-sig"))


def _rows_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {row["source_identity"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate_source_identity")
    return result


def _validate_authority(root: Path, authority: dict[str, Any]) -> None:
    records = authority.get("records") or []
    if authority.get("schema") != "video_cloner_accepted_lifecycle_end_correction":
        raise ValueError("lifecycle_authority_schema")
    if authority.get("authority") != AUTHORITY or authority.get("reproduction_authority") is not True:
        raise ValueError("lifecycle_authority_not_accepted")
    if not records or len({row.get("object_id") for row in records}) != len(records):
        raise ValueError("lifecycle_authority_records")
    mapping = authority.get("canonical_mapping") or {}
    source_fps = float(mapping.get("source_fps") or 0.0)
    timeline_fps = float(mapping.get("timeline_fps") or 0.0)
    if source_fps <= 0.0 or timeline_fps <= 0.0:
        raise ValueError("lifecycle_mapping_fps")
    for record in records:
        original = record.get("original_timeline_interval")
        accepted = record.get("accepted_timeline_interval")
        last_visible = record.get("last_visible_source_frame")
        first_nonvisible = record.get("first_nonvisible_source_frame")
        source_end = record.get("source_end_exclusive")
        if not record.get("object_id") or record.get("reproduction_authority") is not True:
            raise ValueError("lifecycle_record_identity_or_authority")
        if not isinstance(original, list) or not isinstance(accepted, list) or len(original) != 2 or len(accepted) != 2:
            raise ValueError("lifecycle_record_intervals")
        if not all(isinstance(value, int) for value in (*original, *accepted, last_visible, first_nonvisible, source_end)):
            raise ValueError("lifecycle_record_integer_boundaries")
        if original[0] != accepted[0] or accepted[1] <= original[1]:
            raise ValueError("lifecycle_record_end_only_extension")
        if last_visible + 1 != first_nonvisible or first_nonvisible != source_end:
            raise ValueError("lifecycle_record_half_open_source_boundary")
        mapped_end = round(source_end / source_fps * timeline_fps)
        if record.get("accepted_timeline_end_exclusive") != mapped_end or accepted[1] != mapped_end:
            raise ValueError("lifecycle_record_canonical_mapping")
        evidence = record.get("evidence_refs") or []
        by_frame = {row.get("source_frame"): row for row in evidence if "source_frame" in row}
        last = by_frame.get(last_visible) or {}
        first = by_frame.get(first_nonvisible) or {}
        if last.get("classification") not in {"VISIBLE", "TRANSITIONAL"}:
            raise ValueError("lifecycle_last_visible_evidence")
        if last.get("classification") == "TRANSITIONAL" and last.get("object_visibility") != "PARTIALLY_VISIBLE":
            raise ValueError("lifecycle_transitional_visibility_evidence")
        if first.get("classification") != "NOT_VISIBLE":
            raise ValueError("lifecycle_first_nonvisible_evidence")
        for item in evidence:
            if _sha256(root / item["path"]) != item["sha256"]:
                raise ValueError(f"lifecycle_evidence_hash:{item['path']}")
    source = authority.get("source_video") or {}
    if _sha256(root / source["path"]) != source["sha256"]:
        raise ValueError("lifecycle_source_video_hash")


def _branch_counts(authority: dict[str, Any], base: dict[str, Any]) -> dict[str, int]:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    target_ids = {row["object_id"].lower() for row in authority["records"]}
    by_id = _rows_by_id(base["objects"])
    target_literals = {str(by_id[target]["text"]["value"]).lower() for target in target_ids}
    reel_tokens = {Path(authority["source_video"]["path"]).stem.lower()}
    counts = {"literal": 0, "identity": 0, "reel": 0}
    for node in ast.walk(tree):
        expression = node.test if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)) else None
        if expression is None:
            continue
        values = [child.value.lower() for child in ast.walk(expression) if isinstance(child, ast.Constant) and isinstance(child.value, str)]
        counts["literal"] += sum(any(token in value for token in target_literals) for value in values)
        counts["identity"] += sum(any(token in value for token in target_ids) for value in values)
        counts["reel"] += sum(any(token in value for token in reel_tokens) for value in values)
    return counts


def _without_intervals(row: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(row)
    result.pop("source_interval", None)
    result.pop("resolve_interval", None)
    return result


def compile_f6_contract(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base = _load_pinned(root, F5_CONTRACT, F5_SHA256)
    authority = _load_pinned(root, LIFECYCLE_AUTHORITY, LIFECYCLE_AUTHORITY_SHA256)
    _validate_authority(root, authority)
    contract = copy.deepcopy(base)
    targets = {record["object_id"]: record for record in authority["records"]}
    for collection_name in ("objects", "identity_records"):
        rows = _rows_by_id(contract[collection_name])
        for object_id, record in targets.items():
            row = rows.get(object_id)
            if row is None or row["source_interval"] != record["original_timeline_interval"] or row["resolve_interval"] != record["original_timeline_interval"]:
                raise ValueError(f"lifecycle_original_interval_mismatch:{object_id}:{collection_name}")
            row["source_interval"] = copy.deepcopy(record["accepted_timeline_interval"])
            row["resolve_interval"] = copy.deepcopy(record["accepted_timeline_interval"])

    branches = _branch_counts(authority, base)
    contract.update(
        {
            "schema": "video_cloner_step5_f6_lifecycle_end_correction_compile_contract",
            "schema_version": 1,
            "base_f5_contract": {"path": F5_CONTRACT.as_posix(), "sha256": F5_SHA256},
            "lifecycle_end_correction_authority": {"path": LIFECYCLE_AUTHORITY.as_posix(), "sha256": LIFECYCLE_AUTHORITY_SHA256},
            "lifecycle_end_correction_count": len(targets),
            "production_branch_counts": branches,
            "resolve_mutated": False,
        }
    )
    base_objects, objects = _rows_by_id(base["objects"]), _rows_by_id(contract["objects"])
    base_identities, identities = _rows_by_id(base["identity_records"]), _rows_by_id(contract["identity_records"])
    changed = {
        object_id
        for before, after in ((base_objects, objects), (base_identities, identities))
        for object_id in before
        if (before[object_id]["source_interval"], before[object_id]["resolve_interval"])
        != (after[object_id]["source_interval"], after[object_id]["resolve_interval"])
    }
    checks = {
        "only_authorized_lifecycle_records_changed": changed == set(targets),
        "lifecycle_start_unchanged": all(objects[key]["source_interval"][0] == targets[key]["original_timeline_interval"][0] for key in targets),
        "source_end_is_half_open": all(row["source_end_exclusive"] == row["first_nonvisible_source_frame"] == row["last_visible_source_frame"] + 1 for row in targets.values()),
        "canonical_source_timeline_mapping_used": all(row["accepted_timeline_end_exclusive"] == round(row["source_end_exclusive"] / authority["canonical_mapping"]["source_fps"] * authority["canonical_mapping"]["timeline_fps"]) for row in targets.values()),
        "lifecycle_end_extended": all(row["accepted_timeline_interval"][1] > row["original_timeline_interval"][1] for row in targets.values()),
        "all_non_lifecycle_fields_unchanged": all(_without_intervals(before[key]) == _without_intervals(after[key]) for before, after in ((base_objects, objects), (base_identities, identities)) for key in before),
        "scale_domain_unchanged": all(before[key].get("keyframes", {}).get("scale") == after[key].get("keyframes", {}).get("scale") and before[key].get("scale_decision") == after[key].get("scale_decision") for before, after in ((base_objects, objects), (base_identities, identities)) for key in before),
        "text_domain_unchanged": all(base_objects[key].get("text") == objects[key].get("text") for key in base_objects),
        "style_domain_unchanged": all(_without_intervals(base_objects[key]) == _without_intervals(objects[key]) for key in base_objects),
        "position_domain_unchanged": all(base_objects[key].get("position") == objects[key].get("position") for key in base_objects),
        "ownership_domain_unchanged": all((base_objects[key].get("composition"), base_objects[key].get("object_origin")) == (objects[key].get("composition"), objects[key].get("object_origin")) for key in base_objects),
        "other_lifecycle_intervals_unchanged": all((base_objects[key]["source_interval"], base_objects[key]["resolve_interval"]) == (objects[key]["source_interval"], objects[key]["resolve_interval"]) for key in set(base_objects) - set(targets)),
        "final_renderable_objects_65": len(contract["objects"]) == contract["final_renderable_object_count"] == 65,
        "human_approvals_unchanged": (contract["human_decision_count"], contract["human_approved_count"], contract["pending_human_decisions"]) == (9, 9, 0),
        "zero_production_literal_branches": branches["literal"] == 0,
        "zero_production_identity_branches": branches["identity"] == 0,
        "zero_production_reel_branches": branches["reel"] == 0,
        "resolve_not_mutated": contract["resolve_mutated"] is False and authority["resolve_mutated"] is False,
    }
    validation = {
        "schema": "video_cloner_step5_f6_lifecycle_end_correction_validation",
        "schema_version": 1,
        "result": "PASS_F6_6000_LIFECYCLE_CORRECTION" if all(checks.values()) else "FAIL_F6_6000_LIFECYCLE_CORRECTION",
        "all_pass": all(checks.values()),
        "checks": checks,
        "counts": {
            "base_frozen_identities": len(contract["identity_records"]),
            "base_renderable_identities": contract["base_renderable_identity_count"],
            "corrected_lifecycle_identities": len(changed),
            "final_renderable_objects": len(contract["objects"]),
            "human_approved": contract["human_approved_count"],
        },
        "production_branch_counts": branches,
        "resolve_mutated": False,
    }
    if not validation["all_pass"]:
        raise ValueError("f6_validation_failed")
    return authority, contract, validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    authority, contract, validation = compile_f6_contract()
    artifacts = {
        "step5_f6_lifecycle_end_correction_authority.json": authority,
        "step5_f6_compile_contract.json": contract,
        "step5_f6_validation.json": validation,
    }
    for name, value in artifacts.items():
        (output / name).write_bytes(_bytes(value))
    print(json.dumps({"ok": True, "result": validation["result"], "counts": validation["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
