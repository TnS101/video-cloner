from video_cloner.resolve.fcpxml import extract_caption_style_events


def _event(identity, text="the", start=5.4, end=6.4, **extra):
    row = {"event_id": extra.pop("event_id", identity or "legacy"), "text": text, "start": start, "end": end, **extra}
    if identity is not None:
        row["visual_event_identity"] = identity
    return row


def test_different_visual_identities_survive_same_legacy_key_with_metadata():
    hits = _event("caption_tracklet_0029", text="broad phrase", tracklet_ids=["caption_tracklet_0029"])
    yard = _event("caption_tracklet_0031", text="broad phrase", tracklet_ids=["caption_tracklet_0031"])

    events = extract_caption_style_events({"caption_style_events": [hits, yard]}, fps=30.0)

    assert [event["raw"]["visual_event_identity"] for event in events] == [
        "caption_tracklet_0029", "caption_tracklet_0031"
    ]
    assert events[1]["raw"]["tracklet_ids"] == ["caption_tracklet_0031"]


def test_same_visual_identity_keeps_first_row_deterministically():
    first = _event("continuous_visual_identity_0028", text="sign", start=5.333, end=6.3, event_id="first")
    duplicate = _event("continuous_visual_identity_0028", text="different", start=8.0, end=9.0, event_id="second")

    events = extract_caption_style_events({"caption_style_events": [first, duplicate]}, fps=30.0)

    assert len(events) == 1
    assert events[0]["id"] == "first"
    assert (events[0]["start"], events[0]["end"]) == (5.333, 6.3)


def test_legacy_collision_keeps_existing_first_row_behavior():
    first = _event(None, text="legacy", event_id="first")
    duplicate = _event(None, text="legacy", event_id="second")

    events = extract_caption_style_events({"caption_style_events": [first, duplicate]}, fps=30.0)

    assert len(events) == 1
    assert events[0]["id"] == "first"


def test_repeated_the_and_continuous_sign_survive_in_deterministic_time_order():
    rows = [
        _event("lower_the", start=5.4, end=6.4, bbox=[370, 803, 526, 878]),
        _event("continuous_visual_identity_0028", text="sign", start=5.333, end=6.3, tracklet_ids=["caption_tracklet_0028", "caption_tracklet_0033"]),
        _event("upper_the", start=5.3, end=6.433, bbox=[508, 389, 620, 445]),
    ]

    events = extract_caption_style_events({"caption_style_events": rows}, fps=30.0)

    assert [event["raw"]["visual_event_identity"] for event in events] == [
        "upper_the", "continuous_visual_identity_0028", "lower_the"
    ]
    assert events[1]["raw"]["tracklet_ids"] == ["caption_tracklet_0028", "caption_tracklet_0033"]
    assert events[0]["raw"]["bbox"] != events[2]["raw"]["bbox"]
