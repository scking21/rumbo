import test from 'node:test';import assert from 'node:assert/strict';import {fixture} from './support.mjs';import {subjectActor} from '../worker/storage.js';import {exportProject} from '../worker/export.js';import {spawnSync} from 'node:child_process';
test('owner export streams verified ledger and all historical immutable artifacts',async()=>{
 const {storage}=fixture(),owner=await subjectActor('owner');const p=await storage.createProject('owner','demo',{project_id:'demo',goal:'Test',original_request:'Synthetic only',decision_owner:owner,constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'ok',kind:'file_contains',value:'hello'}]}]});
 const w=await storage.openWorker('owner',p.project_key,'maker'),engine=await storage.workerEngine('owner',p.project_key,w.worker_id);
 await engine.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300});for(const content of ['hello first','hello second'])await engine.execute('ingest_artifact',{task_id:'one',contract_revision:1,filename:'x.txt',content});
 const response=await exportProject(storage,'owner',p.project_key),text=await response.text();const lines=text.trim().split('\n').map(JSON.parse);assert.equal(lines.filter(x=>x.type==='artifact').length,2);assert.equal(lines.at(-1).complete,true);
 const checked=spawnSync('python3',['scripts/verify-export.py'],{input:text,encoding:'utf8'});assert.equal(checked.status,0,checked.stderr);assert.equal(JSON.parse(checked.stdout).verified,true);
 const truncated=spawnSync('python3',['scripts/verify-export.py'],{input:text.split('\n').slice(0,-2).join('\n'),encoding:'utf8'});assert.notEqual(truncated.status,0);
 await assert.rejects(()=>exportProject(storage,'outsider',p.project_key),e=>e.code==='FORBIDDEN');
});
