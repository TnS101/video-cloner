from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_track_state_preserves_raw_false_without_filtering_inventory() -> None:
    module = _load("resolve_workspace/modules/video_cloner_step5_f8a_completion_diagnostic.py", "f8a_completion")

    class Timeline:
        def GetIsTrackEnabled(self, _kind, _index):
            return False

    assert module._track_state(Timeline(), "video", 1) == {
        "method_present": True,
        "raw_type": "bool",
        "raw_repr": "False",
        "reported_enabled": False,
        "exception": None,
    }


def test_active_scale_defaults_to_one_and_interpolates() -> None:
    module = _load("scripts/analysis/complete_step5_f8a_evidence.py", "f8a_local")
    assert module._active_scale({"keyframes": {"scale": []}}, 5) == 1.0
    row = {"keyframes": {"scale": [{"timeline_frame": 0, "value": 1.0}, {"timeline_frame": 10, "value": 2.0}]}}
    assert module._active_scale(row, 5) == 1.5
