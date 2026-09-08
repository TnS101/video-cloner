from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_PRECAPTION_SOURCE_TRANSPORT_V1"
ARCHITECTURE_FAMILY = "pre_caption_clean_donor_source_transport_v1"
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
HOLD_SENTINELS = (434, 438, 443, 448)
EXPECTED_SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
EXPECTED_FOREGROUND_MANIFEST_SHA256 = "7b2cd599494c06f12cc22af5f7cb4fd8226f8a8e8a15ffdaac498cf0576e00c6"
EXPECTED_DIFF_HELPER_SHA256 = "ca95ccfa9e9070a8b4f4ade24afd89d441d016eb931476b4e0d30fffd5a7817d"
MIN_COMBINED_SOURCE_BACKED_COVERAGE = 0.83
MIN_PRECAPTION_VALID_COVERAGE = 0.98
MIN_SOURCE_GLYPH_REDUCTION = 0.70
MIN_RIGHT_GLYPH_REMOVAL = 0.75
MAX_NEW_DARK_ARTIFACT_RATIO = 0.03
MAX_NEW_BRIGHT_ARTIFACT_RATIO = 0.03
MAX_BOUNDARY_RING_MAE = 30.0
EXPECTED_PRECAPTION_BRIDGE_METHOD = "farneback_dense_to_similarity"
DENSE_BRIDGE_MIN_SUPPORT_PIXELS = 15000
DENSE_BRIDGE_MIN_FB_VALID_FRACTION = 0.95
DENSE_BRIDGE_MAX_MEDIAN_FB_ERROR = 0.50
DENSE_BRIDGE_MAX_PHOTOMETRIC_MAE = 25.0
DENSE_BRIDGE_MIN_SAMPLED_CORRESPONDENCES = 4000
DENSE_BRIDGE_MIN_RANSAC_INLIERS = 2500
DENSE_BRIDGE_MAX_MEDIAN_RANSAC_ERROR = 1.10
DENSE_BRIDGE_MAX_P95_RANSAC_ERROR = 1.70
REQUIRED_ARTIFACT_NAMES = (
    "COME_BEFORE_AFTER_PRECAPTION_SOURCE_TRANSPORT_V1.mp4",
    "BEFORE_AFTER_CONTACT_SHEET.png",
    "MASK_CONTACT_SHEET.png",
    "PRECLEAN_BACKGROUND_DONOR_PLATE.png",
    "PRECLEAN_PERSON_DONOR_PLATE_REF.png",
    "TEMPORAL_PERSON_PLATE.png",
    "DONOR_PROVENANCE.png",
    "PROOF_RUN_RESULT.json",
)


class ValidationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require_artifacts(artifact_dir: Path) -> list[dict[str, object]]:
    rows = []
    for name in REQUIRED_ARTIFACT_NAMES:
        path = artifact_dir / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValidationError(f"required artifact missing or empty: {name}")
        rows.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    final_dir = artifact_dir / "inpainted_frames"
    files = sorted(final_dir.glob("frame_*.png")) if final_dir.is_dir() else []
    if len(files) != 24:
        raise ValidationError(f"expected 24 final PNGs, got {len(files)}")
    rows.append({
        "name": "inpainted_frames",
        "count": 24,
        "total_bytes": sum(p.stat().st_size for p in files),
        "first_sha256": sha256_file(files[0]),
        "last_sha256": sha256_file(files[-1]),
    })
    return rows


def require_dense_bridge(result: dict) -> dict:
    dense = result.get("precaption_dense_bridge")
    if not isinstance(dense, dict) or dense.get("method") != EXPECTED_PRECAPTION_BRIDGE_METHOD:
        raise ValidationError("pre-caption dense bridge evidence missing")
    return dense


