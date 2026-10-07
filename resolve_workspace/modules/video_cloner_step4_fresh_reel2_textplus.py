from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier

_autorun_state = os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN")
os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = "1"
try:
    from resolve_workspace import resolve_apply_caption_animation_step_3C as animation
finally:
    if _autorun_state is None:
        os.environ.pop("VC_DISABLE_WORKSPACE_AUTORUN", None)
    else:
        os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = _autorun_state

from scripts.davinci.resolve_apply_video_cloner_metadata import set_caption_textplus_style_inputs
from scripts.standalone.video_cloner_textplus import prepare_textplus_authority


TASK_ID = "VIDEO_CLONER_STEP4_FRESH_REEL2_TEXTPLUS_V1"
MODE = "apply"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_identity_snapshot(payload: Mapping[str, Any], paths: Mapping[str, Path]) -> list[dict[str, Any]]:
    module_path = Path(__file__).resolve()
    module_sha = _sha256(module_path) if module_path.is_file() else None
    rows = []
    for name, path in paths.items():
        exists = path.is_file()
        observed_sha = _sha256(path) if exists else None
        stat = path.stat() if exists else None
        rows.append({
            "name": name,
            "expected_sha256": payload.get(f"{name}_sha256"),
            "runtime_path": str(path),
            "is_file": exists,
            "observed_sha256": observed_sha,
            "size": stat.st_size if stat else None,
            "mtime_ns": stat.st_mtime_ns if stat else None,
            "loaded_module_file": str(module_path),
            "loaded_module_sha256": module_sha,
        })
    return rows


def _same_path(left: Any, right: Path) -> bool:
    try:
        return Path(str(left)).resolve() == right.resolve()
    except (OSError, TypeError, ValueError):
        return False


def _style(raw: Mapping[str, Any]) -> dict[str, Any]:
    anchor = raw.get("anchor") if isinstance(raw.get("anchor"), Mapping) else {}
    bold, italic = bool(raw.get("bold")), bool(raw.get("italic"))
    face = "Bold Italic" if bold and italic else "Bold" if bold else "Italic" if italic else "Regular"
    return {
        "font_family": str(raw.get("font_name") or "Arial"),
        "font_style": face,
        "font_size_px": float(raw.get("font_size_px") or 68),
        "textplus_size": float(raw["textplus_size"]),
        "text_color": str(raw.get("fill") or "#ffffff"),
        "stroke_color": str(raw.get("outline") or "#000000"),
        "stroke_width": float(raw.get("outline_px") or 0),
        "shadow_enabled": bool(raw.get("shadow")) and float(raw.get("shadow_opacity") or 0) > 0,
        "shadow_color": str(raw.get("shadow") or "#000000"),
        "shadow_opacity": float(raw.get("shadow_opacity") or 0),
        "center": [float(anchor.get("x", 0.5)), 1.0 - float(anchor.get("y", 0.5))],
        "case_style": "preserve",
        "style_event_id": raw.get("matched_style_event_id"),
        "style_profile_id": raw.get("profile_id"),
    }


def _textplus(item: Any) -> tuple[Any, Any]:
    comp = carrier._safe(item, "GetFusionCompByIndex", 1)
    tools = carrier._safe(comp, "GetToolList", False, "TextPlus", default={}) if comp is not None else {}
    if not isinstance(tools, Mapping):
        tools = carrier._safe(comp, "GetToolList", default={}) if comp is not None else {}
    found = [tool for tool in tools.values() if carrier._tool_regid(tool) == "TextPlus"] if isinstance(tools, Mapping) else []
    if comp is None or len(found) != 1:
        raise ValueError("textplus_identity")
    return comp, found[0]


def _animation_result_matches_authority(result: Mapping[str, Any], payload: object) -> bool:
    return result.get("ok") is True and bool(result.get("selected")) == bool(payload)


