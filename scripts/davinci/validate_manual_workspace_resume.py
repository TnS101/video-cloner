from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3D_LIFECYCLE_VISUAL_LAYER_MANUAL_WORKSPACE_RESUME_V1"
SOURCE_TASK_ID = "DZSQH7AUHJT_STEP_3D_LIFECYCLE_VISUAL_LAYER_REAPPLY_V2R1"
SOURCE_RUN_ID = "20260804T091230681Z_7b9148d4f8994b619650d70effa88f1f"
EXPECTED_COMMAND_SHA256 = "acea7b5cb0e95ed20a178eb7a77b25f2959adebdb71787b48a1ec0fa4d85c72e"
EXPECTED_ACCEPTED_STATE_SHA256 = "739d7ebe082925cb5c50d5b2e871581dbb9205042ed2ca3285561f71ceba8e14"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object_required:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def report_dir(root: Path) -> Path:
    return root / ".agent" / "reports" / TASK_ID / SOURCE_RUN_ID


def source_report_dir(root: Path) -> Path:
    return root / ".agent" / "reports" / SOURCE_TASK_ID / SOURCE_RUN_ID


def command_candidates(root: Path) -> list[tuple[str, Path]]:
    queue = root / ".agent" / "commands"
    filename = f"{SOURCE_TASK_ID}_{SOURCE_RUN_ID}.json"
    candidates: list[tuple[str, Path]] = []
    for state in ("pending", "running", "completed", "failed"):
        path = queue / state / filename
        if path.is_file():
            candidates.append((state, path))
    return candidates


def validate_launcher(root: Path) -> dict[str, Any]:
    accepted_path = root / ".agent" / "state" / "latest_accepted.json"
    if not accepted_path.is_file():
        raise ValueError("accepted_state_missing")
    accepted_hash = sha256(accepted_path)
    if accepted_hash != EXPECTED_ACCEPTED_STATE_SHA256:
        raise ValueError(
            f"accepted_state_hash:expected={EXPECTED_ACCEPTED_STATE_SHA256}:actual={accepted_hash}"
        )

    accepted = load_json(accepted_path)
    launcher_raw = accepted.get("canonical_launcher_path")
    if not isinstance(launcher_raw, str) or not launcher_raw:
        raise ValueError("canonical_launcher_path_missing")
    launcher = Path(launcher_raw)
    if launcher.name != "VC_Run_Agent_Task.py" or not launcher.is_file():
        raise ValueError(f"canonical_launcher_missing:{launcher}")

    config_path = launcher.with_name("VC_Run_Agent_Task.config.json")
    if not config_path.is_file():
        raise ValueError(f"launcher_config_missing:{config_path}")
    config = load_json(config_path)
    if config.get("schema_version") != 1:
        raise ValueError("launcher_config_schema")

    configured_root = Path(str(config.get("repository_root") or "")).resolve()
    if configured_root != root.resolve():
        raise ValueError(f"launcher_repository_root:{configured_root}")

    bridge_relative = config.get("bridge_module")
    if not isinstance(bridge_relative, str) or not bridge_relative:
        raise ValueError("launcher_bridge_module")
    bridge_path = (root / bridge_relative).resolve()
    bridge_path.relative_to(root.resolve())
    if not bridge_path.is_file():
        raise ValueError(f"launcher_bridge_missing:{bridge_path}")

    launcher_text = launcher.read_text(encoding="utf-8-sig")
    required_tokens = ("bridge.workspace_main", "VC_Run_Agent_Task.config.json", "_run()")
    missing_tokens = [token for token in required_tokens if token not in launcher_text]
    if missing_tokens:
        raise ValueError("launcher_contract:" + ",".join(missing_tokens))

    return {
        "accepted_state_path": str(accepted_path),
        "accepted_state_sha256": accepted_hash,
        "canonical_launcher_path": str(launcher),
        "launcher_sha256": sha256(launcher),
        "launcher_config_path": str(config_path),
        "launcher_config_sha256": sha256(config_path),
        "repository_bridge_path": str(bridge_path),
        "repository_bridge_sha256": sha256(bridge_path),
    }


def validate_preflight(root: Path) -> dict[str, Any]:
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")

    active = []
    queue = root / ".agent" / "commands"
    for state in ("pending", "running"):
        for path in sorted((queue / state).glob("*.json")):
            active.append((state, path))

    target = [entry for entry in active if SOURCE_RUN_ID in entry[1].name]
    unrelated = [entry for entry in active if SOURCE_RUN_ID not in entry[1].name]
    if unrelated:
        raise ValueError(f"unrelated_active_command:{unrelated[0][0]}:{unrelated[0][1].name}")
    if len(target) != 1 or target[0][0] != "pending":
        raise ValueError(f"target_pending_command:{[(state, path.name) for state, path in target]}")

    command_path = target[0][1]
    command_hash = sha256(command_path)
    if command_hash != EXPECTED_COMMAND_SHA256:
        raise ValueError(
            f"command_hash:expected={EXPECTED_COMMAND_SHA256}:actual={command_hash}"
        )
    command = load_json(command_path)
    if command.get("task") != SOURCE_TASK_ID or command.get("run_id") != SOURCE_RUN_ID:
        raise ValueError("command_identity")
    module_value = command.get("module")
    if not isinstance(module_value, str) or not module_value:
        raise ValueError("command_module")
    module_path = (root / module_value).resolve()
    module_path.relative_to(root.resolve())
    if not module_path.is_file():
        raise ValueError(f"command_module_missing:{module_path}")

    source_dir = source_report_dir(root)
    if not source_dir.is_dir():
        raise ValueError("source_report_dir_missing")
    final_report = source_dir / "FINAL_REPORT.md"
    if not final_report.is_file():
        raise ValueError("source_final_report_missing")
    text = final_report.read_text(encoding="utf-8-sig")
    if "FusionScript: VC_Run_Agent_Task.py not found" not in text:
        raise ValueError("source_failure_not_launcher_only")
    if "Command remains pending" not in text:
        raise ValueError("source_pending_not_confirmed")

    launcher = validate_launcher(root)
    return {
        "ok": True,
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "checked_at": utc_now(),
        "execution_route": "RESOLVE_WORKSPACE_MENU_ONLY",
        "external_launcher_forbidden": True,
        "fuscript_forbidden": True,
        "pending_command_path": str(command_path),
        "pending_command_sha256": command_hash,
        "command_module_path": str(module_path),
        "source_failure_classification": "EXTERNAL_FUSCRIPT_LAUNCHER_PATH_FAILURE_BEFORE_COMMAND_CONSUMPTION",
        "manual_action": "Workspace > Scripts > VC_Run_Agent_Task",
        **launcher,
    }


