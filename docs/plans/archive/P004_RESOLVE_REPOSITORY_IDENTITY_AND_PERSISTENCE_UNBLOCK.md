# P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK — ARCHIVED

- FINAL STATUS: `SUPERSEDED / PRE-SHIP DEFERRED`
- SUPERSEDED: 2026-10-09 Europe/Sofia
- REASON: end-of-week shipping speedrun. Caption production is now the critical path; repository/persistence ceremony is deferred to PRE-SHIP.
- T001: `PASS / ACCEPTED — OFFLINE` at `da1d62833f1ec32ba40396a267640aa239ba7046`.
- T002: `BLOCKED BEFORE PUBLICATION`; zero P004 command publication, zero queue processing, zero Resolve invocation, zero SaveProject.
- RETAINED DEBT: save/reopen persistence + repository identity live proof remain mandatory before ship, but do not block PH2 caption work.

---

# P004 — Repository Identity and Persistence Unblock

- PLAN ID: `P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK`
- STATUS: **READY_FOR_CODEX**
- CREATED: 2026-10-09 Europe/Sofia
- PHASE: PH1 persistence checkpoint (PH2 production unblock only)
- ARCHITECT BASELINE: `main@a102a94b34431bcc609ed5cfc4e048cfc6b3fa0a`
- ARCHITECT DRAFT BRANCH: `architect/p004-persistence-unblock-draft`
- PREDECESSOR: `P003_FALLBACK_PERSISTENCE_ACCEPTANCE` — BLOCKED / CLOSED. No P003 retry.
- WORKER GATE: **OPEN FOR T002 ONLY — PREPARATION/PUBLICATION**. T001 is accepted at `da1d62833f1ec32ba40396a267640aa239ba7046`. Codex may prepare and publish exactly one fresh pending finalizer command, then STOP. Queue processing, Resolve invocation, `SaveProject`, T003/T004 and PH2 implementation are explicitly prohibited.

## One observable Win Condition

**`P004_PERSISTENCE_UNBLOCKED`** iff the existing Reel #3 target is saved **exactly once** through a newly attributable, evidence-bound finalizer path and survives **one** human Resolve close/reopen plus existing read-only verifier cycle unchanged. Otherwise precise `BLOCKED_*` and STOP. P004 is NOT full PH1/product/visual/idempotency acceptance.

## Accepted facts / bottleneck