def _representative_overlap(lifecycle: Mapping[str, Any]) -> dict[str, Any]:
    layer_ids = lifecycle.get("visual_overlap_pairs")
    if isinstance(layer_ids, list) and len(layer_ids) == 1 and isinstance(layer_ids[0], list):
        layer_ids = layer_ids[0]
    if not isinstance(layer_ids, list) or len(layer_ids) != 2 or not all(isinstance(value, str) and value.startswith("caption_layer_") for value in layer_ids):
        raise ValueError("visual_overlap_pair_contract")
    semantic_ids = [value[len("caption_layer_"):] for value in layer_ids]
    matches = []
    for composition in lifecycle.get("visual_compositions") or []:
        tokens = composition.get("tokens") if isinstance(composition, Mapping) else None
        covered = {str(value) for token in tokens or [] if isinstance(token, Mapping) for value in token.get("semantic_ids") or []}
        if (composition.get("relation") or {}).get("mode") == "simultaneous" and set(semantic_ids) <= covered:
            matches.append(composition)
    if len(matches) != 1:
        raise ValueError(f"visual_overlap_composition_contract:{len(matches)}")
    composition = matches[0]
    tokens = [token for semantic_id in semantic_ids for token in composition["tokens"] if semantic_id in token["semantic_ids"]]
    if len(tokens) != 2:
        raise ValueError("visual_overlap_token_contract")
    return {
        "composition_id": composition["composition_id"],
        "mode": "simultaneous",
        "window": composition["window"],
        "tokens": [{"token_id": token["token_id"], "semantic_ids": token["semantic_ids"], "window": token["window"]} for token in tokens],
    }


def _baseline(timeline: Any) -> dict[str, Any]:
    snapshot = carrier.timeline_snapshot(timeline)
    v1 = list(carrier._safe(timeline, "GetItemListInTrack", "video", 1, default=[]) or [])
    a1 = list(carrier._safe(timeline, "GetItemListInTrack", "audio", 1, default=[]) or [])
    upper = [row for row in snapshot["items"] if row["track_type"] == "video" and row["track_index"] > 1]
    duration = int(snapshot["end_frame"] or 0) - int(snapshot["start_frame"] or 0)
    result = {"video_clip_count": len(v1), "audio_clip_count": len(a1), "duration_frames": duration, "caption_title_count": len(upper)}
    if result != {"video_clip_count": 14, "audio_clip_count": 1, "duration_frames": 854, "caption_title_count": 0}:
        raise ValueError(f"baseline_contract:{result}")
    return result


