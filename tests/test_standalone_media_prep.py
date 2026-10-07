from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "standalone" / "video_cloner_media_prep.py"
SPEC = importlib.util.spec_from_file_location("video_cloner_media_prep", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MEDIA = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MEDIA
SPEC.loader.exec_module(MEDIA)


def config(tmp_path: Path, **overrides):
    return MEDIA.RuntimeConfig.load(tmp_path, environ={}, overrides=overrides)


def test_url_identity_is_deterministic_and_query_fragment_independent_for_instagram():
    first = MEDIA.InputSpec.from_url("HTTPS://www.instagram.com/reel/AbC_123/?utm_source=test#fragment")
    second = MEDIA.InputSpec.from_url("https://www.instagram.com/reel/AbC_123")
    assert first.video_id == second.video_id == "AbC_123"
    assert first.kind == "url"


def test_generic_url_identity_is_deterministic():
    first = MEDIA.InputSpec.from_url("https://example.test/watch/item?b=2&a=1")
    second = MEDIA.InputSpec.from_url("https://EXAMPLE.test/watch/item?a=1&b=2#ignored")
    assert first.video_id == second.video_id
    assert first.video_id.startswith("item_")


def test_local_video_input_and_paths_are_deterministic(tmp_path: Path):
    video = tmp_path / "incoming" / "Sample Clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video")
    spec = MEDIA.InputSpec.from_local(video)
    first = MEDIA.build_run_context(spec, config(tmp_path / "project"))
    second = MEDIA.build_run_context(spec, config(tmp_path / "project"))
    assert spec.video_id == "Sample_Clip"
    assert first == second
    assert first.source_video_path == video.resolve()
    assert first.analysis_dir == (tmp_path / "project" / "data" / "Sample_Clip" / "analysis").resolve()
    assert first.wav_path.name == "Sample_Clip.wav"
    assert first.proxy_path.name == "Sample_Clip_proxy.mp4"


def test_directory_initialization_is_idempotent(tmp_path: Path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_local(video), config(tmp_path / "project"))
    context.initialize_directories()
    context.initialize_directories()
    for path in (context.analysis_dir, context.frame_sampling_dir, context.planning_dir, context.davinci_dir, context.debug_dir, context.logs_dir):
        assert path.is_dir()


