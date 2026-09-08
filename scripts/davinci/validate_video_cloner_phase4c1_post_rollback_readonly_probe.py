"""Validate post-rollback probe evidence without contacting Resolve."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resolve_workspace.modules.video_cloner_phase4c1_post_rollback_readonly_probe import (
    ACTION,
    DETERMINISM_CLASSIFICATIONS,
    LINKAGE_CLASSIFICATIONS,
    MEDIA_CLASSIFICATIONS,
    MODE,
    PROFILE_REEL1,
    PROFILE_REEL2,
    TARGET_CLASSIFICATIONS,
    TASK_ID,
    ZERO_MUTATIONS,
    compare_passes,
)
from scripts.davinci.prepare_video_cloner_phase4c1_post_rollback_readonly_probe import MODULE


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(path.name)
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_report(command: dict, report: dict) -> list[str]:
    failures = []
    payload = command.get("payload") or {}
    if command.get("task") != TASK_ID or command.get("module") != MODULE or command.get("mode") != MODE or payload.get("action") != ACTION:
        failures.append("command_identity")
    if payload.get("read_only") is not True or payload.get("mutation_permitted") is not False:
        failures.append("read_only_contract")
    if report.get("operation_id") != payload.get("operation_id") or report.get("project_name") != payload.get("expected_project_name"):
        failures.append("operation_identity")
    profile = str(payload.get("diagnostic_profile") or PROFILE_REEL2)
    if profile not in (PROFILE_REEL2, PROFILE_REEL1) or report.get("diagnostic_profile", PROFILE_REEL2) != profile:
        failures.append("diagnostic_profile")
    pass_a, pass_b = report.get("signature_pass_a"), report.get("signature_pass_b")
    if not isinstance(pass_a, dict) or not isinstance(pass_b, dict):
        failures.append("snapshot_passes")
    else:
        for label, snapshot_pass in (("a", pass_a), ("b", pass_b)):
            timelines = snapshot_pass.get("timelines")
            if not isinstance(timelines, list) or snapshot_pass.get("declared_timeline_count") != len(timelines):
                failures.append(f"snapshot_pass_{label}")
                continue
            if any(row.get("timeline_index") != index or not isinstance(row.get("snapshot"), dict) or not row["snapshot"].get("signature") for index, row in enumerate(timelines, 1)):
                failures.append(f"snapshot_rows_{label}")
        expected_classification, expected_mismatches = compare_passes(pass_a, pass_b)
        if report.get("read_determinism_classification") != expected_classification or report.get("signature_mismatches") != expected_mismatches:
            failures.append("determinism_semantics")
    if report.get("read_determinism_classification") not in DETERMINISM_CLASSIFICATIONS:
        failures.append("determinism_classification")
    for mismatch in report.get("signature_mismatches") or []:
        differences = mismatch.get("differences")
        if not isinstance(differences, list) or not differences:
            failures.append("field_diff_missing")
            break
        if any(not isinstance(row, dict) or set(row) != {"path", "kind", "value_a", "value_b"} for row in differences):
            failures.append("field_diff_surface")
            break
    if profile == PROFILE_REEL2:
        target = report.get("target_rollback_state") or {}
        if target.get("classification") not in TARGET_CLASSIFICATIONS:
            failures.append("target_classification")
        elif target.get("classification") == "ROLLBACK_TARGET_BASELINE_RESTORED" and not all((target.get("checks") or {}).values()):
            failures.append("target_baseline_semantics")
    else:
        target = report.get("reel1_restoration_state") or {}
        contract = payload.get("target_contract") or {}
        spans = target.get("spans")
        allowed = {"ORIGINAL_ORPHAN_PRESENT", "VALID_REPLACEMENT_PRESENT", "UNEXPECTED_OR_PARTIAL_ITEM", "MISSING"}
        if (
            target.get("classification") != "REEL1_EXPECTED_SPANS_CLASSIFIED"
            or target.get("occurrence_count") != 1
            or target.get("expected_spans") != contract.get("expected_spans")
            or not isinstance(spans, list)
            or len(spans) != 5
            or any((row.get("start"), row.get("end")) != (expected.get("start"), expected.get("end")) for row, expected in zip(spans, contract.get("expected_spans") or []))
            or any(row.get("classification") not in allowed or not isinstance(row.get("items"), list) for row in spans)
        ):
            failures.append("reel1_span_evidence")
        if not isinstance(report.get("current_timeline_name"), str) or report.get("current_timeline_name") not in (report.get("indexed_timeline_names") or []):
            failures.append("current_timeline_identity")
        protection = report.get("reel2_protection_state") or {}
        if protection.get("occurrence_count") != 1 or protection.get("ok") is not True or not all((protection.get("checks") or {}).values()) or not protection.get("timeline_signature"):
            failures.append("reel2_protection")
    neutral = report.get("neutral_media") or {}
    if neutral.get("classification") not in MEDIA_CLASSIFICATIONS or not isinstance(neutral.get("objects"), list) or neutral.get("count") != len(neutral.get("objects", [])):
        failures.append("neutral_media")
    linkage = report.get("reel1_flash_carriers") or {}
    if profile == PROFILE_REEL2 and (linkage.get("classification") not in LINKAGE_CLASSIFICATIONS or not isinstance(linkage.get("carriers"), list) or linkage.get("count") != len(linkage.get("carriers", []))):
        failures.append("reel1_linkage")
    if report.get("read_only") is not True or report.get("mutation_counts") != ZERO_MUTATIONS:
        failures.append("zero_mutation")
    if report.get("ok") is not True or report.get("failures"):
        failures.append("runtime_ok")
    return failures


def validate(root: Path, run_id: str) -> tuple[dict, list[str]]:
    root = root.resolve()
    run_dir = root / ".agent" / "reports" / TASK_ID / run_id
    required = ("probe_command.json", "publication_receipt.json", "status.json", "report.json", "run.log")
    failures = [f"missing:{name}" for name in required if not (run_dir / name).is_file() or (run_dir / name).stat().st_size == 0]
    if failures:
        return {"ok": False, "task_id": TASK_ID, "run_id": run_id, "failures": failures}, failures
    command, receipt, status, report = (load(run_dir / name) for name in ("probe_command.json", "publication_receipt.json", "status.json", "report.json"))
    command_name = f"{TASK_ID}_{run_id}.json"
    queue = root / ".agent" / "commands"
    completed = queue / "completed" / command_name
    locations = [queue / state / command_name for state in ("pending", "running", "completed", "failed") if (queue / state / command_name).is_file()]
    if locations != [completed] or not completed.is_file() or sha256(completed) != receipt.get("command_sha256"):
        failures.append("command_lifecycle")
    if status.get("ok") is not True or status.get("run_id") not in (None, run_id):
        failures.append("status")
    if receipt.get("task_id") != TASK_ID or receipt.get("run_id") != run_id or receipt.get("command_count") != 1:
        failures.append("receipt")
    failures.extend(validate_report(command, report))
    summary = {
        "ok": not failures,
        "task_id": TASK_ID,
        "run_id": run_id,
        "read_determinism_classification": report.get("read_determinism_classification"),
        "target_rollback_classification": (report.get("target_rollback_state") or {}).get("classification"),
        "neutral_media_classification": (report.get("neutral_media") or {}).get("classification"),
        "reel1_linkage_classification": (report.get("reel1_flash_carriers") or {}).get("classification"),
        "mutation_counts": report.get("mutation_counts"),
        "failures": failures,
    }
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result, failures = validate(args.root, args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
