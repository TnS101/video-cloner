from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_visual_first_resolve_pilot.py"
PUBLISHER_PATH = ROOT / "scripts" / "davinci" / "prepare_step_3D_visual_first_resolve_pilot.py"
VALIDATOR_PATH = ROOT / "scripts" / "davinci" / "validate_step_3D_visual_first_resolve_pilot.py"
REVIEW_PATH = ROOT / "scripts" / "analysis" / "build_step_3D_visual_first_resolve_pilot_review.py"
AUTHORITY_PATH = ROOT / "artifacts" / "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3" / "visual_authority_script_renderability_v3.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pilot = load("step3d_visual_first_resolve_pilot", MODULE_PATH)
publisher = load("step3d_visual_first_resolve_pilot_publisher", PUBLISHER_PATH)
validator = load("step3d_visual_first_resolve_pilot_validator", VALIDATOR_PATH)
review = load("step3d_visual_first_resolve_pilot_review", REVIEW_PATH)


def authority():
    return json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))


def test_task_identity_and_runtime_route_are_exact():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert pilot.TASK_ID == "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_RESOLVE_PILOT_V1"
    assert publisher.TASK_ID == pilot.TASK_ID
    assert validator.TASK_ID == pilot.TASK_ID
    assert "append_batch_by_placement" in source
    assert 'base.direct_call(item, "ImportFusionComp"' not in source  # import is routed through the proven helper
    assert "media.import_source_comp" in source
    assert "InsertFusionTitleIntoTimeline" not in source
    assert "InsertFusionCompositionIntoTimeline" not in source


def test_locked_authority_compiles_seven_groups_and_seventeen_tracks():
    rows = pilot.flatten_authority(authority(), ROOT)
    assert len(rows) == 17
    assert len({row["group_id"] for row in rows}) == 7
    assert [row["target_track"] for row in rows] == list(range(8, 25))
    assert len({row["target_name"] for row in rows}) == 17
    assert all(row["transcript_timing_promoted_to_authority"] is False for row in rows)


def test_visual_text_identity_and_persistence_are_not_transcript_timed():
    rows = {row["visual_token_id"]: row for row in pilot.flatten_authority(authority(), ROOT)}
    assert rows["vf_01_nineteen"]["display_text"] == "Nineteen"
    assert rows["vf_01_nineteen"]["source_cue_id"] == "sub_006"
    assert rows["vf_04_market"]["target_range"] == [464, 493]
    assert rows["vf_04_back"]["target_range"] == [476, 493]
    assert rows["vf_04_their"]["target_range"] == [482, 496]
    assert rows["vf_06_blocks"]["position_keys"][0]["source_top_origin_value"][0] > 0.60


def test_visual_only_decorations_use_reviewed_text_and_sibling_size_evidence():
    rows = {row["visual_token_id"]: row for row in pilot.flatten_authority(authority(), ROOT)}
    just = rows["vf_02_decorative_glyph"]
    glyph_i = rows["vf_05_decorative_glyph"]
    assert just["display_text"] == "Already"
    assert glyph_i["display_text"] == "I"
    assert just["source_cue_id"] is None and just["base_size_cue_id"] == "sub_018"
    assert glyph_i["source_cue_id"] is None and glyph_i["base_size_cue_id"] == "sub_076"
    assert just["font"]["font_family"] == "Gabriola"
    assert glyph_i["font"]["font_style"] == "Regular"


def test_heavy_font_class_resolves_to_existing_selected_font():
    rows = pilot.flatten_authority(authority(), ROOT)
    heavy = [row for row in rows if row["style_lock"]["font_class"] == "heavy_geometric_sans"]
    assert heavy
    assert all(row["font"]["font_family"] == "Clash Grotesk Variable" for row in heavy)
    assert all(row["font"]["font_style"] == "Bold" for row in heavy)


