"""Publish the final six-caption OSS-002C recovered-motion delta."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
base_spec = importlib.util.spec_from_file_location("vc_oss002c_base_publisher", Path(__file__).with_name("prepare_oss002c_recovered_caption_batch.py"))
if base_spec is None or base_spec.loader is None:
    raise ImportError("cannot_load_oss002c_base_publisher")
base = importlib.util.module_from_spec(base_spec)
base_spec.loader.exec_module(base)

MODULE_RELATIVE = "resolve_workspace/modules/oss002c_full_recovered_motion_rollout.py"
FCPXML = base.FCPXML
RECIPES = base.RECIPES
RECOVERY = base.RECOVERY
spec = importlib.util.spec_from_file_location("vc_oss002c_full_rollout", ROOT / MODULE_RELATIVE)
if spec is None or spec.loader is None:
    raise ImportError(f"cannot_load:{MODULE_RELATIVE}")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def publish(root: Path = ROOT) -> dict[str, str]:
    return base.publish_delta(batch, MODULE_RELATIVE, root)


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
