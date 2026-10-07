import copy

import pytest

from scripts.analysis.compile_step5a_f3_scale_authority import (
    absolute_size,
    compile_f3_contract,
    compile_scale_decision,
    load_scale_authorities,
)


def _row(identity: str = "sample", *, base: float = 0.4, renderable: bool = True, source: str = "STEP_4B_RAW_SAMPLE") -> dict:
    return {
        "source_identity": identity,
        "renderable": renderable,
        "source_interval": [10, 20],
        "size": {"resolve_value": base, "source_authority": "AUTHORITATIVE"},
        "keyframes": {"scale": [{"timeline_frame": 11, "local_frame": 1, "value": 1.3, "source": source}]},
    }


def _authority(identity: str = "sample") -> dict:
    return {
        "schema": "video_cloner_step5a_f3a2_scale_lifecycle_boundary_adjudication",
        "identity": identity,
        "authority": "ACCEPTED_SCALE_REPRODUCTION_ADJUDICATION",
        "relative_scale_anchors": [
            {"timeline_frame": 10, "relative_scale": 0.82, "phase": "ENTRY_EXPANSION"},
            {"timeline_frame": 11, "relative_scale": 1.0, "phase": "PLATEAU"},
            {"timeline_frame": 12, "relative_scale": 1.0, "phase": "PLATEAU"},
            {"timeline_frame": 13, "relative_scale": 0.9, "phase": "EXIT_CONTRACTION"},
        ],
        "phase_boundaries": {"contraction_start": {"timeline_frame": 13}},
        "interpolation_policy": {"overshoot_allowed": False},
        "_path": "accepted.json",
        "_sha256": "abc",
        "_phases": {
            "ENTRY_EXPANSION": {"interpolation": "LINEAR"},
            "PLATEAU": {"interpolation": "HOLD"},
            "EXIT_CONTRACTION": {"interpolation": "LINEAR"},
        },
    }


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["source_identity"]: row for row in rows}


def test_relative_scale_maps_to_each_identity_base_size() -> None:
    assert absolute_size(0.4, 1.0) == pytest.approx(0.4)
    assert absolute_size(0.4, 0.82) == pytest.approx(0.328)
    assert absolute_size(0.4, 1.3) == pytest.approx(0.52)
    first, _ = compile_scale_decision(_row("first", base=0.4), _authority("first"))
    second, _ = compile_scale_decision(_row("second", base=0.2), _authority("second"))
    assert first[0]["value"] == pytest.approx(0.328)
    assert second[0]["value"] == pytest.approx(0.164)
    assert all(key["value"] == pytest.approx(0.4 * key["relative_scale"]) for key in first)


def test_scale_gate_suppresses_measurements_labels_orphans_and_nonrenderable_rows() -> None:
    for label in ("SCALE", "SCALE_OVERSHOOT"):
        row = _row()
        row["derived_label"] = label
        keys, decision = compile_scale_decision(row, None)
        assert keys == []
        assert decision["scale_suppression_reason"] == "NO_ACCEPTED_REPRODUCTION_AUTHORITY_RAW_MEASUREMENTS_ONLY"
    orphan = _row(source="STEP_4C_EDITOR_NEUTRAL_KEYFRAME")
    assert compile_scale_decision(orphan, None)[1]["scale_suppression_reason"] == "NO_ACCEPTED_REPRODUCTION_AUTHORITY_ORPHAN_STEP4C"
    nonrenderable = _row(renderable=False)
    assert compile_scale_decision(nonrenderable, _authority())[0] == []
    assert compile_scale_decision(nonrenderable, _authority())[1]["scale_suppression_reason"] == "NON_RENDERABLE_IDENTITY"


def test_authority_is_consumed_generically_with_safe_segments() -> None:
    keys, decision = compile_scale_decision(_row(), _authority())
    assert decision["scale_authority_status"] == "AUTHORIZED"
    assert [key["interpolation_to_next"] for key in keys] == ["LINEAR", "HOLD", "LINEAR", "NONE"]
    assert [key["relative_scale"] for key in keys] == [0.82, 1.0, 1.0, 0.9]
    assert all(key["source"] == "STEP5A_F3A2_ACCEPTED_SCALE_AUTHORITY" for key in keys)



