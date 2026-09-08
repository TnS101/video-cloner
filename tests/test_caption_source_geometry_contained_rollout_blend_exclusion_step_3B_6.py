from __future__ import annotations

import copy
import inspect
import os
import unittest

os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = "1"

from resolve_workspace import resolve_apply_caption_source_geometry_contained_rollout_step_3B_6 as runtime
from scripts.davinci import prepare_caption_source_geometry_contained_rollout_step_3B_6 as preparer
from scripts.davinci import validate_caption_source_geometry_contained_rollout_plan_step_3B_6 as plan_validator
from scripts.davinci import validate_resolve_caption_source_geometry_contained_rollout_step_3B_6 as runtime_validator


class BlendExclusionTests(unittest.TestCase):
    FRAME_MAP = {
        "sub_007": [1, 2],
        "sub_013": [1, 2, 3, 4, 5],
        "sub_110": [0, 1, 2, 3, 4],
        "sub_114": [0, 1, 2, 3, 4, 5],
    }

    def valid_plan(self) -> dict:
        items = []
        for cue_id, (text, start, end) in plan_validator.EXPECTED_CUES.items():
            center = [
                {"input": "Center", "local_frame": frame, "timeline_frame": start + frame, "expected": [0.5, 0.5]}
                for frame in self.FRAME_MAP[cue_id]
            ]
            size = [
                {"input": "Size", "local_frame": frame, "timeline_frame": start + frame, "expected": 0.05}
                for frame in self.FRAME_MAP[cue_id]
            ]
            excluded = [
                {
                    "input": "Blend", "local_frame": index, "timeline_frame": start + index,
                    "source_expected": float(index), "reason": "source_visibility_boundary",
                    "provenance": "source_visibility_boundary",
                    "exclusion_reason": "Blend is outside the Step 3B.6D source-geometry property allowlist",
                    "executable": False,
                }
                for index in range(plan_validator.EXPECTED_EXCLUDED_BLEND_BY_CUE[cue_id])
            ]
            items.append(
                {
                    "cue_id": cue_id, "text": text, "name": f"VC_TEXTPLUS_{int(cue_id[-3:]):04d}_{cue_id}",
                    "start_frame": start, "end_frame": end,
                    "accepted_source_instance": True,
                    "source_exactness": "source_redetected_dense_word_instance", "fallback_reasons": [],
                    "visibility": {"fully_contained_in_existing_item": True},
                    "targets": center + size, "center_targets": center, "size_targets": size,
                    "blend_targets": [], "excluded_targets": excluded,
                    "write_inputs": ["Center", "Size"],
                }
            )
        plan = {
            "ok": True, "schema": plan_validator.SCHEMA, "created_at_unix": 1.0,
            "rollout_items": items,
            "property_contract": {
                "allowed_operation_properties": ["Center", "Size"],
                "known_excluded_source_properties": ["Blend"],
                "unknown_properties_fail_closed": True,
            },
            "safety_contract": {
                "only_contained_accepted_cues_writable": True,
                "timeline_item_boundaries_read_only": True,
                "other_v3_captions_read_only": True,
                "opacity_proxy_diagnostic_only": True,
                "binary_visibility_gate_allowed": False,
                "center_size_property_allowlist_enforced": True,
                "unknown_properties_fail_closed": True,
                "z_order_read_only": True,
                "hard_outline_default_forbidden": True,
                "solid_outline_100pct_no_blur_forbidden": True,
            },
            "summary": {
                "v3_item_count": 116, "accepted_source_instance_count": 45,
                "unresolved_source_instance_count": 30, "timing_mismatch_excluded_count": 41,
                "rollout_item_count": 4, "center_target_count": 18, "size_target_count": 18,
                "blend_target_count": 0, "other_property_target_count": 0,
                "excluded_blend_target_count": 6, "total_target_count": 36,
                "visibility_gated_caption_count": 0,
                "expected_first_modified_count": 3, "expected_first_already_correct_count": 1,
                "protected_animation_caption_count": 8, "protected_animation_target_count": 16,
            },
            "failures": [], "warnings": [],
        }
        self.refresh_hash(plan)
        return plan

    @staticmethod
    def refresh_hash(plan: dict) -> None:
        plan["plan_hash"] = plan_validator.canonical_hash(plan, ignored=("created_at_unix",))

    def valid_report(self, plan: dict) -> dict:
        items_after = [
            {
                "cue_id": item["cue_id"], "name": item["name"], "all_present": True,
                "targets": [{**target, "present": True, "matched": True} for target in item["targets"]],
            }
            for item in plan["rollout_items"]
        ]
        return {
            "ok": True, "workspace_version": runtime_validator.WORKSPACE_VERSION,
            "run_mode": "first_application", "plan_hash": plan["plan_hash"], "failures": [],
            "summary": {
                "v3_candidate_count": 116, "accepted_source_instance_count": 45,
                "unresolved_source_instance_count": 30, "timing_mismatch_excluded_count": 41,
                "rollout_item_count": 4, "mapped_count": 4, "modified_count": 3, "already_correct_count": 1,
                "target_key_count": 36, "target_key_verified_count": 36,
                "center_key_count": 18, "center_key_verified_count": 18,
                "size_key_count": 18, "size_key_verified_count": 18,
                "blend_key_count": 0, "blend_key_verified_count": 0, "other_property_key_count": 0,
                "excluded_blend_target_count": 6,
                "non_rollout_caption_count": 112, "non_rollout_caption_verified_count": 112,
                "protected_animation_caption_count": 8, "protected_animation_verified_count": 8,
                "protected_animation_target_count": 16, "protected_animation_target_verified_count": 16,
                "opacity_proxy_applied_count": 0, "binary_visibility_target_count": 0,
                "z_order_write_count": 0, "timeline_boundary_write_count": 0,
                "timeline_integrity_failure_count": 0, "protected_integrity_failure_count": 0,
                "rollback_performed_count": 0, "failed_count": 0,
            },
            "items_after": items_after,
            "writes": [{"target": target} for item in plan["rollout_items"] for target in item["targets"]],
            "track_integrity": {"ok": True}, "v3_track_integrity": {"ok": True},
        }

    def test_property_selection_preserves_center_and_size_exactly(self) -> None:
        plan = self.valid_plan()
        center = [row for item in plan["rollout_items"] for row in item["center_targets"]]
        size = [row for item in plan["rollout_items"] for row in item["size_targets"]]
        blend = [row for item in plan["rollout_items"] for row in item["excluded_targets"]]
        executable, excluded, unknown = preparer.select_contained_rollout_operations(center + size + blend)
        self.assertEqual(executable, center + size)
        self.assertEqual(excluded, blend)
        self.assertEqual(unknown, [])

    def test_property_selection_reports_unknown_property(self) -> None:
        executable, excluded, unknown = preparer.select_contained_rollout_operations(
            [{"input": "Center"}, {"input": "TrackingAngle"}]
        )
        self.assertEqual(executable, [{"input": "Center"}])
        self.assertEqual(excluded, [])
        self.assertEqual(unknown, ["TrackingAngle"])

    def test_valid_plan_has_exact_operation_and_exclusion_inventory(self) -> None:
        result = plan_validator.validate(self.valid_plan())
        self.assertTrue(result["ok"], result["failures"])
        self.assertTrue(result["checks"]["target_counts"])
        self.assertTrue(result["checks"]["excluded_blend_audit"])

    def test_validator_rejects_injected_blend_plan_operation(self) -> None:
        plan = self.valid_plan()
        plan["rollout_items"][0]["targets"].append({"input": "Blend", "local_frame": 0, "expected": 1.0})
        plan["summary"].update({"blend_target_count": 1, "total_target_count": 37})
        self.refresh_hash(plan)
        result = plan_validator.validate(plan)
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["target_input_contract"])

    def test_validator_rejects_unknown_plan_operation(self) -> None:
        plan = self.valid_plan()
        plan["rollout_items"][0]["targets"].append({"input": "TrackingAngle", "local_frame": 0, "expected": 1.0})
        plan["summary"].update({"other_property_target_count": 1, "total_target_count": 37})
        self.refresh_hash(plan)
        result = plan_validator.validate(plan)
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["target_input_contract"])

    def test_validator_rejects_blend_mutation_manifest(self) -> None:
        plan = self.valid_plan()
        plan["mutation_manifest"] = {"operations": [{"input": "Blend"}]}
        self.refresh_hash(plan)
        result = plan_validator.validate(plan)
        self.assertFalse(result["checks"]["mutation_manifest_contract"])

    def test_missing_extra_and_duplicate_cues_fail(self) -> None:
        for mutation in ("missing", "extra", "duplicate"):
            with self.subTest(mutation=mutation):
                plan = self.valid_plan()
                if mutation == "missing":
                    plan["rollout_items"].pop()
                elif mutation == "extra":
                    plan["rollout_items"].append({"cue_id": "sub_999"})
                else:
                    plan["rollout_items"][-1] = copy.deepcopy(plan["rollout_items"][0])
                self.refresh_hash(plan)
                self.assertFalse(plan_validator.validate(plan)["ok"])

    def test_contaminated_or_group_inferred_source_fails(self) -> None:
        plan = self.valid_plan()
        plan["rollout_items"][0]["source_exactness"] = "group_inferred_not_source_exact"
        self.refresh_hash(plan)
        result = plan_validator.validate(plan)
        self.assertFalse(result["checks"]["all_accepted"])

    def test_runtime_guard_accepts_only_center_and_size_plan(self) -> None:
        self.assertEqual(runtime.executable_plan_failures(self.valid_plan()), [])

    def test_runtime_guard_rejects_blend_and_unknown_properties(self) -> None:
        for input_name in ("Blend", "TrackingAngle"):
            with self.subTest(input_name=input_name):
                plan = self.valid_plan()
                plan["mutation_manifest"] = {"operations": [{"input": input_name}]}
                failures = runtime.executable_plan_failures(plan)
                self.assertIn("rollout_property_contract_failed", failures)
                self.assertIn("mutation_manifest_property_contract_failed", failures)

    def test_runtime_validator_accepts_zero_blend_evidence(self) -> None:
        plan = self.valid_plan()
        result = runtime_validator.validate(plan, self.valid_report(plan), "first_application_pass")
        self.assertTrue(result["ok"], result["failures"])

    def test_runtime_validator_rejects_blend_or_unknown_mutation_evidence(self) -> None:
        for input_name in ("Blend", "TrackingAngle"):
            with self.subTest(input_name=input_name):
                plan = self.valid_plan()
                report = self.valid_report(plan)
                report["mutation_manifest"] = {"operations": [{"input": input_name}]}
                result = runtime_validator.validate(plan, report, "first_application_pass")
                self.assertFalse(result["checks"]["runtime_property_contract"])

    def test_plan_hash_is_stable_across_unchanged_preparations(self) -> None:
        first = self.valid_plan()
        second = copy.deepcopy(first)
        second["created_at_unix"] = 2.0
        self.refresh_hash(second)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        first.pop("created_at_unix")
        second.pop("created_at_unix")
        self.assertEqual(first, second)

    def test_preparer_has_no_resolve_queue_or_run_id_path(self) -> None:
        source = inspect.getsource(preparer)
        self.assertNotIn(".agent/commands", source)
        self.assertNotIn('"run_id":', source)
        self.assertNotIn("uuid", source)
        self.assertNotIn("GetResolve", source)


if __name__ == "__main__":
    unittest.main()
