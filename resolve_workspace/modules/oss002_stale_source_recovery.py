"""Delete the one stale OSS-002 disposable source timeline and nothing else."""
from __future__ import annotations

from typing import Any

from resolve_workspace.modules import oss002_sub008_production_canary as canary


TASK_ID = "OSS002_STALE_SOURCE_RECOVERY_V1"
MODE = "oss002_stale_source_recovery"
PROJECT_NAME = canary.PROJECT_NAME
TARGET_TIMELINE = canary.TARGET_TIMELINE
STALE_TIMELINE = canary.SOURCE_TIMELINE
EXPECTED_RESOLVE_VERSION = canary.EXPECTED_RESOLVE_VERSION


def _inventory(project: Any) -> list[dict[str, Any]]:
    return [
        {"index": index, **canary._timeline_identity(canary.carrier._call(project, "GetTimelineByIndex", index))}
        for index in range(1, int(canary.carrier._call(project, "GetTimelineCount") or 0) + 1)
    ]


def _semantic_inventory(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(str(row["name"]), str(row["unique_id"])) for row in rows]


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "mode": MODE,
        "run_id": run_id,
        "save_project_called": False,
        "timeline_inventory_before": [],
        "timeline_inventory_after": [],
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "expected_project": PROJECT_NAME,
            "target_timeline": TARGET_TIMELINE,
            "stale_timeline": STALE_TIMELINE,
            "save_after_verified_deletion": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")

        result["resolve_version"] = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != EXPECTED_RESOLVE_VERSION:
            raise ValueError(f"resolve_version:{result['resolve_version']}")
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != PROJECT_NAME:
            raise ValueError(f"project_identity:{canary._name(project) if project else ''}")
        pool = canary.carrier._call(project, "GetMediaPool")
        target = canary._find_timeline(project, TARGET_TIMELINE)
        before = _inventory(project)
        result["timeline_inventory_before"] = before
        stale_matches = [
            canary.carrier._call(project, "GetTimelineByIndex", row["index"])
            for row in before if row["name"] == STALE_TIMELINE
        ]
        if len(stale_matches) != 1:
            raise ValueError(f"stale_timeline_count:{len(stale_matches)}")
        stale = stale_matches[0]
        target_identity = canary._timeline_identity(target)
        stale_identity = canary._timeline_identity(stale)
        result["target"] = {"project": PROJECT_NAME, **target_identity}
        result["stale_timeline"] = stale_identity
        if not stale_identity["unique_id"] or stale_identity["unique_id"] == target_identity["unique_id"]:
            raise ValueError("stale_timeline_is_production")
        if canary.carrier._call(project, "SetCurrentTimeline", target) is not True:
            raise RuntimeError("target_timeline_activation")
        current = canary.carrier._call(project, "GetCurrentTimeline")
        if canary.carrier._timeline_key(current) != canary.carrier._timeline_key(target):
            raise RuntimeError("target_timeline_activation_readback")
        if canary.carrier._call(pool, "DeleteTimelines", [stale]) is not True:
            raise RuntimeError("stale_timeline_delete")
        after = _inventory(project)
        result["timeline_inventory_after"] = after
        expected_after = [row for row in _semantic_inventory(before) if row != (stale_identity["name"], stale_identity["unique_id"])]
        if _semantic_inventory(after) != expected_after:
            raise RuntimeError("post_delete_inventory")
        if canary.carrier._call(manager, "SaveProject") is not True:
            result["save_project_called"] = True
            result["save_project_returned"] = False
            raise RuntimeError("save_project_failed")
        result.update({
            "ok": True,
            "deleted_timeline": stale_identity,
            "production_timeline_untouched": True,
            "save_project_called": True,
            "save_project_returned": True,
        })
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
    return result
