from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from video_cloner.config import RuntimeConfig, build_run_context
from video_cloner.contracts import InputSpec, RunContext


REPORT_SCHEMA = "video_cloner.planning_run.v1"


@dataclass(frozen=True)
class StageSpec:
    name: str
    script: str
    inputs: tuple[str, ...]
    output: str


STAGES = (
    StageSpec("merge", "video_cloner/planning/merge.py", ("transitions", "beatmap", "shots", "motion", "transcript", "caption_style", "caption_occlusion"), "analysis"),
    StageSpec("plan", "video_cloner/planning/plan.py", ("analysis",), "edit_plan"),
    StageSpec("validate", "video_cloner/planning/validate.py", ("analysis", "edit_plan"), "validated_edit_plan"),
    StageSpec("compile", "video_cloner/planning/compile.py", ("analysis", "validated_edit_plan"), "generic_edit_commands"),
)
STAGE_BY_NAME = {stage.name: stage for stage in STAGES}
REQUIRED_MERGE_INPUTS = ("transitions", "beatmap", "shots", "motion")
OPTIONAL_MERGE_INPUTS = ("transcript", "caption_style", "caption_occlusion")


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


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _read_json(path: Path, label: str) -> object:
    if not _nonempty(path):
        raise RuntimeError(f"missing or empty {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"malformed JSON for {label}: {path}") from error


class PlanningRunError(RuntimeError):
    def __init__(self, report: Mapping[str, object]):
        self.report = dict(report)
        failure = self.report.get("first_failure")
        if isinstance(failure, Mapping):
            message = f"planning failed at {failure.get('stage', 'unknown')}: {failure.get('error', 'unknown failure')}"
        else:
            message = "planning failed"
        super().__init__(message)


class PlanningOrchestrator:
    def __init__(self, context: RunContext, transition_authority: str | Path, runner: Runner = _default_runner):
        self.context = context
        self.runner = runner
        self.transition_authority = Path(transition_authority).expanduser().resolve()
        video_id = context.video_id
        analysis = context.analysis_dir
        planning = context.planning_dir
        self.artifacts: dict[str, Path] = {
            "transitions": self.transition_authority,
            "beatmap": analysis / f"{video_id}_beatmap.json",
            "shots": analysis / f"{video_id}_shots.json",
            "motion": analysis / f"{video_id}_motion.json",
            "transcript": analysis / f"{video_id}_transcript.json",
            "caption_style": analysis / f"{video_id}_caption_style.json",
            "caption_occlusion": analysis / f"{video_id}_caption_occlusion.json",
            "analysis": analysis / f"{video_id}_analysis.json",
            "edit_plan": planning / f"{video_id}_edit_plan.json",
            "validated_edit_plan": planning / f"{video_id}_validated_edit_plan.json",
            "generic_edit_commands": planning / f"{video_id}_generic_edit_commands.json",
        }
        self.report_path = planning / f"{video_id}_planning_run.json"

    def canonical_contract(self) -> dict[str, object]:
        return {
            "schema": REPORT_SCHEMA,
            "video_id": self.context.video_id,
            "transition_authority": str(self.transition_authority),
            "artifacts": {key: str(path) for key, path in self.artifacts.items()},
            "stages": [{"name": stage.name, "script": stage.script, "inputs": list(stage.inputs), "output": stage.output} for stage in STAGES],
            "interpreter_role": "python_default",
            "report_path": str(self.report_path),
            "phase2_analyzers_invoked": False,
            "fcpxml_invoked": False,
            "resolve_invoked": False,
        }

    def _script_path(self, stage: StageSpec) -> Path:
        return (self.context.config.project_root / stage.script).resolve()

    def _interpreter(self) -> str:
        return str(self.context.config.python_default)

    def _command(self, stage: StageSpec) -> list[str]:
        a = self.artifacts
        command = [self._interpreter(), str(self._script_path(stage))]
        if stage.name == "merge":
            command.extend(["--transitions", str(a["transitions"]), "--beatmap", str(a["beatmap"]), "--shots", str(a["shots"]), "--motion", str(a["motion"])])
            for key, flag in (("transcript", "--transcript"), ("caption_style", "--caption-style"), ("caption_occlusion", "--caption-occlusion")):
                if _nonempty(a[key]):
                    command.extend([flag, str(a[key])])
            command.extend(["--output", str(a["analysis"]), "--job-id", self.context.video_id])
            return command
        if stage.name == "plan":
            return command + ["--analysis", str(a["analysis"]), "--output", str(a["edit_plan"]), "--model", self.context.config.ollama_model, "--skip-llm"]
        if stage.name == "validate":
            return command + ["--analysis", str(a["analysis"]), "--edit-plan", str(a["edit_plan"]), "--output", str(a["validated_edit_plan"]), "--strict", "true", "--strict-metadata", "true", "--enforce-expected-action", "true", "--validate-rich-contract", "true"]
        if stage.name == "compile":
            return command + ["--analysis", str(a["analysis"]), "--validated-edit-plan", str(a["validated_edit_plan"]), "--output", str(a["generic_edit_commands"]), "--subtitle-source", "words"]
        raise ValueError(f"unsupported stage: {stage.name}")

    def _load_previous(self) -> dict[str, object]:
        if not _nonempty(self.report_path):
            return {}
        try:
            value = json.loads(self.report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) and value.get("schema") == REPORT_SCHEMA else {}

    def _write_report(self, report: Mapping[str, object]) -> None:
        self.context.planning_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.report_path.with_suffix(self.report_path.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.report_path)

    @staticmethod
    def _explicit_video_ids(value: object) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"video_id", "job_id"} and isinstance(child, str) and child.strip():
                    found.add(child.strip())
                elif isinstance(child, (dict, list)):
                    found.update(PlanningOrchestrator._explicit_video_ids(child))
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    found.update(PlanningOrchestrator._explicit_video_ids(child))
        return found

    def _validate_transition_authority(self, value: object) -> None:
        if not isinstance(value, dict) or value.get("success") is not True or value.get("schema") != "video_cloner_transitions":
            raise RuntimeError("transition authority does not match the accepted transitions schema")
        rows = value.get("transitions")
        if not isinstance(rows, list):
            raise RuntimeError("transition authority rows are malformed")
        if not rows:
            summary = value.get("transition_summary")
            meta = value.get("_meta")
            counts = [value.get(key) for key in ("shot_count", "boundaries_total", "boundaries_attempted", "transition_count")]
            if (
                value.get("schema_version") != "2.0"
                or not all(isinstance(count, int) and not isinstance(count, bool) and count >= 0 for count in counts)
                or value.get("shot_count") < 1
                or value.get("boundaries_total") != max(0, int(value.get("shot_count")) - 1)
                or value.get("boundaries_attempted") != value.get("boundaries_total")
                or value.get("transition_count") != 0
                or value.get("skipped") != []
                or value.get("quality_flags") != []
                or not isinstance(summary, dict)
                or summary.get("boundaries_total") != value.get("boundaries_total")
                or summary.get("transition_count") != 0
                or summary.get("skipped_count") != 0
                or summary.get("ready_for_merge_analysis") is not True
                or summary.get("ready_for_generic_compiler") is not True
                or not isinstance(meta, dict)
                or meta.get("safe_for_merge_analysis") is not True
            ):
                raise RuntimeError("empty transition authority is incomplete or inconsistent")
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("transition authority contains a malformed row")
            kind = str(row.get("transition_type") or "")
            if kind in {"whip_pan", "slide_transition"}:
                raise RuntimeError(f"transition authority contains executable rejected transition type: {kind}")
            if kind in {"whip_pan_candidate", "slide_transition_candidate"}:
                if row.get("editor_actionable") is not False or row.get("duration_frames") != 0 or float(row.get("duration_seconds", -1)) != 0.0:
                    raise RuntimeError(f"candidate transition is executable: {kind}")
                context = (row.get("scores") or {}).get("directional_context") if isinstance(row.get("scores"), dict) else None
                if not isinstance(context, dict) or not isinstance(context.get("outgoing"), dict) or not isinstance(context.get("incoming"), dict):
                    raise RuntimeError(f"candidate transition lacks directional context: {kind}")

    def _validate_merge_inputs(self) -> None:
        for key in REQUIRED_MERGE_INPUTS:
            value = _read_json(self.artifacts[key], f"merge input {key}")
            if key == "shots" and not isinstance(value, list):
                raise RuntimeError("shots merge input must be a JSON list")
            if key != "shots" and not isinstance(value, dict):
                raise RuntimeError(f"{key} merge input must be a JSON object")
            ids = self._explicit_video_ids(value)
            if ids and ids != {self.context.video_id}:
                raise RuntimeError(f"video identity mismatch in {key}: {sorted(ids)}")
            if key == "transitions":
                self._validate_transition_authority(value)
        for key in OPTIONAL_MERGE_INPUTS:
            if _nonempty(self.artifacts[key]):
                value = _read_json(self.artifacts[key], f"optional merge input {key}")
                if not isinstance(value, dict):
                    raise RuntimeError(f"{key} merge input must be a JSON object")
                ids = self._explicit_video_ids(value)
                if ids and ids != {self.context.video_id}:
                    raise RuntimeError(f"video identity mismatch in {key}: {sorted(ids)}")

    @staticmethod
    def _transition_rows(analysis: Mapping[str, object]) -> list[Mapping[str, object]]:
        timeline = analysis.get("timeline")
        shots = timeline.get("shots") if isinstance(timeline, Mapping) else None
        if not isinstance(shots, list):
            return []
        return [row for shot in shots if isinstance(shot, Mapping) for row in [shot.get("transition_to_next")] if isinstance(row, Mapping)]

    @staticmethod
    def _operations(generic: Mapping[str, object]) -> list[Mapping[str, object]]:
        timeline = generic.get("timeline")
        if not isinstance(timeline, list):
            return []
        return [operation for command in timeline if isinstance(command, Mapping) for operation in (command.get("operations") or []) if isinstance(operation, Mapping)]

    def _validate_output(self, stage: StageSpec) -> tuple[object, str]:
        value = _read_json(self.artifacts[stage.output], f"{stage.name} output")
        if not isinstance(value, dict):
            raise RuntimeError(f"{stage.name} output must be a JSON object")
        video_id = self.context.video_id
        if stage.name == "merge":
            job = value.get("job")
            if value.get("success") is not True or not str(value.get("analysis_version") or "").startswith("merge_analysis_") or not isinstance(job, dict) or job.get("job_id") != video_id:
                raise RuntimeError("merged analysis contract is invalid")
            rows = self._transition_rows(value)
            for row in rows:
                kind = str(row.get("transition_type") or "")
                if kind in {"whip_pan", "slide_transition"} and row.get("editor_actionable") is True:
                    raise RuntimeError("merged analysis reactivated rejected whip/slide authority")
                if kind in {"whip_pan_candidate", "slide_transition_candidate"} and (row.get("editor_actionable") is not False or row.get("duration_frames") != 0):
                    raise RuntimeError("merged analysis corrupted candidate transition authority")
        elif stage.name == "plan":
            meta = value.get("_meta")
            if value.get("video_id") != video_id or not isinstance(value.get("timeline"), list) or not isinstance(meta, dict) or meta.get("skip_llm") is not True or meta.get("sanitized") is not True:
                raise RuntimeError("deterministic edit plan contract is invalid")
        elif stage.name == "validate":
            meta = value.get("_meta")
            if value.get("success") is not True or value.get("video_id") != video_id or value.get("analysis_video_id") != video_id or value.get("errors_count") != 0 or not isinstance(meta, dict) or meta.get("ready_for_compile_generic_edit_v2") is not True:
                raise RuntimeError("validated edit plan contract is invalid")
        elif stage.name == "compile":
            if value.get("success") is not True or value.get("schema") != "generic_edit_commands" or value.get("schema_version") != "2.0" or value.get("video_id") != video_id or not isinstance(value.get("timeline"), list) or not value.get("timeline"):
                raise RuntimeError("generic edit command contract is invalid")
            operations = self._operations(value)
            operation_names = {str(operation.get("operation") or "") for operation in operations}
            forbidden = {"speed_ramp", "transform_zoom"}
            if operation_names & forbidden or any("blur" in name.lower() for name in operation_names):
                raise RuntimeError("generic commands promoted rejected speed/zoom/blur authority")
            for operation in operations:
                if operation.get("operation") == "transition_hint":
                    transition_type = str((operation.get("parameters") or {}).get("transition_type") or "") if isinstance(operation.get("parameters"), dict) else ""
                    if transition_type in {"whip_pan", "whip_pan_candidate", "slide_transition", "slide_transition_candidate", "blur_transition"}:
                        raise RuntimeError(f"generic commands promoted rejected transition authority: {transition_type}")
            for command in value.get("timeline", []):
                if isinstance(command, dict) and not (command.get("source_start_frame") == command.get("timeline_start_frame") and command.get("source_end_frame") == command.get("timeline_end_frame") and command.get("source_duration_frames") == command.get("timeline_duration_frames")):
                    raise RuntimeError("generic commands do not preserve source/timeline mapping")
        version = str(value.get("analysis_version") or value.get("version") or value.get("planner_version") or value.get("validation_version") or value.get("compiler_version") or value.get("schema_version") or "")
        if not version:
            version = f"script_sha256:{_sha256(self._script_path(stage))[:16]}"
        return value, version

    def _stage_inputs(self, stage: StageSpec) -> tuple[str, ...]:
        if stage.name != "merge":
            return stage.inputs
        return tuple(key for key in stage.inputs if key in REQUIRED_MERGE_INPUTS or _nonempty(self.artifacts[key]))

    def _identity(self, stage: StageSpec) -> tuple[list[dict[str, object]], str, str, str]:
        inputs = []
        for key in self._stage_inputs(stage):
            path = self.artifacts[key]
            inputs.append({"artifact": key, "path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)})
        command = self._command(stage)
        interpreter_sha = _hash_text(command[0])
        profile_sha = _hash_text(json.dumps(command, ensure_ascii=False, separators=(",", ":")))
        identity = {"stage": stage.name, "script_sha256": _sha256(self._script_path(stage)), "interpreter_role": "python_default", "interpreter_identity_sha256": interpreter_sha, "command_profile_sha256": profile_sha, "inputs": inputs}
        fingerprint = _hash_text(json.dumps(identity, sort_keys=True, separators=(",", ":")))
        return inputs, fingerprint, interpreter_sha, profile_sha

    @staticmethod
    def _previous_records(previous: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        records = previous.get("stages")
        if not isinstance(records, list):
            return {}
        return {str(record.get("stage")): record for record in records if isinstance(record, Mapping)}

    def _can_reuse(self, stage: StageSpec, previous: Mapping[str, object], fingerprint: str) -> bool:
        output = self.artifacts[stage.output]
        if previous.get("status") not in {"generated", "reused"} or previous.get("input_fingerprint") != fingerprint:
            return False
        if not _nonempty(output) or previous.get("output_sha256") != _sha256(output):
            return False
        try:
            self._validate_output(stage)
        except RuntimeError:
            return False
        return True

    def authority_summary(self) -> dict[str, object]:
        analysis, _ = self._validate_output(STAGE_BY_NAME["merge"])
        generic, _ = self._validate_output(STAGE_BY_NAME["compile"])
        assert isinstance(analysis, dict) and isinstance(generic, dict)
        rows = self._transition_rows(analysis)
        operations = self._operations(generic)
        operation_counts: dict[str, int] = {}
        for operation in operations:
            name = str(operation.get("operation") or "")
            operation_counts[name] = operation_counts.get(name, 0) + 1
        candidate_frames: dict[str, list[int]] = {"whip_pan_candidate": [], "slide_transition_candidate": []}
        for row in rows:
            kind = str(row.get("transition_type") or "")
            if kind in candidate_frames and isinstance(row.get("cut_frame"), int):
                candidate_frames[kind].append(int(row["cut_frame"]))
        flash_hints = [operation for operation in operations if operation.get("operation") == "transition_hint" and isinstance(operation.get("parameters"), dict) and operation["parameters"].get("transition_type") == "flash_cut"]
        return {
            "operation_counts": operation_counts,
            "speed_operations": operation_counts.get("speed_ramp", 0),
            "zoom_operations": operation_counts.get("transform_zoom", 0),
            "generated_blur_operations": sum(count for name, count in operation_counts.items() if "blur" in name.lower()),
            "whip_candidate_count": len(candidate_frames["whip_pan_candidate"]),
            "whip_candidate_frames": sorted(candidate_frames["whip_pan_candidate"]),
            "slide_candidate_count": len(candidate_frames["slide_transition_candidate"]),
            "slide_candidate_frames": sorted(candidate_frames["slide_transition_candidate"]),
            "flash_transition_hints": len(flash_hints),
            "rejected_transition_operations": sum(1 for operation in operations if operation.get("operation") == "transition_hint" and str((operation.get("parameters") or {}).get("transition_type") or "") in {"whip_pan", "whip_pan_candidate", "slide_transition", "slide_transition_candidate", "blur_transition"}),
        }

    def run(self, force: bool = False, force_stages: Iterable[str] | None = None) -> dict[str, object]:
        requested = set(force_stages or ())
        unknown = requested - set(STAGE_BY_NAME)
        if unknown:
            raise ValueError(f"unknown forced stages: {sorted(unknown)}")
        forced = set(STAGE_BY_NAME) if force else requested
        self.context.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.context.planning_dir.mkdir(parents=True, exist_ok=True)
        previous_records = self._previous_records(self._load_previous())
        report: dict[str, object] = {"schema": REPORT_SCHEMA, "video_id": self.context.video_id, "started_at_utc": _utc_now(), "status": "running", "transition_authority": str(self.transition_authority), "stages": [], "first_failure": None, "phase2_analyzers_invoked": False, "network_invoked": False, "fcpxml_invoked": False, "resolve_invoked": False, "timeline_mutated": False}
        started = time.monotonic()
        records = report["stages"]
        assert isinstance(records, list)
        for stage in STAGES:
            stage_started = time.monotonic()
            try:
                script = self._script_path(stage)
                if not _nonempty(script):
                    raise RuntimeError(f"canonical stage script missing: {stage.script}")
                if stage.name == "merge":
                    self._validate_merge_inputs()
                inputs, fingerprint, interpreter_sha, profile_sha = self._identity(stage)
                prior = previous_records.get(stage.name, {})
                if stage.name not in forced and self._can_reuse(stage, prior, fingerprint):
                    _, version = self._validate_output(stage)
                    output = self.artifacts[stage.output]
                    record = {"stage": stage.name, "stage_version": version, "status": "reused", "input_paths": inputs, "input_fingerprint": fingerprint, "script_path": stage.script, "script_sha256": _sha256(script), "interpreter_role": "python_default", "interpreter_identity_sha256": interpreter_sha, "command_profile_sha256": profile_sha, "output_path": str(output), "output_bytes": output.stat().st_size, "output_sha256": _sha256(output), "runtime_sec": round(time.monotonic() - stage_started, 6), "failure_class": None, "error": None}
                    records.append(record)
                    self._write_report(report)
                    continue
                result = self.runner(self._command(stage))
                if result.returncode != 0:
                    raise RuntimeError(f"stage exited with code {result.returncode}")
                _, version = self._validate_output(stage)
                output = self.artifacts[stage.output]
                record = {"stage": stage.name, "stage_version": version, "status": "generated", "input_paths": inputs, "input_fingerprint": fingerprint, "script_path": stage.script, "script_sha256": _sha256(script), "interpreter_role": "python_default", "interpreter_identity_sha256": interpreter_sha, "command_profile_sha256": profile_sha, "output_path": str(output), "output_bytes": output.stat().st_size, "output_sha256": _sha256(output), "runtime_sec": round(time.monotonic() - stage_started, 6), "failure_class": None, "error": None}
                records.append(record)
                self._write_report(report)
            except Exception as error:
                failure_class = "EXECUTION" if "exited with code" in str(error) else "CONTRACT"
                record = {"stage": stage.name, "status": "failed", "failure_class": failure_class, "error": str(error), "runtime_sec": round(time.monotonic() - stage_started, 6), "output_path": str(self.artifacts[stage.output])}
                records.append(record)
                report["first_failure"] = {"stage": stage.name, "failure_class": failure_class, "error": str(error)}
                report["status"] = "failed"
                report["finished_at_utc"] = _utc_now()
                report["runtime_sec"] = round(time.monotonic() - started, 6)
                self._write_report(report)
                raise PlanningRunError(report) from error
        report["finished_at_utc"] = _utc_now()
        report["runtime_sec"] = round(time.monotonic() - started, 6)
        report["summary"] = {status: sum(1 for record in records if record.get("status") == status) for status in ("generated", "reused", "failed")}
        report["authority"] = self.authority_summary()
        report["status"] = "success"
        self._write_report(report)
        return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic Video Cloner authority planning without n8n, FCPXML, or Resolve.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url")
    source.add_argument("--local-video")
    parser.add_argument("--transition-authority", required=True)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--config")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-stage", action="append", choices=sorted(STAGE_BY_NAME), default=[])
    parser.add_argument("--print-contract", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = RuntimeConfig.load(args.project_root, args.config)
    input_spec = InputSpec.from_url(args.url) if args.url else InputSpec.from_local(args.local_video)
    context = build_run_context(input_spec, config)
    orchestrator = PlanningOrchestrator(context, args.transition_authority)
    if args.print_contract:
        print(json.dumps(orchestrator.canonical_contract(), indent=2, sort_keys=True))
        return 0
    try:
        report = orchestrator.run(force=args.force, force_stages=args.force_stage)
    except PlanningRunError as error:
        print(json.dumps(error.report, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
