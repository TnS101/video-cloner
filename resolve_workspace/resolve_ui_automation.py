"""Small Resolve UI/API automation adapter; no media or caption mutations."""
from __future__ import annotations
import argparse, json, os, sys

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=("connect", "list-projects", "open-project", "save"), default="connect")
    p.add_argument("--project")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.dry_run:
        print(json.dumps({"ok": True, "mode": "dry_run", "action": args.action, "project": args.project}))
        return 0
    try:
        import DaVinciResolveScript as dvr
        resolve = dvr.scriptapp("Resolve")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"Resolve scripting API unavailable: {exc}"}))
        return 2
    if not resolve:
        print(json.dumps({"ok": False, "error": "Resolve scripting API returned no application"})); return 2
    pm = resolve.GetProjectManager()
    if args.action == "connect": result = {"connected": True}
    elif args.action == "list-projects": result = {"projects": pm.GetProjectList() or []}
    elif args.action == "open-project": result = {"opened": bool(args.project and pm.LoadProject(args.project)), "project": args.project}
    else: result = {"saved": bool(resolve.GetProject() and resolve.GetProject().Save())}
    print(json.dumps({"ok": True, "action": args.action, "result": result})); return 0

if __name__ == "__main__": raise SystemExit(main())
