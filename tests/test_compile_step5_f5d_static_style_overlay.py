from __future__ import annotations

import json

from scripts.analysis.compile_step5_f5d_static_style_overlay import (
    F5A_CONTRACT,
    ROOT,
    _bytes,
    compile_f5_contract,
)


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["source_identity"]: row for row in rows}


def test_all_nine_human_approvals_compile_to_generic_style_ir() -> None:
    authority, contract, validation = compile_f5_contract()
    rows = _by_id(contract["objects"])

    assert authority["human_decision_count"] == authority["human_approved_count"] == 9
    assert authority["pending_human_decisions"] == 0
    assert all(row["human_approved"] is True for row in authority["records"])

    assert rows["continuous_visual_identity_0028"]["font"]["resolve_family"] == "Tahoma"
    assert rows["continuous_visual_identity_0028"]["font"]["resolve_style"] == "Bold"
    assert rows["continuous_visual_identity_0028"]["fill"]["resolve_rgb"] == [205, 139, 99]

    listing = rows["recovered_display_object_listing_0003"]
    assert (listing["font"]["resolve_family"], listing["font"]["resolve_style"]) == ("Arial", "Black")
    assert listing["fill"]["resolve_rgb"] == [250, 218, 172]
    assert listing["size"]["resolve_value"] == listing["scale_decision"]["static_base_size"] == 0.113888889
    assert listing["position"]["resolve_center"] == [0.50555556, 0.603125]
    assert listing["resolve_interval"] == [330, 347]

    buyers = rows["caption_tracklet_0097"]
    assert (buyers["font"]["resolve_family"], buyers["font"]["resolve_style"]) == ("Arial", "Black")
    assert buyers["font"]["italic"] is True
    assert buyers["font"]["italic_treatment"] == {
        "type": "textplus_transform_shear",
        "input": "TransformShear",
        "value": 0.08393,
        "authority": "SOURCE_MEASURED_VERTICAL_SLANT_PROXY",
    }

    why = rows["recovered_display_object_why_0001"]
    assert (why["font"]["resolve_family"], why["font"]["resolve_style"]) == ("Tahoma", "Bold")
    assert why["fill"]["type"] == "linear_gradient"
    assert why["fill"]["orientation"] == "HORIZONTAL"
    assert why["fill"]["direction"] == "LEFT_TO_RIGHT_A_TO_B"
    assert why["fill"]["stops"] == [
        {"position": 0.0, "rgb": [190, 68, 78]},
        {"position": 1.0, "rgb": [169, 50, 115]},
    ]
    assert why["opacity"]["mode"] == "constant"
    assert why["opacity"]["resolve_value"] == 0.75
    assert "opacity_stops" not in json.dumps(why, sort_keys=True)
    assert why["keyframes"]["relative_visibility"] == []

    local_we = rows["recovered_display_object_local_we_0002"]
    assert (local_we["font"]["resolve_family"], local_we["font"]["resolve_style"]) == ("Segoe UI", "Regular")
    assert validation["all_pass"] is True


def test_protected_domains_and_required_controls_are_unchanged() -> None:
    _, contract, validation = compile_f5_contract()
    base = json.loads((ROOT / F5A_CONTRACT).read_text(encoding="utf-8"))
    base_objects, objects = _by_id(base["objects"]), _by_id(contract["objects"])
    base_identities, identities = _by_id(base["identity_records"]), _by_id(contract["identity_records"])

    assert len(contract["identity_records"]) == 113
    assert contract["base_renderable_identity_count"] == 62
    assert contract["recovered_display_object_count"] == 3
    assert len(contract["objects"]) == 65
    for key in ("text_domain_unchanged", "timing_domain_unchanged", "scale_domain_unchanged", "lifecycle_domain_unchanged", "ownership_domain_unchanged", "position_domain_unchanged", "motion_rotation_visibility_unchanged"):
        assert validation["checks"][key] is True

    for identity in ("caption_tracklet_0045", "caption_tracklet_0064", "caption_tracklet_0089", "continuous_visual_identity_0113"):
        assert objects[identity] == base_objects[identity]
    for identity in ("caption_tracklet_0061", "caption_tracklet_0062", "caption_tracklet_0063"):
        assert identities[identity] == base_identities[identity]
    assert identities["caption_tracklet_0061"]["text"]["value"] == "reels"
    assert identities["caption_tracklet_0061"]["renderable"] is True
    assert identities["caption_tracklet_0062"]["renderable"] is False
    assert identities["caption_tracklet_0063"]["renderable"] is False


def test_generalization_guards_and_determinism_pass() -> None:
    first = compile_f5_contract()
    second = compile_f5_contract()
    validation = first[2]
    assert validation["production_branch_counts"] == {"literal": 0, "identity": 0, "reel": 0, "human_choice": 0}
    assert [_bytes(value) for value in first] == [_bytes(value) for value in second]
    assert validation["resolve_mutated"] is False
    assert validation["result"] == "PASS_F5_HUMAN_APPROVED_STATIC_STYLE_IMPLEMENTATION"
