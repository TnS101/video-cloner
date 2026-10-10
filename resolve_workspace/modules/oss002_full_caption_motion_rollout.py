"""Reconcile Reel #3 to the accepted OSS-002 caption-motion authority."""
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


rep = _load("vc_oss002_rep", MODULE_DIR / "oss002_oss_animation_representative_batch.py")
canary, batch = rep.canary, rep.batch

TASK_ID = "OSS002_FULL_CAPTION_MOTION_ROLLOUT_V1"
MODE = "oss002_full_caption_motion_rollout"
EXPECTED_NESTED = 20
LEGACY_NAME = batch.ACCEPTED_SOURCE_NAME
LEGACY_UID = batch.ACCEPTED_SOURCE_UID
REPRESENTATIVE_NAMES = {
    9: "_VC_OSS002_OSS_SUB009_73b8a610ab0e",
    12: "_VC_OSS002_OSS_SUB012_73b8a610ab0e",
    15: "_VC_OSS002_OSS_SUB015_73b8a610ab0e",
    26: "_VC_OSS002_OSS_SUB026_73b8a610ab0e",
}
STEP3C_ORDINALS = {10, 13, 19, 21, 22, 24, 27, 31, 32, 52, 55, 69, 70, 73, 93}
STEP3C_PATTERN = re.compile(r"^_VC_OSS002_SUB(\d{3})_2ec99e623a75$")
FULL_PREFIX = "_VC_OSS002_FULL_SUB"


def _authority(path: Path) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "video_cloner.oss002_full_motion_rollout" or manifest.get("decision") != "COMBINE_ACCEPTED":
        raise ValueError("manifest_authority")
    rows = {int(row["ordinal"]): row for row in manifest.get("captions") or []}
    if set(rows) != set(range(1, 113)) or manifest.get("counts", {}).get("total_captions") != 112:
        raise ValueError("manifest_caption_count")
    recipe_path = path.parent / "DZatr0EJt4B_caption_animation_recipes_oss002_full.json"
    recipes_payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipes = {int(str(row["caption_id"]).rsplit("_", 1)[-1]): rep.recipe_contract.validate_recipe(row) for row in recipes_payload.get("recipes") or []}
    for ordinal, row in rows.items():
        if row["motion_detected"] and ordinal not in recipes:
            raise ValueError(f"motion_recipe_missing:{ordinal}")
    return rows, recipes, manifest


def _source_name(ordinal: int, run_id: str) -> str:
    token = str(run_id).rsplit("_", 1)[-1][:12]
    if not token:
        raise ValueError("run_id_source_name")
    return f"{FULL_PREFIX}{ordinal:03d}_{token}"


