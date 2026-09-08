# Standalone Migration Sequence

1. Phase 1 — ACCEPTED: RunContext, URL/local ingest, WAV, proxy, configuration, and explicit media DAG.
2. Phase 2 — ACCEPTED: deterministic orchestration of seven canonical analyzers with prerequisite validation, hash-based reuse, selected/all force, failure isolation, and a sanitized run manifest.
3. Phase 3 — SOURCE_PRESENT_NOT_ACCEPTED: deterministic analysis collection and planner runner; not executed by Phase 2 acceptance and requires its own gate.
4. Phase 4 — SOURCE_PRESENT_NOT_ACCEPTED: generic edit validation and compiler orchestration; do not execute until prior gates are accepted.
5. Phase 5 — PARTIAL_SOURCE_PRESENT_NOT_ACCEPTED: cut-only FCPXML compilation source exists, but full DaVinci artifact compilation is not accepted.
6. Phase 6 — permanent bridge application with immutable command/evidence protocol.
7. Phase 7 — end-to-end parity on a non-Reel #1 fixture, then protected Reel #1 regression.
8. Phase 8 — only after parity, classify proven superseded scripts as archive candidates.

Each phase is a separate verification boundary. No destructive cleanup precedes parity.

These Standalone Migration phases are unrelated to Reel pipeline phase numbers embedded in retained historical filenames.
