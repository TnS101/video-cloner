from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
BUILDER_PATH = ROOT / "scripts" / "analysis" / "build_caption_visual_first_authority_pilot.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_caption_visual_first_authority_pilot.py"
CONTRACT_PATH = ROOT / "data" / "DZsqH7auhjt" / "analysis" / "DZsqH7auhjt_caption_visual_first_pilot_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load_module("visual_first_builder", BUILDER_PATH)
validator = load_module("visual_first_validator", VALIDATOR_PATH)


class VisualFirstAuthorityPilotTests(unittest.TestCase):
    def test_contract_contains_seven_user_rejected_windows(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        groups = contract["pilot_groups"]
        self.assertEqual(len(groups), 7)
        self.assertEqual(
            [group["group_id"] for group in groups],
            list(validator.EXPECTED_GROUP_IDS),
        )

    def test_contract_makes_source_pixels_primary_and_transcript_fallback_only(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        policy = contract["authority_policy"]
        self.assertEqual(policy["primary_authority"], "source_video_pixels")
        self.assertEqual(
            policy["transcript_use"],
            "search_seed_and_canonical_text_fallback_only",
        )
        self.assertIn(
            "one_transcript_cue_equals_one_visual_instance",
            policy["forbidden_assumptions"],
        )

    def test_contract_preserves_nineteen_display_identity(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        first = contract["pilot_groups"][0]["visual_tokens"][0]
        self.assertEqual(first["display_text"], "Nineteen")
        self.assertEqual(first["transcript_aliases"], ["19", "19."])
        self.assertEqual(first["text_authority"], "user_visual_evidence")

    def test_contract_supports_visual_only_decorations(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        tokens = {
            token["visual_token_id"]: token
            for group in contract["pilot_groups"]
            for token in group["visual_tokens"]
        }
        self.assertEqual(tokens["vf_02_decorative_glyph"]["visual_kind"], "decoration")
        self.assertEqual(tokens["vf_02_decorative_glyph"]["transcript_cue_ids"], [])
        self.assertEqual(tokens["vf_05_decorative_glyph"]["text_authority"], "visual_only")

    def test_normalize_cue_id_accepts_existing_zero_padded_style_ids(self):
        self.assertEqual(builder.normalize_cue_id("sub_0057"), "sub_057")
        self.assertEqual(builder.normalize_cue_id("sub_057"), "sub_057")
        self.assertEqual(builder.normalize_cue_id(57), "sub_057")
        self.assertIsNone(builder.normalize_cue_id(None))

    def test_union_window_uses_only_visual_evidence_windows(self):
        windows = [
            {"source": "style_event", "window": [100, 110]},
            {"source": "source_track_observations", "window": [97, 118]},
        ]
        self.assertEqual(builder.union_window(windows), [97, 118])
        self.assertIsNone(builder.union_window([]))

    def test_text_similarity_accepts_visual_aliases_without_forcing_identity(self):
        self.assertGreater(builder.text_similarity("Nineteen", "nineteen"), 0.99)
        self.assertLess(builder.text_similarity("Nineteen", "19"), 0.5)
        self.assertGreater(builder.text_similarity("blocks", "Buildings Blocks"), 0.65)

    def test_context_window_is_search_seed_not_authority(self):
        cues = {
            "sub_001": builder.Cue("sub_001", 1, 1.0, 1.2, "one"),
            "sub_002": builder.Cue("sub_002", 2, 1.2, 1.4, "two"),
        }
        window = builder.context_window_from_cues(["sub_001", "sub_002"], cues, 12)
        self.assertEqual(window, [12, 46])

    def test_validator_rejects_transcript_timing_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "PILOT_SUMMARY.md").write_text("summary\n", encoding="utf-8")
            manifest = {
                "task_id": validator.TASK_ID,
                "ok": True,
                "schema": "video_cloner_caption_visual_first_authority_pilot",
                "summary": {
                    "pilot_group_count": 7,
                    "transcript_timing_promoted_count": 1,
                    "resolve_modified": False,
                    "full_rollout_authorized": False,
                },
            }
            (output / "visual_authority_pilot.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(validator.ValidationError, "transcript_timing_promoted"):
                validator.validate(output)


if __name__ == "__main__":
    unittest.main()
