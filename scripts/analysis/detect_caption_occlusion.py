"""Compatibility wrapper; remove after all analyzer callers use the package module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == "__main__":
    from runpy import run_module

    run_module("video_cloner.analysis.caption_occlusion", run_name="__main__")
else:
    from video_cloner.analysis import caption_occlusion as _implementation

    globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})
