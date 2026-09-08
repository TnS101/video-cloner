from __future__ import annotations

import importlib.util
import json
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

    def test_selector_never_escapes_discovered_directories(self):
        discovered = self.tmp / "portable" / "Scripts" / "Edit"
        discovered.mkdir(parents=True)
        (discovered / installer.ANCHOR).write_text("")
        (discovered / "resolve_apply_video_cloner_metadata.py").write_text("")
        self.assertEqual(installer.select_canonical([discovered]), discovered)

    def test_removes_stale_bridge_pyc(self):
        directory = self.tmp / "Scripts" / "Edit" / "__pycache__"; directory.mkdir(parents=True)
        stale = directory / "VC_Agent_Bridge.cpython-311.pyc"; stale.write_bytes(b"x")
        self.assertEqual(installer.remove_bridge_files(directory.parent), [str(stale)])
        self.assertFalse(stale.exists())

    def test_aborts_when_resolve_running(self):
        repo = self.tmp / "repo"; (repo / "resolve_workspace").mkdir(parents=True); (repo / "resolve_workspace" / installer.LAUNCHER).write_text("")
        with patch.object(installer, "running_processes", return_value=["Resolve.exe"]):
            self.assertEqual(installer.install(repo), 1)

    def test_install_is_idempotent_and_writes_repository_config(self):
        repo = self.tmp / "repo"
        source_dir = repo / "resolve_workspace"; source_dir.mkdir(parents=True)
        (source_dir / installer.LAUNCHER).write_text("# launcher\n", encoding="utf-8")
        canonical = self.tmp / "Scripts" / "Edit"; canonical.mkdir(parents=True)
        (canonical / installer.ANCHOR).write_text("# anchor\n", encoding="utf-8")
        (canonical / "resolve_apply_video_cloner_metadata.py").write_text("# marker\n", encoding="utf-8")
        unrelated = canonical / "unrelated.py"; unrelated.write_text("# preserve\n", encoding="utf-8")
        with patch.object(installer, "running_processes", return_value=[]), patch.object(installer, "discover_script_dirs", return_value=[canonical]):
            self.assertEqual(installer.install(repo), 0)
            first_launcher_hash = installer.sha256(canonical / installer.LAUNCHER)
            first_config = json.loads((canonical / installer.CONFIG).read_text(encoding="utf-8"))
            self.assertEqual(installer.install(repo), 0)
        self.assertEqual(installer.sha256(canonical / installer.LAUNCHER), first_launcher_hash)
        self.assertEqual(json.loads((canonical / installer.CONFIG).read_text(encoding="utf-8")), first_config)
        self.assertEqual(first_config["repository_root"], str(repo))
        self.assertEqual(first_config["command_queue"], ".agent\\commands")
        self.assertTrue(unrelated.exists())
        self.assertTrue(all((repo / ".agent" / "commands" / state).is_dir() for state in installer.QUEUE_DIRS))

    def test_recovers_legacy_command_once_without_changing_identity(self):
        repo = self.tmp / "repo"; queue = repo / ".agent" / "commands"; queue.mkdir(parents=True)
        filename = "BRIDGE_SMOKE_TEST_V1_existing.json"; run_id = "existing-run"
        legacy = queue / filename
        legacy.write_text(json.dumps({"task": "BRIDGE_SMOKE_TEST_V1", "run_id": run_id}), encoding="utf-8")
        original_hash = installer.sha256(legacy)
        first = installer.recover_existing_command(repo, filename, run_id)
        second = installer.recover_existing_command(repo, filename, run_id)
        self.assertEqual(first["result"], "recovered")
        self.assertEqual(second["result"], "already_pending")
        self.assertEqual(first["sha256"], original_hash)
        pending = queue / "pending" / filename
        self.assertEqual(json.loads(pending.read_text(encoding="utf-8"))["run_id"], run_id)
        self.assertEqual(len(list(queue.rglob(filename))), 1)

    def test_recovery_preserves_completed_command(self):
        repo = self.tmp / "repo"; completed = repo / ".agent" / "commands" / "completed"; completed.mkdir(parents=True)
        filename = "existing.json"; run_id = "completed-run"
        command = completed / filename; command.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
        result = installer.recover_existing_command(repo, filename, run_id)
        self.assertEqual(result["result"], "already_completed")
        self.assertTrue(command.exists())
        self.assertFalse((repo / ".agent" / "commands" / "pending" / filename).exists())

    def test_recovery_rejects_conflicting_copies(self):
        repo = self.tmp / "repo"; queue = repo / ".agent" / "commands"
        for state in ("pending", "completed"):
            (queue / state).mkdir(parents=True, exist_ok=True)
            (queue / state / "same.json").write_text(json.dumps({"run_id": "same"}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            installer.recover_existing_command(repo, "same.json", "same")
