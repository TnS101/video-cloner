#!/usr/bin/env python3
"""Validate V3 sparse pixel-restore occlusion, including independent pixel authority."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

import cv2  # type: ignore
import numpy as np  # type: ignore

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v3"
NEW_MATTE_NAME = "VC_OCCLUSION_PIXEL_RESTORE_matte_span_0001_v3_sub_0052"
EXPECTED_TEXTPLUS_COUNT = 114
TARGET_RANGE = [426, 454]
DURATION = 28
ANCHOR_DIR = "data/DZsqH7auhjt/analysis/foreground_matte_spans/matte_span_0001"
ANCHOR_HASHES = {
    429: "fbea2275e7f1edb16e1e3c2130c587a5948968e1af847d7abb36d41a3cf9a971",
    430: "72f4f8cd0e7ecae13c8d28f3d1e44a77c890a730f591668430e0c613d84287b9",
    431: "b1d5a8e481d2370355d82dc2d8e9ad7bb9bf0b4e5e9e162e97561fafd15f3d03",
    432: "8f07161e5e1d0f597f9268efa851f700452ebd0d89858aa40721f1ef96979883",
    433: "5831a4d86ba3b4bc0fd50908f46a4d8ecadfb9f7d304ecaac2d921ecf53ea74f",
}
SENTINELS = [429, 431, 434, 438, 443, 448, 452, 453]


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict): raise ValueError(f"expected_object:{path}")
    return value


def raw_sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def parse_frame(path: Path) -> int:
    digits = ""
    for char in reversed(path.stem):
        if char.isdigit(): digits = char + digits
        elif digits: break
    if not digits: raise ValueError(f"frame_name:{path.name}")
    return int(digits)


def indexed_pngs(directory: Path) -> Dict[int, Path]:
    rows = {parse_frame(path): path for path in sorted(directory.glob("*.png"))}
    if set(rows) != set(range(*TARGET_RANGE)): raise ValueError(f"render_frames:{directory}:{sorted(rows)}")
    return rows


def recompute_glyph(with_bgr: np.ndarray, without_bgr: np.ndarray) -> np.ndarray:
    delta = cv2.absdiff(with_bgr, without_bgr)
    peak = np.max(delta, axis=2)
    strong = peak >= 8
    weak = peak >= 1
    near = cv2.dilate(strong.astype(np.uint8) * 255, np.ones((5, 5), dtype=np.uint8), iterations=1) > 0
    return (weak & near).astype(np.uint8) * 255


def _read_bgr(path: Path) -> np.ndarray:
    value = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if value is None: raise ValueError(f"read:{path}")
    return value


def _read_gray(path: Path) -> np.ndarray:
    value = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if value is None: raise ValueError(f"read:{path}")
    return value


def validate_person_chain(root: Path, generated: Path, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    frames = manifest.get("frames") if isinstance(manifest.get("frames"), list) else []
    by_frame = {int(row.get("timeline_frame")): row for row in frames if isinstance(row, Mapping)}
    if set(by_frame) != set(range(*TARGET_RANGE)): raise ValueError("manifest_frames")
    masks: Dict[int, np.ndarray] = {}
    rows = []
    for frame in range(*TARGET_RANGE):
        path = generated / "person_masks" / f"person_{frame:06d}.png"
        mask = _read_gray(path); masks[frame] = mask
        row = by_frame[frame]; person = row.get("person") if isinstance(row.get("person"), Mapping) else {}
        if frame in ANCHOR_HASHES:
            canonical = root / ANCHOR_DIR / f"mask_{frame:06d}.png"
            canonical_mask = _read_gray(canonical)
            ok = raw_sha256(canonical) == ANCHOR_HASHES[frame] and np.array_equal(canonical_mask, mask)
            detail = {"mode": "anchor", "matched": ok}
        else:
            from_frame = int(person.get("from_timeline_frame") or -1)
            matrix = np.asarray(person.get("matrix"), dtype=np.float64)
            if matrix.shape != (2, 3) or from_frame not in masks:
                # Backward-generated frames refer to the next frame, which is already an anchor/mask.
                if from_frame not in set(range(*TARGET_RANGE)) or matrix.shape != (2, 3): raise ValueError(f"person_chain:{frame}")
            source_mask = masks.get(from_frame)
            if source_mask is None:
                # For backward chain, load the already-generated higher frame directly.
                source_mask = _read_gray(generated / "person_masks" / f"person_{from_frame:06d}.png")
            expected = cv2.warpAffine(source_mask, matrix, (source_mask.shape[1], source_mask.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            ok = bool(np.array_equal(expected, mask))
            detail = {"mode": str(person.get("mode") or ""), "from_frame": from_frame, "matched": ok}
        rows.append({"frame": frame, **detail})
        if not ok: raise ValueError(f"person_affine_authority:{frame}")
    return {"rows": rows, "ok": True}


def analyze_pixels(root: Path, run_dir: Path) -> Dict[str, Any]:
    generated = run_dir / "generated_pixel_restore_v3"
    manifest = load_json(generated / "manifest.json")
    if (
        manifest.get("task_id") != TASK_ID
        or manifest.get("timeline_range_half_open") != TARGET_RANGE
        or manifest.get("duration_frames") != DURATION
        or manifest.get("rgb_authority") != "resolve_render_with_target_come_disabled"
        or manifest.get("person_authority") != "canonical_humanseg_anchors_plus_global_affine_only"
        or manifest.get("forbidden_mask_growth") != ["grabcut", "dense_optical_flow", "local_segmentation_growth"]
    ):
        raise ValueError("helper_manifest_contract")
    person = validate_person_chain(root, generated, manifest)
    with_rows = indexed_pngs(run_dir / "render_with_come_no_oldmatte")
    without_rows = indexed_pngs(run_dir / "render_without_come_no_oldmatte")
    target_rows = indexed_pngs(run_dir / "render_target_occlusion_v3")
    by_frame = {int(row["timeline_frame"]): row for row in manifest["frames"]}

    rows = []
    sentinel_pass = 0
    for frame in range(*TARGET_RANGE):
        with_bgr = _read_bgr(with_rows[frame]); without_bgr = _read_bgr(without_rows[frame]); target = _read_bgr(target_rows[frame])
        rgba_path = generated / "rgba" / f"rgba_{frame:06d}.png"
        rgba = cv2.imread(str(rgba_path), cv2.IMREAD_UNCHANGED)
        if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4: raise ValueError(f"rgba:{frame}")
        if with_bgr.shape != without_bgr.shape or target.shape != with_bgr.shape or rgba.shape[:2] != with_bgr.shape[:2]: raise ValueError(f"dimensions:{frame}")
        glyph = recompute_glyph(with_bgr, without_bgr)
        stored_glyph = _read_gray(generated / "glyph_masks" / f"glyph_{frame:06d}.png")
        if not np.array_equal(glyph, stored_glyph): raise ValueError(f"glyph_authority:{frame}")
        person_small = _read_gray(generated / "person_masks" / f"person_{frame:06d}.png")
        person_full = cv2.resize(person_small, (1080, 1920), interpolation=cv2.INTER_LINEAR)
        expected_alpha = np.where(glyph > 0, person_full, 0).astype(np.uint8)
        alpha = rgba[:, :, 3]
        if not np.array_equal(alpha, expected_alpha): raise ValueError(f"alpha_authority:{frame}")
        active = alpha > 0
        if np.any(rgba[:, :, :3][~active] != 0): raise ValueError(f"rgba_rgb_outside_alpha:{frame}")
        if np.any(rgba[:, :, :3][active] != without_bgr[active]): raise ValueError(f"rgba_rgb_authority:{frame}")
        if raw_sha256(rgba_path) != by_frame[frame].get("rgba_sha256"): raise ValueError(f"rgba_hash:{frame}")

        diff_target_with = cv2.absdiff(target, with_bgr)
        outside = alpha == 0
        core = alpha >= 250
        outside_peak = np.max(diff_target_with, axis=2)
        outside_changed = int(np.count_nonzero((outside_peak > 2) & outside))
        outside_pixels = int(np.count_nonzero(outside))
        outside_fraction = outside_changed / max(1, outside_pixels)
        outside_mae = float(diff_target_with[outside].mean()) if outside_pixels else 0.0
        core_delta = cv2.absdiff(target, without_bgr)
        core_pixels = int(np.count_nonzero(core))
        core_mae = float(core_delta[core].mean()) if core_pixels else 0.0
        effect = cv2.absdiff(with_bgr, without_bgr)
        intended_effect_pixels = int(np.count_nonzero((np.max(effect, axis=2) > 2) & active))
        row_ok = bool(outside_fraction <= 0.0001 and outside_mae <= 0.50 and (core_pixels == 0 or core_mae <= 3.0))
        if frame in SENTINELS and intended_effect_pixels >= 20 and core_pixels >= 10 and core_mae <= 3.0: sentinel_pass += 1
        rows.append({
            "timeline_frame": frame, "alpha_pixels": int(np.count_nonzero(active)), "core_pixels": core_pixels,
            "intended_effect_pixels": intended_effect_pixels, "outside_changed_pixels": outside_changed,
            "outside_changed_fraction": round(outside_fraction, 9), "outside_mae": round(outside_mae, 6),
            "core_vs_without_mae": round(core_mae, 6), "ok": row_ok,
        })
    total_alpha = sum(row["alpha_pixels"] for row in rows)
    checks = {
        "person_chain_independent": person.get("ok") is True,
        "all_frame_pixel_localization": all(row["ok"] for row in rows),
        "sentinels": sentinel_pass >= 6,
        "sparse_effect_nonempty": total_alpha >= 500,
    }
    result = {"schema_version": 1, "task_id": TASK_ID, "checks": checks, "sentinel_pass_count": sentinel_pass, "sentinel_frames": SENTINELS,
              "alpha_pixels_total": total_alpha, "rows": rows, "person_authority": person, "ok": all(checks.values())}
    (run_dir / "pixel_validation_v3.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def latest_run_dir(root: Path) -> Path:
    parent = root / ".agent" / "reports" / TASK_ID
    rows = sorted(path for path in parent.iterdir() if path.is_dir()) if parent.is_dir() else []
    if not rows: raise ValueError("run_dir_missing")
    return rows[-1]


def validate(root: Path, run_dir: Path) -> Dict[str, Any]:
    report = load_json(run_dir / "report.json")
    persistent = load_json(run_dir / "persistent_readback.json")
    application = load_json(run_dir / "occlusion_v3_application.json")
    render_authority = load_json(run_dir / "render_authority_v3.json")
    helper_invocation = load_json(run_dir / "pixel_restore_helper_invocation.json")
    source_contract = load_json(run_dir / "source_contract_verification.json")
    anchors = load_json(run_dir / "clean_person_anchor_verification.json")
    receipt = load_json(run_dir / "publication_receipt.json")
    final_render = load_json(run_dir / "final_render_v3.json")
    pixel = analyze_pixels(root, run_dir)
    pchecks = persistent.get("checks") if isinstance(persistent.get("checks"), Mapping) else {}
    app_checks = application.get("checks") if isinstance(application.get("checks"), Mapping) else {}
    occ = persistent.get("occlusion") if isinstance(persistent.get("occlusion"), Mapping) else {}
    rows = occ.get("rows") if isinstance(occ.get("rows"), list) else []
    checks = {
        "runtime_ok": report.get("ok") is True,
        "source_exact": report.get("source_timeline_name") == SOURCE_TIMELINE_NAME,
        "target_exact": report.get("target_timeline_name") == TARGET_TIMELINE_NAME,
        "textplus_114": report.get("final_textplus_count") == EXPECTED_TEXTPLUS_COUNT,
        "persistent_caption_mutations_zero": report.get("caption_mutation_count") == 0,
        "temporary_toggle_exactly_one": report.get("temporary_caption_toggle_count") == 1,
        "occlusion_mutation_one": report.get("occlusion_mutation_count") == 1,
        "one_save": report.get("save_call_count") == 1,
        "one_resolve_invocation": report.get("resolve_invocation_contract") == 1,
        "source_unchanged": report.get("source_timeline_unchanged") is True,
        "caption_baseline_unchanged": report.get("caption_baseline_unchanged") is True,
        "persistent": report.get("persistent_readback_ok") is True and persistent.get("ok") is True,
        "idempotency": report.get("idempotency_ok") is True,
        "helper": report.get("pixel_restore_helper_ok") is True and helper_invocation.get("ok") is True,
        "render_authority": render_authority.get("ok") is True and render_authority.get("rgb_authority") == "resolve_render_with_target_come_disabled",
        "final_render": report.get("final_render_evidence_generated") is True and final_render.get("ok") is True,
        "pixel_authority": pixel.get("ok") is True,
        "source_contract": source_contract.get("verified_count", 0) >= 9,
        "anchors": anchors.get("ok") is True and len(anchors.get("rows") or []) == 5,
        "application_checks": bool(app_checks) and all(value is True for value in app_checks.values()),
        "persistent_checks": bool(pchecks) and all(value is True for value in pchecks.values()),
        "matte_exact": bool(not occ.get("old") and not occ.get("v2") and len(rows) == 1 and rows[0].get("name") == NEW_MATTE_NAME and [rows[0].get("start"), rows[0].get("end")] == TARGET_RANGE and int(rows[0].get("track_index") or 0) > int(occ.get("max_caption_track") or 0)),
        "visual_gate_locked": report.get("visual_approval_required") is True and report.get("further_rollout_authorized") is False,
        "single_manual_action": receipt.get("manual_action_count") == 1,
    }
    ok = all(checks.values())
    result = {"schema_version": 1, "task_id": TASK_ID, "run_id": report.get("run_id"), "checks": checks, "pixel_validation": pixel,
              "visual_approval_required": True, "further_rollout_authorized": False, "ok": ok}
    (run_dir / "technical_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# {TASK_ID}", "", "## Technical result", "", f"- Verdict: `{'PASS' if ok else 'FAIL'}`", f"- Run ID: `{report.get('run_id')}`",
        f"- Source: `{SOURCE_TIMELINE_NAME}`", f"- Target: `{TARGET_TIMELINE_NAME}`", f"- Text+: `{report.get('final_textplus_count')}`",
        f"- Persistent caption mutations: `{report.get('caption_mutation_count')}`", f"- Temporary duplicate caption toggles: `{report.get('temporary_caption_toggle_count')}`",
        f"- Occlusion mutations: `{report.get('occlusion_mutation_count')}`", f"- Save calls: `{report.get('save_call_count')}`", "",
        "## Pixel authority", "", "- Person mask: canonical HumanSeg anchors + independently verified global affine only.",
        "- Glyph mask: independently recomputed exact Resolve COME on/off difference.", "- Overlay RGB: exact Resolve render with COME disabled; raw source RGB is forbidden.",
        f"- Sentinel pixel checks: `{pixel.get('sentinel_pass_count')}/{len(SENTINELS)}`", f"- Pixel authority: `{'PASS' if pixel.get('ok') else 'FAIL'}`", "",
        "## Next gate", "", "**Human visual approval is required. Further rollout is not authorized.**", "",
    ]
    (run_dir / "FINAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--root", type=Path, default=Path.cwd()); parser.add_argument("--run-dir", type=Path); parser.add_argument("--latest", action="store_true"); args = parser.parse_args()
    root = args.root.resolve()
    try: run_dir = args.run_dir.resolve() if args.run_dir else latest_run_dir(root); result = validate(root, run_dir)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True)); return 1
    print(json.dumps(result, sort_keys=True)); return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
