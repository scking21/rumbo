import hashlib
import unittest
from unittest.mock import patch

from rumbo.core import RumboError
from pathlib import Path
import tempfile

from rumbo.core import Engine


class UploadPreconditionTests(unittest.TestCase):
    def test_rejected_upload_preserves_ledger_and_blob_store(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        owner = Engine(root, 'owner', 'human')
        worker = Engine(root, 'maker', 'worker')
        owner.execute('create_contract', dict(project_id='case', decision_owner='owner',
            goal='Register exact CSV', original_request='Check my CSV', constraints=[],
            tasks=[dict(id='export', title='Export', dependencies=[],
                        acceptance=[dict(id='tag', kind='file_contains', value='name')])]))
        worker.execute('claim_task', dict(task_id='export', contract_revision=1, lease_seconds=120))
        body = 'name,amount\r\n'
        digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
        args = dict(task_id='export', contract_revision=1, filename='output.csv',
                    content=body.rstrip(), expected_sha256=digest, expected_artifact_revision=0)
        before = worker.snapshot()['ledger_head']
        with patch.object(worker, '_store_upload', wraps=worker._store_upload) as store:
            with self.assertRaisesRegex(RumboError, 'REVIEWED_BYTES_CHANGED'):
                worker.execute('ingest_artifact', args)
            store.assert_not_called()
            self.assertEqual(before, worker.snapshot()['ledger_head'])
            accepted = worker.execute('ingest_artifact', dict(args, content=body))
            self.assertEqual(accepted['tasks'][0]['artifact']['sha256'], digest)
            with self.assertRaisesRegex(RumboError, 'STALE_REGISTRATION'):
                worker.execute('ingest_artifact', dict(args, content=body))
            self.assertEqual(store.call_count, 1)
            self.assertEqual(accepted['ledger_head'], worker.snapshot()['ledger_head'])
