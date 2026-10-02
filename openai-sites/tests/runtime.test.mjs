import test from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import {Miniflare} from 'miniflare';
import {canonical} from '../worker/codec.js';import {Storage,subjectActor} from '../worker/storage.js';
test('actual workerd D1/R2 runtime persists end-to-end and serializes competing claims',async()=>{
 const mf=new Miniflare({modules:true,scriptPath:'dist/server/index.js',compatibilityDate:'2026-07-29',d1Databases:['DB'],r2Buckets:['ARTIFACTS']});
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
