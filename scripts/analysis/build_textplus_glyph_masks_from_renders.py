"""Build compact per-frame glyph masks from Resolve Text+ on/off renders."""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3D_GLYPH_MASK_RENDER_PROBE_V1"
FRAME_IN = 420
FRAME_OUT = 462
TARGET_IN = 428
TARGET_OUT = 451
EXPECTED_FRAME_COUNT = FRAME_OUT - FRAME_IN + 1
EXPECTED_TARGET_COUNT = TARGET_OUT - TARGET_IN + 1
DIFF_THRESHOLD = 6
MIN_COMPONENT_AREA = 3
DILATE_RADIUS = 2
MIN_TARGET_AREA_RATIO = 0.0003
MAX_TARGET_AREA_RATIO = 0.12
MAX_COMPONENT_FILL_RATIO = 0.93


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"image_read:{path}")
    return image


def remove_small_components(mask: np.ndarray, minimum_area: int = MIN_COMPONENT_AREA) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    result = np.zeros(mask.shape, dtype=np.uint8)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= minimum_area:
            result[labels == label] = 255
    return result


def build_glyph_mask(with_text: np.ndarray, without_text: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    if with_text.shape != without_text.shape:
        raise ValueError("shape_mismatch")
    delta = cv2.absdiff(with_text, without_text)
    strength = np.max(delta, axis=2)
    raw = np.where(strength >= DIFF_THRESHOLD, 255, 0).astype(np.uint8)
    raw = remove_small_components(raw)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DILATE_RADIUS * 2 + 1, DILATE_RADIUS * 2 + 1))
    mask = cv2.dilate(raw, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    components = []
    for label in range(1, count):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        w = int(stats[label, cv2.CC_STAT_WIDTH])
        h = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        box_area = max(1, w * h)
        components.append({
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "area": area,
            "fill_ratio": area / box_area,
        })

    pixels = int(np.count_nonzero(mask))
    total = int(mask.shape[0] * mask.shape[1])
    outside = mask == 0
    outside_delta_max = int(np.max(strength[outside])) if np.any(outside) else 0
    return mask, {
        "raw_pixels": int(np.count_nonzero(raw)),
        "mask_pixels": pixels,
        "area_ratio": pixels / total,
        "component_count": len(components),
        "components": components,
        "max_component_fill_ratio": max((row["fill_ratio"] for row in components), default=0.0),
        "outside_mask_delta_max": outside_delta_max,
        "mean_mask_delta": float(np.mean(strength[mask > 0])) if pixels else 0.0,
    }


def make_contact_sheet(images: Sequence[np.ndarray], labels: Sequence[str], columns: int = 4, cell_width: int = 360) -> np.ndarray:
    if not images:
        raise ValueError("contact_sheet_empty")
    rows = math.ceil(len(images) / columns)
    prepared = []
    cell_height = None
    for image, label in zip(images, labels):
        scale = cell_width / image.shape[1]
        resized = cv2.resize(image, (cell_width, max(1, int(round(image.shape[0] * scale)))), interpolation=cv2.INTER_AREA)
        header = np.zeros((34, cell_width, 3), dtype=np.uint8)
        cv2.putText(header, label, (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        tile = np.vstack([header, resized])
        cell_height = tile.shape[0] if cell_height is None else max(cell_height, tile.shape[0])
        prepared.append(tile)
    canvas = np.zeros((rows * int(cell_height), columns * cell_width, 3), dtype=np.uint8)
    for index, tile in enumerate(prepared):
        row = index // columns
        column = index % columns
        canvas[row * int(cell_height): row * int(cell_height) + tile.shape[0], column * cell_width: (column + 1) * cell_width] = tile
    return canvas


def pair_paths(render_result: Mapping[str, Any]) -> List[Tuple[int, Path, Path]]:
    with_paths = [Path(value) for value in render_result.get("with_textplus_files") or []]
    without_paths = [Path(value) for value in render_result.get("without_textplus_files") or []]
    if len(with_paths) != EXPECTED_FRAME_COUNT or len(without_paths) != EXPECTED_FRAME_COUNT:
        raise ValueError(f"render_count:{len(with_paths)}:{len(without_paths)}")
    return [(FRAME_IN + index, with_paths[index], without_paths[index]) for index in range(EXPECTED_FRAME_COUNT)]


def build(report_dir: Path, output_dir: Path) -> Dict[str, Any]:
    report_dir = report_dir.resolve()
    output_dir = output_dir.resolve()
    render_result = load_json(report_dir / "glyph_render_result.json")
    if render_result.get("task_id") != TASK_ID or not render_result.get("ok"):
        raise ValueError("render_result")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    masks_dir = output_dir / "glyph_masks"
    overlays_dir = output_dir / "overlays"
    diff_dir = output_dir / "differences"
    with_copy_dir = output_dir / "with_textplus"
    without_copy_dir = output_dir / "without_textplus"
    for directory in (masks_dir, overlays_dir, diff_dir, with_copy_dir, without_copy_dir):
        directory.mkdir(parents=True, exist_ok=True)

    rows = []
    mask_sheet_images = []
    mask_sheet_labels = []
    pair_sheet_images = []
    pair_sheet_labels = []

    for frame, with_path, without_path in pair_paths(render_result):
        if not with_path.is_file() or not without_path.is_file():
            raise ValueError(f"render_file_missing:{frame}")
        with_image = load_image(with_path)
        without_image = load_image(without_path)
        mask, metrics = build_glyph_mask(with_image, without_image)
        target = TARGET_IN <= frame <= TARGET_OUT
        area_ratio = float(metrics["area_ratio"])
        nonempty = int(metrics["mask_pixels"]) > 0
        compact = float(metrics["max_component_fill_ratio"]) <= MAX_COMPONENT_FILL_RATIO
        target_ok = bool(
            not target
            or (
                nonempty
                and MIN_TARGET_AREA_RATIO <= area_ratio <= MAX_TARGET_AREA_RATIO
                and compact
            )
        )

        mask_path = masks_dir / f"glyph_mask_{frame:06d}.png"
        overlay_path = overlays_dir / f"glyph_overlay_{frame:06d}.png"
        diff_path = diff_dir / f"glyph_diff_{frame:06d}.png"
        cv2.imwrite(str(mask_path), mask)
        overlay = with_image.copy()
        overlay[mask > 0] = (0.35 * overlay[mask > 0] + 0.65 * np.array([0, 0, 255])).astype(np.uint8)
        cv2.imwrite(str(overlay_path), overlay)
        delta = cv2.absdiff(with_image, without_image)
        cv2.imwrite(str(diff_path), delta)
        shutil.copy2(with_path, with_copy_dir / f"frame_{frame:06d}{with_path.suffix.lower()}")
        shutil.copy2(without_path, without_copy_dir / f"frame_{frame:06d}{without_path.suffix.lower()}")

        row = {
            "frame": frame,
            "target": target,
            "with_textplus": str(with_path),
            "without_textplus": str(without_path),
            "mask": str(mask_path),
            "overlay": str(overlay_path),
            "difference": str(diff_path),
            "nonempty": nonempty,
            "compact": compact,
            "target_ok": target_ok,
            **metrics,
        }
        rows.append(row)

        if target:
            mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            mask_sheet_images.append(mask_bgr)
            mask_sheet_labels.append(f"frame {frame} mask {area_ratio:.4f}")
            pair = np.hstack([with_image, without_image, overlay])
            pair_sheet_images.append(pair)
            pair_sheet_labels.append(f"frame {frame}: with | without | mask")

    target_rows = [row for row in rows if row["target"]]
    summary = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "frame_in": FRAME_IN,
        "frame_out": FRAME_OUT,
        "target_in": TARGET_IN,
        "target_out": TARGET_OUT,
        "frame_count": len(rows),
        "target_frame_count": len(target_rows),
        "target_nonempty_count": sum(1 for row in target_rows if row["nonempty"]),
        "target_compact_count": sum(1 for row in target_rows if row["compact"]),
        "minimum_target_area_ratio": min((row["area_ratio"] for row in target_rows), default=0.0),
        "maximum_target_area_ratio": max((row["area_ratio"] for row in target_rows), default=0.0),
        "maximum_outside_mask_delta": max((row["outside_mask_delta_max"] for row in rows), default=0),
        "rows": rows,
    }
    summary["ok"] = bool(
        summary["frame_count"] == EXPECTED_FRAME_COUNT
        and summary["target_frame_count"] == EXPECTED_TARGET_COUNT
        and summary["target_nonempty_count"] == EXPECTED_TARGET_COUNT
        and summary["target_compact_count"] == EXPECTED_TARGET_COUNT
        and all(row["target_ok"] for row in target_rows)
    )

    cv2.imwrite(str(output_dir / "glyph_mask_contact_sheet.jpg"), make_contact_sheet(mask_sheet_images, mask_sheet_labels))
    cv2.imwrite(str(output_dir / "render_difference_contact_sheet.jpg"), make_contact_sheet(pair_sheet_images, pair_sheet_labels, columns=2, cell_width=540))
    write_json(output_dir / "report.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = build(Path(args.report_dir), Path(args.output_dir))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
