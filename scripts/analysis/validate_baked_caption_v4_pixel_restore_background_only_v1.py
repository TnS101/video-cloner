from __future__ import annotations

import argparse
import json
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_V4_PIXEL_RESTORE_BACKGROUND_ONLY_V1"
EXPECTED_FAMILY = "accepted_v4_full_foreground_veto_background_only_propainter_v1"
FRAMES = tuple(range(429, 453))
HOLD_SENTINELS = (434, 438, 443, 448)
MIN_RGBA_COVERAGE = 0.985
MIN_GLYPH_REDUCTION = 0.70
MIN_RIGHT_REMOVAL = 0.75


class ValidationError(RuntimeError):
    pass


def _map(rows, label):
    if not isinstance(rows, list):
        raise ValidationError(f"{label} is missing")
    result = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("timeline_frame"), int):
            result[int(row["timeline_frame"])] = row
    if set(result) != set(FRAMES):
        raise ValidationError(f"{label} frame coverage mismatch: {sorted(result)}")
    return result


def validate(artifact_dir: Path) -> dict:
    result_path = artifact_dir / "PROOF_RUN_RESULT.json"
    if not result_path.is_file():
        raise ValidationError("PROOF_RUN_RESULT.json missing")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("task_id") != TASK_ID or result.get("ok") is not True:
        raise ValidationError("unexpected runtime result identity/status")
    architecture = result.get("architecture") or {}
    if architecture.get("family") != EXPECTED_FAMILY:
        raise ValidationError("unexpected architecture family")
    if float(architecture.get("min_rgba_glyph_person_coverage", 0.0)) != MIN_RGBA_COVERAGE:
        raise ValidationError("RGBA coverage contract changed")
    inputs = _map(result.get("input_rows"), "input_rows")
    metrics = _map(result.get("composite_rows"), "composite_rows")

    checks = {}
    checks["rgba_authority_coverage"] = all(
        float(inputs[f].get("rgba_glyph_person_coverage", 0.0)) >= MIN_RGBA_COVERAGE for f in FRAMES
    )
    checks["background_only_inference"] = all(
        int(inputs[f].get("background_inference_mask_pixels", 0)) > 0
        and int(inputs[f].get("foreground_preserve_pixels", 0)) > 0
        and int(inputs[f].get("inference_person_overlap_pixels", -1)) == 0
        and int(inputs[f].get("inference_foreground_preserve_overlap_pixels", -1)) == 0
        for f in FRAMES
    )
    checks["outside_authority_exact"] = all(
        int(metrics[f].get("outside_authority_changed_pixels", -1)) == 0 for f in FRAMES
    )
    checks["person_context_exact"] = all(
        int(metrics[f].get("protected_person_context_changed_pixels", -1)) == 0 for f in FRAMES
    )
    checks["foreground_preserve_exact"] = all(
        int(metrics[f].get("foreground_preserve_changed_pixels", -1)) == 0 for f in FRAMES
    )
    checks["source_glyph_reduction"] = all(
        float(metrics[f].get("safe_glyph_dark_reduction", -1.0)) >= MIN_GLYPH_REDUCTION
        for f in HOLD_SENTINELS
    )
    checks["right_glyph_removal"] = all(
        float(metrics[f].get("right_source_dark_removal", -1.0)) >= MIN_RIGHT_REMOVAL
        for f in HOLD_SENTINELS
    )
    checks["late_tail_mode"] = (
        metrics[451].get("background_mode") == "tail_closed_compact_background_only"
        and metrics[452].get("background_mode") == "tail_closed_compact_background_only"
    )
    checks["no_resolve"] = (
        result.get("resolve_invocations") == 0
        and result.get("save_project_calls") == 0
        and result.get("timeline_mutations") == 0
    )
    required = [
        "PROPAINTER_TOOLCHAIN.json",
        "PROOF_RUN_RESULT.json",
        "PROPAINTER_BACKGROUND_RUN.log",
        "COME_BEFORE_AFTER_V4_PIXEL_RESTORE_BACKGROUND_ONLY_V1.mp4",
        "BEFORE_AFTER_CONTACT_SHEET.png",
        "MASK_CONTACT_SHEET.png",
    ]
    checks["artifacts"] = all((artifact_dir / name).is_file() and (artifact_dir / name).stat().st_size > 0 for name in required)
    checks["final_frames"] = all(
        (artifact_dir / "inpainted_frames" / f"frame_{f:06d}.png").is_file() for f in FRAMES
    )
    technical_pass = all(checks.values())
    validation = {
        "task_id": TASK_ID,
        "technical_pass": technical_pass,
        "status": "technical_pass_visual_pending" if technical_pass else "technical_fail",
        "checks": checks,
        "sentinels": {
            str(f): {
                "source_glyph_reduction": metrics[f].get("safe_glyph_dark_reduction"),
                "right_glyph_removal": metrics[f].get("right_source_dark_removal"),
            }
            for f in HOLD_SENTINELS
        },
        "min_rgba_glyph_person_coverage": min(float(inputs[f]["rgba_glyph_person_coverage"]) for f in FRAMES),
        "max_outside_authority_changed_pixels": max(int(metrics[f]["outside_authority_changed_pixels"]) for f in FRAMES),
        "max_person_context_changed_pixels": max(int(metrics[f]["protected_person_context_changed_pixels"]) for f in FRAMES),
        "resolve_invocations": result.get("resolve_invocations"),
        "save_project_calls": result.get("save_project_calls"),
        "timeline_mutations": result.get("timeline_mutations"),
    }
    (artifact_dir / "PROOF_VALIDATION.json").write_text(json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8")
    report_lines = [
        f"# {TASK_ID}",
        "",
        f"Status: `{validation['status']}`",
        "",
        f"- Minimum accepted V4 RGBA/person-glyph coverage: `{validation['min_rgba_glyph_person_coverage']:.6f}`",
        f"- Maximum protected-person changed pixels: `{validation['max_person_context_changed_pixels']}`",
        f"- Maximum outside-authority changed pixels: `{validation['max_outside_authority_changed_pixels']}`",
        "- Resolve invocations: `0`",
        "- SaveProject calls: `0`",
        "- Timeline mutations: `0`",
        "",
        "Human visual approval is required before Resolve integration.",
    ]
    (artifact_dir / "FINAL_REPORT.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    if not technical_pass:
        failed = [name for name, ok in checks.items() if not ok]
        raise ValidationError(f"technical validation failed: {failed}")
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    validate(Path(args.artifact_dir).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
