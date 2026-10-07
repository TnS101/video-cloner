from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/calibrate_step2f_font_authority.py"
SPEC = importlib.util.spec_from_file_location("calibration", SCRIPT)
calibration = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(calibration)


def test_existing_source_style_thresholds_downgrade_ranking_only_certainty():
    from scripts.standalone.video_cloner_font_inference import authority_classification

    assert authority_classification([{"score": .746}, {"score": .723}], .455) == ("BEST_AVAILABLE_FONT_MATCH_MEDIUM", "MEDIUM")
    assert authority_classification([{"score": .80}, {"score": .70}], .70) == ("BEST_AVAILABLE_FONT_MATCH_HIGH", "HIGH")


def test_authoritative_cross_property_disagreement_is_detected():
    record = {
        "typography": {
            "intrinsic_weight": {"category": "REGULAR", "authority": {"status": "AUTHORITATIVE"}},
            "observed_thickness": {"observed_visual_weight_category": "LIGHT", "authority": {"status": "PROVISIONAL"}},
        }
    }
    assert calibration.cross_property_conflicts(record, "BLACK") == ["selected_BLACK_vs_authoritative_intrinsic_weight_REGULAR"]


def test_provisional_cross_property_signal_does_not_create_false_conflict():
    record = {
        "typography": {
            "intrinsic_weight": {"category": "REGULAR", "authority": {"status": "PROVISIONAL"}},
            "observed_thickness": {"observed_visual_weight_category": "LIGHT", "authority": {"status": "PROVISIONAL"}},
        }
    }
    assert calibration.cross_property_conflicts(record, "BLACK") == []


def test_production_calibrator_contains_no_control_specific_rules():
    source = SCRIPT.read_text(encoding="utf-8")
    for value in ("caption_tracklet_0091", "caption_tracklet_0061", '"buy"', '"reels"'):
        assert value not in source
