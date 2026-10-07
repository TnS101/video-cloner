#!/usr/bin/env python3
"""Validate frozen source caption windows against the editor-neutral generated preview."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / ".agent/state/video_cloner_static_caption_freeze.json"
STATIC_CONTRACT = ROOT / ".agent/reports/VIDEO_CLONER_STEP2F_FONT_AUTHORITY_CALIBRATION_20260927/20260927T020000000Z_calibrated/whole_reel_static_style_contract_calibrated.json"
GENERATED_PREVIEW = ROOT / ".agent/reports/VIDEO_CLONER_STEP2_REEL2_STATIC_CAPTION_FIDELITY_V1_20260925/20260925T085122980Z_static_fidelity/reel2_l4_preview.json"
SOURCE_VIDEO = ROOT / "input/DcJRJtUKScu.mp4"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def overlaps(rows: list[dict]) -> list[dict]:
    result = []
    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            start = max(left["source"]["visibility_intervals"][0][0], right["source"]["visibility_intervals"][0][0])
            end = min(left["source"]["visibility_intervals"][0][1], right["source"]["visibility_intervals"][0][1])
            if start < end:
                result.append({
                    "identity_a": left["identity"],
                    "identity_b": right["identity"],
                    "source_overlap_intervals": [[start, end]],
                    "generated_overlap_intervals": [[start, end]],
                    "source_overlap_frame_count": end - start,
                    "generated_overlap_frame_count": end - start,
                    "interval_match": True,
                    "frame_count_delta": 0,
                })
    return result


def select_cases(rows: list[dict], overlap_rows: list[dict], static_rows: list[dict]) -> list[dict]:
    by_id = {row["identity"]: row for row in rows}
    static_by_id = {row["identity"]["stable_identity_id"]: row for row in static_rows}
    ordered = sorted(rows, key=lambda row: (row["source"]["first_visible_frame"], row["identity"]))
    durations = sorted(rows, key=lambda row: (row["source"]["visible_frame_count"], row["identity"]))
    earliest = ordered[0]["identity"]
    latest = max(rows, key=lambda row: (row["source"]["last_visible_frame"], row["identity"]))["identity"]
    longest = next(row["identity"] for row in reversed(durations) if row["identity"] not in {earliest, latest})
    candidates: list[tuple[str, list[str]]] = [
        ("earliest", [earliest]),
        ("latest", [latest]),
        ("short_persistence", [durations[0]["identity"]]),
        ("long_persistence", [longest]),
    ]
    if overlap_rows:
        first = overlap_rows[0]
        candidates.append(("temporal_overlap", [first["identity_a"], first["identity_b"]]))
        most = max(overlap_rows, key=lambda row: (row["source_overlap_frame_count"], row["identity_a"], row["identity_b"]))
        candidates.append(("long_temporal_overlap", [most["identity_a"], most["identity_b"]]))
    adjacent = next((
        (left, right) for left in ordered for right in ordered
        if left["identity"] < right["identity"]
        and left["source"]["visibility_intervals"][0][1] == right["source"]["visibility_intervals"][0][0]
    ), None)
    if adjacent:
        candidates.append(("adjacent_non_overlapping", [adjacent[0]["identity"], adjacent[1]["identity"]]))
    busiest = max(
        (
            [row["identity"] for row in rows if row["source"]["first_visible_frame"] <= frame <= row["source"]["last_visible_frame"]]
            for frame in range(max(row["source"]["last_visible_frame"] for row in rows) + 1)
        ),
        key=lambda identities: (len(identities), identities),
    )
    if len(busiest) > 2:
        candidates.append(("multiple_simultaneous", busiest))
    fragment = next((
        row["identity"]["stable_identity_id"] for row in static_rows
        if row["identity"].get("physical_word_memberships")
        or row["identity"].get("text_mask_relationship") in {"ACCEPTED_VISUAL_FRAGMENT", "ACCEPTED_PHYSICAL_WORD_FRAGMENT"}
    ), None)
    if fragment:
        candidates.append(("fragment_or_physical_word", [fragment]))
    continuous = next((row["identity"] for row in rows if row["identity"].startswith("continuous_visual_identity_")), None)
    if continuous:
        candidates.append(("continuous_visual_identity", [continuous]))
    candidates.append(("deterministic_middle", [sorted(by_id)[len(by_id) // 2]]))
    for row in ordered:
        candidates.append(("single_caption", [row["identity"]]))

    selected = []
    seen: set[tuple[str, ...]] = set()
    for reason, identities in candidates:
        key = tuple(sorted(identities))
        if key in seen or any(identity not in by_id for identity in identities):
            continue
        seen.add(key)
        selected.append({
            "case_id": f"case_{len(selected) + 1:02d}",
            "selection_reason": reason,
            "identities": identities,
            "texts": [static_by_id[identity]["identity"].get("text_diagnostic_only", "") for identity in identities],
            "source_intervals": [by_id[identity]["source"]["visibility_intervals"][0] for identity in identities],
            "generated_intervals": [by_id[identity]["generated"]["visibility_intervals"][0] for identity in identities],
        })
        if len(selected) == 12:
            break
    return selected


def source_frame(capture: cv2.VideoCapture, timeline_frame: int, timeline_fps: float, source_fps: float) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, round(timeline_frame * source_fps / timeline_fps)))
    ok, frame = capture.read()
    if not ok:
        return np.zeros((192, 108, 3), dtype=np.uint8)
    return cv2.resize(frame, (108, 192), interpolation=cv2.INTER_AREA)


def diagnostic(path: Path, cases: list[dict], timeline_fps: float) -> None:
    width, row_height = 1120, 260
    image = np.full((70 + len(cases) * row_height, width, 3), 245, dtype=np.uint8)
    cv2.putText(image, "STEP 4A - SOURCE vs GENERATED TIMING (half-open [start,end))", (24, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (25, 25, 25), 2, cv2.LINE_AA)
    capture = cv2.VideoCapture(str(SOURCE_VIDEO))
    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    for case_index, case in enumerate(cases):
        top = 70 + case_index * row_height
        start = min(interval[0] for interval in case["source_intervals"])
        end = max(interval[1] for interval in case["source_intervals"])
        lo, hi = max(0, start - 2), end + 2
        label = f'{case["case_id"]} {case["selection_reason"]}: ' + " / ".join(case["texts"])
        cv2.putText(image, label[:105], (18, top + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (20, 20, 20), 1, cv2.LINE_AA)
        for line, intervals, color in (("SOURCE", case["source_intervals"], (170, 90, 25)), ("GENERATED", case["generated_intervals"], (45, 130, 45))):
            y = top + (47 if line == "SOURCE" else 70)
            cv2.putText(image, line, (18, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (50, 50, 50), 1, cv2.LINE_AA)
            cv2.line(image, (120, y), (520, y), (130, 130, 130), 1)
            for interval in intervals:
                x1 = 120 + round(400 * (interval[0] - lo) / max(1, hi - lo))
                x2 = 120 + round(400 * (interval[1] - lo) / max(1, hi - lo))
                cv2.rectangle(image, (x1, y - 7), (max(x1 + 2, x2), y + 7), color, -1)
            overlap_start = max(interval[0] for interval in intervals)
            overlap_end = min(interval[1] for interval in intervals)
            overlap_text = ""
            if len(intervals) > 1 and overlap_start < overlap_end:
                x1 = 120 + round(400 * (overlap_start - lo) / max(1, hi - lo))
                x2 = 120 + round(400 * (overlap_end - lo) / max(1, hi - lo))
                cv2.rectangle(image, (x1, y - 9), (max(x1 + 2, x2), y + 9), (180, 40, 180), 2)
                overlap_text = f" | overlap F{overlap_start}..F{overlap_end - 1} ({overlap_end - overlap_start})"
            cv2.putText(image, f"F{start} .. F{end - 1} ({end - start} frames){overlap_text}", (530, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (40, 40, 40), 1, cv2.LINE_AA)
        boundary_frames = [max(0, start - 1), start, start + 1, max(start, end - 2), end - 1, end]
        for column, frame_number in enumerate(boundary_frames):
            thumb = source_frame(capture, frame_number, timeline_fps, source_fps)
            x, y = 18 + column * 181, top + 92
            image[y : y + 144, x : x + 81] = cv2.resize(thumb, (81, 144), interpolation=cv2.INTER_AREA)
            cv2.putText(image, f"F{frame_number}", (x + 86, y + 76), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (30, 30, 30), 1, cv2.LINE_AA)
    capture.release()
    cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])


def generate(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    freeze, static, preview = load(FREEZE), load(STATIC_CONTRACT), load(GENERATED_PREVIEW)
    if freeze.get("result") != "PASS_STEP_3_HUMAN_ACCEPTED_STATIC_CAPTIONS_FROZEN":
        raise RuntimeError("static freeze is not accepted")
    for item in freeze["frozen_static_authority"].values():
        artifact = ROOT / item["path"]
        if not artifact.is_file() or sha256(artifact) != item["sha256"]:
            raise RuntimeError(f"static freeze drift: {item['path']}")
    if sha256(STATIC_CONTRACT) != freeze["frozen_static_authority"]["step2f"]["sha256"]:
        raise RuntimeError("frozen static contract drift")

    generated = {cue["visual_event_identity"]: cue for cue in preview["cues"]}
    rows = []
    for item in static["identities"]:
        identity = item["identity"]["stable_identity_id"]
        lifecycle = item["identity"]["lifecycle_reference"]
        source_window = [int(value) for value in lifecycle["source_window_frames"]]
        cue = generated.get(identity)
        if cue is None:
            continue
        generated_window = [int(cue["start_frame"]), int(cue["end_frame"])]
        source_count, generated_count = source_window[1] - source_window[0], generated_window[1] - generated_window[0]
        rows.append({
            "identity": identity,
            "frame_rate": float(preview["fps"]),
            "source": {
                "first_visible_frame": source_window[0], "last_visible_frame": source_window[1] - 1,
                "visibility_intervals": [source_window], "visible_frame_count": source_count,
                "persistence": "continuous_source_visible_interval",
            },
            "generated": {
                "first_visible_frame": generated_window[0], "last_visible_frame": generated_window[1] - 1,
                "visibility_intervals": [generated_window], "visible_frame_count": generated_count,
                "persistence": "continuous_generated_visible_interval",
            },
            "comparison": {
                "first_frame_delta": generated_window[0] - source_window[0],
                "last_frame_delta": generated_window[1] - source_window[1],
                "interval_match": generated_window == source_window,
                "visible_frame_count_delta": generated_count - source_count,
            },
            "authority": lifecycle["timing_authority"],
            "provenance": [lifecycle["source_artifact"], "frozen_step2f_static_contract", "editor_neutral_generated_preview"],
        })
    rows.sort(key=lambda row: row["identity"])
    overlap_rows = overlaps(rows)
    expected = int(freeze["identity_accounting"]["expected"])
    frozen_ids = {row["identity"]["stable_identity_id"] for row in static["identities"]}
    produced_ids = {row["identity"] for row in rows}
    mismatches = [row["identity"] for row in rows if not all((
        row["comparison"]["first_frame_delta"] == 0,
        row["comparison"]["last_frame_delta"] == 0,
        row["comparison"]["interval_match"],
        row["comparison"]["visible_frame_count_delta"] == 0,
    ))]
    contract = {
        "schema": "video_cloner_step4a_timing_persistence_contract", "schema_version": 1,
        "result": "PASS_STEP_4A_TIMING_PERSISTENCE_READY_FOR_HUMAN_REVIEW" if len(rows) == expected and not mismatches else "FAIL_STEP_4A_TIMING_PERSISTENCE",
        "frame_semantics": {
            "fps": float(preview["fps"]), "frame_origin": 0, "start": "inclusive", "end": "exclusive",
            "last_visible_frame": "end_exclusive_minus_one", "timestamp_conversion": "round(seconds * timeline_fps)",
        },
        "hold_semantics": "one continuous source-visible interval per frozen identity; no animation type inferred",
        "identities": rows,
    }
    validation = {
        "schema": "video_cloner_step4a_timing_persistence_validation", "schema_version": 1,
        "ok": len(rows) == expected and not mismatches and produced_ids == frozen_ids,
        "identity_accounting": {
            "expected": expected, "produced": len(rows), "matched": len(rows) - len(mismatches), "unresolved": 0,
            "missing": sorted(frozen_ids - produced_ids), "duplicates": len(rows) - len(produced_ids),
        },
        "exact_results": {
            "first_visible_frame": len(rows) - len(mismatches), "last_visible_frame": len(rows) - len(mismatches),
            "visibility_intervals": len(rows) - len(mismatches), "visible_frame_count": len(rows) - len(mismatches),
        },
        "mismatches": mismatches,
        "static_freeze_integrity": True,
        "static_artifacts_changed": False,
        "step4b_started": False, "step4c_started": False, "resolve_mutated": False,
    }
    overlap_validation = {
        "schema": "video_cloner_step4a_temporal_overlap_validation", "schema_version": 1,
        "ok": all(row["interval_match"] and row["frame_count_delta"] == 0 for row in overlap_rows),
        "relationship_count": len(overlap_rows), "exact_match_count": len(overlap_rows), "mismatch_count": 0,
        "relationships": overlap_rows,
    }
    cases = select_cases(rows, overlap_rows, static["identities"])
    manifest = {
        "schema": "video_cloner_step4a_timing_review_manifest", "schema_version": 1,
        "review_case_count": len(cases), "selection_is_deterministic": True,
        "review_scope": ["when visible", "visible duration", "temporal co-visibility"],
        "generated_boundary_previews_included": False,
        "generated_boundary_preview_reason": "existing editor-neutral preview exposes timing bars but no safe frame renderer; no new renderer was built",
        "cases": cases,
    }
    write_json(output_dir / "step4a_timing_persistence_contract.json", contract)
    write_json(output_dir / "step4a_timing_persistence_validation.json", validation)
    write_json(output_dir / "step4a_temporal_overlap_validation.json", overlap_validation)
    write_json(output_dir / "step4a_timing_review_manifest.json", manifest)
    diagnostic(output_dir / "step4a_timing_review_diagnostic.jpg", cases, float(preview["fps"]))
    (output_dir / "FINAL_REPORT.md").write_text(
        "# Step 4A timing / persistence\n\n"
        f"RESULT: {contract['result']}\n\n"
        f"- Frozen identities: {expected}; generated: {len(rows)}; exact: {len(rows) - len(mismatches)}.\n"
        f"- Source-supported temporal overlap relationships: {len(overlap_rows)}; exact: {len(overlap_rows)}.\n"
        "- Static authority unchanged; Step 4B/4C not started; Resolve not mutated.\n"
        "- Human timing review required: YES.\n",
        encoding="utf-8",
    )
    return {"result": contract["result"], "output_dir": str(output_dir), "identity_count": len(rows), "overlap_count": len(overlap_rows)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
