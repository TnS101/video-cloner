import hashlib
import json
from pathlib import Path


import video_cloner.caption_grammar as MODULE

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "video_cloner" / "caption_grammar.py"


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_normalizes_hints_without_inventing_boundaries(tmp_path):
    source = {
        "success": True,
        "video_info": {"width": 1080, "height": 1920},
        "summary": {"position": "middle_center", "text_color_median": "#ffffff"},
        "caption_style_resolved": {
            "confidence": {"score": 0.8, "frame_coverage_ratio": 0.75},
            "typography": {"density": {"label": "word_by_word"}},
        },
        "caption_style_profiles": [{
            "style_id": "style_01",
            "sample_count": 3,
            "typography": {"font_family": "unknown", "font_weight": "bold", "font_height_px": 60},
            "placement": {"position": "middle_center"},
            "colors": {"fill": "#ffffff", "stroke": "#000000"},
            "stroke": {"enabled": True, "width_px_estimate": 4},
        }],
        "caption_style_events": [
            {"event_id": "one", "style_profile_id": "style_01", "start": 0.0, "end": 0.5, "duration": 0.5, "typography": {"font_family": "unknown"}, "animation": {"type": "slide", "confidence": 0.7, "samples": 5}},
            {"event_id": "two", "style_profile_id": "style_01", "start": 0.5, "end": 1.0, "duration": 0.5, "typography": {"font_family": "unknown"}, "animation": {"type": "scale_pop", "confidence": 0.8, "samples": 5}},
            {"event_id": "three", "style_profile_id": "style_01", "start": 1.0, "end": 1.1, "duration": 0.1, "typography": {"font_family": "unknown"}, "animation": {"type": "unknown_or_static_insufficient_samples", "samples": 1}},
        ],
    }
    path = tmp_path / "caption_style.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    grammar = MODULE.build_grammar(path, "fresh_reel")

    assert {row["family"]: row["boundary_count"] for row in grammar["animation_families"]} == {
        "combination": 1,
        "slide": 1,
        "unresolved": 1,
    }
    assert grammar["font_rules"]["font_family_status"] == "UNKNOWN"
    assert grammar["color_opacity_rules"]["fill_opacity"]["evidence_status"] == "UNKNOWN"
    assert grammar["enter_exit_combos"] == [{
        "combo": "unresolved->continuous_hold->unresolved",
        "caption_count": 3,
        "relationship_counts": {"UNKNOWN": 3},
        "evidence_status": "UNKNOWN",
        "reason": "generic event samples do not distinguish enter from exit",
    }]
    assert all(row["animation"]["enter"]["direction"] == "unknown" for row in grammar["per_caption_or_cluster_evidence"])
    assert all(row["animation"]["exit"]["easing_category"] == "unknown" for row in grammar["per_caption_or_cluster_evidence"])


def test_fresh_artifact_is_deterministic_and_does_not_touch_accepted_reel2():
    source = ROOT / "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_style.json"
    accepted = ROOT / "data/DcJRJtUKScu/analysis/DcJRJtUKScu_caption_style_grammar.json"
    accepted_hash = _hash(accepted)

    first = MODULE.build_grammar(source, "DZatr0EJt4B")
    second = MODULE.build_grammar(source, "DZatr0EJt4B")

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert json.loads(json.dumps(first)) == first
    assert first["schema"] == "video_cloner_caption_style_grammar"
    assert first["persistence_rules"]["caption_count"] == 162
    assert len(first["caption_style_families"]) == 5
    assert len(first["per_caption_or_cluster_evidence"]) == 162
    assert first["font_rules"]["font_family_status"] == "UNKNOWN"
    assert first["unresolved"]["opacity_count"] == 162
    assert first["unresolved"]["entry_animation_count"] == 162
    assert _hash(accepted) == accepted_hash
    source_text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "dcjrjtukscu" not in source_text
    assert "gold" not in source_text
    assert "drt" not in source_text
