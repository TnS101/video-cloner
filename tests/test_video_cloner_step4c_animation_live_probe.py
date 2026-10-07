from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


probe = load(ROOT / "resolve_workspace/modules/video_cloner_step4c_animation_live_probe.py", "step4c_probe")
publisher = load(ROOT / "scripts/davinci/prepare_video_cloner_step4c_animation_live_probe.py", "step4c_publisher")
native = load(ROOT / "resolve_workspace/modules/step_3D_native_textplus_title_probe.py", "step4c_native")


class Input:
    def __init__(self):
        self.values = {}
        self.connected = None

    def __getitem__(self, frame): return self.values.get(frame)
    def GetConnectedOutput(self): return self.connected


class Modifier:
    def __init__(self, kind, input_object):
        self.kind = kind
        self.input = input_object

    def GetAttrs(self): return {"TOOLS_RegID": self.kind}
    def GetKeyFrames(self): return dict(self.input.values)


class Output:
    def __init__(self, modifier): self.modifier = modifier
    def GetTool(self): return self.modifier
    def GetAttrs(self): return {"OUTS_Name": self.modifier.kind}


class Tool:
    def __init__(self, regid="TextPlus", name=None):
        self.regid, self.Name = regid, name or regid
        self.inputs = {"Center": Input(), "Size": Input(), "StyledText": Input(), "Input": Input()}
    def FindInput(self, name): return self.inputs.get(name)
    def GetAttrs(self): return {"TOOLS_RegID": self.regid, "TOOLS_Name": self.Name}
    def SetInput(self, name, value): self.inputs[name].values[0] = value
    def GetInput(self, name, frame=0): return self.inputs[name].values.get(frame)


class Comp:
    def __init__(self, textplus_count=1, connected=True):
        self.text_tools = [Tool("TextPlus", f"Text{index + 1}") for index in range(textplus_count)]
        self.tool = self.text_tools[0] if self.text_tools else None
        self.media_out = Tool("MediaOut", "MediaOut1")
        if connected and self.tool is not None:
            self.media_out.FindInput("Input").connected = Output(self.tool)

    def GetToolList(self, _selected=False, regid=None):
        tools = {tool.Name: tool for tool in [*self.text_tools, self.media_out]}
        return tools if regid is None else {name: tool for name, tool in tools.items() if tool.regid == regid}


class Item:
    count = 0

    def __init__(self, name, start, end, track, textplus=False, textplus_count=1, connected=True, fusion_count=None):
        Item.count += 1
        self.name, self.start, self.end, self.track = name, start, end, track
        self.uid = f"item-{Item.count}"
        self.comp = Comp(textplus_count, connected) if textplus else None
        self.fusion_count = fusion_count

    def GetName(self): return self.name
    def SetName(self, name): self.name = name; return True
    def GetUniqueId(self): return self.uid
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.end - self.start
    def GetFusionCompCount(self): return self.fusion_count if self.fusion_count is not None else (1 if self.comp else 0)
    def GetFusionCompByIndex(self, index): return self.comp if index == 1 else None
    def GetMediaPoolItem(self): return None
    def GetProperty(self): return {}


class Timeline:
    def __init__(self, name, tracks=None):
        self.name, self.uid = name, f"timeline-{name}"
        self.tracks = {int(key): list(value) for key, value in (tracks or {1: []}).items()}
        self.project = None
        self.locks = {}
        self.current_frame = 0

    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetTrackCount(self, kind): return max(self.tracks, default=0) if kind == "video" else 0
    def GetItemListInTrack(self, kind, index): return list(self.tracks.get(index, [])) if kind == "video" else []
    def GetStartFrame(self): return 0
    def GetEndFrame(self): return max((item.end for items in self.tracks.values() for item in items), default=1000)
    def GetStartTimecode(self): return "01:00:00:00"
    def GetCurrentTimecode(self):
        seconds, frame = divmod(self.current_frame, 24)
        return f"01:00:{seconds:02d}:{frame:02d}"
    def GetSetting(self, name): return "24" if name in ("timelineFrameRate", "timelinePlaybackFrameRate") else ""
    def SetCurrentTimecode(self, value):
        parts = value.replace(";", ":").split(":")
        self.current_frame = int(parts[-2]) * 24 + int(parts[-1])
        return True
    def SetTrackLock(self, kind, index, locked): self.locks[(kind, index)] = locked; return True
    def AddTrack(self, kind): self.tracks.setdefault(max(self.tracks, default=0) + 1, []); return kind == "video"
    def DeleteClips(self, items, _ripple):
        for track in self.tracks:
            self.tracks[track] = [item for item in self.tracks[track] if item not in items]
        return True
    def DuplicateTimeline(self, name):
        clone = Timeline(name, {
            track: [Item(item.name, item.start, item.end, track, textplus=item.comp is not None) for item in items]
            for track, items in self.tracks.items()
        })
        clone.project = self.project
        self.project.timelines.append(clone)
        return clone


