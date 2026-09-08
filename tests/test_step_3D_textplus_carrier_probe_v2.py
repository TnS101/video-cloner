from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = (
    ROOT
    / "resolve_workspace"
    / "modules"
    / "step_3D_textplus_carrier_probe_v2.py"
)
PUBLISHER_PATH = (
    ROOT
    / "scripts"
    / "davinci"
    / "prepare_step_3D_textplus_carrier_probe_v2.py"
)
VALIDATOR_PATH = (
    ROOT
    / "scripts"
    / "davinci"
    / "validate_step_3D_textplus_carrier_probe_v2.py"
)


def load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load(RUNTIME_PATH, "textplus_carrier_probe_v2_runtime")
publisher = load(PUBLISHER_PATH, "textplus_carrier_probe_v2_publisher")
validator = load(VALIDATOR_PATH, "textplus_carrier_probe_v2_validator")


class FakeItem:
    def __init__(
        self,
        name: str,
        unique_id: str,
        start: int,
        end: int,
        comp_count: int = 1,
    ) -> None:
        self.name = name
        self.unique_id = unique_id
        self.start = start
        self.end = end
        self.comp_count = comp_count

    def GetDuration(self) -> int:
        return self.end - self.start

    def GetFusionCompCount(self) -> int:
        return self.comp_count


class FakeTimeline:
    def __init__(self, tracks: dict[int, list[FakeItem]]) -> None:
        self.tracks = tracks

    def GetName(self) -> str:
        return "DZsqH7auhjt_textplus_full"

    def GetUniqueId(self) -> str:
        return "source-id"


class FakeController:
    @staticmethod
    def get_track_count(timeline: FakeTimeline, track_type: str) -> int:
        assert track_type == "video"
        return max(timeline.tracks, default=0)

    @staticmethod
    def get_track_items(
        timeline: FakeTimeline,
        track_type: str,
        track_index: int,
    ) -> list[FakeItem]:
        assert track_type == "video"
        return timeline.tracks.get(track_index, [])

    @staticmethod
    def timeline_item_name(item: FakeItem) -> str:
        return item.name

    @staticmethod
    def timeline_item_unique_id(item: FakeItem) -> str:
        return item.unique_id

    @staticmethod
    def timeline_item_start(item: FakeItem) -> int:
        return item.start

    @staticmethod
    def timeline_item_end(item: FakeItem) -> int:
        return item.end


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (root / ".agent" / "state").mkdir(parents=True)
    (root / ".agent" / "state" / "latest_accepted.json").write_text(
        '{"accepted": true}\n',
        encoding="utf-8",
    )
    for relative in publisher.SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n", encoding="utf-8")
    return root


