"""Compatibility CLI for ``video_cloner.analysis.pipeline``.

Removal gate: migrate module and operator callers to ``video-cloner analyze``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from video_cloner.analysis.pipeline import *  # noqa: F401,F403
from video_cloner.analysis.pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
