from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping


SCHEMA = "video_cloner.transition_authority.v1"
SCHEMA_VERSION = "1.0"
SUPPORTED = {"flash_cut"}


class TransitionAuthorityError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_transition_authority(
    generic: Mapping[str, object], *, run_id: str, source_generic: str | Path | None = None
) -> dict[str, object]:
    if generic.get("success") is not True or generic.get("schema") != "generic_edit_commands":
        raise TransitionAuthorityError("generic planning output is not successful generic_edit_commands")
    if generic.get("schema_version") != "2.0":
        raise TransitionAuthorityError("unsupported generic planning schema")
    video_id = generic.get("video_id")
    if not isinstance(video_id, str) or not video_id.strip():
        raise TransitionAuthorityError("generic planning output has no video identity")
    if not isinstance(run_id, str) or not run_id.strip():
        raise TransitionAuthorityError("transition authority requires a run identity")
    timeline = generic.get("timeline")
    if not isinstance(timeline, list):
        raise TransitionAuthorityError("generic planning output has no timeline")

    rows: list[dict[str, object]] = []
    seen_boundaries: set[int] = set()
    for command_index, command in enumerate(timeline, start=1):
        if not isinstance(command, Mapping):
            raise TransitionAuthorityError(f"timeline command {command_index} is malformed")
        start = command.get("timeline_start_frame")
        boundary = command.get("timeline_end_frame")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, boundary)) or boundary <= start:
            raise TransitionAuthorityError(f"timeline command {command_index} has invalid frame range")
        operations = command.get("operations")
        if not isinstance(operations, list):
            raise TransitionAuthorityError(f"timeline command {command_index} has malformed operations")
        for operation_index, operation in enumerate(operations, start=1):
            if not isinstance(operation, Mapping) or operation.get("operation") != "transition_hint":
                continue
            params = operation.get("parameters")
            if not isinstance(params, Mapping):
                raise TransitionAuthorityError(f"transition hint {command_index}:{operation_index} is malformed")
            if operation.get("editor_actionable") is False or params.get("editor_actionable") is False or params.get("actionable") is False:
                continue
            transition_type = str(params.get("transition_type") or "").strip().lower()
            if transition_type not in SUPPORTED:
                raise TransitionAuthorityError(f"unsupported authorized transition type: {transition_type or 'unknown'}")
            requested_boundary = params.get("timeline_cut_frame", params.get("cut_frame"))
            if isinstance(requested_boundary, bool) or not isinstance(requested_boundary, int) or requested_boundary != boundary:
                raise TransitionAuthorityError(f"transition hint {command_index}:{operation_index} has invalid boundary")
            duration = params.get("duration_frames")
            outgoing = params.get("outgoing_frames")
            incoming = params.get("incoming_frames")
            if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (duration, outgoing, incoming)):
                raise TransitionAuthorityError(f"transition hint {command_index}:{operation_index} has invalid range")
            if outgoing + incoming != duration:
                raise TransitionAuthorityError(f"transition hint {command_index}:{operation_index} has inconsistent range")
            if boundary in seen_boundaries:
                raise TransitionAuthorityError(f"duplicate executable transition boundary: {boundary}")
            seen_boundaries.add(boundary)
            rows.append({
                "id": f"{video_id}_flash_{len(rows) + 1:03d}",
                "boundary_frame": boundary,
                "transition_type": "flash_cut",
                "handoff_type": "flash_v4_visual_carrier",
                "duration_frames": duration,
                "alignment": "centered_on_cut",
                "source_planning_ref": {
                    "command_index": command_index,
                    "operation_index": operation_index,
                    "operation": "transition_hint",
                },
                "confidence": params.get("confidence"),
                "strength": params.get("strength"),
            })

    rows.sort(key=lambda row: int(row["boundary_frame"]))
    for index, row in enumerate(rows, start=1):
        row["id"] = f"{video_id}_flash_{index:03d}"
    result: dict[str, object] = {
        "success": True,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "video_id": video_id,
        "run_id": run_id,
        "source_generic": str(source_generic) if source_generic is not None else None,
        "source_generic_sha256": _sha256(Path(source_generic)) if source_generic is not None else None,
        "native_transitions": [],
        "flash_handoffs": rows,
        "summary": {"native_count": 0, "flash_handoff_count": len(rows), "decision_count": len(rows)},
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generic", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.generic).expanduser().resolve()
    generic = json.loads(source.read_text(encoding="utf-8-sig"))
    authority = build_transition_authority(generic, run_id=args.run_id, source_generic=source)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(authority, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
