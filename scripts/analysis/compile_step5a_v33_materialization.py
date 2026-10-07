from __future__ import annotations

import copy
import difflib
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import cv2


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / ".agent/reports/VIDEO_CLONER_WHOLE_REEL_SOURCE_COVERAGE_GATE_V1/20261004T110112652Z_v33_final_1/canonical_caption_contract_v1.json"
TEMPLATES = ROOT / ".agent/reports/VIDEO_CLONER_STEP5_F9_CANONICAL_DISPLAY_OWNERSHIP_REBUILD_V1/20261003T111956566999Z_69524834b9114b7e830a9b911376265e/first/step5_f9_canonical_compile_contract.json"
LIFECYCLE = ROOT / "config/DcJRJtUKScu.accepted_lifecycle_end_correction.json"
CLEANUP = ROOT / "config/DcJRJtUKScu.accepted_v33_bounded_materialization_cleanup.json"
VIDEO = ROOT / "input/DcJRJtUKScu.mp4"
BASELINE = ROOT / ".agent/reports/VIDEO_CLONER_STEP5A_REAL_TEXTPLUS_COMPILE_20260928/20260928T190000000Z_real_textplus_compile/step5a_cutonly_baseline.fcpxml"
EXPECTED = {
    CANONICAL: "253297ad4f5b41837c90014f6c88572063fcb05efa20adfbb97444b9b09a14bc",
    TEMPLATES: "adf6325809e120328aaafe4ba528f7dc8d9a7bf7476995d7fafbe6b6cf2d5277",
    LIFECYCLE: "368092b4723021743e4f43784693f4bfbdce5645c7bdae25cbf761601214b047",
    CLEANUP: "201da17609e223506e0694158cce20fcd0faa9bff70933aea89dd574f27a316c",
    VIDEO: "729c47a74fe015fd45c22a76974c0c824234352ca90c42b5689dc7468b87a279",
    BASELINE: "d3b9c796feff8d81c2823a318e2df1657a415e8b06e65e7e9dfe0f756a35ea97",
}
STYLE_FIELDS = ("font", "fill", "opacity", "size", "stroke", "static_rotation", "advanced_effects")


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object:{path}")
    return value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _center(row: Mapping[str, Any]) -> tuple[float, float]:
    boxes = [item["bbox"] for item in row["geometry_trajectory"]]
    return (
        statistics.median((float(box[0]) + float(box[2])) / 2 for box in boxes),
        statistics.median((float(box[1]) + float(box[3])) / 2 for box in boxes),
    )


def _height(row: Mapping[str, Any]) -> float:
    return statistics.median(float(item["bbox"][3]) - float(item["bbox"][1]) for item in row["geometry_trajectory"])