class MediaPool:
    pass


class Project:
    def __init__(self, name="New Project 1", include_disposable=False):
        reel1 = Timeline(probe.REEL1, {1: [Item("base1", 0, 900, 1)], 3: [Item("VC_TEXTPLUS_0001_sub_001", 10, 20, 3, True)]})
        reel2 = Timeline(probe.REEL2, {1: [Item("base2", 0, 854, 1)]})
        self.name, self.timelines, self.current, self.media_pool = name, [reel1, reel2], reel1, MediaPool()
        if include_disposable:
            self.timelines.append(Timeline("VC_STEP4C_ANIMATION_PROBE_test", {1: [], 2: [], 3: []}))
        for timeline in self.timelines: timeline.project = self

    def GetName(self): return self.name
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]
    def GetCurrentTimeline(self): return self.current
    def SetCurrentTimeline(self, timeline): self.current = timeline; return True
    def GetMediaPool(self): return self.media_pool


class Manager:
    def __init__(self, project, mutate_on_save=False): self.project, self.save_calls, self.mutate_on_save = project, 0, mutate_on_save
    def GetCurrentProject(self): return self.project
    def SaveProject(self):
        self.save_calls += 1
        if self.mutate_on_save:
            self.project.timelines[1].tracks[1][0].name = "changed"
        return True


class Resolve:
    def __init__(self, project, mutate_on_save=False): self.manager, self.page = Manager(project, mutate_on_save), "edit"
    def GetProjectManager(self): return self.manager
    def GetCurrentPage(self): return self.page
    def OpenPage(self, page): self.page = page; return True


class Animation:
    def __init__(self): self.calls = []
    def find_input(self, tool, name): return tool.FindInput(name)
    def connected_output(self, input_object): return input_object.GetConnectedOutput() if input_object else None
    def read_input(self, tool, name, frame): return tool.FindInput(name).values.get(frame)
    def normalize_value(self, _name, value): return value
    def values_match(self, _name, actual, expected): return actual == expected
    def apply_authorized_animation(self, _comp, tool, payload, duration):
        self.calls.append(copy.deepcopy(payload))
        if payload is None:
            return {"ok": True, "selected": False, "modified": False, "keyframes_written": 0, "readback": []}
        name = payload["property"]
        input_object = tool.FindInput(name)
        expected = {row["frame"]: row["value"] for row in payload["keyframes"]}
        if input_object.connected is not None and input_object.values == expected:
            return {"ok": True, "modified": False, "already_correct": True, "keyframes_written": 0, "readback": []}
        kind = "Path" if name == "Center" else "BezierSpline"
        input_object.connected = Output(Modifier(kind, input_object))
        input_object.values = expected
        return {"ok": True, "modified": True, "keyframes_written": len(expected), "readback": [{"matched": True} for _ in expected]}
    def input_targets_are_correct(self, tool, name, targets):
        item = tool.FindInput(name)
        return item.connected is not None and all(item.values[row["local_frame"]] == row["expected"] for row in targets)