def validate_result(result: dict) -> list[str]:
    if result.get("task_id") != TASK_ID or result.get("ok") is not True:
        raise ValidationError("unexpected proof result contract")
    if result.get("resolve_invocations") != 0 or result.get("timeline_mutations") != 0 or result.get("save_project_calls") != 0:
        raise ValidationError("offline proof touched Resolve state")

    architecture = result.get("architecture") or {}
    if architecture.get("family") != ARCHITECTURE_FAMILY:
        raise ValidationError("unexpected architecture family")
    if int(architecture.get("attempt_number", 0)) != 1:
        raise ValidationError("unexpected architecture attempt")
    if int(architecture.get("generative_inference_calls", -1)) != 0:
        raise ValidationError("generative inference entered source-backed proof")

    source = result.get("source_authority") or {}
    if source.get("source_video_sha256") != EXPECTED_SOURCE_VIDEO_SHA256:
        raise ValidationError("source video authority mismatch")
    if source.get("foreground_manifest_sha256") != EXPECTED_FOREGROUND_MANIFEST_SHA256:
        raise ValidationError("foreground authority mismatch")
    if source.get("diffueraser_authority_helper_sha256") != EXPECTED_DIFF_HELPER_SHA256:
        raise ValidationError("authority helper mismatch")
    if int(source.get("precaption_clean_source_frame", -1)) != 533:
        raise ValidationError("clean pre-caption donor frame changed")
    if int(source.get("precaption_sharp_source_frame", -1)) != 534:
        raise ValidationError("sharp pre-caption bridge frame changed")
    if int(source.get("bridge_timeline_frame", -1)) != 427:
        raise ValidationError("accepted V4 bridge timeline frame changed")
    if source.get("precaption_bridge_method") != EXPECTED_PRECAPTION_BRIDGE_METHOD:
        raise ValidationError("pre-caption dense bridge method changed")

    dense = require_dense_bridge(result)

    rows = result.get("frame_metrics")
    if not isinstance(rows, list) or len(rows) != 24:
        raise ValidationError("expected 24 frame metrics")
    by_frame = {int(row["timeline_frame"]): row for row in rows if isinstance(row, dict)}
    if set(by_frame) != set(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1)):
        raise ValidationError("frame metric inventory mismatch")

    failures = []
    if int(dense.get("support_pixels", -1)) < DENSE_BRIDGE_MIN_SUPPORT_PIXELS:
        failures.append("dense_bridge_support")
    if float(dense.get("fb_valid_fraction", -1.0)) < DENSE_BRIDGE_MIN_FB_VALID_FRACTION:
        failures.append("dense_bridge_fb_valid_fraction")
    if float(dense.get("median_fb_error_process_pixels", 999.0)) > DENSE_BRIDGE_MAX_MEDIAN_FB_ERROR:
        failures.append("dense_bridge_fb_error")
    if float(dense.get("photometric_mae_process_pixels", 999.0)) > DENSE_BRIDGE_MAX_PHOTOMETRIC_MAE:
        failures.append("dense_bridge_photometric_mae")
    if int(dense.get("sampled_correspondences", -1)) < DENSE_BRIDGE_MIN_SAMPLED_CORRESPONDENCES:
        failures.append("dense_bridge_correspondences")
    if int(dense.get("ransac_inliers", -1)) < DENSE_BRIDGE_MIN_RANSAC_INLIERS:
        failures.append("dense_bridge_ransac_inliers")
    if float(dense.get("median_ransac_error_process_pixels", 999.0)) > DENSE_BRIDGE_MAX_MEDIAN_RANSAC_ERROR:
        failures.append("dense_bridge_ransac_median")
    if float(dense.get("p95_ransac_error_process_pixels", 999.0)) > DENSE_BRIDGE_MAX_P95_RANSAC_ERROR:
        failures.append("dense_bridge_ransac_p95")
    for frame, row in sorted(by_frame.items()):
        if int(row.get("outside_authority_changed_pixels", -1)) != 0:
            failures.append(f"outside_authority:{frame}")
        if int(row.get("protected_person_changed_pixels", -1)) != 0:
            failures.append(f"protected_person:{frame}")
        if float(row.get("source_backed_combined_fraction", -1.0)) < MIN_COMBINED_SOURCE_BACKED_COVERAGE:
            failures.append(f"source_backed_coverage:{frame}")
        if float(row.get("transported_person_valid_fraction", -1.0)) < MIN_PRECAPTION_VALID_COVERAGE:
            failures.append(f"precaption_transport_validity:{frame}")
        if float(row.get("new_dark_artifact_ratio", 1.0)) > MAX_NEW_DARK_ARTIFACT_RATIO:
            failures.append(f"new_dark_artifact:{frame}")
        if float(row.get("new_bright_artifact_ratio", 1.0)) > MAX_NEW_BRIGHT_ARTIFACT_RATIO:
            failures.append(f"new_bright_artifact:{frame}")
        if float(row.get("boundary_ring_mae", 999.0)) > MAX_BOUNDARY_RING_MAE:
            failures.append(f"boundary_ring_mae:{frame}")

    for frame in HOLD_SENTINELS:
        row = by_frame[frame]
        if float(row.get("safe_glyph_dark_reduction", -1.0)) < MIN_SOURCE_GLYPH_REDUCTION:
            failures.append(f"source_glyph_reduction:{frame}")
        if float(row.get("right_source_dark_removal", -1.0)) < MIN_RIGHT_GLYPH_REMOVAL:
            failures.append(f"right_glyph_removal:{frame}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    artifact_dir = Path(args.artifact_dir).resolve()
    result_path = artifact_dir / "PROOF_RUN_RESULT.json"
    if not result_path.is_file():
        raise ValidationError("PROOF_RUN_RESULT.json missing")
    result = load_json(result_path)
    if not isinstance(result, dict):
        raise ValidationError("proof result must be an object")
    failures = validate_result(result)
    dense = require_dense_bridge(result)
    artifact_rows = require_artifacts(artifact_dir)
    technical_pass = not failures
    status = "technical_pass_visual_pending" if technical_pass else "technical_fail"
    rows = {int(row["timeline_frame"]): row for row in result["frame_metrics"]}
    validation = {
        "task_id": TASK_ID,
        "status": status,
        "technical_pass": technical_pass,
        "visual_approval_required": True,
        "failure_class_if_technical_fail": "F_ARCHITECTURE",
        "failures": failures,
        "thresholds": {
            "min_combined_source_backed_coverage": MIN_COMBINED_SOURCE_BACKED_COVERAGE,
            "min_precaption_valid_coverage": MIN_PRECAPTION_VALID_COVERAGE,
            "min_source_glyph_reduction": MIN_SOURCE_GLYPH_REDUCTION,
            "min_right_glyph_removal": MIN_RIGHT_GLYPH_REMOVAL,
            "max_new_dark_artifact_ratio": MAX_NEW_DARK_ARTIFACT_RATIO,
            "max_new_bright_artifact_ratio": MAX_NEW_BRIGHT_ARTIFACT_RATIO,
            "max_boundary_ring_mae": MAX_BOUNDARY_RING_MAE,
            "dense_bridge_min_support_pixels": DENSE_BRIDGE_MIN_SUPPORT_PIXELS,
            "dense_bridge_min_fb_valid_fraction": DENSE_BRIDGE_MIN_FB_VALID_FRACTION,
            "dense_bridge_max_median_fb_error": DENSE_BRIDGE_MAX_MEDIAN_FB_ERROR,
            "dense_bridge_max_photometric_mae": DENSE_BRIDGE_MAX_PHOTOMETRIC_MAE,
            "dense_bridge_min_sampled_correspondences": DENSE_BRIDGE_MIN_SAMPLED_CORRESPONDENCES,
            "dense_bridge_min_ransac_inliers": DENSE_BRIDGE_MIN_RANSAC_INLIERS,
            "dense_bridge_max_median_ransac_error": DENSE_BRIDGE_MAX_MEDIAN_RANSAC_ERROR,
            "dense_bridge_max_p95_ransac_error": DENSE_BRIDGE_MAX_P95_RANSAC_ERROR,
        },
        "precaption_dense_bridge": dense,
        "sentinels": {str(f): rows[f] for f in HOLD_SENTINELS},
        "visual_acceptance_contract": [
            "No readable or glyph-like COME topology remains.",
            "No pale rectangles, bars, islands, or smears remain in the repaired region.",
            "No visible hair, face, or person corruption is introduced.",
            "No obvious temporal flicker or donor-patch popping occurs across frames 429-452.",
            "The repair looks source-consistent rather than generated or cloned as a visible patch.",
        ],
        "artifacts": artifact_rows,
        "resolve_invocations": result.get("resolve_invocations"),
        "timeline_mutations": result.get("timeline_mutations"),
        "save_project_calls": result.get("save_project_calls"),
    }
    (artifact_dir / "PROOF_VALIDATION.json").write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = [
        f"# {TASK_ID}", "", f"Status: `{status}`", "",
        f"Technical pass: `{str(technical_pass).lower()}`",
        "Visual approval required: `true`", "", "## Failures",
    ]
    report.extend([f"- {x}" for x in failures] or ["- None"])
    report += [
        "", "## Sentinel metrics", "",
        "| Frame | Combined source coverage | Temporal any | Source-glyph reduction | Right-glyph removal | New-dark | New-bright | Boundary MAE |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for frame in HOLD_SENTINELS:
        row = rows[frame]
        report.append(
            f"| {frame} | {float(row['source_backed_combined_fraction']):.4f} | "
            f"{float(row['source_backed_temporal_any_fraction']):.4f} | "
            f"{float(row['safe_glyph_dark_reduction']):.4f} | "
            f"{float(row['right_source_dark_removal']):.4f} | "
            f"{float(row['new_dark_artifact_ratio']):.4f} | "
            f"{float(row['new_bright_artifact_ratio']):.4f} | "
            f"{float(row['boundary_ring_mae']):.2f} |"
        )
    report += [
        "",
        "Human visual review is mandatory even after technical PASS.",
        "Resolve integration remains forbidden until that visual review passes.",
        "If this source-backed architecture visually fails, do not create a mask/threshold variant.",
    ]
    (artifact_dir / "FINAL_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({
        "task_id": TASK_ID, "status": status, "technical_pass": technical_pass,
        "failures": failures,
    }, sort_keys=True))
    return 0 if technical_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
