from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load_module("occlusion_v4_runtime", "resolve_workspace/modules/final_occlusion_composition_v4.py")
pixels = load_module("occlusion_v4_pixels", "scripts/analysis/validate_final_occlusion_pixel_restore_v4.py")
preparer = load_module("occlusion_v4_preparer", "scripts/davinci/prepare_final_occlusion_composition_v4.py")


def test_v4_starts_from_accepted_source_and_rejects_all_failed_targets():
    assert runtime.SOURCE_TIMELINE_NAME.endswith("_confirmed74_repair_metrics_v1")
    assert runtime.REJECTED_V1_TIMELINE_NAME.endswith("_occlusion_complete_v1")
    assert runtime.REJECTED_V2_TIMELINE_NAME.endswith("_occlusion_complete_v2")
    assert runtime.REJECTED_V3_TIMELINE_NAME.endswith("_occlusion_complete_v3")
    assert runtime.TARGET_TIMELINE_NAME.endswith("_occlusion_complete_v4")
    assert runtime.SOURCE_TIMELINE_NAME not in {
        runtime.REJECTED_V1_TIMELINE_NAME,
        runtime.REJECTED_V2_TIMELINE_NAME,
        runtime.REJECTED_V3_TIMELINE_NAME,
    }


def test_v3_failure_evidence_proves_relative_zero_vs_native_range_mismatch():
    technical = json.loads((ROOT / preparer.V3_TECHNICAL).read_text(encoding="utf-8"))
    pixel = json.loads((ROOT / preparer.V3_PIXEL).read_text(encoding="utf-8"))
    application = json.loads((ROOT / preparer.V3_APPLICATION).read_text(encoding="utf-8"))
    result = preparer.validate_v3_failure(technical, pixel, application)
    assert result["ok"] is True
    assert result["rejected_source_range"] == [0, 28]
    assert result["media_pool_native_range"] == [426, 454]


def test_native_source_range_requires_media_pool_native_indices():
    props = {"Start": "426", "End": "453", "Frames": "28"}
    assert runtime.native_source_range(props) == (426, 454)


def test_native_source_range_rejects_relative_zero_metadata():
    props = {"Start": "0", "End": "27", "Frames": "28"}
    try:
        runtime.native_source_range(props)
    except RuntimeError as exc:
        assert "native_sequence_range" in str(exc)
    else:
        raise AssertionError("relative zero metadata must be rejected")


def test_append_uses_native_426_454_not_relative_zero(monkeypatch):
    captured = {}
    dummy_item = object()

    def fake_append(project, timeline, clip_rows, target_track):
        captured["rows"] = clip_rows
        captured["target_track"] = target_track
        return {"ok": True, "detected_items": [dummy_item], "returned_items": []}

    monkeypatch.setattr(runtime.LEGACY, "_append_media_clip_infos", fake_append)
    monkeypatch.setattr(runtime.LEGACY, "set_timeline_item_name", lambda item, name: {"ok": True, "name": name})
    monkeypatch.setattr(
        runtime.LEGACY,
        "verify_generated_item_range_with_settle",
        lambda item, start, end, track, timeout_sec, poll_interval_sec: {
            "ok": True, "actual": {"start": start, "end": end, "duration": end - start}
        },
    )

    result = runtime.append_native_index_sequence(
        object(), object(), object(), 25,
        {"Start": "426", "End": "453", "Frames": "28"},
    )
    assert result["ok"] is True
    assert result["source_range_used"] == [426, 454]
    row = captured["rows"][0]
    assert row["source_start"] == 426
    assert row["source_end_frame_api"] == 454
    assert row["record_start"] == 426
    assert row["record_end"] == 454


def _write_pixel_fixture(tmp_path: Path, broken: bool) -> tuple[Path, Path, Path, Path]:
    with_dir = tmp_path / "with"
    without_dir = tmp_path / "without"
    target_dir = tmp_path / "target"
    generated = tmp_path / "generated"
    rgba_dir = generated / "rgba"
    for directory in (with_dir, without_dir, target_dir, rgba_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for frame in range(426, 454):
        without = np.zeros((64, 64, 3), dtype=np.uint8)
        without[:] = (30 + (frame % 20), 70, 110)
        with_come = without.copy()
        with_come[20:36, 18:48] = (5, 5, 5)

        rgba = np.zeros((64, 64, 4), dtype=np.uint8)
        if frame != 426:
            rgba[24:34, 28:40, :3] = without[24:34, 28:40]
            rgba[24:34, 28:40, 3] = 255

        target = with_come.copy()
        if not broken and frame != 426:
            active = rgba[:, :, 3] > 0
            target[active] = without[active]

        cv2.imwrite(str(with_dir / f"with_{frame:08d}.png"), with_come)
        cv2.imwrite(str(without_dir / f"without_{frame:08d}.png"), without)
        cv2.imwrite(str(target_dir / f"target_{frame:08d}.png"), target)
        cv2.imwrite(str(rgba_dir / f"rgba_{frame:06d}.png"), rgba)
    return with_dir, without_dir, target_dir, generated


def test_pixel_gate_passes_same_frame_restore(tmp_path):
    paths = _write_pixel_fixture(tmp_path, broken=False)
    result = pixels.analyze(*paths)
    assert result["ok"] is True
    assert result["sentinel_pass_count"] == len(pixels.SENTINELS)
    assert all(row["ok"] for row in result["rows"])


def test_pixel_gate_rejects_v3_style_noop_clamp(tmp_path):
    paths = _write_pixel_fixture(tmp_path, broken=True)
    result = pixels.analyze(*paths)
    assert result["ok"] is False
    assert result["checks"]["sequence_not_frozen_on_first_frame"] is False
    assert result["sentinel_pass_count"] == 0
    assert any(row["target_equals_with_come_render"] for row in result["rows"] if row["alpha_pixels"] > 0)


def test_runtime_pixel_gate_occurs_before_project_save():
    source = (ROOT / "resolve_workspace/modules/final_occlusion_composition_v4.py").read_text(encoding="utf-8")
    gate_pos = source.index("_run_pre_save_pixel_gate(root, report_dir, command)")
    save_pos = source.index("save = base.save_project(project_manager)", gate_pos)
    assert gate_pos < save_pos


def test_runtime_does_not_call_legacy_relative_zero_append_helper():
    source = (ROOT / "resolve_workspace/modules/final_occlusion_composition_v4.py").read_text(encoding="utf-8")
    assert "_append_rgba_sequence_item(" not in source
    assert "relative_zero_image_sequence_trim" not in source  # command contract belongs in preparer, not runtime behavior


def test_persistent_caption_contract_remains_frozen():
    assert preparer.EXPECTED_TEXTPLUS_COUNT == 114
    assert preparer.TARGET_CAPTION_NAME == "VC_TEXTPLUS_0052_sub_052"
    assert preparer.TARGET_RANGE == [426, 454]
    source = (ROOT / "resolve_workspace/modules/final_occlusion_composition_v4.py").read_text(encoding="utf-8")
    assert '"caption_mutation_count": 0' in source
    assert 'SetClipEnabled", False' in source


def test_v4_reuses_proven_v3_mask_builder_and_changes_only_sequence_application_boundary():
    source = (ROOT / "resolve_workspace/modules/final_occlusion_composition_v4.py").read_text(encoding="utf-8")
    assert "helper = V3._run_helper(root, report_dir, command)" in source
    assert "native_source_range(properties)" in source
    assert "source_range_used" in source
