#!/usr/bin/env python3
"""Build/install a wheel offline and verify it without importing the checkout.

Install setuptools>=68 and wheel before running. The build and the fresh
standard-library-only test environment never resolve dependencies from indexes.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv

ROOT = Path(__file__).resolve().parents[1]
TEST_FILES = ('test_core.py', 'test_protocol.py', 'test_demo.py',
              'test_backup.py', 'test_installed.py')
# These two tests need source packaging inputs and run in the normal full suite.
# The other installed/registry cases exercise the installed wheel here.
SOURCE_ONLY_TESTS = {
    'test_packaged_launcher_ignores_legacy_environment_and_has_unique_actor_after_restart',
    'test_packaged_launcher_requires_plugin_data_even_with_legacy_environment',
}


def isolated_environment(environment):
    result = dict(environment)
    for name in ('PYTHONPATH', 'PYTHONHOME'):
        result.pop(name, None)
    result.update(PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    return result


def validate_import_paths(source_root, install_prefix, paths):
    source_root = Path(source_root).resolve()
    install_prefix = Path(install_prefix).resolve()
    for name, value in paths.items():
        path = Path(value).resolve()
        if path == source_root or source_root in path.parents:
            raise ValueError(name+' imported from source checkout instead of isolated wheel')
        if install_prefix not in path.parents:
            raise ValueError(name+' did not import from the isolated wheel environment')


def installed_checks(tests):
    """Invoked only by the fresh venv, with isolated (-I) Python startup."""
    modules = {name: importlib.import_module(name) for name in
               ('rumbo', 'rumbo.core', 'rumbo.protocol', 'rumbo.registry', 'rumbo.installed')}
    paths = {name: module.__file__ for name, module in modules.items()}
    validate_import_paths(ROOT, sys.prefix, paths)
    entrypoint = Path(sys.executable).with_name('rumbo')
    help_result = subprocess.run([str(entrypoint), '--help'], check=True,
                                 capture_output=True, text=True, timeout=10)
    if 'Rumbo local contract and evidence referee' not in help_result.stdout:
        raise ValueError('Installed rumbo console entrypoint did not provide its CLI')
    board = Path(paths['rumbo']).parent/'web/board.html'
    if board.read_bytes() != (ROOT/'rumbo/web/board.html').read_bytes():
        raise ValueError('Installed wheel board differs from the canonical resource')
    sys.path.insert(0, str(tests))
    suite = unittest.defaultTestLoader.discover(str(tests))

    def flatten(items):
        for item in items:
            if isinstance(item, unittest.TestSuite):
                yield from flatten(item)
            else:
                yield item

    cases = list(flatten(suite))
    excluded = {case._testMethodName for case in cases if case._testMethodName in SOURCE_ONLY_TESTS}
    if excluded != SOURCE_ONLY_TESTS:
        raise ValueError('Expected source-only packaging tests were not discovered')
    selected = [case for case in cases if case._testMethodName not in SOURCE_ONLY_TESTS]
    expected_modules = {Path(name).stem for name in TEST_FILES}
    if {case.__class__.__module__ for case in selected} != expected_modules:
        raise ValueError('An installed-wheel test module was not discovered')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    report = dict(installed_tests=result.testsRun, failures=len(result.failures),
                  errors=len(result.errors), skipped=len(result.skipped),
                  excluded_source_packaging_tests=len(excluded),
                  imported_modules=paths, console_entrypoint=str(entrypoint),
                  python=sys.version.split()[0])
    print(json.dumps(report), flush=True)
    return 0 if result.wasSuccessful() and not result.skipped else 1


def verify(wheel=None):
    env = isolated_environment(os.environ)
    with tempfile.TemporaryDirectory(prefix='rumbo-wheel-verification-') as tmp:
        workspace = Path(tmp).resolve()
        if wheel is None:
            destination = workspace/'wheels'
            subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-index',
                '--no-deps', '--no-build-isolation', '--wheel-dir', str(destination), str(ROOT)],
                check=True, env=env, cwd=workspace, timeout=120)
            wheels = list(destination.glob('rumbo_referee-*.whl'))
            if len(wheels) != 1:
                raise ValueError('Expected exactly one Rumbo wheel')
            wheel = wheels[0]
        else:
            wheel = Path(wheel).resolve(strict=True)
        environment = workspace/'venv'
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
        python = environment/'bin/python'
        subprocess.run([str(python), '-I', '-m', 'pip', 'install', '--no-index',
            '--no-deps', str(wheel)], check=True, env=env, cwd=workspace, timeout=60)
        tests = workspace/'tests'
        tests.mkdir()
        for name in TEST_FILES:
            shutil.copyfile(ROOT/'tests'/name, tests/name)
        return subprocess.run([str(python), '-I', str(Path(__file__).resolve()),
            '--installed-check', str(tests)], env=env, cwd=workspace, timeout=240).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, help='Verify an existing wheel instead of building one')
    parser.add_argument('--installed-check', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.installed_check:
            return installed_checks(args.installed_check)
        return verify(args.wheel)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Installed wheel verification failed: '+str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
