"""Read-only acceptance recovery for the already-saved fresh Reel #2 timeline."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_step4_fresh_reel2_textplus as fresh


TASK_ID = "VIDEO_CLONER_STEP4_FRESH_REEL2_READONLY_ACCEPTANCE_V1"
MODE = "readonly_acceptance"
TARGET_NAME = "VC_REEL2_FRESH_TEXTPLUS_STEP4_20260914T181634Z"
ZERO_MUTATIONS = {"saves": 0, "creates": 0, "deletes": 0, "imports": 0, "title_writes": 0, "modifier_writes": 0, "keyframe_writes": 0, "timeline_selections": 0}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validated_path(payload: Mapping[str, Any], name: str) -> Path:
    path = Path(str(payload.get(name) or "")).resolve()
    if not path.is_file() or _sha256(path) != payload.get(f"{name}_sha256"):
        raise ValueError(f"artifact_identity:{name}")
    return path


def _modifier(tool: Any, input_name: str) -> dict[str, Any]:
    input_object = fresh.animation.find_input(tool, input_name)
    output = fresh.animation.connected_output(input_object)
    modifier = fresh.carrier._safe(output, "GetTool", default=None) if output is not None else None
    attrs = fresh.carrier._safe(modifier, "GetAttrs", default={}) if modifier is not None else {}
    return {
        "connected": output is not None,
        "type": str((attrs or {}).get("TOOLS_RegID") or "") or None,
        "keyframes": json.loads(json.dumps(fresh.carrier._safe(modifier, "GetKeyFrames", default={}) or {}, default=str)),
    }


def _identity_rows(authority: Mapping[str, Any], timeline: Any) -> tuple[dict[str, dict[str, Any]], int, int]:
    actual: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    textplus_count = basic_title_count = 0
    for track in range(2, int(fresh.carrier._safe(timeline, "GetTrackCount", "video", default=0) or 0) + 1):
        for item in fresh.carrier._safe(timeline, "GetItemListInTrack", "video", track, default=[]) or []:
            start = int(fresh.carrier._safe(item, "GetStart", default=-1) or -1)
            end = int(fresh.carrier._safe(item, "GetEnd", default=-1) or -1)
            try:
                comp, tool = fresh._textplus(item)
                text = str(fresh.carrier._safe(tool, "GetInput", "StyledText", 0, default="") or "")
                textplus_count += 1
                row = {"item": item, "comp": comp, "tool": tool, "item_unique_id": fresh.carrier._unique_id(item), "track": track, "start": start, "end": end, "text": text}
                actual.setdefault((track, start, end, text), []).append(row)
            except ValueError:
                if fresh.carrier._title_text(item):
                    basic_title_count += 1

    matched: dict[str, dict[str, Any]] = {}
    for cue in authority["cues"]:
        key = (int(cue["lane"]) + 1, int(cue["start_frame"]), int(cue["end_frame"]), str(cue["text"]))
        rows = actual.get(key) or []
        if len(rows) != 1:
            raise ValueError(f"caption_identity:{cue['id']}:{len(rows)}")
        matched[str(cue["id"])] = rows[0]
    if len(matched) != 91 or textplus_count != 91 or basic_title_count != 0:
        raise ValueError(f"caption_counts:{len(matched)}:{textplus_count}:{basic_title_count}")
    return matched, textplus_count, basic_title_count


def _protected_delta(before: list[dict[str, Any]], after: list[dict[str, Any]], prefix: str) -> int:
    select = lambda rows: {(row["name"], row["unique_id"]): row["signature"] for row in rows if row["name"].startswith(prefix) and row["name"] != TARGET_NAME}
    left, right = select(before), select(after)
    return len(set(left) ^ set(right)) + sum(left[key] != right[key] for key in set(left) & set(right))


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "read_only": True, "save_count": 0, "mutation_counts": dict(ZERO_MUTATIONS), "failures": []}
    try:
        payload = command.get("payload") or {}
        forbidden = ("mutation_permitted", "save_project", "create_permitted", "delete_permitted", "import_permitted", "title_write_permitted", "modifier_write_permitted", "keyframe_write_permitted", "timeline_selection_permitted")
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or payload.get("read_only") is not True or any(payload.get(name) is not False for name in forbidden) or payload.get("expected_project") != "New Project 1" or payload.get("target_timeline_name") != TARGET_NAME:
            raise ValueError("read_only_command_authority")

        paths = {name: _validated_path(payload, name) for name in ("generic", "style", "lifecycle", "failed_report")}
        failed = _read(paths["failed_report"])
        if failed.get("save_count") != 1 or failed.get("failures") != ["StopIteration: "]:
            raise ValueError("failed_run_evidence")
        lifecycle = _read(paths["lifecycle"])
        authority = fresh.prepare_textplus_authority(_read(paths["generic"]), _read(paths["style"]), lifecycle)
        overlap = fresh._representative_overlap(lifecycle)
        if len(authority["cues"]) != 91 or len(lifecycle["visual_compositions"]) != 90 or int(lifecycle["summary"]["unresolved_visual_composition_count"]) != 0:
            raise ValueError("authority_counts")

        manager = fresh.carrier._safe(resolve, "GetProjectManager")
        project = fresh.carrier._safe(manager, "GetCurrentProject")
        if project is None or str(fresh.carrier._safe(project, "GetName", default="") or "") != payload["expected_project"]:
            raise ValueError("project_identity")
        timelines = fresh.carrier._timelines(project)
        targets = [timeline for timeline in timelines if str(fresh.carrier._safe(timeline, "GetName", default="") or "") == TARGET_NAME]
        if len(targets) != 1:
            raise ValueError(f"persisted_timeline_occurrence:{len(targets)}")
        target = targets[0]
        before = [fresh.carrier.timeline_snapshot(timeline) for timeline in timelines]

        v1 = list(fresh.carrier._safe(target, "GetItemListInTrack", "video", 1, default=[]) or [])
        a1 = list(fresh.carrier._safe(target, "GetItemListInTrack", "audio", 1, default=[]) or [])
        frames = int(fresh.carrier._safe(target, "GetEndFrame", default=0) or 0) - int(fresh.carrier._safe(target, "GetStartFrame", default=0) or 0)
        if (len(v1), len(a1), frames) != (14, 1, 854):
            raise ValueError(f"persisted_baseline:{len(v1)}:{len(a1)}:{frames}")
        rows, textplus_count, basic_title_count = _identity_rows(authority, target)

        grouped = {}
        for text, semantic_ids in (("We don't", ["sub_001", "sub_002"]), ("6000", ["sub_065", "sub_066"])):
            cues = [cue for cue in authority["cues"] if cue["text"] == text and cue.get("source_cue_ids") == semantic_ids]
            if len(cues) != 1:
                raise ValueError(f"grouped_token:{text}")
            cue = cues[0]
            grouped[text] = {"token_id": cue["id"], "semantic_ids": semantic_ids, "window": [cue["start_frame"], cue["end_frame"]], "item_unique_id": rows[cue["id"]]["item_unique_id"]}

        social = next(cue for cue in authority["cues"] if cue["id"] == "visual_token_sub_045")
        social_row = rows[social["id"]]
        size_modifier = _modifier(social_row["tool"], "Size")
        frame_0 = fresh.animation.normalize_value("Size", fresh.animation.read_input(social_row["tool"], "Size", 0))
        frame_23 = fresh.animation.normalize_value("Size", fresh.animation.read_input(social_row["tool"], "Size", 23))
        expected = (0.080528214, 0.10833333333333332)
        if [social["start_frame"], social["end_frame"]] != [359, 383] or int(social["duration_frames"]) != 24 or size_modifier["type"] != "BezierSpline" or not fresh.animation.values_match("Size", frame_0, expected[0]) or not fresh.animation.values_match("Size", frame_23, expected[1]):
            raise ValueError(f"social_animation:{size_modifier['type']}:{frame_0}:{frame_23}")

        topology = []
        for caption_id, row in rows.items():
            for input_name in ("Center", "Size"):
                modifier = _modifier(row["tool"], input_name)
                if modifier["connected"]:
                    topology.append({"caption_id": caption_id, "input": input_name, "modifier": modifier})
        if len(topology) != 1 or topology[0]["caption_id"] != social["id"] or topology[0]["input"] != "Size":
            raise ValueError(f"animation_topology:{[(row['caption_id'], row['input']) for row in topology]}")

        after = [fresh.carrier.timeline_snapshot(timeline) for timeline in fresh.carrier._timelines(project)]
        if before != after:
            raise ValueError("readonly_state_changed")
        reel1_delta = _protected_delta(before, after, "DZsqH7auhjt")
        reel2_delta = _protected_delta(before, after, "DcJRJtUKScu")
        result.update({
            "ok": True,
            "classification": "STEP4_TECHNICALLY_PROVEN_FRESH_REEL2_READY_FOR_HUMAN_ACCEPTANCE",
            "generation_evidence": {"failed_run_id": failed.get("run_id"), "save_count": 1, "reporting_failure": "StopIteration"},
            "persisted_timeline": {"name": TARGET_NAME, "unique_id": fresh.carrier._unique_id(target), "video_clip_count": 14, "audio_clip_count": 1, "duration_frames": 854, "textplus_count": textplus_count, "basic_title_count": basic_title_count, "composition_count": 90, "token_count": 91, "unresolved_count": 0},
            "representative": {"grouped": grouped, "overlap": overlap},
            "animation": {"caption_id": social["id"], "item_unique_id": social_row["item_unique_id"], "window": [359, 383], "duration_frames": 24, "static_size": float((authority["cue_styles"].get(int(social["index"])) or authority["style"])["textplus_size"]), "modifier": size_modifier, "frame_0_size": frame_0, "frame_23_size": frame_23, "authorized_count": 1, "applied_count": 1, "unauthorized_count": 0},
            "protected_state": {"reel1_delta": reel1_delta, "previous_reel2_delta": reel2_delta, "unrelated_mutation_count": 0, "audit_save_count": 0, "before_after_equal": True},
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
    return result