def _inventory_key(row: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return row.get("name"), row.get("unique_id"), row.get("signature")


def _timeline_identity_rows(timelines: list[Any]) -> list[dict[str, Any]]:
    return [{
        "index": index,
        "name": str(carrier._safe(timeline, "GetName", default="") or ""),
        "unique_id": carrier._unique_id(timeline) or None,
        "timeline": timeline,
    } for index, timeline in enumerate(timelines, 1)]


def _inventory_delta(before: list[Mapping[str, Any]], after: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in after if not any(carrier._same_timeline(row["timeline"], old["timeline"]) for old in before)]


def _select_owned_timeline(returned: Any, delta: list[Mapping[str, Any]]) -> tuple[Any, str]:
    if returned is not None and returned is not True and returned is not False:
        matches = [row for row in delta if carrier._same_timeline(returned, row["timeline"])]
        if len(matches) == 1:
            return matches[0]["timeline"], "direct_return"
    if len(delta) == 1:
        return delta[0]["timeline"], "inventory_delta"
    return None, "none" if not delta else "ambiguous"


def _textplus_provision_matches_titles(provision: Mapping[str, Any], titles: list[Mapping[str, Any]]) -> bool:
    rows = provision.get("rows")
    return (
        provision.get("ok") is True
        and provision.get("created_count") == len(titles)
        and isinstance(rows, list)
        and len(rows) == len(titles)
        and provision.get("failures") == []
    )


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": context.get("run_id"), "save_count": 0, "failures": []}
    target = manager = project = None
    created = saved = False
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != context.get("run_id"):
            raise ValueError("command_identity")
        if payload.get("create_new") is not True or payload.get("save_once") is not True or payload.get("delete_existing") is not False:
            raise ValueError("mutation_authority")

        root = Path(str(payload["repository_root"])).resolve()
        paths = {name: Path(str(payload[name])).resolve() for name in ("fcpxml", "generic", "style", "lifecycle", "proxy")}
        identity_rows = _artifact_identity_snapshot(payload, paths)
        for name, path in paths.items():
            row = next(item for item in identity_rows if item["name"] == name)
            if not row["is_file"] or row["observed_sha256"] != row["expected_sha256"]:
                result["artifact_identity_diagnostics"] = identity_rows
                result["artifact_identity_failure"] = row
                raise ValueError(f"artifact_identity:{name}")

        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or str(carrier._safe(project, "GetName", default="") or "") != payload["expected_project"]:
            raise ValueError("project_identity")
        pool = carrier._safe(project, "GetMediaPool")
        before_timelines = carrier._timelines(project)
        before_identity = _timeline_identity_rows(before_timelines)
        before = [carrier.timeline_snapshot(row) for row in before_timelines]
        before_current = carrier._safe(project, "GetCurrentTimeline")
        result["import_pre_count"] = len(before_identity)
        result["import_pre_inventory"] = [{key: row[key] for key in ("index", "name", "unique_id")} for row in before_identity]
        result["import_previous_current"] = next((
            {key: row[key] for key in ("index", "name", "unique_id")}
            for row in before_identity if carrier._same_timeline(row["timeline"], before_current)
        ), None)
        if any(row["name"] == payload["timeline_name"] for row in before):
            raise ValueError("target_name_exists")

        authority = prepare_textplus_authority(_read(paths["generic"]), _read(paths["style"]), _read(paths["lifecycle"]))
        cues = list(authority["cues"])
        lifecycle = _read(paths["lifecycle"])
        compositions = {str(row["composition_id"]): row for row in lifecycle["visual_compositions"]}
        accepted_motion = [cue for cue in cues if cue.get("animation_authority") and (compositions.get(str(cue.get("visual_composition_id"))) or {}).get("authority", {}).get("reason") == "source_video_dense_template_track"]
        if len(cues) != 92 or len(compositions) != 91 or int(lifecycle["summary"]["unresolved_visual_composition_count"]) != 0 or len(accepted_motion) != 1:
            raise ValueError("caption_authority_contract")
        motion_cue = accepted_motion[0]
        keyframes = motion_cue["animation_authority"]["keyframes"]
        if motion_cue["duration_frames"] != 24 or [row["frame"] for row in keyframes] != [0, 23] or abs(float(keyframes[0]["value"]) - 0.080528214) > 1e-12 or abs(float(keyframes[1]["value"]) - 0.10833333333333332) > 1e-12:
            raise ValueError("motion_authority_contract")

        try:
            returned = pool.ImportTimelineFromFile(str(paths["fcpxml"]))
        except Exception as exc:
            result["import_exception"] = {"type": type(exc).__name__, "message": str(exc)}
            raise ValueError("import_timeline_exception") from exc
        result["import_exception"] = None
        result["import_return_type"] = type(returned).__name__
        result["import_return_truthy"] = bool(returned)
        result["import_return_name"] = str(carrier._safe(returned, "GetName", default="") or "") if returned is not None else None
        result["import_return_uid"] = carrier._unique_id(returned) or None if returned is not None else None

        after_identity = _timeline_identity_rows(carrier._timelines(project))
        delta = _inventory_delta(before_identity, after_identity)
        result["import_post_count"] = len(after_identity)
        result["import_post_inventory"] = [{key: row[key] for key in ("index", "name", "unique_id")} for row in after_identity]
        result["import_inventory_delta"] = [{key: row[key] for key in ("index", "name", "unique_id")} for row in delta]
        target, ownership = _select_owned_timeline(returned, delta)
        result["import_ownership"] = ownership
        if target is None:
            raise ValueError(f"import_ownership:{ownership}")
        created = True
        result["owned_timeline"] = {
            "name": str(carrier._safe(target, "GetName", default="") or ""),
            "unique_id": carrier._unique_id(target) or None,
        }
        result["actual_name_match"] = result["owned_timeline"]["name"] == payload["timeline_name"]
        if not result["actual_name_match"]:
            raise ValueError("import_target_identity")
        baseline = _baseline(target)
        if not carrier._safe(project, "SetCurrentTimeline", target, default=False):
            raise ValueError("target_activation")
        while int(carrier._safe(target, "GetTrackCount", "video", default=0) or 0) < 3:
            if not carrier._safe(target, "AddTrack", "video", default=False):
                raise ValueError("caption_track_creation")
        if int(carrier._safe(target, "GetTrackCount", "video", default=0) or 0) != 3:
            raise ValueError("caption_track_contract")

        v1 = list(carrier._safe(target, "GetItemListInTrack", "video", 1, default=[]) or [])
        source = carrier._safe(v1[0], "GetMediaPoolItem") if v1 else None
        props = carrier._safe(source, "GetClipProperty", default={}) if source is not None else {}
        source_path = next((props.get(key) for key in ("File Path", "FilePath", "Path") if isinstance(props, Mapping) and props.get(key)), None)
        if source is None or not _same_path(source_path, paths["proxy"]):
            raise ValueError("carrier_source_identity")

        titles = [{"caption_id": cue["id"], "text": cue["text"], "timeline_start": cue["start_frame"], "duration": cue["duration_frames"], "lane": cue["lane"]} for cue in cues]
        provision = carrier.apply_carrier_textplus_v2(project, target, titles, source, {
            "ownership": carrier.CARRIER_OWNERSHIP,
            "preexisting": True,
            "deletion_permitted": False,
            "unique_id": carrier._unique_id(source),
            "source_start": 0,
        })
        if not _textplus_provision_matches_titles(provision, titles):
            raise ValueError(
                "textplus_provision:"
                f"ok={provision.get('ok')!r},"
                f"created_count={provision.get('created_count')!r},"
                f"rows={len(provision.get('rows')) if isinstance(provision.get('rows'), list) else None},"
                f"requested={len(titles)},failures={provision.get('failures')!r}"
            )

        items = {carrier._unique_id(item): item for track in (2, 3) for item in (carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or [])}
        rows = {row["caption_id"]: row for row in provision["rows"]}
        style_results, animation_results = [], []
        for cue in cues:
            item = items.get(rows[cue["id"]]["item_unique_id"])
            if item is None:
                raise ValueError("provisioned_item_reacquisition")
            comp, tool = _textplus(item)
            raw_style = authority["cue_styles"].get(int(cue["index"])) or authority["style"]
            style = _style(raw_style)
            args = argparse.Namespace(
                caption_apply_outline=style["stroke_width"] > 0,
                caption_apply_shadow=style["shadow_enabled"],
                caption_shading_probe_only=False,
                caption_outline_element=2,
                caption_shadow_element=3,
                caption_outline_width_scale=1.0,
                caption_outline_thickness=None,
                caption_shadow_opacity=None,
                caption_shadow_offset_x=0.003,
                caption_shadow_offset_y=0.003,
                caption_shadow_softness=None,
            )
            styled = set_caption_textplus_style_inputs(tool, cue, style, int(cue["index"]), args=args, comp=comp)
            if not styled.get("applied"):
                raise ValueError(f"style_readback:{cue['id']}")
            style_results.append({"caption_id": cue["id"], "item_unique_id": carrier._unique_id(item), "style": styled})
            payload_for_cue = cue["animation_authority"] if cue is motion_cue else None
            applied = animation.apply_authorized_animation(comp, tool, payload_for_cue, int(cue["duration_frames"]))
            if not _animation_result_matches_authority(applied, payload_for_cue):
                raise ValueError(f"animation_application:{cue['id']}")
            animation_results.append({"caption_id": cue["id"], "item_unique_id": carrier._unique_id(item), "result": applied})

        pre_save = carrier.timeline_snapshot(target)
        textplus_count = 0
        basic_title_count = 0
        for track in (2, 3):
            for item in carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or []:
                try:
                    _textplus(item)
                    textplus_count += 1
                except ValueError:
                    if carrier._title_text(item):
                        basic_title_count += 1
        if textplus_count != 92 or basic_title_count != 0:
            raise ValueError("caption_object_contract")

        after_before_save = carrier._timeline_inventory(project)
        protected_before = Counter(_inventory_key(row) for row in before)
        protected_after = Counter(_inventory_key(row) for row in after_before_save if row["unique_id"] != pre_save["unique_id"])
        if protected_before != protected_after:
            raise ValueError("protected_timeline_mutation")

        if carrier._safe(manager, "SaveProject", default=False) is False:
            raise ValueError("save_project")
        result["save_count"] = 1
        saved = True

        project = carrier._safe(manager, "GetCurrentProject")
        reacquired = [row for row in carrier._timelines(project) if carrier._unique_id(row) == pre_save["unique_id"]]
        if len(reacquired) != 1:
            raise ValueError("post_save_timeline_reacquisition")
        target = reacquired[0]
        if not carrier._safe(project, "SetCurrentTimeline", target, default=False):
            raise ValueError("post_save_target_activation")
        post_save = carrier.timeline_snapshot(target)
        if post_save["signature"] != pre_save["signature"]:
            raise ValueError("post_save_timeline_readback")

        motion_row = next(row for row in animation_results if row["caption_id"] == motion_cue["id"])
        overlap = _representative_overlap(lifecycle)
        multiword = next(cue for cue in cues if len(cue.get("source_cue_ids") or []) > 1)
        result.update({
            "ok": True,
            "classification": "FRESH_REEL2_TEXTPLUS_PERSISTED",
            "project_name": payload["expected_project"],
            "timeline_name": post_save["name"],
            "timeline_unique_id": post_save["unique_id"],
            "baseline": baseline,
            "caption_counts": {"tokens": len(cues), "compositions": len(compositions), "textplus": textplus_count, "basic_titles": basic_title_count},
            "motion": {"caption_id": motion_cue["id"], "item_unique_id": motion_row["item_unique_id"], "window": [motion_cue["start_frame"], motion_cue["end_frame"]], "static_base_size": float((authority["cue_styles"].get(int(motion_cue["index"])) or authority["style"])["textplus_size"]), "keyframes": keyframes, "authorized_count": 1, "applied_count": sum(bool(row["result"].get("selected")) for row in animation_results), "unauthorized_applied_count": sum(bool(row["result"].get("selected")) for row in animation_results if row["caption_id"] != motion_cue["id"]), "readback": motion_row["result"]},
            "representative": {"multiword": {"caption_id": multiword["id"], "text": multiword["text"], "semantic_ids": multiword["source_cue_ids"]}, "overlap": overlap, "styled": style_results[0]},
            "reacquired": True,
            "current_timeline_is_target": carrier._same_timeline(carrier._safe(project, "GetCurrentTimeline"), target),
            "protected_timeline_delta": 0,
            "unrelated_mutations": [],
            "timeline_snapshot": post_save,
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
        if created and not saved and project is not None and target is not None:
            pool = carrier._safe(project, "GetMediaPool")
            deleted = bool(carrier._safe(pool, "DeleteTimelines", [target], default=False))
            restored = bool(carrier._safe(project, "SetCurrentTimeline", before_current, default=False)) if before_current is not None else None
            result["rollback_deleted_new_target"] = deleted
            result["rollback"] = {"attempted": True, "deleted_owned_timeline": deleted, "restored_previous_current": restored}
        else:
            result["rollback"] = {"attempted": False, "reason": "saved" if saved else "ownership_not_proven"}
    return result
