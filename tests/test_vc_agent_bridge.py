from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from resolve_workspace import VC_Agent_Bridge as bridge


class BridgeQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vc_bridge_test_"))
        self.repo = self.tmp / "repo"
        self.queue = self.repo / ".agent" / "commands"
        for name in bridge.QUEUE_DIRS:
            (self.queue / name).mkdir(parents=True)
        (self.repo / "resolve_workspace" / "modules").mkdir(parents=True)
        self.config = self.tmp / bridge.CONFIG_NAME
        self.config.write_text(json.dumps({"schema_version": 1, "repository_root": str(self.repo), "command_queue": ".agent\\commands"}), encoding="utf-8")
        self.trace = self.tmp / "bootstrap.log"
        self.old_trace = bridge.BOOTSTRAP_TRACE
        bridge.BOOTSTRAP_TRACE = self.trace

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        bridge.BOOTSTRAP_TRACE = self.old_trace

    def command(self, name="task.json", run_id="r1", module="resolve_workspace/modules/test_module.py", ok=True):
        report_dir = self.repo / "reports" / run_id
        payload = {"schema_version": 1, "task": "TEST", "run_id": run_id, "module": module,
                   "mode": "dry_run", "status_path": str(report_dir / "status.json"),
                   "log_path": str(report_dir / "run.log"), "report_path": str(report_dir / "report.json")}
        path = self.queue / "pending" / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def module(self, ok=True):
        (self.repo / "resolve_workspace" / "modules" / "test_module.py").write_text(
            f"def run(resolve, context): return {{'ok': {ok!r}, 'run_id': context['run_id'], 'test': 'TEST', 'timeline_modified': False}}\n", encoding="utf-8")

    def test_config_discovery(self):
        self.assertEqual(bridge.load_config(self.config)["repository_root"], self.repo)

    def test_missing_config(self):
        with self.assertRaises(bridge.BridgeError): bridge.load_config(self.tmp / "missing.json")

    def test_invalid_repository_root(self):
        self.config.write_text(json.dumps({"schema_version": 1, "repository_root": str(self.tmp / "nope"), "command_queue": ".agent\\commands"}), encoding="utf-8")
        with self.assertRaises(bridge.BridgeError): bridge.load_config(self.config)

    def test_oldest_selection_and_claim(self):
        old = self.command("old.json", "old"); new = self.command("new.json", "new")
        os.utime(old, (10, 10)); os.utime(new, (20, 20))
        claimed = bridge.claim_oldest(self.queue)
        self.assertEqual(claimed[0].name, "old.json")
        self.assertTrue((self.queue / "running" / "old.json").exists())

    def test_success_completed_transition(self):
        self.module(True); self.command(); self.assertEqual(bridge.process_one(self.config, resolve=object()), 0)
        self.assertTrue((self.queue / "completed" / "task.json").exists())

    def test_failure_failed_transition(self):
        self.module(False); self.command(); self.assertEqual(bridge.process_one(self.config, resolve=object()), 1)
        self.assertTrue((self.queue / "failed" / "task.json").exists())

    def test_duplicate_run_id_rejection(self):
        self.command("pending.json", "same"); (self.queue / "running" / "active.json").write_text(json.dumps({"run_id": "same"}), encoding="utf-8")
        with self.assertRaises(bridge.BridgeError): bridge.claim_oldest(self.queue)
        self.assertTrue((self.queue / "failed" / "pending.json").exists())

    def test_no_command_available(self):
        self.assertEqual(bridge.process_one(self.config, resolve=object()), 0)

    def test_bootstrap_trace_precedes_config_loading(self):
        self.assertEqual(bridge.workspace_entrypoint(self.tmp / "missing.json"), 1)
        text = self.trace.read_text(encoding="utf-8")
        self.assertIn("event=entry_point_started", text)
        self.assertIn("entry-point-started=true", text)
        self.assertIn("event=entry_point_exception", text)
        self.assertIn("Traceback", text)

    def test_invalid_config_trace_contains_traceback(self):
        self.config.write_text("not-json", encoding="utf-8")
        self.assertEqual(bridge.workspace_entrypoint(self.config), 1)
        self.assertIn("Traceback", self.trace.read_text(encoding="utf-8"))

    def test_imported_bridge_does_not_consume_commands(self):
        self.module(True)
        ns = {"__name__": "resolve_workspace_invocation", "__file__": str(self.tmp / "VC_Agent_Bridge.py"), "resolve": object(), "fusion": object()}
        shutil.copy2(Path(bridge.__file__), self.tmp / "VC_Agent_Bridge.py")
        (self.tmp / bridge.CONFIG_NAME).write_text(self.config.read_text(encoding="utf-8"), encoding="utf-8")
        exec(compile((self.tmp / "VC_Agent_Bridge.py").read_text(encoding="utf-8"), str(self.tmp / "VC_Agent_Bridge.py"), "exec"), ns)
        self.assertTrue((self.queue / "pending").exists())
        self.assertTrue((self.queue / "pending").exists())

    def test_cli_import_does_not_process_queue(self):
        self.module(True); path = self.command("untouched.json", "untouched")
        import importlib.util
        spec = importlib.util.spec_from_file_location("bridge_import_only", bridge.__file__)
        loaded = importlib.util.module_from_spec(spec); assert spec.loader is not None; spec.loader.exec_module(loaded)
        self.assertTrue(path.exists())

    def test_module_path_traversal_rejected(self):
        with self.assertRaises(bridge.BridgeError): bridge.safe_module_path(self.repo, {"module": "../escape.py"})

    def test_exact_smoke_run_id_preserved(self):
        expected = "20260801T094710993Z_2389202f723d42708dfabbac38221f25"
        path = self.command("smoke.json", expected)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["run_id"], expected)


if __name__ == "__main__": unittest.main()
