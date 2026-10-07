"""Bounded F8A source/Resolve-layer attribution and isolated Text+ size probe."""
from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import video_cloner_step5_f7_validation_rebuild as f7
from scripts.standalone.video_cloner_media_prep import InputSpec, RuntimeConfig, build_run_context

TASK_ID = "VIDEO_CLONER_STEP5_F8A_ATTRIBUTION_SIZE_DIAGNOSTIC_V1"
MODE = "step5_f8a_attribution_size_diagnostic"
PROJECT = "New Project 1"
TARGET = "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_66203b559cbd"
TARGET_UID = "80d5e22c-355d-47e7-a788-8f7dc68f718c"
PROBE_PREFIX = "VIDEO_CLONER_F8A_DISPOSABLE_"
CASES = (
    ("launch", 55, 69, ("caption_tracklet_0009",)),
    ("selling", 90, 113, ("continuous_visual_identity_0014",)),
    ("before_early", 122, 153, ("caption_tracklet_0022",)),
    ("yard", 140, 175, ("caption_tracklet_0031",)),
    ("before_late", 154, 192, ("caption_tracklet_0037",)),
    ("why", 227, 284, ("recovered_display_object_why_0001",)),
    ("invest_shows", 271, 339, ("caption_tracklet_0045", "caption_tracklet_0051")),
    ("listing", 341, 426, ("recovered_display_object_listing_0003",)),
    ("reels", 348, 435, ("caption_tracklet_0061",)),
    ("social", 370, 462, ("caption_tracklet_0064",)),
    ("not", 396, 495, ("caption_tracklet_0067",)),
    ("6000", 550, 687, ("caption_tracklet_0089",)),
    ("matching_lower", 610, 762, ("caption_tracklet_0094",)),
    ("matching_upper", 626, 783, ("caption_tracklet_0096",)),
    ("launching", 727, 909, ("caption_tracklet_0110",)),
)

SOURCE_BBOXES = {
    ("launch", "caption_tracklet_0009"): [306, 394, 848, 504],
    ("selling", "continuous_visual_identity_0014"): [184, 377, 896, 601],
    ("before_early", "caption_tracklet_0022"): [291, 317, 626, 395],
    ("yard", "caption_tracklet_0031"): [520, 806, 716, 885],
    ("before_late", "caption_tracklet_0037"): [289, 414, 502, 487],
    ("why", "recovered_display_object_why_0001"): [212, 290, 918, 520],
    ("invest_shows", "caption_tracklet_0045"): [369, 708, 735, 854],
    ("invest_shows", "caption_tracklet_0051"): [383, 822, 606, 872],
    ("listing", "recovered_display_object_listing_0003"): [414, 721, 678, 803],
    ("reels", "caption_tracklet_0061"): [429, 750, 653, 814],
    ("social", "caption_tracklet_0064"): [397, 742, 681, 812],
    ("not", "caption_tracklet_0067"): [226, 326, 826, 582],
    ("6000", "caption_tracklet_0089"): [120, 349, 934, 647],
    ("matching_lower", "caption_tracklet_0094"): [167, 396, 917, 570],
    ("matching_upper", "caption_tracklet_0096"): [172, 493, 953, 721],
    ("launching", "caption_tracklet_0110"): [333, 815, 747, 905],
}


def _timecode(start: str, offset: int, fps: int = 24) -> str:
    delimiter = ";" if ";" in start else ":"
    parts = start.replace(";", ":").split(":")
    if len(parts) != 4 or offset < 0:
        raise ValueError(f"timecode:{start}:{offset}")
    hours, minutes, seconds, frame = (int(value) for value in parts)
    total = (((hours * 60 + minutes) * 60 + seconds) * fps + frame + offset)
    frame = total % fps
    total //= fps
    seconds = total % 60
    total //= 60
    minutes = total % 60
    hours = total // 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{delimiter}{frame:02d}"


def _rect(value: Any) -> list[int] | None:
    if isinstance(value, Mapping):
        candidates = (
            tuple(value.get(key, value.get(str(key))) for key in range(1, 5)),
            tuple(value.get(key) for key in ("Left", "Bottom", "Right", "Top")),
            tuple(value.get(key) for key in ("left", "bottom", "right", "top")),
        )
        value = next((row for row in candidates if all(part is not None for part in row)), None)
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [int(round(float(part))) for part in value]
    except (TypeError, ValueError):
        return None


