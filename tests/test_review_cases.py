"""Package review cases must describe the distribution's actual tool authority.

These structural/backend checks are not completed model or native-host review cases.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from rumbo.installed import InstalledProtocol
from rumbo.protocol import tool_definitions
from scripts.package_release import GATES, build_local, build_submission

ROOT=Path(__file__).resolve().parents[1]

def cases_from_zip(path):
    with zipfile.ZipFile(path) as archive:
        manifest=json.loads(archive.read('rumbo/plugin.json'))
    return manifest['extensions']['com.openai']['review']['test_cases']

def expected_tools(case):
    return {name.strip() for name in case['tools_triggered'].split(',')}

class DistributionReviewCasesTests(unittest.TestCase):
    def test_local_cases_start_with_real_installed_discovery_and_binding(self):
        # Regresses if local packaging again embeds the generic remote cases.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); target=root/'local.zip'; build_local(ROOT,target)
            cases=cases_from_zip(target)
            self.assertEqual(expected_tools(cases['positive'][0]),
                             {'rumbo_list_projects','rumbo_connect_project','rumbo_state'})
            self.assertIn('worker',cases['positive'][0]['expected_behavior'].lower())
            with zipfile.ZipFile(target) as archive:archive.extractall(root/'extracted')
            data=root/'plugin-data';data.mkdir(mode=0o700)
            request=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'})+'\n'
            response=subprocess.run([sys.executable,str(root/'extracted/rumbo/scripts/run_mcp.py')],
                input=request,text=True,capture_output=True,env=dict(os.environ,PLUGIN_DATA=str(data)))
            self.assertEqual(response.returncode,0,response.stderr)
            available={tool['name'] for tool in json.loads(response.stdout)['result']['tools']}
            self.assertNotIn('rumbo_submit_review',available)
            for case in cases['positive']:
                self.assertLessEqual(expected_tools(case),available,case['description'])
            self.assertNotIn('owner portal',json.dumps(cases).lower())
            self.assertIn('worker-only',cases['negative'][1]['description'].lower())

    def test_submission_cases_are_hosted_and_do_not_require_installed_tools(self):
        config={key:'https://rumbo.company.dev/'+key for key in ('website_url','support_url','privacy_url','terms_url','video_url')}
        config.update(mcp_url='https://rumbo.company.dev/mcp',attestations={key:True for key in GATES})
        # In-memory packaging fixture only. No real endpoint or gate is attested.
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'submission.zip';build_submission(ROOT,target,config)
            cases=cases_from_zip(target)
            self.assertTrue((ROOT/'docs/reviewer-cases-hosted.json').is_file(), 'Hosted cases need a separate source file')
            self.assertEqual(cases,json.loads((ROOT/'docs/reviewer-cases-hosted.json').read_text()))
            available={tool['name'] for tool in tool_definitions(oauth=True)}
            self.assertEqual(expected_tools(cases['positive'][0]),{'open_project_board'})
            for case in cases['positive']:
                self.assertLessEqual(expected_tools(case),available,case['description'])
            text=json.dumps(cases).lower()
            self.assertNotIn('rumbo_connect_project',text)
            self.assertNotIn('rumbo_list_projects',text)
            self.assertIn('server-mapped',text)

    def test_local_negative_case_cannot_gain_reviewer_or_human_authority(self):
        # Exercise real dispatcher rejection, not just presence of safety wording.
        with tempfile.TemporaryDirectory() as tmp:
            protocol=InstalledProtocol(Path(tmp).resolve())
            listed=protocol.dispatch({'jsonrpc':'2.0','id':1,'method':'tools/list'})
            names={tool['name'] for tool in listed['result']['tools']}
            for name in ('rumbo_submit_review','rumbo_decide','rumbo_create_contract','rumbo_revise_contract'):
                self.assertNotIn(name,names)
                result=protocol.dispatch({'jsonrpc':'2.0','id':2,'method':'tools/call',
                    'params':{'name':name,'arguments':{'actor':'human','role':'human'}}})
                self.assertEqual(result['error']['code'],-32602)
            result=protocol.dispatch({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{
                'name':'rumbo_connect_project','arguments':{'alias':'review-demo','role':'human'}}})
            self.assertTrue(result['result']['isError'])
            self.assertIsNone(protocol.alias)
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_review_case_files_are_scenarios_not_observed_evidence(self):
        for name in ('reviewer-cases-local.json','reviewer-cases-hosted.json'):
            self.assertTrue((ROOT/'docs'/name).is_file(), 'Missing distribution-specific case file: '+name)
            cases=json.loads((ROOT/'docs'/name).read_text())
            self.assertEqual(set(cases),{'positive','negative'})
            self.assertIn('name,amount\nDemo,5\n',cases['positive'][3]['expected_behavior'])
            self.assertEqual(len(cases['positive']),5)
            self.assertEqual(len(cases['negative']),3)
            for case in cases['positive']:
                self.assertEqual(set(case),{'description','prompt','tools_triggered','expected_behavior'})
                self.assertTrue(all(isinstance(value,str) and value.strip() for value in case.values()))
            for case in cases['negative']:
                self.assertEqual(set(case),{'description','prompt'})
                self.assertTrue(all(isinstance(value,str) and value.strip() for value in case.values()))
            self.assertNotIn('observed_result',json.dumps(cases))
