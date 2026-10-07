from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from typing import Mapping


UNSUPPORTED_EXECUTABLE = {"whip_pan", "slide_transition"}


class TransitionFilterError(ValueError):
    pass


def filter_mvp_transitions(source: Mapping[str, object]) -> dict[str, object]:
    if source.get("success") is not True or source.get("schema") != "video_cloner_transitions":
        raise TransitionFilterError("input is not a successful video_cloner_transitions artifact")
    source_rows = source.get("transitions")
    if not isinstance(source_rows, list):
        raise TransitionFilterError("input transitions must be a list")

    result = copy.deepcopy(dict(source))
    rows = result["transitions"]
    assert isinstance(rows, list)
    demoted = 0
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise TransitionFilterError(f"transition {index} is malformed")
        kind = str(row.get("transition_type") or "")
        if kind not in UNSUPPORTED_EXECUTABLE:
            continue
        row.update(
            {
                "transition_type": f"{kind}_candidate",
                "editor_actionable": False,
                "is_editor_candidate": False,
                "duration_frames": 0,
                "duration_seconds": 0.0,
                "outgoing_frames": 0,
                "incoming_frames": 0,
                "side": "cut_only",
                "placement": "cut_only",
                "actionability_reason": f"unsupported_mvp_backend:{kind}",
            }
        )
        demoted += 1

    result["summary"] = dict(sorted(Counter(str(row.get("transition_type") or "unknown") for row in rows).items()))
    result["mvp_filter"] = {
        "demoted_count": demoted,
        "demoted_types": sorted(UNSUPPORTED_EXECUTABLE),
        "policy": "preserve_evidence_but_do_not_emit_unsupported_executable_transitions",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Demote transition families unsupported by the MVP Resolve backend.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    source = json.loads(source_path.read_text(encoding="utf-8-sig"))
    filtered = filter_mvp_transitions(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"success": True, "output": str(output_path), **filtered["mvp_filter"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
