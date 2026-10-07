from pathlib import Path

import numpy as np

from scripts.standalone import video_cloner_font_inference as inference


FONTS = Path(r"C:\Windows\Fonts")


def test_source_visible_scoring_text_uses_bbox_linkage_not_transcript_text():
    evidence = {"text": "long transcript sentence", "observations": [{"accepted": True, "timestamp": 2.0, "bbox": [10, 20, 80, 50]}]}
    events = [{"event_id": "visual_1", "observed_text": "visible", "text": "long transcript sentence", "start": 1.5, "end": 2.5, "observations": [{"bbox": [11, 20, 79, 50]}]}]

    result = inference.source_visible_scoring_text(evidence, events)

    assert result["text"] == "visible"
    assert result["authority"] == "SOURCE_VISIBLE_OBSERVED_TEXT_BBOX_MATCH"


def test_source_pixel_authority_precedes_bbox_ocr_linkage_and_can_fail_closed():
    evidence = {
        "font_scoring_text_authority": {
            "text": None,
            "visual_text": "partial transition fragment",
            "authority": "SOURCE_VISIBLE_PIXELS_BOUNDED_LINKAGE_DECISION",
            "reason": "fragment_has_no_full_word_scoring_authority",
        },
        "observations": [{"accepted": True, "timestamp": 2.0, "bbox": [10, 20, 80, 50]}],
    }
    events = [{"event_id": "ocr", "observed_text": "unrelated transcript", "start": 1.5, "end": 2.5, "placement": {"bbox": [10, 20, 80, 50]}}]

    assert inference.source_visible_scoring_text(evidence, events) == evidence["font_scoring_text_authority"]


def test_source_visible_scoring_text_fails_closed_when_bbox_match_is_ambiguous():
    evidence = {"observations": [{"accepted": True, "timestamp": 2.0, "bbox": [10, 20, 80, 50]}]}
    events = [
        {"event_id": "a", "observed_text": "one", "start": 1.5, "end": 2.5, "observations": [{"bbox": [10, 20, 80, 50]}]},
        {"event_id": "b", "observed_text": "two", "start": 1.5, "end": 2.5, "observations": [{"bbox": [10, 20, 80, 50]}]},
    ]

    assert inference.source_visible_scoring_text(evidence, events)["reason"] == "ambiguous_source_visible_text_bbox_match"


def test_uniform_mask_comparison_preserves_aspect_and_rejects_non_uniform_fit():
    source = inference.render_text_mask("sign", FONTS / "ariblk.ttf")
    candidate = inference.render_text_mask("sign", FONTS / "arial.ttf")

    result = inference.compare_masks(source, candidate)

    assert result["non_uniform_scale_ratio"] == 1.0
    assert result["final_height"] == source.shape[0]
    assert result["candidate_aspect_ratio"] == round(candidate.shape[1] / candidate.shape[0], 6)


def test_candidate_ranking_is_deterministic_and_prefers_matching_glyphs():
    fonts = [
        {"family": "Arial", "style": "Bold", "weight": "Bold", "path": FONTS / "arialbd.ttf", "renderer_compatible": True},
        {"family": "Ink Free", "style": "Regular", "weight": "Regular", "path": FONTS / "Inkfree.ttf", "renderer_compatible": True},
    ]
    source = inference.render_text_mask("buyers", FONTS / "arialbd.ttf")

    first = inference.rank_font_candidates("buyers", source, fonts)
    second = inference.rank_font_candidates("buyers", source, list(reversed(fonts)))

    assert [(row["family"], row["style"], row["score"]) for row in first] == [
        (row["family"], row["style"], row["score"]) for row in second
    ]
    assert first[0]["family"] == "Arial"
    assert first[0]["score"] > first[1]["score"]


def test_source_mask_reports_low_confidence_instead_of_fabricating_empty_evidence():
    mask, confidence = inference.source_text_mask(np.zeros((40, 100, 3), dtype=np.uint8), "#ffffff")

    assert mask.shape == (1, 1)
    assert confidence == 0.0


def test_symbol_font_without_real_text_glyphs_is_rejected():
    assert inference.font_supports_text(FONTS / "arial.ttf", "sign") is True
    assert inference.font_supports_text(FONTS / "segmdl2.ttf", "sign") is False


def test_weak_real_world_score_fails_closed_as_unresolved():
    authority, confidence = inference.authority_classification(
        [{"score": 0.48}, {"score": 0.47}], 0.95
    )

    assert (authority, confidence) == ("UNRESOLVED_FONT_STYLE", "LOW")


def test_multi_frame_aggregation_is_order_independent_and_rejects_contamination():
    clean = inference.render_text_mask("hits", FONTS / "arial.ttf")
    corrupt = np.ones((clean.shape[0], clean.shape[1] * 2), dtype=bool)
    rows = [
        {"frame": frame, "timestamp": frame / 24, "bbox": [0, 0, clean.shape[1], clean.shape[0]],
         "mask": clean, "foreground_confidence": 0.8, "contamination_score": 0.05,
         "overlap_risk": 0.0, "blur_quality": 0.9, "accepted": True, "reason": "accepted"}
        for frame in (1, 2, 3)
    ] + [{"frame": 4, "timestamp": 4 / 24, "bbox": [0, 0, corrupt.shape[1], corrupt.shape[0]],
          "mask": corrupt, "foreground_confidence": 0.9, "contamination_score": 0.95,
          "overlap_risk": 0.9, "blur_quality": 0.9, "accepted": True, "reason": "accepted"}]

    first = inference.aggregate_source_masks(rows)
    second = inference.aggregate_source_masks(reversed(rows))

    assert np.array_equal(first["mask"], second["mask"])
    assert first["usable_frame_count"] == 3
    assert first["status"] == "CLEAN_MULTI_FRAME_EVIDENCE"
    assert inference.compare_masks(first["mask"], clean)["iou"] > 0.95


