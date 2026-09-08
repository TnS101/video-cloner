from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_is_sparse_v2_restore_from_accepted_size_fix_source():
    text = (ROOT / "resolve_workspace/modules/step_3D_v4_baked_original_caption_removal_window_v1.py").read_text(encoding="utf-8")
    assert 'SOURCE_TIMELINE_NAME = SIZE.TARGET_TIMELINE_NAME' in text
    assert 'TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_baked_remove_window_v1"' in text
    assert 'TARGET_TRACK = 2' in text
    assert 'CLEAN_RANGE = (426, 455)' in text
    assert 'RESTORE_NAME = "VC_BAKED_CAPTION_PIXEL_RESTORE_window_051_056_v1"' in text
    assert 'raw_source' not in text.lower()
    assert 'source_start, source_end = _native_range(properties)' in text
    assert '"source_start": source_start' in text
    assert '"record_start": CLEAN_RANGE[0]' in text


def test_runtime_freezes_captions_and_v4_and_gates_before_save():
    text = (ROOT / "resolve_workspace/modules/step_3D_v4_baked_original_caption_removal_window_v1.py").read_text(encoding="utf-8")
    assert 'V1.caption_snapshots_equal(source_caption_before, after_second_caption)' in text
    assert 'stable_inventory_without_restore(target) == source_inventory_without_restore' in text
    assert 'V4.verify_v4_occlusion(target).get("ok") is True' in text
    assert '_run_pixel_validator(root, report_dir, command)' in text
    assert text.index('_run_pixel_validator(root, report_dir, command)') < text.rindex('save = base.save_project(project_manager)')
    assert '"caption_mutation_count": 0' in text
    assert '"occlusion_mutation_count": 0' in text
    assert '"further_rollout_authorized": False' in text


