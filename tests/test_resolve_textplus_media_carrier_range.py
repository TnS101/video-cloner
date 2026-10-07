import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "davinci" / "resolve_apply_video_cloner_metadata.py"


def load_module():
    spec = importlib.util.spec_from_file_location("resolve_textplus_carrier_range", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("source_start", "duration", "expected_api_end"), [(0, 12, 12), (20, 7, 27)])
def test_textplus_carrier_uses_exclusive_resolve_api_end(monkeypatch, source_start, duration, expected_api_end):
    module = load_module()
    captured = {}
    monkeypatch.setattr(module, "_find_textplus_carrier_source", lambda _items, _duration: {
        "ok": True,
        "source_item": object(),
        "media_pool_item": object(),
        "source_start": source_start,
        "source_end_inclusive": expected_api_end - 1,
        "attempts": [],
    })

    def capture(_project, _timeline, rows, _track):
        captured.update(rows[0])
        return {"ok": False, "returned_items": [], "detected_items": [], "errors": ["stop_after_payload"]}

    monkeypatch.setattr(module, "_append_media_clip_infos", capture)
    module.provision_textplus_media_carrier(
        project=object(), timeline=object(), video_items=[], start_frame=100,
        end_frame=100 + duration, target_track=3, generated_name="proof",
    )

    assert captured["source_start"] == source_start
    assert captured["source_end_inclusive"] == expected_api_end - 1
    assert captured["source_end_frame_api"] == expected_api_end
    assert captured["api_end_semantics"] == "exclusive"
