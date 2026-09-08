from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_textplus_carrier_probe.py"
PREPARE_PATH = ROOT / "scripts" / "davinci" / "prepare_step_3D_textplus_carrier_probe.py"
VALIDATE_PATH = ROOT / "scripts" / "davinci" / "validate_step_3D_textplus_carrier_probe.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load(MODULE_PATH, "probe_module")
prepare = load(PREPARE_PATH, "prepare_module")
validate = load(VALIDATE_PATH, "validate_module")


class FakeInput:
    def __init__(self):
        self.values = {}
        self.connected = None

    def __getitem__(self, frame):
        return self.values.get(frame)

    def __setitem__(self, frame, value):
        self.values[frame] = value

    def GetConnectedOutput(self):
        return self.connected


class FakeTextTool:
    def __init__(self):
        self.values = {"StyledText": "", "Center": [0.5, 0.5]}
        self.inputs = {"Center": FakeInput()}

    def SetInput(self, name, value, frame=None):
        if frame is None:
            self.values[name] = value
        else:
            self.inputs.setdefault(name, FakeInput()).values[frame] = value
        return True

    def GetInput(self, name, frame=None):
        if frame is not None and name in self.inputs and frame in self.inputs[name].values:
            return self.inputs[name].values[frame]
        return self.values.get(name)

    def GetInputList(self):
        return self.inputs


class FakeComp:
    pass


class FakeItem:
    def __init__(self, name, start, end, track=1):
        self.name = name
        self.start = start
        self.end = end
        self.track = track
        self.comp = FakeComp()
        self.text_tool = FakeTextTool()

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetTrackTypeAndIndex(self):
        return ["video", self.track]


class FakeTimeline:
    def __init__(self, name, unique_id):
        self.name = name
        self.unique_id = unique_id
        self.items = {1: []}

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.unique_id

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, track_index):
        return list(self.items.get(track_index, [])) if track_type == "video" else []

    def GetSetting(self, name):
        return "24"

    def GetStartFrame(self):
        return 0


class FakeMediaPool:
    def __init__(self, project, delete_ok=True):
        self.project = project
        self.delete_ok = delete_ok

    def CreateEmptyTimeline(self, name):
        timeline = FakeTimeline(name, f"uid-{name}")
        self.project.timelines.append(timeline)
        self.project.current = timeline
        return timeline

    def DeleteTimelines(self, timelines):
        if not self.delete_ok:
            return False
        for timeline in timelines:
            if timeline in self.project.timelines:
                self.project.timelines.remove(timeline)
        return True


class FakeProject:
    def __init__(self, delete_ok=True):
        self.original = FakeTimeline("ORIGINAL", "uid-original")
        self.timelines = [self.original]
        self.current = self.original
        self.media_pool = FakeMediaPool(self, delete_ok=delete_ok)

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index):
        return self.timelines[index - 1]

    def GetCurrentTimeline(self):
        return self.current

    def SetCurrentTimeline(self, timeline):
        if timeline not in self.timelines:
            return False
        self.current = timeline
        return True

    def GetMediaPool(self):
        return self.media_pool

    def GetSetting(self, name):
        return "24"


class FakeProjectManager:
    def __init__(self, project):
        self.project = project
        self.save_count = 0

    def GetCurrentProject(self):
        return self.project

    def SaveProject(self):
        self.save_count += 1
        return True


class FakeResolve:
    def __init__(self, project):
        self.pm = FakeProjectManager(project)

    def GetProjectManager(self):
        return self.pm


