#!/usr/bin/env python3
"""Installed worker-only launcher; project aliases are owner-provisioned."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rumbo.installed import main

if __name__ == '__main__':
    raise SystemExit(main())
