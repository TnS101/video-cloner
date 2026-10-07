"""Compatibility wrapper; remove after caption callers use the package module."""
import sys
from video_cloner.captions import fcpxml as _implementation
globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})
sys.modules[__name__] = _implementation