def test_top_origin_positions_are_converted_to_fusion_coordinates():
    assert pilot.fusion_center([0.25, 0.30]) == [0.25, 0.70]
    rows = {row["visual_token_id"]: row for row in pilot.flatten_authority(authority(), ROOT)}
    source = rows["vf_02_already"]["position_keys"][0]["source_top_origin_value"]
    actual = rows["vf_02_already"]["position_keys"][0]["value"]
    assert actual == [source[0], 1.0 - source[1]]


def test_comp_base_size_parser_supports_static_and_spline(tmp_path):
    static = tmp_path / "static.comp"
    static.write_text('Size = Input { Value = 0.125, },', encoding="utf-8")
    spline = tmp_path / "spline.comp"
    spline.write_text('Size = Input { SourceOp = "X" },\nX = BezierSpline { KeyFrames = { [0] = { 0.075, } } }', encoding="utf-8")
    assert pilot.parse_comp_base_size(static) == 0.125
    assert pilot.parse_comp_base_size(spline) == 0.075


def test_absolute_size_keys_are_anchored_to_source_comp_size():
    rows = {row["visual_token_id"]: row for row in pilot.flatten_authority(authority(), ROOT)}
    row = rows["vf_07_something"]
    assert row["base_size"] > 0.0
    assert all(abs(key["value"] - row["base_size"] * key["scale"]) < 1e-12 for key in row["size_keys"])


def test_review_format_prefers_mp4_h264():
    selection = pilot.select_review_video_format(
        {"QuickTime": "mov", "MP4": "mp4", "PNG": "png"},
        {
            "QuickTime": {"H.264": "H264"},
            "MP4": {"H.264 Native": "H264_Native", "H.265": "H265"},
            "PNG": {"RGB 16-bit": "RGB16"},
        },
    )
    assert selection["ok"] is True
    assert selection["selected"]["extension"] == "mp4"
    assert "H264" in selection["selected"]["codec"]


def test_render_settings_treat_output_overrides_as_optional(tmp_path):
    class FakeProject:
        def __init__(self):
            self.payloads = []

        def SetRenderSettings(self, payload):
            self.payloads.append(dict(payload))
            return "FormatWidth" not in payload and "ReplaceExistingFilesInPlace" not in payload

    project = FakeProject()
    settings = pilot.render_settings(
        tmp_path,
        "source_only",
        {"width": 540, "height": 960, "frame_rate": 24.0},
    )
    result = pilot.apply_render_settings(project, settings)

    assert result["ok"] is True
    assert all(row["accepted"] for row in result["required"])
    optional = {row["group"]: row for row in result["optional"]}
    assert optional["dimensions"]["accepted"] is False
    assert optional["replacement"]["accepted"] is False
    assert result["effective_settings"]["MarkIn"] == 176
    assert result["effective_settings"]["MarkOut"] == 692
    assert "FormatWidth" not in result["effective_settings"]
    assert "ReplaceExistingFilesInPlace" not in result["effective_settings"]


def test_render_configuration_falls_back_to_next_codec_when_required_settings_fail(tmp_path):
    class FakeProject:
        def __init__(self):
            self.codec = None

        def SetCurrentRenderFormatAndCodec(self, render_format, codec):
            self.codec = codec
            return True

        def SetCurrentRenderMode(self, mode):
            return mode == 1

        def SetRenderSettings(self, payload):
            if self.codec == "H264_NVIDIA" and "TargetDir" in payload:
                return False
            return True

    project = FakeProject()
    settings = pilot.render_settings(
        tmp_path,
        "generated_only",
        {"width": 540, "height": 960, "frame_rate": 24.0},
    )
    result = pilot.configure_review_render(
        project,
        settings,
        [
            {"format": "MP4", "codec": "H264_NVIDIA", "extension": "mp4"},
            {"format": "MP4", "codec": "H264", "extension": "mp4"},
        ],
    )

    assert result["ok"] is True
    assert result["selection"]["codec"] == "H264"
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["settings"]["failed_group"] == "destination"
    assert result["attempts"][1]["settings"]["ok"] is True


