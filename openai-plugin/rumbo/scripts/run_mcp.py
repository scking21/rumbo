#!/usr/bin/env python3
"""Local plugin launcher; the operator explicitly selects the trusted project."""
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rumbo.core import Engine, RumboError
from rumbo.protocol import serve_stdio

root=os.environ.get('RUMBO_PROJECT_ROOT')
if not root:
    print('RUMBO_PROJECT_ROOT must be set by the local host to an existing approved project. No project is selected automatically.',file=sys.stderr)
    raise SystemExit(2)
try:
    serve_stdio(Engine(root,os.environ.get('RUMBO_ACTOR','local-worker'),os.environ.get('RUMBO_ROLE','worker')))
except (RumboError,ValueError,OSError) as e:
    print(str(e),file=sys.stderr)
    raise SystemExit(2)
