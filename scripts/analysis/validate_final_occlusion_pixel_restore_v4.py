#!/usr/bin/env python3
"""Validate V4 occlusion pixels before or after the single project save.

The V4 correction is specifically for the image-sequence source-index bug proven
by V3: the MediaPoolItem native frame range is 426..453, while the rejected
runtime appended source frames 0..27. Resolve clamped that invalid trim to the
first image. This validator requires the final render to restore the matching
same-frame without-COME pixels, not merely stay inside the alpha mask.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4"
FRAME_RANGE = (426, 454)
SENTINELS = (427, 429, 431, 434, 438, 443, 448, 452, 453)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def indexed(directory: Path) -> Dict[int, Path]:
    rows: Dict[int, Path] = {}
    for path in sorted(directory.glob("*.png")):
        digits = "".join(ch for ch in path.stem if ch.isdigit())
        if not digits:
            continue
        frame = int(digits[-8:])
        if frame in rows:
            raise ValueError(f"duplicate_frame:{frame}:{directory}")
        rows[frame] = path
    return rows


def read_bgr(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"decode:{path}")
    return image


def read_rgba(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        raise ValueError(f"rgba:{path}")
    return image


def analyze(
    with_dir: Path,
    without_dir: Path,
    target_dir: Path,
    generated_root: Path,
) -> Dict[str, Any]:
    with_rows = indexed(with_dir)
    without_rows = indexed(without_dir)
    target_rows = indexed(target_dir)
    expected = set(range(*FRAME_RANGE))
    if set(with_rows) != expected:
        raise ValueError(f"with_frames:{sorted(with_rows)}")
    if set(without_rows) != expected:
        raise ValueError(f"without_frames:{sorted(without_rows)}")
    if set(target_rows) != expected:
        raise ValueError(f"target_frames:{sorted(target_rows)}")

    rows = []
    sentinel_pass = 0
    visible_frames = 0
    for frame in range(*FRAME_RANGE):
        with_bgr = read_bgr(with_rows[frame])
        without_bgr = read_bgr(without_rows[frame])
        target_bgr = read_bgr(target_rows[frame])
        rgba = read_rgba(generated_root / "rgba" / f"rgba_{frame:06d}.png")
        if with_bgr.shape != without_bgr.shape or target_bgr.shape != with_bgr.shape or rgba.shape[:2] != with_bgr.shape[:2]:
            raise ValueError(f"dimensions:{frame}")

        alpha = rgba[:, :, 3]
        active = alpha > 0
        core = alpha >= 250
        outside = ~active

        target_vs_with = cv2.absdiff(target_bgr, with_bgr)
        target_vs_without = cv2.absdiff(target_bgr, without_bgr)
        with_vs_without = cv2.absdiff(with_bgr, without_bgr)

        outside_peak = np.max(target_vs_with, axis=2)
        outside_changed = int(np.count_nonzero((outside_peak > 2) & outside))
        outside_pixels = int(np.count_nonzero(outside))
        outside_fraction = outside_changed / max(1, outside_pixels)
        outside_mae = float(target_vs_with[outside].mean()) if outside_pixels else 0.0

        active_pixels = int(np.count_nonzero(active))
        core_pixels = int(np.count_nonzero(core))
        effect_pixels = int(np.count_nonzero((np.max(target_vs_with, axis=2) > 2) & active))
        intended_pixels = int(np.count_nonzero((np.max(with_vs_without, axis=2) > 2) & active))
        core_mae = float(target_vs_without[core].mean()) if core_pixels else 0.0
        target_equals_with = bool(np.array_equal(target_bgr, with_bgr))

        # Frame 426 has a deliberately empty intersection. It must be a no-op.
        if active_pixels == 0:
            row_ok = bool(
                frame == FRAME_RANGE[0]
                and target_equals_with
                and outside_changed == 0
            )
        else:
            visible_frames += 1
            row_ok = bool(
                outside_fraction <= 0.0001
                and outside_mae <= 0.50
                and core_pixels >= 10
                and intended_pixels >= 20
                and effect_pixels >= 20
                and not target_equals_with
                and core_mae <= 3.0
            )

        if frame in SENTINELS and row_ok:
            sentinel_pass += 1

        rows.append({
            "timeline_frame": frame,
            "alpha_pixels": active_pixels,
            "core_pixels": core_pixels,
            "intended_effect_pixels": intended_pixels,
            "actual_effect_pixels": effect_pixels,
            "outside_changed_pixels": outside_changed,
            "outside_changed_fraction": round(outside_fraction, 9),
            "outside_mae": round(outside_mae, 6),
            "core_vs_same_frame_without_mae": round(core_mae, 6),
            "target_equals_with_come_render": target_equals_with,
            "ok": row_ok,
        })

    checks = {
        "all_28_frames_present": len(rows) == 28,
        "first_empty_frame_is_noop": rows[0]["alpha_pixels"] == 0 and rows[0]["ok"] is True,
        "same_frame_restore_all_frames": all(row["ok"] for row in rows),
        "sequence_not_frozen_on_first_frame": visible_frames >= 20 and all(
            not row["target_equals_with_come_render"]
            for row in rows
            if row["alpha_pixels"] > 0
        ),
        "sentinels_all_pass": sentinel_pass == len(SENTINELS),
    }
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "frame_range_half_open": list(FRAME_RANGE),
        "sentinel_frames": list(SENTINELS),
        "sentinel_pass_count": sentinel_pass,
        "rows": rows,
        "checks": checks,
        "ok": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-dir", type=Path, required=True)
    parser.add_argument("--without-dir", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--generated-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = analyze(
            args.with_dir.resolve(),
            args.without_dir.resolve(),
            args.target_dir.resolve(),
            args.generated_root.resolve(),
        )
        write_json(args.output.resolve(), result)
    except Exception as exc:  # noqa: BLE001
        result = {"schema_version": 1, "task_id": TASK_ID, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        write_json(args.output.resolve(), result)
        print(json.dumps(result, sort_keys=True))
        return 1
    print(json.dumps({"ok": result["ok"], "sentinel_pass_count": result["sentinel_pass_count"]}, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
