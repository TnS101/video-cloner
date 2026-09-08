from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runtime = load("reel1_idempotency", ROOT / "resolve_workspace/modules/video_cloner_phase5_reel1_flash_v4_idempotency.py")
fixtures = load("reel1_restore_tests", ROOT / "tests/test_video_cloner_phase5_reel1_flash_v4_orphan_restoration.py")
validator = load("reel1_idempotency_validator", ROOT / "scripts/davinci/validate_video_cloner_phase5_reel1_flash_v4_idempotency.py")


def complete_carriers():
    rows = fixtures.carriers()
    for index, row in enumerate(rows, 1):
        row.name = f"VC_FLASH_{index:03d}_frame_{row.start + 2:04d}"
        row.comps = ["Composition 1"]
        row.uid = EXPECTED_UIDS[index - 1]
    return rows


EXPECTED_UIDS = ["1fecf6d7-d9cc-4f95-a364-46f6720ad1d2", "167f2069-22e7-4cde-95af-a32fb4a4d4f3",
                 "55bb94da-1514-43a2-8f93-f91747080977", "4fd5f1a9-80e8-47ef-8a82-567a268293ae",
                 "8be67962-3df9-461c-9325-8576f070c9b2"]


def command(plan=None):
    return {"run_id": "test-run", "command": {"task": runtime.TASK_ID, "mode": runtime.MODE, "run_id": "test-run",
            "payload": {"expected_project": runtime.PROJECT_NAME, "target_timeline_name": runtime.TARGET_TIMELINE_NAME,
                        "repository_root": str(ROOT), "accepted_plan": plan or fixtures.plan(),
                        "accepted_plan_file_sha256": runtime.EXPECTED_PLAN_SHA256, "restoration_report": {},
                        "persistence_report": {}, "read_only": False}}}


def simulate(monkeypatch, mutate=None, inventory_drift=None):
    target_items = complete_carriers()
    if mutate:
        mutate(target_items)
    historical = fixtures.Timeline(runtime.RESTORE.HISTORICAL_TIMELINE_NAME, [fixtures.Item(426, 454, uid="historical")])
    target = fixtures.Timeline(runtime.TARGET_TIMELINE_NAME, target_items)
    reel2 = fixtures.Timeline(runtime.RESTORE.REEL2_TIMELINE_NAME, [fixtures.Item(0, 854, name="reel2", media=fixtures.Media(uid="reel2"), uid="reel2")])
    project = fixtures.Project(target, historical, reel2)
    manager = fixtures.Manager(project)
    inventory_calls = 0

    def snapshot(timeline):
        return {"signature": runtime.EXPECTED_COMPLETE_SIGNATURE if timeline is target else f"signature:{timeline.name}"}

    def inventory(project_arg, target_name):
        nonlocal inventory_calls
        inventory_calls += 1
        rows = [{"name": timeline.name, "signature": snapshot(timeline)["signature"]} for timeline in project_arg.timelines]
        if inventory_drift and inventory_calls == 2:
            rows[-1]["signature"] = "drift"
        return rows, [row for row in rows if row["name"] != target_name]

    monkeypatch.setattr(runtime.BASE, "validate_plan", lambda value: None)
    monkeypatch.setattr(runtime, "_load_prerequisites", lambda *args: (EXPECTED_UIDS, inventory(project, runtime.TARGET_TIMELINE_NAME)[0]))
    monkeypatch.setattr(runtime.BASE, "non_target_inventory", inventory)
    monkeypatch.setattr(runtime.P4B, "timeline_snapshot", snapshot)
    monkeypatch.setattr(runtime.RESTORE, "_media_and_references", lambda *args, **kwargs: (
        {"unique_id": runtime.EXPECTED_MEDIA_UID},
        [{"timeline": runtime.RESTORE.HISTORICAL_TIMELINE_NAME, "track_index": 25, "start": 426, "end": 454, "fusion_comp_count": 0}]
        + [{"timeline": runtime.TARGET_TIMELINE_NAME, "track_index": 26, "start": start, "end": end, "fusion_comp_count": 1}
           for start, end in runtime.EXPECTED_SPANS]))
    monkeypatch.setattr(runtime.V4, "neutral_flash_snapshot", lambda *args: {"ok": mutate is None, "neutral_carrier_count": 5, "source_video_carrier_count": 0})
    for owner, name in ((runtime.BASE.V1, "configure_flash"), (runtime.BASE.V1, "append_flash_carriers"),
                        (runtime.V4, "import_neutral_carrier"), (runtime.V4, "_delete_owned_media_pool_item")):
        monkeypatch.setattr(owner, name, lambda *args, _name=name, **kwargs: (_ for _ in ()).throw(AssertionError(_name)))
    result = runtime.run(fixtures.Resolve(manager), command())
    return result, project, manager, target_items


