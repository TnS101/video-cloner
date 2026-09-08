from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "resolve_workspace/modules/step_3E_visual_fidelity_v2_isolated_resolve_rollout_v1.py"
PREPARER_PATH = ROOT / "scripts/davinci/prepare_step_3E_visual_fidelity_v2_isolated_resolve_rollout_v1.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("vf2_rollout_point_compat_v6", RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runtime = load_runtime()


def load_preparer():
    spec = importlib.util.spec_from_file_location("vf2_rollout_preparer_retry_v6", PREPARER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(PREPARER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


preparer = load_preparer()


class FakeBase:
    def normalize_point(self, value):
        if isinstance(value, Mapping):
            if "x" in value and "y" in value:
                return [float(value["x"]), float(value["y"])]
            if 0 in value and 1 in value:
                return [float(value[0]), float(value[1])]
            if "0" in value and "1" in value:
                return [float(value["0"]), float(value["1"])]
            return None
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
            return [float(value[0]), float(value[1])]
        return None

    def find_named_item(self, timeline, name):
        return 3, object()

    def item_summary(self, track, item):
        return {
            "track_index": 3,
            "start": 10,
            "end": 11,
            "duration": 1,
            "fusion_comp_count": 1,
            "media_pool_item_name": "protected",
        }

    def get_comp(self, item):
        return object()

    def get_text_tool(self, comp):
        return object()

    def read_input(self, tool, name, frame):
        if name == "Center":
            return [0.5, 0.4]
        if name == "Size":
            return 0.08
        if name == "Opacity1":
            return 1.0
        raise AssertionError(name)


class FakeOld:
    @staticmethod
    def scalar_match(actual, expected, tolerance):
        return abs(float(actual) - float(expected)) <= float(tolerance)

    @staticmethod
    def style_matches(base, item, expected):
        return expected == {"Font": "Impact"}


class ProtectedPointCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.base = FakeBase()

    def test_list_points_compare_exactly(self):
        self.assertTrue(runtime.point_matches(self.base, [0.5, 0.4], [0.5, 0.4], 1e-4))
        self.assertFalse(runtime.point_matches(self.base, [0.5, 0.4], [0.51, 0.4], 1e-4))

    def test_keyed_expected_point_is_normalized_before_comparison(self):
        self.assertTrue(runtime.point_matches(self.base, [0.5, 0.4], {"x": 0.5, "y": 0.4}, 1e-4))
        self.assertTrue(runtime.point_matches(self.base, {"0": 0.5, "1": 0.4}, {"x": 0.5, "y": 0.4}, 1e-4))

    def test_malformed_points_return_false_without_exception(self):
        for value in (None, {}, {"x": 0.5}, [0.5], "0.5,0.4"):
            with self.subTest(value=value):
                self.assertFalse(runtime.point_matches(self.base, [0.5, 0.4], value, 1e-4))
                self.assertFalse(runtime.point_matches(self.base, value, [0.5, 0.4], 1e-4))

    def test_protected_snapshot_accepts_keyed_center_without_mutating_snapshot(self):
        snapshot = {
            "target_name": "protected",
            "summary": self.base.item_summary(3, object()),
            "static_style": {"Font": "Impact"},
            "center": [{"x": 0.5, "y": 0.4}],
            "size": [0.08],
            "opacity1": [1.0],
        }
        before = copy.deepcopy(snapshot)
        result = runtime.verify_protected_snapshot(self.base, FakeOld(), object(), snapshot)
        self.assertTrue(result["ok"])
        self.assertTrue(result["checks"]["center"])
        self.assertEqual(snapshot, before)

    def test_protected_snapshot_center_mismatch_is_false_not_exception(self):
        snapshot = {
            "target_name": "protected",
            "summary": self.base.item_summary(3, object()),
            "static_style": {"Font": "Impact"},
            "center": [{"x": 0.52, "y": 0.4}],
            "size": [0.08],
            "opacity1": [1.0],
        }
        result = runtime.verify_protected_snapshot(self.base, FakeOld(), object(), snapshot)
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["center"])


class RepairRetryPublicationTests(unittest.TestCase):
    @staticmethod
    def _write_json(path: Path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_single_failed_run_with_clean_cleanup_allows_exactly_one_repair_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_id = "failed_run"
            artifacts = Path(".agent/reports") / preparer.TASK_ID / run_id
            command = {"task_id": preparer.TASK_ID, "run_id": run_id, "artifacts_dir": str(artifacts)}
            self._write_json(root / ".agent/commands/failed" / f"{preparer.TASK_ID}_{run_id}.json", command)
            self._write_json(root / artifacts / "failure_cleanup.json", {"ok": True, "accepted_state_unchanged": True, "errors": []})
            state = preparer.validate_retry_state(root)
            self.assertEqual(state, {"repair_retry": True, "prior_failed_run_id": run_id})

    def test_retry_gate_rejects_bad_cleanup_and_second_failed_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_id = "failed_run"
            artifacts = Path(".agent/reports") / preparer.TASK_ID / run_id
            command = {"task_id": preparer.TASK_ID, "run_id": run_id, "artifacts_dir": str(artifacts)}
            first = root / ".agent/commands/failed" / f"{preparer.TASK_ID}_{run_id}.json"
            self._write_json(first, command)
            self._write_json(root / artifacts / "failure_cleanup.json", {"ok": False, "accepted_state_unchanged": True, "errors": ["cleanup"]})
            with self.assertRaisesRegex(ValueError, "prior_failure_cleanup"):
                preparer.validate_retry_state(root)
            second_id = "failed_run_2"
            second_artifacts = Path(".agent/reports") / preparer.TASK_ID / second_id
            self._write_json(root / ".agent/commands/failed" / f"{preparer.TASK_ID}_{second_id}.json", {"task_id": preparer.TASK_ID, "run_id": second_id, "artifacts_dir": str(second_artifacts)})
            with self.assertRaisesRegex(ValueError, "repair_retry_limit:2"):
                preparer.validate_retry_state(root)


if __name__ == "__main__":
    unittest.main()