def test_helper_accepts_lifecycle_style_geometry_when_word_track_is_absent():
    helper = load("scripts/analysis/build_step_3D_v4_baked_original_caption_removal_window_v1.py", "baked_remove_helper_test")
    base = helper.BASE
    style = base.load_json(ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_style.json")
    lifecycle = base.load_json(ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json")
    tracks = base.load_json(ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json")
    style_map, _, lifecycle_map, track_map = base.build_contract_maps(style, lifecycle, tracks)
    assert "sub_052" in lifecycle_map
    assert "sub_052" not in track_map
    assert base.cue_bbox("sub_052", 431, style_map, lifecycle_map, track_map) is not None
    assert "sub_053" in lifecycle_map
    assert "sub_053" not in track_map
    assert base.cue_bbox("sub_053", 434, style_map, lifecycle_map, track_map) is not None


def test_helper_forbids_come_foreground_and_bounds_mask():
    helper = load("scripts/analysis/build_step_3D_v4_baked_original_caption_removal_window_v1.py", "baked_remove_mask_test")
    frame = np.full((120, 100, 3), 180, np.uint8)
    # High-contrast dark glyph-like patch crossing the foreground silhouette.
    cv2.rectangle(frame, (35, 48), (65, 58), (10, 10, 10), -1)
    foreground = np.zeros((120, 100), np.uint8)
    foreground[:, 45:60] = 255
    bbox = [0.30, 0.34, 0.70, 0.56]
    mask, meta = helper.caption_pixel_mask_v2(
        frame, bbox, foreground, [(10, 10, 10)], [(10, 10, 10)], allow_foreground=False
    )
    assert np.count_nonzero(mask) > 0
    assert np.count_nonzero((mask > 0) & (foreground > 0)) == 0
    assert meta["foreground_pixels"] == 0
    assert np.count_nonzero(mask) / mask.size < helper.MAX_MASK_AREA_RATIO


def test_helper_uses_exact_resolve_render_not_source_video():
    text = (ROOT / "scripts/analysis/build_step_3D_v4_baked_original_caption_removal_window_v1.py").read_text(encoding="utf-8")
    assert '--base-render-dir' in text
    assert 'indexed_pngs(base_dir, CONTEXT_RANGE)' in text
    assert 'cv2.VideoCapture' not in text
    assert 'SOURCE_OCCLUDED_CUES = frozenset({"sub_052"})' in text
    assert 'enable_grabcut_fallback=False' in text
    assert 'backend="paddle_humanseg"' in text


def test_pixel_validator_rejects_outside_damage_and_accepts_exact_sparse_restore(tmp_path: Path):
    mod = load("scripts/analysis/validate_step_3D_v4_baked_original_caption_removal_window_v1.py", "baked_pixel_validator_test")
    base_dir = tmp_path / "base"
    generated = tmp_path / "generated"
    target = tmp_path / "target"
    for directory in (base_dir, generated / "cleaned", generated / "masks", target):
        directory.mkdir(parents=True, exist_ok=True)

    frame_rows = []
    for frame in range(400, 480):
        image = np.full((24, 16, 3), frame % 251, np.uint8)
        assert cv2.imwrite(str(base_dir / f"base_{frame:06d}.png"), image)
    for frame in range(426, 455):
        original = cv2.imread(str(base_dir / f"base_{frame:06d}.png"))
        cleaned = original.copy()
        mask = np.zeros(original.shape[:2], np.uint8)
        # Every sentinel/non-sentinel frame gets a tiny non-empty, changing restore
        # so sequence-not-frozen is deterministic.
        mask[5:8, 6:9] = 255
        cleaned[5:8, 6:9] = ((frame * 3) % 255, (frame * 5) % 255, (frame * 7) % 255)
        assert cv2.imwrite(str(generated / "cleaned" / f"cleaned_{frame:06d}.png"), cleaned)
        assert cv2.imwrite(str(generated / "masks" / f"mask_{frame:06d}.png"), mask)
        assert cv2.imwrite(str(target / f"target_{frame:06d}.png"), cleaned)
        frame_rows.append({"frame": frame, "mask_pixels": 9})
    manifest = {
        "task_id": mod.TASK_ID,
        "ok": True,
        "clean_range": [426, 455],
        "checks": {"authority": True},
        "frames": frame_rows,
    }
    (generated / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = mod.validate(base_dir, generated, target)
    assert result["ok"] is True
    damaged = cv2.imread(str(target / "target_000431.png"))
    damaged[0, 0] = 255 - damaged[0, 0]
    cv2.imwrite(str(target / "target_000431.png"), damaged)
    assert mod.validate(base_dir, generated, target)["ok"] is False


def test_preparer_locks_window_and_forbids_unrelated_mutations():
    text = (ROOT / "scripts/davinci/prepare_step_3D_v4_baked_original_caption_removal_window_v1.py").read_text(encoding="utf-8")
    assert '"context_range": CONTEXT_RANGE' in text
    assert '"clean_range": CLEAN_RANGE' in text
    assert '"restore_track": TARGET_TRACK' in text
    assert '"raw_source_rgb_overlay_authorized": False' in text
    assert '"whole_frame_replacement_authorized": False' in text
    assert '"caption_mutation_authorized": False' in text
    assert '"caption_recreation_authorized": False' in text
    assert '"motion_fade_mutation_authorized": False' in text
    assert '"size_fix_mutation_authorized": False' in text
    assert '"occlusion_mutation_authorized": False' in text
    assert '"pre_save_pixel_gate_required": True' in text
    assert '"full_reel_rollout_authorized": False' in text


def test_technical_validator_requires_exact_bounded_result():
    mod = load("scripts/davinci/validate_step_3D_v4_baked_original_caption_removal_window_v1.py", "baked_technical_validator_test")
    report = {
        "ok": True,
        "source_timeline_name": mod.SOURCE,
        "target_timeline_name": mod.TARGET,
        "final_textplus_count": 114,
        "caption_mutation_count": 0,
        "baked_removal_mutation_count": 1,
        "occlusion_mutation_count": 0,
        "restore_track": 2,
        "restore_range": [426, 455],
        "save_call_count": 1,
        "source_timeline_unchanged": True,
        "v4_occlusion_preserved": True,
        "motion_fade_and_size_fix_preserved": True,
        "persistent_readback_ok": True,
        "idempotency_ok": True,
        "pre_save_pixel_authority_ok": True,
        "target_timeline_kept": True,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
    }
    persistent = {"ok": True, "checks": {"a": True}, "visual_approval_required": True, "further_rollout_authorized": False}
    pixel = {"ok": True, "checks": {"a": True}, "sentinel_pass_count": 9, "sentinel_count": 9}
    helper = {"ok": True, "checks": {"a": True}, "clean_range": [426, 455]}
    assert mod.validate(report, persistent, pixel, helper)["ok"] is True
    report["caption_mutation_count"] = 1
    assert mod.validate(report, persistent, pixel, helper)["ok"] is False


def test_preparer_discovers_historical_virtual_environments_before_system_python(tmp_path: Path):
    mod = load(
        "scripts/davinci/prepare_step_3D_v4_baked_original_caption_removal_window_v1.py",
        "baked_remove_preparer_env_discovery_test",
    )
    ocr = tmp_path / "Virtual Environments" / "venv_ocr" / "Scripts" / "python.exe"
    generic = tmp_path / "Virtual Environments" / "venv" / "Scripts" / "python.exe"
    other = tmp_path / "Virtual Environments" / "venv_audio" / "Scripts" / "python.exe"
    for path in (ocr, generic, other):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    rows = mod.python_candidates(tmp_path, None)
    assert rows[0] == str(ocr)
    assert rows[1] == str(generic)
    assert str(other) in rows
    assert rows.index(str(ocr)) < rows.index(sys.executable)


def test_preparer_probe_requires_real_gpu_humanseg_module():
    text = (ROOT / "scripts/davinci/prepare_step_3D_v4_baked_original_caption_removal_window_v1.py").read_text(encoding="utf-8")
    assert "paddle.device.set_device('gpu:0')" in text
    assert "paddlehub.Module(name='humanseg_lite')" in text
    assert "humanseg_module_ok" in text
    assert "timeout=120" in text
