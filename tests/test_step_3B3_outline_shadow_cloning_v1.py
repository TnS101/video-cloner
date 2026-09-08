from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3B3_outline_shadow_cloning_v1.py"
V4_PERSISTENT = ROOT / ".agent" / "reports" / "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4" / "20260812T174800495896Z_07d0e09144764182a5c4b1ec41ca6952" / "persistent_readback.json"
EFFECT_PLAN = ROOT / "data" / "DZsqH7auhjt" / "analysis" / "DZsqH7auhjt_caption_effect_mode_plan_step_3B_3C.json"
VISUAL_AUTHORITY = ROOT / "data" / "DZsqH7auhjt" / "analysis" / "DZsqH7auhjt_visual_polish_authority_v4.json"
PREPARER_PATH = ROOT / "scripts" / "davinci" / "prepare_step_3B3_outline_shadow_cloning_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("step3b3_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module




def load_preparer():
    spec = importlib.util.spec_from_file_location("step3b3_prepare_test_module", PREPARER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def accepted_fixture(module):
    persistent = load_json(V4_PERSISTENT)
    snapshot = persistent["target_caption_snapshot"]
    effect = load_json(EFFECT_PLAN)
    visual = load_json(VISUAL_AUTHORITY)
    authority = module.build_authority(snapshot["names"], effect, visual)
    return snapshot, authority


def row_by_name(snapshot, name):
    return next(row for row in snapshot["rows"] if row["name"] == name)


def set_series(snapshot, name, field, value):
    row = row_by_name(snapshot, name)
    prop = row["properties"][field]
    prop["values"] = [value for _ in prop["values"]]


def test_task_is_bounded_to_accepted_v4_source():
    module = load_module()
    assert module.SOURCE_TIMELINE_NAME.endswith("_occlusion_complete_v4")
    assert module.TARGET_TIMELINE_NAME.endswith("_occlusion_complete_v4_outline_shadow_v1")
    assert module.AUTHORIZED_EFFECT_FIELDS == {"Enabled2", "Enabled3"}


def test_current_accepted_snapshot_has_exact_two_source_authority_mismatches():
    module = load_module()
    snapshot, authority = accepted_fixture(module)
    audit = module.audit_snapshot(snapshot, authority)
    assert authority["counts"] == {"legacy": 96, "merged": 1, "visual_first": 17, "total": 114}
    assert audit["mismatch_count"] == 2
    assert module.mismatch_signature(audit) == module.expected_source_mismatch_signature()


def test_only_enabling_come_outline_and_shadow_completes_authority():
    module = load_module()
    snapshot, authority = accepted_fixture(module)
    target = copy.deepcopy(snapshot)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled2", 1.0)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled3", 1.0)
    audit = module.audit_snapshot(target, authority)
    assert audit["ok"] is True
    assert audit["mismatch_count"] == 0
    assert module.frozen_snapshot_equal(snapshot, target) is True


def test_frozen_snapshot_guard_rejects_center_regression():
    module = load_module()
    snapshot, _authority = accepted_fixture(module)
    target = copy.deepcopy(snapshot)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled2", 1.0)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled3", 1.0)
    row = row_by_name(target, module.TARGET_CAPTION_NAME)
    values = row["properties"]["Center"]["values"]
    values[0] = {"1": 0.123, "2": 0.456, "3": 0.0}
    assert module.frozen_snapshot_equal(snapshot, target) is False


def test_frozen_snapshot_guard_rejects_unrelated_shadow_change():
    module = load_module()
    snapshot, _authority = accepted_fixture(module)
    target = copy.deepcopy(snapshot)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled2", 1.0)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled3", 1.0)
    row = next(row for row in target["rows"] if row["name"] != module.TARGET_CAPTION_NAME and row["properties"].get("Enabled3", {}).get("exists"))
    row["properties"]["Enabled3"]["values"][0] = 0.123
    assert module.frozen_snapshot_equal(snapshot, target) is False


def test_visual_first_shadow_opacity_is_ratio_locked_not_static():
    module = load_module()
    snapshot, authority = accepted_fixture(module)
    target = copy.deepcopy(snapshot)
    name = "VC_VISUAL_FIRST_FULL_0001_vf_01_nineteen"
    row = row_by_name(target, name)
    assert len(set(row["properties"]["Opacity3"]["values"])) > 1
    row["properties"]["Opacity3"]["values"][0] += 0.05
    audit = module.audit_snapshot(target, authority)
    assert any(m["name"] == name and m["field"] == "Opacity3/Opacity1" for m in audit["mismatches"])


def test_merged_they_uses_matching_sub_051_sub_054_authority():
    module = load_module()
    snapshot, authority = accepted_fixture(module)
    rule = authority["rules"][module.MERGED_THEY_NAME]
    assert rule["kind"] == "merged"
    assert rule["cue_ids"] == ["sub_051", "sub_054"]
    row = row_by_name(snapshot, module.MERGED_THEY_NAME)
    # This merged accepted caption is already source-authority compliant.
    isolated = {"count": 1, "rows": [row]}
    mini_authority = {"rules": {module.MERGED_THEY_NAME: rule}, "counts": {"merged": 1}}
    assert module.audit_snapshot(isolated, mini_authority)["ok"] is True


def test_authority_rejects_unknown_current_caption():
    module = load_module()
    snapshot, _authority = accepted_fixture(module)
    names = list(snapshot["names"])
    names[-1] = "VC_UNKNOWN_CAPTION"
    try:
        module.build_authority(names, load_json(EFFECT_PLAN), load_json(VISUAL_AUTHORITY))
    except ValueError as exc:
        assert "authority_unknown" in str(exc)
    else:
        raise AssertionError("unknown current caption must fail authority construction")


