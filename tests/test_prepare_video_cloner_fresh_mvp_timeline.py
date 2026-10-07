import json

import pytest

from video_cloner.resolve import queue as prepare


def test_publish_writes_one_safe_bridge_command(tmp_path, monkeypatch):
    manifest = tmp_path / "timeline_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(prepare, "allocate_run_id", lambda: "20261007T120000000Z_0123456789abcdef0123456789abcdef")

    receipt = prepare.publish(
        tmp_path,
        manifest,
        {
            "artifact_set_sha256": "artifact",
            "textplus_fingerprint": "textplus",
            "fcpxml_sha256": "fcpxml",
            "report_sha256": "report",
        },
        "Project",
        "Timeline",
    )

    command = json.loads((tmp_path / receipt["command_path"]).read_text(encoding="utf-8"))
    assert command["module"] == prepare.MODULE
    assert command["payload"] | {
        "import_permitted": True,
        "replace_existing_timeline": False,
        "save_project": False,
        "delete_permitted": False,
        "relink_permitted": False,
        "metadata_controller_permitted": False,
    } == command["payload"]
    with pytest.raises(ValueError, match="active_command"):
        prepare.publish(tmp_path, manifest, command["payload"], "Project", "Timeline")
