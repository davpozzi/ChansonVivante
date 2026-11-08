"""Historical entry point kept as a compatibility shim.

The application implementation lives in the current root entry point. Keeping
this module as a delegating wrapper prevents archived launch paths from
silently retaining an obsolete Flet API.
"""
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import flet as ft

from ChansonVivante import main


if __name__ == "__main__":
    ft.run(main)
