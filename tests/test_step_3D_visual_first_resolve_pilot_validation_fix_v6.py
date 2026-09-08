from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "davinci" / "validate_step_3D_visual_first_resolve_pilot.py"
REVIEW = ROOT / "scripts" / "analysis" / "build_step_3D_visual_first_resolve_pilot_review.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


validator = load("visual_first_validator_v6", VALIDATOR)
review = load("visual_first_review_v6", REVIEW)


def test_completed_runtime_status_without_state_is_accepted():
    status = {
        "schema_version": 1,
        "run_id": "RUN123",
        "ok": True,
        "running": False,
        "finished_at": "2026-08-10T01:13:42Z",
        "report_path": "report.json",
    }
    assert validator.status_is_completed(status, "RUN123") is True


def test_nonterminal_runtime_status_without_state_is_rejected():
    status = {
        "schema_version": 1,
        "run_id": "RUN123",
        "ok": True,
        "running": True,
        "finished_at": None,
    }
    assert validator.status_is_completed(status, "RUN123") is False


def test_legacy_explicit_completed_state_remains_accepted():
    assert validator.status_is_completed({"state": "completed"}, "RUN123") is True
    assert validator.status_is_completed({"status": "completed"}, "RUN123") is True


def test_review_builder_uses_corrected_v3_authority():
    assert review.AUTHORITY_TASK_ID == "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3"
    assert str(review.AUTHORITY_RELATIVE_PATH).replace("\\", "/").endswith(
        "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3/visual_authority_script_renderability_v3.json"
    )
