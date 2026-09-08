# Video Cloner repository guidance

- Do not launch DaVinci Resolve or mutate Resolve projects or timelines from automated tests.
- Treat `.agent/commands/{pending,running,completed,failed}` as ignored local Resolve runtime state; never commit it.
- Standalone Migration phase labels in `docs/migration` are distinct from Reel pipeline phase labels in retained historical filenames.
