from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
F2_CONTRACT_PATH = ".agent/reports/VIDEO_CLONER_STEP5A_F2_GENERIC_TEXT_AUTHORITY_REPAIR_20260930_V1/20260930T110048416Z_luna_execute/step5a_f2_compile_contract.json"
EXPECTED_F2_SHA256 = "c0978298eacc3aa079e5b19a6a0ef893aac74c24f82ed0a795f37c77fe9b16d3"
EXPECTED_SCALE_AUTHORITIES = {
    ".agent/reports/VIDEO_CLONER_STEP5A_F3A2_6000_SCALE_LIFECYCLE_BOUNDARY_20260930/20260930T123557715Z_adjudicated/step5a_f3a2_6000_scale_lifecycle_boundary_adjudication.json": "e8d20e25a41f6bb6929149ae5c8cac5945933ccb3cbd51d8b284b080334bb25e",
}
SAFE_INTERPOLATIONS = {"LINEAR", "HOLD"}


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def absolute_size(base_size: float, relative_scale: float) -> float:
    base, ratio = float(base_size), float(relative_scale)
    if not math.isfinite(base) or base <= 0:
        raise ValueError("invalid_static_base_size")
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("invalid_relative_scale")
    return round(base * ratio, 9)


def load_scale_authorities(root: Path, expected: dict[str, str] | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    expected = expected or EXPECTED_SCALE_AUTHORITIES
    authorities: dict[str, dict[str, Any]] = {}
    inputs: dict[str, dict[str, str]] = {}
    for relative_path, expected_hash in expected.items():
        path = root / relative_path
        actual_hash = sha(path)
        if actual_hash != expected_hash:
            raise ValueError(f"scale_authority_hash_drift:{relative_path}")
        artifact = read(path)
        if artifact.get("schema") != "video_cloner_step5a_f3a2_scale_lifecycle_boundary_adjudication":
            raise ValueError(f"scale_authority_schema:{relative_path}")
        if artifact.get("authority") != "ACCEPTED_SCALE_REPRODUCTION_ADJUDICATION" or artifact.get("reproduction_authority") is not True:
            raise ValueError(f"scale_authority_not_accepted:{relative_path}")
        if artifact.get("reexpansion_authorized") is not False:
            raise ValueError(f"unsafe_reexpansion_authority:{relative_path}")
        policy = artifact.get("interpolation_policy") or {}
        if any(policy.get(flag) is not False for flag in ("overshoot_allowed", "undershoot_allowed", "new_extrema_allowed", "synthetic_rebound_allowed")):
            raise ValueError(f"unsafe_interpolation_policy:{relative_path}")
        phases = {row["phase"]: row for row in artifact.get("phase_authority") or []}
        if not phases or any(row.get("interpolation") not in SAFE_INTERPOLATIONS for row in phases.values()):
            raise ValueError(f"unsupported_phase_interpolation:{relative_path}")
        anchors = artifact.get("relative_scale_anchors") or []
        identity = str(artifact.get("identity") or "")
        if not identity or not anchors or identity in authorities:
            raise ValueError(f"invalid_scale_authority_identity:{relative_path}")
        authorities[identity] = {**copy.deepcopy(artifact), "_path": relative_path, "_sha256": actual_hash, "_phases": phases}
        inputs[identity] = {"path": relative_path, "sha256": actual_hash}
    return authorities, inputs


def _suppression_reason(row: dict[str, Any], diagnostic: list[dict[str, Any]]) -> str:
    if not row.get("renderable"):
        return "NON_RENDERABLE_IDENTITY"
    sources = {str(key.get("source") or "") for key in diagnostic}
    if "STEP_4C_EDITOR_NEUTRAL_KEYFRAME" in sources:
        return "NO_ACCEPTED_REPRODUCTION_AUTHORITY_ORPHAN_STEP4C"
    if diagnostic:
        return "NO_ACCEPTED_REPRODUCTION_AUTHORITY_RAW_MEASUREMENTS_ONLY"
    return "NO_ACCEPTED_REPRODUCTION_AUTHORITY"


def compile_scale_decision(row: dict[str, Any], scale_authority: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    identity = row["source_identity"]
    renderable = row.get("renderable") is True
    base_size = float(row["size"]["resolve_value"])
    diagnostic = copy.deepcopy((row.get("keyframes") or {}).get("scale") or [])
    common = {
        "identity": identity,
        "renderable": renderable,
        "static_base_size": base_size,
        "static_base_size_authority": row["size"].get("source_authority"),
        "diagnostic_input_scale_measurements": diagnostic,
    }
    if not renderable or scale_authority is None:
        reason = _suppression_reason(row, diagnostic)
        return [], {
            **common,
            "scale_authority_status": "SUPPRESSED",
            "scale_authority_source": None,
            "relative_scale_anchors": [],
            "compiled_absolute_size_anchors": [],
            "interpolation_policy": "STATIC_BASE_SIZE",
            "scale_suppression_reason": reason,
            "provenance": {"f2_diagnostic_measurements_preserved": bool(diagnostic)},
        }

    if scale_authority.get("identity") != identity:
        raise ValueError(f"scale_authority_identity_mismatch:{identity}")
    start, end = map(int, row["source_interval"])
    raw_anchors = copy.deepcopy(scale_authority["relative_scale_anchors"])
    frames = [int(anchor["timeline_frame"]) for anchor in raw_anchors]
    if frames != sorted(set(frames)):
        raise ValueError(f"scale_anchor_order:{identity}")
    if any(not start <= frame < end for frame in frames):
        raise ValueError(f"scale_anchor_bounds:{identity}")
    phase_rows = scale_authority["_phases"]
    if any(str(anchor.get("phase") or "") not in phase_rows for anchor in raw_anchors):
        raise ValueError(f"scale_anchor_phase:{identity}")

    compiled: list[dict[str, Any]] = []
    for index, anchor in enumerate(raw_anchors):
        phase = str(anchor["phase"])
        ratio = float(anchor["relative_scale"])
        if index + 1 == len(raw_anchors):
            interpolation = "NONE"
        else:
            next_phase = str(raw_anchors[index + 1]["phase"])
            interpolation = "HOLD" if phase == next_phase == "PLATEAU" else "LINEAR"
        compiled.append({
            "timeline_frame": int(anchor["timeline_frame"]),
            "local_frame": int(anchor["timeline_frame"]) - start,
            "value": absolute_size(base_size, ratio),
            "relative_scale": ratio,
            "authority": scale_authority["authority"],
            "source": "STEP5A_F3A2_ACCEPTED_SCALE_AUTHORITY",
            "phase": phase,
            "interpolation_to_next": interpolation,
            "value_role": "SOURCE_SUPPORTED_VALUE",
        })

    contraction_start = int(scale_authority["phase_boundaries"]["contraction_start"]["timeline_frame"])
    contraction_values = [key["relative_scale"] for key in compiled if key["timeline_frame"] >= contraction_start]
    if any(right > left for left, right in zip(contraction_values, contraction_values[1:])):
        raise ValueError(f"reexpansion_after_contraction:{identity}")
    if any(key["interpolation_to_next"] not in SAFE_INTERPOLATIONS | {"NONE"} for key in compiled):
        raise ValueError(f"unsafe_compiled_interpolation:{identity}")

    source = {"path": scale_authority["_path"], "sha256": scale_authority["_sha256"], "schema": scale_authority["schema"]}
    return compiled, {
        **common,
        "scale_authority_status": "AUTHORIZED",
        "scale_authority_source": source,
        "relative_scale_anchors": raw_anchors,
        "compiled_absolute_size_anchors": copy.deepcopy(compiled),
        "interpolation_policy": copy.deepcopy(scale_authority["interpolation_policy"]),
        "scale_suppression_reason": None,
        "provenance": {"accepted_scale_authority": source, "f2_diagnostic_measurements_replaced": len(diagnostic)},
    }


def _without_f3_scale(row: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(row)
    value.pop("scale_decision", None)
    value["keyframes"]["scale"] = []
    return value


def _count_keys(rows: Iterable[dict[str, Any]]) -> int:
    return sum(len((row.get("keyframes") or {}).get("scale") or []) for row in rows)


def compile_f3_contract(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    f2_path = root / F2_CONTRACT_PATH
    f2_hash = sha(f2_path)
    if f2_hash != EXPECTED_F2_SHA256:
        raise ValueError("f2_contract_hash_drift")
    f2 = read(f2_path)
    if f2.get("schema") != "video_cloner_step5a_f2_text_authority_compile_contract":
        raise ValueError("f2_contract_schema")
    if f2.get("identity_count") != 113 or f2.get("object_count") != 62:
        raise ValueError("f2_identity_accounting")
    authorities, authority_inputs = load_scale_authorities(root)

    records: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for source in f2["identity_records"]:
        row = copy.deepcopy(source)
        compiled, decision = compile_scale_decision(row, authorities.get(row["source_identity"]))
        row["keyframes"]["scale"] = compiled
        row["scale_decision"] = decision
        records.append(row)
        decisions.append(decision)
    objects = [row for row in records if row["renderable"]]

    f2_scale_rows = [key for row in f2["identity_records"] for key in row["keyframes"]["scale"]]
    f2_renderable_scale_rows = [key for row in f2["identity_records"] if row["renderable"] for key in row["keyframes"]["scale"]]
    compiled_rows = [key for row in records for key in row["keyframes"]["scale"]]
    authorized = [decision["identity"] for decision in decisions if decision["scale_authority_status"] == "AUTHORIZED"]
    unit_errors = sum(
        abs(float(key["value"]) - absolute_size(row["size"]["resolve_value"], key["relative_scale"])) > 1e-9
        for row in records for key in row["keyframes"]["scale"]
    )
    raw_ratio_as_absolute = sum(abs(float(key["value"]) - float(key["relative_scale"])) <= 1e-9 for key in compiled_rows)
    max_static_row = max(objects, key=lambda row: float(row["size"]["resolve_value"]))
    animated = [(row, key) for row in objects for key in row["keyframes"]["scale"]]
    max_animated_row, max_animated_key = max(animated, key=lambda pair: float(pair[1]["value"]))
    counts = {
        "total_identities": len(records),
        "renderable_identities": len(objects),
        "current_f2_scale_key_count": len(f2_scale_rows),
        "current_f2_renderable_scale_key_count": len(f2_renderable_scale_rows),
        "authorized_scale_identities": len(authorized),
        "authorized_scale_identity_list": authorized,
        "authorized_relative_scale_key_count": sum(len(decision["relative_scale_anchors"]) for decision in decisions if decision["scale_authority_status"] == "AUTHORIZED"),
        "final_editor_scale_key_count": len(compiled_rows),
        "suppressed_raw_measurement_scale_keys": sum(key.get("source") == "STEP_4B_RAW_SAMPLE" for key in f2_scale_rows),
        "suppressed_orphan_scale_keys": sum(key.get("source") == "STEP_4C_EDITOR_NEUTRAL_KEYFRAME" for key in f2_scale_rows),
        "suppressed_renderable_orphan_scale_keys": sum(key.get("source") == "STEP_4C_EDITOR_NEUTRAL_KEYFRAME" for key in f2_renderable_scale_rows),
        "unauthorized_scale_commands": sum(key.get("source") != "STEP5A_F3A2_ACCEPTED_SCALE_AUTHORITY" for key in compiled_rows),
        "non_renderable_scale_commands": _count_keys(row for row in records if not row["renderable"]),
        "relative_as_absolute_unit_errors": unit_errors,
        "raw_ratio_as_absolute_count": raw_ratio_as_absolute,
    }
    safety = {
        "max_static_base_size": float(max_static_row["size"]["resolve_value"]),
        "identity_with_max_static_base_size": max_static_row["source_identity"],
        "max_compiled_animated_size": float(max_animated_key["value"]),
        "identity_with_max_animated_size": max_animated_row["source_identity"],
        "interpolation_overshoot_risk": 0,
        "reexpansion_after_contraction": False,
    }

    contract = copy.deepcopy(f2)
    inputs = copy.deepcopy(f2["inputs"])
    inputs["accepted_scale_reproduction_authorities"] = authority_inputs
    contract.update({
        "schema": "video_cloner_step5a_f3_scale_compile_contract",
        "schema_version": 1,
        "base_f2_contract": {"path": F2_CONTRACT_PATH, "sha256": f2_hash},
        "inputs": inputs,
        "identity_records": records,
        "objects": objects,
        "scale_compilation": {"counts": counts, "oversize_safety": safety},
        "resolve_mutated": False,
    })
    base_by_id = {row["source_identity"]: row for row in f2["identity_records"]}
    checks = {
        "identity_accounting_113": len(records) == 113,
        "renderable_identity_accounting_62": len(objects) == 62,
        "f2_scale_accounting_44_total_43_renderable": len(f2_scale_rows) == 44 and len(f2_renderable_scale_rows) == 43,
        "only_pinned_authorities_consumed": set(authorized) == set(authorities),
        "one_authorized_scale_identity": len(authorized) == 1,
        "nine_authorized_relative_anchors": counts["authorized_relative_scale_key_count"] == 9,
        "nine_final_editor_scale_keys": counts["final_editor_scale_key_count"] == 9,
        "no_unauthorized_scale_commands": counts["unauthorized_scale_commands"] == 0,
        "no_non_renderable_scale_commands": counts["non_renderable_scale_commands"] == 0,
        "no_relative_as_absolute_unit_errors": unit_errors == 0 and raw_ratio_as_absolute == 0,
        "no_interpolation_overshoot_risk": safety["interpolation_overshoot_risk"] == 0,
        "no_reexpansion_after_contraction": safety["reexpansion_after_contraction"] is False,
        "non_scale_domains_unchanged": all(_without_f3_scale(base_by_id[row["source_identity"]]) == _without_f3_scale(row) for row in records),
        "text_unchanged": all(base_by_id[row["source_identity"]]["text"] == row["text"] for row in records),
        "timing_unchanged": all(base_by_id[row["source_identity"]]["resolve_interval"] == row["resolve_interval"] for row in records),
        "position_unchanged": all(base_by_id[row["source_identity"]]["keyframes"]["position"] == row["keyframes"]["position"] for row in records),
        "freeze_hashes_match": all(item["match"] for item in contract["freeze_integrity"]),
        "resolve_not_mutated": contract["resolve_mutated"] is False,
    }
    validation = {
        "schema": "video_cloner_step5a_f3_scale_validation",
        "schema_version": 1,
        "checks": checks,
        "all_pass": all(checks.values()),
        "counts": counts,
        "oversize_safety": safety,
        "contract_sha256": digest(contract),
    }
    decision_artifact = {
        "schema": "video_cloner_step5a_f3_scale_decisions",
        "schema_version": 1,
        "inputs": {"f2": contract["base_f2_contract"], "scale_authorities": authority_inputs},
        "counts": counts,
        "decisions": decisions,
    }
    return contract, validation, decision_artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    first = compile_f3_contract()
    second = compile_f3_contract()
    names = ("step5a_f3_compile_contract.json", "step5a_f3_validation.json", "step5a_f3_scale_decisions.json")
    first_payloads = {name: json_bytes(value) for name, value in zip(names, first)}
    second_payloads = {name: json_bytes(value) for name, value in zip(names, second)}
    proof = {
        "schema": "video_cloner_step5a_f3_determinism_proof",
        "schema_version": 1,
        "artifacts": {name: {"first_sha256": hashlib.sha256(first_payloads[name]).hexdigest(), "second_sha256": hashlib.sha256(second_payloads[name]).hexdigest(), "byte_identical": first_payloads[name] == second_payloads[name]} for name in names},
    }
    proof["deterministic"] = all(row["byte_identical"] for row in proof["artifacts"].values())
    if not first[1]["all_pass"] or not proof["deterministic"]:
        raise SystemExit(2)
    for name, payload in first_payloads.items():
        (out / name).write_bytes(payload)
    (out / "step5a_f3_determinism_proof.json").write_bytes(json_bytes(proof))
    print(json.dumps({"ok": True, "output_dir": str(out), "counts": first[1]["counts"], "deterministic": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
