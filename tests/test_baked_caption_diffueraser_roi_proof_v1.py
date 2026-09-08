from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "analysis" / "run_baked_caption_diffueraser_roi_proof_v1.py"
PROVISIONER_PATH = ROOT / "scripts" / "analysis" / "provision_diffueraser_proof_v1.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_baked_caption_diffueraser_roi_proof_v1.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_task_ids_match():
    runner = load_module("diffueraser_runner_task", RUNNER_PATH)
    provisioner = load_module("diffueraser_provisioner_task", PROVISIONER_PATH)
    validator = load_module("diffueraser_validator_task", VALIDATOR_PATH)
    expected = "DZSQH7AUHJT_BAKED_CAPTION_DIFFUERASER_ROI_PROOF_V1"
    assert runner.TASK_ID == expected
    assert provisioner.TASK_ID == expected
    assert validator.TASK_ID == expected


def test_runner_serializes_nested_windows_paths_as_strings(tmp_path):
    runner = load_module("diffueraser_runner_json_safe", RUNNER_PATH)
    path = tmp_path / "nested" / "frame.png"
    value = {"path": path, "rows": [(path, {"again": path})]}
    safe = runner.json_safe(value)
    assert safe == {"path": str(path), "rows": [[str(path), {"again": str(path)}]]}


def test_diffueraser_source_is_pinned():
    provisioner = load_module("diffueraser_provisioner_pin", PROVISIONER_PATH)
    assert provisioner.DIFFUERASER_COMMIT == "8e6f279ac7531e27ad1849c6f8dab5372a8597e7"
    assert provisioner.MIN_GPU_MEMORY_MIB >= 11000
    assert provisioner.HF_MODELS["diffuEraser"]["revision"] == "ad510dca07fa8e155d4bd8d002085bb8ec8f60e5"
    assert provisioner.HF_MODELS["PCM_Weights"]["revision"] == "39560fead4ce00f94db3cb8e93dd8fba90ec0be6"


def test_interrupted_huggingface_downloads_resume_without_deleting_unmarked_cache():
    source = PROVISIONER_PATH.read_text(encoding="utf-8")
    assert 'dest.exists() and revision_marker.is_file()' in source
    assert 'not revision_marker.is_file() or' not in source


def test_roi_contains_union_and_is_bounded_for_12gb_proof():
    runner = load_module("diffueraser_runner_roi", RUNNER_PATH)
    m1 = np.zeros((1920, 1080), np.uint8)
    m2 = np.zeros_like(m1)
    m1[660:780, 300:700] = 255
    m2[665:790, 350:760] = 255
    x1, y1, x2, y2 = runner.derive_roi([m1, m2], (1920, 1080))
    assert x1 <= 300 and x2 >= 760
    assert y1 <= 660 and y2 >= 790
    assert x2 - x1 >= runner.MIN_ROI_WIDTH
    assert y2 - y1 >= runner.MIN_ROI_HEIGHT
    assert (y2 - y1) / float(x2 - x1) <= 0.78


def test_inward_feather_is_zero_outside_and_full_inside():
    runner = load_module("diffueraser_runner_feather", RUNNER_PATH)
    mask = np.zeros((100, 100), np.uint8)
    mask[20:80, 20:80] = 255
    alpha = runner.inward_feather(mask, 8)
    assert alpha[0, 0] == 0
    assert alpha[20, 20] < 255
    assert alpha[50, 50] == 255


def test_semantic_alpha_preserves_person_outside_caption_repair():
    runner = load_module("diffueraser_runner_alpha", RUNNER_PATH)
    shape = (120, 180)
    row = np.zeros(shape, np.uint8)
    compact = np.zeros(shape, np.uint8)
    score = np.zeros(shape, np.uint8)
    person = np.zeros(shape, np.uint8)
    row[40:80, 20:160] = 255
    compact[50:70, 50:130] = 255
    score[52:68, 55:125] = 255
    person[20:110, 90:170] = 255
    result = runner.build_final_alpha(row, compact, score, person)
    protected = result["protected_person"]
    assert np.all(result["alpha"][protected] == 0)
    assert np.all(result["alpha"][result["source_caption"]] == 255)
    assert np.count_nonzero(result["person_repair"]) > np.count_nonzero((score > 0) & (person > 0))


def test_visual_artifact_metric_catches_black_sky_block():
    runner = load_module("diffueraser_runner_artifact", RUNNER_PATH)
    before = np.full((120, 180, 3), 210, np.uint8)
    after = before.copy()
    alpha = np.zeros((120, 180), np.uint8)
    alpha[20:100, 20:160] = 255
    after[30:90, 30:80] = 40
    caption = np.zeros((120, 180), np.uint8)
    caption[50:70, 80:120] = 255
    person = np.zeros((120, 180), np.uint8)
    metrics = runner.visual_artifact_metrics(before, after, alpha, caption, person)
    assert metrics["new_dark_artifact_ratio"] > runner.MAX_NEW_DARK_ARTIFACT_RATIO


def test_source_glyph_reduction_is_relative_to_source_population():
    runner = load_module("diffueraser_runner_relative_reduction", RUNNER_PATH)
    assert runner.relative_reduction(0.50, 0.10) == 0.80
    assert runner.relative_reduction(0.40, 0.40) == 0.0
    assert runner.relative_reduction(0.0, 0.0) == 0.0


def test_validator_retains_original_glyph_thresholds():
    validator = load_module("diffueraser_validator_thresholds", VALIDATOR_PATH)
    assert validator.MIN_SOURCE_GLYPH_REDUCTION == 0.70
    assert validator.MIN_RIGHT_GLYPH_REMOVAL == 0.75


def test_architecture_family_is_new_and_prior_families_closed():
    runner = load_module("diffueraser_runner_family", RUNNER_PATH)
    assert runner.ARCHITECTURE_FAMILY == "diffueraser_roi_source_authority_semantic_composite_v1"
    assert "propainter_semantic_split_person_repair_v1" in runner.CLOSED_ARCHITECTURE_FAMILIES
    assert "stabilized_source_backed_person_then_background_v1" in runner.CLOSED_ARCHITECTURE_FAMILIES
    assert "propainter_v4_foreground_veto_background_only_v1" in runner.CLOSED_ARCHITECTURE_FAMILIES
