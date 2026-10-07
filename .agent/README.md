# Resolve execution queue

This repository owns a local, file-backed boundary for explicit DaVinci Resolve
commands. It is not the universal coding-agent workflow or a general task queue.

The queue root is `.agent/commands` with four states:

- `pending` contains complete command JSON files waiting for Resolve.
- `running` contains the one command atomically claimed by the bridge.
- `completed` and `failed` preserve terminal command records.

The Resolve Workspace launcher loads `resolve_workspace/VC_Agent_Bridge.py` and
processes at most one pending file per invocation, ordered by filename. A command
must provide a unique non-empty `run_id`, a repository-relative Python `module`,
and repository-contained `status_path`, `log_path`, and `report_path`. The module
must expose `run(resolve, context)` and return a JSON object. Duplicate filenames
or run IDs fail closed; terminal evidence is never overwritten.

The installer creates the four state directories and installs the launcher plus
an adjacent repository-location config. Queue files, bridge logs, installer
state, and command outputs under `.agent` are machine-local and ignored by Git.
Tests use temporary repositories and injected Resolve objects; they do not start
Resolve or mutate a project or timeline.
