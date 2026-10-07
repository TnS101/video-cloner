from __future__ import annotations

from pathlib import Path
import inspect

from video_cloner import cli, pipeline
from video_cloner.config import RuntimeConfig


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
    monkeypatch.setattr(pipeline, "publish", lambda *args, **kwargs: {"command_path": ".agent/commands/pending/command.json"})
    result = pipeline.run(source, config)
    assert result["run_id"] and result["status"] == "success"
    assert Path(result["manifest_path"]).is_file()
    assert result["stages"]["publish"]["status"] == "success"
    assert "module" not in inspect.signature(pipeline.publish).parameters
