"""Benchmark the bounded OSS routes and emit Reel #3 animation recipes."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_cloner.caption_motion_oss import (
    ROUTE_LK,
    ROUTE_TEMPLATE,
    caption_authority,
    derive_recipe,
    extract_transforms,
    select_localization_event,
)


BENCHMARK_CASES = (
    ("selected_translation", "style_event_caption_tracklet_0010"),
    ("missed_translation", "style_event_caption_tracklet_0011"),
    ("selected_scale", "style_event_caption_tracklet_0017"),
    ("missed_compound", "style_event_caption_tracklet_0041"),
    ("missed_compound_2", "style_event_caption_tracklet_0080"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _accepted_observations(event: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in (event.get("observations") or [])
        if str(row.get("observation_provenance") or "").startswith("accepted")
    ]


def _ground_truth(observations: list[dict[str, Any]], width: int, height: int) -> list[tuple[float, float, float]]:
    boxes = [row["bbox"] for row in observations]
    reference = boxes[-1]
    center = ((reference[0] + reference[2]) / 2.0, (reference[1] + reference[3]) / 2.0)
    area = max(1.0, float((reference[2] - reference[0]) * (reference[3] - reference[1])))
    return [
        (
            ((box[0] + box[2]) / 2.0 - center[0]) / width,
            ((box[1] + box[3]) / 2.0 - center[1]) / height,
            math.sqrt(max(1.0, float((box[2] - box[0]) * (box[3] - box[1]))) / area),
        )
        for box in boxes
    ]


def _translation_direction(row: tuple[float, float, float]) -> int:
    x, y, _ = row
    dominant = x if abs(x) >= abs(y) else y
    return int(dominant > 0.003) - int(dominant < -0.003)


def _scale_direction(row: tuple[float, float, float]) -> int:
    return int(row[2] > 1.05) - int(row[2] < 0.95)


def benchmark(video: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(row.get("event_id")): row for row in events}
    capture = __import__("cv2").VideoCapture(str(video))
    width = int(capture.get(__import__("cv2").CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(__import__("cv2").CAP_PROP_FRAME_HEIGHT) or 0)
    capture.release()
    routes = []
    for route in (ROUTE_LK, ROUTE_TEMPLATE):
        cases = []
        for label, event_id in BENCHMARK_CASES:
            event = by_id[event_id]
            observations = _accepted_observations(event)
            timestamps = [float(row["timestamp"]) for row in observations]
            row: dict[str, Any] = {"case": label, "event_id": event_id, "text": event.get("text"), "ok": False}
            try:
                predicted, confidence = extract_transforms(video, event, route, timestamps)
                truth = _ground_truth(observations, width, height)
                position_errors = [math.hypot(actual[0] - expected[0], actual[1] - expected[1]) for actual, expected in zip(predicted, truth)]
                scale_errors = [abs(actual[2] - expected[2]) for actual, expected in zip(predicted, truth)]
                residual = [(actual[0] - expected[0], actual[1] - expected[1]) for actual, expected in zip(predicted, truth)]
                jitter = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(residual, residual[1:])) / max(1, len(residual) - 1)
                row.update(
                    {
                        "ok": True,
                        "position_mae": round(sum(position_errors) / len(position_errors), 6),
                        "scale_mae": round(sum(scale_errors) / len(scale_errors), 6),
                        "temporal_residual_jitter": round(jitter, 6),
                        "translation_direction_match": _translation_direction(predicted[0]) == _translation_direction(truth[0]),
                        "scale_direction_match": _scale_direction(predicted[0]) == _scale_direction(truth[0]),
                        "mean_tracker_confidence": round(sum(confidence) / len(confidence), 4),
                        "compound_channels": ["position", "scale"],
                    }
                )
            except Exception as exc:
                row["failure"] = f"{type(exc).__name__}: {exc}"
            cases.append(row)
        successes = [row for row in cases if row["ok"]]
        coverage = len(successes) / len(cases)
        direction = sum(
            int(bool(row["translation_direction_match"])) + int(bool(row["scale_direction_match"]))
            for row in successes
        ) / max(1, 2 * len(successes))
        position_mae = sum(float(row["position_mae"]) for row in successes) / max(1, len(successes))
        scale_mae = sum(float(row["scale_mae"]) for row in successes) / max(1, len(successes))
        jitter = sum(float(row["temporal_residual_jitter"]) for row in successes) / max(1, len(successes))
        fidelity = 35.0 * (0.45 * coverage + 0.20 * direction + 0.20 * max(0.0, 1.0 - position_mae / 0.08) + 0.15 * max(0.0, 1.0 - scale_mae / 0.25))
        compound = 20.0 * coverage
        robustness = 15.0 * coverage * max(0.0, 1.0 - jitter / 0.08)
        fixed = {ROUTE_LK: (13.0, 9.0), ROUTE_TEMPLATE: (14.0, 8.0)}[route]
        score = fidelity + compound + robustness + fixed[0] + fixed[1] + 5.0
        routes.append(
            {
                "route": route,
                "score": round(score, 1),
                "score_breakdown": {
                    "fidelity_coverage_35": round(fidelity, 1),
                    "compound_representation_20": round(compound, 1),
                    "robustness_15": round(robustness, 1),
                    "integration_speed_15": fixed[0],
                    "runtime_compatibility_10": fixed[1],
                    "license_maintenance_5": 5.0,
                },
                "successful_cases": len(successes),
                "case_count": len(cases),
                "cases": cases,
            }
        )
    winner = max(routes, key=lambda row: row["score"])["route"]
    return {
        "schema": "video_cloner.oss002_caption_motion_benchmark",
        "schema_version": 1,
        "reel": "DZatr0EJt4B",
        "routes": routes,
        "winner": winner,
        "decision": "COMBINE",
        "decision_components": ["OpenCV motion extraction", "HyperFrames independent seekable channels", "OSS-001 Resolve nested Text+ carrier"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--fcpxml", type=Path, required=True)
    parser.add_argument("--style-evidence", type=Path, required=True)
    parser.add_argument("--targets", default="9,12,15,26")
    parser.add_argument("--benchmark-output", type=Path, required=True)
    parser.add_argument("--recipe-output", type=Path, required=True)
    args = parser.parse_args()
    style = json.loads(args.style_evidence.read_text(encoding="utf-8"))
    events = style.get("style_events") or []
    benchmark_payload = benchmark(args.video, events)
    if benchmark_payload["winner"] != ROUTE_TEMPLATE:
        raise RuntimeError(f"unexpected_winner:{benchmark_payload['winner']}")
    captions = caption_authority(args.fcpxml)
    ordinals = [int(value.strip()) for value in args.targets.split(",") if value.strip()]
    recipes = []
    for ordinal in ordinals:
        caption = captions[ordinal - 1]
        event = select_localization_event(events, ordinal)
        recipes.append(derive_recipe(args.video, caption, event, ROUTE_TEMPLATE))
    payload = {
        "schema": "video_cloner.caption_animation_recipe_set",
        "schema_version": 1,
        "reel": "DZatr0EJt4B",
        "route": ROUTE_TEMPLATE,
        "decision": "COMBINE",
        "sources": {
            "video": {"path": str(args.video), "sha256": _sha256(args.video)},
            "fcpxml": {"path": str(args.fcpxml), "sha256": _sha256(args.fcpxml)},
            "localization": {"path": str(args.style_evidence), "sha256": _sha256(args.style_evidence), "animation_classification_used": False},
            "hyperframes": {"repo": "heygen-com/hyperframes", "commit": "46f6cb356785bed79e1ce7b79d7e7accc697786a", "license": "Apache-2.0", "role": "independent seekable channel representation"},
            "opencv": {"version": __import__("cv2").__version__, "license": "Apache-2.0", "role": "multi-scale template motion extraction"},
        },
        "recipes": recipes,
    }
    benchmark_payload["inputs"] = payload["sources"]
    _write_json(args.benchmark_output, benchmark_payload)
    _write_json(args.recipe_output, payload)
    print(json.dumps({"benchmark": str(args.benchmark_output), "recipes": str(args.recipe_output), "winner": ROUTE_TEMPLATE, "recipe_count": len(recipes)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
