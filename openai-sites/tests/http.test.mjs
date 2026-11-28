import test from 'node:test';import assert from 'node:assert/strict';
import worker from '../worker/index.js';import {fixture} from './support.mjs';
import {subjectActor} from '../worker/storage.js';
const origin='https://rumbo.test';
function request(path,body,headers={}){return new Request(origin+path,{method:body===undefined?'GET':'POST',headers:{...(body===undefined?{}:{'content-type':'application/json'}),...headers},...(body===undefined?{}:{body:JSON.stringify(body)})});}
const identity=(user='owner')=>({'oai-authenticated-user-id':user,'oai-authenticated-user-email':user+'@example.test'});
async function rpc(env,name,args={},user='owner',extra={}){const res=await worker.fetch(request('/mcp',{jsonrpc:'2.0',id:1,method:'tools/call',params:{name,arguments:args}},{...identity(user),accept:'application/json',...extra}),env);return {status:res.status,body:await res.json()};}
const contract=async()=>({project_id:'example',goal:'Synthetic <script> work',original_request:'No real user data',decision_owner:await subjectActor('owner'),constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'contains',kind:'file_contains',value:'hello'},{id:'review',kind:'manual_review',prompt:'Inspect exact bytes'}]}]});
async function browser(env){const res=await worker.fetch(request('/',undefined,{...identity(),'sec-fetch-mode':'navigate','sec-fetch-dest':'document'}),env);const html=await res.text();assert.equal(res.status,200);return {...identity(),cookie:res.headers.get('set-cookie').split(';')[0],origin,'sec-fetch-site':'same-origin','sec-fetch-mode':'cors','x-rumbo-csrf':html.match(/name="rumbo-csrf" content="([^"]+)"/)[1]};}
test('anonymous discovery reveals no project data; data tools require real identity',async()=>{
 const {env}=fixture();const res=await worker.fetch(request('/mcp',{jsonrpc:'2.0',id:1,method:'tools/list'}),env);assert.equal(res.status,200);const tools=(await res.json()).result.tools;
 for(const forbidden of ['decide','create_contract','revise_contract','set_member','rumbo_submit_artifact'])assert.ok(!tools.some(t=>t.name.includes(forbidden)));
 const names=tools.map(t=>t.name);assert.ok(names.includes('rumbo_open_worker'));assert.ok(names.includes('rumbo_submit_review'));
 const unauthorized=await worker.fetch(request('/mcp',{jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'rumbo_list_projects',arguments:{}}},{'oai-sites-authorization':'Bearer synthetic'}),env);assert.equal(unauthorized.status,401);
});
test('MCP rejects malformed JSON, oversized requests, unsupported methods and notifications correctly',async()=>{
 const {env}=fixture();assert.equal((await worker.fetch(new Request(origin+'/mcp',{method:'GET'}),env)).status,405);
 const malformed=await worker.fetch(new Request(origin+'/mcp',{method:'POST',headers:{'content-type':'application/json'},body:'{"a":1,"a":2}'}),env);assert.equal((await malformed.json()).error.code,-32700);
 const note=await worker.fetch(request('/mcp',{jsonrpc:'2.0',method:'notifications/initialized'}),env);assert.equal(note.status,202);assert.equal(await note.text(),'');
 const huge=await worker.fetch(new Request(origin+'/mcp',{method:'POST',headers:{'content-type':'application/json'},body:'x'.repeat(1048577)}),env);assert.equal(huge.status,413);
});
test('owner browser CSRF/session boundary rejects forged modes, bearer transport and cross-origin',async()=>{
 const {env}=fixture();const good=await browser(env),body={contract:await contract()};
 for(const headers of [identity(),{...good,origin:'https://evil.test'},{...good,'x-rumbo-csrf':'bad'},{...good,authorization:'Bearer delegated-agent'},{...good,'mcp-protocol-version':'2025-11-25'},{...good,'sec-fetch-site':'cross-site'}]){
  const r=await worker.fetch(request('/owner/api/create',body,headers),env);assert.equal(r.status,403);
 }
 const res=await worker.fetch(request('/owner/api/create',body,good),env);assert.equal(res.status,200);assert.equal((await res.json()).alias,'example');
 const c=await rpc(env,'rumbo_decide',{project_key:'example'});assert.equal(c.body.error.code,-32602);
});
test('full HTTP owner/worker/separate-reviewer workflow; read tools make no writes',async()=>{
 const {env,storage,db}=fixture(),headers=await browser(env);const made=await worker.fetch(request('/owner/api/create',{contract:await contract()},headers),env);const {project_key}=await made.json();
 await storage.setMember('owner',project_key,'reviewer','reviewer');
 const open=await rpc(env,'rumbo_open_worker',{project_key,label:'Maker'});const worker_id=open.body.result.structuredContent.worker_id;
 const work={project_key,worker_id};for(const [name,args] of [
  ['rumbo_claim_task',{task_id:'one',contract_revision:1,lease_seconds:300}],
  ['rumbo_ingest_artifact',{task_id:'one',contract_revision:1,filename:'output.txt',content:'hello <script>alert(1)</script>'}],
  ['rumbo_run_checks',{task_id:'one',contract_revision:1,artifact_revision:1}]
 ]){const r=await rpc(env,name,{...work,...args});assert.equal(r.body.result?.isError,false,JSON.stringify(r));}
 const args={project_key,task_id:'one',contract_revision:1,artifact_revision:1,check_id:'review',outcome:'pass',detail:'Synthetic separate reviewer'};
 assert.equal((await rpc(env,'rumbo_submit_review',args)).body.result.isError,true);
 assert.equal((await rpc(env,'rumbo_submit_review',args,'reviewer')).body.result.isError,false);
 const artifact=await (await worker.fetch(request('/api/artifact?project_key='+project_key+'&task_id=one&contract_revision=1&artifact_revision=1',undefined,identity()),env)).json();
 const decision=await worker.fetch(request('/owner/api/decide',{project_key,task_id:'one',contract_revision:1,artifact_revision:1,outcome:'accepted',reason:'Synthetic owner checked bytes',expected_review_basis:artifact.review_context.review_basis},headers),env);assert.equal(decision.status,200);assert.equal((await decision.json()).tasks[0].status,'accepted');
 const before=db.prepare('SELECT total_changes() AS n').get().n;
 for(const [name,args] of [['rumbo_list_projects',{}],['rumbo_state',{project_key}],['open_project_board',{project_key}],['rumbo_read_artifact',{project_key,task_id:'one',contract_revision:1,artifact_revision:1}]])assert.equal((await rpc(env,name,args)).body.result.isError,false);
 assert.equal(db.prepare('SELECT total_changes() AS n').get().n,before);
 assert.equal((await rpc(env,'rumbo_state',{project_key},'outsider')).body.result.isError,true);
});
test('owner API requires an inspected basis and rejects refreshed evidence without appending a decision',async()=>{
 const {env,storage}=fixture(),headers=await browser(env),made=await worker.fetch(request('/owner/api/create',{contract:await contract()},headers),env),{project_key}=await made.json();
 await storage.setMember('owner',project_key,'reviewer','reviewer');const opened=await storage.openWorker('owner',project_key,'Maker'),maker=await storage.workerEngine('owner',project_key,opened.worker_id);
 await maker.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300});await maker.execute('ingest_artifact',{task_id:'one',contract_revision:1,filename:'output.txt',content:'hello'});await maker.execute('run_checks',{task_id:'one',contract_revision:1,artifact_revision:1});
 await (await storage.reviewerEngine('reviewer',project_key)).execute('submit_review',{task_id:'one',contract_revision:1,artifact_revision:1,check_id:'review',outcome:'pass',detail:'Synthetic exact review'});
 const common={project_key,task_id:'one',contract_revision:1,artifact_revision:1,outcome:'accepted',reason:'Inspected exact current basis'};
 const missing=await worker.fetch(request('/owner/api/decide',common,headers),env);assert.equal(missing.status,400);assert.equal((await missing.json()).code,'MISSING_FIELD');
 const inspected=await (await worker.fetch(request('/api/artifact?project_key='+project_key+'&task_id=one&contract_revision=1&artifact_revision=1',undefined,identity()),env)).json();
 await maker.execute('run_checks',{task_id:'one',contract_revision:1,artifact_revision:1});
 const stale=await worker.fetch(request('/owner/api/decide',{...common,expected_review_basis:inspected.review_context.review_basis},headers),env);assert.equal(stale.status,409);assert.equal((await stale.json()).code,'STALE_REVIEW');assert.equal((await maker.snapshot()).tasks[0].decisions.length,0);
 const fresh=await (await worker.fetch(request('/api/artifact?project_key='+project_key+'&task_id=one&contract_revision=1&artifact_revision=1',undefined,identity()),env)).json();
 const accepted=await worker.fetch(request('/owner/api/decide',{...common,expected_review_basis:fresh.review_context.review_basis},headers),env);assert.equal(accepted.status,200);assert.equal((await accepted.json()).tasks[0].status,'accepted');
});
test('owner API permits identical accepted reconfirmation but rebases changed reason and reject transitions',async()=>{
 const {env,storage}=fixture(),headers=await browser(env),made=await worker.fetch(request('/owner/api/create',{contract:await contract()},headers),env),{project_key}=await made.json();
 await storage.setMember('owner',project_key,'reviewer','reviewer');const opened=await storage.openWorker('owner',project_key,'Maker'),maker=await storage.workerEngine('owner',project_key,opened.worker_id);
 await maker.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300});await maker.execute('ingest_artifact',{task_id:'one',contract_revision:1,filename:'output.txt',content:'hello'});await maker.execute('run_checks',{task_id:'one',contract_revision:1,artifact_revision:1});await (await storage.reviewerEngine('reviewer',project_key)).execute('submit_review',{task_id:'one',contract_revision:1,artifact_revision:1,check_id:'review',outcome:'pass',detail:'Synthetic exact review'});
 const artifact=()=>worker.fetch(request('/api/artifact?project_key='+project_key+'&task_id=one&contract_revision=1&artifact_revision=1',undefined,identity()),env).then(response=>response.json());
 const post=payload=>worker.fetch(request('/owner/api/decide',payload,headers),env),base={project_key,task_id:'one',contract_revision:1,artifact_revision:1,outcome:'accepted',reason:'Stable owner rationale'};
 let view=await artifact();assert.equal((await post({...base,expected_review_basis:view.review_context.review_basis})).status,200);
 view=await artifact();const acceptedBasis=view.review_context.review_basis,identical={...base,expected_review_basis:acceptedBasis};assert.equal((await post(identical)).status,200);assert.equal((await post(identical)).status,200);
 assert.equal((await (await storage.engine('owner',project_key,'human')).snapshot()).tasks[0].decisions.length,3);
 assert.equal((await post({...identical,reason:'Changed owner rationale'})).status,200);let stale=await post(identical);assert.equal(stale.status,409);assert.equal((await stale.json()).code,'STALE_REVIEW');
 view=await artifact();const changedBasis=view.review_context.review_basis;assert.equal((await post({...base,outcome:'rejected',reason:'Blocking issue found',expected_review_basis:changedBasis})).status,200);
 stale=await post({...base,expected_review_basis:changedBasis});assert.equal(stale.status,409);assert.equal((await stale.json()).code,'STALE_REVIEW');
 view=await artifact();assert.equal((await post({...base,expected_review_basis:view.review_context.review_basis})).status,200);stale=await post({...base,expected_review_basis:changedBasis});assert.equal(stale.status,409);
});
test('board global and thread entrypoints accept empty arguments and safely select authorized projects',async()=>{
 const {env,storage}=fixture();let board=await rpc(env,'open_project_board',{});assert.equal(board.body.result.isError,false);assert.deepEqual(board.body.result.structuredContent.projects,[]);
 await storage.createProject('owner','example',await contract());board=await rpc(env,'open_project_board',{});assert.equal(board.body.result.structuredContent.project_id,'example');
 const c=await contract();c.project_id='second';await storage.createProject('owner','second',c);board=await rpc(env,'open_project_board',{});assert.equal(board.body.result.structuredContent.projects.length,2);assert.equal(board.body.result.structuredContent.project_selection_required,true);
});

test('export returns the ownership error as a browser response for a shared project', async () => {
 const {env,storage,db} = fixture();
 try {
  const data = {...await contract(), decision_owner:await subjectActor('colleague')};
  const project = await storage.createProject('colleague', data.project_id, data);
  await storage.setMember('colleague', project.project_key, 'owner', 'viewer');
  const headers = await browser(env);
  const response = await worker.fetch(request('/owner/api/export', {project_key:project.project_key}, headers), env);
  assert.equal(response.status, 403);
  const error = await response.json();
  assert.equal(error.code, 'FORBIDDEN');
  assert.match(error.error, /project owner/i);
 } finally {
  db.close();
 }
});
