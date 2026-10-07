from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Sequence

from video_cloner.config import RuntimeConfig, build_run_context
from video_cloner.contracts import InputSpec, RunContext


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), check=False, capture_output=True, text=True)


class MediaPreparer:
    def __init__(self, context: RunContext, runner: Runner = _default_runner):
        self.context = context
        self.runner = runner

    def _run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        result = self.runner(argv)
        if result.returncode != 0:
            raise RuntimeError(f"external command failed with exit code {result.returncode}: {Path(argv[0]).name}")
        return result

    def download_command(self) -> list[str]:
        if self.context.input_spec.kind != "url":
            raise ValueError("download command is only valid for URL input")
        command = [
            self.context.config.yt_dlp,
            "-S", "res,ext:mp4:m4a",
            "--recode-video", "mp4",
            "--print", "after_move:filepath",
            "-o", str(self.context.source_video_path),
        ]
        if self.context.config.cookies_path:
            command.extend(("--cookies", str(self.context.config.cookies_path)))
        command.append(self.context.input_spec.locator)
        return command

    def wav_command(self) -> list[str]:
        return [
            self.context.config.ffmpeg, "-y", "-i", str(self.context.source_video_path),
            "-vn", "-ac", "1", "-ar", "22050", "-sample_fmt", "s16", str(self.context.wav_path),
        ]

    def proxy_command(self) -> list[str]:
        return [
            self.context.config.ffmpeg, "-y", "-i", str(self.context.source_video_path),
            "-vf", "scale=-2:540,fps=24", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "30", "-an", str(self.context.proxy_path),
        ]

    def acquire_source(self, force: bool = False) -> RunContext:
        if self.context.input_spec.kind == "local":
            return self.context
        source = self.context.source_video_path
        if not force and source.is_file() and source.stat().st_size > 0:
            return self.context
        self._run(self.download_command())
        self.context = self.context.with_source(source)
        if self.context.source_video_path.stat().st_size <= 0:
            raise RuntimeError(
                f"source acquisition did not create a non-empty artifact: {self.context.source_video_path}"
            )
        return self.context

    def prepare(self, force: bool = False) -> dict[str, object]:
        self.context.initialize_directories()
        self.acquire_source(force=force)
        if not self.context.source_video_path.is_file() or self.context.source_video_path.stat().st_size <= 0:
            raise FileNotFoundError(f"source video is unavailable or empty: {self.context.source_video_path}")
        generated: list[str] = []
        if force or not (self.context.wav_path.is_file() and self.context.wav_path.stat().st_size > 0):
            self._run(self.wav_command())
            generated.append("wav")
        if force or not (self.context.proxy_path.is_file() and self.context.proxy_path.stat().st_size > 0):
            self._run(self.proxy_command())
            generated.append("proxy")
        for label, path in (("wav", self.context.wav_path), ("proxy", self.context.proxy_path)):
            if not path.is_file() or path.stat().st_size <= 0:
                raise RuntimeError(f"{label} preparation did not create a non-empty artifact: {path}")
        return {"generated": generated, "context": self.context.public_contract()}


def ingest(
    input_spec: InputSpec,
    config: RuntimeConfig,
    *,
    force: bool = False,
    run_id: str | None = None,
    runner: Runner = _default_runner,
) -> dict[str, object]:
    return MediaPreparer(build_run_context(input_spec, config, run_id=run_id), runner).prepare(force=force)
