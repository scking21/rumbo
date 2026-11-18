#!/usr/bin/env python3
"""Stop hook: report when work the owner accepted is no longer accepted.

Silent unless the project has an engine ledger (.rumbo/state.sqlite3). Then it blocks once per
problem and at most 3 times per session on ACCEPTANCE_LOST: a task the owner accepted is no
longer accepted, because its bytes, dependencies or agreed definition changed, or new work
replaced it. Edits outside the contract are not blocked; in live sessions that blocked every
small requested fix and surfaced nothing new.

It reads the ledger read-only, never writes it, and always exits 0.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

MAX_BLOCKS = 3


def _load_core():
    # The plugin ships the engine beside this script's folder; load it by path so the
    # installed plugin's folder name does not matter.
    path = Path(__file__).resolve().parents[1] / 'core.py'
    spec = importlib.util.spec_from_file_location('rumbo_engine_core', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def problems(project, core):
    try:
        engine = core.Engine(project, 'stop-gate', 'viewer', read_only=True)
        state = engine.snapshot()
    except core.RumboError as error:
        if error.code == 'NO_CONTRACT':
            return []
        return [('unreadable', 'LEDGER_UNREADABLE: ' + error.message)]
    found = []
    for task in state['tasks']:
        accepted = [d for d in task['decisions'] if d['outcome'] == 'accepted']
        if accepted and task['status'] != 'accepted':
            why = task['stale_reason'] or ('new work replaced the accepted artifact' if task['status'] in ('produced', 'checks_passed') else task['status'])
            found.append(('lost:' + task['id'] + ':' + accepted[-1]['id'],
                          'ACCEPTANCE_LOST ' + task['id'] + ': the owner accepted this task, but it is now ' + task['status'] + ' (' + why + ')'))
    return found


def _marker(session_id):
    folder = Path(os.environ.get('RUMBO_STATE_DIR') or Path(tempfile.gettempdir()) / 'rumbo') / 'engine-gate'
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if folder.is_symlink() or not folder.is_dir() or folder.stat().st_uid != os.getuid():
            return None
    except OSError:
        return None
    return folder / hashlib.sha256(session_id.encode('utf-8', 'surrogatepass')).hexdigest()[:32]


def _read_marker(marker):
    try:
        data = json.loads(marker.read_text())
        if isinstance(data, int):
            return dict(count=data, reported=[])
        if isinstance(data, dict) and isinstance(data.get('count'), int) and isinstance(data.get('reported'), list):
            return data
    except (OSError, ValueError):
        pass
    return dict(count=0, reported=[])


def _write_marker(marker, data):
    try:
        if marker.is_symlink():
            return
        fd = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(json.dumps(data))
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    args = parser.parse_args(argv)
    try:
        hook = json.loads(sys.stdin.read() or '{}')
        if not isinstance(hook, dict):
            hook = {}
    except ValueError:
        hook = {}
    project = Path(args.project)
    if not (project / '.rumbo' / 'state.sqlite3').is_file():
        return 0
    try:
        found = problems(project, _load_core())
    except Exception as error:  # a broken gate must not trap the session
        found = [('error', 'GATE_ERROR: ' + type(error).__name__)]
    session_id = hook.get('session_id') if isinstance(hook.get('session_id'), str) else ''
    marker = _marker(session_id) if session_id else None
    if marker:
        # Each problem blocks once per session: the agent cannot clear a lost acceptance itself,
        # so repeating the same block only costs turns. A session gets at most MAX_BLOCKS blocks.
        seen = _read_marker(marker)
        found = [(key, text) for key, text in found if key not in seen['reported']]
        if not found or seen['count'] >= MAX_BLOCKS:
            return 0
        _write_marker(marker, dict(count=seen['count'] + 1, reported=seen['reported'] + [key for key, _ in found]))
    elif not found or hook.get('stop_hook_active'):
        return 0
    command = 'python3 -m rumbo --root "' + str(project) + '" state'
    reason = ('Rumbo ledger (.rumbo/state.sqlite3, read it with: ' + command + '): work the owner accepted is no longer accepted.\n- ' +
              '\n- '.join(text for _, text in found) +
              '\nTell the user in one line which accepted work is affected and that only the owner can accept it again. '
              'If your changes caused this, claim the task and register and check the work again, or ask the owner with request_decision. '
              'This gate reports each problem once per session.')
    print(json.dumps({'decision': 'block', 'reason': reason}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
