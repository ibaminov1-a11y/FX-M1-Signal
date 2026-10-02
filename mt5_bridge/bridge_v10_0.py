"""Stable launcher, with bundled pure-Python HTTP dependencies."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent/'_vendor'))
from event_core.server import main
if __name__=='__main__':main()
