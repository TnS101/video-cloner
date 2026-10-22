from __future__ import annotations

from pathlib import Path
import inspect
import pytest

from video_cloner import cli, pipeline
from video_cloner.config import RuntimeConfig
from video_cloner.resolve.queue import application_plan, publish as publish_command


def test_context_and_cli_route_to_same_pipeline_api(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "reel.mp4"
    source.write_bytes(b"video")
    config = RuntimeConfig.load(tmp_path)
    run = pipeline.context(source, config, run_id="run-1")
    assert run.video_id == "reel"
    assert run.run_id == "run-1"

    called = {}
    monkeypatch.setattr(pipeline, "analyze", lambda context, **options: called.update(context=context, options=options) or {"status": "success"})
    assert cli.main(["analyze", "--project-root", str(tmp_path), "--local-video", str(source)]) == 0
    assert called["context"].video_id == "reel"
    assert called["options"] == {"force": False, "force_analyzers": []}


def test_compile_translates_options_to_proven_compiler(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    def compiler(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr("video_cloner.resolve.fcpxml.main", compiler)
    result = pipeline.compile("generic.json", "style.json", "timeline.fcpxml", "report.json", options={"timeline_mode": "full_timeline", "include_audio": False})
    assert result == 0
    assert captured["argv"][-4:] == ["--timeline-mode", "full_timeline", "--include-audio", "false"]


def test_unified_application_plan_applies_only_supported_layers() -> None:
    dna = {
        "captions": {"compositions": {"compositions": [{"members": [{"accepted_animation": {"status": "unresolved"}}]}]}},
        "transitions": {"transitions": [{"id": "t1"}]},
        "occlusion_and_masks": {"occlusion_events": [{"id": "o1"}]},
        "motion_vfx": {"segments": [{"id": "m1"}]},
    }
    report = {
        "style": {"per_cue_style_events": {"matched_cue_count": 1, "fallback_cue_count": 0}},
        "caption_lifecycle": {"enabled": False},
        "fcpxml": {"position_mode": "detected_fcpx"},
    }
    plan = application_plan(dna, report, {"cuts": [{}], "audio_rows": [{}], "titles": [{}]})
    assert plan["caption_font_style_geometry"]["disposition"] == "apply"
    assert plan["caption_font_style_geometry"]["position_mode"] == "detected_fcpx"
    assert plan["caption_animations"]["disposition"] == "unresolved"
    assert plan["speed_ramps"]["disposition"] == "unsupported"


def test_publish_creates_exactly_one_pending_unified_task(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    contract = {"artifact_set_sha256": "a", "textplus_fingerprint": "b", "fcpxml_sha256": "c", "report_sha256": "d"}
    receipt = publish_command(tmp_path, manifest, contract, "Project", "Target")
    assert receipt["pending_queue_count"] == 1
    assert len(list((tmp_path / ".agent/commands/pending").glob("*.json"))) == 1
    with pytest.raises(ValueError, match="active_command:pending"):
        publish_command(tmp_path, manifest, contract, "Project", "Target")


def test_full_run_gets_identity_and_publication_cannot_select_module(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "reel.mp4"
    source.write_bytes(b"source")
    config = RuntimeConfig.load(tmp_path, overrides={"resolve_project_name": "Project", "target_timeline": "Target"})
    run_context = pipeline.context(source, config)
    run_context.initialize_directories()
    run_context.wav_path.write_bytes(b"wav")
    run_context.proxy_path.write_bytes(b"proxy")
    monkeypatch.setattr(pipeline, "ingest", lambda *args, **kwargs: {"generated": []})
    monkeypatch.setattr(pipeline, "analyze", lambda *args, **kwargs: {"status": "success"})
    monkeypatch.setattr(pipeline, "filter_transitions", lambda *args, **kwargs: "filtered.json")
    monkeypatch.setattr(pipeline, "plan", lambda *args, **kwargs: {"status": "success"})
    monkeypatch.setattr(pipeline, "profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(pipeline, "compile", lambda *args, **kwargs: 0)
    published = {}
    monkeypatch.setattr(pipeline, "publish", lambda *args, **kwargs: published.update(kwargs) or {"command_path": ".agent/commands/pending/command.json"})
    result = pipeline.run(source, config)
    assert result["run_id"] and result["status"] == "success"
    assert Path(result["manifest_path"]).is_file()
    assert result["stages"]["publish"]["status"] == "success"
    assert published["editing_dna"].name == "reel_editing_dna.json"
    assert result["resolve_status"] == "ready_for_resolve"
    assert "module" not in inspect.signature(pipeline.publish).parameters
