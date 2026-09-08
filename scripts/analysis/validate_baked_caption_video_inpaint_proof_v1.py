from __future__ import annotations

import argparse
import json
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_VIDEO_INPAINT_PROOF_V9"
EXPECTED_FRAMES = list(range(429, 453))
HOLD_SENTINELS = [434, 438, 443, 448]
EXPECTED_SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
MAX_DYNAMIC_RIGHT_GUARD_PIXELS = 180
MAX_COMPACT_VS_LEGACY_SOLID_RATIO = 0.90
MIN_SCORE_MASK_COVERAGE = 0.84
MIN_INFERENCE_BRIDGE_ADDED_PIXELS = 2000
MIN_INFERENCE_BRIDGE_ROWS = 80
PERSON_REPAIR_DILATION_PIXELS = 3
PERSON_REPAIR_FEATHER_SIGMA = 1.5
MAX_PERSON_REPAIR_AUTHORITY_RATIO = 0.05
MIN_PERSON_GLYPH_SEED_PIXELS = 4000
MIN_PERSON_GLYPH_DELTA_MAE = 2.0
TAIL_BACKGROUND_START_FRAME = 451
ARCHITECTURE_FAMILY = "propainter_semantic_split_person_repair_v1"
ARCHITECTURE_STOP = "stop_architecture_family_no_v10_mask_dilation_feather_threshold_retry"


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValidationError(f"expected JSON object: {path}")
    return value


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
        checks["proof_only_mode"] = result.get("mode") == "offline_video_inpainting_proof_only"
        checks["no_resolve"] = result.get("resolve_invocations") == 0 and result.get("save_project_calls") == 0
        checks["no_timeline_mutation"] = result.get("timeline_mutations") == 0
        checks["source_window"] = result.get("source_window") == [429, 453] and result.get("frame_count") == 24

        temporal_context = result.get("temporal_context") or {}
        context_rows = temporal_context.get("rows") or []
        checks["temporal_context_strategy"] = temporal_context.get("strategy") == "target_only_no_clean_same_shot_context_v1"
        checks["temporal_context_source_authority"] = (
            temporal_context.get("source_video") == "input/DZsqH7auhjt.mp4"
            and temporal_context.get("source_video_sha256") == EXPECTED_SOURCE_VIDEO_SHA256
            and float(temporal_context.get("source_video_fps", 0.0)) == 30.0
            and temporal_context.get("source_visible_range") == [537, 564]
        )
        checks["target_only_inference_sequence"] = (
            temporal_context.get("pre_context_source_frames") == []
            and temporal_context.get("post_context_source_frames") == []
            and temporal_context.get("context_mask_pixels") == 0
            and context_rows == []
            and result.get("inference_frame_count") == 24
        )

        mask_authority = result.get("mask_authority") or {}
        checks["semantic_split_inference_contract"] = (
            mask_authority.get("inpaint_mask_strategy")
            == "row_filled_background_plus_source_glyph_person_repair_v1"
            and mask_authority.get("composite_mask_strategy")
            == "semantic_split_person_repair_tail_feather_v1"
            and mask_authority.get("inference_person_veto") is True
            and mask_authority.get("person_inference_mode") == "veto_except_source_glyph_repair"
            and mask_authority.get("final_person_veto") is True
            and mask_authority.get("foreground_person_authority_strategy")
            == "accepted_v4_person_masks_canonical_humanseg_plus_global_affine_v1"
            and mask_authority.get("person_repair_dilation_pixels") == PERSON_REPAIR_DILATION_PIXELS
            and float(mask_authority.get("person_repair_feather_sigma", 0.0)) == PERSON_REPAIR_FEATHER_SIGMA
            and float(mask_authority.get("max_person_repair_authority_ratio", 1.0))
            == MAX_PERSON_REPAIR_AUTHORITY_RATIO
            and mask_authority.get("min_person_glyph_seed_pixels") == MIN_PERSON_GLYPH_SEED_PIXELS
            and mask_authority.get("tail_background_start_frame") == TAIL_BACKGROUND_START_FRAME
            and mask_authority.get("tail_background_close_kernel") == [81, 7]
            and mask_authority.get("tail_background_dilation_pixels") == 4
            and float(mask_authority.get("tail_background_feather_sigma", 0.0)) == 3.0
            and mask_authority.get("composite_alpha_min") == 8
            and isinstance(mask_authority.get("foreground_manifest_sha256"), str)
            and len(mask_authority.get("foreground_manifest_sha256")) == 64
        )
        checks["compact_mask_contract"] = (
            mask_authority.get("max_composite_right_glyph_guard_pixels") == 180
            and mask_authority.get("compact_hull_min_component_area") == 50
            and mask_authority.get("compact_hull_close_kernel") == [9, 5]
            and mask_authority.get("compact_hull_dilation_pixels") == 2
            and mask_authority.get("compact_inference_dilation_pixels") == 6
            and mask_authority.get("min_inference_bridge_added_pixels") == MIN_INFERENCE_BRIDGE_ADDED_PIXELS
            and mask_authority.get("min_inference_bridge_rows") == MIN_INFERENCE_BRIDGE_ROWS
            and mask_authority.get("right_glyph_discovery_threshold") == 185
            and mask_authority.get("right_glyph_probe_inside_pixels") == 80
            and float(mask_authority.get("max_compact_vs_legacy_solid_ratio", 1.0))
            == MAX_COMPACT_VS_LEGACY_SOLID_RATIO
            and float(mask_authority.get("min_score_mask_coverage", 0.0)) == MIN_SCORE_MASK_COVERAGE
        )
        checks["source_glyph_residual_metric"] = (
            mask_authority.get("glyph_score_mask_strategy") == "transformed_v3_glyph_clipped_to_source_bbox_v1"
        )
        checks["final_composite_clamped_to_authority"] = mask_authority.get("final_composite_mask_dilation_pixels") == 0

        iteration_guard = result.get("iteration_guard") or {}
        checks["error_loop_guard"] = (
            iteration_guard.get("architecture_family") == ARCHITECTURE_FAMILY
            and iteration_guard.get("same_family_visual_retry_allowed") is False
            and iteration_guard.get("technical_integration_fix_allowed") is True
            and iteration_guard.get("on_visual_fail") == ARCHITECTURE_STOP
        )

        input_frame_rows = result.get("input_frames")
        if not isinstance(input_frame_rows, list):
            raise ValidationError("input_frames missing")
        input_by_frame = {
            int(row["timeline_frame"]): row
            for row in input_frame_rows
            if isinstance(row, dict) and "timeline_frame" in row
        }
        checks["all_input_frames_present"] = sorted(input_by_frame) == EXPECTED_FRAMES

        frame_rows = result.get("frame_metrics")
        if not isinstance(frame_rows, list):
            raise ValidationError("frame_metrics missing")
        by_frame = {
            int(row["timeline_frame"]): row
            for row in frame_rows
            if isinstance(row, dict) and "timeline_frame" in row
        }
        checks["all_frames_present"] = sorted(by_frame) == EXPECTED_FRAMES
        checks["outside_mask_exact"] = all(
            int(by_frame[frame].get("outside_changed_pixels", -1)) == 0 for frame in EXPECTED_FRAMES
        )
        checks["masked_region_changed"] = (
            sum(float(by_frame[frame].get("masked_mae", 0.0)) >= 2.0 for frame in EXPECTED_FRAMES) >= 20
        )
        checks["dynamic_right_guard_bounds"] = all(
            0 <= int(by_frame[frame].get("dynamic_right_guard_pixels", -1)) <= MAX_DYNAMIC_RIGHT_GUARD_PIXELS
            for frame in EXPECTED_FRAMES
        )
        checks["row_filled_background_bridge"] = all(
            int(by_frame[frame].get("inference_bridge_added_pixels", -1)) >= MIN_INFERENCE_BRIDGE_ADDED_PIXELS
            and int(by_frame[frame].get("inference_bridge_rows", -1)) >= MIN_INFERENCE_BRIDGE_ROWS
            for frame in EXPECTED_FRAMES
        )

        semantic_rows = []
        for frame in EXPECTED_FRAMES:
            row = by_frame[frame]
            pre_split = int(row.get("pre_split_row_filled_mask_pixels", 0))
            actual_inpaint = int(row.get("inpaint_mask_pixels", 0))
            person_pixels = int(row.get("person_mask_pixels", 0))
            person_seed = int(row.get("person_glyph_seed_pixels", 0))
            person_repair = int(row.get("person_repair_inference_pixels", 0))
            person_ratio = float(row.get("person_repair_inference_ratio", 1.0))
            seed_full_alpha = int(row.get("person_glyph_seed_full_alpha_pixels", -1))
            person_context_changed = int(row.get("person_context_changed_pixels", -1))
            person_repair_changed = int(row.get("person_repair_changed_pixels", 0))
            background_compact = int(row.get("background_compact_pixels", 0))
            background_covered = int(row.get("background_compact_covered_pixels", -1))
            semantic_rows.append(
                {
                    "timeline_frame": frame,
                    "pre_split_row_filled_mask_pixels": pre_split,
                    "inpaint_mask_pixels": actual_inpaint,
                    "person_mask_pixels": person_pixels,
                    "person_glyph_seed_pixels": person_seed,
                    "person_repair_inference_pixels": person_repair,
                    "person_repair_inference_ratio": person_ratio,
                    "person_glyph_seed_full_alpha_pixels": seed_full_alpha,
                    "person_context_changed_pixels": person_context_changed,
                    "person_repair_changed_pixels": person_repair_changed,
                    "pass": (
                        pre_split > actual_inpaint > 0
                        and person_pixels >= 150000
                        and person_seed >= MIN_PERSON_GLYPH_SEED_PIXELS
                        and person_repair >= person_seed
                        and 0.0 < person_ratio <= MAX_PERSON_REPAIR_AUTHORITY_RATIO
                        and seed_full_alpha == person_seed
                        and person_context_changed == 0
                        and person_repair_changed > 0
                        and background_compact > 0
                        and background_covered == background_compact
                        and 0 < int(row.get("composite_mask_pixels", 0)) <= actual_inpaint
                        and int(row.get("composite_alpha_sum", 0)) > 0
                    ),
                }
            )
        checks["semantic_split_person_protection"] = all(row["pass"] for row in semantic_rows)
        checks["foreground_background_modes"] = all(
            by_frame[frame].get("foreground_background_mode")
            == (
                "row_filled_background_plus_person_glyph_repair"
                if frame < TAIL_BACKGROUND_START_FRAME
                else "tail_closed_background_plus_person_glyph_repair"
            )
            for frame in EXPECTED_FRAMES
        )
        checks["protected_person_context_exact"] = all(
            int(by_frame[frame].get("person_context_changed_pixels", -1)) == 0
            for frame in EXPECTED_FRAMES
        )

        compact_rows = []
        for frame in EXPECTED_FRAMES:
            row = input_by_frame[frame]
            compact_source_pixels = int(row.get("compact_source_mask_pixels", 0))
            legacy_pixels = int(row.get("legacy_solid_reference_pixels", 0))
            compact_ratio = float(row.get("compact_vs_legacy_solid_ratio", 1.0))
            score_coverage = float(row.get("score_mask_coverage", 0.0))
            compact_rows.append(
                {
                    "timeline_frame": frame,
                    "compact_source_mask_pixels": compact_source_pixels,
                    "legacy_solid_reference_pixels": legacy_pixels,
                    "compact_vs_legacy_solid_ratio": compact_ratio,
                    "score_mask_coverage": score_coverage,
                    "pass": (
                        compact_source_pixels >= 25000
                        and legacy_pixels > compact_source_pixels
                        and compact_ratio <= MAX_COMPACT_VS_LEGACY_SOLID_RATIO
                        and score_coverage >= MIN_SCORE_MASK_COVERAGE
                    ),
                }
            )
        checks["compact_source_mask_area_and_coverage"] = all(row["pass"] for row in compact_rows)

        sentinel_rows = []
        person_repair_sentinels = []
        for frame in HOLD_SENTINELS:
            row = by_frame.get(frame) or {}
            before = float(row.get("safe_glyph_dark_ratio_lt140_before", 0.0))
            after = float(row.get("safe_glyph_dark_ratio_lt140_after", 1.0))
            relative = ((before - after) / before) if before > 1e-9 else 0.0
            sentinel_rows.append(
                {
                    "timeline_frame": frame,
                    "before_glyph_dark_ratio": before,
                    "after_glyph_dark_ratio": after,
                    "relative_glyph_dark_reduction": relative,
                    "pass": before >= 0.35 and after <= 0.20 and relative >= 0.70,
                }
            )
            person_seed = int(row.get("person_glyph_seed_pixels", 0))
            person_mae = float(row.get("person_glyph_delta_mae", 0.0))
            person_repair_sentinels.append(
                {
                    "timeline_frame": frame,
                    "person_glyph_seed_pixels": person_seed,
                    "person_glyph_delta_mae": person_mae,
                    "pass": person_seed >= MIN_PERSON_GLYPH_SEED_PIXELS and person_mae >= MIN_PERSON_GLYPH_DELTA_MAE,
                }
            )
        checks["hold_sentinel_source_glyph_reduction"] = all(row["pass"] for row in sentinel_rows)
        checks["hold_sentinel_person_glyph_replacement_activity"] = all(
            row["pass"] for row in person_repair_sentinels
        )

        right_guard_rows = []
        for frame in HOLD_SENTINELS:
            row = by_frame.get(frame) or {}
            source_dark_pixels = int(row.get("right_source_dark_pixels", 0))
            survival = float(row.get("right_source_dark_survival_lt140", 1.0))
            removal = 1.0 - survival
            right_guard_rows.append(
                {
                    "timeline_frame": frame,
                    "source_dark_pixels": source_dark_pixels,
                    "dark_survival_ratio": survival,
                    "dark_removal_ratio": removal,
                    "pass": source_dark_pixels >= 3000 and survival <= 0.25 and removal >= 0.75,
                }
            )
        checks["hold_sentinel_right_glyph_guard_removal"] = all(row["pass"] for row in right_guard_rows)

        artifact_specs = {
            "MASK_CONTACT_SHEET.png": 1000,
            "BEFORE_AFTER_CONTACT_SHEET.png": 1000,
            "COME_BEFORE_AFTER_PROOF_V9.mp4": 10000,
            "PROPAINTER_RUN.log": 100,
        }
        artifact_checks = {}
        for name, minimum in artifact_specs.items():
            path = artifact_dir / name
            artifact_checks[name] = path.is_file() and path.stat().st_size >= minimum
        checks["required_artifacts"] = all(artifact_checks.values())
        final_frames_dir = artifact_dir / "inpainted_frames"
        final_frames = sorted(final_frames_dir.glob("frame_*.png")) if final_frames_dir.is_dir() else []
        checks["final_frame_count"] = len(final_frames) == 24

        technical_pass = all(value is True for value in checks.values())
        status = "technical_pass_visual_pending" if technical_pass else "technical_fail"
        validation = {
            "task_id": TASK_ID,
            "status": status,
            "technical_pass": technical_pass,
            "visual_approval_required": True,
            "checks": checks,
            "hold_sentinels": sentinel_rows,
            "person_glyph_repair_sentinels": person_repair_sentinels,
            "right_glyph_guard_sentinels": right_guard_rows,
            "semantic_split_rows": semantic_rows,
            "compact_mask_rows": compact_rows,
            "artifact_checks": artifact_checks,
            "iteration_guard": iteration_guard,
            "non_goal": "This proof does not authorize Resolve integration or any broader baked-caption rollout.",
        }
        validation_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
        report_lines = [
            f"# {TASK_ID}",
            "",
            f"Technical status: **{status}**",
            "",
            "This is an offline ProPainter proof only. Resolve was not invoked and no timeline was modified.",
            "",
            "## Technical checks",
        ]
        for key, value in checks.items():
            report_lines.append(f"- {key}: {'PASS' if value is True else 'FAIL'}")
        report_lines += [
            "",
            "## Required human gate",
            "",
            "Inspect `COME_BEFORE_AFTER_PROOF_V9.mp4`, `BEFORE_AFTER_CONTACT_SHEET.png`, and `MASK_CONTACT_SHEET.png`.",
            "Approve only if baked COME is removed with no C/O/M/E remnants or late E, while the woman's face, sunglasses, hairline, hair volume, and head silhouette remain stable with no blobs, seams, wedges, smearing, or temporal swimming.",
            "V9 specifically masks only source-backed COME pixels inside the accepted V4 person matte; broad person repainting is forbidden.",
            "",
            "## Error-loop stop rule",
            "",
            "If V9 is technical PASS but human visual FAIL, stop this ProPainter semantic-split mask architecture family. Do not produce V10 by changing mask dilation, feather, threshold, or topology. A later attempt must use a different recovery architecture/source.",
            "No Resolve integration is authorized by this report alone.",
            "",
        ]
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        print(json.dumps(validation, indent=2))
        return 0 if technical_pass else 1
    except Exception as exc:
        errors.append(repr(exc))
        validation = {
            "task_id": TASK_ID,
            "status": "technical_fail",
            "technical_pass": False,
            "visual_approval_required": True,
            "checks": checks,
            "errors": errors,
        }
        validation_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
        report_path.write_text(
            f"# {TASK_ID}\n\nTechnical status: **technical_fail**\n\nError: `{errors[-1]}`\n",
            encoding="utf-8",
        )
        print(json.dumps(validation, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
