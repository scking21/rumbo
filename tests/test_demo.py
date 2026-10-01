from pathlib import Path
import tempfile
import unittest
from rumbo.demo import create_demo
from rumbo.core import RumboError

class DemoTests(unittest.TestCase):
    def test_reproducible_synthetic_states_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            a=create_demo(one); b=create_demo(two)
            self.assertEqual(a,b)
            self.assertTrue(a['demo'])
            self.assertEqual({t['status'] for t in a['tasks']},{'accepted','produced','checks_passed','stale','unclaimed','blocked'})
            with self.assertRaisesRegex(RumboError,'CONTRACT_EXISTS'):
                create_demo(one)
            self.assertEqual((Path(one)/'sample.csv').read_text(),'name,amount\nSynthetic Ada,12\n')
    def test_existing_artifact_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'sample.csv';path.write_text('real user data')
            with self.assertRaisesRegex(RumboError,'DEMO_NOT_EMPTY'):
                create_demo(root)
            self.assertEqual(path.read_text(),'real user data')
