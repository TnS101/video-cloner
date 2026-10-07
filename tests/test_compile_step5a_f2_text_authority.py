import copy

from scripts.analysis.compile_step5a_f2_text_authority import compile_f2_contract, select_display_text
from scripts.analysis.compile_step5a_textplus_contract import compile_contract as compile_base_contract


def _link(identity: str, relationship: str, contract: str, source: str | None, font: str | None) -> dict:
    return {
        "identity": identity,
        "contract_text": contract,
        "source_visible_text": source,
        "font_scoring_text": font,
        "text_mask_relationship": relationship,
        "source_evidence_provenance": {"authority": "SOURCE_VISIBLE_PIXELS_BOUNDED_LINKAGE_DECISION"},
    }


def _by_id(rows: list[dict], key: str = "identity") -> dict[str, dict]:
    return {row[key]: row for row in rows}


def _without_text(row: dict) -> dict:
    value = copy.deepcopy(row)
    value.pop("text", None)
    value.pop("renderable", None)
    value.pop("display_text_decision", None)
    return value


def test_generic_selection_precedence_and_fail_closed_policy() -> None:
    unresolved = select_display_text(_link("a", "EXPLICITLY_UNRESOLVED", "diagnostic", None, "diagnostic"), None, None)
    assert unresolved["renderable"] is False
    assert unresolved["suppression_reason"] == "EXPLICITLY_UNRESOLVED_WITHOUT_HIGHER_AUTHORITY"

    mismatch = select_display_text(_link("b", "MISMATCH", "word", "noise", "word"), None, None)
    assert mismatch["renderable"] is False
    assert mismatch["suppression_reason"] == "UNSAFE_MISMATCH_WITHOUT_HIGHER_AUTHORITY"

    visual = select_display_text(_link("c", "EXACT_MATCH", "wrong", "RIGHT", "RIGHT"), None, None)
    assert visual["renderable"] is True
    assert visual["selected_display_text"] == "RIGHT"
    assert visual["display_text_authority"] == "STRONG_ACCEPTED_VISUAL_TEXT"

    inconsistent = select_display_text(_link("d", "EXACT_MATCH", "home.", "home", "home."), None, None)
    assert inconsistent["renderable"] is False

    fragment = select_display_text(_link("e", "ACCEPTED_VISUAL_FRAGMENT", "calling", "calling", "ling"), None, None)
    assert fragment["renderable"] is True
    assert fragment["selected_display_text"] == "ling"

    owner = {
        "accepted_display_text": "accepted",
        "display_object_group_id": "g",
        "case": "CASE",
        "disposition": "RENDERABLE_CANONICAL_OWNER",
        "canonical_owner_identity": "f",
    }
    alias = {**owner, "disposition": "NON_RENDERING_LIFECYCLE_ALIAS_MERGED_INTO_CANONICAL_OWNER"}
    duplicate = {**owner, "disposition": "SUPPRESS_UNRESOLVED_DUPLICATE"}
    assert select_display_text(_link("f", "MISMATCH", "x", "y", "x"), owner, None)["selected_display_text"] == "accepted"
    assert select_display_text(_link("g", "MISMATCH", "x", "y", "x"), alias, None)["renderable"] is False
    assert select_display_text(_link("h", "EXPLICITLY_UNRESOLVED", "x", None, "x"), duplicate, None)["renderable"] is False

    duplicate_one = select_display_text(_link("i", "EXACT_MATCH", "same", "same", "same"), None, None)
    duplicate_two = select_display_text(_link("j", "EXACT_MATCH", "same", "same", "same"), None, None)
    assert duplicate_one["renderable"] is duplicate_two["renderable"] is True


def test_whole_reel_f2_authority_accounting_and_regressions() -> None:
    contract, validation, decisions_artifact = compile_f2_contract()
    rerun = compile_f2_contract()
    assert (contract, validation, decisions_artifact) == rerun
    assert validation["all_pass"] is True
    counts = validation["counts"]
    assert counts == {
        "total_frozen_identities": 113,
        "renderable_identities": 62,
        "non_rendering_alias_identities": 1,
        "suppressed_unresolved_identities": 47,
        "suppressed_unsafe_mismatch_identities": 0,
        "suppressed_other_unsafe_identities": 3,
        "adjudicated_display_text_identities": 5,
        "source_visual_text_identities": 19,
        "accepted_fragment_identities": 10,
        "safe_contract_text_identities": 31,
    }
    decisions = _by_id(decisions_artifact["decisions"])
    objects = _by_id(contract["objects"], "source_identity")

    assert decisions["caption_tracklet_0045"]["selected_display_text"] == "invest"
    assert decisions["caption_tracklet_0045"]["renderable"] is True
    assert decisions["caption_tracklet_0044"]["renderable"] is False
    assert decisions["caption_tracklet_0048"]["renderable"] is False
    assert sum(row["selected_display_text"] == "invest" and row["renderable"] for row in decisions.values()) == 1
    assert decisions["caption_tracklet_0064"]["selected_display_text"] == "social"
    assert decisions["caption_tracklet_0066"]["renderable"] is False
    assert sum(row["selected_display_text"] == "social" and row["renderable"] for row in decisions.values()) == 1
    assert decisions["caption_tracklet_0044"]["selected_display_text"] is None

    assert decisions["continuous_visual_identity_0113"]["selected_display_text"] == "PAMELA"
    assert decisions["caption_tracklet_0114"]["renderable"] is False
    assert decisions["caption_tracklet_0115"]["renderable"] is False
    assert decisions["caption_tracklet_0012"]["selected_display_text"] == "launch"
    assert decisions["caption_tracklet_0061"]["selected_display_text"] == "reels"

    dump_ids = {
        "caption_tracklet_0034",
        "caption_tracklet_0035",
        "caption_tracklet_0038",
        "caption_tracklet_0053",
        "caption_tracklet_0056",
        "caption_tracklet_0071",
        "caption_tracklet_0074",
    }
    assert all(
        not decisions[identity]["renderable"]
        or decisions[identity]["selected_display_text"] != decisions[identity]["contract_text"]
        for identity in dump_ids
    )
    assert validation["full_sentence_dump_cases_remaining"] == []
    assert validation["unsafe_visible_text_identities"] == []
    assert validation["other_text_authority_blockers"] == []
    assert set(objects) == {row["identity"] for row in decisions.values() if row["renderable"]}

    base, _ = compile_base_contract()
    base_rows = _by_id(base["objects"], "source_identity")
    all_rows = _by_id(contract["identity_records"], "source_identity")
    assert set(base_rows) == set(all_rows)
    assert all(_without_text(base_rows[identity]) == _without_text(all_rows[identity]) for identity in base_rows)
    assert contract["resolve_mutated"] is False
    assert all(row["match"] for row in contract["freeze_integrity"])
