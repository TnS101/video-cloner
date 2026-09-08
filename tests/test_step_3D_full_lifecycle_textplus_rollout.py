from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace" / "modules" / "step_3D_full_lifecycle_textplus_rollout.py"
PUBLISHER_PATH = ROOT / "scripts" / "davinci" / "prepare_step_3D_full_lifecycle_textplus_rollout.py"
VALIDATOR_PATH = ROOT / "scripts" / "davinci" / "validate_step_3D_full_lifecycle_textplus_rollout.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rollout = load(MODULE_PATH, "step_3D_full_lifecycle_textplus_rollout")
publisher = load(PUBLISHER_PATH, "prepare_step_3D_full_lifecycle_textplus_rollout")
validator = load(VALIDATOR_PATH, "validate_step_3D_full_lifecycle_textplus_rollout")


def load_plan():
    return rollout.compile_rollout_plan(
        rollout.load_json(ROOT / rollout.LIFECYCLE_AUTHORITY_RELATIVE_PATH),
        rollout.load_json(ROOT / rollout.WORD_TRACKS_RELATIVE_PATH),
        rollout.load_json(ROOT / rollout.SOURCE_CONTROLLER_REPORT_RELATIVE_PATH),
        rollout.load_json(ROOT / rollout.ANIMATION_TARGETS_RELATIVE_PATH),
    )


def test_contract_uses_only_the_live_proven_runtime_route():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert rollout.TASK_ID == "DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6"
    assert publisher.TASK_ID == rollout.TASK_ID
    assert validator.TASK_ID == rollout.TASK_ID
    assert "AppendToTimeline" in source
    assert "import_source_comp" in source
    assert "ImportFusionComp" in (ROOT / "resolve_workspace" / "modules" / "step_3D_media_backed_fusion_clone.py").read_text(encoding="utf-8")
    assert "InsertFusionCompositionIntoTimeline" not in source
    assert "InsertFusionTitleIntoTimeline" not in source
    assert '"AddFusionComp"' not in source


def test_source_range_policy_accepts_only_exact_or_bounded_shortened_resolve_end():
    exact = rollout.source_range_verdict([280, 283], [280, 283])
    assert exact["ok"] is True
    assert exact["classification"] == "exact"

    observed_short_ranges = {
        "sub_022": ([280, 282], [280, 283]),
        "sub_027": ([305, 307], [305, 308]),
        "sub_047": ([402, 404], [402, 405]),
        "sub_073": ([521, 522], [521, 524]),
        "sub_075": ([611, 613], [611, 614]),
        "sub_076": ([613, 615], [613, 616]),
        "sub_106": ([844, 846], [844, 847]),
        "sub_115": ([894, 896], [894, 897]),
    }
    for cue_id, (actual, expected) in observed_short_ranges.items():
        verdict = rollout.source_range_verdict(actual, expected)
        assert verdict["ok"] is True, cue_id
        assert verdict["classification"] == "resolve_end_shortened", cue_id
        assert verdict["start_delta"] == 0
        assert verdict["end_delta"] in {-1, -2}

    assert rollout.source_range_verdict([279, 283], [280, 283])["ok"] is False
    assert rollout.source_range_verdict([280, 280], [280, 283])["ok"] is False
    assert rollout.source_range_verdict([280, 284], [280, 283])["ok"] is False


def test_source_inventory_artifact_is_written_before_inventory_failure():
    source = MODULE_PATH.read_text(encoding="utf-8")
    write_index = source.index('base.write_json(report_dir / "source_inventory_before.json", source_before)')
    failure_index = source.index('if not source_before.get("ok"):', write_index)
    assert write_index < failure_index


def test_plan_compiles_116_cues_into_115_visual_instances():
    plan = load_plan()
    assert plan["ok"] is True
    assert plan["summary"]["source_layer_count"] == 116
    assert plan["summary"]["visual_instance_count"] == 115
    assert plan["summary"]["represented_cue_count"] == 116
    assert plan["summary"]["represented_cue_ids_unique"] == 116
    assert len(plan["source_catalog"]) == 116
    assert len(plan["instances"]) == 115


