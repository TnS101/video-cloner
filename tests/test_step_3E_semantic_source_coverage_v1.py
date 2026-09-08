import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


b = load("semantic_coverage_builder", "scripts/analysis/build_step_3E_semantic_source_coverage_v1.py")
v = load("semantic_coverage_validator", "scripts/analysis/validate_step_3E_semantic_source_coverage_v1.py")


def candidate(text="development", confidence=0.92, bbox=(100, 100, 260, 150)):
    return SimpleNamespace(
        text=text,
        confidence=confidence,
        bbox=list(bbox),
        source_text=text,
        source_kind="ocr_line",
    )


def test_probe_frames_use_only_source_pixel_evidence():
    row = {
        "source_pixel_scan": {"selected_frames": [20, 21, 22, 23], "peak_frame": 22},
        "visual_window": [20, 24],
        "search_seed_only": {"window": [100, 120]},
    }
    assert b.probe_frames_for_row(row, max_frames=7) == [20, 21, 22, 23]


def test_probe_frames_are_deterministically_bounded():
    row = {
        "source_pixel_scan": {"selected_frames": list(range(10, 30)), "peak_frame": 18},
        "visual_window": [10, 30],
    }
    frames = b.probe_frames_for_row(row, max_frames=5)
    assert len(frames) == 5
    assert frames[0] == 10
    assert frames[-1] == 29


def test_short_token_requires_exact_semantics():
    weak = candidate(text="l", bbox=(95, 95, 115, 150))
    result = b.semantic_candidate_score(
        weak, "I", (105, 122), (25, 55), 540, 960,
        min_text_similarity=0.62, crop_localized=True,
    )
    assert result is None


def test_long_token_may_use_fuzzy_ocr_with_spatial_support():
    cand = candidate(text="developrnent", confidence=0.88, bbox=(100, 100, 280, 150))
    result = b.semantic_candidate_score(
        cand, "development", (190, 125), (180, 50), 540, 960,
        min_text_similarity=0.62, crop_localized=False,
    )
    assert result is not None
    assert result["text_similarity"] >= 0.62


def test_far_duplicate_is_rejected_on_full_frame():
    cand = candidate(text="the", confidence=0.99, bbox=(450, 800, 500, 850))
    result = b.semantic_candidate_score(
        cand, "the", (100, 100), (60, 40), 540, 960,
        min_text_similarity=0.62, crop_localized=False,
    )
    assert result is None


def test_confirmed_requires_two_normal_observations():
    observations = [
        {"text_similarity": 0.93, "ocr_confidence": 0.91},
        {"text_similarity": 0.88, "ocr_confidence": 0.86},
    ]
    status, reasons = b.classify_probe(
        observations,
        source_pixel_detected_frames=5,
        source_pixel_confidence="high",
        min_median_similarity=0.62,
        min_median_confidence=0.24,
    )
    assert status == "source_confirmed"
    assert reasons == []


def test_negative_ocr_does_not_become_absent():
    status, reasons = b.classify_probe(
        [],
        source_pixel_detected_frames=7,
        source_pixel_confidence="high",
        min_median_similarity=0.62,
        min_median_confidence=0.24,
    )
    assert status == "source_unresolved"
    assert "no_semantic_ocr_match_in_source_pixel_probe" in reasons


def test_protected_composite_reconciles_structural_rows_generically():
    authority = {
        "instances": [
            {
                "instance_id": "visual_composite",
                "target_name": "VC_VISUAL_COMPOSITE",
                "canonical_text": "I was",
                "presence_status": "protected_existing",
                "text_resolution": {
                    "ok": True,
                    "method": "nearby_canonical_sequence_by_source_aspect",
                    "source_instance_ids": ["sub_a", "sub_b"],
                },
            }
        ]
    }
    result = b.protected_composite_map(authority)
    assert set(result) == {"sub_a", "sub_b"}
    assert result["sub_a"]["protected_instance_id"] == "visual_composite"


def test_validator_rejects_not_evaluated_status(tmp_path):
    authority_dir = tmp_path / v.CURRENT_AUTHORITY.parent
    authority_dir.mkdir(parents=True)
    excluded = [
        {
            "instance_id": f"sub_{i:03d}",
            "presence_status": "source_unresolved" if i < 14 else "source_not_evaluated",
        }
        for i in range(v.EXPECTED_EXCLUDED)
    ]
    protected = [{"instance_id": "protected", "presence_status": "protected_existing"}]
    (tmp_path / v.CURRENT_AUTHORITY).write_text(json.dumps({"instances": excluded + protected}), encoding="utf-8")

    rows = []
    for i, source in enumerate(excluded):
        rows.append(
            {
                "instance_id": source["instance_id"],
                "coverage_status": "source_unresolved" if i else "source_not_evaluated",
                "transcript_timing_authority": False,
                "search_prior": {
                    "authority": "source_pixel_visibility_only",
                    "cue_or_transcript_window_used_as_authority": False,
                    "probe_frames": [1, 2],
                },
                "probe_evidence": {"reasons": ["probe_inconclusive"]},
            }
        )
    coverage = {
        "task_id": v.TASK_ID,
        "ok": True,
        "policy": {
            "source_pixel_windows_are_search_priors_only": True,
            "transcript_timing_authority": False,
            "geometry_only_cannot_confirm_semantics": True,
            "negative_ocr_alone_cannot_prove_absence": True,
            "protected_composite_can_reconcile_redundant_structural_rows": True,
            "per_cue_hardcoded_overrides": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "configuration": {"min_text_similarity": 0.62, "min_median_ocr_confidence": 0.24},
        "summary": {
            "evaluated_excluded_instances": 53,
            "source_confirmed_instances": 0,
            "source_absent_or_nonsemantic_instances": 0,
            "source_unresolved_instances": 52,
            "source_not_evaluated_instances": 1,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "coverage": rows,
        "semantic_sha256": "",
    }
    coverage["semantic_sha256"] = v.canonical_sha256({k: val for k, val in coverage.items() if k != "semantic_sha256"})
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
    with pytest.raises(v.ValidationError, match="not_evaluated_forbidden"):
        v.validate(tmp_path, coverage_path, tmp_path / "validation.json")
