import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/adjudicate_step4d_source_required_effects.py"
SELECTION = ROOT / "tests/fixtures/step4d_source_effect_adjudication_cases.json"
SPEC = importlib.util.spec_from_file_location("step4d_source_adjudication", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_source_required_adjudication_is_bounded_and_fail_closed():
    artifacts = MODULE.build(SELECTION)
    adjudication = json.loads(artifacts["step4d_source_required_effect_adjudication.json"])
    validation = json.loads(artifacts["step4d_source_required_effect_adjudication_validation.json"])

    assert validation["result"] == "PASS_STEP_4D_SOURCE_REQUIRED_EFFECT_ADJUDICATION_READY_FOR_HUMAN_REVIEW"
    assert validation["freeze_integrity"]["status"] == "PASS"
    assert set(adjudication["class_verdicts"]) == set(MODULE.EFFECTS)
    assert all(row["verdict"] in MODULE.CASE_VERDICTS for row in adjudication["cases"])
    assert all(row["evidence_validity"] in {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"} for row in adjudication["cases"] if row["verdict"] == "SOURCE_REQUIRED")
    assert all(row["verdict"] == "UNRESOLVED" for row in adjudication["cases"] if row["evidence_validity"] not in {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"})
    assert {effect: row["verdict"] for effect, row in adjudication["class_verdicts"].items()} == {
        "shadow": "SOURCE_REQUIRED",
        "glow": "NOT_SOURCE_REQUIRED",
        "texture": "NOT_SOURCE_REQUIRED",
        "gradient": "NOT_SOURCE_REQUIRED",
        "clipping": "UNRESOLVED",
    }
    assert adjudication["caption_occlusion_status"]["verdict"] == "BLOCKED_BY_OWNERSHIP_EVIDENCE"
    assert validation["production_hardcoded_identities"] == []
    assert validation["production_effect_mechanisms_added"] == 0
    assert validation["upstream_artifacts_changed"] is validation["resolve_mutated"] is validation["step5_started"] is validation["step6_started"] is False
