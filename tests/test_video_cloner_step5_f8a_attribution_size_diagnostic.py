from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "resolve_workspace/modules/video_cloner_step5_f8a_attribution_size_diagnostic.py"


def _load():
    spec = importlib.util.spec_from_file_location("f8a", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_case_scope_and_timecode() -> None:
    module = _load()
    assert len(module.CASES) == 15
    assert len(module.SOURCE_BBOXES) == 16
    assert {identity for case in module.CASES for identity in case[3]} >= {
        "continuous_visual_identity_0014", "caption_tracklet_0067", "caption_tracklet_0089",
        "caption_tracklet_0094", "caption_tracklet_0096", "caption_tracklet_0045",
        "caption_tracklet_0061", "recovered_display_object_listing_0003",
    }
    assert module._timecode("01:00:00:00", 55) == "01:00:02:07"


def test_rect_normalization() -> None:
    module = _load()
    assert module._rect([10, 20, 110, 70]) == [10, 20, 110, 70]
    assert module._rect({1: 10, 2: 20, 3: 110, 4: 70}) == [10, 20, 110, 70]
    assert module._rect({"Left": 10, "Bottom": 20, "Right": 110, "Top": 70}) == [10, 20, 110, 70]
    assert module._rect({}) is None


def test_cleanup_requires_no_save_and_complete_rollback() -> None:
    module = _load()
    source = RUNTIME.read_text(encoding="utf-8")
    assert 'cleanup["project_saved"] is False' in source
    assert 'cleanup["target_unchanged"]' in source
    assert 'cleanup["probe_absent"]' in source
    assert "SaveProject" not in source


def test_source_provenance_accepts_only_original_or_its_canonical_proxy(tmp_path: Path) -> None:
    module = _load()
    root = tmp_path / "project"
    source = root / "input" / "Sample_Clip.mp4"
    proxy = root / "media" / "Sample_Clip_proxy.mp4"
    source.parent.mkdir(parents=True)
    proxy.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    proxy.write_bytes(b"proxy")

    original = module._source_provenance(source, {str(source)}, root)
    assert original["provenance_relation"] == "ORIGINAL_SOURCE"
    assert original["carrier_match"] is True
    assert original["original_source_path"] == str(source.resolve())

    derived = module._source_provenance(source, {str(proxy)}, root)
    assert derived["canonical_proxy_path"] == str(proxy.resolve())
    assert derived["provenance_relation"] == "CANONICAL_MEDIA_PREP_PROXY"
    assert derived["identity_match"] is derived["carrier_match"] is True

    other = root / "media" / "Other_proxy.mp4"
    other.write_bytes(b"other")
    assert module._source_provenance(source, {str(other)}, root)["carrier_match"] is False

    outside = tmp_path / "outside" / proxy.name
    outside.parent.mkdir()
    outside.write_bytes(b"same name, wrong provenance")
    outside_result = module._source_provenance(source, {str(outside)}, root)
    assert outside_result["identity_match"] is True
    assert outside_result["carrier_match"] is False

    missing = root / "media" / "missing.mp4"
    missing_result = module._source_provenance(source, {str(missing)}, root)
    assert missing_result["provenance_relation"] == "OFFLINE_V1_CARRIER"
    assert missing_result["carrier_match"] is False
    assert module._source_provenance(source, {str(source), str(proxy)}, root)["carrier_match"] is False
