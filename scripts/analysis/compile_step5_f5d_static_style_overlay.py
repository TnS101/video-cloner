from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable


ROOT = Path(os.environ.get("VIDEO_CLONER_ROOT", Path(__file__).resolve().parents[2])).resolve()
F5A_CONTRACT = Path(
    ".agent/reports/VIDEO_CLONER_STEP5A_F5A_LISTING_OBJECT_LIFECYCLE_RECOVERY_20260930_V1/"
    "20260930T171039690Z_luna_resume/first/step5a_f5a_compile_contract.json"
)
F5A_SHA256 = "52544783c9fa89d9bb36bdd56d2181f87b61796afe7ef34b80a101259fae6161"
AUTO_AUTHORITY = Path("config/DcJRJtUKScu.accepted_static_style_position_adjudication.json")
AUTO_AUTHORITY_SHA256 = "50ace714efe41ef0a434c17618022b96603c1965fcc16976b742d03c4ae09af4"
HUMAN_AUTHORITY = Path("config/DcJRJtUKScu.accepted_human_static_style_adjudication.json")
HUMAN_AUTHORITY_SHA256 = "151c3aac95eb71bcdd609321f85f88ab1d26c6546b89cc4d23d516fe29e113cf"
STYLE_AUTHORITY = "ACCEPTED_HUMAN_STATIC_STYLE_ADJUDICATION"


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pinned(root: Path, path: Path, expected: str) -> dict[str, Any]:
    actual = _sha256(root / path)
    if actual != expected:
        raise ValueError(f"pinned_hash_mismatch:{path.as_posix()}:{actual}")
    return json.loads((root / path).read_text(encoding="utf-8-sig"))


def _validate_human_authority(root: Path, authority: dict[str, Any]) -> None:
    records = authority.get("records") or []
    required = {"object_id", "property", "selected_value", "human_approved", "approval_phase", "source_evidence_refs"}
    if authority.get("schema") != "video_cloner_accepted_human_static_style_adjudication":
        raise ValueError("human_authority_schema")
    if authority.get("authority") != STYLE_AUTHORITY or authority.get("f5_compile_authorized") is not True:
        raise ValueError("human_authority_not_final")
    if (authority.get("human_decision_count"), authority.get("human_approved_count"), authority.get("pending_human_decisions")) != (9, 9, 0):
        raise ValueError("human_decision_accounting")
    if len(records) != 9 or len({(row.get("object_id"), row.get("property")) for row in records}) != 9:
        raise ValueError("human_authority_records")
    for row in records:
        if not required.issubset(row) or row["human_approved"] is not True or not row["source_evidence_refs"]:
            raise ValueError("human_record_incomplete")
        for evidence in row["source_evidence_refs"]:
            if not (root / evidence).is_file():
                raise ValueError(f"human_evidence_missing:{evidence}")


def _targets(contract: dict[str, Any], object_id: str) -> list[dict[str, Any]]:
    rows = [row for collection in (contract["objects"], contract["identity_records"]) for row in collection if row["source_identity"] == object_id]
    if not rows:
        raise ValueError(f"style_target_missing:{object_id}")
    return rows


def _apply_font(row: dict[str, Any], value: dict[str, Any]) -> None:
    compiled = {
        "resolve_family": value["family"],
        "resolve_style": value["style"],
        "source_authority": STYLE_AUTHORITY,
        "value_role": "HUMAN_APPROVED_VALUE",
    }
    if value.get("italic"):
        compiled["italic"] = True
        compiled["italic_treatment"] = copy.deepcopy(value["italic_treatment"])
    row["font"] = compiled


def _apply_fill(row: dict[str, Any], value: dict[str, Any]) -> None:
    fill_type = value["type"]
    if fill_type == "solid":
        compiled = {"type": fill_type, "resolve_rgb": copy.deepcopy(value["rgb"])}
    elif fill_type == "linear_gradient":
        compiled = copy.deepcopy(value)
        row["advanced_effects"]["gradient"] = "HUMAN_APPROVED_LINEAR_GRADIENT"
    else:
        raise ValueError(f"unsupported_fill_type:{fill_type}")
    compiled.update({"source_authority": STYLE_AUTHORITY, "value_role": "HUMAN_APPROVED_VALUE"})
    row["fill"] = compiled


