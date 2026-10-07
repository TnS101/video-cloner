from pathlib import Path

from resolve_workspace.modules.video_cloner_step4_fresh_reel2_textplus import (
    _animation_result_matches_authority,
    _artifact_identity_snapshot,
    _inventory_delta,
    _representative_overlap,
    _select_owned_timeline,
    _textplus_provision_matches_titles,
    _timeline_identity_rows,
)


class _Timeline:
    def __init__(self, name, unique_id):
        self.name = name
        self.unique_id = unique_id

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.unique_id


def test_artifact_identity_snapshot_captures_runtime_observation(tmp_path):
    artifact = tmp_path / "style.json"
    artifact.write_text("{}", encoding="utf-8")
    rows = _artifact_identity_snapshot(
        {"style_sha256": "expected"},
        {"style": artifact},
    )

    assert rows == [{
        "name": "style",
        "expected_sha256": "expected",
        "runtime_path": str(artifact.resolve()),
        "is_file": True,
        "observed_sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        "size": 2,
        "mtime_ns": rows[0]["mtime_ns"],
        "loaded_module_file": str(Path(__file__).resolve().parents[1] / "resolve_workspace/modules/video_cloner_step4_fresh_reel2_textplus.py"),
        "loaded_module_sha256": rows[0]["loaded_module_sha256"],
    }]


def test_social_animation_uses_frozen_adapter_result_contract():
    payload = {
        "authority": "visual_observed",
        "source_evidence_id": "style_event_sub_045",
        "source_type": "scale",
        "property": "Size",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
            {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
        ],
    }

    assert 23 + 1 == 24
    assert _animation_result_matches_authority(
        {"ok": True, "selected": True, "modified": True, "keyframes_written": 2},
        payload,
    )
    assert not _animation_result_matches_authority(
        {"ok": True, "selected": False, "modified": False, "keyframes_written": 0},
        payload,
    )


def test_overlap_pair_resolves_combined_simultaneous_composition():
    lifecycle = {
        "visual_overlap_pairs": [["caption_layer_sub_007", "caption_layer_sub_008"]],
        "visual_compositions": [{
            "composition_id": "visual_composition_sub_007__sub_008",
            "relation": {"mode": "simultaneous"},
            "window": [49, 62],
            "tokens": [
                {"token_id": "visual_token_sub_007", "semantic_ids": ["sub_007"], "window": [49, 53]},
                {"token_id": "visual_token_sub_008", "semantic_ids": ["sub_008"], "window": [49, 62]},
            ],
        }],
    }

    assert _representative_overlap(lifecycle) == {
        "composition_id": "visual_composition_sub_007__sub_008",
        "mode": "simultaneous",
        "window": [49, 62],
        "tokens": [
            {"token_id": "visual_token_sub_007", "semantic_ids": ["sub_007"], "window": [49, 53]},
            {"token_id": "visual_token_sub_008", "semantic_ids": ["sub_008"], "window": [49, 62]},
        ],
    }


def test_import_ownership_uses_direct_return_then_single_inventory_delta():
    existing = _Timeline("existing", "uid-existing")
    imported = _Timeline("VC_R2_S5_20260919T120000Z", "uid-new")
    before = _timeline_identity_rows([existing])
    delta = _inventory_delta(before, _timeline_identity_rows([existing, imported]))

    assert [(row["name"], row["unique_id"]) for row in delta] == [(imported.name, imported.unique_id)]
    assert _select_owned_timeline(imported, delta) == (imported, "direct_return")
    assert _select_owned_timeline(True, delta) == (imported, "inventory_delta")
    assert _select_owned_timeline(None, delta + [_timeline_identity_rows([_Timeline("other", "uid-other")])[0]]) == (None, "ambiguous")


def test_textplus_provision_requires_exact_requested_title_cardinality():
    titles = [{"caption_id": f"sub_{index:03d}"} for index in range(92)]

    def provision(created_count):
        return {"ok": True, "created_count": created_count, "rows": [{}] * created_count, "failures": []}

    assert not _textplus_provision_matches_titles(provision(91), titles)
    assert _textplus_provision_matches_titles(provision(92), titles)
    assert not _textplus_provision_matches_titles(provision(93), titles)
