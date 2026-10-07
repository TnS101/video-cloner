from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.davinci import compile_davinci_textplus_fcpxml as canonical
from scripts.standalone.video_cloner_textplus import (
    StandaloneTextplusError,
    render_visual_compositions,
    resolve_visual_style_authority,
)


ROOT = Path(__file__).parents[1]
STYLE = ROOT / "data" / "DcJRJtUKScu" / "analysis" / "DcJRJtUKScu_caption_style.json"


def _token(token_id: str, text: str, semantic_ids: list[str], window: list[int], event_id: str) -> dict:
    return {
        "token_id": token_id,
        "visual_event_identity": "test_" + token_id.removeprefix("visual_token_"),
        "text": text,
        "semantic_ids": semantic_ids,
        "window": window,
        "style_evidence_id": event_id,
    }


def test_reel2_exact_visual_style_authority_compiles_without_reset_or_rematch(monkeypatch):
    style_data = json.loads(STYLE.read_text(encoding="utf-8-sig"))
    compositions = [
        {
            "composition_id": "visual_composition_sub_004",
            "window": [20, 24],
            "authority": {"kind": "transcript_fallback", "evidence_ids": ["style_event_sub_0004"]},
            "tokens": [_token("visual_token_sub_004", "list", ["sub_004"], [20, 24], "style_event_sub_0004")],
        },
        {
            "composition_id": "visual_composition_sub_061__sub_062",
            "window": [493, 514],
            "relation": {"mode": "simultaneous", "predecessor_token_ids": []},
            "authority": {"kind": "visual_primary", "evidence_ids": ["style_event_sub_0061", "style_event_sub_0062"]},
            "tokens": [
                _token("visual_token_sub_061", "calling", ["sub_061"], [493, 514], "style_event_sub_0061"),
                _token("visual_token_sub_062", "and", ["sub_062"], [493, 514], "style_event_sub_0062"),
            ],
        },
        {
            "composition_id": "visual_composition_sub_065",
            "window": [542, 554],
            "authority": {"kind": "visual_primary", "evidence_ids": ["style_event_sub_0066"]},
            "tokens": [_token("visual_token_sub_065", "6000", ["sub_065", "sub_066"], [542, 554], "style_event_sub_0066")],
        },
    ]
    cues, info = render_visual_compositions(
        compositions, ["sub_004", "sub_061", "sub_062", "sub_065", "sub_066"], 24.0
    )
    monkeypatch.setattr(canonical, "score_style_event_for_cue", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("heuristic rematch")))
    cue_styles, count = resolve_visual_style_authority(cues, style_data, 24.0)
    xml = canonical.build_caption_only_fcpxml(
        cues, canonical.extract_style_contract(style_data), cue_styles, 24.0, 1080, 1920,
        "STEP3", "VC Caption", "1.10", canonical.DEFAULT_BASIC_TITLE_UID, 1, "reset", 0.0, 0.0,
    )
    titles = ET.fromstring(xml).findall(".//title")
    compiled = {
        title.find("text/text-style").text: (
            title.find("adjust-transform").attrib["position"],
            title.find("text-style-def/text-style").attrib,
        )
        for title in titles
    }

    assert info["semantic_coverage_exact"] is True
    assert count == 4
    assert [(cue["text"], cue["start_frame"], cue["end_frame"]) for cue in cues[1:3]] == [
        ("calling", 493, 514), ("and", 493, 514)
    ]
    assert compiled["list"][0] == "28.512 183.936"
    assert compiled["6000"][0] == "-12.960 459.840"
    assert compiled["calling"][0] == "-201.960 -23.232"
    assert compiled["and"][0] == "-213.516 -30.336"
    assert compiled["calling"][1]["alignment"] == compiled["and"][1]["alignment"] == "left"
    assert compiled["list"][1]["alignment"] == compiled["6000"][1]["alignment"] == "center"

    expected = {
        "list": (68, "#f8f4f2", "#3d2924", 4.0, "#3d2924", 0.85, 2.0),
        "6000": (295, "#f6d19e", "#061312", 22.0, "#061312", 0.85, 2.0),
        "calling": (124, "#f5f3f1", "#291914", 7.0, "#291914", 0.85, 2.0),
        "and": (103, "#f6f5f5", "#291711", 6.0, "#291711", 0.85, 2.0),
    }
    for cue in cues:
        contract = cue_styles[cue["index"]]
        assert contract["matched_style_event_id"] == cue["style_evidence_id"]
        assert (
            contract["font_size_px"], contract["fill"], contract["outline"], contract["outline_px"],
            contract["shadow"], contract["shadow_opacity"], contract["shadow_px"],
        ) == expected[cue["text"]]
        assert contract["bold"] is True
        assert contract["font_name"] == contract["renderer_font_fallback"] == "Arial"
        assert contract["font_family_authority"] == "unresolved"
        assert contract["unresolved_style_properties"] == [
            "font_family", "static_scale", "glow", "semantic_emphasis"
        ]


def test_alignment_defaults_to_center_when_authority_is_absent_or_invalid():
    base = {
        "font_name": "Arial", "font_size_px": 60, "fill_fcpxml": "1 1 1 1", "bold": False,
        "italic": False, "outline_fcpxml": "0 0 0 1", "outline_px": 2,
        "shadow_fcpxml": "0 0 0 0.85", "shadow_px": 2,
    }
    assert 'alignment=\"center\"' in canonical.fcpxml_text_style_attrs(base)
    assert 'alignment=\"center\"' in canonical.fcpxml_text_style_attrs({**base, "alignment": "diagonal"})


def test_missing_direct_style_evidence_fails_closed():
    cue = {
        "id": "visual_token_sub_004", "index": 1, "text": "list",
        "source_cue_ids": ["sub_004"], "style_evidence_id": "missing_event",
    }
    with pytest.raises(StandaloneTextplusError, match="missing or unaccepted"):
        resolve_visual_style_authority([cue], {"caption_style_events": []}, 24.0)
