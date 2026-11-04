#!/usr/bin/env python3
"""Explicit Codex-local record operations. No host hooks or session discovery."""
import argparse
import importlib.util
import io
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'validate', 'check', 'show'):
        sub = subs.add_parser(name, allow_abbrev=False)
        sub.add_argument('--record', required=True, help='Explicit authorized project record path')
        if name == 'init':
            sub.add_argument('--objective', required=True)
            sub.add_argument('--quote', required=True, help='Exact user quote; use - for stdin')
        elif name == 'show':
            sub.add_argument('--max-chars', type=int, default=1500)
    args = parser.parse_args(argv)
    # Resolve this distribution, not cwd, PATH, an environment variable or a session.
    script = Path(__file__).resolve()
    runtime = script.with_name('_commitments_record.py')
    if runtime.is_symlink() or not runtime.is_file():
        parser.error('Bundled commitments runtime is missing; restore the reviewed package')
    spec = importlib.util.spec_from_file_location('rumbo_commitments_runtime', runtime)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if args.command == 'check':
        args.transcript = None  # This adapter never reads host/session transcripts.
    if args.command == 'show':
        # Canonical show also accepts Claude hook JSON. Explicit Codex show must
        # neither consume a live input pipe nor create hook/session markers.
        previous_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO('')
            return module.cmd_show(args)
        finally:
            sys.stdin = previous_stdin
    return getattr(module, 'cmd_'+args.command)(args)


if __name__ == '__main__':
    raise SystemExit(main())
