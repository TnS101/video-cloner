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
    if (roaming / ANCHOR).is_file() and any("video_cloner" in item.name.lower() for item in roaming.glob("*.py")):
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
    config = {"schema_version": 1, "repository_root": str(repo), "bridge_module": "resolve_workspace\\VC_Agent_Bridge.py", "command_queue": ".agent\\commands"}
    destination = canonical / LAUNCHER; destination_config = canonical / CONFIG
    shutil.copy2(source, destination); destination_config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
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
    state = {"canonical_scripts_edit": str(canonical), "anchor_script": str(canonical / ANCHOR), "repository_root": str(repo), "launcher_path": str(destination), "launcher_hash": sha256(destination), "installation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    state_path = repo / ".agent" / "state" / "resolve_bridge_installation.json"; state_path.parent.mkdir(parents=True, exist_ok=True); state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"CANONICAL {canonical}\nREMOVED {len(removed)}\nSHA256 {state['launcher_hash']}\nPASS")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--root", required=True)
    raise SystemExit(install(Path(parser.parse_args().root).resolve()))