def _output_extent(tool: Any, local_frame: int) -> dict[str, Any]:
    output = carrier._safe(tool, "FindMainOutput", 1, default=None)
    if output is None:
        outputs = carrier._safe(tool, "GetOutputList", default={}) or {}
        values = list(outputs.values()) if isinstance(outputs, Mapping) else list(outputs or [])
        output = values[0] if values else None
    if output is None:
        return {"ok": False, "reason": "main_output_missing"}
    raw = carrier._safe(output, "GetDoD", local_frame, default=None)
    rect = _rect(raw)
    image_metadata: dict[str, Any] = {}
    if rect is None:
        image = carrier._safe(output, "GetValue", local_frame, default=None)
        if image is not None:
            rect = _rect(getattr(image, "DataWindow", None))
            image_metadata = {
                "width": getattr(image, "Width", None),
                "height": getattr(image, "Height", None),
                "original_width": getattr(image, "OriginalWidth", None),
                "original_height": getattr(image, "OriginalHeight", None),
            }
    return {
        "ok": rect is not None,
        "local_frame": local_frame,
        "raw_dod": f7.IMPLEMENTATION.visual.base.json_safe(raw),
        "bbox": rect,
        "width_px": None if rect is None else rect[2] - rect[0],
        "height_px": None if rect is None else rect[3] - rect[1],
        "image": image_metadata,
    }


def _media(item: Any) -> dict[str, Any]:
    media = carrier._safe(item, "GetMediaPoolItem", default=None)
    props = carrier._safe(media, "GetClipProperty", default={}) if media is not None else {}
    return f7.IMPLEMENTATION.visual.base.json_safe(props if isinstance(props, Mapping) else {})


def _source_provenance(source_path: Path, v1_paths: set[str], root: Path = ROOT) -> dict[str, Any]:
    source = source_path.resolve()
    input_spec = InputSpec.from_local(source)
    canonical_proxy = build_run_context(input_spec, RuntimeConfig.load(root, environ={})).proxy_path
    actual_paths = sorted({Path(value).expanduser().resolve() for value in v1_paths})
    actual = actual_paths[0] if len(actual_paths) == 1 else None
    actual_identity = None
    if actual is not None:
        actual_identity = actual.stem[:-6] if actual.stem.endswith("_proxy") else actual.stem
    relation = "AMBIGUOUS_V1_CARRIERS" if len(actual_paths) > 1 else "MISSING_V1_CARRIER"
    if actual is not None and not actual.is_file():
        relation = "OFFLINE_V1_CARRIER"
    elif actual == source:
        relation = "ORIGINAL_SOURCE"
    elif actual == canonical_proxy:
        relation = "CANONICAL_MEDIA_PREP_PROXY"
    identity_match = actual_identity == input_spec.video_id
    carrier_match = actual is not None and actual.is_file() and actual in {source, canonical_proxy}
    return {
        "original_source_path": str(source),
        "original_source_identity": input_spec.video_id,
        "canonical_proxy_path": str(canonical_proxy),
        "actual_v1_media_path": None if actual is None else str(actual),
        "actual_v1_media_name": None if actual is None else actual.name,
        "provenance_relation": relation,
        "identity_match": identity_match,
        "carrier_match": carrier_match,
    }


def _audit(timeline: Any, expected: Mapping[tuple[int, int, int], Mapping[str, Any]]) -> dict[str, Any]:
    tracks = []
    all_items = []
    for track_type in ("video", "subtitle", "audio"):
        count = int(carrier._safe(timeline, "GetTrackCount", track_type, default=0) or 0)
        for index in range(1, count + 1):
            track = {
                "track_type": track_type,
                "track_index": index,
                "name": str(carrier._safe(timeline, "GetTrackName", track_type, index, default="") or ""),
                "enabled": bool(carrier._safe(timeline, "GetIsTrackEnabled", track_type, index, default=True)),
                "items": [],
            }
            for item in list(carrier._safe(timeline, "GetItemListInTrack", track_type, index, default=[]) or []):
                start = int(carrier._safe(item, "GetStart", default=-1))
                end = int(carrier._safe(item, "GetEnd", default=-1))
                fusion_count = int(carrier._safe(item, "GetFusionCompCount", default=0) or 0)
                key = (index, start, end)
                contract_row = expected.get(key) if track_type == "video" else None
                if track_type == "video" and index == 1:
                    classification = "SOURCE_BAKED_TEXT"
                elif contract_row is not None and fusion_count > 0:
                    classification = "TRACKED_F7_TEXTPLUS"
                elif track_type == "subtitle" or carrier._title_text(item) is not None or fusion_count > 0:
                    classification = "OTHER_RESOLVE_TEXT_LAYER"
                else:
                    classification = "NON_TEXT_LAYER"
                row = {
                    "track_type": track_type,
                    "track_index": index,
                    "track_enabled": track["enabled"],
                    "item_name": str(carrier._safe(item, "GetName", default="") or ""),
                    "item_unique_id": carrier._unique_id(item),
                    "start": start,
                    "end": end,
                    "fusion_comp_count": fusion_count,
                    "styled_text": carrier._title_text(item),
                    "media_properties": _media(item),
                    "classification": classification,
                    "source_identity": None if contract_row is None else contract_row["source_identity"],
                }
                track["items"].append(row)
                all_items.append(row)
            tracks.append(track)
    cases = []
    for name, frame, source_frame, identities in CASES:
        active = [row for row in all_items if row["track_enabled"] and row["start"] <= frame < row["end"]]
        text_layers = [row for row in active if row["classification"] != "NON_TEXT_LAYER"]
        cases.append({
            "case": name,
            "timeline_frame": frame,
            "source_frame": source_frame,
            "expected_identities": list(identities),
            "active_text_layers": text_layers,
            "unknown": any(row["classification"] == "OTHER_RESOLVE_TEXT_LAYER" for row in text_layers),
        })
    return {"tracks": tracks, "cases": cases, "unknown_case_count": sum(row["unknown"] for row in cases)}


