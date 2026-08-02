from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_vc_agent_live.py"
SPEC = importlib.util.spec_from_file_location("vc_installer", SCRIPT)
installer = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self): self.tmp = Path(tempfile.mkdtemp(prefix="vc_installer_test_"))
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def test_selects_one_roaming_anchor_directory(self):
        roaming = self.tmp / "Roaming" / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Edit"
        other = self.tmp / "portable" / "Scripts" / "Edit"
        for directory in (roaming, other):
            directory.mkdir(parents=True); (directory / installer.ANCHOR).write_text(""); (directory / "resolve_apply_video_cloner_metadata.py").write_text("")
        with patch.dict("os.environ", {"APPDATA": str(self.tmp / "Roaming")}, clear=False):
            self.assertEqual(installer.select_canonical([other, roaming]), roaming.resolve())

    def test_removes_stale_bridge_pyc(self):
        directory = self.tmp / "Scripts" / "Edit" / "__pycache__"; directory.mkdir(parents=True)
        stale = directory / "VC_Agent_Bridge.cpython-311.pyc"; stale.write_bytes(b"x")
        self.assertEqual(installer.remove_bridge_files(directory.parent), [str(stale)])
        self.assertFalse(stale.exists())

    def test_aborts_when_resolve_running(self):
        repo = self.tmp / "repo"; (repo / "resolve_workspace").mkdir(parents=True); (repo / "resolve_workspace" / installer.LAUNCHER).write_text("")
        with patch.object(installer, "running_processes", return_value=["Resolve.exe"]):
            self.assertEqual(installer.install(repo), 1)