def _apply_opacity(row: dict[str, Any], value: dict[str, Any]) -> None:
    if value.get("mode") != "constant" or not 0.0 <= float(value.get("value", -1.0)) <= 1.0:
        raise ValueError("unsupported_opacity")
    row["opacity"] = {
        "mode": "constant",
        "resolve_value": float(value["value"]),
        "source_authority": STYLE_AUTHORITY,
        "value_role": "HUMAN_APPROVED_VALUE",
    }


PROPERTY_HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], None]] = {
    "font": _apply_font,
    "fill": _apply_fill,
    "opacity": _apply_opacity,
}
AUTO_PATHS = {
    "static_size": (("size", "resolve_value"), ("scale_decision", "static_base_size")),
    "resolve_center": (("position", "resolve_center"),),
}


def _set_path(row: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = copy.deepcopy(value)


def _apply_authorities(contract: dict[str, Any], automatic: dict[str, Any], human: dict[str, Any]) -> None:
    for record in automatic.get("records") or []:
        for row in _targets(contract, record["object_id"]):
            for property_name in record["authorized_properties"]:
                paths = AUTO_PATHS.get(property_name)
                if paths is None:
                    raise ValueError(f"unsupported_automatic_property:{property_name}")
                for path in paths:
                    _set_path(row, path, record[property_name])
    for record in human["records"]:
        handler = PROPERTY_HANDLERS.get(record["property"])
        if handler is None:
            raise ValueError(f"unsupported_human_property:{record['property']}")
        for row in _targets(contract, record["object_id"]):
            handler(row, record["selected_value"])


def _domain(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{field: copy.deepcopy(row.get(field)) for field in fields} for row in rows]


def _branch_counts(authority: dict[str, Any], f5a: dict[str, Any]) -> dict[str, int]:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    target_ids = {row["object_id"].lower() for row in authority["records"]}
    by_id = {row["source_identity"]: row for row in f5a["objects"]}
    target_literals = {str(by_id[target]["text"]["value"]).lower() for target in target_ids}
    reel_tokens = {Path(F5A_CONTRACT).stem.lower(), Path(HUMAN_AUTHORITY).stem.lower()}
    counts = {"literal": 0, "identity": 0, "reel": 0, "human_choice": 0}
    for node in ast.walk(tree):
        expression = node.test if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)) else None
        if expression is None:
            continue
        values = [child.value.lower() for child in ast.walk(expression) if isinstance(child, ast.Constant) and isinstance(child.value, str)]
        counts["literal"] += sum(any(token in value for token in target_literals) for value in values)
        counts["identity"] += sum(any(token in value for token in target_ids) for value in values)
        counts["reel"] += sum(any(token in value for token in reel_tokens) for value in values)
        counts["human_choice"] += sum("selected_winner" in value or "source_candidate_id" in value for value in values)
    return counts


