"""Entry point retained for the user's existing launcher. EventCore only, no V10 engine."""
from pathlib import Path
import sys
vendor=Path(__file__).with_name('_vendor')
if vendor.is_dir():sys.path.insert(0,str(vendor))
from event_core.server import main
if __name__=='__main__': main()
