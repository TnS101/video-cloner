#!/usr/bin/env python3
"""Validate the temporal occlusion correction, including rendered pixel evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V2"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v2"
EXPECTED_TEXTPLUS_COUNT = 114
NEW_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_temporal_v2_sub_0052"
NEW_MATTE_RANGE = [426, 454]
NEW_MATTE_DURATION = 28
ASSET_DIR = "data/DZsqH7auhjt/analysis/foreground_rgba_assets/matte_span_0001_temporal_v2"
ASSET_MANIFEST = f"{ASSET_DIR}/manifest.json"


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def latest_run_dir(root: Path) -> Path:
    report_root = root / ".agent" / "reports" / TASK_ID
    rows = sorted(path for path in report_root.iterdir() if path.is_dir()) if report_root.is_dir() else []
    if len(rows) != 1:
        raise ValueError(f"run_dir_count:{len(rows)}")
    return rows[0]




def summarize_pixel_diff(source: Any, target: Any, alpha: Any, frame: int, source_name: str = "source.png", target_name: str = "target.png") -> Dict[str, Any]:
    import numpy as np  # type: ignore
    diff = np.abs(target.astype(np.int16) - source.astype(np.int16))
    changed = np.max(diff, axis=2) > 3
    outer = alpha <= 5
    core = alpha >= 245
    outer_pixels = int(outer.sum())
    core_pixels = int(core.sum())
    outside_changed = int(np.logical_and(changed, outer).sum())
    inside_changed = int(np.logical_and(changed, core).sum())
    outside_fraction = float(outside_changed / outer_pixels) if outer_pixels else 0.0
    outside_mae = float(diff[outer].mean()) if outer_pixels else 0.0
    inside_mae = float(diff[core].mean()) if core_pixels else 0.0
    return {
        "timeline_frame": frame,
        "source_render": source_name,
        "target_render": target_name,
        "outer_pixels": outer_pixels,
        "core_pixels": core_pixels,
        "outside_changed_pixels": outside_changed,
        "outside_changed_fraction": round(outside_fraction, 9),
        "outside_mae": round(outside_mae, 6),
        "inside_changed_pixels": inside_changed,
        "inside_mae": round(inside_mae, 6),
    }

def analyze_pixel_evidence(root: Path, run_dir: Path) -> Dict[str, Any]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"opencv_numpy_required:{exc}") from exc

    manifest = load_json(root / ASSET_MANIFEST)
    source_files = sorted((run_dir / "render_source_baseline").glob("*.png"))
    target_files = sorted((run_dir / "render_target_occlusion_v2").glob("*.png"))
    expected_frames = list(range(*NEW_MATTE_RANGE))
    if len(source_files) != NEW_MATTE_DURATION or len(target_files) != NEW_MATTE_DURATION:
        raise ValueError(f"render_file_count:{len(source_files)}:{len(target_files)}")

    rows = []
    for index, frame in enumerate(expected_frames):
        source = cv2.imread(str(source_files[index]), cv2.IMREAD_COLOR)
        target = cv2.imread(str(target_files[index]), cv2.IMREAD_COLOR)
        asset_rgba = cv2.imread(str(root / ASSET_DIR / f"rgba_{frame:06d}.png"), cv2.IMREAD_UNCHANGED)
        if source is None or target is None or asset_rgba is None or asset_rgba.ndim != 3 or asset_rgba.shape[2] != 4:
            raise ValueError(f"pixel_read:{frame}")
        alpha = asset_rgba[:, :, 3]
        if source.shape != target.shape or source.shape[:2] != alpha.shape[:2] or source.shape[:2] != (1920, 1080):
            raise ValueError(f"pixel_dimensions:{frame}:{source.shape}:{target.shape}:{alpha.shape}")
        rows.append(summarize_pixel_diff(source, target, alpha, frame, source_files[index].name, target_files[index].name))

    sentinels = list(((manifest.get("validation_contract") or {}).get("sentinel_frames") or []))
    by_frame = {row["timeline_frame"]: row for row in rows}
    sentinel_rows = [by_frame[frame] for frame in sentinels if frame in by_frame]
    sentinel_changed = [row for row in sentinel_rows if row["inside_changed_pixels"] >= 25 and row["inside_mae"] >= 0.25]
    localization_ok = all(row["outside_changed_fraction"] <= 0.0001 and row["outside_mae"] <= 0.50 for row in rows)
    inside_total = sum(int(row["inside_changed_pixels"]) for row in rows)
    effect_ok = len(sentinel_rows) >= 6 and len(sentinel_changed) >= 5 and inside_total >= 500
    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "frame_range_half_open": NEW_MATTE_RANGE,
        "source_render_count": len(source_files),
        "target_render_count": len(target_files),
        "localization_thresholds": {"outside_changed_fraction_max": 0.0001, "outside_mae_max": 0.50},
        "effect_thresholds": {"sentinel_inside_changed_pixels_min": 25, "sentinel_inside_mae_min": 0.25, "sentinel_pass_min": 5, "inside_changed_total_min": 500},
        "sentinel_frames": sentinels,
        "sentinel_pass_count": len(sentinel_changed),
        "inside_changed_pixels_total": inside_total,
        "localization_ok": localization_ok,
        "effect_ok": effect_ok,
        "rows": rows,
        "ok": bool(localization_ok and effect_ok),
    }
    (run_dir / "pixel_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def validate(root: Path, run_dir: Path) -> Dict[str, Any]:
    report = load_json(run_dir / "report.json")
    persistent = load_json(run_dir / "persistent_readback.json")
    assets = load_json(run_dir / "temporal_rgba_asset_verification.json")
    application = load_json(run_dir / "occlusion_v2_application.json")
    render = load_json(run_dir / "pixel_render_evidence.json")
    source_contract = load_json(run_dir / "source_contract_verification.json")
    source_video = load_json(run_dir / "source_video_verification.json")
    receipt = load_json(run_dir / "publication_receipt.json")
    pixel = analyze_pixel_evidence(root, run_dir)

    pchecks = persistent.get("checks") if isinstance(persistent.get("checks"), Mapping) else {}
    app_checks = application.get("checks") if isinstance(application.get("checks"), Mapping) else {}
    occlusion = persistent.get("occlusion") if isinstance(persistent.get("occlusion"), Mapping) else {}
    rows = occlusion.get("rows") if isinstance(occlusion.get("rows"), list) else []
    old_rows = occlusion.get("old_rows") if isinstance(occlusion.get("old_rows"), list) else []

    checks = {
        "runtime_ok": report.get("ok") is True,
        "source_exact": report.get("source_timeline_name") == SOURCE_TIMELINE_NAME,
        "target_exact": report.get("target_timeline_name") == TARGET_TIMELINE_NAME,
        "textplus_count": report.get("final_textplus_count") == EXPECTED_TEXTPLUS_COUNT,
        "caption_mutations_zero": report.get("caption_mutation_count") == 0,
        "occlusion_mutation_exactly_one": report.get("occlusion_mutation_count") == 1,
        "one_save": report.get("save_call_count") == 1,
        "one_resolve_invocation_contract": report.get("resolve_invocation_contract") == 1,
        "source_unchanged": report.get("source_timeline_unchanged") is True,
        "caption_baseline_unchanged": report.get("caption_baseline_unchanged") is True,
        "persistent_readback": report.get("persistent_readback_ok") is True and persistent.get("ok") is True,
        "idempotency": report.get("idempotency_ok") is True,
        "pixel_render_generated": report.get("pixel_render_evidence_generated") is True and render.get("ok") is True,
        "pixel_render_validated": pixel.get("ok") is True,
        "further_rollout_locked": report.get("further_rollout_authorized") is False and persistent.get("further_rollout_authorized") is False,
        "visual_approval_required": report.get("visual_approval_required") is True and persistent.get("visual_approval_required") is True,
        "asset_hashes": assets.get("ok") is True and assets.get("verified_count") == 29,
        "source_contract": source_contract.get("verified_count", 0) >= 14,
        "source_video_hash": source_video.get("ok") is True,
        "publication_single_manual_action": receipt.get("manual_action_count") == 1,
        "application_checks": bool(app_checks) and all(value is True for value in app_checks.values()),
        "persistent_checks": bool(pchecks) and all(value is True for value in pchecks.values()),
        "matte_exact": bool(
            not old_rows
            and len(rows) == 1
            and rows[0].get("name") == NEW_MATTE_NAME
            and [rows[0].get("start"), rows[0].get("end")] == NEW_MATTE_RANGE
            and rows[0].get("duration") == NEW_MATTE_DURATION
            and rows[0].get("media_pool_item_name") == NEW_MATTE_NAME
            and int(rows[0].get("track_index") or 0) > int(occlusion.get("max_caption_track") or 0)
        ),
    }
    ok = all(checks.values())
    result = {"schema_version":1,"task_id":TASK_ID,"run_id":report.get("run_id"),"checks":checks,"pixel_validation":pixel,
              "visual_approval_required":True,"further_rollout_authorized":False,"ok":ok}

    lines = [
        f"# {TASK_ID}", "", "## Technical result", "", f"- Verdict: `{'PASS' if ok else 'FAIL'}`", f"- Run ID: `{report.get('run_id')}`",
        f"- Source: `{SOURCE_TIMELINE_NAME}`", f"- Target: `{TARGET_TIMELINE_NAME}`", f"- Text+: `{report.get('final_textplus_count')}`",
        f"- Caption mutations: `{report.get('caption_mutation_count')}`", f"- Occlusion mutations: `{report.get('occlusion_mutation_count')}`",
        f"- Save calls: `{report.get('save_call_count')}`", f"- Occlusion track: `{report.get('occlusion_target_track')}`", "",
        "## Pixel evidence", "", f"- Rendered source frames: `{pixel.get('source_render_count')}`", f"- Rendered target frames: `{pixel.get('target_render_count')}`",
        f"- Difference localization outside alpha: `{'PASS' if pixel.get('localization_ok') else 'FAIL'}`",
        f"- Occlusion effect sentinels: `{pixel.get('sentinel_pass_count')}/{len(pixel.get('sentinel_frames') or [])}`", f"- Pixel evidence: `{'PASS' if pixel.get('ok') else 'FAIL'}`", "",
        "## Boundary", "", "- Caption baseline equality: " + ("PASS" if checks["caption_baseline_unchanged"] else "FAIL"),
        "- Persistent readback: " + ("PASS" if checks["persistent_readback"] else "FAIL"), "- Idempotency no-op: " + ("PASS" if checks["idempotency"] else "FAIL"),
        "- Source timeline unchanged: " + ("PASS" if checks["source_unchanged"] else "FAIL"), "", "## Next gate", "",
        "**Human visual approval is still required. Further rollout is not authorized.**", "",
    ]
    (run_dir / "FINAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    (run_dir / "technical_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        run_dir = args.run_dir.resolve() if args.run_dir is not None else latest_run_dir(root)
        result = validate(root, run_dir)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok":False,"error":f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
