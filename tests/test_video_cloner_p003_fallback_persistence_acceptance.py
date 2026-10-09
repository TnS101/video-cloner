import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from resolve_workspace.modules import video_cloner_p003_post_reopen_verification as reopen
from resolve_workspace.modules import video_cloner_phase6_offline_timeline_live_application as finalizer


ROOT = Path(__file__).resolve().parents[1]
FINALIZER_MODULE = ROOT / "resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py"
VERIFIER_MODULE = ROOT / "resolve_workspace/modules/video_cloner_p003_post_reopen_verification.py"
GIT_EXE = ROOT / "git.exe"


class Timeline:
    def __init__(self, name=finalizer.TARGET_NAME, uid=finalizer.TARGET_UID):
        self.name, self.uid = name, uid

    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid


class Pool:
    def __init__(self, rows): self.rows = rows


class Project:
    def __init__(self, timeline_rows, media_rows, timelines=None):
        self.name = finalizer.PROJECT_NAME
        self.timeline_rows = timeline_rows
        self.pool = Pool(media_rows)
        self.timelines = timelines or [Timeline()]
        self.current = self.timelines[0]

    def GetName(self): return self.name
    def GetMediaPool(self): return self.pool
    def GetCurrentTimeline(self): return self.current


class Manager:
    def __init__(self, project, saved=True, after_save=None):
        self.project, self.saved, self.after_save, self.save_calls = project, saved, after_save, 0

    def GetCurrentProject(self): return self.project
    def SaveProject(self):
        self.save_calls += 1
        if self.after_save:
            self.after_save(self.project)
        return self.saved


class Resolve:
    def __init__(self, manager): self.manager = manager
    def GetProjectManager(self): return self.manager


def contract():
    titles = [
        {"name": f"caption-{index}", "text": f"word-{index}", "timeline_start": index * 2, "duration": 2, "lane": 1}
        for index in range(112)
    ]
    xml = {"timeline_name": finalizer.TARGET_NAME, "titles": titles, "flash_handoffs": []}
    return {
        "xml": xml,
        "artifact_set_sha256": "set",
        "textplus_fingerprint": "fingerprint",
        "fcpxml_sha256": "xml",
        "report_sha256": "report",
    }


def snapshot(rows=None, signature="target-signature"):
    rows = rows or [
        {
            "track_type": "video", "track_index": 2, "name": "Text", "start": index * 2,
            "end": index * 2 + 2, "duration": 2, "left_offset": None, "media_path": "", "title_text": None,
        }
        for index in range(112)
    ]
    return {
        "name": finalizer.TARGET_NAME,
        "unique_id": finalizer.TARGET_UID,
        "start_frame": 0,
        "end_frame": 673,
        "settings": {"timelineFrameRate": 24.0},
        "video_track_count": 2,
        "audio_track_count": 1,
        "items": rows,
        "signature": signature,
    }


def validation():
    return {"ok": True, "snapshot": snapshot(), "v1_clip_count": 8, "a1_clip_count": 1, "v2_title_count": 112, "flash_handoff_count": 0, "duration_frames": 673}


def inventories():
    target = {**snapshot(), "signature": "target-signature"}
    gold = {"name": finalizer.GOLD_NAME, "unique_id": finalizer.GOLD_UID, "signature": "gold", "items": []}
    timelines = [target, gold] + [
        {"name": f"protected-{index}", "unique_id": f"uid-{index}", "signature": f"p-{index}", "items": []}
        for index in range(44)
    ]
    media = [{"signature": f"media-{index}"} for index in range(55)]
    return timelines, media


