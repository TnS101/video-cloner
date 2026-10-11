"""Apply the bounded cross-authority association to saved OSS-002B detections."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_cloner.caption_motion_oss import ROUTE_TEMPLATE, derive_recipe
from video_cloner.text_localization_oss import associate_caption, lifecycle_proposals


def _priors(events: list[dict[str, Any]], caption: dict[str, Any], fps: float) -> list[dict[str, Any]]:
    start = int(caption["start_frame"]) / fps
    end = (int(caption["start_frame"]) + int(caption["duration"])) / fps
    return [
        {"bbox": (event.get("placement") or {}).get("bbox"), "start": event.get("start"), "end": event.get("end"), "event_id": event.get("event_id")}
        for event in events
        if event.get("role") == "spoken_caption"
        and float(event.get("end") or 0.0) >= start - 0.2
        and float(event.get("start") or 0.0) <= end + 0.2
    ]


def _annotate(video: Path, rows: list[dict[str, Any]], output: Path) -> None:
    capture = cv2.VideoCapture(str(video))
    tiles = []
    try:
        for row in rows:
            evidence = ((row.get("event") or {}).get("localization_evidence") or {}).get("frames") or []
            frame_index = int(evidence[-1]["frame"]) if evidence else int(row["start_frame"])
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            if evidence:
                x1, y1, x2, y2 = (int(round(value)) for value in evidence[-1]["bbox"])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 5)
            tile = cv2.resize(frame, (360, 640))
            label = f"{row['ordinal']} {row['text']} -> {row.get('detected_phrase') or row['status']}"
            cv2.putText(tile, label[:48], (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2, cv2.LINE_AA)
            tiles.append(tile)
    finally:
        capture.release()
    if not tiles:
        return
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[index : index + 4]) for index in range(0, len(tiles), 4)])
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), sheet)


def build(video: Path, manifest_path: Path, style_path: Path, raw_path: Path, source: str, contact_sheet: Path | None = None) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    captions = manifest["captions"]
    by_ordinal = {int(row["ordinal"]): row for row in captions}
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    events = json.loads(style_path.read_text(encoding="utf-8")).get("style_events") or []
    capture = cv2.VideoCapture(str(video))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_size = (int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
    capture.release()
    rows = []
    for raw_row in raw["results"]:
        ordinal = int(raw_row["ordinal"])
        caption = by_ordinal[ordinal]
        detections = {int(frame): candidates for frame, candidates in raw_row["anchor_candidates"].items()}
        try:
            event = associate_caption(captions, caption, fps, frame_size, detections, source, _priors(events, caption, fps))
            recipe = derive_recipe(video, caption, event, ROUTE_TEMPLATE)
            rows.append(
                {
                    "ordinal": ordinal, "text": caption["text"], "start_frame": caption["start_frame"], "status": "associated",
                    "detected_phrase": event["detected_phrase"], "association_confidence": event["localization_confidence"],
                    "composition_id": event["composition_id"], "tracker_confidence": recipe["confidence"], "event": event, "recipe": recipe,
                }
            )
        except Exception as exc:
            rows.append(
                {"ordinal": ordinal, "text": caption["text"], "start_frame": caption["start_frame"], "status": "ambiguous", "error": f"{type(exc).__name__}: {exc}"}
            )
    if contact_sheet:
        _annotate(video, rows, contact_sheet)
    associated_events = [row["event"] for row in rows if row["status"] == "associated"]
    return {
        "schema": "video_cloner.oss002c_cross_authority_benchmark",
        "source": source,
        "sample_size": len(rows),
        "associated": sum(row["status"] == "associated" for row in rows),
        "ambiguous": sum(row["status"] != "associated" for row in rows),
        "lifecycle": lifecycle_proposals(associated_events, frame_size),
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--style-evidence", type=Path, required=True)
    parser.add_argument("--raw-detections", type=Path, required=True)
    parser.add_argument("--source", choices=("paddleocr_fallback", "easyocr_fallback"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contact-sheet", type=Path)
    args = parser.parse_args()
    result = build(args.video, args.manifest, args.style_evidence, args.raw_detections, args.source, args.contact_sheet)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("source", "sample_size", "associated", "ambiguous")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
