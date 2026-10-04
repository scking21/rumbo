import test from 'node:test';import assert from 'node:assert/strict';import {readFileSync,readdirSync} from 'node:fs';import {Miniflare} from 'miniflare';
import {createOfflineRuntime} from './offline-runtime.mjs';
import {canonical} from '../worker/codec.js';import {Storage,subjectActor} from '../worker/storage.js';
test('actual workerd D1/R2 runtime persists end-to-end and serializes competing claims',async()=>{
 const mf=createOfflineRuntime(Miniflare,{modules:true,scriptPath:'dist/server/index.js',compatibilityDate:'2026-07-29',d1Databases:['DB'],r2Buckets:['ARTIFACTS']});
 try{
  const db=await mf.getD1Database('DB');for(const name of readdirSync('drizzle').filter(n=>/^\d+.*\.sql$/.test(n)).sort())for(const sql of readFileSync('drizzle/'+name,'utf8').split('--> statement-breakpoint'))if(sql.trim())await db.prepare(sql).run();
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
  let db=await mf.getD1Database('DB');for(const name of readdirSync('drizzle').filter(n=>/^\d+.*\.sql$/.test(n)).sort())for(const sql of readFileSync('drizzle/'+name,'utf8').split('--> statement-breakpoint'))if(sql.trim())await db.prepare(sql).run();
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

test('actual workerd upgrades populated D1 and permanent empty R2 guards block delayed conditional uploads across deletion retries',async()=>{
 const {sha256,utf8}=await import('../worker/codec.js');
 const mf=createOfflineRuntime(Miniflare,{modules:true,script:"export default {fetch(){return new Response('synthetic deletion test');}};",compatibilityDate:'2026-07-29',d1Databases:['DB'],r2Buckets:['ARTIFACTS']});
 let resume;
 try{
  const db=await mf.getD1Database('DB'),bucket=await mf.getR2Bucket('ARTIFACTS');
  for(const sql of readFileSync('drizzle/0000_initial.sql','utf8').split('--> statement-breakpoint'))if(sql.trim())await db.prepare(sql).run();
  const key=await sha256('owner\0runtime-delete'),actor=await subjectActor('owner'),oldBytes=utf8('existing deployed artifact'),oldDigest=await sha256(oldBytes),zero='0'.repeat(64);
  const contract={project_id:'runtime-delete',goal:'Synthetic migrated project',original_request:'Only emulator data',decision_owner:actor,constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'hello'}]}],contract_revision:1,contract_change_reason:'Synthetic initial contract'};
  const payload=canonical({action:'create_contract',data:contract,actor,role:'human',at:1}),eventDigest=await sha256(zero+'\n'+payload);
  await db.batch([
   db.prepare('INSERT INTO projects (key,alias,owner_subject,owner_actor,head_seq,head_digest,event_bytes,created_at) VALUES (?,?,?,?,1,?,?,1)').bind(key,'runtime-delete','owner',actor,eventDigest,payload.length),
   db.prepare('INSERT INTO events (project_key,seq,payload,previous,digest) VALUES (?,1,?,?,?)').bind(key,payload,zero,eventDigest),
   db.prepare('INSERT INTO artifacts (project_key,digest,size) VALUES (?,?,?)').bind(key,oldDigest,oldBytes.length)
  ]);await bucket.put(key+'/'+oldDigest,oldBytes);
  for(const name of readdirSync('drizzle').filter(n=>/^\d+.*\.sql$/.test(n)&&!n.startsWith('0000')).sort())for(const sql of readFileSync('drizzle/'+name,'utf8').split('--> statement-breakpoint'))if(sql.trim())await db.prepare(sql).run();
  assert.equal((await db.prepare('SELECT lifecycle FROM projects WHERE key=?').bind(key).first()).lifecycle,'active');assert.equal((await db.prepare('SELECT guard_written FROM artifacts WHERE project_key=?').bind(key).first()).guard_written,0);
  const primitiveKey='synthetic-permanent-guard';await bucket.put(primitiveKey,new Uint8Array());assert.equal(await bucket.put(primitiveKey,utf8('must not overwrite'),{onlyIf:{etagDoesNotMatch:'*'}}),null);await bucket.put(primitiveKey,new Uint8Array());assert.equal((await (await bucket.get(primitiveKey)).arrayBuffer()).byteLength,0);
  let ready,failGuard=true,conditionalResult='not run';const paused=new Promise(r=>ready=r),gate=new Promise(r=>resume=r),bytes=utf8('delayed authorized upload'),digest=await sha256(bytes);
  const storage=new Storage({DB:db,ARTIFACTS:{get:k=>bucket.get(k),async put(k,v,options){if(options?.onlyIf){ready();await gate;conditionalResult=await bucket.put(k,v,options);return conditionalResult;}if(failGuard){failGuard=false;throw new Error('synthetic guard outage');}return bucket.put(k,v,options);}}}),io=await storage.projectIO('owner',key);
  const uploading=io.artifacts.put(digest,bytes);await paused;
  assert.deepEqual(await storage.deleteProject('owner',key,'runtime-delete'),{project_key:key,status:'deleting',retry:true});assert.equal((await storage.listProjects('owner'))[0].lifecycle,'deleting');
  assert.deepEqual(await storage.deleteProject('owner',key,'runtime-delete'),{project_key:key,status:'deleted'});resume();await assert.rejects(uploading,e=>e.code==='FORBIDDEN');assert.equal(conditionalResult,null);
  for(const d of [oldDigest,digest])assert.equal((await (await bucket.get(key+'/'+d)).arrayBuffer()).byteLength,0);
  assert.deepEqual(await storage.deleteProject('owner',key,'runtime-delete'),{project_key:key,status:'deleted'});assert.equal((await db.prepare('SELECT count(*) AS n FROM projects').first()).n,0);assert.equal((await db.prepare('SELECT count(*) AS n FROM artifacts').first()).n,0);assert.deepEqual(await db.prepare('SELECT * FROM deleted_projects').first(),{key});
  await assert.rejects(()=>db.prepare('INSERT INTO projects (key,alias,owner_subject,owner_actor,created_at) VALUES (?,?,?,?,1)').bind(key,'runtime-delete','owner',actor).run(),/PROJECT_DELETED/);
 }finally{resume?.();await mf.dispose();}
});
