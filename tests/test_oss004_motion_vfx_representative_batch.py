import inspect

import pytest

from resolve_workspace.modules import oss004_motion_vfx_representative_batch as runtime


def test_recipes_are_bounded_independent_channels_with_required_targets():
    recipes = runtime.normalize_recipes()
    assert len(recipes) == 6  # five human-review targets; the whip owns two clip sides.
    assert {row["id"] for row in recipes} >= {"boundary_211_slide_in", "boundary_461_whip_out", "boundary_461_whip_in", "boundary_629_slide_in"}
    assert all(set(row) == {"id", "shot", "window", "behavior", "position", "scale", "blur", "confidence", "provenance"} for row in recipes)
    assert runtime.SOURCE_INVENTORY["deferred_to_oss005"] == ["shot_001", "shot_002", "shot_004"]


def test_local_keys_map_only_inside_live_comp_range():
    recipe = runtime.normalize_recipes()[2]
    mapped = runtime.absolute_keys(recipe, 100, 189)
    assert mapped["position"] == [[100, [0.5, 0.5]], [189, [0.536, 0.485]]]
    assert mapped["scale"] == [[100, 1.0], [189, 1.18]]
    with pytest.raises(ValueError, match="comp_visible_range"):
        runtime.absolute_keys(recipe, 100, 188)


def test_transform_and_blur_mappings_preserve_source_direction():
    rows = {row["id"]: row for row in runtime.normalize_recipes()}
    assert rows["boundary_211_slide_in"]["position"] == [[0, [0.54, 0.49]], [5, [0.5, 0.5]]]
    assert rows["shot_004_push_in_pan"]["scale"] == [[0, 1.0], [89, 1.18]]
    assert rows["boundary_461_whip_out"]["blur"][-1] == [84, [2.7308, 0.6827]]
    assert rows["boundary_461_whip_in"]["blur"][0] == [0, [2.7308, 0.6827]]


def test_runtime_scope_has_no_transition_or_retime_mutation_and_no_legacy_cleanup():
    source = inspect.getsource(runtime)
    for forbidden in ("DeleteFusionCompByName", "DeleteTool", "SetProperty", "SetClipProperty", "ChangeClipSpeed", "ImportTimelineFromFile"):
        assert forbidden not in source
    assert '"MediaIn"' in source and '"Transform"' in source and '"MediaOut"' in source
    assert '"Blur"' in source
    assert "LoadFusionCompByName" in source


def test_selected_shots_are_exact_and_native_transitions_remain_contractual():
    assert [row["shot"] for row in runtime.normalize_recipes()] == [1, 3, 4, 5, 6, 8]
    assert runtime.BOUNDARIES == ((80, 11), (286, 11), (376, 11))
    assert runtime.DERIVATIVE_NAME.endswith("__OSS004_MOTION_VFX_V1")
