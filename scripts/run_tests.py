#!/usr/bin/env python3
"""Run the new suite; CI may require every optional/browser test to execute."""
import argparse
from pathlib import Path
import sys
import unittest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--strict',action='store_true',help='Fail if any test skips or no board browser tests are discovered')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    suite=unittest.defaultTestLoader.discover(str(root/'tests'))
    def flatten(suite):
        for item in suite:
            if isinstance(item,unittest.TestSuite):yield from flatten(item)
            else:yield item
    browser_count=sum('BoardBrowserTests.' in test.id() for test in flatten(suite))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if args.strict and (result.skipped or browser_count<5):
        print('STRICT QA FAILED: all tests, including at least five browser cases, must execute without skips.',file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
