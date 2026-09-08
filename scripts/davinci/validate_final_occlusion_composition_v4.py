#!/usr/bin/env python3
"""Validate native-indexed final occlusion V4 after the single Resolve run."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v4"
NEW_MATTE_NAME = "VC_OCCLUSION_PIXEL_RESTORE_matte_span_0001_v4_sub_0052"
EXPECTED_TEXTPLUS_COUNT = 114
TARGET_RANGE = [426, 454]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def latest_run_dir(root: Path) -> Path:
    parent = root / ".agent" / "reports" / TASK_ID
    rows = sorted(path for path in parent.iterdir() if path.is_dir()) if parent.is_dir() else []
    if not rows:
        raise ValueError("run_dir_missing")
    return rows[-1]


def validate(root: Path, run_dir: Path) -> Dict[str, Any]:
    pixel_mod = _load(
        "vc_occlusion_v4_pixel_validator",
        root / "scripts" / "analysis" / "validate_final_occlusion_pixel_restore_v4.py",
    )
    report = load_json(run_dir / "report.json")
    persistent = load_json(run_dir / "persistent_readback.json")
    application = load_json(run_dir / "occlusion_v4_application.json")
    render_authority = load_json(run_dir / "render_authority_v4.json")
    source_contract = load_json(run_dir / "source_contract_verification.json")
    anchors = load_json(run_dir / "clean_person_anchor_verification.json")
    receipt = load_json(run_dir / "publication_receipt.json")
    final_render = load_json(run_dir / "final_render_v4.json")
    pre_save = load_json(run_dir / "pre_save_pixel_validation_v4.json")

    recomputed = pixel_mod.analyze(
        run_dir / "render_with_come_no_oldmatte",
        run_dir / "render_without_come_no_oldmatte",
        run_dir / "render_target_occlusion_v4",
        run_dir / "generated_pixel_restore_v3",
    )
    (run_dir / "pixel_validation_v4.json").write_text(
        json.dumps(recomputed, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    pchecks = persistent.get("checks") if isinstance(persistent.get("checks"), Mapping) else {}
    app_checks = application.get("checks") if isinstance(application.get("checks"), Mapping) else {}
    occ = persistent.get("occlusion") if isinstance(persistent.get("occlusion"), Mapping) else {}
    rows = occ.get("rows") if isinstance(occ.get("rows"), list) else []
    first = application.get("first_application") if isinstance(application.get("first_application"), Mapping) else {}
    append = first.get("append") if isinstance(first.get("append"), Mapping) else {}
    imported = first.get("import") if isinstance(first.get("import"), Mapping) else {}
    properties = imported.get("properties") if isinstance(imported.get("properties"), Mapping) else {}

    native_source_range = first.get("native_source_range")
    append_source_range = append.get("source_range_used")
    media_native_range = [
        int(properties.get("Start") or -1),
        int(properties.get("End") or -1) + 1,
    ]

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
        "render_authority": render_authority.get("ok") is True and render_authority.get("rgb_authority") == "resolve_render_with_target_come_disabled",
        "final_render": report.get("final_render_evidence_generated") is True and final_render.get("ok") is True,
        "pre_save_pixel_authority": report.get("pre_save_pixel_authority_ok") is True and pre_save.get("ok") is True,
        "post_runtime_pixel_authority": recomputed.get("ok") is True,
        "source_contract": source_contract.get("verified_count", 0) >= 13,
        "anchors": anchors.get("ok") is True and len(anchors.get("rows") or []) == 5,
        "application_checks": bool(app_checks) and all(value is True for value in app_checks.values()),
        "persistent_checks": bool(pchecks) and all(value is True for value in pchecks.values()),
        "native_media_range": media_native_range == TARGET_RANGE,
        "native_source_range_used": native_source_range == TARGET_RANGE and append_source_range == TARGET_RANGE,
        "relative_zero_trim_not_used": append_source_range != [0, 28],
        "matte_exact": bool(
            not occ.get("old")
            and not occ.get("v2")
            and not occ.get("v3")
            and len(rows) == 1
            and rows[0].get("name") == NEW_MATTE_NAME
            and [rows[0].get("start"), rows[0].get("end")] == TARGET_RANGE
            and int(rows[0].get("track_index") or 0) > int(occ.get("max_caption_track") or 0)
        ),
        "visual_gate_locked": report.get("visual_approval_required") is True and report.get("further_rollout_authorized") is False,
        "single_manual_action": receipt.get("manual_action_count") == 1,
    }
    ok = all(checks.values())
    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": report.get("run_id"),
        "checks": checks,
        "native_source_range": append_source_range,
        "pixel_validation": recomputed,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
        "ok": ok,
    }
    (run_dir / "technical_validation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# {TASK_ID}",
        "",
        "## Technical result",
        "",
        f"- Verdict: `{'PASS' if ok else 'FAIL'}`",
        f"- Run ID: `{report.get('run_id')}`",
        f"- Source: `{SOURCE_TIMELINE_NAME}`",
        f"- Target: `{TARGET_TIMELINE_NAME}`",
        f"- Text+: `{report.get('final_textplus_count')}`",
        f"- Caption mutations: `{report.get('caption_mutation_count')}`",
        f"- Occlusion mutations: `{report.get('occlusion_mutation_count')}`",
        f"- Save calls: `{report.get('save_call_count')}`",
        "",
        "## Native sequence correction",
        "",
        f"- Media native range: `{media_native_range}`",
        f"- Append source range: `{append_source_range}`",
        "- Rejected V3 trim: `[0, 28]`",
        "",
        "## Pixel authority",
        "",
        f"- Pre-save gate: `{'PASS' if pre_save.get('ok') else 'FAIL'}`",
        f"- Post-runtime recomputation: `{'PASS' if recomputed.get('ok') else 'FAIL'}`",
        f"- Sentinels: `{recomputed.get('sentinel_pass_count')}/{len(recomputed.get('sentinel_frames') or [])}`",
        "",
        "## Next gate",
        "",
        "**Human visual approval is required. Further rollout is not authorized.**",
        "",
    ]
    (run_dir / "FINAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        run_dir = args.run_dir.resolve() if args.run_dir else latest_run_dir(root)
        result = validate(root, run_dir)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
