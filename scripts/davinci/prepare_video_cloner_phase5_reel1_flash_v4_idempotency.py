"""Queue one immutable Reel #1 completed-Flash idempotency command."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "VIDEO_CLONER_PHASE5_REEL1_FLASH_IDEMPOTENCY_V1"
MODE = "phase5_reel1_flash_v4_idempotency"
DEFAULT_PLAN = Path(".agent/reports/VIDEO_CLONER_PHASE4C1_ACCEPTED_FLASH_V4_INTEGRATION/20260818T155057413Z_bc06f111358f4bf8916dc121111459c4/flash_plan.json")
DEFAULT_RESTORATION = Path(".agent/reports/VIDEO_CLONER_PHASE5_REEL1_RELINKED_FLASH_INPLACE_RESTORATION_V1/20260907T172351907Z_649b02fd98cd4e5d9c3f7868d62e53e4/report.json")
DEFAULT_PERSISTENCE = Path(".agent/reports/VIDEO_CLONER_PHASE5_PHASE4C1_POST_ROLLBACK_SIGNATURE_AND_SHARED_MEDIA_READONLY_PROBE_V1/20260907T174216080Z_d208b3dfd50349cbae0663348c34c1d9/report.json")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_command(root: Path, run_id: str, plan_path: Path, restoration_path: Path, persistence_path: Path) -> dict:
    prior = _load("vc_prepare_reel1_restore", root / "scripts/davinci/prepare_video_cloner_phase5_reel1_flash_v4_orphan_restoration.py")
    runtime = _load("vc_reel1_idempotency", root / "resolve_workspace/modules/video_cloner_phase5_reel1_flash_v4_idempotency.py")
    if prior._sha256(plan_path) != prior.PLAN_SHA256:
        raise ValueError("accepted_plan_file_hash")
    plan = prior.normalize_plan(root, json.loads(plan_path.read_text(encoding="utf-8-sig")))
    payload = {
        "repository_root": str(root), "expected_project": runtime.PROJECT_NAME,
        "target_timeline_name": runtime.TARGET_TIMELINE_NAME, "accepted_plan": plan,
        "accepted_plan_file_sha256": prior.PLAN_SHA256,
        "restoration_report": {"path": restoration_path.relative_to(root).as_posix(), "sha256": runtime.EXPECTED_RESTORATION_SHA256},
        "persistence_report": {"path": persistence_path.relative_to(root).as_posix(), "sha256": runtime.EXPECTED_PERSISTENCE_SHA256},
        "read_only": False,
    }
    runtime._load_prerequisites(root, payload)
    report = f".agent/reports/{TASK_ID}/{run_id}"
    return {
        "schema_version": 1, "task": TASK_ID, "run_id": run_id,
        "module": "resolve_workspace/modules/video_cloner_phase5_reel1_flash_v4_idempotency.py",
        "mode": MODE, "status_path": f"{report}/status.json", "log_path": f"{report}/run.log",
        "report_path": f"{report}/report.json", "payload": payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--restoration-report", type=Path, default=DEFAULT_RESTORATION)
    parser.add_argument("--persistence-report", type=Path, default=DEFAULT_PERSISTENCE)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = args.root.resolve()
    paths = [path.resolve() if path.is_absolute() else (root / path).resolve()
             for path in (args.plan, args.restoration_report, args.persistence_report)]
    if any(root not in path.parents for path in paths):
        raise SystemExit("FAIL: authority path outside repository")
    prior = _load("vc_prepare_reel1_restore_id", root / "scripts/davinci/prepare_video_cloner_phase5_reel1_flash_v4_orphan_restoration.py")
    rid = args.run_id or prior.run_id()
    try:
        command = build_command(root, rid, *paths)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    command_root = root / ".agent/commands"
    if any(any((command_root / state).glob("*.json")) for state in ("pending", "running")):
        raise SystemExit("FAIL: active command exists")
    queue = command_root / "pending"
    queue.mkdir(parents=True, exist_ok=True)
    out = queue / f"{TASK_ID}_{rid}.json"
    report_dir = root / ".agent/reports" / TASK_ID / rid
    report_dir.mkdir(parents=True, exist_ok=False)
    encoded = json.dumps(command, indent=2, sort_keys=True) + "\n"
    out.write_text(encoded, encoding="utf-8")
    (report_dir / "command.json").write_text(encoded, encoding="utf-8")
    print(json.dumps({"ok": True, "run_id": rid, "command_path": out.relative_to(root).as_posix()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