def write_terminal_run(
    root: Path,
    run_id: str,
    runtime_report: dict[str, Any],
    state: str,
) -> None:
    report_dir = root / ".agent" / "reports" / validator.TASK_ID / run_id
    report_dir.mkdir(parents=True)
    queue = root / ".agent" / "commands"
    for name in ("pending", "running", "completed", "failed"):
        (queue / name).mkdir(parents=True, exist_ok=True)

    command = {
        "task_id": validator.TASK_ID,
        "mode": validator.MODE,
        "run_id": run_id,
        "accepted_state_sha256": validator.raw_sha256(
            root / ".agent" / "state" / "latest_accepted.json"
        ),
    }
    command_path = queue / state / f"{validator.TASK_ID}_{run_id}.json"
    command_path.write_text(
        json.dumps(command, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "probe_command.json").write_text(
        json.dumps(command, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "publication_receipt.json").write_text(
        json.dumps(
            {
                "task_id": validator.TASK_ID,
                "run_id": run_id,
                "command_sha256": validator.raw_sha256(command_path),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "report.json").write_text(
        json.dumps(runtime_report, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "status.json").write_text(
        '{"running": false}\n',
        encoding="utf-8",
    )
    (report_dir / "run.log").write_text("terminal\n", encoding="utf-8")


def passing_runtime_report(run_id: str) -> dict[str, Any]:
    return {
        "task_id": validator.TASK_ID,
        "mode": validator.MODE,
        "run_id": run_id,
        "ok": True,
        "carrier_backend": "fusion_composition_explicit_textplus",
        "source_contract_verified_count": 5,
        "edit_page_active": True,
        "protected_caption_count_before": 116,
        "provisioning": {
            "creation": {
                "returned_truthy": True,
                "new_item_count": 1,
                "detected_by": "returned_object_exact_range",
            }
        },
        "text_readback_ok": True,
        "modifier_connected": True,
        "frame_0_readback_ok": True,
        "frame_3_readback_ok": True,
        "temporary_timeline_deleted": True,
        "original_timeline_restored": True,
        "original_page_restored": True,
        "protected_source_unchanged": True,
        "accepted_state_unchanged": True,
        "save_call_count": 2,
        "failures": [],
    }


def test_task_boundary_is_v2() -> None:
    assert runtime.TASK_ID.endswith("_V2")
    assert publisher.TASK_ID == runtime.TASK_ID == validator.TASK_ID
    assert publisher.MODE == runtime.MODE == validator.MODE


def test_runtime_uses_populated_duplicate_and_exact_production_helper() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    assert 'PROTECTED_SOURCE_TIMELINE = "DZsqH7auhjt_textplus_full"' in source
    assert '"DuplicateTimeline"' in source
    assert '"OpenPage", "edit"' in source
    assert "apply_subtitle_track_guard" in source
    assert "provision_textplus_fusion_composition" in source
    assert "InsertFusionTitleIntoTimeline" not in source
    assert "AppendToTimeline" not in source


def test_runtime_persists_provisioning_before_rejecting_failure() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    write_at = source.index('report_dir / "probe_provisioning.json"')
    reject_at = source.index(
        'raise RuntimeError(\n'
        '                "fusion_composition_provisioning:"'
    )
    assert write_at < reject_at


def test_runtime_proves_two_keyframes_and_persistent_reacquisition() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    assert "CENTER_FRAME_0" in source
    assert "CENTER_FRAME_3" in source
    assert '"Center",\n            0,' in source
    assert '"Center",\n            3,' in source
    assert '"GetCurrentProject"' in source
    assert '"reacquire_probe_item"' in source


def test_runtime_cleanup_protects_source_and_accepted_state() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    assert "protected_source_unchanged" in source
    assert '"DeleteTimelines"' in source
    assert "accepted_state_unchanged" in source
    assert '"failure_cleanup"' in source


def test_source_caption_snapshot_is_stable_and_filtered() -> None:
    timeline = FakeTimeline(
        {
            3: [
                FakeItem("VC_TEXTPLUS_0002_sub_002", "b", 20, 25),
                FakeItem("unrelated", "x", 1, 2),
                FakeItem("VC_TEXTPLUS_0001_sub_001", "a", 10, 20),
            ]
        }
    )
    snapshot = runtime.source_caption_snapshot(FakeController, timeline)
    assert snapshot["caption_count"] == 2
    assert [row["name"] for row in snapshot["rows"]] == [
        "VC_TEXTPLUS_0001_sub_001",
        "VC_TEXTPLUS_0002_sub_002",
    ]
    assert snapshot["rows"][0]["duration"] == 10
    assert snapshot["rows"][0]["fusion_comp_count"] == 1


def test_lock_guard_requires_only_target_video_track_unlocked() -> None:
    assert runtime.lock_guard_ok(
        {
            "lock_snapshot_during": {
                "video": {1: True, 2: True, 5: False},
                "audio": {1: True},
            }
        },
        5,
    )
    assert not runtime.lock_guard_ok(
        {
            "lock_snapshot_during": {
                "video": {1: False, 5: False},
                "audio": {1: True},
            }
        },
        5,
    )


def test_publisher_uses_normalized_source_hashes_and_one_workspace_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_repo(tmp_path)
    monkeypatch.setattr(
        publisher,
        "run_id_now",
        lambda: "20260805T120000000000Z_0123456789abcdef0123456789abcdef",
    )
    receipt = publisher.publish(root)
    command = json.loads(
        (
            root
            / ".agent"
            / "reports"
            / publisher.TASK_ID
            / receipt["run_id"]
            / "probe_command.json"
        ).read_text(encoding="utf-8")
    )
    assert command["source_contract"]["algorithm"] == (
        "sha256_text_lf_normalized"
    )
    assert set(command["source_contract"]["hashes"]) == set(
        publisher.SOURCE_PATHS
    )
    assert command["probe"]["source_timeline"] == (
        "DZsqH7auhjt_textplus_full"
    )
    assert command["probe"]["target_track"] == 5
    assert command["probe"]["workspace_invocations"] == 1


def test_publisher_rejects_active_command(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    pending = root / ".agent" / "commands" / "pending"
    pending.mkdir(parents=True)
    (pending / "other.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="active_command"):
        publisher.publish(root)


def test_validator_accepts_complete_pass(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    run_id = "run-pass"
    runtime_report = passing_runtime_report(run_id)
    write_terminal_run(root, run_id, runtime_report, "completed")
    report_dir = root / ".agent" / "reports" / validator.TASK_ID / run_id
    for name in validator.REQUIRED_SUCCESS_ARTIFACTS:
        path = report_dir / name
        if not path.exists():
            path.write_text("{}\n", encoding="utf-8")
    result = validator.validate(
        root,
        run_id,
        timeout_seconds=0,
        poll_seconds=0,
    )
    assert result["ok"] is True
    assert result["production_call_returned_item"] is True
    assert result["new_item_count"] == 1


def test_validator_reports_terminal_runtime_failure_without_missing_artifact_noise(
    tmp_path: Path,
) -> None:
    root = make_repo(tmp_path)
    run_id = "run-fail"
    runtime_report = passing_runtime_report(run_id)
    runtime_report.update(
        {
            "ok": False,
            "provisioning": {
                "creation": {
                    "returned_truthy": False,
                    "new_item_count": 0,
                },
                "errors": [
                    "InsertFusionCompositionIntoTimeline created no detectable item."
                ],
            },
            "failures": [
                "RuntimeError: fusion_composition_provisioning:no_item"
            ],
        }
    )
    write_terminal_run(root, run_id, runtime_report, "failed")
    result = validator.validate(
        root,
        run_id,
        timeout_seconds=0,
        poll_seconds=0,
    )
    assert result["ok"] is False
    assert "command_state:failed" in result["failures"]
    assert any(
        value.startswith("runtime:RuntimeError:")
        for value in result["failures"]
    )
    assert not any(
        value.startswith("artifact:") for value in result["failures"]
    )


def test_validator_rejects_changed_accepted_state(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    run_id = "run-state-change"
    runtime_report = passing_runtime_report(run_id)
    write_terminal_run(root, run_id, runtime_report, "completed")
    report_dir = root / ".agent" / "reports" / validator.TASK_ID / run_id
    for name in validator.REQUIRED_SUCCESS_ARTIFACTS:
        path = report_dir / name
        if not path.exists():
            path.write_text("{}\n", encoding="utf-8")
    (root / ".agent" / "state" / "latest_accepted.json").write_text(
        '{"accepted": false}\n',
        encoding="utf-8",
    )
    result = validator.validate(
        root,
        run_id,
        timeout_seconds=0,
        poll_seconds=0,
    )
    assert result["ok"] is False
    assert "check:accepted_state_disk" in result["failures"]
