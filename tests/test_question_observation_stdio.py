"""Release regression: process-level guarded questions in the actual local plugin build."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rumbo.protocol import tool_definitions
from rumbo.installed import installed_tool_definitions
from scripts.package_release import build_local

ROOT = Path(__file__).resolve().parents[1]

class QuestionStdioTests(unittest.TestCase):
    def test_local_optional_catalog_does_not_advertise_unimplemented_remote_support(self):
        base = {t['name']:t for t in tool_definitions(oauth=True)}
        local = {t['name']:t for t in tool_definitions(oauth=True, question_observations=True)}
        self.assertEqual(set(base),set(local))
        for name in base:
            item=copy.deepcopy(local[name])
            schema=item['inputSchema']
            additions={'rumbo_state':('question_task_id','related_task_ids'),'rumbo_request_decision':('observation',)}.get(name,())
            for key in additions:
                self.assertNotIn(key,schema['required'])
                del schema['properties'][key]
            if name=='rumbo_state':
                self.assertEqual(schema.pop('dependentRequired'),{'related_task_ids':['question_task_id']})
            self.assertEqual(item,base[name])
        installed = {t['name'] for t in installed_tool_definitions()}
        self.assertNotIn('rumbo_submit_review',installed)

    def test_exact_packaged_stdio_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            zip_path, output = td/'local.zip', td/'report.json'
            digest = build_local(ROOT,zip_path)
            r = subprocess.run([sys.executable,'-I','-B','-S',str(ROOT/'scripts/verify_question_stdio.py'),
                                str(zip_path),str(output)],cwd=td,text=True,capture_output=True,timeout=30)
            self.assertEqual(r.returncode,0,r.stderr)
            report=json.loads(output.read_text())
            self.assertEqual(report['archive_sha256'],digest)
            self.assertEqual(len(report['cases']),7)
            self.assertEqual(report['adapter'],'0.3.8')
            self.assertEqual(report['server']['version'],'0.3.6')
