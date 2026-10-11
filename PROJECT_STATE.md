# PROJECT_STATE.md — VIDEO CLONER CURRENT PRODUCT STATE

## Objective

Finish Video Cloner as the intelligence/analysis layer that can inspect a reference Reel and reproduce its core editing behavior into an editable clone. Future Auto Editing/application automation is a separate project/layer.

## Active production target

- Reel: `DZatr0EJt4B` (Reel #3)
- Resolve: Free `21.0.4.5`
- Accepted visual baseline: `VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_TRANSITIONS_V1`
- Branch: `architect/p004-persistence-unblock-draft`
- Current remote checkpoint before this product-only cleanup: `cddb9f2d56a947dfa2f47ad06a19a363074cb658`

## Already working / accepted

- Cuts + audio baseline.
- Captions: 69 editable V3 animated replacements + 43 visible V2 static fallbacks. Accepted for MVP; do not reopen.
- Native transitions: 3 selectable/editable `Blur Dissolve` transitions at boundaries 80, 286, 376. Accepted for MVP; do not reopen.
- Resolve native transition insertion route is proven.
- Existing OSS/reuse work is historical knowledge, not an active process queue.

## Current move

Finish OSS-004 core motion/VFX using the implementation already committed in:

`cddb9f2d56a947dfa2f47ad06a19a363074cb658`

The previous Codex session was terminated because it spent >35 minutes on snapshot/graph-validation design. Do not restart that work. Inspect the existing OSS-004 implementation, publish/run the smallest representative Resolve batch, and judge the visible result.

Expected representative set includes the already-selected 211 / 461 / 629 motion-VFX cases plus the two already-selected shot-motion examples. Do not search for more unless the implementation itself proves one target invalid.

## Next

1. Accept/fix/defer the OSS-004 representative batch, then full-rollout the working motion/VFX.
2. OSS-005 speed ramps/retiming.
3. Integrated Reel #3 review.
4. Generalization test.
5. Only after Video Cloner is complete: optional polish and the separate Auto Editing layer.

## Known non-blocking debt

- Old experimental `VC_OSS003_` Fusion effects may exist. Ignore unless they visibly break the current product.
- Caption persistence and exact 1:1 kinetic typography are post-MVP polish.
- Exact transition-strength mapping is post-MVP polish.

## Hard rule

PRODUCT IMPLEMENTATION ONLY.

No architecture, infrastructure, process artifacts, trackers, plans, reports, validation frameworks, snapshot systems, rollback frameworks, new test frameworks or documentation maintenance unless the user explicitly asks for them.
