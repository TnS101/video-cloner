from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "davinci"
    / "validate_manual_workspace_resume.py"
)
spec = importlib.util.spec_from_file_location("manual_workspace_resume", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")

    launcher = tmp_path / "Resolve" / "Fusion" / "Scripts" / "Edit" / "VC_Run_Agent_Task.py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "CONFIG_NAME='VC_Run_Agent_Task.config.json'\n"
        "def _run():\n    return bridge.workspace_main()\n"
        "_run()\n",
        encoding="utf-8",
    )
    bridge = root / "resolve_workspace" / "VC_Agent_Bridge.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("def workspace_main(**kwargs): return 0\n", encoding="utf-8")
    config = launcher.with_name("VC_Run_Agent_Task.config.json")
    write_json(
        config,
        {
            "schema_version": 1,
            "repository_root": str(root.resolve()),
            "bridge_module": "resolve_workspace/VC_Agent_Bridge.py",
        },
    )

    accepted = root / ".agent" / "state" / "latest_accepted.json"
    write_json(accepted, {"canonical_launcher_path": str(launcher)})
    module.EXPECTED_ACCEPTED_STATE_SHA256 = digest(accepted)

    runtime = root / "resolve_workspace" / "modules" / "step_3D_apply_visual_layers.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("def main(*args, **kwargs): return 0\n", encoding="utf-8")

    command = root / ".agent" / "commands" / "pending" / (
        f"{module.SOURCE_TASK_ID}_{module.SOURCE_RUN_ID}.json"
    )
    write_json(
        command,
        {
            "task": module.SOURCE_TASK_ID,
            "run_id": module.SOURCE_RUN_ID,
            "module": "resolve_workspace/modules/step_3D_apply_visual_layers.py",
        },
    )
    module.EXPECTED_COMMAND_SHA256 = digest(command)

    report = root / ".agent" / "reports" / module.SOURCE_TASK_ID / module.SOURCE_RUN_ID
    report.mkdir(parents=True)
    (report / "FINAL_REPORT.md").write_text(
        "FusionScript: VC_Run_Agent_Task.py not found\nCommand remains pending\n",
        encoding="utf-8",
    )
    return root


def test_preflight_accepts_only_manual_workspace_route(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    result = module.validate_preflight(root)
    assert result["ok"] is True
    assert result["execution_route"] == "RESOLVE_WORKSPACE_MENU_ONLY"
    assert result["fuscript_forbidden"] is True


def test_preflight_rejects_unrelated_active_command(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_json(root / ".agent" / "commands" / "pending" / "other.json", {"task": "other"})
    try:
        module.validate_preflight(root)
    except ValueError as exc:
        assert "unrelated_active_command" in str(exc)
    else:
        raise AssertionError("expected failure")


def test_preflight_rejects_missing_canonical_launcher(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    accepted = root / ".agent" / "state" / "latest_accepted.json"
    write_json(accepted, {"canonical_launcher_path": str(tmp_path / "missing.py")})
    module.EXPECTED_ACCEPTED_STATE_SHA256 = digest(accepted)
    try:
        module.validate_preflight(root)
    except ValueError as exc:
        assert "canonical_launcher_missing" in str(exc)
    else:
        raise AssertionError("expected failure")


def test_command_inventory_detects_completed_state(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    pending = root / ".agent" / "commands" / "pending" / (
        f"{module.SOURCE_TASK_ID}_{module.SOURCE_RUN_ID}.json"
    )
    completed = root / ".agent" / "commands" / "completed" / pending.name
    completed.parent.mkdir(parents=True)
    pending.replace(completed)
    assert module.command_candidates(root) == [("completed", completed)]


def test_validate_completed_rejects_failed_command(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    pending = root / ".agent" / "commands" / "pending" / (
        f"{module.SOURCE_TASK_ID}_{module.SOURCE_RUN_ID}.json"
    )
    failed = root / ".agent" / "commands" / "failed" / pending.name
    failed.parent.mkdir(parents=True)
    pending.replace(failed)
    try:
        module.validate_completed(root)
    except ValueError as exc:
        assert "source_command_not_completed:failed" in str(exc)
    else:
        raise AssertionError("expected failure")
