#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

VERSION = "validate_resolve_caption_animation_step_3C_v1_2_archived_mode_reports"
EXPECTED_WORKSPACE_PREFIX = "resolve_caption_animation_step_3C_"
VALID_MODES = {"first_application_pass", "idempotent_second_run"}


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def integer(mapping: Dict[str, Any], key: str) -> int:
    try:
        return int(mapping.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def bool_value(mapping: Dict[str, Any], key: str) -> bool:
    return bool(mapping.get(key))


def selected_plan_items(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = plan.get("items") or []
    if not isinstance(items, list):
        return []
    return [
        row
        for row in items
        if isinstance(row, dict) and bool(row.get("selected"))
    ]


def animation_keyframe_count(item: Dict[str, Any]) -> int:
    animation = item.get("animation") or {}
    if not isinstance(animation, dict):
        return 0
    declared = animation.get("target_keyframe_count")
    try:
        if declared is not None:
            return int(declared)
    except (TypeError, ValueError):
        pass
    keyframes = animation.get("keyframes") or []
    return len(keyframes) if isinstance(keyframes, list) else 0


def plan_counts(plan: Dict[str, Any]) -> Dict[str, int]:
    items = plan.get("items") or []
    item_count = len(items) if isinstance(items, list) else 0
    selected = selected_plan_items(plan)
    target_count = sum(animation_keyframe_count(row) for row in selected)
    return {
        "item_count": item_count,
        "selected_count": len(selected),
        "target_keyframe_count": target_count,
        "static_count": max(0, item_count - len(selected)),
    }


def report_item_index(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = report.get("items") or []
    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name:
            result[name] = row
    return result


def validate_target_rows(
    selected_items: Iterable[Dict[str, Any]],
    report: Dict[str, Any],
) -> Tuple[bool, List[str], int]:
    failures: List[str] = []
    report_items = report_item_index(report)
    verified_target_count = 0

    for plan_item in selected_items:
        name = str(plan_item.get("name") or "").strip()
        expected_targets = animation_keyframe_count(plan_item)
        report_item = report_items.get(name)

        if report_item is None:
            failures.append(f"missing_report_item:{name}")
            continue

        targets = report_item.get("targets") or []
        if not isinstance(targets, list):
            targets = []

        if len(targets) != expected_targets:
            failures.append(
                f"target_count_mismatch:{name}:"
                f"expected={expected_targets}:actual={len(targets)}"
            )

        for target in targets:
            if not isinstance(target, dict):
                failures.append(f"invalid_target_row:{name}")
                continue

            input_name = str(target.get("input") or "unknown")
            frame = target.get("local_frame", target.get("frame", "?"))

            if not bool(target.get("modifier_connected")):
                failures.append(
                    f"modifier_not_connected:{name}:{input_name}@{frame}"
                )
            if not bool(target.get("matched_after")):
                failures.append(
                    f"temporal_value_mismatch:{name}:{input_name}@{frame}"
                )
            if not bool(target.get("present_after")):
                failures.append(
                    f"persistent_target_not_verified:{name}:{input_name}@{frame}"
                )
            else:
                verified_target_count += 1

        if not bool(report_item.get("ok")):
            failures.append(f"report_item_not_ok:{name}")

    return len(failures) == 0, failures, verified_target_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Strict Major Step 3C Resolve report validator. Uses separate "
            "first-application and idempotency report snapshots."
        )
    )
    parser.add_argument("--mode", required=True, choices=sorted(VALID_MODES))
    parser.add_argument("--plan", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    args = parser.parse_args()

    plan_path = Path(args.plan)
    report_path = Path(args.report)
    output_path = Path(args.output)

    plan = load_json(plan_path)
    report = load_json(report_path)
    summary = report.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}

    expected_v3 = int(args.expected_v3_count)
    counts = plan_counts(plan)
    selected = selected_plan_items(plan)
    selected_count = counts["selected_count"]
    expected_keyframes = counts["target_keyframe_count"]

    failures: List[str] = []
    warnings: List[str] = []

    expected_run_mode = (
        "first_application"
        if args.mode == "first_application_pass"
        else "idempotent_second_run"
    )

    plan_hash = str(plan.get("plan_hash") or "")
    report_plan_hash = str(report.get("plan_hash") or "")
    workspace_version = str(report.get("workspace_version") or "")

    checks: Dict[str, bool] = {
        "plan_ok": bool(plan.get("ok")),
        "report_ok": bool(report.get("ok")),
        "workspace_version": workspace_version.startswith(
            EXPECTED_WORKSPACE_PREFIX
        ),
        "report_run_mode": str(report.get("run_mode") or "")
        == expected_run_mode,
        "plan_hash_match": bool(plan_hash)
        and report_plan_hash == plan_hash,
        "expected_v3_count": integer(summary, "v3_candidate_count")
        == expected_v3,
        "plan_item_count": counts["item_count"] == expected_v3
        and integer(summary, "plan_item_count") == expected_v3,
        "selected_count": selected_count > 0
        and integer(summary, "selected_animation_count") == selected_count,
        "mapped_count": integer(summary, "mapped_count") == selected_count,
        "static_untouched_count": integer(summary, "static_untouched_count")
        == counts["static_count"],
        "target_keyframe_count": integer(summary, "target_keyframe_count")
        == expected_keyframes,
        "readback_success_count": integer(
            summary, "readback_success_count"
        )
        == selected_count,
        "readback_keyframe_count": integer(
            summary, "readback_keyframe_count"
        )
        == expected_keyframes,
        "failed_count": integer(summary, "failed_count") == 0,
        "font_integrity_failure_count": integer(
            summary, "font_integrity_failure_count"
        )
        == 0,
        "timeline_integrity_failure_count": integer(
            summary, "timeline_integrity_failure_count"
        )
        == 0,
        "core_track_integrity": bool_value(
            report.get("core_track_integrity") or {}, "ok"
        ),
        "v3_track_integrity": bool_value(
            report.get("v3_track_integrity") or {}, "ok"
        ),
        "keyframe_presence_verified": bool_value(
            summary, "keyframe_presence_verified"
        )
        and integer(summary, "readback_keyframe_count")
        == integer(summary, "target_keyframe_count"),
    }

    target_rows_ok, target_failures, verified_target_count = (
        validate_target_rows(selected, report)
    )
    checks["per_target_persistence"] = target_rows_ok
    checks["verified_target_count"] = verified_target_count == expected_keyframes
    failures.extend(target_failures)

    modified = integer(summary, "modified_count")
    already = integer(summary, "already_correct_count")
    written = integer(summary, "keyframes_written_count")

    if args.mode == "first_application_pass":
        checks.update(
            {
                "first_run_modified_count": modified == selected_count,
                "first_run_already_correct_count": already == 0,
                "first_run_keyframes_written": written == expected_keyframes,
            }
        )
    else:
        checks.update(
            {
                "second_run_modified_count": modified == 0,
                "second_run_already_correct_count": already == selected_count,
                "second_run_keyframes_written": written == 0,
            }
        )

    for key, passed in checks.items():
        if not passed:
            failures.append(key)

    failures = list(dict.fromkeys(failures))

    if (
        args.mode == "first_application_pass"
        and str(report.get("run_mode") or "") == "idempotent_second_run"
    ):
        warnings.append(
            "The supplied report is a second-run report. The latest report "
            "was overwritten after the animations were already present. Use "
            "the archived first-application report or adopt the saved first "
            "report with the recovery BAT."
        )

    validation = {
        "ok": len(failures) == 0,
        "step": "Major Step 3C",
        "validator_version": VERSION,
        "mode": args.mode,
        "plan": str(plan_path),
        "report": str(report_path),
        "selected_animation_count": selected_count,
        "expected_keyframe_count": expected_keyframes,
        "summary": {
            "v3_candidate_count": integer(summary, "v3_candidate_count"),
            "plan_item_count": counts["item_count"],
            "selected_animation_count": selected_count,
            "mapped_count": integer(summary, "mapped_count"),
            "modified_count": modified,
            "already_correct_count": already,
            "static_untouched_count": integer(
                summary, "static_untouched_count"
            ),
            "target_keyframe_count": integer(
                summary, "target_keyframe_count"
            ),
            "keyframes_written_count": written,
            "readback_success_count": integer(
                summary, "readback_success_count"
            ),
            "readback_keyframe_count": integer(
                summary, "readback_keyframe_count"
            ),
            "verified_target_count": verified_target_count,
            "failed_count": integer(summary, "failed_count"),
            "font_integrity_failure_count": integer(
                summary, "font_integrity_failure_count"
            ),
            "timeline_integrity_failure_count": integer(
                summary, "timeline_integrity_failure_count"
            ),
            "keyframe_presence_verified": bool_value(
                summary, "keyframe_presence_verified"
            ),
            "animation_type_counts": summary.get(
                "animation_type_counts"
            )
            or {},
        },
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
        "output": str(output_path),
    }

    write_json(output_path, validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