def compile_f5_contract(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    f5a = _load_pinned(root, F5A_CONTRACT, F5A_SHA256)
    automatic = _load_pinned(root, AUTO_AUTHORITY, AUTO_AUTHORITY_SHA256)
    human = _load_pinned(root, HUMAN_AUTHORITY, HUMAN_AUTHORITY_SHA256)
    _validate_human_authority(root, human)

    contract = copy.deepcopy(f5a)
    _apply_authorities(contract, automatic, human)
    branches = _branch_counts(human, f5a)
    contract.update(
        {
            "schema": "video_cloner_step5_f5_human_approved_static_style_compile_contract",
            "schema_version": 1,
            "base_f5a_contract": {"path": F5A_CONTRACT.as_posix(), "sha256": F5A_SHA256},
            "automatic_static_style_authority": {"path": AUTO_AUTHORITY.as_posix(), "sha256": AUTO_AUTHORITY_SHA256},
            "human_static_style_authority": {"path": HUMAN_AUTHORITY.as_posix(), "sha256": HUMAN_AUTHORITY_SHA256},
            "human_decision_count": 9,
            "human_approved_count": 9,
            "pending_human_decisions": 0,
            "production_branch_counts": branches,
            "step_5b_status": "COMPLETE_HUMAN_APPROVED_STATIC_STYLE",
            "resolve_mutated": False,
        }
    )

    checks = {
        "human_authority_complete": len(human["records"]) == 9 and human["human_approved_count"] == 9 and human["pending_human_decisions"] == 0,
        "base_identity_accounting_113": len(contract["identity_records"]) == 113,
        "base_renderable_accounting_62": contract["base_renderable_identity_count"] == 62,
        "recovered_display_objects_3": contract["recovered_display_object_count"] == 3,
        "final_renderable_objects_65": len(contract["objects"]) == contract["final_renderable_object_count"] == 65,
        "text_domain_unchanged": _domain(contract["objects"], ("text",)) == _domain(f5a["objects"], ("text",)) and _domain(contract["identity_records"], ("text",)) == _domain(f5a["identity_records"], ("text",)),
        "timing_domain_unchanged": _domain(contract["objects"], ("source_interval", "resolve_interval")) == _domain(f5a["objects"], ("source_interval", "resolve_interval")) and _domain(contract["identity_records"], ("source_interval", "resolve_interval")) == _domain(f5a["identity_records"], ("source_interval", "resolve_interval")),
        "scale_domain_unchanged": _domain(contract["objects"], ("size", "scale_decision")) == _domain(f5a["objects"], ("size", "scale_decision")) and _domain(contract["identity_records"], ("size", "scale_decision")) == _domain(f5a["identity_records"], ("size", "scale_decision")),
        "lifecycle_domain_unchanged": _domain(contract["objects"], ("renderable", "source_interval", "resolve_interval")) == _domain(f5a["objects"], ("renderable", "source_interval", "resolve_interval")) and _domain(contract["identity_records"], ("renderable", "source_interval", "resolve_interval")) == _domain(f5a["identity_records"], ("renderable", "source_interval", "resolve_interval")),
        "ownership_domain_unchanged": _domain(contract["objects"], ("composition", "object_origin")) == _domain(f5a["objects"], ("composition", "object_origin")) and _domain(contract["identity_records"], ("composition", "object_origin")) == _domain(f5a["identity_records"], ("composition", "object_origin")),
        "position_domain_unchanged": _domain(contract["objects"], ("position",)) == _domain(f5a["objects"], ("position",)) and _domain(contract["identity_records"], ("position",)) == _domain(f5a["identity_records"], ("position",)),
        "motion_rotation_visibility_unchanged": _domain(contract["objects"], ("keyframes", "static_rotation")) == _domain(f5a["objects"], ("keyframes", "static_rotation")) and _domain(contract["identity_records"], ("keyframes", "static_rotation")) == _domain(f5a["identity_records"], ("keyframes", "static_rotation")),
        "all_human_records_applied": all(any(row["source_identity"] == record["object_id"] for row in contract["objects"]) for record in human["records"]),
        "zero_production_literal_branches": branches["literal"] == 0,
        "zero_production_identity_branches": branches["identity"] == 0,
        "zero_production_reel_branches": branches["reel"] == 0,
        "zero_production_human_choice_branches": branches["human_choice"] == 0,
        "resolve_not_mutated": contract["resolve_mutated"] is False and human["resolve_mutated"] is False and automatic["resolve_mutated"] is False,
    }
    validation = {
        "schema": "video_cloner_step5_f5d_human_approved_static_style_validation",
        "schema_version": 1,
        "result": "PASS_F5_HUMAN_APPROVED_STATIC_STYLE_IMPLEMENTATION" if all(checks.values()) else "FAIL_F5_HUMAN_APPROVED_STATIC_STYLE_IMPLEMENTATION",
        "all_pass": all(checks.values()),
        "checks": checks,
        "counts": {
            "base_frozen_identities": 113,
            "base_renderable_identities": 62,
            "recovered_display_objects": 3,
            "final_renderable_objects": 65,
            "human_decisions": 9,
            "human_approved": 9,
            "pending_human_decisions": 0,
        },
        "production_branch_counts": branches,
        "resolve_mutated": False,
    }
    if not validation["all_pass"]:
        raise ValueError("f5_validation_failed")
    return human, contract, validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    authority, contract, validation = compile_f5_contract()
    artifacts = {
        "step5_f5d_human_static_style_authority.json": authority,
        "step5_f5_compile_contract.json": contract,
        "step5_f5d_validation.json": validation,
    }
    for name, value in artifacts.items():
        (output / name).write_bytes(_bytes(value))
    print(json.dumps({"ok": True, "result": validation["result"], "counts": validation["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
