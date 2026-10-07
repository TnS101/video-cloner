from collections import Counter
import hashlib
from pathlib import Path

import pytest

from resolve_workspace.modules import video_cloner_phase6_offline_timeline_live_application as live


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / ".agent/reports/VIDEO_CLONER_PHASE6_READONLY_PREFLIGHT_V1/PHASE6_CANONICAL_V1_READONLY_20260912T163528077Z_908ef71215214ccb8d85d96b41e4c82c/report.json"


class Object:
    def __init__(self, **values): self.__dict__.update(values)
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetMediaPool(self): return self.pool


class Tool:
    def __init__(self, text): self.text = text
    def GetAttrs(self): return {"TOOLS_RegID": "TextPlus"}
    def GetInput(self, name, *args): return self.text if name == "StyledText" else None


class Comp:
    def __init__(self, text): self.tool = Tool(text)
    def GetToolList(self, *args): return {"Text1": self.tool}


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


class Media:
    def __init__(self, path): self.path = path
    def GetClipProperty(self): return {"File Path": str(self.path)}


class Timeline:
    def __init__(self, contract, normalized=True):
        self.contract = contract
        self.video = {1: [Item("cut", 0, 20, Media(contract["proxy"]))]}
        for row in contract["titles"] + contract["flash_handoffs"]:
            self.video.setdefault(row["lane"] + 1, []).append(Item("Text" if normalized else row["name"], row["timeline_start"], row["duration"], text=row["text"]))
        self.audio = {1: [Item("audio", 0, 20, Media(contract["audio"]))]}
    def GetName(self): return self.contract["timeline_name"]
    def GetUniqueId(self): return "target"
    def GetTrackCount(self, kind): return max((self.video if kind == "video" else self.audio), default=0)
    def GetItemListInTrack(self, kind, track): return list((self.video if kind == "video" else self.audio).get(track, []))
    def GetStartFrame(self): return 0
    def GetEndFrame(self): return 20
    def GetSetting(self, key): return "24"


@pytest.fixture
def contract(tmp_path):
    proxy, audio = tmp_path / "proxy.mp4", tmp_path / "audio.wav"
    return {
        "timeline_name": "target", "fps": 24, "duration_frames": 20, "proxy": proxy, "audio": audio,
        "cuts": [{"name": "cut", "timeline_start": 0, "source_start": 0, "duration": 20}],
        "audio_rows": [{"name": "audio", "timeline_start": 0, "source_start": 0, "duration": 20}],
        "titles": [
            {"name": "caption-a", "text": "6000", "timeline_start": 0, "duration": 5, "lane": 1},
            {"name": "caption-b", "text": "launching", "timeline_start": 5, "duration": 5, "lane": 1},
            {"name": "caption-c", "text": "c", "timeline_start": 2, "duration": 5, "lane": 2},
        ],
        "title_lanes": [1, 2],
        "flash_handoffs": [{"name": "flash", "text": " ", "timeline_start": 10, "duration": 3, "lane": 3}],
    }


def test_readback_requires_exact_owned_target_and_protected_state(monkeypatch):
    target = Object(name="target", uid="owned")
    project = Object(pool=object())
    monkeypatch.setattr(live.base, "_timelines", lambda _: [target])
    monkeypatch.setattr(live.base, "validate_target", lambda *_, **__: {"ok": True})
    monkeypatch.setattr(live.base, "_timeline_inventory", lambda _: [{"name": "target", "unique_id": "owned", "signature": "t"}])
    monkeypatch.setattr(live.base, "_media_pool_inventory", lambda _: [{"signature": "m"}])
    assert live._readback(project, "target", "owned", {"xml": {}}, Counter(), Counter({"m": 1})) == {"ok": True}

    target.uid = "other"
    try:
        live._readback(project, "target", "owned", {"xml": {}}, Counter(), Counter({"m": 1}))
    except ValueError as exc:
        assert str(exc) == "post_save_target_identity"
    else:
        raise AssertionError("target identity drift was accepted")


def test_preflight_path_accepts_repository_paths_and_rejects_external_paths():
    assert live._preflight_path(ROOT, PREFLIGHT.relative_to(ROOT)) == PREFLIGHT
    assert live._preflight_path(ROOT, str(PREFLIGHT).swapcase()) == PREFLIGHT
    assert live._preflight_path(ROOT, str(PREFLIGHT).replace("/", "\\")) == PREFLIGHT
    for outside in (ROOT / "../outside.json", Path(str(ROOT) + " Evil/report.json")):
        with pytest.raises(ValueError, match="preflight_report_outside_repository"):
            live._preflight_path(ROOT, outside)


def test_actual_step7b_preflight_report_validates_without_mutation():
    digest = hashlib.sha256(PREFLIGHT.read_bytes()).hexdigest()
    declared = {
        "artifact_set_sha256": "75e90bbe71de541664e9dcd76be07188f12a42f0d62499d8f20c5dd77a45fea2",
        "textplus_fingerprint": "75e90bbe71de541664e9dcd76be07188f12a42f0d62499d8f20c5dd77a45fea2",
        "fcpxml_sha256": "e4ccc65a5ed1e7245d264333488390bfee68d32b3a116753223725f98143fd95",
        "report_sha256": "9b411430aa200c90411c5474a7769ffac56ec29d095d63540ba19a313dad984f",
    }
    path, report = live._load_preflight(ROOT, {
        "preflight_report_path": str(PREFLIGHT.relative_to(ROOT)),
        "preflight_report_sha256": digest,
    }, declared, "New Project 1", "DcJRJtUKScu_offline_timeline_v1")
    assert path == PREFLIGHT
    assert report["classification"] == "LIVE_IMPORT_PRECONDITIONS_PASS"
    assert not any(report["mutation_counts"].values())


