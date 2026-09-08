"""Validate one terminal glyph-mask render probe and build mask artifacts."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import time
from pathlib import Path
from typing import Any, Dict, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_GLYPH_MASK_RENDER_PROBE_V1"
MODE = "STEP_3D_GLYPH_MASK_RENDER_PROBE"
SOURCE_TIMELINE = "DZsqH7auhjt_textplus_full_step_3D_complete"
ANALYSIS_PATH = Path(__file__).resolve().parents[1] / "analysis" / "build_textplus_glyph_masks_from_renders.py"
_spec = importlib.util.spec_from_file_location("vc_build_glyph_masks", ANALYSIS_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def find_command(root: Path, run_id: str) -> Tuple[str, Path]:
    queue = root / ".agent" / "commands"
    for state in ("completed", "failed", "running", "pending"):
        directory = queue / state
        if directory.is_dir():
            for path in directory.glob(f"*{run_id}*.json"):
                return state, path
    raise ValueError("command_not_found")


def wait_terminal(root: Path, run_id: str, timeout_seconds: float, poll_seconds: float = 1.0) -> Tuple[str, Path, Dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    observations = []
    while time.monotonic() < deadline:
        state, path = find_command(root, run_id)
        observations.append({"state": state, "path": str(path), "at": utc_now()})
        if state in {"completed", "failed"}:
            return state, path, {"observations": observations}
        time.sleep(poll_seconds)
    raise TimeoutError("terminal_timeout")


def final_report(validation: Dict[str, Any]) -> str:
    lines = [
        f"# {TASK_ID}",
        "",
        f"- Result: `{'PASS' if validation.get('ok') else 'FAIL'}`",
        f"- Run ID: `{validation.get('run_id')}`",
        f"- Command state: `{validation.get('command_state')}`",
        f"- Backend: `{validation.get('backend')}`",
        f"- Render format/codec: `{validation.get('render_format')}` / `{validation.get('render_codec')}`",
        f"- Rendered frames with/without Text+: `{validation.get('with_textplus_frame_count')}` / `{validation.get('without_textplus_frame_count')}`",
        f"- Disabled Text+ items: `{validation.get('disabled_textplus_count')}`",
        f"- Target glyph masks: `{validation.get('target_nonempty_count')}` / `24`",
        f"- Target glyph compactness: `{validation.get('target_compact_count')}` / `24`",
        f"- Target mask area range: `{validation.get('minimum_target_area_ratio')}`–`{validation.get('maximum_target_area_ratio')}`",
        f"- Source timeline unchanged: `{validation.get('source_timeline_unchanged')}`",
        f"- Temporary timeline deleted: `{validation.get('temporary_timeline_deleted')}`",
        f"- Accepted state unchanged: `{validation.get('accepted_state_unchanged')}`",
        f"- Save calls: `{validation.get('save_call_count')}`",
        f"- Visual approval required: `{validation.get('visual_review_required')}`",
    ]
    if validation.get("failures"):
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- `{failure}`" for failure in validation["failures"])
    if validation.get("ok"):
        lines.extend([
            "",
            "## Review artifacts",
            "",
            "- `glyph_mask_contact_sheet.jpg`",
            "- `render_difference_contact_sheet.jpg`",
            "- `glyph_masks/`",
            "- `with_textplus/` and `without_textplus/`",
        ])
    return "\n".join(lines) + "\n"


def validate(root: Path, run_id: str, timeout_seconds: float = 1800.0) -> Dict[str, Any]:
    root = root.resolve()
    report_dir = root / ".agent" / "reports" / TASK_ID / run_id
    if not report_dir.is_dir():
        raise ValueError("report_dir")
    receipt_path = report_dir / "publication_receipt.json"
    command_copy_path = report_dir / "glyph_probe_command.json"
    if not receipt_path.is_file() or not command_copy_path.is_file():
        raise ValueError("publication_evidence")
    receipt = load_json(receipt_path)
    command_copy = load_json(command_copy_path)
    if receipt.get("run_id") != run_id or command_copy.get("run_id") != run_id:
        raise ValueError("run_id")
    if command_copy.get("task_id") != TASK_ID or command_copy.get("mode") != MODE:
        raise ValueError("command_identity")

    state, command_path, wait = wait_terminal(root, run_id, timeout_seconds)
    command = load_json(command_path)
    if raw_sha256(command_path) != receipt.get("command_sha256"):
        raise ValueError("command_sha256")

    report_path = report_dir / "report.json"
    status_path = report_dir / "status.json"
    if not report_path.is_file() or not status_path.is_file():
        raise ValueError("terminal_report_missing")
    runtime = load_json(report_path)
    status = load_json(status_path)
    failures = []
    if state != "completed":
        failures.append(f"command_state:{state}")
    if status.get("running") is not False:
        failures.append("status_running")
    if not runtime.get("ok"):
        runtime_failures = runtime.get("failures")
        if isinstance(runtime_failures, list) and runtime_failures:
            failures.extend(f"runtime:{value}" for value in runtime_failures)
        else:
            failures.append(f"runtime:{runtime.get('error') or 'not_ok'}")

    mask_result: Dict[str, Any] = {}
    artifact_dir = root / "artifacts" / TASK_ID / run_id
    if not failures:
        try:
            mask_result = analysis.build(report_dir, artifact_dir)
            if not mask_result.get("ok"):
                failures.append("glyph_mask_build")
        except BaseException as exc:
            failures.append(f"glyph_mask_build:{type(exc).__name__}:{exc}")

    accepted_path = root / ".agent" / "state" / "latest_accepted.json"
    accepted_disk = accepted_path.is_file() and raw_sha256(accepted_path) == command.get("accepted_state_sha256")
    checks = {
        "task_id": runtime.get("task_id") == TASK_ID,
        "mode": runtime.get("mode") == MODE,
        "backend": runtime.get("backend") == "resolve_lossless_dual_render_plus_textplus_disable",
        "run_id": runtime.get("run_id") == run_id,
        "source_timeline": runtime.get("source_timeline_name") == SOURCE_TIMELINE,
        "render_with": runtime.get("with_textplus_frame_count") == 43,
        "render_without": runtime.get("without_textplus_frame_count") == 43,
        "disabled_count": runtime.get("disabled_textplus_count") == 115,
        "source_unchanged": runtime.get("source_timeline_unchanged") is True,
        "temporary_deleted": runtime.get("temporary_timeline_deleted") is True,
        "accepted_runtime": runtime.get("accepted_state_unchanged") is True,
        "accepted_disk": accepted_disk,
        "save_count": runtime.get("save_call_count") == 1,
        "mask_frame_count": mask_result.get("frame_count") == 43,
        "mask_target_count": mask_result.get("target_frame_count") == 24,
        "mask_target_nonempty": mask_result.get("target_nonempty_count") == 24,
        "mask_target_compact": mask_result.get("target_compact_count") == 24,
        "mask_ok": mask_result.get("ok") is True,
    }
    for name, ok in checks.items():
        if not ok:
            failures.append(f"check:{name}")

    validation = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "ok": not failures,
        "validated_at": utc_now(),
        "command_state": state,
        "command_path": str(command_path),
        "wait": wait,
        "checks": checks,
        "failures": failures,
        "backend": runtime.get("backend"),
        "render_format": runtime.get("render_format"),
        "render_codec": runtime.get("render_codec"),
        "with_textplus_frame_count": runtime.get("with_textplus_frame_count"),
        "without_textplus_frame_count": runtime.get("without_textplus_frame_count"),
        "disabled_textplus_count": runtime.get("disabled_textplus_count"),
        "source_timeline_unchanged": runtime.get("source_timeline_unchanged"),
        "temporary_timeline_deleted": runtime.get("temporary_timeline_deleted"),
        "accepted_state_unchanged": runtime.get("accepted_state_unchanged") and accepted_disk,
        "save_call_count": runtime.get("save_call_count"),
        "target_nonempty_count": mask_result.get("target_nonempty_count"),
        "target_compact_count": mask_result.get("target_compact_count"),
        "minimum_target_area_ratio": mask_result.get("minimum_target_area_ratio"),
        "maximum_target_area_ratio": mask_result.get("maximum_target_area_ratio"),
        "artifact_dir": str(artifact_dir),
        "visual_review_required": True,
    }
    write_json(report_dir / "validation.json", validation)
    (report_dir / "FINAL_REPORT.md").write_text(final_report(validation), encoding="utf-8")
    print(json.dumps(validation, indent=2, sort_keys=True))
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    args = parser.parse_args()
    result = validate(Path(args.root), args.run_id, args.timeout_seconds)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
