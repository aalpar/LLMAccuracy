"""Pytest fixtures shared across capability-map generator tests."""
import sys
from pathlib import Path

# Make generate_capability_problems importable under its module name.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# And algebra-accuracy for the imported Problem dataclass.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "algebra-accuracy"),
)
