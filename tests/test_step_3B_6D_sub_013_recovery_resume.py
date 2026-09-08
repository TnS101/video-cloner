from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "resolve_workspace/modules/step_3B_6D_sub_013_recovery_resume.py"
PREPARER = ROOT / "scripts/davinci/prepare_step_3B_6D_sub_013_recovery_resume_command.py"
VALIDATOR = ROOT / "scripts/davinci/validate_step_3B_6D_sub_013_recovery_resume.py"


def test_resume_runtime_is_strictly_read_only():
    source = MODULE.read_text(encoding="utf-8")
    forbidden = (
        "SaveProject",
        "DeleteModifier",
        "AddModifier",
        "Disconnect",
        "ConnectTo",
        "RemoveKeyFrame",
        "SetInput",
        "inp[",
    )
    for token in forbidden:
        assert token not in source
    assert '"current_run_setter_call_count": 0' in source
    assert '"timeline_modified": False' in source


def test_topology_comparison_uses_only_structural_fields():
    source = MODULE.read_text(encoding="utf-8")
    assert "raw_keyframe_structure" in source
    assert '"OUTS_ID"' in source
    assert '"OUTS_DataType"' in source
    assert '"INPS_ID"' in source
    assert 'comparison_scope": "structural fields only; dynamic values excluded"' in source
    assert 'safe(output, "GetAttrs"' in source
    assert '"modifier": {' in source


def test_resume_binds_exact_failed_setter_lineage_and_never_replays_it():
    source = MODULE.read_text(encoding="utf-8")
    assert "20260802T185045608Z_e574ca97eb634e518481365d1398d3d9" in source
    assert "source_setter_call_count" in source
    assert "exact_two_allowlisted_corrections" in source
    assert "resume_state_not_36_target_equal" in source


def test_preparer_allocates_only_after_prerequisites_and_uses_real_conflict_iteration():
    source = PREPARER.read_text(encoding="utf-8")
    allocation = source.index("run_id = allocate_run_id()")
    assert source.index("validate_hashes(root)") < allocation
    assert source.index("validate_source_failure(root, queue_root)") < allocation
    assert source.index("validate_no_conflicts(root, queue_root)") < allocation
    assert "for path in (queue_root / state).glob" in source
    assert "MANUAL_ACTION_REQUIRED: run Workspace > Scripts > VC_Agent_Bridge exactly once" in source


def test_validator_requires_unique_completed_lifecycle_and_zero_mutation_phase_three():
    source = VALIDATOR.read_text(encoding="utf-8")
    assert 'instances != [completed_path]' in source
    assert '"current_run_setter_call_count") != 0' in source
    assert '"current_target": 36' in source
    assert '"structural_topology_unchanged": True' in source
