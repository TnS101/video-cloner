# Local Video Cloner agent queue

This is a local, file-backed queue for infrastructure tasks. It deliberately has
no caption implementation or caption-specific task type.

Queue directories:

- `task_queue/pending` — tasks waiting to run
- `task_queue/running` — atomically claimed tasks
- `task_queue/completed` and `task_queue/failed` — terminal task records
- `task_queue/reports` — working reports
- `data/agent_reports/archive` — immutable report archive

Examples:

```bat
run_agent_task.bat enqueue --kind noop --name infrastructure_smoke
run_agent_task.bat run-once
run_agent_task.bat status
```

`resolve_ui` tasks are dry-run unless `--allow-resolve-ui` is supplied to the
worker. This keeps infrastructure tests from changing a Resolve project.
