from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "analysis" / "run_baked_caption_semantic_sky_plate_proof_v1.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_baked_caption_semantic_sky_plate_proof_v1.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load("semantic_sky_runner", RUNNER_PATH)
validator = _load("semantic_sky_validator", VALIDATOR_PATH)


def test_contract_is_offline_and_bounded():
    assert runner.TASK_ID == "DZSQH7AUHJT_BAKED_CAPTION_SEMANTIC_SKY_PLATE_PROOF_V1"
    assert runner.SOURCE_FRAME_START == 429
    assert runner.SOURCE_FRAME_END == 452
    assert runner.FRAME_COUNT == 24
    assert runner.PERSON_LABEL == 1
    assert runner.MAX_DYNAMIC_RIGHT_GUARD_PIXELS == 180
    assert runner.MIN_REMOVAL_PIXELS == 15_000
    assert validator.MIN_REMOVAL_PIXELS == 15_000


def test_choose_person_instance_prefers_central_person():
    h, w = 200, 120
    labels = np.array([1, 1, 3])
    scores = np.array([0.95, 0.90, 0.99])
    boxes = np.array([[2, 20, 25, 190], [35, 15, 90, 195], [40, 20, 95, 180]], dtype=np.float32)
    masks = np.zeros((3, 1, h, w), dtype=np.float32)
    masks[0, 0, 20:190, 2:25] = 1.0
    masks[1, 0, 15:195, 35:90] = 1.0
    masks[2, 0, 20:180, 40:95] = 1.0
    old_min_area = runner.MIN_PERSON_MASK_AREA
    old_max_area = runner.MAX_PERSON_MASK_AREA
    old_overlap = runner.MIN_PERSON_ROI_OVERLAP
    try:
        runner.MIN_PERSON_MASK_AREA = 500
        runner.MAX_PERSON_MASK_AREA = 50_000
        runner.MIN_PERSON_ROI_OVERLAP = 300
        selected = runner.choose_person_instance(labels, scores, boxes, masks, frame_shape=(h, w))
    finally:
        runner.MIN_PERSON_MASK_AREA = old_min_area
        runner.MAX_PERSON_MASK_AREA = old_max_area
        runner.MIN_PERSON_ROI_OVERLAP = old_overlap
    assert selected["index"] == 1
    assert selected["roi_overlap"] > 300


def test_choose_person_instance_rejects_nonperson_only():
    h, w = 200, 120
    labels = np.array([3])
    scores = np.array([0.99])
    boxes = np.array([[35, 15, 90, 195]], dtype=np.float32)
    masks = np.ones((1, 1, h, w), dtype=np.float32)
    try:
        runner.choose_person_instance(labels, scores, boxes, masks, frame_shape=(h, w))
    except runner.ProofError as exc:
        assert "valid central person" in str(exc)
    else:
        raise AssertionError("expected ProofError")


def test_person_guard_stays_inside_expanded_box():
    mask = np.zeros((100, 120), dtype=bool)
    mask[20:90, 30:80] = True
    guard = runner.build_person_guard(mask, [30, 20, 80, 90])
    assert guard.shape == mask.shape
    assert guard[50, 50]
    assert not guard[0, 0]
    assert not guard[:, 100:].any()


def test_semantic_sky_plate_preserves_person_and_outside_authority():
    image = np.full((80, 120, 3), 200, dtype=np.uint8)
    image[:, :, 0] = 210
    image[30:50, 35:85] = (20, 20, 20)
    authority = np.zeros((80, 120), dtype=bool)
    authority[25:55, 25:95] = True
    person = np.zeros((80, 120), dtype=bool)
    person[28:58, 52:68] = True
    image[person] = (40, 50, 60)
    score = np.zeros((80, 120), dtype=np.uint8)
    score[30:50, 35:85] = 255
    old_min = runner.SKY_MIN_SAMPLES_PER_SIDE
    old_removal = runner.MIN_REMOVAL_PIXELS
    try:
        runner.SKY_MIN_SAMPLES_PER_SIDE = 2
        runner.MIN_REMOVAL_PIXELS = 100
        final, removal, alpha = runner.apply_semantic_sky_plate(image, authority, person, (25, 25, 95, 55), score)
    finally:
        runner.SKY_MIN_SAMPLES_PER_SIDE = old_min
        runner.MIN_REMOVAL_PIXELS = old_removal
    assert removal.any()
    assert alpha.max() == 1.0
    assert np.array_equal(final[person], image[person])
    assert np.array_equal(final[~authority], image[~authority])
    assert np.mean(final[35:45, 40:50]) > 100


