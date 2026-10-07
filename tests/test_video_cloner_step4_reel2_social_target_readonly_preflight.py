from __future__ import annotations

from copy import deepcopy

import pytest

from resolve_workspace.modules import video_cloner_step4_reel2_social_target_readonly_preflight as subject


class Remote:
    def __init__(self, **methods):
        self.__dict__.update(methods)


def item(uid="item-social", name="Text", track=2, start=365, end=376, text="social,", comps=None):
    properties = {"Type": "Basic Title", "StyledText": text}
    return track, Remote(
        GetUniqueId=lambda: uid, GetName=lambda: name, GetStart=lambda: start,
        GetEnd=lambda: end, GetDuration=lambda: end - start,
        GetLeftOffset=lambda: None, GetMediaPoolItem=lambda: None,
        GetProperty=lambda: properties, GetFusionCompCount=lambda: len(comps or []),
        GetFusionCompByIndex=lambda index: (comps or [])[index - 1],
    )


def timeline(name=subject.TIMELINE_NAME, uid=subject.TIMELINE_UID, items=None):
    rows = items if items is not None else [item()]
    return Remote(
        GetName=lambda: name, GetUniqueId=lambda: uid, GetStartFrame=lambda: 0,
        GetEndFrame=lambda: 854, GetSetting=lambda key: 24,
        GetTrackCount=lambda kind: max([row[0] for row in rows], default=0) if kind == "video" else 0,
        GetItemListInTrack=lambda kind, track: [value for row_track, value in rows if kind == "video" and row_track == track],
    )


def resolve(project_name=subject.PROJECT_NAME, timelines=None):
    values = timelines if timelines is not None else [timeline()]
    project = Remote(
        GetName=lambda: project_name, GetTimelineCount=lambda: len(values),
        GetTimelineByIndex=lambda index: values[index - 1],
    )
    manager = Remote(GetCurrentProject=lambda: project)
    return Remote(GetProjectManager=lambda: manager)


def test_basic_title_requires_reconstruction():
    result = subject.inspect(resolve())
    assert result["classification"] == "TEXTPLUS_RECONSTRUCTION_REQUIRED"
    assert result["target"]["timeline_item_uid"] == "item-social"
    assert result["target"]["fusion_composition_count"] == 0
    assert result["target"]["textplus_node_count"] == 0
    assert result["compatibility"]["can_host_unchanged"] is False


def test_wrong_project_fails_closed():
    with pytest.raises(ValueError, match="project_identity"):
        subject.inspect(resolve(project_name="Wrong"))


def test_wrong_timeline_uid_fails_closed():
    with pytest.raises(ValueError, match="timeline_uid"):
        subject.inspect(resolve(timelines=[timeline(uid="wrong")]))


def test_duplicate_timeline_or_structural_target_fails_closed():
    with pytest.raises(ValueError, match="timeline_name_occurrence"):
        subject.inspect(resolve(timelines=[timeline(), timeline()]))
    with pytest.raises(ValueError, match="structural_target_occurrence"):
        subject.inspect(resolve(timelines=[timeline(items=[item(), item(uid="duplicate")])]))


@pytest.mark.parametrize("rows", [[item(track=3)], [item(start=364)], []])
def test_wrong_track_range_or_missing_target_fails_closed(rows):
    with pytest.raises(ValueError, match="structural_target_occurrence"):
        subject.inspect(resolve(timelines=[timeline(items=rows)]))


def test_styled_text_mismatch_fails_closed():
    with pytest.raises(ValueError, match="styled_text"):
        subject.inspect(resolve(timelines=[timeline(items=[item(text="wrong")])]))


def test_textplus_target_reports_modifier_state():
    modifier = Remote(GetAttrs=lambda: {"TOOLS_RegID": "BezierSpline"}, GetKeyFrames=lambda: {0: 0.7, 23: 1.0})
    output = Remote(GetTool=lambda: modifier)
    input_object = Remote(GetConnectedOutput=lambda: output)
    tool = Remote(
        GetAttrs=lambda: {"TOOLS_Name": "Template", "TOOLS_RegID": "TextPlus"},
        GetInput=lambda name, frame=0: "social," if name == "StyledText" else None,
        FindInput=lambda name: input_object if name == "Size" else None,
    )
    comp = Remote(GetToolList=lambda *args: {"tool": tool})
    result = subject.inspect(resolve(timelines=[timeline(items=[item(comps=[comp])])]))
    assert result["classification"] == "TEXTPLUS_TARGET_EXISTS"
    assert result["target"]["textplus_nodes"][0]["modifiers"]["Size"]["modifier_type"] == "BezierSpline"


def test_mutation_command_is_rejected():
    payload = {
        "read_only": True, "expected_project": subject.PROJECT_NAME,
        "target_timeline_name": subject.TIMELINE_NAME,
        "expected_timeline_uid": subject.TIMELINE_UID,
        "expected_item_name": subject.ITEM_NAME, "expected_track": subject.TRACK,
        "expected_start": subject.START, "expected_end": subject.END,
        "expected_text": subject.TEXT, "canonical_window": subject.CANONICAL_WINDOW,
        "local_animation_range": subject.LOCAL_ANIMATION_RANGE,
    }
    for key in (
        "mutation_permitted", "save_project", "create_permitted", "delete_permitted",
        "title_write_permitted", "modifier_write_permitted", "keyframe_write_permitted",
        "import_permitted", "relink_permitted", "replace_permitted", "timeline_selection_permitted",
    ):
        payload[key] = False
    command = {"task_id": subject.TASK_ID, "mode": subject.MODE, "run_id": "run", "payload": payload}
    subject.validate_command(command, "run")
    mutated = deepcopy(command)
    mutated["payload"]["save_project"] = True
    with pytest.raises(ValueError, match="read_only_command_authority"):
        subject.validate_command(mutated, "run")
