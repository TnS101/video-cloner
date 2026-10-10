"""Build the accepted OSS-002 motion authority for all Reel #3 captions."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_cloner.caption_motion_oss import ROUTE_TEMPLATE, caption_authority, derive_recipe, select_localization_event


LEGACY_ORDINAL = 8
REPRESENTATIVE_ORDINALS = {9, 12, 15, 26}
STEP3C_ORDINALS = {10, 13, 19, 21, 22, 24, 27, 31, 32, 52, 55, 69, 70, 73, 93}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ordinal(recipe: dict[str, Any]) -> int:
    return int(str(recipe["caption_id"]).rsplit("_", 1)[-1])


def _metrics(recipe: dict[str, Any]) -> dict[str, float]:
    positions = [tuple(float(part) for part in row["value"]) for row in recipe["channels"]["position"]]
    scales = [float(row["value"][0]) for row in recipe["channels"]["scale"]]
    position_delta = max(
        (math.dist(left, right) for index, left in enumerate(positions) for right in positions[index + 1 :]),
        default=0.0,
    )
    scale_delta = max(scales, default=1.0) - min(scales, default=1.0)
    tail_position = math.dist(positions[-2], positions[-1]) if len(positions) > 1 else 0.0
    tail_scale = abs(scales[-2] - scales[-1]) if len(scales) > 1 else 0.0
    return {
        "position_delta": round(position_delta, 6),
        "scale_delta": round(scale_delta, 6),
        "tail_position_noise": round(tail_position, 6),
        "tail_scale_noise": round(tail_scale, 6),
    }


def _robust_floor(values: list[float], minimum: float) -> float:
    if not values:
        return minimum
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    return round(max(minimum, median + 3.0 * mad), 6)


def build(video: Path, fcpxml: Path, style_evidence: Path, representatives: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    captions = caption_authority(fcpxml)
    if len(captions) != 112:
        raise ValueError(f"caption_count:{len(captions)}")
    events = json.loads(style_evidence.read_text(encoding="utf-8")).get("style_events") or []
    accepted = {
        _ordinal(row): row
        for row in json.loads(representatives.read_text(encoding="utf-8")).get("recipes") or []
    }
    if set(accepted) != REPRESENTATIVE_ORDINALS:
        raise ValueError(f"representative_authority:{sorted(accepted)}")

    recipes: list[dict[str, Any]] = []
    failures: dict[int, str] = {}
    metrics: dict[int, dict[str, float]] = {}
    for caption in captions:
        ordinal = int(caption["ordinal"])
        try:
            event = select_localization_event(events, ordinal)
            recipe = derive_recipe(video, caption, event, ROUTE_TEMPLATE)
            recipes.append(recipe)
            metrics[ordinal] = _metrics(recipe)
        except Exception as exc:
            failures[ordinal] = f"{type(exc).__name__}: {exc}"

    by_ordinal = {_ordinal(row): row for row in recipes}
    for ordinal in REPRESENTATIVE_ORDINALS:
        if ordinal not in by_ordinal or by_ordinal[ordinal]["channels"] != accepted[ordinal]["channels"]:
            raise ValueError(f"representative_recipe_changed:{ordinal}")

    confidence_floor = round(min(float(accepted[ordinal]["confidence"]) for ordinal in REPRESENTATIVE_ORDINALS) * 0.8, 4)
    stable = [
        ordinal for ordinal, recipe in by_ordinal.items()
        if int(recipe["duration"]) >= 4 and float(recipe["confidence"]) >= confidence_floor
    ]
    position_floor = _robust_floor([metrics[ordinal]["tail_position_noise"] for ordinal in stable], 2.0 / 1080.0)
    scale_floor = _robust_floor([metrics[ordinal]["tail_scale_noise"] for ordinal in stable], 0.05)

    rows = []
    meaningful = set()
    for caption in captions:
        ordinal = int(caption["ordinal"])
        recipe = by_ordinal.get(ordinal)
        row_metrics = metrics.get(ordinal, {"position_delta": 0.0, "scale_delta": 0.0})
        detected = bool(
            recipe
            and float(recipe["confidence"]) >= confidence_floor
            and (
                row_metrics["position_delta"] > position_floor
                or row_metrics["scale_delta"] > scale_floor
            )
        )
        if detected:
            meaningful.add(ordinal)
        if ordinal == LEGACY_ORDINAL:
            action = "preserve_accepted_legacy"
        elif ordinal in REPRESENTATIVE_ORDINALS:
            if not detected:
                raise ValueError(f"accepted_representative_not_meaningful:{ordinal}")
            action = "reuse_accepted_oss_representative"
        elif ordinal in STEP3C_ORDINALS:
            action = "supersede_step3c_with_oss" if detected else "remove_step3c_enable_original"
        else:
            action = "create_oss_disable_original" if detected else "keep_original_enabled"
        rows.append(
            {
                "ordinal": ordinal,
                "caption_id": caption["caption_id"],
                "text": caption["text"],
                "start_frame": caption["start_frame"],
                "duration": caption["duration"],
                "motion_detected": detected,
                "position_delta": row_metrics["position_delta"],
                "scale_delta": row_metrics["scale_delta"],
                "confidence": float(recipe["confidence"]) if recipe else None,
                "recipe_id": caption["caption_id"] if recipe else None,
                "recipe_path": "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_animation_recipes_oss002_full.json" if recipe else None,
                "action": action,
                "extraction_failure": failures.get(ordinal),
            }
        )

    counts = {
        "total_captions": 112,
        "meaningful_motion": len(meaningful),
        "static": 112 - len(meaningful),
        "extraction_failures": len(failures),
        "representatives_reused": len(REPRESENTATIVE_ORDINALS),
        "step3c_superseded": sum(row["action"] == "supersede_step3c_with_oss" for row in rows),
        "step3c_removed_static": sum(row["action"] == "remove_step3c_enable_original" for row in rows),
        "expected_final_replacements": 1 + len(meaningful - {LEGACY_ORDINAL}),
    }
    motion_rows = [row for row in rows if row["motion_detected"]]
    compound_rows = [row for row in motion_rows if row["position_delta"] > position_floor and row["scale_delta"] > scale_floor]
    translation_rows = [row for row in motion_rows if row["scale_delta"] <= scale_floor]
    scale_rows = [row for row in motion_rows if row["position_delta"] <= position_floor]

    def sample(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row[key] for key in ("ordinal", "caption_id", "text", "start_frame", "duration", "position_delta", "scale_delta", "confidence", "action")}

    review_samples = {
        "translation_heavy": sample(max(translation_rows or motion_rows, key=lambda row: row["position_delta"])),
        "scale_heavy": sample(max(scale_rows or motion_rows, key=lambda row: row["scale_delta"])),
        "compound": sample(max(compound_rows or motion_rows, key=lambda row: row["position_delta"] + row["scale_delta"])),
        "early": sample(motion_rows[0]),
        "middle": sample(min(motion_rows, key=lambda row: abs(row["start_frame"] - 336))),
        "late": sample(motion_rows[-1]),
        "newly_detected_step3c_miss": sample(next(row for row in motion_rows if row["action"] == "create_oss_disable_original")),
    }
    recipe_set = {
        "schema": "video_cloner.caption_animation_recipe_set",
        "schema_version": 1,
        "reel": "DZatr0EJt4B",
        "route": ROUTE_TEMPLATE,
        "decision": "COMBINE_ACCEPTED_FULL_ROLLOUT",
        "sources": {
            "video": {"path": str(video), "sha256": _sha256(video)},
            "fcpxml": {"path": str(fcpxml), "sha256": _sha256(fcpxml)},
            "localization": {"path": str(style_evidence), "sha256": _sha256(style_evidence), "animation_classification_used": False},
        },
        "recipes": recipes,
    }
    manifest = {
        "schema": "video_cloner.oss002_full_motion_rollout",
        "schema_version": 1,
        "reel": "DZatr0EJt4B",
        "route": ROUTE_TEMPLATE,
        "decision": "COMBINE_ACCEPTED",
        "noise_floor": {
            "method": "median_plus_3mad_of_settled_tail_steps",
            "position": position_floor,
            "scale": scale_floor,
            "confidence": confidence_floor,
            "confidence_basis": "80_percent_of_weakest_human_accepted_representative",
        },
        "counts": counts,
        "review_samples": review_samples,
        "captions": rows,
    }
    return recipe_set, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--fcpxml", type=Path, required=True)
    parser.add_argument("--style-evidence", type=Path, required=True)
    parser.add_argument("--representatives", type=Path, required=True)
    parser.add_argument("--recipe-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()
    recipes, manifest = build(args.video, args.fcpxml, args.style_evidence, args.representatives)
    _write(args.recipe_output, recipes)
    _write(args.manifest_output, manifest)
    print(json.dumps({"counts": manifest["counts"], "noise_floor": manifest["noise_floor"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
