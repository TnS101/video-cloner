#!/usr/bin/env python3
"""Read-only, fail-closed prerequisite audit for the Step 3B.6D four-cue rollout."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Sequence

VERSION = "inspect_caption_source_geometry_contained_rollout_prerequisites_step_3B_6D_v1_1_center_size_only"
TRACK_SCHEMA = "video_cloner_caption_word_instance_tracks"
PROBE_PLAN_SCHEMA = "video_cloner_caption_source_geometry_probe_plan"
EXPECTED = {
    "sub_007": ("While", 196, 199),
    "sub_013": ("out", 224, 230),
    "sub_110": ("looks", 862, 868),
    "sub_114": ("AND", 888, 894),
}
ACCEPTED_PROBE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6C_IDEMPOTENCY_EVIDENCE_REGENERATION_V1"
ACCEPTED_PROBE_RUN_ID = "20260802T132415124Z_adb873fd4d154b25a99fd4efce8b6e7f"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def canonical_hash(value: Dict[str, Any], ignored: Sequence[str] = ()) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    for key in ignored:
        clean.pop(key, None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def optional_json(path: Path) -> tuple[Dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        return load_json(path), None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, f"invalid:{type(exc).__name__}:{exc}"


def same_path(value: Any, expected: Path) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).resolve() == expected.resolve()


def assigned_literal(path: Path, name: str) -> Any:
    if not path.is_file():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
                return ast.literal_eval(node.value)
    except (OSError, SyntaxError, ValueError):
        return None
    return None


def integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def assess(
    tracks_path: Path,
    redetection_validation_path: Path,
    animation_plan_path: Path,
    probe_plan_path: Path,
    probe_report_path: Path,
    probe_validation_path: Path,
    preparer_path: Path,
) -> Dict[str, Any]:
    required = {
        "tracks": tracks_path,
        "redetection_validation": redetection_validation_path,
        "animation_plan": animation_plan_path,
        "probe_plan": probe_plan_path,
        "probe_report": probe_report_path,
        "probe_validation": probe_validation_path,
        "preparer": preparer_path,
    }
    loaded: Dict[str, Dict[str, Any] | None] = {}
    artifacts: Dict[str, Any] = {}
    missing: list[str] = []
    invalid: list[str] = []
    for label, path in required.items():
        if label == "preparer":
            error = None if path.is_file() else "missing"
            value = None
        else:
            value, error = optional_json(path)
        loaded[label] = value
        artifacts[label] = {"path": str(path.resolve()), "sha256": sha256(path), "error": error}
        if error == "missing":
            missing.append(label)
        elif error:
            invalid.append(label)

    tracks = loaded["tracks"] or {}
    redetection = loaded["redetection_validation"] or {}
    animation = loaded["animation_plan"] or {}
    probe_plan = loaded["probe_plan"] or {}
    probe_report = loaded["probe_report"] or {}
    probe_validation = loaded["probe_validation"] or {}

    track_rows = [
        track
        for scene in (tracks.get("scenes") or [])
        for track in (scene.get("tracks") or [])
        if str(track.get("cue_id") or "") in EXPECTED
    ]
    item_rows = [item for item in (animation.get("items") or []) if str(item.get("cue_id") or "") in EXPECTED]
    targets: Dict[str, Any] = {}
    for cue_id, (text, start, end) in EXPECTED.items():
        cue_tracks = [row for row in track_rows if row.get("cue_id") == cue_id]
        cue_items = [row for row in item_rows if row.get("cue_id") == cue_id]
        track = cue_tracks[0] if len(cue_tracks) == 1 else {}
        item = cue_items[0] if len(cue_items) == 1 else {}
        geometry = track.get("geometry") or {}
        first = geometry.get("first_visible_frame")
        last = geometry.get("last_visible_frame")
        observations = sorted(track.get("frame_observations") or [], key=lambda row: int(row.get("timeline_frame") or -1))
        observed_frames = [int(row.get("timeline_frame")) for row in observations if row.get("timeline_frame") is not None]
        expected_frames = list(range(int(first), int(last) + 1)) if first is not None and last is not None else []
        checks = {
            "one_source_record": len(cue_tracks) == 1,
            "one_timeline_item": len(cue_items) == 1,
            "text": track.get("text") == text and item.get("text") == text,
            "accepted_source_exact": bool(track.get("accepted_source_instance")) and track.get("source_exactness") == "source_redetected_dense_word_instance",
            "no_fallback": not track.get("fallback_reasons"),
            "cue_range": int(track.get("cue_start_frame") or -1) == start and int(track.get("cue_end_frame") or -1) == end,
            "timeline_item_range": int(item.get("start_frame") or -1) == start and int(item.get("end_frame") or -1) == end,
            "timeline_item_identity": item.get("name") == f"VC_TEXTPLUS_{int(cue_id[-3:]):04d}_{cue_id}",
            "source_contained": first is not None and last is not None and start <= int(first) <= int(last) < end,
            "dense_observations": bool(expected_frames) and observed_frames == expected_frames,
            "observation_values": bool(observations) and all(
                isinstance(row.get("position"), list)
                and len(row["position"]) == 2
                and row.get("scale_proxy") is not None
                and row.get("source_frame") is not None
                for row in observations
            ),
        }
        targets[cue_id] = {
            "text": text,
            "cue_range": [start, end],
            "source_visible_range": [first, last],
            "observation_count": len(observations),
            "checks": checks,
            "accepted": all(checks.values()),
        }

    expected_probe_hash = canonical_hash(probe_plan, ignored=("created_at_unix",)) if probe_plan else None
    validation_checks = probe_validation.get("checks") if isinstance(probe_validation.get("checks"), dict) else {}
    probe_checks = {
        "plan_ok": bool(probe_plan.get("ok")),
        "plan_schema": probe_plan.get("schema") == PROBE_PLAN_SCHEMA,
        "plan_hash": bool(expected_probe_hash) and probe_plan.get("plan_hash") == expected_probe_hash,
        "report_ok": bool(probe_report.get("ok")),
        "report_mode": probe_report.get("run_mode") == "idempotent_second_run",
        "report_plan_hash": bool(expected_probe_hash) and probe_report.get("plan_hash") == expected_probe_hash,
        "report_control": probe_report.get("probe_cue_id") == "sub_114" and int((probe_report.get("summary") or {}).get("target_key_verified_count") or 0) == 12,
        "report_idempotent": int((probe_report.get("summary") or {}).get("modified_count", -1)) == 0 and int((probe_report.get("summary") or {}).get("already_correct_count") or 0) == 1,
        "validation_ok": bool(probe_validation.get("ok")),
        "validation_mode": probe_validation.get("mode") == "idempotent_second_run",
        "validation_no_failures": not probe_validation.get("failures"),
        "validation_checks": bool(validation_checks) and all(value is True for value in validation_checks.values()),
        "validation_plan_binding": same_path(probe_validation.get("plan"), probe_plan_path),
        "validation_report_binding": same_path(probe_validation.get("report"), probe_report_path),
        "canonical_task": probe_report.get("task_id") == ACCEPTED_PROBE_TASK_ID and probe_validation.get("task_id") == ACCEPTED_PROBE_TASK_ID,
        "canonical_run": probe_report.get("run_id") == ACCEPTED_PROBE_RUN_ID and probe_validation.get("run_id") == ACCEPTED_PROBE_RUN_ID,
        "readback_only": probe_report.get("timeline_modified") is False
        and integer(probe_report.get("setter_call_count")) == 0
        and integer(probe_report.get("effective_mutation_count")) == 0
        and integer(probe_report.get("blend_operation_count")) == 0,
    }
    allowed_properties = assigned_literal(preparer_path, "ALLOWED_OPERATION_PROPERTIES")
    excluded_properties = assigned_literal(preparer_path, "KNOWN_EXCLUDED_SOURCE_PROPERTIES")
    global_checks = {
        "tracks_ok": bool(tracks.get("ok")) and tracks.get("schema") == TRACK_SCHEMA,
        "tracks_count": int((tracks.get("summary") or {}).get("v3_item_count") or 0) == 116,
        "redetection_validation": bool(redetection.get("ok")) and not redetection.get("failures"),
        "animation_plan": bool(animation.get("ok")) and len(animation.get("items") or []) == 116,
        "center_size_only_preparer": tuple(allowed_properties or ()) == ("Center", "Size"),
        "bounded_blend_exclusion": tuple(excluded_properties or ()) == ("Blend",),
    }
    blockers = [f"missing:{label}" for label in missing] + [f"invalid:{label}" for label in invalid]
    blockers.extend(f"global:{name}" for name, ok in global_checks.items() if not ok)
    blockers.extend(f"probe:{name}" for name, ok in probe_checks.items() if not ok)
    blockers.extend(f"target:{cue_id}" for cue_id, row in targets.items() if not row["accepted"])
    eligible = not blockers
    return {
        "ok": eligible,
        "eligible_for_build": eligible,
        "preparation_permitted": eligible,
        "runtime_command_permitted": False,
        "step": "Major Step 3B.6D prerequisite investigation",
        "version": VERSION,
        "expected_cues": [{"cue_id": cue_id, "text": values[0]} for cue_id, values in EXPECTED.items()],
        "artifacts": artifacts,
        "global_checks": global_checks,
        "probe_checks": probe_checks,
        "targets": targets,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracks", required=True, type=Path)
    parser.add_argument("--redetection-validation", required=True, type=Path)
    parser.add_argument("--animation-plan", required=True, type=Path)
    parser.add_argument("--probe-plan", required=True, type=Path)
    parser.add_argument("--probe-report", required=True, type=Path)
    parser.add_argument("--probe-validation", required=True, type=Path)
    parser.add_argument("--preparer", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = assess(
            args.tracks.resolve(), args.redetection_validation.resolve(), args.animation_plan.resolve(),
            args.probe_plan.resolve(), args.probe_report.resolve(), args.probe_validation.resolve(),
            args.preparer.resolve(),
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "eligible_for_build": False,
            "runtime_command_permitted": False,
            "step": "Major Step 3B.6D prerequisite investigation",
            "version": VERSION,
            "blockers": ["investigator_exception"],
            "exception": f"{type(exc).__name__}: {exc}",
        }
    payload["output"] = str(args.output.resolve())
    write_json(args.output.resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("eligible_for_build") else 1


if __name__ == "__main__":
    raise SystemExit(main())
