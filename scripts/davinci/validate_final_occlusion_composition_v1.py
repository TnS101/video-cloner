#!/usr/bin/env python3
"""Validate the single final occlusion composition runtime result."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V1"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v1"
EXPECTED_TEXTPLUS_COUNT = 114
MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
MATTE_RANGE = [429, 434]


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


def validate(root: Path, run_dir: Path) -> Dict[str, Any]:
    report = load_json(run_dir / "report.json")
    persistent = load_json(run_dir / "persistent_readback.json")
    assets = load_json(run_dir / "approved_rgba_asset_verification.json")
    application = load_json(run_dir / "occlusion_application.json")
    source_contract = load_json(run_dir / "source_contract_verification.json")
    receipt = load_json(run_dir / "publication_receipt.json")

    pchecks = persistent.get("checks") if isinstance(persistent.get("checks"), Mapping) else {}
    app_checks = application.get("checks") if isinstance(application.get("checks"), Mapping) else {}
    occlusion = persistent.get("occlusion") if isinstance(persistent.get("occlusion"), Mapping) else {}
    rows = occlusion.get("rows") if isinstance(occlusion.get("rows"), list) else []

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
        "further_rollout_locked": report.get("further_rollout_authorized") is False and persistent.get("further_rollout_authorized") is False,
        "visual_approval_required": report.get("visual_approval_required") is True and persistent.get("visual_approval_required") is True,
        "asset_hashes": assets.get("ok") is True and assets.get("verified_count") == 6,
        "source_contract": source_contract.get("verified_count", 0) >= 10,
        "publication_single_manual_action": receipt.get("manual_action_count") == 1,
        "application_checks": bool(app_checks) and all(value is True for value in app_checks.values()),
        "persistent_checks": bool(pchecks) and all(value is True for value in pchecks.values()),
        "matte_exact": bool(
            len(rows) == 1
            and rows[0].get("name") == MATTE_NAME
            and [rows[0].get("start"), rows[0].get("end")] == MATTE_RANGE
            and rows[0].get("duration") == 5
            and rows[0].get("media_pool_item_name") == MATTE_NAME
            and int(rows[0].get("track_index") or 0) > int(occlusion.get("max_caption_track") or 0)
        ),
    }
    ok = all(checks.values())
    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": report.get("run_id"),
        "checks": checks,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
        "ok": ok,
    }

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
        f"- Occlusion track: `{report.get('occlusion_target_track')}`",
        "",
        "## Boundary",
        "",
        "- Caption baseline equality: " + ("PASS" if checks["caption_baseline_unchanged"] else "FAIL"),
        "- Persistent readback: " + ("PASS" if checks["persistent_readback"] else "FAIL"),
        "- Idempotency no-op: " + ("PASS" if checks["idempotency"] else "FAIL"),
        "- Source timeline unchanged: " + ("PASS" if checks["source_unchanged"] else "FAIL"),
        "- Approved RGBA hashes: " + ("PASS" if checks["asset_hashes"] else "FAIL"),
        "",
        "## Next gate",
        "",
        "**Human visual approval is required. Further rollout is not authorized by this validator.**",
        "",
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
        if args.run_dir is not None:
            run_dir = args.run_dir.resolve()
        else:
            run_dir = latest_run_dir(root)
        result = validate(root, run_dir)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
