from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_visual_instance_correction.py"
PUBLISHER_PATH = ROOT / "scripts" / "davinci" / "prepare_step_3D_visual_instance_correction.py"
VALIDATOR_PATH = ROOT / "scripts" / "davinci" / "validate_step_3D_visual_instance_correction.py"
WORD_TRACKS_PATH = ROOT / "data" / "DZsqH7auhjt" / "analysis" / "DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json"
LIFECYCLE_PATH = ROOT / "data" / "DZsqH7auhjt" / "analysis" / "DZsqH7auhjt_caption_lifecycle_redetection_step_3D.json"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load(MODULE_PATH, "visual_instance_correction")
publisher = load(PUBLISHER_PATH, "visual_instance_correction_publisher")
validator = load(VALIDATOR_PATH, "visual_instance_correction_validator")


def test_contract_keeps_only_proven_runtime_route():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert probe.TASK_ID == "DZSQH7AUHJT_STEP_3D_VISUAL_INSTANCE_CORRECTION_V3"
    assert publisher.TASK_ID == probe.TASK_ID
    assert validator.TASK_ID == probe.TASK_ID
    assert "append_carriers_by_return_order" in source
    assert "import_source_comp" in source
    assert "InsertFusionCompositionIntoTimeline" not in source
    assert "InsertFusionTitleIntoTimeline" not in source
    assert '"AddFusionComp"' not in source


def test_source_tracks_merge_two_transcript_cues_into_one_visual_instance():
    document = probe.load_json(WORD_TRACKS_PATH)
    plan = probe.select_they_visual_instance(document, [430, 452])
    assert plan["ok"] is True
    assert plan["source_cue_ids"] == ["sub_051", "sub_054"]
    assert plan["style_source_cue_id"] == "sub_051"
    assert plan["visual_window"] == [428, 452]
    assert plan["selected_group_size"] == 2
    assert len(plan["position_keys"]) == 24
    assert len(plan["opacity_keys"]) == 24
    assert plan["stabilization"]["ok"] is True


def test_visual_instance_is_above_come_at_shared_frame_433():
    plan = probe.select_they_visual_instance(probe.load_json(WORD_TRACKS_PATH), [430, 452])
    key = next(row for row in plan["position_keys"] if row["timeline_frame"] == 433)
    assert key["local_frame"] == 5
    assert key["value"][1] > probe.COME_HOLD_CENTER[1] + 0.02
    assert key["value"][0] < probe.COME_HOLD_CENTER[0]


def test_visual_instance_merger_rejects_same_word_at_different_geometry():
    left = {
        "text": "they",
        "geometry": {
            "first_visible_frame": 1,
            "last_visible_frame": 2,
            "median_bbox_width_px": 200,
            "median_bbox_height_px": 60,
        },
        "frame_observations": [{"position": [0.2, 0.3]}],
    }
    right = {
        "text": "THEY",
        "geometry": {
            "first_visible_frame": 3,
            "last_visible_frame": 4,
            "median_bbox_width_px": 200,
            "median_bbox_height_px": 60,
        },
        "frame_observations": [{"position": [0.7, 0.8]}],
    }
    assert probe.same_visual_instance(left, right) is False


def test_come_exit_is_derived_from_redetection_and_moves_right_while_decaying():
    plan = probe.build_come_exit_plan(probe.load_json(LIFECYCLE_PATH))
    assert plan["ok"] is True
    assert plan["exit_window"] == [448, 452]
    assert [row["timeline_frame"] for row in plan["center_keys"]] == [447, 448, 449, 450, 451]
    assert plan["center_keys"][-1]["value"][0] > plan["center_keys"][0]["value"][0] + 0.05
    assert plan["opacity_keys"][-1]["factor"] < 0.6
    assert plan["opacity_keys"][0]["factor"] == 1.0


def test_come_exit_geometry_matches_known_hold_center():
    plan = probe.build_come_exit_plan(probe.load_json(LIFECYCLE_PATH))
    first_exit = plan["center_keys"][1]["value"]
    assert first_exit[0] > 0.52
    assert abs(first_exit[1] - probe.COME_HOLD_CENTER[1]) < 0.002


class FakeOutput:
    pass


class FakeInput:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.connected = None

    def __getitem__(self, frame):
        return self.values.get(frame)

    def __setitem__(self, frame, value):
        self.values[frame] = value

    def GetConnectedOutput(self):
        return self.connected

    def GetAttrs(self):
        return {}


class FakeTool:
    def __init__(self):
        self.inputs = {
            "Center": FakeInput({0: {1: 0.5, 2: 0.6, 3: 0.0}}),
            "Opacity1": FakeInput({0: 1.0}),
            "Opacity2": FakeInput({0: 1.0}),
            "Opacity3": FakeInput({0: 0.85}),
            "StyledText": FakeInput({0: "THEY"}),
            "GlobalOut": FakeInput({0: 3}),
            "Size": FakeInput({0: 0.116030765278}),
            "Red1": FakeInput({0: 0.701961}),
            "Green1": FakeInput({0: 0.443137}),
            "Blue1": FakeInput({0: 0.376471}),
            "Enabled2": FakeInput({0: 1.0}),
            "Thickness2": FakeInput({0: 0.0566037736}),
            "Enabled3": FakeInput({0: 1.0}),
        }

    def FindInput(self, name):
        return self.inputs.get(name)

    def GetInputList(self):
        return self.inputs

    def GetInput(self, name, frame):
        value = self.inputs[name].values.get(frame)
        if value is None and frame != 0:
            earlier = [key for key in self.inputs[name].values if key <= frame]
            value = self.inputs[name].values[max(earlier)] if earlier else None
        return value

    def SetInput(self, name, value, frame=None):
        self.inputs[name].values[0 if frame is None else frame] = value
        return True

    def AddModifier(self, name, _modifier):
        self.inputs[name].connected = FakeOutput()
        return True


