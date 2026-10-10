# OSS_ADOPTION_QUEUE.md — Video Cloner Proven-Code Queue

- UPDATED: 2026-10-10
- MODE: SPEEDRUN / PROVEN-CODE-FIRST
- RULE: `REUSE > ADAPT > COMBINE > BUILD`
- ACTIVE: `OSS-002`

## Production Override — 2026-10-10

Human visual review overrules the prior assumption that the existing Video Cloner caption-animation detector was good enough to roll forward.

### Frozen route

Existing custom Step 3C plan:

- 16 selected captions;
- 10 `scale`;
- 6 `slide`;
- 0 `scale_pop`.

What the live evidence proves:

- the Resolve application carrier works;
- one persisted `sub_008` slide is visible/editable;
- many real source animations remain undetected;
- several source captions use compound motion such as translation + scale;
- the simple custom taxonomy is not close enough to production fidelity.

Decision: **FROZEN / REJECTED FOR PRODUCTION. No further tuning.**

## Sequential Queue

### OSS-001 — Editable Resolve Text+ carrier — PASS / CLOSED

Primary:
- `samuelgursky/davinci-resolve-mcp@94c7a885d53f13be78522ce96561a9e9e21d64c5`
- MIT.

Proven:
- native Text+ insertion;
- nested source timeline;
- source MediaPoolItem;
- exact `AppendToTimeline` placement;
- placed-item `GetTimeline()`;
- inner Text+ reach-back/editability.

Keep frozen as the application primitive.

### OSS-002 — Caption animation detection/representation/application — ACTIVE / OSS OVERDRIVE

Objective:
- replace the frozen custom detector with proven OSS adaptation that materially improves coverage and compound-motion fidelity.

Primary first adaptation target:
- `heygen-com/hyperframes@46f6cb356785bed79e1ce7b79d7e7accc697786a`
- Apache-2.
- Audit concrete reusable animation/runtime/GSAP/caption-identity/synthetic-reference mechanisms.
- Do **not** assume it is a complete reference-video detector; verify exact capability.

Supporting candidate pool:
- `kurbaitaev/ghost-editor@9f197e4e65691d190ba63efa6c061d9c43f02cf6` — MIT.
- video-style-kit / EditDNA patterns already captured in research.
- Remotion only behind explicit license approval.

Execution:
- map winning OSS representation through OSS-001 Resolve carrier.

Acceptance:
- materially better coverage than 16-caption custom plan;
- compound transforms supported where present;
- editable Resolve output;
- batch HUMAN_REVIEW accepted.

Build gate:
- no greenfield detector work before the strongest two compatible OSS routes/compositions fail the same named requirement.

### OSS-003 — Transitions — NEXT

Primary:
- reuse/adapt proven transition mechanisms/patterns from HyperFrames + Resolve-compatible primitives.

Goal:
- apply source-backed transitions visibly and editably.
- no reopening cuts.

### OSS-004 — Core motion / VFX

Use proven mechanisms from HyperFrames / Resolve primitives and established CV components only where source evidence requires them.

Potential CV primitives already researched:
- OpenCV;
- RAFT / GMFlow where optical-flow evidence materially improves a required effect.

### OSS-005 — Speed ramps / retiming

Reuse proven retiming mechanisms; integrate only source-backed ramps.

### OSS-006 — Cuts / scene detection

Current cuts are accepted.

Only reopen on actual failure/generalization evidence.

Candidates:
- PySceneDetect;
- TransNetV2 fallback.

### OSS-007 — Auto rough-cut
- auto-editor.

### OSS-008 — Caption timing/alignment
- WhisperX;
- VideoLingo.

### OSS-009 — Timeline IR/interchange
- OpenTimelineIO.

### OSS-010 — Style schema
- current VC profile + EditDNA/video-style-kit/ghost-editor audit.

### OSS-011 — QA / acceptance
- reusable render/readback/human-review acceptance layer.

### OSS-012 — Content automation
- MoneyPrinterTurbo + VideoLingo/ghost-editor patterns.

## Visual Critical Path

`OSS-002 caption animations`
-> `OSS-003 transitions`
-> `OSS-004 motion/VFX`
-> `OSS-005 speed ramps`
-> integrated visual review.

## Future Animation Exemplar Sources

After the current critical path, the animation system should accept adapters for:

- reference-video frames/clips;
- CSS/JS/GSAP;
- pure code;
- GIFs;
- frame sequences;
- very short MP4/GIF samples;
- Resolve templates/timelines/DRT/DRP-like project artifacts where supported.

All should normalize to a common animation recipe/representation before editor-specific application.
