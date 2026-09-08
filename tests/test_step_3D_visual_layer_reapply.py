from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace/modules/step_3D_apply_visual_layers.py"
SPEC = importlib.util.spec_from_file_location("step3d_visual_layers", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PUBLISHER_PATH = ROOT / "scripts/davinci/prepare_step_3D_visual_layer_reapply_command.py"
PUBLISHER_SPEC = importlib.util.spec_from_file_location("step3d_visual_layers_publisher", PUBLISHER_PATH)
assert PUBLISHER_SPEC is not None and PUBLISHER_SPEC.loader is not None
PUBLISHER = importlib.util.module_from_spec(PUBLISHER_SPEC)
PUBLISHER_SPEC.loader.exec_module(PUBLISHER)


VALIDATOR_PATH = ROOT / "scripts/davinci/validate_step_3D_visual_layer_reapply.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "step3d_visual_layers_validator", VALIDATOR_PATH
)
assert VALIDATOR_SPEC is not None and VALIDATOR_SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def real_contract():
    return MODULE.validate_plan_contract(
        load(MODULE.POSITION_PLAN_REL),
        load(MODULE.LIFECYCLE_PLAN_REL),
        load(MODULE.ANIMATION_TARGETS_REL),
    )


def test_real_plan_contract_has_expected_partition():
    contract = real_contract()
    assert contract["summary"] == {
        "caption_count": 116,
        "animation_count": 8,
        "keyframe_count": 16,
        "translated_center_count": 4,
        "scale_animation_count": 4,
        "visual_primary_count": 49,
        "transcript_fallback_count": 67,
    }
    assert set(contract["expected_modifier_inputs"]["sub_052"]) == {"Center"}
    assert set(contract["expected_modifier_inputs"]["sub_019"]) == {"Size"}


def test_real_lifecycle_windows_are_unique_and_fit_animation_frames():
    contract = real_contract()
    windows = [tuple(row["lifecycle_window"]) for row in contract["lifecycle_items"]]
    assert len(windows) == len(set(windows)) == 116
    for animation in contract["animation_items"]:
        lifecycle = contract["lifecycle_by_cue"][animation["cue_id"]]["lifecycle_window"]
        duration = lifecycle[1] - lifecycle[0]
        assert max(target["local_frame"] for target in animation["targets"]) < duration


def test_match_caption_rows_uses_window_and_text_not_resolve_item_name():
    contract = real_contract()
    rows = []
    for layer in contract["lifecycle_items"]:
        rows.append({
            "item": object(),
            "comp": object(),
            "tool": object(),
            "track_index": 2,
            "start": layer["lifecycle_window"][0],
            "end": layer["lifecycle_window"][1],
            "text": layer["text"],
            "name": "Text",
        })
    matched = MODULE.match_caption_rows(contract["lifecycle_items"], rows)
    assert len(matched) == 116
    assert matched["sub_052"]["name"] == "Text"
    assert (matched["sub_081"]["start"], matched["sub_081"]["end"]) == (628, 656)


def test_match_caption_rows_rejects_duplicate_window():
    contract = real_contract()
    layer = contract["lifecycle_items"][0]
    row = {
        "item": object(),
        "comp": object(),
        "tool": object(),
        "track_index": 2,
        "start": layer["lifecycle_window"][0],
        "end": layer["lifecycle_window"][1],
        "text": layer["text"],
        "name": "Text",
    }
    with pytest.raises(ValueError, match="caption_window_match"):
        MODULE.match_caption_rows([layer], [row, dict(row)])


def test_match_caption_rows_rejects_wrong_text():
    contract = real_contract()
    layer = contract["lifecycle_items"][0]
    row = {
        "item": object(),
        "comp": object(),
        "tool": object(),
        "track_index": 2,
        "start": layer["lifecycle_window"][0],
        "end": layer["lifecycle_window"][1],
        "text": "wrong",
        "name": "Text",
    }
    with pytest.raises(ValueError, match="caption_text_match"):
        MODULE.match_caption_rows([layer], [row])


class FakeComp:
    def Lock(self):
        return True

    def Unlock(self):
        return True


