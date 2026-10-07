"""Compatibility wrapper for the canonical offline FCPXML compiler.

Removal gate: migrate all historical import and CLI callers to
``video_cloner.resolve.fcpxml`` or the unified CLI.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from video_cloner.resolve import fcpxml as _implementation
globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})
if __name__ != "__main__": sys.modules[__name__] = _implementation
if __name__ == "__main__": raise SystemExit(_implementation.main())
