"""Publish one disposable track-26 overlap diagnostic command."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

TASK_ID = "VIDEO_CLONER_PHASE5_FLASH_APPEND_OVERLAP_TRACK26_PROBE_V1"
MODE = "phase5_flash_append_overlap_track26_probe"
MODULE = "resolve_workspace/modules/video_cloner_phase5_flash_append_overlap_track26_probe.py"
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/advanced_transition_flash_application_v1.py",
    "resolve_workspace/modules/advanced_transition_flash_neutral_rgba_v4.py",
    "resolve_workspace/modules/video_cloner_phase4b_timeline_application.py",
    "resolve_workspace/VC_Agent_Bridge.py",
)


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def new_run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def active_commands(root: Path) -> list[Path]:
    queue = root / ".agent" / "commands"
    return [path for state in ("pending", "running") for path in (queue / state).glob("*.json")]


def prepare(root: Path, run_id: str | None = None) -> dict:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    for relative in SOURCE_PATHS:
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")
    rid = run_id or new_run_id()
    report = Path(".agent") / "reports" / TASK_ID / rid
    report_dir = root / report
    report_dir.mkdir(parents=True, exist_ok=False)
    pending = root / ".agent" / "commands" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    name_suffix = rid[-12:]
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": rid,
        "module": MODULE,
        "mode": MODE,
        "status_path": str(report / "status.json").replace("\\", "/"),
        "log_path": str(report / "run.log").replace("\\", "/"),
        "report_path": str(report / "report.json").replace("\\", "/"),
        "source_contract": {
            "algorithm": "sha256_text_lf_normalized",
            "hashes": {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS},
        },
        "payload": {
            "expected_project": "New Project 1",
            "disposable_timeline_name": f"VC_PHASE5_TRACK26_PROBE_{name_suffix}",
            "track_index": 26,
            "record_frame": 94,
            "duration_frames": 4,
            "read_only": False,
            "cleanup_required": True,
        },
    }
    command_path = pending / f"{TASK_ID}_{rid}.json"
    text = json.dumps(command, indent=2, sort_keys=True) + "\n"
    command_path.write_text(text, encoding="utf-8")
    (report_dir / "command.json").write_text(text, encoding="utf-8")
    receipt = {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": rid,
        "command_path": str(command_path.relative_to(root)).replace("\\", "/"),
        "report_dir": str(report).replace("\\", "/"),
        "resolve_executions": 0,
    }
    (report_dir / "publication_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id")
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.run_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
