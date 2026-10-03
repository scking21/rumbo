import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture} from './support.mjs';
import {Storage,subjectActor} from '../worker/storage.js';

const contract=owner=>({project_id:'workflows',goal:'Exact synthetic workflow',original_request:'Deterministic interruption and restart coverage',decision_owner:owner,constraints:[],tasks:['one','two'].map(id=>({id,title:id,dependencies:[],acceptance:[{id:'contains',kind:'file_contains',value:'hello'}]}))});
const claim=(task_id='one',contract_revision=1)=>({task_id,contract_revision,lease_seconds:300});
const upload=(content='hello committed',task_id='one',contract_revision=1)=>({task_id,contract_revision,filename:'artifact.txt',content});
const check=(artifact_revision=1,contract_revision=1)=>({task_id:'one',contract_revision,artifact_revision});
async function setup(){
 const f=fixture(),c=contract(await subjectActor('owner')),p=await f.storage.createProject('owner','workflows',c);
 const session=await f.storage.openWorker('owner',p.project_key,'first worker'),worker=await f.storage.workerEngine('owner',p.project_key,session.worker_id),owner=await f.storage.engine('owner',p.project_key,'human');
 return {...f,c,p,session,worker,owner};
}
function barrier(){let enter,release;return {entered:new Promise(r=>enter=r),gate:new Promise(r=>release=r),enter:()=>enter(),release:()=>release()};}

test('stale contract operations leave the committed ledger and upload store unchanged',async()=>{
 const {worker,owner,c,objects}=await setup();await worker.execute('claim_task',claim());await worker.execute('ingest_artifact',upload());
 await owner.execute('revise_contract',{contract:c,expected_revision:1,reason:'New exact scope'});const before=await owner.snapshot(),objectCount=objects.size;
 for(const [action,args] of [['claim_task',claim()],['ingest_artifact',upload('hello stale')],['run_checks',check()]])await assert.rejects(()=>worker.execute(action,args),e=>e.code==='STALE_CONTRACT');
 await assert.rejects(()=>worker.artifactView(check()),e=>e.code==='STALE_CONTRACT');assert.deepEqual(await owner.snapshot(),before);assert.equal(objects.size,objectCount);
});

test('an upload paused across a contract revision cannot commit stale work and can be retried after restart',async()=>{
 const {worker,owner,c,storage,p,session,env,db}=await setup();await worker.execute('claim_task',claim());
 const b=barrier(),put=env.ARTIFACTS.put;let writes=0;env.ARTIFACTS.put=async(...args)=>{writes++;b.enter();await b.gate;return put(...args);};
 const pending=worker.execute('ingest_artifact',upload());await b.entered;
 await owner.execute('revise_contract',{contract:c,expected_revision:1,reason:'Owner updated while upload was in flight'});b.release();
 await assert.rejects(pending,e=>e.code==='STALE_CONTRACT');assert.equal((await owner.snapshot()).tasks[0].artifact,null);assert.equal(db.prepare('SELECT count(*) AS n FROM artifacts').get().n,1);
 const restarted=await new Storage(env).workerEngine('owner',p.project_key,session.worker_id);await restarted.execute('claim_task',claim('one',2));await restarted.execute('ingest_artifact',upload('hello committed','one',2));
 assert.equal((await restarted.artifactView(check(1,2))).text,'hello committed');assert.equal(writes,1,'The committed retry reuses the exact already uploaded digest');
});

test('checks paused across an artifact replacement cannot append evidence for the older revision',async()=>{
 const {worker,owner,env}=await setup();await worker.execute('claim_task',claim());await worker.execute('ingest_artifact',upload());
 const b=barrier(),get=env.ARTIFACTS.get;let reads=0;env.ARTIFACTS.get=async(...args)=>{const result=await get(...args);if(++reads===2){b.enter();await b.gate;}return result;};
 // The first read projects state; the second obtains the exact bytes to check.
 const pending=worker.execute('run_checks',check());await b.entered;await worker.execute('ingest_artifact',upload('hello replacement'));b.release();
 await assert.rejects(pending,e=>e.code==='STALE_ARTIFACT');const state=await owner.snapshot();assert.equal(state.tasks[0].artifact.revision,2);assert.deepEqual(state.tasks[0].evidence,[]);
});

test('concurrent owner revisions produce one revision and reject the stale contender',async()=>{
 const {owner,c,storage,p}=await setup(),second=await storage.engine('owner',p.project_key,'human');
 const results=await Promise.allSettled([owner,second].map((engine,i)=>engine.execute('revise_contract',{contract:{...c,goal:'Revision candidate '+i},expected_revision:1,reason:'Concurrent owner edit '+i})));
 assert.equal(results.filter(x=>x.status==='fulfilled').length,1);assert.equal(results.filter(x=>x.status==='rejected'&&x.reason.code==='STALE_CONTRACT').length,1);
 const restarted=await storage.engine('owner',p.project_key,'human');assert.equal((await restarted.snapshot()).contract_revision,2);assert.equal((await restarted.snapshot()).events_count,2);
});

