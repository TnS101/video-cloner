from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "analysis" / "run_baked_caption_precaption_source_transport_v1.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_baked_caption_precaption_source_transport_v1.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_architecture_adds_real_precaption_information_and_keeps_closed_families_closed():
    m = load_module(RUNNER_PATH, "source_transport_runner_contract")
    assert m.ARCHITECTURE_FAMILY == "pre_caption_clean_donor_source_transport_v1"
    assert m.ARCHITECTURE_ATTEMPT == 1
    assert m.PRECAPTION_CLEAN_FRAME == 533
    assert m.PRECAPTION_SHARP_FRAME == 534
    assert m.REFERENCE_SOURCE_FRAME == 536
    assert "stabilized_source_backed_person_then_background_v1" in m.CLOSED_ARCHITECTURE_FAMILIES
    assert "diffueraser_roi_source_authority_semantic_composite_v1" in m.CLOSED_ARCHITECTURE_FAMILIES
    assert "lama_highres_roi_source_authority_semantic_composite_v1" in m.CLOSED_ARCHITECTURE_FAMILIES


def test_timeline_source_mapping_is_exact_and_outside_old_target_window():
    m = load_module(RUNNER_PATH, "source_transport_mapping")
    assert len(m.EXPECTED_SOURCE_MAPPING) == 24
    assert m.EXPECTED_SOURCE_MAPPING[429] == 536
    assert m.EXPECTED_SOURCE_MAPPING[452] == 565
    assert m.PRECAPTION_CLEAN_FRAME < min(m.EXPECTED_SOURCE_MAPPING.values())
    assert m.PRECAPTION_SHARP_FRAME < min(m.EXPECTED_SOURCE_MAPPING.values())


def test_compose_to_reference_composes_pairwise_affines():
    m = load_module(RUNNER_PATH, "source_transport_compose")
    pairwise = {}
    for frame in range(m.SOURCE_FRAME_START, m.SOURCE_FRAME_END):
        pairwise[(frame, frame + 1)] = np.array([[1.0, 0.0, 2.0], [0.0, 1.0, -1.0]])
    transforms = m.compose_to_reference(pairwise, m.SOURCE_FRAME_START)
    assert np.allclose(transforms[m.SOURCE_FRAME_START], np.eye(3))
    # A later frame maps backwards to the reference.
    assert np.allclose(transforms[m.SOURCE_FRAME_START + 1][:2, 2], [-2.0, 1.0])


def test_temporal_person_plate_uses_only_person_pixels_without_score():
    m = load_module(RUNNER_PATH, "source_transport_plate")
    images = [
        np.full((4, 5, 3), 10, dtype=np.uint8),
        np.full((4, 5, 3), 30, dtype=np.uint8),
        np.full((4, 5, 3), 50, dtype=np.uint8),
    ]
    person = [np.full((4, 5), 255, dtype=np.uint8) for _ in images]
    score = [np.zeros((4, 5), dtype=np.uint8) for _ in images]
    score[1][1, 2] = 255
    plate, count = m.build_temporal_person_plate(images, person, score)
    assert count[0, 0] == 3
    assert count[1, 2] == 2
    assert np.all(plate[0, 0] == 30)
    assert np.all(plate[1, 2] == 30)  # median of 10 and 50


def test_photometric_fit_recovers_bounded_linear_transform():
    m = load_module(RUNNER_PATH, "source_transport_photo")
    yy, xx = np.mgrid[:30, :40]
    source = np.stack([xx + yy, 2 * xx + yy, xx + 2 * yy], axis=2).astype(np.uint8)
    target = np.clip(source.astype(np.float32) * 1.1 + 7.0, 0, 255).astype(np.uint8)
    support = np.ones((30, 40), dtype=np.uint8) * 255
    params = m.fit_channel_affine(source, target, support)
    assert all(0.9 < gain < 1.25 for gain, _ in params)
    corrected = m.apply_channel_affine(source, params)
    assert float(np.mean(np.abs(corrected.astype(np.int16) - target.astype(np.int16)))) < 2.0


