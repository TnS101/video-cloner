from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/repair_transition_observation_ownership.py"
SPEC = importlib.util.spec_from_file_location("transition_repair", SCRIPT)
repair = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(repair)


def test_rle_round_trip():
    mask = np.array([[0, 1, 1], [0, 0, 1]], dtype=bool)
    assert np.array_equal(mask, repair.decode([2, 3], repair.encode(mask)))


def test_rebuild_with_no_owned_observations_is_explicitly_unresolved():
    row = {"observations": [{"source_frame": 1, "accepted": False, "reason": "transition"}]}
    repair.rebuild_mask(row)
    assert row["accepted_frame_count"] == 0
    assert row["final_mask_rle"] == []
    assert row["unknown_rle"] == [[0, 1]]
    assert row["unresolved_reason"]
