from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_module("scripts/davinci/prepare_advanced_transition_flash_application_v1.py", "flash_prepare")
runtime = load_module("resolve_workspace/modules/advanced_transition_flash_application_v1.py", "flash_runtime")
validator = load_module("scripts/davinci/validate_advanced_transition_flash_application_v1.py", "flash_validator")


class FakeCaptionItem:
    def __init__(self, name: str, start: int):
        self._name = name
        self._start = start

    def GetName(self):
        return self._name

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._start + 4

    def GetDuration(self):
        return 4


class FakeCaptionTimeline:
    def __init__(self, names):
        self._items = [FakeCaptionItem(name, index * 5) for index, name in enumerate(names)]

    def GetTrackCount(self, kind):
        return 1 if kind == "video" else 0

    def GetItemListInTrack(self, kind, index):
        if kind == "video" and index == 1:
            return list(self._items)
        return []


def test_caption_snapshot_accepts_current_97_plus_17_mixed_prefix_topology():
    names = [f"VC_TEXTPLUS_{index:04d}_sub_{index:03d}" for index in range(1, 98)]
    names += [f"VC_VISUAL_FIRST_FULL_{index:04d}_vf_{index:02d}" for index in range(1, 18)]
    snapshot = runtime.caption_snapshot(FakeCaptionTimeline(names))
    assert snapshot["count"] == 114
    assert len(snapshot["rows"]) == 114
    assert sum(row["name"].startswith("VC_TEXTPLUS_") for row in snapshot["rows"]) == 97
    assert sum(row["name"].startswith("VC_VISUAL_FIRST_FULL_") for row in snapshot["rows"]) == 17


class FakeAppendItem:
    def __init__(self, uid: str, start: int, duration: int = 4, name: str = "DZsqH7auhjt_proxy.mp4"):
        self._uid = uid
        self._start = start
        self._duration = duration
        self._name = name

    def GetUniqueId(self):
        return self._uid

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._start + self._duration

    def GetDuration(self):
        return self._duration

    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name
        return True


class FakeAppendTimeline:
    def __init__(self, target_track: int):
        self.target_track = target_track
        self.items = []

    def GetTrackCount(self, kind):
        return self.target_track if kind == "video" else 0

    def GetItemListInTrack(self, kind, index):
        if kind == "video" and index == self.target_track:
            return list(self.items)
        return []


class FakeAppendMediaPool:
    def __init__(self, timeline):
        self.timeline = timeline
        self.last_clip_infos = []

    def AppendToTimeline(self, clip_infos):
        self.last_clip_infos = [dict(row) for row in clip_infos]
        returned_proxies = []
        for index, row in enumerate(clip_infos, start=1):
            start = int(row["recordFrame"])
            # Match the proven Resolve 21 contract: endFrame is an exclusive
            # source endpoint, so source duration is endFrame - startFrame.
            duration = int(row["endFrame"]) - int(row["startFrame"])
            actual = FakeAppendItem(f"actual-{index}", start, duration)
            self.timeline.items.append(actual)
            # Model the Resolve 21 runtime failure: the API return object is a
            # different proxy from the object exposed by GetItemListInTrack.
            returned_proxies.append(FakeAppendItem("", start, duration))
        return returned_proxies


def test_append_flash_carriers_prefers_detected_timeline_items_over_returned_proxies():
    target_track = 26
    timeline = FakeAppendTimeline(target_track)
    media_pool = FakeAppendMediaPool(timeline)
    flashes = [
        {"name": f"VC_FLASH_{index:03d}_frame_{cut:04d}", "start_frame": cut - 2, "duration_frames": 4}
        for index, cut in enumerate([96, 377, 426, 454, 758], start=1)
    ]
    result = runtime.append_flash_carriers(
        media_pool,
        timeline,
        {"media_pool_item": object(), "source_start": 0},
        flashes,
        target_track,
    )
    assert result["ok"] is True
    assert result["returned_count"] == 5
    assert result["detected_count"] == 5
    assert result["candidate_source"] == "detected_timeline_items"
    assert result["assigned_count"] == 5
    assert result["source_api_end_semantics"] == "exclusive"
    assert [row["startFrame"] for row in media_pool.last_clip_infos] == [0] * 5
    assert [row["endFrame"] for row in media_pool.last_clip_infos] == [4] * 5
    assert [row["requested_duration"] for row in result["requested_source_ranges"]] == [4] * 5
    assert [row["source_end_frame_api"] for row in result["requested_source_ranges"]] == [4] * 5
    assert [item.GetDuration() for item in timeline.items] == [4] * 5
    assert [item.GetName() for item in timeline.items] == [row["name"] for row in flashes]
    assert [row["track_index"] for row in result["candidate_rows"]] == [target_track] * 5


