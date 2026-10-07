from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.standalone import video_cloner_caption_lifecycle as lifecycle


def cue(index: int, text: str, source_ids=None) -> dict:
    return {
        "id": f"sub_{index:03d}",
        "text": text,
        "source_cue_ids": source_ids or [f"sub_{index:03d}"],
    }


def event(identity: str, cue_id: str, text: str, start: float, end: float, *, accepted=True) -> dict:
    return {
        "event_id": f"style_event_{identity}",
        "visual_event_identity": identity,
        "continuous_visual_identity_id": f"continuous_{identity}",
        "tracklet_ids": [identity],
        "cue_id": cue_id,
        "text": text,
        "start": start,
        "end": end,
        "style_profile_id": "style_test",
        "match": {"reason": "accepted" if accepted else "low_caption_score"},
        "observation_provenance": ["accepted_direct"],
        "semantic_reference": {"cue_id": cue_id},
    }


def compositions(cues, events, *, fps=24.0, accepted_motion=None, display_text_authority=None):
    return lifecycle._visual_compositions(cues, events, [], [], accepted_motion, fps, display_text_authority)


def tokens(rows):
    return [token for row in rows for token in row["tokens"]]


def active(rows, seconds: float, fps=24.0):
    frame = seconds * fps
    return [token for token in tokens(rows) if token["window"][0] <= frame < token["window"][1]]


def test_accepted_visual_identity_owns_object_and_provenance():
    source = event("caption_tracklet_0001", "sub_001", "We", 0.5, 1.0)
    row = tokens(compositions([cue(1, "We")], [source]))[0]

    assert row["visual_event_identity"] == "caption_tracklet_0001"
    assert row["window"] == [12, 24]
    assert row["style_evidence_id"] == "style_event_caption_tracklet_0001"
    assert row["style_ref"] == "style_test"
    assert row["tracklet_ids"] == ["caption_tracklet_0001"]
    assert row["continuous_visual_identity_id"] == "continuous_caption_tracklet_0001"
    assert row["semantic_ids"] == ["sub_001"]


def test_shared_or_broad_cue_does_not_gate_visual_object_cardinality():
    rows = compositions(
        [cue(17, "the")],
        [
            event("caption_tracklet_0026", "sub_017", "the", 5.3, 6.0),
            event("caption_tracklet_0030", "sub_017", "the", 5.5, 6.1),
            event("caption_tracklet_0029", "2", "before the sign hits the yard", 5.4, 6.0),
        ],
    )
    by_identity = {row["visual_event_identity"]: row for row in tokens(rows)}

    assert set(by_identity) == {
        "caption_tracklet_0026", "caption_tracklet_0030", "caption_tracklet_0029"
    }
    assert by_identity["caption_tracklet_0026"]["semantic_ids"] == ["sub_017"]
    assert by_identity["caption_tracklet_0030"]["semantic_ids"] == ["sub_017"]
    assert by_identity["caption_tracklet_0029"]["semantic_cue_id"] == "2"
    assert by_identity["caption_tracklet_0029"]["semantic_ids"] == []


def test_duplicate_identity_fails_closed_and_nonaccepted_or_missing_identity_does_not_seed():
    duplicate = event("caption_tracklet_0001", "sub_001", "We", 0.5, 1.0)
    with pytest.raises(lifecycle.LifecycleGenerationError, match="duplicate accepted visual_event_identity"):
        compositions([cue(1, "We")], [duplicate, {**duplicate, "event_id": "duplicate"}])

    rejected = event("caption_tracklet_0002", "sub_002", "don't", 0.5, 1.0, accepted=False)
    missing = {**event("unused", "sub_002", "don't", 0.5, 1.0), "visual_event_identity": ""}
    assert tokens(compositions([cue(1, "We")], [duplicate, rejected, missing])) == [
        tokens(compositions([cue(1, "We")], [duplicate]))[0]
    ]


