from __future__ import annotations

import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

COMPILER_PATH = Path(__file__).parents[1] / "scripts" / "davinci" / "compile_davinci_textplus_fcpxml.py"
VALIDATOR_PATH = Path(__file__).parents[1] / "scripts" / "davinci" / "validate_caption_lifecycle_fcpxml_step_3D.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compiler = load_module(COMPILER_PATH, "compiler_lifecycle_test")
validator = load_module(VALIDATOR_PATH, "validator_lifecycle_test")


def cue(index: int, text: str, start: int, end: int) -> dict:
    return {
        "index": index,
        "id": f"sub_{index:03d}",
        "text": text,
        "start": start / 24,
        "end": end / 24,
        "duration": (end - start) / 24,
        "start_frame": start,
        "end_frame": end,
        "duration_frames": end - start,
        "raw": {
            "timeline_start_frame": start,
            "timeline_end_frame": end,
        },
    }


def layer(index: int, text: str, transcript: list[int], lifecycle: list[int], authority: str) -> dict:
    return {
        "cue_id": f"sub_{index:03d}",
        "cue_index": index,
        "text": text,
        "transcript_window": transcript,
        "lifecycle_window": lifecycle,
        "timing_authority": authority,
        "lifecycle_status": "source_observed" if authority != "transcript_fallback" else "fallback",
        "animation_selected_step_3C": index == 2,
        "animation_type_step_3C": "slide" if index == 2 else None,
        "visual_confidence_label": "high" if authority != "transcript_fallback" else "unresolved",
    }


def plan(layers: list[dict]) -> dict:
    visual = sum(1 for row in layers if str(row["timing_authority"]).startswith("visual_primary"))
    fallback = sum(1 for row in layers if row["timing_authority"] == "transcript_fallback")
    animated = sum(1 for row in layers if row.get("animation_selected_step_3C"))
    return {
        "ok": True,
        "schema": compiler.LIFECYCLE_PLAN_SCHEMA,
        "schema_version": 1,
        "version": "test",
        "authority_policy": "VISUAL_PRIMARY_TRANSCRIPT_TEXT_AND_TIMING_FALLBACK_CALIBRATED",
        "mandatory_visual_redetection_queue": [],
        "layers": layers,
        "summary": {
            "caption_layer_count": len(layers),
            "visual_primary_count": visual,
            "transcript_fallback_count": fallback,
            "selected_animation_count": animated,
            "selected_animation_visual_primary_count": animated,
        },
    }


def test_visual_lifecycle_overrides_timing_and_preserves_display_casing():
    cues = [cue(1, "come", 10, 14), cue(2, "knows", 14, 18)]
    data = plan([
        layer(1, "COME", [10, 14], [10, 22], "visual_primary_redetected"),
        layer(2, "KNOWS", [14, 18], [14, 21], "visual_primary_redetected"),
    ])
    applied, info = compiler.apply_caption_lifecycle_plan(cues, data, fps=24, base_lane=1)
    assert [(row["start_frame"], row["end_frame"], row["text"]) for row in applied] == [
        (10, 22, "COME"),
        (14, 21, "KNOWS"),
    ]
    assert info["visual_primary_count"] == 2
    assert info["lane_allocation"]["lane_count"] == 2
    assert applied[0]["lane"] != applied[1]["lane"]


def test_lane_allocator_reuses_lane_after_interval_end():
    cues = [cue(1, "a", 0, 5), cue(2, "b", 2, 8), cue(3, "c", 5, 9)]
    info = compiler.allocate_caption_lanes(cues, base_lane=3)
    assert info["lane_count"] == 2
    assert cues[0]["lane"] == 3
    assert cues[1]["lane"] == 4
    assert cues[2]["lane"] == 3


def test_transcript_fallback_must_remain_on_transcript_window():
    cues = [cue(1, "word", 10, 12)]
    data = plan([layer(1, "word", [10, 12], [10, 13], "transcript_fallback")])
    try:
        compiler.apply_caption_lifecycle_plan(cues, data, fps=24, base_lane=1)
    except ValueError as exc:
        assert "fallback_window" in str(exc)
    else:
        raise AssertionError("expected fallback window validation failure")


def test_title_xml_uses_assigned_lane():
    item = cue(1, "COME", 10, 22)
    item["lane"] = 4
    style = {
        "font_name": "Arial",
        "font_size_px": 60,
        "fill_fcpxml": "1 1 1 1",
        "bold": False,
        "italic": False,
        "outline_fcpxml": "0 0 0 1",
        "outline_px": 2,
        "shadow_fcpxml": "0 0 0 0.85",
        "shadow_px": 2,
        "anchor": {"x": 0.5, "y": 0.5},
    }
    xml = compiler.build_title_xml(item, style, 24, 1080, 1920, "r2", 1, "VC Caption")
    title = ET.fromstring(xml)
    assert title.attrib["lane"] == "4"
    assert title.attrib["offset"] == "10/24s"
    assert title.attrib["duration"] == "12/24s"


def test_validator_rejects_same_lane_overlap():
    data = plan([
        layer(1, "A", [0, 2], [0, 5], "visual_primary"),
        layer(2, "B", [2, 4], [2, 6], "visual_primary"),
    ])
    report = {
        "success": True,
        "caption_lifecycle": {
            "enabled": True,
            "visual_primary_count": 2,
            "transcript_fallback_count": 0,
            "animated_caption_count": 1,
            "animated_visual_lifecycle_count": 1,
            "lane_allocation": {"lane_count": 1, "max_lane": 1},
        },
    }
    titles = [
        {"index": 1, "name": "VC Caption 0001 - A", "lane": 1, "start_frame": 0, "duration_frames": 5, "text": "A"},
        {"index": 2, "name": "VC Caption 0002 - B", "lane": 1, "start_frame": 2, "duration_frames": 4, "text": "B"},
    ]
    result = validator.validate(data, report, titles)
    assert result["ok"] is False
    assert result["same_lane_overlap_count"] == 1
