"""The whole suite in one unittest run: every test_*.py in this folder. Exit status 0 only when all pass."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py", top_level_dir=str(HERE))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
