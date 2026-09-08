"""Validate completed Phase 4C1 bridge evidence without contacting Resolve."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from resolve_workspace.modules import video_cloner_phase4c1_flash_v4_integration as runtime


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(path.name)
    return value


def validate(root: Path, rid: str, mode: str) -> tuple[dict, list[str]]:
    run_dir = root.resolve() / ".agent" / "reports" / runtime.TASK_ID / rid
    required = ("command.json", "publication_receipt.json", "flash_plan.json", "phase4c1_flash_result.json", "status.json", "report.json", "run.log")
    failures = [f"missing:{name}" for name in required if not (run_dir / name).is_file() or (run_dir / name).stat().st_size == 0]
    if failures:
        return {"ok": False, "failures": failures}, failures
    report = load(run_dir / "report.json")
    result = load(run_dir / "phase4c1_flash_result.json")
    command = load(run_dir / "command.json")
    plan = load(run_dir / "flash_plan.json")
    runtime.validate_plan(plan)
    flash = result.get("flash_after") or {}
    rows = flash.get("rows") or []
    expected = plan["flashes"]
    expected_count = len(expected)
    expected_starts = [row["start_frame"] for row in expected]
    artifact = plan["artifact"]
    counts = result.get("forbidden_operation_counts") or {}
    before = result.get("non_target_before") or []
    after = result.get("non_target_after") or []
    key = lambda row: (row.get("name"), row.get("signature"))
    checks = {
        "runtime_ok": report.get("ok") is True and result.get("ok") is True,
        "mode": result.get("run_mode") == mode,
        "identity": result.get("project_name") == plan["project_name"] and result.get("target_timeline_name") == plan["target_timeline_name"] and (command.get("payload") or {}).get("target_timeline_name") == plan["target_timeline_name"],
        "carrier_count": flash.get("count") == expected_count and flash.get("neutral_carrier_count") == expected_count and flash.get("source_video_carrier_count") == 0,
        "exact_starts": [row.get("start") for row in rows] == expected_starts,
        "four_frames": [row.get("duration") for row in rows] == [4] * expected_count,
        "fusion": all((row.get("fusion") or {}).get("ok") is True for row in rows),
        "base": (result.get("base_after") or {}).get("clip_count") == artifact["clip_count"] and (result.get("base_after") or {}).get("duration_frames") == artifact["duration_frames"] and (result.get("base_after") or {}).get("signature") == (result.get("base_before") or {}).get("signature"),
        "non_targets": result.get("protected_timeline_unchanged") is True and Counter(map(key, before)) == Counter(map(key, after)),
        "forbidden": counts and not any(counts.values()),
        "save": result.get("save_project_count") == (1 if mode == "apply" and expected_count else 0),
    }
    if mode == "apply" and expected_count:
        visual = result.get("visual_evidence") or {}
        checks["visual"] = visual.get("ok") is True and visual.get("total_frames") == expected_count * 4 and all(Path(path).is_file() and Path(path).stat().st_size > 0 for row in visual.get("rows", []) for path in row.get("files", []))
        checks["alpha"] = result.get("alpha_readback_checks") == expected_count * 3
        checks["created"] = result.get("created_carriers") == expected_count and result.get("configured_fusion") == expected_count
    else:
        checks["idempotent"] = result.get("idempotent") is True and result.get("created_carriers") == 0 and result.get("configured_fusion") == 0 and result.get("media_import_count") == 0 and result.get("track_add_count") == 0
    failures.extend(key for key, value in checks.items() if not value)
    summary = {"ok": not failures, "task_id": runtime.TASK_ID, "run_id": rid, "run_mode": mode, "checks": checks, "carrier_names": [row.get("name") for row in rows], "carrier_starts": [row.get("start") for row in rows], "durations": [row.get("duration") for row in rows], "track_indices": [row.get("track_index") for row in rows], "save_project_count": result.get("save_project_count"), "failures": failures}
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-mode", choices=("apply", "idempotency"), required=True)
    args = parser.parse_args()
    result, failures = validate(args.root, args.run_id, args.run_mode)
    run_dir = args.root.resolve() / ".agent" / "reports" / runtime.TASK_ID / args.run_id
    (run_dir / "validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