test('concurrent equal-content uploads share stored bytes but keep separate task histories',async()=>{
 const {worker,storage,p,env,db,objects}=await setup(),secondSession=await storage.openWorker('owner',p.project_key,'second worker'),second=await storage.workerEngine('owner',p.project_key,secondSession.worker_id);
 await worker.execute('claim_task',claim('one'));await second.execute('claim_task',claim('two'));
 await Promise.all([worker.execute('ingest_artifact',upload('hello shared','one')),second.execute('ingest_artifact',upload('hello shared','two'))]);
 const restarted=await new Storage(env).engine('owner',p.project_key,'human'),state=await restarted.snapshot();assert.equal(state.events_count,5);assert.equal(objects.size,1);assert.equal(db.prepare('SELECT sum(size) AS n FROM artifacts').get().n,12);
 assert.equal(state.tasks[0].artifact.sha256,state.tasks[1].artifact.sha256);assert.notEqual(state.tasks[0].artifact.maker,state.tasks[1].artifact.maker);assert.ok(state.tasks.every(t=>t.artifact.revision===1));
});

test('expired task claims remain expired after restart and previous workers cannot upload',async()=>{
 const {worker,storage,p,session,env}=await setup();worker.clock=()=>1000;await worker.execute('claim_task',claim());
 const secondSession=await storage.openWorker('owner',p.project_key,'replacement worker'),second=await storage.workerEngine('owner',p.project_key,secondSession.worker_id);second.clock=()=>1300;await second.execute('claim_task',claim());
 const restarted=await new Storage(env).workerEngine('owner',p.project_key,session.worker_id);restarted.clock=()=>1300;await assert.rejects(()=>restarted.execute('ingest_artifact',upload()),e=>e.code==='LEASE_REQUIRED');
 await second.execute('ingest_artifact',upload('hello replacement'));assert.equal((await second.snapshot()).tasks[0].artifact.maker,second.actor);
});

test('a full ledger rejects an upload before creating any quota reservation or object',async()=>{
 const {worker,owner,c,storage,p,db,objects}=await setup(),{canonical,sha256}=await import('../worker/codec.js'),{MAX_LEDGER_BYTES}=await import('../worker/engine.js');
 const io=await storage.projectIO('owner',p.project_key);let rows=await io.store.read(),count=rows.length,head=rows.at(-1).digest,used=rows.reduce((n,r)=>n+r.payload.length,0),revision=1;
 async function append(event){const payload=canonical(event),row={seq:count+1,payload,previous:head,digest:await sha256(head+'\n'+payload)};assert.equal(await io.store.append({count,head},row),true);count++;head=row.digest;used+=payload.length;}
 const large={...c,demo:false,constraints:Array.from({length:50},()=> 'x'.repeat(4000))};
 // Arrange valid repeated complete-contract revisions without quadratic replay.
 while(true){const event={action:'revise_contract',actor:owner.actor,role:'human',at:1000,data:{...large,contract_revision:revision+1,contract_change_reason:'Synthetic full-ledger workflow'}};
  if(used+canonical(event).length>MAX_LEDGER_BYTES-8192)break;await append(event);revision++;
 }
 worker.clock=()=>1000;await worker.execute('claim_task',claim('one',revision));rows=await io.store.read();count=rows.length;head=rows.at(-1).digest;used=rows.reduce((n,r)=>n+r.payload.length,0);
 while(true){const event={action:'request_decision',actor:worker.actor,role:'worker',at:1000,data:{id:'e'+(count+1),task_id:'one',question:'',actor:worker.actor,contract_revision:revision,at:1000}},overhead=canonical(event).length;
  const length=Math.min(4000,MAX_LEDGER_BYTES-used-overhead-10);if(length<1)break;event.data.question='q'.repeat(length);await append(event);
 }
 assert.ok(MAX_LEDGER_BYTES-used<500,'Fixture leaves less space than an upload event');
 await assert.rejects(()=>worker.execute('ingest_artifact',upload('hello full ledger','one',revision)),e=>e.code==='LEDGER_LIMIT');
 assert.equal(db.prepare('SELECT count(*) AS n FROM artifacts').get().n,0,'Rejected upload must not consume reserved quota');assert.equal(objects.size,0);
 assert.equal((await io.store.read()).at(-1).digest,head,'Rejected upload must not append an event');
});