class Carrier:
    def __init__(self, delta_count=1, returned_mismatch=False, track=None, start_offset=0,
                 duration_offset=0, textplus_count=1, connected=True, fusion_count=None):
        self.delta_count = delta_count
        self.returned_mismatch = returned_mismatch
        self.track = track
        self.start_offset = start_offset
        self.duration_offset = duration_offset
        self.textplus_count = textplus_count
        self.connected = connected
        self.fusion_count = fusion_count

    def provision_textplus_media_carrier(self, project, timeline, video_items, start_frame,
                                         end_frame, target_track, generated_name):
        del project, video_items
        track = self.track or target_track
        start = start_frame + self.start_offset
        end = start + (end_frame - start_frame) + self.duration_offset
        created = []
        for index in range(self.delta_count):
            item = Item(generated_name if index == 0 else generated_name + "_extra", start, end, track,
                        textplus=True, textplus_count=self.textplus_count,
                        connected=self.connected, fusion_count=self.fusion_count)
            timeline.tracks.setdefault(track, []).append(item)
            created.append(item)
        returned = Item("fallback", start, end, track, textplus=True) if self.returned_mismatch else (created[0] if created else Item("fallback", start, end, track, textplus=True))
        return returned, {"ok": True, "backend": "media_pool_video_carrier_with_fusion_textplus"}

    @staticmethod
    def list_fusion_tools(comp): return list(comp.GetToolList(False).values())
    @staticmethod
    def fusion_tool_regid(tool): return tool.GetAttrs()["TOOLS_RegID"]
    @staticmethod
    def fusion_tool_name(tool): return tool.GetAttrs()["TOOLS_Name"]


class Snapshots:
    @staticmethod
    def timeline_snapshot(timeline):
        rows = [(track, item.name, item.uid, item.start, item.end) for track in sorted(timeline.tracks) for item in timeline.tracks[track]]
        value = {"name": timeline.name, "uid": timeline.uid, "rows": rows}
        value["signature"] = json.dumps(value, sort_keys=True)
        return value


def command(name="VC_STEP4C_ANIMATION_PROBE_test"):
    return {"task_id": probe.TASK_ID, "mode": probe.MODE, "run_id": "run", "source_contract": {},
            "payload": {"expected_project": probe.PROJECT_NAME, "protected_timelines": [probe.REEL1, probe.REEL2],
                        "disposable_timeline_name": name, "mutation_permitted": True, "cleanup_permitted": False}}


def run_fake(monkeypatch, project=None, mutate_on_save=False, command_value=None):
    project = project or Project()
    animation = Animation()
    monkeypatch.setattr(probe, "queue_preflight", lambda _root, _run: {"running_count": 1, "pending_count": 0})
    monkeypatch.setattr(probe, "repository_root", lambda: ROOT)
    monkeypatch.setattr(native, "verify_source_contract", lambda _root, _command: {"verified_count": 5})
    result = probe.execute(Resolve(project, mutate_on_save), {"command": command_value or command(), "run_id": "run"}, (native, animation, Snapshots, Carrier()))
    return result, animation, project


def existing_full_command(timeline, **overrides):
    value = command(timeline.name)
    value["payload"].update({
        "reuse_existing_owned_disposable": True,
        "ownership_required": "EXISTING_NEWLY_CREATED",
        "expected_disposable_uid": timeline.uid,
    })
    value["payload"].update(overrides)
    return value


def insertion_context(carrier=None, project=None):
    project = project or Project(include_disposable=True)
    timeline = project.timelines[-1]
    while timeline.GetTrackCount("video") < probe.TARGET_TRACK:
        timeline.AddTrack("video")
    animation = Animation()
    return project, timeline, animation, carrier or Carrier()


def insert(carrier=None, project=None):
    project, timeline, animation, carrier = insertion_context(carrier, project)
    result = probe._insert_title(native, animation, carrier, Resolve(project), project, timeline,
                                 probe.STATIC_PROOF_FRAME, probe.STATIC_PROOF_NAME)
    return result, project, timeline


