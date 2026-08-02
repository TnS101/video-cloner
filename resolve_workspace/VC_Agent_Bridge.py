"""Repository-backed Resolve command bridge.

The installed copy discovers the repository only through the adjacent config
file. It consumes exactly one command per invocation and never creates a run id.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

CONFIG_NAME = "VC_Agent_Bridge.config.json"
QUEUE_DIRS = ("pending", "running", "completed", "failed")
BRIDGE_BUILD = "VC_Agent_Bridge_20260801_bootstrap_v1"
BOOTSTRAP_TRACE = Path(tempfile.gettempdir()) / "VideoCloner_VC_Agent_Bridge_bootstrap.log"


class BridgeError(RuntimeError):
    pass


def bootstrap_trace(event: str, **fields: Any) -> None:
    """Append an early, best-effort trace that is independent of config/queue."""
    try:
        lines = [f"utc_timestamp={utc_now()}", f"event={event}", f"bridge_build={BRIDGE_BUILD}",
                 f"file={Path(__file__).resolve()}", f"cwd={Path.cwd()}", f"name={__name__}",
                 f"python={sys.version.replace(chr(10), ' ')}",
                 f"resolve_global={'resolve' in globals()}", f"fusion_global={'fusion' in globals()}" ]
        lines.extend(f"{key}={value}" for key, value in fields.items())
        with BOOTSTRAP_TRACE.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except BaseException:
        pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def load_config(config_path: Path | str | None = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else Path(__file__).with_name(CONFIG_NAME)
    if not path.is_file():
        raise BridgeError(f"missing bridge config: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except BaseException as exc:
        raise BridgeError(f"invalid bridge config: {path}: {exc}") from exc
    if config.get("schema_version") != 1:
        raise BridgeError("unsupported bridge config schema")
    repository_root = Path(str(config.get("repository_root") or "")).expanduser()
    if not repository_root.is_dir():
        raise BridgeError(f"invalid repository root: {repository_root}")
    if config.get("command_queue") != ".agent\\commands":
        raise BridgeError("command_queue must be .agent\\commands")
    config["repository_root"] = repository_root
    config["config_path"] = path.resolve()
    return config


def command_queue(config: Dict[str, Any]) -> Path:
    root = Path(config["repository_root"]).resolve()
    queue = root / ".agent" / "commands"
    for name in QUEUE_DIRS:
        (queue / name).mkdir(parents=True, exist_ok=True)
    return queue


def load_command(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise BridgeError(f"invalid command JSON: {path}: {exc}") from exc
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise BridgeError("command run_id is required")
    return payload


def pending_commands(queue: Path) -> list[Path]:
    return sorted((p for p in (queue / "pending").glob("*.json") if p.is_file()), key=lambda p: (p.stat().st_mtime_ns, p.name))


def active_run_ids(queue: Path) -> set[str]:
    ids: set[str] = set()
    for path in (queue / "running").glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig")).get("run_id")
            if isinstance(value, str):
                ids.add(value)
        except Exception:
            continue
    return ids


def claim_oldest(queue: Path) -> tuple[Path, Dict[str, Any]] | None:
    paths = pending_commands(queue)
    if not paths:
        return None
    source = paths[0]
    command = load_command(source)
    if command["run_id"] in active_run_ids(queue):
        failed = queue / "failed" / source.name
        os.replace(source, failed)
        raise BridgeError(f"duplicate active run_id rejected: {command['run_id']}")
    running = queue / "running" / source.name
    os.replace(source, running)
    return running, command


def safe_module_path(repository_root: Path, command: Dict[str, Any]) -> Path:
    module_value = command.get("module")
    if not isinstance(module_value, str) or not module_value:
        raise BridgeError("command module is required")
    candidate = Path(module_value)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix.lower() != ".py":
        raise BridgeError(f"module path rejected: {module_value}")
    resolved = (repository_root / candidate).resolve()
    try:
        resolved.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise BridgeError(f"module path rejected: {module_value}") from exc
    if not resolved.is_file():
        raise BridgeError(f"module not found: {module_value}")
    return resolved


def write_text(path_value: str, text: str) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path_value: str, payload: Dict[str, Any]) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def resolve_application() -> Any:
    try:
        import DaVinciResolveScript as dvr  # type: ignore
        resolve = dvr.scriptapp("Resolve")
    except Exception as exc:
        raise BridgeError(f"Resolve scripting API unavailable: {exc}") from exc
    if not resolve:
        raise BridgeError("Resolve scripting API returned no application")
    return resolve


def execute_command(command: Dict[str, Any], repository_root: Path, resolve: Any = None) -> Dict[str, Any]:
    module_path = safe_module_path(repository_root, command)
    spec = importlib.util.spec_from_file_location("vc_agent_command_module", module_path)
    if spec is None or spec.loader is None:
        raise BridgeError(f"could not load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runner = getattr(module, "run", None)
    if not callable(runner):
        raise BridgeError("command module must expose run(resolve, context)")
    active_resolve = resolve if resolve is not None else resolve_application()
    result = runner(active_resolve, {"run_id": command["run_id"], "command": command})
    if not isinstance(result, dict):
        raise BridgeError("command module result must be a JSON object")
    return result


def process_one(config_path: Path | str | None = None, resolve: Any = None) -> int:
    config = load_config(config_path) if config_path else {
        "repository_root": Path(__file__).resolve().parent.parent,
        "command_queue": ".agent\\commands",
    }
    repository_root = Path(config["repository_root"])
    queue = command_queue(config)
    pending = pending_commands(queue)
    bootstrap_trace("queue_processing_start", repository_root=repository_root,
                    pending_directory=queue / "pending", pending_count=len(pending),
                    selected_command=(pending[0] if pending else ""),
                    selected_run_id=(load_command(pending[0])["run_id"] if pending else ""))
    claimed = claim_oldest(queue)
    if claimed is None:
        return 0
    running_path, command = claimed
    run_id = command["run_id"]
    status_path = command.get("status_path")
    log_path = command.get("log_path")
    report_path = command.get("report_path")
    started = utc_now()
    status = {"schema_version": 1, "run_id": run_id, "running": True, "ok": False, "started_at": started}
    if status_path:
        write_json(status_path, status)
    if log_path:
        write_text(log_path, f"{run_id} bridge_started {started}\n")
    code = 1
    try:
        result = execute_command(command, repository_root, resolve=resolve)
        report = dict(result)
        report.update({"run_id": run_id, "module": command.get("module"), "mode": command.get("mode"), "ok": bool(result.get("ok"))})
        code = 0 if report["ok"] else 1
        final_status = {"schema_version": 1, "run_id": run_id, "running": False, "ok": report["ok"], "finished_at": utc_now(), "report_path": report_path}
        if report_path:
            write_json(report_path, report)
        if status_path:
            write_json(status_path, final_status)
        if log_path:
            write_text(log_path, f"{run_id} bridge_finished ok={report['ok']} {final_status['finished_at']}\n")
        os.replace(running_path, queue / ("completed" if report["ok"] else "failed") / running_path.name)
        return code
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        failure = {"schema_version": 1, "run_id": run_id, "ok": False, "error": error}
        if report_path:
            write_json(report_path, failure)
        if status_path:
            write_json(status_path, {"schema_version": 1, "run_id": run_id, "running": False, "ok": False, "finished_at": utc_now(), "error": error})
        if log_path:
            write_text(log_path, f"{run_id} bridge_failed {error}\n{traceback.format_exc()}\n")
        os.replace(running_path, queue / "failed" / running_path.name)
        return code


def workspace_entrypoint(config_path: Path | str | None = None, resolve: Any = None, fusion: Any = None) -> int:
    bootstrap_trace("entry_point_started", **{"entry-point-started": "true"})
    try:
        return process_one(config_path, resolve=resolve)
    except BaseException:
        bootstrap_trace("entry_point_exception", traceback=traceback.format_exc())
        return 1


def workspace_main(resolve: Any = None, fusion: Any = None, config_path: Path | str | None = None) -> int:
    """Explicit Workspace entry point used by the live Resolve launcher."""
    bootstrap_trace("entry_point_started", **{"entry-point-started": "true"})
    try:
        return process_one(config_path, resolve=resolve)
    except BaseException:
        bootstrap_trace("entry_point_exception", traceback=traceback.format_exc())
        return 1


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    return workspace_main(config_path=args.config)


if __name__ == "__main__":
    raise SystemExit(main())
