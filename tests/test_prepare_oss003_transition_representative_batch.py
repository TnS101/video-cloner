import json
import shutil
from pathlib import Path

from scripts.davinci import prepare_oss003_transition_representative_batch as prepare


def test_publishes_one_hash_locked_command(tmp_path: Path):
    source_root = Path(__file__).resolve().parents[1]
    for relative in (prepare.MODULE_RELATIVE, prepare.AUTHORITY_RELATIVE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, target)
    result = prepare.publish(tmp_path)
    pending = list((tmp_path / ".agent/commands/pending").glob("*.json"))
    command = json.loads(pending[0].read_text())
    assert len(pending) == 1
    assert result["run_id"] == command["run_id"]
    assert command["payload"]["expected_boundaries"] == [80, 286, 376]
    assert command["payload"]["save_after_verification"] is True
    assert (tmp_path / result["recipe_path"]).is_file()
