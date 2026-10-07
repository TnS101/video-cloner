from scripts.analysis.compile_step5a_textplus_contract import compile_contract


def test_step5a_contract_is_authority_aware_and_complete() -> None:
    contract, preflight = compile_contract()
    assert preflight["all_pass"] is True
    assert contract["object_count"] == 113
    assert len({row["source_identity"] for row in contract["objects"]}) == 113
    assert sum(bool(row["advanced_effects"]["shadow"]) for row in contract["objects"]) == 1
    assert all(
        0 <= key["value"] <= 1
        and key["source_relative_value"] >= 0
        and key["mapping"] == "PER_IDENTITY_PEAK_NORMALIZED_RELATIVE_VISIBILITY_NOT_ABSOLUTE_ALPHA"
        for row in contract["objects"]
        for key in row["keyframes"]["relative_visibility"]
    )
    six_thousand = [row for row in contract["objects"] if row["text"]["value"] == "6000"]
    assert len(six_thousand) == 2
    assert all(not row["keyframes"]["rotation"] for row in six_thousand)
    assert all(
        row["advanced_effects"]["clipping"] == row["advanced_effects"]["caption_occlusion"] == "UNSUPPORTED_OMITTED"
        for row in contract["objects"]
    )
