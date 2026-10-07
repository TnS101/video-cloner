from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import video_cloner_step4_fresh_reel2_textplus as fresh
from scripts.davinci.resolve_apply_video_cloner_metadata import set_caption_textplus_style_inputs
from scripts.standalone.video_cloner_textplus import prepare_textplus_authority


TASK_ID = "VIDEO_CLONER_STEP4_SUB001_STYLE_PROBE_V1"


def _first_mismatch(style_result: Mapping[str, Any]) -> dict[str, Any] | None:
    for name in ("Font", "Style", "Size", "Center", "Enabled1", "Red1", "Green1", "Blue1", "Alpha1", "Enabled2", "Enabled3", "Enabled4", "Enabled5", "Enabled6", "Enabled7", "Enabled8", "StyledText"):
        row = (style_result.get("inputs") or {}).get(name) or {}
        if not row.get("verified"):
            return {"field": name, "api_input": name, "expected": ((row.get("write") or {}).get("value")), "actual": ((row.get("readback") or {}).get("value")), "detail": row}
    shading = style_result.get("shading_probe") or {}
    for section in ("outline", "shadow"):
        for row in (shading.get(section) or {}).get("attempts") or []:
            if row.get("required", True) and not row.get("ok"):
                return {"field": section, "api_input": row.get("resolved_input_id") or row.get("candidates"), "expected": row.get("value"), "actual": ((row.get("readback") or {}).get("value")), "detail": row}
    return None


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": context.get("run_id"), "save_count": 0, "failures": []}
    project = target = current_before = None
    created = False
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task_id") != TASK_ID or command.get("mode") != "probe" or command.get("run_id") != context.get("run_id"):
            raise ValueError("command_identity")
        paths = {name: Path(str(payload[name])).resolve() for name in ("fcpxml", "generic", "style", "lifecycle", "proxy")}
        for name, path in paths.items():
            if not path.is_file() or fresh._sha256(path) != payload[f"{name}_sha256"]:
                raise ValueError(f"artifact_identity:{name}")

        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or str(carrier._safe(project, "GetName", default="") or "") != payload["expected_project"]:
            raise ValueError("project_identity")
        pool = carrier._safe(project, "GetMediaPool")
        current_before = carrier._safe(project, "GetCurrentTimeline")
        protected_before = carrier._timeline_inventory(project)
        if any(row["name"] == payload["timeline_name"] for row in protected_before):
            raise ValueError("probe_target_exists")

        authority = prepare_textplus_authority(fresh._read(paths["generic"]), fresh._read(paths["style"]), fresh._read(paths["lifecycle"]))
        cue = authority["cues"][0]
        if cue["id"] != "visual_token_sub_001":
            raise ValueError("probe_token_identity")
        raw_style = authority["cue_styles"].get(int(cue["index"])) or authority["style"]
        runtime_style = fresh._style(raw_style)

        carrier._safe(pool, "ImportTimelineFromFile", str(paths["fcpxml"]))
        matches = [row for row in carrier._timelines(project) if str(carrier._safe(row, "GetName", default="") or "") == payload["timeline_name"]]
        if len(matches) != 1:
            raise ValueError("import_target_identity")
        target = matches[0]
        created = True
        fresh._baseline(target)
        if not carrier._safe(project, "SetCurrentTimeline", target, default=False):
            raise ValueError("probe_target_activation")
        if not carrier._safe(target, "AddTrack", "video", default=False):
            raise ValueError("probe_track_creation")

        v1 = list(carrier._safe(target, "GetItemListInTrack", "video", 1, default=[]) or [])
        source = carrier._safe(v1[0], "GetMediaPoolItem") if v1 else None
        props = carrier._safe(source, "GetClipProperty", default={}) if source is not None else {}
        source_path = next((props.get(key) for key in ("File Path", "FilePath", "Path") if isinstance(props, Mapping) and props.get(key)), None)
        if source is None or not fresh._same_path(source_path, paths["proxy"]):
            raise ValueError("probe_carrier_identity")

        provision = carrier.apply_carrier_textplus_v2(project, target, [{"caption_id": cue["id"], "text": cue["text"], "timeline_start": cue["start_frame"], "duration": cue["duration_frames"], "lane": cue["lane"]}], source, {
            "ownership": carrier.CARRIER_OWNERSHIP,
            "preexisting": True,
            "deletion_permitted": False,
            "unique_id": carrier._unique_id(source),
            "source_start": 0,
        })
        if not provision.get("ok") or provision.get("created_count") != 1:
            raise ValueError(f"probe_provision:{provision.get('failures')}")
        item_id = provision["rows"][0]["item_unique_id"]
        item = next((item for item in carrier._safe(target, "GetItemListInTrack", "video", 2, default=[]) or [] if carrier._unique_id(item) == item_id), None)
        if item is None:
            raise ValueError("probe_item_reacquisition")
        comp, tool = fresh._textplus(item)
        args = argparse.Namespace(
            caption_apply_outline=runtime_style["stroke_width"] > 0,
            caption_apply_shadow=runtime_style["shadow_enabled"],
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
        style_result = set_caption_textplus_style_inputs(tool, cue, runtime_style, int(cue["index"]), args=args, comp=comp)
        mismatch = _first_mismatch(style_result)

        if not carrier._safe(pool, "DeleteTimelines", [target], default=False):
            raise ValueError("probe_rollback")
        created = False
        if current_before is not None:
            carrier._safe(project, "SetCurrentTimeline", current_before, default=False)
        protected_after = carrier._timeline_inventory(project)
        if protected_before != protected_after:
            raise ValueError("protected_timeline_delta")

        result.update({
            "ok": True,
            "classification": "STYLE_FIELD_DIVERGENCE_PROVEN" if mismatch else "STYLE_PROBE_PASSED",
            "token": {"id": cue["id"], "text": cue["text"], "window": [cue["start_frame"], cue["end_frame"]]},
            "expected_authority": raw_style,
            "runtime_style_payload": runtime_style,
            "alignment": {"authority": ((raw_style.get("placement") or {}).get("horizontal_align")), "enforced_by_current_writer": False},
            "style_readback": style_result,
            "first_mismatch": mismatch,
            "rollback_deleted_disposable": True,
            "protected_timeline_delta": 0,
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
        if created and project is not None and target is not None:
            result["rollback_deleted_disposable"] = bool(carrier._safe(carrier._safe(project, "GetMediaPool"), "DeleteTimelines", [target], default=False))
            if current_before is not None:
                carrier._safe(project, "SetCurrentTimeline", current_before, default=False)
    return result
