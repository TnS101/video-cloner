from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts/analysis/build_step_3E_post_visual_metrics_polish_v1.py"
RUNTIME_PATH = ROOT / "resolve_workspace/modules/step_3E_post_visual_metrics_polish_v1.py"
PREPARER_PATH = ROOT / "scripts/davinci/prepare_step_3E_post_visual_metrics_polish_v1.py"
CONFIRMED_PATH = ROOT / "artifacts/DZSQH7AUHJT_STEP_3E_CONFIRMED74_REPAIR_AUTHORITY_V1/confirmed74_repair_authority_v1.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = load_module(BUILDER_PATH, "post_visual_metrics_builder_under_test")
runtime = load_module(RUNTIME_PATH, "post_visual_metrics_runtime_under_test")
preparer = load_module(PREPARER_PATH, "post_visual_metrics_preparer_under_test")


@pytest.fixture(scope="module")
def authority():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "post_visual_metrics_polish_v1.json"
        yield builder.build(ROOT, output)


def test_direct_anchor_calibration_uses_source_vs_generated_glyph_height():
    token = {
        "font": {"font_family": "Any Family", "font_style": "Bold"},
        "application_base_size_candidate": 0.072,
        "source_pixel_anchor": {"source_height_px": 50, "generated_height_px": 20},
    }
    result = builder.direct_anchor_calibration(token)
    assert result is not None
    assert result["direct_size_factor"] == pytest.approx(2.5)
    assert result["rendered_size_per_source_px"] == pytest.approx(0.0036)


def test_family_calibration_is_robust_and_font_scoped():
    def token(size, generated, family="Family A"):
        return {
            "visual_token_id": f"v_{size}_{generated}_{family}",
            "font": {"font_family": family, "font_style": "Bold"},
            "application_base_size_candidate": size,
            "source_pixel_anchor": {"source_height_px": 50, "generated_height_px": generated},
        }

    rows = [
        token(0.075, 20),
        token(0.076, 20),
        token(0.074, 20),
        token(0.20, 20),  # robust-median outlier; no cue or word rule is involved
        token(0.06, 30, family="Family B"),
    ]
    result = builder.robust_family_calibration(rows)
    assert set(result) == {("Family A", "Bold"), ("Family B", "Bold")}
    assert result[("Family A", "Bold")]["rendered_size_per_source_px"] == pytest.approx(0.00375)
    assert result[("Family B", "Bold")]["rendered_size_per_source_px"] == pytest.approx(0.002)


def test_protected_composite_text_reconciliation_is_semantic_and_generic():
    semantic = {
        "coverage": [
            {
                "instance_id": "struct_a",
                "coverage_status": "source_absent_or_nonsemantic",
                "protected_composite": {
                    "protected_instance_id": "visual_x",
                    "protected_target_name": "VISUAL_TARGET",
                    "protected_text": "canonical sequence",
                    "source_instance_ids": ["struct_a", "struct_b"],
                    "resolution_method": "generic_sequence_resolution",
                },
            },
            {
                "instance_id": "struct_b",
                "coverage_status": "source_absent_or_nonsemantic",
                "protected_composite": {
                    "protected_instance_id": "visual_x",
                    "protected_target_name": "VISUAL_TARGET",
                    "protected_text": "canonical sequence",
                    "source_instance_ids": ["struct_a", "struct_b"],
                    "resolution_method": "generic_sequence_resolution",
                },
            },
        ]
    }
    protected = [
        {
            "visual_token_id": "visual_x",
            "target_name": "VISUAL_TARGET",
            "display_text": "stale visual text",
            "visual_window": [10, 20],
        }
    ]
    updates = builder.protected_text_reconciliation(semantic, protected)
    assert len(updates) == 1
    assert updates[0]["old_text"] == "stale visual text"
    assert updates[0]["new_text"] == "canonical sequence"
    assert updates[0]["source_instance_ids"] == ["struct_a", "struct_b"]
    assert updates[0]["basis"] == "semantic_coverage_protected_composite_reconciliation"


