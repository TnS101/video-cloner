# ARCHITECT_RULES.md — Video Cloner Browser Architect Contract v2.1

## Authority

Priority:
1. explicit human command / Win Condition / active Reel/target;
2. direct current evidence;
3. `PROJECT_STATE.md`;
4. stable `ARCHITECTURE.md`;
5. current `plan.md`;
6. `PROJECT_TRACKER.xlsx`;
7. older decisions/history.

The Architect may challenge a route, but may not silently switch Reel, target, phase, priority, or human sequencing.

## Hard Win Condition

Ship a working Video Cloner by end of week that analyzes a reference Reel and reproduces the core/basic principles of its editor's style as a usable editable clone.

## HARD LAW — PROVEN CODE FIRST

Before designing or implementing a **material mechanism**, the Architect and Worker must first determine whether proven existing code already solves it.

Order:

`REUSE > ADAPT > COMBINE > BUILD`

### Material mechanism examples
- editor automation primitive;
- caption/title carrier;
- transition/effect engine;
- scene/cut detector;
- optical-flow/motion primitive;
- ASR/alignment pipeline;
- timeline IR/interchange;
- renderer;
- automation/content pipeline;
- major dependency.

### "Proven" standard

Prefer:
1. live-tested exact-system mechanism;
2. mature active library with tests/benchmarks;
3. reproducible end-to-end implementation with direct output verification.

Stars are supporting evidence, not proof.

Before adoption check:
- license;
- maintenance/current activity;
- exact mechanism overlap;
- target-platform/runtime compatibility;
- integration cost;
- real verification evidence.

### Custom BUILD gate

Custom implementation is authorized only when:
- no materially relevant proven route exists; OR
- the best proven route fails a bounded compatibility test; OR
- the route cannot satisfy a named product requirement; OR
- license/security/runtime constraints make reuse impossible.

The incompatibility must be recorded concretely.

"Not invented here", preference, aesthetics, or architecture purity are not valid reasons to reject working proven code.

### No blind copying

OSS-first does NOT mean trust every GitHub repo:
- no code copying without license;
- no low-proof repo treated as production authority;
- no AGPL/custom-license integration without human approval;
- no wholesale dependency adoption when a small stable mechanism is enough.

## Production Value Gate

Before work:
> If finished today, does this visibly advance the Win Condition or directly unblock the Critical Path?

If NO -> backlog/side quest/pre-ship.

Two consecutive process-only tasks in production require human approval.

## Stage/session law

One meaningful Stage normally spans 3–10 substantial steps in the same Browser/Codex sessions.

Fresh session only when:
- human-visible milestone changes materially;
- architecture/security/dependency route changes materially;
- context is stale/contaminated;
- release/hardening begins.

The human just changed the dependency/reuse route materially, so S007 is a valid fresh Stage.

## State ownership

`PROJECT_STATE.md` = single volatile operational truth.

`ARCHITECTURE.md` = stable boundaries only.

`PROJECT_TRACKER.xlsx` = human roadmap/backlog/research view; update at meaningful stage/priority changes, not every task.

`plan.md` = current Stage contract.

## Risk tiers

### R1 — reversible production
- normal implementation/integration;
- focused tests;
- up to 3 repairs;
- short result.

### R2 — live/high-risk integration
- Resolve mutation;
- destructive/external action;
- human visual gate;
- durable evidence as needed.

### R3 — architecture/security/release
- explicit decision;
- stronger checkpoint/regression;
- human approval for one-way doors.

## Research rule

Research is no longer merely "late stage".

For any material mechanism:
1. search existing solutions;
2. audit serious candidates;
3. stop when the reuse/build decision is stable;
4. pin selected source/version;
5. integrate the smallest proven mechanism.

For Video Cloner, the comprehensive baseline is:
`docs/research/OSS_PROVEN_CODE_RESEARCH_20261009.md`.

Future searches should be targeted to new gaps, not repeat the entire ecosystem scan.

## Review policy

Evidence hierarchy:

real output / rendered result / live readback
> integration test
> focused automated tests
> docs/claims
> popularity
> worker confidence.

Never accept "works in mocks" over a known live-tested upstream route.

## Status semantics

- PASS — observable result achieved.
- FAIL_REPAIRABLE — repair remains inside the selected proven route.
- HUMAN_REVIEW — human action/judgment is next.
- BLOCKED — safe progress impossible without new input/decision/permission.

## Anti-loop kill rules

Stop and change route when:
- 3 materially similar repairs fail;
- 2 plan rewrites happen without a user-visible artifact;
- 2 consecutive process-only tasks occur in PRODUCTION;
- process consumes >20% of a production Stage without visible payoff;
- a custom mechanism is being debugged while a proven upstream implementation of the same mechanism has not been tested;
- duplicated state/gates create more work than risk reduction.

When a proven upstream route exists, the correct response to a custom loop is usually **replace the custom route**, not add another probe.

## Human role

Human owns objective, priority, active Reel/target, material tradeoffs, license/cost approval, destructive actions, and subjective visual acceptance.

Do not turn the human into a relay between agents for routine process.
