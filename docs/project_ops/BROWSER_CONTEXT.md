# Browser Context — GitHub-First

## Normal mode

A fresh Browser Architect chat should receive the GitHub repository URL and read from `main`:

1. `ARCHITECT_RULES.md`
2. `PROJECT_STATE.md`
3. `ARCHITECTURE.md`
4. `PROJECT_TRACKER.xlsx`
5. `plan.md`

This avoids repeatedly uploading ZIP snapshots now that clean GitHub authority exists.

## Attach only when needed

- current Codex `REPORT.md` when reviewing the current Plan;
- screenshots / local logs / ignored runtime artifacts that GitHub cannot contain;
- `docs/RESEARCH_BASELINE.md` when a new mechanism/dependency is being chosen;
- decision/test docs when materially relevant.

## ZIP fallback

Use `scripts/project_ops/make_browser_context.ps1` only when GitHub access is unavailable or a local-only context handoff is required.

Never treat stale ChatGPT Project knowledge as stronger than GitHub current state.