def test_wav_and_proxy_commands_match_canonical_contract(tmp_path: Path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_local(video), config(tmp_path / "project", ffmpeg="ffmpeg-custom"))
    prep = MEDIA.MediaPreparer(context)
    assert prep.wav_command() == ["ffmpeg-custom", "-y", "-i", str(video.resolve()), "-vn", "-ac", "1", "-ar", "22050", "-sample_fmt", "s16", str(context.wav_path)]
    assert prep.proxy_command() == ["ffmpeg-custom", "-y", "-i", str(video.resolve()), "-vf", "scale=-2:540,fps=24", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-an", str(context.proxy_path)]


def test_proxy_is_created_before_consumers_become_ready(tmp_path: Path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_local(video), config(tmp_path / "project"))
    calls = []

    def runner(argv):
        calls.append(list(argv))
        Path(argv[-1]).write_bytes(b"artifact")
        return subprocess.CompletedProcess(argv, 0, "", "")

    assert not context.proxy_consumers_ready()
    result = MEDIA.MediaPreparer(context, runner).prepare()
    assert result["generated"] == ["wav", "proxy"]
    assert context.proxy_consumers_ready()
    assert tuple(result["context"]["media_dag"]["proxy"]) == MEDIA.PROXY_CONSUMERS
    assert calls[0][-1] == str(context.wav_path)
    assert calls[1][-1] == str(context.proxy_path)


def test_prepare_is_idempotent_when_artifacts_are_non_empty(tmp_path: Path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_local(video), config(tmp_path / "project"))
    calls = []

    def runner(argv):
        calls.append(list(argv))
        Path(argv[-1]).write_bytes(b"artifact")
        return subprocess.CompletedProcess(argv, 0, "", "")

    prep = MEDIA.MediaPreparer(context, runner)
    assert prep.prepare()["generated"] == ["wav", "proxy"]
    assert prep.prepare()["generated"] == []
    assert len(calls) == 2


def test_url_prepare_is_idempotent_after_source_and_derivatives_exist(tmp_path: Path):
    context = MEDIA.build_run_context(
        MEDIA.InputSpec.from_url("https://example.test/video/url-id"),
        config(tmp_path / "project"),
    )
    calls = []

    def runner(argv):
        calls.append(list(argv))
        if argv[0] == context.config.yt_dlp:
            context.source_video_path.write_bytes(b"downloaded-video")
        else:
            Path(argv[-1]).write_bytes(b"artifact")
        return subprocess.CompletedProcess(argv, 0, "", "")

    prep = MEDIA.MediaPreparer(context, runner)
    first = prep.prepare()
    assert first["generated"] == ["wav", "proxy"]
    assert [call[0] for call in calls] == [
        context.config.yt_dlp,
        context.config.ffmpeg,
        context.config.ffmpeg,
    ]
    assert calls[1][-1] == str(context.wav_path)
    assert calls[2][-1] == str(context.proxy_path)
    assert context.proxy_consumers_ready()

    second = prep.prepare(force=False)
    assert second["generated"] == []
    assert len(calls) == 3
    assert context.proxy_consumers_ready()


def test_url_prepare_force_refreshes_source_wav_and_proxy(tmp_path: Path):
    context = MEDIA.build_run_context(
        MEDIA.InputSpec.from_url("https://example.test/video/url-id"),
        config(tmp_path / "project"),
    )
    calls = []
    downloads = 0

    def runner(argv):
        nonlocal downloads
        calls.append(list(argv))
        if argv[0] == context.config.yt_dlp:
            downloads += 1
            context.source_video_path.write_bytes(f"download-{downloads}".encode("ascii"))
        else:
            Path(argv[-1]).write_bytes(f"artifact-{downloads}".encode("ascii"))
        return subprocess.CompletedProcess(argv, 0, "", "")

    prep = MEDIA.MediaPreparer(context, runner)
    prep.prepare()
    calls.clear()
    result = prep.prepare(force=True)
    assert result["generated"] == ["wav", "proxy"]
    assert [call[0] for call in calls] == [
        context.config.yt_dlp,
        context.config.ffmpeg,
        context.config.ffmpeg,
    ]
    assert context.source_video_path.read_bytes() == b"download-2"
    assert context.wav_path.read_bytes() == b"artifact-2"
    assert context.proxy_path.read_bytes() == b"artifact-2"
    assert context.proxy_consumers_ready()


def test_config_precedence_defaults_file_environment_overrides(tmp_path: Path):
    cfg_path = tmp_path / "runtime.json"
    cfg_path.write_text(json.dumps({"ffmpeg": "from-file", "ollama_model": "file-model"}), encoding="utf-8")
    loaded = MEDIA.RuntimeConfig.load(
        tmp_path,
        cfg_path,
        environ={"VIDEO_CLONER_FFMPEG": "from-env", "VIDEO_CLONER_OLLAMA_MODEL": "env-model"},
        overrides={"ffmpeg": "from-cli"},
    )
    assert loaded.ffmpeg == "from-cli"
    assert loaded.ollama_model == "env-model"
    assert loaded.yt_dlp == "yt-dlp"


def test_cookie_path_is_used_but_never_serialized(tmp_path: Path):
    secret = tmp_path / "private" / "cookies.txt"
    loaded = config(tmp_path / "project", cookies_path=str(secret))
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_url("https://example.test/video/id"), loaded)
    command = MEDIA.MediaPreparer(context).download_command()
    assert "--cookies" in command and str(secret.resolve()) in command
    serialized = json.dumps(context.public_contract())
    assert str(secret.resolve()) not in serialized
    assert "cookies.txt" not in serialized
    assert context.public_contract()["runtime"]["cookies_configured"] is True


def test_runtime_contract_redacts_endpoint_credentials_and_query_tokens(tmp_path: Path):
    loaded = config(tmp_path / "project", ollama_url="http://user:secret@localhost:11434/api?token=hidden")
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_url("https://example.test/video/id"), loaded)
    serialized = json.dumps(context.public_contract())
    assert "secret" not in serialized
    assert "hidden" not in serialized
    assert context.public_contract()["runtime"]["ollama"]["url"] == "http://localhost:11434/api"


def test_external_failure_does_not_echo_cookie_or_input_values(tmp_path: Path):
    secret = tmp_path / "private" / "cookies.txt"
    loaded = config(tmp_path / "project", cookies_path=str(secret))
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_url("https://example.test/private?id=token"), loaded)

    def runner(argv):
        return subprocess.CompletedProcess(argv, 7, "", "sensitive stderr")

    with pytest.raises(RuntimeError) as error:
        MEDIA.MediaPreparer(context, runner).acquire_source()
    message = str(error.value)
    assert str(secret.resolve()) not in message
    assert "example.test" not in message
    assert "sensitive stderr" not in message


def test_public_contract_never_invokes_or_imports_resolve(tmp_path: Path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_local(video), config(tmp_path / "project", python_resolve="python312"))
    contract = context.public_contract()
    assert contract["resolve_invoked"] is False
    assert contract["runtime"]["resolve"]["configured"] is True
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "DaVinciResolveScript" not in source
    assert "--apply-zoom" not in source
    assert "--animated-zoom" not in source


def test_new_runtime_has_no_hardcoded_reel_url_or_identity():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "DS5AyItD8DV" not in source
    assert "DZsqH7auhjt" not in source
    assert "instagram.com/reel" not in source.lower()


def test_tests_use_only_temporary_project_data(tmp_path: Path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    context = MEDIA.build_run_context(MEDIA.InputSpec.from_local(video), config(tmp_path / "project"))
    assert tmp_path in context.video_data_root.parents
    assert context.video_data_root != ROOT / "data" / context.video_id
    assert context.video_id != "DZsqH7auhjt"
