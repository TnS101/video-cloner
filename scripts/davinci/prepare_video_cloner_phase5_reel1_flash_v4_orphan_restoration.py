"""Queue one immutable in-place Reel #1 flash restoration command."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "VIDEO_CLONER_PHASE5_REEL1_RELINKED_FLASH_INPLACE_RESTORATION_V1"
MODE = "phase5_reel1_relinked_flash_inplace_restoration"
TARGET = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4_flash_transition_v4"
SOURCE_TARGET = "DZsqH7auhjt_standalone_timeline"
EXPECTED_CUTS = (96, 377, 426, 454, 758)
EXPECTED_SPANS = ((94, 98), (375, 379), (424, 428), (452, 456), (756, 760))
PLAN_SHA256 = "39FCD4B29289632B110716843EF37E5208D5CBEEB2B03EA64EBE587C57B31443"
PLAN_SEMANTIC_SHA256 = "c619335b631927b8652a5b390cf000dae4f213b84db6062136cee709cf2659db"
PREREQUISITE_SHA256 = "F73798C65BF9A38705464CCE9E8960410BBA8F72B554C3E951F112E781F2024D"
DEFAULT_PREREQUISITE = Path(".agent/reports/VIDEO_CLONER_PHASE5_PHASE4C1_POST_ROLLBACK_SIGNATURE_AND_SHARED_MEDIA_READONLY_PROBE_V1/20260907T150600040Z_8328449dd6ef40b0acbcfd61e4862cf3/report.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load(root: Path, name: str, relative: str):
    path = root / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base(root: Path):
    return _load(root, "vc_prepare_inplace_base", "resolve_workspace/modules/video_cloner_phase4c1_flash_v4_integration.py")


def normalize_plan(root: Path, plan: dict) -> dict:
    """Convert the immutable accepted Reel #1 schema-v1 plan through the canonical builder."""
    base = _base(root)
    identity = (plan.get("schema"), plan.get("schema_version"), plan.get("task_id"), plan.get("project_name"), plan.get("target_timeline_name"))
    if identity != ("video_cloner.phase4c1_flash_v4_plan", 1, base.TASK_ID, base.PROJECT_NAME, SOURCE_TARGET):
        raise ValueError("reel1_plan_identity")
    rows = plan.get("flashes")
    geometry = [(row.get("cut_frame"), row.get("start_frame"), row.get("start_frame", -1) + row.get("duration_frames", -1)) for row in rows] if isinstance(rows, list) else []
    if geometry != [(cut, start, end) for cut, (start, end) in zip(EXPECTED_CUTS, EXPECTED_SPANS)]:
        raise ValueError("reel1_plan_geometry")
    unhashed = dict(plan)
    semantic_hash = unhashed.pop("plan_sha256", None)
    if semantic_hash != PLAN_SEMANTIC_SHA256 or base.V1.canonical_sha256(unhashed) != PLAN_SEMANTIC_SHA256:
        raise ValueError("reel1_plan_authority_hash")
    planner = _load(root, "vc_prepare_inplace_planner", "scripts/davinci/prepare_video_cloner_phase4c1_flash_v4_integration.py")
    normalized = planner.build_plan({"transitions": rows}, base.PROJECT_NAME, TARGET)
    base.validate_plan(normalized)
    return normalized


def run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--prerequisite-report", type=Path, default=DEFAULT_PREREQUISITE)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = args.root.resolve()
    plan_path = args.plan.resolve()
    prerequisite_path = args.prerequisite_report if args.prerequisite_report.is_absolute() else root / args.prerequisite_report
    prerequisite_path = prerequisite_path.resolve()
    if _sha256(plan_path) != PLAN_SHA256:
        raise SystemExit("FAIL: accepted plan file hash mismatch")
    plan = normalize_plan(root, json.loads(plan_path.read_text(encoding="utf-8-sig")))
    if root not in prerequisite_path.parents or _sha256(prerequisite_path) != PREREQUISITE_SHA256:
        raise SystemExit("FAIL: prerequisite report path or hash mismatch")
    prerequisite = json.loads(prerequisite_path.read_text(encoding="utf-8-sig"))
    if prerequisite.get("ok") is not True or prerequisite.get("read_only") is not True or prerequisite.get("read_determinism_classification") != "TIMELINE_SIGNATURES_STABLE_TWO_PASS" or prerequisite.get("signature_mismatches"):
        raise SystemExit("FAIL: prerequisite report contract mismatch")
    rid = args.run_id or run_id()
    report = f".agent/reports/{TASK_ID}/{rid}"
    command = {
        "schema_version": 1,
        "task": TASK_ID,
        "run_id": rid,
        "module": "resolve_workspace/modules/video_cloner_phase5_reel1_flash_v4_orphan_restoration.py",
        "mode": MODE,
        "status_path": f"{report}/status.json",
        "log_path": f"{report}/run.log",
        "report_path": f"{report}/report.json",
        "payload": {
            "repository_root": str(root),
            "expected_project": "New Project 1",
            "target_timeline_name": TARGET,
            "accepted_plan": plan,
            "accepted_plan_file_sha256": PLAN_SHA256,
            "prerequisite_report": {"path": prerequisite_path.relative_to(root).as_posix(), "sha256": PREREQUISITE_SHA256},
            "read_only": False,
        },
    }
    command_root = root / ".agent/commands"
    if any(any((command_root / state).glob("*.json")) for state in ("pending", "running")):
        raise SystemExit("FAIL: active command exists")
    queue = command_root / "pending"
    queue.mkdir(parents=True, exist_ok=True)
    out = queue / f"{TASK_ID}_{rid}.json"
    report_dir = root / report
    report_dir.mkdir(parents=True, exist_ok=False)
    encoded = json.dumps(command, indent=2, sort_keys=True) + "\n"
    out.write_text(encoded, encoding="utf-8")
    (report_dir / "command.json").write_text(encoded, encoding="utf-8")
    print(json.dumps({"ok": True, "run_id": rid, "command_path": out.relative_to(root).as_posix()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