def test_precaption_plate_uses_533_only_inside_contamination():
    m = load_module(RUNNER_PATH, "source_transport_donor")
    frame533 = np.full((40, 50, 3), 100, dtype=np.uint8)
    frame534 = np.full((40, 50, 3), 120, dtype=np.uint8)
    # Give the fit support variation so least-squares remains well-defined.
    for x in range(50):
        frame533[:, x] = 80 + x
        frame534[:, x] = 90 + x
    contamination = np.zeros((40, 50), dtype=np.uint8)
    contamination[15:25, 20:30] = 255
    person = np.zeros_like(contamination)
    identity = np.eye(3)
    plate, provenance, valid, params = m.build_precaption_reference_plate(
        frame533, frame534, identity, identity, contamination, person
    )
    assert np.all(provenance[contamination == 0] == 534)
    assert np.all(provenance[contamination > 0] == 533)
    assert np.all(valid == 255)
    assert np.array_equal(plate[5, 5], frame534[5, 5])
    assert len(params) == 3
    assert any(abs(bias) > 1.0 for _, bias in params)


def test_pairwise_person_affine_recovers_small_translation():
    cv2 = pytest.importorskip("cv2")
    m = load_module(RUNNER_PATH, "source_transport_affine")
    rng = np.random.default_rng(7)
    image = np.zeros((1200, 800, 3), dtype=np.uint8)
    # Textured person-safe support in the same vertical interval as production.
    texture = rng.integers(20, 235, size=(420, 300, 3), dtype=np.uint8)
    image[660:1080, 250:550] = texture
    person = np.zeros((1200, 800), dtype=np.uint8)
    person[640:1120, 220:580] = 255
    score = np.zeros_like(person)
    score[700:760, 330:470] = 255
    matrix_true = np.array([[1.0, 0.0, 6.0], [0.0, 1.0, -4.0]], dtype=np.float32)
    target = cv2.warpAffine(image, matrix_true, (800, 1200))
    target_person = cv2.warpAffine(person, matrix_true, (800, 1200), flags=cv2.INTER_NEAREST)
    target_score = cv2.warpAffine(score, matrix_true, (800, 1200), flags=cv2.INTER_NEAREST)
    matrix, metrics = m.estimate_pairwise_person_affine(
        image, target, person, target_person, score, target_score
    )
    assert metrics["inliers"] >= m.PAIRWISE_MIN_INLIERS
    assert abs(matrix[0, 2] - 6.0) < 1.5
    assert abs(matrix[1, 2] + 4.0) < 1.5




