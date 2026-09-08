# Video Cloner Workspace Audit

Authority gate: PASS. Bundle SHA-256 `1eff7d4a59cb184cd1e7b7817d9f596f0ea2e00c0a3a4ebac63d3f3ebf60d4bb`; immutable workflow SHA-256 `d8d8a43f284d086823a71d384b696e76a3107e0169ae979b4b32832abc11655d`.

The immutable workflow has 33 nodes, 25 reachable nodes, eight unreachable nodes, zero sub-workflows, and 15 reachable repository script dependencies. All 15 dependencies exist in the inspected repository. Accepted report evidence establishes the post-n8n Flash V4, Occlusion V4, caption lifecycle, speed guard, zoom guard, and Reel #1 baselines. Missing historical `.agent/reports` paths are not runtime prerequisites.

The refreshed classification covers all 437 tracked files in the correction worktree based on migration head `17d29fec0923e0f3c9d9d9adba6c704e5a802332`:

- PRODUCT_RUNTIME: 127
- TEST: 208
- DURABLE_DOC_CONFIG: 10
- MIGRATION_EVIDENCE: 3
- HISTORICAL_RETAINED: 89
- GENERATED_LOCAL: 0
- TOTAL: 437

`PRODUCT_RUNTIME` includes the canonical workflow dependencies, standalone migration source, the Resolve bridge boundary, and retained runnable Reel implementations needed for parity. A runtime classification is not a permanent-architecture claim. `HISTORICAL_RETAINED` is proof, recovery, audit, rejected-candidate, or otherwise unaccepted source retained until parity; it is not active standalone architecture and is not authorized for deletion by this audit. `MIGRATION_EVIDENCE` is temporary review material removable only after migration acceptance.

The inventory records the PR #5 relationship for every tracked path: 332 added, 18 modified, and 87 unchanged from the local `main` tree. The resulting 350-file PR diff has a one-to-one classification match. Generated media, caches, logs, credentials, Resolve databases/projects/runtime state, and machine-local `.agent` state are excluded from Git and have zero tracked entries.

Standalone Migration phases describe repository migration gates. They are not the Reel pipeline phases embedded in retained filenames such as `video_cloner_phase4*` or `video_cloner_phase5*`. Source or tests present for a later Standalone Migration phase do not imply that phase was executed or accepted. No Resolve execution or live project/timeline mutation was used for this audit.

## PR #8 Reel fixture regression gate

PR #8 remains **BLOCKED** by these source-issue test failures:

- `tests/test_speed_ramp_planner_authority_v1.py::test_reel1_cli_pipeline_emits_16_nonactionable_candidates_and_zero_speed_ops`
- `tests/test_speed_ramp_planner_authority_v1.py::test_reel1_candidate_primary_actions_are_monotonic_source_preserving`
- `tests/test_zoom_planner_authority_v1.py::test_reel1_cli_pipeline_emits_15_nonactionable_zoom_candidates_and_zero_zoom_ops`

The affected-family run otherwise passed 125 tests and seven subtests. All three failures require ignored, untracked `data/DZsqH7auhjt/analysis/DZsqH7auhjt_analysis.json`, which is absent from both migration base `17d29fec0923e0f3c9d9d9adba6c704e5a802332` and this correction head. Product runtime and the Reel fixture expectations are unchanged by the correction. Advancing this gate requires a separately authorized product correction with accepted transition authority.