def _nested_by_name(timeline: Any) -> dict[str, dict[str, Any]]:
    rows = batch._nested_items(timeline)
    names = [row["source"]["name"] for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_nested_source_name")
    return {row["source"]["name"]: row for row in rows}


def _caption_snapshot(timeline: Any, base_frame: int) -> list[tuple[Any, ...]]:
    return rep._caption_snapshot(canary.basic_title_rows(timeline), base_frame)


def _unrelated_snapshot(timeline: Any) -> list[tuple[Any, ...]]:
    rows = []
    for kind, tracks in (("video", [1]), ("audio", range(1, int(canary._optional(timeline, "GetTrackCount", "audio", default=0) or 0) + 1))):
        for track in tracks:
            for index, item in enumerate(canary._optional(timeline, "GetItemListInTrack", kind, track, default=[]) or []):
                pool_item = canary._optional(item, "GetMediaPoolItem")
                rows.append((kind, track, index, canary._name(item), canary._item_start(item), canary._item_duration(item), canary._name(pool_item), str(canary._optional(pool_item, "GetUniqueId", default="") or "")))
    return rows


def _append(pool: Any, project: Any, target: Any, source: Any, recipe: dict[str, Any], track: int, base_frame: int) -> Any:
    canary.carrier._call(project, "SetCurrentTimeline", target)
    returned = canary.carrier._call(pool, "AppendToTimeline", [{
        "mediaPoolItem": canary.carrier._call(source, "GetMediaPoolItem"),
        "startFrame": 0,
        "endFrame": recipe["duration"],
        "trackIndex": track,
        "recordFrame": base_frame + recipe["start_frame"],
    }])
    if not isinstance(returned, (list, tuple)) or len(returned) != 1 or returned[0] is None:
        raise RuntimeError(f"replacement_append:{recipe['caption_id']}")
    item = returned[0]
    track_type, track_index = canary.carrier._call(item, "GetTrackTypeAndIndex")
    actual = (track_type, int(track_index), canary._item_start(item) - base_frame, canary._item_duration(item))
    expected = ("video", track, recipe["start_frame"], recipe["duration"])
    if actual != expected:
        raise RuntimeError(f"replacement_placement:{recipe['caption_id']}:{actual!r}")
    inner = canary.carrier._call(canary.carrier._call(item, "GetMediaPoolItem"), "GetTimeline")
    if inner is None or canary.carrier._timeline_key(inner) != canary.carrier._timeline_key(source):
        raise RuntimeError(f"replacement_reachback:{recipe['caption_id']}")
    return item


def _build_source(pool: Any, project: Any, name: str, recipe: dict[str, Any], style: dict[str, Any]) -> Any:
    source = canary.carrier._call(pool, "CreateEmptyTimeline", name)
    identity = canary._timeline_identity(source)
    if source is None or identity["name"] != name or not identity["unique_id"] or canary.carrier._call(project, "SetCurrentTimeline", source) is not True:
        raise RuntimeError(f"source_create:{recipe['caption_id']}")
    canary.carrier._call(source, "InsertFusionTitleIntoTimeline", "Text+")
    item, tool = canary.carrier._find_textplus(source)
    rep.canary._set_static_style(tool, style)
    comp = canary.carrier._call(item, "GetFusionCompByIndex", 1)
    rep.apply_recipe_channels(comp, tool, recipe, style)
    if canary.carrier._call(source, "GetMediaPoolItem") is None:
        raise RuntimeError(f"source_media_pool_item:{recipe['caption_id']}")
    return source


def _rollback(project: Any, pool: Any, created_sources: list[Any], created_items: list[Any], old_rows: list[dict[str, Any]], old_deleted: bool, original_states: dict[int, bool], created_track: int | None, base_frame: int, before_nested: list[tuple[Any, ...]]) -> dict[str, Any]:
    restored_items = restored_captions = sources_deleted = track_removed = True
    try:
        target = canary._activate_target(project)
        if created_items:
            canary._optional(target, "DeleteClips", created_items, False, default=False)
        rows = canary.basic_title_rows(target)
        for ordinal, enabled in original_states.items():
            item = rows[ordinal - 1]["item"]
            restored_captions = restored_captions and canary._optional(item, "SetClipEnabled", enabled, default=False) is not False and canary._clip_enabled(item) is enabled
        if old_deleted:
            for row in old_rows:
                source_item = canary.carrier._call(row["inner"], "GetMediaPoolItem")
                returned = canary.carrier._call(pool, "AppendToTimeline", [{
                    "mediaPoolItem": source_item, "startFrame": 0, "endFrame": row["duration"],
                    "trackIndex": row["track"], "recordFrame": row["start"],
                }])
                restored_items = restored_items and isinstance(returned, (list, tuple)) and len(returned) == 1
        if created_sources:
            canary.carrier._call(project, "SetCurrentTimeline", target)
            sources_deleted = canary._optional(pool, "DeleteTimelines", created_sources, default=False) is True
        if created_track is not None:
            items = canary._optional(target, "GetItemListInTrack", "video", created_track, default=[]) or []
            track_removed = not items and canary._optional(target, "DeleteTrack", "video", created_track, default=False) is True
        target = canary._activate_target(project)
        rows = canary.basic_title_rows(target)
        verified = all(rows[ordinal - 1]["enabled"] is enabled for ordinal, enabled in original_states.items()) and rep._stable_nested(target, base_frame) == before_nested
    except Exception:
        verified = False
    return {"old_items_restored": restored_items, "originals_restored": restored_captions, "new_sources_deleted": sources_deleted, "temporary_track_removed": track_removed, "nested_baseline_verified": verified, "ok": restored_items and restored_captions and sources_deleted and track_removed and verified}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_called": False, "failures": []}
    project = pool = None
    created_sources: list[Any] = []
    created_items: list[Any] = []
    old_rows: list[dict[str, Any]] = []
    old_deleted = False
    created_track: int | None = None
    original_states: dict[int, bool] = {}
    before_nested: list[tuple[Any, ...]] = []
    caption_before: list[tuple[Any, ...]] = []
    unrelated_before: list[tuple[Any, ...]] = []
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
            "expected_existing_nested_count": EXPECTED_NESTED,
            "save_after_verification": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        result["resolve_version"] = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError(f"resolve_version:{result['resolve_version']}")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        manifest_path = canary._repository_file(root, payload.get("manifest_path"), payload.get("manifest_sha256"), "manifest")
        recipe_path = canary._repository_file(root, payload.get("recipe_path"), payload.get("recipe_sha256"), "recipe")
        fcpxml_path = canary._repository_file(root, payload.get("fcpxml_path"), payload.get("fcpxml_sha256"), "fcpxml")
        authority, recipes, manifest = _authority(manifest_path)
        if recipe_path.name != "DZatr0EJt4B_caption_animation_recipes_oss002_full.json":
            raise ValueError("recipe_path")
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
        original_states = {ordinal: row["enabled"] for ordinal, row in enumerate(captions, 1)}
        caption_before = _caption_snapshot(target, base_frame)
        unrelated_before = _unrelated_snapshot(target)
        nested = _nested_by_name(target)
        before_nested = rep._stable_nested(target, base_frame)
        if len(nested) != EXPECTED_NESTED:
            raise ValueError(f"nested_count:{len(nested)}")
        legacy = nested.get(LEGACY_NAME)
        if legacy is None or legacy["source"]["unique_id"] != LEGACY_UID or legacy["start"] - base_frame != 39 or legacy["duration"] != 5:
            raise ValueError("legacy_sub008")
        for ordinal, name in REPRESENTATIVE_NAMES.items():
            row = nested.get(name)
            contract = authority[ordinal]
            if row is None or row["start"] - base_frame != contract["start_frame"] or row["duration"] != contract["duration"]:
                raise ValueError(f"representative:{ordinal}")
        old_rows = [row for name, row in nested.items() if STEP3C_PATTERN.match(name)]
        old_ordinals = {int(STEP3C_PATTERN.match(row["source"]["name"]).group(1)) for row in old_rows}
        if old_ordinals != STEP3C_ORDINALS or len(old_rows) != 15:
            raise ValueError(f"step3c_inventory:{sorted(old_ordinals)}")
        allowed = {LEGACY_NAME, *REPRESENTATIVE_NAMES.values(), *(row["source"]["name"] for row in old_rows)}
        if set(nested) != allowed:
            raise ValueError("unowned_nested_item")
        expected_disabled = {8, *REPRESENTATIVE_NAMES, *STEP3C_ORDINALS}
        if {ordinal for ordinal, enabled in original_states.items() if not enabled} != expected_disabled:
            raise ValueError("baseline_caption_enabled_state")

        create_ordinals = [ordinal for ordinal, row in authority.items() if row["action"] in {"create_oss_disable_original", "supersede_step3c_with_oss"}]
        existing_names = {row["name"] for row in canary._timeline_inventory(project)}
        names = {ordinal: _source_name(ordinal, run_id) for ordinal in create_ordinals}
        if any(name in existing_names for name in names.values()):
            raise ValueError("source_timeline_collision")
        superseded = sorted(ordinal for ordinal in create_ordinals if ordinal in STEP3C_ORDINALS)
        if superseded:
            if canary.carrier._call(target, "AddTrack", "video") is not True:
                raise RuntimeError("temporary_track_create")
            created_track = 4
        placed_by_ordinal: dict[int, Any] = {}
        temporary: dict[int, Any] = {}
        for ordinal in create_ordinals:
            recipe, style = recipes[ordinal], styles[ordinal]
            source = _build_source(pool, project, names[ordinal], recipe, style)
            created_sources.append(source)
            target = canary._activate_target(project)
            item = _append(pool, project, target, source, recipe, 4 if ordinal in STEP3C_ORDINALS else 3, base_frame)
            created_items.append(item)
            (temporary if ordinal in STEP3C_ORDINALS else placed_by_ordinal)[ordinal] = item
            if ordinal not in STEP3C_ORDINALS:
                original = canary.basic_title_rows(target)[ordinal - 1]["item"]
                if canary.carrier._call(original, "SetClipEnabled", False) is False or canary._clip_enabled(original) is not False:
                    raise RuntimeError(f"original_disable:{ordinal}")

        target = canary._activate_target(project)
        if canary.carrier._call(target, "DeleteClips", [row["item"] for row in old_rows], False) is not True:
            raise RuntimeError("step3c_item_delete")
        old_deleted = True
        for ordinal in sorted(STEP3C_ORDINALS - set(superseded)):
            original = canary.basic_title_rows(target)[ordinal - 1]["item"]
            if canary.carrier._call(original, "SetClipEnabled", True) is False or canary._clip_enabled(original) is not True:
                raise RuntimeError(f"static_original_enable:{ordinal}")
        for ordinal in superseded:
            source = created_sources[create_ordinals.index(ordinal)]
            authoritative = _append(pool, project, target, source, recipes[ordinal], 3, base_frame)
            created_items.append(authoritative)
            placed_by_ordinal[ordinal] = authoritative
        if temporary and canary.carrier._call(target, "DeleteClips", list(temporary.values()), False) is not True:
            raise RuntimeError("temporary_item_delete")
        created_items = list(placed_by_ordinal.values())
        old_sources = [row["inner"] for row in old_rows]
        canary.carrier._call(project, "SetCurrentTimeline", target)
        if canary.carrier._call(pool, "DeleteTimelines", old_sources) is not True:
            raise RuntimeError("step3c_source_delete")
        if created_track is not None:
            if canary._optional(target, "GetItemListInTrack", "video", created_track, default=[]) or []:
                raise RuntimeError("temporary_track_not_empty")
            if canary.carrier._call(target, "DeleteTrack", "video", created_track) is not True:
                raise RuntimeError("temporary_track_delete")

        target = canary._activate_target(project)
        final_nested = _nested_by_name(target)
        if any(STEP3C_PATTERN.match(name) for name in final_nested) or len(final_nested) != manifest["counts"]["expected_final_replacements"]:
            raise RuntimeError("final_nested_inventory")
        final_by_ordinal = {8: final_nested[LEGACY_NAME], **{ordinal: final_nested[name] for ordinal, name in REPRESENTATIVE_NAMES.items()}}
        for name, row in final_nested.items():
            match = re.match(r"^_VC_OSS002_FULL_SUB(\d{3})_", name)
            if match:
                ordinal = int(match.group(1))
                if ordinal in final_by_ordinal:
                    raise RuntimeError(f"duplicate_ordinal:{ordinal}")
                final_by_ordinal[ordinal] = row
        motion_ordinals = {ordinal for ordinal, row in authority.items() if row["motion_detected"]}
        expected_ordinals = {8, *(motion_ordinals - {8})}
        if set(final_by_ordinal) != expected_ordinals:
            raise RuntimeError("final_ordinal_inventory")
        final_captions = canary.basic_title_rows(target)
        for ordinal, row in enumerate(final_captions, 1):
            expected_enabled = ordinal not in expected_ordinals
            if row["enabled"] is not expected_enabled:
                raise RuntimeError(f"final_caption_enabled:{ordinal}")
        final_caption_snapshot = _caption_snapshot(target, base_frame)
        if [(ordinal, start, duration, text) for ordinal, start, duration, _, text in final_caption_snapshot] != [(ordinal, start, duration, text) for ordinal, start, duration, _, text in caption_before]:
            raise RuntimeError("caption_timing_text_changed")
        if _unrelated_snapshot(target) != unrelated_before:
            raise RuntimeError("unrelated_media_changed")
        if int(canary.carrier._call(target, "GetTrackCount", "video") or 0) != 3:
            raise RuntimeError("final_track_count")
        result.update({
            "verification": "PASS",
            "counts": manifest["counts"],
            "replacements_created": len(create_ordinals),
            "representatives_reused": 4,
            "step3c_replacements_removed": 15,
            "overlay_tracks_used": [3],
            "extraction_failures": [row["ordinal"] for row in authority.values() if row["extraction_failure"]],
            "review_samples": manifest["review_samples"],
            "protected_sub008": {"source_name": LEGACY_NAME, "source_uid": LEGACY_UID, "track": 3, "start": 39, "duration": 5},
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
            result["rollback"] = _rollback(project, pool, created_sources, created_items, old_rows, old_deleted, original_states, created_track, base_frame, before_nested)
        return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
