# AGENTS.md — Video Cloner Codex Worker Contract

## Role

You are the implementation/execution worker for the CURRENT approved `plan.md` only. The Browser Architect owns product strategy, architecture, sequencing, acceptance, and the next Plan.

## Mandatory session start

Before product edits or live execution:

1. Read this `AGENTS.md` completely.
2. Read `plan.md` completely.
3. Read `ARCHITECTURE.md` and `PROJECT_STATE.md`.
4. Read any project-specific files explicitly required by the Plan.
5. If applicable global skills are discoverable, read them and record their names. Their absence is non-blocking unless `plan.md` says `REQUIRED`.
6. Run and record:
   - `git status --short`
   - `git branch --show-current`
   - `git rev-parse HEAD`
7. Confirm Plan ID, scope, accepted product baseline, acceptance criteria, repair limit, human gates, and stop conditions.

If the Plan is missing/stale/non-executable or Git state is unsafe: STOP — BLOCKED.

## Plan gate

Implement/execute only when `plan.md` status is `READY_FOR_CODEX` or `ACTIVE_CODEX`.

One Plan ID belongs to this Codex session. Do not continue into another Plan.

## Git gate

- Do not work from an unexplained dirty tree.
- Do not force push, rewrite history, or discard changes you did not create.
- Keep changes bounded to Plan scope.
- Do not commit secrets or machine-local state.
- Do not recreate deleted historical Step/Phase scripts because old reports mention them.

## Video Cloner protected boundaries

Preserve unless the current Plan explicitly authorizes otherwise:

- `video_cloner.pipeline` public orchestration API;
- `video-cloner run` normal operator path;
- bounded queue publication;
- run ID / manifest / artifact provenance contracts;
- `.agent/commands/{pending,running,completed,failed}` as ignored local Resolve runtime state;
- installed/frozen Resolve launcher/bridge contract;
- protected Reel #2 GOLD identity and accepted artifacts;
- `docs/repo_hygiene/DEFERRED_CAPABILITIES_INDEX.md` retention policy.

Automated tests must NOT launch Resolve or mutate real Resolve projects/timelines.

## `.agent` / `.project_ops` boundary

`.agent` is ONLY the Resolve runtime/queue namespace.

Worker project-management output goes to:

`.project_ops/reports/<PLAN_ID>/<TASK_ID>/REPORT.md`

Temporary/heavy task artifacts go to:

`.project_ops/artifacts/<PLAN_ID>/<TASK_ID>/`

Use `.project_ops/templates/REPORT_TEMPLATE.md`.

## Task law

Default:

**one task = one observable result = one verification boundary**

Do not silently add adjacent fixes, cleanup, dependency upgrades, refactors, or future-proofing.

Prefer:

`inspect → smallest allowed action/change → focused verification → affected regression → evidence → REPORT.md → STOP / HUMAN GATE`

Do not weaken validators/tests to manufacture PASS. Do not swallow a real failure.

## Research/dependency rule

Do not add/change a material dependency unless the Plan explicitly authorizes the reuse/build decision. Prefer existing repository mechanisms first.

## Human intervention

Stop and report `HUMAN_INTERVENTION: YES` when the Plan reaches:

- Resolve Workspace/UI execution;
- credentials/permissions;
- destructive external action;
- subjective/visual acceptance;
- material architecture or dependency choice.

State exactly WHAT the human must do, WHY, and WHAT evidence/result must be returned.

Never claim human visual approval yourself.

## Report contract

After each bounded task write the required report using the template. Include:

- Plan ID / Task ID;
- session label;
- applicable external skills status;
- baseline branch/commit + initial Git status;
- exact objective;
- concise approach;
- files changed and why;
- commands/tests run;
- exact evidence/artifacts;
- acceptance criteria table;
- PASS / FAIL / BLOCKED;
- deviations/remaining risks;
- human intervention YES/NO;
- final Git status.

Do NOT recommend the next project Plan. The Browser Architect chooses it.

## Stop conditions

Stop immediately when:

- current Plan is not executable;
- Git state is unsafe/ambiguous;
- architecture must change;
- scope expansion is required;
- a new unauthorized dependency is required;
- human action is required;
- the allowed repair limit is exceeded;
- evidence contradicts success;
- visual/subjective approval is required;
- rollback cannot be proven.