def accepted_report():
    accepted = contract()
    timelines, media = inventories()
    overlays = [
        {
            "expected_text": row["text"], "title_text": None, "media_path": "", "name": "Text",
            "track": row["lane"] + 1, "start": row["timeline_start"],
            "end": row["timeline_start"] + row["duration"], "duration": row["duration"], "match_count": 1,
        }
        for row in accepted["xml"]["titles"]
    ]
    current = {"name": finalizer.TARGET_NAME, "unique_id": finalizer.TARGET_UID}
    structural = validation()
    return {
        "ok": True,
        "task_id": "VIDEO_CLONER_P002_LIVE_TARGET_FORENSIC_READBACK_V1",
        "run_id": finalizer.P002_RUN_ID,
        "mode": "p002_readonly_existing_target_forensics",
        "classification": "DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID",
        "fallback_eligible": True,
        "project_name": finalizer.PROJECT_NAME,
        "target_timeline_name": finalizer.TARGET_NAME,
        "target_unique_id": finalizer.TARGET_UID,
        "overlay_mapping_exact": True,
        "overlay_evidence": overlays,
        "strict_validation": {"failure": "ValueError: target_title", "ok": False, "result": None},
        "structural_validation": {"failure": None, "ok": True, "result": structural},
        "target_snapshot": structural["snapshot"],
        "zero_mutation_claim": True,
        "mutation_counts": {key: 0 for key in (
            "exports", "fusion_writes", "media_imports", "media_relinks", "media_replaces", "metadata_writes",
            "project_saves", "renders", "timeline_appends", "timeline_deletes", "timeline_imports", "timeline_selections", "title_writes",
        )},
        "failures": [],
        "current_timeline_before": current,
        "current_timeline_after": current,
        "current_timeline_unchanged": True,
        "timeline_inventory_before": timelines,
        "timeline_inventory_after": timelines,
        "timeline_inventory_unchanged": True,
        "media_pool_inventory_before": media,
        "media_pool_inventory_after": media,
        "media_pool_inventory_unchanged": True,
        "artifact_set_sha256": "set",
        "textplus_fingerprint": "fingerprint",
        "fcpxml_sha256": "xml",
        "report_sha256": "report",
    }


def test_exact_p002_fallback_evidence_is_accepted():
    accepted = contract()
    finalizer._validate_p002_report(accepted_report(), accepted, {key: accepted[key] for key in ("artifact_set_sha256", "textplus_fingerprint", "fcpxml_sha256", "report_sha256")})


@pytest.mark.parametrize("mutation", [
    "run", "uid", "classification", "fallback", "missing_overlay", "text", "geometry", "media_path",
    "strict", "structural", "mutation_counter",
])
def test_incomplete_or_contradictory_p002_evidence_fails(mutation):
    accepted = contract()
    report = copy.deepcopy(accepted_report())
    if mutation == "run": report["run_id"] = "wrong"
    elif mutation == "uid": report["target_unique_id"] = "wrong"
    elif mutation == "classification": report["classification"] = "wrong"
    elif mutation == "fallback": report["fallback_eligible"] = False
    elif mutation == "missing_overlay": report["overlay_evidence"].pop()
    elif mutation == "text": report["overlay_evidence"][0]["expected_text"] = "wrong"
    elif mutation == "geometry": report["overlay_evidence"][0]["start"] += 1
    elif mutation == "media_path": report["overlay_evidence"][0]["media_path"] = "title.mov"
    elif mutation == "strict": report["strict_validation"]["failure"] = "ValueError: other"
    elif mutation == "structural": report["structural_validation"]["ok"] = False
    else: report["mutation_counts"]["project_saves"] = 1
    declared = {key: accepted[key] for key in ("artifact_set_sha256", "textplus_fingerprint", "fcpxml_sha256", "report_sha256")}
    with pytest.raises(ValueError):
        finalizer._validate_p002_report(report, accepted, declared)


def test_evidence_hash_mismatch_fails(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"ok": True}), encoding="utf-8")
    monkeypatch.setattr(finalizer, "EVIDENCE_FILES", {"one": (evidence.name, "wrong")})
    with pytest.raises(ValueError, match="evidence_identity:one"):
        finalizer._authenticate_files(tmp_path)


