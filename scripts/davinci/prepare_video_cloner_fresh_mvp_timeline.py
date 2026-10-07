"""Compatibility wrapper for canonical offline queue publication.

Removal gate: migrate operator callers to ``video-cloner publish``.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from video_cloner.resolve import queue as _implementation
globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})
sys.modules[__name__] = _implementation
if __name__ == "__main__": raise SystemExit(_implementation.main())
