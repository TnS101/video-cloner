from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resolve_workspace.modules.video_cloner_phase6_textplus_application import (
    MODE,
    NODE,
    NODE_CONTRACT,
    TASK_ID,
    _fingerprint,
    load_phase5_contract,
    parse_textplus_fcpxml,
)


MODULE = "resolve_workspace/modules/video_cloner_phase6_textplus_application.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label}_object")
    return value


def inside(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}_outside_repository") from exc
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ValueError(f"{label}_missing")
    return resolved


def identity(path: Path) -> dict[str, object]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def allocate_run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def build_package(
    root: Path,
    generic: Path,
    proxy: Path,
    style: Path,
    audio: Path,
    fcpxml: Path,
    compiler_report_path: Path,
    target: str,
) -> tuple[Path, dict[str, Any]]:
    root = root.resolve()
    generic, proxy, style, audio, fcpxml, compiler_report_path = (
        inside(root, path, label)
        for path, label in (
            (generic, "generic"), (proxy, "proxy"), (style, "caption_style"),
            (audio, "audio"), (fcpxml, "fcpxml"), (compiler_report_path, "compiler_report"),
        )
    )
    generic_value = read_json(generic, "generic")
    compiler_report = read_json(compiler_report_path, "compiler_report")
    if generic_value.get("success") is not True or generic_value.get("schema") != "generic_edit_commands":
        raise ValueError("generic_contract")
    compiler_schema = compiler_report.get("schema")
    if compiler_report.get("success") is not True or compiler_schema not in {
        "video_cloner_davinci_textplus_fcpxml", "video_cloner.standalone_fcpxml.v1",
    }:
        raise ValueError("compiler_report_contract")
    xml = parse_textplus_fcpxml(fcpxml, proxy, audio)
    if xml["timeline_name"] != target:
        raise ValueError("target_timeline_contract")
    subtitles = generic_value.get("subtitle_clips")
    if not isinstance(subtitles, list):
        raise ValueError("caption_count")
    caption_contract = []
    if compiler_schema == "video_cloner.standalone_fcpxml.v1":
        report_inputs = compiler_report.get("inputs")
        report_output = compiler_report.get("output")
        authority = compiler_report.get("caption_authority")
        metrics = authority.get("metrics") if isinstance(authority, Mapping) else None
        semantic = authority.get("semantic") if isinstance(authority, Mapping) else None
        summary = semantic.get("summary") if isinstance(semantic, Mapping) else None
        structure = compiler_report.get("structure")
        if (
            not isinstance(report_inputs, Mapping) or not isinstance(report_output, Mapping)
            or report_inputs.get("generic_sha256") != sha256(generic)
            or report_inputs.get("caption_style_sha256") != sha256(style)
            or report_inputs.get("source_video_sha256") != sha256(proxy)
            or report_inputs.get("source_audio_sha256") != sha256(audio)
            or report_output.get("sha256") != sha256(fcpxml)
            or report_output.get("timeline_name") != target
            or not isinstance(metrics, Mapping) or not isinstance(summary, Mapping) or not isinstance(structure, Mapping)
            or metrics.get("semantic_ledger_count") != len(subtitles)
            or metrics.get("semantic_ledger_exactly_once") is not True
            or summary.get("source_cue_count") != len(subtitles)
            or summary.get("source_coverage_exact") is not True
            or structure.get("caption_count") != len(xml["titles"])
        ):
            raise ValueError("caption_semantic_authority")
        caption_pairs = [(f"render_{index:04d}", title) for index, title in enumerate(xml["titles"], start=1)]
    else:
        if len(subtitles) != len(xml["titles"]):
            raise ValueError("caption_count")
        caption_pairs = []
        for subtitle, title in zip(subtitles, xml["titles"]):
            if not isinstance(subtitle, Mapping) or not subtitle.get("subtitle_id") or subtitle.get("text") != title["text"]:
                raise ValueError("caption_identity")
            caption_pairs.append((str(subtitle["subtitle_id"]), title))
    for caption_id, title in caption_pairs:
        caption_contract.append({
            "subtitle_id": caption_id, "text": title["text"],
            "timeline_start_frame": title["timeline_start"],
            "timeline_end_frame": title["timeline_start"] + title["duration"],
            "lane": title["lane"],
        })

    report_path = fcpxml.with_name(fcpxml.stem + "_import_report.json")
    report = {
        "success": True,
        "schema": "video_cloner.standalone_textplus_fcpxml_report.v1",
        "inputs": {
            "generic": identity(generic), "caption_style": identity(style),
            "source_video": identity(proxy), "source_audio": identity(audio),
        },
        "output": identity(fcpxml) | {"fcpxml": str(fcpxml)},
        "structure": {
            "v1_clip_count": len(xml["cuts"]), "a1_clip_count": len(xml["audio_rows"]),
            "v2_title_count": len(xml["titles"]), "timeline_duration_frames": xml["duration_frames"],
            "caption_contract": caption_contract, "caption_lane_count": len(xml["title_lanes"]),
            "max_caption_lane": xml["title_lanes"][-1], "same_lane_overlap_count": 0,
            "overlap_preserved": True,
        },
        "source_compiler_report": identity(compiler_report_path),
    }
    write_json(report_path, report)

    inputs = {"generic": identity(generic), "proxy": identity(proxy), "caption_style": identity(style), "audio": identity(audio)}
    producer = {"adapter": "prepare_video_cloner_fresh_mvp_timeline.v1", "compiler_version": compiler_report.get("version") or compiler_schema}
    node_identity = {"node": NODE, "inputs": inputs, "producer": producer}
    node = {
        "contract": NODE_CONTRACT, "producer": producer, "fingerprint": _fingerprint(node_identity),
        "outputs": {"fcpxml": identity(fcpxml), "report": identity(report_path)},
    }
    manifest = {
        "schema": "video_cloner.standalone_phase5_manifest.v1", "version": 1,
        "artifact_set_contract": "offline_fcpxml_only_no_resolve", "inputs": inputs, "nodes": {NODE: node},
    }
    manifest["artifact_set_sha256"] = _fingerprint(manifest)
    manifest_path = fcpxml.with_name(fcpxml.stem + "_manifest.json")
    write_json(manifest_path, manifest)
    contract = load_phase5_contract(root, manifest_path)
    return manifest_path, contract


