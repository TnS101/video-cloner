"""Read-only post-rollback timeline, Flash, and neutral-media diagnostics."""
from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P4B = _load("vc_phase4b_for_post_rollback_probe", "video_cloner_phase4b_timeline_application.py")
LOCATION = _load("vc_location_for_post_rollback_probe", "video_cloner_phase4c1_flash_location_probe.py")
V1 = LOCATION.V1

TASK_ID = "VIDEO_CLONER_PHASE5_PHASE4C1_POST_ROLLBACK_SIGNATURE_AND_SHARED_MEDIA_READONLY_PROBE_V1"
MODE = "phase4c1_post_rollback_signature_and_shared_media_readonly_probe"
ACTION = "inspect_post_rollback_signature_and_shared_media"
REEL1_TIMELINE = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4_flash_transition_v4"
REEL2_TIMELINE = "DcJRJtUKScu_standalone_timeline"
PROFILE_REEL2 = "reel2_fcpxml_baseline"
PROFILE_REEL1 = "reel1_orphan_restoration_post_failure"
REEL1_SPANS = ((94, 98), (375, 379), (424, 428), (452, 456), (756, 760))
REEL1_ORPHAN_ITEM_NAME = "VC_FLASH_NEUTRAL_RGBA_V4"
DETERMINISM_CLASSIFICATIONS = {
    "TIMELINE_SIGNATURES_STABLE_TWO_PASS",
    "TIMELINE_SIGNATURE_HASH_DRIFT_SEMANTICS_STABLE",
    "TIMELINE_SIGNATURE_SEMANTIC_DRIFT",
    "TIMELINE_SIGNATURE_PROBE_BLOCKED",
}
TARGET_CLASSIFICATIONS = {
    "ROLLBACK_TARGET_BASELINE_RESTORED",
    "ROLLBACK_TARGET_RESIDUAL_FLASH_STATE",
    "ROLLBACK_TARGET_STATE_MISMATCH",
    "ROLLBACK_TARGET_PROBE_BLOCKED",
}
MEDIA_CLASSIFICATIONS = {
    "NEUTRAL_MEDIA_SINGLE_SHARED_OBJECT",
    "NEUTRAL_MEDIA_DISTINCT_REEL_OBJECTS",
    "NEUTRAL_MEDIA_DUPLICATED_OBJECTS",
    "NEUTRAL_MEDIA_MISSING",
    "NEUTRAL_MEDIA_STATE_AMBIGUOUS",
}
LINKAGE_CLASSIFICATIONS = {
    "REEL1_FLASH_MEDIA_LINKAGE_INTACT",
    "REEL1_FLASH_MEDIA_LINKAGE_BROKEN",
    "REEL1_FLASH_MEDIA_LINKAGE_PARTIAL",
    "REEL1_FLASH_MEDIA_LINKAGE_UNKNOWN",
}
ZERO_MUTATIONS = {"selections": 0, "creates": 0, "deletes": 0, "renames": 0, "imports": 0, "media_imports": 0, "fusion_writes": 0, "saves": 0}


def canonical(value: object) -> str:
    return P4B.canonical_sha256(value)


def recursive_diff(a: Any, b: Any, path: str = "$") -> list[dict[str, Any]]:
    if type(a) is not type(b):
        return [{"path": path, "kind": "TYPE", "value_a": a, "value_b": b}]
    if isinstance(a, Mapping):
        rows = []
        for key in sorted(set(a) | set(b), key=str):
            child = f"{path}.{key}"
            if key not in a or key not in b:
                rows.append({"path": child, "kind": "MISSING", "value_a": a.get(key), "value_b": b.get(key)})
            else:
                rows.extend(recursive_diff(a[key], b[key], child))
        return rows
    if isinstance(a, list):
        if a == b:
            return []
        hashes_a, hashes_b = [canonical(row) for row in a], [canonical(row) for row in b]
        if Counter(hashes_a) == Counter(hashes_b):
            return [{"path": path, "kind": "ORDER_ONLY", "value_a": a, "value_b": b}]
        rows = []
        if len(a) != len(b):
            rows.append({"path": f"{path}.length", "kind": "VALUE", "value_a": len(a), "value_b": len(b)})
        for index in range(min(len(a), len(b))):
            rows.extend(recursive_diff(a[index], b[index], f"{path}[{index}]"))
        if len(a) > len(b):
            rows.append({"path": f"{path}[{len(b)}:]", "kind": "MISSING", "value_a": a[len(b):], "value_b": None})
        elif len(b) > len(a):
            rows.append({"path": f"{path}[{len(a)}:]", "kind": "MISSING", "value_a": None, "value_b": b[len(a):]})
        return rows
    return [] if a == b else [{"path": path, "kind": "VALUE", "value_a": a, "value_b": b}]


