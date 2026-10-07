from __future__ import annotations

import json

from video_cloner.config import RuntimeConfig, build_run_context
from video_cloner.contracts import ArtifactIdentity, InputSpec, StageResult, new_run_id


def test_config_exposes_explicit_workers_and_configurable_state(tmp_path):
    config = RuntimeConfig.load(
        tmp_path,
        environ={},
        overrides={
            "state_root": "runtime-state",
            "python_default": "core-python",
            "python_audio": "audio-python",
            "python_ocr": "ocr-python",
            "resolve_project_name": "configured-project",
            "target_timeline": "configured-timeline",
        },
    )
    assert config.state_root == (tmp_path / "runtime-state").resolve()
    assert config.runtime_workers()["core_python"] == "core-python"
    assert config.runtime_workers()["audio_python"] == "audio-python"
    assert config.runtime_workers()["ocr_python"] == "ocr-python"
    assert config.public_runtime()["resolve"]["project_name"] == "configured-project"


def test_run_identity_is_explicit_without_changing_legacy_context(tmp_path):
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"video")
    config = RuntimeConfig.load(tmp_path / "project", environ={})
    legacy = build_run_context(InputSpec.from_local(video), config)
    assert "run_id" not in legacy.public_contract()
    run_id = new_run_id(legacy.video_id)
    canonical = build_run_context(legacy.input_spec, config, run_id=run_id)
    assert canonical.public_contract()["run_id"] == run_id


def test_artifact_and_stage_contracts_capture_provenance(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps({"ok": True}), encoding="utf-8")
    identity = ArtifactIdentity.from_path(artifact, tmp_path)
    result = StageResult("analysis", "success", outputs=(identity,), runtime_identity={"python": "3.14"})
    document = result.as_dict()
    assert document["outputs"] == [identity.as_dict()]
    assert identity.path == "artifact.json"
    assert len(identity.sha256) == 64
