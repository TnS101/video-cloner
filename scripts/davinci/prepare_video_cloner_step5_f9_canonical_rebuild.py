"""Compile and publish one fresh canonical-ownership F7 rebuild command."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analysis.compile_step5a_f9_canonical_display_ownership import compile_contract, digest, json_bytes

TASK_ID = "VIDEO_CLONER_STEP5_F9_CANONICAL_DISPLAY_OWNERSHIP_REBUILD_V1"
MODE = "apply_fresh_canonical_validation_rebuild"
MODULE = "resolve_workspace/modules/video_cloner_step5_f9_canonical_rebuild.py"
BASELINE = ROOT / ".agent/reports/VIDEO_CLONER_STEP5A_REAL_TEXTPLUS_COMPILE_20260928/20260928T190000000Z_real_textplus_compile/step5a_cutonly_baseline.fcpxml"
BASELINE_SHA256 = "d3b9c796feff8d81c2823a318e2df1657a415e8b06e65e7e9dfe0f756a35ea97"


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(json_bytes(value))
    os.replace(temporary, path)


def _active_commands() -> list[Path]:
    return [path for state in ("pending", "running") for path in (ROOT / ".agent/commands" / state).glob("*.json")]


def _review_sheet(report_dir: Path) -> Path:
    cases = [
        ("Selling", 113, "one continuous Selling owner"),
        ("calling", 625, "one calling owner; no independent ling"),
        ("buyers", 720, "one buyers owner; no buy + ers split"),
        ("with the buyers", 797, "three owners: with + the + buyers"),
        ("we have", 816, "two co-visible owners: we + have"),
        ("your why?", 284, "two co-visible owners: your + why?"),
        ("Matching", 762, "one continuous Matching owner"),
    ]
    frame_dir = report_dir / "ownership_source_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for case, frame, expected in cases:
        target = frame_dir / f"{case.replace(' ', '_').replace('?', '')}_{frame:04d}.png"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(ROOT / "input/DcJRJtUKScu.mp4"), "-vf", f"select=eq(n\\,{frame})", "-vsync", "0", "-frames:v", "1", str(target)], check=True)
        rows.append((case, frame, expected, target))
    width, image_width, row_height = 760, 270, 500
    sheet = Image.new("RGB", (width, row_height * len(rows)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for index, (case, frame, expected, target) in enumerate(rows):
        image = Image.open(target).convert("RGB")
        image.thumbnail((image_width, 480))
        y = index * row_height
        sheet.paste(image, ((image_width - image.width) // 2, y))
        draw.text((image_width + 24, y + 35), f"{case}  |  source frame {frame}", fill=(255, 220, 170))
        draw.text((image_width + 24, y + 85), "Expected ownership:", fill="white")
        draw.text((image_width + 24, y + 120), expected, fill=(220, 220, 220))
    output = report_dir / "source_vs_expected_ownership_review.jpg"
    sheet.save(output, quality=92)
    write(report_dir / "source_vs_expected_ownership_review.json", {"schema": "video_cloner_f9_source_vs_expected_ownership_review", "cases": [{"case": case, "source_frame": frame, "expected_ownership": expected, "source_image": str(target)} for case, frame, expected, target in rows], "sheet": str(output)})
    return output


def publish(now: dt.datetime | None = None) -> dict[str, Any]:
    active = _active_commands()
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    if hashlib.sha256(BASELINE.read_bytes()).hexdigest() != BASELINE_SHA256:
        raise ValueError("baseline_hash_drift")
    now = now or dt.datetime.now(dt.timezone.utc)
    unique = uuid.uuid4().hex
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + unique
    target_timeline = "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_CANONICAL_" + unique[:12]
    report_dir = ROOT / ".agent/reports" / TASK_ID / run_id

    first = list(compile_contract())
    second = list(compile_contract())
    for artifacts in (first, second):
        artifacts[0]["validation_timeline"] = target_timeline
        artifacts[2]["contract_sha256"] = digest(artifacts[0])
    names = ("step5_f9_canonical_compile_contract.json", "step5_f9_ownership_audit.json", "step5_f9_validation.json", "step5_f9_ownership_authority.json")
    first_payloads = {name: json_bytes(value) for name, value in zip(names, first)}
    second_payloads = {name: json_bytes(value) for name, value in zip(names, second)}
    proof = {"schema": "video_cloner_step5_f9_publisher_determinism", "artifacts": {name: {"first_sha256": hashlib.sha256(first_payloads[name]).hexdigest(), "second_sha256": hashlib.sha256(second_payloads[name]).hexdigest(), "byte_identical": first_payloads[name] == second_payloads[name]} for name in names}}
    proof["deterministic"] = all(row["byte_identical"] for row in proof["artifacts"].values())
    if first[2]["all_pass"] is not True or not proof["deterministic"]:
        raise ValueError("canonical_preflight")
    for branch, payloads in (("first", first_payloads), ("second", second_payloads)):
        for name, payload in payloads.items():
            path = report_dir / branch / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    write(report_dir / "determinism_proof.json", proof)
    review_sheet = _review_sheet(report_dir)

    contract_path = report_dir / "first" / names[0]
    audit_path = report_dir / "first" / names[1]
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "status_path": str((report_dir / "status.json").relative_to(ROOT)),
        "log_path": str((report_dir / "run.log").relative_to(ROOT)),
        "report_path": str((report_dir / "bridge_report.json").relative_to(ROOT)),
        "payload": {
            "report_dir": str(report_dir),
            "contract_path": str(contract_path),
            "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            "ownership_audit_path": str(audit_path),
            "ownership_audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
            "baseline_fcpxml": str(BASELINE),
            "baseline_fcpxml_sha256": BASELINE_SHA256,
            "target_timeline": target_timeline,
        },
    }
    command_path = ROOT / ".agent/commands/pending" / f"{TASK_ID}_{run_id}.json"
    if _active_commands():
        raise ValueError("queue_changed_before_publication")
    write(report_dir / "command.json", command)
    write(command_path, command)
    receipt = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path),
        "report_dir": str(report_dir),
        "target_timeline": target_timeline,
        "module": MODULE,
        "mode": MODE,
        "expected_renderable_count": first[0]["object_count"],
        "review_sheet": str(review_sheet),
    }
    write(report_dir / "publication_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
