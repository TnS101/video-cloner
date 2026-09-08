from __future__ import annotations

import importlib.util
import json
from pathlib import Path, PureWindowsPath

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "analysis" / "run_baked_caption_v4_pixel_restore_background_only_v1.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_baked_caption_v4_pixel_restore_background_only_v1.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_architecture_identity_and_closed_families():
    runner = _load(RUNNER_PATH, "bg_runner_identity")
    assert runner.ARCHITECTURE_FAMILY == "accepted_v4_full_foreground_veto_background_only_propainter_v1"
    assert "stabilized_source_backed_person_then_background_v1" in runner.CLOSED_FAMILIES
    assert runner.MIN_RGBA_GLYPH_PERSON_COVERAGE == 0.985


def test_alpha_composite_exact_for_opaque_and_transparent():
    runner = _load(RUNNER_PATH, "bg_runner_alpha")
    base = np.array([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8)
    overlay = np.array([[[100, 110, 120], [130, 140, 150]]], dtype=np.uint8)
    alpha = np.array([[0, 255]], dtype=np.uint8)
    out = runner._alpha_composite(base, overlay, alpha)
    assert np.array_equal(out[0, 0], base[0, 0])
    assert np.array_equal(out[0, 1], overlay[0, 1])


def test_foreground_preserve_includes_entire_person_and_rgba_edge():
    runner = _load(RUNNER_PATH, "bg_runner_foreground")
    person = np.zeros((5, 6), dtype=np.uint8)
    person[1:4, 2:4] = 255
    alpha = np.zeros_like(person)
    alpha[0, 4] = 128
    preserve = runner._build_foreground_preserve(person, alpha)
    assert np.all(preserve[person > 0])
    assert preserve[0, 4]
    assert not preserve[0, 0]


def test_background_alpha_never_expands_inference_mask():
    runner = _load(RUNNER_PATH, "bg_runner_mask")
    inference = np.zeros((40, 60), dtype=np.uint8)
    inference[10:30, 10:50] = 255
    compact = np.zeros_like(inference)
    compact[15:25, 15:45] = 255
    for frame in (450, 451, 452):
        alpha, _ = runner._build_background_alpha(frame, inference, compact)
        assert np.all((alpha > 0) <= (inference > 0))


def _synthetic_result(tmp_path: Path):
    validator = _load(VALIDATOR_PATH, "bg_validator_fixture")
    inputs = []
    metrics = []
    for frame in validator.FRAMES:
        inputs.append(
            {
                "timeline_frame": frame,
                "rgba_glyph_person_coverage": 0.99,
                "background_inference_mask_pixels": 10000,
                "foreground_preserve_pixels": 12000,
                "person_pixels": 11000,
                "inference_person_overlap_pixels": 0,
                "inference_foreground_preserve_overlap_pixels": 0,
            }
        )
        metrics.append(
            {
                "timeline_frame": frame,
                "background_mode": "tail_closed_compact_background_only" if frame >= 451 else "row_filled_background_only",
                "outside_authority_changed_pixels": 0,
                "protected_person_context_changed_pixels": 0,
                "foreground_preserve_changed_pixels": 0,
                "safe_glyph_dark_reduction": 0.80,
                "right_source_dark_removal": 0.80,
            }
        )
    result = {
        "task_id": validator.TASK_ID,
        "ok": True,
        "architecture": {
            "family": validator.EXPECTED_FAMILY,
            "min_rgba_glyph_person_coverage": validator.MIN_RGBA_COVERAGE,
        },
        "input_rows": inputs,
        "composite_rows": metrics,
        "resolve_invocations": 0,
        "save_project_calls": 0,
        "timeline_mutations": 0,
    }
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(result), encoding="utf-8")
    for name in (
        "PROPAINTER_TOOLCHAIN.json",
        "PROPAINTER_BACKGROUND_RUN.log",
        "COME_BEFORE_AFTER_V4_PIXEL_RESTORE_BACKGROUND_ONLY_V1.mp4",
        "BEFORE_AFTER_CONTACT_SHEET.png",
        "MASK_CONTACT_SHEET.png",
    ):
        (tmp_path / name).write_bytes(b"x")
    final_dir = tmp_path / "inpainted_frames"
    final_dir.mkdir()
    for frame in validator.FRAMES:
        (final_dir / f"frame_{frame:06d}.png").write_bytes(b"x")
    return validator


def test_validator_accepts_complete_synthetic_pass(tmp_path: Path):
    validator = _synthetic_result(tmp_path)
    result = validator.validate(tmp_path)
    assert result["technical_pass"] is True
    assert result["status"] == "technical_pass_visual_pending"