@pytest.mark.parametrize("normalized", [True, False])
def test_stable_title_identity_accepts_normalized_or_descriptive_names(contract, normalized):
    result = live.base.validate_target(Timeline(contract, normalized), contract)
    assert result["v2_title_count"] == 3 and result["flash_handoff_count"] == 1


def test_timeline_identity_accepts_distinct_resolve_wrappers_for_same_object():
    assert live.base._same_timeline(Object(uid="same"), Object(uid="same"))
    assert not live.base._same_timeline(Object(uid="one"), Object(uid="two"))


@pytest.mark.parametrize(("mutation", "error"), [
    ("wrong_track", "target_same_lane_overlap"),
    ("wrong_order", "target_title"),
    ("wrong_start", "target_same_lane_overlap"),
    ("wrong_duration", "target_same_lane_overlap"),
    ("missing", "target_track_counts"),
    ("extra", "target_same_lane_overlap"),
    ("duplicate", "target_same_lane_overlap"),
    ("flash_track", "target_title_lanes"),
    ("flash_timing", "target_timing"),
])
def test_stable_title_identity_still_fails_closed(contract, mutation, error):
    timeline = Timeline(contract)
    if mutation == "wrong_track": timeline.video[3].append(timeline.video[2].pop())
    elif mutation == "wrong_order": timeline.video[2][0].text, timeline.video[2][1].text = timeline.video[2][1].text, timeline.video[2][0].text
    elif mutation == "wrong_start": timeline.video[2][0].start += 1
    elif mutation == "wrong_duration": timeline.video[2][0].duration += 1
    elif mutation == "missing": timeline.video[2].pop()
    elif mutation == "extra": timeline.video[2].append(Item("Text", 4, 2, text="x"))
    elif mutation == "duplicate": timeline.video[2].append(timeline.video[2][0])
    elif mutation == "flash_track": timeline.video[3].append(timeline.video[4].pop())
    else: timeline.video[4][0].start += 1
    with pytest.raises(ValueError, match=error):
        live.base.validate_target(timeline, contract)


def test_title_text_uses_existing_named_fusion_comp_readonly():
    assert live.base._title_text(Item("Text", 0, 1, text="launching")) == "launching"


def test_structural_readback_can_record_proven_direct_text_api_limitation(contract):
    timeline = Timeline(contract)
    for rows in timeline.video.values():
        for item in rows:
            item.text = None
    assert live.base.validate_target(timeline, contract, require_title_text=False)["v2_title_count"] == 3
    with pytest.raises(ValueError, match="target_title"):
        live.base.validate_target(timeline, contract)


def _fallback_inputs(contract):
    timeline = Timeline(contract)
    for rows in timeline.video.values():
        for item in rows:
            item.text = None
    validation = live.base.validate_target(timeline, contract, require_title_text=False)
    zero = {"timeline_imports": 0, "saves": 0, "deletes": 0, "relinks": 0, "replaces": 0, "media_imports": 0}
    return (
        {"xml": contract, "fcpxml_sha256": "canonical"}, validation,
        {"original_import_count": 1, "preflight_target_state": "ABSENT"},
        {"failures": ["ValueError: target_title"], "mutation_counts": zero},
        {"failures": ["ValueError: timeline_export_failed"], "mutation_counts": zero},
    )


def test_provenance_structural_semantic_fallback_passes_only_when_unobservable(contract):
    args = _fallback_inputs(contract)
    result = live._provenance_semantic_acceptance(*args, "canonical")
    assert result["policy"] == "PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1"
    assert result["probes"]["launching"] == {"text": "launching", "track": 2, "start": 5, "duration": 5}


@pytest.mark.parametrize(("mutation", "error"), [
    ("direct_mismatch", "direct_semantic_mismatch"),
    ("export_mismatch", "export_semantic_mismatch"),
    ("second_import", "fallback_import_provenance"),
    ("wrong_sha", "fallback_canonical_sha"),
])
def test_provenance_structural_semantic_fallback_rejects_contradictions(contract, mutation, error):
    values = list(_fallback_inputs(contract))
    if mutation == "direct_mismatch": values[1]["snapshot"]["items"][1]["title_text"] = "wrong"
    elif mutation == "export_mismatch": values[4]["pre_save_export"] = {"caption_texts_exposed": True, "captions_exact": 2}
    elif mutation == "second_import": values[2]["original_import_count"] = 2
    canonical_sha = "wrong" if mutation == "wrong_sha" else "canonical"
    with pytest.raises(ValueError, match=error):
        live._provenance_semantic_acceptance(*values, canonical_sha)


@pytest.mark.parametrize("mutation", ["wrong_track", "wrong_start", "missing", "extra"])
def test_fallback_keeps_structural_guards(contract, mutation):
    timeline = Timeline(contract)
    for rows in timeline.video.values():
        for item in rows:
            item.text = None
    if mutation == "wrong_track": timeline.video[3].append(timeline.video[2].pop())
    elif mutation == "wrong_start": timeline.video[2][0].start += 1
    elif mutation == "missing": timeline.video[2].pop()
    else: timeline.video[2].append(Item("Text", 4, 2))
    with pytest.raises(ValueError):
        live.base.validate_target(timeline, contract, require_title_text=False)