class FakeController:
    def __init__(self, provision_ok=True, readback_text=None):
        self.provision_ok = provision_ok
        self.readback_text = readback_text

    def provision_textplus_fusion_composition(self, timeline, start_frame, end_frame, fps, target_track, generated_name):
        if not self.provision_ok:
            return None, {"ok": False, "backend": "fusion_composition_explicit_textplus"}
        item = FakeItem(generated_name, start_frame, end_frame, target_track)
        timeline.items.setdefault(target_track, []).append(item)
        return item, {"ok": True, "backend": "fusion_composition_explicit_textplus"}

    def get_or_create_existing_title_text_tool(self, item, allow_add_fusion_comp=False):
        return item.comp, item.text_tool, {"ok": True}

    def set_fusion_input_best_effort(self, tool, name, value):
        tool.SetInput(name, value)
        return {"ok": True}

    def try_read_fusion_input(self, tool, name):
        value = tool.GetInput(name)
        if name == "StyledText" and self.readback_text is not None:
            value = self.readback_text
        return {"ok": True, "value": value}

    def fusion_input_values_equivalent(self, expected, actual, tolerance=1e-5):
        return expected == actual

    def timeline_item_name(self, item):
        return item.name

    def timeline_item_start(self, item):
        return item.start

    def timeline_item_end(self, item):
        return item.end

    def timeline_item_track_info(self, item):
        return {"track_type": "video", "track_index": item.track}


class FakeAnimation:
    def ensure_modifier(self, comp, tool, input_name):
        tool.inputs[input_name].connected = object()
        return {"ok": True, "created": True}

    def write_key(self, tool, input_name, frame, expected):
        tool.inputs[input_name][frame] = expected
        return {"ok": True}

    def read_input(self, tool, input_name, frame):
        return tool.inputs[input_name][frame]

    def find_input(self, tool, input_name):
        return tool.inputs[input_name]

    def connected_output(self, input_object):
        return input_object.GetConnectedOutput()

    def values_match(self, input_name, actual, expected):
        return actual == expected


