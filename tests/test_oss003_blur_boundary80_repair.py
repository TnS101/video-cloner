import json
import shutil
from pathlib import Path

from resolve_workspace.modules import oss003_blur_boundary80_repair as repair
from scripts.davinci import prepare_oss003_blur_boundary80_repair as prepare


class Input:
    def __init__(self): self.connected, self.keys = None, {}
    def GetConnectedOutput(self): return self.connected
    def __setitem__(self, frame, value): self.keys[int(frame)] = float(value)
    def __getitem__(self, frame): return self.keys.get(int(frame), 0.0)


class Tool:
    def __init__(self, regid, name):
        self.regid, self.name, self.pass_through = regid, name, False
        self.inputs = {key: Input() for key in ("Input", "XBlurSize", "YBlurSize")}
    def GetAttrs(self): return {"TOOLS_RegID": self.regid, "TOOLS_Name": self.name, "TOOLB_PassThrough": self.pass_through}
    def SetAttrs(self, attrs): self.pass_through = bool(attrs.get("TOOLB_PassThrough", self.pass_through)); self.name = attrs.get("TOOLS_Name", self.name); return True
    def FindInput(self, name): return self.inputs.get(name)
    def FindMainOutput(self, _index): return self
    def ConnectInput(self, name, output): self.inputs[name].connected = output; return True
    def AddModifier(self, name, _kind): self.inputs[name].connected = object(); return True
    def GetInput(self, name, frame=None): return self.inputs[name][0 if frame is None else frame]


class Comp:
    def __init__(self, start, end):
        self.attrs = {"COMPN_GlobalStart": start, "COMPN_GlobalEnd": end, "COMPN_RenderStart": start, "COMPN_RenderEnd": end}
        media_in, old_blur, media_out = Tool("MediaIn", "MediaIn1"), Tool("Blur", "OLD_BLUR"), Tool("MediaOut", "MediaOut1")
        old_blur.ConnectInput("Input", media_in); media_out.ConnectInput("Input", old_blur)
        self.tools = [media_in, old_blur, media_out]
    def GetAttrs(self): return dict(self.attrs)
    def GetToolList(self, _selected): return {index: tool for index, tool in enumerate(self.tools, 1)}
    def AddTool(self, kind, *_args): tool = Tool(kind, kind); self.tools.append(tool); return tool
    def DeleteTool(self, tool): self.tools.remove(tool)


def test_frame_conversion_uses_visible_comp_range_not_timeline_or_zero():
    outgoing, incoming = Comp(100, 179), Comp(500, 630)
    assert repair._comp_range(outgoing, 80)[:2] == (100, 179)
    assert repair._comp_range(incoming, 131)[:2] == (500, 630)
    assert repair._keys("outgoing", 100, 179) == [(100, 0.0), (175, 0.0), (178, 4.8555), (179, 6.474)]
    assert repair._keys("incoming", 500, 630) == [(500, 6.474), (501, 4.8555), (505, 0.0), (630, 0.0)]


def test_reconciles_media_in_blur_media_out_and_samples_rendered_frames():
    comp = Comp(100, 179)
    old = next(tool for tool in comp.tools if tool.regid == "Blur")
    untouched = ("cuts", (0, 80, 211), "captions", 112, "audio", "same")
    row = repair._reconcile(comp, old, "outgoing", 100, 179, "run_abcdef1234567890")
    assert row["topology"]["ok"] is True
    assert row["evaluated_frames"] == [100, 178, 179]
    assert row["evaluated_values"]["XBlurSize"] == [(100, 0.0), (178, 4.8555), (179, 6.474)]
    assert row["evaluated_values"]["YBlurSize"] == row["evaluated_values"]["XBlurSize"]
    assert [tool.regid for tool in comp.tools].count("Blur") == 1
    assert untouched == ("cuts", (0, 80, 211), "captions", 112, "audio", "same")


def test_publishes_exactly_one_boundary80_command(tmp_path: Path):
    module = tmp_path / prepare.MODULE_RELATIVE
    module.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve().parents[1] / prepare.MODULE_RELATIVE, module)
    failed = tmp_path / ".agent/commands/failed" / f"old_{repair.OLD_RUN_ID}.json"
    failed.parent.mkdir(parents=True, exist_ok=True)
    failed.write_text("{}")
    result = prepare.publish(tmp_path)
    pending = list((tmp_path / ".agent/commands/pending").glob("*.json"))
    command = json.loads(pending[0].read_text())
    assert len(pending) == 1
    assert command["payload"]["boundary_frame"] == 80
    assert command["payload"]["expected_old_comp_names"] == list(repair.TARGETS.values())
    assert command["payload"]["peak_blur"] == 6.474
    assert result["run_id"] == command["run_id"]
