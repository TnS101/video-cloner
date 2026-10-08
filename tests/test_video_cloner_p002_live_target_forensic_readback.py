import ast
from pathlib import Path

import pytest

from resolve_workspace.modules import video_cloner_p002_live_target_forensic_readback as forensic


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "resolve_workspace/modules/video_cloner_p002_live_target_forensic_readback.py"


class Tool:
    def __init__(self, text): self.text = text
    def GetAttrs(self): return {"TOOLS_RegID": "TextPlus"}
    def GetInput(self, name, *args): return self.text if name == "StyledText" else None


class Comp:
    def __init__(self, text): self.tool = Tool(text)
    def GetToolList(self, *args): return {"Text1": self.tool}


class Media:
    def __init__(self, path): self.path = path
    def GetClipProperty(self): return {"File Path": str(self.path)}


class Item:
    def __init__(self, name, start, duration, media=None, text=None):
        self.name, self.start, self.duration, self.media, self.text = name, start, duration, media, text
    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.start + self.duration
    def GetDuration(self): return self.duration
    def GetLeftOffset(self): return self.start
    def GetMediaPoolItem(self): return self.media
    def GetProperty(self): return {}
    def GetFusionCompCount(self): return 0
    def GetFusionCompNameList(self): return ["Composition 1"] if self.text is not None else []
    def GetFusionCompByName(self, name): return Comp(self.text) if name == "Composition 1" else None


class Folder:
    def GetName(self): return "root"
    def GetClipList(self): return []
    def GetSubFolderList(self): return []


class Pool:
    def GetRootFolder(self): return Folder()


class Timeline:
    def __init__(self, contract, uid="target", texts=None, title_media=""):
        self.contract, self.uid = contract, uid
        self.video = {1: [Item("cut", 0, 20, Media(contract["proxy"]))]}
        overlays = contract["titles"] + contract["flash_handoffs"]
        texts = [row["text"] for row in overlays] if texts is None else texts
        for row, text in zip(overlays, texts):
            media = Media(title_media) if title_media else None
            self.video.setdefault(row["lane"] + 1, []).append(Item("Text", row["timeline_start"], row["duration"], media, text))
        self.audio = {1: [Item("audio", 0, 20, Media(contract["audio"]))]}
    def GetName(self): return self.contract["timeline_name"]
    def GetUniqueId(self): return self.uid
    def GetTrackCount(self, kind): return max((self.video if kind == "video" else self.audio), default=0)
    def GetItemListInTrack(self, kind, track): return list((self.video if kind == "video" else self.audio).get(track, []))
    def GetStartFrame(self): return 0
    def GetEndFrame(self): return 20
    def GetSetting(self, key): return "24"


class Project:
    def __init__(self, timelines, name="New Project 1"):
        self.timelines, self.name, self.pool = timelines, name, Pool()
        self.current = timelines[0] if timelines else None
    def GetName(self): return self.name
    def GetMediaPool(self): return self.pool
    def GetCurrentTimeline(self): return self.current
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, index): return self.timelines[index - 1]


class Manager:
    def __init__(self, project): self.project = project
    def GetCurrentProject(self): return self.project


class Resolve:
    def __init__(self, project): self.manager = Manager(project)
    def GetProjectManager(self): return self.manager


@pytest.fixture
def contract(tmp_path):
    return {
        "timeline_name": "target", "fps": 24, "duration_frames": 20,
        "proxy": tmp_path / "proxy.mp4", "audio": tmp_path / "audio.wav",
        "cuts": [{"name": "cut", "timeline_start": 0, "source_start": 0, "duration": 20}],
        "audio_rows": [{"name": "audio", "timeline_start": 0, "source_start": 0, "duration": 20}],
        "titles": [
            {"name": "a", "text": "hello", "timeline_start": 0, "duration": 5, "lane": 1},
            {"name": "b", "text": "world", "timeline_start": 5, "duration": 5, "lane": 1},
        ],
        "title_lanes": [1],
        "flash_handoffs": [{"name": "flash", "text": " ", "timeline_start": 10, "duration": 3, "lane": 2}],
    }


def command(tmp_path, contract):
    declared = {"artifact_set_sha256": "set", "textplus_fingerprint": "fingerprint", "fcpxml_sha256": "xml", "report_sha256": "report"}
    payload = {
        "action": forensic.ACTION, "read_only": True, "zero_mutation": True,
        "import_permitted": False, "save_project": False, "timeline_selection_permitted": False,
        "delete_permitted": False, "append_permitted": False, "title_write_permitted": False,
        "fusion_write_permitted": False, "media_import_permitted": False, "relink_permitted": False,
        "replace_permitted": False, "export_permitted": False, "render_permitted": False,
        "metadata_write_permitted": False, "retry_permitted": False,
        "repository_root": str(ROOT), "manifest_path": str(tmp_path / "manifest.json"),
        "expected_project": "New Project 1", "target_timeline_name": contract["timeline_name"], **declared,
    }
    return {"task": forensic.TASK_ID, "run_id": "p002", "mode": forensic.MODE, "payload": payload}, declared