def test_complete_state_is_reused_with_zero_mutations(monkeypatch):
    result, project, manager, items = simulate(monkeypatch)
    assert result["ok"] is True and result["classification"] == "RELINKED_FLASH_ALREADY_COMPLETE"
    assert result["completed_state_after"]["classification"] == "VALID_RELINKED_FLASH_COMPLETE_STATE"
    assert result["mutation_counts"] == runtime.ZERO_MUTATIONS
    assert result["carrier_uids_before"] == result["carrier_uids_after"] == EXPECTED_UIDS
    assert [item.uid for item in items] == EXPECTED_UIDS
    assert manager.save_count == 0 and project.set_calls == []


def test_missing_or_malformed_fusion_wrong_name_span_duplicate_and_media_fail_closed(monkeypatch):
    mutations = [
        lambda rows: rows[0].comps.clear(),
        lambda rows: None,
        lambda rows: setattr(rows[0], "name", "wrong"),
        lambda rows: setattr(rows[0], "end", 99),
        lambda rows: rows.append(fixtures.Item(800, 804, name="VC_FLASH_006_frame_0802")),
        lambda rows: setattr(rows[0].media, "uid", "wrong"),
    ]
    for mutate in mutations:
        result, project, manager, _ = simulate(monkeypatch, mutate=mutate)
        assert result["ok"] is False and result["classification"] == "FAILED_CLOSED"
        assert manager.save_count == 0 and project.set_calls == []


def test_historical_or_reel2_signature_drift_fails_closed(monkeypatch):
    result, project, manager, _ = simulate(monkeypatch, inventory_drift=True)
    assert result["ok"] is False and result["failures"] == ["RuntimeError: live_inventory_drift"]
    assert manager.save_count == 0 and project.set_calls == []


def test_authority_geometry_drift_fails_before_live_validation(monkeypatch):
    bad = fixtures.plan()
    bad["flashes"][0]["start_frame"] = 93
    monkeypatch.setattr(runtime.BASE, "validate_plan", lambda value: None)
    result = runtime.run(None, command(bad))
    assert result["ok"] is False and result["failures"] == ["ValueError: accepted_plan_geometry"]


def test_runtime_has_no_standalone_export_dependency():
    source = Path(runtime.__file__).read_text(encoding="utf-8").lower()
    assert "fcpxml" not in source and "standalone_timeline" not in source


def test_offline_validator_accepts_exact_no_op_report(monkeypatch, tmp_path):
    result, _, _, _ = simulate(monkeypatch)
    report_dir = tmp_path / ".agent/reports" / runtime.TASK_ID / "test-run"
    report_dir.mkdir(parents=True)
    import json
    (report_dir / "report.json").write_text(json.dumps(result), encoding="utf-8")
    validated = validator.validate(tmp_path, "test-run")
    assert validated == {"ok": True, "run_id": "test-run", "failures": [],
                         "classification": "PASS_PHASE5_REEL1_FLASH_IDEMPOTENCY"}
