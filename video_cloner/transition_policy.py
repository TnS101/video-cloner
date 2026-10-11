from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from typing import Mapping


UNSUPPORTED_EXECUTABLE = {"whip_pan", "slide_transition"}
OSS003_BLUR_CUTS = (80, 286, 376)


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


def normalize_oss003_recipes(source: Mapping[str, object]) -> dict[str, object]:
    """Reduce the accepted Reel #3 evidence to editor-independent OSS-003 recipes."""
    if source.get("success") is not True or source.get("schema") != "video_cloner_transitions":
        raise TransitionFilterError("input is not a successful video_cloner_transitions artifact")
    rows = source.get("transitions")
    if not isinstance(rows, list):
        raise TransitionFilterError("input transitions must be a list")
    by_cut = {int(row.get("cut_frame", -1)): row for row in rows if isinstance(row, Mapping)}
    recipes = []
    for cut in OSS003_BLUR_CUTS:
        row = by_cut.get(cut)
        if (
            not row
            or row.get("transition_type") != "blur_transition"
            or row.get("editor_actionable") is not True
            or int(row.get("duration_frames") or 0) <= 0
        ):
            raise TransitionFilterError(f"missing executable blur evidence at cut {cut}")
        recipes.append(
            {
                "boundary_frame": cut,
                "from_shot": int(row["from_shot"]),
                "to_shot": int(row["to_shot"]),
                "family": "blur_handoff",
                "duration_frames": int(row["duration_frames"]),
                "outgoing_frames": int(row["outgoing_frames"]),
                "incoming_frames": int(row["incoming_frames"]),
                "direction": "none",
                "intensity": float(row["transition_strength"]),
                "easing": "smooth",
                "confidence": str(row["confidence"]),
                "provenance": {"schema": source["schema"], "analysis_version": source.get("analysis_version")},
            }
        )
    return {
        "schema": "video_cloner.transition_recipe_set.v1",
        "video_id": "DZatr0EJt4B",
        "fps": float(source.get("fps") or 0),
        "recipes": recipes,
        "deferred_to_oss004": [461],
        "analysis_only": [cut for cut in (211, 629) if cut in by_cut],
    }


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
