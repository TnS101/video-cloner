from __future__ import annotations

import argparse
import json
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_SOURCE_BACKED_TEMPORAL_RECOVERY_V1"
ARCHITECTURE_FAMILY = "stabilized_source_backed_person_then_background_v1"
CLOSED_ARCHITECTURE_FAMILY = "propainter_semantic_split_person_repair_v1"
VISUAL_FAIL_STOP = "stop_current_family_no_mask_parameter_retry"
EXPECTED_FRAMES = list(range(429, 453))
HOLD_SENTINELS = (434, 438, 443, 448)
REFERENCE_FRAME = 443
EXPECTED_SOURCE_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
EXPECTED_SOURCE_RANGE = [537, 564]
EXPECTED_CROP = [284, 620, 796, 940]
PAIRWISE_MIN_INLIERS = 40
PAIRWISE_MAX_MEDIAN_ERROR = 1.25
PAIRWISE_MIN_SCALE = 0.97
PAIRWISE_MAX_SCALE = 1.03
PAIRWISE_MAX_ROTATION_DEGREES = 2.0
MIN_ANY_COVERAGE = 0.83
MIN_TWO_OBSERVATION_COVERAGE = 0.75
MAX_MODEL_UNRESOLVED = 0.25
MIN_PERSON_SEED_DELTA_MAE = 2.0
MIN_SAFE_GLYPH_PIXELS = 4000
MIN_SOURCE_GLYPH_BEFORE_DARK_RATIO = 0.35
MAX_SOURCE_GLYPH_AFTER_DARK_RATIO = 0.20
MIN_SOURCE_GLYPH_RELATIVE_REDUCTION = 0.70
MIN_RIGHT_SOURCE_DARK_PIXELS = 3000
MAX_RIGHT_DARK_SURVIVAL = 0.25
MIN_RIGHT_DARK_REMOVAL = 0.75


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValidationError(f"expected JSON object: {path}")
    return value


def _frame_map(rows, name: str) -> dict[int, dict]:
    if not isinstance(rows, list):
        raise ValidationError(f"{name} missing")
    result = {
        int(row["timeline_frame"]): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("timeline_frame"), int)
    }
    if sorted(result) != EXPECTED_FRAMES:
        raise ValidationError(f"{name} frame set mismatch: {sorted(result)}")
    return result


