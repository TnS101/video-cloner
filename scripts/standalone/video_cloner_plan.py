"""Compatibility CLI for canonical planning; remove after callers use the unified CLI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from video_cloner.planning.pipeline import *  # noqa: F401,F403
from video_cloner.planning.pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
