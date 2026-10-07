from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

import scripts.analysis.compile_step5a_f4_display_object_recovery as compiler

from scripts.analysis.compile_step5a_f4_display_object_recovery import (
    AUTHORITY_SHA256,
    F3_CONTRACT,
    ROOT,
    _sha256,
    _validate_record,
    append_recovery_objects,
    compile_f4_contract,
    load_recovery_authority,
)


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["source_identity"]: row for row in rows}


def test_recovery_authority_parses_generically_and_is_pinned() -> None:
    authority, path = load_recovery_authority()
    assert authority["authority"] == "ACCEPTED_DISPLAY_OBJECT_RECOVERY"
    assert _sha256(path) == AUTHORITY_SHA256
    assert len(authority["recovery_objects"]) == 2


def test_recovery_requires_source_supported_lifecycle_and_text() -> None:
    authority, _ = load_recovery_authority()
    record = copy.deepcopy(authority["recovery_objects"][0])
    record["source_visible_start_frame"] = None
    with pytest.raises(ValueError, match="integer_lifecycle"):
        _validate_record(record, authority)
    record = copy.deepcopy(authority["recovery_objects"][0])
    record["accepted_display_text"] = ""
    with pytest.raises(ValueError, match="proven_text"):
        _validate_record(record, authority)


def test_whole_reel_f4_contract_recovers_two_objects_without_mutating_base() -> None:
    contract, validation, decisions = compile_f4_contract()
    f3 = json.loads((ROOT / F3_CONTRACT).read_text(encoding="utf-8"))
    assert validation["all_pass"] is True
    assert validation["counts"] == {
        "base_frozen_identities": 113,
        "base_renderable_identities": 62,
        "recovered_display_objects": 2,
        "final_renderable_objects": 64,
    }
    assert contract["identity_records"] == f3["identity_records"]
    assert contract["objects"][:62] == f3["objects"]
    assert [row["method"] for row in decisions["decisions"]] == ["ACCEPTED_DISPLAY_OBJECT_RECOVERY"] * 2


def test_bounded_missing_objects_and_invest_ownership_match_source_evidence() -> None:
    contract, _, _ = compile_f4_contract()
    base = _by_id(contract["identity_records"])
    recovered = {row["text"]["value"]: row for row in contract["objects"] if row.get("object_origin") == "RECOVERED_DISPLAY_OBJECT"}
    assert recovered["why?"]["source_interval"] == [222, 233]
    assert recovered["why?"]["position"]["source_bbox"] == [212, 290, 918, 520]
    assert recovered["We"]["source_interval"] == [238, 287]
    assert recovered["We"]["composition"]["neighbor_identity"] == "caption_tracklet_0045"
    assert base["caption_tracklet_0045"]["renderable"] is True
    assert base["caption_tracklet_0045"]["text"]["value"] == "invest"
    assert base["caption_tracklet_0044"]["renderable"] is False
    assert base["caption_tracklet_0044"]["text"]["value"] is None


def test_duplicate_regressions_and_f3_scale_decisions_remain_exact() -> None:
    contract, _, _ = compile_f4_contract()
    f3 = json.loads((ROOT / F3_CONTRACT).read_text(encoding="utf-8"))
    rows = _by_id(contract["identity_records"])
    assert rows["caption_tracklet_0064"]["renderable"] is True
    assert rows["caption_tracklet_0064"]["text"]["value"] == "social"
    assert rows["caption_tracklet_0066"]["renderable"] is False
    assert rows["continuous_visual_identity_0113"]["text"]["value"] == "PAMELA"
    assert rows["caption_tracklet_0114"]["renderable"] is False
    assert rows["caption_tracklet_0115"]["renderable"] is False
    assert [row["scale_decision"] for row in contract["identity_records"]] == [row["scale_decision"] for row in f3["identity_records"]]


def test_repeated_semantic_words_are_not_globally_deduplicated() -> None:
    authority, path = load_recovery_authority()
    first = copy.deepcopy(authority["recovery_objects"][0])
    second = copy.deepcopy(authority["recovery_objects"][1])
    first["accepted_display_text"] = second["accepted_display_text"] = "repeat"
    objects = append_recovery_objects([], [first, second], path.relative_to(ROOT), AUTHORITY_SHA256)
    assert [row["text"]["value"] for row in objects] == ["repeat", "repeat"]


def test_production_has_no_caption_literal_identity_or_reel_specific_branch() -> None:
    source = Path(compiler.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = ("why", "caption_tracklet_", "continuous_visual_identity_", "dcjrjtukscu")
    hits = []
    for node in ast.walk(tree):
        expression = node.test if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)) else None
        if expression is None:
            continue
        for value in (child.value for child in ast.walk(expression) if isinstance(child, ast.Constant) and isinstance(child.value, str)):
            if any(token in value.lower() for token in forbidden):
                hits.append((node.lineno, value))
    assert hits == []
