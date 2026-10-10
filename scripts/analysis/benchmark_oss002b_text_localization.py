"""Benchmark one OSS text-localization provider on fixed Reel #3 failures."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import cv2


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_cloner.caption_motion_oss import ROUTE_TEMPLATE, derive_recipe
from video_cloner.text_localization_oss import anchor_frames, easyocr_candidates, fallback_event, paddleocr_candidates, rank_candidates


SAMPLE_ORDINALS = (2, 4, 30, 38, 44, 54, 75, 80, 85, 97, 100, 110)


def _frames(video: Path, indexes: set[int]) -> tuple[dict[int, Any], float, tuple[int, int]]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"video_open:{video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    size = (int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    rows = {}
    try:
        for index in sorted(indexes):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f"video_frame:{index}")
            rows[index] = frame
    finally:
        capture.release()
    return rows, fps, size


def _prior(events: list[dict[str, Any]], caption: dict[str, Any], fps: float) -> list[object] | None:
    target = (int(caption["start_frame"]) + int(caption["duration"]) / 2.0) / fps
    candidates = []
    for event in events:
        bbox = (event.get("placement") or {}).get("bbox")
        if event.get("role") == "spoken_caption" and isinstance(bbox, list) and len(bbox) == 4:
            midpoint = (float(event.get("start") or 0.0) + float(event.get("end") or 0.0)) / 2.0
            candidates.append((abs(midpoint - target), bbox))
    return min(candidates, default=(0.0, None), key=lambda row: row[0])[1]


def build(provider: str, video: Path, manifest_path: Path, style_path: Path, ordinals: tuple[int, ...]) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_ordinal = {int(row["ordinal"]): row for row in manifest["captions"]}
    captions = [by_ordinal[ordinal] for ordinal in ordinals]
    if any(not row.get("extraction_failure") for row in captions):
        raise ValueError("benchmark_requires_failures")
    frames, fps, size = _frames(video, {frame for caption in captions for frame in anchor_frames(caption)})
    if provider == "easyocr":
        import easyocr

        engine = easyocr.Reader(["en"], gpu=False, verbose=False)
        detect = easyocr_candidates
        source = "easyocr_fallback"
    elif provider == "paddleocr":
        from paddleocr import PaddleOCR

        engine = PaddleOCR(lang="en", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, device="cpu")
        detect = paddleocr_candidates
        source = "paddleocr_fallback"
    else:
        raise ValueError(f"provider:{provider}")
    started = time.perf_counter()
    detections = {index: detect(engine, frame) for index, frame in frames.items()}
    elapsed = time.perf_counter() - started
    events = json.loads(style_path.read_text(encoding="utf-8")).get("style_events") or []
    rows = []
    for caption in captions:
        prior = _prior(events, caption, fps)
        evidence = {
            str(frame): rank_candidates(str(caption["text"]), detections.get(frame) or [], size, prior)[:3]
            for frame in anchor_frames(caption)
        }
        try:
            event = fallback_event(caption, fps, size, detections, source, prior)
            recipe = derive_recipe(video, caption, event, ROUTE_TEMPLATE)
            positions = [key["value"] for key in recipe["channels"]["position"]]
            scales = [float(key["value"][0]) for key in recipe["channels"]["scale"]]
            plausible = max((abs(float(value)) for pair in positions for value in pair), default=0.0) <= 0.5 and min(scales) >= 0.5 and max(scales) <= 1.5
            rows.append({
                "ordinal": int(caption["ordinal"]), "text": caption["text"], "status": "recovered",
                "localization_confidence": event["localization_confidence"], "event": event,
                "tracker_confidence": recipe["confidence"], "motion_plausible": plausible, "anchor_candidates": evidence,
            })
        except Exception as exc:
            rows.append({"ordinal": int(caption["ordinal"]), "text": caption["text"], "status": "failed", "error": f"{type(exc).__name__}: {exc}", "anchor_candidates": evidence})
    return {
        "schema": "video_cloner.oss002b_text_localization_benchmark",
        "provider": provider,
        "sample_ordinals": list(ordinals),
        "sample_size": len(ordinals),
        "unique_anchor_frames": len(frames),
        "runtime_seconds": round(elapsed, 3),
        "recovered": sum(row["status"] == "recovered" for row in rows),
        "downstream_tracker_success": sum(row.get("motion_plausible") is True for row in rows),
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("easyocr", "paddleocr"), required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--style-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ordinals", nargs="*", type=int, default=SAMPLE_ORDINALS)
    args = parser.parse_args()
    result = build(args.provider, args.video, args.manifest, args.style_evidence, tuple(args.ordinals))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("provider", "sample_size", "unique_anchor_frames", "runtime_seconds", "recovered", "downstream_tracker_success")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
