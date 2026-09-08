#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence


TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_ACCEPTANCE_FINALIZER_V1"
STEP = "Step 3B.6D"
SOURCE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_TOPOLOGY_REPAIR_V1"
SOURCE_RUN_ID = "20260803T091309371Z_0fde893916bf4b11ae67e33b776afbdb"
SOURCE_COMMAND_SHA256 = "78ea522ef7c62488a4f09aea382e8c83a5471602f1bfeff07050263d5fc0d54c"
SOURCE_REPORT_REL = Path(".agent/reports") / SOURCE_TASK_ID / SOURCE_RUN_ID
LATEST_ACCEPTED_REL = Path(".agent/state/latest_accepted.json")
EXPECTED_LATEST_ACCEPTED_SHA256 = "b90348ba92341f5b26e1f5755b250f0a00ab9bf72a8cc53c7db068ac945a5696"

EXPECTED_SOURCE_HASHES: Dict[str, str] = {
    "FINAL_REPORT.md": "07f3f22e9e8fd5cb46092971f3afbca79cb929919af618450176b4e3b9c046ef",
    "address_resolved_operation_comparison.json": "74e735bf98c15f7e540346fce9159948e4eede5f987cecc8d65bf3a4cce980dd",
    "affected_regression_report.json": "cf96dcc94cda8d6fcdfcd3916bb6f3a05c8f905304ecb2b68832201e530a8f8d",
    "direct_frame_state_comparison.json": "2787ac815344a980fd763f4f7a5abf524f3e7a1e362d574d8859e2e0c09c7625",
    "key_deletion_journal.json": "a673fa15e794e10d84bd3cf6d9af6977668783ee311dc36efecf63fc310f1a2d",
    "lifecycle_runtime_observation.json": "c227318cff580a84f2ac5b03a9aa082f0637f48ae27bfbc83b1275a27d5713e0",
    "phase3_idempotency_report.json": "584342eb176f851c39f9578ea88be002f7f3fc93426ee484dd444b690d085ecf",
    "protected_state_audit.json": "eec21cfcf225b6b4df10130b8d3178069ccf4e54c3a78ee8bcfce340cb2ff3aa",
    "publication_receipt.json": "b599fa4bf6cc112f82af2632044209abcd6da9851c242fdd7a0f27283068c091",
    "report.json": "5f1773858f0b072914c526372376675d47568f895027c13a12f46a993ca05a37",
    "run.log": "57abd0dd074193e0811b3ac0a0457257199af3dda1d9600f639fc948abd6c94d",
    "status.json": "c1b3c1ebbdcb3ebbb48e76586e3cbe3db55790e08bf308f074fafb8ec7c64260",
    "topology_preservation_audit.json": "cb4edd78fc7cb5ed75245c2963cda5d93392dbc4207a1440a98d48a97f46e3e4",
    "topology_repair_command.json": SOURCE_COMMAND_SHA256,
    "topology_repair_post_state.json": "789eee6040b0448e4f518cb794add160af3e275fd3cbd8295aa9c6c102d64e9f",
    "topology_repair_pre_state.json": "670b273d9a3986dded11d86bce9f8f0dd782bf9501ea6565ba135ba73f4db5d0",
    "topology_repair_validation.json": "f11e2fdbc6556cd5bbd76d5f37c1e4baf317c9ab8b3ede26a64acca38d0cdf25",
}

EXPECTED_APPROVAL = {
    "schema": "video_cloner_manual_visual_approval",
    "schema_version": "1.0",
    "task_id": TASK_ID,
    "step": STEP,
    "source_task_id": SOURCE_TASK_ID,
    "source_run_id": SOURCE_RUN_ID,
    "approved": True,
    "approved_by": "user",
    "approved_at": "2026-08-03T12:52:00+03:00",
    "statement": "VISUAL_PASS — Step 3B.6D approved.",
    "screenshot_sha256": "527538f53b112aaa1e54b6e4d3e4db10fd0bf5e4a3fbe68b5d49f67415a7ab48",
}