class FakeAnimationHelper:
    def __init__(self):
        self.correct = False
        self.modifier_calls = []
        self.write_calls = []

    def input_targets_are_correct(self, tool, input_name, targets):
        return self.correct

    def ensure_modifier(self, comp, tool, input_name):
        self.modifier_calls.append(input_name)
        return {"ok": True, "created": True}

    def write_key(self, tool, input_name, frame, expected):
        self.write_calls.append((input_name, frame, expected))
        return {"ok": True}


def test_apply_animation_items_creates_expected_modifier_and_keys():
    helper = FakeAnimationHelper()
    item = {
        "cue_id": "sub_052",
        "animation_type": "slide",
        "targets": [
            {"input": "Center", "local_frame": 0, "expected": [0.1, 0.2]},
            {"input": "Center", "local_frame": 3, "expected": [0.3, 0.4]},
        ],
    }
    result = MODULE.apply_animation_items(
        {"sub_052": {"comp": FakeComp(), "tool": object()}},
        [item],
        helper,
    )
    assert result["modified_count"] == 1
    assert result["keyframes_written_count"] == 2
    assert helper.modifier_calls == ["Center"]
    assert [row[:2] for row in helper.write_calls] == [("Center", 0), ("Center", 3)]


def test_apply_animation_items_is_idempotent_when_targets_are_correct():
    helper = FakeAnimationHelper()
    helper.correct = True
    item = {
        "cue_id": "sub_019",
        "animation_type": "scale",
        "targets": [{"input": "Size", "local_frame": 0, "expected": 0.1}],
    }
    result = MODULE.apply_animation_items(
        {"sub_019": {"comp": FakeComp(), "tool": object()}},
        [item],
        helper,
    )
    assert result["modified_count"] == 0
    assert result["already_correct_count"] == 1
    assert helper.modifier_calls == []
    assert helper.write_calls == []


class FakePositionHelper:
    def __init__(self):
        self.correct = set()
        self.writes = []

    def target_position_is_correct(self, tool, item, tolerance):
        return item["cue_id"] in self.correct

    def write_position(self, comp, tool, item, tolerance):
        self.writes.append(item["cue_id"])
        return {"ok": True, "write_mode": item["position_write_mode"]}


def test_apply_position_items_handles_modified_and_idempotent_items():
    helper = FakePositionHelper()
    helper.correct.add("sub_001")
    items = [
        {"cue_id": "sub_001", "position_write_mode": "static_center", "target_center": [0.5, 0.5]},
        {"cue_id": "sub_002", "position_write_mode": "static_center", "target_center": [0.6, 0.6]},
    ]
    live = {
        "sub_001": {"comp": object(), "tool": object()},
        "sub_002": {"comp": object(), "tool": object()},
    }
    result = MODULE.apply_position_items(live, items, helper)
    assert result["position_count"] == 2
    assert result["already_correct_count"] == 1
    assert result["modified_count"] == 1
    assert helper.writes == ["sub_002"]

class CloneTool:
    def __init__(self, text, owner=None, name="Text1"):
        self.text = text
        self.owner = owner
        self.name = name

    def GetAttrs(self):
        return {"TOOLS_RegID": "TextPlus"}

    def Delete(self):
        if self.owner is not None:
            self.owner.tools.pop(self.name, None)
        return True


class CloneComp:
    def __init__(self, text):
        self.tool = CloneTool(text)

    def GetToolList(self, selected=False, regid=None):
        if regid not in (None, "TextPlus"):
            return {}
        return {"Text1": self.tool}

    def CopySettings(self, tools):
        assert self.tool in list(tools)
        return {"text": self.tool.text}


class SourceCloneItem:
    def __init__(self, text):
        self.text = text

    def ExportFusionComp(self, path, index):
        assert index == 1
        Path(path).write_text(self.text, encoding="utf-8")
        return True


class TargetCloneItem:
    def __init__(self):
        self.comps = {}

    def GetFusionCompNameList(self):
        return list(self.comps)

    def ImportFusionComp(self, path):
        name = "Composition 1"
        text = Path(path).read_text(encoding="utf-8")
        comp = CloneComp(text)
        self.comps[name] = comp
        return comp

    def GetFusionCompByIndex(self, index):
        values = list(self.comps.values())
        return values[index - 1] if 1 <= index <= len(values) else None

    def DeleteFusionCompByName(self, name):
        return self.comps.pop(name, None) is not None


class DefaultTargetTool:
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name

    def Delete(self):
        self.owner.tools.pop(self.name, None)
        return True


