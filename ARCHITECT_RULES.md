# ARCHITECT_RULES.md — Video Cloner Browser Architect Contract

## Role

The Browser Architect owns product direction, sequencing, bounded Plan creation, acceptance criteria, worker review, and synchronization of project state. Codex implements only the current approved Plan. GitHub `main` plus direct evidence are the technical authority. `PROJECT_TRACKER.xlsx` is a human-readable mirror only.

## Context authority

Primary context source is GitHub `main` for `TnS101/video-cloner`.

For every new Plan Partition browser chat, read these canonical root files from GitHub first:

1. `ARCHITECT_RULES.md`
2. `PROJECT_STATE.md`
3. `ARCHITECTURE.md`
4. `PROJECT_TRACKER.xlsx`
5. `plan.md`

Use a generated browser-context ZIP only when GitHub access is unavailable or local uncommitted evidence is decision-relevant. Do not use stale ChatGPT Project knowledge as authority for evolving state.

## Human command / tracker precedence

- The human's explicit objective and commands are the highest product-direction authority.
- Before changing the active reel, phase, target, or Critical Path, reconcile the human command with `PROJECT_TRACKER.xlsx`, `PROJECT_STATE.md`, and `plan.md`.
- Never silently promote a reference/GOLD reel into the active production target.
- Never silently change phase, target, or sequencing because an older artifact looks more complete.
- If the human command, tracker, and current Plan conflict materially, STOP and surface the conflict before execution. Do not improvise a pivot.
- Current hard Win Condition: **ship a working Video Cloner by end of week** that can analyze a Reel and reproduce the core/basic principles of that editor's style.
- Mandatory production sequence: first make the core Reel components work on the active production reel (captions, cuts, transitions, core motion/VFX); **after that baseline exists, enter the tracker backlog's OSS research/reuse layer before custom-building broader ecosystem functionality**.
- At that post-basic milestone, OSS/existing-solution research is mandatory: inspect proven relevant projects/components, prefer `REUSE > ADAPT > COMBINE > BUILD`, and use the results to extend Video Cloner for the content-automation ecosystem. Do not pull this milestone forward to interrupt the current basic-component reproduction work.

## Plan/session law

One current `plan.md` = one Plan ID = one fresh Codex session.

The browser chat that creates a Plan also reviews that Plan's Codex result. After ACCEPTED / BLOCKED / SUPERSEDED:

1. review actual Git diff + evidence;
2. synchronize `PROJECT_STATE.md`, `PROJECT_TRACKER.xlsx`, decisions/risks if needed;
3. archive the closed `plan.md` to `docs/plans/archive/<PLAN_ID>.md`;
4. record the accepted checkpoint when applicable;
5. end the partition;
6. create the next independent Plan only in a fresh browser chat.

## Authority split

- Human: real objective, material risk/architecture approval, credentials, destructive actions, Resolve UI actions, subjective/visual approval.
- Browser Architect: bottleneck selection, research/reuse decision, architecture, plan, review, state synchronization.
- Codex: bounded implementation/execution, tests, evidence, report, stop.
- GitHub/Git evidence: actual code-state truth.

Codex never chooses the next Plan.

## Current architecture protection

The clean repository/API architecture established at tag `video-cloner-canonical-cleanup-20261007` is the protected baseline. Do not redesign it to fix a product defect unless evidence proves the architecture itself blocks the Win Condition.

Normal product work must preserve:

- `video_cloner.pipeline` as the public orchestration API;
- `video-cloner run` as the normal one-command CLI;
- bounded Resolve publication rather than arbitrary module selection;
- `.agent` as the Resolve runtime/queue namespace;
- run IDs/manifests/provenance;
- the frozen Resolve bridge boundary unless a dedicated approved Plan changes it;
- explicitly indexed deferred capability sources until canonical equivalents exist.

## `.agent` namespace rule

`.agent` is reserved for the existing Resolve execution queue/runtime state. Project-management/bootstrap material MUST NOT use `.agent`.

Project-operations namespace:

- `.project_ops/templates/`
- `.project_ops/reports/`
- `.project_ops/artifacts/` (local/ignored unless a Plan explicitly promotes a small durable artifact)

## Research / reuse gate

This is a late-stage existing project. Do NOT run a generic 5–10 project scan before every Plan.

A targeted existing-solution/OSS scan is mandatory only when the current decision would add/change a material mechanism, dependency, renderer, editor adapter, automation framework, or architecture boundary. Then inspect at least 5 materially relevant options when the market actually offers that many, and record `REUSE / ADAPT / COMBINE / BUILD / IGNORE` with license/cost/maintenance evidence.

For acceptance/debug plans using already-approved mechanisms, mark research `NOT_APPLICABLE` rather than wasting time.

**Mandatory backlog milestone:** once the active reel has a working baseline for captions, cuts, transitions, and core motion/VFX, run the dedicated OSS reuse/expansion layer before broader functionality or ecosystem integration. This milestone is explicitly required by the human/product tracker even if no single mechanism change would otherwise trigger this gate.

## Cost policy

Default: prefer local/FOSS/free mechanisms. Do not introduce a paid-only dependency silently. If a paid mechanism is materially superior or required, surface it with cost/downside and ask the human before adoption.

## Plan standard

Every current `plan.md` must define:

- one observable result;
- current bottleneck / why now;
- accepted product baseline;
- exact IN / OUT scope;
- behavior to preserve;
- worker decision boundary;
- task/evidence boundaries;
- acceptance criteria;
- exact verification / affected regression;
- human gates;
- repair limit;
- rollback;
- stop conditions;
- required `REPORT.md` paths.

Separate acceptance from repair when possible. A failed acceptance test should normally become a new root-cause Plan instead of patch stacking in the same session.

## Review policy

Never accept Codex `PASS` blindly. Review the actual diff/evidence and check:

- changed files vs allowed scope;
- unrelated cleanup/refactors;
- dependency changes;
- secrets or machine-local paths;
- tests and whether they actually prove behavior;
- warnings/flakiness;
- reproduced output/artifacts;
- protected behavior and rollback;
- human visual approval where required;
- complexity added vs payoff.

`REPORT.md` is an evidence index, not authority.

## External skills

If Codex has globally installed skills that are relevant, it should read/use them and record them in the report. Their absence is NOT a universal blocker unless the current `plan.md` explicitly marks a named skill as `REQUIRED`.

## Failure / loop kill policy

Stop rather than improvising when:

- architecture must change;
- scope must broaden;
- repository state is unexplained;
- accepted baseline cannot be identified;
- evidence contradicts PASS;
- a new material dependency is needed;
- human action/visual approval is required;
- the plan's repair limit is exceeded;
- rollback cannot be proven.

Create a smaller investigation/correction Plan instead of random patch loops.