def test_frozen_guard_allows_only_target_effect_slot_representation_activation():
    module = load_module()
    snapshot, _authority = accepted_fixture(module)
    target = copy.deepcopy(snapshot)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled2", 1.0)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled3", 1.0)
    row = row_by_name(target, module.TARGET_CAPTION_NAME)
    # Resolve can expose previously dormant slot metadata/values after Enabled2/3 flips.
    row["properties"]["Red2"]["data_type"] = "Number"
    row["properties"]["Green2"]["data_type"] = "Number"
    row["properties"]["Blue2"]["data_type"] = "Number"
    row["properties"]["Red3"]["data_type"] = "Number"
    row["properties"]["Green3"]["data_type"] = "Number"
    row["properties"]["Blue3"]["data_type"] = "Number"
    row["properties"]["Alpha2"] = {"exists": True, "connected": False, "data_type": "Number", "keyframes": {}, "values": [1.0] * 28}
    row["properties"]["Thickness2"] = {"exists": True, "connected": False, "data_type": "Number", "keyframes": {}, "values": [0.0566037736] * 28}
    assert module.frozen_snapshot_equal(snapshot, target) is True


def test_frozen_guard_still_rejects_target_fill_regression():
    module = load_module()
    snapshot, _authority = accepted_fixture(module)
    target = copy.deepcopy(snapshot)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled2", 1.0)
    set_series(target, module.TARGET_CAPTION_NAME, "Enabled3", 1.0)
    row = row_by_name(target, module.TARGET_CAPTION_NAME)
    row["properties"]["Red1"]["values"][0] += 0.1
    assert module.frozen_snapshot_equal(snapshot, target) is False


def test_target_effect_contract_spec_is_complete_source_backed_14_plus_3():
    module = load_module()
    _snapshot, authority = accepted_fixture(module)
    specs = module.target_effect_contract_spec(authority)
    required = [row for row in specs if row["required"]]
    optional = [row for row in specs if not row["required"]]
    assert len(required) == 14
    assert len(optional) == 3
    expected = {row["label"]: row["expected"] for row in specs}
    assert expected["outline_enabled"] == 1.0
    assert expected["outline_shape"] == 1.0
    assert abs(expected["outline_thickness"] - 0.0566037736) < 1e-12
    assert expected["outline_outside_only"] == 1.0
    assert expected["shadow_enabled"] == 1.0
    assert expected["shadow_shape"] == 0.0
    assert expected["shadow_opacity"] == 0.85
    assert expected["shadow_offset"] == [0.003, 0.003]
    assert abs(expected["shadow_softness_x"] - 0.0188679245) < 1e-12
    assert abs(expected["shadow_softness_y"] - 0.0188679245) < 1e-12


class FakeContractBase:
    def __init__(self, values):
        self.values = dict(values)

    def find_input(self, _tool, name):
        return object() if name in self.values else None

    def read_input(self, _tool, name, _frame):
        return self.values.get(name)

    @staticmethod
    def json_safe(value):
        return value


def contract_values_from_spec(module, authority):
    values = {}
    for row in module.target_effect_contract_spec(authority):
        # Expose the first canonical candidate for each contract row.
        values[row["candidates"][0]] = row["expected"]
    return values


def test_full_target_effect_contract_passes_exact_authority_and_rejects_thickness_drift():
    module = load_module()
    _snapshot, authority = accepted_fixture(module)
    values = contract_values_from_spec(module, authority)
    base = FakeContractBase(values)
    result = module.validate_target_effect_contract(base, object(), authority)
    assert result["ok"] is True
    assert result["required_matched_count"] == 14
    assert result["optional_exposed_count"] == 3
    assert result["optional_matched_count"] == 3

    bad = dict(values)
    bad["Thickness2"] = 0.5
    result = module.validate_target_effect_contract(FakeContractBase(bad), object(), authority)
    assert result["ok"] is False
    failed = [row for row in result["rows"] if not row["matched"]]
    assert [row["label"] for row in failed] == ["outline_thickness"]


def test_preparer_accepts_only_the_known_cleaned_failed_run(tmp_path):
    preparer = load_preparer()
    run_id = preparer.PREVIOUS_FAILED_RUN_ID
    failed = tmp_path / ".agent" / "commands" / "failed"
    report_dir = tmp_path / ".agent" / "reports" / preparer.TASK_ID / run_id
    failed.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (failed / f"{preparer.TASK_ID}_{run_id}.json").write_text(json.dumps({
        "task_id": preparer.TASK_ID, "run_id": run_id
    }), encoding="utf-8")
    (report_dir / "report.json").write_text(json.dumps({
        "task_id": preparer.TASK_ID,
        "run_id": run_id,
        "ok": False,
        "failures": ["RuntimeError: unrelated_caption_regression"],
        "save_call_count": 1,
        "failure_cleanup_ok": True,
        "failed_target_retained": False,
    }), encoding="utf-8")
    (report_dir / "failure_cleanup.json").write_text(json.dumps({
        "ok": True, "save_call_count": 1
    }), encoding="utf-8")
    result = preparer.validate_previous_failed_run(tmp_path)
    assert result == {
        "run_id": run_id,
        "failure": "unrelated_caption_regression",
        "cleanup_ok": True,
        "target_retained": False,
    }
