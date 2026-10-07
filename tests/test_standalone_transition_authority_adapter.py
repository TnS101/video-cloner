import copy
import json
from pathlib import Path

import pytest

from video_cloner.captions.fcpxml import compile_fcpxml
from scripts.standalone.video_cloner_transition_authority import (
    TransitionAuthorityError,
    build_transition_authority,
)


ROOT = Path(__file__).resolve().parents[1]
GENERIC = ROOT / "data" / "DcJRJtUKScu" / "planning" / "DcJRJtUKScu_generic_edit_commands.json"


def _generic():
    return json.loads(GENERIC.read_text(encoding="utf-8"))


def test_authorized_flash_cut_maps_to_one_authority_row():
    authority = build_transition_authority(_generic(), run_id="r1", source_generic=GENERIC)
    assert authority["summary"] == {"native_count": 0, "flash_handoff_count": 1, "decision_count": 1}
    row = authority["flash_handoffs"][0]
    assert (row["transition_type"], row["boundary_frame"], row["duration_frames"]) == ("flash_cut", 596, 9)
    assert row["source_planning_ref"] == {"command_index": 9, "operation_index": 2, "operation": "transition_hint"}


def test_rejected_observations_do_not_become_executable_rows():
    generic = _generic()
    generic["timeline"][0]["observations"] = {"transition_candidate": {"transition_type": "slide_transition", "actionable": False}}
    authority = build_transition_authority(generic, run_id="r1")
    assert authority["flash_handoffs"]
    assert all(row["transition_type"] == "flash_cut" for row in authority["flash_handoffs"])


def test_non_actionable_planning_row_is_ignored():
    generic = _generic()
    op = next(op for command in generic["timeline"] for op in command["operations"] if op.get("operation") == "transition_hint")
    op["parameters"]["actionable"] = False
    authority = build_transition_authority(generic, run_id="r1")
    assert authority["summary"] == {"native_count": 0, "flash_handoff_count": 0, "decision_count": 0}


@pytest.mark.parametrize("mutation", ["duplicate", "range", "unsupported"])
def test_invalid_or_unsupported_authority_fails_closed(mutation):
    generic = _generic()
    op = next(op for command in generic["timeline"] for op in command["operations"] if op.get("operation") == "transition_hint")
    if mutation == "duplicate":
        command = next(command for command in generic["timeline"] if op in command["operations"])
        command["operations"].append(copy.deepcopy(op))
    elif mutation == "range":
        op["parameters"]["incoming_frames"] = 0
    else:
        op["parameters"]["transition_type"] = "slide_transition"
    with pytest.raises(TransitionAuthorityError):
        build_transition_authority(generic, run_id="r1")


def test_no_transition_input_is_valid_and_deterministic():
    generic = _generic()
    for command in generic["timeline"]:
        command["operations"] = [op for op in command["operations"] if op.get("operation") != "transition_hint"]
    first = build_transition_authority(generic, run_id="r1")
    second = build_transition_authority(generic, run_id="r1")
    assert first == second
    assert first["summary"] == {"native_count": 0, "flash_handoff_count": 0, "decision_count": 0}


def test_authority_is_consumable_by_existing_compiler(tmp_path):
    generic = _generic()
    authority = build_transition_authority(generic, run_id="r1")
    authority_path = tmp_path / "authority.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")
    report = compile_fcpxml(GENERIC, tmp_path / "out.fcpxml", tmp_path / "report.json", transition_authority_path=authority_path, transition_run_id="r1")
    assert report["transition_authority"]["flash_handoff_count"] == 1
    assert report["structure"]["flash_handoff_count"] == 1