def publish(
    root: Path,
    manifest_path: Path,
    contract: Mapping[str, Any],
    project: str,
    target: str,
    state_root: Path | None = None,
) -> dict[str, Any]:
    if not project or not target:
        raise ValueError("explicit_target_identity")
    state = (state_root or root / ".agent").resolve()
    try:
        state_relative = state.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("state_root_outside_repository") from exc
    queue = state / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    active = [(state, path) for state in ("pending", "running") for path in sorted((queue / state).glob("*.json"))]
    if active:
        raise ValueError(f"active_command:{active[0][0]}:{active[0][1].name}")
    run_id = allocate_run_id()
    if re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", run_id) is None:
        raise ValueError("run_id")
    relative_report = f"{state_relative}/reports/{TASK_ID}/{run_id}"
    report_dir = root / relative_report
    report_dir.mkdir(parents=True, exist_ok=False)
    command = {
        "schema_version": 1, "task": TASK_ID, "run_id": run_id, "module": MODULE, "mode": MODE,
        "status_path": f"{relative_report}/status.json", "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root), "manifest_path": str(manifest_path), "selected_node": NODE,
            "artifact_set_sha256": contract["artifact_set_sha256"], "textplus_fingerprint": contract["textplus_fingerprint"],
            "fcpxml_sha256": contract["fcpxml_sha256"], "report_sha256": contract["report_sha256"],
            "expected_project": project, "target_timeline_name": target, "require_target_absent": True,
            "import_permitted": True, "replace_existing_timeline": False, "save_project": False,
            "delete_permitted": False, "relink_permitted": False, "metadata_controller_permitted": False,
        },
    }
    pending = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(report_dir / "import_command.json", command)
    write_json(pending, command)
    receipt = {
        "ok": True, "task_id": TASK_ID, "run_id": run_id,
        "command_path": str(pending.relative_to(root)).replace("\\", "/"),
        "command_sha256": sha256(pending), "pending_queue_count": len(list((queue / "pending").glob("*.json"))),
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--generic", type=Path, required=True)
    parser.add_argument("--proxy", type=Path, required=True)
    parser.add_argument("--caption-style", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--fcpxml", type=Path, required=True)
    parser.add_argument("--compiler-report", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--target-timeline", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        manifest, contract = build_package(root, args.generic, args.proxy, args.caption_style, args.audio, args.fcpxml, args.compiler_report, args.target_timeline)
        receipt = publish(root, manifest, contract, args.project, args.target_timeline)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