def test_only_the_visually_proven_they_aliases_are_merged():
    plan = load_plan()
    merged = [row for row in plan["instances"] if len(row["source_cue_ids"]) > 1]
    assert len(merged) == 1
    assert merged[0]["instance_id"] == "visual_instance_sub_051_sub_054"
    assert merged[0]["source_cue_ids"] == ["sub_051", "sub_054"]
    assert merged[0]["style_source_cue_id"] == "sub_051"
    assert merged[0]["target_range"] == [428, 452]
    assert merged[0]["text"] == "they"
    assert merged[0]["correction_profile"] == "merged_they_v3"


def test_visual_lane_and_pre_base_carrier_allocation_are_deterministic():
    plan = load_plan()
    assert plan["summary"]["lane_count"] == 5
    assert plan["summary"]["lane_usage"] == {"1": 71, "2": 22, "3": 16, "4": 5, "5": 1}
    assert plan["summary"]["same_lane_overlap_count"] == 0
    assert plan["same_lane_overlaps"] == []
    assert {row["target_track"] for row in plan["instances"]} == {3, 4, 5, 6, 7}
    assert plan["summary"]["carrier_track_usage"] == {"3": 71, "4": 22, "5": 16, "6": 5, "7": 1}
    assert plan["summary"]["carrier_overlap_count"] == 0
    assert plan["carrier_overlaps"] == []
    for lane in range(1, 6):
        rows = sorted(
            [row for row in plan["instances"] if row["lane"] == lane],
            key=lambda row: row["target_range"][0],
        )
        assert all(left["target_range"][1] <= right["target_range"][0] for left, right in zip(rows, rows[1:]))


def test_one_frame_visual_instance_uses_source_endpoint_padding_without_timeline_tail():
    plan = load_plan()
    by_id = {row["instance_id"]: row for row in plan["instances"]}
    row = by_id["sub_073"]

    assert row["target_range"] == [521, 522]
    assert row["target_track"] == 3
    assert row["carrier_range"] == [521, 522]
    assert row["carrier_track"] == 3
    assert row["carrier_padding"] is None
    assert row["append_source_end_padding_frames"] == 1
    assert plan["summary"]["one_frame_carrier_count"] == 1
    assert plan["summary"]["one_frame_carrier_ids"] == ["sub_073"]
    assert plan["carrier_overrides"] == []

def test_runtime_base_collision_audit_relocates_only_come_to_v7():
    plan = load_plan()
    base_inventory = [{
        "name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
        "media_pool_item_name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
        "track_index": 4,
        "start": 429,
        "end": 434,
        "duration": 5,
    }]
    resolved = rollout.resolve_base_carrier_collisions(plan["instances"], base_inventory)

    assert resolved["ok"] is True
    assert resolved["relocation_count"] == 1
    assert resolved["relocation_ids"] == ["sub_052"]
    assert resolved["remaining_base_collisions"] == []
    assert resolved["carrier_overlaps"] == []
    assert resolved["carrier_track_usage"] == {"3": 71, "4": 21, "5": 16, "6": 5, "7": 2}

    by_id = {row["instance_id"]: row for row in resolved["instances"]}
    assert by_id["sub_052"]["target_track"] == 4
    assert by_id["sub_052"]["target_range"] == [430, 452]
    assert by_id["sub_052"]["carrier_track"] == 7
    assert by_id["sub_052"]["carrier_range"] == [430, 452]
    assert resolved["relocations"][0]["base_collisions"] == [{
        "name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
        "media_pool_item_name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
        "track_index": 4,
        "range": [429, 434],
    }]


def test_complete_115_payload_audit_has_no_late_batch_edge_case():
    plan = load_plan()
    base_inventory = [{
        "name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
        "media_pool_item_name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
        "track_index": 4,
        "start": 429,
        "end": 434,
        "duration": 5,
    }]
    resolved = rollout.resolve_base_carrier_collisions(plan["instances"], base_inventory)
    marker = object()
    carrier_source = {
        "media_pool_item": marker,
        "source_start": 0,
        "attempts": [{"duration": 96}],
    }
    audit = rollout.audit_append_payloads(resolved["instances"], base_inventory, carrier_source)

    assert audit["ok"] is True
    assert audit["payload_count"] == 115
    assert audit["issue_count"] == 0
    assert audit["duplicate_placements"] == []
    assert audit["carrier_overlaps"] == []
    assert all(row["clip_info"]["endFrame"] > row["clip_info"]["startFrame"] for row in audit["rows"])
    assert max(row["clip_info"]["endFrame"] for row in audit["rows"]) < 96
    come = next(row for row in audit["rows"] if row["cue_id"] == "sub_052")
    assert come["carrier_track"] == 7
    assert come["carrier_range"] == [430, 452]
    assert come["clip_info"] == {
        "startFrame": 0,
        "endFrame": 22,
        "recordFrame": 430,
        "trackIndex": 7,
        "mediaType": 1,
    }


