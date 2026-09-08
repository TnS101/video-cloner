#!/usr/bin/env python3
"""Publish one bounded baked-original caption-removal window command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_WINDOW_V1"
MODE = "STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_WINDOW_V1"
MODULE = "resolve_workspace/modules/step_3D_v4_baked_original_caption_removal_window_v1.py"
HELPER = "scripts/analysis/build_step_3D_v4_baked_original_caption_removal_window_v1.py"
PIXEL_VALIDATOR = "scripts/analysis/validate_step_3D_v4_baked_original_caption_removal_window_v1.py"
SOURCE = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_"
    "repair_metrics_v1_occlusion_complete_v4_motion_fade_v1_the_size_fix_v1"
)
TARGET = SOURCE + "_baked_remove_window_v1"
SOURCE_VIDEO = "input/DZsqH7auhjt.mp4"
SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
CONTEXT_RANGE = [400, 480]
CLEAN_RANGE = [426, 455]
TARGET_CUES = [f"sub_{value:03d}" for value in range(51, 57)]
RESTORE_NAME = "VC_BAKED_CAPTION_PIXEL_RESTORE_window_051_056_v1"
TARGET_TRACK = 2
SIZE_RUN = ".agent/reports/DZSQH7AUHJT_CAPTION_THE_SIZE_POP_FIX_V1/20260813T193846470431Z_2a38db99c03d4c149386a2a217ee8846"
V4_RUN = ".agent/reports/DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4/20260812T174800495896Z_07d0e09144764182a5c4b1ec41ca6952"

EXPECTED_SUPPLIED_HASHES = {
    "resolve_workspace/modules/caption_the_size_pop_fix_v1.py": "f4ffe5609d624a68c8370e985e6ad13a690faf2d7c09215bde20efe1b598d696",
    "resolve_workspace/modules/caption_motion_fade_application_v1.py": "2d1d557e87c43f2f4c7feb82bc1f1b08a44d143044c0a5c3161089b5f7a50c3e",
    "resolve_workspace/modules/final_occlusion_composition_v4.py": "b7ca380d6d92d8575e3576b4e075361f591df3b09cb1e072d0495b34241ac519",
    "resolve_workspace/modules/final_occlusion_composition_v3.py": "8445070fd6f44dc0a43a76a35b0965d8068fdf6a7c5a60c2147c940681a350d0",
    "resolve_workspace/modules/final_occlusion_composition_v2.py": "253b858c11664bd70b3f9f07ee7fb3b197ccbf143e0748e911ba22337cd18de3",
    "resolve_workspace/modules/final_occlusion_composition_v1.py": "937e3a3161b073d293f3a466f37d5c64ca0f2662e3a21aa03eb90459745568c7",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py": "809d32839cda387bc1c9497fefd50efc8176a47159099ef42a16551f0839ef09",
    "resolve_workspace/VC_Agent_Bridge.py": "1af3e506b7e67ce8f402f41b7a5fa2618f24f4760db43257f95aaa01706e5da6",
    "scripts/analysis/remove_baked_captions_window.py": "337f0381bca1644a32754d541218f7e5adaac665a137f6244284dee73d86686b",
    "scripts/analysis/remove_baked_captions_window_temporal.py": "d877a4add9571d3f3cb421d4caea9e5b5943ff00f45f6ddbb7c7d1f3b3e40a07",
    "scripts/analysis/detect_caption_occlusion.py": "33efce4cf115b9068761eb6a363d322102965e176d18ac5b71b01c4a98cbd2f9",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_style.json": "d1c06f1372cfb3bd12953ec99ca1ba8f3efb936200abc5729b614c6f41cc2780",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json": "ae2035648e35b7bc30811206315892b843ef779fdff9181dddb81dc69c69f3a8",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json": "15ac3efde34e69a3242ffd0ff615f7fd257d1a90953f2fb2be7d6e7ed12dc5b5",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_occlusion.json": "9b7375166b356ea57dc83b08d9eadcd97f3e9a7f16e24b23249138cbf4831dcd",
    f"{SIZE_RUN}/report.json": "c4c2230b0ee6ae880d0011b1e0ddf504efa7a3a3453395ce5276f473bc09e396",
    f"{SIZE_RUN}/technical_validation.json": "6d1245bb0cf2ea0f35300e774f4128cf76e8187cd90a301209cb1ac8a3ab6770",
    f"{SIZE_RUN}/persistent_readback.json": "7081837dffa4c071a2763a3fd2cfff8a169ee43169028b56b56a6dc122ba531f",
    f"{V4_RUN}/report.json": "861a6207debdfb70b1d3032f2c586a5166d14511ea9282fec4fc525d4fd148bd",
    f"{V4_RUN}/technical_validation.json": "62140b38a1146a7332a2f83e0452e1d48b24f1c30d20a64d8e5b928ea9090327",
    f"{V4_RUN}/persistent_readback.json": "815375c7ea2cdd10ac17f19cad285989d6efc2d348de6da504d838e041047274",
}
SOURCE_PATHS = tuple(EXPECTED_SUPPLIED_HASHES) + (MODULE, HELPER, PIXEL_VALIDATOR)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def active_commands(root: Path) -> List[Path]:
    rows: List[Path] = []
    for state in ("pending", "running"):
        directory = root / ".agent" / "commands" / state
        if directory.is_dir():
            rows.extend(sorted(directory.glob("*.json")))
    return rows


def validate_accepted_source(root: Path) -> None:
    report = load_json(root / SIZE_RUN / "report.json")
    technical = load_json(root / SIZE_RUN / "technical_validation.json")
    persistent = load_json(root / SIZE_RUN / "persistent_readback.json")
    checks = technical.get("checks") if isinstance(technical.get("checks"), Mapping) else {}
    pchecks = persistent.get("checks") if isinstance(persistent.get("checks"), Mapping) else {}
    if (
        report.get("ok") is not True
        or report.get("target_timeline_name") != SOURCE
        or report.get("final_textplus_count") != 114
        or report.get("caption_recreation_count") != 0
        or report.get("center_write_count") != 0
        or report.get("opacity_write_count") != 0
        or report.get("style_write_count") != 0
        or report.get("timing_track_mutation_count") != 0
        or report.get("occlusion_mutation_count") != 0
        or report.get("save_call_count") != 1
        or report.get("source_timeline_unchanged") is not True
        or report.get("motion_fade_source_preserved_except_target_size") is not True
        or report.get("v4_occlusion_preserved") is not True
        or report.get("persistent_readback_ok") is not True
        or report.get("idempotency_ok") is not True
        or technical.get("ok") is not True
        or not checks
        or not all(value is True for value in checks.values())
        or persistent.get("ok") is not True
        or not pchecks
        or not all(value is True for value in pchecks.values())
    ):
        raise ValueError("accepted_size_fix_source")

    v4_report = load_json(root / V4_RUN / "report.json")
    v4_technical = load_json(root / V4_RUN / "technical_validation.json")
    v4_persistent = load_json(root / V4_RUN / "persistent_readback.json")
    vt = v4_technical.get("checks") if isinstance(v4_technical.get("checks"), Mapping) else {}
    vp = v4_persistent.get("checks") if isinstance(v4_persistent.get("checks"), Mapping) else {}
    if (
        v4_report.get("ok") is not True
        or v4_report.get("final_textplus_count") != 114
        or v4_report.get("caption_mutation_count") != 0
        or v4_report.get("occlusion_mutation_count") != 1
        or v4_report.get("save_call_count") != 1
        or v4_report.get("persistent_readback_ok") is not True
        or v4_report.get("idempotency_ok") is not True
        or v4_report.get("source_timeline_unchanged") is not True
        or v4_technical.get("ok") is not True
        or not vt
        or not all(value is True for value in vt.values())
        or v4_persistent.get("ok") is not True
        or not vp
        or not all(value is True for value in vp.values())
    ):
        raise ValueError("accepted_v4_source")


def validate_supplied_hashes(root: Path) -> None:
    for relative, expected in EXPECTED_SUPPLIED_HASHES.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"source_missing:{relative}")
        actual = normalized_sha256(path)
        if actual != expected:
            raise ValueError(f"source_hash:{relative}:{actual}:{expected}")


def python_candidates(root: Path, explicit: str | None) -> List[str]:
    candidates: List[str] = []
    virtual_root = root / "Virtual Environments"
    preferred = [
        virtual_root / "venv_ocr" / "Scripts" / "python.exe",
        virtual_root / "venv" / "Scripts" / "python.exe",
    ]
    discovered: List[Path] = []
    if virtual_root.is_dir():
        discovered = sorted(virtual_root.glob("*/Scripts/python.exe"), key=lambda path: str(path).lower())
    for value in (
        explicit,
        *(str(path) for path in preferred),
        *(str(path) for path in discovered),
        str(root / ".venv" / "Scripts" / "python.exe"),
        str(root / "venv" / "Scripts" / "python.exe"),
        sys.executable,
        shutil.which("python"),
        shutil.which("python3"),
    ):
        if value and str(value) not in candidates:
            candidates.append(str(value))
    return candidates


def select_external_python(root: Path, explicit: str | None) -> Dict[str, Any]:
    probe = "\n".join(
        [
            "import json, sys",
            "result = {'ok': False, 'python': sys.executable}",
            "try:",
            "    import cv2, numpy, paddle, paddlehub",
            "    compiled = bool(paddle.device.is_compiled_with_cuda())",
            "    result.update({'cv2': cv2.__version__, 'numpy': numpy.__version__, 'paddle': paddle.__version__,",
            "                   'paddlehub': getattr(paddlehub, '__version__', None), 'cuda': compiled})",
            "    if compiled:",
            "        paddle.device.set_device('gpu:0')",
            "        device = str(paddle.device.get_device())",
            "        model = paddlehub.Module(name='humanseg_lite')",
            "        result.update({'device': device, 'humanseg_module': type(model).__name__,",
            "                       'humanseg_module_ok': model is not None})",
            "        result['ok'] = bool(device.startswith('gpu') and model is not None)",
            "except Exception as exc:",
            "    result['error'] = type(exc).__name__ + ':' + str(exc)",
            "print(json.dumps(result, sort_keys=True))",
        ]
    )
    attempts = []
    for candidate in python_candidates(root, explicit):
        path = Path(candidate)
        if not path.is_file() and shutil.which(candidate) is None:
            attempts.append({"python": candidate, "ok": False, "reason": "not_found"})
            continue
        try:
            proc = subprocess.run([candidate, "-c", probe], cwd=str(root), text=True, capture_output=True, timeout=120, check=False)
        except Exception as exc:  # noqa: BLE001
            attempts.append({"python": candidate, "ok": False, "reason": f"{type(exc).__name__}:{exc}"})
            continue
        row = {"python": candidate, "returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "ok": False}
        if proc.returncode == 0:
            try:
                info = json.loads(proc.stdout.strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                info = {}
            row["info"] = info
            if info.get("ok") is True and info.get("cuda") is True:
                row["ok"] = True
                attempts.append(row)
                return {"python": str(info.get("python") or candidate), "attempts": attempts, "ok": True}
        attempts.append(row)
    raise ValueError("paddle_cuda_python:" + json.dumps(attempts, sort_keys=True))


def publish(root: Path, explicit_python: str | None = None) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    validate_supplied_hashes(root)
    validate_accepted_source(root)
    video = root / SOURCE_VIDEO
    if not video.is_file() or raw_sha256(video) != SOURCE_VIDEO_SHA256:
        raise ValueError("source_video_hash")
    for relative in (MODULE, HELPER, PIXEL_VALIDATOR):
        if not (root / relative).is_file():
            raise ValueError(f"patch_file_missing:{relative}")
    external = select_external_python(root, explicit_python)

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        directory = queue / state
        directory.mkdir(parents=True, exist_ok=True)
        existing = list(directory.glob(f"{TASK_ID}_*.json"))
        if existing:
            raise ValueError(f"task_command_exists:{state}:{existing[0].name}")
    report_root = root / ".agent" / "reports" / TASK_ID
    if report_root.exists() and any(path.is_dir() for path in report_root.iterdir()):
        raise ValueError("task_report_exists")
    report_root.mkdir(parents=True, exist_ok=True)

    run_id = run_id_now()
    report_dir = report_root / run_id
    report_dir.mkdir()
    source_hashes = {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS}
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": utc_now(),
        "artifacts_dir": str(report_dir.relative_to(root)).replace("/", "\\"),
        "status_path": str((report_dir / "status.json").relative_to(root)).replace("/", "\\"),
        "log_path": str((report_dir / "run.log").relative_to(root)).replace("/", "\\"),
        "report_path": str((report_dir / "report.json").relative_to(root)).replace("/", "\\"),
        "source_contract": {"version": 1, "algorithm": SOURCE_HASH_ALGORITHM, "hashes": source_hashes},
        "baked_removal": {
            "source_timeline_name": SOURCE,
            "target_timeline_name": TARGET,
            "expected_textplus_count": 114,
            "context_range": CONTEXT_RANGE,
            "clean_range": CLEAN_RANGE,
            "target_cues": TARGET_CUES,
            "restore_name": RESTORE_NAME,
            "restore_track": TARGET_TRACK,
            "external_python": external["python"],
            "external_python_probe": external,
            "paddle_hub_module": "humanseg_lite",
            "exact_resolve_base_render_required": True,
            "raw_source_rgb_overlay_authorized": False,
            "whole_frame_replacement_authorized": False,
            "caption_mutation_authorized": False,
            "caption_recreation_authorized": False,
            "motion_fade_mutation_authorized": False,
            "size_fix_mutation_authorized": False,
            "occlusion_mutation_authorized": False,
            "v4_occlusion_must_persist": True,
            "v2_restore_is_only_timeline_mutation": True,
            "one_save_required": True,
            "one_resolve_invocation_required": True,
            "pre_save_pixel_gate_required": True,
            "persistent_readback_required": True,
            "idempotency_required": True,
            "visual_approval_required": True,
            "full_reel_rollout_authorized": False,
        },
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path.relative_to(root)).replace("/", "\\"),
        "external_python": external,
        "source_video_sha256": SOURCE_VIDEO_SHA256,
        "manual_action": "Workspace > Scripts > VC_Run_Agent_Task",
        "manual_action_count": 1,
        "visual_approval_required": True,
        "full_reel_rollout_authorized": False,
        "ok": True,
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    write_json(report_dir / "baked_removal_command.json", command)
    return {"command": command, "command_path": command_path, "receipt": receipt}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--external-python")
    args = parser.parse_args()
    try:
        result = publish(args.root, args.external_python)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "task_id": TASK_ID, "run_id": result["command"]["run_id"], "command_path": str(result["command_path"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
