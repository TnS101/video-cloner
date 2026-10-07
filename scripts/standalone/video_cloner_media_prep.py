"""Compatibility CLI for canonical media ingestion.

Removal gate: migrate the root BAT/operator callers to ``video-cloner ingest``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from video_cloner.config import RuntimeConfig, build_run_context
from video_cloner.contracts import MEDIA_PREP_DAG, PROXY_CONSUMERS, InputSpec, RunContext
from video_cloner.ingestion.media import MediaPreparer


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