def test_six_member_hierarchy_coexists_with_shared_the_and_broad_hits_yard():
    hierarchy = [
        event("caption_tracklet_0027", "sub_016", "before", 5.30, 6.00),
        event("caption_tracklet_0026", "sub_017", "the", 5.30, 6.00),
        event("continuous_visual_identity_0028", "sub_018", "sign", 5.35, 6.00),
        event("caption_tracklet_0029", "2", "before the sign hits the yard", 5.40, 6.00),
        event("caption_tracklet_0030", "sub_017", "the", 5.45, 6.05),
        event("caption_tracklet_0031", "2", "before the sign hits the yard", 5.50, 6.10),
    ]
    rows = compositions([cue(16, "before"), cue(17, "the"), cue(18, "sign")], hierarchy)
    current = active(rows, 5.83)

    assert len(current) == 6
    assert len({row["visual_event_identity"] for row in current}) == 6
    assert sum(row["semantic_cue_id"] == "sub_017" for row in current) == 2
    assert sum(row["semantic_cue_id"] == "2" for row in current) == 2
    assert len(rows) == 1
    assert rows[0]["relation"]["mode"] == "simultaneous"


def test_group_window_merge_does_not_extend_first_visual_identity():
    rows = compositions(
        [cue(1, "first"), cue(2, "second")],
        [
            event("caption_tracklet_first", "sub_001", "first", 1.0, 1.1),
            event("caption_tracklet_second", "sub_002", "second", 1.05, 2.0),
        ],
    )

    assert rows[0]["window"] == [24, 48]
    assert [row["window"] for row in tokens(rows)] == [[24, 26], [25, 48]]


def test_source_visible_recovery_clones_style_without_reusing_visual_identity():
    source = {
        **event("caption_tracklet_0092", "sub_069", "our", 23.9, 24.1),
        "placement": {"anchor": {"x": 0.5, "y": 0.44}},
        "typography": {"font_height_px": 50},
    }
    recovered = lifecycle._source_visible_recovery_events({
        "source_visible_recoveries": [{
            "visual_event_identity": "source_visible_recovery_0113",
            "style_source_visual_identity": "caption_tracklet_0092",
            "cue_id": "sub_0068",
            "text": "in",
            "source_frame_window": [707, 713],
            "bbox": [535, 805, 594, 862],
            "evidence": [{"path": "frame.jpg", "sha256": "a" * 64, "kind": "source_frame"}],
        }],
    }, [source], 30.0, 1080, 1920)

    assert len(recovered) == 1
    assert recovered[0]["visual_event_identity"] == "source_visible_recovery_0113"
    assert recovered[0]["cue_id"] == "sub_0068"
    assert recovered[0]["text"] == recovered[0]["observed_text"] == "in"
    assert recovered[0]["start"] == 707 / 30
    assert recovered[0]["end"] == 713 / 30
    assert recovered[0]["placement"]["bbox"] == [535, 805, 594, 862]


def test_we_dont_and_two_6000_identities_remain_independent():
    rows = compositions(
        [cue(1, "We"), cue(2, "don't"), cue(65, "6000", ["sub_065", "sub_066"])],
        [
            event("caption_tracklet_0001", "sub_001", "We", 0.5, 1.0),
            event("caption_tracklet_0002", "sub_002", "don't", 0.6, 1.0),
            event("caption_tracklet_0088", "sub_066", "6000", 22.5, 22.8),
            event("caption_tracklet_0089", "sub_066", "6000", 23.0, 23.4),
        ],
    )
    assert {row["visual_event_identity"] for row in active(rows, 0.8)} == {
        "caption_tracklet_0001", "caption_tracklet_0002"
    }
    six_thousand = [row for row in tokens(rows) if row["text"] == "6000"]
    assert [row["visual_event_identity"] for row in six_thousand] == [
        "caption_tracklet_0088", "caption_tracklet_0089"
    ]
    assert [row["window"] for row in six_thousand] == [[540, 547], [552, 562]]


