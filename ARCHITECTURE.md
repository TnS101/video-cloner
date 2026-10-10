# ARCHITECTURE.md — Video Cloner Stable System Boundaries

- STATUS: APPROVED
- VERSION: A002
- LAST UPDATED: 2026-10-10
- BASELINE: `video-cloner-canonical-cleanup-20261007`

> Stable architecture only. **Do not place current Reel/target, active stage, temporary sequencing, current blocker or sprint status here.** Those belong in `PROJECT_STATE.md`.

## 1. System Purpose

Turn a reference video plus extracted editing/style evidence into deterministic analysis, edit decisions, reusable style/profile artifacts, an editable timeline package, and bounded editor application so the generated result can reproduce the source editor's visible behavior.

## 2. Product Capability Constraints

The architecture must support, where present in source evidence:

- cuts/shot timing;
- caption semantic/composition/style/lifecycle/animation;
- transitions;
- motion transforms / zoom / retiming when source-backed;
- supported VFX/occlusion;
- deterministic provenance and editable output;
- human visual acceptance of perceptual fidelity.

## 3. Stable Architecture Summary

```text
Operator / future UI / external service
        |
        v
video-cloner CLI  OR  video_cloner.pipeline API
        |
        v
ingest/reuse
 -> analysis
 -> animation exemplar/source adapters
 -> normalized animation recipe / style authority
 -> transition policy
 -> planning
 -> profiles/style authority
 -> editable timeline/FCPXML compilation
 -> bounded Resolve command publication
        |
        v
.agent/commands (local Resolve runtime state)
        |
        v
Resolve Workspace launcher
 -> VC_Run_Agent_Task.py
 -> VC_Agent_Bridge.py
 -> bounded application modules
```

No public API launches Resolve directly.

## 4. Components and Responsibilities

| Component | Responsibility | Must Preserve |
|---|---|---|
| `video_cloner.pipeline` | Public orchestration, run identity, manifests | stable API for CLI/future UI/services |
| `video_cloner.config` / contracts | validated runtime/tool/identity inputs | no hidden machine constants |
| `video_cloner.ingestion` | deterministic media ingest/prep | reusable artifacts |
| `video_cloner.analysis.*` | cuts/transcript/rhythm/caption/motion/transitions/occlusion evidence | capability separation + provenance |
| animation exemplar adapters | ingest reference-video evidence or external exemplars such as CSS/JS/GSAP/code, GIF/frame sequences, short clips and supported Resolve templates/timelines | normalize to editor-independent animation recipes; no live mutation |
| animation execution adapters | map normalized animation recipes into editable editor-native constructs | source representation stays separate from Resolve application |
| `video_cloner.planning.*` | merge/plan/validate/compile edit decisions | deterministic validated plan |
| caption/style/profile modules | convert evidence into reusable visual/edit authority | no silent live mutation |
| `video_cloner.resolve.fcpxml` | editable offline timeline compilation | deterministic output contract |
| `video_cloner.resolve.queue` | bounded operation publication | no arbitrary caller-selected module |
| `.agent/commands` | local Resolve runtime state | machine-local queue namespace |
| Resolve launcher/bridge | explicit live mutation boundary | fail closed + bounded operation |
| `.project_ops` | lightweight project-management/evidence support | never used as Resolve runtime |

## 5. Durable Interfaces / Contracts

- CLI: `video-cloner run ...`
- Python: `video_cloner.pipeline.run(...)`
- Offline: `run_offline(...)`
- immutable run identity / manifest;
- bounded Resolve publication;
- human gate for live/subjective editor operations.

## 6. Runtime Model

- Windows development/runtime environment.
- Core Python supports 3.10-3.14.
- Audio/OCR may use configured worker environments.
- FFmpeg / yt-dlp / optional local inference / Resolve are external adapters.
- Do not force single-environment unification during feature debugging.

## 7. Security / State Boundary

- secrets/local configuration remain untracked;
- `.agent` is Resolve runtime state;
- `.project_ops` is project-management/evidence support;
- public identity/provenance must not expose credentials/query secrets.

## 8. Protected Known-Good Behavior

- canonical GitHub source and recovery history;
- public CLI/API architecture;
- explicit Resolve mutation boundary;
- protected historical/GOLD fixtures and accepted artifacts;
- deferred capability sources remain available until canonical replacements/tests exist.

## 9. Explicit Non-Goals of the Architecture

- agentic editor control as the deterministic execution engine;
- speculative multi-editor redesign without an approved product requirement;
- rebuilding historical script forests as runtime;
- coupling animation understanding to one detector, one exemplar format or one renderer;
- forcing one dependency/runtime environment when adapters already isolate concerns.

## 10. Architecture Change Triggers

Open a material architecture decision only when evidence shows:

- a required product behavior cannot fit current public/application boundaries;
- a material dependency/renderer/editor adapter/data model must change;
- repeated implementation failures prove the boundary itself is wrong;
- security/data constraints materially change.

Ordinary bugs, visual tuning, Reel-specific production work and local adapter fixes are not architecture changes.

## 11. Detailed Authority Pointers

- `docs/CANONICAL_PROJECT_STATE.md`
- `docs/VIDEO_CLONER_FINAL_HANDOFF.md`
- `docs/repo_hygiene/CURRENT_PIPELINE_GRAPH.md`
- `docs/repo_hygiene/DEFERRED_CAPABILITIES_INDEX.md`
- `docs/repo_hygiene/CANONICAL_REGRESSION_BASELINE.md`
