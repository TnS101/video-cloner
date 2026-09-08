#!/usr/bin/env python3
"""Validate Step 3B.3 outline/shadow cloning V1 after the single Resolve run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3B3_OUTLINE_SHADOW_CLONING_V1"
PREVIOUS_FAILED_RUN_ID = "20260813T103450539914Z_22ea243b7f3b487db2c75d3f8fe91c0d"
SOURCE = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4"
TARGET = SOURCE + "_outline_shadow_v1"
TARGET_CAPTION = "VC_TEXTPLUS_0052_sub_052"


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def find_run(root: Path, run_id: str | None) -> Path:
    task_root = root / ".agent" / "reports" / TASK_ID
    if not task_root.is_dir():
        raise ValueError("task_report_root_missing")
    if run_id:
        run = task_root / run_id
        if not run.is_dir():
            raise ValueError(f"run_missing:{run_id}")
        return run
    rows = sorted(path for path in task_root.iterdir() if path.is_dir() and path.name != PREVIOUS_FAILED_RUN_ID)
    if len(rows) != 1:
        raise ValueError(f"expected_one_repair_run:{len(rows)}")
    return rows[0]


def all_true(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value) and all(item is True for item in value.values())


def validate(root: Path, run: Path) -> Dict[str, Any]:
    required = [
        "publication_receipt.json",
        "outline_shadow_command.json",
        "source_contract_verification.json",
        "outline_shadow_preflight.json",
        "outline_shadow_application.json",
        "persistent_readback.json",
        "report.json",
        "status.json",
    ]
    missing = [name for name in required if not (run / name).is_file()]
    if missing:
        raise ValueError(f"missing_artifacts:{missing}")

    receipt = load_json(run / "publication_receipt.json")
    command = load_json(run / "outline_shadow_command.json")
    contract = load_json(run / "source_contract_verification.json")
    preflight = load_json(run / "outline_shadow_preflight.json")
    application = load_json(run / "outline_shadow_application.json")
    persistent = load_json(run / "persistent_readback.json")
    report = load_json(run / "report.json")
    status = load_json(run / "status.json")
    run_id = run.name

    source_audit = preflight.get("source_effect_audit") if isinstance(preflight.get("source_effect_audit"), Mapping) else {}
    source_mismatches = source_audit.get("mismatches") if isinstance(source_audit.get("mismatches"), list) else []
    mismatch_shape = sorted(
        (str(row.get("name") or ""), str(row.get("field") or ""), row.get("expected"), row.get("actual"))
        for row in source_mismatches if isinstance(row, Mapping)
    )
    expected_shape = sorted([
        (TARGET_CAPTION, "Enabled2", 1.0, 0.0),
        (TARGET_CAPTION, "Enabled3", 1.0, 0.0),
    ])
    first = application.get("first_application") if isinstance(application.get("first_application"), Mapping) else {}
    second = application.get("second_application") if isinstance(application.get("second_application"), Mapping) else {}
    post_audit = application.get("post_effect_audit") if isinstance(application.get("post_effect_audit"), Mapping) else {}
    first_contract = first.get("target_effect_contract") if isinstance(first.get("target_effect_contract"), Mapping) else {}
    second_contract = second.get("target_effect_contract") if isinstance(second.get("target_effect_contract"), Mapping) else {}
    persistent_contract = persistent.get("target_effect_contract") if isinstance(persistent.get("target_effect_contract"), Mapping) else {}
    pchecks = persistent.get("checks")
    achecks = application.get("checks")
    occ = persistent.get("target_occlusion") if isinstance(persistent.get("target_occlusion"), Mapping) else {}
    occ_rows = occ.get("rows") if isinstance(occ.get("rows"), list) else []

    completed = list((root / ".agent" / "commands" / "completed").glob(f"{TASK_ID}_{run_id}.json"))
    failed = list((root / ".agent" / "commands" / "failed").glob(f"{TASK_ID}_{run_id}.json"))

    checks = {
        "single_manual_action": receipt.get("ok") is True and receipt.get("manual_action_count") == 1,
        "command_identity": command.get("task_id") == TASK_ID and command.get("run_id") == run_id,
        "source_contract": contract.get("ok") is True,
        "bridge_status_completed": status.get("ok") is True and status.get("running") is False,
        "command_terminal_completed": len(completed) == 1 and not failed,
        "runtime_ok": report.get("ok") is True and not report.get("failures"),
        "source_exact": report.get("source_timeline_name") == SOURCE,
        "target_exact": report.get("target_timeline_name") == TARGET,
        "textplus_114": report.get("final_textplus_count") == 114,
        "source_unchanged": report.get("source_timeline_unchanged") is True,
        "source_preimage_exact_two": mismatch_shape == expected_shape and source_audit.get("mismatch_count") == 2,
        "authority_coverage_114": preflight.get("authority_counts") == {"legacy": 96, "merged": 1, "visual_first": 17, "total": 114},
        "v4_source_occlusion_present": isinstance(preflight.get("source_v4_occlusion"), Mapping) and preflight["source_v4_occlusion"].get("ok") is True,
        "targeted_writes_exactly_two": report.get("targeted_effect_write_count") == 2 and first.get("write_count") == 2,
        "target_caption_exact": report.get("targeted_caption_name") == TARGET_CAPTION and report.get("targeted_caption_count") == 1,
        "target_fields_exact": sorted(report.get("targeted_effect_fields") or []) == ["Enabled2", "Enabled3"],
        "no_unrelated_caption_mutations": report.get("unrelated_caption_mutation_count") == 0,
        "no_occlusion_mutation": report.get("occlusion_mutation_count") == 0 and report.get("v4_occlusion_preserved") is True,
        "application_checks": all_true(achecks),
        "post_effect_authority_complete": post_audit.get("ok") is True and post_audit.get("mismatch_count") == 0,
        "first_full_effect_contract": first_contract.get("ok") is True and first_contract.get("required_count") == 14 and first_contract.get("required_matched_count") == 14 and first_contract.get("optional_count") == 3 and first_contract.get("optional_exposed_count") == 3 and first_contract.get("optional_matched_count") == 3,
        "second_full_effect_contract": second_contract.get("ok") is True and second_contract.get("required_matched_count") == 14 and second_contract.get("optional_matched_count") == 3,
        "idempotent_second_noop": second.get("idempotent_noop") is True and second.get("mutated") is False and second.get("write_count") == 0,
        "one_save": report.get("save_call_count") == 1,
        "one_resolve_invocation": report.get("resolve_invocation_contract") == 1,
        "persistent": persistent.get("ok") is True,
        "persistent_checks": all_true(pchecks),
        "persistent_target_effect_authority": isinstance(persistent.get("target_effect_audit"), Mapping) and persistent["target_effect_audit"].get("ok") is True,
        "persistent_full_effect_contract": persistent_contract.get("ok") is True and persistent_contract.get("required_matched_count") == 14 and persistent_contract.get("optional_matched_count") == 3,
        "persistent_v4_occlusion": occ.get("ok") is True and len(occ_rows) == 1 and [occ_rows[0].get("start"), occ_rows[0].get("end"), occ_rows[0].get("track_index")] == [426, 454, 25],
        "persistent_readback": report.get("persistent_readback_ok") is True,
        "idempotency": report.get("idempotency_ok") is True,
        "visual_gate_locked": report.get("visual_approval_required") is True and persistent.get("visual_approval_required") is True and report.get("further_rollout_authorized") is False and persistent.get("further_rollout_authorized") is False,
    }
    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "checks": checks,
        "source_effect_mismatches_before": source_mismatches,
        "target_effect_mismatch_count_after": post_audit.get("mismatch_count"),
        "visual_approval_required": True,
        "further_rollout_authorized": False,
        "ok": all(value is True for value in checks.values()),
    }
    write_json(run / "technical_validation.json", result)

    lines = [
        "# FINAL REPORT",
        "",
        f"Task: `{TASK_ID}`",
        f"Run ID: `{run_id}`",
        f"Technical result: **{'PASS' if result['ok'] else 'FAIL'}**",
        "",
        f"- Source: `{SOURCE}`",
        f"- Target: `{TARGET}`",
        f"- Text+: `{report.get('final_textplus_count')}`",
        f"- Targeted caption: `{TARGET_CAPTION}`",
        f"- Targeted writes: `{report.get('targeted_effect_write_count')}` (`Enabled2`, `Enabled3`)",
        f"- Full COME effect contract: `{'PASS' if persistent_contract.get('ok') else 'FAIL'}` (14 required + 3 exposed optional inputs)",
        f"- Unrelated caption mutations: `{report.get('unrelated_caption_mutation_count')}`",
        f"- Occlusion mutations: `{report.get('occlusion_mutation_count')}`",
        f"- Save calls: `{report.get('save_call_count')}`",
        f"- Persistent readback: `{'PASS' if report.get('persistent_readback_ok') else 'FAIL'}`",
        f"- Idempotency: `{'PASS' if report.get('idempotency_ok') else 'FAIL'}`",
        f"- V4 occlusion preserved: `{'PASS' if report.get('v4_occlusion_preserved') else 'FAIL'}`",
        "- Further rollout: unauthorized",
        "- Human visual approval: required",
        "",
        "Stop after this report. Do not continue to caption motion/fade or baked-caption removal until human visual approval.",
    ]
    (run / "FINAL_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        run = find_run(root, args.run_id)
        result = validate(root, run)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": result["ok"], "task_id": TASK_ID, "run_id": result["run_id"], "checks": result["checks"]}, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
