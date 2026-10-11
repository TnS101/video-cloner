"""Minimal Python adaptation of the pinned Resolve MCP ``placeTransition``.

Source: samuelgursky/davinci-resolve-mcp@94c7a885d53f13be78522ce96561a9e9e21d64c5
File: resolve-advanced/vendor/drp-format/place-transition.js
License: MIT, Copyright (c) 2025-2026 DaVinci Resolve MCP Contributors and
Bradford Operations LLC. Permission is granted, free of charge, to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies, provided
this notice is included. The software is provided "AS IS", without warranty.

Only the runtime plumbing differs: stdlib zipfile/uuid replace JSZip and
generateUUID. Timeline selection and transition insertion follow the pinned
function's string-surgery mechanism.
"""
from __future__ import annotations

import hashlib
import html
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any


SEQ_ENTRY_RE = re.compile(r"(^|/)SeqContainer(?:\d*\.xml|/[^/]+\.xml)$")
TRACK_RE = re.compile(r"<Element>\s*<Sm2TiTrack\b[\s\S]*?</Sm2TiTrack>\s*</Element>")
CLIP_RE = re.compile(r"<Element>\s*<Sm2Ti(?:VideoClip|AudioClip|Generator)\b[\s\S]*?</Sm2Ti(?:VideoClip|AudioClip|Generator)>\s*</Element>")
TRANSITION_RE = re.compile(r"<Element>\s*<Sm2TiTransition\b[\s\S]*?</Sm2TiTransition>\s*</Element>")

TRANSITION_TEMPLATE = """<Element>
      <Sm2TiTransition DbId="a1ee9cd6-e3ba-4d5c-82a4-2e110fdcdd0a">
       <FieldsBlob>000000020000001c8012190000002c789c6366606400028ee3f30fbf642000006baa031f</FieldsBlob>
       <PrettyType>Cross Dissolve</PrettyType>
       <Name>Cross Dissolve</Name>
       <Start>88104</Start>
       <Duration>24</Duration>
       <LinkedItemSync/>
       <WasDisbanded>false</WasDisbanded>
       <MarkersBA/>
       <UiMemento>0</UiMemento>
       <Flags>0</Flags>
       <PriorityIndex>0</PriorityIndex>
       <EffectFiltersBA>000000020000003a800a37081238024a004a004a004a004a29088b015224ffffffe00000000000000c0000000000000000001800000000000c00000000000000f03f</EffectFiltersBA>
       <ImportExportMetadataBA/>
       <RenderTextEnabled>true</RenderTextEnabled>
       <RenderTextGanged>true</RenderTextGanged>
       <RenderTextPrefixed>true</RenderTextPrefixed>
       <AlignmentType>2</AlignmentType>
       <Position>2</Position>
      </Sm2TiTransition>
     </Element>"""