def test_full_probe_contract_dispatches_exact_payloads_and_proves_persistence_idempotency_static_and_protection(monkeypatch):
    result, animation, _project = run_fake(monkeypatch)
    assert result["ok"] is True
    assert result["ownership"] == "NEWLY_CREATED"
    assert animation.calls == [None, probe.CENTER_PAYLOAD, probe.SIZE_PAYLOAD, probe.CENTER_PAYLOAD, probe.SIZE_PAYLOAD]
    assert result["persistent_readback"]["Center"]["targets_ok"] is True
    assert result["persistent_readback"]["Size"]["targets_ok"] is True
    assert result["persistent_readback"]["Center"]["readback"] == [
        {"frame": 0, "expected": [-0.0106, 0.0565], "actual": [-0.0106, 0.0565], "matched": True},
        {"frame": 2, "expected": [0.0, 0.0], "actual": [0.0, 0.0], "matched": True},
    ]
    assert [row["frame"] for row in result["persistent_readback"]["Size"]["readback"]] == [0, 7]
    assert result["second_application"]["Center"]["keyframes_written"] == 0
    assert result["second_application"]["Size"]["keyframes_written"] == 0
    assert result["static"]["before"] == result["static"]["after"]
    assert result["protected_unchanged"] == {probe.REEL1: True, probe.REEL2: True}
    assert result["mutation_counts"]["project_saves"] == 1


def test_existing_owned_full_probe_requires_exact_identity_and_never_duplicates(monkeypatch):
    project = Project(include_disposable=True)
    disposable = project.timelines[-1]
    disposable.tracks[3].append(Item(probe.STATIC_PROOF_NAME, 100, 112, 3, True))
    project.timelines[0].DuplicateTimeline = lambda _name: (_ for _ in ()).throw(AssertionError("duplicate"))
    result, animation, project = run_fake(monkeypatch, project, command_value=existing_full_command(disposable))
    assert result["ok"] is True
    assert result["ownership"] == "EXISTING_NEWLY_CREATED"
    assert result["existing_target_preflight"]["identity"] == {"name": disposable.name, "unique_id": disposable.uid}
    assert result["mutation_counts"]["timeline_create"] == 0
    assert len(project.timelines) == 3
    assert next(item for item in disposable.tracks[3] if item.name == probe.STATIC_PROOF_NAME).uid
    assert [item.start for item in disposable.tracks[3] if item.name in probe.ITEM_NAMES] == list(probe.EXISTING_TARGET_FRAMES)
    assert animation.calls == [None, probe.CENTER_PAYLOAD, probe.SIZE_PAYLOAD, probe.CENTER_PAYLOAD, probe.SIZE_PAYLOAD]
    assert result["protected_unchanged"] == {probe.REEL1: True, probe.REEL2: True}


def test_existing_owned_full_probe_fails_closed_on_identity_or_ownership_mismatch(monkeypatch):
    cases = [
        {"expected_disposable_uid": "wrong"},
        {"ownership_required": "PREEXISTING_COMPATIBLE"},
        {"ownership_required": None},
    ]
    for overrides in cases:
        project = Project(include_disposable=True)
        disposable = project.timelines[-1]
        result, animation, project = run_fake(monkeypatch, project, command_value=existing_full_command(disposable, **overrides))
        assert result["ok"] is False
        assert result["mutation_counts"]["timeline_create"] == result["mutation_counts"]["title_insert"] == 0
        assert animation.calls == []
        assert len(project.timelines) == 3


def test_existing_owned_full_probe_rejects_wrong_name_project_protected_or_ambiguous_target(monkeypatch):
    project = Project(include_disposable=True)
    disposable = project.timelines[-1]
    missing = existing_full_command(disposable)
    missing["payload"]["disposable_timeline_name"] = "VC_STEP4C_ANIMATION_PROBE_missing"
    result, animation, _project = run_fake(monkeypatch, project, command_value=missing)
    assert result["ok"] is False and animation.calls == []

    wrong_project = Project(name="Wrong Project", include_disposable=True)
    result, animation, _project = run_fake(monkeypatch, wrong_project, command_value=existing_full_command(wrong_project.timelines[-1]))
    assert result["ok"] is False and animation.calls == []

    for protected in (probe.REEL1, probe.REEL2):
        protected_project = Project()
        timeline = next(row for row in protected_project.timelines if row.name == protected)
        result, animation, _project = run_fake(monkeypatch, protected_project, command_value=existing_full_command(timeline))
        assert result["ok"] is False and animation.calls == []

    ambiguous = Project(include_disposable=True)
    original = ambiguous.timelines[-1]
    duplicate = Timeline(original.name, {1: [], 2: [], 3: []})
    duplicate.uid = original.uid
    duplicate.project = ambiguous
    ambiguous.timelines.append(duplicate)
    result, animation, _project = run_fake(monkeypatch, ambiguous, command_value=existing_full_command(original))
    assert result["ok"] is False and animation.calls == []


