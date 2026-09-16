#!/usr/bin/env python3
from pathlib import Path
import sys

LIB_ROOT = Path(__file__).resolve().parents[3]
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))

from jot_core.timelog_hook import main


if __name__ == "__main__":
    raise SystemExit(main())