def test_tristate_evidence_is_deterministic_and_unknown_has_no_score_authority():
    foreground = np.zeros((8, 12), dtype=bool)
    foreground[2:6, 2:5] = True
    unknown = np.zeros_like(foreground)
    unknown[2:6, 7:10] = True
    background = ~(foreground | unknown)
    clean = foreground.copy()
    mismatch_only_unknown = foreground | unknown
    mismatch_known = foreground.copy()
    mismatch_known[0, 0] = True
    mismatch_foreground = foreground.copy()
    mismatch_foreground[2, 2] = False

    clean_score = inference.compare_known_regions(foreground, background, unknown, clean)
    unknown_score = inference.compare_known_regions(foreground, background, unknown, mismatch_only_unknown)
    known_score = inference.compare_known_regions(foreground, background, unknown, mismatch_known)
    foreground_score = inference.compare_known_regions(foreground, background, unknown, mismatch_foreground)

    assert clean_score == unknown_score
    assert known_score["score"] < clean_score["score"]
    assert foreground_score["score"] < clean_score["score"]
    assert foreground_score["foreground_mismatch_count"] == 1
    assert known_score["background_mismatch_count"] == 1
    assert unknown_score["unknown_pixel_count"] == int(unknown.sum())


def test_overlap_pixels_remain_unknown_and_residual_strip_reduces_confidence():
    glyph = np.zeros((20, 40), dtype=bool)
    glyph[4:17, 8:14] = True
    overlap = np.zeros_like(glyph)
    overlap[:, 10:18] = True
    clean_rows = [
        {"frame": frame, "timestamp": frame / 24, "bbox": [0, 0, 40, 20], "mask": glyph,
         "unknown_mask": overlap, "foreground_confidence": 0.8, "contamination_score": 0.05,
         "overlap_risk": 0.2, "blur_quality": 0.9, "accepted": True, "reason": "accepted"}
        for frame in (1, 2, 3)
    ]
    strip = glyph.copy()
    strip[1:2, :] = True
    strip_rows = [{**row, "mask": strip, "unknown_mask": np.zeros_like(strip)} for row in clean_rows]

    clean = inference.aggregate_source_masks(clean_rows)
    contaminated = inference.aggregate_source_masks(strip_rows)

    assert np.array_equal(clean["unknown_mask"], inference.aggregate_source_masks(reversed(clean_rows))["unknown_mask"])
    assert clean["unknown_mask"].any()
    assert not np.logical_and(clean["foreground_mask"], clean["unknown_mask"]).any()
    assert contaminated["artifact_penalty"] > 0
    assert contaminated["confidence"] < inference.aggregate_source_masks([
        {**row, "unknown_mask": np.zeros_like(glyph)} for row in clean_rows
    ])["confidence"]


def test_known_region_gate_fails_closed_without_discriminative_foreground():
    empty = np.zeros((20, 40), dtype=bool)

    passed, reason = inference.known_region_evidence_gate(
        empty, ~empty, empty, usable_frame_count=3
    )

    assert passed is False
    assert reason == "insufficient_known_foreground_pixels"
    assert inference.known_region_ranking_authority(
        [], evidence_gate_passed=passed, evidence_gate_reason=reason,
        evidence_classification="CONTAMINATED_EVIDENCE", unknown_ratio=0.0,
    ) == ("NO_AUTHORITATIVE_FONT_RANKING", reason)


def test_known_region_font_ranking_is_deterministic():
    source = inference.render_text_mask("sign", FONTS / "arial.ttf")
    foreground = np.pad(source, 4)
    unknown = np.zeros_like(foreground)
    background = ~foreground
    fonts = [
        {"family": "Arial", "style": "Regular", "weight": "Regular", "path": FONTS / "arial.ttf", "renderer_compatible": True},
        {"family": "Arial", "style": "Bold", "weight": "Bold", "path": FONTS / "arialbd.ttf", "renderer_compatible": True},
    ]

    first, first_count = inference.rank_font_candidates_known_regions("sign", foreground, background, unknown, fonts)
    second, second_count = inference.rank_font_candidates_known_regions("sign", foreground, background, unknown, list(reversed(fonts)))

    assert first == second
    assert first_count == second_count == 2
    assert first[0]["family"] == "Arial"


def test_known_region_coarse_shortlist_retains_full_pool_winner():
    fonts = inference.discover_installed_fonts()
    source = inference.render_text_mask("sign", FONTS / "impact.ttf")
    foreground = np.pad(source, 12)
    unknown = np.zeros_like(foreground)
    background = ~foreground
    full_pool = []
    for font in fonts:
        if not inference.font_supports_text(font["path"], "sign"):
            continue
        try:
            mask = inference.render_text_mask("sign", font["path"])
        except OSError:
            continue
        full_pool.append((
            -float(inference.compare_known_regions(foreground, background, unknown, mask)["score"]),
            str(font["family"]).casefold(), str(font["style"]).casefold(),
        ))
    expected = min(full_pool)[1:]

    ranking, compared = inference.rank_font_candidates_known_regions(
        "sign", foreground, background, unknown, list(reversed(fonts)),
    )

    assert compared == 16
    assert (ranking[0]["family"].casefold(), ranking[0]["style"].casefold()) == expected
