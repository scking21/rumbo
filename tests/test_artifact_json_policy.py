"""Canonical artifact-only JSON limits, independent of transport limits."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from rumbo.core import Engine

class ArtifactJSONPolicyTests(unittest.TestCase):
    def outcome(self,content):
        with tempfile.TemporaryDirectory() as root:
            owner=Engine(root,'owner','human',clock=lambda:1000)
            worker=Engine(root,'maker','worker',clock=lambda:1000)
            owner.execute('create_contract',dict(project_id='policy',goal='Bounded',original_request='Check ok',decision_owner='owner',constraints=[],tasks=[dict(id='one',title='One',dependencies=[],acceptance=[dict(id='json',kind='json_equals',key='ok',value=True)])]))
            worker.execute('claim_task',dict(task_id='one',contract_revision=1,lease_seconds=300))
            worker.execute('ingest_artifact',dict(task_id='one',contract_revision=1,filename='out.json',content=content))
            state=worker.execute('run_checks',dict(task_id='one',contract_revision=1,artifact_revision=1))
            return state['tasks'][0]['evidence'][-1]['outcome']

    def test_depth_512_including_root_is_supported_and_513_fails(self):
        for depth in [65,511,512,513,990]:
            with self.subTest(depth=depth):
                content='{"ok":true,"unused":'+'['*(depth-1)+'0'+']'*(depth-1)+'}'
                self.assertEqual(self.outcome(content),'pass' if depth<=512 else 'fail')

    def test_explicit_integer_limit_ignores_interpreter_conversion_configuration(self):
        configurable=hasattr(sys,'set_int_max_str_digits')
        prior=sys.get_int_max_str_digits() if configurable else None
        try:
            for configured in ([640,4300,0] if configurable else [None]):
                if configurable:sys.set_int_max_str_digits(configured)
                for digits in [4299,4300,4301]:
                    with self.subTest(configured=configured,digits=digits):
                        content='{"ok":true,"unused":'+'9'*digits+'}'
                        self.assertEqual(self.outcome(content),'pass' if digits<=4300 else 'fail')
        finally:
            if configurable:sys.set_int_max_str_digits(prior)

    def test_bracket_characters_in_escaped_strings_are_not_nesting(self):
        self.assertEqual(self.outcome(json.dumps(dict(ok=True,unused='["\\'*1000))),'pass')

    def test_existing_duplicate_and_unused_nonfinite_behavior_is_preserved(self):
        for value in ['NaN','Infinity','-Infinity','1e999','9'*4301+'.0','9'*4301+'e0']:
            with self.subTest(value=value[:30]):self.assertEqual(self.outcome('{"ok":true,"unused":'+value+'}'),'pass')
        self.assertEqual(self.outcome('{"ok":false,"ok":true}'),'pass')
        self.assertEqual(self.outcome('{"ok":true,"ok":false}'),'fail')

    def test_raw_byte_encoding_detection_is_preserved(self):
        from rumbo.core import artifact_json
        text='{"ok":true,"😀":"é"}'
        for encoding in ['utf-8','utf-8-sig','utf-16','utf-16-le','utf-16-be','utf-32','utf-32-le','utf-32-be']:
            with self.subTest(encoding=encoding):self.assertEqual(artifact_json(text.encode(encoding)),json.loads(text))

    def test_historical_evidence_remains_until_explicit_recheck(self):
        import hashlib
        from rumbo.core import canonical
        for content in ['{"ok":true,"unused":'+'['*512+'0'+']'*512+'}', '{"ok":true,"unused":"'+chr(92)+'ud800"}']:
            with tempfile.TemporaryDirectory() as root:
                owner=Engine(root,'owner','human',clock=lambda:1000)
                owner.execute('create_contract',dict(project_id='legacy',goal='Bounded',original_request='Check ok',decision_owner='owner',constraints=[],tasks=[dict(id='one',title='One',dependencies=[],acceptance=[dict(id='json',kind='json_equals',key='ok',value=True)])]))
                owner.execute('claim_task',dict(task_id='one',contract_revision=1,lease_seconds=300))
                owner.execute('ingest_artifact',dict(task_id='one',contract_revision=1,filename='out.json',content=content))
                owner.execute('run_checks',dict(task_id='one',contract_revision=1,artifact_revision=1))
                with owner._db() as db:
                    raw,previous=db.execute('SELECT payload,previous FROM events WHERE seq=4').fetchone()
                    event=json.loads(raw);event['data']['evidence'][0]['outcome']='pass';raw=canonical(event)
                    db.execute('UPDATE events SET payload=?,digest=? WHERE seq=4',(raw,hashlib.sha256((previous+'\n'+raw).encode()).hexdigest()))
                self.assertEqual(owner.snapshot()['tasks'][0]['status'],'checks_passed')
                accepted=owner.execute('decide',dict(task_id='one',contract_revision=1,artifact_revision=1,outcome='accepted',reason='Historical receipt'))
                self.assertEqual(accepted['tasks'][0]['status'],'accepted')
                checked=owner.execute('run_checks',dict(task_id='one',contract_revision=1,artifact_revision=1))
                self.assertEqual(checked['tasks'][0]['evidence'][0]['outcome'],'pass')
                self.assertEqual(checked['tasks'][0]['evidence'][-1]['outcome'],'fail')
                self.assertEqual(checked['tasks'][0]['status'],'produced')

    def test_scalar_strings_include_discarded_duplicate_values_and_keys(self):
        slash=chr(92)
        for literal in [slash+'ud800',slash+'udfff']:
            for content in ['{"ok":true,"unused":"'+literal+'"}', '{"ok":true,"'+literal+'":0}', '{"ok":true,"unused":"'+literal+'","unused":0}', '{"ok":true,"unused":["'+literal+'"],"unused":0}', '{"ok":true,"unused":{"'+literal+'":0},"unused":0}']:
                with self.subTest(content=content):self.assertEqual(self.outcome(content),'fail')
        self.assertEqual(self.outcome('{"ok":true,"unused":"'+slash+'ud83d'+slash+'ude00"}'),'pass')
        self.assertEqual(self.outcome('{"ok":true,"unused":"😀"}'),'pass')

    def test_strict_scalar_byte_decoding_preserves_valid_non_bmp(self):
        from rumbo.core import artifact_json
        for encoding in ['utf-8','utf-8-sig','utf-16','utf-16-le','utf-16-be','utf-32','utf-32-le','utf-32-be']:
            with self.subTest(encoding=encoding):self.assertEqual(artifact_json('{"😀":true}'.encode(encoding)),{'😀':True})
            for point in [0xd800,0xdbff,0xdc00,0xdfff]:
                with self.subTest(encoding=encoding,point=point),self.assertRaises((ValueError,UnicodeError)):
                    artifact_json(('{"ok":true,"unused":"'+chr(point)+'"}').encode(encoding,'surrogatepass'))
        for encoding in ['utf-32-le','utf-32-be']:
            with self.subTest(encoding=encoding),self.assertRaises((ValueError,UnicodeError)):
                artifact_json(('{"ok":true,"unused":"'+chr(0xd800)+chr(0xdc00)+'"}').encode(encoding,'surrogatepass'))
