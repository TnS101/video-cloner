# RESEARCH_BASELINE.md — Video Cloner Reuse / Existing-Solution Policy

## Current status

- CURRENT PLAN: `P001_LIVE_RESOLVE_ACCEPTANCE`
- RESEARCH GATE: `NOT_APPLICABLE`
- REASON: P001 validates already-approved canonical mechanisms and adds no dependency/architecture choice.

## Late-stage research rule

Before custom-building or integrating a NEW material mechanism, Browser Architect must inspect the strongest relevant existing mechanisms first. This includes new:

- caption/animation renderer;
- rough-cut engine;
- editor adapter/exporter;
- media-analysis subsystem;
- orchestration/runtime mechanism;
- model/service dependency.

When triggered, target at least 5 materially relevant alternatives if that many credible options exist. Record:

- repository/tool + URL;
- maintenance/activity;
- license/commercial implications;
- local/free usability and any hard limits;
- reusable mechanism;
- integration friction;
- `REUSE / ADAPT / COMBINE / BUILD / IGNORE` decision;
- concrete rejection reason.

Do not integrate a project merely because it is interesting.

## Known future research queue — NOT YET DECIDED

The human has identified these as future candidates worth investigating when their capability becomes the bottleneck:

- HyperFrames / Remotion-style programmatic animation/rendering;
- deterministic rough-cut OSS such as auto-editor-like mechanisms;
- multi-editor timeline/export adapters.

These names are prompts for a future evidence-based scan, not approved dependencies.

## Current reuse decision

For P001: `REUSE EXISTING CANONICAL VIDEO CLONER + FROZEN RESOLVE BOUNDARY`.
