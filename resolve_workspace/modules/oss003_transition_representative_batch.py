"""Apply three source-backed blur handoffs to the existing Reel #3 V1 clips."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canary = _load("vc_oss003_canary", HERE / "oss002_sub008_production_canary.py")
rep = _load("vc_oss003_rep", HERE / "oss002_oss_animation_representative_batch.py")
full = _load("vc_oss003_full", HERE / "oss002_full_caption_motion_rollout.py")
fusion = _load("vc_oss003_fusion", HERE / "advanced_transition_flash_application_v1.py")
policy = _load("vc_oss003_policy", HERE.parents[1] / "video_cloner" / "transition_policy.py")

TASK_ID = "OSS003_TRANSITION_REPRESENTATIVE_BATCH_V1"
MODE = "oss003_transition_representative_batch"
EXPECTED_V1 = ((0, 80), (80, 131), (211, 75), (286, 90), (376, 85), (461, 97), (558, 71), (629, 44))
EXPECTED_NESTED = 69
COMP_PREFIX = "VC_OSS003_BLUR_"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_file(root: Path, relative: Any, expected: Any) -> Path:
    path = (root / str(relative or "")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("authority_path") from exc
    if not path.is_file() or _sha256(path) != str(expected or ""):
        raise ValueError("authority_hash")
    return path


def _v1_rows(timeline: Any) -> list[dict[str, Any]]:
    rows = []
    for item in canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []:
        rows.append({"item": item, "start": canary._item_start(item), "duration": canary._item_duration(item)})
    return sorted(rows, key=lambda row: (row["start"], row["duration"]))


def _v1_contract(timeline: Any, base: int) -> list[dict[str, Any]]:
    rows = _v1_rows(timeline)
    actual = tuple((row["start"] - base, row["duration"]) for row in rows)
    if actual != EXPECTED_V1:
        raise ValueError(f"v1_contract:{actual!r}")
    return rows


def _owned_names(item: Any) -> list[str]:
    return [str(name) for name in (canary._optional(item, "GetFusionCompNameList", default=[]) or []) if str(name).startswith(COMP_PREFIX)]


def build_clip_plan(recipes: list[Mapping[str, Any]], v1_durations: tuple[int, ...] = tuple(row[1] for row in EXPECTED_V1)) -> dict[int, list[tuple[int, float]]]:
    plan: dict[int, list[tuple[int, float]]] = {}
    for row in recipes:
        left, right = int(row["from_shot"]) - 1, int(row["to_shot"]) - 1
        amount = round(0.005 + 0.015 * float(row["intensity"]), 6)
        plan.setdefault(left, []).extend([(v1_durations[left] - int(row["outgoing_frames"]), 0.0), (v1_durations[left] - 1, amount)])
        plan.setdefault(right, []).extend([(0, amount), (int(row["incoming_frames"]) - 1, 0.0)])
    return {index: sorted(set(keys)) for index, keys in sorted(plan.items())}


def _apply_comp(item: Any, keys: list[tuple[int, float]], name: str, owned: dict[str, Any]) -> dict[str, Any]:
    before = list(canary._optional(item, "GetFusionCompNameList", default=[]) or [])
    comp = canary._optional(item, "AddFusionComp", default=None)
    after = list(canary._optional(item, "GetFusionCompNameList", default=[]) or [])
    created = [str(value) for value in after if value not in before]
    if len(created) == 1:
        owned.update({"item": item, "name": created[0]})
    if comp is None or len(created) != 1:
        raise RuntimeError("fusion_comp_create")
    current = created[0]
    if canary._optional(item, "RenameFusionCompByName", current, name, default=False) is not True:
        raise RuntimeError("fusion_comp_rename")
    owned["name"] = name
    media_in, media_out = fusion.find_tool(comp, "MediaIn"), fusion.find_tool(comp, "MediaOut")
    blur = canary._optional(comp, "AddTool", "Blur", -32768, -32768, default=None)
    if media_in is None or media_out is None or blur is None or not fusion.set_tool_name(blur, f"{name}_TOOL"):
        raise RuntimeError("blur_graph")
    if not fusion.connect_tool(media_in, blur).get("ok") or not fusion.connect_tool(blur, media_out).get("ok"):
        raise RuntimeError("blur_connect")
    for input_name in ("XBlurSize", "YBlurSize"):
        if not fusion.ensure_bezier_modifier(comp, blur, input_name).get("ok"):
            raise RuntimeError(f"blur_modifier:{input_name}")
        for frame, value in keys:
            if not fusion.write_animated_scalar(blur, input_name, frame, value).get("ok"):
                raise RuntimeError(f"blur_key:{input_name}:{frame}")
    readback = {
        input_name: [(frame, fusion.read_input(blur, input_name, frame).get("value")) for frame, _ in keys]
        for input_name in ("XBlurSize", "YBlurSize")
    }
    if any(not fusion.numeric_close(actual, expected) for values in readback.values() for (frame, actual), (_, expected) in zip(values, keys)):
        raise RuntimeError("blur_readback")
    return {"owned": owned, "comp_name": name, "keys": keys, "readback": readback}


def _rollback(project: Any, created: list[dict[str, Any]]) -> dict[str, Any]:
    target = canary._activate_target(project)
    deleted = 0
    for row in reversed(created):
        if canary._optional(row["item"], "DeleteFusionCompByName", row["name"], default=False) is True:
            deleted += 1
    remaining = sum(len(_owned_names(row["item"])) for row in _v1_rows(target))
    return {"attempted": len(created), "deleted": deleted, "remaining_owned": remaining, "ok": deleted == len(created) and remaining == 0}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_count": 0, "failures": []}
    project = None
    created: list[dict[str, Any]] = []
    before: dict[str, Any] = {}
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT, "target_timeline": rep.EXPECTED_TIMELINE,
            "target_timeline_uid": rep.EXPECTED_TIMELINE_UID, "expected_video_track_count": 3,
            "expected_caption_count": 112, "expected_nested_count": EXPECTED_NESTED,
            "expected_boundaries": [80, 286, 376], "save_after_verification": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(k) != v for k, v in required.items()):
            raise ValueError("command_authority")
        result["resolve_version"] = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError("resolve_version")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        authority = json.loads(_repo_file(root, payload.get("transition_authority_path"), payload.get("transition_authority_sha256")).read_text(encoding="utf-8-sig"))
        if _sha256(Path(__file__).resolve()) != payload.get("module_sha256"):
            raise ValueError("module_hash")
        recipes = policy.normalize_oss003_recipes(authority)["recipes"]
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        target = canary._activate_target(project)
        if canary._timeline_identity(target)["unique_id"] != rep.EXPECTED_TIMELINE_UID:
            raise ValueError("timeline_uid")
        if int(canary.carrier._call(target, "GetTrackCount", "video") or 0) != 3:
            raise ValueError("video_track_count")
        base = int(canary.carrier._call(target, "GetStartFrame") or 0)
        v1 = _v1_contract(target, base)
        captions = canary.basic_title_rows(target)
        nested = rep._stable_nested(target, base)
        if len(captions) != 112 or len(nested) != EXPECTED_NESTED:
            raise ValueError("caption_baseline")
        if any(_owned_names(row["item"]) for row in v1):
            raise ValueError("owned_transition_collision")
        clip_plan = build_clip_plan(recipes)
        if any(int(canary._optional(v1[index]["item"], "GetFusionCompCount", default=0) or 0) != 0 for index in clip_plan):
            raise ValueError("target_clip_fusion_collision")
        before = {"v1": full._unrelated_snapshot(target), "captions": rep._caption_snapshot(captions, base), "nested": nested, "tracks": 3}
        token = run_id.rsplit("_", 1)[-1][:12]
        for index, keys in clip_plan.items():
            name = f"{COMP_PREFIX}SHOT_{index + 1:03d}_{token}"
            row = {"item": v1[index]["item"], "name": ""}
            created.append(row)
            applied = _apply_comp(row["item"], keys, name, row)
            row["name"] = applied["comp_name"]
            row["evidence"] = applied
        target = canary._activate_target(project)
        after = {
            "v1": full._unrelated_snapshot(target), "captions": rep._caption_snapshot(canary.basic_title_rows(target), base),
            "nested": rep._stable_nested(target, base), "tracks": int(canary.carrier._call(target, "GetTrackCount", "video") or 0),
        }
        if before != after or sum(len(_owned_names(row["item"])) for row in _v1_rows(target)) != 5:
            raise RuntimeError("post_apply_safety_verification")
        saved = canary.carrier._call(project, "SaveProject")
        result["save_project_count"] = 1
        result["save_project_return"] = saved
        if saved is not True:
            raise RuntimeError("save_project")
        result.update({"ok": True, "verification": "PASS", "boundaries": [80, 286, 376], "owned_comp_count": 5, "mutated_shots": [1, 2, 3, 4, 5], "applications": [row["evidence"] for row in created]})
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if project is not None and created and result.get("save_project_return") is not True:
            result["rollback"] = _rollback(project, created)
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