def command(module_sha="module"):
    accepted = contract()
    payload = {
        "action": finalizer.ACTION, "save_once": True, "import_permitted": False, "save_project": True,
        "close_project_permitted": False, "timeline_selection_permitted": False, "delete_permitted": False,
        "rename_permitted": False, "append_permitted": False, "title_write_permitted": False,
        "fusion_write_permitted": False, "relink_permitted": False, "replace_permitted": False,
        "media_import_permitted": False, "export_permitted": False, "render_permitted": False,
        "metadata_write_permitted": False, "retry_permitted": False, "repository_root": str(ROOT),
        "expected_repository_head": "head", "git_executable_path": str(GIT_EXE),
        "git_executable_sha256": "git-sha", "finalizer_module_sha256": module_sha,
        "manifest_path": finalizer.EVIDENCE_FILES["manifest"][0], "manifest_sha256": finalizer.MANIFEST_SHA256,
        "selected_node": finalizer.base.NODE, "expected_project": finalizer.PROJECT_NAME,
        "target_timeline_name": finalizer.TARGET_NAME, "expected_target_uid": finalizer.TARGET_UID,
        **{key: accepted[key] for key in ("artifact_set_sha256", "textplus_fingerprint", "fcpxml_sha256", "report_sha256")},
    }
    return {"task": finalizer.TASK_ID, "run_id": "p003", "mode": finalizer.MODE, "payload": payload}


def execute_finalizer(monkeypatch, saved=True, before=None, after_save=None, timelines=None, git_values=None, command_value=None, git_error=None):
    accepted = accepted_report()
    timeline_rows, media_rows = inventories()
    if before:
        before(timeline_rows, media_rows)
    project = Project(timeline_rows, media_rows, timelines)
    manager = Manager(project, saved=saved, after_save=after_save)
    git_values = git_values or {"branch": "main", "rev-parse": "head"}
    if git_error:
        monkeypatch.setattr(finalizer, "_authenticated_git", lambda payload: (_ for _ in ()).throw(ValueError(git_error)))
    else:
        monkeypatch.setattr(finalizer, "_authenticated_git", lambda payload: GIT_EXE)
    monkeypatch.setattr(finalizer, "_git_value", lambda root, executable, *args: git_values[args[0]])
    monkeypatch.setattr(finalizer.base, "_sha256", lambda path: "module")
    monkeypatch.setattr(finalizer, "_fixed_path", lambda root, key: (ROOT / command()["payload"]["manifest_path"]).resolve())
    monkeypatch.setattr(finalizer.base, "load_phase5_contract", lambda *args: contract())
    monkeypatch.setattr(finalizer, "_accepted_evidence", lambda *args: accepted)
    monkeypatch.setattr(finalizer.base, "_timelines", lambda project: project.timelines)
    monkeypatch.setattr(finalizer.base, "_timeline_inventory", lambda project: copy.deepcopy(project.timeline_rows))
    monkeypatch.setattr(finalizer.base, "_media_pool_inventory", lambda pool: copy.deepcopy(pool.rows))
    monkeypatch.setattr(finalizer.base, "validate_target", lambda *args, **kwargs: validation())
    result = finalizer.run(Resolve(manager), {"run_id": "p003", "command": command_value or command()})
    return result, manager


def test_finalizer_validates_then_saves_exactly_once(monkeypatch):
    result, manager = execute_finalizer(monkeypatch)
    assert result["ok"] is True
    assert result["semantic_acceptance"]["policy"] == finalizer.POLICY
    assert result["mutation_counts"]["saves"] == manager.save_calls == 1


@pytest.mark.parametrize("module", [finalizer, reopen])
def test_valid_absolute_git_binding_is_authenticated(module, tmp_path):
    executable = tmp_path / "git.exe"
    executable.write_bytes(b"trusted git")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    assert module._authenticated_git({"git_executable_path": str(executable), "git_executable_sha256": digest}) == executable.resolve()


