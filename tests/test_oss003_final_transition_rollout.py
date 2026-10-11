import inspect
import zipfile
from pathlib import Path

from resolve_workspace.modules import oss003_final_transition_rollout as runtime
from resolve_workspace.modules import oss003_native_blur_drt as blur


def _drt(path: Path) -> None:
    clips = "".join(
        f'<Element><Sm2TiVideoClip DbId="clip{index}"><Start>{start}</Start><Duration>{duration}</Duration></Sm2TiVideoClip></Element>'
        for index, (start, duration) in enumerate(runtime.batch.EXPECTED_V1)
    )
    track = f'<Element><Sm2TiTrack DbId="track"><Items>{clips}</Items></Sm2TiTrack></Element>'
    container = f'<Sm2SequenceContainer DbId="container"><VideoTrackVec>{track}</VideoTrackVec><Sequence>sequence</Sequence></Sm2SequenceContainer>'
    media_pool = f'<Sm2Timeline DbId="timeline"><Name>{runtime.FINAL_NAME}</Name><Sequence><Sm2Sequence DbId="sequence"/></Sequence></Sm2Timeline>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("MediaPool/root/MpFolder.xml", media_pool)
        archive.writestr("SeqContainer/container.xml", container)
        archive.writestr("opaque.bin", b"unchanged")


def _donor() -> str:
    return blur.base.TRANSITION_TEMPLATE.replace("Cross Dissolve", "Blur Dissolve").replace("<Start>88104</Start>", "<Start>75</Start>").replace("<Duration>24</Duration>", "<Duration>11</Duration>")


def test_places_three_native_blurs_without_touching_other_archive_members(tmp_path):
    source, target = tmp_path / "source.drt", tmp_path / "target.drt"
    _drt(source)
    placed = blur.place_blur_transitions(source, target, timeline_name=runtime.FINAL_NAME, timeline_uuid="container", donor_element=_donor(), track=1, boundaries=list(runtime.BOUNDARIES))
    assert [(row["cut"], row["duration"]) for row in placed] == list(runtime.BOUNDARIES)
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(target) as after:
        assert after.read("opaque.bin") == before.read("opaque.bin")
        xml = after.read("SeqContainer/container.xml").decode()
    assert xml.count("<Sm2TiTransition ") == 3
    assert [int(next(iter(blur.ET.fromstring(match.group(0)))).findtext("Start")) for match in blur.base.TRANSITION_RE.finditer(xml)] == [75, 281, 371]


def test_duplicate_boundary_fails_closed(tmp_path):
    source, target = tmp_path / "source.drt", tmp_path / "target.drt"
    _drt(source)
    try:
        blur.place_blur_transitions(source, target, timeline_name=runtime.FINAL_NAME, timeline_uuid="container", donor_element=_donor(), track=1, boundaries=[(80, 11), (80, 11)])
    except ValueError as exc:
        assert str(exc) == "duplicate_boundary"
    else:
        raise AssertionError("duplicate boundary accepted")


def test_successful_import_is_retained_and_fusion_cleanup_is_nonblocking():
    source = inspect.getsource(runtime)
    retained = source.split("if imported_successfully and project is not None and imported is not None:", 1)[1].split("elif project is not None", 1)[0]
    assert "_delete_exact" not in retained
    assert "DeleteTool" not in source
    assert "DeleteFusionCompByName" not in source
    assert '"fusion_debt": {"policy": "deferred", "blocking": False' in source