def test_preflight_project_failure_performs_zero_mutation(monkeypatch):
    project = Project(name="wrong")
    result, animation, project = run_fake(monkeypatch, project)
    assert result["ok"] is False
    assert len(project.timelines) == 2
    assert animation.calls == []


def test_ambiguous_ownership_performs_zero_animation_mutation(monkeypatch):
    project = Project(include_disposable=True)
    result, animation, project = run_fake(monkeypatch, project)
    assert result["ok"] is False
    assert len(project.timelines) == 3
    assert animation.calls == []


def test_protected_state_change_fails_probe(monkeypatch):
    result, _animation, _project = run_fake(monkeypatch, mutate_on_save=True)
    assert result["ok"] is False
    assert "protected_state_changed" in result["failures"][0]


def test_queue_preflight_requires_only_matching_running_command(tmp_path):
    queue = tmp_path / ".agent/commands"
    (queue / "pending").mkdir(parents=True)
    (queue / "running").mkdir()
    running = queue / "running/cmd.json"
    running.write_text(json.dumps({"run_id": "run", "task_id": probe.TASK_ID}), encoding="utf-8")
    assert probe.queue_preflight(tmp_path, "run")["running_count"] == 1
    (queue / "pending/other.json").write_text("{}", encoding="utf-8")
    try:
        probe.queue_preflight(tmp_path, "run")
    except RuntimeError as exc:
        assert "queue_state" in str(exc)
    else:
        raise AssertionError("unsafe queue accepted")


