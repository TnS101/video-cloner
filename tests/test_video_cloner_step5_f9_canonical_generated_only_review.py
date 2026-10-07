from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_canonical_source_and_cases_are_accepted() -> None:
    module = _load(ROOT / "scripts/davinci/prepare_video_cloner_step5_f9_canonical_generated_only_review.py", "f9_review_prepare")
    result = module.preflight()
    assert result["pass"] is True
    assert result["canonical_textplus_count"] == result["persisted_textplus_count"] == 65
    assert result["missing"] == result["unexpected"] == 0
    assert result["canonical_case_check"]["all_pass"] is True
    assert result["protected_source_mutation_planned"] is False
    assert result["canonical_source_mutation_planned"] is False


def test_generated_only_readback_uses_contract_count() -> None:
    source = (ROOT / "resolve_workspace/modules/video_cloner_step5_f8_generated_only_review.py").read_text(encoding="utf-8")
    assert 'len(generated) == len(expected_ids)' in source
    assert 'len(generated) == 65' not in source
    assert 'contract.get("object_count") != 65' not in source
