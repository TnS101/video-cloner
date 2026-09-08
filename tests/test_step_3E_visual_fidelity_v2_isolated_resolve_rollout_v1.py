from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts/analysis/build_step_3E_visual_fidelity_v2_resolve_rollout_authority_v1.py"
RUNTIME_PATH = ROOT / "resolve_workspace/modules/step_3E_visual_fidelity_v2_isolated_resolve_rollout_v1.py"
PREPARER_PATH = ROOT / "scripts/davinci/prepare_step_3E_visual_fidelity_v2_isolated_resolve_rollout_v1.py"
AUTHORITY_PATH = ROOT / "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1/visual_fidelity_v2_resolve_rollout_authority_v1.json"
RECOVERY_PATH = ROOT / "artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_v1.json"
FINAL_AUDIT_PATH = ROOT / "artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_v1.json"
PROTECTED_PERSISTENT_PATH = ROOT / ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = load_module(BUILDER_PATH, "vf2_rollout_builder_under_test")
runtime = load_module(RUNTIME_PATH, "vf2_rollout_runtime_under_test")
preparer = load_module(PREPARER_PATH, "vf2_rollout_preparer_under_test")


class VisualFidelityV2IsolatedResolveRolloutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not AUTHORITY_PATH.is_file():
            builder.build(ROOT, AUTHORITY_PATH)
        cls.authority = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8-sig"))
        cls.part = runtime.authority_partition(cls.authority)
        cls.audit = json.loads(FINAL_AUDIT_PATH.read_text(encoding="utf-8-sig"))
        cls.recovery = json.loads(RECOVERY_PATH.read_text(encoding="utf-8-sig"))

    def test_exact_final_partition(self):
        summary = self.authority["summary"]
        self.assertEqual(summary["recreate_total"], 87)
        self.assertEqual(summary["v2_repair_recreate"], 73)
        self.assertEqual(summary["semantic_recreate"], 13)
        self.assertEqual(summary["visual_companion_recreate"], 1)
        self.assertEqual(summary["preserved_unresolved"], 9)
        self.assertEqual(summary["quarantined_remove"], 1)
        self.assertEqual(summary["protected_total"], 17)
        self.assertEqual(summary["protected_exit_updates"], 3)
        self.assertEqual(summary["target_physical_textplus"], 113)

    def test_final_audit_is_consumed_without_source_absence(self):
        summary = self.audit["summary"]
        self.assertEqual(summary["evaluated_residual"], 9)
        self.assertEqual(summary["recovered_semantic"], 2)
        self.assertEqual(summary["unresolved_after_full_visual_audit"], 7)
        self.assertEqual(summary["source_absent_claims"], 0)
        self.assertFalse(self.authority["policy"]["residual_unresolved_mutation_authorized"])
        self.assertEqual(self.authority["policy"]["source_absence_claims"], 0)

    def test_sparse_short_anchor_quarantine_is_artifact_driven(self):
        audit_rows = self.audit["repair_authority_quarantine"]
        quarantine = self.authority["quarantine_remove"]
        self.assertEqual(len(audit_rows), 1)
        self.assertEqual(len(quarantine), 1)
        self.assertEqual(quarantine[0]["instance_id"], audit_rows[0]["instance_id"])
        self.assertTrue(quarantine[0]["action"].startswith("remove_or_do_not_materialize"))
        self.assertFalse(self.authority["policy"]["per_cue_hardcoded_overrides"])
        self.assertFalse(self.authority["policy"]["screenshot_specific_overrides"])

    def test_recreate_preserve_quarantine_scopes_are_disjoint(self):
        recreate = {x["target_name"] for x in self.part["recreate"]}
        preserve = {x["target_name"] for x in self.part["preserve"]}
        quarantine = {x["target_name"] for x in self.part["quarantine"]}
        self.assertEqual(len(recreate), 87)
        self.assertEqual(len(preserve), 9)
        self.assertEqual(len(quarantine), 1)
        self.assertFalse(recreate & preserve)
        self.assertFalse(recreate & quarantine)
        self.assertFalse(preserve & quarantine)
        self.assertEqual(len(recreate | preserve | quarantine), 97)

    def test_semantic_recovery_count_is_13(self):
        rows = [x for x in self.part["recreate"] if str(x["kind"]).startswith("semantic_recovered_")]
        self.assertEqual(len(rows), 13)
        for row in rows:
            start, end = row["target_range"]
            self.assertEqual([x["timeline_frame"] for x in row["position_keys"]], list(range(start, end)))
            self.assertEqual(row["size_action"], "preserve_source_static")
            self.assertEqual(row["opacity_action"], "hold_source_layer_opacity_fade_deferred")

    def test_visual_companion_recovery_uses_source_style_and_track(self):
        rows = [x for x in self.part["recreate"] if x["kind"] == "visual_companion_recovered"]
        self.assertEqual(len(rows), 1)
        plan = rows[0]
        source = next(x for x in self.recovery["classifications"] if x.get("classification") == "source_visual_companion_recovered")
        self.assertEqual(plan["instance_id"], source["instance_id"])
        self.assertEqual(plan["display_text"], source["display_text"])
        self.assertEqual(plan["fill_hex"], source["style_lock"]["fill"])
        self.assertEqual(plan["font_override"]["font_family"], source["font"]["font_family"])
        self.assertEqual(plan["target_range"], source["visual_window"])

    def test_companion_static_overrides_are_complete(self):
        plan = next(x for x in self.part["recreate"] if x["kind"] == "visual_companion_recovered")
        values = runtime.static_overrides(plan)
        self.assertEqual(values["StyledText"], plan["display_text"])
        self.assertEqual(values["Font"], plan["font_override"]["font_family"])
        self.assertEqual(values["Style"], plan["font_override"]["font_style"])
        self.assertEqual(values["Enabled2"], 0.0)
        self.assertEqual(values["Enabled3"], 1.0)
        self.assertIn("Red1", values)
        self.assertIn("Red3", values)

    def test_v2_repairs_preserve_static_motion_by_default(self):
        v2 = [x for x in self.part["recreate"] if x["kind"] == "v2_repair"]
        self.assertEqual(len(v2), 73)
        for row in v2:
            start, end = row["target_range"]
            self.assertEqual(len(row["position_keys"]), end - start)
            self.assertEqual(row["opacity_action"], "hold_source_layer_opacity_fade_deferred")
        self.assertGreater(self.authority["summary"]["explicit_position_rows"], 0)

    def test_protected_scope_is_center_only_for_exactly_three_exits(self):
        exits = self.part["exits"]
        self.assertEqual(len(exits), 3)
        for row in exits:
            self.assertEqual(row["action"], "center_only_source_exit_trajectory_within_existing_item_range")
            self.assertTrue(all(0 <= key["local_frame"] < row["target_range"][1] - row["target_range"][0] for key in row["position_keys"]))
            self.assertTrue(row["position_keys"])
        self.assertFalse(self.authority["policy"]["protected_non_exit_motion_mutation_authorized"])

    def test_occlusion_is_required_above_all_textplus(self):
        occ = self.part["occlusion"]
        self.assertEqual(occ["required_layer_order"], "foreground_rgba_above_textplus")
        self.assertEqual(occ["target_track_policy"], "max_physical_textplus_track_plus_one")
        self.assertEqual(occ["duration_frames"], 5)
        self.assertTrue(occ["persistent_readback_required"])

    def test_physical_accounting_is_113_not_forced_to_117(self):
        self.assertEqual(73 + 13 + 1 + 9 + 17, 113)
        self.assertEqual(self.authority["summary"]["target_physical_textplus"], 113)
        self.assertEqual(self.authority["summary"]["structural_total"], 117)
        self.assertEqual(self.authority["summary"]["composite_structural_already_absent"], 3)

    def test_materialization_preserves_or_applies_size_exactly(self):
        source_size = 0.08125
        preserve = next(x for x in self.part["recreate"] if x["size_action"] == "preserve_source_static")
        materialized = runtime.materialize_plan(preserve, source_size)
        self.assertTrue(all(abs(x["value"] - source_size) < 1e-12 for x in materialized["size_keys"]))
        targeted = next(x for x in self.part["recreate"] if x["size_action"] == "source_target")
        materialized = runtime.materialize_plan(targeted, source_size)
        self.assertTrue(all(abs(x["value"] - targeted["target_size"]) < 1e-12 for x in materialized["size_keys"]))

    def test_detector_score_never_controls_opacity(self):
        self.assertFalse(self.authority["policy"]["detector_score_controls_opacity"])
        for row in self.part["recreate"]:
            plan = runtime.materialize_plan(row, float(row.get("target_size") or 0.08))
            self.assertTrue(all(x["factor"] == 1.0 for x in plan["opacity_keys"]))


    def test_final_audit_source_contract_normalizes_line_endings_and_bom(self):
        expected = builder.FINAL_AUDIT_SOURCE_CONTRACTS[next(iter(builder.FINAL_AUDIT_SOURCE_CONTRACTS))]
        source = next(iter(builder.FINAL_AUDIT_SOURCE_CONTRACTS))
        canonical = (ROOT / source).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        self.assertEqual(builder.normalized_text_sha256(ROOT / source), expected)
        with tempfile.TemporaryDirectory() as td:
            crlf = Path(td) / "source.py"
            crlf.write_bytes(b"\xef\xbb\xbf" + canonical.replace("\n", "\r\n").encode("utf-8"))
            self.assertEqual(builder.normalized_text_sha256(crlf), expected)

    def test_all_final_audit_source_contracts_match_current_sources(self):
        self.assertEqual(len(builder.FINAL_AUDIT_SOURCE_CONTRACTS), 3)
        for rel, expected in builder.FINAL_AUDIT_SOURCE_CONTRACTS.items():
            self.assertTrue((ROOT / rel).is_file())
            self.assertEqual(builder.normalized_text_sha256(ROOT / rel), expected)

    def test_rollout_authority_records_final_audit_normalized_source_contracts(self):
        contracts = self.authority["final_audit_source_contracts"]
        self.assertEqual(set(contracts), {str(x) for x in builder.FINAL_AUDIT_SOURCE_CONTRACTS})
        for rel, expected in builder.FINAL_AUDIT_SOURCE_CONTRACTS.items():
            row = contracts[str(rel)]
            self.assertEqual(row["normalized_text_sha256"], expected)
            self.assertEqual(row["expected_normalized_text_sha256"], expected)
            self.assertEqual(row["normalization"], "utf8_strip_bom_crlf_to_lf")

    def test_protected_persistent_contract_ignores_only_volatile_reacquire_diagnostics(self):
        persistent = json.loads(PROTECTED_PERSISTENT_PATH.read_text(encoding="utf-8-sig"))
        expected = builder.EXPECTED_PROTECTED_PERSISTENT_SEMANTIC_SHA256
        self.assertEqual(builder.protected_persistent_semantic_sha256(persistent), expected)

        mutated = json.loads(json.dumps(persistent))
        mutated["reacquire_calls"] = [{"returned_repr": "<PyRemoteObject at 0xDEADBEEF>"}]
        self.assertEqual(builder.protected_persistent_semantic_sha256(mutated), expected)

    def test_protected_persistent_contract_rejects_visual_state_change(self):
        persistent = json.loads(PROTECTED_PERSISTENT_PATH.read_text(encoding="utf-8-sig"))
        mutated = json.loads(json.dumps(persistent))
        mutated["rows"][0]["summary"]["start"] += 1
        self.assertNotEqual(
            builder.protected_persistent_semantic_sha256(mutated),
            builder.EXPECTED_PROTECTED_PERSISTENT_SEMANTIC_SHA256,
        )

    def test_rollout_authority_records_raw_and_semantic_persistent_evidence(self):
        contract = self.authority["protected_persistent_contract"]
        self.assertEqual(contract["semantic_projection"], "all_fields_except_volatile_reacquire_calls")
        self.assertEqual(contract["semantic_sha256"], builder.EXPECTED_PROTECTED_PERSISTENT_SEMANTIC_SHA256)
        self.assertEqual(contract["expected_semantic_sha256"], builder.EXPECTED_PROTECTED_PERSISTENT_SEMANTIC_SHA256)
        self.assertEqual(len(contract["raw_sha256_observed"]), 64)

    def test_authority_semantic_hash_and_preparer_contract(self):
        expected = builder.canonical_sha256({k: v for k, v in self.authority.items() if k != "semantic_sha256"})
        self.assertEqual(self.authority["semantic_sha256"], expected)
        preparer.validate_authority(self.authority)

    def test_timeline_isolation_and_rollout_lock(self):
        self.assertNotEqual(runtime.SOURCE_TIMELINE_NAME, runtime.TARGET_TIMELINE_NAME)
        self.assertIn("repair_metrics_v1", runtime.SOURCE_TIMELINE_NAME)
        self.assertIn("visual_fidelity_v2_v1", runtime.TARGET_TIMELINE_NAME)
        self.assertTrue(self.authority["policy"]["visual_approval_required"])
        self.assertFalse(self.authority["policy"]["further_rollout_authorized"])
        self.assertTrue(self.authority["policy"]["fade_polish_deferred"])


if __name__ == "__main__":
    unittest.main()