def run_source_validator(root: Path) -> dict[str, Any]:
    validator = root / "scripts" / "davinci" / "validate_step_3D_visual_layer_reapply.py"
    if not validator.is_file():
        raise ValueError("source_validator_missing")
    result = subprocess.run(
        [
            sys.executable,
            str(validator),
            "--root",
            str(root),
            "--run-id",
            SOURCE_RUN_ID,
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            "source_validator_failed:"
            + str(result.returncode)
            + ":"
            + (result.stdout + result.stderr)[-2000:]
        )
    return {
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def validate_completed(root: Path) -> dict[str, Any]:
    candidates = command_candidates(root)
    if len(candidates) != 1:
        raise ValueError(f"command_state_inventory:{[(state, path.name) for state, path in candidates]}")
    state, command_path = candidates[0]
    if state != "completed":
        raise ValueError(f"source_command_not_completed:{state}")

    accepted_path = root / ".agent" / "state" / "latest_accepted.json"
    accepted_hash = sha256(accepted_path)
    if accepted_hash != EXPECTED_ACCEPTED_STATE_SHA256:
        raise ValueError(
            f"accepted_state_changed:expected={EXPECTED_ACCEPTED_STATE_SHA256}:actual={accepted_hash}"
        )

    required = [
        "status.json",
        "report.json",
        "run.log",
        "visual_layer_preflight.json",
        "source_fusion_comp_exports.json",
        "fusion_comp_clone_application.json",
        "animation_application.json",
        "position_application.json",
        "visual_layer_readback.json",
        "source_timeline_protection.json",
        "visual_layer_application_result.json",
    ]
    source_dir = source_report_dir(root)
    missing = [name for name in required if not (source_dir / name).is_file()]
    if missing:
        raise ValueError("required_runtime_artifacts:" + ",".join(missing))

    source_validation = run_source_validator(root)
    validation_path = source_dir / "visual_layer_application_validation.json"
    if not validation_path.is_file():
        raise ValueError("source_validation_artifact_missing")
    validation = load_json(validation_path)
    if validation.get("ok") is not True:
        raise ValueError("source_validation_not_ok")

    result = {
        "ok": True,
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "source_run_id": SOURCE_RUN_ID,
        "checked_at": utc_now(),
        "execution_route": "RESOLVE_WORKSPACE_MENU_ONLY",
        "command_state": state,
        "command_path": str(command_path),
        "accepted_state_unchanged": True,
        "accepted_state_sha256": accepted_hash,
        "source_validation_path": str(validation_path),
        "source_validator": source_validation,
        "visual_approval_required": True,
        "verdict": "STEP_3D_LIFECYCLE_FUSION_VISUAL_LAYERS_CLONED",
    }
    return result


def write_final_report(path: Path, result: dict[str, Any], passed: bool) -> None:
    verdict = "PASS" if passed else "FAIL"
    lines = [
        f"# {TASK_ID}",
        "",
        "## Result",
        "",
        verdict,
        "",
        "## Execution route",
        "",
        "- Resolve Workspace menu only.",
        "- `fuscript.exe` and all external launcher attempts were forbidden.",
        f"- Source task: `{SOURCE_TASK_ID}`",
        f"- Source run: `{SOURCE_RUN_ID}`",
        "",
        "## Evidence",
        "",
        "```json",
        json.dumps(result, indent=2),
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def preflight(root: Path) -> int:
    directory = report_dir(root)
    if directory.exists():
        raise ValueError("resume_report_already_exists")
    result = validate_preflight(root)
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory / "manual_workspace_preflight.json", result)
    write_final_report(directory / "FINAL_REPORT.md", result, passed=True)
    print(json.dumps(result, indent=2))
    print("MANUAL_ACTION_REQUIRED: Workspace > Scripts > VC_Run_Agent_Task")
    return 0


def validate(root: Path) -> int:
    directory = report_dir(root)
    preflight_path = directory / "manual_workspace_preflight.json"
    if not preflight_path.is_file():
        raise ValueError("manual_workspace_preflight_missing")
    result = validate_completed(root)
    atomic_json(directory / "manual_workspace_resume_validation.json", result)
    write_final_report(directory / "FINAL_REPORT.md", result, passed=True)
    print(json.dumps(result, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "validate"))
    parser.add_argument("--root", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        if args.mode == "preflight":
            return preflight(root)
        return validate(root)
    except Exception as exc:
        directory = report_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        result = {
            "ok": False,
            "task_id": TASK_ID,
            "source_task_id": SOURCE_TASK_ID,
            "source_run_id": SOURCE_RUN_ID,
            "checked_at": utc_now(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        atomic_json(directory / "manual_workspace_resume_failure.json", result)
        write_final_report(directory / "FINAL_REPORT.md", result, passed=False)
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
