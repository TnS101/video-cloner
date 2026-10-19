"""Harvest and place a Resolve-authored Blur Dissolve transition element.

This is the smallest extension of the pinned placeTransition string-surgery
mechanism from samuelgursky/davinci-resolve-mcp at
94c7a885d53f13be78522ce96561a9e9e21d64c5 (MIT).
"""
from __future__ import annotations

import importlib.util
import html
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("vc_oss003_native_drt_base", HERE / "oss003_native_transition_drt.py")
if spec is None or spec.loader is None:
    raise ImportError("cannot_load_native_drt_base")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def extract_transition(path: Path, timeline_name: str, track: int = 1) -> dict[str, Any]:
    selected = base.select_top_level(path, timeline_name)
    _, contents = base._archive(path)
    xmls = base._text_files(contents)
    all_transitions = [(entry, match.group(0)) for entry, xml in xmls.items() for match in base.TRANSITION_RE.finditer(xml)]
    if len(all_transitions) != 1 or all_transitions[0][0] != selected["entry"]:
        raise ValueError(f"transition_count_or_container:{len(all_transitions)}")
    xml = xmls[selected["entry"]]
    _, vector = base._inner(xml, "VideoTrackVec")
    tracks = base.TRACK_RE.findall(vector)
    if track > len(tracks):
        raise ValueError(f"video_track:{len(tracks)}")
    _, items = base._inner(tracks[track - 1], "Items")
    matches = base.TRANSITION_RE.findall(items)
    if len(matches) != 1:
        raise ValueError(f"track_transition_count:{len(matches)}")
    element = ET.fromstring(matches[0])
    transition = next(iter(element))
    fields = {child.tag: child.text or "" for child in transition}
    identities = [f"{node.tag}@DbId" for node in transition.iter() if "DbId" in node.attrib]
    return {
        "timeline_name": timeline_name, "container_uuid": selected["id"], "entry": selected["entry"],
        "track": track, "transition_count": 1, "element": matches[0],
        "db_id": transition.attrib.get("DbId", ""), "identity_fields": identities,
        "fields": fields, "pretty_type": fields.get("PrettyType", ""),
        "start": int(fields.get("Start", -1)), "duration": int(fields.get("Duration", -1)),
    }


def transition_diff(cross: dict[str, Any], blur: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(cross["fields"]) | set(blur["fields"]))
    differing = {key: {"cross": cross["fields"].get(key), "blur": blur["fields"].get(key)} for key in keys if cross["fields"].get(key) != blur["fields"].get(key)}
    style_fields = {key: value for key, value in blur["fields"].items() if key not in {"Start", "Duration"}}
    return {
        "pretty_type_only": set(differing) == {"PrettyType", "Name"},
        "fields_blob_differs": cross["fields"].get("FieldsBlob") != blur["fields"].get("FieldsBlob"),
        "effect_filters_ba_differs": cross["fields"].get("EffectFiltersBA") != blur["fields"].get("EffectFiltersBA"),
        "differing_fields": differing,
        "identity_fields_regenerated": blur["identity_fields"],
        "reusable_style_payload": style_fields,
    }


def place_blur_transition(source: Path, target: Path, *, timeline_name: str, timeline_uuid: str, donor_element: str, track: int, at_frame: int, duration_frames: int) -> dict[str, Any]:
    donor_root = ET.fromstring(donor_element)
    donor = next(iter(donor_root))
    if (donor.findtext("PrettyType") or "") != "Blur Dissolve":
        raise ValueError("donor_pretty_type")
    selected = base.select_top_level(source, timeline_name)
    if selected["id"] != timeline_uuid:
        raise ValueError(f"top_level_uuid:{selected['id']}")
    infos, contents = base._archive(source)
    entry = selected["entry"]
    original = contents[entry].decode("utf-8-sig")
    vector_match, vector = base._inner(original, "VideoTrackVec")
    tracks = base.TRACK_RE.findall(vector)
    if track < 1 or track > len(tracks):
        raise ValueError(f"video_track:{len(tracks)}")
    items_match, items = base._inner(tracks[track - 1], "Items")
    clips = base.CLIP_RE.findall(items)
    left_index = next((index for index in range(len(clips) - 1) if base._number(clips[index], "Start") + base._number(clips[index], "Duration") == base._number(clips[index + 1], "Start") == at_frame), -1)
    if left_index < 0:
        raise ValueError(f"abutting_boundary:{at_frame}")
    start = at_frame - duration_frames // 2
    transition = re.sub(r'DbId="[0-9a-fA-F-]+"', lambda _: f'DbId="{uuid.uuid4()}"', donor_element)
    transition = re.sub(r"<Start>\d+</Start>", f"<Start>{start}</Start>", transition)
    transition = re.sub(r"<Duration>\d+</Duration>", f"<Duration>{duration_frames}</Duration>", transition)
    new_items = items.replace(clips[left_index], clips[left_index] + transition, 1)
    new_track = tracks[track - 1][:items_match.start()] + f"<Items>{new_items}</Items>" + tracks[track - 1][items_match.end():]
    new_vector = vector.replace(tracks[track - 1], new_track, 1)
    patched = original[:vector_match.start()] + f"<VideoTrackVec>{new_vector}</VideoTrackVec>" + original[vector_match.end():]
    contents[entry] = patched.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as output:
        for info in infos:
            output.writestr(info, contents[info.filename])
    placed = extract_transition(target, timeline_name, track)
    if placed["pretty_type"] != "Blur Dissolve" or placed["start"] != start or placed["duration"] != duration_frames:
        raise RuntimeError("blur_transition_offline_readback")
    return {key: placed[key] for key in ("container_uuid", "entry", "track", "pretty_type", "start", "duration")} | {"end": start + duration_frames, "cut": at_frame}