@pytest.mark.parametrize("module", [finalizer, reopen])
@pytest.mark.parametrize("case", ["missing", "relative", "path_only", "hash", "swapped"])
def test_invalid_git_binding_fails_closed(module, tmp_path, case):
    executable = tmp_path / "git.exe"
    executable.write_bytes(b"trusted git")
    payload = {
        "git_executable_path": str(executable),
        "git_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }
    if case == "missing":
        payload["git_executable_path"] = str(tmp_path / "missing.exe")
    elif case == "relative":
        payload["git_executable_path"] = "git.exe"
    elif case == "path_only":
        payload.pop("git_executable_sha256")
    elif case == "hash":
        payload["git_executable_sha256"] = "wrong"
    else:
        swapped = tmp_path / "swapped.exe"
        swapped.write_bytes(b"different executable")
        payload["git_executable_path"] = str(swapped)
    with pytest.raises(ValueError, match="git_executable_identity"):
        module._authenticated_git(payload)


@pytest.mark.parametrize("module", [finalizer, reopen])
def test_git_nonzero_exit_fails_without_path_fallback(module, monkeypatch):
    class Completed:
        returncode, stdout = 1, ""

    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)) or Completed())
    executable = GIT_EXE.resolve()
    with pytest.raises(ValueError, match="repository_git_identity"):
        module._git_value(ROOT, executable, "rev-parse", "HEAD")
    assert calls[0][0] == [str(executable), "rev-parse", "HEAD"]
    assert calls[0][1]["cwd"] == str(ROOT)


@pytest.mark.parametrize("git_values", [
    {"branch": "wrong", "rev-parse": "head"},
    {"branch": "main", "rev-parse": "wrong"},
])
def test_wrong_repository_git_identity_fails_before_save(monkeypatch, git_values):
    result, manager = execute_finalizer(monkeypatch, git_values=git_values)
    assert result["failures"] == ["ValueError: repository_git_identity"]
    assert manager.save_calls == 0


def test_wrong_repository_root_fails_before_git_or_save(monkeypatch, tmp_path):
    cmd = command()
    cmd["payload"]["repository_root"] = str(tmp_path)
    result, manager = execute_finalizer(monkeypatch, command_value=cmd)
    assert result["failures"] == ["ValueError: repository_identity"]
    assert manager.save_calls == 0


def test_git_executable_rejection_precedes_resolve_and_save(monkeypatch):
    result, manager = execute_finalizer(monkeypatch, git_error="git_executable_identity")
    assert result["failures"] == ["ValueError: git_executable_identity"]
    assert manager.save_calls == 0


@pytest.mark.parametrize("drift", ["target", "protected", "media"])
def test_pre_save_drift_fails_before_save(monkeypatch, drift):
    def mutate(timelines, media):
        if drift == "target": timelines[0]["items"][0]["duration"] += 1
        elif drift == "protected": timelines[1]["unique_id"] = "wrong"
        else: media[0]["signature"] = "wrong"
    result, manager = execute_finalizer(monkeypatch, before=mutate)
    assert result["ok"] is False
    assert manager.save_calls == 0


def test_save_failure_fails_after_one_attempt(monkeypatch):
    result, manager = execute_finalizer(monkeypatch, saved=False)
    assert result["failures"] == ["ValueError: save_project"]
    assert result["mutation_counts"]["saves"] == manager.save_calls == 1


@pytest.mark.parametrize("drift", ["target", "protected", "media"])
def test_immediate_post_save_drift_fails(monkeypatch, drift):
    def mutate(project):
        if drift == "target": project.timeline_rows[0]["items"][0]["duration"] += 1
        elif drift == "protected": project.timeline_rows[1]["unique_id"] = "wrong"
        else: project.pool.rows[0]["signature"] = "wrong"
    result, manager = execute_finalizer(monkeypatch, after_save=mutate)
    assert result["ok"] is False
    assert manager.save_calls == 1


def saved_state():
    timelines, media = inventories()
    return {"current_timeline": {"name": finalizer.TARGET_NAME, "unique_id": finalizer.TARGET_UID}, "timeline_inventory": timelines, "media_pool_inventory": media, "target_validation": validation()}