def test_real_authority_has_exact_bounded_mutation_scope(authority):
    summary = authority["summary"]
    assert summary["confirmed74_repair_instances"] == 74
    assert summary["protected_v4_instances"] == 17
    assert summary["unresolved_preserved"] == 23
    assert summary["composite_structural_removed"] == 3
    assert summary["expected_physical_textplus_count"] == 114
    assert summary["protected_size_updates"] == 16
    assert summary["repair_size_updates"] == 70
    assert summary["protected_text_updates"] == 1
    assert summary["font_calibration_profiles"] == 3
    assert summary["position_updates"] == 0
    assert summary["opacity_updates"] == 0


def test_real_composite_reconciliation_corrects_stale_protected_text_from_semantic_evidence(authority):
    updates = authority["protected_text_updates"]
    assert len(updates) == 1
    row = updates[0]
    assert row["instance_id"] == "vf_02_decorative_glyph"
    assert row["old_text"] == "Already"
    assert row["new_text"] == "I was"
    assert row["source_instance_ids"] == ["sub_016", "sub_017"]
    assert row["resolution_methods"] == ["nearby_canonical_sequence_by_source_aspect"]


def test_text_changed_protected_composite_is_not_sized_from_stale_generated_bbox(authority):
    text_ids = {row["instance_id"] for row in authority["protected_text_updates"]}
    size_ids = {row["instance_id"] for row in authority["protected_size_updates"]}
    assert text_ids
    assert not (text_ids & size_ids)


def test_real_font_calibration_uses_only_supported_measured_profiles(authority):
    profiles = {
        (row["font_family"], row["font_style"]): row
        for row in authority["font_render_calibration"]
    }
    assert set(profiles) == {
        ("Clash Grotesk Variable", "Bold"),
        ("Gabriola", "Regular"),
        ("Verdana", "Bold"),
    }
    assert profiles[("Clash Grotesk Variable", "Bold")]["sample_count"] == 14
    assert profiles[("Verdana", "Bold")]["sample_count"] == 1
    assert profiles[("Gabriola", "Regular")]["sample_count"] == 1


def test_repair_size_updates_never_guess_for_unmeasured_font_profiles(authority):
    confirmed = json.loads(CONFIRMED_PATH.read_text(encoding="utf-8-sig"))
    measured = {
        (row["font_family"], row["font_style"])
        for row in authority["font_render_calibration"]
    }
    updated_names = {row["target_name"] for row in authority["repair_size_updates"]}
    unsupported = []
    for row in confirmed["repair_instances"]:
        font = row.get("font") or {}
        key = (str(font.get("font_family") or ""), str(font.get("font_style") or ""))
        if key not in measured:
            unsupported.append(row["target_name"])
    assert len(unsupported) == 4
    assert not (set(unsupported) & updated_names)


def test_unresolved_and_removed_structural_rows_are_never_mutated(authority):
    confirmed = json.loads(CONFIRMED_PATH.read_text(encoding="utf-8-sig"))
    mutated = {
        row["target_name"]
        for section in ("protected_size_updates", "repair_size_updates", "protected_text_updates")
        for row in authority[section]
    }
    unresolved = {row["target_name"] for row in confirmed["preserve_unresolved"]}
    removed = {row["target_name"] for row in confirmed["remove_composite_structural"]}
    assert not (mutated & unresolved)
    assert not (mutated & removed)


def test_representative_size_failures_expand_through_generic_calibration(authority):
    by_instance = {
        row["instance_id"]: row
        for section in ("protected_size_updates", "repair_size_updates")
        for row in authority[section]
    }
    # Regression representatives from visual review. Production code does not branch on these IDs/texts.
    assert by_instance["vf_03_stakes"]["direct_size_factor"] == pytest.approx(2.5)
    assert by_instance["vf_07_something"]["direct_size_factor"] == pytest.approx(2.5)
    assert by_instance["sub_037"]["size_factor"] > 2.7
    assert by_instance["sub_038"]["size_factor"] > 2.7
    assert by_instance["sub_039"]["size_factor"] > 2.7


def test_opacity_and_center_are_explicitly_preserved(authority):
    assert authority["policy"]["position_mutation_authorized"] is False
    assert authority["policy"]["opacity_mutation_authorized"] is False
    assert authority["summary"]["position_updates"] == 0
    assert authority["summary"]["opacity_updates"] == 0
    fade = authority["protected_fade_evidence"]
    assert len(fade) == 17
    assert all(row["action"] == "preserve_existing_opacity_keys" for row in fade)
    something = next(row for row in fade if row["instance_id"] == "vf_07_something")
    assert something["exit_window"] == [685, 692]
    assert something["exit_min_factor"] == pytest.approx(0.25)