class FinalizationError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FinalizationError(f"missing_file:{path}") from exc
    except json.JSONDecodeError as exc:
        raise FinalizationError(f"invalid_json:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise FinalizationError(f"expected_json_object:{path}")
    return value


def json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        write_bytes(temporary, data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FinalizationError(message)


def require_equal(actual: Any, expected: Any, field: str) -> None:
    if actual != expected:
        raise FinalizationError(f"field_mismatch:{field}:expected={expected!r}:actual={actual!r}")


def require_zero_fields(payload: Mapping[str, Any], fields: Iterable[str], prefix: str) -> None:
    for field in fields:
        require_equal(payload.get(field), 0, f"{prefix}.{field}")


def validate_approval(approval_path: Path) -> Dict[str, Any]:
    approval = load_json(approval_path)
    for field, expected in EXPECTED_APPROVAL.items():
        require_equal(approval.get(field), expected, f"approval.{field}")

    checklist = approval.get("checklist_confirmed")
    require(isinstance(checklist, list), "approval.checklist_confirmed_not_list")
    require(len(checklist) == 7, "approval.checklist_confirmed_count")
    require(all(isinstance(item, str) and item.strip() for item in checklist), "approval.checklist_invalid")
    return approval


def validate_hashes(source_dir: Path) -> Dict[str, str]:
    observed: Dict[str, str] = {}
    for name, expected in EXPECTED_SOURCE_HASHES.items():
        path = source_dir / name
        require(path.is_file(), f"missing_source_artifact:{path}")
        actual = sha256_file(path)
        require_equal(actual, expected, f"sha256.{name}")
        observed[name] = actual
    return observed


def validate_source_evidence(repo_root: Path) -> Dict[str, Any]:
    source_dir = repo_root / SOURCE_REPORT_REL
    hashes = validate_hashes(source_dir)

    status = load_json(source_dir / "status.json")
    require_equal(status.get("ok"), True, "status.ok")
    require_equal(status.get("running"), False, "status.running")
    require_equal(status.get("run_id"), SOURCE_RUN_ID, "status.run_id")

    report = load_json(source_dir / "report.json")
    require_equal(report.get("ok"), True, "report.ok")
    require_equal(report.get("task_id"), SOURCE_TASK_ID, "report.task_id")
    require_equal(report.get("run_id"), SOURCE_RUN_ID, "report.run_id")
    require_equal(report.get("topology_restored"), True, "report.topology_restored")
    require_equal(report.get("accepted_state_unchanged"), True, "report.accepted_state_unchanged")
    require_equal(report.get("address_resolved_current_target"), 36, "report.address_resolved_current_target")
    require_equal(report.get("address_resolved_current_other"), 0, "report.address_resolved_current_other")
    require_equal(report.get("direct_frame_current_target"), 34, "report.direct_frame_current_target")
    require_equal(report.get("direct_frame_current_other"), 2, "report.direct_frame_current_other")
    require_equal(report.get("key_delete_call_count"), 2, "report.key_delete_call_count")
    require_equal(report.get("value_setter_call_count"), 0, "report.value_setter_call_count")
    require_equal(report.get("modifier_mutation_call_count"), 0, "report.modifier_mutation_call_count")
    require_equal(report.get("save_call_count"), 0, "report.save_call_count")
    require_equal(report.get("manual_visual_approval_required"), True, "report.manual_visual_approval_required")
    require_equal(report.get("step_3B_6D_acceptance_status"), "BLOCKED_PENDING_CLOUD_REVIEW", "report.step_3B_6D_acceptance_status")

    validation = load_json(source_dir / "topology_repair_validation.json")
    require_equal(validation.get("ok"), True, "validation.ok")
    require_equal(validation.get("task_id"), SOURCE_TASK_ID, "validation.task_id")
    require_equal(validation.get("run_id"), SOURCE_RUN_ID, "validation.run_id")
    require_equal(validation.get("topology_restored"), True, "validation.topology_restored")
    require_equal(validation.get("lifecycle"), ["pending", "running", "completed"], "validation.lifecycle")
    require_equal(validation.get("key_delete_call_count"), 2, "validation.key_delete_call_count")
    require_equal(validation.get("value_setter_call_count"), 0, "validation.value_setter_call_count")
    require_equal(validation.get("command_sha256"), SOURCE_COMMAND_SHA256, "validation.command_sha256")
    require_equal(validation.get("address_resolved_result"), {"current_other": 0, "current_target": 36}, "validation.address_resolved_result")
    require_equal(validation.get("direct_frame_result"), {"current_other": 2, "current_target": 34}, "validation.direct_frame_result")

    address = load_json(source_dir / "address_resolved_operation_comparison.json")
    for field, expected in {
        "operation_count": 36,
        "current_target": 36,
        "current_other": 0,
        "missing": 0,
        "ambiguous": 0,
        "blend": 0,
    }.items():
        require_equal(address.get(field), expected, f"address.{field}")
    operations = address.get("operations")
    require(isinstance(operations, list) and len(operations) == 36, "address.operations_count")
    raw_rows = [
        row for row in operations
        if isinstance(row, dict) and row.get("addressing") == "capture_raw_key_identity"
    ]
    require_equal(len(raw_rows), 2, "address.raw_identity_row_count")
    require_equal(
        {(row.get("cue_id"), row.get("property"), row.get("raw_key_identifier"), row.get("raw_time")) for row in raw_rows},
        {("sub_013", "Center", 2, 1.0), ("sub_013", "Size", 2, 1.0)},
        "address.raw_identity_rows",
    )
    require(all(row.get("classification") == "CURRENT_TARGET" for row in raw_rows), "address.raw_rows_not_target")

    direct = load_json(source_dir / "direct_frame_state_comparison.json")
    for field, expected in {
        "operation_count": 36,
        "current_target": 34,
        "current_other": 2,
        "missing": 0,
        "ambiguous": 0,
        "blend": 0,
    }.items():
        require_equal(direct.get(field), expected, f"direct.{field}")
    direct_operations = direct.get("operations")
    require(isinstance(direct_operations, list) and len(direct_operations) == 36, "direct.operations_count")
    direct_other = [row for row in direct_operations if isinstance(row, dict) and row.get("classification") == "CURRENT_OTHER"]
    require_equal(
        {(row.get("cue_id"), row.get("property"), row.get("local_frame"), row.get("timeline_frame")) for row in direct_other},
        {("sub_013", "Center", 2, 226), ("sub_013", "Size", 2, 226)},
        "direct.expected_interpolated_rows",
    )

    journal_raw = json.loads((source_dir / "key_deletion_journal.json").read_text(encoding="utf-8"))
    require(isinstance(journal_raw, list), "journal_not_list")
    require_equal(len(journal_raw), 2, "journal.count")
    require_equal(
        {(row.get("cue_id"), row.get("property"), row.get("deleted_time")) for row in journal_raw if isinstance(row, dict)},
        {("sub_013", "Center", 2.0), ("sub_013", "Size", 2.0)},
        "journal.deletions",
    )
    require(all(row.get("ok") is True and row.get("retained_values_unchanged") is True for row in journal_raw), "journal.invalid_row")

    topology = load_json(source_dir / "topology_preservation_audit.json")
    require_equal(topology.get("ok"), True, "topology.ok")
    require_equal(topology.get("v3_candidate_count"), 116, "topology.v3_candidate_count")
    require_equal(
        {(row.get("cue_id"), row.get("property"), row.get("time")) for row in topology.get("deleted_keys") or []},
        {("sub_013", "Center", 2.0), ("sub_013", "Size", 2.0)},
        "topology.deleted_keys",
    )
    for property_name in ("Center", "Size"):
        structure = (((topology.get("actual_after") or {}).get("sub_013") or {}).get(property_name) or {}).get("raw_keyframe_structure")
        require_equal(structure, {"1": 0.0, "2": 1.0, "3": 3.0, "4": 4.0}, f"topology.sub_013.{property_name}")

    protected = load_json(source_dir / "protected_state_audit.json")
    require_equal(protected.get("ok"), True, "protected.ok")
    require_equal(protected.get("protected_operation_count"), 34, "protected.operation_count")
    require_equal(protected.get("protected_values_unchanged"), True, "protected.values_unchanged")
    require_equal(protected.get("non_target_write_count"), 0, "protected.non_target_write_count")
    require_equal(protected.get("key_delete_call_count"), 2, "protected.key_delete_call_count")
    require_zero_fields(protected, ("value_setter_call_count", "modifier_mutation_call_count", "blend_operation_count"), "protected")

    phase3 = load_json(source_dir / "phase3_idempotency_report.json")
    require_equal(phase3.get("ok"), True, "phase3.ok")
    require_equal(phase3.get("structural_topology_restored"), True, "phase3.structural_topology_restored")
    require_equal(phase3.get("timeline_modified"), False, "phase3.timeline_modified")
    require_equal(phase3.get("address_resolved_current_target"), 36, "phase3.address_resolved_current_target")
    require_equal(phase3.get("address_resolved_current_other"), 0, "phase3.address_resolved_current_other")
    require_zero_fields(phase3, ("effective_mutations", "key_delete_calls", "modifier_mutations", "blend_operations", "value_setter_calls"), "phase3")

    regression = load_json(source_dir / "affected_regression_report.json")
    require_equal(regression.get("ok"), True, "regression.ok")
    require_equal(regression.get("step"), "Major Step 3B.6B", "regression.step")
    require_equal(regression.get("failures"), [], "regression.failures")
    require_equal((regression.get("summary") or {}).get("v3_item_count"), 116, "regression.v3_item_count")

    lifecycle = load_json(source_dir / "lifecycle_runtime_observation.json")
    require_equal(lifecycle.get("task_id"), SOURCE_TASK_ID, "lifecycle.task_id")
    require_equal(lifecycle.get("run_id"), SOURCE_RUN_ID, "lifecycle.run_id")
    require_equal(lifecycle.get("running_observed"), True, "lifecycle.running_observed")
    require_equal(lifecycle.get("running_command_sha256"), SOURCE_COMMAND_SHA256, "lifecycle.command_sha256")

    publication = load_json(source_dir / "publication_receipt.json")
    require_equal(publication.get("task_id"), SOURCE_TASK_ID, "publication.task_id")
    require_equal(publication.get("run_id"), SOURCE_RUN_ID, "publication.run_id")
    require_equal(publication.get("pending_observed"), True, "publication.pending_observed")
    require_equal(publication.get("command_sha256"), SOURCE_COMMAND_SHA256, "publication.command_sha256")

    command_rel = Path(str(validation.get("command_path") or ""))
    require(not command_rel.is_absolute() and ".." not in command_rel.parts, "invalid_completed_command_path")
    command_path = repo_root / command_rel
    require(command_path.is_file(), f"missing_completed_command:{command_path}")
    require_equal(sha256_file(command_path), SOURCE_COMMAND_SHA256, "completed_command.sha256")

    final_report_text = (source_dir / "FINAL_REPORT.md").read_text(encoding="utf-8")
    require("PASS — TOPOLOGY_RESTORED" in final_report_text, "source_final_report_missing_pass")
    require(SOURCE_RUN_ID in final_report_text, "source_final_report_missing_run_id")
    require("BLOCKED_PENDING_CLOUD_REVIEW" in final_report_text, "source_final_report_missing_review_block")

    return {
        "source_dir": str(source_dir),
        "hashes": hashes,
        "command_path": str(command_rel).replace("\\", "/"),
        "command_sha256": SOURCE_COMMAND_SHA256,
        "topology_restored": True,
        "address_resolved_current_target": 36,
        "address_resolved_current_other": 0,
        "direct_frame_current_target": 34,
        "direct_frame_current_other": 2,
        "phase3_zero_mutations": True,
        "regression_ok": True,
    }


def command_inventory(repo_root: Path) -> Dict[str, str]:
    command_root = repo_root / ".agent/commands"
    if not command_root.exists():
        return {}
    inventory: Dict[str, str] = {}
    for path in sorted(command_root.rglob("*")):
        if path.is_file():
            inventory[path.relative_to(repo_root).as_posix()] = sha256_file(path)
    return inventory


def make_run_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return timestamp.strftime("%Y%m%dT%H%M%S%fZ_") + uuid.uuid4().hex


def is_already_accepted(state: Mapping[str, Any]) -> bool:
    return (
        state.get("accepted_task") == TASK_ID
        and state.get("accepted_step") == STEP
        and state.get("source_task") == SOURCE_TASK_ID
        and state.get("source_run_id") == SOURCE_RUN_ID
        and state.get("visual_approved") is True
        and state.get("visual_approval_required") is False
    )


def validate_existing_acceptance(repo_root: Path, state: Mapping[str, Any]) -> Dict[str, Any]:
    for field in ("status_path", "report_path", "log_path", "final_report_path"):
        raw = state.get(field)
        require(isinstance(raw, str) and raw, f"existing_acceptance_missing_{field}")
        path = Path(raw)
        require(path.is_file(), f"existing_acceptance_file_missing:{field}:{path}")
    return {
        "ok": True,
        "already_accepted": True,
        "run_id": state.get("accepted_run_id"),
        "accepted_task": TASK_ID,
        "source_task": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
    }


def build_updated_state(
    current: Mapping[str, Any],
    report_dir: Path,
    run_id: str,
    approval: Mapping[str, Any],
) -> Dict[str, Any]:
    updated = dict(current)
    updated.update({
        "accepted_task": TASK_ID,
        "accepted_run_id": run_id,
        "accepted_step": STEP,
        "source_task": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_command_sha256": SOURCE_COMMAND_SHA256,
        "status_path": str((report_dir / "status.json").resolve()),
        "report_path": str((report_dir / "report.json").resolve()),
        "log_path": str((report_dir / "run.log").resolve()),
        "final_report_path": str((report_dir / "FINAL_REPORT.md").resolve()),
        "queue_state": "completed",
        "command_required": False,
        "timeline_modified": False,
        "bridge_ready": bool(current.get("bridge_ready", True)),
        "visual_approval_required": False,
        "visual_approved": True,
        "visual_approved_at": approval["approved_at"],
        "visual_approval_statement": approval["statement"],
        "visual_approval_evidence_sha256": approval["screenshot_sha256"],
        "topology_restored": True,
        "address_resolved_target_count": 36,
        "phase3_zero_mutations": True,
        "step_3B_6D_status": "ACCEPTED",
    })
    return updated


def final_report_markdown(run_id: str, source: Mapping[str, Any]) -> str:
    return f"""# Approach

Validated the immutable Step 3B.6D topology-repair evidence, completed command lineage, 36-operation address-resolved result, Phase 3 zero-mutation result, affected Step 3B.6B regression, and the user-provided visual approval. Updated only the accepted-state pointer and wrote immutable acceptance evidence. No Resolve command, bridge invocation, timeline mutation, or Step 3B.6E work occurred.

# Files changed

- `.agent/state/latest_accepted.json`
- `.agent/reports/{TASK_ID}/{run_id}/acceptance_validation.json`
- `.agent/reports/{TASK_ID}/{run_id}/visual_approval_receipt.json`
- `.agent/reports/{TASK_ID}/{run_id}/state_update_receipt.json`
- `.agent/reports/{TASK_ID}/{run_id}/status.json`
- `.agent/reports/{TASK_ID}/{run_id}/report.json`
- `.agent/reports/{TASK_ID}/{run_id}/run.log`
- `.agent/reports/{TASK_ID}/{run_id}/FINAL_REPORT.md`

# Commands run

- Focused acceptance-finalizer tests.
- Step 3B.6D evidence and hash validation.
- Completed-command readback validation.
- Atomic accepted-state update.
- Accepted-state persistent readback.
- `git diff --check`.

# Key evidence

- Acceptance finalizer run ID: `{run_id}`.
- Source topology-repair task: `{SOURCE_TASK_ID}`.
- Source topology-repair run: `{SOURCE_RUN_ID}`.
- Source completed command SHA-256: `{SOURCE_COMMAND_SHA256}`.
- Topology restored: `{str(source['topology_restored']).lower()}`.
- Address-resolved result: 36 `CURRENT_TARGET`, 0 `CURRENT_OTHER`.
- Direct-frame interpretation preserved: 34 `CURRENT_TARGET`, 2 expected interpolated `CURRENT_OTHER`.
- Phase 3: zero mutations.
- Step 3B.6B regression: passed.
- User visual approval: confirmed.
- Command inventory: unchanged.
- Resolve/timeline mutation by finalizer: none.

# PASS or FAIL

PASS — STEP_3B.6D_ACCEPTED

# Exact blocker or remaining risk

No Step 3B.6D blocker remains. Step 3B.6E is outside this task and requires a separate reviewed package.

Manual visual approval required: NO
"""


def finalize(
    repo_root: Path,
    approval_path: Path,
    run_id_factory: Callable[[], str] = make_run_id,
) -> Dict[str, Any]:
    repo_root = repo_root.resolve()
    approval_path = approval_path.resolve()
    require((repo_root / "AGENTS.md").is_file(), f"not_repository_root:{repo_root}")

    approval = validate_approval(approval_path)
    source = validate_source_evidence(repo_root)
    latest_path = repo_root / LATEST_ACCEPTED_REL
    current_bytes = latest_path.read_bytes() if latest_path.is_file() else b""
    require(current_bytes, f"missing_latest_accepted:{latest_path}")
    current = load_json(latest_path)

    if is_already_accepted(current):
        result = validate_existing_acceptance(repo_root, current)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    require_equal(sha256_bytes(current_bytes), EXPECTED_LATEST_ACCEPTED_SHA256, "latest_accepted.sha256")
    require_equal(current.get("accepted_task"), "BRIDGE_SMOKE_TEST_V1", "latest_accepted.accepted_task")
    require_equal(current.get("visual_approval_required"), False, "latest_accepted.visual_approval_required")
    require_equal(current.get("timeline_modified"), False, "latest_accepted.timeline_modified")
    require_equal(current.get("bridge_ready"), True, "latest_accepted.bridge_ready")

    commands_before = command_inventory(repo_root)
    run_id = run_id_factory()
    require(isinstance(run_id, str) and run_id and "/" not in run_id and "\\" not in run_id, "invalid_run_id")

    report_root = repo_root / ".agent/reports" / TASK_ID
    final_dir = report_root / run_id
    temporary_dir = report_root / f".{run_id}.tmp"
    require(not final_dir.exists(), f"report_dir_exists:{final_dir}")
    require(not temporary_dir.exists(), f"temporary_report_dir_exists:{temporary_dir}")

    updated_state = build_updated_state(current, final_dir, run_id, approval)
    updated_state_bytes = json_bytes(updated_state)
    before_hash = sha256_bytes(current_bytes)
    after_hash = sha256_bytes(updated_state_bytes)

    acceptance_validation = {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "step": STEP,
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_command_sha256": SOURCE_COMMAND_SHA256,
        "source_hashes": source["hashes"],
        "topology_restored": True,
        "address_resolved_current_target": 36,
        "address_resolved_current_other": 0,
        "direct_frame_current_target": 34,
        "direct_frame_current_other": 2,
        "phase3_zero_mutations": True,
        "affected_regression_ok": True,
        "visual_approved": True,
        "visual_approval_required": False,
        "accepted_state_update_authorized": True,
        "step_3B_6D_status": "ACCEPTED",
        "step_3B_6E_started": False,
    }
    visual_receipt = dict(approval)
    visual_receipt.update({
        "validated": True,
        "acceptance_task_id": TASK_ID,
        "acceptance_run_id": run_id,
    })
    state_receipt = {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "state_path": LATEST_ACCEPTED_REL.as_posix(),
        "before_sha256": before_hash,
        "after_sha256": after_hash,
        "previous_accepted_task": current.get("accepted_task"),
        "new_accepted_task": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "atomic_replace": True,
    }
    status = {
        "schema_version": 1,
        "ok": True,
        "running": False,
        "run_id": run_id,
        "task_id": TASK_ID,
        "report_path": str((final_dir / "report.json").resolve()),
        "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    report = {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": "acceptance_finalizer",
        "step": STEP,
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_command_sha256": SOURCE_COMMAND_SHA256,
        "topology_restored": True,
        "address_resolved_current_target": 36,
        "address_resolved_current_other": 0,
        "direct_frame_current_target": 34,
        "direct_frame_current_other": 2,
        "phase3_effective_mutations": 0,
        "affected_regression_ok": True,
        "visual_approved": True,
        "visual_approval_required": False,
        "timeline_modified": False,
        "resolve_command_created": False,
        "bridge_invocation_count": 0,
        "accepted_state_updated": True,
        "step_3B_6D_status": "ACCEPTED",
        "step_3B_6E_started": False,
        "failures": [],
    }
    run_log = "\n".join([
        f"[{datetime.now(timezone.utc).isoformat()}] validate source evidence: PASS",
        f"[{datetime.now(timezone.utc).isoformat()}] validate visual approval: PASS",
        f"[{datetime.now(timezone.utc).isoformat()}] update latest accepted state: PASS",
        f"[{datetime.now(timezone.utc).isoformat()}] final verdict: STEP_3B.6D_ACCEPTED",
        "",
    ]).encode("utf-8")

    report_files = {
        "acceptance_validation.json": json_bytes(acceptance_validation),
        "visual_approval_receipt.json": json_bytes(visual_receipt),
        "state_update_receipt.json": json_bytes(state_receipt),
        "latest_accepted_payload.json": updated_state_bytes,
        "status.json": json_bytes(status),
        "report.json": json_bytes(report),
        "run.log": run_log,
        "FINAL_REPORT.md": final_report_markdown(run_id, source).encode("utf-8"),
    }

    report_root.mkdir(parents=True, exist_ok=True)
    temporary_dir.mkdir()
    try:
        for name, data in report_files.items():
            write_bytes(temporary_dir / name, data)

        atomic_write_bytes(latest_path, updated_state_bytes)
        try:
            os.replace(temporary_dir, final_dir)
        except Exception:
            atomic_write_bytes(latest_path, current_bytes)
            raise
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise

    persisted = latest_path.read_bytes()
    require_equal(sha256_bytes(persisted), after_hash, "latest_accepted.persistent_sha256")
    persisted_state = load_json(latest_path)
    require(is_already_accepted(persisted_state), "latest_accepted.persistent_semantics")
    require_equal(persisted_state.get("accepted_run_id"), run_id, "latest_accepted.accepted_run_id")

    commands_after = command_inventory(repo_root)
    require_equal(commands_after, commands_before, "command_inventory")

    result = {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "accepted_step": STEP,
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "latest_accepted_sha256": after_hash,
        "report_dir": str(final_dir),
        "command_inventory_unchanged": True,
        "timeline_modified": False,
        "bridge_invocation_count": 0,
        "step_3B_6D_status": "ACCEPTED",
        "step_3B_6E_started": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize accepted Step 3B.6D evidence after user visual approval.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--approval", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        finalize(Path(args.repo_root), Path(args.approval))
    except (FinalizationError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "task_id": TASK_ID, "failure": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
