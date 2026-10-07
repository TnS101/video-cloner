from argparse import Namespace

from scripts.davinci.resolve_apply_video_cloner_metadata import probe_safe_textplus_shading


class FakeInput:
    def __init__(self, name):
        self.name = name

    def GetAttrs(self):
        return {"INPS_ID": self.name, "INPS_Name": self.name}


class FakeTextPlus:
    def __init__(self):
        self.values = {f"Enabled{index}": 0 for index in range(2, 9)}
        self.writes = []

    def GetInputList(self):
        names = list(self.values)
        if self.values["Enabled2"]:
            names += ["ElementShape2", "Red2", "Green2", "Blue2", "Alpha2", "Thickness2", "OutsideOnly2"]
        return {name: FakeInput(name) for name in names}

    def SetInput(self, name, value):
        if name not in self.GetInputList():
            return False
        self.values[name] = value
        self.writes.append((name, value))
        return True

    def GetInput(self, name, *_args):
        return self.values.get(name)


class FakeComp:
    def __init__(self):
        self.locked = False

    def Lock(self):
        self.locked = True

    def Unlock(self):
        self.locked = False


def test_requested_outline_is_enabled_before_its_controls_are_written():
    tool = FakeTextPlus()
    comp = FakeComp()
    args = Namespace(
        caption_apply_outline=True,
        caption_apply_shadow=False,
        caption_shading_probe_only=False,
        caption_outline_element=2,
        caption_shadow_element=3,
        caption_outline_width_scale=1.0,
        caption_outline_thickness=None,
        caption_shadow_opacity=None,
        caption_shadow_offset_x=0.003,
        caption_shadow_offset_y=0.003,
        caption_shadow_softness=None,
    )

    result = probe_safe_textplus_shading(
        tool,
        {"stroke_width": 5, "font_size_px": 91, "stroke_color": "#7d878b"},
        args,
        comp=comp,
    )

    assert result["safe"] is True
    assert result["can_write_stroke"] is True
    assert result["outline"]["applied"] is True
    assert tool.writes.index(("Enabled2", 1)) < tool.writes.index(("ElementShape2", 1))
    assert tool.values["ElementShape2"] == 1
    assert tool.values["Enabled2"] == 1
    assert all(tool.values[f"Enabled{index}"] == 0 for index in range(3, 9))
    assert comp.locked is False
