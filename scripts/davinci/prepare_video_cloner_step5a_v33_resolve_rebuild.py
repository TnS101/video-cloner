from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analysis.compile_step5a_v33_materialization import BASELINE, build_artifacts, digest, write_contact_sheet


TASK_ID = "VIDEO_CLONER_STEP5A_V33_BOUNDED_MATERIALIZATION_CLEANUP_V1"
MODE = "apply_v33_bounded_cleanup_caption_and_generated_only_timelines"
MODULE = "resolve_workspace/modules/video_cloner_step5a_v33_resolve_rebuild.py"
REPORT_ROOT = ROOT / ".agent/reports/VIDEO_CLONER_STEP5A_V33_BOUNDED_MATERIALIZATION_CLEANUP_V1"


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def active_commands() -> list[Path]:
    return [path for state in ("pending", "running") for path in (ROOT / ".agent/commands" / state).glob("*.json")]


def publish(now: dt.datetime | None = None) -> dict[str, Any]:
    active = active_commands()
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    first, second = build_artifacts(), build_artifacts()
    run_1_hash, run_2_hash = digest(first["manifest"]), digest(second["manifest"])
    if run_1_hash != run_2_hash or first != second:
        raise ValueError("materialization_nondeterministic")
    now = now or dt.datetime.now(dt.timezone.utc)
    unique = uuid.uuid4().hex
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + unique
    report_dir = REPORT_ROOT / run_id
    applied = "VIDEO_CLONER_STEP5A_V33_BOUNDED_CLEANUP_APPLIED_" + unique[:12]
    review = "VIDEO_CLONER_STEP5B_V33_BOUNDED_CLEANUP_GENERATED_ONLY_" + unique[:12]
    first["manifest"]["applied_timeline"] = applied
    first["manifest"]["generated_only_timeline"] = review
    second["manifest"]["applied_timeline"] = applied
    second["manifest"]["generated_only_timeline"] = review
    run_1_hash, run_2_hash = digest(first["manifest"]), digest(second["manifest"])
    determinism = {"schema": "video_cloner_v33_materialization_determinism_report_v1", "run_1_manifest_hash": run_1_hash, "run_2_manifest_hash": run_2_hash, "identical": run_1_hash == run_2_hash and first == second}
    if not determinism["identical"]:
        raise ValueError("materialization_nondeterministic_after_naming")
    artifacts = {
        "materialization_manifest_v33.json": first["manifest"],
        "render_object_reconciliation.json": first["reconciliation"],
        "bounded_materialization_cleanup_audit.json": first["cleanup"],
        "materialization_authority_audit.json": first["authority"],
        "materialization_completeness_audit.json": first["completeness"],
        "track_lane_collision_audit.json": first["collisions"],
        "materialization_regression_controls.json": first["regression"],
        "local_framewise_visual_sanity.json": first["local_visual_sanity"],
        "materialization_determinism_report.json": determinism,
        "protected_timeline_guard.json": first["protected_guard"],
        "generated_only_equivalence_plan.json": first["equivalence"],
        "resolve_task_payload_preview.json": {**first["payload_preview"], "applied_timeline": applied, "generated_only_timeline": review},
        "plan_state_update.json": first["plan"],
    }
    for name, value in artifacts.items():
        write(report_dir / name, value)
    write_contact_sheet(report_dir / "local_overlap_contact_sheet.png", first["local_visual_sanity"])
    manifest_path = report_dir / "materialization_manifest_v33.json"
    command = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "module": MODULE,
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "status_path": str((report_dir / "status.json").relative_to(ROOT)),
        "log_path": str((report_dir / "run.log").relative_to(ROOT)),
        "report_path": str((report_dir / "bridge_report.json").relative_to(ROOT)),
        "payload": {
            "report_dir": str(report_dir), "manifest_path": str(manifest_path), "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "baseline_fcpxml": str(BASELINE), "baseline_fcpxml_sha256": first["manifest"]["baseline_fcpxml"]["sha256"],
            "applied_timeline": applied, "generated_only_timeline": review,
        },
    }
    command_path = ROOT / ".agent/commands/pending" / f"{TASK_ID}_{run_id}.json"
    if active_commands():
        raise ValueError("queue_changed_before_publication")
    write(report_dir / "command.json", command)
    write(command_path, command)
    receipt = {"task_id": TASK_ID, "run_id": run_id, "command_path": str(command_path), "report_dir": str(report_dir), "applied_timeline": applied, "generated_only_timeline": review, "module": MODULE, "mode": MODE, "expected_objects": first["manifest"]["object_count"], "manifest_hash": run_1_hash}
    write(report_dir / "publication_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
