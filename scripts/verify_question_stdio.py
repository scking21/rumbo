"""Independently launch the supplied local ZIP's actual stdio process; never install or contact a service."""
import argparse, copy, hashlib, json, os, select, sqlite3, subprocess, sys, tempfile, zipfile
from pathlib import Path

def run(archive, destination):
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); alias='notebook'; project=root/'project'; project.mkdir()
        data=root/'private-plugin-data'; data.mkdir(mode=0o700)
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            z.extractall(root/'unpacked')
        plugin=root/'unpacked/rumbo'
        sys.path.insert(0,str(plugin))
        from rumbo.core import Engine
        from rumbo.registry import register_project
        assert Path(sys.modules['rumbo.core'].__file__).resolve()==plugin/'rumbo/core.py'
        manifest=json.loads((plugin/'mcp.json').read_text())['mcpServers']['rumbo']
        assert manifest['type']=='stdio' and manifest['cwd']=='${PLUGIN_ROOT}' and manifest['command']=='python3'
        argv=[v.replace('${PLUGIN_ROOT}',str(plugin)) for v in manifest['args']]
        portable=json.loads((plugin/'plugin.json').read_text())
        codex=json.loads((plugin/'.codex-plugin/plugin.json').read_text())
        assert portable['version']==codex['version']=='0.3.8'
        def task(id):
            return dict(id=id,title='Heading for '+id,acceptance=[dict(id='text',kind='file_contains',value='notes')],dependencies=[])
        contract=dict(project_id='notebook',goal='Prepare notes',original_request='Draft the two headings.',
                      decision_owner='editor',revision_scope='task',constraints=[],tasks=[task('outline'),task('index')])
        owner=Engine(project,'editor','human'); owner.execute('create_contract',contract)
        register_project(data, alias, project)
        env=dict(os.environ,PLUGIN_DATA=str(data)); env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
        process=subprocess.Popen([sys.executable,'-I','-B','-S',*argv],cwd=plugin,env=env,
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        transcript=[]; rows=[]; counter=0
        def rpc(method, params):
            nonlocal counter
            counter+=1; obj=dict(jsonrpc='2.0',id=counter,method=method,params=params)
            process.stdin.write(json.dumps(obj)+'\n');process.stdin.flush()
            if not select.select([process.stdout],[],[],10)[0]: raise TimeoutError('Missing stdio response')
            res=json.loads(process.stdout.readline())
            assert res['id']==counter; transcript.append(dict(request=obj,response=res)); return res
        def call(name,**args): return rpc('tools/call',dict(name=name,arguments=args))
        def value(name,**args):
            result=call(name,**args)['result']
            assert not result['isError'],result
            return result['structuredContent']
        def raw():
            with sqlite3.connect(owner.db_path.as_uri()+'?mode=ro', uri=True) as db:
                assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
                return [dict(seq=n,payload=json.loads(p),digest=h) for n,p,h in db.execute('SELECT seq,payload,digest FROM events ORDER BY seq')]
        def revise(idx,title):
            contract['tasks'][idx]['title']=title
            owner.execute('revise_contract',dict(contract=copy.deepcopy(contract),expected_revision=owner.snapshot()['contract_revision'],reason='Edit heading'))
        def question(case,text,obs,expected,receipt=False):
            before=raw()
            args={'task_id':'outline','question':text}
            if obs is not None: args['observation']=obs
            if receipt: args['response_mode']='receipt'
            response=call('rumbo_request_decision',**args)['result']; after=raw()
            assert before==after[:len(before)]
            delta=after[len(before):]
            if expected=='STALE_QUESTION':
                assert not delta and response['isError'] and response['structuredContent']==dict(code='STALE_QUESTION',recovery=dict(tool='rumbo_state',arguments={'question_task_id':'outline'}))
                assert 'STALE_QUESTION:' in response['content'][0]['text']
            else:
                assert not response['isError'] and len(delta)==1
                event=delta[0]['payload']; d=event['data']; assert event['action']=='request_decision'
                assert d['question']==text and d['contract_revision']==owner.snapshot()['contract_revision']
                assert (d['observation']==obs if obs is not None else 'observation' not in d)
                if receipt: assert response['structuredContent']['kind']=='rumbo.mutation_receipt.v1'
            assert Engine(project,'observer','viewer',read_only=True,create=False).checkpoint()['ledger_head']==after[-1]['digest']
            rows.append(dict(case=case,expected=expected,event_delta=delta,head_before=before[-1]['digest'],head_after=after[-1]['digest']))
        try:
            info=rpc('initialize',dict(protocolVersion='2025-11-25',capabilities={},clientInfo=dict(name='disposable-package-probe',version='1')))['result']
            assert info['serverInfo']['version']=='0.3.6'
            process.stdin.write(json.dumps(dict(jsonrpc='2.0',method='notifications/initialized'))+'\n');process.stdin.flush()
            tools=rpc('tools/list',{})['result']['tools']; schemas={t['name']:t['inputSchema'] for t in tools}
            assert 'rumbo_submit_review' not in schemas
            assert not any(n in schemas for n in ['rumbo_decide','rumbo_revise_contract','rumbo_create_contract'])
            assert schemas['rumbo_state']['required']==[]
            assert {'question_task_id','related_task_ids'} == set(schemas['rumbo_state']['properties'])
            assert set(schemas['rumbo_request_decision']['required']) == {'task_id','question'}
            assert 'observation' in schemas['rumbo_request_decision']['properties']
            assert 'PROJECT_UNBOUND' in call('rumbo_state',question_task_id='outline')['result']['content'][0]['text']
            projects=value('rumbo_list_projects')['projects']; assert any(x['alias']==alias for x in projects)
            bound=value('rumbo_connect_project',alias=alias); assert bound['role']=='worker'
            assert 'PROJECT_ALREADY_BOUND' in call('rumbo_connect_project',alias=alias)['result']['content'][0]['text']
            assert call('rumbo_submit_review')['error']['message']=='Unknown tool'
            state=value('rumbo_state'); assert not {'question_observation','owner_review_url'} & set(state)
            assert state==owner.snapshot()
            head=raw()
            assert call('rumbo_state',related_task_ids=['index'])['result']['isError']
            assert call('rumbo_state',question_task_id='outline',related_task_ids=None)['result']['isError']
            assert call('rumbo_state',question_task_id='outline',role='human')['result']['isError']
            assert head==raw()
            question('legacy ordinary request','Review headings?',None,'OK')
            obs=value('rumbo_state',question_task_id='outline')['question_observation']
            question('conservative unchanged','Review outline?',obs,'OK')
            s=value('rumbo_state',question_task_id='outline')
            q='Use '+s['tasks'][1]['title']+'?'; revise(1,'New index')
            question('undeclared cross-reference defaults conservative',q,s['question_observation'],'STALE_QUESTION')
            s=value('rumbo_state',question_task_id='outline',related_task_ids=['index'])
            q='Use '+s['tasks'][1]['title']+'?'; revise(1,'Another index')
            question('declared sibling reference',q,s['question_observation'],'STALE_QUESTION')
            s=value('rumbo_state',question_task_id='outline',related_task_ids=[])
            q='Use '+s['tasks'][0]['title']+'?'; revise(1,'Independent heading')
            question('declared target tolerates disjoint revision + receipt',q,s['question_observation'],'OK',True)
            revise(0,'Rewritten outline')
            question('stale target holds old question',q,s['question_observation'],'STALE_QUESTION')
            s=value('rumbo_state',question_task_id='outline')
            question('reread and recompose', 'Keep '+s['tasks'][0]['title']+'?',s['question_observation'],'OK')
            assert not any(t['decisions'] for t in value('rumbo_state')['tasks'])
        finally:
            process.stdin.close()
            if process.wait(timeout=5)!=0: raise RuntimeError(process.stderr.read())
        destination.write_text(json.dumps(dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            adapter=portable['version'],server=info['serverInfo'],tool_count=len(tools),cases=rows,
            method='actual unpacked isolated stdio process with temporary owner-provisioned registry; no live host or install',
            transcript=transcript),indent=2,sort_keys=True)+'\n')
        print(f'Packaged stdio: {len(rows)}/{len(rows)} question schedules; handshake, catalogs, role/binding, invalid inputs, readback and receipt assertions passed.')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();run(a.archive,a.output)
