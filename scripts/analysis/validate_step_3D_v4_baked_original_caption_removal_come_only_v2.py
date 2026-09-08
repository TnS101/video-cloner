#!/usr/bin/env python3
"""Independently validate the applied COME-only baked-caption restore by pixels."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_COME_ONLY_V2"
EXPECTED_RANGE = (429, 453)
SENTINELS = (429, 431, 434, 438, 443, 448, 452)
MAX_CORE_MAE = 4.0
MAX_OUTSIDE_BBOX_MAE = 0.25
MAX_PERSON_MAE = 0.25
MIN_SENTINEL_DARK_REDUCTION = 0.20


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
    rows = {frame_number(path): path for path in sorted(directory.glob("*.png"))}
    expected = set(range(*expected_range))
    if set(rows) != expected:
        raise ValidationError(f"frame_set:missing={sorted(expected-set(rows))}:extra={sorted(set(rows)-expected)}")
    return rows


def load_manifest(root: Path) -> Dict[str, Any]:
    path = root / "manifest.json"
    if not path.is_file():
        raise ValidationError("manifest_missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("task_id") != TASK_ID or value.get("ok") is not True:
        raise ValidationError("manifest_identity")
    if value.get("clean_range") != list(EXPECTED_RANGE) or value.get("target_cues") != ["sub_052"]:
        raise ValidationError("manifest_scope")
    checks = value.get("checks") if isinstance(value.get("checks"), Mapping) else {}
    if not checks or not all(item is True for item in checks.values()):
        raise ValidationError("manifest_checks")
    if value.get("temporal_donor_reconstruction_used") is not False or value.get("foreground_reconstruction_used") is not False:
        raise ValidationError("forbidden_reconstruction_mode")
    return value


def _dark_score(frame: np.ndarray, bbox: list[int], person: np.ndarray) -> int:
    x1, y1, x2, y2 = bbox
    crop = frame[y1:y2, x1:x2]
    p = person[y1:y2, x1:x2] > 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    contrast = cv2.absdiff(gray, cv2.GaussianBlur(gray, (0, 0), 2.0))
    candidate = (hsv[:, :, 2] <= 190) & (hsv[:, :, 1] <= 105) & (contrast >= 2) & ~p
    return int(np.count_nonzero(candidate))


def validate(base_dir: Path, generated_root: Path, target_base_dir: Path) -> Dict[str, Any]:
    manifest = load_manifest(generated_root)
    base_rows = indexed(base_dir, EXPECTED_RANGE)
    target_rows = indexed(target_base_dir, EXPECTED_RANGE)
    cleaned_rows = indexed(generated_root / "cleaned", EXPECTED_RANGE)
    foreground_rows = indexed(generated_root / "foreground", EXPECTED_RANGE)
    manifest_rows = {int(row["frame"]): row for row in manifest.get("frames", [])}
    if set(manifest_rows) != set(range(*EXPECTED_RANGE)):
        raise ValidationError("manifest_frame_rows")

    frame_reports = []
    sentinel_pass = 0
    distinct_changed_hashes = set()
    all_person_exact = True
    all_bbox_localized = True
    all_core = True

    for frame in range(*EXPECTED_RANGE):
        original = cv2.imread(str(base_rows[frame]), cv2.IMREAD_COLOR)
        cleaned = cv2.imread(str(cleaned_rows[frame]), cv2.IMREAD_COLOR)
        target = cv2.imread(str(target_rows[frame]), cv2.IMREAD_COLOR)
        person = cv2.imread(str(foreground_rows[frame]), cv2.IMREAD_GRAYSCALE)
        if any(value is None for value in (original, cleaned, target, person)):
            raise ValidationError(f"decode:{frame}")
        row_manifest = manifest_rows[frame]
        bbox = [int(v) for v in row_manifest.get("bbox_pixels", [])]
        if len(bbox) != 4:
            raise ValidationError(f"bbox:{frame}")
        x1, y1, x2, y2 = bbox
        bbox_mask = np.zeros(original.shape[:2], np.uint8)
        bbox_mask[y1:y2, x1:x2] = 255
        person_active = person > 0
        outside_bbox = bbox_mask == 0
        delta = cv2.absdiff(target, original)
        target_vs_cleaned = cv2.absdiff(target, cleaned)
        changed = np.max(delta, axis=2) > 2

        person_mae = float(np.mean(delta[person_active])) if np.any(person_active) else 0.0
        outside_bbox_mae = float(np.mean(delta[outside_bbox])) if np.any(outside_bbox) else 0.0
        core = changed & (bbox_mask > 0) & ~person_active
        core_mae = float(np.mean(target_vs_cleaned[core])) if np.any(core) else 0.0
        before_dark = _dark_score(original, bbox, person)
        after_dark = _dark_score(target, bbox, person)
        reduction = 0.0 if before_dark <= 0 else max(0.0, (before_dark - after_dark) / float(before_dark))

        person_ok = person_mae <= MAX_PERSON_MAE and int(np.count_nonzero(changed & person_active)) == 0
        bbox_ok = outside_bbox_mae <= MAX_OUTSIDE_BBOX_MAE and int(np.count_nonzero(changed & outside_bbox)) == 0
        core_ok = bool(np.any(core)) and core_mae <= MAX_CORE_MAE
        all_person_exact &= person_ok
        all_bbox_localized &= bbox_ok
        all_core &= core_ok
        if np.any(core):
            distinct_changed_hashes.add(__import__("hashlib").sha256(target[core].tobytes()).hexdigest())

        report = {
            "frame": frame,
            "changed_pixels": int(np.count_nonzero(changed)),
            "changed_person_pixels": int(np.count_nonzero(changed & person_active)),
            "changed_outside_bbox_pixels": int(np.count_nonzero(changed & outside_bbox)),
            "person_mae": round(person_mae, 6),
            "outside_bbox_mae": round(outside_bbox_mae, 6),
            "core_target_vs_cleaned_mae": round(core_mae, 6),
            "dark_score_before": before_dark,
            "dark_score_after": after_dark,
            "dark_reduction": round(reduction, 6),
            "person_exact": person_ok,
            "bbox_localized": bbox_ok,
            "core_restore": core_ok,
        }
        if frame in SENTINELS:
            sentinel_ok = bool(person_ok and bbox_ok and core_ok and reduction >= MIN_SENTINEL_DARK_REDUCTION)
            report["sentinel"] = True
            report["sentinel_pass"] = sentinel_ok
            sentinel_pass += int(sentinel_ok)
        frame_reports.append(report)

    checks = {
        "manifest_authority": True,
        "target_scope_sub_052_only": manifest.get("target_cues") == ["sub_052"],
        "no_person_pixels_changed": all_person_exact,
        "all_changes_inside_source_backed_bbox": all_bbox_localized,
        "same_frame_restore_matches_generated": all_core,
        "sentinels_all_pass": sentinel_pass == len(SENTINELS),
        "sequence_not_frozen": len(distinct_changed_hashes) >= 3,
    }
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": all(checks.values()),
        "clean_range": list(EXPECTED_RANGE),
        "sentinels": list(SENTINELS),
        "sentinel_pass_count": sentinel_pass,
        "sentinel_count": len(SENTINELS),
        "thresholds": {
            "max_core_mae": MAX_CORE_MAE,
            "max_outside_bbox_mae": MAX_OUTSIDE_BBOX_MAE,
            "max_person_mae": MAX_PERSON_MAE,
            "min_sentinel_dark_reduction": MIN_SENTINEL_DARK_REDUCTION,
        },
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
            raise ValidationError("checks:" + ",".join(k for k, v in result["checks"].items() if not v))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "task_id": TASK_ID, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "task_id": TASK_ID, "sentinels": result["sentinel_pass_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
