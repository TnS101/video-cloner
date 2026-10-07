from __future__ import annotations

import ast
from pathlib import Path

from scripts.analysis.compile_step5a_f9_canonical_display_ownership import compile_contract, digest

ROOT = Path(__file__).resolve().parents[1]


def test_all_113_identities_resolve_deterministically() -> None:
    first = compile_contract()
    second = compile_contract()
    contract, audit, validation, _authority = first
    assert digest(first) == digest(second)
    assert audit["base_identity_count"] == 113
    assert audit["compositions_audited"] == 15
    assert sum(audit["role_counts"].values()) == 113
    assert audit["ownership_conflicts"] == []
    assert audit["source_required_missing_objects"] == []
    assert audit["unsupported_duplicate_owners"] == []
    assert validation["all_pass"] is True
    assert validation["same_track_overlap_count"] == 0
    assert validation["carrier_plan"]["title_count"] == contract["object_count"] == 65


def test_source_backed_failure_cases_and_unrelated_fragments() -> None:
    contract, audit, validation, _authority = compile_contract()
    objects = {row["source_identity"]: row for row in contract["objects"]}
    assert objects["caption_tracklet_0082"]["text"]["value"] == "calling"
    assert "caption_tracklet_0083" not in objects
    assert objects["caption_tracklet_0090"]["text"]["value"] == "buyers"
    assert "caption_tracklet_0091" not in objects
    assert objects["caption_tracklet_0101"]["text"]["value"] == "with"
    assert "caption_tracklet_0102" not in objects
    assert objects["caption_tracklet_0105"]["text"]["value"] == "have"
    assert objects["caption_tracklet_0106"]["text"]["value"] == "we"
    assert objects["caption_tracklet_0107"]["text"]["value"] == "have"
    assert objects["caption_tracklet_0043"]["text"]["value"] == "your"
    assert objects["continuous_visual_identity_0014"]["resolve_interval"] == [68, 108]
    assert "caption_tracklet_0013" not in objects
    assert objects["caption_tracklet_0094"]["text"]["value"] == "Matching"
    assert objects["caption_tracklet_0094"]["resolve_interval"] == [599, 629]
    assert "caption_tracklet_0096" not in objects
    assert all(row["ok"] for row in audit["targeted_cases"])
    for identity in ("caption_tracklet_0002", "caption_tracklet_0030", "caption_tracklet_0031", "caption_tracklet_0032", "caption_tracklet_0050"):
        assert identity in objects
    assert sum(row["text"]["value"] == "personally" for row in objects.values()) == 3
    assert validation["checks"]["f3_scale_unchanged"] is True
    assert validation["checks"]["f5_style_unchanged"] is True
    assert validation["checks"]["f6_6000_lifecycle"] is True
    assert validation["checks"]["f3_6000_scale_keys"] is True
    assert validation["checks"]["unrelated_controls_unchanged"] is True


def test_resolver_has_no_case_specific_production_branch_and_runtime_count_is_dynamic() -> None:
    source = (ROOT / "scripts/analysis/compile_step5a_f9_canonical_display_ownership.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"calling", "ling", "buy", "ers", "buyers", "the", "we", "have", "your", "why?", "selling", "matching"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
            assert not any(isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value.casefold() in banned for child in ast.walk(node))
    runtime = (ROOT / "resolve_workspace/modules/video_cloner_step5_f9_canonical_rebuild.py").read_text(encoding="utf-8")
    assert "count != 65" not in runtime
    assert 'audit.get("final_renderable_object_count") != count' in runtime
