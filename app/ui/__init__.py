"""Qt widgets for the picker window."""

from pathlib import Path

# Anchored on this package, not the entry script: in the frozen build main.py
# runs as a top-level script, so its own __file__ points elsewhere.
UI_DIR = Path(__file__).resolve().parent