class AddCopySettingsComp:
    def __init__(self, *, paste_ok=True):
        self.tools = {"MediaOut1": DefaultTargetTool(self, "MediaOut1")}
        self.tool = None
        self.paste_ok = paste_ok
        self.locked = False

    def Lock(self):
        self.locked = True
        return True

    def Unlock(self):
        self.locked = False
        return True

    def GetToolList(self, selected=False, regid=None):
        if regid == "TextPlus":
            return {name: tool for name, tool in self.tools.items() if name == "Text1"}
        return dict(self.tools)

    def CopySettings(self, tools):
        names = [tool.name for tool in tools if isinstance(tool, DefaultTargetTool)]
        return {"kind": "default", "tool_names": names}

    def Paste(self, settings):
        if not self.paste_ok:
            return False
        if settings.get("kind") == "default":
            self.tool = None
            self.tools = {
                name: DefaultTargetTool(self, name)
                for name in settings["tool_names"]
            }
            return True
        self.tool = CloneTool(settings["text"], owner=self)
        self.tools = {
            "Text1": self.tool,
            "MediaOut1": DefaultTargetTool(self, "MediaOut1"),
        }
        return True


class AddCopySettingsTargetItem(TargetCloneItem):
    def __init__(self, *, paste_ok=True):
        super().__init__()
        self.paste_ok = paste_ok

    def ImportFusionComp(self, path):
        return None

    def AddFusionComp(self):
        name = "Composition 1"
        comp = AddCopySettingsComp(paste_ok=self.paste_ok)
        self.comps[name] = comp
        return comp


class DelayedHandleTargetItem(AddCopySettingsTargetItem):
    def __init__(self, *, unavailable_reads=2):
        super().__init__()
        self.unavailable_reads = unavailable_reads

    def AddFusionComp(self):
        super().AddFusionComp()
        return None

    def GetFusionCompByName(self, name):
        if self.unavailable_reads > 0:
            self.unavailable_reads -= 1
            return None
        return self.comps.get(name)

    def GetFusionCompByIndex(self, index):
        if self.unavailable_reads > 0:
            self.unavailable_reads -= 1
            return None
        return super().GetFusionCompByIndex(index)


class ExistingBlankTargetItem(AddCopySettingsTargetItem):
    def __init__(self):
        super().__init__()
        self.comps["Composition 1"] = AddCopySettingsComp()


class LoadByNameOnlyBlankTargetItem(ExistingBlankTargetItem):
    def __init__(self):
        super().__init__()
        self.load_calls = []

    def GetFusionCompByName(self, name):
        return None

    def GetFusionCompByIndex(self, index):
        return None

    def LoadFusionCompByName(self, name):
        self.load_calls.append(name)
        return self.comps.get(name)


class MockResolvePage:
    def __init__(self, page="edit", *, open_ok=True):
        self.page = page
        self.open_ok = open_ok
        self.open_calls = []

    def GetCurrentPage(self):
        return self.page

    def OpenPage(self, page):
        self.open_calls.append(page)
        if self.open_ok:
            self.page = page
            return True
        return False


class FusionPageRequiredBlankTargetItem(ExistingBlankTargetItem):
    def __init__(self, resolve):
        super().__init__()
        self.resolve = resolve
        self.load_calls = []

    def GetFusionCompByName(self, name):
        if self.resolve.GetCurrentPage() != "fusion":
            return None
        return self.comps.get(name)

    def GetFusionCompByIndex(self, index):
        if self.resolve.GetCurrentPage() != "fusion":
            return None
        return super().GetFusionCompByIndex(index)

    def LoadFusionCompByName(self, name):
        self.load_calls.append((self.resolve.GetCurrentPage(), name))
        if self.resolve.GetCurrentPage() != "fusion":
            return None
        return self.comps.get(name)


class ClonePositionHelper:
    @staticmethod
    def fusion_comp(item):
        return item.GetFusionCompByIndex(1)

    @staticmethod
    def textplus_tool(comp):
        return comp.tool if comp is not None else None

    @staticmethod
    def read_input(tool, name):
        return tool.text if name == "StyledText" else None


