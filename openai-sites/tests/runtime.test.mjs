import test from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import {Miniflare} from 'miniflare';
import {createOfflineRuntime} from './offline-runtime.mjs';
import {canonical} from '../worker/codec.js';import {Storage,subjectActor} from '../worker/storage.js';
test('actual workerd D1/R2 runtime persists end-to-end and serializes competing claims',async()=>{
 const mf=createOfflineRuntime(Miniflare,{modules:true,scriptPath:'dist/server/index.js',compatibilityDate:'2026-07-29',d1Databases:['DB'],r2Buckets:['ARTIFACTS']});
 try{
  const db=await mf.getD1Database('DB');for(const sql of readFileSync('drizzle/0000_initial.sql','utf8').split('--> statement-breakpoint'))if(sql.trim())await db.prepare(sql).run();
  const runtime=await mf.getWorker();
  const identity={'oai-authenticated-user-id':'owner','oai-authenticated-user-email':'owner@example.test'};
  // Node/Miniflare's fetch transport is not a browser navigation. Keep the
  // browser-only gate closed; seed the synthetic owner contract through D1.
  const page=await runtime.fetch('https://rumbo.test/',{headers:identity});assert.equal(page.status,403);
  const contract={project_id:'runtime',goal:'Synthetic workerd test',original_request:'Only test data',decision_owner:await subjectActor('owner'),constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'contains',kind:'file_contains',value:'hello'}]}]};
  const storage=new Storage({DB:db,ARTIFACTS:await mf.getR2Bucket('ARTIFACTS')});
  const {project_key}=await storage.createProject('owner','runtime',contract);
  const call=async(name,args)=>{const r=await runtime.fetch('https://rumbo.test/mcp',{method:'POST',headers:{...identity,'content-type':'application/json'},body:canonical({jsonrpc:'2.0',id:1,method:'tools/call',params:{name,arguments:args}})});return r.json();};
  const workers=await Promise.all(Array.from({length:8},(_,i)=>call('rumbo_open_worker',{project_key,label:'worker '+i})));assert.ok(workers.every(w=>w.result?.isError===false));
  const claims=await Promise.all(workers.map(w=>call('rumbo_claim_task',{project_key,worker_id:w.result.structuredContent.worker_id,task_id:'one',contract_revision:1,lease_seconds:300})));
  assert.equal(claims.filter(c=>c.result?.isError===false).length,1);assert.ok(claims.filter(c=>c.result?.isError===true).every(c=>c.result.content[0].text.startsWith('LEASE_CONFLICT')));
  const winner=workers[claims.findIndex(c=>!c.result.isError)].result.structuredContent.worker_id;
  const uploaded=await call('rumbo_ingest_artifact',{project_key,worker_id:winner,task_id:'one',contract_revision:1,filename:'test.txt',content:'hello runtime'});assert.equal(uploaded.result.isError,false);
  const read=await call('rumbo_read_artifact',{project_key,task_id:'one',contract_revision:1,artifact_revision:1});assert.equal(read.result.structuredContent.text,'hello runtime');
  const bucket=await mf.getR2Bucket('ARTIFACTS');assert.equal((await bucket.list()).objects.length,1);
 }finally{await mf.dispose();}
});

test('actual workerd restart restores D1 leases, exact R2 bytes and subsequent evidence writes',async()=>{
 const {mkdtemp,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path');
 const root=await mkdtemp(join(tmpdir(),'rumbo-sites-restart-'));
 const options={modules:true,scriptPath:'dist/server/index.js',compatibilityDate:'2026-07-29',d1Databases:['DB'],r2Buckets:['ARTIFACTS'],d1Persist:join(root,'d1'),r2Persist:join(root,'r2')};
 let mf=createOfflineRuntime(Miniflare,options);try{
  let db=await mf.getD1Database('DB');for(const sql of readFileSync('drizzle/0000_initial.sql','utf8').split('--> statement-breakpoint'))if(sql.trim())await db.prepare(sql).run();
  let storage=new Storage({DB:db,ARTIFACTS:await mf.getR2Bucket('ARTIFACTS')});
  const contract={project_id:'restart',goal:'Synthetic persistent restart',original_request:'Restart local emulators only',decision_owner:await subjectActor('owner'),constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'contains',kind:'file_contains',value:'hello'}]}]};
  const {project_key}=await storage.createProject('owner','restart',contract),session=await storage.openWorker('owner',project_key,'maker');let engine=await storage.workerEngine('owner',project_key,session.worker_id);
  await engine.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300});const content='\ufeffhello exact 😀\r\n';
  await engine.execute('ingest_artifact',{task_id:'one',contract_revision:1,filename:'restart.txt',content});const before=await engine.snapshot();
  await mf.dispose();mf=createOfflineRuntime(Miniflare,options);db=await mf.getD1Database('DB');storage=new Storage({DB:db,ARTIFACTS:await mf.getR2Bucket('ARTIFACTS')});engine=await storage.workerEngine('owner',project_key,session.worker_id);
  const after=await engine.snapshot();assert.equal(after.ledger_head,before.ledger_head);assert.deepEqual(after.tasks[0].lease,before.tasks[0].lease);assert.equal((await engine.artifactView({task_id:'one',contract_revision:1,artifact_revision:1})).text,content);
  const replacement=await storage.openWorker('owner',project_key,'replacement'),other=await storage.workerEngine('owner',project_key,replacement.worker_id);await assert.rejects(()=>other.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300}),e=>e.code==='LEASE_CONFLICT');
  await engine.execute('run_checks',{task_id:'one',contract_revision:1,artifact_revision:1});const owner=await storage.engine('owner',project_key,'human');const accepted=await owner.execute('decide',{task_id:'one',contract_revision:1,artifact_revision:1,outcome:'accepted',reason:'Synthetic exact bytes survived restart'});assert.equal(accepted.tasks[0].status,'accepted');assert.equal(accepted.events_count,5);
 }finally{await mf.dispose();await rm(root,{recursive:true,force:true});}
});

test('synthetic workerd rejects outbound fetches locally instead of contacting an external service',async()=>{
 const mf=createOfflineRuntime(Miniflare,{modules:true,compatibilityDate:'2026-07-29',script:`export default {async fetch(){const response=await fetch('https://synthetic-outbound.invalid/blocked');return Response.json({status:response.status,message:await response.text()});}};`});
 try{const runtime=await mf.getWorker(),response=await runtime.fetch('https://synthetic.invalid/local-dispatch');const result=await response.json();assert.equal(result.status,500);assert.match(result.message,/^Error: External fetch is disabled in synthetic Rumbo tests/);}finally{await mf.dispose();}
});