def snapshot_pass(project: Any) -> dict[str, Any]:
    count = int(V1.safe_call(project, "GetTimelineCount", default=0) or 0)
    rows = []
    for index in range(1, count + 1):
        timeline = V1.safe_call(project, "GetTimelineByIndex", index, default=None)
        if timeline is None:
            raise RuntimeError(f"timeline_missing:{index}")
        rows.append({"timeline_index": index, "timeline_name": P4B.timeline_name(timeline), "snapshot": P4B.timeline_snapshot(timeline)})
    return {"declared_timeline_count": count, "timelines": rows}


def compare_passes(pass_a: Mapping[str, Any], pass_b: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if pass_a.get("declared_timeline_count") != pass_b.get("declared_timeline_count"):
        diff = recursive_diff(pass_a, pass_b)
        return "TIMELINE_SIGNATURE_SEMANTIC_DRIFT", [{"timeline_index": None, "timeline_name": None, "signature_a": None, "signature_b": None, "differences": diff, "order_only": False}]
    rows_a, rows_b = pass_a.get("timelines", []), pass_b.get("timelines", [])
    mismatches = []
    for row_a, row_b in zip(rows_a, rows_b):
        snap_a, snap_b = row_a["snapshot"], row_b["snapshot"]
        differences = recursive_diff({k: v for k, v in snap_a.items() if k != "signature"}, {k: v for k, v in snap_b.items() if k != "signature"})
        if snap_a.get("signature") != snap_b.get("signature") or differences or row_a["timeline_name"] != row_b["timeline_name"]:
            if row_a["timeline_name"] != row_b["timeline_name"]:
                differences.insert(0, {"path": "$.name", "kind": "VALUE", "value_a": row_a["timeline_name"], "value_b": row_b["timeline_name"]})
            mismatches.append({
                "timeline_index": row_a["timeline_index"],
                "timeline_name": row_a["timeline_name"],
                "timeline_name_b": row_b["timeline_name"],
                "signature_a": snap_a.get("signature"),
                "signature_b": snap_b.get("signature"),
                "differences": differences,
                "order_only": bool(differences) and all(row["kind"] == "ORDER_ONLY" for row in differences),
            })
    if not mismatches:
        return "TIMELINE_SIGNATURES_STABLE_TWO_PASS", []
    if all(row["order_only"] for row in mismatches):
        return "TIMELINE_SIGNATURE_HASH_DRIFT_SEMANTICS_STABLE", mismatches
    return "TIMELINE_SIGNATURE_SEMANTIC_DRIFT", mismatches


def _properties(media: Any) -> dict[str, Any]:
    value = V1.safe_call(media, "GetClipProperty", default={}) or {}
    return dict(value) if isinstance(value, Mapping) else {}


def _media_row(media: Any, folder_path: str = "") -> dict[str, Any]:
    properties = _properties(media)
    path = next((str(properties[key]) for key in ("File Path", "FilePath", "Path") if properties.get(key)), "")
    uid = str(V1.safe_call(media, "GetUniqueId", default="") or "")
    if not uid:
        uid = next((str(properties[key]) for key in ("Media ID", "Unique ID", "Clip ID") if properties.get(key)), "")
    return {
        "folder_path": folder_path,
        "name": str(V1.safe_call(media, "GetName", default="") or ""),
        "unique_id": uid or None,
        "resolved_path": path,
        "frame_rate": next((properties.get(key) for key in ("Video Frame Rate", "FPS", "Frame Rate") if properties.get(key) not in (None, "")), None),
        "alpha_mode": next((properties.get(key) for key in ("Alpha mode", "Alpha Mode") if properties.get(key) not in (None, "")), None),
    }


def enumerate_media_pool(media_pool: Any, tokens: list[str]) -> tuple[list[dict[str, Any]], bool]:
    root = V1.safe_call(media_pool, "GetRootFolder", default=None)
    if root is None:
        return [], False
    found, seen = [], set()

    def walk(folder: Any, parents: list[str]) -> None:
        marker = id(folder)
        if marker in seen:
            return
        seen.add(marker)
        name = str(V1.safe_call(folder, "GetName", default="") or "")
        here = parents + ([name] if name else [])
        clips = V1.safe_call(folder, "GetClipList", default=[]) or []
        values = clips.values() if isinstance(clips, Mapping) else clips
        for media in values:
            row = _media_row(media, "/".join(here))
            haystack = f"{row['name']}\n{row['resolved_path']}".lower()
            if any(token.lower() in haystack for token in tokens):
                found.append(row)
        children = V1.safe_call(folder, "GetSubFolderList", default=[]) or []
        values = children.values() if isinstance(children, Mapping) else children
        for child in values:
            walk(child, here)

    walk(root, [])
    return found, True


def media_classification(rows: list[dict[str, Any]], complete: bool) -> str:
    if not complete:
        return "NEUTRAL_MEDIA_STATE_AMBIGUOUS"
    if not rows:
        return "NEUTRAL_MEDIA_MISSING"
    if len(rows) == 1:
        return "NEUTRAL_MEDIA_SINGLE_SHARED_OBJECT"
    identities = [(str(row.get("name") or "").lower(), str(row.get("resolved_path") or "").lower()) for row in rows]
    return "NEUTRAL_MEDIA_DUPLICATED_OBJECTS" if len(set(identities)) < len(identities) else "NEUTRAL_MEDIA_DISTINCT_REEL_OBJECTS"


def _linked_to_inventory(row: Mapping[str, Any], media_rows: list[dict[str, Any]]) -> bool:
    uid = row.get("media_unique_id")
    if uid:
        return any(media.get("unique_id") == uid for media in media_rows)
    key = (str(row.get("media_pool_item_name") or "").lower(), str(row.get("resolved_path") or "").lower())
    return any((str(media.get("name") or "").lower(), str(media.get("resolved_path") or "").lower()) == key for media in media_rows)


def inspect_items(project: Any, identity: Mapping[str, Any], media_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    flash_matches, historical = [], []
    count = int(V1.safe_call(project, "GetTimelineCount", default=0) or 0)
    for timeline_index in range(1, count + 1):
        timeline = V1.safe_call(project, "GetTimelineByIndex", timeline_index, default=None)
        if timeline is None:
            continue
        name = P4B.timeline_name(timeline)
        for track_index, item in V1.all_video_items(timeline):
            match = LOCATION.inspect_item(name, timeline_index, track_index, item, identity)
            if match["classification"] != "NO_FLASH_MATCH":
                flash_matches.append(match)
            media = V1.safe_call(item, "GetMediaPoolItem", default=None)
            if name != REEL1_TIMELINE or media is None:
                continue
            media_row = _media_row(media)
            haystack = f"{media_row['name']}\n{media_row['resolved_path']}".lower()
            if not (V1.item_name(item).startswith("VC_FLASH_") or "flash_neutral_rgba_v4" in haystack):
                continue
            row = {
                "timeline_name": name,
                "timeline_index": timeline_index,
                "track_index": track_index,
                "start": V1.item_start(item),
                "end": V1.item_end(item),
                "duration": V1.item_duration(item),
                "item_name": V1.item_name(item),
                "has_media_pool_item": True,
                "media_pool_item_name": media_row["name"],
                "media_unique_id": media_row["unique_id"],
                "resolved_path": media_row["resolved_path"],
                "fusion_comp_count": int(V1.safe_call(item, "GetFusionCompCount", default=0) or 0),
            }
            row["linked_to_enumerated_media"] = _linked_to_inventory(row, media_rows)
            historical.append(row)
    return flash_matches, historical


def linkage_classification(rows: list[dict[str, Any]], media_complete: bool) -> str:
    if not media_complete:
        return "REEL1_FLASH_MEDIA_LINKAGE_UNKNOWN"
    valid = sum(row.get("has_media_pool_item") is True and row.get("linked_to_enumerated_media") is True for row in rows)
    if len(rows) == 5 and valid == 5:
        return "REEL1_FLASH_MEDIA_LINKAGE_INTACT"
    if valid == 0:
        return "REEL1_FLASH_MEDIA_LINKAGE_BROKEN"
    return "REEL1_FLASH_MEDIA_LINKAGE_PARTIAL"


def target_state(pass_b: Mapping[str, Any], payload: Mapping[str, Any], flash_matches: list[dict[str, Any]]) -> dict[str, Any]:
    target_name = str(payload["expected_target_timeline_name"])
    matches = [row for row in pass_b.get("timelines", []) if row.get("timeline_name") == target_name]
    if len(matches) != 1:
        return {"classification": "ROLLBACK_TARGET_STATE_MISMATCH", "occurrence_count": len(matches), "checks": {"one_target": False}}
    snapshot = matches[0]["snapshot"]
    flash_rows = [row for row in flash_matches if row.get("timeline_name") == target_name]
    source_rows = sorted([row for row in snapshot.get("video_items", []) if not str(row.get("name") or "").startswith("VC_FLASH_")], key=lambda row: (row.get("start"), row.get("track_index"), row.get("name")))
    expected = payload["accepted_baseline"]
    clips = expected["clips"]
    base = int(snapshot.get("start_frame") or 0)
    mapping = len(source_rows) == len(clips) and all(
        row.get("track_index") == 1
        and row.get("start") is not None
        and row["start"] - base == clip["timeline_start"]
        and row.get("duration") == clip["duration"]
        and row.get("left_offset") == clip["source_start"]
        and row.get("has_media_pool_item") is True
        and P4B.same_path(str(row.get("media_path") or ""), expected["source_path"])
        for row, clip in zip(source_rows, clips)
    )
    fps_values = [value for value in snapshot.get("settings", {}).values() if value not in (None, "")]
    checks = {
        "one_target": True,
        "video_track_count": snapshot.get("video_track_count") == 1,
        "audio_track_count": snapshot.get("audio_track_count") == expected["audio_track_count"],
        "v1_clip_count": len(source_rows) == expected["clip_count"],
        "duration": snapshot.get("end_frame") is not None and snapshot["end_frame"] - base == expected["duration_frames"],
        "fps": bool(fps_values) and all(abs(float(value) - expected["fps"]) <= 1e-6 for value in fps_values),
        "audio_items_empty": not snapshot.get("audio_items"),
        "source_mapping": mapping,
        "flash_absent": not flash_rows,
    }
    residual = snapshot.get("video_track_count") != 1 or bool(flash_rows)
    classification = "ROLLBACK_TARGET_RESIDUAL_FLASH_STATE" if residual else ("ROLLBACK_TARGET_BASELINE_RESTORED" if all(checks.values()) else "ROLLBACK_TARGET_STATE_MISMATCH")
    exact = [row for row in flash_rows if row.get("classification") == "EXACT_FLASH_MATCH"]
    return {
        "classification": classification,
        "occurrence_count": 1,
        "timeline_index": matches[0]["timeline_index"],
        "video_track_count": snapshot.get("video_track_count"),
        "audio_track_count": snapshot.get("audio_track_count"),
        "v1_clip_count": len(source_rows),
        "duration_frames": snapshot.get("end_frame") - base if snapshot.get("end_frame") is not None else None,
        "settings": snapshot.get("settings"),
        "flash_like_items": flash_rows,
        "exact_expected_flash_count": len(exact),
        "partial_flash_count": len(flash_rows) - len(exact),
        "fusion_composition_count": sum(int(row.get("fusion_comp_count") or 0) for row in snapshot.get("video_items", [])),
        "checks": checks,
        "v1_source_mapping": source_rows,
    }


def _range_item(track_index: int, item: Any, media_rows: list[dict[str, Any]]) -> dict[str, Any]:
    media = V1.safe_call(item, "GetMediaPoolItem", default=None)
    media_row = _media_row(media) if media is not None else {}
    row = {
        "track_index": track_index,
        "start": V1.item_start(item),
        "end": V1.item_end(item),
        "duration": V1.item_duration(item),
        "item_name": V1.item_name(item),
        "has_media_pool_item": media is not None,
        "media_pool_item_name": media_row.get("name"),
        "media_unique_id": media_row.get("unique_id"),
        "resolved_path": media_row.get("resolved_path") or "",
        "fusion_comp_count": int(V1.safe_call(item, "GetFusionCompCount", default=0) or 0),
    }
    row["linked_to_enumerated_media"] = _linked_to_inventory(row, media_rows) if media is not None else False
    return row


def reel1_state(project: Any, pass_b: Mapping[str, Any], payload: Mapping[str, Any], media_rows: list[dict[str, Any]]) -> dict[str, Any]:
    contract = payload.get("target_contract") or {}
    spans = tuple((row.get("start"), row.get("end")) for row in contract.get("expected_spans") or [])
    if (
        payload.get("expected_target_timeline_name") != REEL1_TIMELINE
        or contract.get("timeline_name") != REEL1_TIMELINE
        or contract.get("accepted_historical_timeline_name") != REEL1_TIMELINE
        or contract.get("occurrence_count") != 1
        or contract.get("expected_track_index") != 26
        or contract.get("expected_orphan_item_name") != REEL1_ORPHAN_ITEM_NAME
        or spans != REEL1_SPANS
    ):
        raise ValueError("reel1_target_contract")
    matches = [row for row in pass_b.get("timelines", []) if row.get("timeline_name") == REEL1_TIMELINE]
    if len(matches) != 1:
        return {"classification": "REEL1_TARGET_OCCURRENCE_MISMATCH", "occurrence_count": len(matches), "expected_spans": list(contract["expected_spans"]), "spans": [], "unexpected_items": []}
    timeline = V1.safe_call(project, "GetTimelineByIndex", matches[0]["timeline_index"], default=None)
    all_items = [
        row
        for track, item in V1.all_video_items(timeline)
        for row in (_range_item(track, item, media_rows),)
        if track == 26 or row["item_name"].startswith("VC_FLASH_") or "flash_neutral_rgba_v4" in f"{row['media_pool_item_name']}\n{row['resolved_path']}".lower()
    ]
    span_rows = []
    for start, end in REEL1_SPANS:
        items = [row for row in all_items if row["start"] < end and row["end"] > start]
        exact = len(items) == 1 and items[0]["start"] == start and items[0]["end"] == end and items[0]["track_index"] == 26
        if not items:
            classification = "MISSING"
        elif exact and items[0]["item_name"] == REEL1_ORPHAN_ITEM_NAME and items[0]["has_media_pool_item"] is False and items[0]["fusion_comp_count"] == 0:
            classification = "ORIGINAL_ORPHAN_PRESENT"
        elif exact and items[0]["has_media_pool_item"] is True and items[0]["linked_to_enumerated_media"] is True and items[0]["fusion_comp_count"] > 0 and items[0]["item_name"].startswith("VC_FLASH_"):
            classification = "VALID_REPLACEMENT_PRESENT"
        else:
            classification = "UNEXPECTED_OR_PARTIAL_ITEM"
        span_rows.append({"start": start, "end": end, "classification": classification, "items": items})
    unexpected = [item for row in span_rows if row["classification"] == "UNEXPECTED_OR_PARTIAL_ITEM" for item in row["items"]]
    classifications = Counter(row["classification"] for row in span_rows)
    return {
        "classification": "REEL1_EXPECTED_SPANS_CLASSIFIED",
        "occurrence_count": 1,
        "timeline_index": matches[0]["timeline_index"],
        "timeline_signature": matches[0]["snapshot"].get("signature"),
        "video_track_count": matches[0]["snapshot"].get("video_track_count"),
        "track_inventory": matches[0]["snapshot"].get("video_items"),
        "expected_spans": list(contract["expected_spans"]),
        "spans": span_rows,
        "classification_counts": dict(classifications),
        "unexpected_items": unexpected,
    }


def reel2_protection_state(pass_b: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    required = {"timeline_name": REEL2_TIMELINE, "occurrence_count": 1, "v1_clip_count": 14, "duration_frames": 854, "fps": 24, "video_track_count": 1, "v2_absent": True, "flash_absent": True}
    if dict(contract) != required:
        raise ValueError("reel2_protection_contract")
    matches = [row for row in pass_b.get("timelines", []) if row.get("timeline_name") == REEL2_TIMELINE]
    if len(matches) != 1:
        return {"ok": False, "occurrence_count": len(matches), "checks": {"one_target": False}}
    snapshot = matches[0]["snapshot"]
    base = int(snapshot.get("start_frame") or 0)
    v1 = [row for row in snapshot.get("video_items", []) if row.get("track_index") == 1]
    fps_values = [value for value in snapshot.get("settings", {}).values() if value not in (None, "")]
    checks = {
        "one_target": True,
        "v1_clip_count": len(v1) == 14,
        "duration": snapshot.get("end_frame") is not None and snapshot["end_frame"] - base == 854,
        "fps": bool(fps_values) and all(abs(float(value) - 24) <= 1e-6 for value in fps_values),
        "no_v2": snapshot.get("video_track_count") == 1,
        "no_flash": not any(str(row.get("name") or "").startswith("VC_FLASH_") or int(row.get("fusion_comp_count") or 0) for row in snapshot.get("video_items", [])),
    }
    return {"ok": all(checks.values()), "occurrence_count": 1, "timeline_index": matches[0]["timeline_index"], "timeline_signature": snapshot.get("signature"), "checks": checks}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "action": ACTION, "read_only": True, "mutation_counts": dict(ZERO_MUTATIONS), "failures": []}
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or payload.get("action") != ACTION:
            raise ValueError("command_identity")
        if payload.get("read_only") is not True or payload.get("mutation_permitted") is not False:
            raise ValueError("read_only_authority")
        profile = str(payload.get("diagnostic_profile") or PROFILE_REEL2)
        if profile not in (PROFILE_REEL2, PROFILE_REEL1):
            raise ValueError("diagnostic_profile")
        identity = payload.get("expected_flash_identity")
        if profile == PROFILE_REEL2:
            LOCATION.validate_identity(identity)
            if LOCATION.canonical_sha256(identity) != payload.get("expected_flash_identity_sha256"):
                raise ValueError("flash_identity_hash")
        manager = V1.safe_call(resolve, "GetProjectManager", default=None)
        project = V1.safe_call(manager, "GetCurrentProject", default=None)
        if project is None:
            raise RuntimeError("current_project")
        project_name = str(V1.safe_call(project, "GetName", default="") or "")
        if project_name != payload.get("expected_project_name"):
            raise RuntimeError("project_identity")
        current = V1.safe_call(project, "GetCurrentTimeline", default=None)
        current_name = P4B.timeline_name(current) if current is not None else None
        pass_a = snapshot_pass(project)
        pass_b = snapshot_pass(project)
        determinism, mismatches = compare_passes(pass_a, pass_b)
        names = [row["timeline_name"] for row in pass_a["timelines"]]
        duplicates = [{"timeline_name": name, "count": count} for name, count in sorted(Counter(names).items()) if count > 1]
        media_pool = V1.safe_call(project, "GetMediaPool", default=None)
        tokens = list(payload.get("neutral_media_search_tokens") or [])
        media_rows, media_complete = enumerate_media_pool(media_pool, tokens) if media_pool is not None else ([], False)
        flash_matches, historical = inspect_items(project, identity, media_rows) if profile == PROFILE_REEL2 else ([], [])
        media_state = media_classification(media_rows, media_complete)
        linkage = linkage_classification(historical, media_complete)
        target = target_state(pass_b, payload, flash_matches) if profile == PROFILE_REEL2 else None
        reel1 = reel1_state(project, pass_b, payload, media_rows) if profile == PROFILE_REEL1 else None
        protection = reel2_protection_state(pass_b, payload.get("reel2_protection_contract") or {}) if profile == PROFILE_REEL1 else None
        report.update({
            "ok": True,
            "diagnostic_profile": profile,
            "operation_id": payload.get("operation_id"),
            "project_name": project_name,
            "current_timeline_name": current_name,
            "declared_timeline_count": pass_a["declared_timeline_count"],
            "indexed_timeline_names": names,
            "duplicate_timeline_names": duplicates,
            "signature_pass_a": pass_a,
            "signature_pass_b": pass_b,
            "signature_mismatches": mismatches,
            "read_determinism_classification": determinism,
            "target_rollback_state": target,
            "reel1_restoration_state": reel1,
            "reel2_protection_state": protection,
            "project_wide_flash": {
                "classification": LOCATION.project_classification(flash_matches, payload["expected_target_timeline_name"]),
                "matches": flash_matches,
                "exact_count": sum(row["classification"] == "EXACT_FLASH_MATCH" for row in flash_matches),
                "partial_count": sum(row["classification"] == "PARTIAL_FLASH_MATCH" for row in flash_matches),
            },
            "neutral_media": {"classification": media_state, "enumeration_complete": media_complete, "objects": media_rows, "count": len(media_rows), "expected_paths": payload.get("expected_neutral_paths")},
            "reel1_flash_carriers": {"timeline_name": REEL1_TIMELINE, "classification": linkage, "carriers": historical, "count": len(historical)},
        })
    except BaseException as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
        report["read_determinism_classification"] = "TIMELINE_SIGNATURE_PROBE_BLOCKED"
        report.setdefault("target_rollback_state", {"classification": "ROLLBACK_TARGET_PROBE_BLOCKED"})
        report.setdefault("neutral_media", {"classification": "NEUTRAL_MEDIA_STATE_AMBIGUOUS", "enumeration_complete": False, "objects": []})
        report.setdefault("reel1_flash_carriers", {"classification": "REEL1_FLASH_MEDIA_LINKAGE_UNKNOWN", "carriers": []})
    return report
