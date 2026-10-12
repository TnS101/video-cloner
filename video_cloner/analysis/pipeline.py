from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from video_cloner.config import RuntimeConfig, build_run_context
from video_cloner.contracts import InputSpec, RunContext


REPORT_SCHEMA = "video_cloner.analysis_run.v1"
COMMAND_PROFILE = "immutable_n8n_video_cloner_2026_07"


@dataclass(frozen=True)
class AnalyzerSpec:
    name: str
    script: str
    interpreter: str
    inputs: tuple[str, ...]
    output: str


ANALYZERS = (
    AnalyzerSpec("cuts", "video_cloner/analysis/cuts.py", "python_default", ("proxy",), "shots"),
    AnalyzerSpec("transcript", "video_cloner/analysis/transcription.py", "python_audio", ("wav",), "transcript"),
    AnalyzerSpec("rhythm", "video_cloner/analysis/rhythm.py", "python_audio", ("wav",), "beatmap"),
    AnalyzerSpec("caption_style", "video_cloner/analysis/caption_style.py", "python_ocr", ("source_video", "transcript"), "caption_style"),
    AnalyzerSpec("font_candidates", "scripts/analysis/detect_caption_font_candidates.py", "python_ocr", ("source_video", "caption_style"), "font_candidates"),
    AnalyzerSpec("motion", "video_cloner/analysis/motion.py", "python_default", ("proxy", "shots"), "motion"),
    AnalyzerSpec("transitions", "video_cloner/analysis/transitions.py", "python_default", ("proxy", "shots"), "transitions"),
    AnalyzerSpec("caption_occlusion", "video_cloner/analysis/caption_occlusion.py", "python_ocr", ("proxy", "caption_style", "transcript"), "caption_occlusion"),
)
ANALYZER_BY_NAME = {spec.name: spec for spec in ANALYZERS}
PRODUCER = {spec.output: spec.name for spec in ANALYZERS}


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), check=False, capture_output=True, text=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


class AnalysisRunError(RuntimeError):
    def __init__(self, report: Mapping[str, object]):
        self.report = dict(report)
        failure = self.report.get("first_failure") or {}
        if isinstance(failure, Mapping):
            message = f"analysis failed at {failure.get('analyzer', 'unknown')}: {failure.get('error', 'unknown failure')}"
        else:
            message = "analysis failed"
        super().__init__(message)