- P002: `DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID`, 112/112 captions structurally mapped, direct title text null, title media paths empty, fallback eligible. Do not reopen `target_title` or caption diagnosis.
- P003 T001 offline: accepted (26 focused, 83 affected regression). T002 published one exact command. T003 failed before live-state read/save: `FileNotFoundError [WinError 2]` from bare `git` inside Resolve Python; `saves=0`, all mutation counters zero; P003 is terminal and will not be retried.
- Both `resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py` and `resolve_workspace/modules/video_cloner_p003_post_reopen_verification.py` use `subprocess.run(["git", ...])`. The existing installed launcher/bridge binds repository root but does not replace HEAD/branch verification.
- Target in `New Project 1`: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`, UID `4aaa91c0-c434-4439-a15a-92ce86e80256`; 46 timelines (45 protected), 55 media items, 8 video/1 audio clips, 112 overlays, 673 frames. Exact current timeline and protected/media signatures must match accepted P002 evidence before save.
- Protected Reel #2 GOLD: `DcJRJtUKScu_offline_timeline_v1`, UID `4ad2a3c3-031c-464d-96aa-76a045608ad6`, DRT SHA-256 `99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e`.
- Resolve is open; keep current project/target untouched until an explicitly authorized human gate.

## Repository-identity mechanism: choose Route A (REUSE / ADAPT)

| Route | Outcome | Decision |
|---|---|---|
| A. Command-bound absolute Git executable | Preparation locates canonical `git.exe`, validates that it can query the **actual target repo**, records path + SHA-256; Resolve authenticates path/hash before invoking it; old branch/HEAD checks retained | **WIN — smallest bounded repair to existing code** |
| B. Existing runtime identity | Launcher/bridge provides resolved repository root and safe module path, but not equivalent trusted HEAD/branch verification | REJECT as insufficient alone |
| C. Parse Git state without execution | Would require handling worktrees, gitfiles, packed refs, symbolic refs and detached HEAD correctly; no confirmed reusable equivalent | REJECT: more code/risk |

Research stop: A/B/C inspected; no external dependency/OSS scan. No architecture tree, no new general identity framework. One dedicated local helper **only if** it removes duplication across finalizer/verifier; otherwise minimal in-place changes.

### Exact safety contract for Route A

Preparation (outside Resolve) resolves the absolute actual Git executable (not a PATH string), checks a regular executable file, obtains its SHA-256, executes the expected `branch --show-current` and `rev-parse HEAD` against the exact repository root, and binds both path/hash and expected repo HEAD into the new queue command. Resolve must resolve/canonicalize that command-bound path, verify exact SHA-256 and file, disallow bare `"git"` and ambient PATH lookup, then invoke only that executable with explicit `cwd=root` and existing branch/HEAD comparisons. Fail closed before live validation/save on missing, invalid, swapped executable, missing or unexpected branch/HEAD, mismatched root, executable error or command contract mismatch. Re-verify command-bound executable identity for the later read-only verifier command. Avoid permanent machine-specific constants and do not trust an unvalidated path/hash merely because the payload supplies it.

## Scope and complexity budget

IN: one bounded Git discovery/identity repair to **both** identity callers; command preparation binding; minimal focused tests; unchanged accepted P003 fallback/save semantics; one fresh finalizer command/live save attempt; one read-only reopen verifier command/cycle; P004 task reports/evidence.

OUT: PH2 implementation, caption/font/animation code, `target_title` reopening, strict-validator weakening, same-target replay, idempotency acceptance, full human visual acceptance, PH1 ship certification, dataset work, broad research, dependencies, queue redesign, unrelated hardening, architecture expansion, new launcher/bridge changes.

HARD CAP: **one mechanism decision; one implementation patch; one focused offline test batch plus affected regression; one newly attributable save attempt; one close/reopen verifier cycle.** No P004A/B/C, extra diagnostic Plans, auto retries, or broad acceptance ceremony. Any evidence of destructive mutation is an immediate stop.

## Tasks — strict serial gates

### T001 — Offline repository identity repair
- STATUS: **PASS / ACCEPTED — OFFLINE** — commit `da1d62833f1ec32ba40396a267640aa239ba7046`
- Allowed implementation: `resolve_workspace/modules/video_cloner_phase6_offline_timeline_live_application.py`, `resolve_workspace/modules/video_cloner_p003_post_reopen_verification.py`, minimum corresponding `tests/test_video_cloner_p003_fallback_persistence_acceptance.py` (and at most one tiny reused helper if strictly required). Command-preparation changes only if an existing prep utility is demonstrably the correct owner; otherwise bind via T002 bounded preparation procedure.
- Scope: replace bare Git calls in both modules with authenticated command-bound `git.exe`; keep repository-root/HEAD/branch validation unchanged. Preserve P003 fixed evidence/hash/fallback, `SaveProject` guard, verifier read-only surface, protected/current/media comparison.
- Tests: correct signed command-bound executable; missing/path-only/hash mismatch/swapped binary/bad exit/non-main/wrong HEAD/wrong root rejected **before SaveProject**; finalizer save once only on accepted baseline; verifier zero mutation and identity proof. Mock Git process: offline tests must never launch Resolve or save real project.
- Verify: targeted P003 test + affected P002/Phase6/bridge/prep regression; `git diff --check`; verify only allowed files changed and no launcher/bridge/public API import contract drift.
- Required report: `.project_ops/reports/P004_RESOLVE_REPOSITORY_IDENTITY_AND_PERSISTENCE_UNBLOCK/T001/REPORT.md`.
- **STOP** for Architect review. No command publication or live action.

### T002 — Prepare one fresh attributable command
- STATUS: **AUTHORIZED — PREPARATION/PUBLICATION ONLY**
- Only after separate T001 approval. Require clean/explained tree, exact committed repair SHA, executable absolute path/hash authenticated from preparation environment, fresh command/run ID (never P003 run `20261008T120754374Z_11c3411415444aa2a83b816bf7bacb88`), accepted P001/P002 identities/hashes, frozen runtime identities, and empty pending/running queue.
- Bind exact command-root, expected repository HEAD and authenticated Git path/hash; bind updated finalizer module SHA and expected project/target/UID/evidence. Only `save_once` and `save_project` true; all other mutation flags false; `retry_permitted=false`.
- Publish **exactly one** pending finalizer command. No Resolve invocation. Report `.../T002/REPORT.md`.
- **STOP** before human action.

### T003 — One live finalizer invocation
- STATUS: **NOT_STARTED / NOT_AUTHORIZED**
- Only after T002 review/explicit human gate: human executes `Resolve → Workspace → Scripts → VC_Run_Agent_Task` **once**.
- Finalizer authenticates executable, repository HEAD/branch and exact command, project/target UID, P001/P002 evidence, 112 caption structures, full P002 live target/current/protected/media baseline, and only then calls `SaveProject` exactly once. Verify immediate post-save state; all other mutation counters zero.
- Report `.../T003/REPORT.md`, including command/run/status/report/log SHA-256 and pre/post signatures. **NO RETRY**. If PASS, proceed to T004; otherwise terminal STOP.

### T004 — One close/reopen persistence cycle
- STATUS: **NOT_STARTED / NOT_AUTHORIZED**
- Only after T003 PASS: prepare one new attributable **read-only** verifier command using the existing post-reopen verifier and the same authenticated executable identity contract, with all mutation permissions false. Require pending/running queue empty before one publication.
- Human closes Resolve once **without extra manual save**, reopens Resolve/project and runs `VC_Run_Agent_Task` exactly once for the read-only verifier. If save/discard prompt appears, cancel and report; do not silently choose Save/Discard.
- Require saved target name/UID, signature, 8+1 clips, 112 overlays/geometry, 673 frames, empty title media paths, 46 timeline/45 protected signatures including Reel #2 GOLD, 55 media items and expected artifact/provenance identities unchanged; read-only mutation counters zero. Current timeline selection difference after reopen must be recorded separately, never hide content drift.
- Report `.../T004/REPORT.md`; PASS → `P004_PERSISTENCE_UNBLOCKED`. Exact mismatches → precise BLOCKED / STOP. No second verifier or persistence cycle.

## Kill criteria / fallback (non-negotiable)

1. Any baseline semantic contradiction, target/UID mismatch, structural corruption, protected/current/media inventory mutation, missing target, unexpected SaveProject behavior or reopen persistence drift → **BLOCKED_PRODUCT_CORRECTNESS**, stop PH2 and preserve all evidence/state. Never improvise repair.
2. On a second non-product environment/tooling failure **before SaveProject** during the **single new T003 live attempt** → terminal `BLOCKED_ENVIRONMENT`, no automatic P005 repair. Present human exactly: **A** controlled manual Resolve save plus close/reopen checkpoint (default recommendation when no product correctness risk), or **B** authorize one additional targeted automation repair. Manual checkpoint is production continuity only, never automated acceptance. Do not claim persistence proven without actual readback evidence.
3. Any ambiguous queue/run attribution, unexpected command count, git path/hash/HEAD failure, save/discard prompt, unauthorized mutation, needed second attempt or broader mechanism change → STOP. Preserve original P003 failed run and evidence; never reuse/retry it.
4. After first live invocation, **zero** P004 repair/retry. No automatic new Plan.

## Completion and next Plan

Success is `P004_PERSISTENCE_UNBLOCKED`, **not `PH1_ACCEPTED`**. Close/archive P004 and immediately begin **P005 / PH2_ADVANCED_TEXTPLUS_CAPTION_FIDELITY** (or conventionally equivalent) with actual caption production: REUSE Reel #2 human-cleaned GOLD `DcJRJtUKScu` and retained Step 3C/3D caption lifecycle → ADAPT → MEASURE → IMPROVE → HUMAN REVIEW. Focus font family/weight/size, stroke, opacity, positioning, multiline layout, entry/hold/exit lifecycle, scale/movement/easing/timing, archetype consistency.

PRE-SHIP deferred gates — REQUIRED before release, **not before PH2**: same-target second-run/idempotency, formal target-level human visual APPROVE/REJECT, remainder of PH1/full product certification. Do not insert another acceptance Plan between successful P004 and PH2.

Architect authorization gate: P004 is `READY_FOR_CODEX`; T001 is accepted and authorization is strictly limited to T002 preparation/publication. Codex may publish exactly one fresh pending finalizer command and must STOP after the T002 report for Browser Architect review. No queue processing, Resolve invocation, `SaveProject`, T003/T004, PH2 implementation, or live/project mutation is authorized.
