from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_LAMA_ROI_PROOF_V1"
ARCHITECTURE_FAMILY = "lama_highres_roi_source_authority_semantic_composite_v1"
EXPECTED_MODEL_SHA256 = "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"
SOURCE_FRAME_START = 429
SOURCE_FRAME_END = 452
HOLD_SENTINELS = (434, 438, 443, 448)
MIN_SOURCE_GLYPH_REDUCTION = 0.70
MIN_RIGHT_GLYPH_REMOVAL = 0.75
MAX_NEW_DARK_ARTIFACT_RATIO = 0.03
MAX_NEW_BRIGHT_ARTIFACT_RATIO = 0.03
MAX_BOUNDARY_RING_MAE = 30.0
REQUIRED_ARTIFACT_NAMES = (
    "COME_BEFORE_AFTER_LAMA_ROI_V1.mp4",
    "LAMA_ROI_OUTPUT.mp4",
    "LAMA_RUN.log",
    "BEFORE_AFTER_CONTACT_SHEET.png",
    "MASK_CONTACT_SHEET.png",
    "ROI_AUTHORITY.json",
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


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require_artifacts(artifact_dir: Path) -> list[dict[str, object]]:
    rows = []
    for name in REQUIRED_ARTIFACT_NAMES:
        path = artifact_dir / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValidationError(f"required artifact missing or empty: {name}")
        rows.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    for directory_name in ("lama_generated_roi_frames", "inpainted_frames"):
        directory = artifact_dir / directory_name
        files = sorted(directory.glob("frame_*.png")) if directory.is_dir() else []
        if len(files) != 24:
            raise ValidationError(f"expected 24 PNGs in {directory_name}, got {len(files)}")
        rows.append({
            "name": directory_name,
            "count": len(files),
            "total_bytes": sum(path.stat().st_size for path in files),
            "first_sha256": sha256_file(files[0]),
            "last_sha256": sha256_file(files[-1]),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    artifact_dir = Path(args.artifact_dir).resolve()
    result_path = artifact_dir / "PROOF_RUN_RESULT.json"
    if not result_path.is_file():
        raise ValidationError("PROOF_RUN_RESULT.json missing")
    result = load_json(result_path)
    if not isinstance(result, dict) or result.get("task_id") != TASK_ID or result.get("ok") is not True:
        raise ValidationError("unexpected proof result contract")
    if result.get("resolve_invocations") != 0 or result.get("save_project_calls") != 0 or result.get("timeline_mutations") != 0:
        raise ValidationError("offline proof touched Resolve state")
    architecture = result.get("architecture") or {}
    if architecture.get("family") != ARCHITECTURE_FAMILY or int(architecture.get("attempt", 0)) != 1:
        raise ValidationError("unexpected architecture family/attempt")
    if "no_propainter_prior" not in str(architecture.get("conditioning", "")):
        raise ValidationError("LaMa architecture unexpectedly depends on ProPainter prior")
    model_run = result.get("model_run") or {}
    if model_run.get("model_sha256") != EXPECTED_MODEL_SHA256:
        raise ValidationError("LaMa model hash mismatch")
    if int(model_run.get("frame_count", 0)) != 24:
        raise ValidationError("LaMa did not produce 24 frames")
    rows = result.get("frame_metrics")
    if not isinstance(rows, list) or len(rows) != 24:
        raise ValidationError("expected 24 frame metrics")
    by_frame = {int(row["timeline_frame"]): row for row in rows if isinstance(row, dict)}
    expected_frames = set(range(SOURCE_FRAME_START, SOURCE_FRAME_END + 1))
    if set(by_frame) != expected_frames:
        raise ValidationError("frame metric inventory mismatch")

    failures = []
    for frame, row in sorted(by_frame.items()):
        if int(row.get("outside_authority_changed_pixels", -1)) != 0:
            failures.append(f"outside_authority:{frame}")
        if int(row.get("protected_person_changed_pixels", -1)) != 0:
            failures.append(f"protected_person:{frame}")
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

    artifact_rows = require_artifacts(artifact_dir)
    technical_pass = not failures
    status = "technical_pass_visual_pending" if technical_pass else "technical_fail"
    validation = {
        "task_id": TASK_ID,
        "status": status,
        "technical_pass": technical_pass,
        "visual_approval_required": True,
        "visual_acceptance_contract": [
            "No readable or glyph-like COME topology remains in raw or final output.",
            "No pale/rectangular reconstruction islands or smears remain in the former caption region.",
            "No visible person/hair corruption is introduced.",
            "No obvious temporal flicker/popping is introduced across frames 429-452.",
        ],
        "failures": failures,
        "thresholds": {
            "min_source_glyph_reduction": MIN_SOURCE_GLYPH_REDUCTION,
            "min_right_glyph_removal": MIN_RIGHT_GLYPH_REMOVAL,
            "max_new_dark_artifact_ratio": MAX_NEW_DARK_ARTIFACT_RATIO,
            "max_new_bright_artifact_ratio": MAX_NEW_BRIGHT_ARTIFACT_RATIO,
            "max_boundary_ring_mae": MAX_BOUNDARY_RING_MAE,
        },
        "sentinels": {str(frame): by_frame[frame] for frame in HOLD_SENTINELS},
        "residual_topology_diagnostics": {
            str(frame): {
                "residual_dark_pixels": by_frame[frame].get("residual_dark_pixels"),
                "residual_dark_components": by_frame[frame].get("residual_dark_components"),
                "largest_residual_dark_component_pixels": by_frame[frame].get("largest_residual_dark_component_pixels"),
                "source_dark_overlap_pixels": by_frame[frame].get("source_dark_overlap_pixels"),
            }
            for frame in HOLD_SENTINELS
        },
        "artifacts": artifact_rows,
        "resolve_invocations": result.get("resolve_invocations"),
        "save_project_calls": result.get("save_project_calls"),
        "timeline_mutations": result.get("timeline_mutations"),
    }
    (artifact_dir / "PROOF_VALIDATION.json").write_text(json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8")
    report = [
        f"# {TASK_ID}",
        "",
        f"Status: `{status}`",
        "",
        f"Technical pass: `{str(technical_pass).lower()}`",
        "Visual approval required: `true`",
        "",
        "## Failures",
    ]
    report.extend([f"- {item}" for item in failures] or ["- None"])
    report += [
        "",
        "## Sentinel metrics",
        "",
        "| Frame | Source-glyph reduction | Right-glyph removal | New-dark | New-bright | Boundary MAE | Largest residual dark component |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for frame in HOLD_SENTINELS:
        row = by_frame[frame]
        report.append(
            f"| {frame} | {float(row['safe_glyph_dark_reduction']):.4f} | "
            f"{float(row['right_source_dark_removal']):.4f} | "
            f"{float(row['new_dark_artifact_ratio']):.4f} | {float(row['new_bright_artifact_ratio']):.4f} | "
            f"{float(row['boundary_ring_mae']):.2f} | {int(row.get('largest_residual_dark_component_pixels', 0))} |"
        )
    report += [
        "",
        "Human visual review must inspect both the raw LaMa video and final comparison video.",
        "Resolve integration remains forbidden until human visual approval.",
    ]
    (artifact_dir / "FINAL_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"task_id": TASK_ID, "status": status, "technical_pass": technical_pass, "failures": failures}, sort_keys=True))
    return 0 if technical_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
