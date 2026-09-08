#!/usr/bin/env python3
"""Build the offline Step 3B.3 V2 precedence-aware authority closure report."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

MODULE_RELATIVE = "resolve_workspace/modules/step_3B3_outline_shadow_authority_v2.py"
DEFAULT_OUTPUT = "artifacts/DZSQH7AUHJT_STEP_3B3_OUTLINE_SHADOW_AUTHORITY_RECONCILIATION_V2/effective_authority_validation.json"


def _load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("vc_step3b3_authority_v2_builder", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        module = _load(root / MODULE_RELATIVE)
        report = module.build_report(root)
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({
        "ok": True,
        "task_id": report["task_id"],
        "step_3B3_status": report["decision"]["step_3B3_status"],
        "effective_mismatch_count": report["effective_authority"]["mismatch_count"],
        "timeline_mutation_required": report["decision"]["timeline_mutation_required"],
        "resolve_invocations_required": report["decision"]["resolve_invocations_required"],
        "output": str(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