def execute_verifier(monkeypatch, drift=None):
    timelines, media = inventories()
    live_timelines = [Timeline()]
    if drift == "target": live_timelines = [Timeline(uid="wrong")]
    elif drift == "protected": timelines[1]["unique_id"] = "wrong"
    elif drift == "media": media[0]["signature"] = "wrong"
    project = Project(timelines, media, live_timelines)
    manager = Manager(project)
    monkeypatch.setattr(reopen, "_authenticated_git", lambda payload: GIT_EXE)
    monkeypatch.setattr(reopen, "_git_value", lambda root, executable, *args: "main" if args[0] == "branch" else "head")
    monkeypatch.setattr(reopen.base, "_sha256", lambda path: "module")
    monkeypatch.setattr(reopen, "_repository_path", lambda *args: VERIFIER_MODULE)
    monkeypatch.setattr(reopen.base, "load_phase5_contract", lambda *args: contract())
    monkeypatch.setattr(reopen, "_saved_baseline", lambda *args: ({}, saved_state()))
    monkeypatch.setattr(reopen.base, "_timelines", lambda project: project.timelines)
    monkeypatch.setattr(reopen.base, "_timeline_inventory", lambda project: copy.deepcopy(project.timeline_rows))
    monkeypatch.setattr(reopen.base, "_media_pool_inventory", lambda pool: copy.deepcopy(pool.rows))
    monkeypatch.setattr(reopen.base, "validate_target", lambda *args, **kwargs: validation())
    payload = {
        "action": reopen.ACTION, "read_only": True, "zero_mutation": True, "save_project": False,
        "import_permitted": False, "timeline_selection_permitted": False, "delete_permitted": False,
        "rename_permitted": False, "append_permitted": False, "title_write_permitted": False,
        "fusion_write_permitted": False, "media_import_permitted": False, "relink_permitted": False,
        "replace_permitted": False, "export_permitted": False, "render_permitted": False,
        "metadata_write_permitted": False, "retry_permitted": False, "repository_root": str(ROOT),
        "expected_repository_head": "head", "git_executable_path": str(GIT_EXE),
        "git_executable_sha256": "git-sha", "verifier_module_sha256": "module",
        "manifest_path": "manifest.json", "manifest_sha256": "module",
        "expected_project": reopen.PROJECT_NAME, "target_timeline_name": reopen.TARGET_NAME,
        "expected_target_uid": reopen.TARGET_UID, "finalizer_report_path": "report.json",
        "finalizer_report_sha256": "report", "expected_finalizer_run_id": "finalizer",
        "artifact_set_sha256": "set", "textplus_fingerprint": "fingerprint", "fcpxml_sha256": "xml", "report_sha256": "report",
    }
    cmd = {"task": reopen.TASK_ID, "run_id": "reopen", "mode": reopen.MODE, "payload": payload}
    return reopen.run(Resolve(manager), {"run_id": "reopen", "command": cmd})


def test_read_only_reopen_verifier_accepts_saved_state(monkeypatch):
    result = execute_verifier(monkeypatch)
    assert result["ok"] is True
    assert result["mutation_counts"] == reopen.MUTATION_COUNTS


@pytest.mark.parametrize(("drift", "failure"), [
    ("target", "target_persistence_drift"),
    ("protected", "protected_timeline_drift"),
    ("media", "media_pool_drift"),
])
def test_read_only_reopen_verifier_rejects_drift(monkeypatch, drift, failure):
    assert execute_verifier(monkeypatch, drift)["failures"] == [f"ValueError: {failure}"]


def test_reopen_verifier_has_no_prohibited_mutation_call_surface():
    prohibited = {
        "ImportTimelineFromFile", "SaveProject", "SetCurrentTimeline", "DeleteTimelines", "AppendToTimeline",
        "AddFusionComp", "AddTool", "SetInput", "SetProperty", "SetMetadata", "RelinkClips", "ReplaceClip",
        "ImportMedia", "ExportTimeline", "AddRenderJob", "StartRendering",
    }
    tree = ast.parse(VERIFIER_MODULE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not prohibited & (called | literals)


@pytest.mark.parametrize("module_path", [FINALIZER_MODULE, VERIFIER_MODULE])
def test_repository_identity_has_no_bare_git_fallback(module_path):
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    argv = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.List, ast.Tuple))
        and node.elts
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "git"
    ]
    assert argv == []