def _inventory(project: Any) -> list[dict[str, str]]:
    return sorted(
        ({"name": str(carrier._safe(row, "GetName", default="") or ""), "uid": carrier._unique_id(row)} for row in carrier._timelines(project)),
        key=lambda row: (row["name"], row["uid"]),
    )


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "classification": "BLOCKED"}
    project = original = probe = None
    inventory_before: list[dict[str, str]] = []
    target_before: dict[str, Any] = {}
    cleanup: dict[str, Any] = {"project_saved": False}
    report_dir = Path(str(payload.get("report_dir") or ROOT / ".agent/reports" / TASK_ID / run_id)).resolve()
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        if payload.get("target_timeline") != TARGET or payload.get("target_uid") != TARGET_UID:
            raise ValueError("target_authority")
        contract_path = Path(str(payload["contract_path"])).resolve()
        if f7.IMPLEMENTATION.base.sha(contract_path) != payload.get("contract_sha256"):
            raise ValueError("contract_hash")
        source_path = Path(str(payload["source_path"])).resolve()
        if f7.IMPLEMENTATION.base.sha(source_path) != payload.get("source_sha256"):
            raise ValueError("source_hash")
        contract = f7.IMPLEMENTATION.base.read(contract_path)
        if contract.get("object_count") != 65 or contract.get("validation_timeline") != TARGET:
            raise ValueError("contract_scope")
        rows = list(contract["objects"])
        by_id = {row["source_identity"]: row for row in rows}
        if any(identity not in by_id for case in CASES for identity in case[3]):
            raise ValueError("case_identity")
        expected = {(int(row["z_order_track"]["resolve_track"]), *row["resolve_interval"]): row for row in rows}

        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or carrier._safe(project, "GetName", default="") != PROJECT:
            raise ValueError("project_identity")
        matches = [row for row in carrier._timelines(project) if carrier._safe(row, "GetName", default="") == TARGET]
        if len(matches) != 1 or carrier._unique_id(matches[0]) != TARGET_UID:
            raise ValueError("target_identity")
        target = matches[0]
        original = carrier._safe(project, "GetCurrentTimeline", default=None)
        inventory_before = _inventory(project)
        target_before = carrier.timeline_snapshot(target)

        audit = _audit(target, expected)
        v1_paths = {
            str((row.get("media_properties") or {}).get(key) or "")
            for track in audit["tracks"] if track["track_type"] == "video" and track["track_index"] == 1
            for row in track["items"] for key in ("File Path", "FilePath", "Path")
            if (row.get("media_properties") or {}).get(key)
        }
        audit["v1_source_paths"] = sorted(v1_paths)
        audit.update(_source_provenance(source_path, v1_paths))
        audit["v1_source_match"] = audit["identity_match"] and audit["carrier_match"]
        f7.IMPLEMENTATION.base.write(report_dir / "resolve_layer_audit.json", audit)
        if not audit["v1_source_match"]:
            raise ValueError("v1_source_identity")
        if audit["unknown_case_count"]:
            raise ValueError(f"unknown_text_layers:{audit['unknown_case_count']}")

        measurements = []
        for case_name, frame, source_frame, identities in CASES:
            objects = []
            for identity in identities:
                row = by_id[identity]
                track = int(row["z_order_track"]["resolve_track"])
                start, end = row["resolve_interval"]
                items = [
                    item for item in carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or []
                    if int(carrier._safe(item, "GetStart", default=-1)) == start and int(carrier._safe(item, "GetEnd", default=-1)) == end
                ]
                if len(items) != 1:
                    raise ValueError(f"item_identity:{identity}:{len(items)}")
                _comp, tool = f7.IMPLEMENTATION.base.textplus(items[0])
                extent = _output_extent(tool, frame - start)
                source_bbox = SOURCE_BBOXES[(case_name, identity)]
                source_height = float(source_bbox[3] - source_bbox[1])
                generated_height = extent.get("height_px")
                objects.append({
                    "source_identity": identity,
                    "text": row["text"]["value"],
                    "interval": [start, end],
                    "track": track,
                    "size": row["size"]["resolve_value"],
                    "source_bbox": source_bbox,
                    "source_height_px": source_height,
                    "contract_source_height_px": row["size"]["source_height_px"],
                    "font": row["font"],
                    "extent": extent,
                    "generated_to_source_height_ratio": None if generated_height is None else generated_height / source_height,
                })
            measurements.append({"case": case_name, "timeline_frame": frame, "source_frame": source_frame, "objects": objects})
        f7.IMPLEMENTATION.base.write(report_dir / "generated_extent_measurements.json", {"cases": measurements})
        if any(not obj["extent"]["ok"] for case in measurements for obj in case["objects"]):
            raise ValueError("generated_extent_missing")

        probe_name = PROBE_PREFIX + run_id[-12:]
        if any(row["name"] == probe_name for row in inventory_before):
            raise ValueError("probe_preexists")
        probe = carrier._safe(target, "DuplicateTimeline", probe_name, default=None)
        if probe is None or not carrier._safe(project, "SetCurrentTimeline", probe, default=False):
            raise ValueError("probe_create")
        if not carrier._safe(probe, "SetTrackEnable", "video", 1, False, default=False):
            raise ValueError("disable_probe_v1")
        start_frame = int(carrier._safe(probe, "GetStartFrame", default=0) or 0)
        start_tc = str(carrier._safe(probe, "GetStartTimecode", default="") or "")
        stills = []
        still_dir = report_dir / "generated_layer_only"
        still_dir.mkdir(parents=True, exist_ok=True)
        for case_name, frame, source_frame, _identities in CASES:
            requested = _timecode(start_tc, frame - start_frame)
            if not carrier._safe(probe, "SetCurrentTimecode", requested, default=False):
                raise ValueError(f"set_timecode:{case_name}")
            path = still_dir / f"{case_name}_timeline_{frame:04d}_source_{source_frame:04d}.png"
            exported = bool(carrier._safe(project, "ExportCurrentFrameAsStill", str(path), default=False))
            stills.append({"case": case_name, "timeline_frame": frame, "timecode": requested, "path": str(path), "exported": exported})
            if not exported or not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"export_still:{case_name}")
        f7.IMPLEMENTATION.base.write(report_dir / "isolated_generated_stills.json", {"stills": stills})
        result.update({"ok": True, "classification": "F8A_DIAGNOSTIC_CAPTURED", "layer_audit": str(report_dir / "resolve_layer_audit.json"), "measurements": str(report_dir / "generated_extent_measurements.json"), "stills": str(still_dir)})
    except BaseException as exc:
        result["error"] = f7.IMPLEMENTATION.visual.base.compact_exception(exc)
    finally:
        try:
            if project is not None and original is not None:
                cleanup["previous_timeline_restored"] = bool(carrier._safe(project, "SetCurrentTimeline", original, default=False))
            if project is not None and probe is not None:
                pool = carrier._safe(project, "GetMediaPool")
                cleanup["probe_timeline_deleted"] = bool(carrier._safe(pool, "DeleteTimelines", [probe], default=False))
            elif project is not None:
                cleanup["probe_timeline_deleted"] = not any(str(carrier._safe(row, "GetName", default="") or "").startswith(PROBE_PREFIX) for row in carrier._timelines(project))
            if project is not None:
                cleanup["inventory_unchanged"] = _inventory(project) == inventory_before
                target = next((row for row in carrier._timelines(project) if carrier._unique_id(row) == TARGET_UID), None)
                cleanup["target_unchanged"] = target is not None and carrier.timeline_snapshot(target) == target_before
                cleanup["probe_absent"] = not any(str(carrier._safe(row, "GetName", default="") or "").startswith(PROBE_PREFIX) for row in carrier._timelines(project))
        except BaseException as exc:
            cleanup["error"] = f7.IMPLEMENTATION.visual.base.compact_exception(exc)
        cleanup["ok"] = all(cleanup.get(key) is True for key in ("previous_timeline_restored", "probe_timeline_deleted", "inventory_unchanged", "target_unchanged", "probe_absent")) and cleanup["project_saved"] is False
        result["cleanup"] = cleanup
        if not cleanup["ok"]:
            result["ok"] = False
            result["classification"] = "BLOCKED"
        f7.IMPLEMENTATION.base.write(report_dir / "f8a_attribution_size_diagnostic.json", result)
    return result