def test_review_sample_frames_cover_start_hold_and_exit():
    group = next(group for group in authority()["groups"] if group["group_id"] == "vf_group_07_something_motion")
    frames = review.sample_frames(group)
    assert frames[0] == 658
    assert frames[-1] == 691
    assert 666 in frames
    assert 684 in frames


def test_publisher_requires_locked_authority_and_three_render_modes(tmp_path, monkeypatch):
    root = tmp_path
    (root / "AGENTS.md").write_text("rules", encoding="utf-8")
    for relative in publisher.SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith("visual_authority_script_renderability_v3.json"):
            path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "semantic_sha256": "abc",
                        "summary": {
                            "group_count": 7,
                            "visual_token_count": 17,
                            "unresolved_component_count": 0,
                            "placeholder_count": 0,
                            "transcript_timing_promoted_count": 0,
                            "visual_text_correction_count": 1,
                            "provisional_script_font_candidate_count": 2,
                        },
                        "next_boundary": {
                            "resolve_action_allowed": True,
                            "scope": "seven_windows_only",
                            "full_rollout_allowed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
        elif relative.endswith("script_renderability_validation.json"):
            path.write_text('{"ok": true}', encoding="utf-8")
        else:
            path.write_text("x", encoding="utf-8")
    accepted = root / publisher.ACCEPTED_STATE
    accepted.parent.mkdir(parents=True, exist_ok=True)
    accepted.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(publisher, "run_id_now", lambda: "RUN_123456789012")
    receipt = publisher.publish(root)
    command = json.loads(Path(receipt["command_path"]).read_text(encoding="utf-8"))
    assert command["pilot"]["group_count"] == 7
    assert command["pilot"]["visual_token_count"] == 17
    assert command["pilot"]["render_modes"] == ["source_only", "generated_only", "alignment_overlay"]
    assert command["pilot"]["full_rollout_authorized"] is False
    assert command["pilot"]["visual_approval_required"] is True
    assert command["pilot"]["target_timeline_name"] == pilot.TARGET_TIMELINE_NAME


def test_validator_requires_runtime_and_review_evidence():
    required = set(validator.REQUIRED_RUNTIME_ARTIFACTS)
    assert "authority_plan.json" in required
    assert "pilot_application.json" in required
    assert "review_renders.json" in required
    assert "persistent_readback.json" in required
    assert validator.REQUIRED_REVIEW_ARTIFACTS == (
        "visual_review/review_manifest.json",
        "visual_review/VISUAL_REVIEW.md",
    )


def test_static_input_matcher_supports_font_and_style_strings(monkeypatch):
    class FakeTextTool:
        def __init__(self):
            self.values = {}

        def SetInput(self, name, value):
            self.values[name] = value
            return True

    tool = FakeTextTool()
    monkeypatch.setattr(pilot.base, "read_input", lambda target, name, frame=0: target.values.get(name))
    assert pilot.set_static_input(tool, "Font", "Clash Grotesk Variable")["ok"] is True
    assert pilot.set_static_input(tool, "Style", "Bold")["ok"] is True
    assert pilot.set_static_input(tool, "StyledText", "Nineteen")["ok"] is True
    assert pilot.set_static_input(tool, "Opacity3", 0.18)["ok"] is True


def test_static_policy_disables_outline_without_writing_clamped_or_missing_inputs():
    plan = {
        "visual_token_id": "vf_01_nineteen",
        "display_text": "Nineteen",
        "font": {"font_family": "Clash Grotesk Variable", "font_style": "Bold"},
        "style_lock": {
            "fill": "#15171A",
            "stroke": {"enabled": False},
            "shadow": {"enabled": True, "color": "#E8E8E8", "opacity": 0.18},
        },
    }
    policy = pilot.static_input_policy(plan)
    assert policy["stroke_disabled"] is True
    assert policy["shadow_enabled"] is True
    assert policy["values"]["Enabled2"] == 0.0
    assert "Thickness2" not in policy["values"]
    assert "Opacity2" not in policy["values"]
    assert policy["skipped_inputs"] == ["Thickness2", "Opacity2"]
    assert policy["values"]["Opacity3"] == 0.18


def test_apply_token_arms_size_and_opacity_modifiers(monkeypatch):
    comp = object()
    text_tool = object()
    calls = []

    monkeypatch.setattr(pilot.base, "get_comp", lambda item: comp)
    monkeypatch.setattr(pilot.base, "get_text_tool", lambda actual_comp: text_tool)
    monkeypatch.setattr(
        pilot.visual,
        "extend_comp_range",
        lambda actual_comp, actual_tool, last_frame: {"ok": True, "requested_last_frame": last_frame},
    )
    captured_static = {}

    def set_static_inputs(actual_tool, values):
        captured_static.update(values)
        return {"ok": True, "rows": []}

    monkeypatch.setattr(pilot, "set_static_inputs", set_static_inputs)
    monkeypatch.setattr(pilot.visual, "apply_center_series", lambda actual_tool, keys: {"ok": True, "keys": list(keys)})

    def ensure_modifier(actual_tool, input_name, modifier_name):
        calls.append(("modifier", input_name, modifier_name))
        return {"ok": True, "modifier": modifier_name}

    def write_series(actual_tool, input_name, keys, value_key):
        calls.append(("series", input_name, value_key))
        return {"ok": True, "input": input_name, "rows": list(keys)}

    def apply_opacity(actual_tool, keys):
        calls.append(("opacity", len(keys)))
        return {"ok": True, "rows": []}

    monkeypatch.setattr(pilot.visual, "ensure_modifier", ensure_modifier)
    monkeypatch.setattr(pilot, "write_scalar_series", write_series)
    monkeypatch.setattr(pilot.visual, "apply_opacity_series", apply_opacity)

    plan = {
        "target_range": [176, 191],
        "display_text": "Nineteen",
        "font": {"font_family": "Clash Grotesk Variable", "font_style": "Bold"},
        "style_lock": {
            "fill": "#15171A",
            "stroke": {"enabled": False},
            "shadow": {"enabled": True, "color": "#E8E8E8", "opacity": 0.18},
        },
        "position_keys": [{"local_frame": 0, "value": [0.5, 0.625]}],
        "size_keys": [{"local_frame": 0, "value": 0.08}],
        "opacity_keys": [{"local_frame": 0, "factor": 0.25}],
    }

    result = pilot.apply_token(object(), plan)
    assert result["ok"] is True
    assert ("modifier", "Size", "BezierSpline") in calls
    assert ("series", "Size", "value") in calls
    assert ("opacity", 1) in calls
    assert captured_static["Enabled2"] == 0.0
    assert "Thickness2" not in captured_static
    assert "Opacity2" not in captured_static
    assert result["static_policy"]["skipped_inputs"] == ["Thickness2", "Opacity2"]


def test_locked_authority_has_no_enabled_stroke_tokens():
    rows = pilot.flatten_authority(authority(), ROOT)
    assert len(rows) == 17
    assert all(row["style_lock"]["stroke"]["enabled"] is False for row in rows)


def test_application_failure_stage_reports_exact_substage():
    assert pilot.application_failure_stage(
        {
            "comp_range": {"ok": True},
            "static": {"ok": False},
            "center": {"ok": True},
            "size_modifier": {"ok": True},
            "size": {"ok": True},
            "opacity": {"ok": True},
        }
    ) == "static"
    assert pilot.application_failure_stage(
        {
            "comp_range": {"ok": True},
            "static": {"ok": True},
            "center": {"ok": True},
            "size_modifier": {"ok": False},
            "size": {"ok": False},
            "opacity": {"ok": True},
        }
    ) == "size_modifier"


def test_publisher_allows_exact_five_known_failed_runs_for_repair(tmp_path, monkeypatch):
    root = tmp_path
    (root / "AGENTS.md").write_text("rules", encoding="utf-8")
    for relative in publisher.SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith("visual_authority_script_renderability_v3.json"):
            path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "semantic_sha256": "abc",
                        "summary": {
                            "group_count": 7,
                            "visual_token_count": 17,
                            "unresolved_component_count": 0,
                            "placeholder_count": 0,
                            "transcript_timing_promoted_count": 0,
                            "visual_text_correction_count": 1,
                            "provisional_script_font_candidate_count": 2,
                        },
                        "next_boundary": {
                            "resolve_action_allowed": True,
                            "scope": "seven_windows_only",
                            "full_rollout_allowed": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
        elif relative.endswith("script_renderability_validation.json"):
            path.write_text('{"ok": true}', encoding="utf-8")
        else:
            path.write_text("x", encoding="utf-8")

    accepted = root / publisher.ACCEPTED_STATE
    accepted.parent.mkdir(parents=True, exist_ok=True)
    accepted.write_text("{}", encoding="utf-8")

    failed_dir = root / ".agent" / "commands" / "failed"
    failed_dir.mkdir(parents=True, exist_ok=True)
    report_root = root / ".agent" / "reports" / publisher.TASK_ID
    for old_run, expected_error in publisher.REPAIRABLE_PRIOR_FAILED_RUNS:
        failed_command = failed_dir / f"{publisher.TASK_ID}_{old_run}.json"
        failed_command.write_text(json.dumps({"run_id": old_run}), encoding="utf-8")
        old_report = report_root / old_run
        old_report.mkdir(parents=True, exist_ok=True)
        (old_report / "report.json").write_text(
            json.dumps({"ok": False, "error": expected_error}),
            encoding="utf-8",
        )
        (old_report / "failure_cleanup.json").write_text(
            json.dumps({"ok": True, "target_deleted": True}),
            encoding="utf-8",
        )

    monkeypatch.setattr(publisher, "run_id_now", lambda: "RUN_REPAIR_123456")
    receipt = publisher.publish(root)
    assert receipt["run_id"] == "RUN_REPAIR_123456"
    assert len(list(failed_dir.glob(f"{publisher.TASK_ID}_*.json"))) == 5
    assert (
        root
        / ".agent"
        / "commands"
        / "pending"
        / f"{publisher.TASK_ID}_RUN_REPAIR_123456.json"
    ).is_file()


def test_render_video_retries_next_codec_after_runtime_failure(tmp_path):
    class FakeProject:
        def __init__(self):
            self.codec = ""
            self.settings = {}
            self.jobs = {}
            self.job_counter = 0

        def SetCurrentTimeline(self, timeline):
            return True

        def SetCurrentRenderFormatAndCodec(self, render_format, codec):
            self.codec = codec
            return True

        def SetCurrentRenderMode(self, mode):
            return mode == 1

        def SetRenderSettings(self, payload):
            self.settings.update(dict(payload))
            return True

        def AddRenderJob(self):
            self.job_counter += 1
            job_id = f"job_{self.job_counter}"
            self.jobs[job_id] = {
                "codec": self.codec,
                "target_dir": self.settings["TargetDir"],
                "custom_name": self.settings["CustomName"],
                "status": "Ready",
            }
            return job_id

        def StartRendering(self, job_id):
            job = self.jobs[job_id]
            target_dir = Path(job["target_dir"])
            output = target_dir / f"{job['custom_name']}.mp4"
            if job["codec"] == "H264_NVIDIA":
                output.write_bytes(b"partial")
                job["status"] = "Failed"
            else:
                output.write_bytes(b"complete-video")
                job["status"] = "Complete"
            return True

        def GetRenderJobStatus(self, job_id):
            return {"JobStatus": self.jobs[job_id]["status"]}

        def IsRenderingInProgress(self):
            return False

        def DeleteRenderJob(self, job_id):
            return True

    project = FakeProject()
    result = pilot.render_video(
        project,
        object(),
        tmp_path / "generated_only",
        "generated_only",
        [
            {
                "format": "MP4",
                "codec": "H264_NVIDIA",
                "codec_description": "H.264 NVIDIA",
                "extension": "mp4",
                "score": 925,
            },
            {
                "format": "MP4",
                "codec": "H264",
                "codec_description": "H.264",
                "extension": "mp4",
                "score": 900,
            },
        ],
        {"width": 540, "height": 960, "frame_rate": 24.0},
    )

    assert result["ok"] is True
    assert result["selection"]["codec"] == "H264"
    assert len(result["runtime_attempts"]) == 2
    first, second = result["runtime_attempts"]
    assert first["ok"] is False
    assert first["error"] == "RuntimeError: render_failed:failed"
    assert Path(first["output_dir"]).joinpath("generated_only.mp4").read_bytes() == b"partial"
    assert second["ok"] is True
    assert Path(result["file"]).read_bytes() == b"complete-video"
    assert Path(first["output_dir"]) != Path(second["output_dir"])


def test_render_video_reports_all_runtime_candidate_failures(tmp_path):
    class FakeProject:
        def __init__(self):
            self.codec = ""
            self.settings = {}
            self.counter = 0

        def SetCurrentTimeline(self, timeline):
            return True

        def SetCurrentRenderFormatAndCodec(self, render_format, codec):
            self.codec = codec
            return True

        def SetCurrentRenderMode(self, mode):
            return True

        def SetRenderSettings(self, payload):
            self.settings.update(dict(payload))
            return True

        def AddRenderJob(self):
            self.counter += 1
            return f"job_{self.counter}"

        def StartRendering(self, job_id):
            return True

        def GetRenderJobStatus(self, job_id):
            return {"JobStatus": "Failed"}

        def IsRenderingInProgress(self):
            return False

        def DeleteRenderJob(self, job_id):
            return True

    candidates = [
        {"format": "MP4", "codec": "H264_NVIDIA", "extension": "mp4"},
        {"format": "MP4", "codec": "H264", "extension": "mp4"},
    ]
    result = pilot.render_video(
        FakeProject(),
        object(),
        tmp_path / "generated_only",
        "generated_only",
        candidates,
        {"width": 540, "height": 960, "frame_rate": 24.0},
    )

    assert result["ok"] is False
    assert result["selection"] is None
    assert result["candidate_count"] == 2
    assert len(result["runtime_attempts"]) == 2
    assert all(row["error"] == "RuntimeError: render_failed:failed" for row in result["runtime_attempts"])
    assert "H264_NVIDIA" in result["error"]
    assert "H264" in result["error"]


def test_publisher_repairs_generated_only_runtime_render_failure():
    assert publisher.REPAIRABLE_PRIOR_FAILED_RUNS[-1][0] == "20260809T194731461513Z_be03a73d7b2546fb97f3160ec60eec52"
    assert "render_candidates_exhausted" in publisher.REPAIRABLE_PRIOR_FAILED_RUNS[-1][1]


def test_corrected_script_tokens_use_explicit_authority_font_override():
    rows = {row["visual_token_id"]: row for row in pilot.flatten_authority(authority(), ROOT)}
    for token_id in ("vf_02_decorative_glyph", "vf_05_decorative_glyph"):
        assert rows[token_id]["font"]["font_family"] == "Gabriola"
        assert rows[token_id]["font"]["font_style"] == "Regular"
        assert rows[token_id]["font"]["authority"] == "provisional_renderable_candidate_for_seven_window_visual_review"


def test_corrected_plan_contains_no_katex_script_family():
    rows = pilot.flatten_authority(authority(), ROOT)
    assert all(row["font"]["font_family"] != "KaTeX_Script" for row in rows)