def test_export_and_clone_fusion_comps_then_rollback(tmp_path):
    source_live = {
        "sub_001": {"item": SourceCloneItem("I"), "text": "I"},
        "sub_002": {"item": SourceCloneItem("graduated"), "text": "graduated"},
    }
    paths, exports = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    assert len(exports) == 2
    assert all(row["size"] > 0 for row in exports)

    targets = {
        "sub_001": {"item": TargetCloneItem()},
        "sub_002": {"item": TargetCloneItem()},
    }
    result, rollback = MODULE.clone_fusion_comps(
        targets, source_live, paths, ClonePositionHelper()
    )
    assert result["ok"] is True
    assert result["imported_count"] == 2
    assert result["already_present_count"] == 0
    assert result["direct_import_count"] == 2
    assert result["add_copy_settings_count"] == 0
    assert targets["sub_001"]["text"] == "I"
    assert len(rollback) == 2

    rolled_back = MODULE.rollback_fusion_clones(rollback)
    assert rolled_back["ok"] is True
    assert all(not row["item"].GetFusionCompNameList() for row in targets.values())


def test_clone_fusion_comps_is_idempotent_for_matching_existing_comp(tmp_path):
    source_live = {"sub_001": {"item": SourceCloneItem("I"), "text": "I"}}
    paths, _ = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    target = TargetCloneItem()
    target.ImportFusionComp(str(paths["sub_001"]))
    targets = {"sub_001": {"item": target}}
    result, rollback = MODULE.clone_fusion_comps(
        targets, source_live, paths, ClonePositionHelper()
    )
    assert result["imported_count"] == 0
    assert result["already_present_count"] == 1
    assert result["direct_import_count"] == 0
    assert result["add_copy_settings_count"] == 0
    assert rollback == []


def test_clone_fusion_comps_rejects_wrong_existing_text(tmp_path):
    source_live = {"sub_001": {"item": SourceCloneItem("I"), "text": "I"}}
    paths, _ = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    target = TargetCloneItem()
    wrong = tmp_path / "wrong.comp"
    wrong.write_text("wrong", encoding="utf-8")
    target.ImportFusionComp(str(wrong))
    with pytest.raises(ValueError, match="target_existing_comp_text"):
        MODULE.clone_fusion_comps(
            {"sub_001": {"item": target}},
            source_live,
            paths,
            ClonePositionHelper(),
        )


def test_clone_fusion_comps_falls_back_to_add_comp_and_copy_settings(tmp_path):
    source_live = {
        "sub_001": {
            "item": SourceCloneItem("I"),
            "comp": CloneComp("I"),
            "text": "I",
        }
    }
    paths, _ = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    target = AddCopySettingsTargetItem()
    rollback = []
    state = {}

    result, returned_rollback = MODULE.clone_fusion_comps(
        {"sub_001": {"item": target}},
        source_live,
        paths,
        ClonePositionHelper(),
        rollback_records=rollback,
        mutation_state=state,
    )

    assert returned_rollback is rollback
    assert state == {"started": True}
    assert result["clone_strategy"] == MODULE.CLONE_STRATEGY
    assert result["imported_count"] == 1
    assert result["direct_import_count"] == 0
    assert result["add_copy_settings_count"] == 1
    assert result["items"][0]["clone_method"] == "add_fusion_comp_copy_settings"
    assert result["items"][0]["pasted_tool_count"] == 2
    assert target.GetFusionCompByIndex(1).tool.text == "I"


def test_clone_fusion_comps_waits_for_delayed_add_comp_handle(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE.time, "sleep", lambda _seconds: None)
    source_live = {
        "sub_001": {
            "item": SourceCloneItem("I"),
            "comp": CloneComp("I"),
            "text": "I",
        }
    }
    paths, _ = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    target = DelayedHandleTargetItem(unavailable_reads=3)
    rollback = []
    state = {}

    result, _ = MODULE.clone_fusion_comps(
        {"sub_001": {"item": target}},
        source_live,
        paths,
        ClonePositionHelper(),
        rollback_records=rollback,
        mutation_state=state,
    )

    assert state == {"started": True}
    assert result["add_copy_settings_count"] == 1
    assert result["recovered_blank_count"] == 0
    assert target.GetFusionCompByIndex(1).tool.text == "I"
    assert rollback[0]["action"] == "delete_comp"


