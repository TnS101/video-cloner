from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vc_launcher_test_"))
        self.repo = self.tmp / "repo"; (self.repo / "resolve_workspace").mkdir(parents=True)
        self.launcher = self.tmp / "Scripts" / "Edit" / "VC_Run_Agent_Task.py"; self.launcher.parent.mkdir(parents=True)
        shutil.copy2(Path(__file__).resolve().parents[1] / "resolve_workspace" / "VC_Run_Agent_Task.py", self.launcher)
        self.config = self.launcher.with_name("VC_Run_Agent_Task.config.json")
        self.config.write_text(json.dumps({"schema_version": 1, "repository_root": str(self.repo), "bridge_module": "resolve_workspace\\VC_Agent_Bridge.py", "command_queue": ".agent\\commands"}), encoding="utf-8")

    def tearDown(self) -> None: shutil.rmtree(self.tmp, ignore_errors=True)

    def execute(self, extra=None, include_file=True):
        ns = {"__name__": "ResolveWorkspaceScript"}
        if include_file: ns["__file__"] = str(self.launcher)
        ns.update(extra or {})
        exec(compile(self.launcher.read_text(encoding="utf-8"), str(self.launcher), "exec"), ns)

    def test_non_main_runs_and_forwards_globals(self):
        marker = self.tmp / "called.json"
        (self.repo / "resolve_workspace" / "VC_Agent_Bridge.py").write_text("import json\nfrom pathlib import Path\ndef workspace_main(resolve=None, fusion=None):\n Path(r'" + str(marker) + "').write_text(json.dumps({'resolve': resolve, 'fusion': fusion})); return 0\n", encoding="utf-8")
        self.execute({"resolve": "RESOLVE", "fusion": "FUSION"})
        self.assertEqual(json.loads(marker.read_text()), {"resolve": "RESOLVE", "fusion": "FUSION"})
        self.assertIn("repository_bridge_loaded", (self.repo / ".agent" / "logs" / "VC_Run_Agent_Task_bootstrap.log").read_text())

    def test_directory_trace_precedes_missing_config(self):
        self.config.unlink(); self.execute()
        text = self.launcher.with_name("VC_Run_Agent_Task_bootstrap.log").read_text()
        self.assertIn("launcher_started=true", text); self.assertIn("Traceback", text)

    def test_invalid_repository_root_writes_traceback(self):
        self.config.write_text(json.dumps({"schema_version": 1, "repository_root": str(self.tmp / "missing")}), encoding="utf-8")
        self.execute(); self.assertIn("Traceback", self.launcher.with_name("VC_Run_Agent_Task_bootstrap.log").read_text())

    def test_uses_argv_when_resolve_omits_file_global(self):
        (self.repo / "resolve_workspace" / "VC_Agent_Bridge.py").write_text("def workspace_main(resolve=None, fusion=None): return 0\n", encoding="utf-8")
        original = sys.argv[:]
        try:
            sys.argv = [str(self.launcher)]
            self.execute(include_file=False)
        finally:
            sys.argv = original
        self.assertTrue(self.launcher.with_name("VC_Run_Agent_Task_bootstrap.log").is_file())