def test_social_motion_owner_and_payload_are_unchanged():
    accepted = json.loads(
        (Path(__file__).parents[1] / "config" / "DcJRJtUKScu.accepted_caption_motion.json")
        .read_text(encoding="utf-8")
    )
    decision = {
        **accepted,
        "animation": {
            **accepted["animation"],
            "source_evidence_id": accepted["style_evidence_id"],
            "source_visual_event_identity": accepted["visual_event_identity"],
        },
    }
    row = tokens(compositions(
        [cue(45, "social,")],
        [event("caption_tracklet_0064", "sub_045", "social,", 36.5, 37.6)],
        accepted_motion=decision,
    ))[0]

    assert row["visual_event_identity"] == "caption_tracklet_0064"
    assert row["window"] == [359, 383]
    assert row["accepted_motion_authority"]["keyframes"] == [
        {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
        {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
    ]


def display_authority(decisions):
    return {
        "schema": "video_cloner_reel_display_text_authority",
        "schema_version": 1,
        "decisions": [
            {
                "visual_event_identity": identity,
                "source_text": source_text,
                "display_text": display_text,
                "authority": authority,
                "evidence": [{"path": "evidence.json", "sha256": "a" * 64, "kind": "test"}],
            }
            for identity, source_text, display_text, authority in decisions
        ],
    }


def test_reel_display_text_changes_only_configured_identity_text_and_provenance():
    broad = "sign hits the yard. It starts with a conversation about your why. We invest in how your home shows"
    source_events = [
        event("caption_tracklet_0001", "sub_001", "We", 0.5, 1.0),
        event("caption_tracklet_0002", "sub_002", "don't", 0.6, 1.0),
        event("caption_tracklet_0027", "sub_016", "before", 5.30, 6.00),
        event("caption_tracklet_0026", "sub_017", "the", 5.30, 6.00),
        event("continuous_visual_identity_0028", "sub_018", "sign", 5.35, 6.00),
        event("caption_tracklet_0029", "2", broad, 5.40, 6.00),
        event("caption_tracklet_0030", "sub_017", "the", 5.45, 6.05),
        event("caption_tracklet_0031", "2", broad, 5.50, 6.10),
        event("caption_tracklet_0088", "sub_066", ",000", 22.5, 22.8),
        event("caption_tracklet_0089", "sub_066", ",000", 23.0, 23.4),
    ]
    authority = display_authority([
        ("continuous_visual_identity_0028", "sign", "sign", "confirmed_semantic_correction"),
        ("caption_tracklet_0029", broad, "hits", "confirmed_source_observed"),
        ("caption_tracklet_0031", broad, "yard", "confirmed_source_observed"),
        ("caption_tracklet_0088", ",000", "6000", "confirmed_source_observed"),
        ("caption_tracklet_0089", ",000", "6000", "confirmed_source_observed"),
    ])
    cues = [cue(1, "We"), cue(2, "don't"), cue(16, "before"), cue(17, "the"), cue(18, "sign"), cue(66, ",000")]
    baseline = {row["visual_event_identity"]: row for row in tokens(compositions(cues, source_events))}
    actual = {row["visual_event_identity"]: row for row in tokens(compositions(cues, source_events, display_text_authority=authority))}

    assert set(actual) == set(baseline)
    assert {identity: row["window"] for identity, row in actual.items()} == {
        identity: row["window"] for identity, row in baseline.items()
    }
    assert actual["caption_tracklet_0001"]["text"] == "We"
    assert actual["caption_tracklet_0002"]["text"] == "don't"
    hierarchy = {
        row["visual_event_identity"]: row["text"]
        for row in active(list(compositions(cues, source_events, display_text_authority=authority)), 5.83)
    }
    assert hierarchy == {
        "caption_tracklet_0027": "before", "caption_tracklet_0026": "the",
        "continuous_visual_identity_0028": "sign", "caption_tracklet_0029": "hits",
        "caption_tracklet_0030": "the", "caption_tracklet_0031": "yard",
    }
    assert [actual[identity]["text"] for identity in ("caption_tracklet_0088", "caption_tracklet_0089")] == ["6000", "6000"]
    configured = {row["visual_event_identity"] for row in authority["decisions"]}
    assert {
        identity for identity, row in actual.items() if row.get("display_text_authority")
    } == configured
    for identity in configured:
        assert actual[identity]["display_text_evidence"] == [
            {"path": "evidence.json", "sha256": "a" * 64, "kind": "test"}
        ]
    for identity in set(actual) - configured:
        assert "display_text_authority" not in actual[identity]
        assert "display_text_evidence" not in actual[identity]


def test_display_text_authority_fails_closed_for_stale_or_unknown_identity():
    source = event("caption_tracklet_0029", "2", "broad phrase", 5.4, 6.0)
    stale = display_authority([
        ("caption_tracklet_0029", "different phrase", "hits", "confirmed_source_observed")
    ])
    with pytest.raises(lifecycle.LifecycleGenerationError, match="stale display text decision"):
        compositions([], [source], display_text_authority=stale)

    unknown = display_authority([
        ("caption_tracklet_9999", "missing", "missing", "confirmed_source_observed")
    ])
    with pytest.raises(lifecycle.LifecycleGenerationError, match="not an accepted visual event"):
        compositions([], [source], display_text_authority=unknown)
