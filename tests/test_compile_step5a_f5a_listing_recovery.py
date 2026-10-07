from __future__ import annotations

import ast
import json
from pathlib import Path

import scripts.analysis.compile_step5a_f5a_listing_recovery as compiler

from scripts.analysis.compile_step5a_f5a_listing_recovery import (
    AUTHORITY,
    AUTHORITY_SHA256,
    F4_CONTRACT,
    ROOT,
    compile_f5a_contract,
    load_listing_authority,
)


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["source_identity"]: row for row in rows}


def test_authority_lifecycle_geometry_and_mapping_are_source_pinned() -> None:
    authority = load_listing_authority()
    record = authority["recovery_objects"][0]
    assert len(authority["recovery_objects"]) == 1
    assert record["accepted_display_text"] == "listing"
    assert [record["source_visible_start_frame"], record["source_visible_end_frame"] + 1] == [413, 433]
    assert [record["timeline_start_frame"], record["timeline_end_frame"]] == [330, 347]
    assert record["source_bbox"] == [414, 721, 678, 803]
    assert record["resolve_center"] == [0.50555556, 0.603125]
    assert record["source_height_px"] == 82.0
    assert record["composition_relationship"]["relationship"] == "SEQUENTIAL_NO_OVERLAP"
    assert record["source_provenance"]["following_object_first_source_frame"] == 433
    assert compiler._sha256(ROOT / AUTHORITY) == AUTHORITY_SHA256


def test_one_generic_recovery_preserves_all_f4_objects_and_identities() -> None:
    _, contract, validation = compile_f5a_contract()
    f4 = json.loads((ROOT / F4_CONTRACT).read_text(encoding="utf-8"))
    base_rows = _by_id(f4["identity_records"])
    rows = _by_id(contract["identity_records"])
    assert validation["all_pass"] is True
    assert len(contract["identity_records"]) == 113
    assert len(f4["objects"]) == 64
    assert len(contract["objects"]) == 65
    assert contract["identity_records"] == f4["identity_records"]
    assert contract["objects"][:-1] == f4["objects"]
    assert rows["caption_tracklet_0061"]["renderable"] is True
    assert rows["caption_tracklet_0061"]["text"]["value"] == "reels"
    assert rows["caption_tracklet_0062"]["renderable"] is False
    assert rows["caption_tracklet_0063"]["renderable"] is False
    assert rows["caption_tracklet_0045"] == base_rows["caption_tracklet_0045"]
    assert rows["caption_tracklet_0064"] == base_rows["caption_tracklet_0064"]
    assert rows["continuous_visual_identity_0113"] == base_rows["continuous_visual_identity_0113"]
    assert [row["text"]["value"] for row in contract["objects"][62:64]] == ["why?", "We"]
    assert contract["recovered_display_object_count"] == 3


def test_listing_is_independent_and_style_and_motion_remain_unresolved() -> None:
    _, contract, _ = compile_f5a_contract()
    listing = contract["objects"][-1]
    assert listing["object_origin"] == "RECOVERED_DISPLAY_OBJECT"
    assert listing["source_identity"] == "recovered_display_object_listing_0003"
    assert listing["text"]["value"] == "listing"
    assert listing["source_interval"] == [330, 347]
    assert listing["position"]["source_bbox"] == [414, 721, 678, 803]
    assert listing["size"]["source_height_px"] == 82.0
    assert listing["font"]["source_authority"] == "STYLE_UNRESOLVED_PENDING_F5"
    assert listing["composition"]["neighbor_identity"] == "caption_tracklet_0061"
    assert listing["composition"]["ownership"] == "INDEPENDENT_DISPLAY_OBJECT"
    assert all(not values for values in listing["keyframes"].values())
    assert contract["resolve_mutated"] is False


def test_required_18_checks_pass_and_all_existing_domains_are_byte_semantic_equal() -> None:
    _, contract, validation = compile_f5a_contract()
    f4 = json.loads((ROOT / F4_CONTRACT).read_text(encoding="utf-8"))
    required = [key for key in validation["checks"] if key[:2].isdigit()]
    assert len(required) == 18
    assert all(validation["checks"][key] for key in required)
    for field in ("source_interval", "text", "scale_decision", "font", "position", "composition"):
        assert [row.get(field) for row in contract["objects"][:-1]] == [row.get(field) for row in f4["objects"]]
    assert validation["counts"] == {
        "base_frozen_identities": 113,
        "base_renderable_identities": 62,
        "preexisting_recovered_display_objects": 2,
        "total_recovered_display_objects": 3,
        "final_renderable_objects": 65,
    }


def test_production_has_no_literal_identity_reel_or_recovery_id_branch() -> None:
    source = Path(compiler.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = (
        "listing",
        "reels",
        "caption_tracklet_0061",
        "caption_tracklet_0062",
        "caption_tracklet_0063",
        "dcjrjtukscu",
        "recovered_display_object_listing_0003",
    )
    hits = []
    for node in ast.walk(tree):
        expression = node.test if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)) else None
        if expression is None:
            continue
        values = [child.value for child in ast.walk(expression) if isinstance(child, ast.Constant) and isinstance(child.value, str)]
        hits.extend((node.lineno, value) for value in values if any(token in value.lower() for token in forbidden))
    assert hits == []
