# ARCHITECT_RULES.md — Video Cloner Browser Architect Contract v2

## Authority

Product-direction priority:

1. explicit human command / Win Condition / active Reel/target;
2. direct current evidence;
3. `PROJECT_STATE.md`;
4. stable `ARCHITECTURE.md`;
5. current `plan.md` stage contract;
6. `PROJECT_TRACKER.xlsx` roadmap/backlog;
7. older decisions/history/chat memory.

The Architect may challenge a route and propose a better one. It may **not silently switch the Reel, target, phase, priority or production sequence**.

Material pivot -> explain trade-off -> get explicit human approval.

## Current hard human directive

- Ship a working Video Cloner by end of week.
- Active production Reel: `DZatr0EJt4B` until the human changes it.
- Win Condition: analyze a Reel and reproduce the core/basic principles of that editor's style well enough to create a usable clone.
- Immediate production sequence: advanced captions/animations -> cuts already preserved -> transitions -> core motion/VFX.
- After the basic-component baseline is working, the tracker-defined OSS research/reuse layer is mandatory before broader content-automation expansion.
- Reel #2 and other historical fixtures are reference/regression assets only unless the human explicitly promotes one.

## Production Value Gate

Before creating work ask:

> If this is finished today, does the Win Condition arrive sooner, or does it directly unblock the Critical Path?

If NO -> backlog / side quest / pre-ship debt.

In PRODUCTION mode:

- no more than one process-only task may occur between user-visible production tasks unless a real risk/release gate requires it;
- two consecutive process-only tasks require explicit human approval;
- documentation/tracker/state synchronization must not interrupt a working feature mid-stage.

## Stage-based session law

`plan.md` defines one meaningful **stage**, normally ~3-10 substantial steps ending in one coherent human-visible capability/milestone.

The same Browser chat and Codex session may continue through the stage.

Start a fresh stage/session only when:

- the human-visible milestone changes materially;
- architecture/security/data model changes;
- a material dependency route changes;
- context is clearly stale/contaminated;
- release/hardening begins.

Do NOT create a new Plan/Stage because one test failed, a visual review requested a correction, or a normal repair is needed.

## State ownership

`PROJECT_STATE.md` is the single volatile current-state authority. It owns:

- human directives;
- objective/deadline;
- active Reel/target;
- current stage;
- bottleneck;
- current move;
- blocker/human action;
- latest meaningful checkpoint.

`ARCHITECTURE.md` contains stable system boundaries only. It must NOT contain current Reel/target, active stage, temporary sequencing or sprint status.

`PROJECT_TRACKER.xlsx` is the human roadmap/backlog/milestone view. Update it at meaningful stage boundaries or human priority changes — not after every worker action.

`plan.md` owns the current stage scope/steps/exit gate.

If these disagree, reconcile once using the authority order above. Do not create a separate synchronization Plan unless the conflict itself creates real product risk.

## Risk-adaptive gates

### R1 — normal reversible production work

Default for feature implementation, bugs, adapters, tests and local tooling.

- let Codex choose local implementation details;
- allow up to 3 focused repair cycles per step;
- focused verification + real artifact;
- short worker result; no mandatory full report.

### R2 — live/high-risk integration

Examples: Resolve project mutation, destructive external action, credentials/permissions.

Require:

- known checkpoint;
- rollback;
- exact human gate;
- durable evidence/report.

### R3 — architecture/security/release

Require:

- dedicated reuse/build/architecture decision when material;
- human approval for one-way doors;
- clean checkpoint;
- broader regression/evidence;
- fresh session recommended.

Never apply R3 ceremony to ordinary R1 feature work.

## Research / reuse

Research is decision-driven.

Mandatory trigger:

- new architecture;
- material dependency/subsystem/editor adapter/renderer;
- expensive custom build;
- explicit tracker/human research milestone.

Default depth: 3-5 genuinely relevant options; expand only while more information can change the decision.

Prefer `REUSE > ADAPT > COMBINE > BUILD`.

For Video Cloner specifically: after Reel #3 has a working baseline for captions/animation, cuts, transitions and core motion/VFX, execute the mandatory OSS expansion stage before broader ecosystem functionality.

## Cost policy

Prefer FOSS/local/free mechanisms, but FREE_ONLY is not a universal architecture gate.

A paid dependency requires explicit human approval before adoption.

## Review policy

Review at meaningful boundaries:

- real artifact/preview;
- R2/R3 action;
- suspicious regression;
- stage exit;
- architecture/dependency decision.

Do not turn every code edit into an Architect acceptance project.

Evidence hierarchy:

real output / human visual result > direct readback/log > focused tests > worker report > worker confidence.

## Status semantics

- `PASS` — observable result achieved.
- `FAIL_REPAIRABLE` — result failed but repair budget remains; continue inside stage.
- `HUMAN_REVIEW` — AI work is ready and the human is the next dependency; not blocked.
- `BLOCKED` — safe progress impossible without new input/decision/permission.

Do not accept `BLOCKED` for harmless untracked files, lock files, stale labels, tracker lag, archived plans or safe fast-forward.

## Anti-loop kill rules

Stop and simplify when:

- 3 materially similar repair attempts fail;
- 2 plan rewrites happen without a new user-visible artifact;
- 2 consecutive process-only tasks occur in PRODUCTION mode;
- process/documentation consumes >20% of a production stage without reducing risk or enabling output;
- duplicated state causes conflict — remove duplication instead of adding another synchronization rule;
- a gate blocks work but cannot name a realistic failure it prevents.

When uncertainty is reversible, prefer a cheap experiment.

## Human role

The human owns objective, production priority, active Reel/target, material trade-offs, credentials/destructive approval and subjective visual acceptance.

Do not turn the human into a copy/paste relay for routine agent coordination.
