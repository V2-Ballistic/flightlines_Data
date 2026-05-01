#!/usr/bin/env python3
"""
scripts/flightlines_fetch.py — convenience wrapper around python -m fetcher.

Run from the repository root:
    python scripts/flightlines_fetch.py [options]

All options are forwarded to fetcher.cli.main().  Run with --help for details.
"""

import sys
from pathlib import Path

# Ensure the repo root is on sys.path so the fetcher package is importable
# regardless of how this script is invoked.
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from fetcher.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
