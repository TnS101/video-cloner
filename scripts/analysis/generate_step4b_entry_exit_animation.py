#!/usr/bin/env python3
"""Generate evidence-backed boundary-local caption animation authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
STATIC_FREEZE = ROOT / ".agent/state/video_cloner_static_caption_freeze.json"
TIMING_FREEZE = ROOT / ".agent/state/video_cloner_timing_persistence_freeze.json"
STATIC_CONTRACT = ROOT / ".agent/reports/VIDEO_CLONER_STEP2F_FONT_AUTHORITY_CALIBRATION_20260927/20260927T020000000Z_calibrated/whole_reel_static_style_contract_calibrated.json"
TIMING_CONTRACT = ROOT / ".agent/reports/VIDEO_CLONER_STEP4A_TIMING_PERSISTENCE_20260927/20260927T122000000Z_human_review_ready/step4a_timing_persistence_contract.json"
SOURCE_VIDEO = ROOT / "input/DcJRJtUKScu.mp4"
FPS = 24.0
SLIDE_MIN = 0.012  # Existing Step 3C normalizer threshold.
SCALE_MIN = 0.055  # Existing Step 3C normalizer threshold.


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def verify_freezes() -> dict:
    static, timing = load(STATIC_FREEZE), load(TIMING_FREEZE)
    if static.get("result") != "PASS_STEP_3_HUMAN_ACCEPTED_STATIC_CAPTIONS_FROZEN":
        raise RuntimeError("static freeze is not accepted")
    if timing.get("result") != "PASS_STEP_4A_HUMAN_ACCEPTED_TIMING_PERSISTENCE_FROZEN":
        raise RuntimeError("Step 4A freeze is not accepted")
    for group in (static["frozen_static_authority"], timing["frozen_timing_authority"]):
        for item in group.values():
            if not isinstance(item, dict) or "path" not in item:
                continue
            path = ROOT / item["path"]
            if not path.is_file() or sha256(path) != item["sha256"]:
                raise RuntimeError(f"frozen artifact drift: {item['path']}")
    if sha256(STATIC_FREEZE) != timing["static_freeze"]["sha256"]:
        raise RuntimeError("static freeze hash drift")
    return {
        "static_freeze_sha256": sha256(STATIC_FREEZE),
        "timing_freeze_sha256": sha256(TIMING_FREEZE),
        "static_contract_sha256": sha256(STATIC_CONTRACT),
        "timing_contract_sha256": sha256(TIMING_CONTRACT),
    }


def observations(static_row: dict) -> list[dict]:
    result = []
    for row in static_row["geometry"]["accepted_source_observations"]:
        x1, y1, x2, y2 = map(float, row["bbox"])
        result.append({
            "frame": round(float(row["timestamp"]) * FPS),
            "center": [(x1 + x2) / 2160.0, (y1 + y2) / 3840.0],
            "scale": math.sqrt(max(1.0, (x2 - x1) * (y2 - y1))),
            "source_frame": int(row["source_frame"]),
            "crop_sha256": row["crop_sha256"],
        })
    unique = {}
    for row in result:
        unique[row["frame"]] = row
    return [unique[key] for key in sorted(unique)]


def classify_boundary(points: list[dict], start: int, end: int, side: str) -> dict:
    boundary_frame = start if side == "entry" else end - 1
    fallback_interval = [start, min(end, start + 1)] if side == "entry" else [max(start, end - 1), end]
    if end - start <= 6:
        return unresolved(fallback_interval, "entry_exit_windows_overlap", points)
    lo, hi = ((start, min(end - 1, start + 5)) if side == "entry" else (max(start, end - 6), end - 1))
    local = [row for row in points if lo <= row["frame"] <= hi]
    covered = local and (local[0]["frame"] <= start + 1 if side == "entry" else local[-1]["frame"] >= end - 2)
    if len(local) < 2 or not covered:
        return unresolved(fallback_interval, "insufficient_boundary_observations", local)
    first, last = local[0], local[-1]
    slide = math.dist(first["center"], last["center"])
    scale = abs(last["scale"] / first["scale"] - 1.0)
    interval = [first["frame"], min(end, last["frame"] + 1)]
    provenance = evidence(local)
    if slide < SLIDE_MIN and scale < SCALE_MIN:
        return unresolved(fallback_interval, "abrupt_visibility_transition_not_proven", local)
    if slide >= SLIDE_MIN and scale >= SCALE_MIN:
        return unresolved(interval, "mixed_scale_and_slide_boundary_evidence", local)
    if len(local) < 3:
        return unresolved(interval, "boundary_locality_not_proven", local)
    stable_pair = local[-2:] if side == "entry" else local[:2]
    stable_slide = math.dist(stable_pair[0]["center"], stable_pair[1]["center"])
    stable_scale = abs(stable_pair[1]["scale"] / stable_pair[0]["scale"] - 1.0)
    if stable_slide >= SLIDE_MIN or stable_scale >= SCALE_MIN:
        return unresolved(interval, "motion_not_localized_to_boundary", local)
    if slide >= SLIDE_MIN:
        anchor = last["center"] if side == "entry" else first["center"]
        values = [[round(row["center"][0] - anchor[0], 8), round(row["center"][1] - anchor[1], 8)] for row in local]
        kind, parameters = "slide", {"property": "Center", "keyframes": keyframes(local, values)}
    else:
        anchor = last["scale"] if side == "entry" else first["scale"]
        values = [round(row["scale"] / anchor, 8) for row in local]
        kind, parameters = "scale", {"property": "Size", "keyframes": keyframes(local, values)}
    return {
        "type": kind, "start_frame": interval[0], "end_frame": interval[1],
        "parameters": parameters, "confidence": "high", "authority": "AUTHORITATIVE",
        "status": "SUPPORTED_MATCHED", "provenance": provenance,
    }


def keyframes(points: list[dict], values: list[object]) -> list[dict]:
    first, span = points[0]["frame"], max(1, points[-1]["frame"] - points[0]["frame"])
    return [
        {"frame": row["frame"], "relative_time": round((row["frame"] - first) / span, 6), "value": value}
        for row, value in zip(points, values)
    ]


def evidence(points: list[dict]) -> list[dict]:
    return [{"source_frame": row["source_frame"], "timeline_frame": row["frame"], "crop_sha256": row["crop_sha256"]} for row in points]


def unresolved(interval: list[int], reason: str, points: list[dict]) -> dict:
    return {
        "type": "unresolved", "start_frame": interval[0], "end_frame": interval[1],
        "parameters": {}, "confidence": "low", "authority": "UNRESOLVED",
        "status": "UNRESOLVED", "reason": reason, "provenance": evidence(points),
    }


def select_cases(rows: list[dict]) -> list[dict]:
    selected, seen = [], set()
    for kind in ("slide", "scale", "abrupt", "unresolved"):
        for side in ("entry", "exit"):
            row = next((item for item in rows if item[side]["type"] == kind), None)
            if row and row["identity"] not in seen:
                selected.append({"identity": row["identity"], "text": row["text_diagnostic_only"], "side": side, "decision": row[side]})
                seen.add(row["identity"])
    for row in sorted(rows, key=lambda item: (item["visibility_interval"][1] - item["visibility_interval"][0], item["identity"])):
        if row["identity"] not in seen:
            selected.append({"identity": row["identity"], "text": row["text_diagnostic_only"], "side": "entry", "decision": row["entry"]})
            seen.add(row["identity"])
        if len(selected) == 12:
            break
    return selected[:12]


def diagnostic(cases: list[dict], abrupt_correction: dict) -> bytes:
    width, row_height = 1120, 210
    image = np.full((80 + len(cases) * row_height, width, 3), 245, dtype=np.uint8)
    cv2.putText(image, "STEP 4B - SOURCE BOUNDARIES / EDITOR-NEUTRAL REPRODUCTION", (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.putText(image, f"ABRUPT {abrupt_correction['before']} -> {abrupt_correction['after']} | DOWNGRADED {abrupt_correction['downgraded']} | geometry alone fails closed", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (20, 20, 150), 1, cv2.LINE_AA)
    capture = cv2.VideoCapture(str(SOURCE_VIDEO))
    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    for index, case in enumerate(cases):
        top = 80 + index * row_height
        decision = case["decision"]
        label = f'{case["identity"]} {case["text"]} | {case["side"].upper()} {decision["type"].upper()} F{decision["start_frame"]}:{decision["end_frame"]} {decision["confidence"]}'
        cv2.putText(image, label[:125], (16, top + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (25, 25, 25), 1, cv2.LINE_AA)
        boundary = decision["start_frame"] if case["side"] == "entry" else decision["end_frame"] - 1
        for column, timeline_frame in enumerate(range(max(0, boundary - 2), boundary + 4)):
            capture.set(cv2.CAP_PROP_POS_FRAMES, round(timeline_frame * source_fps / FPS))
            ok, frame = capture.read()
            thumb = cv2.resize(frame, (81, 144), interpolation=cv2.INTER_AREA) if ok else np.zeros((144, 81, 3), dtype=np.uint8)
            x, y = 16 + column * 150, top + 42
            image[y:y + 144, x:x + 81] = thumb
            cv2.putText(image, f"F{timeline_frame}", (x + 84, y + 76), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (30, 30, 30), 1, cv2.LINE_AA)
        cv2.putText(image, "generated: " + json.dumps(decision["parameters"], sort_keys=True)[:75], (915, top + 100), cv2.FONT_HERSHEY_SIMPLEX, 0.30, (45, 90, 45), 1, cv2.LINE_AA)
    capture.release()
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def build() -> dict[str, bytes]:
    freeze_hashes = verify_freezes()
    static, timing = load(STATIC_CONTRACT), load(TIMING_CONTRACT)
    timing_by_id = {row["identity"]: row for row in timing["identities"]}
    rows = []
    for static_row in static["identities"]:
        identity = static_row["identity"]["stable_identity_id"]
        timing_row = timing_by_id.get(identity)
        if timing_row is None:
            continue
        start, end = timing_row["source"]["visibility_intervals"][0]
        points = observations(static_row)
        rows.append({
            "identity": identity,
            "text_diagnostic_only": static_row["identity"].get("text_diagnostic_only", ""),
            "visibility_interval": [start, end],
            "entry": classify_boundary(points, start, end, "entry"),
            "exit": classify_boundary(points, start, end, "exit"),
            "provenance": [static_row["identity"]["source_evidence_reference"], "frozen_step4a_timing_contract"],
        })
    rows.sort(key=lambda row: row["identity"])
    frozen_ids = {row["identity"]["stable_identity_id"] for row in static["identities"]}
    produced_ids = {row["identity"] for row in rows}
    counts = lambda side: {kind: sum(row[side]["type"] == kind for row in rows) for kind in ("abrupt", "fade", "pop", "slide", "scale", "unresolved", "unsupported")}
    entry_counts, exit_counts = counts("entry"), counts("exit")
    downgraded_entry = sum(row["entry"].get("reason") == "abrupt_visibility_transition_not_proven" for row in rows)
    downgraded_exit = sum(row["exit"].get("reason") == "abrupt_visibility_transition_not_proven" for row in rows)
    abrupt_correction = {
        "before": entry_counts["abrupt"] + exit_counts["abrupt"] + downgraded_entry + downgraded_exit,
        "after": entry_counts["abrupt"] + exit_counts["abrupt"],
        "downgraded": downgraded_entry + downgraded_exit,
        "entry_downgraded": downgraded_entry,
        "exit_downgraded": downgraded_exit,
        "surviving_abrupt_evidence": [],
    }
    source_code = Path(__file__).read_text(encoding="utf-8")
    reel_literals = sorted(set(re.findall(r"\\b(?:sub_\\d+|caption_tracklet_\\d+)\\b", source_code)))
    full_lifetime = any(row[side]["end_frame"] - row[side]["start_frame"] >= row["visibility_interval"][1] - row["visibility_interval"][0] for row in rows for side in ("entry", "exit") if row[side]["type"] in {"slide", "scale"})
    contract = {
        "schema": "video_cloner_step4b_entry_exit_animation_contract", "schema_version": 1,
        "result": "PASS_STEP_4B_ENTRY_EXIT_ANIMATION_READY_FOR_HUMAN_REVIEW" if len(rows) == 113 and produced_ids == frozen_ids else "FAIL_STEP_4B_ENTRY_EXIT_ANIMATION",
        "frame_semantics": timing["frame_semantics"],
        "taxonomy": ["abrupt", "fade", "pop", "slide", "scale", "unresolved", "unsupported"],
        "pop_scale_policy": "POP is not split from SCALE without an existing defensible classifier",
        "identities": rows,
    }
    validation = {
        "schema": "video_cloner_step4b_entry_exit_validation", "schema_version": 1,
        "ok": contract["result"].startswith("PASS_"),
        "identity_accounting": {"expected": 113, "produced": len(rows), "missing": sorted(frozen_ids - produced_ids), "duplicates": len(rows) - len(produced_ids)},
        "entry_results": entry_counts, "exit_results": exit_counts,
        "abrupt_evidence_correction": abrupt_correction,
        "boundary_timing": {"inside_frozen_intervals": all(row["visibility_interval"][0] <= row[side]["start_frame"] < row[side]["end_frame"] <= row["visibility_interval"][1] for row in rows for side in ("entry", "exit"))},
        "freeze_integrity": freeze_hashes,
        "static_artifacts_changed": False, "step4a_timing_artifacts_changed": False,
        "step4c_started": False, "step4d_started": False, "resolve_mutated": False,
        "generalization_gate": {"reel_specific_production_literals": reel_literals, "full_lifetime_keyframes": full_lifetime},
    }
    cases = select_cases(rows)
    manifest = {"schema": "video_cloner_step4b_entry_exit_review_manifest", "schema_version": 1, "review_case_count": len(cases), "selection_is_deterministic": True, "abrupt_evidence_correction": abrupt_correction, "cases": cases}
    report = (
        "# Step 4B entry / exit animation\n\n"
        f"RESULT: {contract['result']}\n\n- Identities: {len(rows)}/113; entry decisions: {len(rows)}; exit decisions: {len(rows)}.\n"
        f"- Entry: {entry_counts}; exit: {exit_counts}.\n"
        f"- ABRUPT evidence correction: {abrupt_correction['before']} before; {abrupt_correction['after']} after; {abrupt_correction['downgraded']} downgraded to UNRESOLVED.\n"
        "- Surviving ABRUPT evidence: none; geometry-only candidates fail closed.\n"
        "- Static and Step 4A timing freezes unchanged; Step 4C/4D not started; Resolve not mutated.\n"
        "- Human entry/exit review required: YES.\n"
    ).encode()
    return {
        "step4b_entry_exit_animation_contract.json": json_bytes(contract),
        "step4b_entry_exit_validation.json": json_bytes(validation),
        "step4b_entry_exit_review_manifest.json": json_bytes(manifest),
        "step4b_entry_exit_review_diagnostic.jpg": diagnostic(cases, abrupt_correction),
        "FINAL_REPORT.md": report,
    }


def generate(output_dir: Path) -> dict:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    first, second = build(), build()
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in first.items()}
    identical = first == second
    output_dir.mkdir(parents=True)
    for name, data in first.items():
        (output_dir / name).write_bytes(data)
    proof = {"schema": "video_cloner_step4b_determinism_proof", "schema_version": 1, "rerun_byte_identical": identical, "artifact_sha256": hashes}
    (output_dir / "determinism_proof.json").write_bytes(json_bytes(proof))
    if not identical:
        raise RuntimeError("Step 4B generation is not deterministic")
    return {"result": load(output_dir / "step4b_entry_exit_animation_contract.json")["result"], "output_dir": str(output_dir), "artifact_sha256": hashes}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
