"""Apply seven OSS-002C recovered recipes without altering the accepted 56."""
from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any


MODULE_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


full = _load("vc_oss002_full", MODULE_DIR / "oss002_full_caption_motion_rollout.py")
rep, canary, batch = full.rep, full.canary, full.batch

TASK_ID = "OSS002C_RECOVERED_CAPTION_BATCH_V1"
MODE = "oss002c_recovered_caption_batch"
TARGET_ORDINALS = (5, 37, 54, 75, 80, 101, 107)
EXPECTED_EXISTING_NESTED = 56
SOURCE_PREFIX = "_VC_OSS002C_SUB"


def _classification_sets(recovery_path: Path) -> tuple[set[int], set[int], set[int]]:
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    if recovery.get("schema") != "video_cloner.oss002c_cross_authority_recovery" or recovery.get("counts", {}).get("new_meaningful_motion") != 13:
        raise ValueError("recovery_authority")
    statuses = {int(row["ordinal"]): row["status"] for row in recovery.get("captions") or []}
    meaningful = {ordinal for ordinal, status in statuses.items() if status == "recovered_meaningful_motion"}
    static = {ordinal for ordinal, status in statuses.items() if status == "recovered_static"}
    unsupported = {ordinal for ordinal, status in statuses.items() if status in {"ambiguous", "rejected_false_association"}}
    if len(meaningful) != 13 or len(static) != 13 or len(unsupported) != 6:
        raise ValueError("recovery_classification")
    return meaningful, static, unsupported


def _recipe_map(recipe_path: Path) -> dict[int, dict[str, Any]]:
    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    return {
        int(str(row["caption_id"]).rsplit("_", 1)[-1]): rep.recipe_contract.validate_recipe(row)
        for row in payload.get("recipes") or []
    }


def _authorities(recovery_path: Path, recipe_path: Path, target_ordinals: tuple[int, ...] = TARGET_ORDINALS) -> dict[int, dict[str, Any]]:
    meaningful, _, _ = _classification_sets(recovery_path)
    recipes = _recipe_map(recipe_path)
    if any(ordinal not in meaningful or ordinal not in recipes for ordinal in target_ordinals):
        raise ValueError("batch_targets")
    return {ordinal: recipes[ordinal] for ordinal in target_ordinals}


def _source_name(ordinal: int, run_id: str) -> str:
    token = str(run_id).rsplit("_", 1)[-1][:12]
    if not token:
        raise ValueError("run_id_source_name")
    return f"{SOURCE_PREFIX}{ordinal:03d}_{token}"


def _ordinal_from_source(name: str) -> int | None:
    match = re.search(r"SUB(\d{3})_", name)
    return int(match.group(1)) if match else None