def execute(monkeypatch, tmp_path, contract, timelines):
    cmd, declared = command(tmp_path, contract)
    monkeypatch.setattr(forensic.base, "load_phase5_contract", lambda *_: {"xml": contract, **declared})
    return forensic.run(Resolve(Project(timelines)), {"run_id": "p002", "command": cmd})


def test_direct_textplus_readback_passes_strict_validation_without_mutation(monkeypatch, tmp_path, contract):
    result = execute(monkeypatch, tmp_path, contract, [Timeline(contract)])
    assert result["ok"] is True
    assert result["strict_validation"]["ok"] is True
    assert [row["title_text"] for row in result["overlay_evidence"]] == ["hello", "world", " "]
    assert result["classification"] == "FORENSIC_EVIDENCE_INSUFFICIENT"
    assert result["mutation_counts"] == forensic.MUTATION_COUNTS
    assert result["current_timeline_unchanged"] and result["timeline_inventory_unchanged"] and result["media_pool_inventory_unchanged"]


def test_unobservable_title_text_is_structurally_valid_and_fallback_eligible(monkeypatch, tmp_path, contract):
    result = execute(monkeypatch, tmp_path, contract, [Timeline(contract, texts=[None, None, None])])
    assert result["classification"] == "DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID"
    assert result["strict_validation"]["failure"] == "ValueError: target_title"
    assert result["structural_validation"]["ok"] is True
    assert result["fallback_eligible"] is True


def test_wrong_observed_text_is_classified(monkeypatch, tmp_path, contract):
    result = execute(monkeypatch, tmp_path, contract, [Timeline(contract, texts=["wrong", "world", " "])])
    assert result["classification"] == "DIRECT_TITLE_TEXT_MISMATCH"
    assert result["fallback_eligible"] is False


def test_nonempty_title_media_path_is_classified(monkeypatch, tmp_path, contract):
    result = execute(monkeypatch, tmp_path, contract, [Timeline(contract, title_media=tmp_path / "title.mov")])
    assert result["classification"] == "TITLE_MEDIA_PATH_CONTAMINATION"
    assert result["structural_validation"]["failure"] == "ValueError: target_title"


def test_structural_mismatch_is_classified(monkeypatch, tmp_path, contract):
    timeline = Timeline(contract, texts=[None, None, None])
    timeline.video[2][0].duration += 1
    result = execute(monkeypatch, tmp_path, contract, [timeline])
    assert result["classification"] == "STRUCTURAL_TARGET_MISMATCH"
    assert result["structural_validation"]["ok"] is False


def test_partial_observability_fails_closed(monkeypatch, tmp_path, contract):
    result = execute(monkeypatch, tmp_path, contract, [Timeline(contract, texts=["hello", None, None])])
    assert result["classification"] == "FORENSIC_EVIDENCE_INSUFFICIENT"
    assert result["fallback_eligible"] is False


@pytest.mark.parametrize("case", ["wrong_project", "missing", "duplicate"])
def test_wrong_or_nonunique_identity_fails_closed(monkeypatch, tmp_path, contract, case):
    timelines = [] if case == "missing" else [Timeline(contract)]
    if case == "duplicate": timelines.append(Timeline(contract, uid="duplicate"))
    cmd, declared = command(tmp_path, contract)
    monkeypatch.setattr(forensic.base, "load_phase5_contract", lambda *_: {"xml": contract, **declared})
    project = Project(timelines, name="Wrong" if case == "wrong_project" else "New Project 1")
    result = forensic.run(Resolve(project), {"run_id": "p002", "command": cmd})
    assert result["ok"] is False
    assert result["classification"] == "FORENSIC_EVIDENCE_INSUFFICIENT"


def test_explicit_read_only_flags_are_required(monkeypatch, tmp_path, contract):
    cmd, _ = command(tmp_path, contract)
    cmd["payload"]["save_project"] = True
    result = forensic.run(object(), {"run_id": "p002", "command": cmd})
    assert result["failures"] == ["ValueError: read_only_authority"]


def test_source_has_no_prohibited_mutation_call_surface():
    prohibited = {
        "ImportTimelineFromFile", "SaveProject", "SetCurrentTimeline", "DeleteTimelines", "AppendToTimeline",
        "AddFusionComp", "AddTool", "SetInput", "SetProperty", "SetMetadata", "RelinkClips", "ReplaceClip",
        "ImportMedia", "ExportTimeline", "AddRenderJob", "StartRendering",
    }
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    safe_method_literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not prohibited & (called | safe_method_literals)
