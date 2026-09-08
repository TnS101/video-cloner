from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "davinci" / "finalize_step_3B_6D_acceptance.py"
spec = importlib.util.spec_from_file_location("acceptance_finalizer", SCRIPT_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def approval_payload() -> Dict[str, Any]:
    value = dict(module.EXPECTED_APPROVAL)
    value["checklist_confirmed"] = [
        "sub_013 / out inspected",
        "Center keys only at Fusion times 0, 1, 3, and 4",
        "Size keys only at Fusion times 0, 1, 3, and 4",
        "No spike or discontinuity around timeline frame 226",
        "Reference position and scale accepted",
        "Motion continuity accepted",
        "sub_007, sub_110, and sub_114 spot-checks accepted",
    ]
    return value


def source_payloads() -> Dict[str, Any]:
    source_run = module.SOURCE_RUN_ID
    source_task = module.SOURCE_TASK_ID
    command_hash = module.SOURCE_COMMAND_SHA256
    topology = {
        "ok": True,
        "v3_candidate_count": 116,
        "deleted_keys": [
            {"cue_id": "sub_013", "property": "Center", "time": 2.0},
            {"cue_id": "sub_013", "property": "Size", "time": 2.0},
        ],
        "actual_after": {
            "sub_013": {
                "Center": {"raw_keyframe_structure": {"1": 0.0, "2": 1.0, "3": 3.0, "4": 4.0}},
                "Size": {"raw_keyframe_structure": {"1": 0.0, "2": 1.0, "3": 3.0, "4": 4.0}},
            }
        },
    }
    address_operations = [
        {
            "addressing": "capture_raw_key_identity" if index in (5, 10) else "direct_clip_local_frame",
            "classification": "CURRENT_TARGET",
            "cue_id": "sub_013" if index in (5, 10) else "protected",
            "property": "Center" if index == 5 else ("Size" if index == 10 else "Center"),
            "raw_key_identifier": 2 if index in (5, 10) else None,
            "raw_time": 1.0 if index in (5, 10) else None,
        }
        for index in range(36)
    ]
    direct_operations = [
        {
            "classification": "CURRENT_OTHER" if index in (5, 10) else "CURRENT_TARGET",
            "cue_id": "sub_013" if index in (5, 10) else "protected",
            "property": "Center" if index == 5 else ("Size" if index == 10 else "Center"),
            "local_frame": 2 if index in (5, 10) else 0,
            "timeline_frame": 226 if index in (5, 10) else index,
        }
        for index in range(36)
    ]
    return {
        "status.json": {"ok": True, "running": False, "run_id": source_run},
        "report.json": {
            "ok": True,
            "task_id": source_task,
            "run_id": source_run,
            "topology_restored": True,
            "accepted_state_unchanged": True,
            "address_resolved_current_target": 36,
            "address_resolved_current_other": 0,
            "direct_frame_current_target": 34,
            "direct_frame_current_other": 2,
            "key_delete_call_count": 2,
            "value_setter_call_count": 0,
            "modifier_mutation_call_count": 0,
            "save_call_count": 0,
            "manual_visual_approval_required": True,
            "step_3B_6D_acceptance_status": "BLOCKED_PENDING_CLOUD_REVIEW",
        },
        "topology_repair_validation.json": {
            "ok": True,
            "task_id": source_task,
            "run_id": source_run,
            "topology_restored": True,
            "lifecycle": ["pending", "running", "completed"],
            "key_delete_call_count": 2,
            "value_setter_call_count": 0,
            "command_sha256": command_hash,
            "command_path": f".agent/commands/completed/{source_task}_{source_run}.json",
            "address_resolved_result": {"current_other": 0, "current_target": 36},
            "direct_frame_result": {"current_other": 2, "current_target": 34},
        },
        "address_resolved_operation_comparison.json": {
            "operation_count": 36,
            "current_target": 36,
            "current_other": 0,
            "missing": 0,
            "ambiguous": 0,
            "blend": 0,
            "operations": address_operations,
        },
        "direct_frame_state_comparison.json": {
            "operation_count": 36,
            "current_target": 34,
            "current_other": 2,
            "missing": 0,
            "ambiguous": 0,
            "blend": 0,
            "operations": direct_operations,
        },
        "key_deletion_journal.json": [
            {"cue_id": "sub_013", "property": "Center", "deleted_time": 2.0, "ok": True, "retained_values_unchanged": True},
            {"cue_id": "sub_013", "property": "Size", "deleted_time": 2.0, "ok": True, "retained_values_unchanged": True},
        ],
        "topology_preservation_audit.json": topology,
        "protected_state_audit.json": {
            "ok": True,
            "protected_operation_count": 34,
            "protected_values_unchanged": True,
            "non_target_write_count": 0,
            "key_delete_call_count": 2,
            "value_setter_call_count": 0,
            "modifier_mutation_call_count": 0,
            "blend_operation_count": 0,
        },
        "phase3_idempotency_report.json": {
            "ok": True,
            "structural_topology_restored": True,
            "timeline_modified": False,
            "address_resolved_current_target": 36,
            "address_resolved_current_other": 0,
            "effective_mutations": 0,
            "key_delete_calls": 0,
            "modifier_mutations": 0,
            "blend_operations": 0,
            "value_setter_calls": 0,
        },
        "affected_regression_report.json": {
            "ok": True,
            "step": "Major Step 3B.6B",
            "failures": [],
            "summary": {"v3_item_count": 116},
        },
        "lifecycle_runtime_observation.json": {
            "task_id": source_task,
            "run_id": source_run,
            "running_observed": True,
            "running_command_sha256": command_hash,
        },
        "publication_receipt.json": {
            "task_id": source_task,
            "run_id": source_run,
            "pending_observed": True,
            "command_sha256": command_hash,
        },
        "FINAL_REPORT.md": f"PASS — TOPOLOGY_RESTORED\n{source_run}\nBLOCKED_PENDING_CLOUD_REVIEW\n",
        "run.log": "PASS\n",
        "topology_repair_command.json": {"task_id": source_task, "run_id": source_run},
        "topology_repair_post_state.json": {},
        "topology_repair_pre_state.json": {},
    }


def make_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "AGENTS.md").parent.mkdir(parents=True)
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    latest = {
        "accepted_task": "BRIDGE_SMOKE_TEST_V1",
        "accepted_run_id": "bridge-run",
        "resolve_version": "21.0.1.11",
        "canonical_launcher_path": "launcher",
        "repository_bridge_path": "bridge",
        "status_path": "old-status",
        "report_path": "old-report",
        "log_path": "old-log",
        "final_report_path": "old-final",
        "queue_state": "completed",
        "timeline_modified": False,
        "bridge_ready": True,
        "visual_approval_required": False,
    }
    latest_path = root / module.LATEST_ACCEPTED_REL
    write_json(latest_path, latest)
    monkeypatch.setattr(module, "EXPECTED_LATEST_ACCEPTED_SHA256", module.sha256_file(latest_path))

    source_dir = root / module.SOURCE_REPORT_REL
    payloads = source_payloads()
    for name, payload in payloads.items():
        path = source_dir / name
        if isinstance(payload, str):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        else:
            write_json(path, payload)

    command_path = root / f".agent/commands/completed/{module.SOURCE_TASK_ID}_{module.SOURCE_RUN_ID}.json"
    command_path.parent.mkdir(parents=True, exist_ok=True)
    command_path.write_bytes((source_dir / "topology_repair_command.json").read_bytes())
    command_hash = module.sha256_file(command_path)
    monkeypatch.setattr(module, "SOURCE_COMMAND_SHA256", command_hash)
    validation = json.loads((source_dir / "topology_repair_validation.json").read_text(encoding="utf-8"))
    validation["command_sha256"] = command_hash
    write_json(source_dir / "topology_repair_validation.json", validation)
    lifecycle = json.loads((source_dir / "lifecycle_runtime_observation.json").read_text(encoding="utf-8"))
    lifecycle["running_command_sha256"] = command_hash
    write_json(source_dir / "lifecycle_runtime_observation.json", lifecycle)
    publication = json.loads((source_dir / "publication_receipt.json").read_text(encoding="utf-8"))
    publication["command_sha256"] = command_hash
    write_json(source_dir / "publication_receipt.json", publication)

    expected_hashes = {name: module.sha256_file(source_dir / name) for name in payloads}
    monkeypatch.setattr(module, "EXPECTED_SOURCE_HASHES", expected_hashes)

    approval_path = tmp_path / "approval.json"
    write_json(approval_path, approval_payload())
    return root, approval_path


