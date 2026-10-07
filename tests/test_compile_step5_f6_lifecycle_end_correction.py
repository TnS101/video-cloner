from __future__ import annotations

import json

from scripts.analysis.compile_step5_f6_lifecycle_end_correction import (
    F5_CONTRACT,
    ROOT,
    _bytes,
    compile_f6_contract,
)


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["source_identity"]: row for row in rows}


def test_source_proven_half_open_boundary_uses_canonical_mapping() -> None:
    authority, contract, validation = compile_f6_contract()
    record = authority["records"][0]
    target = _by_id(contract["objects"])[record["object_id"]]

    assert record["last_visible_source_frame"] == 744
    assert record["first_nonvisible_source_frame"] == record["source_end_exclusive"] == 745
    assert record["accepted_timeline_end_exclusive"] == round(745 / 30.0 * 24.0) == 596
    assert record["original_timeline_interval"] == [542, 570]
    assert record["accepted_timeline_interval"] == target["source_interval"] == target["resolve_interval"] == [542, 596]
    assert target["source_interval"][0] == 542
    assert target["source_interval"][1] > 570
    assert validation["checks"]["canonical_source_timeline_mapping_used"] is True
    assert validation["checks"]["source_end_is_half_open"] is True


def test_only_lifecycle_end_changes_and_f5_domains_remain_frozen() -> None:
    authority, contract, validation = compile_f6_contract()
    base = json.loads((ROOT / F5_CONTRACT).read_text(encoding="utf-8"))
    target_id = authority["records"][0]["object_id"]
    base_objects, objects = _by_id(base["objects"]), _by_id(contract["objects"])
    base_identities, identities = _by_id(base["identity_records"]), _by_id(contract["identity_records"])

    assert len(contract["identity_records"]) == 113
    assert contract["base_renderable_identity_count"] == 62
    assert contract["recovered_display_object_count"] == 3
    assert len(contract["objects"]) == contract["final_renderable_object_count"] == 65
    assert (contract["human_decision_count"], contract["human_approved_count"], contract["pending_human_decisions"]) == (9, 9, 0)
    assert validation["counts"]["corrected_lifecycle_identities"] == 1
    assert validation["checks"]["only_authorized_lifecycle_records_changed"] is True
    for key, value in validation["checks"].items():
        assert value is True, key

    for before, after in ((base_objects, objects), (base_identities, identities)):
        for identity in before:
            expected = json.loads(json.dumps(before[identity]))
            if identity == target_id:
                expected["source_interval"][1] = 596
                expected["resolve_interval"][1] = 596
            assert after[identity] == expected

    target_before, target_after = base_objects[target_id], objects[target_id]
    assert target_after["text"] == target_before["text"]
    assert target_after["position"] == target_before["position"]
    assert (target_after.get("composition"), target_after.get("object_origin")) == (target_before.get("composition"), target_before.get("object_origin"))
    assert target_after["keyframes"]["scale"] == target_before["keyframes"]["scale"]
    assert target_after["scale_decision"] == target_before["scale_decision"]
    assert len(target_after["keyframes"]["scale"]) == 9
    assert [key["timeline_frame"] for key in target_after["keyframes"]["scale"]] == [542, 543, 544, 545, 546, 547, 548, 549, 550]
    assert max(key["timeline_frame"] for key in target_after["keyframes"]["scale"]) == 550


def test_generalization_guards_and_determinism_pass() -> None:
    first = compile_f6_contract()
    second = compile_f6_contract()
    validation = first[2]

    assert validation["production_branch_counts"] == {"literal": 0, "identity": 0, "reel": 0}
    assert [_bytes(value) for value in first] == [_bytes(value) for value in second]
    assert validation["resolve_mutated"] is False
    assert validation["result"] == "PASS_F6_6000_LIFECYCLE_CORRECTION"
