from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from .contracts import InputSpec, RunContext


ENV_PREFIX = "VIDEO_CLONER_"
LOCAL_CONFIG_NAME = "video_cloner.local.json"


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
class RuntimeConfig:
    project_root: Path
    data_root: Path
    input_root: Path
    media_root: Path
    state_root: Path
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
    resolve_project_name: str | None = None
    target_timeline: str | None = None
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
            "state_root": root / ".agent",
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
            "resolve_project_name": None,
            "target_timeline": None,
            "ollama_url": "http://127.0.0.1:11434",
            "ollama_model": "llama3.1",
            "cookies_path": None,
        }
        path = Path(config_path).expanduser().resolve() if config_path else root / LOCAL_CONFIG_NAME
        if path.is_file():
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
        for key in ("data_root", "input_root", "media_root", "state_root"):
            values[key] = _optional_path(values[key], root)
        for key in ("resolve_home", "resolve_script_api", "resolve_script_lib", "resolve_portable_exe", "cookies_path"):
            values[key] = _optional_path(values[key], root)
        return cls(project_root=root, **values)  # type: ignore[arg-type]

    @property
    def core_python(self) -> str:
        return self.python_default

    @property
    def audio_python(self) -> str:
        return self.python_audio

    @property
    def ocr_python(self) -> str:
        return self.python_ocr

    def runtime_workers(self) -> dict[str, str | None]:
        return {
            "core_python": self.python_default,
            "audio_python": self.python_audio,
            "ocr_python": self.python_ocr,
            "rhythm_python": self.python_rhythm,
            "resolve_python": self.python_resolve,
            "ffmpeg": self.ffmpeg,
            "yt_dlp": self.yt_dlp,
        }

    def identity(self) -> str:
        public = json.dumps(self.public_runtime(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(public.encode("utf-8")).hexdigest()

    def public_runtime(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "data_root": str(self.data_root),
            "input_root": str(self.input_root),
            "media_root": str(self.media_root),
            "state_root": str(self.state_root),
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
                "project_name": self.resolve_project_name,
                "target_timeline": self.target_timeline,
            },
            "ollama": {"url": _public_endpoint(self.ollama_url), "model": self.ollama_model},
            "cookies_configured": self.cookies_path is not None,
        }


def build_run_context(input_spec: InputSpec, config: RuntimeConfig, run_id: str | None = None) -> RunContext:
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
        run_id=run_id,
    )