def test_whole_reel_f3_scale_contract_and_regressions() -> None:
    contract, validation, decisions = compile_f3_contract()
    assert (contract, validation, decisions) == compile_f3_contract()
    assert validation["all_pass"] is True
    assert contract["identity_count"] == 113
    assert contract["object_count"] == 62
    counts = validation["counts"]
    assert counts["current_f2_scale_key_count"] == 44
    assert counts["current_f2_renderable_scale_key_count"] == 43
    assert counts["authorized_scale_identities"] == 1
    assert counts["authorized_scale_identity_list"] == ["caption_tracklet_0089"]
    assert counts["authorized_relative_scale_key_count"] == 9
    assert counts["final_editor_scale_key_count"] == 9
    assert counts["suppressed_raw_measurement_scale_keys"] == 42
    assert counts["suppressed_orphan_scale_keys"] == 2
    assert counts["suppressed_renderable_orphan_scale_keys"] == 1
    assert counts["unauthorized_scale_commands"] == 0
    assert counts["non_renderable_scale_commands"] == 0
    assert counts["relative_as_absolute_unit_errors"] == 0
    assert counts["raw_ratio_as_absolute_count"] == 0

    rows = _by_id(contract["identity_records"])
    six_thousand = rows["caption_tracklet_0089"]
    keys = six_thousand["keyframes"]["scale"]
    expected_ratios = [0.82, 0.9, 0.96, 1.0, 1.0, 1.0, 0.96, 0.92, 0.86]
    assert [key["timeline_frame"] for key in keys] == list(range(542, 551))
    assert [key["relative_scale"] for key in keys] == expected_ratios
    base = six_thousand["size"]["resolve_value"]
    assert [key["value"] for key in keys] == pytest.approx([base * ratio for ratio in expected_ratios])
    assert [key["interpolation_to_next"] for key in keys] == ["LINEAR", "LINEAR", "LINEAR", "HOLD", "HOLD", "LINEAR", "LINEAR", "LINEAR", "NONE"]
    assert max(key["timeline_frame"] for key in keys) == 550
    assert all(right <= left for left, right in zip(expected_ratios[6:], expected_ratios[7:]))

    assert rows["continuous_visual_identity_0014"]["keyframes"]["scale"] == []
    assert rows["caption_tracklet_0067"]["keyframes"]["scale"] == []
    assert rows["caption_tracklet_0086"]["keyframes"]["scale"] == []
    assert rows["caption_tracklet_0087"]["keyframes"]["scale"] == []
    assert rows["caption_tracklet_0112"]["keyframes"]["scale"] == []
    assert all(row["keyframes"]["scale"] == [] for identity, row in rows.items() if identity != "caption_tracklet_0089")
    assert all(key["value"] == pytest.approx(base * key["relative_scale"]) for key in keys)


def test_f2_text_timing_position_and_other_domains_remain_exact() -> None:
    contract, _, _ = compile_f3_contract()
    f2 = __import__("json").loads((__import__("pathlib").Path(__file__).resolve().parents[1] / contract["base_f2_contract"]["path"]).read_text(encoding="utf-8-sig"))
    f2_rows = _by_id(f2["identity_records"])
    for row in contract["identity_records"]:
        before = copy.deepcopy(f2_rows[row["source_identity"]])
        after = copy.deepcopy(row)
        after.pop("scale_decision")
        before["keyframes"]["scale"] = []
        after["keyframes"]["scale"] = []
        assert after == before
    assert [row["text"] for row in contract["identity_records"]] == [row["text"] for row in f2["identity_records"]]
    assert [row["resolve_interval"] for row in contract["identity_records"]] == [row["resolve_interval"] for row in f2["identity_records"]]
    assert [row["keyframes"]["position"] for row in contract["identity_records"]] == [row["keyframes"]["position"] for row in f2["identity_records"]]


def test_pinned_f3a2_authority_loads_without_identity_specific_code() -> None:
    authorities, inputs = load_scale_authorities(__import__("pathlib").Path(__file__).resolve().parents[1])
    assert set(authorities) == set(inputs) == {"caption_tracklet_0089"}
    assert authorities["caption_tracklet_0089"]["authority"] == "ACCEPTED_SCALE_REPRODUCTION_ADJUDICATION"