def test_success_updates_only_state_and_acceptance_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, approval = make_repo(tmp_path, monkeypatch)
    before_commands = module.command_inventory(root)
    result = module.finalize(root, approval, run_id_factory=lambda: "20260803T100000000000Z_test")

    assert result["ok"] is True
    assert result["step_3B_6D_status"] == "ACCEPTED"
    state = json.loads((root / module.LATEST_ACCEPTED_REL).read_text(encoding="utf-8"))
    assert state["accepted_task"] == module.TASK_ID
    assert state["accepted_step"] == module.STEP
    assert state["source_run_id"] == module.SOURCE_RUN_ID
    assert state["visual_approved"] is True
    assert state["visual_approval_required"] is False
    assert state["timeline_modified"] is False
    report_dir = root / ".agent/reports" / module.TASK_ID / result["run_id"]
    assert (report_dir / "FINAL_REPORT.md").is_file()
    assert (report_dir / "acceptance_validation.json").is_file()
    assert module.command_inventory(root) == before_commands


def test_source_hash_mismatch_stops_without_state_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, approval = make_repo(tmp_path, monkeypatch)
    latest_path = root / module.LATEST_ACCEPTED_REL
    before = latest_path.read_bytes()
    (root / module.SOURCE_REPORT_REL / "report.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(module.FinalizationError, match="sha256.report.json"):
        module.finalize(root, approval, run_id_factory=lambda: "never")

    assert latest_path.read_bytes() == before
    assert not (root / ".agent/reports" / module.TASK_ID).exists()


def test_source_semantic_mismatch_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, approval = make_repo(tmp_path, monkeypatch)
    report_path = root / module.SOURCE_REPORT_REL / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["address_resolved_current_target"] = 35
    write_json(report_path, report)
    hashes = dict(module.EXPECTED_SOURCE_HASHES)
    hashes["report.json"] = module.sha256_file(report_path)
    monkeypatch.setattr(module, "EXPECTED_SOURCE_HASHES", hashes)

    with pytest.raises(module.FinalizationError, match="report.address_resolved_current_target"):
        module.finalize(root, approval, run_id_factory=lambda: "never")


def test_visual_approval_mismatch_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, approval = make_repo(tmp_path, monkeypatch)
    payload = json.loads(approval.read_text(encoding="utf-8"))
    payload["approved"] = False
    write_json(approval, payload)

    with pytest.raises(module.FinalizationError, match="approval.approved"):
        module.finalize(root, approval, run_id_factory=lambda: "never")


def test_latest_accepted_drift_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, approval = make_repo(tmp_path, monkeypatch)
    state_path = root / module.LATEST_ACCEPTED_REL
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["unexpected"] = True
    write_json(state_path, state)

    with pytest.raises(module.FinalizationError, match="latest_accepted.sha256"):
        module.finalize(root, approval, run_id_factory=lambda: "never")


def test_already_accepted_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, approval = make_repo(tmp_path, monkeypatch)
    first = module.finalize(root, approval, run_id_factory=lambda: "20260803T100000000000Z_test")
    second = module.finalize(root, approval, run_id_factory=lambda: "must-not-run")
    assert second["already_accepted"] is True
    assert second["run_id"] == first["run_id"]
    report_dirs = list((root / ".agent/reports" / module.TASK_ID).iterdir())
    assert len(report_dirs) == 1
