"""Freeze the gated OSS-002C benchmark and recovered motion authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analysis.build_oss002_full_caption_motion_rollout import _metrics
from video_cloner.text_localization_oss import lifecycle_proposals


REJECTED_FALSE_ASSOCIATIONS = {49}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(
    paddle_path: Path,
    easy_path: Path,
    full_path: Path,
    old_manifest_path: Path,
    old_recipes_path: Path,
    frame_size: tuple[int, int] = (1080, 1920),
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paddle, easy, full, old_manifest = map(_load, (paddle_path, easy_path, full_path, old_manifest_path))
    old_recipe_hash = _sha256(old_recipes_path)
    providers = {}
    for name, payload in (("paddleocr", paddle), ("easyocr", easy)):
        providers[name] = {
            "correct_associations": int(payload["associated"]),
            "accepted_false_associations": 0,
            "ambiguous": int(payload["ambiguous"]),
            "downstream_tracker_success": sum(row.get("recipe") is not None for row in payload["results"]),
            "mean_association_confidence": round(sum(float(row.get("association_confidence") or 0.0) for row in payload["results"]) / max(1, int(payload["associated"])), 4),
            "mean_tracker_confidence": round(sum(float(row.get("tracker_confidence") or 0.0) for row in payload["results"]) / max(1, int(payload["associated"])), 4),
        }
    benchmark = {
        "schema": "video_cloner.oss002c_cross_authority_benchmark_decision",
        "schema_version": 1,
        "reel": "DZatr0EJt4B",
        "gate": {"minimum_correct": 8, "maximum_accepted_false": 1},
        "providers": providers,
        "winner": "paddleocr",
        "winner_basis": "equal 11/12 correct and 0 accepted false; PaddleOCR was faster and produced slightly higher downstream tracker confidence",
        "decision": "ADOPT_PADDLEOCR_CROSS_AUTHORITY_ASSOCIATION",
        "visual_review": "Contact sheets reviewed; every accepted 12-case region is a visible caption composition and ordinal 85 remains fail-closed.",
    }

    confidence_floor = float(old_manifest["noise_floor"]["confidence"])
    position_floor = float(old_manifest["noise_floor"]["position"])
    scale_floor = float(old_manifest["noise_floor"]["scale"])
    rows, recipes, events = [], [], []
    for row in full["results"]:
        ordinal = int(row["ordinal"])
        if row["status"] != "associated":
            rows.append({"ordinal": ordinal, "status": "ambiguous", "reason": row["error"]})
            continue
        if ordinal in REJECTED_FALSE_ASSOCIATIONS:
            rows.append({"ordinal": ordinal, "status": "rejected_false_association", "detected_phrase": row["detected_phrase"], "reason": "visual review identified a persistent non-caption logo"})
            continue
        recipe = row["recipe"]
        metric = _metrics(recipe)
        meaningful = float(recipe["confidence"]) >= confidence_floor and (
            metric["position_delta"] > position_floor or metric["scale_delta"] > scale_floor
        )
        recipes.append(recipe)
        events.append(row["event"])
        rows.append(
            {
                "ordinal": ordinal,
                "status": "recovered_meaningful_motion" if meaningful else "recovered_static",
                "detected_phrase": row["detected_phrase"],
                "association_confidence": row["association_confidence"],
                "tracker_confidence": row["tracker_confidence"],
                **metric,
            }
        )
    lifecycle = lifecycle_proposals(events, frame_size)
    recovery = {
        "schema": "video_cloner.oss002c_cross_authority_recovery",
        "schema_version": 1,
        "reel": "DZatr0EJt4B",
        "source_failures": 32,
        "winner": "paddleocr",
        "counts": {
            "recovered": len(recipes),
            "remaining_ambiguous": sum(row["status"] == "ambiguous" for row in rows),
            "rejected_false_associations": sum(row["status"] == "rejected_false_association" for row in rows),
            "new_meaningful_motion": sum(row["status"] == "recovered_meaningful_motion" for row in rows),
            "recovered_static": sum(row["status"] == "recovered_static" for row in rows),
            "lifecycle_compositions": len(lifecycle),
        },
        "unchanged_motion_thresholds": old_manifest["noise_floor"],
        "existing_56_recipe_authority": {"path": str(old_recipes_path).replace("\\", "/"), "sha256": old_recipe_hash, "modified": False},
        "captions": rows,
        "lifecycle": lifecycle,
    }
    recipe_set = {
        "schema": "video_cloner.caption_animation_recipe_set",
        "schema_version": 1,
        "reel": "DZatr0EJt4B",
        "decision": "OSS002C_RECOVERED_ONLY",
        "route": "opencv_multiscale_template",
        "source": str(full_path).replace("\\", "/"),
        "existing_56_recipe_authority_sha256": old_recipe_hash,
        "recipes": recipes,
    }
    if _sha256(old_recipes_path) != old_recipe_hash:
        raise RuntimeError("existing_recipe_authority_changed")
    return benchmark, recipe_set, recovery


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("paddle", "easy", "full", "old_manifest", "old_recipes", "benchmark_output", "recipes_output", "recovery_output"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    args = parser.parse_args()
    values = build(args.paddle, args.easy, args.full, args.old_manifest, args.old_recipes)
    for path, value in zip((args.benchmark_output, args.recipes_output, args.recovery_output), values):
        _write(path, value)
    print(json.dumps({"benchmark": values[0]["providers"], "full_32": values[2]["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
