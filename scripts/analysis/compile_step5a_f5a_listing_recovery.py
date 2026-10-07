from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from scripts.analysis.compile_step5a_f4_display_object_recovery import (
    _load_pinned,
    _sha256,
    _validate_record,
    compile_recovery_object,
)


ROOT = Path(os.environ.get("VIDEO_CLONER_ROOT", Path(__file__).resolve().parents[2])).resolve()
F4_CONTRACT = Path(
    ".agent/reports/VIDEO_CLONER_STEP5A_F4_MISSING_DUPLICATE_CAPTION_RECOVERY_20260930_V1/"
    "20260930T142346380Z_luna_execute/first/step5a_f4_compile_contract.json"
)
F4_SHA256 = "cd4c4f56e160777d8260712b2cadf8e7f3a98a7b96d1a62435ad8b07c3531179"
AUTHORITY = Path("config/DcJRJtUKScu.accepted_listing_display_object_recovery.json")
AUTHORITY_SHA256 = "77e29431f71c7479fea412c0b12d1ee2099fb12e1fafe99af03ac2b0cf2f6a90"


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_listing_authority(root: Path = ROOT) -> dict[str, Any]:
    authority = _load_pinned(root / AUTHORITY, AUTHORITY_SHA256)
    if authority.get("schema") != "video_cloner_accepted_display_object_recovery":
        raise ValueError("accepted_recovery_authority_schema")
    if authority.get("authority") != "ACCEPTED_DISPLAY_OBJECT_RECOVERY":
        raise ValueError("accepted_recovery_authority_status")
    for artifact in authority.get("evidence_artifacts", []):
        if _sha256(root / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"evidence_hash_mismatch:{artifact['path']}")
    return authority


def _branch_counts(record: dict[str, Any]) -> dict[str, int]:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    literal_tokens = {
        record["accepted_display_text"].lower(),
        record["composition_relationship"]["neighbor_source_text"].lower(),
    }
    identity_tokens = {
        record["composition_relationship"]["neighbor_identity"].lower(),
        record["recovery_object_id"].lower(),
    }
    reel_tokens = {Path(record["source_provenance"]["geometry_evidence_path"]).stem.lower(), Path(record["source_provenance"]["entry_contact_sheet"]).stem.lower()}
    counts = {"literal": 0, "identity": 0, "reel": 0}
    for node in ast.walk(tree):
        expression = node.test if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)) else None
        if expression is None:
            continue
        values = [child.value.lower() for child in ast.walk(expression) if isinstance(child, ast.Constant) and isinstance(child.value, str)]
        counts["literal"] += sum(any(token in value for token in literal_tokens) for value in values)
        counts["identity"] += sum(any(token in value for token in identity_tokens) for value in values)
        counts["reel"] += sum(any(token in value for token in reel_tokens) for value in values)
    return counts


