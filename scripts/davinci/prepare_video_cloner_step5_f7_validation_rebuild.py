"""Publish the accepted F7 fresh Resolve validation rebuild command."""
from __future__ import annotations

import copy
import hashlib
import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier

PREPARE = ROOT / ".agent/tasks/inbox/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_20261001_V1/files/prepare.py"
MODULE = "resolve_workspace/modules/video_cloner_step5_f7_validation_rebuild.py"
PLACEMENT_AUTHORITY = ROOT / "config/DcJRJtUKScu.accepted_f7_physical_track_placement.json"


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def projection(objects: list[dict], fields: tuple[str, ...]) -> str:
    return fingerprint([{key: row.get(key) for key in fields} for row in objects])


def apply_placement_authority(contract: dict, authority: dict) -> tuple[dict, dict]:
    source = contract["objects"]
    if len(source) != 65 or contract.get("object_count") != 65:
        raise ValueError("f7_placement_object_count")
    if authority.get("task_id") != "VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_V1" or authority.get("canonical_mapping") != "lane = resolve_track - 1":
        raise ValueError("f7_placement_authority")
    corrected = copy.deepcopy(contract)
    objects = corrected["objects"]
    by_id = {row["source_identity"]: row for row in objects}
    if len(by_id) != 65:
        raise ValueError("f7_placement_identity_count")

    missing_before = 0
    before = {}
    for row in objects:
        placement = row["z_order_track"]
        track = int(placement["resolve_track"])
        lane = track - 1
        if placement.get("lane") is None:
            missing_before += 1
        elif int(placement["lane"]) != lane:
            raise ValueError(f"f7_noncanonical_lane:{row['source_identity']}")
        before[row["source_identity"]] = (track, lane)
        placement["lane"] = lane

    authorized = {}
    for correction in authority.get("corrections", []):
        identity = correction["source_identity"]
        row = by_id.get(identity)
        if row is None or row["text"]["value"] != correction["expected_text"]:
            raise ValueError(f"f7_placement_identity:{identity}")
        expected = correction["before"]
        if before[identity] != (int(expected["resolve_track"]), int(expected["effective_lane"])):
            raise ValueError(f"f7_placement_before:{identity}")
        after = correction["after"]
        track, lane = int(after["resolve_track"]), int(after["lane"])
        if track <= 1 or lane <= 0 or lane != track - 1:
            raise ValueError(f"f7_placement_mapping:{identity}")
        row["z_order_track"].update({"resolve_track": track, "lane": lane})
        authorized[identity] = {"before": list(before[identity]), "after": [track, lane]}

    physical_changes = {
        row["source_identity"]: {
            "before": list(before[row["source_identity"]]),
            "after": [int(row["z_order_track"]["resolve_track"]), int(row["z_order_track"]["lane"])],
        }
        for row in objects
        if before[row["source_identity"]] != (int(row["z_order_track"]["resolve_track"]), int(row["z_order_track"]["lane"]))
    }
    if physical_changes != authorized or len(physical_changes) != 3:
        raise ValueError("f7_placement_change_scope")

    overlaps = []
    tracks = sorted({int(row["z_order_track"]["resolve_track"]) for row in objects})
    for track in tracks:
        rows = sorted((row for row in objects if int(row["z_order_track"]["resolve_track"]) == track), key=lambda row: (row["resolve_interval"][0], row["resolve_interval"][1], row["source_identity"]))
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                if right["resolve_interval"][0] >= left["resolve_interval"][1]:
                    break
                overlaps.append({"track": track, "left": left["source_identity"], "left_interval": left["resolve_interval"], "right": right["source_identity"], "right_interval": right["resolve_interval"]})
    if overlaps:
        raise ValueError(f"f7_placement_overlap:{overlaps}")

    titles = [{
        "caption_id": row["source_identity"], "text": row["text"]["value"],
        "timeline_start": row["resolve_interval"][0],
        "duration": row["resolve_interval"][1] - row["resolve_interval"][0],
        "lane": row["z_order_track"]["lane"],
    } for row in objects]
    plan = carrier.carrier_textplus_operation_plan(titles)
    fields = {
        "text": ("source_identity", "text", "display_text_decision"),
        "lifecycle": ("source_identity", "source_interval", "resolve_interval"),
        "style": ("source_identity", "font", "fill", "opacity", "size", "stroke", "static_rotation", "advanced_effects"),
        "position": ("source_identity", "position"),
        "scale": ("source_identity", "scale_decision", "keyframes"),
        "ownership": ("source_identity", "object_origin", "composition"),
        "renderability": ("source_identity", "renderable"),
    }
    invariant_hashes = {name: {"before": projection(source, keys), "after": projection(objects, keys)} for name, keys in fields.items()}
    if any(value["before"] != value["after"] for value in invariant_hashes.values()):
        raise ValueError("f7_nonplacement_authority_changed")
    target_6000 = next(row for row in objects if row["source_identity"] == "caption_tracklet_0089")
    if target_6000["resolve_interval"] != [542, 596] or len(target_6000["keyframes"]["scale"]) != 9:
        raise ValueError("f7_6000_authority")
    controls = {text: fingerprint([row for row in objects if row["text"]["value"].lower() == text]) for text in ("launch", "invest", "reels")}
    validation = {
        "schema": "video_cloner_f7_placement_validation", "object_count": 65,
        "tracks_scanned": tracks, "canonical_mapping": "lane = resolve_track - 1",
        "normalized_missing_lane_count": missing_before,
        "missing_lane_count": sum(row["z_order_track"].get("lane") is None for row in objects),
        "lane_track_mismatch_count": sum(int(row["z_order_track"]["lane"]) != int(row["z_order_track"]["resolve_track"]) - 1 for row in objects),
        "physical_placement_change_count": len(physical_changes), "physical_placement_changes": physical_changes,
        "unchanged_physical_placement_count": 65 - len(physical_changes),
        "same_track_overlap_count": len(overlaps), "same_track_overlaps": overlaps,
        "carrier_plan": {"result": "PASS", "title_count": len(plan["titles"]), "lanes": plan["lanes"], "sha256": plan["sha256"]},
        "f6_6000_interval": target_6000["resolve_interval"], "f6_6000_scale_key_count": len(target_6000["keyframes"]["scale"]),
        "invariant_hashes": invariant_hashes, "regression_control_hashes": controls, "derived_objects_sha256": fingerprint(objects), "pass": True,
    }
    return corrected, validation


def main() -> int:
    if not PREPARE.is_file():
        raise FileNotFoundError(PREPARE)
    authority = json.loads(PLACEMENT_AUTHORITY.read_text(encoding="utf-8-sig"))
    namespace = runpy.run_path(str(PREPARE))
    entrypoint = namespace["main"]
    entrypoint.__globals__["MODULE"] = MODULE
    original_write = entrypoint.__globals__["write"]

    def write_with_placement(path: Path, value: object) -> None:
        if path.name != "step5_f7_compile_contract.json":
            original_write(path, value)
            return
        corrected, validation = apply_placement_authority(value, authority)
        corrected["f7_placement_authority"] = {
            "path": str(PLACEMENT_AUTHORITY.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(PLACEMENT_AUTHORITY.read_bytes()).hexdigest(),
        }
        original_write(path, corrected)
        original_write(path.with_name("step5_f7_placement_authority.json"), authority)
        original_write(path.with_name("step5_f7_placement_validation.json"), validation)

    entrypoint.__globals__["write"] = write_with_placement
    return int(entrypoint())


if __name__ == "__main__":
    raise SystemExit(main())
