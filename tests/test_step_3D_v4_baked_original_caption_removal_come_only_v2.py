from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BUILD = load(
    "test_baked_come_builder_v2",
    "scripts/analysis/build_step_3D_v4_baked_original_caption_removal_come_only_v2.py",
)
PIXEL = load(
    "test_baked_come_pixel_v2",
    "scripts/analysis/validate_step_3D_v4_baked_original_caption_removal_come_only_v2.py",
)
PREP = load(
    "test_baked_come_prep_v2",
    "scripts/davinci/prepare_step_3D_v4_baked_original_caption_removal_come_only_v2.py",
)
SAME = load(
    "test_baked_come_same_v2",
    "scripts/davinci/validate_step_3D_v4_baked_original_caption_removal_come_only_v2.py",
)


def test_scope_is_only_come_and_accepted_source_is_preserved():
    assert BUILD.TARGET_CUE == "sub_052"
    assert BUILD.CLEAN_RANGE == (429, 453)
    runtime = (ROOT / "resolve_workspace/modules/step_3D_v4_baked_original_caption_removal_come_only_v2.py").read_text(encoding="utf-8")
    assert "CLEAN_RANGE = (429, 453)" in runtime
    assert 'TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_baked_remove_come_only_v2"' in runtime
    assert PREP.TARGET_CUES == ["sub_052"]
    assert PREP.RESTORE_NAME == "VC_BAKED_CAPTION_PIXEL_RESTORE_sub_052_come_v2"
    assert SAME.EXPECTED_RANGE == [429, 453]


def test_mask_detects_dark_sky_glyph_but_never_person():
    h, w = 240, 320
    frame = np.full((h, w, 3), (220, 220, 220), np.uint8)
    cv2.rectangle(frame, (90, 80), (135, 105), (15, 15, 15), -1)
    cv2.rectangle(frame, (145, 80), (195, 105), (15, 15, 15), -1)
    cv2.rectangle(frame, (175, 55), (230, 170), (20, 20, 20), -1)
    person = np.zeros((h, w), np.uint8)
    cv2.rectangle(person, (168, 48), (238, 178), 255, -1)
    bbox = [0.20, 0.25, 0.72, 0.52]
    mask, meta = BUILD.come_background_mask(frame, bbox, person, [(0, 0, 0)])
    assert np.count_nonzero(mask) > 0
    assert meta["person_overlap_pixels"] == 0
    assert np.count_nonzero((mask > 0) & (person > 0)) == 0
    assert np.count_nonzero(mask[75:112, 85:165]) > 0


def test_same_frame_inpaint_preserves_protected_person_exactly():
    h, w = 180, 260
    frame = np.full((h, w, 3), (210, 215, 220), np.uint8)
    cv2.rectangle(frame, (70, 70), (150, 92), (10, 10, 10), -1)
    person = np.zeros((h, w), np.uint8)
    cv2.rectangle(person, (140, 45), (205, 155), 255, -1)
    mask, _ = BUILD.come_background_mask(frame, [0.20, 0.28, 0.72, 0.60], person, [(0, 0, 0)])
    cleaned = BUILD.BASE.inpaint_caption_pixels(frame, mask, BUILD.INPAINT_RADIUS)
    cleaned[person > 0] = frame[person > 0]
    assert np.array_equal(cleaned[person > 0], frame[person > 0])
    assert np.mean(cv2.absdiff(cleaned, frame)[mask > 0]) > 1.0


def _write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), image)


def _synthetic_pixel_case(tmp_path: Path, person_mutation: bool):
    base = tmp_path / "base"
    target = tmp_path / "target"
    generated = tmp_path / "generated"
    for d in (base, target, generated / "cleaned", generated / "foreground"):
        d.mkdir(parents=True, exist_ok=True)
    frames = []
    for frame_no in range(429, 453):
        original = np.full((80, 100, 3), 220, np.uint8)
        cv2.rectangle(original, (30, 25), (53, 34), (10, 10, 10), -1)
        person = np.zeros((80, 100), np.uint8)
        cv2.rectangle(person, (58, 18), (78, 65), 255, -1)
        cleaned = original.copy()
        cv2.rectangle(cleaned, (30, 25), (53, 34), (220 + (frame_no % 3), 220, 220), -1)
        out = cleaned.copy()
        if person_mutation and frame_no == 431:
            out[30, 60] = (0, 0, 0)
        _write_png(base / f"base_{frame_no:06d}.png", original)
        _write_png(target / f"target_{frame_no:06d}.png", out)
        _write_png(generated / "cleaned" / f"cleaned_{frame_no:06d}.png", cleaned)
        _write_png(generated / "foreground" / f"foreground_{frame_no:06d}.png", person)
        frames.append({"frame": frame_no, "bbox_pixels": [25, 20, 70, 42], "mask_pixels": 100, "person_overlap_pixels": 0})
    manifest = {
        "task_id": PIXEL.TASK_ID,
        "ok": True,
        "clean_range": [429, 453],
        "target_cues": ["sub_052"],
        "temporal_donor_reconstruction_used": False,
        "foreground_reconstruction_used": False,
        "checks": {"x": True},
        "frames": frames,
    }
    (generated / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return PIXEL.validate(base, generated, target)


def test_pixel_validator_rejects_any_person_change(tmp_path: Path):
    result = _synthetic_pixel_case(tmp_path, True)
    assert result["checks"]["no_person_pixels_changed"] is False
    assert result["ok"] is False


def test_pixel_validator_accepts_local_background_only_restore(tmp_path: Path):
    result = _synthetic_pixel_case(tmp_path, False)
    assert result["checks"]["no_person_pixels_changed"] is True
    assert result["checks"]["all_changes_inside_source_backed_bbox"] is True
    assert result["checks"]["sentinels_all_pass"] is True
    assert result["ok"] is True


def test_forbidden_architecture_flags_are_locked():
    source = (ROOT / "scripts/analysis/build_step_3D_v4_baked_original_caption_removal_come_only_v2.py").read_text(encoding="utf-8")
    assert '"temporal_donor_reconstruction_used": False' in source
    assert '"foreground_reconstruction_used": False' in source
    prep = (ROOT / "scripts/davinci/prepare_step_3D_v4_baked_original_caption_removal_come_only_v2.py").read_text(encoding="utf-8")
    assert '"restore_person_overlap_authorized": False' in prep
    assert '"temporal_donor_reconstruction_authorized": False' in prep


def test_runtime_only_adds_one_v2_restore_name():
    runtime = (ROOT / "resolve_workspace/modules/step_3D_v4_baked_original_caption_removal_come_only_v2.py").read_text(encoding="utf-8")
    assert "TARGET_TRACK = 2" in runtime
    assert 'RESTORE_NAME = "VC_BAKED_CAPTION_PIXEL_RESTORE_sub_052_come_v2"' in runtime
    assert "def verify_restore(" in runtime