def test_payload_audit_rejects_unresolved_base_collision_before_append():
    plan = load_plan()
    base_inventory = [
        {
            "name": f"blocker_v{track}",
            "media_pool_item_name": f"blocker_v{track}",
            "track_index": track,
            "start": 429,
            "end": 452,
            "duration": 23,
        }
        for track in range(3, 8)
    ]
    resolved = rollout.resolve_base_carrier_collisions(plan["instances"], base_inventory)

    assert resolved["ok"] is False
    assert any(row["instance_id"] == "sub_052" for row in resolved["unresolved"])


def test_all_eight_accepted_animations_fit_their_lifecycle_instances():
    plan = load_plan()
    animated = [row for row in plan["instances"] if row["animation_selected"]]
    assert [row["instance_id"] for row in animated] == [
        "sub_019",
        "sub_052",
        "sub_057",
        "sub_058",
        "sub_065",
        "sub_078",
        "sub_081",
        "sub_116",
    ]
    for row in animated:
        duration = row["target_range"][1] - row["target_range"][0]
        assert max(target["local_frame"] for target in row["animation"]["targets"]) < duration


def test_controller_source_ranges_are_used_instead_of_reinvented_transcript_ranges():
    plan = load_plan()
    catalog = {row["cue_id"]: row for row in plan["source_catalog"]}
    assert catalog["sub_022"]["source_range"] == [280, 283]
    assert catalog["sub_027"]["source_range"] == [305, 308]
    assert catalog["sub_115"]["source_range"] == [894, 897]
    by_instance = {row["instance_id"]: row for row in plan["instances"]}
    assert by_instance["sub_022"]["source_range"] == [280, 283]
    assert by_instance["sub_022"]["target_range"] == [278, 286]


def test_special_v3_corrections_are_preserved_without_affecting_other_instances():
    plan = load_plan()
    profiles = {row["instance_id"]: row["correction_profile"] for row in plan["instances"]}
    assert profiles["sub_052"] == "come_v3"
    assert profiles["visual_instance_sub_051_sub_054"] == "merged_they_v3"
    assert sum(1 for value in profiles.values() if value == "source_comp") == 113


def test_batching_is_track_local_and_bounded():
    plan = load_plan()
    batches = rollout.batch_rows(rollout.append_specs(plan["instances"]), size=8)
    assert batches
    assert sum(len(batch) for batch in batches) == 115
    assert all(1 <= len(batch) <= 8 for batch in batches)
    assert all(len({row["carrier_track"] for row in batch}) == 1 for batch in batches)
    assert [row["carrier_range"][0] for row in batches[0]] == sorted(row["carrier_range"][0] for row in batches[0])
    one_frame = next(row for batch in batches for row in batch if row["cue_id"] == "sub_073")
    assert one_frame["carrier_range"] == [521, 522]
    assert one_frame["carrier_track"] == 3


def test_signature_comparison_supports_source_preservation_and_special_overrides():
    source = {
        "Center": [0.5, 0.6],
        "Size": 0.1,
        "Red1": 0.7,
        "Enabled2": 1.0,
        "Opacity1": 1.0,
    }
    exact = rollout.signature_matches(source, source)
    assert exact["ok"] is True
    overridden_actual = dict(source)
    overridden_actual["Size"] = 0.2
    overridden_actual["Enabled2"] = 0.0
    overridden = rollout.signature_matches(
        overridden_actual,
        source,
        overrides={"Size": 0.2, "Enabled2": 0.0},
    )
    assert overridden["ok"] is True
    ignored = rollout.signature_matches(
        {"Center": [0.1, 0.2], "Size": 0.1, "Red1": 0.7, "Enabled2": 1.0, "Opacity1": 0.4},
        source,
        ignored={"Center", "Opacity1"},
    )
    assert ignored["ok"] is True


