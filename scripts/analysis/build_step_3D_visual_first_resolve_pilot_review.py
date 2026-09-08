#!/usr/bin/env python3
"""Build seven synchronized visual-review contact sheets from Resolve renders."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_RESOLVE_PILOT_V1"
AUTHORITY_TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3"
AUTHORITY_RELATIVE_PATH = Path(
    "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3/"
    "visual_authority_script_renderability_v3.json"
)
FRAME_IN = 176
FRAME_OUT = 692
EXPECTED_FRAME_COUNT = FRAME_OUT - FRAME_IN + 1
EXPECTED_GROUP_COUNT = 7
EXPECTED_TOKEN_COUNT = 17
PANEL_WIDTH = 360
PANEL_HEIGHT = 640
LABEL_HEIGHT = 34
MODE_ORDER = ("source_only", "generated_only", "alignment_overlay")
MODE_LABELS = {
    "source_only": "ORIGINAL SOURCE",
    "generated_only": "GENERATED TEXT+ ONLY",
    "alignment_overlay": "ALIGNMENT OVERLAY",
}


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_frames(group: Mapping[str, Any]) -> List[int]:
    start, end = [int(value) for value in group["group_window"]]
    hold = group.get("group_hold_window") if isinstance(group.get("group_hold_window"), list) else [start, end]
    hold_start, hold_end = [int(value) for value in hold]
    candidates = [
        start,
        min(end - 1, max(start, hold_start)),
        min(end - 1, max(start, (hold_start + max(hold_start + 1, hold_end) - 1) // 2)),
        min(end - 1, max(start, hold_end - 1)),
        end - 1,
    ]
    return sorted(set(candidates))


class VideoReader:
    def __init__(self, path: Path):
        self.path = path
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            raise ValueError(f"video_open:{path}")
        self.frame_count = int(round(self.capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        self.width = int(round(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        self.height = int(round(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0.0)

    def read_timeline_frame(self, timeline_frame: int) -> np.ndarray:
        index = int(timeline_frame) - FRAME_IN
        if not (0 <= index < self.frame_count):
            raise ValueError(f"frame_index:{self.path}:{timeline_frame}:{index}:{self.frame_count}")
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise ValueError(f"frame_read:{self.path}:{timeline_frame}")
        return frame

    def close(self) -> None:
        self.capture.release()


def resize_panel(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    scale = min(PANEL_WIDTH / max(1, width), PANEL_HEIGHT / max(1, height))
    resized = cv2.resize(frame, (max(1, int(round(width * scale))), max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((PANEL_HEIGHT, PANEL_WIDTH, 3), dtype=np.uint8)
    y = (PANEL_HEIGHT - resized.shape[0]) // 2
    x = (PANEL_WIDTH - resized.shape[1]) // 2
    canvas[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
    return canvas


def labeled_panel(frame: np.ndarray, label: str, timeline_frame: int) -> np.ndarray:
    panel = resize_panel(frame)
    header = np.zeros((LABEL_HEIGHT, PANEL_WIDTH, 3), dtype=np.uint8)
    cv2.putText(header, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(header, f"F{timeline_frame}", (PANEL_WIDTH - 64, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([header, panel])


def build(repo_root: Path, report_dir: Path) -> Dict[str, Any]:
    report = load_json(report_dir / "report.json")
    render_result = load_json(report_dir / "review_renders.json")
    authority = load_json(repo_root / AUTHORITY_RELATIVE_PATH)
    if report.get("task_id") != TASK_ID or render_result.get("task_id") != TASK_ID:
        raise ValueError("task_identity")
    if report.get("ok") is not True or render_result.get("ok") is not True:
        raise ValueError("runtime_not_passed")
    if authority.get("task_id") != AUTHORITY_TASK_ID or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    if authority.get("summary", {}).get("group_count") != EXPECTED_GROUP_COUNT:
        raise ValueError("authority_group_count")
    if authority.get("summary", {}).get("visual_token_count") != EXPECTED_TOKEN_COUNT:
        raise ValueError("authority_token_count")

    render_paths: Dict[str, Path] = {}
    for mode in MODE_ORDER:
        row = render_result.get("renders", {}).get(mode)
        if not isinstance(row, Mapping) or row.get("ok") is not True:
            raise ValueError(f"render_missing:{mode}")
        path = Path(str(row.get("file") or ""))
        if not path.is_absolute():
            path = repo_root / path
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"render_file:{mode}:{path}")
        render_paths[mode] = path

    readers = {mode: VideoReader(path) for mode, path in render_paths.items()}
    try:
        counts = {reader.frame_count for reader in readers.values()}
        dimensions = {(reader.width, reader.height) for reader in readers.values()}
        if len(counts) != 1 or min(counts) < EXPECTED_FRAME_COUNT:
            raise ValueError(f"video_frame_counts:{sorted(counts)}")
        if len(dimensions) != 1:
            raise ValueError(f"video_dimensions:{sorted(dimensions)}")

        review_dir = report_dir / "visual_review"
        review_dir.mkdir(parents=True, exist_ok=True)
        group_rows = []
        for group in authority["groups"]:
            group_id = str(group["group_id"])
            frames = sample_frames(group)
            contact_rows = []
            for timeline_frame in frames:
                panels = [
                    labeled_panel(readers[mode].read_timeline_frame(timeline_frame), MODE_LABELS[mode], timeline_frame)
                    for mode in MODE_ORDER
                ]
                contact_rows.append(np.hstack(panels))
            sheet = np.vstack(contact_rows)
            sheet_path = review_dir / f"{group_id}_comparison.jpg"
            if not cv2.imwrite(str(sheet_path), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 94]):
                raise ValueError(f"contact_sheet_write:{group_id}")
            group_rows.append(
                {
                    "group_id": group_id,
                    "label": str(group.get("label") or ""),
                    "group_window": [int(value) for value in group["group_window"]],
                    "sample_frames": frames,
                    "token_ids": [str(token["visual_token_id"]) for token in group.get("tokens") or []],
                    "contact_sheet": str(sheet_path),
                    "contact_sheet_size": sheet_path.stat().st_size,
                    "contact_sheet_sha256": raw_sha256(sheet_path),
                }
            )

        instructions = review_dir / "VISUAL_REVIEW.md"
        lines = [
            "# Seven-window visual review",
            "",
            "Technical PASS does not authorize the full rollout.",
            "",
            "For each sheet compare:",
            "",
            "1. ORIGINAL SOURCE — the baked source caption authority.",
            "2. GENERATED TEXT+ ONLY — editable reconstruction without source video.",
            "3. ALIGNMENT OVERLAY — both layers together for geometry and lifecycle comparison.",
            "",
            "Approve or reject every group for text identity, font, color, scale, position, z-order, entrance, hold, persistence, and exit.",
            "The Gabriola script font is provisional for this pilot; explicitly approve or reject its visual match.",
        ]
        instructions.write_text("\n".join(lines) + "\n", encoding="utf-8")

        manifest = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": report.get("run_id"),
            "ok": True,
            "authority_task_id": AUTHORITY_TASK_ID,
            "authority_path": str(repo_root / AUTHORITY_RELATIVE_PATH),
            "provisional_script_font_candidate_count": authority.get("summary", {}).get("provisional_script_font_candidate_count"),
            "script_font_visual_approval_required": True,
            "frame_range": [FRAME_IN, FRAME_OUT],
            "expected_frame_count": EXPECTED_FRAME_COUNT,
            "video_frame_count": next(iter(counts)),
            "video_dimensions": list(next(iter(dimensions))),
            "video_fps": {mode: readers[mode].fps for mode in MODE_ORDER},
            "renders": {
                mode: {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "sha256": raw_sha256(path),
                }
                for mode, path in render_paths.items()
            },
            "group_count": len(group_rows),
            "token_count": sum(len(row["token_ids"]) for row in group_rows),
            "groups": group_rows,
            "instructions": str(instructions),
            "visual_approval_required": True,
            "full_rollout_authorized": False,
        }
        write_json(review_dir / "review_manifest.json", manifest)
        return manifest
    finally:
        for reader in readers.values():
            reader.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = build(args.root.resolve(), args.report_dir.resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    print(f"PASS {TASK_ID}: review_groups={manifest['group_count']} renders=3")
    print(Path(manifest["instructions"]).parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
