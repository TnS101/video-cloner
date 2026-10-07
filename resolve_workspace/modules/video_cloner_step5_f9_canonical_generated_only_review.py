"""Create one generated-only review timeline from the accepted F9 canonical timeline."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_step5_f8_generated_only_review as f8

TASK_ID = "VIDEO_CLONER_STEP5_F9_CANONICAL_GENERATED_ONLY_REVIEW_V1"
MODE = "create_f9_canonical_generated_only_review"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object:{path}")
    return value


def _artifact(payload: dict[str, Any], name: str) -> dict[str, Any]:
    path = Path(str(payload[f"{name}_path"])).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != payload[f"{name}_sha256"]:
        raise ValueError(f"{name}_hash")
    return _read(path)


def canonical_case_check(contract: dict[str, Any], audit: dict[str, Any], validation: dict[str, Any]) -> dict[str, bool]:
    objects = {row["source_identity"]: row for row in contract.get("objects", [])}
    texts = [str(row.get("text", {}).get("value") or "") for row in objects.values()]
    targeted = {row["case"]: row.get("ok") is True for row in audit.get("targeted_cases", [])}
    checks = {
        "calling": objects.get("caption_tracklet_0082", {}).get("text", {}).get("value") == "calling",
        "ling_suppressed": "caption_tracklet_0083" not in objects and "ling" not in texts,
        "buyers": objects.get("caption_tracklet_0090", {}).get("text", {}).get("value") == "buyers",
        "buy_suppressed": "caption_tracklet_0091" not in objects and "buy" not in texts,
        "ers_suppressed": "ers" not in texts,
        "your": objects.get("caption_tracklet_0043", {}).get("text", {}).get("value") == "your",
        "why": objects.get("recovered_display_object_why_0001", {}).get("text", {}).get("value") == "why?",
        "we": objects.get("caption_tracklet_0106", {}).get("text", {}).get("value") == "we",
        "have": objects.get("caption_tracklet_0107", {}).get("text", {}).get("value") == "have",
        "selling_continuity": objects.get("continuous_visual_identity_0014", {}).get("resolve_interval") == [68, 108] and "caption_tracklet_0013" not in objects,
        "matching_continuity": objects.get("caption_tracklet_0094", {}).get("resolve_interval") == [599, 629] and "caption_tracklet_0096" not in objects,
        "targeted_cases": all(targeted.get(name) is True for name in ("calling", "buyers", "with_the_buyers", "we_have", "your_why", "Selling", "Matching")),
        "no_duplicate_owner": validation.get("duplicate_canonical_owners") == 0 and validation.get("unsupported_fragment_renders") == 0,
    }
    checks["all_pass"] = all(checks.values())
    return checks


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    report_dir = Path(str(payload.get("report_dir") or ROOT / ".agent/reports" / TASK_ID / run_id)).resolve()
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "classification": "BLOCKED", "mutation_counts": {}}
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        contract = _artifact(payload, "contract")
        audit = _artifact(payload, "audit")
        validation = _artifact(payload, "validation")
        cases = canonical_case_check(contract, audit, validation)
        if not cases["all_pass"] or validation.get("pass") is not True or validation.get("persisted_renderable_objects") != contract.get("object_count"):
            raise ValueError("canonical_source_validation")

        inner_command = copy.deepcopy(command)
        inner_command.update({"task_id": f8.TASK_ID, "mode": f8.MODE})
        inner_command["payload"].update({"f7_timeline": payload["source_timeline"], "f7_timeline_uid": payload["source_timeline_uid"]})
        inner = f8.run(resolve, {"run_id": run_id, "command": inner_command})
        result["mutation_counts"] = inner.get("mutation_counts", {})
        if inner.get("ok") is not True:
            result.update({"error": inner.get("error", "generated_only_isolation"), "rollback": inner.get("rollback")})
            return result

        machine_path = report_dir / "f8_generated_only_machine_check.json"
        machine = _read(machine_path)
        machine.update({
            "canonical_case_check": cases,
            "canonical_source_timeline_unchanged": machine.get("f7_timeline_unchanged") is True,
            "expected_canonical_textplus_count": contract["object_count"],
            "old_caption_object_count": machine.get("other_text_or_generated_extra_count"),
        })
        machine["ok"] = machine.get("ok") is True and machine["canonical_source_timeline_unchanged"] and cases["all_pass"]
        output = report_dir / "step5_f9_canonical_generated_only_machine_check.json"
        f8.f7.IMPLEMENTATION.base.write(output, machine)
        if not machine["ok"]:
            raise ValueError("f9_machine_check")
        result.update({
            "ok": True,
            "classification": "READY_FOR_F9_CANONICAL_HUMAN_REVIEW",
            "canonical_case_check": cases,
            "review_timeline": inner["review_timeline"],
            "machine_check": str(output),
        })
    except BaseException as exc:
        result["error"] = f8.f7.IMPLEMENTATION.visual.base.compact_exception(exc)
    finally:
        f8.f7.IMPLEMENTATION.base.write(report_dir / "step5_f9_canonical_generated_only_review.json", result)
    return result
