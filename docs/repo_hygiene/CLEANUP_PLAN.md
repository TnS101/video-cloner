# Cleanup Plan

No cleanup is authorized by this audit. The current tree is not safe for deletion because canonical fresh-run files are untracked and Resolve completion is unproven.

## Ordered execution

1. **Baseline and provenance.** Reconcile the branch (`ahead 1, behind 2`), review all 190 dirty paths, commit the intended source/tests/docs in coherent commits, and create a baseline tag. Do not sweep ignored `.agent` evidence into Git; select durable reports/manifests explicitly.
2. **Close the Resolve truth gap.** Reproduce the `target_title`/`import_returned_identity` failures with one read-only preflight or controlled disposable timeline. Define whether a created-but-unvalidated timeline is rollback, retry, or accepted state. No module deletion before this.
3. **Freeze contracts.** Record one manifest containing source, analyzer, planning, profile, compiler, queue, bridge, and Resolve-module hashes for `DZatr0EJt4B`. Rebuild the stale style profile so its input hashes match the current artifacts.
4. **Create the canonical package.** Move logic capability-by-capability into the target modules. Reuse existing functions; do not rewrite algorithms. Add one `video-cloner` CLI with subcommands for ingest, analyze, plan, profile, compile, queue, and run-offline.
5. **Migrate callers.** Point the root BAT and current tests to the CLI/package. Make the pipeline command perform the proven sequence and produce a single run manifest. Keep old command names as thin compatibility wrappers only where a real caller remains.
6. **Consolidate Resolve.** Retain `VC_Run_Agent_Task.py` and `VC_Agent_Bridge.py`; migrate Phase 6 behavior into one generic timeline-import module. Inventory every pending/running/completed/failed command module string before changing or removing any module.
7. **Focused regression.** Run pure package tests, bridge dispatch tests, compiler contract tests, then the affected legacy regression once. Make missing Reel-1 fixtures self-contained or explicitly external; do not accept an erroring suite.
8. **Fresh-Reel end-to-end.** Re-run `DZatr0EJt4B` from URL through offline compilation. Verify artifact hashes, then run a controlled Resolve first application, persistent readback, second application/idempotency, and human visual review where required.
9. **Retire wrappers.** Remove only wrappers with zero callers in source, tests, BAT/PS1, command JSON, accepted reports/manifests, and installed Resolve Scripts/Edit inventory.
10. **Delete stale source after proof.** Preserve source history in the pre-hygiene Git snapshot/tag. Extract only durable regression tests, fixtures, forensic reports, concise documentation, and accepted manifests/hashes; then delete stale runtime implementations after caller and parity gates pass. Do not create a permanent old-code archive directory.
11. **Ignore generated noise.** Add `.pytest-tmp-*`, benchmark scratch, `_browser_evidence_*`, local usage dumps, queue runtime state, and caches to `.gitignore` only after deciding which evidence must be promoted to durable fixtures/reports.
12. **Final proof and tag.** Run the canonical focused regression and one end-to-end fixture, inspect `git status`, verify no generated/media artifacts are tracked, commit, and tag the cleaned baseline.

## Deletion gates

A file is removable only when all are true:

- no static import/call/subprocess/BAT/PowerShell reference;
- no dynamic module string in active or accepted queue/manifests;
- no installed Resolve launcher reference;
- replacement passes equivalent focused tests;
- `DZatr0EJt4B` end-to-end and Resolve idempotency pass;
- useful bug evidence remains readable without importing the file.

## First safe deletion batch after migration

The likely first batch is seven files: five `scripts/analysis/repair_*.py` scripts and two files under `scripts/davinci/archive(for studio)/`. This is a candidate count, not present authorization. The two metadata-controller copies should follow only after installed-script and command-history checks prove zero use.