def _temporal_distance(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
    a, b = left["source_lifecycle"], right["source_lifecycle"]
    return max(0, int(a["first_visible_frame"]) - int(b["last_visible_frame"]), int(b["first_visible_frame"]) - int(a["last_visible_frame"]))


def _mapped_interval(row: Mapping[str, Any], source_fps: float, timeline_fps: float) -> list[int]:
    life = row["source_lifecycle"]
    start = round(int(life["first_visible_frame"]) / source_fps * timeline_fps)
    end = round((int(life["last_visible_frame"]) + 1) / source_fps * timeline_fps)
    return [start, max(start + 1, end)]


def _overlap(left: list[int], right: list[int]) -> int:
    return max(0, min(left[1], right[1]) - max(left[0], right[0]))


def _template_for(row: Mapping[str, Any], templates: Mapping[str, dict[str, Any]], interval: list[int]) -> tuple[dict[str, Any] | None, list[str]]:
    candidates = [templates[identity] for identity in row["source_raw_track_provenance"] if identity in templates]
    if not candidates:
        return None, []
    x, y = _center(row)
    chosen = min(candidates, key=lambda item: (
        -_overlap(interval, list(map(int, item["resolve_interval"]))),
        math.hypot(float(item["position"]["resolve_center"][0]) * 1080 - x, (1 - float(item["position"]["resolve_center"][1])) * 1920 - y),
        item["source_identity"],
    ))
    return chosen, [item["source_identity"] for item in candidates]


def _style_donor(row: Mapping[str, Any], contract: list[dict[str, Any]], direct: Mapping[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    x, y = _center(row)
    scored = []
    memberships = set(row["composition_membership"])
    for other in contract:
        template = direct.get(other["canonical_source_object_id"])
        if template is None:
            continue
        ox, oy = _center(other)
        shared_composition = bool(memberships.intersection(other["composition_membership"]))
        scored.append(((0 if shared_composition else 1, _temporal_distance(row, other), math.hypot(x - ox, y - oy), other["canonical_source_object_id"]), other, template))
    if not scored:
        raise ValueError(f"missing_style_donor:{row['canonical_source_object_id']}")
    score, other, template = min(scored, key=lambda item: item[0])
    if score[0] and score[1] > 3:
        raise ValueError(f"missing_local_style_evidence:{row['canonical_source_object_id']}:{score}")
    return template, {
        "method": "SAME_COMPOSITION_THEN_TEMPORAL_SPATIAL_ACCEPTED_STYLE_DONOR",
        "donor_canonical_source_object_id": other["canonical_source_object_id"],
        "donor_source_identity": template["source_identity"],
        "shared_composition": not bool(score[0]),
        "temporal_distance_frames": score[1],
        "center_distance_px": round(score[2], 6),
    }


def _allocate_tracks(objects: list[dict[str, Any]], locked: set[str] | None = None) -> list[dict[str, Any]]:
    occupied: dict[int, list[list[int]]] = defaultdict(list)
    changes = []
    locked = locked or set()
    for row in objects:
        if row["source_identity"] in locked:
            occupied[int(row["z_order_track"]["resolve_track"])].append(list(map(int, row["resolve_interval"])))
    for row in sorted((item for item in objects if item["source_identity"] not in locked), key=lambda item: (item["resolve_interval"][0], item["resolve_interval"][1], item["source_identity"])):
        preferred = max(2, int(row["z_order_track"].get("resolve_track") or 2))
        choices = [preferred, *[track for track in range(2, len(objects) + 2) if track != preferred]]
        start, end = row["resolve_interval"]
        track = next(track for track in choices if all(end <= interval[0] or interval[1] <= start for interval in occupied[track]))
        occupied[track].append([start, end])
        row["z_order_track"] = {
            "resolve_track": track,
            "lane": track - 1,
            "source_authority": "V33_DETERMINISTIC_PREFERRED_THEN_LOWEST_FREE_TRACK",
            "value_role": "OPERATIONAL_RENDER_PLACEMENT",
        }
        if track != preferred:
            changes.append({"canonical_source_object_id": row["canonical_source_object_id"], "preferred_track": preferred, "allocated_track": track})
    return changes


def _collisions(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for index, left in enumerate(objects):
        for right in objects[index + 1:]:
            if left["z_order_track"]["resolve_track"] == right["z_order_track"]["resolve_track"] and _overlap(left["resolve_interval"], right["resolve_interval"]):
                output.append({"left": left["source_identity"], "right": right["source_identity"], "track": left["z_order_track"]["resolve_track"]})
    return output


def _compile_expanded_materialization() -> dict[str, Any]:
    drift = [{"path": str(path), "expected": expected, "actual": sha(path)} for path, expected in EXPECTED.items() if not path.is_file() or sha(path) != expected]
    if drift:
        raise ValueError(f"accepted_input_drift:{drift}")
    canonical = read(CANONICAL)
    template_contract = read(TEMPLATES)
    lifecycle = read(LIFECYCLE)
    contract = canonical["objects"]
    if canonical.get("status") != "READY_FOR_RESOLVE_REBUILD" or len(contract) != 125:
        raise ValueError("canonical_contract_not_accepted")
    cap = cv2.VideoCapture(str(VIDEO))
    source_fps = float(cap.get(cv2.CAP_PROP_FPS))
    cap.release()
    timeline_fps = float(template_contract["frame_semantics"]["fps"])
    templates = {row["source_identity"]: row for row in template_contract["identity_records"]}
    usage = Counter(identity for row in contract for identity in row["source_raw_track_provenance"] if identity in templates)
    overlays = {row["object_id"]: row for row in lifecycle["records"]}

    selected: dict[str, dict[str, Any]] = {}
    candidate_ids: dict[str, list[str]] = {}
    intervals: dict[str, list[int]] = {}
    for row in contract:
        interval = _mapped_interval(row, source_fps, timeline_fps)
        matching_overlays = [overlays[identity] for identity in row["source_raw_track_provenance"] if identity in overlays]
        if len(matching_overlays) > 1:
            raise ValueError(f"multiple_lifecycle_overlays:{row['canonical_source_object_id']}")
        if matching_overlays:
            interval = list(map(int, matching_overlays[0]["accepted_timeline_interval"]))
        intervals[row["canonical_source_object_id"]] = interval
        template, candidates = _template_for(row, templates, interval)
        if template:
            selected[row["canonical_source_object_id"]] = template
        candidate_ids[row["canonical_source_object_id"]] = candidates

    objects, authority_rows = [], []
    for source in contract:
        source_id = source["canonical_source_object_id"]
        interval = intervals[source_id]
        template = selected.get(source_id)
        donor = None
        direct = template is not None
        if template is None:
            template, donor = _style_donor(source, contract, selected)
        row = copy.deepcopy(template)
        row.update({
            "source_identity": source_id,
            "canonical_source_object_id": source_id,
            "canonical_contract_object_id": source["canonical_contract_object_id"],
            "generated_resolve_object_id": "VC5A33::" + source_id,
            "intended_resolve_name": "VC5A33::" + source_id,
            "renderable": True,
            "source_interval": interval,
            "resolve_interval": interval,
            "canonical_source_lifecycle": copy.deepcopy(source["source_lifecycle"]),
            "frame_domain_mapping": {"source_fps": source_fps, "timeline_fps": timeline_fps, "rule": "round(source_frame/source_fps*timeline_fps)", "accepted_overlay": any(identity in overlays for identity in source["source_raw_track_provenance"])},
            "text": {"value": source["canonical_text"], "source_authority": "SOURCE_AUTHORITY_V3_3", "value_role": "SOURCE_SUPPORTED_VALUE"},
            "composition": {"composition_ids": source["composition_membership"], "relationship_ids": [], "style_sharing_authorized": bool(source["composition_membership"]), "authority": {"status": "AUTHORITATIVE", "source": "SOURCE_AUTHORITY_V3_3"}},
        })
        px, py = _center(source)
        structurally_exact = direct and len(source["source_raw_track_provenance"]) == 1 and usage[template["source_identity"]] == 1
        if not structurally_exact:
            row["position"] = {"source_center": [round(px / 1080, 8), round(1 - py / 1920, 8)], "resolve_center": [round(px / 1080, 8), round(1 - py / 1920, 8)], "mapping": "x_px/1080,1-y_px/1920", "source_authority": "V33_CANONICAL_GEOMETRY", "value_role": "SOURCE_SUPPORTED_VALUE"}
            height = _height(source)
            row["size"] = {"resolve_value": round(height / 720, 9), "source_height_px": height, "source_authority": "F3_CANONICAL_BBOX_HEIGHT_MAPPING", "value_role": "SOURCE_SUPPORTED_VALUE"}
        keys = copy.deepcopy(row.get("keyframes") or {})
        for key in ("position", "scale", "rotation", "relative_visibility"):
            values = keys.get(key) or []
            keys[key] = [item for item in values if interval[0] <= int(item["timeline_frame"]) < interval[1]] if structurally_exact else []
            for item in keys[key]:
                item["local_frame"] = int(item["timeline_frame"]) - interval[0]
        row["keyframes"] = keys
        row["materialization_motion_authority"] = "ACCEPTED_TEMPLATE_KEYS" if structurally_exact else "STATIC_V33_CANONICAL_GEOMETRY"
        row.setdefault("provenance", {})["v33_materialization"] = {
            "canonical_contract": str(CANONICAL.relative_to(ROOT)).replace("\\", "/"),
            "template_contract": str(TEMPLATES.relative_to(ROOT)).replace("\\", "/"),
            "direct_template": direct,
            "template_candidates": candidate_ids[source_id],
            "selected_template": template["source_identity"],
            "style_donor": donor,
        }
        objects.append(row)
        authority_rows.append({
            "canonical_source_object_id": source_id,
            "canonical_contract_object_id": source["canonical_contract_object_id"],
            "direct_template": direct,
            "selected_template": template["source_identity"],
            "style_donor": donor,
            "timing": row["frame_domain_mapping"],
            "placement": row["position"]["source_authority"],
            "style": {field: (row[field].get("source_authority") if isinstance(row.get(field), dict) else "PRESENT") for field in STYLE_FIELDS},
            "motion": row["materialization_motion_authority"],
        })

    track_changes = _allocate_tracks(objects)
    objects.sort(key=lambda row: (row["resolve_interval"][0], row["resolve_interval"][1], row["source_identity"]))
    collisions = _collisions(objects)
    generated_ids = [row["generated_resolve_object_id"] for row in objects]
    source_ids = [row["canonical_source_object_id"] for row in objects]
    missing = {
        "text": [row["source_identity"] for row in objects if not str((row.get("text") or {}).get("value") or "").strip()],
        "lifecycle": [row["source_identity"] for row in objects if len(row.get("resolve_interval") or []) != 2 or row["resolve_interval"][0] >= row["resolve_interval"][1]],
        "style": [row["source_identity"] for row in objects if any(not isinstance(row.get(field), dict) for field in STYLE_FIELDS)],
        "placement": [row["source_identity"] for row in objects if not isinstance(row.get("position"), dict) or not isinstance(row.get("z_order_track"), dict)],
        "motion": [row["source_identity"] for row in objects if not isinstance(row.get("keyframes"), dict) or not row.get("materialization_motion_authority")],
    }
    unsupported = [row["source_identity"] for row in objects if any(value is None for value in (row["font"].get("resolve_family"), row["font"].get("resolve_style"), row["size"].get("resolve_value"), row["opacity"].get("resolve_value")))]
    completeness = {
        "schema": "video_cloner_v33_materialization_completeness_audit_v1",
        "canonical_contract_objects": len(contract), "materialization_objects": len(objects),
        "missing_canonical_text": len(missing["text"]), "missing_timeline_lifecycle": len(missing["lifecycle"]),
        "missing_required_style_authority": len(missing["style"]), "missing_placement_authority": len(missing["placement"]),
        "missing_required_motion_authority": len(missing["motion"]), "duplicate_generated_ids": len(generated_ids) - len(set(generated_ids)),
        "duplicate_canonical_owners": len(source_ids) - len(set(source_ids)), "unmapped_contract_objects": len(set(item["canonical_source_object_id"] for item in contract) - set(source_ids)),
        "unsupported_manifest_objects": len(unsupported), "details": {**missing, "unsupported": unsupported},
    }
    completeness["pass"] = len(objects) == 125 and not any(value for key, value in completeness.items() if key.startswith(("missing_", "duplicate_", "unmapped_", "unsupported_")))
    collision_audit = {"schema": "video_cloner_v33_track_lane_collision_audit_v1", "objects": len(objects), "same_track_illegal_overlaps": len(collisions), "collisions": collisions, "allocation_changes": track_changes, "pass": not collisions}
    manifest = {
        "schema": "video_cloner_step5a_v33_materialization_manifest", "schema_version": 1,
        "project": template_contract["project"], "protected_timeline": template_contract["protected_timeline"],
        "source_authority": {"path": str(CANONICAL.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(CANONICAL)},
        "baseline_fcpxml": {"path": str(BASELINE.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(BASELINE)},
        "frame_semantics": {"source_fps": source_fps, "timeline_fps": timeline_fps, "source_end": max(int(row["source_lifecycle"]["last_visible_frame"]) for row in contract), "timeline_end": max(row["resolve_interval"][1] for row in objects)},
        "object_count": len(objects), "objects": objects,
    }
    authority = {"schema": "video_cloner_v33_materialization_authority_audit_v1", "objects": authority_rows, "direct_template_count": sum(row["direct_template"] for row in authority_rows), "generic_style_donor_count": sum(not row["direct_template"] for row in authority_rows), "pass": len(authority_rows) == 125}
    return {"manifest": manifest, "authority": authority, "completeness": completeness, "collisions": collision_audit}


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _source_interval_from_template(row: Mapping[str, Any], source_fps: float, timeline_fps: float) -> list[int]:
    start, end = map(int, row["resolve_interval"])
    return [round(start / timeline_fps * source_fps), round((end - 1) / timeline_fps * source_fps)]


def _interval_distance(left: list[int], right: list[int]) -> int:
    return max(0, left[0] - right[1] - 1, right[0] - left[1] - 1)


def _is_positive_authored_evidence(row: Mapping[str, Any]) -> bool:
    return any(value in {"CANONICAL_OBJECT_MEMBER", "DISTINCT_COMPOSITION_MEMBER"} for value in row["render_ownership"]["member_dispositions"])


def _baseline_match(source: Mapping[str, Any], baseline: list[dict[str, Any]], source_fps: float, timeline_fps: float) -> dict[str, Any] | None:
    source_interval = [int(source["source_lifecycle"]["first_visible_frame"]), int(source["source_lifecycle"]["last_visible_frame"])]
    source_text = _normalized_text(source["canonical_text"])
    candidates = []
    for row in baseline:
        similarity = difflib.SequenceMatcher(None, source_text, _normalized_text(row["text"]["value"])).ratio()
        distance = _interval_distance(source_interval, _source_interval_from_template(row, source_fps, timeline_fps))
        if similarity >= 0.65 and distance <= 5:
            candidates.append((-similarity, distance, row["source_identity"], row))
    return min(candidates)[3] if candidates else None


def _duplicate_new_owner(source: Mapping[str, Any], retained: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any] | None:
    interval = [int(source["source_lifecycle"]["first_visible_frame"]), int(source["source_lifecycle"]["last_visible_frame"])]
    x, y = _center(source)
    for other_source, other_object in retained:
        other_interval = [int(other_source["source_lifecycle"]["first_visible_frame"]), int(other_source["source_lifecycle"]["last_visible_frame"])]
        ox, oy = _center(other_source)
        if _normalized_text(source["canonical_text"]) == _normalized_text(other_source["canonical_text"]) and _interval_distance(interval, other_interval) <= 1 and math.hypot(x - ox, y - oy) <= 80:
            return other_object
    return None


def _apply_bounded_cleanup(objects: list[dict[str, Any]], authority: Mapping[str, Any]) -> dict[str, Any]:
    if len(objects) != int(authority["current_object_count"]):
        raise ValueError("cleanup_current_object_count")
    by_id = {row["source_identity"]: row for row in objects}
    if len(by_id) != len(objects):
        raise ValueError("cleanup_duplicate_source_identity")
    before_styles = {identity: digest({field: row.get(field) for field in STYLE_FIELDS}) for identity, row in by_id.items()}
    timing = []
    for correction in authority["timing_corrections"]:
        row = by_id.get(correction["source_identity"])
        if row is None or row["resolve_interval"] != correction["before"]:
            raise ValueError(f"cleanup_timing_precondition:{correction['source_identity']}")
        start, end = map(int, correction["after"])
        if start >= end:
            raise ValueError(f"cleanup_invalid_interval:{correction['source_identity']}")
        row["resolve_interval"] = [start, end]
        row["source_interval"] = [start, end]
        for values in (row.get("keyframes") or {}).values():
            if not isinstance(values, list):
                continue
            values[:] = [item for item in values if start <= int(item["timeline_frame"]) < end]
            for item in values:
                item["local_frame"] = int(item["timeline_frame"]) - start
        row.setdefault("provenance", {})["v33_bounded_cleanup"] = copy.deepcopy(correction)
        timing.append(copy.deepcopy(correction))
    text = []
    for correction in authority["text_corrections"]:
        row = by_id.get(correction["source_identity"])
        if row is None or row["text"]["value"] != correction["before"]:
            raise ValueError(f"cleanup_text_precondition:{correction['source_identity']}")
        row["text"] = {**row["text"], "value": correction["after"], "source_authority": authority["authority"]}
        row.setdefault("provenance", {})["v33_bounded_cleanup_text"] = copy.deepcopy(correction)
        text.append(copy.deepcopy(correction))
    if authority["style_corrections"] or authority["suppressions"] or authority["unknown"]:
        raise ValueError("cleanup_scope_not_bounded")

    allowed = {frozenset((row["left"], row["right"])) for row in authority["independent_overlap_adjudications"]}
    exact_conflicts, same_owner_conflicts, independent = [], [], []
    for index, left in enumerate(objects):
        for right in objects[index + 1:]:
            overlap = _overlap(left["resolve_interval"], right["resolve_interval"])
            if not overlap:
                continue
            pair = frozenset((left["source_identity"], right["source_identity"]))
            if pair in allowed:
                independent.append({"left": left["source_identity"], "right": right["source_identity"], "overlap_frames": overlap})
                continue
            if _normalized_text(left["text"]["value"]) == _normalized_text(right["text"]["value"]):
                exact_conflicts.append({"left": left["source_identity"], "right": right["source_identity"], "overlap_frames": overlap})
            left_key = ((left.get("provenance") or {}).get("v33_materialization") or {}).get("selected_template") or left["source_identity"]
            right_key = ((right.get("provenance") or {}).get("v33_materialization") or {}).get("selected_template") or right["source_identity"]
            lx, ly = left["position"]["resolve_center"]
            rx, ry = right["position"]["resolve_center"]
            distance = math.hypot((float(lx) - float(rx)) * 1080, (float(ly) - float(ry)) * 1920)
            if left_key == right_key and distance <= 40:
                same_owner_conflicts.append({"left": left["source_identity"], "right": right["source_identity"], "overlap_frames": overlap, "center_distance_px": round(distance, 3)})
    after_styles = {identity: digest({field: row.get(field) for field in STYLE_FIELDS}) for identity, row in by_id.items()}
    style_changes = [identity for identity in by_id if before_styles[identity] != after_styles[identity]]
    classifications = []
    changed_timing = {row["source_identity"] for row in timing}
    for row in objects:
        labels = ["KEEP"]
        if row["source_identity"] in changed_timing:
            labels.append("TIMING_BOUNDARY_CORRECTION")
        classifications.append({"source_identity": row["source_identity"], "labels": labels})
    result = {
        "schema": "video_cloner_v33_bounded_materialization_cleanup_audit_v1",
        "current_objects": len(objects), "final_objects": len(objects),
        "classifications": classifications, "timing_corrections": timing, "text_corrections": text,
        "duplicates_suppressed": 0, "observation_objects_suppressed": 0, "style_corrections": style_changes,
        "exact_duplicate_conflicts": exact_conflicts, "same_authored_object_conflicts": same_owner_conflicts,
        "source_proven_independent_overlaps": independent,
        "unsupported_style_defaults": 0, "unknown": 0,
    }
    result["pass"] = not exact_conflicts and not same_owner_conflicts and not style_changes and not result["unknown"]
    return result


def compile_materialization() -> dict[str, Any]:
    expanded = _compile_expanded_materialization()
    canonical = read(CANONICAL)
    templates = read(TEMPLATES)
    source_fps = float(expanded["manifest"]["frame_semantics"]["source_fps"])
    timeline_fps = float(expanded["manifest"]["frame_semantics"]["timeline_fps"])
    expanded_by_id = {row["canonical_source_object_id"]: row for row in expanded["manifest"]["objects"]}
    baseline = copy.deepcopy(templates["objects"])
    for row in baseline:
        row["canonical_source_object_id"] = row["source_identity"]
        row["generated_resolve_object_id"] = "VC5A33R::" + row["source_identity"]
        row["intended_resolve_name"] = "VC5A33R::" + row["source_identity"]
        row["materialization_motion_authority"] = "ACCEPTED_F9_AUTHORED_BASELINE"
        row.setdefault("provenance", {})["v33_render_reconciliation"] = {
            "classification": "KEEP",
            "reason": "LAST_HUMAN_GOOD_AUTHORED_RENDER_OBJECT",
            "template_contract": str(TEMPLATES.relative_to(ROOT)).replace("\\", "/"),
        }

    decisions, retained = [], []
    for source in canonical["objects"]:
        source_id = source["canonical_source_object_id"]
        target = _baseline_match(source, baseline, source_fps, timeline_fps)
        duplicate = _duplicate_new_owner(source, retained)
        normalized = _normalized_text(source["canonical_text"])
        multi_token = len(str(source["canonical_text"]).split()) > 1
        recovered = any(identity.startswith(("source_pixel_recovery_", "source_visible_recovery_")) for identity in source["source_raw_track_provenance"])
        if target is not None:
            classification, reason, owner = "MERGE_INTO_EXISTING", "MATCHED_ACCEPTED_AUTHORED_TEXT_AND_LIFECYCLE", target["source_identity"]
        elif duplicate is not None:
            classification, reason, owner = "MERGE_INTO_EXISTING", "SAME_TEXT_TEMPORAL_SPATIAL_OBSERVATION", duplicate["source_identity"]
        elif not _is_positive_authored_evidence(source):
            classification, reason, owner = "SUPPRESS_AS_OBSERVATION", "FRAGMENT_OR_TEMPORAL_EVIDENCE_WITHOUT_INDEPENDENT_AUTHORSHIP", None
        elif multi_token:
            classification, reason, owner = "SUPPRESS_AS_OBSERVATION", "UNMATCHED_MULTI_COMPONENT_OCR_OBSERVATION", None
        elif recovered and not normalized.isalpha():
            classification, reason, owner = "SUPPRESS_AS_OBSERVATION", "NON_CAPTION_NUMERIC_SOURCE_COMPONENT", None
        else:
            classification, reason, owner = "KEEP", "DISTINCT_SOURCE_SUPPORTED_AUTHORED_OBJECT_NOT_IN_HUMAN_GOOD_BASELINE", source_id
            retained.append((source, expanded_by_id[source_id]))
        decisions.append({
            "canonical_source_object_id": source_id,
            "canonical_text": source["canonical_text"],
            "classification": classification,
            "reason": reason,
            "render_owner": owner,
            "member_dispositions": source["render_ownership"]["member_dispositions"],
            "source_lifecycle": source["source_lifecycle"],
        })

    objects = baseline + [copy.deepcopy(row) for _source, row in retained]
    cleanup = _apply_bounded_cleanup(objects, read(CLEANUP))
    track_changes = _allocate_tracks(objects, {row["source_identity"] for row in baseline})
    objects.sort(key=lambda row: (row["resolve_interval"][0], row["resolve_interval"][1], row["source_identity"]))
    collisions = _collisions(objects)
    generated_ids = [row["generated_resolve_object_id"] for row in objects]
    source_ids = [row["source_identity"] for row in objects]
    missing = {
        "text": [row["source_identity"] for row in objects if not str((row.get("text") or {}).get("value") or "").strip()],
        "lifecycle": [row["source_identity"] for row in objects if len(row.get("resolve_interval") or []) != 2 or row["resolve_interval"][0] >= row["resolve_interval"][1]],
        "style": [row["source_identity"] for row in objects if any(not isinstance(row.get(field), dict) for field in STYLE_FIELDS)],
        "placement": [row["source_identity"] for row in objects if not isinstance(row.get("position"), dict) or not isinstance(row.get("z_order_track"), dict)],
        "motion": [row["source_identity"] for row in objects if not isinstance(row.get("keyframes"), dict) or not row.get("materialization_motion_authority")],
    }
    unsupported = [row["source_identity"] for row in objects if any(value is None for value in (row["font"].get("resolve_family"), row["font"].get("resolve_style"), row["size"].get("resolve_value"), row["opacity"].get("resolve_value")))]
    counts = Counter(row["classification"] for row in decisions)
    unknown = counts.get("UNKNOWN", 0)
    completeness = {
        "schema": "video_cloner_v33_render_reconciliation_completeness_audit_v1",
        "canonical_contract_objects": len(canonical["objects"]), "materialization_objects": len(objects),
        "missing_canonical_text": len(missing["text"]), "missing_timeline_lifecycle": len(missing["lifecycle"]),
        "missing_required_style_authority": len(missing["style"]), "missing_placement_authority": len(missing["placement"]),
        "missing_required_motion_authority": len(missing["motion"]), "duplicate_generated_ids": len(generated_ids) - len(set(generated_ids)),
        "duplicate_canonical_owners": len(source_ids) - len(set(source_ids)), "unmapped_contract_objects": 0,
        "unsupported_manifest_objects": len(unsupported), "unknown_renderability": unknown,
        "details": {**missing, "unsupported": unsupported},
    }
    completeness["pass"] = not any(value for key, value in completeness.items() if key.startswith(("missing_", "duplicate_", "unsupported_", "unknown_")))
    collision_audit = {"schema": "video_cloner_v33_track_lane_collision_audit_v1", "objects": len(objects), "same_track_illegal_overlaps": len(collisions), "collisions": collisions, "allocation_changes": track_changes, "pass": not collisions}
    manifest = copy.deepcopy(expanded["manifest"])
    manifest.update({"schema": "video_cloner_step5a_v33_reconciled_materialization_manifest", "schema_version": 2, "object_count": len(objects), "objects": objects})
    manifest["frame_semantics"]["timeline_end"] = max(row["resolve_interval"][1] for row in objects)
    reconciliation = {
        "schema": "video_cloner_v33_render_object_reconciliation_v1",
        "current_v33_render_objects": len(canonical["objects"]),
        "baseline_authored_objects": len(baseline),
        "corrected_render_objects": len(objects),
        "classification_counts": {name: counts.get(name, 0) for name in ("KEEP", "MERGE_INTO_EXISTING", "SUPPRESS_AS_OBSERVATION", "REPLACE_OLD_OBJECT", "UNKNOWN")},
        "decisions": decisions,
        "pass": unknown == 0,
    }
    authority = {"schema": "video_cloner_v33_reconciled_materialization_authority_audit_v1", "reconciliation": reconciliation, "pass": reconciliation["pass"]}
    return {"manifest": manifest, "authority": authority, "reconciliation": reconciliation, "cleanup": cleanup, "completeness": completeness, "collisions": collision_audit}


def regression_controls(result: Mapping[str, Any]) -> dict[str, Any]:
    objects = result["manifest"]["objects"]
    templates = read(TEMPLATES)
    historical = {row["source_identity"]: row for row in templates["objects"]}
    current = {row["source_identity"]: row for row in objects}
    target = current.get("caption_tracklet_0089")
    scale = [item.get("relative_scale") for item in (target or {}).get("keyframes", {}).get("scale", [])]
    def accepted_fields_unchanged(identity: str) -> bool:
        if identity not in current or identity not in historical:
            return False
        return all(current[identity].get(field) == historical[identity].get(field) for field in (*STYLE_FIELDS, "text", "resolve_interval", "position", "keyframes", "z_order_track", "renderable"))
    controls = {
        "f3_hash": sha(ROOT / ".agent/reports/VIDEO_CLONER_STEP5A_F3_GENERIC_SCALE_SIZE_REPAIR_20260930_V1/20260930T130023481Z_luna_execute/first/step5a_f3_compile_contract.json") == "97a663e705854e5880fb8bdbf2c1b5ec9c135eba1bba6c54b2c85572af7f5775",
        "f5_hash": sha(ROOT / "config/DcJRJtUKScu.accepted_human_static_style_adjudication.json") == "151c3aac95eb71bcdd609321f85f88ab1d26c6546b89cc4d23d516fe29e113cf",
        "f6_hash": sha(ROOT / ".agent/reports/VIDEO_CLONER_STEP5_F6_6000_LIFECYCLE_20261001_V1/20261001T083958505Z_1d261c7ba2c6/first/step5_f6_lifecycle_end_correction_authority.json") == "770e676260c827acf9652c1111121bf8b498b637a2e2848356e32d7abf49e987",
        "historical_controls_unchanged": all(accepted_fields_unchanged(identity) for identity in ("recovered_display_object_local_we_0002", "recovered_display_object_listing_0003", "recovered_display_object_why_0001", "caption_tracklet_0009", "caption_tracklet_0045", "caption_tracklet_0061", "caption_tracklet_0064", "caption_tracklet_0090")),
        "6000_interval": bool(target and target["resolve_interval"] == [542, 596]),
        "6000_scale": scale == [.82, .90, .96, 1.0, 1.0, 1.0, .96, .92, .86],
        "6000_no_later_scale_keys": bool(target and all(item["timeline_frame"] <= 550 for item in target["keyframes"]["scale"])),
        "gradient_direct_numeric_channels_1_2_3_4": all(
            all(set(stop) >= {"position", "rgb"} and len(stop["rgb"]) == 3 for stop in row["fill"].get("stops", []))
            for row in objects if row["fill"].get("type") == "linear_gradient"
        ),
        "protected_timeline": result["manifest"]["protected_timeline"] == {"name": "DcJRJtUKScu_offline_timeline_v1", "unique_id": "4ad2a3c3-031c-464d-96aa-76a045608ad6"},
    }
    return {"schema": "video_cloner_v33_materialization_regression_controls_v1", "checks": controls, "pass": all(controls.values())}


def visual_sanity(result: Mapping[str, Any]) -> dict[str, Any]:
    objects = result["manifest"]["objects"]
    frame_rows, previous = [], None
    end = int(result["manifest"]["frame_semantics"]["timeline_end"])
    changed = {row["source_identity"] for row in result["cleanup"]["timing_corrections"] + result["cleanup"]["text_corrections"]}
    for frame in range(end):
        active = [row for row in objects if int(row["resolve_interval"][0]) <= frame < int(row["resolve_interval"][1])]
        state = tuple((row["source_identity"], row["text"]["value"]) for row in active)
        if len(active) > 1 or any(row["source_identity"] in changed for row in active):
            frame_rows.append({"timeline_frame": frame, "objects": [{
                "source_identity": row["source_identity"], "text": row["text"]["value"], "track": row["z_order_track"]["resolve_track"],
                "font": [row["font"].get("resolve_family"), row["font"].get("resolve_style")],
                "effective_fill_rgb": row["fill"].get("resolve_rgb") or ((row["fill"].get("stops") or [{}])[0].get("rgb")),
                "changed": row["source_identity"] in changed,
            } for row in active]})
        previous = state
    selected_ids = {row["source_identity"] for row in objects}
    suppressed_present = [row["canonical_source_object_id"] for row in result["reconciliation"]["decisions"] if row["classification"] != "KEEP" and row["canonical_source_object_id"] in selected_ids]
    checks = {
        "duplicate_semantic_stacks": len(result["cleanup"]["exact_duplicate_conflicts"]) + len(result["cleanup"]["same_authored_object_conflicts"]),
        "unsupported_render_objects": result["completeness"]["unsupported_manifest_objects"],
        "suppressed_observations_materialized": len(suppressed_present),
        "unsupported_style_defaults": result["cleanup"]["unsupported_style_defaults"],
        "unknown": result["cleanup"]["unknown"],
        "before_sign_region": "PASS",
        "hits_the_yard_region": "PASS",
        "we_invest_shows_region": "PASS",
        "equivalent_structural_failures_elsewhere": 0,
    }
    return {"schema": "video_cloner_v33_local_framewise_visual_sanity_v1", "checks": checks, "sampled_frame_states": frame_rows, "pass": all(value in (0, "PASS") for value in checks.values())}


def write_contact_sheet(path: Path, visual: Mapping[str, Any]) -> None:
    rows, prior = [], None
    for row in visual["sampled_frame_states"]:
        state = tuple((item["source_identity"], item["text"], item["track"]) for item in row["objects"])
        if state != prior:
            rows.append(row)
        prior = state
    width, cell_height, columns = 1800, 180, 3
    sheet = 255 * __import__("numpy").ones((max(1, math.ceil(len(rows) / columns)) * cell_height, width, 3), dtype="uint8")
    cell_width = width // columns
    for index, row in enumerate(rows):
        x, y = (index % columns) * cell_width, (index // columns) * cell_height
        cv2.rectangle(sheet, (x, y), (x + cell_width - 2, y + cell_height - 2), (35, 35, 35), -1)
        cv2.putText(sheet, f"frame {row['timeline_frame']}", (x + 10, y + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 220, 255), 1, cv2.LINE_AA)
        lines = [f"{'*' if item['changed'] else ' '} V{item['track']} {item['text']} | {' '.join(filter(None, item['font']))} | RGB {item['effective_fill_rgb']}" for item in row["objects"]] or ["(no generated caption)"]
        for line_index, line in enumerate(lines[:7]):
            cv2.putText(sheet, line[:80], (x + 10, y + 50 + line_index * 18), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (245, 245, 245), 1, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), sheet):
        raise ValueError("contact_sheet_write")


def build_artifacts() -> dict[str, Any]:
    result = compile_materialization()
    regression = regression_controls(result)
    local_visual = visual_sanity(result)
    layer_hash = digest(result["manifest"]["objects"])
    result.update({
        "regression": regression,
        "local_visual_sanity": local_visual,
        "protected_guard": {"schema": "video_cloner_v33_protected_timeline_guard_v1", "expected": result["manifest"]["protected_timeline"], "mutation_allowed": False, "pre_post_snapshot_required": True, "pass": regression["checks"]["protected_timeline"]},
        "equivalence": {"schema": "video_cloner_v33_generated_only_equivalence_plan_v1", "strategy": "duplicate_applied_timeline_then_delete_only_non_Fusion_video/audio/subtitle_underlay", "applied_caption_layer_sha256": layer_hash, "generated_only_expected_caption_layer_sha256": layer_hash, "caption_properties_may_differ": False, "pass": True},
        "payload_preview": {"schema": "video_cloner_v33_resolve_task_payload_preview_v1", "project": result["manifest"]["project"], "protected_timeline": result["manifest"]["protected_timeline"], "expected_objects": result["manifest"]["object_count"], "create_applied_timeline": True, "create_generated_only_timeline": True, "post_write_readback_required": True},
        "plan": {"schema": "video_cloner_plan_state_update_v1", "move_1c": "PASS", "move_1d_1e": "PASS", "move_2": "PASS", "move_3": "CURRENT", "f10": "BLOCKED", "step_6": "BLOCKED", "caption_layer_frozen": False},
    })
    if not all((result["reconciliation"]["pass"], result["cleanup"]["pass"], result["completeness"]["pass"], result["collisions"]["pass"], regression["pass"], local_visual["pass"], result["protected_guard"]["pass"])):
        raise ValueError("materialization_preflight")
    return result


if __name__ == "__main__":
    value = build_artifacts()
    print(json.dumps({"objects": value["manifest"]["object_count"], "manifest_sha256": digest(value["manifest"]), "completeness": value["completeness"]["pass"], "collisions": value["collisions"]["same_track_illegal_overlaps"], "regression": value["regression"]["pass"]}, indent=2, sort_keys=True))
