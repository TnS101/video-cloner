# Git Health Audit

## Manifest semantics

`PRE_HYGIENE_SOURCE_MANIFEST.json` is the **PRE-COMMIT WORKING-TREE MANIFEST**. Its `tracked` and `modified` fields deliberately describe the working tree before recovery commit `f728d4ae1073a2b37f58e5b06a77ed6b97ca0605`; files recorded there as `tracked: false` may therefore be tracked by that commit. `SNAPSHOT_COMMIT_MANIFEST.json` is the separate authority for the actual committed Git tree and derives object IDs and byte hashes directly from that snapshot commit.

Audit date: 2026-10-07.

## State

- Branch: `migration/autonomy-baseline-20260908`.
- HEAD: `41d47ce411be3d41679ba38b7453fe411e53f2de` (`chore: checkpoint current video cloner state`).
- Upstream relation: ahead 1, behind 2.
- Dirty paths at audit start: 190.
- Modified tracked files: 12, including compiler, caption authority, Phase 6 Resolve application, and tests.
- Untracked runtime/operations scripts: 85; untracked Python tests: 65.
- Four Git worktrees are registered. No worktree cleanup was performed.

The working state is **not an accepted or clean production baseline**. A recovery snapshot commit may preserve it exactly before review; that snapshot proves recoverability only, not correctness or acceptance.

## Tracking findings

- `data/`, `input/`, `media/`, media extensions, Python caches, and `.pytest_cache/` are ignored correctly.
- `.agent/*` is ignored except `.agent/README.md`. This hides command queues and accepted reports from normal Git provenance; selected durable evidence must be promoted deliberately, not by removing the blanket ignore without review.
- `.pytest-tmp-*`, `.benchmark-inspect-*`, `_browser_evidence_*`, and root usage dumps are not ignored and currently appear as untracked noise.
- No tracked cache/media/generated binary matched the audited patterns.
- The largest tracked files are source or documentation, not binaries. The two metadata controllers are about 560 KB each.
- No byte-identical duplicate script files were found.

## Large/duplicate source risk

`resolve_workspace/resolve_apply_video_cloner_metadata.py` and `scripts/davinci/resolve_apply_video_cloner_metadata.py` are near copies: the current diff is 38 insertions and 33 deletions. Keeping two large mutable controllers is a drift risk. The bridge/module architecture is the target owner, but these files remain unsafe to delete until installed Resolve and command-history references are checked.

## Generated and forensic material

- `_browser_evidence_REEL2_PHASE3_AUTHORITY_V2/` is generated evidence, not runtime source.
- `.pytest-tmp-*` and `.benchmark-inspect-*` are replaceable scratch directories.
- `keyframe_api_usage.txt`, `latest_accepted_usage.txt`, and `step_3B_6E_usage.txt` look generated; preserve until their producing task/report is identified.
- Reports are valuable, but historical report copies of source must never be importable production dependencies.

## Hard-coded legacy search

| Token | Finding |
| --- | --- |
| `DZatr0EJt4B` | Source occurrences are limited to two current tests; legitimate fresh-Reel fixture evidence. |
| `DcJRJtUKScu` | 48 source/test/report paths; generic builders replaced two hard-coded profile builders, while many Step/Phase scripts remain Reel-specific references. |
| `New Project 1` | 39 paths plus current command payload; environment-specific production configuration and a migration blocker. |
| `Step4`, `Step5`, `Phase4`, `Phase5`, `Phase6` | Concentrated in bounded historical/diagnostic families; not proof of staleness because command JSON may dynamically select them. |
| `_browser_evidence` | No runtime source reference found; one untracked generated directory exists. |
| `n8n` | 13 paths, mainly compatibility provenance/comments and archived adapters; current orchestration does not invoke n8n. |
| `113` | Raw search is noisy (78 files, mostly numeric data/fixtures). Each production constant needs contextual review; the token alone is not a deletion signal. |

## Dynamic execution findings

- `VC_Run_Agent_Task.py` dynamically loads the repository bridge from installed configuration.
- `VC_Agent_Bridge.py` validates and dynamically imports `command["module"]`; every queued/accepted module string is therefore a runtime dependency.
- Several versioned Resolve modules dynamically import predecessor versions. A `v1` file may be required by `v4`.
- Analysis and planning orchestrators use `subprocess.run` with fixed repository filenames.
- Additional legacy controllers and visual-repair modules use `importlib` and subprocess validators; these require family-level migration, not isolated deletion.

## Recommended Git baseline action

Create a non-destructive recovery snapshot commit that includes current source/test/doc/config state and tag it with an explicit non-acceptance name. Review and green regression happen on top of that preserved point; neither the snapshot commit nor its tag is an accepted/clean baseline.
