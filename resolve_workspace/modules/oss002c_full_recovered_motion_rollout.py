"""Apply only the six missing canonical OSS-002C motion replacements."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any


MODULE_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("vc_oss002c_delta", MODULE_DIR / "oss002c_recovered_caption_batch.py")
if spec is None or spec.loader is None:
    raise ImportError("cannot_load_oss002c_delta")
delta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delta)

TASK_ID = "OSS002C_FULL_RECOVERED_MOTION_ROLLOUT_V1"
MODE = "oss002c_full_recovered_motion_rollout"
TARGET_ORDINALS = (53, 78, 79, 87, 88, 108)
EXPECTED_EXISTING_NESTED = 63
REPRESENTATIVE_SOURCE_NAMES = {
    ordinal: f"_VC_OSS002C_SUB{ordinal:03d}_9505c20c898e"
    for ordinal in (5, 37, 54, 75, 80, 101, 107)
}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    return delta.run_delta(
        resolve,
        context,
        task_id=TASK_ID,
        mode=MODE,
        target_ordinals=TARGET_ORDINALS,
        expected_existing_nested=EXPECTED_EXISTING_NESTED,
        accepted_source_names=REPRESENTATIVE_SOURCE_NAMES,
        require_all_meaningful=True,
    )


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