def make_root(tmp_path: Path):
    root = tmp_path
    for relative in (
        probe.MODULE_RELATIVE_PATH,
        probe.CONTROLLER_RELATIVE_PATH,
        probe.ANIMATION_RELATIVE_PATH,
        probe.BRIDGE_RELATIVE_PATH,
        probe.ACCEPTED_STATE_RELATIVE_PATH,
        "AGENTS.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    return root


def make_command(root: Path, run_id="run-1"):
    report_dir = root / ".agent" / "reports" / probe.TASK_ID / run_id
    return {
        "task_id": probe.TASK_ID,
        "mode": probe.MODE,
        "run_id": run_id,
        "artifacts_dir": str(report_dir.relative_to(root)),
        "accepted_state_sha256": probe.raw_sha256(root / probe.ACCEPTED_STATE_RELATIVE_PATH),
        "source_contract": {
            "version": 1,
            "algorithm": probe.SOURCE_HASH_ALGORITHM,
            "hashes": {
                relative: probe.normalized_sha256(root / relative)
                for relative in (
                    probe.MODULE_RELATIVE_PATH,
                    probe.CONTROLLER_RELATIVE_PATH,
                    probe.ANIMATION_RELATIVE_PATH,
                    probe.BRIDGE_RELATIVE_PATH,
                )
            },
        },
        "probe": {
            "timeline_name": "VC_STEP3D_TEXTPLUS_PROBE_ABC",
            "item_name": "VC_STEP3D_TEXTPLUS_ITEM_ABC",
        },
    }


def run_probe(monkeypatch, tmp_path, controller=None, delete_ok=True):
    root = make_root(tmp_path)
    project = FakeProject(delete_ok=delete_ok)
    resolve = FakeResolve(project)
    controller = controller or FakeController()
    animation = FakeAnimation()
    monkeypatch.setattr(probe, "repository_root", lambda: root)
    monkeypatch.setattr(probe, "load_runtime_helpers", lambda _root: (controller, animation))
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    command = make_command(root)
    result = probe.run(resolve, {"run_id": "run-1", "command": command})
    return result, root, resolve, project


def test_probe_success_persists_reacquires_and_cleans(monkeypatch, tmp_path):
    result, root, resolve, project = run_probe(monkeypatch, tmp_path)
    assert result["ok"] is True
    assert result["carrier_backend"] == "fusion_composition_explicit_textplus"
    assert result["text_readback_ok"] is True
    assert result["modifier_connected"] is True
    assert result["keyframe_readback_ok"] is True
    assert result["temporary_timeline_deleted"] is True
    assert result["original_timeline_restored"] is True
    assert result["save_call_count"] == 2
    assert resolve.pm.save_count == 2
    assert [timeline.name for timeline in project.timelines] == ["ORIGINAL"]
    report_dir = root / ".agent" / "reports" / probe.TASK_ID / "run-1"
    assert (report_dir / "probe_creation.json").is_file()
    assert (report_dir / "probe_persistent_readback.json").is_file()
    assert (report_dir / "probe_cleanup.json").is_file()


def test_probe_provision_failure_deletes_temporary_timeline(monkeypatch, tmp_path):
    result, _root, resolve, project = run_probe(
        monkeypatch,
        tmp_path,
        controller=FakeController(provision_ok=False),
    )
    assert result["ok"] is False
    assert any("fusion_composition_provisioning" in value for value in result["failures"])
    assert result["temporary_timeline_deleted"] is True
    assert [timeline.name for timeline in project.timelines] == ["ORIGINAL"]
    assert resolve.pm.save_count == 1


def test_probe_readback_failure_cleans_up(monkeypatch, tmp_path):
    result, _root, _resolve, project = run_probe(
        monkeypatch,
        tmp_path,
        controller=FakeController(readback_text="wrong"),
    )
    assert result["ok"] is False
    assert result["temporary_timeline_deleted"] is True
    assert [timeline.name for timeline in project.timelines] == ["ORIGINAL"]


def test_probe_delete_failure_is_hard_failure(monkeypatch, tmp_path):
    result, _root, _resolve, project = run_probe(monkeypatch, tmp_path, delete_ok=False)
    assert result["ok"] is False
    assert result["temporary_timeline_deleted"] is False
    assert len(project.timelines) == 2


def test_source_contract_rejects_changed_dependency(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    command = make_command(root)
    (root / probe.CONTROLLER_RELATIVE_PATH).write_text("changed", encoding="utf-8")
    monkeypatch.setattr(probe, "repository_root", lambda: root)
    with pytest.raises(ValueError, match="source_contract_hash"):
        probe.run(FakeResolve(FakeProject()), {"run_id": "run-1", "command": command})


def test_runtime_helper_import_restores_autorun_environment(monkeypatch, tmp_path):
    root = tmp_path
    controller = root / probe.CONTROLLER_RELATIVE_PATH
    animation = root / probe.ANIMATION_RELATIVE_PATH
    controller.parent.mkdir(parents=True, exist_ok=True)
    animation.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text(
        "\n".join(f"def {name}(*a, **k): pass" for name in (
            "provision_textplus_fusion_composition",
            "get_or_create_existing_title_text_tool",
            "set_fusion_input_best_effort",
            "try_read_fusion_input",
            "fusion_input_values_equivalent",
            "timeline_item_name",
            "timeline_item_start",
            "timeline_item_end",
            "timeline_item_track_info",
        )),
        encoding="utf-8",
    )
    animation.write_text(
        "import os\nAUTORUN = os.environ.get('VC_DISABLE_WORKSPACE_AUTORUN')\n" +
        "\n".join(f"def {name}(*a, **k): pass" for name in (
            "ensure_modifier", "write_key", "read_input", "find_input", "connected_output", "values_match"
        )),
        encoding="utf-8",
    )
    monkeypatch.setenv("VC_DISABLE_WORKSPACE_AUTORUN", "original")
    _controller, loaded_animation = probe.load_runtime_helpers(root)
    assert loaded_animation.AUTORUN == "1"
    assert probe.os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] == "original"


def test_publisher_creates_one_fresh_command(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    module_source = ROOT / probe.MODULE_RELATIVE_PATH
    target = root / probe.MODULE_RELATIVE_PATH
    target.write_bytes(module_source.read_bytes())
    monkeypatch.setattr(prepare, "run_id_now", lambda: "RID")
    receipt = prepare.publish(root)
    command_path = root / ".agent" / "commands" / "pending" / f"{prepare.TASK_ID}_RID.json"
    assert command_path.is_file()
    command = json.loads(command_path.read_text(encoding="utf-8"))
    assert command["probe"]["cleanup_required"] is True
    assert command["source_contract"]["algorithm"] == prepare.SOURCE_HASH_ALGORITHM
    assert receipt["command_sha256"] == prepare.raw_sha256(command_path)



def test_publisher_allows_existing_luna_preflight_report_directory(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    module_source = ROOT / probe.MODULE_RELATIVE_PATH
    target = root / probe.MODULE_RELATIVE_PATH
    target.write_bytes(module_source.read_bytes())
    preflight = root / ".agent" / "reports" / prepare.TASK_ID / "PREFLIGHT_20260805T000000Z"
    preflight.mkdir(parents=True)
    (preflight / "FINAL_REPORT.md").write_text("preflight", encoding="utf-8")
    monkeypatch.setattr(prepare, "run_id_now", lambda: "RID2")
    receipt = prepare.publish(root)
    assert receipt["run_id"] == "RID2"
    assert (root / ".agent" / "commands" / "pending" / f"{prepare.TASK_ID}_RID2.json").is_file()

def test_publisher_rejects_active_command(tmp_path):
    root = make_root(tmp_path)
    active = root / ".agent" / "commands" / "pending" / "active.json"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="active_command"):
        prepare.publish(root)


def terminal_fixture(tmp_path: Path, state: str, runtime_ok: bool):
    root = tmp_path
    run_id = "RID"
    report_dir = root / ".agent" / "reports" / validate.TASK_ID / run_id
    report_dir.mkdir(parents=True)
    command = {
        "task_id": validate.TASK_ID,
        "mode": validate.MODE,
        "run_id": run_id,
        "accepted_state_sha256": "",
    }
    queue_path = root / ".agent" / "commands" / state / validate.command_name(run_id)
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(json.dumps(command), encoding="utf-8")
    accepted = root / ".agent" / "state" / "latest_accepted.json"
    accepted.parent.mkdir(parents=True)
    accepted.write_text("{}", encoding="utf-8")
    command["accepted_state_sha256"] = validate.raw_sha256(accepted)
    queue_path.write_text(json.dumps(command), encoding="utf-8")
    (report_dir / "probe_command.json").write_text(json.dumps(command), encoding="utf-8")
    (report_dir / "publication_receipt.json").write_text(
        json.dumps({"run_id": run_id, "command_sha256": validate.raw_sha256(queue_path)}),
        encoding="utf-8",
    )
    runtime = {
        "ok": runtime_ok,
        "task_id": validate.TASK_ID,
        "mode": validate.MODE,
        "run_id": run_id,
        "carrier_backend": "fusion_composition_explicit_textplus",
        "source_contract_verified_count": 4,
        "text_readback_ok": True,
        "modifier_connected": True,
        "keyframe_readback_ok": True,
        "temporary_timeline_deleted": True,
        "original_timeline_restored": True,
        "save_call_count": 2,
        "accepted_state_unchanged": True,
        "failures": [] if runtime_ok else ["live_failure"],
    }
    (report_dir / "report.json").write_text(json.dumps(runtime), encoding="utf-8")
    (report_dir / "status.json").write_text(json.dumps({"running": False, "ok": runtime_ok}), encoding="utf-8")
    if runtime_ok:
        for name in validate.REQUIRED_SUCCESS_ARTIFACTS:
            path = report_dir / name
            if not path.exists():
                path.write_text("{}" if path.suffix == ".json" else "ok", encoding="utf-8")
    return root, run_id


def test_validator_accepts_completed_probe(tmp_path):
    root, run_id = terminal_fixture(tmp_path, "completed", True)
    result = validate.validate(root, run_id, timeout_seconds=0.0, poll_seconds=0.01)
    assert result["ok"] is True
    assert (root / ".agent" / "reports" / validate.TASK_ID / run_id / "probe_validation.json").is_file()


def test_validator_reports_runtime_failure_before_success_artifact_checks(tmp_path):
    root, run_id = terminal_fixture(tmp_path, "failed", False)
    result = validate.validate(root, run_id, timeout_seconds=0.0, poll_seconds=0.01)
    assert result["ok"] is False
    assert any("runtime:live_failure" in value for value in result["failures"])
    assert not any(value.startswith("artifact:") for value in result["failures"])


def test_validator_times_out_while_command_is_running(tmp_path):
    root, run_id = terminal_fixture(tmp_path, "running", False)
    with pytest.raises(TimeoutError, match="command_not_terminal"):
        validate.validate(root, run_id, timeout_seconds=0.0, poll_seconds=0.01)
