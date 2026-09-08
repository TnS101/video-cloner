"""Validate Step 3D visual-layer application evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3D_LIFECYCLE_VISUAL_LAYER_FUSION_PAGE_RECOVERY_V1"
MODE = "apply_step_3D_visual_layers_fusion_page_recovery_v1"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_lifecycle"
SOURCE_HASH_CONTRACT_VERSION = 2
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
CLONE_STRATEGY = "IMPORT_THEN_FUSION_PAGE_LOAD_AND_ORPHAN_RECOVERY_V4"
SOURCE_DEPENDENCY_PATHS = {
    "resolve_workspace/modules/step_3D_apply_visual_layers.py",
    "resolve_workspace/resolve_apply_caption_position_full_step_3B_5.py",
    "resolve_workspace/resolve_apply_caption_animation_step_3C.py",
    "resolve_workspace/modules/step_3D_import_lifecycle_timeline.py",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_position_full_plan_step_3B_5B.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_animation_step_3C_source_targets.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json",
    "data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_step_3D_lifecycle.fcpxml",
}
REQUIRED = (
    "visual_layer_command.json",
    "publication_receipt.json",
    "visual_layer_preflight.json",
    "source_fusion_comp_exports.json",
    "fusion_page_activation.json",
    "fusion_comp_clone_application.json",
    "animation_application.json",
    "position_application.json",
    "visual_layer_readback.json",
    "source_timeline_protection.json",
    "visual_layer_application_result.json",
    "status.json",
    "report.json",
    "run.log",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command_inventory(root: Path, exclude_run_id: str) -> list[dict[str, Any]]:
    rows = []
    queue = root / ".agent/commands"
    for state in ("pending", "running", "completed", "failed"):
        for path in sorted((queue / state).glob("*.json")):
            if exclude_run_id in path.name:
                continue
            rows.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha256(path),
            })
    return rows


def validate(root: Path, run_id: str) -> tuple[dict[str, Any], list[str]]:
    root = root.resolve()
    run_dir = root / ".agent/reports" / TASK_ID / run_id
    failures: list[str] = []
    for name in REQUIRED:
        path = run_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"missing_or_empty:{name}")
    if failures:
        return {"ok": False, "task_id": TASK_ID, "run_id": run_id, "failures": failures}, failures

    command = load_json(run_dir / "visual_layer_command.json")
    receipt = load_json(run_dir / "publication_receipt.json")
    preflight = load_json(run_dir / "visual_layer_preflight.json")
    exports = load_json(run_dir / "source_fusion_comp_exports.json")
    page_activation = load_json(run_dir / "fusion_page_activation.json")
    clones = load_json(run_dir / "fusion_comp_clone_application.json")
    animation = load_json(run_dir / "animation_application.json")
    position = load_json(run_dir / "position_application.json")
    readback = load_json(run_dir / "visual_layer_readback.json")
    protection = load_json(run_dir / "source_timeline_protection.json")
    application = load_json(run_dir / "visual_layer_application_result.json")
    status = load_json(run_dir / "status.json")
    report = load_json(run_dir / "report.json")

    command_name = f"{TASK_ID}_{run_id}.json"
    queue = root / ".agent/commands"
    completed = queue / "completed" / command_name
    instances = [
        queue / state / command_name
        for state in ("pending", "running", "completed", "failed")
        if (queue / state / command_name).is_file()
    ]
    if instances != [completed]:
        failures.append("command_lifecycle_not_completed")
    command_hash = sha256(completed) if completed.is_file() else None
    if command_hash != receipt.get("command_sha256"):
        failures.append("command_hash_lineage")

    payload = command.get("payload") or {}
    if (
        command.get("task") != TASK_ID
        or command.get("run_id") != run_id
        or command.get("mode") != MODE
        or payload.get("apply_permitted") is not True
        or payload.get("create_timeline") is not False
        or payload.get("delete_timeline") is not False
        or payload.get("save_project") is not True
        or payload.get("clone_source_fusion_comps") is not True
        or payload.get("activate_fusion_page") is not True
        or payload.get("clone_strategy") != CLONE_STRATEGY
        or payload.get("source_timeline_name") != SOURCE_TIMELINE_NAME
        or payload.get("target_timeline_name") != TARGET_TIMELINE_NAME
    ):
        failures.append("command_contract")
    source_hashes = payload.get("source_hashes")
    if (
        payload.get("source_hash_contract_version") != SOURCE_HASH_CONTRACT_VERSION
        or payload.get("source_hash_algorithm") != SOURCE_HASH_ALGORITHM
        or not isinstance(source_hashes, dict)
        or set(source_hashes) != SOURCE_DEPENDENCY_PATHS
        or any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in (source_hashes or {}).values()
        )
        or preflight.get("source_hash_contract_version") != SOURCE_HASH_CONTRACT_VERSION
        or preflight.get("source_hash_algorithm") != SOURCE_HASH_ALGORITHM
        or preflight.get("source_hashes") != source_hashes
        or preflight.get("source_dependency_count") != len(SOURCE_DEPENDENCY_PATHS)
        or preflight.get("clone_strategy") != CLONE_STRATEGY
    ):
        failures.append("source_hash_contract")

    if status.get("ok") is not True or status.get("running") is not False:
        failures.append("status_contract")
    if report.get("ok") is not True or report.get("failures") not in ([], None):
        failures.append("runtime_report")

    if (
        preflight.get("ok") is not True
        or preflight.get("source_caption_count") != 116
        or preflight.get("target_caption_count") != 116
        or preflight.get("target_zero_comp_count", 0)
        + preflight.get("target_existing_comp_count", 0) != 116
        or (preflight.get("plan_summary") or {}).get("animation_count") != 8
        or (preflight.get("plan_summary") or {}).get("keyframe_count") != 16
        or (preflight.get("source_visual_contract_gate") or {}).get("ok") is not True
        or (preflight.get("source_visual_contract_gate") or {}).get("authority")
        != "ACCEPTED_SOURCE_COMP_IDENTITY_PLUS_PLAN_DRIVEN_TARGET_READBACK"
        or (preflight.get("source_visual_contract_gate") or {}).get(
            "source_caption_fusion_and_text_gate"
        ) is not True
        or (preflight.get("source_visual_contract_gate") or {}).get(
            "target_position_readback_required"
        ) != 116
        or (preflight.get("source_visual_contract_gate") or {}).get(
            "target_animation_readback_required"
        ) != 8
        or (preflight.get("source_visual_contract_gate") or {}).get(
            "target_keyframe_readback_required"
        ) != 16
        or preflight.get("writes_attempted") is not False
    ):
        failures.append("preflight_contract")

    if (
        exports.get("ok") is not True
        or exports.get("caption_count") != 116
        or len(exports.get("files") or []) != 116
    ):
        failures.append("source_exports_contract")

    if (
        page_activation.get("ok") is not True
        or str(page_activation.get("page_after") or "").casefold() != "fusion"
        or page_activation.get("target_timeline_selected") is not True
        or page_activation.get("target_caption_count_after_activation") != 116
    ):
        failures.append("fusion_page_activation_contract")
    if (
        clones.get("ok") is not True
        or clones.get("clone_strategy") != CLONE_STRATEGY
        or clones.get("caption_count") != 116
        or clones.get("imported_count", 0) + clones.get("already_present_count", 0) != 116
        or clones.get("direct_import_count", 0)
        + clones.get("add_copy_settings_count", 0)
        + clones.get("recovered_blank_count", 0)
        != clones.get("imported_count", 0)
    ):
        failures.append("clone_application_contract")

    if (
        animation.get("ok") is not True
        or animation.get("selected_animation_count") != 8
        or animation.get("modified_count", 0) + animation.get("already_correct_count", 0) != 8
    ):
        failures.append("animation_application_contract")
    if (
        position.get("ok") is not True
        or position.get("position_count") != 116
        or position.get("modified_count", 0) + position.get("already_correct_count", 0) != 116
    ):
        failures.append("position_application_contract")

    if (
        readback.get("ok") is not True
        or readback.get("position_verified_count") != 116
        or readback.get("animation_verified_count") != 8
        or readback.get("keyframe_verified_count") != 16
        or readback.get("identity_verified_count") != 116
        or readback.get("style_verified_count") != 116
        or readback.get("layout_verified_count") != 116
        or len(readback.get("center_modifier_cues") or []) != 4
        or len(readback.get("size_modifier_cues") or []) != 4
        or readback.get("failures") not in ([], None)
    ):
        failures.append("readback_contract")

    if (
        protection.get("ok") is not True
        or protection.get("source_timeline_name") != SOURCE_TIMELINE_NAME
        or protection.get("source_timeline_unchanged") is not True
        or protection.get("source_before") != protection.get("source_after")
        or protection.get("target_timeline_name") != TARGET_TIMELINE_NAME
        or protection.get("timeline_names_before") != protection.get("timeline_names_after")
        or protection.get("timeline_created") is not False
        or protection.get("timeline_deleted") is not False
        or protection.get("accepted_state_sha256_before")
        != protection.get("accepted_state_sha256_after")
        or protection.get("save_call_count") != 1
    ):
        failures.append("protection_contract")

    if (
        application.get("ok") is not True
        or application.get("classification")
        != "SOURCE_FUSION_COMPS_CLONED_TO_LIFECYCLE_TIMELINE"
        or application.get("clone_strategy") != CLONE_STRATEGY
        or application.get("fusion_page_activated") is not True
        or application.get("source_timeline_name") != SOURCE_TIMELINE_NAME
        or application.get("target_timeline_name") != TARGET_TIMELINE_NAME
        or application.get("current_timeline_name") != TARGET_TIMELINE_NAME
        or application.get("caption_count") != 116
        or application.get("caption_lane_count") != 5
        or application.get("fusion_comp_imported_count", 0)
        + application.get("fusion_comp_already_present_count", 0) != 116
        or application.get("fusion_comp_direct_import_count", 0)
        + application.get("fusion_comp_add_copy_settings_count", 0)
        + application.get("fusion_comp_recovered_blank_count", 0)
        != application.get("fusion_comp_imported_count", 0)
        or application.get("position_verified_count") != 116
        or application.get("animation_verified_count") != 8
        or application.get("keyframe_verified_count") != 16
        or application.get("center_modifier_count") != 4
        or application.get("size_modifier_count") != 4
        or application.get("source_timeline_modified") is not False
        or application.get("timeline_created") is not False
        or application.get("save_call_count") != 1
        or application.get("accepted_state_changed") is not False
        or application.get("visual_approval_required") is not True
    ):
        failures.append("application_result_contract")

    if (
        report.get("classification")
        != "SOURCE_FUSION_COMPS_CLONED_TO_LIFECYCLE_TIMELINE"
        or report.get("current_timeline_name") != TARGET_TIMELINE_NAME
        or report.get("position_verified_count") != 116
        or report.get("animation_verified_count") != 8
        or report.get("keyframe_verified_count") != 16
        or report.get("source_timeline_modified") is not False
        or report.get("timeline_created") is not False
        or report.get("save_call_count") != 1
        or report.get("visual_approval_required") is not True
    ):
        failures.append("runtime_counts")

    latest_path = root / ".agent/state/latest_accepted.json"
    latest_hash = sha256(latest_path) if latest_path.is_file() else None
    if latest_hash != payload.get("accepted_state_sha256"):
        failures.append("accepted_state_changed")
    if command_inventory(root, run_id) != payload.get("command_inventory_before_publication"):
        failures.append("non_current_command_inventory_changed")
    if list((queue / "pending").glob("*.json")) or list((queue / "running").glob("*.json")):
        failures.append("active_command_after_run")

    result = {
        "ok": not failures,
        "task_id": TASK_ID,
        "run_id": run_id,
        "classification": application.get("classification") if not failures else None,
        "clone_strategy": application.get("clone_strategy"),
        "command_sha256": command_hash,
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "current_timeline_name": application.get("current_timeline_name"),
        "caption_count": application.get("caption_count"),
        "caption_lane_count": application.get("caption_lane_count"),
        "position_verified_count": application.get("position_verified_count"),
        "animation_verified_count": application.get("animation_verified_count"),
        "keyframe_verified_count": application.get("keyframe_verified_count"),
        "fusion_comp_imported_count": application.get("fusion_comp_imported_count"),
        "fusion_comp_already_present_count": application.get("fusion_comp_already_present_count"),
        "fusion_comp_direct_import_count": application.get(
            "fusion_comp_direct_import_count"
        ),
        "fusion_comp_add_copy_settings_count": application.get(
            "fusion_comp_add_copy_settings_count"
        ),
        "position_modified_count": application.get("position_modified_count"),
        "animation_modified_count": application.get("animation_modified_count"),
        "source_timeline_unchanged": protection.get("source_timeline_unchanged"),
        "visual_approval_required": True,
        "next_boundary": "Play the lifecycle timeline and visually approve caption positions, independent overlaps, and Step 3C motion.",
        "failures": failures,
    }
    return result, failures


def final_report(result: dict[str, Any]) -> str:
    return "\n".join([
        "# Approach",
        "",
        "Reused the existing Step 3D lifecycle timeline, cloned the 116 accepted Text+ Fusion compositions from the protected original timeline onto the lifecycle-timed title items, verified positions and animations, saved once, and performed persistent readback without touching the original timeline.",
        "",
        "# Key evidence",
        "",
        f"- Run ID: `{result['run_id']}`.",
        f"- Classification: `{result.get('classification')}`.",
        f"- Fusion comps imported: {result.get('fusion_comp_imported_count')}; already present: {result.get('fusion_comp_already_present_count')}.",
        f"- Clone routes: direct import {result.get('fusion_comp_direct_import_count')}; AddFusionComp + CopySettings {result.get('fusion_comp_add_copy_settings_count')}; recovered blank comp {result.get('fusion_comp_recovered_blank_count')}.",
        "- Positions verified: 116/116.",
        "- Animated captions verified: 8/8; persistent keyframes: 16/16.",
        "- Center modifiers: 4; Size modifiers: 4.",
        "- Original timeline unchanged; no timeline created or deleted.",
        "- Accepted state unchanged.",
        "",
        "# PASS or FAIL",
        "",
        "PASS — STEP_3D_LIFECYCLE_FUSION_VISUAL_LAYERS_CLONED",
        "",
        "# Next boundary",
        "",
        "Play the lifecycle timeline and visually compare caption positions and animations against the source video.",
        "",
        "Manual visual approval required: YES",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result, failures = validate(args.root, args.run_id)
    run_dir = args.root.resolve() / ".agent/reports" / TASK_ID / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "visual_layer_application_validation.json", result)
    if not failures:
        (run_dir / "FINAL_REPORT.md").write_text(final_report(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