class FakeItem:
    def __init__(self, uid: str, track: int, start: int, end: int):
        self.uid = uid
        self.track = track
        self.start = start
        self.end = end
        self.name = f"raw_{uid}"

    def GetUniqueId(self):
        return self.uid

    def GetName(self):
        return self.name

    def SetName(self, value):
        self.name = value
        return True

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetFusionCompCount(self):
        return 0

    def GetMediaPoolItem(self):
        return None


class FakeTimeline:
    def __init__(self, items):
        self.items = list(items)

    def GetTrackCount(self, track_type):
        return max((item.track for item in self.items), default=1) if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, track_index):
        if track_type != "video":
            return []
        return [item for item in self.items if item.track == track_index]


class FakeMediaPool:
    def __init__(self, timeline):
        self.timeline = timeline
        self.created = []

    def AppendToTimeline(self, clip_infos):
        self.created = [
            FakeItem(
                f"new_{index}",
                int(info["trackIndex"]),
                int(info["recordFrame"]),
                int(info["recordFrame"]) + int(info["endFrame"]) - int(info["startFrame"]),
            )
            for index, info in enumerate(clip_infos)
        ]
        self.timeline.items.extend(self.created)
        return list(reversed(self.created))



def test_duplicate_base_inventory_comparison_ignores_resolve_generated_unique_ids():
    source = [
        {
            "name": "clip.mp4",
            "unique_id": "source-id",
            "track_index": 1,
            "start": 0,
            "end": 100,
            "duration": 100,
            "media_pool_item_name": "clip.mp4",
        },
        {
            "name": "Cross Dissolve",
            "unique_id": "source-transition-id",
            "track_index": 1,
            "start": 96,
            "end": 100,
            "duration": 4,
            "media_pool_item_name": None,
        },
    ]
    duplicate = [
        dict(source[0], unique_id="duplicate-id"),
        dict(source[1], unique_id="duplicate-transition-id"),
    ]

    comparison = rollout.compare_non_caption_inventory(source, duplicate)

    assert comparison["ok"] is True
    assert comparison["source_count"] == 2
    assert comparison["target_count"] == 2
    assert comparison["first_mismatch"] is None
    assert "unique_id" not in comparison["comparison_fields"]


def test_duplicate_base_inventory_comparison_still_rejects_semantic_drift():
    source = [
        {
            "name": "clip.mp4",
            "unique_id": "source-id",
            "track_index": 1,
            "start": 0,
            "end": 100,
            "duration": 100,
            "media_pool_item_name": "clip.mp4",
        }
    ]
    shifted = [dict(source[0], unique_id="duplicate-id", end=101, duration=101)]

    comparison = rollout.compare_non_caption_inventory(source, shifted)

    assert comparison["ok"] is False
    assert comparison["first_mismatch"] == {
        "index": 0,
        "source": {field: source[0].get(field) for field in rollout.BASE_INVENTORY_STABLE_FIELDS},
        "target": {field: shifted[0].get(field) for field in rollout.BASE_INVENTORY_STABLE_FIELDS},
    }

def test_append_assignment_matches_actual_placement_not_return_order(monkeypatch):
    timeline = FakeTimeline([FakeItem("base", 1, 0, 100)])
    media_pool = FakeMediaPool(timeline)
    monkeypatch.setattr(rollout.time, "sleep", lambda _seconds: None)
    specs = [
        {"cue_id": "a", "name": "A", "target_range": [10, 15], "target_track": 3},
        {"cue_id": "b", "name": "B", "target_range": [20, 27], "target_track": 3},
    ]
    result = rollout.append_batch_by_placement(
        media_pool,
        timeline,
        {"media_pool_item": object(), "source_start": 0},
        specs,
    )
    assert result["ok"] is True
    assert result["assigned_count"] == 2
    assert [row["summary"]["name"] for row in result["rows"]] == ["A", "B"]
    assert [row["summary"]["start"] for row in result["rows"]] == [10, 20]


