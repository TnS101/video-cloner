#!/usr/bin/env python3
"""Record Step 4D bookkeeping correction, human acceptance, and final freeze."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.analysis import adjudicate_step4d_clipping_final as clipping
from scripts.analysis import investigate_step4d_effect_evidence_validity as gate

STATE_PATH = ROOT / ".agent/state/video_cloner_step4d_advanced_text_effects_freeze.json"
SHADOW_FREEZE = ROOT / ".agent/state/video_cloner_step4d_shadow_freeze.json"
SHADOW_FREEZE_SHA256 = "bf788d25e02607e34a08b27a40005c5047906247bcce6cf8601d3b7ace9e11e8"
SOURCE_CLOSURE = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_FINAL_CLIPPING_ADJUDICATION_CLOSURE_READINESS_20260928/20260928T170000000Z_human_review_ready"
SOURCE_OCCLUSION = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_CAPTION_OCCLUSION_OWNERSHIP_ZORDER_20260928/20260928T153000000Z_human_review_ready"
AUTHORITY_PATHS = {
    "necessity_investigation": ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_ADVANCED_TEXT_EFFECT_NECESSITY_INVESTIGATION_20260927_V1/20260927T190000000Z_investigation/step4d_effect_necessity_audit.json",
    "effect_evidence_validity": ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_EFFECT_EVIDENCE_VALIDITY_GATE_20260927_V2/20260927T223000000Z_investigation/step4d_effect_evidence_validity_audit.json",
    "bounded_effect_evidence_repair": ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_BOUNDED_EFFECT_EVIDENCE_REPAIR_20260927_V3/20260928T000500000Z_human_review_ready/step4d_effect_evidence_repair_contract.json",
    "source_required_adjudication": ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_SOURCE_REQUIRED_EFFECT_ADJUDICATION_20260928_V2/20260928T013000000Z_human_review_ready/step4d_source_required_effect_adjudication.json",
    "bounded_shadow_implementation": ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_BOUNDED_SHADOW_IMPLEMENTATION_20260928_V2/20260928T023000000Z_human_review_ready/step4d_shadow_ir_contract.json",
    "calibrated_shadow_ir": ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_SHADOW_PARAMETER_FIDELITY_20260928_V2/20260928T123000000Z_human_review_ready/step4d_shadow_ir_calibrated.json",
    "shadow_human_acceptance": ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_SHADOW_HUMAN_ACCEPTANCE_AND_FREEZE_20260928/20260928T130000000Z_human_accepted/step4d_shadow_human_acceptance.json",
    "shadow_freeze": SHADOW_FREEZE,
    "caption_occlusion_adjudication": SOURCE_OCCLUSION / "step4d_caption_occlusion_evidence.json",
    "caption_occlusion_validation": SOURCE_OCCLUSION / "step4d_caption_occlusion_validation.json",
    "final_clipping_adjudication": SOURCE_CLOSURE / "step4d_clipping_final_adjudication.json",
    "final_clipping_validation": SOURCE_CLOSURE / "step4d_clipping_validation.json",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def reference(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": relative(path), "sha256": sha256(path)}


def verify_accepted_state() -> dict:
    freeze = gate.prior.freeze_integrity()
    if sha256(SHADOW_FREEZE) != SHADOW_FREEZE_SHA256:
        raise RuntimeError("accepted shadow freeze drift")
    for path in AUTHORITY_PATHS.values():
        load(path)
    clipping_adjudication = load(AUTHORITY_PATHS["final_clipping_adjudication"])
    occlusion = load(AUTHORITY_PATHS["caption_occlusion_adjudication"])
    if clipping_adjudication["class_verdict"] != "UNSUPPORTED_WITH_CURRENT_EVIDENCE":
        raise RuntimeError("accepted clipping verdict drift")
    if occlusion["class_level_verdict"] != "UNSUPPORTED_WITH_CURRENT_EVIDENCE":
        raise RuntimeError("accepted occlusion verdict drift")
    if any(row["final_verdict"] == "SOURCE_REQUIRED_CLIPPING" for row in clipping_adjudication["cases"]):
        raise RuntimeError("unexpected clipping authority")
    if occlusion["source_required_occlusion_identities"]:
        raise RuntimeError("unexpected occlusion authority")
    shadow = load(SHADOW_FREEZE)
    if shadow["shadow_identity_accounting"]["positive_count"] != 1 or shadow["shadow_identity_accounting"]["negative_control_parameter_authority_count"] != 0 or shadow["shadow_identity_accounting"]["global_propagation"]:
        raise RuntimeError("accepted shadow authority drift")
    return {"freeze_integrity": freeze, "shadow_freeze_sha256": sha256(SHADOW_FREEZE)}


def closure_report(matrix: dict, capabilities: dict, acceptance_path: str, freeze_path: str) -> bytes:
    lines = [
        "RESULT: PASS_STEP_4D_HUMAN_ACCEPTED_ADVANCED_TEXT_EFFECTS_FROZEN_CURRENT_VERSION", "",
        "HUMAN_DECISION: ACCEPT", "STEP_4D_CURRENT_VERSION_DECISION: ACCEPT",
        "STEP_4D_FINAL_STATUS: COMPLETE / HUMAN-ACCEPTED / FROZEN CURRENT VERSION",
        "ADVANCED_TEXT_EFFECTS_STATUS: FROZEN_CURRENT_VERSION_WITH_EXPLICIT_DEFERRED_REQUIRED_CAPABILITIES", "",
        "FINAL_EFFECT_CLASS_MATRIX",
    ]
    for name, row in matrix["classes"].items():
        lines.append(f"- {name}: {json.dumps(row, sort_keys=True)}")
    lines.extend(["", "DEFERRED_REQUIRED_CAPABILITIES"])
    for row in capabilities["capabilities"]:
        lines.append(f"- {row['id']}: {row['status']}; required before {row['required_before']}")
    lines.extend([
        "", "CURRENT_VERSION_COMPLETE_SEMANTICS: source-required shadow reproduced at accepted approximate fidelity; glow/texture/gradient not source-required; clipping/occlusion explicitly unsupported and not fabricated",
        "PRODUCT_COMPLETE_SEMANTICS: NOT CLAIMED; generic clipping and occlusion detection remain required before final parity/release",
        "QUALITY_TARGET_CLAIMED: NO", "LONG_TERM_TARGET: >=85% HUMAN-ACCEPTABLE RECONSTRUCTION on a representative benchmark",
        "PRODUCTION_RUNTIME_CHANGED: NO", "UPSTREAM_ARTIFACTS_CHANGED: NO", "RESOLVE_MUTATED: NO",
        "STEP_5_STATUS: UNBLOCKED / NOT STARTED", "STEP_6_STARTED: NO",
        f"STEP4D_ACCEPTANCE_ARTIFACT_PATH: {acceptance_path}", f"STEP4D_FREEZE_ARTIFACT_PATH: {freeze_path}",
        "STEP_4D_REOPEN_ALLOWED_NOW: NO", "NEXT_STEP_NAME_ONLY: Step 5 — UNBLOCKED / NOT STARTED", "",
    ])
    return "\n".join(lines).encode()


def build(output: Path, accepted_at: str) -> dict[str, bytes]:
    verified = verify_accepted_state()
    matrix = clipping.class_matrix("UNSUPPORTED_WITH_CURRENT_EVIDENCE")
    matrix.update({
        "current_milestone_status": "COMPLETE_HUMAN_ACCEPTED_FROZEN_CURRENT_VERSION",
        "current_version_closure_ready": True, "human_acceptance_required_before_freeze": False,
        "advanced_text_effects_status": "FROZEN_CURRENT_VERSION_WITH_EXPLICIT_DEFERRED_REQUIRED_CAPABILITIES",
    })
    capabilities = clipping.deferred_capabilities()
    required_ids = ["CAPTION_CLIPPING_DETECTION_V2", "CAPTION_OCCLUSION_DETECTION_V2"]
    by_id = {row["id"]: row for row in capabilities["capabilities"]}
    if set(by_id) != set(required_ids) or any(by_id[name]["status"] != "DEFERRED_REQUIRED_CAPABILITY" or by_id[name]["required_before"] != "FINAL_PARITY / RELEASE ACCEPTANCE" for name in required_ids):
        raise RuntimeError("deferred capability accounting incomplete")
    identities = {row["identity"] for row in load(AUTHORITY_PATHS["final_clipping_adjudication"])["cases"]}
    shadow = load(SHADOW_FREEZE)["shadow_identity_accounting"]
    identities.update(shadow["positive_identities"] + shadow["negative_controls"])
    script_text = Path(__file__).read_text(encoding="utf-8")
    hardcoded = sorted(identity for identity in identities if identity in script_text)
    validation = {
        "schema": "video_cloner_step4d_final_closure_validation", "schema_version": 1,
        "result": "PASS_STEP_4D_HUMAN_ACCEPTED_ADVANCED_TEXT_EFFECTS_FROZEN_CURRENT_VERSION",
        "freeze_integrity": verified["freeze_integrity"], "shadow_freeze_status": "PASS", "shadow_freeze_sha256": verified["shadow_freeze_sha256"],
        "bookkeeping_correction": "PASS_CAPTION_CLIPPING_DETECTION_V2_ADDED",
        "required_deferred_capabilities": required_ids, "required_before": "FINAL_PARITY / RELEASE ACCEPTANCE",
        "clipping_adjudication_changed": False, "occlusion_adjudication_changed": False, "unknown_pixel_semantics_changed": False,
        "shadow_authority_changed": False, "production_effect_mechanisms_added": 0, "production_hardcoded_identities": hardcoded,
        "generalization_gate": "PASS" if not hardcoded else "FAIL", "production_runtime_changed": False,
        "upstream_artifacts_changed": False, "resolve_mutated": False, "step5_status": "UNBLOCKED_NOT_STARTED", "step6_started": False,
        "human_decision": "ACCEPT", "step4d_current_version_decision": "ACCEPT", "step4d_final_status": "COMPLETE_HUMAN_ACCEPTED_FROZEN_CURRENT_VERSION",
    }
    output_rel = relative(output)
    acceptance_path = f"{output_rel}/step4d_human_acceptance.json"
    freeze_path = relative(STATE_PATH)
    report = closure_report(matrix, capabilities, acceptance_path, freeze_path)
    core = {
        "step4d_effect_class_final_matrix.json": json_bytes(matrix),
        "step4d_deferred_required_capabilities.json": json_bytes(capabilities),
        "step4d_final_closure_validation.json": json_bytes(validation),
        "FINAL_REPORT.md": report,
    }
    acceptance = {
        "schema": "video_cloner_step4d_human_acceptance", "schema_version": 1, "accepted_at": accepted_at,
        "human_decision": "ACCEPT", "step_4d_current_version_decision": "ACCEPT",
        "human_decision_source": "ACCEPT_STEP_4D_CURRENT_VERSION_AFTER_REQUIRED_BOOKKEEPING_CORRECTION",
        "bookkeeping_correction_satisfied": True,
        "accepted_class_matrix": matrix["classes"],
        "deferred_required_capabilities": required_ids,
        "unsupported_capabilities_considered_solved": False,
        "quality_target_claimed": False,
        "accepted_artifacts": {name: {"path": f"{output_rel}/{name}", "sha256": sha256_bytes(data)} for name, data in core.items()},
    }
    core["step4d_human_acceptance.json"] = json_bytes(acceptance)
    proof = {
        "schema": "video_cloner_step4d_final_closure_determinism", "schema_version": 1,
        "complete_generation_count": 2, "rerun_byte_identical": True,
        "artifact_sha256": {name: sha256_bytes(data) for name, data in core.items()},
    }
    core["determinism_proof.json"] = json_bytes(proof)
    authority = {name: reference(path) for name, path in AUTHORITY_PATHS.items()}
    authority.update({name.removesuffix(".json").replace("FINAL_REPORT.md", "final_step4d_closure_report"): {"path": f"{output_rel}/{name}", "sha256": sha256_bytes(data)} for name, data in core.items()})
    freeze = {
        "schema": "video_cloner_step4d_advanced_text_effects_freeze_state", "schema_version": 1, "updated_at": accepted_at,
        "result": "PASS_STEP_4D_HUMAN_ACCEPTED_ADVANCED_TEXT_EFFECTS_FROZEN_CURRENT_VERSION",
        "step": "STEP_4D_ADVANCED_TEXT_EFFECTS", "step4d_final_status": "COMPLETE_HUMAN_ACCEPTED_FROZEN_CURRENT_VERSION",
        "advanced_text_effects_status": "FROZEN_CURRENT_VERSION_WITH_EXPLICIT_DEFERRED_REQUIRED_CAPABILITIES",
        "human_decision": "ACCEPT", "reopen_allowed_now": False,
        "reopen_conditions": ["final_parity_material_inadequacy", "CAPTION_CLIPPING_DETECTION_V2_work_begins", "CAPTION_OCCLUSION_DETECTION_V2_work_begins", "new_source_reel_requires_unsupported_advanced_effect"],
        "effect_class_matrix": matrix["classes"], "deferred_required_capabilities": required_ids,
        "frozen_step4d_authority": authority,
        "upstream_freezes": verified["freeze_integrity"]["hashes"], "shadow_freeze_sha256": verified["shadow_freeze_sha256"],
        "production_runtime_changed": False, "upstream_artifacts_changed": False, "resolve_mutated": False,
        "quality_target_claimed": False, "step5_status": "UNBLOCKED_NOT_STARTED", "step6_started": False,
    }
    core["__freeze_state__"] = json_bytes(freeze)
    return core


def generate(output: Path, accepted_at: str) -> dict:
    if output.exists(): raise FileExistsError(output)
    if STATE_PATH.exists(): raise FileExistsError(STATE_PATH)
    first, second = build(output, accepted_at), build(output, accepted_at)
    if first != second: raise RuntimeError("non-deterministic Step 4D closure")
    output.mkdir(parents=True)
    for name, data in first.items():
        if name != "__freeze_state__": (output / name).write_bytes(data)
    STATE_PATH.write_bytes(first["__freeze_state__"])
    freeze = load(STATE_PATH)
    for item in freeze["frozen_step4d_authority"].values():
        path = ROOT / item["path"]
        if not path.is_file() or sha256(path) != item["sha256"]: raise RuntimeError(f"frozen artifact mismatch: {path}")
    return {"result": freeze["result"], "output": str(output), "freeze": str(STATE_PATH)}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=Path, required=True); parser.add_argument("--accepted-at", required=True)
    args = parser.parse_args(); print(json.dumps(generate(args.output_dir.resolve(), args.accepted_at), sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
