from scripts.analysis.build_camera_style_profile import build_camera_style_profile


def test_builds_locked_talking_head_profile_and_reframe_plan():
    motion = {
        "summary": {"dominant_motion_family": "pan_tilt"},
        "segments": [
            {"shot_id": 1, "start_seconds": 0.0, "end_seconds": 2.0, "motion_family": "pan_tilt", "confidence": "high", "global_motion": {"translation": {"direction": "pan_right"}}},
            {"shot_id": 2, "start_seconds": 2.0, "end_seconds": 4.0, "motion_family": "push_in", "confidence": "medium"},
        ],
    }
    observations = [
        {"shot_id": 1, "time_sec": 0.2, "detected": True, "center": [0.49, 0.37], "size": [0.16, 0.2]},
        {"shot_id": 1, "time_sec": 1.0, "detected": True, "center": [0.51, 0.38], "size": [0.17, 0.21]},
        {"shot_id": 2, "time_sec": 2.5, "detected": True, "center": [0.5, 0.39], "size": [0.18, 0.22]},
        {"shot_id": 2, "time_sec": 3.5, "detected": False},
    ]

    profile = build_camera_style_profile(motion, observations)

    assert profile["schema"] == "video_cloner.camera_style.v1"
    assert profile["framing"] == "centered_talking_head"
    assert profile["subject_lock"] is True
    assert profile["camera_motion"]["behavior"] == "moving"
    assert profile["camera_motion"]["origin"] == "source_or_baked_editor_indeterminate"
    assert profile["reframe_strategy"] == "sampled_primary_face_center"
    assert len(profile["editor_transform"]["keyframes"]) == 3
    assert len(profile["punch_in_events"]) == 1
    assert profile["pan_events"][0]["direction"] == "pan_right"


def test_fails_closed_when_no_face_is_detected():
    profile = build_camera_style_profile({"segments": []}, [{"shot_id": 1, "time_sec": 0.0, "detected": False}])

    assert profile["framing"] == "unknown"
    assert profile["subject_lock"] is False
    assert profile["reframe_strategy"] == "preserve_source_frame"
    assert profile["editor_transform"]["operation"] == "none"
    assert profile["confidence"] == 0.0