def test_fake_append_model_proves_end_frame_is_exclusive():
    timeline = FakeAppendTimeline(26)
    media_pool = FakeAppendMediaPool(timeline)
    returned = media_pool.AppendToTimeline([{
        "mediaPoolItem": object(),
        "startFrame": 0,
        "endFrame": 4,
        "mediaType": 1,
        "trackIndex": 26,
        "recordFrame": 94,
    }])
    assert len(returned) == 1
    assert len(timeline.items) == 1
    assert timeline.items[0].GetStart() == 94
    assert timeline.items[0].GetEnd() == 98
    assert timeline.items[0].GetDuration() == 4


def authority_fixture():
    rows = []
    for cut in prepare.EXPECTED_FLASH_FRAMES:
        rows.append({
            "transition_type": "flash_cut",
            "confidence": "high",
            "editor_actionable": True,
            "cut_frame": cut,
            "duration_frames": 4,
            "outgoing_frames": 2,
            "incoming_frames": 2,
            "placement": "at_cut",
            "handle_check": {"ok": True},
            "reasons": ["white-frame/luma spike near boundary"],
            "transition_strength": 0.75,
            "scores": {"white_ratio_max": 0.6, "luma_delta": 0.2},
        })
    rows.append({
        "transition_type": "hard_cut",
        "confidence": "medium",
        "editor_actionable": False,
        "cut_frame": 999,
    })
    return {"transitions": rows}


def test_build_plan_selects_exact_five_flash_events():
    plan = prepare.build_plan(authority_fixture())
    assert plan["flash_count"] == 5
    assert [row["cut_frame"] for row in plan["flashes"]] == [96, 377, 426, 454, 758]


def test_build_plan_uses_source_backed_four_frame_white_pulse():
    plan = prepare.build_plan(authority_fixture())
    for row in plan["flashes"]:
        assert row["duration_frames"] == 4
        assert row["start_frame"] == row["cut_frame"] - 2
        assert row["flash_color"] == [1.0, 1.0, 1.0]
        assert row["alpha_keyframes"] == [[0, 0.0], [2, 0.75], [3, 0.0]]


def test_build_plan_rejects_missing_authority_event():
    value = authority_fixture()
    value["transitions"] = value["transitions"][1:]
    try:
        prepare.build_plan(value)
    except ValueError as exc:
        assert "flash_authority_frames" in str(exc)
    else:
        raise AssertionError("missing flash event accepted")


def test_runtime_plan_validation_accepts_hashed_plan():
    plan = prepare.build_plan(authority_fixture())
    plan["transition_authority_sha256"] = "a" * 64
    plan["plan_sha256"] = runtime.canonical_sha256(plan)
    runtime.validate_plan(plan)


def test_runtime_plan_validation_rejects_peak_opacity_drift():
    plan = prepare.build_plan(authority_fixture())
    plan["transition_authority_sha256"] = "a" * 64
    plan["flashes"][0]["alpha_keyframes"][1][1] = 1.0
    plan["plan_sha256"] = runtime.canonical_sha256(plan)
    try:
        runtime.validate_plan(plan)
    except ValueError as exc:
        assert "plan_flash_contract" in str(exc)
    else:
        raise AssertionError("opacity drift accepted")


def synthetic_target():
    rows = []
    for index, cut in enumerate([96, 377, 426, 454, 758], start=1):
        rows.append({
            "name": f"VC_FLASH_{index:03d}_frame_{cut:04d}",
            "track_index": 5,
            "start": cut - 2,
            "end": cut + 2,
            "duration": 4,
            "fusion": {"ok": True},
            "contract_ok": True,
        })
    return {
        "caption_snapshot": {"count": 114, "sha256": "captions", "video_track_count": 5},
        "flash_snapshot": {"count": 5, "expected_count": 5, "track_index": 5, "rows": rows, "ok": True},
        "caption_count_ok": True,
        "caption_geometry_unchanged": True,
        "track_count_ok": True,
        "ok": True,
    }


