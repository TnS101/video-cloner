from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from typing import Mapping, Sequence

from scripts.davinci import compile_davinci_textplus_fcpxml as canonical


REPORT_SCHEMA = "video_cloner.standalone_textplus.v1"


class StandaloneTextplusError(RuntimeError):
    pass


def _read(path: str | Path, label: str) -> tuple[Path, dict]:
    resolved = Path(path).expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise StandaloneTextplusError(f"missing or malformed {label}: {resolved}") from error
    if not isinstance(value, dict):
        raise StandaloneTextplusError(f"{label} must be a JSON object")
    return resolved, value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_cue_id(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return f"sub_{int(digits):03d}" if digits and int(digits) > 0 else ""


def _source_evidence(event: Mapping[str, object]) -> dict[str, object] | None:
    raw = event.get("raw") if isinstance(event.get("raw"), Mapping) else event
    observed_values = raw.get("observed_texts")
    if not isinstance(observed_values, list):
        return None
    observed = [canonical.norm_text(value) for value in observed_values if canonical.norm_text(value)]
    semantic = [canonical.normalize_semantic_caption_text(value) for value in observed]
    if len(semantic) < 2 or not semantic[0] or len(set(semantic)) != 1:
        return None
    selected = canonical.norm_text(raw.get("observed_text"))
    if canonical.normalize_semantic_caption_text(selected) != semantic[0]:
        return None
    confidence = raw.get("confidence") if isinstance(raw.get("confidence"), Mapping) else {}
    return {
        "event_id": str(raw.get("event_id") or event.get("id") or ""),
        "cue_id": _source_cue_id(raw.get("cue_id") or event.get("cue_id")),
        "observed_text": selected,
        "observed_texts": observed,
        "start": event.get("start"),
        "end": event.get("end"),
        "confidence": dict(confidence),
    }


def _event_proposal(
    event: Mapping[str, object],
    cues: Sequence[Mapping[str, object]],
    cue_index: int,
) -> dict[str, object] | None:
    evidence = _source_evidence(event)
    if evidence is None:
        return None
    observed = str(evidence["observed_text"])
    observed_semantic = canonical.normalize_semantic_caption_text(observed)
    transcript = canonical.norm_text(cues[cue_index].get("text"))
    transcript_semantic = canonical.normalize_semantic_caption_text(transcript)

    if observed_semantic == transcript_semantic:
        text = observed if observed.casefold() == transcript.casefold() else transcript
        return {
            "start": cue_index,
            "end": cue_index,
            "text": text,
            "decision": "source_exact",
            "evidence": evidence,
        }

    # A source composite must be a single rendered token whose semantic text is
    # exactly the concatenation of adjacent transcript cues ending at this cue.
    if not any(character.isspace() for character in observed):
        combined = transcript_semantic
        for start in range(cue_index - 1, -1, -1):
            combined = canonical.normalize_semantic_caption_text(cues[start].get("text")) + combined
            if combined == observed_semantic:
                return {
                    "start": start,
                    "end": cue_index,
                    "text": observed,
                    "decision": "source_composite",
                    "evidence": evidence,
                }
            if len(combined) >= len(observed_semantic):
                break

    transcript_words = transcript.split()
    observed_words = observed.split()
    if (
        len(transcript_words) == len(observed_words) == 1
        and transcript_semantic.isalpha()
        and observed_semantic.isalpha()
        and SequenceMatcher(None, transcript_semantic, observed_semantic).ratio() >= 0.70
    ):
        return {
            "start": cue_index,
            "end": cue_index,
            "text": observed,
            "decision": "source_corrected",
            "evidence": evidence,
        }
    return None


def validate_caption_authority(
    cues: Sequence[Mapping[str, object]], source_ids: Sequence[str]
) -> dict[str, object]:
    expected = list(source_ids)
    position = {cue_id: index for index, cue_id in enumerate(expected)}
    if not expected or len(position) != len(expected) or any(not cue_id for cue_id in expected):
        raise StandaloneTextplusError("generic caption source IDs are empty or duplicated")
    flattened: list[str] = []
    authority_ids: list[str] = []
    for cue in cues:
        cue_id = str(cue.get("id") or "")
        coverage = cue.get("source_cue_ids")
        text = canonical.norm_text(cue.get("text"))
        if not cue_id or not text or not isinstance(coverage, list) or not coverage:
            raise StandaloneTextplusError("caption authority cue is malformed")
        covered = [str(value) for value in coverage]
        if any(value not in position for value in covered):
            raise StandaloneTextplusError("caption authority references an unknown source cue")
        reconciliation = cue.get("reconciliation")
        if not isinstance(reconciliation, Mapping):
            raise StandaloneTextplusError("caption authority reconciliation is missing")
        decision = str(reconciliation.get("decision") or "")
        if decision not in {"transcript_fallback", "source_exact", "source_corrected", "source_composite"}:
            raise StandaloneTextplusError("caption authority reconciliation decision is unsupported")
        evidence = reconciliation.get("evidence")
        if decision != "transcript_fallback" and (not isinstance(evidence, list) or not evidence):
            raise StandaloneTextplusError("caption authority semantic correction has no source evidence")
        if decision == "source_composite" and len(covered) < 2:
            raise StandaloneTextplusError("caption authority composite does not cover multiple source cues")
        if decision != "source_composite" and len(covered) != 1:
            raise StandaloneTextplusError("caption authority non-composite covers multiple source cues")
        if decision in {"source_exact", "source_corrected", "source_composite"}:
            observed = [row for row in evidence if isinstance(row, Mapping) and canonical.normalize_semantic_caption_text(row.get("observed_text")) == canonical.normalize_semantic_caption_text(text)]
            if not observed:
                raise StandaloneTextplusError("caption authority text is not supported by its source evidence")
        indexes = [position[value] for value in covered]
        if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            raise StandaloneTextplusError("caption authority many-to-one coverage is not adjacent")
        authority_ids.append(cue_id)
        flattened.extend(covered)
    if len(set(authority_ids)) != len(authority_ids):
        raise StandaloneTextplusError("caption authority IDs are duplicated")
    if flattened != expected:
        raise StandaloneTextplusError("caption authority source coverage is duplicated, dropped, or reordered")
    return {
        "source_cue_count": len(expected),
        "authority_cue_count": len(cues),
        "source_coverage_count": len(flattened),
        "source_coverage_exact": True,
    }


def derive_caption_authority(
    raw_cues: Sequence[Mapping[str, object]],
    style_data: Mapping[str, object],
    fps: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    source_ids = [str(cue.get("id") or "") for cue in raw_cues]
    by_id = {cue_id: index for index, cue_id in enumerate(source_ids)}
    proposals: dict[int, list[dict[str, object]]] = {}
    for event in canonical.extract_caption_style_events(dict(style_data), fps=fps):
        cue_id = _source_cue_id(event.get("cue_id"))
        if cue_id not in by_id:
            continue
        proposal = _event_proposal(event, raw_cues, by_id[cue_id])
        if proposal is not None:
            proposals.setdefault(int(proposal["start"]), []).append(proposal)

    authority: list[dict[str, object]] = []
    cursor = 0
    while cursor < len(raw_cues):
        candidates = proposals.get(cursor, [])
        distinct = {
            (int(row["end"]), str(row["text"]), str(row["decision"]))
            for row in candidates
        }
        selected = candidates[0] if len(distinct) == 1 else None
        end = int(selected["end"]) if selected is not None else cursor
        covered = source_ids[cursor : end + 1]
        first = raw_cues[cursor]
        last = raw_cues[end]
        cue = dict(first)
        cue.update({
            "id": covered[0],
            "index": len(authority) + 1,
            "text": str(selected["text"]) if selected is not None else canonical.norm_text(first.get("text")),
            "start": first.get("start"),
            "end": last.get("end"),
            "start_frame": first.get("start_frame"),
            "end_frame": last.get("end_frame"),
            "source_cue_ids": covered,
            "reconciliation": {
                "decision": str(selected["decision"]) if selected is not None else "transcript_fallback",
                "evidence": [selected["evidence"]] if selected is not None else [],
            },
        })
        raw = dict(first.get("raw") or {})
        raw["timeline_start_frame"] = cue["start_frame"]
        raw["timeline_end_frame"] = cue["end_frame"]
        cue["raw"] = raw
        cue["duration"] = round(float(cue["end"]) - float(cue["start"]), 6)
        cue["duration_frames"] = int(cue["end_frame"]) - int(cue["start_frame"])
        authority.append(cue)
        cursor = end + 1

    summary = validate_caption_authority(authority, source_ids)
    decisions: dict[str, int] = {}
    for cue in authority:
        decision = str((cue.get("reconciliation") or {}).get("decision"))
        decisions[decision] = decisions.get(decision, 0) + 1
    return authority, {
        "schema": "video_cloner.caption_authority.v1",
        "schema_version": 1,
        "summary": {**summary, "decision_counts": dict(sorted(decisions.items()))},
        "cues": authority,
    }


def _overlap_pairs(cues: Sequence[Mapping[str, object]]) -> int:
    ordered = sorted(cues, key=lambda cue: (int(cue["start_frame"]), int(cue["end_frame"])))
    return sum(
        1
        for index, left in enumerate(ordered)
        for right in ordered[index + 1 :]
        if int(right["start_frame"]) < int(left["end_frame"])
    )


def _authority_overlap_pairs(cues: Sequence[Mapping[str, object]], lifecycle: Mapping[str, object]) -> int:
    by_layer = {f"caption_layer_{cue['id']}": cue for cue in cues}
    pairs = lifecycle.get("visual_overlap_pairs")
    if not isinstance(pairs, list) or len({tuple(pair) for pair in pairs if isinstance(pair, list)}) != len(pairs):
        raise StandaloneTextplusError("caption lifecycle overlap authority is missing or duplicated")
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or pair[0] not in by_layer or pair[1] not in by_layer:
            raise StandaloneTextplusError("caption lifecycle overlap pair references an unknown cue")
        left, right = by_layer[pair[0]], by_layer[pair[1]]
        if int(left["start_frame"]) >= int(right["end_frame"]) or int(right["start_frame"]) >= int(left["end_frame"]):
            raise StandaloneTextplusError("caption lifecycle overlap pair is not present in emitted timing")
    expected = (lifecycle.get("summary") or {}).get("visual_concurrent_overlap_pair_count")
    if expected != len(pairs):
        raise StandaloneTextplusError("caption lifecycle overlap summary does not match its pair authority")
    return len(pairs)


def validate_caption_cues(cues: Sequence[Mapping[str, object]], expected_ids: Sequence[str]) -> dict[str, object]:
    ids = [str(cue.get("id") or "") for cue in cues]
    if ids != list(expected_ids) or len(set(ids)) != len(ids):
        raise StandaloneTextplusError("caption cue IDs/order/cardinality do not match caption authority")

    lane_intervals: dict[int, list[tuple[int, int]]] = {}
    for cue in cues:
        lane = int(cue.get("lane") or 1)
        lane_intervals.setdefault(lane, []).append((int(cue["start_frame"]), int(cue["end_frame"])))
    same_lane_overlaps = 0
    for intervals in lane_intervals.values():
        intervals.sort()
        same_lane_overlaps += sum(current[0] < previous[1] for previous, current in zip(intervals, intervals[1:]))
    if same_lane_overlaps:
        raise StandaloneTextplusError(f"same-lane caption overlaps: {same_lane_overlaps}")

    return {
        "semantic_cue_count": len(cues),
        "overlap_pair_count": _overlap_pairs(cues),
        "same_lane_overlap_count": same_lane_overlaps,
        "lane_usage": {str(lane): len(lane_intervals[lane]) for lane in sorted(lane_intervals)},
    }


def prepare_textplus_authority(
    generic: Mapping[str, object],
    style_data: Mapping[str, object],
    lifecycle: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if generic.get("success") is not True or generic.get("schema") != "generic_edit_commands":
        raise StandaloneTextplusError("generic command authority is invalid")
    fps = canonical.extract_fps(dict(generic), fallback=24.0)
    raw_cues, source_info = canonical.extract_subtitle_cues(dict(generic), source="subtitle_clips", fps=fps)
    generic_ids = [str(row.get("subtitle_id") or "") for row in generic.get("subtitle_clips", []) if isinstance(row, dict)]
    if len(raw_cues) != len(generic_ids) or not raw_cues:
        raise StandaloneTextplusError("generic captions are missing or malformed")
    base_cues = canonical.enforce_timing_rules(raw_cues, fps=fps, min_duration_frames=1, prevent_overlap=True)
    authority_cues, caption_authority = derive_caption_authority(base_cues, style_data, fps)
    expected_ids = [str(row["id"]) for row in authority_cues]
    cues = canonical.enforce_timing_rules(authority_cues, fps=fps, min_duration_frames=1, prevent_overlap=True)

    lifecycle_info: dict[str, object] = {"enabled": False}
    if lifecycle is not None:
        try:
            cues, lifecycle_info = canonical.apply_caption_lifecycle_plan(cues, dict(lifecycle), fps=fps, base_lane=1)
        except ValueError as error:
            raise StandaloneTextplusError(str(error)) from error

    metrics = validate_caption_cues(cues, expected_ids)
    metrics["all_interval_overlap_pair_count"] = metrics.pop("overlap_pair_count")
    metrics["overlap_pair_count"] = _authority_overlap_pairs(cues, lifecycle) if lifecycle else 0
    source_text = {str(cue.get("id")): canonical.norm_text(cue.get("text")) for cue in raw_cues}
    casing_differences = [
        {"cue_id": coverage[0], "generic": source_text[coverage[0]], "output": output}
        for cue in cues
        for coverage in [list(cue.get("source_cue_ids") or [])]
        for output in [canonical.norm_text(cue.get("text"))]
        if (
            len(coverage) == 1
            and source_text[coverage[0]] != output
            and canonical.normalize_semantic_caption_text(source_text[coverage[0]])
            == canonical.normalize_semantic_caption_text(output)
        )
    ]
    metrics.update({
        "dropped_semantic_words": 0,
        "added_semantic_words": 0,
        "casing_difference_count": len(casing_differences),
        "casing_differences": casing_differences,
        "lifecycle_timing_change_count": int(lifecycle_info.get("lifecycle_differs_from_transcript_count", 0)),
    })

    style = canonical.extract_style_contract(dict(style_data), profile_id="primary", overrides={})
    cue_styles, style_info = canonical.assign_style_events_to_cues(
        cues, dict(style_data), style, {}, fps, enabled=True, match_window_sec=1.25, min_match_score=0.12
    )
    return {
        "fps": fps,
        "cues": cues,
        "style": style,
        "cue_styles": cue_styles,
        "caption_source": source_info,
        "caption_authority": caption_authority,
        "caption_lifecycle": lifecycle_info,
        "caption_metrics": metrics,
        "style_event_matches": style_info.get("matched_cue_count", 0),
    }


def compile_textplus(
    generic_path: str | Path,
    caption_style_path: str | Path,
    output_fcpxml: str | Path,
    report_path: str | Path,
    lifecycle_path: str | Path | None = None,
    timeline_name: str | None = None,
) -> dict[str, object]:
    generic_file, generic = _read(generic_path, "generic commands")
    style_file, style_data = _read(caption_style_path, "caption style")
    lifecycle_file: Path | None = None
    lifecycle: dict | None = None
    if lifecycle_path is not None:
        lifecycle_file, lifecycle = _read(lifecycle_path, "caption lifecycle authority")
    prepared = prepare_textplus_authority(generic, style_data, lifecycle)
    fps = float(prepared["fps"])
    cues = prepared["cues"]
    style = prepared["style"]
    cue_styles = prepared["cue_styles"]
    name = timeline_name or f"{generic.get('video_id', generic_file.stem)}_standalone_textplus"
    xml = canonical.build_caption_only_fcpxml(
        cues, style, cue_styles, fps, 1080, 1920, name, "VC Caption", "1.10",
        canonical.DEFAULT_BASIC_TITLE_UID, 1, "reset", 0.0, 0.0,
    )
    xml_bytes = xml.encode("utf-8")
    root = ET.fromstring(xml_bytes)
    titles = root.findall(".//title")
    if len(titles) != len(cues):
        raise StandaloneTextplusError("canonical Text+ output dropped captions")

    output = Path(output_fcpxml).expanduser().resolve()
    report_file = Path(report_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(xml_bytes)
    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "success": True,
        "video_id": generic.get("video_id"),
        "inputs": {
            "generic": str(generic_file),
            "generic_sha256": _sha256_bytes(generic_file.read_bytes()),
            "caption_style": str(style_file),
            "caption_style_sha256": _sha256_bytes(style_file.read_bytes()),
            "caption_lifecycle": str(lifecycle_file) if lifecycle_file else None,
            "caption_lifecycle_sha256": _sha256_bytes(lifecycle_file.read_bytes()) if lifecycle_file else None,
        },
        "caption_source": prepared["caption_source"],
        "caption_authority": prepared["caption_authority"],
        "caption_lifecycle": prepared["caption_lifecycle"],
        "caption_metrics": prepared["caption_metrics"],
        "style_event_matches": prepared["style_event_matches"],
        "output": {"fcpxml": str(output), "sha256": _sha256_bytes(xml_bytes), "title_count": len(titles)},
        "canonical_textplus_compiler": str(Path(canonical.__file__).resolve()),
        "edit_operations_compiled": False,
        "resolve_invoked": False,
        "timeline_mutated": False,
        "save_project_invoked": False,
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile standalone editable Text+ captions without edit operations or Resolve.")
    parser.add_argument("--generic", required=True)
    parser.add_argument("--caption-style", required=True)
    parser.add_argument("--caption-lifecycle-plan")
    parser.add_argument("--output-fcpxml", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--timeline-name")
    args = parser.parse_args(argv)
    try:
        report = compile_textplus(
            args.generic, args.caption_style, args.output_fcpxml, args.report,
            args.caption_lifecycle_plan, args.timeline_name,
        )
    except StandaloneTextplusError as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
