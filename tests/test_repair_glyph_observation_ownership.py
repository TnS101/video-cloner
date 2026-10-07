from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/repair_glyph_observation_ownership.py"
SPEC = importlib.util.spec_from_file_location("ownership", SCRIPT)
ownership = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(ownership)


def test_rejects_only_selected_cross_identity_observation():
    glyph = {"identity_count": 2, "summary": {}, "identities": [
        {"identity": "a", "evidence_classification": "CLEAN_SINGLE_FRAME_EVIDENCE", "observations": [{"source_frame": 7, "bbox": [1, 2, 3, 4], "accepted": True, "reason": "accepted"}]},
        {"identity": "b", "evidence_classification": "CLEAN_SINGLE_FRAME_EVIDENCE", "observations": []},
    ]}
    font = {"approved_v2_authority": {}, "identities": [
        {"identity": "a", "text": "wrong", "font_rerank_status": "AUTHORITATIVE_FONT_RANKING", "top_candidates": [{"family": "Impact"}]},
        {"identity": "b", "text": "kept", "font_rerank_status": "PROVISIONAL_FONT_RANKING", "top_candidates": []},
    ]}
    reduction = {"identity_count": 2, "identities": [{"identity": "a", "full_pool_exact_comparisons": 9}, {"identity": "b", "full_pool_exact_comparisons": 8}], "gate_failed_identities": []}
    decision = {"identity": "a", "source_frame": 7, "bbox": [1, 2, 3, 4], "rejection_reason": "cross_identity"}
    repaired_glyph, repaired_font, repaired_reduction = ownership.repair(glyph, font, reduction, decision)
    assert repaired_glyph["identities"][0]["accepted_frame_count"] == 0
    assert repaired_glyph["identities"][0]["unknown_rle"] == [[0, 1]]
    assert repaired_glyph["identities"][1] == glyph["identities"][1]
    assert repaired_font["identities"][0]["font_rerank_status"] == "NO_AUTHORITATIVE_FONT_RANKING"
    assert repaired_reduction["gate_failed_identities"][0]["identity"] == "a"
    assert repaired_reduction["full_pool_exact_comparisons"] == 8
