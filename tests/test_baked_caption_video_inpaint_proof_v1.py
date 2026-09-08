from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_module(rel: str, name: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provisioner_is_pinned_and_isolated():
    mod = load_module("scripts/analysis/provision_propainter_proof_v1.py", "proof_provision")
    assert mod.TASK_ID == "DZSQH7AUHJT_BAKED_CAPTION_VIDEO_INPAINT_PROOF_V9"
    assert mod.PROPAINTER_REPOSITORY == "https://github.com/sczhou/ProPainter.git"
    assert mod.PROPAINTER_COMMIT == "e870e79321c31b733e2031af5aa2fb1fe3ac7eec"
    assert mod.TORCH_VERSION == "2.8.0"
    assert mod.TORCHVISION_VERSION == "0.23.0"
    assert mod.TORCH_INDEX_URL.endswith("/cu128")
    assert "LOCALAPPDATA" in mod.default_external_root.__code__.co_names or "LOCALAPPDATA" in mod.default_external_root.__code__.co_consts


def test_style_authority_requires_exact_come_anchors():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_run")
    payload = {
        "style_events": [
            {
                "event_id": "style_event_sub_0052",
                "observed_text": "COME",
                "observations": [
                    {"timestamp": 17.879, "bbox": [264, 661, 687, 775]},
                    {"timestamp": 18.56, "bbox": [334, 660, 746, 764]},
                    {"timestamp": 18.67, "bbox": [339, 662, 758, 768]},
                ],
            }
        ]
    }
    assert mod.verify_style_anchors(payload) == mod.EXPECTED_STYLE_ANCHORS


def test_interpolated_bboxes_are_bounded_and_move_right():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_interp")
    anchors = {k: v[:] for k, v in mod.EXPECTED_STYLE_ANCHORS.items()}
    boxes = [mod.interpolate_bbox(frame, anchors) for frame in range(429, 453)]
    assert boxes[0] == (264, 661, 687, 775)
    assert boxes[16] == (334, 660, 746, 764)  # frame 445
    assert boxes[19] == (339, 662, 758, 768)  # frame 448
    assert boxes[-1][0] > boxes[19][0]
    for x1, y1, x2, y2 in boxes:
        assert 0 <= x1 < x2 <= 1080
        assert 0 <= y1 < y2 <= 1920
        assert (x2 - x1) < 500
        assert (y2 - y1) < 140


def test_transform_scales_glyph_to_source_bbox_without_frame_escape():
    import cv2

    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_mask")
    mask = np.zeros((1920, 1080), dtype=np.uint8)
    cv2.rectangle(mask, (380, 680), (650, 755), 255, -1)
    target = (264, 661, 687, 775)
    transformed = mod.transform_glyph_mask(mask, target)
    ys, xs = np.where(transformed > 0)
    assert xs.size > 15000
    assert xs.min() >= target[0] - 20
    assert xs.max() <= target[2] + 20
    assert ys.min() >= target[1] - 20
    assert ys.max() <= target[3] + 20


def test_filled_component_hulls_remove_letter_holes_without_solid_bbox():
    import cv2

    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_component_hulls")
    mask = np.zeros((120, 240), dtype=np.uint8)
    cv2.circle(mask, (60, 60), 28, 255, 8)
    cv2.circle(mask, (130, 60), 26, 255, 8)
    filled, count = mod.fill_component_hulls(mask)

    assert count == 2
    assert filled[60, 60] == 255
    assert filled[60, 130] == 255
    assert np.count_nonzero(filled) < mask.size


def test_compact_caption_mask_keeps_final_authority_smaller_than_legacy_solid_reference():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_compact_mask")
    image = np.full((220, 420, 3), 225, dtype=np.uint8)
    glyph = np.zeros((220, 420), dtype=np.uint8)
    # Four separated glyph-like components with holes.
    glyph[80:120, 80:110] = 255
    glyph[80:120, 130:160] = 255
    glyph[80:120, 180:215] = 255
    glyph[80:120, 235:265] = 255
    target = (70, 70, 280, 135)
    compact = mod.build_compact_caption_masks(image, glyph, target)

    composite = compact["composite_mask"]
    inpaint = compact["inpaint_mask"]
    assert np.count_nonzero(composite) >= 8000
    assert np.all((composite == 0) | (inpaint > 0))
    assert 0.0 <= compact["compact_vs_legacy_solid_ratio"] <= mod.MAX_COMPACT_VS_LEGACY_SOLID_RATIO
    assert 0 <= compact["dynamic_right_guard_pixels"] <= mod.MAX_COMPOSITE_RIGHT_GLYPH_GUARD_PIXELS


def test_row_filled_inference_breaks_letter_topology_over_compact_source_authority():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_row_fill")
    composite = np.zeros((80, 180), dtype=np.uint8)
    composite[20:55, 20:45] = 255
    composite[20:55, 65:90] = 255
    composite[20:55, 110:140] = 255
    original = composite.copy()

    seed, added, rows = mod.build_row_filled_inference_seed(composite)

    assert np.array_equal(composite, original)
    assert np.all((composite == 0) | (seed > 0))
    assert seed[35, 55] == 255
    assert seed[35, 100] == 255
    assert added > 0
    assert rows == 35


def test_source_dark_right_extension_tracks_late_tail_without_solid_rectangle():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_right_extension")
    source = (100, 70, 280, 140)
    image = np.full((220, 520, 3), 225, dtype=np.uint8)
    image[92:106, 350:390] = 120
    extension = mod.build_source_dark_right_extension_mask(image, source)

    ys, xs = np.where(extension > 0)
    assert xs.size > 0
    assert xs.max() >= 389
    # It is a bounded component mask, not a full source-bbox-height rectangle.
    assert np.count_nonzero(extension) < (390 - source[2] + 20) * (source[3] - source[1])


def test_compact_right_extension_is_hard_bounded():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_right_bound")
    source = (100, 70, 280, 140)
    image = np.full((220, 520, 3), 225, dtype=np.uint8)
    image[85:115, 450:470] = 120
    glyph = np.zeros((220, 520), dtype=np.uint8)
    glyph[80:125, 120:260] = 255
    compact = mod.build_compact_caption_masks(image, glyph, source)
    assert 0 <= compact["dynamic_right_guard_pixels"] <= mod.MAX_COMPOSITE_RIGHT_GLYPH_GUARD_PIXELS


def test_right_glyph_probe_population_is_required_only_for_hold_sentinels():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_probe_scope")

    # Transition/contact-sheet sentinels may legitimately have sparse dark glyph pixels.
    mod.require_right_glyph_probe_population(429, 1)
    mod.require_right_glyph_probe_population(431, 0)
    mod.require_right_glyph_probe_population(452, 20)

    for frame in mod.HOLD_SENTINELS:
        mod.require_right_glyph_probe_population(frame, mod.RIGHT_GLYPH_MIN_SOURCE_DARK_PIXELS)
        try:
            mod.require_right_glyph_probe_population(frame, mod.RIGHT_GLYPH_MIN_SOURCE_DARK_PIXELS - 1)
        except mod.ProofError:
            pass
        else:
            raise AssertionError(f"hold sentinel {frame} accepted an undersized right-glyph probe")


def test_contact_sheet_uses_defined_composite_mask_authority():
    text = (ROOT / "scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    assert "mask = composite_masks[frame] > 0" in text
    assert "mask = full_masks[frame] > 0" not in text


def test_v9_semantic_split_moves_person_protection_to_inference_boundary():
    text = (ROOT / "scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    assert 'row_filled_mask = compact["inpaint_mask"]' in text
    assert "load_v4_foreground_authority" in text
    assert "load_full_resolution_person_mask" in text
    assert "build_semantic_split_inference_mask" in text
    assert "build_semantic_split_composite_alpha" in text
    assert 'person_inference_mode": "veto_except_source_glyph_repair"' in text
    assert "generated.astype(np.float32) * composite_alpha[..., None]" in text
    assert "final[composite_mask] = generated[composite_mask]" not in text


def test_v9_semantic_split_masks_only_source_glyph_overlap_inside_person():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_v9_split")
    row_filled = np.zeros((600, 1000), dtype=np.uint8)
    row_filled[180:330, 120:880] = 255
    score = np.zeros_like(row_filled)
    score[220:250, 240:300] = 255
    score[220:250, 390:450] = 255
    score[220:250, 540:600] = 255
    compact = score.copy()
    compact[210:260, 680:760] = 255
    person = np.zeros_like(row_filled)
    person[30:580, 160:920] = 255

    inference = mod.build_semantic_split_inference_mask(443, row_filled, score, person)
    inpaint = inference["inpaint_mask"]
    repair = inference["person_repair_mask"]
    person_bool = person > 0
    seed = (score > 0) & person_bool

    assert np.all(inpaint[person_bool & (repair == 0)] == 0)
    assert np.all(inpaint[seed] == 255)
    assert inference["person_glyph_seed_pixels"] >= mod.MIN_PERSON_GLYPH_SEED_PIXELS
    assert 0.0 < inference["person_repair_inference_ratio"] <= mod.MAX_PERSON_REPAIR_AUTHORITY_RATIO
    assert inference["pre_split_row_filled_mask_pixels"] > np.count_nonzero(inpaint)

    composite = mod.build_semantic_split_composite_alpha(
        443,
        inpaint,
        compact,
        person,
        inference["person_glyph_seed"],
        repair,
    )
    alpha = composite["alpha"]
    assert np.all(alpha[seed] == 255)
    assert np.all(alpha[person_bool & (repair == 0)] == 0)
    assert composite["background_mode"] == "row_filled_background_plus_person_glyph_repair"

    tail = mod.build_semantic_split_composite_alpha(
        452,
        inpaint,
        compact,
        person,
        inference["person_glyph_seed"],
        repair,
    )
    assert tail["background_mode"] == "tail_closed_background_plus_person_glyph_repair"
    assert np.all(tail["alpha"][seed] == 255)


def test_score_mask_is_clipped_to_source_bbox():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_score_clip")
    source = np.zeros((100, 120), dtype=np.uint8)
    source[20:80, 10:110] = 255
    target = (30, 25, 90, 75)
    clipped = mod.clip_mask_to_bbox(source, target)

    ys, xs = np.where(clipped > 0)
    assert xs.min() == target[0]
    assert xs.max() == target[2] - 1
    assert ys.min() == target[1]
    assert ys.max() == target[3] - 1


def test_proof_scope_is_offline_and_come_only():
    run_text = (ROOT / "scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    validate_text = (ROOT / "scripts/analysis/validate_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    combined = run_text + "\n" + validate_text
    assert "SOURCE_FRAME_START = 429" in run_text
    assert "SOURCE_FRAME_END = 452" in run_text
    assert "style_event_sub_0052" in run_text
    assert 'INPAINT_MASK_STRATEGY = "row_filled_background_plus_source_glyph_person_repair_v1"' in run_text
    assert 'COMPOSITE_MASK_STRATEGY = "semantic_split_person_repair_tail_feather_v1"' in run_text
    assert "COMPACT_HULL_MIN_COMPONENT_AREA = 50" in run_text
    assert "COMPACT_INFERENCE_DILATION = 6" in run_text
    assert "MAX_COMPOSITE_RIGHT_GLYPH_GUARD_PIXELS = 180" in run_text
    assert "RIGHT_GLYPH_PROBE_INSIDE_PIXELS = 80" in run_text
    assert "FOREGROUND_PERSON_AUTHORITY_STRATEGY" in run_text
    assert "PERSON_REPAIR_DILATION_PIXELS = 3" in run_text
    assert "TAIL_BACKGROUND_START_FRAME = 451" in run_text
    assert 'parser.add_argument("--foreground-authority-dir", required=True)' in run_text
    assert "safe_glyph_dark_ratio_lt140_before" in run_text
    assert "safe_sky_dark_ratio_lt140_before" not in run_text
    assert "DaVinciResolveScript" not in combined
    assert "SaveProject" not in combined
    assert "VC_Run_Agent_Task" not in combined
    assert "visual_approval_required" in combined


def test_validator_requires_source_glyph_residual_reduction_not_old_broad_sky_metric():
    text = (ROOT / "scripts/analysis/validate_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    assert "hold_sentinel_source_glyph_reduction" in text
    assert "safe_glyph_dark_ratio_lt140_before" in text
    assert "after <= 0.20" in text
    assert "relative >= 0.70" in text
    assert "safe_sky_dark_ratio_lt140_before" not in text
    assert "hold_sentinel_right_glyph_guard_removal" in text
    assert "right_source_dark_survival_lt140" in text
    assert "survival <= 0.25" in text
    assert "removal >= 0.75" in text
    assert "compact_source_mask_area_and_coverage" in text
    assert "MAX_COMPACT_VS_LEGACY_SOLID_RATIO = 0.90" in text
    assert "MIN_SCORE_MASK_COVERAGE = 0.84" in text
    assert "post_inpaint_sky_artifact_gate" not in text


def test_provisioner_uses_commit_qualified_fresh_source_path(tmp_path):
    mod = load_module("scripts/analysis/provision_propainter_proof_v1.py", "proof_source_path")
    source = mod.propainter_source_path(tmp_path)

    assert source.parent == tmp_path
    assert mod.PROPAINTER_COMMIT[:12] in source.name
    assert source.name.startswith("ProPainter_checkout_")
    assert source.name != "ProPainter"


def test_provisioner_normal_clone_materializes_worktree_without_no_checkout(tmp_path, monkeypatch):
    from types import SimpleNamespace

    mod = load_module("scripts/analysis/provision_propainter_proof_v1.py", "proof_normal_clone")
    source = tmp_path / "ProPainter_checkout_test"
    calls = []

    monkeypatch.setattr(mod.shutil, "which", lambda name: "git.exe" if name == "git" else None)

    def fake_run(args, *, cwd=None, check=True, capture=True):
        calls.append(list(args))
        if args[:2] == ["git", "clone"]:
            (source / ".git").mkdir(parents=True)
            (source / "requirements.txt").write_text("numpy\n", encoding="utf-8")
            (source / "inference_propainter.py").write_text("# proof\n", encoding="utf-8")
            for directory in ("core", "model", "utils"):
                (source / directory).mkdir(exist_ok=True)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(mod, "run", fake_run)
    monkeypatch.setattr(mod, "current_propainter_commit", lambda path: mod.PROPAINTER_COMMIT)

    mod.ensure_propainter_source(source)

    clone = next(call for call in calls if call[:2] == ["git", "clone"])
    assert "--no-checkout" not in clone
    assert "--filter=blob:none" in clone
    assert "--no-tags" in clone
    assert mod.missing_propainter_paths(source) == []


def test_provisioner_rejects_incomplete_fresh_checkout(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pytest

    mod = load_module("scripts/analysis/provision_propainter_proof_v1.py", "proof_incomplete_fresh")
    source = tmp_path / "ProPainter_checkout_test"

    monkeypatch.setattr(mod.shutil, "which", lambda name: "git.exe" if name == "git" else None)

    def fake_run(args, *, cwd=None, check=True, capture=True):
        if args[:2] == ["git", "clone"]:
            (source / ".git").mkdir(parents=True)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(mod, "run", fake_run)
    monkeypatch.setattr(mod, "current_propainter_commit", lambda path: mod.PROPAINTER_COMMIT)

    with pytest.raises(mod.ProvisionError, match="fresh ProPainter checkout is incomplete"):
        mod.ensure_propainter_source(source)


def test_source_authority_retains_come_native_range_but_rejects_external_context(tmp_path, monkeypatch):
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_source_authority")
    source_dir = tmp_path / "input"
    source_dir.mkdir()
    source_video = source_dir / "DZsqH7auhjt.mp4"
    source_video.write_bytes(b"authority-placeholder")
    monkeypatch.setattr(mod, "sha256_file", lambda path: mod.EXPECTED_SOURCE_VIDEO_SHA256)

    track_payload = {
        "source_video_sha256": mod.EXPECTED_SOURCE_VIDEO_SHA256,
        "source_video_info": {
            "fps": 30.0,
            "frame_count": 1206,
            "width": 1080,
            "height": 1920,
            "is_proxy": False,
        },
    }
    lifecycle_payload = {
        "layers": [
            {
                "cue_id": "sub_052",
                "text": "COME",
                "targeted_redetection": {
                    "tracking": {
                        "first_visible_source_frame": 537,
                        "last_visible_source_frame": 564,
                    }
                },
            }
        ]
    }

    authority = mod.verify_source_context_authority(track_payload, lifecycle_payload, tmp_path)
    assert authority["source_video"] == source_video
    assert authority["first_visible_source_frame"] == 537
    assert authority["last_visible_source_frame"] == 564
    assert authority["pre_context_source_frames"] == []
    assert authority["post_context_source_frames"] == []


def test_target_only_inference_has_no_poisoned_context_frames():
    mod = load_module("scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py", "proof_target_only")
    assert mod.CONTEXT_SOURCE_FRAME_COUNT == 0
    assert mod.FRAME_COUNT == 24
    assert mod.INFERENCE_FRAME_COUNT == 24
    assert mod.TEMPORAL_CONTEXT_STRATEGY == "target_only_no_clean_same_shot_context_v1"
    assert mod.EXPECTED_COME_SOURCE_VISIBLE_RANGE == (537, 564)


def test_v9_foreground_authority_is_hash_verified_and_person_repair_is_bounded():
    text = (ROOT / "scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    assert 'manifest.get("person_authority") != "canonical_humanseg_anchors_plus_global_affine_only"' in text
    assert 'actual_hash = sha256_file(path)' in text
    assert 'if actual_hash != expected_hash:' in text
    assert 'MAX_PERSON_REPAIR_AUTHORITY_RATIO = 0.05' in text
    assert 'MIN_PERSON_GLYPH_SEED_PIXELS = 4000' in text
    assert 'V9 protected person context changed outside source-glyph repair' in text


def test_dynamic_right_guard_and_compact_source_are_serialized_into_frame_metrics():
    text = (ROOT / "scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    assert '"dynamic_right_guard_pixels": frame_rows[target_index]["dynamic_right_guard_pixels"]' in text
    assert '"compact_source_mask_pixels": frame_rows[target_index]["compact_source_mask_pixels"]' in text
    assert 'generated_index = target_index' in text
    assert 'COME_BEFORE_AFTER_PROOF_V9.mp4' in text
    assert 'TEMPORAL_CONTEXT_CONTACT_SHEET.png' not in text


def test_validator_requires_v9_semantic_split_person_protection_contract():
    text = (ROOT / "scripts/analysis/validate_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    assert 'input_frame_rows = result.get("input_frames")' in text
    assert 'row = input_by_frame[frame]' in text
    assert 'compact_source_pixels = int(row.get("compact_source_mask_pixels", 0))' in text
    assert "target_only_no_clean_same_shot_context_v1" in text
    assert "target_only_inference_sequence" in text
    assert "semantic_split_inference_contract" in text
    assert "row_filled_background_bridge" in text
    assert "semantic_split_person_protection" in text
    assert "person_glyph_repair_sentinels" in text
    assert "protected_person_context_exact" in text
    assert "foreground_background_modes" in text
    assert "compact_source_mask_area_and_coverage" in text
    assert "dynamic_right_guard_bounds" in text
    assert "COME_BEFORE_AFTER_PROOF_V9.mp4" in text
    assert "TEMPORAL_CONTEXT_CONTACT_SHEET.png" not in text
    assert "post_inpaint_sky_artifact_gate" not in text


def test_v9_visual_failure_hard_stops_same_family_mask_tuning():
    run_text = (ROOT / "scripts/analysis/run_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    validate_text = (ROOT / "scripts/analysis/validate_baked_caption_video_inpaint_proof_v1.py").read_text(encoding="utf-8")
    assert '"architecture_family": "propainter_semantic_split_person_repair_v1"' in run_text
    assert '"same_family_visual_retry_allowed": False' in run_text
    assert '"technical_integration_fix_allowed": True' in run_text
    assert 'stop_architecture_family_no_v10_mask_dilation_feather_threshold_retry' in run_text
    assert "If V9 is technical PASS but human visual FAIL" in validate_text
    assert "Do not produce V10 by changing mask dilation, feather, threshold, or topology" in validate_text
