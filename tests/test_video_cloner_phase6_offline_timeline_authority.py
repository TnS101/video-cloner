import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from resolve_workspace.modules import video_cloner_phase6_readonly_preflight as preflight
from resolve_workspace.modules.video_cloner_phase6_textplus_application import load_phase5_contract


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "data" / "DcJRJtUKScu" / "davinci" / "offline_timeline_v1"
MANIFEST_NAME = "DcJRJtUKScu_offline_timeline_v1_manifest.json"


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resign(manifest):
    unsigned = dict(manifest)
    unsigned.pop("artifact_set_sha256", None)
    manifest["artifact_set_sha256"] = _fingerprint(unsigned)


@pytest.fixture
def package_copy():
    with tempfile.TemporaryDirectory(prefix="phase6_manifest_", dir=ROOT) as raw:
        target = Path(raw)
        for source in PACKAGE.iterdir():
            shutil.copy2(source, target / source.name)
        manifest_path = target / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text())
        for group in ("authorities", "outputs"):
            for identity in manifest[group].values():
                path = target / Path(identity["path"]).name
                identity.update(path=str(path), bytes=path.stat().st_size, sha256=_sha(path))
        _resign(manifest)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        yield target, manifest_path, manifest


def test_accepted_combined_manifest_resolves_exact_artifact():
    contract = load_phase5_contract(ROOT, PACKAGE / MANIFEST_NAME)
    assert contract["fcpxml_sha256"] == "e4ccc65a5ed1e7245d264333488390bfee68d32b3a116753223725f98143fd95"
    assert (len(contract["xml"]["cuts"]), len(contract["xml"]["audio_rows"]), len(contract["xml"]["titles"]), len(contract["xml"]["flash_handoffs"]), contract["xml"]["duration_frames"]) == (14, 1, 92, 1, 854)


def test_one_byte_artifact_change_fails_closed(package_copy):
    target, manifest_path, manifest = package_copy
    fcpxml = target / Path(manifest["outputs"]["fcpxml"]["path"]).name
    fcpxml.write_bytes(fcpxml.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="fcpxml_hash"):
        load_phase5_contract(ROOT, manifest_path)


def test_legacy_manifest_cannot_masquerade_as_combined(package_copy):
    _, manifest_path, _ = package_copy
    legacy = json.loads((ROOT / "data/DcJRJtUKScu/davinci/standalone_phase5/standalone_phase5_manifest.json").read_text())
    legacy["schema"] = "video_cloner.offline_timeline_v1_manifest.v1"
    _resign(legacy)
    manifest_path.write_text(json.dumps(legacy))
    with pytest.raises(ValueError, match="combined_manifest_identity"):
        load_phase5_contract(ROOT, manifest_path)


def test_wrong_caption_cardinality_fails_closed(package_copy):
    _, manifest_path, manifest = package_copy
    manifest["invariants"]["caption_count"] = 93
    _resign(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="combined_invariants"):
        load_phase5_contract(ROOT, manifest_path)


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_missing_or_duplicate_flash_fails_closed(package_copy, mode):
    target, manifest_path, manifest = package_copy
    transition_path = target / Path(manifest["authorities"]["transition"]["path"]).name
    transition = json.loads(transition_path.read_text())
    transition["flash_handoffs"] = [] if mode == "missing" else transition["flash_handoffs"] * 2
    transition_path.write_text(json.dumps(transition))
    transition_identity = manifest["authorities"]["transition"]
    transition_identity.update(bytes=transition_path.stat().st_size, sha256=_sha(transition_path))
    report_path = target / Path(manifest["outputs"]["report"]["path"]).name
    report = json.loads(report_path.read_text())
    report["inputs"]["transition_authority_sha256"] = _sha(transition_path)
    report_path.write_text(json.dumps(report))
    manifest["outputs"]["report"].update(bytes=report_path.stat().st_size, sha256=_sha(report_path))
    _resign(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="combined_transition_contract"):
        load_phase5_contract(ROOT, manifest_path)


def test_wrong_media_identity_fails_closed(package_copy):
    _, manifest_path, manifest = package_copy
    manifest["inputs"]["proxy"]["sha256"] = "0" * 64
    _resign(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="proxy_hash"):
        load_phase5_contract(ROOT, manifest_path)


def test_unexpected_executable_operation_fails_closed(package_copy):
    target, manifest_path, manifest = package_copy
    report_path = target / Path(manifest["outputs"]["report"]["path"]).name
    report = json.loads(report_path.read_text())
    report["compiled_operation_counts"]["speed"] = 1
    report_path.write_text(json.dumps(report))
    manifest["outputs"]["report"].update(bytes=report_path.stat().st_size, sha256=_sha(report_path))
    _resign(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="combined_executable_operations"):
        load_phase5_contract(ROOT, manifest_path)


class _Folder:
    def GetClipList(self): return []
    def GetSubFolderList(self): return []
    def GetName(self): return "Master"


class _Pool:
    def GetRootFolder(self): return _Folder()


class _Project:
    def GetName(self): return "New Project 1"
    def GetMediaPool(self): return _Pool()
    def GetCurrentTimeline(self): return None
    def GetTimelineCount(self): return 0


class _Manager:
    def GetCurrentProject(self): return _Project()


class _Resolve:
    def GetProjectManager(self): return _Manager()


def test_readonly_preflight_authenticates_without_mutation():
    contract = load_phase5_contract(ROOT, PACKAGE / MANIFEST_NAME)
    run_id = "offline_manifest_preflight"
    payload = {
        "action": preflight.ACTION, "read_only": True, "mutation_permitted": False,
        "import_permitted": False, "save_project": False, "delete_permitted": False,
        "relink_permitted": False, "replace_permitted": False, "metadata_controller_permitted": False,
        "repository_root": str(ROOT), "manifest_path": str(PACKAGE / MANIFEST_NAME),
        "selected_node": "textplus_full", "expected_project": "New Project 1",
        "target_timeline_name": contract["xml"]["timeline_name"],
        "artifact_set_sha256": contract["artifact_set_sha256"],
        "textplus_fingerprint": contract["textplus_fingerprint"],
        "fcpxml_sha256": contract["fcpxml_sha256"], "report_sha256": contract["report_sha256"],
    }
    command = {"task": preflight.TASK_ID, "run_id": run_id, "mode": preflight.MODE, "payload": payload}
    result = preflight.run(_Resolve(), {"run_id": run_id, "command": command})
    assert result["ok"] is True and result["package_verified"] is True and result["target_state"] == "ABSENT"
    assert result["v2_title_count"] == 92 and result["flash_handoff_count"] == 1
    assert result["mutation_counts"] == preflight.ZERO_MUTATIONS