def run_delta(
    resolve: Any,
    context: dict[str, Any],
    *,
    task_id: str,
    mode: str,
    target_ordinals: tuple[int, ...],
    expected_existing_nested: int,
    accepted_source_names: dict[int, str] | None = None,
    require_all_meaningful: bool = False,
) -> dict[str, Any]:
    accepted_source_names = accepted_source_names or {}
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": task_id, "mode": mode, "run_id": run_id, "save_project_called": False, "failures": []}
    project = pool = None
    created_sources: list[Any] = []
    created_items: list[Any] = []
    original_states: dict[int, bool] = {}
    before_nested: list[tuple[Any, ...]] = []
    base_frame = 0
    saved = False
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT,
            "target_timeline": rep.EXPECTED_TIMELINE,
            "target_timeline_uid": rep.EXPECTED_TIMELINE_UID,
            "expected_caption_count": 112,
            "expected_video_track_count": 3,
            "expected_existing_nested_count": expected_existing_nested,
            "target_ordinals": list(target_ordinals),
            "save_after_verification": True,
        }
        if accepted_source_names:
            required.update({
                "canonical_meaningful_count": 13,
                "recovered_static_count": 13,
                "unsupported_count": 6,
                "accepted_oss002c_ordinals": sorted(accepted_source_names),
            })
        if command.get("task") != task_id or command.get("mode") != mode or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        result["resolve_version"] = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError(f"resolve_version:{result['resolve_version']}")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        recovery_path = canary._repository_file(root, payload.get("recovery_path"), payload.get("recovery_sha256"), "recovery")
        recipe_path = canary._repository_file(root, payload.get("recipe_path"), payload.get("recipe_sha256"), "recipe")
        fcpxml_path = canary._repository_file(root, payload.get("fcpxml_path"), payload.get("fcpxml_sha256"), "fcpxml")
        meaningful, recovered_static, unsupported = _classification_sets(recovery_path)
        all_recipes = _recipe_map(recipe_path)
        recipes = _authorities(recovery_path, recipe_path, target_ordinals)
        styles = batch._styles_by_ordinal(fcpxml_path)
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        pool = canary.carrier._call(project, "GetMediaPool")
        target = canary._activate_target(project)
        if canary._timeline_identity(target)["unique_id"] != rep.EXPECTED_TIMELINE_UID:
            raise ValueError("timeline_uid")
        if int(canary.carrier._call(target, "GetTrackCount", "video") or 0) != 3:
            raise ValueError("video_track_count")
        base_frame = int(canary.carrier._call(target, "GetStartFrame") or 0)
        captions = canary.basic_title_rows(target)
        if len(captions) != 112:
            raise ValueError(f"caption_count:{len(captions)}")
        caption_before = rep._caption_snapshot(captions, base_frame)
        unrelated_before = full._unrelated_snapshot(target)
        nested = full._nested_by_name(target)
        before_nested = rep._stable_nested(target, base_frame)
        nested_ordinals = [_ordinal_from_source(name) for name in nested]
        existing_ordinals = {ordinal for ordinal in nested_ordinals if ordinal is not None}
        disabled = {ordinal for ordinal, row in enumerate(captions, 1) if row["enabled"] is False}
        existing_oss002c = {_ordinal_from_source(name) for name in nested if name.startswith(SOURCE_PREFIX)}
        if (
            len(nested) != expected_existing_nested
            or len(nested_ordinals) != len(existing_ordinals)
            or None in nested_ordinals
            or disabled != existing_ordinals
            or disabled & set(target_ordinals)
            or (recovered_static | unsupported) & disabled
            or existing_oss002c != set(accepted_source_names)
            or any(full.STEP3C_PATTERN.match(name) for name in nested)
        ):
            raise ValueError("accepted_baseline")
        for ordinal, name in accepted_source_names.items():
            row, recipe = nested.get(name), all_recipes[ordinal]
            if row is None or row["track"] != 3 or row["start"] - base_frame != recipe["start_frame"] or row["duration"] != recipe["duration"]:
                raise ValueError(f"accepted_oss002c_replacement:{ordinal}")
        if require_all_meaningful and meaningful != set(accepted_source_names) | set(target_ordinals):
            raise ValueError("meaningful_reconciliation")
        original_states = {ordinal: captions[ordinal - 1]["enabled"] for ordinal in target_ordinals}
        for ordinal, recipe in recipes.items():
            source = captions[ordinal - 1]
            if source["enabled"] is not True or source["start"] - base_frame != recipe["start_frame"] or source["duration"] != recipe["duration"]:
                raise ValueError(f"source_caption_contract:{ordinal}")
        names = {ordinal: _source_name(ordinal, run_id) for ordinal in target_ordinals}
        inventory_names = {row["name"] for row in canary._timeline_inventory(project)}
        if any(name in inventory_names for name in names.values()):
            raise ValueError("source_timeline_collision")

        for ordinal in target_ordinals:
            source = full._build_source(pool, project, names[ordinal], recipes[ordinal], styles[ordinal])
            created_sources.append(source)
            target = canary._activate_target(project)
            item = full._append(pool, project, target, source, recipes[ordinal], 3, base_frame)
            created_items.append(item)
            original = canary.basic_title_rows(target)[ordinal - 1]["item"]
            if canary.carrier._call(original, "SetClipEnabled", False) is False or canary._clip_enabled(original) is not False:
                raise RuntimeError(f"original_disable:{ordinal}")

        target = canary._activate_target(project)
        final_nested = rep._stable_nested(target, base_frame)
        final_captions = canary.basic_title_rows(target)
        final_rows = full._nested_by_name(target)
        final_ordinals = [_ordinal_from_source(name) for name in final_rows]
        final_ordinal_set = {ordinal for ordinal in final_ordinals if ordinal is not None}
        if (
            len(final_nested) != expected_existing_nested + len(target_ordinals)
            or not set(before_nested).issubset(final_nested)
            or len(final_ordinals) != len(final_ordinal_set)
            or None in final_ordinals
        ):
            raise RuntimeError("accepted_nested_changed")
        final_disabled = {ordinal for ordinal, row in enumerate(final_captions, 1) if row["enabled"] is False}
        if final_disabled != final_ordinal_set or any(final_captions[ordinal - 1]["enabled"] is not False for ordinal in target_ordinals):
            raise RuntimeError("target_original_enabled")
        if any(final_captions[ordinal - 1]["enabled"] is not True for ordinal in recovered_static | unsupported):
            raise RuntimeError("static_or_unsupported_changed")
        if require_all_meaningful and not meaningful.issubset(final_ordinal_set):
            raise RuntimeError("meaningful_replacement_missing")
        final_snapshot = rep._caption_snapshot(final_captions, base_frame)
        if [(a, b, c, e) for a, b, c, _, e in final_snapshot] != [(a, b, c, e) for a, b, c, _, e in caption_before]:
            raise RuntimeError("caption_timing_text_changed")
        if full._unrelated_snapshot(target) != unrelated_before or int(canary.carrier._call(target, "GetTrackCount", "video") or 0) != 3:
            raise RuntimeError("unrelated_timeline_changed")
        result.update({
            "verification": "PASS", "targets": list(target_ordinals), "replacements_created": len(created_items),
            "accepted_replacements_preserved": expected_existing_nested, "canonical_meaningful": len(meaningful),
            "recovered_static_preserved": len(recovered_static), "unsupported_preserved": len(unsupported), "overlay_tracks_used": [3],
        })
        result["save_project_called"] = True
        result["save_project_returned"] = canary.carrier._call(manager, "SaveProject")
        if result["save_project_returned"] is not True:
            raise RuntimeError("save_project")
        saved = True
        result["ok"] = True
        return result
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if project is not None and pool is not None and not saved:
            result["rollback"] = full._rollback(project, pool, created_sources, created_items, [], False, original_states, None, base_frame, before_nested)
        return result


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    return run_delta(
        resolve,
        context,
        task_id=TASK_ID,
        mode=MODE,
        target_ordinals=TARGET_ORDINALS,
        expected_existing_nested=EXPECTED_EXISTING_NESTED,
    )


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