def test_publisher_registers_exact_bridge_module_without_executing(tmp_path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    for relative in publisher.SOURCES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    monkeypatch.setattr(publisher.uuid, "uuid4", lambda: type("U", (), {"hex": "1234567890abcdef"})())
    receipt = publisher.publish(tmp_path)
    queued = json.loads(Path(receipt["command_path"]).read_text(encoding="utf-8"))
    assert queued["module"] == publisher.MODULE
    assert queued["payload"]["ownership_required"] == "NEWLY_CREATED"
    assert queued["payload"]["cleanup_permitted"] is False
    assert queued["payload"]["protected_timelines"] == [probe.REEL1, probe.REEL2]
    assert queued["source_contract"]["hashes"][publisher.MODULE]


def test_publisher_builds_exact_existing_owned_future_command_in_isolated_queue(tmp_path):
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    for relative in publisher.SOURCES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    receipt = publisher.publish(
        tmp_path,
        "VC_STEP4C_ANIMATION_PROBE_a46ae408cd86",
        "6646e520-e119-4610-aa85-ba27641d483c",
    )
    payload = json.loads(Path(receipt["command_path"]).read_text(encoding="utf-8"))["payload"]
    assert payload == {
        "expected_project": probe.PROJECT_NAME,
        "protected_timelines": [probe.REEL1, probe.REEL2],
        "disposable_timeline_name": "VC_STEP4C_ANIMATION_PROBE_a46ae408cd86",
        "ownership_required": "EXISTING_NEWLY_CREATED",
        "mutation_permitted": True,
        "cleanup_permitted": False,
        "workspace_invocations": 1,
        "expected_disposable_uid": "6646e520-e119-4610-aa85-ba27641d483c",
        "reuse_existing_owned_disposable": True,
    }


def test_dependency_loader_disables_adapter_workspace_autorun(tmp_path, monkeypatch):
    loaded = []

    def fake_load(name, _path):
        loaded.append((name, os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN")))
        return name

    monkeypatch.setattr(probe, "_load", fake_load)
    monkeypatch.delenv("VC_DISABLE_WORKSPACE_AUTORUN", raising=False)
    assert probe.load_dependencies(tmp_path) == ("vc_step4c_native", "vc_step4c_animation", "vc_step4c_snapshot", "vc_step4c_carrier")
    assert loaded[0] == ("vc_step4c_animation", "1")
    assert os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") is None


def test_carrier_insertion_requires_unique_delta_and_matching_returned_uid():
    result, _project, _timeline = insert()
    assert result["delta_uids"] == [result["returned_uid"]]
    assert result["summary"]["track_index"] == probe.TARGET_TRACK
    assert result["summary"]["start"] == probe.STATIC_PROOF_FRAME
    assert result["summary"]["duration"] == probe.TITLE_DURATION
    assert result["fusion_comp_count"] == result["textplus_node_count"] == 1
    assert result["output_connection"]["source_regid"] == "TextPlus"
    assert result["text_readback"] == probe.STATIC_PROOF_NAME


def test_static_only_existing_disposable_inserts_once_without_animation(monkeypatch):
    project = Project(include_disposable=True)
    disposable = project.timelines[-1]
    animation = Animation()
    static_command = command(disposable.name)
    static_command["payload"].update({
        "static_insertion_only": True,
        "ownership_required": "EXISTING_NEWLY_CREATED",
        "expected_disposable_uid": disposable.uid,
    })
    monkeypatch.setattr(probe, "queue_preflight", lambda _root, _run: {"running_count": 1, "pending_count": 0})
    monkeypatch.setattr(probe, "repository_root", lambda: ROOT)
    monkeypatch.setattr(native, "verify_source_contract", lambda _root, _command: {"verified_count": 5})
    result = probe.execute(Resolve(project), {"command": static_command, "run_id": "run"},
                           (native, animation, Snapshots, Carrier()))
    assert result["classification"] == "STEP4C_STATIC_INSERTION_PASS"
    assert result["mutation_counts"]["title_insert"] == 1
    assert result["mutation_counts"]["animation_keyframes_first"] == 0
    assert result["mutation_counts"]["animation_keyframes_second"] == 0
    assert animation.calls == []
    assert result["protected_unchanged"] == {probe.REEL1: True, probe.REEL2: True}


def test_zero_delta_cannot_use_helper_fallback_item():
    try:
        insert(Carrier(delta_count=0))
    except RuntimeError as exc:
        assert "title_ownership" in str(exc) and "delta=0" in str(exc)
    else:
        raise AssertionError("helper fallback bypassed ownership")


def test_multiple_delta_fails_closed():
    try:
        insert(Carrier(delta_count=2))
    except RuntimeError as exc:
        assert "title_ownership" in str(exc) and "delta=2" in str(exc)
    else:
        raise AssertionError("multiple-item delta accepted")


def test_returned_and_delta_uid_mismatch_fails_closed():
    try:
        insert(Carrier(returned_mismatch=True))
    except RuntimeError as exc:
        assert "title_ownership" in str(exc)
    else:
        raise AssertionError("returned/delta mismatch accepted")


def test_wrong_current_timeline_fails_before_provisioning():
    project = Project(include_disposable=True)
    project.SetCurrentTimeline = lambda _timeline: True
    carrier = Carrier()
    try:
        insert(carrier, project)
    except RuntimeError as exc:
        assert "title_timeline_identity" in str(exc)
        assert carrier.delta_count == 1
        assert not project.timelines[-1].tracks.get(probe.TARGET_TRACK)
    else:
        raise AssertionError("wrong current timeline accepted")


def test_wrong_track_start_or_duration_fails_closed():
    for carrier in (Carrier(track=2), Carrier(start_offset=1), Carrier(duration_offset=1)):
        try:
            insert(carrier)
        except RuntimeError as exc:
            assert "title_placement_or_timeline" in str(exc)
        else:
            raise AssertionError("wrong placement accepted")


def test_ambiguous_fusion_or_textplus_identity_fails_closed():
    for carrier in (Carrier(fusion_count=2), Carrier(textplus_count=2), Carrier(connected=False)):
        try:
            insert(carrier)
        except RuntimeError as exc:
            assert "title_" in str(exc)
        else:
            raise AssertionError("ambiguous Fusion identity accepted")
