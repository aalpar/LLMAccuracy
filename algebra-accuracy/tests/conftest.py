"""Pytest fixtures shared across harness tests."""
import sys
from pathlib import Path

# Make algebra-accuracy/ importable as a package root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
