import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../worker/index.js';
import {fixture} from './support.mjs';
import {subjectActor} from '../worker/storage.js';
const origin='https://rumbo.test';
const identity=(subject='owner')=>({'oai-authenticated-user-id':subject,'oai-authenticated-user-email':subject+'@example.test'});
function request(path,body,headers={}){return new Request(origin+path,{method:body===undefined?'GET':'POST',headers:{...(body===undefined?{}:{'content-type':'application/json'}),...headers},...(body===undefined?{}:{body:JSON.stringify(body)})});}
async function browser(env,subject='owner'){
 const response=await worker.fetch(request('/',undefined,{...identity(subject),'sec-fetch-mode':'navigate','sec-fetch-dest':'document'}),env),html=await response.text();
 assert.equal(response.status,200);
 return {...identity(subject),cookie:response.headers.get('set-cookie').split(';')[0],origin,'sec-fetch-site':'same-origin','sec-fetch-mode':'cors','x-rumbo-csrf':html.match(/name="rumbo-csrf" content="([^"]+)"/)[1]};
}
async function project(storage){const contract={project_id:'privacy-example',goal:'Synthetic private content',original_request:'Disposable test only',decision_owner:await subjectActor('owner'),constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'hello'}]}]};return storage.createProject('owner',contract.project_id,contract);}
test('owner navigation removes only expired browser sessions and preserves worker provenance',async()=>{
 const {env,db,storage}=fixture(),made=await project(storage),now=Math.floor(Date.now()/1000);
 db.prepare('INSERT INTO browser_sessions VALUES (?,?,?,?)').run('expired','old-user','old-csrf',now-1);
 db.prepare('INSERT INTO browser_sessions VALUES (?,?,?,?)').run('boundary','boundary-user','boundary-csrf',now);
 db.prepare('INSERT INTO browser_sessions VALUES (?,?,?,?)').run('valid','other-user','valid-csrf',now+3600);
 await storage.setMember('owner',made.project_key,'maker','worker');await storage.openWorker('maker',made.project_key,'Historical maker');db.prepare('UPDATE workers SET expires_at=?').run(now-1);
 await browser(env);
 assert.equal(db.prepare('SELECT count(*) AS n FROM browser_sessions WHERE id_hash=?').get('expired').n,0);
 assert.equal(db.prepare('SELECT count(*) AS n FROM browser_sessions WHERE id_hash=?').get('boundary').n,0);
 assert.equal(db.prepare('SELECT count(*) AS n FROM browser_sessions WHERE id_hash=?').get('valid').n,1);
 assert.equal(db.prepare('SELECT count(*) AS n FROM workers').get().n,1);
 await assert.rejects(()=>storage.setMember('owner',made.project_key,'maker','reviewer'),error=>error.code==='FORBIDDEN');
});
test('owner export remains available before deletion and pending cleanup is a distinct conflict',async()=>{
 const {env,storage}=fixture(),made=await project(storage),good=await browser(env),session=await storage.openWorker('owner',made.project_key,'Synthetic maker'),engine=await storage.workerEngine('owner',made.project_key,session.worker_id);
 await engine.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300});await engine.execute('ingest_artifact',{task_id:'one',contract_revision:1,filename:'export.txt',content:'hello retained evidence'});
 const before=await worker.fetch(request('/owner/api/export',{project_key:made.project_key},good),env);assert.equal(before.status,200);const records=(await before.text()).trim().split('\n').map(JSON.parse);assert.equal(records.at(-1).complete,true);assert.equal(Buffer.from(records.find(row=>row.type==='artifact').base64,'base64').toString(),'hello retained evidence');
 storage.bucket.put=async()=>{throw new Error('Synthetic guard write interruption');};
 const removal=await worker.fetch(request('/owner/api/delete',{project_key:made.project_key,confirmation:'privacy-example'},good),env);assert.equal(removal.status,200);assert.equal((await removal.json()).status,'deleting');
 const state=await worker.fetch(request('/api/state?project_key='+made.project_key,undefined,identity()),env);assert.equal(state.status,409);assert.equal((await state.json()).code,'PROJECT_DELETING');
});
test('deletion requires the owner browser, exact confirmation and never exposes an MCP delete tool',async()=>{
 const {env,storage}=fixture(),made=await project(storage),good=await browser(env),body={project_key:made.project_key,confirmation:'privacy-example'};
 for(const headers of [identity(),{...good,origin:'https://elsewhere.test'},{...good,'x-rumbo-csrf':'wrong'},{...good,authorization:'Bearer synthetic'},{...good,'oai-sites-authorization':'synthetic'},{...good,'mcp-protocol-version':'2025-11-25'}])assert.equal((await worker.fetch(request('/owner/api/delete',body,headers),env)).status,403);
 await storage.setMember('owner',made.project_key,'viewer','viewer');const viewer=await browser(env,'viewer');assert.equal((await worker.fetch(request('/owner/api/delete',body,viewer),env)).status,403);
 const wrong=await worker.fetch(request('/owner/api/delete',{...body,confirmation:'wrong'},good),env);assert.equal(wrong.status,400);assert.equal((await storage.listProjects('owner')).length,1);
 const discovery=await worker.fetch(request('/mcp',{jsonrpc:'2.0',id:1,method:'tools/list'}),env);assert.ok((await discovery.json()).result.tools.every(tool=>!tool.name.includes('delete')));
 const deleted=await worker.fetch(request('/owner/api/delete',body,good),env);assert.equal(deleted.status,200);assert.equal((await deleted.json()).status,'deleted');
 assert.equal((await worker.fetch(request('/owner/api/delete',body,good),env)).status,200);
});
