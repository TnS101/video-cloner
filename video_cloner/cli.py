"""The single discoverable ``video-cloner`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from . import pipeline
from .config import RuntimeConfig


def _source(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--local-video")
    parser.add_argument("--project-root", default=str(Path.cwd()))
    parser.add_argument("--config")


def _source_value(args: argparse.Namespace) -> str:
    return args.url or args.local_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="video-cloner", description="Canonical offline Video Cloner pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest", "analyze"):
        sub = commands.add_parser(name)
        _source(sub)
        sub.add_argument("--force", action="store_true")
    analyze = commands.choices["analyze"]
    analyze.add_argument("--force-analyzer", action="append", default=[])
    profile = commands.add_parser("profile")
    _source(profile)
    profile.add_argument("--samples-per-shot", type=int, default=5)
    plan = commands.add_parser("plan")
    _source(plan)
    plan.add_argument("--transition-authority", required=True)
    plan.add_argument("--force", action="store_true")
    plan.add_argument("--force-stage", action="append", default=[])
    offline = commands.add_parser("run-offline")
    _source(offline)
    offline.add_argument("--transition-authority", required=True)
    offline.add_argument("--force", action="store_true")
    offline.add_argument("--samples-per-shot", type=int, default=5)
    compiler = commands.add_parser("compile")
    compiler.add_argument("--generic", required=True)
    compiler.add_argument("--caption-style", required=True)
    compiler.add_argument("--output-fcpxml", required=True)
    compiler.add_argument("--report", required=True)
    compiler.add_argument("compiler_args", nargs=argparse.REMAINDER, help="additional proven compiler arguments after --")
    publisher = commands.add_parser("publish")
    publisher.add_argument("--project-root", default=str(Path.cwd()))
    publisher.add_argument("--config")
    for name in ("generic", "proxy", "caption-style", "audio", "fcpxml", "compiler-report"):
        publisher.add_argument(f"--{name}", required=True)
    publisher.add_argument("--project")
    publisher.add_argument("--target-timeline")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "compile":
        options = {}
        tail = list(args.compiler_args)
        if tail[:1] == ["--"]:
            tail.pop(0)
        while tail:
            key = tail.pop(0)
            if not key.startswith("--") or not tail:
                raise SystemExit("additional compiler arguments must be --name value pairs")
            options[key[2:].replace("-", "_")] = tail.pop(0)
        return pipeline.compile(args.generic, args.caption_style, args.output_fcpxml, args.report, options=options)
    config = RuntimeConfig.load(args.project_root, args.config)
    if args.command == "publish":
        result = pipeline.publish(config, generic=args.generic, proxy=args.proxy, caption_style=args.caption_style, audio=args.audio, fcpxml=args.fcpxml, compiler_report=args.compiler_report, project=args.project, target_timeline=args.target_timeline)
    else:
        run = pipeline.context(_source_value(args), config)
        if args.command == "ingest":
            result = pipeline.ingest(run.input_spec, config, force=args.force)
        elif args.command == "analyze":
            result = pipeline.analyze(run, force=args.force, force_analyzers=args.force_analyzer)
        elif args.command == "plan":
            result = pipeline.plan(run, args.transition_authority, force=args.force, force_stages=args.force_stage)
        elif args.command == "profile":
            result = pipeline.profile(run, samples_per_shot=args.samples_per_shot)
        else:
            result = pipeline.run_offline(run, args.transition_authority, force=args.force, samples_per_shot=args.samples_per_shot)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
