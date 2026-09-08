from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preparer = load_module("final_occlusion_preparer", "scripts/davinci/prepare_final_occlusion_composition_v1.py")


def test_foreground_contract_is_exact_approved_five_frame_span():
    contract = json.loads((ROOT / preparer.FOREGROUND_CONTRACT).read_text(encoding="utf-8-sig"))
    validation = json.loads((ROOT / preparer.FOREGROUND_VALIDATION).read_text(encoding="utf-8-sig"))
    result = preparer.validate_foreground_contract(contract, validation)
    assert result == {
        "span_id": "matte_span_0001",
        "timeline_range": [429, 434],
        "cue_id": "sub_0052",
        "ok": True,
    }


def test_prior_accepted_metrics_report_is_exact_114_textplus_source():
    report = json.loads((ROOT / preparer.PRIOR_REPORT).read_text(encoding="utf-8-sig"))
    persistent = json.loads((ROOT / preparer.PRIOR_PERSISTENT).read_text(encoding="utf-8-sig"))
    preparer.validate_prior(report, persistent)
    assert report["target_timeline_name"] == preparer.SOURCE_TIMELINE_NAME
    assert report["final_textplus_count"] == 114
    assert report["position_updates"] == 0
    assert report["opacity_updates"] == 0


def test_asset_set_is_exact_manifest_plus_five_rgba_frames():
    assert len(preparer.ASSET_FILES) == 6
    assert preparer.ASSET_FILES[0].endswith("manifest.json")
    assert [Path(path).name for path in preparer.ASSET_FILES[1:]] == [
        "rgba_000429.png",
        "rgba_000430.png",
        "rgba_000431.png",
        "rgba_000432.png",
        "rgba_000433.png",
    ]
    for relative in preparer.ASSET_FILES:
        path = ROOT / relative
        assert path.is_file()
        assert path.stat().st_size > 0


def test_publisher_contract_forbids_caption_and_non_occlusion_mutation(tmp_path):
    # Pure contract check: the published payload must encode the strict scope.
    assert preparer.EXPECTED_TEXTPLUS_COUNT == 114
    assert preparer.MATTE_RANGE == [429, 434]
    assert preparer.MATTE_NAME == "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
    assert preparer.TARGET_TIMELINE_NAME.endswith("_occlusion_complete_v1")


def test_validator_requires_every_runtime_boundary():
    validator = load_module("final_occlusion_validator", "scripts/davinci/validate_final_occlusion_composition_v1.py")
    assert validator.EXPECTED_TEXTPLUS_COUNT == 114
    assert validator.MATTE_RANGE == [429, 434]
    assert validator.SOURCE_TIMELINE_NAME == preparer.SOURCE_TIMELINE_NAME
    assert validator.TARGET_TIMELINE_NAME == preparer.TARGET_TIMELINE_NAME


def test_foreground_contract_rejects_wrong_span():
    contract = json.loads((ROOT / preparer.FOREGROUND_CONTRACT).read_text(encoding="utf-8-sig"))
    validation = json.loads((ROOT / preparer.FOREGROUND_VALIDATION).read_text(encoding="utf-8-sig"))
    contract = json.loads(json.dumps(contract))
    contract["asset_spans"][0]["timeline_frame_end_exclusive"] = 435
    with pytest.raises(ValueError, match="foreground_span_geometry"):
        preparer.validate_foreground_contract(contract, validation)


def test_prior_contract_rejects_any_caption_position_or_opacity_mutation():
    report = json.loads((ROOT / preparer.PRIOR_REPORT).read_text(encoding="utf-8-sig"))
    persistent = json.loads((ROOT / preparer.PRIOR_PERSISTENT).read_text(encoding="utf-8-sig"))
    for key in ("position_updates", "opacity_updates"):
        candidate = json.loads(json.dumps(report))
        candidate[key] = 1
        with pytest.raises(ValueError, match="prior_report"):
            preparer.validate_prior(candidate, persistent)
