# Video Cloner

Video Cloner analyzes a reference video and extracts the editing/style intelligence needed to reproduce its core behavior as an editable clone.

## Current MVP status

Reel #3 is the active production proof.

Accepted now:
- cuts + audio;
- captions with animated V3 replacements and static V2 fallback;
- native Resolve Blur Dissolve transitions.

Current work:
- core motion/VFX;
- then speed/retiming;
- then integrated Reel review and generalization.

The future Auto Editing project is a separate application layer that can consume Video Cloner's analysis/recipes and combine them with rough-cut/caption/editing systems.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

## Main command

```powershell
video-cloner run `
  --project-root . `
  --local-video .\input\source.mp4 `
  --project VideoCloner `
  --target-timeline VIDEO_CLONER_SOURCE_MVP_V1
```

Use `video-cloner run-offline` when Resolve publication is not wanted.

## Development rule

See `AGENTS.md`.

The default is direct product implementation. Do not create architecture/process/validation/test infrastructure unless the user explicitly requests it or the feature literally cannot work without it.
