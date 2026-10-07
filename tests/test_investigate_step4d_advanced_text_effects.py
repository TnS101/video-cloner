import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/investigate_step4d_advanced_text_effects.py"
SPEC = importlib.util.spec_from_file_location("step4d_investigation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_investigation_enforces_methodology_without_preferring_a_conclusion():
    first = MODULE.build()
    second = MODULE.build()
    audit = json.loads(first["step4d_effect_necessity_audit.json"])
    validation = json.loads(first["step4d_necessity_investigation_validation.json"])
    manifest = json.loads(first["step4d_review_manifest.json"])
    assert first == second
    assert audit["identity_accounting"] == {"expected": 113, "produced": 113, "missing": [], "duplicates": 0}
    assert set(audit["effect_classes"]) == set(MODULE.CLASSES)
    assert all(row["classification"] in MODULE.ALLOWED_CLASSIFICATIONS for row in audit["effect_classes"].values())
    assert all(row["status"] in MODULE.ALLOWED_IDENTITY_STATUSES for row in audit["records"])
    assert all(row["evidence_for"] and all(item["provenance"] for item in row["evidence_for"]) for row in audit["effect_classes"].values() if row["classification"] == "SOURCE_REQUIRED")
    expected = {name.lower(): sum(row["classification"] == name for row in audit["effect_classes"].values()) for name in MODULE.ALLOWED_CLASSIFICATIONS}
    assert audit["summary"] == expected
    assert sum(audit["identity_classification_counts"].values()) == 113
    assert validation["legacy_shadow_systematic_defect"]["has_shadow_count"] == 113
    assert validation["legacy_shadow_systematic_defect"]["verdict"].startswith("UNSAFE_")
    assert validation["freeze_integrity"]["status"] == "PASS"
    assert validation["production_effect_mechanisms_added"] == 0
    assert validation["resolve_mutated"] is validation["later_non_caption_vfx_started"] is False
    assert 8 <= manifest["case_count"] <= 15

