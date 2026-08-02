"""Resolve Workspace launcher for one explicit Video Cloner agent command."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

LAUNCHER_VERSION = "VC_Run_Agent_Task_20260801_v1"
CONFIG_NAME = "VC_Run_Agent_Task.config.json"


def _script_path() -> Path:
    """Resolve does not always expose __file__ to Workspace scripts."""
    values = [globals().get("__file__"), sys.argv[0] if sys.argv else None]
    for value in values:
        if value:
            candidate = Path(str(value)).resolve()
            if candidate.name == "VC_Run_Agent_Task.py":
                return candidate
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = Path(appdata) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Edit" / "VC_Run_Agent_Task.py"
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("could not determine VC_Run_Agent_Task.py location")


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _append(trace_path: Path, event: str, **fields: object) -> None:
    try:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"utc_timestamp={_utc()}", f"event={event}",
            f"launcher_version={LAUNCHER_VERSION}", f"file={_script_path()}",
            f"cwd={Path.cwd()}", f"name={__name__}",
            f"python={sys.version.replace(chr(10), ' ')}",
            f"resolve_global_available={'resolve' in globals()}",
            f"fusion_global_available={'fusion' in globals()}", "launcher_started=true",
        ]
        lines.extend(f"{key}={value}" for key, value in fields.items())
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except BaseException:
        pass


def _run() -> int:
    script_path = _script_path()
    launcher_trace = script_path.with_name("VC_Run_Agent_Task_bootstrap.log")
    repository_trace: Path | None = None
    _append(launcher_trace, "launcher_started")
    try:
        config_path = script_path.with_name(CONFIG_NAME)
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        repository_root = Path(str(config.get("repository_root") or "")).resolve()
        if config.get("schema_version") != 1 or not repository_root.is_dir():
            raise RuntimeError(f"invalid launcher config or repository root: {config_path}")
        repository_trace = repository_root / ".agent" / "logs" / "VC_Run_Agent_Task_bootstrap.log"
        _append(repository_trace, "repository_config_loaded", config_path=config_path)
        bridge_path = (repository_root / str(config.get("bridge_module") or "")).resolve()
        bridge_path.relative_to(repository_root)
        if not bridge_path.is_file():
            raise RuntimeError(f"repository bridge missing: {bridge_path}")
        _append(launcher_trace, "repository_bridge_loaded", repository_bridge_path=bridge_path)
        _append(repository_trace, "repository_bridge_loaded", repository_bridge_path=bridge_path)
        spec = importlib.util.spec_from_file_location("vc_agent_repository_bridge", bridge_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load repository bridge: {bridge_path}")
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        result = bridge.workspace_main(resolve=globals().get("resolve"), fusion=globals().get("fusion"))
        _append(launcher_trace, "launcher_completed", return_code=result)
        _append(repository_trace, "launcher_completed", return_code=result)
        return int(result or 0)
    except BaseException:
        details = traceback.format_exc()
        _append(launcher_trace, "launcher_exception", traceback=details)
        if repository_trace is not None:
            _append(repository_trace, "launcher_exception", traceback=details)
        return 1


_run()