def place_blur_transitions(source: Path, target: Path, *, timeline_name: str, timeline_uuid: str, donor_element: str, track: int, boundaries: list[tuple[int, int]], output_timeline_name: str | None = None) -> list[dict[str, Any]]:
    """Place several donor-native transitions while preserving every other DRT byte."""
    donor_root = ET.fromstring(donor_element)
    if (next(iter(donor_root)).findtext("PrettyType") or "") != "Blur Dissolve":
        raise ValueError("donor_pretty_type")
    if len({cut for cut, _ in boundaries}) != len(boundaries):
        raise ValueError("duplicate_boundary")
    selected = base.select_top_level(source, timeline_name)
    if selected["id"] != timeline_uuid:
        raise ValueError(f"top_level_uuid:{selected['id']}")
    infos, contents = base._archive(source)
    entry = selected["entry"]
    original = contents[entry].decode("utf-8-sig")
    if base.TRANSITION_RE.search(original):
        raise ValueError("source_transition_exists")
    vector_match, vector = base._inner(original, "VideoTrackVec")
    tracks = base.TRACK_RE.findall(vector)
    if track < 1 or track > len(tracks):
        raise ValueError(f"video_track:{len(tracks)}")
    items_match, items = base._inner(tracks[track - 1], "Items")
    clips = base.CLIP_RE.findall(items)
    placed = []
    for cut, duration in boundaries:
        left_index = next((index for index in range(len(clips) - 1) if base._number(clips[index], "Start") + base._number(clips[index], "Duration") == base._number(clips[index + 1], "Start") == cut), -1)
        if left_index < 0:
            raise ValueError(f"abutting_boundary:{cut}")
        start = cut - duration // 2
        transition = re.sub(r'DbId="[0-9a-fA-F-]+"', lambda _: f'DbId="{uuid.uuid4()}"', donor_element)
        transition = re.sub(r"<Start>\d+</Start>", f"<Start>{start}</Start>", transition)
        transition = re.sub(r"<Duration>\d+</Duration>", f"<Duration>{duration}</Duration>", transition)
        items = items.replace(clips[left_index], clips[left_index] + transition, 1)
        placed.append({"track": track, "pretty_type": "Blur Dissolve", "start": start, "duration": duration, "end": start + duration, "cut": cut})
    new_track = tracks[track - 1][:items_match.start()] + f"<Items>{items}</Items>" + tracks[track - 1][items_match.end():]
    new_vector = vector.replace(tracks[track - 1], new_track, 1)
    patched = original[:vector_match.start()] + f"<VideoTrackVec>{new_vector}</VideoTrackVec>" + original[vector_match.end():]
    contents[entry] = patched.encode("utf-8")
    if output_timeline_name and output_timeline_name != timeline_name:
        old_name = f"<Name>{html.escape(timeline_name)}</Name>"
        new_name = f"<Name>{html.escape(output_timeline_name)}</Name>"
        folder_entries = [name for name in contents if name.replace("\\", "/").endswith("MpFolder.xml")]
        if len(folder_entries) != 1:
            raise ValueError(f"timeline_name_container:{len(folder_entries)}")
        folder = contents[folder_entries[0]].decode("utf-8-sig")
        if folder.count(old_name) != 2:
            raise ValueError(f"timeline_name_identity:{folder.count(old_name)}")
        contents[folder_entries[0]] = folder.replace(old_name, new_name).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as output:
        for info in infos:
            output.writestr(info, contents[info.filename])
    extracted = [next(iter(ET.fromstring(match.group(0)))) for match in base.TRANSITION_RE.finditer(patched)]
    actual = sorted((int(node.findtext("Start") or -1), int(node.findtext("Duration") or -1)) for node in extracted)
    expected = sorted((cut - duration // 2, duration) for cut, duration in boundaries)
    if actual != expected:
        raise RuntimeError(f"blur_transition_offline_readback:{actual!r}")
    if output_timeline_name and base.select_top_level(target, output_timeline_name)["id"] != timeline_uuid:
        raise RuntimeError("blur_transition_timeline_identity")
    return placed