def test_validator_rejects_inference_foreground_overlap(tmp_path: Path):
    validator = _synthetic_result(tmp_path)
    payload = json.loads((tmp_path / "PROOF_RUN_RESULT.json").read_text())
    payload["input_rows"][0]["inference_foreground_preserve_overlap_pixels"] = 1
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(payload), encoding="utf-8")
    try:
        validator.validate(tmp_path)
    except validator.ValidationError:
        pass
    else:
        raise AssertionError("validator accepted inference over accepted foreground preserve")


def test_validator_rejects_inference_person_overlap(tmp_path: Path):
    validator = _synthetic_result(tmp_path)
    payload = json.loads((tmp_path / "PROOF_RUN_RESULT.json").read_text())
    payload["input_rows"][0]["inference_person_overlap_pixels"] = 1
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(payload), encoding="utf-8")
    try:
        validator.validate(tmp_path)
    except validator.ValidationError:
        pass
    else:
        raise AssertionError("validator accepted inference over accepted person pixels")


def test_validator_rejects_person_context_mutation(tmp_path: Path):
    validator = _synthetic_result(tmp_path)
    payload = json.loads((tmp_path / "PROOF_RUN_RESULT.json").read_text())
    payload["composite_rows"][0]["protected_person_context_changed_pixels"] = 1
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(payload), encoding="utf-8")
    try:
        validator.validate(tmp_path)
    except validator.ValidationError:
        pass
    else:
        raise AssertionError("validator accepted protected-person mutation")


def test_validator_rejects_foreground_preserve_mutation(tmp_path: Path):
    validator = _synthetic_result(tmp_path)
    payload = json.loads((tmp_path / "PROOF_RUN_RESULT.json").read_text())
    payload["composite_rows"][0]["foreground_preserve_changed_pixels"] = 1
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(payload), encoding="utf-8")
    try:
        validator.validate(tmp_path)
    except validator.ValidationError:
        pass
    else:
        raise AssertionError("validator accepted foreground-preserve mutation")


def test_validator_rejects_rgba_coverage_regression(tmp_path: Path):
    validator = _synthetic_result(tmp_path)
    payload = json.loads((tmp_path / "PROOF_RUN_RESULT.json").read_text())
    payload["input_rows"][0]["rgba_glyph_person_coverage"] = 0.90
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(payload), encoding="utf-8")
    try:
        validator.validate(tmp_path)
    except validator.ValidationError:
        pass
    else:
        raise AssertionError("validator accepted RGBA authority regression")


def test_validator_rejects_legacy_removal_gate_regression(tmp_path: Path):
    validator = _synthetic_result(tmp_path)
    payload = json.loads((tmp_path / "PROOF_RUN_RESULT.json").read_text())
    hold_index = list(validator.FRAMES).index(434)
    payload["composite_rows"][hold_index]["safe_glyph_dark_reduction"] = 0.50
    (tmp_path / "PROOF_RUN_RESULT.json").write_text(json.dumps(payload), encoding="utf-8")
    try:
        validator.validate(tmp_path)
    except validator.ValidationError:
        pass
    else:
        raise AssertionError("validator accepted glyph-removal regression")


def test_json_safe_serializes_windows_path_evidence_without_default_str():
    runner = _load(RUNNER_PATH, "bg_runner_json_safe")
    value = {
        "source": PureWindowsPath(r"C:\\Users\\User\\video.mp4"),
        "nested": [PureWindowsPath(r"C:\\tmp\\frame.png")],
    }
    safe = runner._json_safe(value)
    encoded = json.dumps(safe)
    assert "WindowsPath" not in encoded
    assert safe["source"].endswith("video.mp4")
    assert safe["nested"][0].endswith("frame.png")


def test_json_safe_rejects_unknown_runtime_objects():
    runner = _load(RUNNER_PATH, "bg_runner_json_reject")

    class Unknown:
        pass

    try:
        runner._json_safe(Unknown())
    except runner.ProofError:
        pass
    else:
        raise AssertionError("unknown non-JSON runtime object was silently accepted")


def test_reused_generated_dir_requires_exact_24_frame_sequence(tmp_path: Path):
    runner = _load(RUNNER_PATH, "bg_runner_reuse")
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for index in range(runner.FRAME_COUNT):
        (frame_dir / f"{index:04d}.png").write_bytes(b"x")
    assert runner._validate_reused_generated_dir(frame_dir) == frame_dir.resolve()
    (frame_dir / "0023.png").unlink()
    try:
        runner._validate_reused_generated_dir(frame_dir)
    except runner.ProofError:
        pass
    else:
        raise AssertionError("incomplete reused ProPainter output was accepted")
