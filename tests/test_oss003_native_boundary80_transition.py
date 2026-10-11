import zipfile
from pathlib import Path

import pytest

from resolve_workspace.modules import oss003_native_boundary80_transition as live
from resolve_workspace.modules import oss003_native_transition_drt as drt


def _track(items: str) -> str:
    return f"<Element><Sm2TiTrack DbId=\"track\"><Items>{items}</Items></Sm2TiTrack></Element>"


def _clip(identifier: str, start: int, duration: int) -> str:
    return f"<Element><Sm2TiVideoClip DbId=\"{identifier}\"><Start>{start}</Start><Duration>{duration}</Duration></Sm2TiVideoClip></Element>"


def _fixture(path: Path) -> None:
    mp = (
        '<Sm2Timeline DbId="nested-timeline"><Name>nested caption</Name><Sequence><Sm2Sequence DbId="nested-sequence"/></Sequence></Sm2Timeline>'
        f'<Sm2Timeline DbId="proof-timeline"><Name>{live.PROOF_NAME}</Name><Sequence><Sm2Sequence DbId="proof-sequence"/></Sequence></Sm2Timeline>'
    )
    nested = '<Sm2SequenceContainer DbId="nested-container"><VideoTrackVec>' + _track(_clip("nested", 0, 5)) + '</VideoTrackVec><Sequence>nested-sequence</Sequence></Sm2SequenceContainer>'
    top = '<Sm2SequenceContainer DbId="top-container"><VideoTrackVec>' + _track(_clip("left", 1000, 80) + _clip("right", 1080, 131)) + _track(_clip("caption", 1039, 5)) + _track(_clip("nested-title", 1039, 5)) + '</VideoTrackVec><AudioTrackVec>' + _track("") + '</AudioTrackVec><Sequence>proof-sequence</Sequence></Sm2SequenceContainer>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("MediaPool/root/MpFolder.xml", mp)
        archive.writestr("SeqContainer/nested.xml", nested)
        archive.writestr("SeqContainer/top.xml", top)
        archive.writestr("unchanged.bin", b"opaque")


def test_pinned_transition_port_selects_named_top_level_and_changes_only_it(tmp_path):
    source, patched = tmp_path / "source.drt", tmp_path / "patched.drt"
    _fixture(source)
    sequences = drt.list_sequences(source)
    assert next(row for row in sequences if row["name"] == live.PROOF_NAME)["id"] == "top-container"
    result = drt.place_transition(source, patched, timeline_name=live.PROOF_NAME, timeline_uuid="top-container", track=1, at_frame=1080, duration_frames=11)
    assert result["transition_count_before"] == 0
    assert result["transition_count_after"] == 1
    assert (result["start"], result["at_frame"], result["end"], result["duration"]) == (1075, 1080, 1086, 11)
    assert result["outside_target_unchanged"] is True
    assert result["target_restores_exactly"] is True
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(patched) as archive:
        top = archive.read("SeqContainer/top.xml").decode()
        assert "<PrettyType>Cross Dissolve</PrettyType>" in top
        assert archive.read("SeqContainer/nested.xml") == original.read("SeqContainer/nested.xml")
        assert archive.read("unchanged.bin") == b"opaque"


class Item:
    def __init__(self, name, start, duration, pool=None, left=20, right=20, comps=(), props=None):
        self.name, self.start, self.duration, self.pool = name, start, duration, pool
        self.left, self.right, self.comps, self.props = left, right, list(comps), props

    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetDuration(self): return self.duration
    def GetEnd(self): return self.start + self.duration
    def GetMediaPoolItem(self): return self.pool
    def GetLeftOffset(self): return self.left
    def GetRightOffset(self): return self.right
    def GetClipEnabled(self): return True
    def GetFusionCompNameList(self): return list(self.comps)
    def DeleteFusionCompByName(self, name): self.comps.remove(name); return True
    def GetProperty(self): return self.props


class PoolItem:
    def __init__(self, name, uid): self.name, self.uid = name, uid
    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid


class Timeline:
    def __init__(self, tracks): self.tracks = tracks
    def GetItemListInTrack(self, kind, track): return self.tracks.get((kind, track), [])
    def GetTrackCount(self, kind): return max((track for track_kind, track in self.tracks if track_kind == kind), default=0)
    def GetName(self): return live.PROOF_NAME
    def GetUniqueId(self): return "proof-uid"
    def GetStartFrame(self): return 1000


def test_handles_live_discriminator_cleanup_and_preservation_views():
    media = [Item(f"shot{i}", 1000 + i * 80, 80, PoolItem(f"src{i}", f"uid{i}")) for i in range(8)]
    assert live.handle_preflight(media) == {
        "outgoing_right_available": 20, "outgoing_right_required": 6,
        "incoming_left_available": 20, "incoming_left_required": 5,
    }
    media[0].right = 5
    with pytest.raises(ValueError, match="outgoing=5/6"):
        live.handle_preflight(media)
    media[0].right = 20
    media[0].comps = ["VC_OSS003_OLD", "KEEP_ME"]
    transition = Item("Cross Dissolve", 1075, 11, props={})
    captions = [Item(f"caption{i}", 1000 + i, 5) for i in range(112)]
    nested = [Item(f"nested{i}", 1000 + i, 5, PoolItem(f"nested-source{i}", f"nested-uid{i}")) for i in range(69)]
    audio = [Item("audio", 1000, 673, PoolItem("audio-source", "audio-uid"))]
    timeline = Timeline({("video", 1): media + [transition], ("video", 2): captions, ("video", 3): nested, ("audio", 1): audio})
    assert live.transition_readback(timeline, 1080) == {
        "name": "Cross Dissolve", "track": 1, "start": 1075, "end": 1086,
        "duration": 11, "media_pool_item": None, "property": {},
    }
    assert live.remove_experimental_fusion(timeline) == [{"clip": "shot0", "comp": "VC_OSS003_OLD"}]
    assert media[0].comps == ["KEEP_ME"]
    before = live.snapshot(timeline)
    after = live.snapshot(timeline)
    assert live.preservation_view(after) == live.preservation_view(before)
    assert (len(after["v1"]), len(after["v2"]), len(after["v3"]), len(after["a1"])) == (8, 112, 69, 1)
    captions[0].start += 1
    assert live.preservation_view(live.snapshot(timeline)) != live.preservation_view(before)
