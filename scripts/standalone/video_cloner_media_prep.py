from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


VIDEO_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
ENV_PREFIX = "VIDEO_CLONER_"
PROXY_CONSUMERS = (
    "scene_detection",
    "motion_detection",
    "transition_detection",
    "caption_occlusion",
)
MEDIA_PREP_DAG = {
    "source_video": ("wav", "proxy"),
    "wav": ("beat_detection", "transcription"),
    "proxy": PROXY_CONSUMERS,
}


def _safe_video_id(value: str) -> str:
    cleaned = VIDEO_ID_RE.sub("_", value.strip()).strip("._-")
    if not cleaned:
        raise ValueError("video ID is empty after normalization")
    return cleaned[:120]


def _canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL input must be an absolute http(s) URL")
    host = parts.hostname.lower() if parts.hostname else ""
    port = f":{parts.port}" if parts.port else ""
    query = urlencode(sorted(parse_qs(parts.query, keep_blank_values=True).items()), doseq=True)
    return urlunsplit((parts.scheme.lower(), host + port, parts.path.rstrip("/") or "/", query, ""))


def _url_video_id(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]
    query = parse_qs(parts.query)
    candidate = ""
    if host in {"youtu.be", "www.youtu.be"} and segments:
        candidate = segments[0]
    elif host.endswith("youtube.com") and query.get("v"):
        candidate = query["v"][0]
    elif host.endswith("instagram.com") and len(segments) >= 2 and segments[0].lower() in {"p", "reel", "reels", "tv"}:
        candidate = segments[1]
    elif host.endswith("tiktok.com") and "video" in segments:
        index = segments.index("video")
        if index + 1 < len(segments):
            candidate = segments[index + 1]
    if candidate:
        return _safe_video_id(candidate)
    leaf = segments[-1] if segments else host.replace(".", "_")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return _safe_video_id(f"{leaf}_{digest}")


def _optional_path(value: object, base: Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _public_endpoint(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.hostname:
        return value.split("?", 1)[0].split("#", 1)[0]
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme, parts.hostname + port, parts.path, "", ""))


@dataclass(frozen=True)
class InputSpec:
    kind: str
    locator: str
    video_id: str

    @classmethod
    def from_url(cls, value: str) -> "InputSpec":
        canonical = _canonical_url(value)
        return cls("url", canonical, _url_video_id(canonical))

    @classmethod
    def from_local(cls, value: str | Path) -> "InputSpec":
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"local video does not exist: {path}")
        return cls("local", str(path), _safe_video_id(path.stem))


@dataclass(frozen=True)
class RuntimeConfig:
    project_root: Path
    data_root: Path
    input_root: Path
    media_root: Path
    ffmpeg: str = "ffmpeg"
    yt_dlp: str = "yt-dlp"
    python_default: str = sys.executable
    python_audio: str = sys.executable
    python_ocr: str = sys.executable
    python_rhythm: str = sys.executable
    python_resolve: str | None = None
    resolve_home: Path | None = None
    resolve_script_api: Path | None = None
    resolve_script_lib: Path | None = None
    resolve_portable_exe: Path | None = None
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1"
    cookies_path: Path | None = None

    @classmethod
    def load(
        cls,
        project_root: str | Path,
        config_path: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
        overrides: Mapping[str, object] | None = None,
    ) -> "RuntimeConfig":
        root = Path(project_root).expanduser().resolve()
        values: dict[str, object] = {
            "data_root": root / "data",
            "input_root": root / "input",
            "media_root": root / "media",
            "ffmpeg": "ffmpeg",
            "yt_dlp": "yt-dlp",
            "python_default": sys.executable,
            "python_audio": sys.executable,
            "python_ocr": sys.executable,
            "python_rhythm": sys.executable,
            "python_resolve": None,
            "resolve_home": None,
            "resolve_script_api": None,
            "resolve_script_lib": None,
            "resolve_portable_exe": None,
            "ollama_url": "http://127.0.0.1:11434",
            "ollama_model": "llama3.1",
            "cookies_path": None,
        }
        if config_path:
            path = Path(config_path).expanduser().resolve()
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("runtime config must be a JSON object")
            unknown = set(loaded) - set(values)
            if unknown:
                raise ValueError(f"unknown runtime config keys: {sorted(unknown)}")
            values.update(loaded)
        env = dict(os.environ if environ is None else environ)
        for key in values:
            env_key = ENV_PREFIX + key.upper()
            if env_key in env:
                values[key] = env[env_key]
        if overrides:
            unknown = set(overrides) - set(values)
            if unknown:
                raise ValueError(f"unknown runtime overrides: {sorted(unknown)}")
            values.update({key: value for key, value in overrides.items() if value is not None})
        for key in ("data_root", "input_root", "media_root"):
            values[key] = _optional_path(values[key], root)
        for key in ("resolve_home", "resolve_script_api", "resolve_script_lib", "resolve_portable_exe", "cookies_path"):
            values[key] = _optional_path(values[key], root)
        return cls(project_root=root, **values)  # type: ignore[arg-type]

    def public_runtime(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "data_root": str(self.data_root),
            "input_root": str(self.input_root),
            "media_root": str(self.media_root),
            "ffmpeg": self.ffmpeg,
            "yt_dlp": self.yt_dlp,
            "python": {
                "default": self.python_default,
                "audio": self.python_audio,
                "ocr": self.python_ocr,
                "rhythm": self.python_rhythm,
                "resolve_configured": bool(self.python_resolve),
            },
            "resolve": {
                "configured": any((self.python_resolve, self.resolve_home, self.resolve_script_api, self.resolve_script_lib, self.resolve_portable_exe)),
            },
            "ollama": {"url": _public_endpoint(self.ollama_url), "model": self.ollama_model},
            "cookies_configured": self.cookies_path is not None,
        }


