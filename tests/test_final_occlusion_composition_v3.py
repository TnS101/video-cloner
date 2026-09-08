from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load_module("occlusion_v3_helper", "scripts/analysis/build_final_occlusion_pixel_restore_v3.py")
preparer = load_module("occlusion_v3_preparer", "scripts/davinci/prepare_final_occlusion_composition_v3.py")
validator = load_module("occlusion_v3_validator", "scripts/davinci/validate_final_occlusion_composition_v3.py")


def test_v3_starts_from_accepted_source_and_rejects_v1_v2_targets():
    assert preparer.SOURCE_TIMELINE_NAME.endswith("_confirmed74_repair_metrics_v1")
    assert preparer.REJECTED_V1_TIMELINE_NAME.endswith("_occlusion_complete_v1")
    assert preparer.REJECTED_V2_TIMELINE_NAME.endswith("_occlusion_complete_v2")
    assert preparer.TARGET_TIMELINE_NAME.endswith("_occlusion_complete_v3")
    assert preparer.SOURCE_TIMELINE_NAME not in {preparer.REJECTED_V1_TIMELINE_NAME, preparer.REJECTED_V2_TIMELINE_NAME}


def test_v3_contract_freezes_persistent_caption_state():
    assert preparer.EXPECTED_TEXTPLUS_COUNT == 114
    assert preparer.TARGET_CAPTION_NAME == "VC_TEXTPLUS_0052_sub_052"
    assert preparer.TARGET_RANGE == [426, 454]
    assert preparer.NEW_MATTE_NAME.startswith("VC_OCCLUSION_PIXEL_RESTORE_")
    helper_source = Path(ROOT / preparer.HELPER).read_text(encoding="utf-8").lower()
    assert "cv2.grabcut" not in helper_source
    assert "estimateaffinepartial2d" in helper_source


def test_clean_humanseg_anchor_hashes_are_exact():
    result = preparer.validate_anchors(ROOT)
    assert result["ok"] is True
    assert len(result["rows"]) == 5
    assert all(row["matched"] for row in result["rows"])


def test_timeline_to_source_mapping_matches_proven_30_over_24_policy():
    assert [helper.timeline_to_source_frame(frame) for frame in range(426, 434)] == [532, 534, 535, 536, 538, 539, 540, 541]
    assert [helper.timeline_to_source_frame(frame) for frame in range(451, 454)] == [564, 565, 566]


def test_glyph_mask_uses_resolve_difference_and_rejects_isolated_noise():
    without = np.zeros((32, 32, 3), dtype=np.uint8)
    with_come = without.copy()
    with_come[10:18, 9:23] = 180
    with_come[0, 0] = 2  # isolated render noise must not become glyph authority
    glyph, info = helper.caption_glyph_mask(with_come, without)
    assert info["strong_pixels"] == 8 * 14
    assert glyph[12, 12] == 255
    assert glyph[0, 0] == 0
    assert info["glyph_pixels"] >= info["strong_pixels"]


def test_restore_rgba_is_sparse_and_rgb_comes_only_from_without_come_render():
    with_come = np.zeros((1920, 1080, 3), dtype=np.uint8)
    without = np.zeros_like(with_come)
    without[:] = (21, 42, 84)
    with_come[:] = without
    with_come[800:840, 450:650] = (0, 0, 0)
    person = np.zeros((540, 304), dtype=np.uint8)
    person[210:300, 125:180] = 255
    bgra, glyph, person_full, stats = helper.build_restore_bgra(with_come, without, person)
    alpha = bgra[:, :, 3]
    active = alpha > 0
    assert stats["alpha_pixels"] > 0
    assert np.count_nonzero(active & (glyph == 0)) == 0
    assert np.all(bgra[:, :, :3][~active] == 0)
    assert np.array_equal(bgra[:, :, :3][active], without[active])
    assert np.count_nonzero(active & (person_full == 0)) == 0


def test_validator_recomputes_same_glyph_authority_independently():
    rng = np.random.default_rng(12)
    without = rng.integers(0, 180, size=(64, 64, 3), dtype=np.uint8)
    with_come = without.copy()
    with_come[20:35, 15:50] = np.clip(with_come[20:35, 15:50].astype(np.int16) + 70, 0, 255).astype(np.uint8)
    from_helper, _ = helper.caption_glyph_mask(with_come, without)
    from_validator = validator.recompute_glyph(with_come, without)
    assert np.array_equal(from_helper, from_validator)


def test_affine_guard_accepts_small_motion_and_rejects_shape_breaking_transform():
    good = np.array([[1.0, 0.0, 2.0], [0.0, 1.0, -1.0]], dtype=np.float64)
    bad = np.array([[1.25, 0.0, 0.0], [0.0, 1.25, 0.0]], dtype=np.float64)
    assert helper.validate_affine(good, inliers=20, tracked=30)["ok"] is True
    assert helper.validate_affine(bad, inliers=20, tracked=30)["ok"] is False


def test_affine_mask_warp_cannot_grow_caption_shaped_content_locally():
    mask = np.zeros((540, 304), dtype=np.uint8)
    cv2.ellipse(mask, (150, 270), (45, 160), 0, 0, 360, 255, -1)
    matrix = np.array([[1.0, 0.0, 4.0], [0.0, 1.0, 3.0]], dtype=np.float64)
    warped = helper.warp_mask(mask, matrix)
    expected = cv2.warpAffine(mask, matrix, (304, 540), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    assert np.array_equal(warped, expected)


def test_external_python_probe_requires_cv2_and_numpy():
    result = preparer.validate_external_python()
    assert result["ok"] is True
    assert result["versions"]["cv2"]
    assert result["versions"]["numpy"]


def test_v3_validator_requires_non_self_referential_authorities():
    source = Path(ROOT / "scripts/davinci/validate_final_occlusion_composition_v3.py").read_text(encoding="utf-8")
    assert "person_affine_authority" in source
    assert "glyph_authority" in source
    assert "rgba_rgb_authority" in source
    assert "core_vs_without_mae" in source
    assert "outside_changed_fraction" in source


def test_runtime_uses_temporary_caption_toggle_only_before_fresh_target():
    source = Path(ROOT / "resolve_workspace/modules/final_occlusion_composition_v3.py").read_text(encoding="utf-8")
    assert 'SetClipEnabled", False' in source
    assert "temporary_caption_toggle_count" in source
    assert "caption_mutation_count\": 0" in source
    assert source.index("DuplicateTimeline\", temp_name") < source.index("DuplicateTimeline\", TARGET_TIMELINE_NAME")


def test_v3_source_video_contract_is_unchanged():
    expected = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
    assert preparer.SOURCE_VIDEO_SHA256 == expected
    assert helper.SOURCE_VIDEO_SHA256 == expected
