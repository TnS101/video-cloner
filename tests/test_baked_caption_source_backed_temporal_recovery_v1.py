from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "analysis"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_baked_caption_source_backed_temporal_recovery_v1 as runner
import run_baked_caption_video_inpaint_proof_v1 as legacy


def _load_validator():
    path = SCRIPT_DIR / "validate_baked_caption_source_backed_temporal_recovery_v1.py"
    spec = importlib.util.spec_from_file_location("source_backed_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_new_architecture_is_distinct_from_closed_v9_family():
    assert runner.TASK_ID == "DZSQH7AUHJT_BAKED_CAPTION_SOURCE_BACKED_TEMPORAL_RECOVERY_V1"
    assert runner.EXPECTED_LEGACY_TASK_ID == "DZSQH7AUHJT_BAKED_CAPTION_VIDEO_INPAINT_PROOF_V9"
    assert legacy.TASK_ID == runner.EXPECTED_LEGACY_TASK_ID
    assert runner.ARCHITECTURE_FAMILY == "stabilized_source_backed_person_then_background_v1"
    assert "semantic_split_person_repair" not in runner.ARCHITECTURE_FAMILY
    assert runner.CLOSED_ARCHITECTURE_FAMILY == "propainter_semantic_split_person_repair_v1"
    assert runner.VISUAL_FAIL_STOP == "stop_current_family_no_mask_parameter_retry"


def test_source_backed_plate_uses_only_uncovered_person_observations():
    images = []
    persons = []
    scores = []
    for value in (10, 30, 50):
        image = np.full((4, 5, 3), value, dtype=np.uint8)
        person = np.full((4, 5), 255, dtype=np.uint8)
        score = np.zeros((4, 5), dtype=np.uint8)
        images.append(image)
        persons.append(person)
        scores.append(score)
    scores[0][1, 2] = 255
    scores[1][1, 2] = 255
    scores[2][2, 3] = 255

    plate, count = runner.build_source_backed_clean_plate(images, persons, scores)

    assert int(count[1, 2]) == 1
    assert np.all(plate[1, 2] == 50)
    assert int(count[2, 3]) == 2
    assert np.all(plate[2, 3] == 20)
    assert int(count[0, 0]) == 3
    assert np.all(plate[0, 0] == 30)


def test_compose_transforms_identity_is_identity():
    pairwise = {
        (frame, frame + 1): np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
        for frame in range(runner.SOURCE_FRAME_START, runner.SOURCE_FRAME_END)
    }
    transforms = runner.compose_transforms_to_reference(pairwise, runner.REFERENCE_FRAME)
    assert sorted(transforms) == list(range(429, 453))
    for transform in transforms.values():
        np.testing.assert_allclose(transform, np.eye(3), atol=1e-12)


def test_inward_alpha_never_escapes_core_and_forces_full_alpha():
    core = np.zeros((40, 40), dtype=np.uint8)
    core[10:30, 10:30] = 255
    full = np.zeros_like(core)
    full[18:22, 18:22] = 255
    alpha = runner.build_inward_alpha(core, 2.0, full)
    assert float(alpha[0, 0]) == 0.0
    assert np.all(alpha[core == 0] == 0.0)
    assert np.all(alpha[full > 0] == 1.0)
    assert np.all((alpha >= 0.0) & (alpha <= 1.0))


def test_pairwise_affine_recovers_synthetic_person_translation():
    rng = np.random.default_rng(12345)
    height, width = 900, 800
    donor = np.zeros((height, width, 3), dtype=np.uint8)
    texture = rng.integers(20, 240, size=(190, 300, 3), dtype=np.uint8)
    donor[660:850, 250:550] = texture
    donor_person = np.zeros((height, width), dtype=np.uint8)
    donor_person[650:860, 240:560] = 255
    score = np.zeros((height, width), dtype=np.uint8)
    matrix = np.asarray([[1.0, 0.0, 4.0], [0.0, 1.0, 3.0]], dtype=np.float32)
    target = cv2.warpAffine(donor, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    target_person = cv2.warpAffine(donor_person, matrix, (width, height), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)

    estimated, metrics = runner.estimate_pairwise_person_affine(
        donor, target, donor_person, target_person, score, score
    )

    assert metrics["inliers"] >= runner.PAIRWISE_MIN_INLIERS
    assert metrics["median_reprojection_error_process_pixels"] <= runner.PAIRWISE_MAX_MEDIAN_ERROR
    assert abs(float(estimated[0, 2]) - 4.0) < 1.0
    assert abs(float(estimated[1, 2]) - 3.0) < 1.0


def _passing_result() -> dict:
    alignment = []
    for frame in range(429, 452):
        alignment.append(
            {
                "from_frame": frame,
                "to_frame": frame + 1,
                "inliers": 55,
                "median_reprojection_error_process_pixels": 0.5,
                "scale": 1.0,
                "rotation_degrees": 0.0,
                "matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            }
        )
    coverage = []
    inputs = []
    persons = []
    metrics = []
    for frame in range(429, 453):
        coverage.append(
            {
                "timeline_frame": frame,
                "person_glyph_seed_pixels_stabilized": 5000,
                "source_backed_any_pixels": 4600,
                "source_backed_any_fraction": 0.92,
                "source_backed_two_observation_pixels": 4200,
                "source_backed_two_observation_fraction": 0.84,
                "model_unresolved_fraction": 0.16,
            }
        )
        inputs.append(
            {
                "timeline_frame": frame,
                "score_mask_pixels": 10000,
                "person_glyph_seed_pixels": 5000,
                "compact_source_mask_pixels": 40000,
                "row_filled_mask_pixels": 50000,
            }
        )
        persons.append(
            {
                "timeline_frame": frame,
                "person_repair_pixels": 6000,
                "person_seed_pixels": 5000,
                "protected_person_context_changed_pixels": 0,
                "person_seed_delta_mae": 10.0,
            }
        )
        metrics.append(
            {
                "timeline_frame": frame,
                "outside_changed_pixels": 0,
                "person_context_changed_pixels": 0,
                "source_backed_any_fraction": 0.92,
                "source_backed_two_observation_fraction": 0.84,
                "model_unresolved_fraction": 0.16,
                "safe_glyph_score_pixels": 7000,
                "safe_glyph_dark_ratio_lt140_before": 0.50,
                "safe_glyph_dark_ratio_lt140_after": 0.10,
                "safe_glyph_dark_reduction": 0.40,
                "right_source_dark_pixels": 4000,
                "right_source_dark_survival_lt140": 0.10,
                "right_source_dark_removal": 0.90,
                "masked_mae": 12.0,
            }
        )
    return {
        "task_id": runner.TASK_ID,
        "ok": True,
        "mode": "offline_source_backed_temporal_recovery_proof_only",
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
        "source_window": [429, 453],
        "frame_count": 24,
        "reference_frame": 443,
        "iteration_guard": {
            "closed_architecture_family": "propainter_semantic_split_person_repair_v1",
            "closed_reason": "V9 technical PASS received human visual FAIL",
            "current_architecture_family": runner.ARCHITECTURE_FAMILY,
            "reopens_closed_family": False,
            "same_family_visual_retry_allowed": False,
            "on_visual_fail": "stop_current_family_no_mask_parameter_retry",
        },
        "architecture": {
            "family": runner.ARCHITECTURE_FAMILY,
            "person_recovery": "pairwise_lk_ransac_stabilization_plus_real_temporal_pixel_plate_then_propainter_residual",
            "background_recovery": "second_propainter_pass_after_person_cleanup",
            "same_family_mask_tuning_retry": False,
            "stabilized_crop": [284, 620, 796, 940],
            "source_backed_known_min_observations": 2,
            "min_any_source_backed_coverage": 0.83,
            "min_two_observation_source_backed_coverage": 0.75,
        },
        "source_authority": {
            "source_video": "input/DZsqH7auhjt.mp4",
            "source_video_sha256": "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635",
            "source_video_fps": 30.0,
            "source_visible_range": [537, 564],
            "foreground_manifest_sha256": "a" * 64,
        },
        "alignment_rows": alignment,
        "coverage_rows": coverage,
        "input_frames": inputs,
        "person_pass_rows": persons,
        "frame_metrics": metrics,
        "artifacts": {
            "comparison_video": "COME_BEFORE_AFTER_SOURCE_BACKED_TEMPORAL_V1.mp4",
            "before_after_contact_sheet": "BEFORE_AFTER_CONTACT_SHEET.png",
            "stabilization_contact_sheet": "STABILIZATION_CONTACT_SHEET.png",
            "source_backed_person_plate": "STABILIZED_SOURCE_BACKED_PERSON_PLATE.png",
            "person_log": "PROPAINTER_PERSON_RUN.log",
            "background_log": "PROPAINTER_BACKGROUND_RUN.log",
            "final_frames": "inpainted_frames",
        },
        "visual_approval_required": True,
    }


def test_validator_accepts_complete_synthetic_technical_pass(tmp_path: Path):
    result = _passing_result()
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(result), encoding="utf-8")
    for name in (
        "COME_BEFORE_AFTER_SOURCE_BACKED_TEMPORAL_V1.mp4",
        "BEFORE_AFTER_CONTACT_SHEET.png",
        "STABILIZATION_CONTACT_SHEET.png",
        "STABILIZED_SOURCE_BACKED_PERSON_PLATE.png",
        "PROPAINTER_PERSON_RUN.log",
        "PROPAINTER_BACKGROUND_RUN.log",
    ):
        (tmp_path / name).write_bytes(b"nonzero")
    final_dir = tmp_path / "inpainted_frames"
    final_dir.mkdir()
    for frame in range(429, 453):
        (final_dir / f"frame_{frame:06d}.png").write_bytes(b"png")

    validator = SCRIPT_DIR / "validate_baked_caption_source_backed_temporal_recovery_v1.py"
    completed = subprocess.run(
        [sys.executable, str(validator), "--artifact-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    validation = json.loads((tmp_path / "PROOF_VALIDATION.json").read_text(encoding="utf-8"))
    assert validation["technical_pass"] is True
    assert validation["status"] == "technical_pass_visual_pending"


def test_validator_rejects_source_backed_coverage_regression(tmp_path: Path):
    result = _passing_result()
    result["coverage_rows"][0]["source_backed_two_observation_fraction"] = 0.50
    result["coverage_rows"][0]["model_unresolved_fraction"] = 0.50
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(result), encoding="utf-8")
    validator = SCRIPT_DIR / "validate_baked_caption_source_backed_temporal_recovery_v1.py"
    completed = subprocess.run(
        [sys.executable, str(validator), "--artifact-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    validation = json.loads((tmp_path / "PROOF_VALIDATION.json").read_text(encoding="utf-8"))
    assert "source_backed_recoverability" in validation["failed_checks"]


def test_new_scripts_do_not_import_or_invoke_resolve():
    for name in (
        "run_baked_caption_source_backed_temporal_recovery_v1.py",
        "validate_baked_caption_source_backed_temporal_recovery_v1.py",
    ):
        text = (SCRIPT_DIR / name).read_text(encoding="utf-8")
        assert "DaVinciResolveScript" not in text
        assert "SaveProject(" not in text
        assert "scripts/davinci" not in text.replace("\\", "/")