def synthetic_report(mode: str):
    base = {
        "ok": True,
        "task_id": validator.TASK_ID,
        "run_id": "run",
        "run_mode": mode,
        "expected_textplus_count": 114,
        "expected_flash_count": 5,
        "source_timeline_unchanged": True,
        "target_after": synthetic_target(),
        "save_call_count": 1 if mode == "apply" else 0,
        "timeline_duplicate_count": 1 if mode == "apply" else 0,
        "video_track_add_count": 1 if mode == "apply" else 0,
        "flash_carrier_append_count": 5 if mode == "apply" else 0,
        "fusion_flash_configure_count": 5 if mode == "apply" else 0,
    }
    if mode == "apply":
        base.update({"persistent_readback_ok": True, "visual_approval_required": True})
    else:
        base.update({"idempotent": True, "visual_approval_required": False})
    return base


def test_validator_accepts_first_application_contract():
    result = validator.validate_report(synthetic_report("apply"), "apply")
    assert result["ok"] is True
    assert all(result["checks"].values())


def test_validator_accepts_zero_mutation_idempotency_contract():
    result = validator.validate_report(synthetic_report("idempotency"), "idempotency")
    assert result["ok"] is True
    assert all(result["checks"].values())


def test_validator_rejects_caption_geometry_regression():
    report = synthetic_report("apply")
    report["target_after"]["caption_geometry_unchanged"] = False
    result = validator.validate_report(report, "apply")
    assert result["ok"] is False
    assert result["checks"]["caption_geometry_unchanged"] is False


def test_flash_names_encode_source_cut_frames():
    plan = prepare.build_plan(authority_fixture())
    assert [row["name"] for row in plan["flashes"]] == [
        "VC_FLASH_001_frame_0096",
        "VC_FLASH_002_frame_0377",
        "VC_FLASH_003_frame_0426",
        "VC_FLASH_004_frame_0454",
        "VC_FLASH_005_frame_0758",
    ]


class FakeAnimInput:
    def __init__(self, static=0.0):
        self.static = float(static)
        self.keys = {}
        self.connected = None

    def GetConnectedOutput(self):
        return self.connected

    def __setitem__(self, frame, value):
        # Model the live R4 failure: an indexed assignment can be accepted by
        # the wrapper without creating animation until a modifier is connected.
        if self.connected is not None:
            self.keys[int(frame)] = float(value)

    def __getitem__(self, frame):
        return self.keys.get(int(frame), self.static)


class FakeAnimTool:
    def __init__(self):
        self.inputs = {
            "TopLeftAlpha": FakeAnimInput(0.0),
        }

    def FindInput(self, name):
        return self.inputs.get(name)

    def AddModifier(self, name, modifier_name):
        assert modifier_name == "BezierSpline"
        self.inputs[name].connected = object()
        return True

    def SetInput(self, name, value, frame=None):
        # Mirror the live Background behavior from R4: SetInput with a frame
        # does not provide the working keyframe path here.
        return False

    def GetInput(self, name, frame=None):
        inp = self.inputs[name]
        if frame is None:
            return inp.static
        return inp[int(frame)]


class FakeAnimComp:
    pass


def test_animated_scalar_requires_verified_keyframe_readback():
    tool = FakeAnimTool()
    result = runtime.write_animated_scalar(tool, "TopLeftAlpha", 2, 0.75)
    assert result["ok"] is False
    assert runtime.read_input(tool, "TopLeftAlpha", 2)["value"] == 0.0


def test_alpha_modifier_enables_verified_background_keyframes():
    tool = FakeAnimTool()
    modifier = runtime.ensure_bezier_modifier(FakeAnimComp(), tool, "TopLeftAlpha")
    assert modifier["ok"] is True
    assert modifier["created"] is True
    for frame, value in [(0, 0.0), (2, 0.75), (3, 0.0)]:
        write = runtime.write_animated_scalar(tool, "TopLeftAlpha", frame, value)
        assert write["ok"] is True
    assert runtime.read_input(tool, "TopLeftAlpha", 0)["value"] == 0.0
    assert runtime.read_input(tool, "TopLeftAlpha", 2)["value"] == 0.75
    assert runtime.read_input(tool, "TopLeftAlpha", 3)["value"] == 0.0
