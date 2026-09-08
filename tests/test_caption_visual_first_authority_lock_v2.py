from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "data" / "DZsqH7auhjt" / "analysis" / "DZsqH7auhjt_caption_visual_first_authority_lock_v2.json"
BUILDER_PATH = ROOT / "scripts" / "analysis" / "build_caption_visual_first_authority_lock_v2.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_caption_visual_first_authority_lock_v2.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load_module("visual_authority_lock_v2_builder", BUILDER_PATH)
validator = load_module("visual_authority_lock_v2_validator", VALIDATOR_PATH)


class VisualAuthorityLockV2Tests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_contract_contains_seven_groups_and_seventeen_tokens(self):
        self.assertEqual(len(self.contract["groups"]), 7)
        self.assertEqual(sum(len(group["tokens"]) for group in self.contract["groups"]), 17)
        self.assertEqual(
            tuple(group["group_id"] for group in self.contract["groups"]),
            builder.EXPECTED_GROUP_IDS,
        )

    def test_contract_keeps_transcript_timing_non_authoritative(self):
        policy = self.contract["authority_policy"]
        self.assertFalse(policy["transcript_timing_authority"])
        self.assertEqual(policy["transcript_use"], "canonical_text_alias_only")
        self.assertTrue(policy["seven_window_resolve_pilot_authorized"])
        self.assertFalse(policy["full_rollout_authorized"])

    def test_decorative_components_are_resolved_to_visible_text(self):
        tokens = {
            token["visual_token_id"]: token
            for group in self.contract["groups"]
            for token in group["tokens"]
        }
        self.assertEqual(tokens["vf_02_decorative_glyph"]["display_text"], "Just")
        self.assertEqual(tokens["vf_05_decorative_glyph"]["display_text"], "I")
        self.assertEqual(tokens["vf_02_decorative_glyph"]["text_authority"], "visual_only")
        self.assertEqual(tokens["vf_05_decorative_glyph"]["transcript_cue_ids"], [])

    def test_no_contract_placeholder_survives(self):
        serialized = json.dumps(self.contract["groups"], ensure_ascii=False).casefold()
        for placeholder in self.contract["authority_policy"]["forbidden_placeholders"]:
            self.assertNotIn(placeholder.casefold(), serialized)

    def test_every_token_has_explicit_paths_style_and_phases(self):
        for group in self.contract["groups"]:
            for token in group["tokens"]:
                self.assertGreaterEqual(len(token["position_path"]), 2)
                self.assertGreaterEqual(len(token["size_path"]), 2)
                self.assertGreaterEqual(len(token["opacity_path"]), 2)
                self.assertTrue(token["style_lock"]["source_locked"])
                self.assertTrue(token["animation_phases"]["classification"])

    def test_persistent_group_windows_are_visual_first(self):
        tokens = {
            token["visual_token_id"]: token
            for group in self.contract["groups"]
            for token in group["tokens"]
        }
        self.assertEqual(tokens["vf_04_market"]["visual_window"], [464, 493])
        self.assertEqual(tokens["vf_04_back"]["visual_window"], [476, 493])
        self.assertEqual(tokens["vf_04_their"]["visual_window"], [482, 496])
        self.assertNotEqual(tokens["vf_04_market"]["visual_window"], [465, 474])

    def test_blocks_is_explicitly_right_aligned(self):
        tokens = {
            token["visual_token_id"]: token
            for group in self.contract["groups"]
            for token in group["tokens"]
        }
        self.assertGreater(tokens["vf_06_blocks"]["position_path"][0]["value"][0], 0.60)
        self.assertLess(tokens["vf_06_buildings"]["position_path"][0]["value"][0], 0.35)

    def test_something_has_explicit_entrance_hold_and_exit(self):
        token = next(
            token
            for group in self.contract["groups"]
            for token in group["tokens"]
            if token["visual_token_id"] == "vf_07_something"
        )
        self.assertEqual(token["animation_phases"]["entrance_window"], [658, 666])
        self.assertEqual(token["animation_phases"]["hold_window"], [666, 685])
        self.assertEqual(token["animation_phases"]["exit_window"], [685, 692])

    def test_validate_path_rejects_empty_or_out_of_window_rows(self):
        with self.assertRaises(builder.AuthorityLockError):
            builder.validate_path([], [10, 20], "bad", vector=False)
        with self.assertRaises(builder.AuthorityLockError):
            builder.validate_path(
                [{"timeline_frame": 9, "value": 1.0}, {"timeline_frame": 10, "value": 1.0}],
                [10, 20],
                "bad",
                vector=False,
            )

    def test_validator_rejects_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "LOCK_SUMMARY.md").write_text("summary\n", encoding="utf-8")
            manifest = {
                "task_id": validator.TASK_ID,
                "ok": True,
                "summary": {
                    "group_count": 7,
                    "visual_token_count": 17,
                    "visual_only_component_count": 2,
                    "unresolved_component_count": 0,
                    "placeholder_count": 0,
                    "transcript_timing_promoted_count": 0,
                    "resolve_modified": False,
                    "seven_window_resolve_pilot_authorized": True,
                    "full_rollout_authorized": False,
                },
                "groups": [],
            }
            (output / "visual_authority_lock_v2.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            with self.assertRaises(validator.ValidationError):
                validator.validate(output)


if __name__ == "__main__":
    unittest.main()