@dataclass(frozen=True)
class RunContext:
    input_spec: InputSpec
    config: RuntimeConfig
    video_data_root: Path
    analysis_dir: Path
    frame_sampling_dir: Path
    planning_dir: Path
    davinci_dir: Path
    debug_dir: Path
    logs_dir: Path
    source_video_path: Path
    wav_path: Path
    proxy_path: Path

    @property
    def video_id(self) -> str:
        return self.input_spec.video_id

    def initialize_directories(self) -> None:
        for path in (
            self.config.data_root,
            self.config.input_root,
            self.config.media_root,
            self.video_data_root,
            self.analysis_dir,
            self.frame_sampling_dir,
            self.planning_dir,
            self.davinci_dir,
            self.debug_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def with_source(self, path: Path) -> "RunContext":
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"acquired source video does not exist: {resolved}")
        return replace(self, source_video_path=resolved)

    def proxy_consumers_ready(self) -> bool:
        return self.proxy_path.is_file() and self.proxy_path.stat().st_size > 0

    def public_contract(self) -> dict[str, object]:
        return {
            "schema": "video_cloner.run_context.v1",
            "video_id": self.video_id,
            "input_kind": self.input_spec.kind,
            "paths": {
                "video_data_root": str(self.video_data_root),
                "analysis": str(self.analysis_dir),
                "planning": str(self.planning_dir),
                "davinci": str(self.davinci_dir),
                "debug": str(self.debug_dir),
                "logs": str(self.logs_dir),
                "source_video": str(self.source_video_path),
                "wav": str(self.wav_path),
                "proxy": str(self.proxy_path),
            },
            "runtime": self.config.public_runtime(),
            "media_dag": {key: list(value) for key, value in MEDIA_PREP_DAG.items()},
            "proxy_consumers_ready": self.proxy_consumers_ready(),
            "resolve_invoked": False,
        }


def build_run_context(input_spec: InputSpec, config: RuntimeConfig) -> RunContext:
    video_id = input_spec.video_id
    video_root = config.data_root / video_id
    source = Path(input_spec.locator) if input_spec.kind == "local" else config.input_root / f"{video_id}.mp4"
    return RunContext(
        input_spec=input_spec,
        config=config,
        video_data_root=video_root,
        analysis_dir=video_root / "analysis",
        frame_sampling_dir=video_root / "analysis" / "frame_sampling",
        planning_dir=video_root / "planning",
        davinci_dir=video_root / "davinci",
        debug_dir=video_root / "debug",
        logs_dir=video_root / "logs",
        source_video_path=source.resolve(),
        wav_path=(config.media_root / f"{video_id}.wav").resolve(),
        proxy_path=(config.media_root / f"{video_id}_proxy.mp4").resolve(),
    )


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare Video Cloner source, WAV, and proxy without invoking Resolve.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url")
    source.add_argument("--local-video")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--config")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--yt-dlp")
    parser.add_argument("--cookies-path")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--print-context", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    overrides = {"ffmpeg": args.ffmpeg, "yt_dlp": args.yt_dlp, "cookies_path": args.cookies_path}
    config = RuntimeConfig.load(args.project_root, args.config, overrides=overrides)
    input_spec = InputSpec.from_url(args.url) if args.url else InputSpec.from_local(args.local_video)
    context = build_run_context(input_spec, config)
    if args.print_context:
        print(json.dumps(context.public_contract(), indent=2, sort_keys=True))
        return 0
    result = MediaPreparer(context).prepare(force=args.force)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
