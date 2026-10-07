from pathlib import Path

import numpy as np

from scripts.analysis.repair_multi_object_mask_isolation import unresolved_mask_fields
from scripts.standalone import video_cloner_font_inference as glyphs
from scripts.standalone import video_cloner_thickness_stroke as ownership


def test_fail_closed_mask_excludes_foreign_and_marks_ambiguity_unknown():
    target = np.zeros((5, 8), dtype=bool)
    target[1:4, 2:6] = True
    foreign = np.zeros_like(target)
    foreign[1:4, 4:7] = True
    ambiguous = np.zeros_like(target)
    ambiguous[:, 3:5] = True

    result = ownership.build_crop_ownership(target, [foreign], [ambiguous])

    assert not np.any(result["TARGET_OWNED"] & result["FOREIGN_IDENTITY"])
    assert not np.any(result["USABLE_BACKGROUND"] & result["FOREIGN_IDENTITY"])
    assert np.all(result["UNKNOWN_OR_OCCLUDED"][:, 3] & ~result["TARGET_OWNED"][:, 3])


def test_unresolved_mask_has_no_false_foreground_background_or_font_evidence():
    row = {"final_mask_shape": [5, 8], "observations": [{"accepted": True, "reason": "accepted", "bbox": [1, 2, 3, 4]}]}

    result = unresolved_mask_fields(row, "foreign_object_contamination")

    assert result["known_foreground_rle"] == result["known_background_rle"] == result["final_mask_rle"] == []
    assert result["unknown_rle"] == [[0, 40]]
    assert result["accepted_frame_count"] == 0
    assert result["observations"][0]["accepted"] is False
    assert result["evidence_classification"] == "CONTAMINATED_EVIDENCE"


def test_clean_temporal_evidence_survives_a_contaminated_frame():
    clean = np.zeros((8, 12), dtype=bool)
    clean[2:6, 3:9] = True
    rows = [{"frame": frame, "timestamp": frame / 10, "bbox": [0, 0, 12, 8], "mask": clean, "unknown_mask": np.zeros_like(clean), "foreground_confidence": .9, "contamination_score": .0, "overlap_risk": .0, "blur_quality": 1.0, "accepted": True} for frame in (1, 2)]
    rows.append({**rows[0], "frame": 3, "contamination_score": 1.0})

    result = glyphs.aggregate_source_masks(rows)

    assert result["usable_frame_count"] == 2
    assert result["foreground_mask"].shape == (4, 6)
    assert result["foreground_mask"].all()


def test_production_adapter_contains_no_reel_specific_rules():
    source = (Path(__file__).parents[1] / "scripts/analysis/repair_multi_object_mask_isolation.py").read_text(encoding="utf-8")
    assert "caption_tracklet_0068" not in source
    assert "caption_tracklet_0069" not in source
    assert '"listing"' not in source
    assert '"NOT"' not in source