class AnalysisOrchestrator:
    def __init__(self, context: RunContext, runner: Runner = _default_runner):
        self.context = context
        self.runner = runner
        video_id = context.video_id
        root = context.analysis_dir
        self.artifacts: dict[str, Path] = {
            "source_video": context.source_video_path,
            "wav": context.wav_path,
            "proxy": context.proxy_path,
            "shots": root / f"{video_id}_shots.json",
            "transcript": root / f"{video_id}_transcript.json",
            "beatmap": root / f"{video_id}_beatmap.json",
            "caption_style": root / f"{video_id}_caption_style.json",
            "font_candidates": root / f"{video_id}_font_candidates.json",
            "motion": root / f"{video_id}_motion.json",
            "transitions": root / f"{video_id}_transitions.json",
            "caption_occlusion": root / f"{video_id}_caption_occlusion.json",
        }
        self.report_path = root / f"{video_id}_analysis_run.json"

    def canonical_contract(self) -> dict[str, object]:
        return {
            "schema": REPORT_SCHEMA,
            "video_id": self.context.video_id,
            "analysis_dir": str(self.context.analysis_dir),
            "artifacts": {key: str(path) for key, path in self.artifacts.items()},
            "analyzers": [
                {
                    "name": spec.name,
                    "script": spec.script,
                    "interpreter": spec.interpreter,
                    "inputs": list(spec.inputs),
                    "output": spec.output,
                }
                for spec in ANALYZERS
            ],
            "report_path": str(self.report_path),
            "planner_invoked": False,
            "resolve_invoked": False,
        }

    def readiness(self, analyzer: str) -> dict[str, object]:
        spec = ANALYZER_BY_NAME.get(analyzer)
        if spec is None:
            raise ValueError(f"unknown analyzer: {analyzer}")
        missing = [key for key in spec.inputs if not _nonempty(self.artifacts[key])]
        return {"analyzer": analyzer, "ready": not missing, "missing": missing}

    def _script_path(self, spec: AnalyzerSpec) -> Path:
        return (self.context.config.project_root / spec.script).resolve()

    def _interpreter(self, spec: AnalyzerSpec) -> str:
        return str(getattr(self.context.config, spec.interpreter))

    def _command(self, spec: AnalyzerSpec) -> list[str]:
        a = self.artifacts
        script = str(self._script_path(spec))
        python = self._interpreter(spec)
        output = str(a[spec.output])
        if spec.name == "cuts":
            return [python, script, str(a["proxy"]), "23"]
        if spec.name == "transcript":
            return [python, script, str(a["wav"]), "--output", output, "--model", "medium", "--device", "cuda", "--compute-type", "float16", "--caption-mode", "word", "--max-words-per-caption", "1", "--max-caption-chars", "22", "--max-caption-duration", "1.2", "--min-caption-duration", "0.08"]
        if spec.name == "rhythm":
            return [python, script, "--audio", str(a["wav"]), "--output", output, "--output-mode", "compact", "--approximate-downbeats"]
        if spec.name == "caption_style":
            return [python, script, "--video", str(a["source_video"]), "--transcript", str(a["transcript"]), "--output", output, "--frames", str(self.context.frame_sampling_dir), "--mode", "viral_transcript_aware", "--every-seconds", "0.25", "--max-frames", "160", "--min-confidence", "0.35", "--transcript-match-threshold", "0.30", "--regular-caption-score-threshold", "0.46", "--visual-spoken-score-threshold", "0.56", "--visual-spoken-min-confidence", "0.55", "--visual-hook-score-threshold", "0.64", "--save-debug", "true", "--debug-mode", "subtitle_only", "--output-mode", "full", "--emit-caption-style-events", "true", "--clear-frames", "true", "--ocr-lang", "en", "--use-angle-cls", "false", "--ocr-device", "gpu", "--ocr-gpu-id", "0", "--opencv-threads", "4", "--enable-caption-animation-detection", "true", "--animation-samples-per-cue", "5", "--animation-sample-window-sec", "0.22", "--animation-min-samples", "3", "--animation-max-samples", "7"]
        if spec.name == "font_candidates":
            return [python, script, "--video", str(a["source_video"]), "--caption-style", str(a["caption_style"]), "--output", output, "--debug-dir", str(self.context.analysis_dir / "debug_caption_font")]
        if spec.name == "motion":
            return [python, script, "--video", str(a["proxy"]), "--shots", str(a["shots"]), "--output", output, "--output-mode", "compact", "--samples-per-shot", "7", "--pair-delta", "0.18", "--min-shot-duration", "0.35", "--use-caption-mask", "true", "--speed-ramp-min-score", "0.45"]
        if spec.name == "transitions":
            return [python, script, "--video", str(a["proxy"]), "--shots", str(a["shots"]), "--output", output, "--window-frames", "3", "--min-confidence", "medium", "--max-runtime-sec", "45", "--max-boundaries", "300", "--output-mode", "compact"]
        if spec.name == "caption_occlusion":
            return [python, script, "--video", str(a["proxy"]), "--caption-style", str(a["caption_style"]), "--transcript", str(a["transcript"]), "--output", output, "--debug-dir", str(self.context.analysis_dir / "debug_caption_occlusion"), "--write-mask-assets", "true", "--mask-output-dir", str(self.context.analysis_dir / "foreground_masks"), "--clear-mask-assets", "true", "--clear-mask-assets-per-event", "true", "--mask-assets-only-needed", "true", "--mask-stop-on-first-failure", "true", "--mask-progress-every", "25", "--backend", "paddle_humanseg", "--segmentation-device", "gpu", "--paddle-gpu-id", "0", "--paddle-hub-module", "humanseg_lite", "--paddle-seg-threshold", "0.50", "--require-paddle-gpu", "true", "--enable-grabcut-fallback", "false", "--samples-per-event", "3", "--sample-window-sec", "0.18", "--include-inferred-transcript-cues", "true", "--include-word-inferred-cues", "false", "--max-inferred-events", "20", "--max-total-samples", "360", "--time-budget-sec", "0", "--occlusion-threshold", "0.42", "--mask-overlap-threshold", "0.18", "--segmentation-max-side", "960", "--write-debug-frames", "true", "--debug-max-frames", "0", "--clear-debug", "true", "--write-classification-audit", "true", "--classification-audit-dir", str(self.context.analysis_dir / "caption_occlusion_audit"), "--clear-classification-audit", "true", "--progress-every", "10", "--encoding", "utf-8"]
        raise ValueError(f"unsupported analyzer: {spec.name}")

    def _load_previous(self) -> dict[str, object]:
        if not _nonempty(self.report_path):
            return {}
        try:
            value = json.loads(self.report_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) and value.get("schema") == REPORT_SCHEMA else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_report(self, report: Mapping[str, object]) -> None:
        self.context.analysis_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.report_path.with_suffix(self.report_path.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.report_path)

    def _input_identity(self, spec: AnalyzerSpec) -> tuple[list[dict[str, object]], str, str, str]:
        inputs = []
        for key in spec.inputs:
            path = self.artifacts[key]
            inputs.append({"artifact": key, "path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)})
        script = self._script_path(spec)
        command = self._command(spec)
        interpreter_identity_sha256 = hashlib.sha256(command[0].encode("utf-8")).hexdigest()
        command_profile_sha256 = hashlib.sha256(
            json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        identity = {
            "analyzer": spec.name,
            "interpreter_role": spec.interpreter,
            "interpreter_identity_sha256": interpreter_identity_sha256,
            "command_profile_sha256": command_profile_sha256,
            "script_sha256": _sha256(script),
            "inputs": inputs,
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return inputs, hashlib.sha256(encoded).hexdigest(), interpreter_identity_sha256, command_profile_sha256

    def _validate_output(self, spec: AnalyzerSpec) -> tuple[object, str]:
        path = self.artifacts[spec.output]
        if not _nonempty(path):
            raise RuntimeError(f"analyzer did not create a non-empty output: {spec.output}")
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"invalid JSON output for {spec.name}") from error
        if spec.name == "cuts":
            if not isinstance(value, list):
                raise RuntimeError("cuts output must be a JSON list")
        elif not isinstance(value, dict):
            raise RuntimeError(f"{spec.name} output must be a JSON object")
        elif value.get("success") is False or value.get("ok") is False:
            raise RuntimeError(f"{spec.name} output reports failure")
        if isinstance(value, dict):
            version = str(value.get("analysis_version") or value.get("version") or value.get("schema_version") or "")
        else:
            version = ""
        if not version:
            version = f"script_sha256:{_sha256(self._script_path(spec))[:16]}"
        return value, version

    @staticmethod
    def _declared_path(raw: object, base: Path) -> Path:
        if not isinstance(raw, str) or not raw.strip():
            raise RuntimeError("caption occlusion mask asset has a missing path")
        path = Path(raw)
        return path if path.is_absolute() else (base / path).resolve()

    def _output_bundle_fingerprint(self, spec: AnalyzerSpec, value: object) -> str:
        output = self.artifacts[spec.output]
        files = [output]
        if spec.name == "caption_occlusion":
            if not isinstance(value, dict) or not isinstance(value.get("mask_assets"), dict):
                raise RuntimeError("caption occlusion output has no mask asset readiness summary")
            summary = value["mask_assets"]
            assert isinstance(summary, dict)
            if summary.get("enabled") is not True:
                raise RuntimeError("caption occlusion mask asset export is not enabled")
            events = value.get("occlusion_events")
            if not isinstance(events, list):
                raise RuntimeError("caption occlusion output has no event list")
            assets = []
            for event in events:
                asset = event.get("mask_asset") if isinstance(event, dict) else None
                if isinstance(asset, dict) and asset.get("requested") is True:
                    assets.append(asset)
            if summary.get("events_requested") != len(assets) or summary.get("events_complete") != len(assets) or summary.get("events_incomplete") != 0:
                raise RuntimeError("caption occlusion mask event counts are incoherent")
            if not assets:
                if summary.get("frames_written") != 0:
                    raise RuntimeError("caption occlusion reports mask frames without requested assets")
                # The live detector defines mask_assets.ready as False when zero
                # mask assets are requested. That is a valid no-occlusion result:
                # there are no required foreground sidecars to validate or hash.
                root = None
            else:
                if summary.get("ready") is not True:
                    raise RuntimeError("caption occlusion requested mask assets are not editor-ready")
                root = self._declared_path(summary.get("root"), output.parent)
                if not root.is_dir():
                    raise RuntimeError("caption occlusion mask root is missing")
            total_frames = 0
            for asset in assets:
                if asset.get("complete") is not True or asset.get("errors") not in (None, []):
                    raise RuntimeError("caption occlusion mask event is incomplete")
                asset_root = self._declared_path(asset.get("mask_root"), output.parent)
                event_dir = self._declared_path(asset.get("event_dir"), output.parent)
                manifest = self._declared_path(asset.get("manifest"), output.parent)
                if asset_root != root or not event_dir.is_dir() or root not in event_dir.parents or not _nonempty(manifest):
                    raise RuntimeError("caption occlusion mask event paths are incomplete")
                start = asset.get("source_frame_start")
                end = asset.get("source_frame_end_exclusive")
                expected = asset.get("frame_count_expected")
                written = asset.get("frame_count_written")
                if not all(isinstance(number, int) and not isinstance(number, bool) for number in (start, end, expected, written)):
                    raise RuntimeError("caption occlusion mask frame metadata is invalid")
                assert isinstance(start, int) and isinstance(end, int) and isinstance(expected, int) and isinstance(written, int)
                if expected <= 0 or end - start != expected or written != expected:
                    raise RuntimeError("caption occlusion mask frame counts are incoherent")
                pattern = self._declared_path(asset.get("mask_pattern"), output.parent)
                if event_dir not in pattern.parents or "%" not in pattern.name:
                    raise RuntimeError("caption occlusion mask pattern is invalid")
                try:
                    frame_files = [Path(str(pattern) % frame) for frame in range(start, end)]
                except (TypeError, ValueError) as error:
                    raise RuntimeError("caption occlusion mask pattern cannot address its frame range") from error
                if any(not _nonempty(path) for path in frame_files):
                    raise RuntimeError("caption occlusion mask sequence is missing or empty")
                try:
                    manifest_value = json.loads(manifest.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError) as error:
                    raise RuntimeError("caption occlusion mask manifest is invalid") from error
                for key in ("requested", "complete", "source_frame_start", "source_frame_end_exclusive", "frame_count_expected", "frame_count_written", "mask_pattern"):
                    if not isinstance(manifest_value, dict) or manifest_value.get(key) != asset.get(key):
                        raise RuntimeError("caption occlusion mask manifest disagrees with the output JSON")
                files.extend([manifest, *frame_files])
                total_frames += expected
            if summary.get("frames_written") != total_frames:
                raise RuntimeError("caption occlusion total mask frame count is incoherent")
        identities = [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in sorted(set(files), key=lambda item: str(item).casefold())
        ]
        encoded = json.dumps(identities, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _write_cuts(self, stdout: str) -> None:
        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("cuts analyzer returned no JSON result")
        try:
            result = json.loads(lines[-1])
        except json.JSONDecodeError as error:
            raise RuntimeError("cuts analyzer returned invalid JSON") from error
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("cuts"), list):
            raise RuntimeError("cuts analyzer reported failure")
        shots = [
            {
                "shot_id": scene["scene_index"],
                "start_seconds": scene["start_seconds"],
                "end_seconds": scene["end_seconds"],
                "duration_seconds": scene["duration_seconds"],
                "start_frame": scene["start_frame"],
                "end_frame": scene["end_frame"],
            }
            for scene in result["cuts"]
        ]
        self.artifacts["shots"].write_text(json.dumps(shots, indent=2) + "\n", encoding="utf-8")

    def _previous_records(self, previous: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        records = previous.get("analyzers")
        if not isinstance(records, list):
            return {}
        return {str(record.get("analyzer")): record for record in records if isinstance(record, Mapping)}

    def _can_reuse(self, spec: AnalyzerSpec, previous: Mapping[str, object], fingerprint: str) -> bool:
        output = self.artifacts[spec.output]
        if previous.get("status") not in {"generated", "reused"} or previous.get("input_fingerprint") != fingerprint:
            return False
        if not _nonempty(output) or previous.get("output_sha256") != _sha256(output):
            return False
        try:
            value, _ = self._validate_output(spec)
            if previous.get("output_bundle_fingerprint") != self._output_bundle_fingerprint(spec, value):
                return False
        except RuntimeError:
            return False
        return True

    def run(self, force: bool = False, force_analyzers: Iterable[str] | None = None) -> dict[str, object]:
        requested = set(force_analyzers or ())
        unknown = requested - set(ANALYZER_BY_NAME)
        if unknown:
            raise ValueError(f"unknown forced analyzers: {sorted(unknown)}")
        forced = set(ANALYZER_BY_NAME) if force else requested
        self.context.analysis_dir.mkdir(parents=True, exist_ok=True)
        previous = self._load_previous()
        previous_records = self._previous_records(previous)
        started_clock = time.monotonic()
        report: dict[str, object] = {
            "schema": REPORT_SCHEMA,
            "video_id": self.context.video_id,
            "started_at_utc": _utc_now(),
            "status": "running",
            "command_profile": COMMAND_PROFILE,
            "analysis_dir": str(self.context.analysis_dir),
            "analyzers": [],
            "first_failure": None,
            "planner_invoked": False,
            "resolve_invoked": False,
        }
        state: dict[str, str] = {}
        records = report["analyzers"]
        assert isinstance(records, list)

        for spec in ANALYZERS:
            analyzer_started = time.monotonic()
            failed_producers = [PRODUCER[key] for key in spec.inputs if key in PRODUCER and state.get(PRODUCER[key]) in {"failed", "blocked"}]
            missing = [key for key in spec.inputs if not _nonempty(self.artifacts[key])]
            if failed_producers or missing:
                details = sorted(set(missing + [f"producer:{name}" for name in failed_producers]))
                record = {"analyzer": spec.name, "status": "blocked", "failure_class": "PREREQUISITE", "error": f"missing or failed prerequisites: {', '.join(details)}", "runtime_sec": round(time.monotonic() - analyzer_started, 6), "output_path": str(self.artifacts[spec.output])}
                records.append(record); state[spec.name] = "blocked"
                if report["first_failure"] is None:
                    report["first_failure"] = {"analyzer": spec.name, "failure_class": record["failure_class"], "error": record["error"]}
                self._write_report(report)
                continue

            script = self._script_path(spec)
            if not _nonempty(script):
                record = {"analyzer": spec.name, "status": "failed", "failure_class": "PREREQUISITE", "error": f"canonical analyzer script missing: {spec.script}", "runtime_sec": round(time.monotonic() - analyzer_started, 6), "output_path": str(self.artifacts[spec.output])}
                records.append(record); state[spec.name] = "failed"
                if report["first_failure"] is None:
                    report["first_failure"] = {"analyzer": spec.name, "failure_class": record["failure_class"], "error": record["error"]}
                self._write_report(report)
                continue

            inputs, fingerprint, interpreter_identity_sha256, command_profile_sha256 = self._input_identity(spec)
            prior = previous_records.get(spec.name, {})
            if spec.name not in forced and self._can_reuse(spec, prior, fingerprint):
                value, version = self._validate_output(spec)
                output = self.artifacts[spec.output]
                record = {"analyzer": spec.name, "analyzer_version": version, "status": "reused", "input_paths": inputs, "input_fingerprint": fingerprint, "script_path": spec.script, "script_sha256": _sha256(script), "interpreter_role": spec.interpreter, "interpreter_identity_sha256": interpreter_identity_sha256, "command_profile_sha256": command_profile_sha256, "output_path": str(output), "output_bytes": output.stat().st_size, "output_sha256": _sha256(output), "output_bundle_fingerprint": self._output_bundle_fingerprint(spec, value), "runtime_sec": round(time.monotonic() - analyzer_started, 6), "failure_class": None, "error": None}
                records.append(record); state[spec.name] = "reused"; self._write_report(report); continue

            try:
                result = self.runner(self._command(spec))
                if result.returncode != 0:
                    raise RuntimeError(f"analyzer exited with code {result.returncode}")
                if spec.name == "cuts":
                    self._write_cuts(result.stdout)
                value, version = self._validate_output(spec)
                output = self.artifacts[spec.output]
                record = {"analyzer": spec.name, "analyzer_version": version, "status": "generated", "input_paths": inputs, "input_fingerprint": fingerprint, "script_path": spec.script, "script_sha256": _sha256(script), "interpreter_role": spec.interpreter, "interpreter_identity_sha256": interpreter_identity_sha256, "command_profile_sha256": command_profile_sha256, "output_path": str(output), "output_bytes": output.stat().st_size, "output_sha256": _sha256(output), "output_bundle_fingerprint": self._output_bundle_fingerprint(spec, value), "runtime_sec": round(time.monotonic() - analyzer_started, 6), "failure_class": None, "error": None}
                records.append(record); state[spec.name] = "generated"
            except Exception as error:
                failure_class = "EXECUTION" if isinstance(error, RuntimeError) and "exited with code" in str(error) else "OUTPUT_CONTRACT"
                record = {"analyzer": spec.name, "status": "failed", "failure_class": failure_class, "error": str(error), "runtime_sec": round(time.monotonic() - analyzer_started, 6), "output_path": str(self.artifacts[spec.output])}
                records.append(record); state[spec.name] = "failed"
                if report["first_failure"] is None:
                    report["first_failure"] = {"analyzer": spec.name, "failure_class": failure_class, "error": str(error)}
            self._write_report(report)

        report["finished_at_utc"] = _utc_now()
        report["runtime_sec"] = round(time.monotonic() - started_clock, 6)
        report["summary"] = {status: sum(1 for record in records if record.get("status") == status) for status in ("generated", "reused", "failed", "blocked")}
        report["status"] = "failed" if report["first_failure"] else "success"
        self._write_report(report)
        if report["first_failure"]:
            raise AnalysisRunError(report)
        return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run canonical Video Cloner analyzers without planning or Resolve.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url")
    source.add_argument("--local-video")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--config")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-analyzer", action="append", choices=sorted(ANALYZER_BY_NAME), default=[])
    parser.add_argument("--print-contract", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = RuntimeConfig.load(args.project_root, args.config)
    input_spec = InputSpec.from_url(args.url) if args.url else InputSpec.from_local(args.local_video)
    context = build_run_context(input_spec, config)
    orchestrator = AnalysisOrchestrator(context)
    if args.print_contract:
        print(json.dumps(orchestrator.canonical_contract(), indent=2, sort_keys=True))
        return 0
    try:
        report = orchestrator.run(force=args.force, force_analyzers=args.force_analyzer)
    except AnalysisRunError as error:
        print(json.dumps(error.report, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
