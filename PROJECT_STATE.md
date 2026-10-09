# PROJECT_STATE.md — Video Cloner Current Operational Truth

## Human Directives

- REAL OBJECTIVE: ship a usable Video Cloner by end of week.
- ACTIVE PRODUCTION REEL: `DZatr0EJt4B` (Reel #3).
- ACTIVE RESOLVE TARGET: `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`.
- TARGET UID: `4aaa91c0-c434-4439-a15a-92ce86e80256`.
- PRIORITY: production-value work only.
- **NEW HARD DIRECTIVE: OSS-FIRST / PROVEN-CODE-FIRST.**
- Before custom-building any material mechanism, Video Cloner must search/audit/test existing proven code and prefer `REUSE > ADAPT > COMBINE > BUILD`.
- BUILD is allowed only after the best compatible proven route fails a bounded compatibility test or cannot meet a named product requirement.
- No silent Reel/target/phase pivot.

## Win Condition

Analyze a reference Reel and reproduce the core/basic principles of that editor's style well enough to create a usable, editable clone.

## Mode

- MODE: `PRODUCTION`
- DEADLINE: end of week
- DEFAULT DEVELOPMENT POLICY: `OSS_FIRST`
- CURRENT RISK: `R1` until live Resolve compatibility test requires R2

## Current Position

### Preserved working baseline
- Reel #3 offline analysis/planning exists.
- Reel #3 target timeline exists.
- Basic captions remain the accepted baseline.
- Existing cuts/shot structure remain preserved.
- Caption animation detection plan exists:
  - 112 captions total;
  - 16 selected animations;
  - 10 scale;
  - 6 slide.
- Native Resolve Text+ insertion + Fusion comp + Center→Path was proven on a disposable canary.

### Custom route status
- Custom media-backed Fusion carrier: **KILLED** after native Resolve crashes.
- Custom original-caption structural/ordinal canary sequence: **FROZEN** by human directive.
- No further custom carrier/caption-placement mechanism may be invented before proven OSS is tested.

## Main Constraint

Not "how do we invent another caption carrier?"

The bottleneck is now:
**integrate the already-proven external Resolve Text+ placement mechanism into Video Cloner and return to visible Reel #3 progress.**

## Current Stage

- STAGE ID: `S007_OSS_FIRST_PROVEN_CODE_INTEGRATION`
- STATUS: `READY`
- CURRENT MOVE: reproduce `davinci-resolve-mcp` nested-timeline Text+ live workaround on a disposable timeline, then adapt it to Reel #3.
- RESEARCH AUTHORITY: `docs/research/OSS_PROVEN_CODE_RESEARCH_20261009.md`

## Current Proven Route

Primary:
`samuelgursky/davinci-resolve-mcp@94c7a885d53f13be78522ce96561a9e9e21d64c5`

Mechanism:
nested timeline + `InsertFusionTitleIntoTimeline("Text+")` + `AppendToTimeline(trackIndex, recordFrame, startFrame, endFrame)`.

Evidence:
the upstream repository contains live Resolve verification and documents this exact route as the working workaround for chosen-track Text+ placement.

## Mandatory Next Routes by Capability

- cuts/scenes: PySceneDetect / auto-editor before custom;
- word timing: WhisperX / VideoLingo before custom;
- transitions/caption render/synthetic truth: HyperFrames before custom;
- generic timeline interchange: OpenTimelineIO before custom;
- Resolve API limitations/workarounds: davinci-resolve-mcp first;
- content-automation expansion: MoneyPrinterTurbo / ghost-editor / video-editor-agent patterns first.

## Deferred / Pre-ship Debt

- save/reopen persistence proof;
- repository identity proof;
- same-target idempotency;
- release certification.

These do not outrank current visible production work.

## Human Action

None until Codex prepares one disposable OSS compatibility command requiring Resolve.

## Anti-loop Kill Rule

If a proven mechanism exists and we are writing a custom equivalent without first testing it, **STOP**.