def compile_f5a_contract(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    f4 = _load_pinned(root / F4_CONTRACT, F4_SHA256)
    authority = load_listing_authority(root)
    records = authority.get("recovery_objects") or []
    if len(records) != 1:
        raise ValueError(f"listing_recovery_object_count:{len(records)}")
    record = records[0]
    _validate_record(record, authority)

    authority_path = AUTHORITY.as_posix()
    added = compile_recovery_object(record, Path(authority_path), AUTHORITY_SHA256)
    contract = copy.deepcopy(f4)
    contract["objects"] = copy.deepcopy(f4["objects"]) + [added]
    contract.update(
        {
            "schema": "video_cloner_step5a_f5a_listing_recovery_compile_contract",
            "schema_version": 1,
            "base_f4_contract": {"path": F4_CONTRACT.as_posix(), "sha256": F4_SHA256},
            "f5a_recovery_authority": {"path": authority_path, "sha256": AUTHORITY_SHA256},
            "preexisting_recovered_display_object_count": 2,
            "f5a_added_recovered_display_object_count": 1,
            "recovered_display_object_count": 3,
            "final_renderable_object_count": len(contract["objects"]),
            "object_count": len(contract["objects"]),
            "resolve_mutated": False,
        }
    )

    rows = {row["source_identity"]: row for row in f4["identity_records"]}
    old_recoveries = [row for row in f4["objects"] if row.get("object_origin") == "RECOVERED_DISPLAY_OBJECT"]
    branches = _branch_counts(record)
    checks = {
        "01_listing_source_lifecycle_parses": [record["source_visible_start_frame"], record["source_visible_end_frame"] + 1] == [413, 433],
        "02_canonical_source_timeline_mapping": [record["timeline_start_frame"], record["timeline_end_frame"]] == [330, 347],
        "03_exactly_one_listing_recovery_created": len(records) == 1 and contract["objects"][-1]["text"]["value"] == record["accepted_display_text"],
        "04_0061_remains_reels": rows[record["composition_relationship"]["neighbor_identity"]]["renderable"] is True and rows[record["composition_relationship"]["neighbor_identity"]]["text"]["value"] == record["composition_relationship"]["neighbor_source_text"],
        "05_0062_remains_suppressed": rows["caption_tracklet_0062"]["renderable"] is False,
        "06_0063_remains_suppressed": rows["caption_tracklet_0063"]["renderable"] is False,
        "07_existing_f4_recoveries_unchanged": contract["objects"][62:64] == old_recoveries,
        "08_base_113_identities_unchanged": len(contract["identity_records"]) == 113 and contract["identity_records"] == f4["identity_records"],
        "09_base_62_renderables_unchanged": contract["objects"][:62] == f4["objects"][:62],
        "10_total_recovered_objects_is_3": sum(row.get("object_origin") == "RECOVERED_DISPLAY_OBJECT" for row in contract["objects"]) == 3,
        "11_final_renderable_objects_is_65": len(contract["objects"]) == 65,
        "12_existing_timing_unchanged": [row["source_interval"] for row in contract["objects"][:-1]] == [row["source_interval"] for row in f4["objects"]],
        "13_existing_text_unchanged": [row["text"] for row in contract["objects"][:-1]] == [row["text"] for row in f4["objects"]],
        "14_existing_scale_unchanged": [row["scale_decision"] for row in contract["objects"][:-1]] == [row["scale_decision"] for row in f4["objects"]],
        "15_no_style_overlay_applied": added["font"]["source_authority"] == "STYLE_UNRESOLVED_PENDING_F5" and contract["objects"][:-1] == f4["objects"],
        "16_no_production_literal_branch": branches["literal"] == 0,
        "17_no_production_identity_branch": branches["identity"] == 0,
        "18_no_production_reel_branch": branches["reel"] == 0,
        "source_geometry_is_frame_426_evidence": added["position"]["source_bbox"] == [414, 721, 678, 803] and added["size"]["source_height_px"] == 82.0,
        "relationship_is_sequential_without_overlap": added["composition"]["relationship"] == "SEQUENTIAL_NO_OVERLAP" and record["source_provenance"]["following_object_first_source_frame"] == 433,
        "upstream_not_mutated": authority["upstream_artifacts_changed"] is False,
        "resolve_not_mutated": authority["resolve_mutated"] is False and contract["resolve_mutated"] is False,
    }
    validation = {
        "schema": "video_cloner_step5a_f5a_listing_recovery_validation",
        "schema_version": 1,
        "result": "PASS_F5A_LISTING_OBJECT_LIFECYCLE_RECOVERY" if all(checks.values()) else "FAIL_F5A_LISTING_OBJECT_LIFECYCLE_RECOVERY",
        "all_pass": all(checks.values()),
        "checks": checks,
        "production_branch_counts": branches,
        "counts": {
            "base_frozen_identities": len(f4["identity_records"]),
            "base_renderable_identities": 62,
            "preexisting_recovered_display_objects": len(old_recoveries),
            "total_recovered_display_objects": 3,
            "final_renderable_objects": len(contract["objects"]),
        },
    }
    if not validation["all_pass"]:
        raise ValueError("f5a_validation_failed")
    return authority, contract, validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    first = compile_f5a_contract()
    second = compile_f5a_contract()
    names = (
        "step5a_f5a_listing_recovery_authority.json",
        "step5a_f5a_compile_contract.json",
        "step5a_f5a_validation.json",
    )
    artifacts = {}
    for name, left, right in zip(names, first, second):
        left_bytes, right_bytes = _bytes(left), _bytes(right)
        artifacts[name] = {
            "byte_identical": left_bytes == right_bytes,
            "first_sha256": hashlib.sha256(left_bytes).hexdigest(),
            "second_sha256": hashlib.sha256(right_bytes).hexdigest(),
        }
        (output / name).write_bytes(left_bytes)
    proof = {
        "schema": "video_cloner_step5a_f5a_determinism_proof",
        "schema_version": 1,
        "deterministic": all(row["byte_identical"] for row in artifacts.values()),
        "artifacts": artifacts,
    }
    (output / "step5a_f5a_determinism_proof.json").write_bytes(_bytes(proof))
    print(json.dumps({"ok": True, "result": first[2]["result"], "counts": first[2]["counts"], "deterministic": proof["deterministic"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
