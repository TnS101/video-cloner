"""Deterministically install the one Resolve Workspace bridge launcher."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ANCHOR = "resolve_apply_caption_source_geometry_probe_step_3B_6.py"
LAUNCHER = "VC_Run_Agent_Task.py"
CONFIG = "VC_Run_Agent_Task.config.json"
QUEUE_DIRS = ("pending", "running", "completed", "failed")
OLD_NAMES = ("VC_Agent_Bridge.py", "VC_Agent_Bridge_Live.py", LAUNCHER,
             "VC_Agent_Bridge.config.json", "VC_Agent_Bridge_Live.config.json", CONFIG)
PROCESS_NAMES = ("Resolve", "Fusion", "fuscript", "FusionScript")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def running_processes() -> list[str]:
    found = []
    for name in PROCESS_NAMES:
        result = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
        if f'"{name}.exe"'.lower() in result.stdout.lower(): found.append(name + ".exe")
    return found


def candidate_roots() -> list[Path]:
    bases = [Path(value) for value in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"), os.environ.get("PROGRAMDATA")) if value]
    return [base / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Edit" for base in bases]


def discover_script_dirs() -> list[Path]:
    candidates = {path.resolve() for path in candidate_roots() if path.is_dir()}
    # Search every portable Fusion Scripts/Edit root, not only roots containing
    # the anchor: stale bridge files often live in the portable App tree.
    for base in (Path(os.environ.get("USERPROFILE", "")) / "Downloads", Path(os.environ.get("APPDATA", ""))):
        if base.is_dir():
            for scripts in base.rglob("Scripts"):
                edit = scripts / "Edit"
                if scripts.name == "Scripts" and edit.is_dir() and "fusion" in str(scripts).lower():
                    candidates.add(edit.resolve())
            for anchor in base.rglob(ANCHOR):
                if anchor.parent.name.lower() == "edit": candidates.add(anchor.parent.resolve())
    return sorted(candidates, key=lambda value: str(value).lower())


def select_canonical(directories: list[Path]) -> Path:
    anchored = [directory for directory in directories if (directory / ANCHOR).is_file() and any("video_cloner" in item.name.lower() for item in directory.glob("*.py"))]
    if not anchored: raise RuntimeError(f"no Scripts/Edit directory contains {ANCHOR} and another Video Cloner script")
    roaming = (Path(os.environ.get("APPDATA", "")) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Edit").resolve()
    if roaming in anchored:
        return roaming
    return anchored[0]


def remove_bridge_files(directory: Path) -> list[str]:
    removed = []
    for item in directory.rglob("*"):
        if not item.is_file(): continue
        bridge_pyc = item.suffix == ".pyc" and any(name[:-3] in item.name for name in ("VC_Agent_Bridge.py", "VC_Agent_Bridge_Live.py", LAUNCHER))
        if item.name in OLD_NAMES or bridge_pyc:
            item.unlink(); removed.append(str(item))
    return removed


def recover_existing_command(repo: Path, filename: str, run_id: str) -> dict[str, str]:
    """Move one legacy root command to pending, or prove it is already queued."""
    if Path(filename).name != filename or not filename.lower().endswith(".json"):
        raise RuntimeError(f"invalid command filename: {filename}")
    if not run_id:
        raise RuntimeError("run_id is required")
    queue = repo / ".agent" / "commands"
    for state in QUEUE_DIRS:
        (queue / state).mkdir(parents=True, exist_ok=True)
    candidates = [("legacy_root", queue / filename)] + [(state, queue / state / filename) for state in QUEUE_DIRS]
    found = [(state, path) for state, path in candidates if path.is_file()]
    if not found:
        raise RuntimeError(f"existing command not found: {filename}")
    if len(found) != 1:
        locations = ", ".join(str(path) for _, path in found)
        raise RuntimeError(f"conflicting command copies found: {locations}")
    state, source = found[0]
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid existing command: {source}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("run_id") != run_id:
        raise RuntimeError(f"existing command run_id mismatch: {source}")
    before_hash = sha256(source)
    if state == "legacy_root":
        destination = queue / "pending" / filename
        if destination.exists():
            raise RuntimeError(f"refusing to overwrite pending command: {destination}")
        try:
            source.rename(destination)
        except OSError as exc:
            raise RuntimeError(f"could not recover command atomically: {source}: {exc}") from exc
        if sha256(destination) != before_hash:
            raise RuntimeError("recovered command SHA-256 mismatch")
        source = destination
        state = "pending"
        result = "recovered"
    elif state == "pending":
        result = "already_pending"
    elif state == "completed":
        result = "already_completed"
    else:
        raise RuntimeError(f"command is already {state}; preserve it and stop: {source}")
    return {"result": result, "state": state, "path": str(source), "run_id": run_id, "sha256": before_hash}


def install(repo: Path) -> int:
    active = running_processes()
    if active:
        print("ERROR: Resolve/Fusion is running: " + ", ".join(active)); return 1
    source = repo / "resolve_workspace" / LAUNCHER
    if not source.is_file(): print(f"ERROR: missing launcher source: {source}"); return 1
    directories = discover_script_dirs()
    try: canonical = select_canonical(directories)
    except RuntimeError as error: print(f"ERROR: {error}"); return 1
    removed = [path for directory in directories for path in remove_bridge_files(directory)]
    queue = repo / ".agent" / "commands"
    for state_name in QUEUE_DIRS:
        (queue / state_name).mkdir(parents=True, exist_ok=True)
    config = {"schema_version": 1, "repository_root": str(repo), "bridge_module": "resolve_workspace\\VC_Agent_Bridge.py", "command_queue": ".agent\\commands"}
    destination = canonical / LAUNCHER; destination_config = canonical / CONFIG
    shutil.copy2(source, destination)
    config_temporary = destination_config.with_name(destination_config.name + ".tmp")
    config_temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(config_temporary, destination_config)
    if sha256(source) != sha256(destination): print("ERROR: launcher SHA-256 mismatch"); return 1
    launchers = [directory / LAUNCHER for directory in directories if (directory / LAUNCHER).is_file()]
    configs = [directory / CONFIG for directory in directories if (directory / CONFIG).is_file()]
    installed_files = [item for directory in directories for item in directory.rglob("*") if item.is_file()]
    old = [item for item in installed_files if item.name in ("VC_Agent_Bridge.py", "VC_Agent_Bridge_Live.py")]
    pyc = [item for item in installed_files if item.suffix == ".pyc" and ("VC_Agent_Bridge" in item.name or "VC_Run_Agent_Task" in item.name)]
    if launchers != [destination] or configs != [destination_config] or old or pyc:
        print("ERROR: final bridge installation verification failed"); return 1
    for trace in (repo / ".agent" / "logs" / "VC_Run_Agent_Task_bootstrap.log", canonical / "VC_Run_Agent_Task_bootstrap.log"):
        trace.unlink(missing_ok=True)
    installed_config = json.loads(destination_config.read_text(encoding="utf-8-sig"))
    if installed_config != config:
        print("ERROR: installed bridge configuration mismatch"); return 1
    state = {"canonical_scripts_edit": str(canonical), "anchor_script": str(canonical / ANCHOR), "repository_root": str(repo), "launcher_path": str(destination), "launcher_hash": sha256(destination), "config_path": str(destination_config), "config_hash": sha256(destination_config), "command_queue": str(queue), "installation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    state_path = repo / ".agent" / "state" / "resolve_bridge_installation.json"; state_path.parent.mkdir(parents=True, exist_ok=True); state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"CANONICAL {canonical}\nREMOVED {len(removed)}\nSHA256 {state['launcher_hash']}\nPASS")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--recover-only", action="store_true")
    parser.add_argument("--recover-command")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.recover_only:
        try:
            if not args.recover_command or not args.run_id:
                raise RuntimeError("--recover-only requires --recover-command and --run-id")
            print(json.dumps(recover_existing_command(root, args.recover_command, args.run_id), indent=2))
            raise SystemExit(0)
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            raise SystemExit(1)
    raise SystemExit(install(root))
