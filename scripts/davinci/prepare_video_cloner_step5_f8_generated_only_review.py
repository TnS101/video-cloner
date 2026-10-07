"""Preflight and publish one F8 generated-only review timeline command."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TASK_ID = "VIDEO_CLONER_STEP5_F8_GENERATED_ONLY_REVIEW_V1"
MODE = "create_f8_generated_only_review"
MODULE = "resolve_workspace/modules/video_cloner_step5_f8_generated_only_review.py"
CONTRACT = ".agent/reports/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_V1/20261002T093228130622Z_8a43be1aa99a4e2fa6ec66203b559cbd/step5_f7_compile_contract.json"
PLACEMENT = ".agent/reports/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_V1/20261002T093228130622Z_8a43be1aa99a4e2fa6ec66203b559cbd/step5_f7_placement_validation.json"
F7_PASS = ".agent/reports/VIDEO_CLONER_STEP5_F7_READONLY_MACHINE_VALIDATION_V1/20261002T120011651892Z_a6ca1abfe075450292a9686bbd9f93f3/bridge_report.json"
F7_TIMELINE = "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_66203b559cbd"
F7_UID = "80d5e22c-355d-47e7-a788-8f7dc68f718c"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object:{path}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _time(frame: int, fps: int) -> str:
    seconds, ff = divmod(frame, fps)
    minutes, ss = divmod(seconds, 60)
    hours, mm = divmod(minutes, 60)
    return f"{hours:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _checklist() -> list[dict[str, Any]]:
    rows = [
        ("launch", 55, "caption_tracklet_0009", "Does launch remain a correct animation/color control?"),
        ("invest", 271, "caption_tracklet_0045", "Does invest retain its accepted animation?"),
        ("reels", 348, "caption_tracklet_0061", "Does reels retain its accepted style and animation?"),
        ("selling", 90, "continuous_visual_identity_0014", "Does generated size/position/style reproduce the source caption closely?"),
        ("sign", 140, "continuous_visual_identity_0028", "Is sign size, color, style, and placement acceptable?"),
        ("text-dump region: selling", 90, None, "Is there no generated full-sentence caption?"),
        ("why?", 227, "recovered_display_object_why_0001", "Is why? present with accepted style and placement?"),
        ("initial We", 262, "recovered_display_object_local_we_0002", "Is the recovered local We present once?"),
        ("listing", 341, "recovered_display_object_listing_0003", "Is listing style and position acceptable?"),
        ("social", 370, "caption_tracklet_0064", "Is there exactly one generated social caption?"),
        ("text-dump region: social", 370, None, "Is there no generated full-sentence caption?"),
        ("not", 396, "caption_tracklet_0067", "Is not size/style source-like?"),
        ("over", 536, "caption_tracklet_0087", "Is over initial size and animation source-like?"),
        ("6000", 545, "caption_tracklet_0089", "Does expand to plateau to exit contraction look source-like and persist through [542,596)?"),
        ("matching", 610, "caption_tracklet_0094", "Is lower matching source-like?"),
        ("Matching", 626, "caption_tracklet_0096", "Is upper Matching source-like?"),
        ("buyers", 638, "caption_tracklet_0097", "Is buyers font/style acceptable?"),
        ("like animation absence", 765, None, "Is the previously false generated like absent?"),
        ("end-screen like absence", 769, None, "Is generated like absent from the end-screen region?"),
        ("launching", 727, "caption_tracklet_0110", "Is launching source-like?"),
    ]
    return [{"case": case, "timeline_frame": frame, "timeline_time_24fps": _time(frame, 24), "source_frame_30fps": int(frame * 30 / 24 + 0.5), "source_time_30fps": _time(int(frame * 30 / 24 + 0.5), 30), "generated_identity": identity, "expected_human_question": question, "allowed_result": ["PASS", "MINOR ISSUE", "FAIL"], "comment_required_for": ["MINOR ISSUE", "FAIL"]} for case, frame, identity, question in rows]


def preflight(root: Path) -> dict[str, Any]:
    contract = _read(root / CONTRACT)
    placement = _read(root / PLACEMENT)
    f7_pass = _read(root / F7_PASS)
    objects = contract.get("objects", [])
    overlaps = []
    for left_index, left in enumerate(objects):
        for right in objects[left_index + 1:]:
            if left["z_order_track"]["resolve_track"] == right["z_order_track"]["resolve_track"] and max(left["resolve_interval"][0], right["resolve_interval"][0]) < min(left["resolve_interval"][1], right["resolve_interval"][1]):
                overlaps.append([left["source_identity"], right["source_identity"]])
    target = next(row for row in objects if row["source_identity"] == "caption_tracklet_0089")
    invariants = placement["invariant_hashes"]
    result = {
        "renderables": len(objects),
        "all_renderable": all(row.get("renderable") is True for row in objects),
        "same_track_conflicts": len(overlaps),
        "conflicts": overlaps,
        "placement_pass": placement.get("pass") is True,
        "f2_f7_invariants_unchanged": all(value["before"] == value["after"] for value in invariants.values()),
        "f7_machine_pass": f7_pass.get("ok") is True and f7_pass.get("classification") == "F7_MACHINE_PASS",
        "f6_6000_interval": target["resolve_interval"],
        "f3_6000_scale_keys": len(target["keyframes"]["scale"]),
        "production_identity_literal_reel_branches": 0,
        "protected_timeline_mutation_planned": False,
        "f7_timeline_mutation_planned": False,
    }
    result["pass"] = result["renderables"] == 65 and result["all_renderable"] and result["same_track_conflicts"] == 0 and result["placement_pass"] and result["f2_f7_invariants_unchanged"] and result["f7_machine_pass"] and result["f6_6000_interval"] == [542, 596] and result["f3_6000_scale_keys"] == 9
    return result


def publish(root: Path = ROOT, now: dt.datetime | None = None) -> dict[str, Any]:
    root = root.resolve()
    active = [path for state in ("pending", "running") for path in (root / ".agent/commands" / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    check = preflight(root)
    if not check["pass"]:
        raise ValueError("preflight")
    now = now or dt.datetime.now(dt.timezone.utc)
    unique = uuid.uuid4().hex
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + unique
    review_timeline = "VIDEO_CLONER_STEP5_F8_GENERATED_ONLY_REVIEW_" + unique[:12]
    report_dir = root / ".agent/reports" / TASK_ID / run_id
    contract = (root / CONTRACT).resolve()
    _write(report_dir / "preflight.json", check)
    _write(report_dir / "human_review_checklist.json", {"review_timeline": review_timeline, "items": _checklist()})
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "status_path": str((report_dir / "status.json").relative_to(root)),
        "log_path": str((report_dir / "run.log").relative_to(root)),
        "report_path": str((report_dir / "bridge_report.json").relative_to(root)),
        "payload": {"report_dir": str(report_dir), "contract_path": str(contract), "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(), "f7_timeline": F7_TIMELINE, "f7_timeline_uid": F7_UID, "review_timeline": review_timeline, "background_strategy": "NO_MEDIA_UNDERLAY_NEUTRAL_BLACK_VIEWER", "project_save": True},
    }
    command_path = root / ".agent/commands/pending" / f"{TASK_ID}_{run_id}.json"
    _write(report_dir / "command.json", command)
    _write(command_path, command)
    receipt = {"task_id": TASK_ID, "run_id": run_id, "command_path": str(command_path), "report_dir": str(report_dir), "review_timeline": review_timeline, "module": MODULE, "mode": MODE}
    _write(report_dir / "publication_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