def _relative_reduction(before: float, after: float) -> float:
    if before <= 0.0:
        return 0.0
    return (before - after) / before


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).resolve()
    result_path = artifact_dir / "PROOF_RUN_RESULT.json"
    validation_path = artifact_dir / "PROOF_VALIDATION.json"
    report_path = artifact_dir / "FINAL_REPORT.md"
    checks: dict[str, object] = {}
    errors: list[str] = []

    try:
        result = load_json(result_path)
        checks["task_id"] = result.get("task_id") == TASK_ID
        checks["runner_ok"] = result.get("ok") is True
        checks["proof_only_mode"] = result.get("mode") == "offline_source_backed_temporal_recovery_proof_only"
        checks["no_resolve"] = (
            result.get("resolve_invocations") == 0
            and result.get("save_project_calls") == 0
            and result.get("timeline_mutations") == 0
        )
        checks["source_window"] = (
            result.get("source_window") == [429, 453]
            and result.get("frame_count") == 24
            and result.get("reference_frame") == REFERENCE_FRAME
        )

        iteration_guard = result.get("iteration_guard") or {}
        checks["anti_loop_guard"] = (
            iteration_guard.get("closed_architecture_family") == CLOSED_ARCHITECTURE_FAMILY
            and iteration_guard.get("closed_reason") == "V9 technical PASS received human visual FAIL"
            and iteration_guard.get("current_architecture_family") == ARCHITECTURE_FAMILY
            and iteration_guard.get("reopens_closed_family") is False
            and iteration_guard.get("same_family_visual_retry_allowed") is False
            and iteration_guard.get("on_visual_fail") == VISUAL_FAIL_STOP
        )

        architecture = result.get("architecture") or {}
        checks["new_architecture_contract"] = (
            architecture.get("family") == ARCHITECTURE_FAMILY
            and architecture.get("person_recovery")
            == "pairwise_lk_ransac_stabilization_plus_real_temporal_pixel_plate_then_propainter_residual"
            and architecture.get("background_recovery") == "second_propainter_pass_after_person_cleanup"
            and architecture.get("same_family_mask_tuning_retry") is False
            and architecture.get("stabilized_crop") == EXPECTED_CROP
            and architecture.get("source_backed_known_min_observations") == 2
            and float(architecture.get("min_any_source_backed_coverage", 0.0)) == MIN_ANY_COVERAGE
            and float(architecture.get("min_two_observation_source_backed_coverage", 0.0))
            == MIN_TWO_OBSERVATION_COVERAGE
        )

        authority = result.get("source_authority") or {}
        checks["source_authority"] = (
            authority.get("source_video") == "input/DZsqH7auhjt.mp4"
            and authority.get("source_video_sha256") == EXPECTED_SOURCE_SHA256
            and float(authority.get("source_video_fps", 0.0)) == 30.0
            and authority.get("source_visible_range") == EXPECTED_SOURCE_RANGE
            and isinstance(authority.get("foreground_manifest_sha256"), str)
            and len(authority.get("foreground_manifest_sha256")) == 64
        )

        alignment_rows = result.get("alignment_rows")
        if not isinstance(alignment_rows, list) or len(alignment_rows) != 23:
            raise ValidationError("alignment_rows must contain 23 adjacent-frame transforms")
        expected_pairs = [(frame, frame + 1) for frame in range(429, 452)]
        actual_pairs = [(row.get("from_frame"), row.get("to_frame")) for row in alignment_rows if isinstance(row, dict)]
        checks["alignment_sequence"] = actual_pairs == expected_pairs
        checks["alignment_quality"] = all(
            int(row.get("inliers", 0)) >= PAIRWISE_MIN_INLIERS
            and float(row.get("median_reprojection_error_process_pixels", 99.0)) <= PAIRWISE_MAX_MEDIAN_ERROR
            and PAIRWISE_MIN_SCALE <= float(row.get("scale", 0.0)) <= PAIRWISE_MAX_SCALE
            and abs(float(row.get("rotation_degrees", 99.0))) <= PAIRWISE_MAX_ROTATION_DEGREES
            for row in alignment_rows
        )

        coverage = _frame_map(result.get("coverage_rows"), "coverage_rows")
        checks["source_backed_recoverability"] = all(
            float(coverage[frame].get("source_backed_any_fraction", 0.0)) >= MIN_ANY_COVERAGE
            and float(coverage[frame].get("source_backed_two_observation_fraction", 0.0))
            >= MIN_TWO_OBSERVATION_COVERAGE
            and float(coverage[frame].get("model_unresolved_fraction", 1.0)) <= MAX_MODEL_UNRESOLVED
            for frame in EXPECTED_FRAMES
        )

        input_rows = _frame_map(result.get("input_frames"), "input_frames")
        checks["input_authority_nonempty"] = all(
            int(input_rows[frame].get("score_mask_pixels", 0)) > 0
            and int(input_rows[frame].get("person_glyph_seed_pixels", 0)) >= 2500
            and int(input_rows[frame].get("compact_source_mask_pixels", 0)) > 0
            and int(input_rows[frame].get("row_filled_mask_pixels", 0)) > 0
            for frame in EXPECTED_FRAMES
        )

        person_rows = _frame_map(result.get("person_pass_rows"), "person_pass_rows")
        checks["protected_person_exact"] = all(
            int(person_rows[frame].get("protected_person_context_changed_pixels", -1)) == 0
            for frame in EXPECTED_FRAMES
        )
        checks["person_overlap_actually_repaired"] = all(
            float(person_rows[frame].get("person_seed_delta_mae", 0.0)) >= MIN_PERSON_SEED_DELTA_MAE
            for frame in HOLD_SENTINELS
        )

        metrics = _frame_map(result.get("frame_metrics"), "frame_metrics")
        checks["outside_authority_exact"] = all(
            int(metrics[frame].get("outside_changed_pixels", -1)) == 0 for frame in EXPECTED_FRAMES
        )
        checks["protected_person_final_exact"] = all(
            int(metrics[frame].get("person_context_changed_pixels", -1)) == 0 for frame in EXPECTED_FRAMES
        )
        checks["coverage_serialized_into_metrics"] = all(
            float(metrics[frame].get("source_backed_any_fraction", 0.0)) >= MIN_ANY_COVERAGE
            and float(metrics[frame].get("source_backed_two_observation_fraction", 0.0))
            >= MIN_TWO_OBSERVATION_COVERAGE
            for frame in EXPECTED_FRAMES
        )

        glyph_rows = []
        right_rows = []
        for frame in HOLD_SENTINELS:
            row = metrics[frame]
            before = float(row.get("safe_glyph_dark_ratio_lt140_before", 0.0))
            after = float(row.get("safe_glyph_dark_ratio_lt140_after", 1.0))
            rel = _relative_reduction(before, after)
            glyph_rows.append(
                {
                    "timeline_frame": frame,
                    "before_dark_ratio": before,
                    "after_dark_ratio": after,
                    "relative_reduction": rel,
                    "pass": (
                        int(row.get("safe_glyph_score_pixels", 0)) >= MIN_SAFE_GLYPH_PIXELS
                        and before >= MIN_SOURCE_GLYPH_BEFORE_DARK_RATIO
                        and after <= MAX_SOURCE_GLYPH_AFTER_DARK_RATIO
                        and rel >= MIN_SOURCE_GLYPH_RELATIVE_REDUCTION
                    ),
                }
            )
            survival = float(row.get("right_source_dark_survival_lt140", 1.0))
            removal = float(row.get("right_source_dark_removal", 0.0))
            right_rows.append(
                {
                    "timeline_frame": frame,
                    "source_dark_pixels": int(row.get("right_source_dark_pixels", 0)),
                    "survival": survival,
                    "removal": removal,
                    "pass": (
                        int(row.get("right_source_dark_pixels", 0)) >= MIN_RIGHT_SOURCE_DARK_PIXELS
                        and survival <= MAX_RIGHT_DARK_SURVIVAL
                        and removal >= MIN_RIGHT_DARK_REMOVAL
                    ),
                }
            )
        checks["source_glyph_gate"] = all(row["pass"] for row in glyph_rows)
        checks["right_glyph_gate"] = all(row["pass"] for row in right_rows)

        artifact_contract = result.get("artifacts") or {}
        expected_artifacts = {
            "comparison_video": "COME_BEFORE_AFTER_SOURCE_BACKED_TEMPORAL_V1.mp4",
            "before_after_contact_sheet": "BEFORE_AFTER_CONTACT_SHEET.png",
            "stabilization_contact_sheet": "STABILIZATION_CONTACT_SHEET.png",
            "source_backed_person_plate": "STABILIZED_SOURCE_BACKED_PERSON_PLATE.png",
            "person_log": "PROPAINTER_PERSON_RUN.log",
            "background_log": "PROPAINTER_BACKGROUND_RUN.log",
            "final_frames": "inpainted_frames",
        }
        checks["artifact_contract"] = artifact_contract == expected_artifacts
        required_files = [
            artifact_dir / expected_artifacts["comparison_video"],
            artifact_dir / expected_artifacts["before_after_contact_sheet"],
            artifact_dir / expected_artifacts["stabilization_contact_sheet"],
            artifact_dir / expected_artifacts["source_backed_person_plate"],
            artifact_dir / expected_artifacts["person_log"],
            artifact_dir / expected_artifacts["background_log"],
        ]
        final_dir = artifact_dir / expected_artifacts["final_frames"]
        final_files = sorted(final_dir.glob("frame_*.png")) if final_dir.is_dir() else []
        checks["required_artifacts"] = all(path.is_file() and path.stat().st_size > 0 for path in required_files)
        checks["final_frame_artifacts"] = (
            len(final_files) == 24
            and [path.name for path in final_files] == [f"frame_{frame:06d}.png" for frame in EXPECTED_FRAMES]
            and all(path.stat().st_size > 0 for path in final_files)
        )
        checks["visual_approval_required"] = result.get("visual_approval_required") is True

    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        result = {}
        glyph_rows = []
        right_rows = []

    failed_checks = [name for name, passed in checks.items() if passed is not True]
    technical_pass = not errors and not failed_checks
    status = "technical_pass_visual_pending" if technical_pass else "technical_fail"
    validation = {
        "task_id": TASK_ID,
        "status": status,
        "technical_pass": technical_pass,
        "visual_approval_required": True,
        "architecture_family": ARCHITECTURE_FAMILY,
        "checks": checks,
        "failed_checks": failed_checks,
        "errors": errors,
        "source_glyph_sentinels": glyph_rows,
        "right_glyph_sentinels": right_rows,
        "anti_loop": {
            "v9_mask_tuning_family_reopened": False,
            "this_is_a_distinct_architecture": True,
            "on_visual_fail": "return exact visual evidence; do not convert technical PASS into Resolve authority",
        },
    }
    validation_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")

    report_lines = [
        f"# {TASK_ID}",
        "",
        f"Status: **{status}**",
        "",
        "This proof uses source-backed temporal person recovery before a separate background ProPainter pass.",
        "It does not authorize Resolve integration without human visual approval.",
        "",
        f"Technical pass: `{str(technical_pass).lower()}`",
        f"Failed checks: `{failed_checks}`",
        f"Errors: `{errors}`",
        "",
        "## Source-backed recovery",
    ]
    if isinstance(result, dict):
        coverage_rows = result.get("coverage_rows") or []
        if coverage_rows:
            report_lines.extend(
                [
                    f"- Minimum any-donor coverage: `{min(float(row['source_backed_any_fraction']) for row in coverage_rows):.6f}`",
                    f"- Minimum two-donor coverage: `{min(float(row['source_backed_two_observation_fraction']) for row in coverage_rows):.6f}`",
                    f"- Maximum model-unresolved fraction: `{max(float(row['model_unresolved_fraction']) for row in coverage_rows):.6f}`",
                ]
            )
    report_lines.extend(
        [
            "",
            "## Stop boundary",
            "",
            "- Technical FAIL: stop on the first exact gate/evidence; do not invoke Resolve.",
            "- Technical PASS: stop for human visual review.",
            "- Human visual FAIL: preserve the accepted Resolve baseline and return exact failing frames; do not claim this proof as authority.",
            "",
        ]
    )
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print(json.dumps(validation, indent=2))
    return 0 if technical_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
