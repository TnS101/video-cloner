"""Read-only Resolve context probe used by BRIDGE_SMOKE_TEST_V1."""
from __future__ import annotations

from typing import Any, Dict

TEST_NAME = "BRIDGE_SMOKE_TEST_V1"


def _call(obj: Any, method: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, method, None)
        return value() if callable(value) else default
    except Exception:
        return default


def run(resolve: Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Inspect the supplied Resolve object without performing any writes."""
    context = context or {}
    project = _call(resolve, "GetProject") if resolve is not None else None
    timeline = _call(project, "GetCurrentTimeline") if project is not None else None
    result = {
        "ok": True,
        "test": TEST_NAME,
        "run_id": context.get("run_id"),
        "resolve_connected": resolve is not None,
        "project_name": _call(project, "GetName"),
        "timeline_name": _call(timeline, "GetName"),
        "current_page": _call(resolve, "GetCurrentPage"),
        "timeline_modified": False,
    }
    try:
        result["resolve_version"] = _call(resolve, "GetVersionString")
    except Exception:
        result["resolve_version"] = None
    return result


def main() -> int:
    # The Resolve bridge calls run(resolve, context). Direct execution is a
    # compilation/import smoke check and intentionally has no Resolve writes.
    import json
    print(json.dumps(run(None, {"run_id": "direct-import-smoke"}), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