def test_clone_fusion_comps_loads_named_existing_comp_when_getters_return_no_handle(tmp_path):
    source_live = {
        "sub_001": {
            "item": SourceCloneItem("I"),
            "comp": CloneComp("I"),
            "text": "I",
        }
    }
    paths, _ = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    target = LoadByNameOnlyBlankTargetItem()
    rollback = []
    state = {}

    result, _ = MODULE.clone_fusion_comps(
        {"sub_001": {"item": target}},
        source_live,
        paths,
        ClonePositionHelper(),
        rollback_records=rollback,
        mutation_state=state,
    )

    assert target.load_calls == ["Composition 1"]
    assert state == {"started": True}
    assert result["recovered_blank_count"] == 1
    assert result["items"][0]["clone_method"] == "recover_existing_blank_comp_copy_settings"
    assert rollback[0]["action"] == "restore_settings"


def test_activate_fusion_page_opens_and_restore_returns_to_original_page(monkeypatch):
    monkeypatch.setattr(MODULE.time, "sleep", lambda _seconds: None)
    resolve = MockResolvePage("edit")

    activation = MODULE.activate_fusion_page(resolve)

    assert activation == {
        "ok": True,
        "page_before": "edit",
        "page_after": "fusion",
        "open_called": True,
        "open_result": True,
    }
    restored = MODULE.restore_page(resolve, "edit")
    assert restored["ok"] is True
    assert restored["page_after"] == "edit"
    assert resolve.open_calls == ["fusion", "edit"]


def test_fusion_page_activation_exposes_named_existing_comp_for_recovery(tmp_path):
    source_live = {
        "sub_001": {
            "item": SourceCloneItem("I"),
            "comp": CloneComp("I"),
            "text": "I",
        }
    }
    paths, _ = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    resolve = MockResolvePage("edit")
    target = FusionPageRequiredBlankTargetItem(resolve)

    with pytest.raises(RuntimeError, match="target_existing_comp_handle:sub_001"):
        MODULE.clone_fusion_comps(
            {"sub_001": {"item": target}},
            source_live,
            paths,
            ClonePositionHelper(),
        )

    MODULE.activate_fusion_page(resolve)
    rollback = []
    state = {}
    result, _ = MODULE.clone_fusion_comps(
        {"sub_001": {"item": target}},
        source_live,
        paths,
        ClonePositionHelper(),
        rollback_records=rollback,
        mutation_state=state,
    )

    assert result["recovered_blank_count"] == 1
    assert state == {"started": True}
    assert target.GetFusionCompByIndex(1).tool.text == "I"
    assert len(target.load_calls) == 50
    assert set(target.load_calls) == {("edit", "Composition 1")}


def test_clone_fusion_comps_recovers_existing_blank_comp_and_rollback_restores_it(tmp_path):
    source_live = {
        "sub_001": {
            "item": SourceCloneItem("I"),
            "comp": CloneComp("I"),
            "text": "I",
        }
    }
    paths, _ = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    target = ExistingBlankTargetItem()
    original_tool_count = len(target.GetFusionCompByIndex(1).tools)
    rollback = []
    state = {}

    result, _ = MODULE.clone_fusion_comps(
        {"sub_001": {"item": target}},
        source_live,
        paths,
        ClonePositionHelper(),
        rollback_records=rollback,
        mutation_state=state,
    )

    assert state == {"started": True}
    assert result["imported_count"] == 1
    assert result["recovered_blank_count"] == 1
    assert result["items"][0]["clone_method"] == "recover_existing_blank_comp_copy_settings"
    assert target.GetFusionCompByIndex(1).tool.text == "I"
    assert rollback[0]["action"] == "restore_settings"

    rolled_back = MODULE.rollback_fusion_clones(rollback)
    assert rolled_back["ok"] is True
    restored = target.GetFusionCompByIndex(1)
    assert len(restored.tools) == original_tool_count
    assert restored.tool is None


def test_clone_fusion_comps_registers_fallback_before_paste_failure(tmp_path):
    source_live = {
        "sub_001": {
            "item": SourceCloneItem("I"),
            "comp": CloneComp("I"),
            "text": "I",
        }
    }
    paths, _ = MODULE.export_source_fusion_comps(source_live, tmp_path / "exports")
    target = AddCopySettingsTargetItem(paste_ok=False)
    rollback = []
    state = {}

    with pytest.raises(RuntimeError, match="target_comp_paste:sub_001"):
        MODULE.clone_fusion_comps(
            {"sub_001": {"item": target}},
            source_live,
            paths,
            ClonePositionHelper(),
            rollback_records=rollback,
            mutation_state=state,
        )

    assert state == {"started": True}
    assert len(rollback) == 1
    rolled_back = MODULE.rollback_fusion_clones(rollback)
    assert rolled_back["ok"] is True
    assert target.GetFusionCompNameList() == []