def _scalar(xml: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>([^<]*)</{tag}>", xml)
    return html.unescape(match.group(1).strip()) if match else None


def _archive(path: Path) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    with zipfile.ZipFile(path) as source:
        infos = source.infolist()
        return infos, {info.filename: source.read(info.filename) for info in infos}


def _text_files(contents: dict[str, bytes]) -> dict[str, str]:
    return {name: value.decode("utf-8-sig") for name, value in contents.items() if name.lower().endswith(".xml")}


def list_sequences(path: Path) -> list[dict[str, Any]]:
    """Resolve timeline names to the exact SeqContainer UUID used by placeTransition."""
    _, contents = _archive(path)
    xmls = _text_files(contents)
    timelines: list[dict[str, Any]] = []
    for entry, xml in xmls.items():
        if not entry.replace("\\", "/").endswith("MpFolder.xml"):
            continue
        for match in re.finditer(r'<Sm2Timeline DbId="([^"]+)">([\s\S]*?)</Sm2Timeline>', xml):
            sequence = re.search(r'<Sm2Sequence DbId="([^"]+)"', match.group(2))
            timelines.append({
                "name": _scalar(match.group(2), "Name"),
                "timeline_id": match.group(1),
                "sequence_id": sequence.group(1) if sequence else None,
            })
    containers = []
    for entry, xml in xmls.items():
        if not SEQ_ENTRY_RE.search(entry.replace("\\", "/")):
            continue
        identifier = re.search(r'<Sm2SequenceContainer DbId="([^"]+)"', xml)
        containers.append({"entry": entry, "id": identifier.group(1) if identifier else None, "xml": xml})
    for row in timelines:
        matches = [container for container in containers if row["sequence_id"] and f'<Sequence>{row["sequence_id"]}</Sequence>' in container["xml"]]
        row.update({"id": matches[0]["id"], "entry": matches[0]["entry"]} if len(matches) == 1 else {"id": None, "entry": None})
    return timelines


def select_top_level(path: Path, timeline_name: str) -> dict[str, Any]:
    matches = [row for row in list_sequences(path) if row["name"] == timeline_name]
    if len(matches) != 1 or not matches[0]["id"]:
        raise ValueError(f"top_level_sequence:{len(matches)}")
    return matches[0]


def _inner(element: str, tag: str) -> tuple[re.Match[str], str]:
    match = re.search(rf"<{tag}>([\s\S]*?)</{tag}>", element)
    if not match:
        raise ValueError(f"missing_{tag}")
    return match, match.group(1)


def _number(xml: str, tag: str) -> int:
    value = re.search(rf"<{tag}>(\d+)</{tag}>", xml)
    if not value:
        raise ValueError(f"missing_{tag}")
    return int(value.group(1))


def place_transition(source: Path, target: Path, *, timeline_name: str, timeline_uuid: str, track: int, at_frame: int, duration_frames: int) -> dict[str, Any]:
    """Insert one centered Cross Dissolve using the pinned placeTransition algorithm."""
    if track < 1 or duration_frames < 2:
        raise ValueError("transition_arguments")
    selected = select_top_level(source, timeline_name)
    if selected["id"] != timeline_uuid:
        raise ValueError(f"top_level_uuid:{selected['id']}")
    infos, contents = _archive(source)
    entry = selected["entry"]
    original = contents[entry].decode("utf-8-sig")
    vector, vector_inner = _inner(original, "VideoTrackVec")
    tracks = TRACK_RE.findall(vector_inner)
    if track > len(tracks):
        raise ValueError(f"video_track:{len(tracks)}")
    items_match, items = _inner(tracks[track - 1], "Items")
    clips = CLIP_RE.findall(items)
    left_index = next((index for index in range(len(clips) - 1) if _number(clips[index], "Start") + _number(clips[index], "Duration") == _number(clips[index + 1], "Start") == at_frame), -1)
    if left_index < 0:
        raise ValueError(f"abutting_boundary:{at_frame}")
    start = at_frame - duration_frames // 2
    if not start < at_frame < start + duration_frames:
        raise ValueError("transition_does_not_straddle_cut")
    transition = re.sub(r'DbId="[0-9a-fA-F-]+"', f'DbId="{uuid.uuid4()}"', TRANSITION_TEMPLATE)
    transition = re.sub(r"<Start>\d+</Start>", f"<Start>{start}</Start>", transition)
    transition = re.sub(r"<Duration>\d+</Duration>", f"<Duration>{duration_frames}</Duration>", transition)
    new_items = items.replace(clips[left_index], clips[left_index] + transition, 1)
    new_track = tracks[track - 1][:items_match.start()] + f"<Items>{new_items}</Items>" + tracks[track - 1][items_match.end():]
    new_vector_inner = vector_inner.replace(tracks[track - 1], new_track, 1)
    patched = original[:vector.start()] + f"<VideoTrackVec>{new_vector_inner}</VideoTrackVec>" + original[vector.end():]
    contents[entry] = patched.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as output:
        for info in infos:
            output.writestr(info, contents[info.filename])
    source_contents = _archive(source)[1]
    target_contents = _archive(target)[1]
    before_count = sum(len(TRANSITION_RE.findall(xml)) for xml in _text_files(source_contents).values())
    after_xmls = _text_files(target_contents)
    after_count = sum(len(TRANSITION_RE.findall(xml)) for xml in after_xmls.values())
    inserted = TRANSITION_RE.findall(after_xmls[entry])
    restored = after_xmls[entry].replace(inserted[0], "", 1) if len(inserted) == 1 else ""
    unchanged = all(contents_before == target_contents[name] for name, contents_before in source_contents.items() if name != entry)
    if before_count != 0 or after_count != 1 or len(inserted) != 1 or restored != original or not unchanged:
        raise RuntimeError("offline_transition_verification")
    return {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "patched_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "timeline_name": timeline_name, "timeline_uuid": timeline_uuid, "entry": entry,
        "transition_count_before": before_count, "transition_count_after": after_count,
        "track": track, "at_frame": at_frame, "start": start, "end": start + duration_frames,
        "duration": duration_frames, "pretty_type": "Cross Dissolve",
        "outside_target_unchanged": unchanged, "target_restores_exactly": restored == original,
    }
