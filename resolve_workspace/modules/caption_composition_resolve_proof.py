"""Apply the six accepted caption-composition cases to one Reel #3 proof timeline."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rep = _load("vc_caption_struct_rep", HERE / "oss002_oss_animation_representative_batch.py")
canary, batch = rep.canary, rep.batch

TASK_ID = "AN_CAPTION_STRUCT_COMBINED_PROOF_V1"
MODE = "caption_composition_combined_proof_v1"
EXPECTED_PROJECT = "VIDEO_CLONER_REEL3_FREE2104"
SOURCE_TIMELINE = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS004_VISIBLE_V1"
SOURCE_TIMELINE_UID = "412cba08-b996-421c-a563-d31737dded14"
PROOF_TIMELINE = "VC_AN_CAPTION_STRUCT_COMBINED_PROOF_DZatr0EJt4B"
SOURCE_PREFIX = "_VC_AN_CAPTION_STRUCT_"
EXPECTED_SOURCE_COUNTS = {"video_tracks": 3, "V2": 112, "V3": 69}
EXPECTED_INTERSECTING_ORDINALS = {1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 19, 20, 21, 22, 23, 26, 27, 28, 45, 46, 47, 48, 49, 50, 70, 71, 72, 73, 74, 75}
EXPECTED_PRESERVED_ORDINALS = {4, 5, 12, 19, 48, 74, 75}
PROOF_CASES = (
    {
        "case": "V2_A",
        "composition_id": "source_composition_caption_tracklet_0001__caption_tracklet_0003",
        "identities": ("caption_tracklet_0001", "caption_tracklet_0003"),
        "replacement_ordinals": {"caption_tracklet_0001": (2, 3), "caption_tracklet_0003": (1,)},
        "proof_window": (0, 29),
        "required_relationships": (("caption_tracklet_0003", "ABOVE", "caption_tracklet_0001"),),
    },
    {
        "case": "V3_A",
        "composition_id": "source_composition_caption_tracklet_0017__caption_tracklet_0020__caption_tracklet_0021",
        "identities": ("caption_tracklet_0017", "caption_tracklet_0020", "caption_tracklet_0021"),
        "replacement_ordinals": {"caption_tracklet_0017": (13,), "caption_tracklet_0020": (14,), "caption_tracklet_0021": (15,)},
        "proof_window": (65, 79),
        "required_relationships": (
            ("caption_tracklet_0017", "ABOVE", "caption_tracklet_0020"),
            ("caption_tracklet_0017", "ABOVE", "caption_tracklet_0021"),
            ("caption_tracklet_0021", "LEFT_OF", "caption_tracklet_0020"),
        ),
    },
    {
        "case": "V3_A",
        "composition_id": "source_composition_caption_tracklet_0024",
        "identities": ("caption_tracklet_0024",),
        "replacement_ordinals": {"caption_tracklet_0024": (16,)},
        "proof_window": (70, 79),
        "required_relationships": (),
    },
    {
        "case": "V3_B",
        "composition_id": "source_composition_caption_tracklet_0031__caption_tracklet_0033__caption_tracklet_0034__caption_tracklet_0035",
        "identities": ("caption_tracklet_0031", "caption_tracklet_0033", "caption_tracklet_0034", "caption_tracklet_0035"),
        "replacement_ordinals": {"caption_tracklet_0031": (22,), "caption_tracklet_0033": (21,), "caption_tracklet_0034": (23,), "caption_tracklet_0035": (20,)},
        "proof_window": (101, 118),
        "required_relationships": (
            ("caption_tracklet_0035", "LEFT_OF", "caption_tracklet_0033"),
            ("caption_tracklet_0033", "ABOVE", "caption_tracklet_0031"),
            ("caption_tracklet_0033", "ABOVE", "caption_tracklet_0034"),
            ("caption_tracklet_0031", "LEFT_OF", "caption_tracklet_0034"),
        ),
    },
    {
        "case": "V2_C",
        "composition_id": "source_composition_caption_tracklet_0041__continuous_visual_identity_0044",
        "identities": ("caption_tracklet_0041", "continuous_visual_identity_0044"),
        "replacement_ordinals": {"caption_tracklet_0041": (26,), "continuous_visual_identity_0044": ()},
        "proof_window": (127, 144),
        "required_relationships": (("continuous_visual_identity_0044", "ABOVE", "caption_tracklet_0041"),),
    },
    {
        "case": "V2_B",
        "composition_id": "source_composition_caption_tracklet_0090__caption_tracklet_0091__caption_tracklet_0092",
        "identities": ("caption_tracklet_0090", "caption_tracklet_0091", "caption_tracklet_0092"),
        "replacement_ordinals": {"caption_tracklet_0090": (45,), "caption_tracklet_0091": (46,), "caption_tracklet_0092": (47,)},
        "proof_window": (247, 288),
        "required_relationships": (
            ("caption_tracklet_0090", "LEFT_OF", "caption_tracklet_0091"),
            ("caption_tracklet_0090", "ABOVE", "caption_tracklet_0092"),
            ("caption_tracklet_0091", "ABOVE", "caption_tracklet_0092"),
        ),
    },
    {
        "case": "V3_C",
        "composition_id": "source_composition_caption_tracklet_0130__caption_tracklet_0131",
        "identities": ("caption_tracklet_0130", "caption_tracklet_0131"),
        "replacement_ordinals": {"caption_tracklet_0130": (70,), "caption_tracklet_0131": (71,)},
        "proof_window": (413, 444),
        "required_relationships": (("caption_tracklet_0130", "LEFT_OF", "caption_tracklet_0131"),),
    },
    {
        "case": "V3_C",
        "composition_id": "source_composition_caption_tracklet_0133__caption_tracklet_0134",
        "identities": ("caption_tracklet_0133", "caption_tracklet_0134"),
        "replacement_ordinals": {"caption_tracklet_0133": (72,), "caption_tracklet_0134": (73,)},
        "proof_window": (418, 444),
        "required_relationships": (("caption_tracklet_0134", "ABOVE", "caption_tracklet_0133"),),
    },
)
STATIC_FALLBACKS = (
    {
        "case": "V2_C", "composition_id": "source_composition_caption_tracklet_0045__caption_tracklet_0046",
        "visual_identity": "caption_tracklet_0045", "display_text": "I've", "style_ordinal": 27,
        "replacement_ordinals": (27,), "target_range": (127, 144),
        "source_review_frames": (
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_078_5.30s.jpg",
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_083_5.63s.jpg",
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_085_5.80s.jpg",
        ),
        "end_authority": "BOUNDED_PROOF_WINDOW_DIRECT_SOURCE_FRAME_REVIEW",
    },
    {
        "case": "V2_C", "composition_id": "source_composition_caption_tracklet_0045__caption_tracklet_0046",
        "visual_identity": "caption_tracklet_0046", "display_text": "Learned", "style_ordinal": 28,
        "replacement_ordinals": (28,), "target_range": (127, 144),
        "source_review_frames": (
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_078_5.30s.jpg",
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_083_5.63s.jpg",
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_085_5.80s.jpg",
        ),
        "end_authority": "BOUNDED_PROOF_WINDOW_DIRECT_SOURCE_FRAME_REVIEW",
    },
    {
        "case": "V2_B", "composition_id": "source_composition_caption_tracklet_0094",
        "visual_identity": "caption_tracklet_0094", "display_text": "where", "style_ordinal": 49,
        "replacement_ordinals": (49,), "target_range": (274, 279),
        "source_review_frames": (
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_164_11.50s.jpg",
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_166_11.63s.jpg",
        ),
        "end_authority": "NEXT_SOURCE_OBSERVED_CAPTION_START",
    },
    {
        "case": "V2_B", "composition_id": "source_composition_caption_tracklet_0095__caption_tracklet_0096",
        "visual_identity": "caption_tracklet_0095", "display_text": "at.", "style_ordinal": 50,
        "replacement_ordinals": (50,), "target_range": (279, 288),
        "source_review_frames": (
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_167_11.70s.jpg",
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_170_11.90s.jpg",
            "data/DZatr0EJt4B/analysis/frame_sampling/frame_171_12.00s.jpg",
        ),
        "end_authority": "DIRECT_SOURCE_FRAME_REVIEW_BOUNDED_BY_ABSENT_FRAME",
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"object_required:{path}")
    return value


def _repository_file(root: Path, value: object, expected_hash: object, label: str) -> Path:
    path = (root / str(value or "")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}_outside_repository") from exc
    if not path.is_file() or _sha256(path) != expected_hash:
        raise ValueError(f"{label}_identity")
    return path


def _display_text(member: Mapping[str, Any]) -> str:
    targeted = [str(value) for value in member.get("targeted_source_observed_texts") or [] if str(value)]
    observed = [str(value) for value in member.get("source_observed_texts") or [] if str(value)]
    semantic = re.sub(r"[^a-z0-9']", "", str((member.get("semantic_reference") or {}).get("cue_text") or "").casefold())
    semantic_matches = [value for value in observed if re.sub(r"[^a-z0-9']", "", value.casefold()) == semantic]
    candidates = targeted or semantic_matches or observed
    if not candidates:
        raise ValueError(f"display_text:{member.get('visual_identity')}")
    return max(candidates, key=lambda value: (value.count(" "), sum(character.isalpha() for character in value), sum(character.isupper() for character in value), value.lower()))


def _base_center(member: Mapping[str, Any], width: int, height: int) -> list[float]:
    boxes = [row.get("bbox_source_pixels") for row in member.get("source_observations") or []]
    boxes = [row for row in boxes if isinstance(row, list) and len(row) == 4]
    if not boxes:
        raise ValueError(f"member_geometry:{member.get('visual_identity')}")
    x = median((float(row[0]) + float(row[2])) / 2.0 for row in boxes) / width
    y_top = median((float(row[1]) + float(row[3])) / 2.0 for row in boxes) / height
    return [round(x, 9), round(1.0 - y_top, 9)]


def _relationship_keys(composition: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    return {
        (str(row.get("source_identity")), str(row.get("relationship_type")), str(row.get("target_identity")))
        for row in composition.get("spatial_relationships") or []
    }


def _validate_case_relationships(proof: Mapping[str, Any], composition: Mapping[str, Any]) -> None:
    expected = {tuple(row) for row in proof.get("required_relationships") or []}
    missing = expected - _relationship_keys(composition)
    if missing:
        raise ValueError(f"composition_relationships:{proof['case']}:{sorted(missing)}")


def _supported_states(composition: Mapping[str, Any], identity: str, proof_window: Sequence[int]) -> list[Mapping[str, Any]]:
    start, end = (int(value) for value in proof_window)
    return [
        state
        for state in composition.get("states") or []
        if start <= int(state["timeline_frame"]) < end
        and (state.get("member_evidence") or {}).get(identity, {}).get("status") in {"observed_present", "inferred_retained"}
    ]


def _translated_recipe(recipe: Mapping[str, Any], start: int, end: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    channels: dict[str, list[dict[str, Any]]] = {}
    dropped = Counter()
    inserted_holds = []
    for channel, keys in (recipe.get("channels") or {}).items():
        translated = []
        for key in keys:
            global_frame = int(recipe["start_frame"]) + int(key["frame"])
            if start <= global_frame < end:
                translated.append({**key, "frame": global_frame - start})
            else:
                dropped["before" if global_frame < start else "after"] += 1
        if translated and translated[0]["frame"] > 0:
            neutral: Any = [0.0, 0.0] if channel == "position" else [1.0, 1.0] if channel == "scale" else 1.0
            translated.insert(0, {"frame": 0, "interpolation": "hold", "value": neutral})
            inserted_holds.append(channel)
        if translated:
            channels[channel] = translated
    metadata = {
        "original_recipe_start_frame": int(recipe["start_frame"]),
        "application_start_frame": start,
        "conversion": "local_frame = original_recipe_start_frame + recipe_local_frame - application_start_frame",
        "dropped_outside_visibility": dict(dropped),
        "static_hold_before_first_measured_key": inserted_holds,
        "retimed": False,
    }
    if not channels:
        return None, metadata
    adjusted = {**recipe, "start_frame": start, "duration": end - start, "channels": channels}
    rep.recipe_contract.validate_recipe(adjusted)
    return adjusted, metadata


def build_plans(
    compositions_path: Path,
    lifecycle_path: Path,
    style_path: Path,
    recipes_path: Path,
) -> list[dict[str, Any]]:
    payload = _load_json(compositions_path)
    lifecycle = _load_json(lifecycle_path)
    style = _load_json(style_path)
    recipes_payload = _load_json(recipes_path)
    if payload.get("schema") != "video_cloner.caption_compositions" or payload.get("reel") != "DZatr0EJt4B":
        raise ValueError("composition_authority")
    if float((payload.get("coordinate_spaces") or {}).get("timeline", {}).get("fps") or 0) != 24.0:
        raise ValueError("timeline_fps")
    if float((payload.get("coordinate_spaces") or {}).get("source", {}).get("fps") or 0) != 30.0:
        raise ValueError("source_fps")
    video = style.get("video_info") or {}
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if (width, height) != (1080, 1920):
        raise ValueError(f"source_dimensions:{width}x{height}")
    lifecycle_ids = {
        str(token.get("visual_event_identity"))
        for composition in lifecycle.get("visual_compositions") or []
        for token in composition.get("tokens") or []
        if token.get("visual_event_identity")
    }
    compositions = {str(row.get("composition_id")): row for row in payload.get("compositions") or []}
    recipes = {str(row.get("caption_id")): rep.recipe_contract.validate_recipe(row) for row in recipes_payload.get("recipes") or []}
    cross_group = list(payload.get("cross_group_simultaneity") or [])
    case_proofs: dict[str, list[Mapping[str, Any]]] = {}
    for proof in PROOF_CASES:
        case_proofs.setdefault(str(proof["case"]), []).append(proof)
    for case, selected in case_proofs.items():
        for index, left in enumerate(selected):
            for right in selected[index + 1:]:
                left_ids, right_ids = set(left["identities"]), set(right["identities"])
                if not any(
                    (row.get("source_identity") in left_ids and row.get("target_identity") in right_ids)
                    or (row.get("source_identity") in right_ids and row.get("target_identity") in left_ids)
                    for row in cross_group
                ):
                    raise ValueError(f"cross_group_co_visibility:{case}")
    plans = []
    track = 4
    for proof in PROOF_CASES:
        composition = compositions.get(proof["composition_id"])
        if composition is None or set(composition.get("visual_member_identities") or []) != set(proof["identities"]):
            raise ValueError(f"composition_identity:{proof['case']}")
        _validate_case_relationships(proof, composition)
        members = {str(row.get("visual_identity")): row for row in composition.get("members") or []}
        for identity in proof["identities"]:
            if identity not in lifecycle_ids or identity not in members:
                raise ValueError(f"member_identity:{identity}")
            member = members[identity]
            animation = member.get("accepted_animation") or {}
            caption_id = str(animation.get("caption_id") or "")
            recipe = recipes.get(caption_id)
            if animation.get("status") != "linked" or recipe is None or recipe.get("provenance", {}).get("localization_event_id") != animation.get("event_id"):
                raise ValueError(f"animation_identity:{identity}")
            states = _supported_states(composition, identity, proof["proof_window"])
            observed = [state for state in states if state["member_evidence"][identity]["status"] == "observed_present"]
            if not observed:
                raise ValueError(f"positive_visibility:{identity}")
            start = max(int(proof["proof_window"][0]), min(int(state["timeline_frame"]) for state in observed))
            end = int(proof["proof_window"][1])
            negative = [
                int(state["timeline_frame"])
                for state in composition.get("states") or []
                if int(state["timeline_frame"]) > max(int(row["timeline_frame"]) for row in states)
                and (state.get("member_evidence") or {}).get(identity, {}).get("status") == "proven_absent"
            ]
            if negative:
                end = min(end, min(negative))
                end_authority = "FIRST_PROVEN_ABSENT_SAMPLE"
            else:
                end_authority = "PROOF_WINDOW_BOUNDARY_NOT_SOURCE_EXIT"
            adjusted, translation = _translated_recipe(recipe, start, end)
            statuses = Counter(state["member_evidence"][identity]["status"] for state in composition.get("states") or [] if start <= int(state["timeline_frame"]) < end)
            visibility_evidence = [
                {
                    "source_frame": int(state["source_frame"]),
                    "timeline_frame": int(state["timeline_frame"]),
                    **state["member_evidence"][identity],
                }
                for state in composition.get("states") or []
                if start <= int(state["timeline_frame"]) < end
            ]
            plans.append({
                "kind": "composition_member",
                "application_route": "COMPOSITION_AWARE_EDITABLE_TEXTPLUS",
                "case": proof["case"],
                "composition_id": proof["composition_id"],
                "visual_identity": identity,
                "display_text": _display_text(member),
                "caption_id": caption_id,
                "style_ordinal": int(caption_id.rsplit("_", 1)[-1]),
                "replacement_ordinals": list(proof["replacement_ordinals"][identity]),
                "replacement_authority": "DIRECT_VISUAL_IDENTITY_TO_ACCEPTED_ANIMATION_EVENT",
                "target_track": track,
                "target_range": [start, end],
                "start_authority": "FIRST_POSITIVE_SOURCE_OBSERVATION_IN_PROOF_WINDOW",
                "end_authority": end_authority,
                "base_center": _base_center(member, width, height),
                "relationships": list(composition.get("spatial_relationships") or []),
                "cross_group_co_visibility": [
                    row for row in cross_group
                    if identity in {row.get("source_identity"), row.get("target_identity")}
                    and {row.get("source_identity"), row.get("target_identity")} <= set().union(*(set(value["identities"]) for value in case_proofs[str(proof["case"])]))
                ],
                "state_evidence_counts": dict(statuses),
                "visibility_evidence": visibility_evidence,
                "animation_recipe": adjusted,
                "animation_translation": translation,
                "accepted_animation_link": animation,
            })
            track += 1
    for fallback in STATIC_FALLBACKS:
        composition = compositions.get(fallback["composition_id"])
        if composition is None:
            raise ValueError(f"fallback_composition:{fallback['visual_identity']}")
        member = next((row for row in composition.get("members") or [] if row.get("visual_identity") == fallback["visual_identity"]), None)
        semantic_text = str((member or {}).get("semantic_reference", {}).get("cue_text") or "")
        observed_texts = (member or {}).get("source_observed_texts") or []
        if (
            member is None
            or fallback["visual_identity"] not in lifecycle_ids
            or not observed_texts
            or (fallback["display_text"] not in observed_texts and fallback["display_text"].casefold() != semantic_text.casefold())
        ):
            raise ValueError(f"fallback_source_identity:{fallback['visual_identity']}")
        proof_window = next(row["proof_window"] for row in PROOF_CASES if row["case"] == fallback["case"])
        if fallback["target_range"][0] < proof_window[0] or fallback["target_range"][1] > proof_window[1]:
            raise ValueError(f"fallback_visibility:{fallback['visual_identity']}")
        start, end = fallback["target_range"]
        evidence = [
            {"source_frame": int(state["source_frame"]), "timeline_frame": int(state["timeline_frame"]), **state["member_evidence"][fallback["visual_identity"]]}
            for state in composition.get("states") or []
            if start <= int(state["timeline_frame"]) < end
        ]
        plans.append({
            "kind": "static_fallback",
            "application_route": "SOURCE_GROUNDED_STATIC_EDITABLE_TEXTPLUS",
            "case": fallback["case"],
            "composition_id": fallback["composition_id"],
            "visual_identity": fallback["visual_identity"],
            "display_text": fallback["display_text"],
            "caption_id": None,
            "style_ordinal": fallback["style_ordinal"],
            "replacement_ordinals": list(fallback["replacement_ordinals"]),
            "replacement_authority": "DIRECT_REVIEW_OF_EXISTING_SOURCE_FRAME",
            "source_review_frames": list(fallback["source_review_frames"]),
            "target_track": track,
            "target_range": [start, end],
            "start_authority": "SOURCE_OBSERVED_VISIBILITY_WINDOW",
            "end_authority": fallback["end_authority"],
            "base_center": _base_center(member, width, height),
            "relationships": list(composition.get("spatial_relationships") or []),
            "cross_group_co_visibility": [],
            "state_evidence_counts": dict(Counter(row["status"] for row in evidence)),
            "visibility_evidence": evidence,
            "animation_recipe": None,
            "animation_translation": {"reason": "STATIC_FALLBACK_NO_UNAMBIGUOUS_ANIMATION_REQUIRED", "retimed": False},
            "accepted_animation_link": member.get("accepted_animation") or {},
        })
        track += 1
    if len(plans) != 23 or len({row["visual_identity"] for row in plans}) != 23:
        raise ValueError("proof_plan_count")
    if {ordinal for row in plans for ordinal in row["replacement_ordinals"]} != {1, 2, 3, 13, 14, 15, 16, 20, 21, 22, 23, 26, 27, 28, 45, 46, 47, 49, 50, 70, 71, 72, 73}:
        raise ValueError("replacement_identity_contract")
    return plans


def plan_sha256(plans: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(list(plans), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _find_optional(project: Any, name: str) -> Any:
    rows = [canary._optional(project, "GetTimelineByIndex", index) for index in range(1, int(canary._optional(project, "GetTimelineCount", default=0) or 0) + 1)]
    matches = [row for row in rows if row is not None and canary._name(row) == name]
    if len(matches) > 1:
        raise ValueError(f"timeline_name_ambiguous:{name}")
    return matches[0] if matches else None


def _snapshot(timeline: Any) -> list[tuple[Any, ...]]:
    rows = []
    for kind in ("video", "audio"):
        for track in range(1, int(canary._optional(timeline, "GetTrackCount", kind, default=0) or 0) + 1):
            for item in canary._optional(timeline, "GetItemListInTrack", kind, track, default=[]) or []:
                rows.append((kind, track, canary._name(item), canary._item_start(item), canary._item_duration(item), canary._clip_enabled(item)))
    return sorted(rows)


def _source_counts(timeline: Any) -> dict[str, int]:
    return {
        "video_tracks": int(canary._optional(timeline, "GetTrackCount", "video", default=0) or 0),
        "V2": len(canary._optional(timeline, "GetItemListInTrack", "video", 2, default=[]) or []),
        "V3": len(canary._optional(timeline, "GetItemListInTrack", "video", 3, default=[]) or []),
    }


def _caption_inventory(timeline: Any, base_frame: int) -> list[dict[str, Any]]:
    v2_items = canary._optional(timeline, "GetItemListInTrack", "video", 2, default=[]) or []
    rows = [
        {
            "ordinal": ordinal,
            "representation": "V2_BASIC_TITLE",
            "item": item,
            "track": 2,
            "start": canary._item_start(item) - base_frame,
            "duration": canary._item_duration(item),
            "enabled": canary._clip_enabled(item),
            "source": "",
        }
        for ordinal, item in enumerate(sorted(v2_items, key=canary._item_start), start=1)
    ]
    for row in batch._nested_items(timeline):
        if row["track"] != 3:
            continue
        match = re.search(r"SUB(\d{3})(?:_|$)", row["source"]["name"])
        if match is None:
            raise ValueError(f"nested_caption_identity:{row['source']['name']}")
        rows.append({
            "ordinal": int(match.group(1)),
            "representation": "V3_NESTED_TEXTPLUS",
            "item": row["item"],
            "track": row["track"],
            "start": row["start"] - base_frame,
            "duration": row["duration"],
            "enabled": canary._clip_enabled(row["item"]),
            "source": row["source"]["name"],
        })
    if sum(row["representation"] == "V2_BASIC_TITLE" for row in rows) != 112 or sum(row["representation"] == "V3_NESTED_TEXTPLUS" for row in rows) != 69:
        raise ValueError("caption_inventory_count")
    return rows


def _active_caption_rows(rows: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    active: dict[int, Mapping[str, Any]] = {}
    for ordinal in range(1, 113):
        matches = [row for row in rows if row["ordinal"] == ordinal and row["enabled"] is True]
        if len(matches) != 1:
            raise ValueError(f"active_caption_identity:{ordinal}:{len(matches)}")
        active[ordinal] = matches[0]
    return active


def _caption_contract(rows: Sequence[Mapping[str, Any]]) -> list[tuple[Any, ...]]:
    return sorted((row["ordinal"], row["representation"], row["track"], row["start"], row["duration"], row["enabled"], row["source"]) for row in rows)


def _overlaps_windows(row: Mapping[str, Any]) -> bool:
    start, end = int(row["start"]), int(row["start"]) + int(row["duration"])
    return any(start < window_end and end > window_start for window_start, window_end in (proof["proof_window"] for proof in PROOF_CASES))


def _rollback(project: Any, pool: Any, proof: Any, sources: Sequence[Any], source: Any, before: Sequence[Any]) -> dict[str, Any]:
    deleted = True
    try:
        canary._optional(project, "SetCurrentTimeline", source, default=False)
        targets = [row for row in [proof, *sources] if row is not None]
        if targets:
            deleted = canary._optional(pool, "DeleteTimelines", targets, default=False) is True
        preserved = _snapshot(source) == list(before)
    except Exception:
        preserved = False
        deleted = False
    return {"created_timelines_deleted": deleted, "source_preserved": preserved, "ok": deleted and preserved}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "failures": []}
    project = pool = source = proof = None
    sources: list[Any] = []
    source_before: list[tuple[Any, ...]] = []
    saved = False
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "expected_project": EXPECTED_PROJECT,
            "source_timeline": SOURCE_TIMELINE,
            "source_timeline_uid": SOURCE_TIMELINE_UID,
            "proof_timeline": PROOF_TIMELINE,
            "save_after_verification": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if _sha256(Path(__file__).resolve()) != payload.get("module_sha256"):
            raise ValueError("module_identity")
        paths = {
            label: _repository_file(root, payload.get(f"{label}_path"), payload.get(f"{label}_sha256"), label)
            for label in ("compositions", "lifecycle", "style", "recipes", "fcpxml", "reference_video")
        }
        plans = build_plans(paths["compositions"], paths["lifecycle"], paths["style"], paths["recipes"])
        if plan_sha256(plans) != payload.get("plan_sha256"):
            raise ValueError("plan_identity")
        styles = batch._styles_by_ordinal(paths["fcpxml"])
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != EXPECTED_PROJECT:
            raise ValueError("project_identity")
        if _find_optional(project, PROOF_TIMELINE) is not None:
            raise ValueError("proof_timeline_exists")
        source = _find_optional(project, SOURCE_TIMELINE)
        if source is None or canary._timeline_identity(source)["unique_id"] != SOURCE_TIMELINE_UID or _source_counts(source) != EXPECTED_SOURCE_COUNTS:
            raise ValueError("source_timeline_identity")
        source_before = _snapshot(source)
        pool = canary.carrier._call(project, "GetMediaPool")
        proof = canary._optional(source, "DuplicateTimeline", PROOF_TIMELINE, default=None)
        if proof is None or canary._optional(project, "SetCurrentTimeline", proof, default=False) is not True:
            raise RuntimeError("proof_timeline_duplicate")
        base_frame = int(canary._optional(proof, "GetStartFrame", default=0) or 0)
        caption_before = _caption_inventory(proof, base_frame)
        active_before = _active_caption_rows(caption_before)
        replacement_plans = {}
        for plan in plans:
            for ordinal in plan["replacement_ordinals"]:
                if ordinal in replacement_plans:
                    raise ValueError(f"duplicate_replacement_ordinal:{ordinal}")
                replacement_plans[ordinal] = plan
        intersecting = {ordinal: row for ordinal, row in active_before.items() if _overlaps_windows(row)}
        if set(intersecting) != EXPECTED_INTERSECTING_ORDINALS or set(intersecting) - set(replacement_plans) != EXPECTED_PRESERVED_ORDINALS:
            raise ValueError(f"intersecting_caption_contract:{sorted(intersecting)}")
        replacement_mapping = []
        for ordinal, plan in sorted(replacement_plans.items()):
            row = active_before[ordinal]
            if canary._optional(row["item"], "SetClipEnabled", False, default=False) is False or canary._clip_enabled(row["item"]) is not False:
                raise RuntimeError(f"specific_caption_disable:{ordinal}")
            replacement_mapping.append({
                "ordinal": ordinal,
                "old_text": styles[ordinal]["StyledText"],
                "old_representation": row["representation"],
                "old_range": [row["start"], row["start"] + row["duration"]],
                "status": "REPLACED_STATIC_FALLBACK" if plan["kind"] == "static_fallback" else "REPLACED_COMPOSITION_MEMBER",
                "replacement_identity": plan["visual_identity"],
                "replacement_text": plan["display_text"],
                "authority": plan["replacement_authority"],
            })
        replacement_mapping.extend({
            "ordinal": ordinal,
            "old_text": styles[ordinal]["StyledText"],
            "old_representation": row["representation"],
            "old_range": [row["start"], row["start"] + row["duration"]],
            "status": "PRESERVED_COMPLEMENTARY_LAYER",
            "replacement_identity": None,
            "replacement_text": None,
            "authority": "ACCEPTED_SOURCE_TIMELINE_NO_DIRECT_REPLACEMENT_IDENTITY",
        } for ordinal, row in sorted(intersecting.items()) if ordinal not in replacement_plans)
        while int(canary._optional(proof, "GetTrackCount", "video", default=0) or 0) < max(row["target_track"] for row in plans):
            if canary._optional(proof, "AddTrack", "video", default=False) is not True:
                raise RuntimeError("proof_track_create")
        technical = []
        token = run_id.rsplit("_", 1)[-1][:12]
        for index, plan in enumerate(plans, start=1):
            name = f"{SOURCE_PREFIX}{plan['case']}_{index:02d}_{token}"
            if _find_optional(project, name) is not None:
                raise ValueError(f"source_name_collision:{name}")
            nested = canary.carrier._call(pool, "CreateEmptyTimeline", name)
            sources.append(nested)
            if nested is None or canary._optional(project, "SetCurrentTimeline", nested, default=False) is not True:
                raise RuntimeError(f"source_timeline_create:{plan['visual_identity']}")
            canary.carrier._call(nested, "InsertFusionTitleIntoTimeline", "Text+")
            item, tool = canary.carrier._find_textplus(nested)
            ordinal = int(plan["style_ordinal"])
            style_values = {**styles[ordinal], "StyledText": plan["display_text"], "Center": plan["base_center"]}
            static = canary._set_static_style(tool, style_values)
            comp = canary.carrier._call(item, "GetFusionCompByIndex", 1)
            applied = rep.apply_recipe_channels(comp, tool, plan["animation_recipe"], style_values) if plan["animation_recipe"] else {
                "ok": True,
                "channels": {},
                "reason": "source_grounded_static_fallback" if plan["kind"] == "static_fallback" else "no_measured_keys_inside_visibility_window",
            }
            source_item = canary.carrier._call(nested, "GetMediaPoolItem")
            if source_item is None:
                raise RuntimeError("source_media_pool_item")
            canary.carrier._call(project, "SetCurrentTimeline", proof)
            start, end = (int(value) for value in plan["target_range"])
            returned = canary.carrier._call(pool, "AppendToTimeline", [{
                "mediaPoolItem": source_item,
                "startFrame": 0,
                "endFrame": end - start,
                "trackIndex": int(plan["target_track"]),
                "recordFrame": base_frame + start,
            }])
            if not isinstance(returned, (list, tuple)) or len(returned) != 1 or returned[0] is None:
                raise RuntimeError(f"proof_append:{plan['visual_identity']}")
            placed = returned[0]
            placement = {
                "track": int(canary.carrier._call(placed, "GetTrackTypeAndIndex")[1]),
                "start": canary._item_start(placed) - base_frame,
                "duration": canary._item_duration(placed),
            }
            if placement != {"track": int(plan["target_track"]), "start": start, "duration": end - start}:
                raise RuntimeError(f"proof_placement:{plan['visual_identity']}:{placement}")
            inner = canary.carrier._call(canary.carrier._call(placed, "GetMediaPoolItem"), "GetTimeline")
            _, inner_tool = canary.carrier._find_textplus(inner)
            targets = rep._channel_targets(plan["animation_recipe"], style_values) if plan["animation_recipe"] else {}
            if str(rep.canary.animation.read_input(inner_tool, "StyledText", 0) or "") != plan["display_text"]:
                raise RuntimeError(f"text_readback:{plan['visual_identity']}")
            if any(not canary.animation.input_targets_are_correct(inner_tool, input_name, values) for input_name, values in targets.items()):
                raise RuntimeError(f"animation_readback:{plan['visual_identity']}")
            technical.append({"plan": plan, "source_timeline": canary._timeline_identity(nested), "placement": placement, "static": static, "animation": applied, "animation_targets": targets})
        canary.carrier._call(project, "SetCurrentTimeline", proof)
        if _snapshot(source) != source_before or _source_counts(source) != EXPECTED_SOURCE_COUNTS:
            raise RuntimeError("accepted_source_changed")
        proof_tracks = list(range(4, max(row["target_track"] for row in plans) + 1))
        proof_items = sum(len(canary._optional(proof, "GetItemListInTrack", "video", track, default=[]) or []) for track in proof_tracks)
        if proof_items != len(plans):
            raise RuntimeError(f"proof_item_count:{proof_items}")
        caption_after = _caption_contract(_caption_inventory(proof, base_frame))
        expected_caption_after = sorted(
            (*row[:5], False if row[0] in replacement_plans else row[5], *row[6:])
            for row in _caption_contract(caption_before)
        )
        if caption_after != expected_caption_after:
            raise RuntimeError("existing_caption_contract_changed")
        result.update({
            "verification": "PASS",
            "source_timeline": canary._timeline_identity(source),
            "proof_timeline": canary._timeline_identity(proof),
            "composition_artifact": {"path": str(paths["compositions"]), "sha256": _sha256(paths["compositions"])},
            "plan_sha256": plan_sha256(plans),
            "composition_ids": [row["composition_id"] for row in PROOF_CASES],
            "proof_cases": sorted({row["case"] for row in PROOF_CASES}),
            "static_fallback_composition_ids": [row["composition_id"] for row in STATIC_FALLBACKS],
            "technical_rows": technical,
            "replacement_mapping": sorted(replacement_mapping, key=lambda row: row["ordinal"]),
            "replacement_counts": dict(Counter(row["status"] for row in replacement_mapping)),
            "disabled_existing_ordinals": sorted(replacement_plans),
            "generated_member_count": sum(row["kind"] == "composition_member" for row in plans),
            "static_fallback_count": sum(row["kind"] == "static_fallback" for row in plans),
            "unresolved_count": 0,
            "proof_tracks": proof_tracks,
            "reference_video": {"path": str(paths["reference_video"]), "sha256": _sha256(paths["reference_video"])},
        })
        result["save_project_return"] = canary.carrier._call(manager, "SaveProject")
        if result["save_project_return"] is not True:
            raise RuntimeError("save_project")
        saved = True
        result["ok"] = True
        return result
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if project is not None and pool is not None and source is not None and not saved:
            result["rollback"] = _rollback(project, pool, proof, sources, source, source_before)
        return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
