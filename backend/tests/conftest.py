"""Pytest config — adds project root to sys.path so 'backend.' imports work."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