def test_runtime_plan_scope_matches_authority_and_has_no_position_or_opacity_plan(authority):
    plans = runtime.authority_plans(authority)
    assert len(plans["size"]) == 86
    assert len(plans["text"]) == 1
    assert len({row["target_name"] for row in plans["size"]}) == 86
    assert len({row["target_name"] for row in plans["text"]}) == 1
    assert "position" not in plans
    assert "opacity" not in plans


def test_authority_semantic_hash_and_policy_validate(authority):
    expected = builder.canonical_sha256({key: value for key, value in authority.items() if key != "semantic_sha256"})
    assert authority["semantic_sha256"] == expected
    validation = builder.validate_document(authority)
    assert validation["ok"], validation
    assert authority["policy"]["transcript_timing_authority"] is False
    assert authority["policy"]["per_cue_hardcoded_overrides"] is False
    assert authority["policy"]["screenshot_specific_overrides"] is False
    assert authority["policy"]["runtime_authorized"] is False


def synthetic_preparer_authority():
    authority = {
        "task_id": preparer.TASK_ID,
        "ok": True,
        "summary": {
            "expected_physical_textplus_count": preparer.EXPECTED_PHYSICAL,
            "position_updates": 0,
            "opacity_updates": 0,
        },
        "policy": {
            "transcript_timing_authority": False,
            "per_cue_hardcoded_overrides": False,
            "position_mutation_authorized": False,
            "opacity_mutation_authorized": False,
        },
    }
    authority["semantic_sha256"] = preparer.canonical_sha256(authority)
    return authority


def test_preparer_accepts_explicit_zero_mutation_scope():
    # Zero is a valid bounded mutation count; it must not be treated as a missing value.
    preparer.validate_authority(synthetic_preparer_authority())


def test_preparer_rejects_missing_or_nonzero_mutation_scope():
    authority = synthetic_preparer_authority()
    for key, replacement in (("position_updates", None), ("opacity_updates", None), ("position_updates", 1), ("opacity_updates", 1)):
        candidate = copy.deepcopy(authority)
        summary = candidate["summary"]
        if replacement is None:
            summary.pop(key, None)
        else:
            summary[key] = replacement
        candidate["semantic_sha256"] = preparer.canonical_sha256(
            {name: value for name, value in candidate.items() if name != "semantic_sha256"}
        )
        with pytest.raises(ValueError, match="authority_mutation_scope"):
            preparer.validate_authority(candidate)


def test_preparer_accepts_historical_persistent_schema_with_count_proven_by_checks():
    persistent = {
        "ok": True,
        "checks": {
            "source_timeline_unchanged": True,
            "physical_textplus_count": True,
            "v2_empty": True,
        },
    }
    # The confirmed74 runtime intentionally did not emit a top-level
    # expected_physical_textplus_count; its hashed runtime contract proves
    # the exact 114 count through this check, while the prior report proves
    # final_textplus_count == 114 separately.
    preparer.validate_prior_persistent(persistent)


def test_preparer_rejects_unproven_or_conflicting_prior_persistent_count():
    valid = {
        "ok": True,
        "checks": {
            "source_timeline_unchanged": True,
            "physical_textplus_count": True,
            "v2_empty": True,
        },
    }
    candidates = []

    missing_check = copy.deepcopy(valid)
    missing_check["checks"].pop("physical_textplus_count")
    candidates.append(missing_check)

    false_check = copy.deepcopy(valid)
    false_check["checks"]["physical_textplus_count"] = False
    candidates.append(false_check)

    conflicting_top_level = copy.deepcopy(valid)
    conflicting_top_level["expected_physical_textplus_count"] = preparer.EXPECTED_PHYSICAL + 1
    candidates.append(conflicting_top_level)

    failed_other_check = copy.deepcopy(valid)
    failed_other_check["checks"]["source_timeline_unchanged"] = False
    candidates.append(failed_other_check)

    for candidate in candidates:
        with pytest.raises(ValueError, match="prior_persistent"):
            preparer.validate_prior_persistent(candidate)
