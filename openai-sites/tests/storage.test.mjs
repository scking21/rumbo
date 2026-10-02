import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {Storage,subjectActor} from '../worker/storage.js';
import {Engine} from '../worker/engine.js';
import {sha256,utf8} from '../worker/codec.js';
import {fixture} from './support.mjs';
const contract=owner=>({project_id:'example',goal:'Synthetic test',original_request:'Test persistence',decision_owner:owner,constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'hello'}]}]});
test('persistent projects are subject-isolated and owner identity is host-derived',async()=>{
 const {storage}=fixture(),owner=await subjectActor('owner');await storage.createProject('owner','example',contract(owner));
 assert.equal((await storage.listProjects('owner')).length,1);assert.equal((await storage.listProjects('outsider')).length,0);
 await assert.rejects(()=>storage.authorize('outsider','example'),e=>e.code==='FORBIDDEN');
 const second=new Storage(storage.env);assert.equal((await second.engine('owner','example','human')).actor,owner);assert.equal((await (await second.engine('owner','example','human')).snapshot()).contract_revision,1);
});
test('worker handles cannot forge subject/project or become reviewer authority',async()=>{
 const {storage}=fixture();await storage.createProject('owner','example',contract(await subjectActor('owner')));
 const a=await storage.openWorker('owner','example','worker A'),b=await storage.openWorker('owner','example','worker B');assert.notEqual(a.worker_id,b.worker_id);
 const ea=await storage.workerEngine('owner','example',a.worker_id),eb=await storage.workerEngine('owner','example',b.worker_id);assert.notEqual(ea.actor,eb.actor);
 await assert.rejects(()=>storage.workerEngine('outsider','example',a.worker_id),e=>e.code==='FORBIDDEN');
 await assert.rejects(()=>storage.reviewerEngine('owner','example'),e=>e.code==='FORBIDDEN');
});
test('D1 CAS serializes competing claims and R2 persists immutable bytes across instances',async()=>{
 const {storage,env}=fixture();await storage.createProject('owner','example',contract(await subjectActor('owner')));
 const ids=await Promise.all(['A','B','C'].map(label=>storage.openWorker('owner','example',label)));
 const engines=await Promise.all(ids.map(i=>storage.workerEngine('owner','example',i.worker_id)));
 const results=await Promise.allSettled(engines.map(e=>e.execute('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300})));
 assert.equal(results.filter(r=>r.status==='fulfilled').length,1);assert.ok(results.filter(r=>r.status==='rejected').every(r=>r.reason.code==='LEASE_CONFLICT'));
 const index=results.findIndex(r=>r.status==='fulfilled');await engines[index].execute('ingest_artifact',{task_id:'one',contract_revision:1,filename:'test.txt',content:'hello'});
 const restarted=await new Storage(env).workerEngine('owner','example',ids[index].worker_id);assert.equal((await restarted.artifactView({task_id:'one',contract_revision:1,artifact_revision:1})).text,'hello');
});
test('artifact quota reservations are atomic and duplicate content consumes no extra quota',async()=>{
 const {storage,db}=fixture();await storage.createProject('owner','example',contract(await subjectActor('owner')));const io=await storage.projectIO('owner','example');
 const bytes=utf8('hello'),digest=await sha256(bytes);await Promise.all([io.artifacts.put(digest,bytes),io.artifacts.put(digest,bytes)]);assert.equal(db.prepare('SELECT sum(size) AS n FROM artifacts').get().n,5);
 db.prepare('UPDATE artifacts SET size=?').run(64*1024*1024);await assert.rejects(()=>io.artifacts.put(awaitDigest,utf8('more')),e=>e.code==='STORAGE_LIMIT');
});
const awaitDigest=await sha256('more');
test('worker creation racing reviewer promotion cannot give a maker reviewer authority',async()=>{
 const {storage}=fixture();const made=await storage.createProject('owner','example',contract(await subjectActor('owner')));await storage.setMember('owner',made.project_key,'candidate','worker');
 // Hold a previously authorized worker request at its database insertion while
 // the owner completes a reviewer grant. The insertion must recheck membership.
 const original=storage.db.prepare.bind(storage.db);let resume,ready;const paused=new Promise(r=>ready=r);const gate=new Promise(r=>resume=r);
 storage.db.prepare=sql=>{const statement=original(sql);if(sql.startsWith('INSERT INTO workers')){const run=statement.run.bind(statement);statement.run=async()=>{ready();await gate;return run();};}return statement;};
 const opening=storage.openWorker('candidate',made.project_key,'racing worker');await paused;await storage.setMember('owner',made.project_key,'candidate','reviewer');resume();
 await assert.rejects(opening,e=>e.code==='FORBIDDEN');assert.equal((await storage.reviewerEngine('candidate',made.project_key)).role,'reviewer');
});