def test_manifest_bridge_resolver_uses_frame_427_outside_target_mapping(tmp_path):
    cv2 = pytest.importorskip("cv2")
    m = load_module(RUNNER_PATH, "source_transport_manifest_bridge")
    person_dir = tmp_path / "person_masks"
    glyph_dir = tmp_path / "glyph_masks"
    person_dir.mkdir()
    glyph_dir.mkdir()
    person_path = person_dir / "person_000427.png"
    glyph_path = glyph_dir / "glyph_000427.png"
    assert cv2.imwrite(str(person_path), np.full((30, 20), 255, dtype=np.uint8))
    glyph = np.zeros((120, 80), dtype=np.uint8)
    glyph[50:70, 30:50] = 255
    assert cv2.imwrite(str(glyph_path), glyph)
    person_sha = hashlib.sha256(person_path.read_bytes()).hexdigest()
    glyph_sha = hashlib.sha256(glyph_path.read_bytes()).hexdigest()
    manifest = {
        "frames": [{
            "timeline_frame": 427,
            "source_video_frame": 534,
            "person_mask": "person_masks/person_000427.png",
            "glyph_mask": "glyph_masks/glyph_000427.png",
            "glyph_mask_sha256": glyph_sha,
            "person": {
                "ok": True,
                "person_mask_sha256": person_sha,
                "person_mask_size": person_path.stat().st_size,
            },
        }]
    }
    class FakeV9:
        @staticmethod
        def load_full_resolution_person_mask(path, shape):
            raw = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            return cv2.resize(raw, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    row = m.resolve_manifest_frame_authority(tmp_path, manifest, 427, 534, (120, 80), FakeV9)
    assert row["source_video_frame"] == 534
    assert row["person_mask_sha256"] == person_sha
    assert row["glyph_mask_sha256"] == glyph_sha
    assert row["person_mask"].shape == (120, 80)


def test_dense_precaption_bridge_uses_thousands_of_real_correspondences():
    cv2 = pytest.importorskip("cv2")
    m = load_module(RUNNER_PATH, "source_transport_dense_bridge")
    rng = np.random.default_rng(19)
    sharp = np.zeros((1200, 800, 3), dtype=np.uint8)
    texture = rng.integers(20, 235, size=(460, 460, 3), dtype=np.uint8)
    sharp[650:1110, 170:630] = texture
    person = np.zeros((1200, 800), dtype=np.uint8)
    person[630:1140, 140:660] = 255
    score = np.zeros_like(person)
    score[700:780, 310:500] = 255
    truth = np.array([[1.0, 0.0, -5.0], [0.0, 1.0, 3.0]], dtype=np.float32)
    clean = cv2.warpAffine(sharp, truth, (800, 1200), borderMode=cv2.BORDER_REFLECT101)
    matrix, metrics = m.estimate_precaption_dense_bridge_affine(sharp, clean, person, score)
    assert metrics["method"] == m.PRECAPTION_BRIDGE_METHOD
    assert metrics["sampled_correspondences"] >= m.DENSE_BRIDGE_MIN_SAMPLED_CORRESPONDENCES
    assert metrics["ransac_inliers"] >= m.DENSE_BRIDGE_MIN_RANSAC_INLIERS
    assert metrics["fb_valid_fraction"] >= m.DENSE_BRIDGE_MIN_FB_VALID_FRACTION
    assert abs(matrix[0, 2] + 5.0) < 1.5
    assert abs(matrix[1, 2] - 3.0) < 1.5


def test_geometry_preflight_flag_and_old_sparse_bridge_are_not_runtime_path():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "--geometry-preflight-only" in source
    assert "estimate_precaption_bridge_affine(" not in source
    assert "foreground_paths[bridge_timeline_frame]" not in source
    assert "calcOpticalFlowFarneback" in source


def passing_result():
    v = load_module(VALIDATOR_PATH, "source_transport_validator_fixture")
    rows = []
    for frame in range(v.SOURCE_FRAME_START, v.SOURCE_FRAME_END + 1):
        rows.append({
            "timeline_frame": frame,
            "outside_authority_changed_pixels": 0,
            "protected_person_changed_pixels": 0,
            "source_backed_combined_fraction": 1.0,
            "source_backed_temporal_any_fraction": 1.0,
            "transported_person_valid_fraction": 1.0,
            "new_dark_artifact_ratio": 0.0,
            "new_bright_artifact_ratio": 0.0,
            "boundary_ring_mae": 0.0,
            "safe_glyph_dark_reduction": 0.9,
            "right_source_dark_removal": 0.9,
        })
    return {
        "task_id": v.TASK_ID,
        "ok": True,
        "architecture": {
            "family": v.ARCHITECTURE_FAMILY,
            "attempt_number": 1,
            "generative_inference_calls": 0,
        },
        "source_authority": {
            "source_video_sha256": v.EXPECTED_SOURCE_VIDEO_SHA256,
            "foreground_manifest_sha256": v.EXPECTED_FOREGROUND_MANIFEST_SHA256,
            "diffueraser_authority_helper_sha256": v.EXPECTED_DIFF_HELPER_SHA256,
            "precaption_clean_source_frame": 533,
            "precaption_sharp_source_frame": 534,
            "bridge_timeline_frame": 427,
            "precaption_bridge_method": v.EXPECTED_PRECAPTION_BRIDGE_METHOD,
        },
        "precaption_dense_bridge": {
            "method": v.EXPECTED_PRECAPTION_BRIDGE_METHOD,
            "support_pixels": v.DENSE_BRIDGE_MIN_SUPPORT_PIXELS + 1000,
            "fb_valid_fraction": 0.99,
            "median_fb_error_process_pixels": 0.1,
            "photometric_mae_process_pixels": 10.0,
            "sampled_correspondences": v.DENSE_BRIDGE_MIN_SAMPLED_CORRESPONDENCES + 1000,
            "ransac_inliers": v.DENSE_BRIDGE_MIN_RANSAC_INLIERS + 1000,
            "median_ransac_error_process_pixels": 0.5,
            "p95_ransac_error_process_pixels": 1.0,
        },
        "frame_metrics": rows,
        "resolve_invocations": 0,
        "timeline_mutations": 0,
        "save_project_calls": 0,
    }


def test_validator_accepts_exact_source_backed_contract():
    v = load_module(VALIDATOR_PATH, "source_transport_validator_pass")
    assert v.validate_result(passing_result()) == []


def test_validator_rejects_old_coverage_failure_without_lowering_gate():
    v = load_module(VALIDATOR_PATH, "source_transport_validator_coverage")
    result = passing_result()
    result["frame_metrics"][0]["source_backed_combined_fraction"] = 0.753131
    assert "source_backed_coverage:429" in v.validate_result(result)


def test_validator_rejects_generative_inference():
    v = load_module(VALIDATOR_PATH, "source_transport_validator_generation")
    result = passing_result()
    result["architecture"]["generative_inference_calls"] = 1
    with pytest.raises(v.ValidationError, match="generative inference"):
        v.validate_result(result)


def test_validator_preserves_existing_visual_proxy_gates():
    v = load_module(VALIDATOR_PATH, "source_transport_validator_artifact")
    result = passing_result()
    result["frame_metrics"][10]["new_bright_artifact_ratio"] = 0.031
    result["frame_metrics"][14]["boundary_ring_mae"] = 30.1
    failures = v.validate_result(result)
    assert "new_bright_artifact:439" in failures
    assert "boundary_ring_mae:443" in failures


def test_validator_preserves_hold_glyph_gates():
    v = load_module(VALIDATOR_PATH, "source_transport_validator_glyph")
    result = passing_result()
    by = {row["timeline_frame"]: row for row in result["frame_metrics"]}
    by[448]["safe_glyph_dark_reduction"] = 0.699
    by[438]["right_source_dark_removal"] = 0.749
    failures = v.validate_result(result)
    assert "source_glyph_reduction:448" in failures
    assert "right_glyph_removal:438" in failures


def test_validator_rejects_sparse_or_low_quality_precaption_bridge():
    v = load_module(VALIDATOR_PATH, "source_transport_validator_dense_bridge")
    result = passing_result()
    result["source_authority"]["precaption_bridge_method"] = "sparse_lk_affine"
    with pytest.raises(v.ValidationError, match="dense bridge method"):
        v.validate_result(result)
    result = passing_result()
    result["precaption_dense_bridge"]["ransac_inliers"] = v.DENSE_BRIDGE_MIN_RANSAC_INLIERS - 1
    assert "dense_bridge_ransac_inliers" in v.validate_result(result)


def test_source_contains_no_closed_inference_execution_path():
    text = RUNNER_PATH.read_text(encoding="utf-8")
    assert "run_propainter_pass(" not in text
    assert "run_diffueraser(" not in text
    assert "run_lama_inference(" not in text
    assert "torch.jit.load" not in text
    assert "SaveProject(" not in text

def test_comparison_video_has_no_imageio_dependency_and_uses_opencv_writer(tmp_path):
    cv2 = pytest.importorskip("cv2")
    m = load_module(RUNNER_PATH, "source_transport_video_writer")
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "import imageio" not in source
    assert "imageio.mimwrite" not in source
    frames = [
        np.full((48, 64, 3), (20 + i * 20), dtype=np.uint8)
        for i in range(3)
    ]
    output = tmp_path / "probe.mp4"
    info = m.write_rgb_mp4(output, frames, 24.0)
    assert output.is_file() and output.stat().st_size > 0
    assert info["backend"] == "opencv"
    assert info["frame_count"] == 3
    cap = cv2.VideoCapture(str(output))
    assert cap.isOpened()
    decoded = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        assert frame.shape[:2] == (48, 64)
        decoded += 1
    cap.release()
    assert decoded == 3


def test_validator_main_writes_full_outputs_without_scope_or_report_errors(tmp_path, monkeypatch):
    v = load_module(VALIDATOR_PATH, "source_transport_validator_main_regression")
    result = passing_result()
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name in v.REQUIRED_ARTIFACT_NAMES:
        path = tmp_path / name
        if path.name == "PROOF_RUN_RESULT.json":
            continue
        path.write_bytes(b"validator-main-regression\n")
    final_dir = tmp_path / "inpainted_frames"
    final_dir.mkdir()
    for frame in range(v.SOURCE_FRAME_START, v.SOURCE_FRAME_END + 1):
        (final_dir / f"frame_{frame:06d}.png").write_bytes(b"png-regression\n")
    monkeypatch.setattr(sys, "argv", ["validator", "--artifact-dir", str(tmp_path)])
    assert v.main() == 0
    validation = json.loads((tmp_path / "PROOF_VALIDATION.json").read_text(encoding="utf-8"))
    assert validation["status"] == "technical_pass_visual_pending"
    assert validation["technical_pass"] is True
    assert validation["failures"] == []
    assert validation["precaption_dense_bridge"] == result["precaption_dense_bridge"]
    report = (tmp_path / "FINAL_REPORT.md").read_text(encoding="utf-8")
    assert "Technical pass: `true`" in report
    assert "| 448 |" in report
