#!/usr/bin/env python3
"""Validate the Resolve-applied sparse baked-caption removal window by pixels."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_WINDOW_V1"
EXPECTED_RANGE = (426, 455)
SENTINELS = (426, 428, 431, 434, 438, 443, 448, 451, 454)
MAX_CORE_MAE = 4.0
MAX_OUTSIDE_MAE = 0.25


class ValidationError(RuntimeError):
    pass


def frame_number(path: Path) -> int:
    match = re.search(r"(\d+)\s*$", path.stem)
    if not match:
        raise ValidationError(f"frame_number:{path.name}")
    return int(match.group(1))


def indexed(directory: Path, expected_range: Tuple[int, int]) -> Dict[int, Path]:
    if not directory.is_dir():
        raise ValidationError(f"dir_missing:{directory}")
    rows: Dict[int, Path] = {}
    for path in sorted(directory.glob("*.png")):
        number = frame_number(path)
        if number in rows:
            raise ValidationError(f"duplicate:{number}")
        rows[number] = path
    expected = set(range(*expected_range))
    if set(rows) != expected:
        raise ValidationError(f"frame_set:missing={sorted(expected-set(rows))}:extra={sorted(set(rows)-expected)}")
    return rows


def load_manifest(root: Path) -> Dict[str, Any]:
    path = root / "manifest.json"
    if not path.is_file():
        raise ValidationError("manifest_missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("task_id") != TASK_ID or value.get("ok") is not True:
        raise ValidationError("manifest_identity")
    if value.get("clean_range") != list(EXPECTED_RANGE):
        raise ValidationError("manifest_range")
    checks = value.get("checks") if isinstance(value.get("checks"), Mapping) else {}
    if not checks or not all(item is True for item in checks.values()):
        raise ValidationError("manifest_checks")
    return value


def validate(base_dir: Path, generated_root: Path, target_base_dir: Path) -> Dict[str, Any]:
    manifest = load_manifest(generated_root)
    base_rows = indexed(base_dir, (400, 480))
    target_rows = indexed(target_base_dir, EXPECTED_RANGE)
    cleaned_rows = indexed(generated_root / "cleaned", EXPECTED_RANGE)
    mask_rows = indexed(generated_root / "masks", EXPECTED_RANGE)

    frame_reports = []
    sentinel_pass = 0
    distinct_target_inside_hashes = set()
    all_localized = True
    all_core = True
    all_noops = True

    for frame in range(*EXPECTED_RANGE):
        original = cv2.imread(str(base_rows[frame]), cv2.IMREAD_COLOR)
        cleaned = cv2.imread(str(cleaned_rows[frame]), cv2.IMREAD_COLOR)
        target = cv2.imread(str(target_rows[frame]), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(mask_rows[frame]), cv2.IMREAD_GRAYSCALE)
        if any(value is None for value in (original, cleaned, target, mask)):
            raise ValidationError(f"decode:{frame}")
        if original.shape != cleaned.shape or original.shape != target.shape or original.shape[:2] != mask.shape:
            raise ValidationError(f"shape:{frame}")

        active = mask > 0
        outside = ~active
        target_vs_original = cv2.absdiff(target, original)
        target_vs_cleaned = cv2.absdiff(target, cleaned)
        outside_mae = float(np.mean(target_vs_original[outside])) if np.any(outside) else 0.0
        core_mae = float(np.mean(target_vs_cleaned[active])) if np.any(active) else 0.0
        inside_change = float(np.mean(target_vs_original[active])) if np.any(active) else 0.0
        localized = outside_mae <= MAX_OUTSIDE_MAE
        if np.any(active):
            core_ok = core_mae <= MAX_CORE_MAE and inside_change >= 1.0
            all_noops = False
            distinct_target_inside_hashes.add(
                __import__("hashlib").sha256(target[active].tobytes()).hexdigest()
            )
        else:
            core_ok = core_mae == 0.0 and float(np.mean(target_vs_original)) <= MAX_OUTSIDE_MAE
        all_localized &= localized
        all_core &= core_ok

        row = {
            "frame": frame,
            "mask_pixels": int(np.count_nonzero(active)),
            "outside_target_vs_base_mae": round(outside_mae, 6),
            "inside_target_vs_cleaned_mae": round(core_mae, 6),
            "inside_target_vs_base_mae": round(inside_change, 6),
            "localized": localized,
            "core_restore": core_ok,
        }
        if frame in SENTINELS:
            row["sentinel"] = True
            row["sentinel_pass"] = bool(localized and core_ok)
            sentinel_pass += int(row["sentinel_pass"])
        frame_reports.append(row)

    nonzero_manifest_frames = [row for row in manifest.get("frames", []) if int(row.get("mask_pixels") or 0) > 0]
    sequence_not_frozen = len(distinct_target_inside_hashes) >= min(3, max(1, len(nonzero_manifest_frames)))
    checks = {
        "manifest_authority": True,
        "all_frame_pixel_localization": all_localized,
        "all_frame_core_restore": all_core,
        "sentinels_all_pass": sentinel_pass == len(SENTINELS),
        "sequence_not_frozen": sequence_not_frozen,
        "nonzero_restore_exists": bool(nonzero_manifest_frames) and not all_noops,
    }
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": all(checks.values()),
        "clean_range": list(EXPECTED_RANGE),
        "sentinels": list(SENTINELS),
        "sentinel_pass_count": sentinel_pass,
        "sentinel_count": len(SENTINELS),
        "thresholds": {"max_core_mae": MAX_CORE_MAE, "max_outside_mae": MAX_OUTSIDE_MAE},
        "checks": checks,
        "frames": frame_reports,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", required=True, type=Path)
    parser.add_argument("--generated-root", required=True, type=Path)
    parser.add_argument("--target-base-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.base_dir.resolve(), args.generated_root.resolve(), args.target_base_dir.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not result["ok"]:
            failed = ",".join(key for key, value in result["checks"].items() if not value)
            raise ValidationError(f"checks:{failed}")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "task_id": TASK_ID, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "task_id": TASK_ID, "sentinels": result["sentinel_pass_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
