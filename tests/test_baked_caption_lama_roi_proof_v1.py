from __future__ import annotations

import ast
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "analysis" / "run_baked_caption_lama_roi_proof_v1.py"
PROVISIONER = REPO_ROOT / "scripts" / "analysis" / "provision_lama_roi_proof_v1.py"
VALIDATOR = REPO_ROOT / "scripts" / "analysis" / "validate_baked_caption_lama_roi_proof_v1.py"
EXPECTED_MODEL_SHA = "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"
EXPECTED_HELPER_SHA = "ca95ccfa9e9070a8b4f4ade24afd89d441d016eb931476b4e0d30fffd5a7817d"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LamaRoiProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_module("vc_lama_runner_test", RUNNER)
        cls.provisioner = load_module("vc_lama_provisioner_test", PROVISIONER)
        cls.validator = load_module("vc_lama_validator_test", VALIDATOR)

    def test_all_scripts_parse(self):
        for path in (RUNNER, PROVISIONER, VALIDATOR):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_architecture_is_new_engine_not_diffueraser_variant(self):
        self.assertEqual(
            self.runner.ARCHITECTURE_FAMILY,
            "lama_highres_roi_source_authority_semantic_composite_v1",
        )
        self.assertEqual(self.runner.ARCHITECTURE_ATTEMPT, 1)
        self.assertNotIn("diffueraser_roi_source_authority_semantic_composite_v1", self.runner.ARCHITECTURE_FAMILY)

    def test_parent_visual_failure_is_explicit(self):
        self.assertEqual(self.runner.PARENT_FAILURE_CLASS, "G_VISUAL")
        self.assertIn("persistent_dark_glyph_like_topology", self.runner.PARENT_FAILURE_SIGNATURE)

    def test_model_and_authority_hashes_are_pinned(self):
        self.assertEqual(self.runner.EXPECTED_MODEL_SHA256, EXPECTED_MODEL_SHA)
        self.assertEqual(self.provisioner.MODEL_SHA256, EXPECTED_MODEL_SHA)
        self.assertEqual(self.validator.EXPECTED_MODEL_SHA256, EXPECTED_MODEL_SHA)
        self.assertEqual(self.runner.EXPECTED_DIFFUERASER_HELPER_SHA256, EXPECTED_HELPER_SHA)

    def test_gates_are_not_weakened(self):
        self.assertGreaterEqual(self.runner.MIN_SOURCE_GLYPH_REDUCTION, 0.70)
        self.assertGreaterEqual(self.runner.MIN_RIGHT_GLYPH_REMOVAL, 0.75)
        self.assertLessEqual(self.runner.MAX_NEW_DARK_ARTIFACT_RATIO, 0.03)
        self.assertLessEqual(self.runner.MAX_NEW_BRIGHT_ARTIFACT_RATIO, 0.03)
        self.assertLessEqual(self.runner.MAX_BOUNDARY_RING_MAE, 30.0)
        self.assertEqual(self.validator.MIN_SOURCE_GLYPH_REDUCTION, 0.70)
        self.assertEqual(self.validator.MIN_RIGHT_GLYPH_REMOVAL, 0.75)

    def test_frame_boundary_is_exactly_24(self):
        self.assertEqual(self.runner.SOURCE_FRAME_START, 429)
        self.assertEqual(self.runner.SOURCE_FRAME_END, 452)
        self.assertEqual(self.runner.FRAME_COUNT, 24)
        self.assertEqual(self.validator.SOURCE_FRAME_START, 429)
        self.assertEqual(self.validator.SOURCE_FRAME_END, 452)

    def test_closed_families_include_known_same_frame_sky_plate(self):
        self.assertIn(
            "same_frame_rowwise_sky_interpolation_inside_come_authority_minus_semantic_person_v1",
            self.runner.CLOSED_ARCHITECTURE_FAMILIES,
        )
        self.assertIn("propainter_semantic_split_person_repair_v1", self.runner.CLOSED_ARCHITECTURE_FAMILIES)

    def test_native_roi_padding_is_modulo_8_only(self):
        self.assertEqual(self.runner.ceil_modulo(854, 8), 856)
        self.assertEqual(self.runner.ceil_modulo(431, 8), 432)
        self.assertEqual(self.runner.ceil_modulo(432, 8), 432)

    def test_provisioner_reuses_existing_cuda_runtime_without_pip_install(self):
        source = PROVISIONER.read_text(encoding="utf-8")
        self.assertIn("diffueraser_proof_v1", source)
        self.assertNotIn("pip install", source)
        self.assertNotIn("subprocess.check_call", source)

    def test_provisioner_reuses_exact_quarantined_model_without_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_path = root / "big-lama.pt"
            candidate = root / "big-lama.pt.part.sha_mismatch_7ba7aa7ac37a"
            candidate.write_bytes(b"known-model")
            original_hash = self.provisioner.sha256_file
            original_download = self.provisioner._download_once
            try:
                self.provisioner.sha256_file = lambda path: EXPECTED_MODEL_SHA if Path(path) == candidate else original_hash(Path(path))
                self.provisioner._download_once = lambda *args, **kwargs: self.fail("network download must not run")
                result = self.provisioner.ensure_model(model_path)
            finally:
                self.provisioner.sha256_file = original_hash
                self.provisioner._download_once = original_download
            self.assertTrue(model_path.is_file())
            self.assertFalse(candidate.exists())
            self.assertEqual(result["sha256"], EXPECTED_MODEL_SHA)
            self.assertTrue(result["reused_quarantined_download"])
            self.assertFalse(result["downloaded"])

    def test_runner_serializes_windows_paths_without_masking_other_type_errors(self):
        payload = {"artifact": Path(r"C:\\proof\\frame.png")}
        encoded = __import__("json").dumps(payload, default=self.runner.json_path_default)
        self.assertIn("frame.png", encoded)
        with self.assertRaises(TypeError):
            __import__("json").dumps({"bad": object()}, default=self.runner.json_path_default)

    def test_runner_has_no_propainter_inference_call(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("run_diffueraser(", source)
        self.assertNotIn("ProPainter", source)
        self.assertIn("torch.jit.load", source)

    def test_validator_requires_visual_approval_and_raw_output(self):
        source = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn('"LAMA_ROI_OUTPUT.mp4"', source)
        self.assertIn('"visual_approval_required": True', source)
        self.assertIn("No readable or glyph-like COME topology", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
