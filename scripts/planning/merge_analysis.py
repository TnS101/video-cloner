"""Compatibility wrapper; remove after planning callers use the package module."""
import sys
from pathlib import Path
from runpy import run_module
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if __name__ == "__main__": run_module("video_cloner.planning.merge", run_name="__main__")
else:
    from video_cloner.planning.merge import *  # noqa: F401,F403