def test_append_never_emits_a_zero_length_inclusive_source_range(monkeypatch):
    plan = load_plan()
    one_frame_instance = next(row for row in plan["instances"] if row["instance_id"] == "sub_073")
    spec = rollout.append_specs([one_frame_instance])[0]
    timeline = FakeTimeline([FakeItem("base", 1, 0, 100)])
    media_pool = FakeMediaPool(timeline)
    monkeypatch.setattr(rollout.time, "sleep", lambda _seconds: None)

    result = rollout.append_batch_by_placement(
        media_pool,
        timeline,
        {"media_pool_item": object(), "source_start": 0},
        [spec],
    )

    assert result["ok"] is True
    assert len(result["clip_infos"]) == 1
    clip_info = result["clip_infos"][0]
    assert clip_info["startFrame"] == 0
    assert clip_info["endFrame"] == 1
    assert clip_info["mediaType"] == 1
    assert clip_info["trackIndex"] == 3
    assert clip_info["recordFrame"] == 521
    assert result["rows"][0]["summary"]["start"] == 521
    assert result["rows"][0]["summary"]["end"] == 522
    assert result["rows"][0]["summary"]["duration"] == 1


def test_all_115_append_payloads_use_one_source_endpoint_padding_frame():
    plan = load_plan()
    base_inventory = [{
        "name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
        "media_pool_item_name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
        "track_index": 4,
        "start": 429,
        "end": 434,
        "duration": 5,
    }]
    resolved = rollout.resolve_base_carrier_collisions(plan["instances"], base_inventory)
    audit = rollout.audit_append_payloads(
        resolved["instances"],
        base_inventory,
        {"media_pool_item": object(), "source_start": 0, "attempts": [{"duration": 96}]},
    )

    assert audit["ok"] is True
    assert audit["append_source_end_padding_frames"] == 1
    assert len(audit["rows"]) == 115
    for row in audit["rows"]:
        duration = row["carrier_range"][1] - row["carrier_range"][0]
        assert row["clip_info"]["endFrame"] - row["clip_info"]["startFrame"] == duration
        assert row["append_source_span"] == duration + 1


def test_strict_carrier_placement_rejects_the_v5_one_frame_short_readback():
    expected = {"target_track": 3, "target_range": [428, 452]}
    short = {"track_index": 3, "start": 428, "end": 451, "duration": 23}
    exact = {"track_index": 3, "start": 428, "end": 452, "duration": 24}

    assert rollout.exact_carrier_placement_ok(short, expected) is False
    assert rollout.exact_carrier_placement_ok(exact, expected) is True


def test_publisher_has_complete_ten_file_runtime_contract(tmp_path, monkeypatch):
    root = tmp_path
    (root / "AGENTS.md").write_text("rules", encoding="utf-8")
    for relative in publisher.SOURCE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    accepted = root / publisher.ACCEPTED_STATE
    accepted.parent.mkdir(parents=True, exist_ok=True)
    accepted.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(publisher, "run_id_now", lambda: "RUN_123456789012")

    receipt = publisher.publish(root)
    command = json.loads(Path(receipt["command_path"]).read_text(encoding="utf-8"))

    assert len(command["source_contract"]["hashes"]) == 10
    assert command["rollout"]["timeline_name"] == rollout.FINAL_TIMELINE_NAME
    assert command["rollout"]["expected_visual_instance_count"] == 115
    assert command["rollout"]["represented_cue_count"] == 116
    assert command["rollout"]["required_merge_aliases"] == ["sub_051", "sub_054"]
    assert command["rollout"]["caption_tracks"] == [3, 4, 5, 6, 7]
    assert command["rollout"]["one_frame_carrier_ids"] == ["sub_073"]
    assert command["rollout"]["one_frame_visible_range"] == [521, 522]
    assert command["rollout"]["one_frame_carrier_range"] == [521, 522]
    assert command["rollout"]["one_frame_carrier_track"] == 3
    assert command["rollout"]["one_frame_hidden_tail_frames"] == 0
    assert command["rollout"]["append_source_end_padding_frames"] == 1
    assert command["rollout"]["expected_exact_lifecycle_instance_count"] == 115


def test_validator_requires_behavioral_and_persistent_artifacts():
    required = set(validator.REQUIRED_SUCCESS_ARTIFACTS)
    assert "rollout_plan.json" in required
    assert "source_inventory_before.json" in required
    assert "carrier_append_progress.json" in required
    assert "comp_import_progress.json" in required
    assert "correction_application_progress.json" in required
    assert "persistent_readback.json" in required
    assert "rollout_result.json" in required
