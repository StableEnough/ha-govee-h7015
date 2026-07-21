"""Pytest configuration — ensures custom_components is importable."""

from __future__ import annotations

import sys
from pathlib import Path

# The project root must be on sys.path for `import custom_components` to work.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "standalone"))


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "asyncio: async test")
