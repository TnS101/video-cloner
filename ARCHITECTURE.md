# ARCHITECTURE.md — Video Cloner Approved System Boundaries

- STATUS: APPROVED
- VERSION: A001
- LAST UPDATED: 2026-10-09
- APPROVED BY HUMAN: YES
- BASELINE: `video-cloner-canonical-cleanup-20261007`

> This summarizes the CURRENT approved architecture. It does not replace detailed canonical documents under `docs/` and `docs/repo_hygiene/`.

## 1. System Purpose

Turn source video plus editing/style evidence into reproducible analysis, edit decisions, style/profile artifacts, an FCPXML timeline package, and a bounded editor-application command, while preserving run identity/provenance and keeping execution deterministic.

## 2. Observable Product Win Condition

For the immediate product gate, one clean/raw target must be processed through the public pipeline and applied in DaVinci Resolve with:

- correct target identity;
- persistent readback;
- safe declared second-run/idempotency behavior;
- protected timelines untouched;
- human-approved visual result.

Future editor adapters are enabled by the application boundary but are not required for P001.

### Production sequencing override — SPEEDRUN (2026-10-09)

The complete PH1 ship-acceptance criteria in §2 remain **release gates**, but they no longer block PH2 caption production. PH2 begins immediately from the retained Reel #2 GOLD and accepted caption authorities. P004 save/reopen persistence, live repository-identity proof, same-target replay/idempotency, and formal full-target acceptance are deferred to `PRE-SHIP`. This changes sequencing only; it does not weaken release acceptance or alter the approved architecture.

## 3. Current Architecture Summary

```text
Operator / future UI / external service
        |
        v
video-cloner CLI  OR  video_cloner.pipeline API
        |
        v
ingest/reuse
 -> analysis
 -> transition policy
 -> planning
 -> profiles
 -> FCPXML compile
 -> bounded Resolve queue publication
        |
        v
.agent/commands (local runtime state)
        |
        v
Resolve Workspace launcher
 -> VC_Run_Agent_Task.py
 -> VC_Agent_Bridge.py
 -> frozen Phase 6 application module
```

No public API launches Resolve directly.

## 4. Components and Responsibilities

| Component | Responsibility | Must Preserve |
|---|---|---|
| `video_cloner.pipeline` | Public application orchestration, run identity, manifest | One stable API for CLI/future UI/services |
| `video_cloner.config` / `contracts` | Runtime inputs, worker/tool paths, identity/contracts | Validated inputs; no hidden machine constants |
| `video_cloner.ingestion` | Media ingest/prep | Deterministic reusable artifacts |
| `video_cloner.analysis.*` | Cuts/transcript/rhythm/caption/motion/transitions/occlusion evidence | Capability separation; evidence provenance |
| `video_cloner.planning.*` | Merge/plan/validate/compile edit decisions | Deterministic validated plan |
| camera/caption/style/profile modules | Style/edit profile generation | No silent Resolve mutation |
| `video_cloner.resolve.fcpxml` | Offline timeline compilation | Deterministic output contract |
| `video_cloner.resolve.queue` | Bounded operation publication | No arbitrary module path exposed publicly |
| `.agent/commands` | Local Resolve command state | Ignored machine-local runtime namespace |
| Resolve launcher/bridge | Explicit live mutation boundary | Fail closed; provenance; frozen unless dedicated Plan |
| `.project_ops` | Plan/report/project-management support | Must never be used as Resolve queue/runtime |

## 5. Interfaces / Public Contracts

- CLI: `video-cloner run ...`
- Python: `video_cloner.pipeline.run(...)`
- Offline: `run_offline(...)`
- Run evidence: immutable `run_id` + atomic run manifest
- Resolve publication: bounded timeline-import operation, not caller-selected Python module
- Human gate: Resolve Workspace action for live execution

## 6. Runtime Model

- Windows development/runtime environment.
- Core Python supports 3.10–3.14.
- Audio/OCR capabilities may use separately configured Python 3.10 worker environments.
- FFmpeg / yt-dlp / optional Ollama / Resolve are external tools/adapters behind configuration.
- Do not force single-environment unification during product debugging.

## 7. Security / State Boundary

- Secrets/local configuration are untracked (`.env`, cookie path, local runtime state).
- `.agent` is Resolve runtime state and is ignored except `.agent/README.md`.
- `.project_ops/artifacts` and `.handoffs` are local/ignored.
- Public runtime identity must not expose credentials/query secrets.

## 8. Protected Known-Good Behavior

- GitHub `main` + cleanup tag represent clean canonical source.
- Canonical regression remains green (116 current-path tests at bootstrap creation).
- CLI/API do not require BAT/PowerShell/N8N orchestration.
- Resolve live mutation is explicit, not automatic.
- Protected Reel #2 GOLD must not be mutated.
- Deferred capability sources remain indexed until canonical replacements/tests exist.

## 9. Explicit Non-Goals Right Now

- HyperFrames/Remotion/rough-cut/editor-adapter integration before current product bottleneck is resolved.
- Generic multi-editor IR redesign during P001.
- Full dependency/runtime unification.
- Recreating deleted historical Step/Phase script forests.
- Treating agentic editor control as the deterministic execution engine.

## 10. Architecture Risks / SPOFs

- Resolve bridge is still the unaccepted live execution SPOF.
- Some deferred caption/visual capabilities retain legacy compatibility source until canonicalized.
- Finished/flattened Reel evidence cannot prove all underlying editor transforms.
- Human visual acceptance remains required for visual fidelity.

## 11. Architecture Change Triggers

Open an explicit architecture decision only when evidence shows:

- the public pipeline cannot satisfy a required product behavior;
- current bounded editor adapter cannot support a required operation safely;
- a repeated defect is architectural rather than implementation-specific;
- a new editor/rendering mechanism requires a material contract change;
- security/data/dependency constraints materially change.

Codex reports the trigger; Browser Architect decides; human approves material changes.

## 12. Detailed Authority Pointers

- `docs/CANONICAL_PROJECT_STATE.md`
- `docs/VIDEO_CLONER_FINAL_HANDOFF.md`
- `docs/repo_hygiene/CURRENT_PIPELINE_GRAPH.md`
- `docs/repo_hygiene/DEFERRED_CAPABILITIES_INDEX.md`
- `docs/repo_hygiene/CANONICAL_REGRESSION_BASELINE.md`
