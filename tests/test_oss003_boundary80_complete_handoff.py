import inspect

from resolve_workspace.modules import oss003_boundary80_complete_handoff as complete
from tests.test_oss003_blur_boundary80_repair import Comp


def test_preserves_outgoing_and_completes_incoming_active_path():
    outgoing = Comp(0, 79)
    old_out = next(tool for tool in outgoing.tools if tool.regid == "Blur")
    old_out.name = complete.OUTGOING_ACTIVE
    old_out.inputs["XBlurSize"].keys = {0: 0, 78: 4.8555, 79: 6.474}
    old_out.inputs["YBlurSize"].keys = dict(old_out.inputs["XBlurSize"].keys)
    outgoing_before = [(tool.regid, tool.name) for tool in outgoing.tools]
    verified = complete._verify_outgoing(outgoing, 0, 79)
    assert verified["ok"] is True
    assert verified["evaluated_values"]["XBlurSize"] == [(0, 0), (78, 4.8555), (79, 6.474)]
    assert outgoing_before == [(tool.regid, tool.name) for tool in outgoing.tools]

    incoming = Comp(0, 130)
    old_in = next(tool for tool in incoming.tools if tool.regid == "Blur")
    old_in.name = complete.OLD_INCOMING
    applied = complete._create_incoming(incoming, 0, 130, "run_1234567890abcdef")
    assert applied["active_path"]["active_name"] == "VC_OSS003_B80_INCOMING_1234567890ab"
    assert applied["topology"]["ok"] is True
    assert applied["evaluated_values"]["XBlurSize"] == [(0, 6.474), (1, 4.8555), (5, 0.0)]
    assert applied["old_orphan_outside_render_path"] is True
    assert old_in in incoming.tools


def test_completion_has_no_tool_deletion_and_save_is_manager_scoped_once():
    source = inspect.getsource(complete)
    assert "DeleteTool" not in source
    assert 'canary.carrier._call(manager, "SaveProject")' in source
    class Manager:
        def __init__(self): self.calls = 0
        def SaveProject(self): self.calls += 1; return True
    manager = Manager()
    assert complete._save_once(manager) is True
    assert manager.calls == 1