def test_target_union_flattens_position_and_animation_targets():
    position_item = {
        "expected_animation_targets_after": [
            {"input": "Center", "local_frame": 0, "expected": [0.1, 0.2]},
            {"input": "Center", "local_frame": 3, "expected": [0.3, 0.4]},
        ]
    }
    animation_item = {
        "targets": [
            {"input": "Center", "local_frame": 3, "expected": [0.3, 0.4]},
            {"input": "Size", "local_frame": 0, "expected": 0.7},
        ]
    }

    targets = MODULE.target_union(position_item, animation_item)

    assert [(row["input"], row["local_frame"]) for row in targets] == [
        ("Center", 0),
        ("Center", 3),
        ("Size", 0),
    ]


def test_target_union_rejects_non_mapping_target_rows():
    with pytest.raises(ValueError, match="animation_target_type"):
        MODULE.target_union(
            {"expected_animation_targets_after": [["Center", 0]]},
            None,
        )

def test_source_visual_contract_gate_is_advisory_but_requires_target_readback():
    gate = MODULE.source_visual_contract_gate({
        "ok": False,
        "position_verified_count": 115,
        "animation_verified_count": 7,
        "keyframe_verified_count": 14,
        "failures": ["source_position:sub_052", "source_animation:sub_058"],
    })
    assert gate == {
        "ok": True,
        "authority": "ACCEPTED_SOURCE_COMP_IDENTITY_PLUS_PLAN_DRIVEN_TARGET_READBACK",
        "live_source_readback_ok": False,
        "live_source_readback_failures": [
            "source_position:sub_052",
            "source_animation:sub_058",
        ],
        "source_caption_fusion_and_text_gate": True,
        "target_position_readback_required": 116,
        "target_animation_readback_required": 8,
        "target_keyframe_readback_required": 16,
    }


def test_source_visual_contract_gate_records_clean_live_readback():
    gate = MODULE.source_visual_contract_gate({"ok": True, "failures": []})
    assert gate["ok"] is True
    assert gate["live_source_readback_ok"] is True
    assert gate["live_source_readback_failures"] == []


