import inspect
import zipfile
from pathlib import Path

from resolve_workspace.modules import oss003_native_blur_auto_b80 as runtime
from resolve_workspace.modules import oss003_native_blur_drt as blur


def _drt(path: Path, timeline_name: str, transition: str = "") -> None:
    clips = (
        '<Element><Sm2TiVideoClip DbId="left"><Start>0</Start><Duration>80</Duration></Sm2TiVideoClip></Element>'
        + transition
        + '<Element><Sm2TiVideoClip DbId="right"><Start>80</Start><Duration>131</Duration></Sm2TiVideoClip></Element>'
    )
    track = f'<Element><Sm2TiTrack DbId="track"><Items>{clips}</Items></Sm2TiTrack></Element>'
    container = f'<Sm2SequenceContainer DbId="container"><VideoTrackVec>{track}</VideoTrackVec><Sequence>sequence</Sequence></Sm2SequenceContainer>'
    media_pool = f'<Sm2Timeline DbId="timeline"><Name>{timeline_name}</Name><Sequence><Sm2Sequence DbId="sequence"/></Sequence></Sm2Timeline>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("MediaPool/root/MpFolder.xml", media_pool)
        archive.writestr("SeqContainer/container.xml", container)
        archive.writestr("opaque.bin", b"unchanged")


def _blur_element() -> str:
    return (
        blur.base.TRANSITION_TEMPLATE
        .replace("Cross Dissolve", "Blur Dissolve")
        .replace("000000020000001c8012190000002c789c6366606400028ee3f30fbf642000006baa031f", "aa55")
        .replace("000000020000003a800a37081238024a004a004a004a004a29088b015224ffffffe00000000000000c0000000000000000001800000000000c00000000000000f03f", "bb66")
        .replace("<Start>88104</Start>", "<Start>75</Start>")
        .replace("<Duration>24</Duration>", "<Duration>11</Duration>")
    )


def test_harvest_diff_reports_exact_reusable_native_fields(tmp_path):
    cross_path, blur_path = tmp_path / "cross.drt", tmp_path / "blur.drt"
    cross = blur.base.TRANSITION_TEMPLATE.replace("<Start>88104</Start>", "<Start>75</Start>").replace("<Duration>24</Duration>", "<Duration>11</Duration>")
    _drt(cross_path, runtime.DONOR_NAME, cross)
    _drt(blur_path, runtime.DONOR_NAME, _blur_element())
    comparison = blur.transition_diff(blur.extract_transition(cross_path, runtime.DONOR_NAME), blur.extract_transition(blur_path, runtime.DONOR_NAME))
    assert comparison["pretty_type_only"] is False
    assert comparison["fields_blob_differs"] is True
    assert comparison["effect_filters_ba_differs"] is True
    assert comparison["identity_fields_regenerated"] == ["Sm2TiTransition@DbId"]
    assert comparison["reusable_style_payload"]["PrettyType"] == "Blur Dissolve"


def test_harvested_template_places_one_native_blur_at_b80(tmp_path):
    source, patched = tmp_path / "source.drt", tmp_path / "patched.drt"
    _drt(source, runtime.PROOF_NAME)
    result = blur.place_blur_transition(source, patched, timeline_name=runtime.PROOF_NAME, timeline_uuid="container", donor_element=_blur_element(), track=1, at_frame=80, duration_frames=11)
    assert result == {"container_uuid": "container", "entry": "SeqContainer/container.xml", "track": 1, "pretty_type": "Blur Dissolve", "start": 75, "duration": 11, "end": 86, "cut": 80}
    placed = blur.extract_transition(patched, runtime.PROOF_NAME)
    assert placed["db_id"] != "a1ee9cd6-e3ba-4d5c-82a4-2e110fdcdd0a"
    assert placed["fields"]["FieldsBlob"] == "aa55"
    assert placed["fields"]["EffectFiltersBA"] == "bb66"


def test_successful_import_branch_never_deletes_proof_and_has_no_fusion_route():
    source = inspect.getsource(runtime)
    retained_branch = source.split("if imported_successfully and project is not None and imported is not None:", 1)[1].split("elif project is not None", 1)[0]
    assert "_delete_exact" not in retained_branch
    assert "SetCurrentTimeline" in retained_branch
    assert "DeleteFusionCompByName" not in source
    assert "DeleteTool" not in source
