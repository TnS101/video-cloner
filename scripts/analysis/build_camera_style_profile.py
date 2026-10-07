"""Compatibility wrapper; remove after profile callers use the package module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from video_cloner.camera import *  # noqa: F401,F403
from video_cloner.camera import main
if __name__ == "__main__": raise SystemExit(main())