def test_validator_rejects_person_mutation(tmp_path: Path):
    payload = _synthetic_payload()
    payload["frame_metrics"][0]["person_changed_pixels"] = 1
    _write_required_artifacts(tmp_path)
    result = validator.evaluate(payload, tmp_path)
    assert not result["checks"]["person_exact"]
    assert not result["technical_pass"]


def test_validator_accepts_complete_synthetic_contract(tmp_path: Path):
    payload = _synthetic_payload()
    _write_required_artifacts(tmp_path)
    result = validator.evaluate(payload, tmp_path)
    assert result["technical_pass"]
    assert result["status"] == "technical_pass_visual_pending"


def _synthetic_payload():
    rows = []
    for frame in range(429, 453):
        rows.append(
            {
                "timeline_frame": frame,
                "dynamic_right_guard_pixels": 60,
                "score_mask_coverage": 0.98,
                "removal_pixels": 30_000,
                "person_score": 0.95,
                "person_mask_area": 180_000,
                "person_roi_overlap": 100_000,
                "person_changed_pixels": 0,
                "outside_changed_pixels": 0,
                "safe_glyph_dark_ratio_lt140_before": 0.80,
                "safe_glyph_dark_ratio_lt140_after": 0.05,
                "right_source_dark_pixels": 5000,
                "right_source_dark_survival_lt140": 0.05,
            }
        )
    return {
        "task_id": runner.TASK_ID,
        "ok": True,
        "mode": "offline_semantic_person_sky_plate_proof_only",
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
        "source_window": [429, 453],
        "frame_count": 24,
        "semantic_person_model": {
            "model": runner.MASKRCNN_MODEL,
            "weights": runner.MASKRCNN_WEIGHT_ENUM,
            "person_label": 1,
            "score_min": 0.75,
            "mask_threshold": 0.5,
            "guard_dilation_pixels": 4,
            "weight_file": {"sha256": "a" * 64, "bytes": 180_000_000},
            "gpu": "NVIDIA GeForce RTX 5070",
        },
        "sky_plate": {
            "strategy": "same_frame_rowwise_sky_interpolation_inside_come_authority_minus_semantic_person_v1",
            "semantic_authority_dilation_pixels": 3,
            "max_dynamic_right_guard_pixels": 180,
            "min_score_mask_coverage": 0.92,
            "person_pixels_are_exact_source": True,
            "outside_authority_pixels_are_exact_source": True,
        },
        "frame_metrics": rows,
    }


def _write_required_artifacts(tmp_path: Path):
    for name in (
        "COME_BEFORE_AFTER_PROOF_V6.mp4",
        "BEFORE_AFTER_CONTACT_SHEET.png",
        "MASK_CONTACT_SHEET.png",
        "PERSON_MASK_CONTACT_SHEET.png",
    ):
        (tmp_path / name).write_bytes(b"x" * 20_000)
    out = tmp_path / "semantic_sky_frames"
    person = tmp_path / "person_masks"
    authority = tmp_path / "semantic_authority_masks"
    out.mkdir()
    person.mkdir()
    authority.mkdir()
    for frame in range(429, 453):
        (out / f"frame_{frame:06d}.png").write_bytes(b"x")
        (person / f"person_{frame:06d}.png").write_bytes(b"x")
        (authority / f"authority_{frame:06d}.png").write_bytes(b"x")
