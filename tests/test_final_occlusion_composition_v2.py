from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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


preparer = load_module("final_occlusion_v2_preparer", "scripts/davinci/prepare_final_occlusion_composition_v2.py")
validator = load_module("final_occlusion_v2_validator", "scripts/davinci/validate_final_occlusion_composition_v2.py")


def test_temporal_asset_contract_is_exact_28_frame_span():
    result = preparer.validate_temporal_asset(ROOT)
    assert result["timeline_range"] == [426, 454]
    assert result["duration_frames"] == 28
    assert result["approved_anchor_frames"] == [429, 430, 431, 432, 433]
    assert result["asset_file_count"] == 29


def test_temporal_manifest_hashes_match_every_rgba_file():
    manifest = json.loads((ROOT / preparer.ASSET_MANIFEST).read_text(encoding="utf-8"))
    for row in manifest["frames"]:
        frame = row["timeline_frame"]
        path = ROOT / preparer.ASSET_DIR / f"rgba_{frame:06d}.png"
        assert row["rgba_sha256"] == preparer.raw_sha256(path)
        assert row["rgba_size"] == path.stat().st_size
        assert preparer.png_rgba_dimensions(path) == (1080, 1920)


def test_temporal_asset_reuses_original_approved_anchor_bytes_exactly():
    for frame in range(429, 434):
        new = ROOT / preparer.ASSET_DIR / f"rgba_{frame:06d}.png"
        old = ROOT / preparer.OLD_ASSET_DIR / f"rgba_{frame:06d}.png"
        assert preparer.raw_sha256(new) == preparer.raw_sha256(old)


def test_pixel_sentinels_measure_only_new_temporal_extension():
    manifest = json.loads((ROOT / preparer.ASSET_MANIFEST).read_text(encoding="utf-8"))
    sentinels = manifest["validation_contract"]["sentinel_frames"]
    assert sentinels == [434, 438, 443, 448, 452, 453]
    assert all(frame < 429 or frame >= 434 for frame in sentinels)


def test_temporal_mapping_matches_nearest_30fps_source_policy():
    manifest = json.loads((ROOT / preparer.ASSET_MANIFEST).read_text(encoding="utf-8"))
    mappings = [(row["timeline_frame"], row["source_video_frame"]) for row in manifest["frames"]]
    assert mappings[:8] == [(426, 532), (427, 534), (428, 535), (429, 536), (430, 538), (431, 539), (432, 540), (433, 541)]
    assert mappings[-3:] == [(451, 564), (452, 565), (453, 566)]


def test_prior_accepted_source_is_still_114_textplus_baseline():
    report = json.loads((ROOT / preparer.PRIOR_REPORT).read_text(encoding="utf-8-sig"))
    persistent = json.loads((ROOT / preparer.PRIOR_PERSISTENT).read_text(encoding="utf-8-sig"))
    preparer.validate_prior(report, persistent)
    assert report["target_timeline_name"] == preparer.SOURCE_TIMELINE_NAME
    assert report["final_textplus_count"] == 114


def test_v2_never_uses_rejected_v1_target_as_source():
    assert preparer.SOURCE_TIMELINE_NAME.endswith("_confirmed74_repair_metrics_v1")
    assert preparer.REJECTED_V1_TIMELINE_NAME.endswith("_occlusion_complete_v1")
    assert preparer.TARGET_TIMELINE_NAME.endswith("_occlusion_complete_v2")
    assert preparer.SOURCE_TIMELINE_NAME not in {preparer.REJECTED_V1_TIMELINE_NAME, preparer.TARGET_TIMELINE_NAME}


def test_publisher_contract_forbids_caption_mutation_and_requires_pixel_evidence():
    assert preparer.EXPECTED_TEXTPLUS_COUNT == 114
    assert preparer.NEW_MATTE_RANGE == [426, 454]
    assert preparer.NEW_MATTE_NAME == "VC_OCCLUSION_RGBA_matte_span_0001_temporal_v2_sub_0052"
    assert len(preparer.ASSET_FILES) == 29
    assert preparer.SOURCE_VIDEO_SHA256 == "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"


def test_pixel_summary_localizes_change_inside_alpha():
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    target = source.copy()
    alpha = np.zeros((8, 8), dtype=np.uint8)
    alpha[2:6, 2:6] = 255
    target[3:5, 3:5] = 100
    row = validator.summarize_pixel_diff(source, target, alpha, 440)
    assert row["outside_changed_pixels"] == 0
    assert row["outside_changed_fraction"] == 0.0
    assert row["inside_changed_pixels"] == 4
    assert row["inside_mae"] > 0


def test_pixel_summary_detects_unrelated_outside_alpha_change():
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    target = source.copy()
    alpha = np.zeros((8, 8), dtype=np.uint8)
    alpha[2:6, 2:6] = 255
    target[0, 0] = 100
    row = validator.summarize_pixel_diff(source, target, alpha, 440)
    assert row["outside_changed_pixels"] == 1
    assert row["outside_changed_fraction"] > 0


def test_validator_requires_exact_temporal_matte_and_pixel_gate():
    assert validator.NEW_MATTE_RANGE == [426, 454]
    assert validator.NEW_MATTE_DURATION == 28
    assert validator.SOURCE_TIMELINE_NAME == preparer.SOURCE_TIMELINE_NAME
    assert validator.TARGET_TIMELINE_NAME == preparer.TARGET_TIMELINE_NAME


def test_temporal_asset_rejects_wrong_duration(tmp_path):
    # Validate the strict manifest geometry logic without mutating repository input.
    manifest = json.loads((ROOT / preparer.ASSET_MANIFEST).read_text(encoding="utf-8"))
    manifest["duration_frames"] = 27
    clone = tmp_path / "repo"
    asset_dir = clone / preparer.ASSET_DIR
    asset_dir.mkdir(parents=True)
    (asset_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="temporal_asset_contract"):
        preparer.validate_temporal_asset(clone)
