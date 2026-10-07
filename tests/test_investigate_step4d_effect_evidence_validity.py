import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/analysis/investigate_step4d_effect_evidence_validity.py"
SPEC=importlib.util.spec_from_file_location("step4d_effect_validity",SCRIPT)
MODULE=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)


def test_effect_authority_is_gated_by_effect_specific_evidence():
    artifacts=MODULE.build()
    audit=json.loads(artifacts["step4d_effect_evidence_validity_audit.json"])
    report=artifacts["FINAL_REPORT.md"].decode()
    assert audit["freeze_integrity"]["status"]=="PASS"
    assert set(audit["effect_class_results"])==set(MODULE.EFFECTS)
    assert all(row["verdict"] in MODULE.VERDICTS for row in audit["effect_class_results"].values())
    assert all(case["mask_validity"] in MODULE.VALIDITY for case in audit["cases"])
    assert all(case["source_necessity_verdict"]!="SOURCE_REQUIRED" or case["mask_validity"] in {"VALID_FOR_EFFECT","PARTIAL_BUT_USABLE"} for case in audit["cases"])
    assert all(1<=sum(case["effect_class"]==effect for case in audit["cases"])<=3 for effect in MODULE.EFFECTS)
    assert audit["production_effect_mechanisms_added"]==0
    assert audit["upstream_artifacts_changed"] is audit["resolve_mutated"] is audit["step5_started"] is False
    assert report.count("IDENTITY: ")==len(audit["cases"])
    assert "NEXT_STEP_NAME_ONLY: Step 4D bounded effect-evidence mask repair" in report