def test_keyframe_helpers_create_expected_modifiers_and_values():
    tool = FakeTool()
    center = probe.apply_center_series(tool, [
        {"timeline_frame": 10, "local_frame": 2, "value": [0.4, 0.7]},
    ])
    opacity = probe.apply_opacity_series(tool, [
        {"timeline_frame": 10, "local_frame": 2, "factor": 0.5},
    ])
    assert center["ok"] is True
    assert opacity["ok"] is True
    assert probe.base.point_matches(tool.GetInput("Center", 2), [0.4, 0.7])
    assert tool.GetInput("Opacity1", 2) == 0.5
    assert tool.GetInput("Opacity2", 2) == 0.5
    assert tool.GetInput("Opacity3", 2) == 0.425



def test_opacity_series_skips_absent_textplus_layer_inputs():
    tool = FakeTool()
    del tool.inputs["Opacity2"]

    opacity = probe.apply_opacity_series(tool, [
        {"timeline_frame": 10, "local_frame": 2, "factor": 0.5},
    ])

    assert opacity["ok"] is True
    assert opacity["available_inputs"] == ["Opacity1", "Opacity3"]
    assert opacity["skipped_inputs"] == ["Opacity2"]
    assert [row["input"] for row in opacity["rows"]] == ["Opacity1", "Opacity3"]
    assert tool.GetInput("Opacity1", 2) == 0.5
    assert tool.GetInput("Opacity3", 2) == 0.425


def test_they_stabilization_removes_hold_jitter_and_opacity_shimmer():
    plan = probe.select_they_visual_instance(probe.load_json(WORD_TRACKS_PATH), [430, 452])
    positions = [
        row["value"] for row in plan["position_keys"]
        if probe.THEY_HOLD_START <= row["timeline_frame"] < probe.THEY_HOLD_END
    ]
    factors = [
        row["factor"] for row in plan["opacity_keys"]
        if probe.THEY_HOLD_START <= row["timeline_frame"] < probe.THEY_HOLD_END
    ]
    assert positions and all(value == positions[0] for value in positions)
    assert factors and all(value == 1.0 for value in factors)
    entrance = [row["factor"] for row in plan["opacity_keys"] if row["timeline_frame"] < probe.THEY_HOLD_START]
    exit_values = [row["factor"] for row in plan["opacity_keys"] if row["timeline_frame"] >= probe.THEY_HOLD_END]
    assert entrance == sorted(entrance)
    assert exit_values == sorted(exit_values, reverse=True)


def test_come_source_frame_style_doubles_size_and_removes_rejected_effects():
    style = probe.COME_SOURCE_FRAME_STYLE
    assert style["Size"] == 0.232061530556
    assert style["Red1"] == 39.0 / 255.0
    assert style["Green1"] == 43.0 / 255.0
    assert style["Blue1"] == 48.0 / 255.0
    assert style["Enabled2"] == 0.0
    assert style["Thickness2"] == 0.0
    assert style["Enabled3"] == 0.0


def test_static_style_application_and_readback_are_exact():
    tool = FakeTool()
    applied = probe.apply_static_inputs(tool, probe.COME_SOURCE_FRAME_STYLE)
    readback = probe.static_input_readback(tool, probe.COME_SOURCE_FRAME_STYLE)
    assert applied["ok"] is True
    assert readback["ok"] is True
    assert tool.GetInput("Size", 0) == probe.COME_SOURCE_FRAME_STYLE["Size"]
    assert tool.GetInput("Enabled2", 0) == 0.0
    assert tool.GetInput("Enabled3", 0) == 0.0

def test_publisher_has_complete_seven_file_contract(tmp_path, monkeypatch):
    root = tmp_path
    (root / "AGENTS.md").write_text("rules", encoding="utf-8")
    for relative in publisher.SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    accepted = root / publisher.ACCEPTED_STATE
    accepted.parent.mkdir(parents=True, exist_ok=True)
    accepted.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(publisher, "run_id_now", lambda: "RUN_123456789012")

    receipt = publisher.publish(root)
    command = json.loads(Path(receipt["command_path"]).read_text(encoding="utf-8"))

    assert len(command["source_contract"]["hashes"]) == 7
    assert command["probe"]["required_visual_instance_aliases"] == ["sub_051", "sub_054"]
    assert command["probe"]["required_style_source"] == "sub_051"
    assert command["probe"]["they_motion_policy"] == "dense_monotonic_entrance_exit_fixed_source_median_hold"
    assert command["probe"]["come_style_source"] == "source_frame_430_non_occluded_glyph_sample"
    assert command["probe"]["review_window"] == [428, 452]
    assert command["probe"]["timeline_name"].endswith("123456789012")


def test_validator_requires_visual_merge_and_exit_evidence():
    required = set(validator.REQUIRED_SUCCESS_ARTIFACTS)
    assert "visual_instance_plan.json" in required
    assert "correction_application.json" in required
    assert "persistent_readback.json" in required
