"""Deja el paquete wowalerts importable desde los tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
