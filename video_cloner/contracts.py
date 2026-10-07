from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import uuid4

if TYPE_CHECKING:
    from .config import RuntimeConfig


VIDEO_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
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


def safe_video_id(value: str) -> str:
    cleaned = VIDEO_ID_RE.sub("_", value.strip()).strip("._-")
    if not cleaned:
        raise ValueError("video ID is empty after normalization")
    return cleaned[:120]


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL input must be an absolute http(s) URL")
    host = parts.hostname.lower() if parts.hostname else ""
    port = f":{parts.port}" if parts.port else ""
    query = urlencode(sorted(parse_qs(parts.query, keep_blank_values=True).items()), doseq=True)
    return urlunsplit((parts.scheme.lower(), host + port, parts.path.rstrip("/") or "/", query, ""))


def url_video_id(url: str) -> str:
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
        return safe_video_id(candidate)
    leaf = segments[-1] if segments else host.replace(".", "_")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return safe_video_id(f"{leaf}_{digest}")


def new_run_id(video_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{safe_video_id(video_id)}-{timestamp}-{uuid4().hex[:12]}"


@dataclass(frozen=True)
class InputSpec:
    kind: str
    locator: str
    video_id: str

    @classmethod
    def from_url(cls, value: str) -> "InputSpec":
        canonical = canonical_url(value)
        return cls("url", canonical, url_video_id(canonical))

    @classmethod
    def from_local(cls, value: str | Path) -> "InputSpec":
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"local video does not exist: {path}")
        return cls("local", str(path), safe_video_id(path.stem))


@dataclass(frozen=True)
class ArtifactIdentity:
    path: str
    sha256: str
    bytes: int

    @classmethod
    def from_path(cls, path: str | Path, root: str | Path | None = None) -> "ArtifactIdentity":
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"artifact does not exist: {resolved}")
        display = resolved
        if root is not None:
            display = resolved.relative_to(Path(root).expanduser().resolve())
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return cls(display.as_posix(), digest.hexdigest(), resolved.stat().st_size)

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


@dataclass(frozen=True)
class StageResult:
    stage: str
    status: str
    inputs: tuple[ArtifactIdentity, ...] = ()
    outputs: tuple[ArtifactIdentity, ...] = ()
    error: str | None = None
    runtime_identity: Mapping[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "status": self.status,
            "inputs": [item.as_dict() for item in self.inputs],
            "outputs": [item.as_dict() for item in self.outputs],
            "error": self.error,
            "runtime_identity": dict(self.runtime_identity or {}),
        }


@dataclass(frozen=True)
class RunContext:
    input_spec: InputSpec
    config: "RuntimeConfig"
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
    run_id: str | None = None

    @property
    def video_id(self) -> str:
        return self.input_spec.video_id

    def initialize_directories(self) -> None:
        for path in (
            self.config.data_root,
            self.config.input_root,
            self.config.media_root,
            self.config.state_root,
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
        contract: dict[str, Any] = {
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
        if self.run_id is not None:
            contract["run_id"] = self.run_id
        return contract
