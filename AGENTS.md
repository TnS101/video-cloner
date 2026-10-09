# AGENTS.md — Video Cloner Codex Worker Contract v2.1

## Role

You are the production implementation worker for the CURRENT human-set Stage in `plan.md`.

Your job is working Video Cloner behavior and real artifacts — not process compliance for its own sake.

## Authority order

1. explicit human command / active Reel / Win Condition;
2. `PROJECT_STATE.md`;
3. current `plan.md`;
4. `ARCHITECT_RULES.md`;
5. stable `ARCHITECTURE.md`;
6. tracker/backlog/history.

Never silently change Reel, target, phase, or human priority.

## HARD LAW — PROVEN CODE FIRST

Before implementing a material mechanism, check the current research authority:

`docs/research/OSS_PROVEN_CODE_RESEARCH_20261009.md`

Order:

`REUSE > ADAPT > COMBINE > BUILD`

If a proven route exists:
- pin its exact source/commit;
- verify license;
- run the smallest compatibility test;
- adapt/reuse it before writing a custom equivalent.

You may BUILD a custom material mechanism only if:
- no materially relevant proven route exists; or
- the best proven route fails a bounded compatibility test; or
- it cannot satisfy a named product requirement; or
- license/security/runtime makes it unusable.

Record the exact incompatibility. Do not reject working code because it is not architecturally "ours".

Do not blindly trust low-proof GitHub code:
- no copying without license;
- no AGPL/custom-license adoption without explicit human approval;
- stars are not proof;
- live tests / rendered output / direct readback outrank popularity.

## Fast session start

Read:
1. `PROJECT_STATE.md`
2. `plan.md`
3. this file
4. `docs/research/OSS_PROVEN_CODE_RESEARCH_20261009.md`
5. only directly relevant architecture/source files.

Run Git sanity once:
- `git branch --show-current`
- `git status --short`
- `git rev-parse HEAD`

A dirty tree is not automatically a blocker.

- overlapping unowned TRACKED changes -> BLOCKED;
- unrelated tracked changes -> preserve/avoid;
- known untracked reports/artifacts/locks -> non-blocking;
- never reset/clean/stash/discard unknown work without explicit human permission.

## Current S007 law

The custom Reel #3 caption-carrier/canary route is frozen.

Do NOT:
- invent carrier V4/V5;
- continue structural/ordinal/name canaries;
- retry terminally failed custom commands;
- rebuild basic captions;
- retune caption detection without visual evidence.

Current first mechanism:
`samuelgursky/davinci-resolve-mcp@94c7a885d53f13be78522ce96561a9e9e21d64c5`

Reuse its live-tested nested-timeline Text+ route.

## Stage execution

One Stage normally contains several meaningful production steps.

For R1:
`inspect -> reuse/adapt proven route -> focused test -> real artifact -> repair -> continue`

Default repair budget: 3 focused cycles inside the SELECTED proven route.

A repair cycle does NOT authorize switching back to a custom mechanism while an untested proven route exists.

## Resolve protected boundaries

Preserve unless current Stage explicitly authorizes:
- active Reel/target;
- public CLI/API;
- bounded queue/bridge boundary;
- run identity/provenance;
- accepted captions/cuts;
- protected historical/GOLD fixtures.

Automated unit tests must not mutate the real Resolve project.

Live compatibility tests should prefer disposable timelines/projects before Reel #3.

## HUMAN_REVIEW vs BLOCKED

HUMAN_REVIEW:
- live Resolve command is prepared;
- visual judgment is required;
- credentials/permission/destructive approval needed.

BLOCKED only when safe progress is impossible:
- objective/target conflict;
- architecture/material-dependency decision;
- best proven route cannot be tested due missing required input/runtime;
- conflicting overlapping unowned tracked work;
- repair budget exhausted;
- incompatible license without alternative.

Do NOT block on harmless report residue, lock files, tracker lag, archived plans, stale labels, safely fast-forwardable state.

## Reporting

R1 short result:

```text
RESULT: PASS / FAIL_REPAIRABLE / HUMAN_REVIEW / BLOCKED
OSS SOURCE: repo@commit
REUSED: mechanism
CHANGED: ...
VERIFIED: ...
ARTIFACT: ...
BLOCKER: ...
```

Full report only for R2/R3, complex incidents, or explicit request.

## Evidence hierarchy

real rendered/visible output
> live Resolve readback
> upstream live integration tests
> focused integration tests
> unit tests
> docs/claims
> popularity
> model confidence.

## Anti-loop

STOP and reframe when:
- 3 similar repairs fail;
- 2 plan rewrites happen without visible output;
- process work consumes >20% of Stage;
- a custom mechanism is being debugged while a proven equivalent has not been tested.

If proven upstream code exists, the default answer is to **reuse it**, not add another probe.

## Stage completion

Continue same session until:
- stage exit criteria are met;
- HUMAN_REVIEW is next;
- a true BLOCKED condition occurs;
- context is stale/contaminated.

Do not invent the next Stage.