def test_load_module_suppresses_workspace_autorun_and_restores_environment(tmp_path, monkeypatch):
    marker = tmp_path / "autorun.txt"
    helper = tmp_path / "helper.py"
    helper.write_text(
        "import os\n"
        f"MARKER = {str(marker)!r}\n"
        "if os.environ.get('VC_DISABLE_WORKSPACE_AUTORUN') != '1':\n"
        "    open(MARKER, 'w', encoding='utf-8').write('ran')\n"
        "VALUE = 7\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("VC_DISABLE_WORKSPACE_AUTORUN", raising=False)
    loaded = MODULE.load_module(
        helper,
        "side_effect_free_helper",
        suppress_workspace_autorun=True,
    )
    assert loaded.VALUE == 7
    assert not marker.exists()
    assert "VC_DISABLE_WORKSPACE_AUTORUN" not in __import__("os").environ


def test_real_step3_helpers_import_without_running_workspace_entrypoints(monkeypatch):
    monkeypatch.delenv("VC_DISABLE_WORKSPACE_AUTORUN", raising=False)
    position = MODULE.load_module(
        ROOT / MODULE.POSITION_HELPER_REL,
        "test_step3b_helper_no_autorun",
        suppress_workspace_autorun=True,
    )
    animation = MODULE.load_module(
        ROOT / MODULE.ANIMATION_HELPER_REL,
        "test_step3c_helper_no_autorun",
        suppress_workspace_autorun=True,
    )
    assert callable(position.write_position)
    assert callable(animation.ensure_modifier)
    assert "VC_DISABLE_WORKSPACE_AUTORUN" not in __import__("os").environ



def test_lf_normalized_hash_matches_crlf_and_lf(tmp_path):
    lf = tmp_path / "lf.py"
    crlf = tmp_path / "crlf.py"
    lf.write_bytes(b"a = 1\nb = 2\n")
    crlf.write_bytes(b"a = 1\r\nb = 2\r\n")
    assert PUBLISHER.sha256_text_lf(lf) == PUBLISHER.sha256_text_lf(crlf)
    assert MODULE.sha256_text_lf(lf) == MODULE.sha256_text_lf(crlf)


def test_publisher_runtime_and_validator_share_complete_dependency_contract():
    assert PUBLISHER.SOURCE_HASH_CONTRACT_VERSION == MODULE.SOURCE_HASH_CONTRACT_VERSION == 2
    assert VALIDATOR.SOURCE_HASH_CONTRACT_VERSION == 2
    assert PUBLISHER.SOURCE_HASH_ALGORITHM == MODULE.SOURCE_HASH_ALGORITHM
    assert VALIDATOR.SOURCE_HASH_ALGORITHM == PUBLISHER.SOURCE_HASH_ALGORITHM
    assert tuple(PUBLISHER.SOURCE_DEPENDENCY_PATHS) == tuple(MODULE.SOURCE_DEPENDENCY_PATHS)
    assert VALIDATOR.SOURCE_DEPENDENCY_PATHS == set(PUBLISHER.SOURCE_DEPENDENCY_PATHS)
    assert PUBLISHER.TASK_ID == MODULE.TASK_ID == VALIDATOR.TASK_ID
    assert PUBLISHER.MODE == MODULE.MODE == VALIDATOR.MODE
    assert PUBLISHER.CLONE_STRATEGY == MODULE.CLONE_STRATEGY == VALIDATOR.CLONE_STRATEGY
    assert set(PUBLISHER.SOURCE_DEPENDENCY_PATHS) == {
        PUBLISHER.MODULE_REL,
        PUBLISHER.POSITION_HELPER_REL,
        PUBLISHER.ANIMATION_HELPER_REL,
        PUBLISHER.IMPORT_HELPER_REL,
        PUBLISHER.POSITION_PLAN_REL,
        PUBLISHER.ANIMATION_TARGETS_REL,
        PUBLISHER.LIFECYCLE_PLAN_REL,
        PUBLISHER.FCPXML_REL,
    }


def test_real_complete_source_manifest_passes_runtime_contract():
    manifest = PUBLISHER.source_hash_manifest(ROOT)
    assert len(manifest) == 8
    assert manifest[PUBLISHER.IMPORT_HELPER_REL] == MODULE.sha256_text_lf(
        ROOT / PUBLISHER.IMPORT_HELPER_REL
    )
    verified = MODULE.source_hash_contract(
        ROOT,
        {
            "source_hash_contract_version": MODULE.SOURCE_HASH_CONTRACT_VERSION,
            "source_hash_algorithm": MODULE.SOURCE_HASH_ALGORITHM,
            "source_hashes": manifest,
        },
    )
    assert verified == manifest


def test_publisher_manifest_and_runtime_contract_accept_crlf_equivalent_sources(
    tmp_path, monkeypatch
):
    dependencies = ("alpha.py", "nested/beta.json")
    monkeypatch.setattr(PUBLISHER, "SOURCE_DEPENDENCY_PATHS", dependencies)
    monkeypatch.setattr(MODULE, "SOURCE_DEPENDENCY_PATHS", dependencies)

    (tmp_path / "nested").mkdir()
    (tmp_path / "alpha.py").write_bytes(b"VALUE = 7\r\n")
    (tmp_path / "nested/beta.json").write_bytes(b"{\r\n  \"ok\": true\r\n}\r\n")

    manifest = PUBLISHER.source_hash_manifest(tmp_path)
    assert set(manifest) == set(dependencies)
    verified = MODULE.source_hash_contract(
        tmp_path,
        {
            "source_hash_contract_version": MODULE.SOURCE_HASH_CONTRACT_VERSION,
            "source_hash_algorithm": MODULE.SOURCE_HASH_ALGORITHM,
            "source_hashes": manifest,
        },
    )
    assert verified == manifest


def test_runtime_source_hash_contract_rejects_missing_dependency(tmp_path, monkeypatch):
    dependencies = ("alpha.py", "beta.py")
    monkeypatch.setattr(MODULE, "SOURCE_DEPENDENCY_PATHS", dependencies)
    (tmp_path / "alpha.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "beta.py").write_text("B = 2\n", encoding="utf-8")
    manifest = {
        "alpha.py": MODULE.sha256_text_lf(tmp_path / "alpha.py"),
    }
    with pytest.raises(ValueError, match="source_hash_payload_paths"):
        MODULE.source_hash_contract(
            tmp_path,
            {
                "source_hash_contract_version": MODULE.SOURCE_HASH_CONTRACT_VERSION,
                "source_hash_algorithm": MODULE.SOURCE_HASH_ALGORITHM,
                "source_hashes": manifest,
            },
        )


def test_runtime_source_hash_contract_rejects_extra_dependency(tmp_path, monkeypatch):
    dependencies = ("alpha.py",)
    monkeypatch.setattr(MODULE, "SOURCE_DEPENDENCY_PATHS", dependencies)
    (tmp_path / "alpha.py").write_text("A = 1\n", encoding="utf-8")
    manifest = {
        "alpha.py": MODULE.sha256_text_lf(tmp_path / "alpha.py"),
        "../unexpected.py": "0" * 64,
    }
    with pytest.raises(ValueError, match="source_hash_payload_paths"):
        MODULE.source_hash_contract(
            tmp_path,
            {
                "source_hash_contract_version": MODULE.SOURCE_HASH_CONTRACT_VERSION,
                "source_hash_algorithm": MODULE.SOURCE_HASH_ALGORITHM,
                "source_hashes": manifest,
            },
        )


def test_runtime_source_hash_contract_rejects_changed_dependency(tmp_path, monkeypatch):
    dependencies = ("alpha.py",)
    monkeypatch.setattr(MODULE, "SOURCE_DEPENDENCY_PATHS", dependencies)
    path = tmp_path / "alpha.py"
    path.write_text("A = 1\n", encoding="utf-8")
    manifest = {"alpha.py": MODULE.sha256_text_lf(path)}
    path.write_text("A = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_hash:alpha.py"):
        MODULE.source_hash_contract(
            tmp_path,
            {
                "source_hash_contract_version": MODULE.SOURCE_HASH_CONTRACT_VERSION,
                "source_hash_algorithm": MODULE.SOURCE_HASH_ALGORITHM,
                "source_hashes": manifest,
            },
        )


def test_runtime_source_hash_contract_rejects_bad_digest(tmp_path, monkeypatch):
    dependencies = ("alpha.py",)
    monkeypatch.setattr(MODULE, "SOURCE_DEPENDENCY_PATHS", dependencies)
    (tmp_path / "alpha.py").write_text("A = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_hash_payload_digest:alpha.py"):
        MODULE.source_hash_contract(
            tmp_path,
            {
                "source_hash_contract_version": MODULE.SOURCE_HASH_CONTRACT_VERSION,
                "source_hash_algorithm": MODULE.SOURCE_HASH_ALGORITHM,
                "source_hashes": {"alpha.py": "not-a-hash"},
            },
        )


def test_runtime_source_hash_contract_rejects_wrong_version(tmp_path, monkeypatch):
    dependencies = ("alpha.py",)
    monkeypatch.setattr(MODULE, "SOURCE_DEPENDENCY_PATHS", dependencies)
    path = tmp_path / "alpha.py"
    path.write_text("A = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_hash_contract_version"):
        MODULE.source_hash_contract(
            tmp_path,
            {
                "source_hash_contract_version": 1,
                "source_hash_algorithm": MODULE.SOURCE_HASH_ALGORITHM,
                "source_hashes": {"alpha.py": MODULE.sha256_text_lf(path)},
            },
        )


def test_runtime_source_hash_contract_rejects_undeclared_algorithm(tmp_path, monkeypatch):
    dependencies = ("alpha.py",)
    monkeypatch.setattr(MODULE, "SOURCE_DEPENDENCY_PATHS", dependencies)
    path = tmp_path / "alpha.py"
    path.write_text("A = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_hash_algorithm"):
        MODULE.source_hash_contract(
            tmp_path,
            {
                "source_hash_contract_version": MODULE.SOURCE_HASH_CONTRACT_VERSION,
                "source_hashes": {"alpha.py": MODULE.sha256_text_lf(path)},
            },
        )
