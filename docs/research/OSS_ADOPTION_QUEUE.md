# OSS_ADOPTION_QUEUE.md — Video Cloner Sequential Proven-Code Queue

- STATUS: ACTIVE
- POLICY: `REUSE > ADAPT > COMBINE > BUILD`
- HUMAN AUTHORITY: the human may reorder this queue at any time.
- RULE: exactly **one** OSS work unit is `ACTIVE` at a time.
- CURRENT UNIT: `OSS-001`
- ACTIVE REEL FOR PRODUCTION INTEGRATION: `DZatr0EJt4B`
- RESEARCH BASELINE: `docs/research/OSS_PROVEN_CODE_RESEARCH_20261009.md`

This file answers one question at all times:

> **Which proven OSS mechanism are we adapting/reusing right now, and what comes next?**

A work unit changes status only at a meaningful compatibility/integration boundary. Do not create micro-units for individual tests.

## Queue

| ID | Layer / Capability | Primary Proven Route | Backup / Secondary | Immediate Product Outcome | Status | BUILD Gate |
|---|---|---|---|---|---|---|
| OSS-001 | Resolve editable Text+ placement / caption carrier | `samuelgursky/davinci-resolve-mcp@94c7a885...` nested-timeline Text+ | `mhadifilms/dvr`, `pydavinci` | Stable editable Text+ can be placed at exact track/start/duration in Resolve | **ACTIVE** | Only if proven nested-timeline route and next proven wrapper route fail exact compatibility |
| OSS-002 | Advanced caption animation on Reel #3 | proven Text+ carrier from OSS-001 + existing VC detection; HyperFrames as animation/reference benchmark | ghost-editor recipes; Remotion only if license approved | Apply preserved 16-caption plan: 10 scale + 6 slide, visually accepted | QUEUED | Only if proven Text+/animation route cannot express required motion |
| OSS-003 | Transitions | Resolve MCP verified API/workaround ledger + HyperFrames transition catalog/runtime | OpenChatCut reference; Remotion license-gated | Source-backed Reel #3 transitions become executable/editable | QUEUED | Only after proven routes fail named transition family |
| OSS-004 | Core motion / VFX | HyperFrames for animation/synthetic truth + Resolve MCP for editor application | OpenCV; RAFT/GMFlow when optical-flow evidence is required | Highest-ROI Reel #3 motion/VFX family becomes executable (blur/whip/zoom/etc. based on source evidence) | QUEUED | Only after relevant proven mechanism fails on measured Reel #3 gap |
| OSS-005 | Speed ramps / retiming | Resolve MCP capability ledger / known DRT-OTIO route where public API is insufficient; HyperFrames speed-ramp reference | auto-editor effects | Source-backed speed ramps can be represented and reproduced | QUEUED | Only after verified Resolve/existing route cannot meet retime requirement |
| OSS-006 | Cuts / scene detection | PySceneDetect | TransNetV2 | Preserve current cuts now; on generalization, benchmark proven detector before changing cut logic | QUEUED — TRIGGERED BY CUT FAILURE | Only after benchmark failure on actual corpus |
| OSS-007 | Auto rough-cut / silence / motion intervals | auto-editor | timkulbaev/ai-video-editor patterns | Raw footage can be deterministically shortened/segmented without agentic editing loops | QUEUED — GENERALIZATION | Only after auto-editor cannot express required interval logic |
| OSS-008 | Caption word timing / alignment | WhisperX | VideoLingo forced-alignment/chunking | Word-level caption timing becomes robust on unseen/raw reels | QUEUED — GENERALIZATION | Only after measured alignment failure |
| OSS-009 | Timeline IR / interchange | OpenTimelineIO | FCPXML/auto-editor format mechanisms | Avoid custom generic timeline IR if multi-editor/interchange becomes necessary | QUEUED — ON TRIGGER | Only if OTIO cannot express named contract |
| OSS-010 | Style-template / editing-DNA schema | current VC schema + audit of EditDNA / video-style-kit / ghost-editor | ai-video-agent patterns | Strengthen reusable style representation without replacing proven working core | QUEUED — AFTER CORE VISUAL BASELINE | Only after schema comparison identifies a missing contract |
| OSS-011 | QA / visual acceptance tooling | video-editor-agent QA patterns + existing VC readback | render-first frame/dB comparisons | Catch visual/audio regressions before human review | QUEUED — AFTER CORE VISUAL BASELINE | Only if existing + adapted QA cannot catch named failures |
| OSS-012 | Content-automation ecosystem | MoneyPrinterTurbo patterns + VideoLingo + ghost-editor workflow | ShortGPT/reference pipelines | Connect Video Cloner to scripts/assets/TTS/subtitles/publishing without rebuilding solved orchestration | QUEUED — POST CORE CLONER | Custom ecosystem glue only after reuse audit |

## Visual-layer production order

For the **current Reel #3 ship path**, the visual sequence is:

1. **Caption carrier / placement** — OSS-001.
2. **Advanced caption animation** — OSS-002.
3. **Transitions** — OSS-003.
4. **Core motion / VFX** — OSS-004.
5. **Speed ramps / retiming** — OSS-005.
6. **Integrated Reel #3 visual review**.

Cuts are already accepted baseline behavior, so we do **not** reopen them just because OSS-006 exists. OSS-006/007/008 become active when unseen/raw Reel generalization begins or a measured regression triggers them.

## Generalization / automation order

After the current Reel #3 core visual baseline:

7. **Cuts / scene detection benchmark** — OSS-006, only if current cut logic fails.
8. **Auto rough-cut** — OSS-007.
9. **Word timing / alignment** — OSS-008.
10. **Timeline IR** — OSS-009 only if multi-editor/interchange requires it.
11. **Style schema audit** — OSS-010.
12. **QA layer** — OSS-011.
13. **Content automation ecosystem** — OSS-012.

The human may explicitly reorder these based on product value.

## Work-unit state contract

Each unit has exactly one of:

- `ACTIVE` — the only OSS mechanism currently being integrated.
- `QUEUED` — next planned capability.
- `TRIGGERED` — a measured product failure activated it.
- `PASS / INTEGRATED` — proven route works in Video Cloner.
- `FAIL / INCOMPATIBLE` — proven route failed a documented requirement; proceed to backup candidate.
- `DEFERRED` — human moved it out of the Critical Path.

When an ACTIVE unit finishes:

1. record exact source repo + pinned commit + license;
2. record compatibility result;
3. record reused/adapted mechanism;
4. update `PROJECT_STATE.md` CURRENT OSS ITEM;
5. move the next human-approved queue unit to `ACTIVE`;
6. continue production.

Do not create a new custom mechanism unless the unit's BUILD Gate is satisfied.

## Current work unit — OSS-001

### Source
`samuelgursky/davinci-resolve-mcp@94c7a885d53f13be78522ce96561a9e9e21d64c5`

### Exact upstream mechanism
`tests/live_workaround_verification.py::case_nested_title`

Nested timeline:
- create source timeline;
- `InsertFusionTitleIntoTimeline("Text+")`;
- configure Text+;
- get source timeline `MediaPoolItem`;
- use `MediaPool.AppendToTimeline` with exact `trackIndex`, `recordFrame`, `startFrame`, `endFrame`;
- verify track/start/duration;
- reopen inner timeline and verify Text+ remains editable.

### DONE
Disposable compatibility test passes on this Resolve runtime.

### Next
OSS-002 immediately uses this carrier on Reel #3, first one caption, then the preserved 16-caption animation plan.
