#!/usr/bin/env python3
"""Read-only evidence-lineage investigator for the Step 3B.6C geometry probe."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.davinci import validate_caption_source_geometry_probe_evidence_step_3B_6 as gate
except ModuleNotFoundError:  # Direct script execution places this directory on sys.path.
    import validate_caption_source_geometry_probe_evidence_step_3B_6 as gate

VIDEO_ID = "DZsqH7auhjt"
STEP = "Major Step 3B.6C"
PROBE_CUE = "sub_114"
PROBE_TEXT = "AND"
PROBE_RANGE = (888, 894)
CLASSIFICATIONS = {
    "A": "CLASS A — PATH/RESOLUTION DEFECT",
    "B": "CLASS B — SCHEMA/COMPATIBILITY DEFECT",
    "C": "CLASS C — INVALID OR INCONSISTENT EVIDENCE",
    "D": "CLASS D — EVIDENCE NEVER PERSISTED",
    "E": "CLASS E — CURRENT TIMELINE STATE CANNOT BE TRUSTED",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def json_candidates(roots: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.json"):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved


def relevant(path: Path, payload: dict[str, Any], plan_hash: str) -> bool:
    name = path.as_posix().lower()
    step = str(payload.get("step") or "")
    cue = str(payload.get("probe_cue_id") or (payload.get("probe") or {}).get("cue_id") or "")
    return (
        "3b_6c" in name
        or "3b.6c" in step.lower()
        or (payload.get("plan_hash") == plan_hash and cue == PROBE_CUE)
    )


def artifact_row(path: Path, root: Path, payload: dict[str, Any] | None, error: str | None = None) -> dict[str, Any]:
    summary = payload.get("summary") if payload and isinstance(payload.get("summary"), dict) else {}
    probe = payload.get("probe") if payload and isinstance(payload.get("probe"), dict) else {}
    return {
        "path": relative(path, root),
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "json_valid": payload is not None,
        "json_error": error,
        "task_id": (payload or {}).get("task_id", (payload or {}).get("task")),
        "run_id": (payload or {}).get("run_id"),
        "step": (payload or {}).get("step"),
        "schema": (payload or {}).get("schema"),
        "run_mode": (payload or {}).get("run_mode"),
        "mode": (payload or {}).get("mode"),
        "plan_hash": (payload or {}).get("plan_hash"),
        "cue_id": (payload or {}).get("probe_cue_id", probe.get("cue_id")),
        "cue_text": (payload or {}).get("probe_text", probe.get("text")),
        "frame_range": [probe.get("start_frame"), probe.get("end_frame")] if probe else None,
        "project_name": (payload or {}).get("project_name"),
        "timeline_name": (payload or {}).get("timeline_name"),
        "ok": (payload or {}).get("ok"),
        "modified_count": summary.get("modified_count"),
        "already_correct_count": summary.get("already_correct_count"),
    }


def read_workspace_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.is_file():
        return events
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append({"line": number, **value})
    return events


def inspect(repository_root: Path, gate_output: Path, output_dir: Path) -> dict[str, Any]:
    root = repository_root.resolve()
    plan_path = root / "data" / VIDEO_ID / "analysis" / f"{VIDEO_ID}_caption_source_geometry_probe_plan_step_3B_6C.json"
    davinci = root / "data" / VIDEO_ID / "davinci"
    first_report = davinci / f"{VIDEO_ID}_resolve_source_geometry_step_3B_6C_first_application_report.json"
    first_validation = davinci / f"{VIDEO_ID}_resolve_source_geometry_step_3B_6C_first_application_validation.json"
    idempotency_report = davinci / f"{VIDEO_ID}_resolve_source_geometry_step_3B_6C_idempotency_report.json"
    idempotency_validation = davinci / f"{VIDEO_ID}_resolve_source_geometry_step_3B_6C_idempotency_validation.json"
    workspace_log = davinci / f"{VIDEO_ID}_resolve_source_geometry_step_3B_6C_workspace.log"

    plan = load_json(plan_path)
    plan_hash = gate.canonical_hash(plan, ignored=("created_at_unix",))
    rows: list[dict[str, Any]] = []
    payloads: dict[Path, dict[str, Any]] = {}
    invalid: list[str] = []
    search_roots = [root / "data" / VIDEO_ID, root / ".agent" / "reports", root / ".agent" / "commands", root / ".agent" / "state"]
    for path in json_candidates(search_roots):
        try:
            payload = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if "3B_6C" in path.name or "3b_6c" in path.name.lower():
                rows.append(artifact_row(path, root, None, f"{type(exc).__name__}: {exc}"))
                invalid.append(relative(path, root))
            continue
        if relevant(path, payload, plan_hash):
            payloads[path] = payload
            rows.append(artifact_row(path, root, payload))

    gate_reproduction = gate.assess(plan_path, first_report, first_validation, idempotency_report, idempotency_validation)
    gate_reproduction["source_gate_output"] = relative(gate_output, root)
    if gate_output.is_file():
        gate_reproduction["source_gate_output_sha256"] = sha256(gate_output)

    second_reports = [
        (path, value) for path, value in payloads.items()
        if value.get("step") == STEP and value.get("run_mode") == "idempotent_second_run"
    ]
    second_validations = [
        (path, value) for path, value in payloads.items()
        if value.get("step") == STEP and value.get("mode") == "idempotent_second_run"
    ]
    valid_second_reports = [
        (path, value) for path, value in second_reports
        if value.get("ok") is True
        and value.get("plan_hash") == plan_hash
        and value.get("probe_cue_id") == PROBE_CUE
        and int((value.get("summary") or {}).get("modified_count", -1)) == 0
        and int((value.get("summary") or {}).get("already_correct_count") or 0) == 1
    ]
    valid_second_validations = [
        (path, value) for path, value in second_validations
        if value.get("ok") is True and not value.get("failures")
    ]
    canonical_pair_exists = idempotency_report.is_file() and idempotency_validation.is_file()
    events = read_workspace_events(workspace_log)
    finished = [event for event in events if event.get("event") == "workspace_finished"]
    finished_second = [event for event in finished if event.get("run_mode") == "idempotent_second_run"]

    classification: str | None = None
    support: list[str] = []
    if not second_reports and not second_validations and not finished_second and not canonical_pair_exists:
        classification = "D"
        support = [
            "canonical idempotency report is absent",
            "canonical idempotency validation is absent",
            "no semantic second-pass report or validation candidate was discovered",
            "workspace lineage contains no idempotent_second_run completion",
        ]
    elif second_reports or second_validations:
        if not valid_second_reports or not valid_second_validations:
            classification = "C"
            support = ["second-pass candidates exist but do not satisfy identity, status, binding, or no-effective-mutation requirements"]
        elif not canonical_pair_exists:
            classification = "A"
            support = ["valid semantic second-pass evidence exists outside the canonical gate paths"]
        elif not gate_reproduction.get("accepted"):
            classification = "B"
            support = ["canonical valid evidence exists but the current gate rejects its schema"]
    elif canonical_pair_exists and not gate_reproduction.get("accepted"):
        classification = "C"
        support = ["canonical artifacts exist but fail the semantic evidence gate"]

    proven = classification in CLASSIFICATIONS and not invalid
    first_payload = load_json(first_report) if first_report.is_file() else {}
    first_probe = plan.get("probe") if isinstance(plan.get("probe"), dict) else {}
    identity = {
        "video_id": VIDEO_ID,
        "cue_id": first_payload.get("probe_cue_id"),
        "cue_text": first_payload.get("probe_text"),
        "frame_range": [first_probe.get("start_frame"), first_probe.get("end_frame")],
        "project_name": first_payload.get("project_name"),
        "timeline_name": first_payload.get("timeline_name"),
        "item_name": first_payload.get("probe_name"),
        "plan_hash": plan_hash,
        "first_run_id": first_payload.get("run_id"),
    }

    inventory = {"ok": proven, "repository_root": str(root), "search_roots": [relative(path, root) for path in search_roots], "artifacts": sorted(rows, key=lambda row: row["path"]), "invalid_artifacts": invalid}
    lineage = {
        "ok": proven,
        "plan": {"path": relative(plan_path, root), "hash": plan_hash},
        "identity": identity,
        "workspace_events": events,
        "first_pass": {"report": relative(first_report, root), "validation": relative(first_validation, root)},
        "second_pass": {"reports": [relative(path, root) for path, _ in second_reports], "valid_reports": [relative(path, root) for path, _ in valid_second_reports], "validations": [relative(path, root) for path, _ in second_validations], "valid_validations": [relative(path, root) for path, _ in valid_second_validations]},
        "accepted_state": relative(root / ".agent" / "state" / "latest_accepted.json", root),
        "queue_candidates": [row["path"] for row in rows if row["path"].startswith(".agent/commands/")],
    }
    report_payload = load_json(first_report) if first_report.is_file() else {}
    validation_payload = load_json(first_validation) if first_validation.is_file() else {}
    schema = {
        "ok": proven,
        "gate_required_report_fields": ["ok", "run_mode", "plan_hash", "failures", "probe_cue_id", "summary.modified_count", "summary.already_correct_count", "track_integrity.ok", "v3_track_integrity.ok"],
        "gate_required_validation_fields": ["ok", "validator_version", "mode", "failures", "checks", "plan", "report"],
        "first_report_fields": sorted(report_payload),
        "first_validation_fields": sorted(validation_payload),
        "exact_failed_predicates": (gate_reproduction.get("first_application") or {}).get("failures", []) + (gate_reproduction.get("idempotency") or {}).get("failures", []),
        "compatibility_adapter_safe": classification in ("A", "B"),
    }
    assessment = {
        "ok": proven,
        "selected_classification": CLASSIFICATIONS.get(classification),
        "classification_code": classification,
        "evidence": support,
        "historical_idempotency_claim_substantiated": bool(valid_second_reports and valid_second_validations and finished_second),
        "existing_evidence_reusable": classification in ("A", "B"),
        "resolve_evidence_regeneration_required": classification == "D",
        "effective_geometry_mutation_required": False if classification == "D" else None,
        "blend_shared_root_cause": False,
        "blend_next_boundary": "separate PATCH after evidence eligibility is restored",
        "identity": identity,
    }
    recommendation = {
        "ok": proven,
        "next_mode": "BUILD" if classification == "D" else "PATCH" if classification in ("A", "B") else "INVESTIGATE",
        "objective": "Generate immutable Step 3B.6C persistent readback and no-effective-change idempotency evidence for sub_114 without preparing Step 3B.6D." if classification == "D" else "Consume the proven immutable evidence without rewriting it.",
        "expected_files_changed": ["narrow Resolve readback module", "focused tests", "evidence validator wiring"] if classification == "D" else ["current evidence gate", "focused tests"],
        "runtime_boundary": "one bounded Resolve readback/no-op verification; stop on any state divergence; no Step 3B.6D plan or Blend correction" if classification == "D" else "no Resolve execution",
        "manual_boundary": "project New Project 1 and timeline DZsqH7auhjt_textplus_full must be open and identity-verified" if classification == "D" else "none",
        "remaining_risks": ["current timeline state has not been tied to a distinct historical second pass", "Blend remains a separate contained-rollout blocker"],
    }

    outputs = {
        "step_3B_6C_artifact_inventory.json": inventory,
        "step_3B_6C_evidence_lineage.json": lineage,
        "step_3B_6C_schema_comparison.json": schema,
        "step_3B_6C_gate_rejection_reproduction.json": gate_reproduction,
        "step_3B_6C_acceptance_assessment.json": assessment,
        "next_task_recommendation.json": recommendation,
    }
    for name, payload in outputs.items():
        write_json(output_dir.resolve() / name, payload)
    return {"ok": proven, "classification": CLASSIFICATIONS.get(classification), "outputs": sorted(outputs)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--gate-output", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args.repository_root, args.gate_output.resolve(), args.output_dir.resolve())
    except Exception as exc:
        result = {"ok": False, "classification": None, "exception": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
