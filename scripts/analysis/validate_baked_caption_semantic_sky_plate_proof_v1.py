from __future__ import annotations

import argparse
import json
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_SEMANTIC_SKY_PLATE_PROOF_V1"
EXPECTED_FRAMES = list(range(429, 453))
HOLD_SENTINELS = (434, 438, 443, 448)
MAX_DYNAMIC_RIGHT_GUARD_PIXELS = 180
MIN_SCORE_MASK_COVERAGE = 0.92
MIN_REMOVAL_PIXELS = 15_000


class ValidationError(RuntimeError):
    pass


def evaluate(payload: dict, artifact_dir: Path) -> dict:
    checks: dict[str, bool] = {}
    checks["task_id"] = payload.get("task_id") == TASK_ID
    checks["runner_ok"] = payload.get("ok") is True
    checks["proof_only_mode"] = payload.get("mode") == "offline_semantic_person_sky_plate_proof_only"
    checks["no_resolve"] = payload.get("resolve_invocations") == 0 and payload.get("save_project_calls") == 0
    checks["no_timeline_mutation"] = payload.get("timeline_mutations") == 0
    checks["source_window"] = payload.get("source_window") == [429, 453] and payload.get("frame_count") == 24

    model = payload.get("semantic_person_model") or {}
    weight = model.get("weight_file") or {}
    checks["maskrcnn_model_contract"] = (
        model.get("model") == "torchvision.models.detection.maskrcnn_resnet50_fpn_v2"
        and model.get("weights") == "MaskRCNN_ResNet50_FPN_V2_Weights.COCO_V1"
        and model.get("person_label") == 1
        and float(model.get("score_min", 0.0)) == 0.75
        and float(model.get("mask_threshold", 0.0)) == 0.50
        and int(model.get("guard_dilation_pixels", -1)) == 4
        and isinstance(weight.get("sha256"), str)
        and len(weight.get("sha256")) == 64
        and int(weight.get("bytes", 0)) >= 150_000_000
        and str(model.get("gpu") or "").lower().find("5070") >= 0
    )

    sky = payload.get("sky_plate") or {}
    checks["sky_plate_contract"] = (
        sky.get("strategy") == "same_frame_rowwise_sky_interpolation_inside_come_authority_minus_semantic_person_v1"
        and int(sky.get("semantic_authority_dilation_pixels", -1)) == 3
        and int(sky.get("max_dynamic_right_guard_pixels", -1)) == MAX_DYNAMIC_RIGHT_GUARD_PIXELS
        and float(sky.get("min_score_mask_coverage", 0.0)) == MIN_SCORE_MASK_COVERAGE
        and sky.get("person_pixels_are_exact_source") is True
        and sky.get("outside_authority_pixels_are_exact_source") is True
    )

    frame_rows = payload.get("frame_metrics")
    if not isinstance(frame_rows, list):
        raise ValidationError("frame_metrics missing")
    by_frame = {int(row["timeline_frame"]): row for row in frame_rows if isinstance(row, dict) and "timeline_frame" in row}
    checks["all_frames_present"] = sorted(by_frame) == EXPECTED_FRAMES
    checks["outside_authority_exact"] = all(int(by_frame[f].get("outside_changed_pixels", -1)) == 0 for f in EXPECTED_FRAMES)
    checks["person_exact"] = all(int(by_frame[f].get("person_changed_pixels", -1)) == 0 for f in EXPECTED_FRAMES)
    checks["semantic_authority_bounds"] = all(
        0 <= int(by_frame[f].get("dynamic_right_guard_pixels", -1)) <= MAX_DYNAMIC_RIGHT_GUARD_PIXELS
        and float(by_frame[f].get("score_mask_coverage", 0.0)) >= MIN_SCORE_MASK_COVERAGE
        and int(by_frame[f].get("removal_pixels", 0)) >= MIN_REMOVAL_PIXELS
        for f in EXPECTED_FRAMES
    )
    checks["person_detection_all_frames"] = all(
        float(by_frame[f].get("person_score", 0.0)) >= 0.75
        and int(by_frame[f].get("person_mask_area", 0)) >= 90_000
        and int(by_frame[f].get("person_roi_overlap", 0)) >= 40_000
        for f in EXPECTED_FRAMES
    )

    glyph_rows = []
    for frame in HOLD_SENTINELS:
        row = by_frame[frame]
        before = float(row.get("safe_glyph_dark_ratio_lt140_before", 0.0))
        after = float(row.get("safe_glyph_dark_ratio_lt140_after", 1.0))
        relative = ((before - after) / before) if before > 1e-9 else 0.0
        glyph_rows.append(
            {
                "timeline_frame": frame,
                "before": before,
                "after": after,
                "relative_reduction": relative,
                "pass": before >= 0.30 and after <= 0.20 and relative >= 0.70,
            }
        )
    checks["hold_sentinel_source_glyph_reduction"] = all(row["pass"] for row in glyph_rows)

    right_rows = []
    for frame in HOLD_SENTINELS:
        row = by_frame[frame]
        source_dark = int(row.get("right_source_dark_pixels", 0))
        survival = float(row.get("right_source_dark_survival_lt140", 1.0))
        removal = 1.0 - survival
        right_rows.append(
            {
                "timeline_frame": frame,
                "source_dark_pixels": source_dark,
                "dark_survival_ratio": survival,
                "dark_removal_ratio": removal,
                "pass": source_dark >= 2500 and survival <= 0.25 and removal >= 0.75,
            }
        )
    checks["hold_sentinel_right_glyph_removal"] = all(row["pass"] for row in right_rows)

    artifacts = {
        "COME_BEFORE_AFTER_PROOF_V6.mp4": 10_000,
        "BEFORE_AFTER_CONTACT_SHEET.png": 1_000,
        "MASK_CONTACT_SHEET.png": 1_000,
        "PERSON_MASK_CONTACT_SHEET.png": 1_000,
    }
    artifact_checks = {
        name: (artifact_dir / name).is_file() and (artifact_dir / name).stat().st_size >= minimum
        for name, minimum in artifacts.items()
    }
    checks["required_artifacts"] = all(artifact_checks.values())
    outputs = artifact_dir / "semantic_sky_frames"
    person_masks = artifact_dir / "person_masks"
    authority_masks = artifact_dir / "semantic_authority_masks"
    checks["output_frame_count"] = outputs.is_dir() and len(list(outputs.glob("frame_*.png"))) == 24
    checks["person_mask_count"] = person_masks.is_dir() and len(list(person_masks.glob("person_*.png"))) == 24
    checks["authority_mask_count"] = authority_masks.is_dir() and len(list(authority_masks.glob("authority_*.png"))) == 24

    technical_pass = all(value is True for value in checks.values())
    return {
        "task_id": TASK_ID,
        "status": "technical_pass_visual_pending" if technical_pass else "technical_fail",
        "technical_pass": technical_pass,
        "visual_approval_required": True,
        "checks": checks,
        "hold_sentinels": glyph_rows,
        "right_glyph_sentinels": right_rows,
        "artifact_checks": artifact_checks,
        "non_goal": "This proof does not authorize Resolve integration or any broader baked-caption rollout.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    artifact_dir = Path(args.artifact_dir).resolve()
    source = artifact_dir / "SEMANTIC_SKY_PROOF_RESULT.json"
    validation_path = artifact_dir / "PROOF_VALIDATION.json"
    report_path = artifact_dir / "FINAL_REPORT.md"
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValidationError("semantic proof result is not an object")
        result = evaluate(payload, artifact_dir)
        validation_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {TASK_ID}",
            "",
            f"Technical status: **{result['status']}**",
            "",
            "This is an offline semantic-person sky-plate proof only. Resolve was not invoked and no timeline was modified.",
            "",
            "## Technical checks",
        ]
        for key, value in result["checks"].items():
            lines.append(f"- {key}: {'PASS' if value else 'FAIL'}")
        lines += [
            "",
            "## Required human gate",
            "",
            "Inspect `COME_BEFORE_AFTER_PROOF_V6.mp4`, `BEFORE_AFTER_CONTACT_SHEET.png`, `MASK_CONTACT_SHEET.png`, and `PERSON_MASK_CONTACT_SHEET.png`.",
            "Approve only if baked COME is removed with no hair/face damage, no letter-shaped residue, no rectangular sky patches, no seams, and no temporal flicker.",
            "No Resolve integration is authorized by this report alone.",
            "",
        ]
        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0 if result["technical_pass"] else 1
    except Exception as exc:
        result = {
            "task_id": TASK_ID,
            "status": "technical_fail",
            "technical_pass": False,
            "visual_approval_required": True,
            "errors": [repr(exc)],
        }
        validation_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        report_path.write_text(f"# {TASK_ID}\n\nTechnical status: **technical_fail**\n\nError: `{repr(exc)}`\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
