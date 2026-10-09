# Video Cloner Final Handoff

## Product objective

Produce a reproducible video-analysis/edit package and a bounded, provenance-backed Resolve import command from a source video.

## Architecture and commands

The authority is the `video_cloner/` package. Install with `python -m pip install -e .`; run with `video-cloner run --local-video <path> --project <name> --target-timeline <timeline>`. Python callers use `RuntimeConfig.load()` and `video_cloner.pipeline.run()`. The pipeline is ingest/reuse → analysis → transition policy → planning → profile → FCPXML compile → bounded queue publication. `run-offline` omits publication.

## Accepted Reel #2 GOLD identity

The human-accepted Reel #2 caption freeze is source reel `DcJRJtUKScu`, protected timeline `DcJRJtUKScu_offline_timeline_v1`, Resolve unique ID `4ad2a3c3-031c-464d-96aa-76a045608ad6`, and frozen DRT SHA-256 `99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e`. Known accepted deviations include non-1:1 animation/positioning and minor style differences.

## Fresh Reel DZatr0EJt4B proof

The fresh canonical run was `DZatr0EJt4B-20261007T084921050672Z-a5b35ef930c2`. It completed offline analysis, planning, profile generation, FCPXML compilation, and queue publication. Its 1,354-record run manifest SHA-256 was `c3c8a5183c707231fff06060c52fb66b05039719915c8f5b1a11d31192c5ef92`. Durable provenance is [`DZatr0EJt4B_CANONICAL_RUN_MANIFEST.json`](repo_hygiene/DZatr0EJt4B_CANONICAL_RUN_MANIFEST.json) and the detailed Step 4 report.

## Canonical E2E state

Offline generation and bounded queue publication are accepted. The generated command is evidence, not execution. No current public entry point launches Resolve.

## Resolve boundary and launcher

`RESOLVE_LAUNCHER_READY = YES`. The installed launcher is discoverable at the portable Resolve Workspace Scripts path and `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\VC_Run_Agent_Task.py`; both copies and their configs point to `C:\Users\User\Downloads\Projects\Video Cloner`, load `resolve_workspace\VC_Agent_Bridge.py`, and match the frozen repository hashes. Live machine acceptance remains **NOT ACCEPTED** because prior post-import identity/target-title validation failed. Timeline existence is not machine PASS.

## Supported vs deferred

Supported: deterministic ingest, analysis, transition policy, planning, camera/caption/style profiles, FCPXML compilation, bounded publication, manifests, and public CLI/API. Deferred: advanced caption lifecycle/animation, font application, opacity, stroke/shadow, editor transforms, Flash execution, and occlusion/compositing. The exact retained closure is indexed in [`DEFERRED_CAPABILITIES_INDEX.md`](repo_hygiene/DEFERRED_CAPABILITIES_INDEX.md); it is not an active operator surface.

## Tests and environment

Canonical regression is 116 passed; CI-equivalent core is 64 passed; Python 3.10 audio/OCR imports pass; clean package install and both console help commands pass. Virtual environments, `.agent` forensic history, and local media remain ignored local state. The reproducible 335,460,967-byte Step 4 E2E scratch tree was deleted after its durable evidence check.

## Repository authority

Repository cleanup is complete. GitHub `main` and `repo-hygiene/canonical-consolidation-20261007` are identical and authoritative. The audited historical `main` lineage was joined by `ours` merge `7a5b7ba337fc1879872beb6445dd986e632afc7b` without changing canonical tree `aeca13c0385eedeae130f8e601e10245329ec17b`. The exact final authority commit is the commit peeled from annotated tag `video-cloner-canonical-cleanup-20261007`; the tag certifies repository/software authority, not live Resolve acceptance.

## Recovery and lessons

Recovery tag: `video-cloner-pre-hygiene-snapshot-20261007` → `f728d4ae1073a2b37f58e5b06a77ed6b97ca0605`. Git history is the archive; deleted Step/Phase scripts must not be recreated. The important lesson is to separate technical persistence from visual fidelity and to keep Resolve as an explicit machine-acceptance boundary.

## Current speedrun directive — supersedes older sequencing

- **Ship by end of week.**
- Active production reel: **Reel #3 `DZatr0EJt4B`**.
- Existing Reel #3 basic Text+ captions are the baseline; do not rebuild them.
- Current work: advanced caption animations on the existing Reel #3 target, then Reel #3 cuts/transitions/core motion/VFX.
- Reel #2 is retained reference/GOLD evidence only.
- Explicit human commands are highest product-direction authority; Plan + tracker must remain aligned and no silent reel/phase/target pivot is allowed.
- After the active reel has a working baseline for captions, cuts, transitions, and core motion/VFX, the **PROJECT_TRACKER OSS research/reuse backlog layer is mandatory**. Research proven OSS projects/components and prefer reuse/adaptation before custom-building broader content-automation functionality.

## Exact next product-development move

Prepare the generic command-bound advanced caption-animation payload for the existing Reel #3 target `VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B`, then apply/review it once. After caption animation review, continue directly into Reel #3 transitions and core VFX. Do not regenerate basic captions and do not switch to another reel.
