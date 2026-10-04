/** Deterministic clock movement around real replay and optimistic store conflicts. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {Engine} from '../worker/engine.js';
import {memory} from './semantic-stress-support.mjs';

const contract=()=>({project_id:'clock',goal:'Bound lease authority',original_request:'Use synchronized eligibility time',decision_owner:'owner',constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'hello'}]}]});
const claim={task_id:'one',contract_revision:1,lease_seconds:30};
const upload={task_id:'one',contract_revision:1,filename:'output.txt',content:'hello'};
const latest=io=>JSON.parse(io.events.at(-1).payload);
async function fixture(start=1000){
 const io=memory(),time={now:start};
 const owner=new Engine({...io,actor:'owner',role:'human',clock:()=>time.now});
 const worker=new Engine({...io,actor:'maker',role:'worker',clock:()=>time.now});
 await owner.execute('create_contract',contract());await worker.execute('claim_task',claim);
 return {io,time,owner,worker};
}

test('advancing clock records upload eligibility time and returns a fresh lease projection',async()=>{
 const {io,worker}=await fixture(),ticks=[1029,1031,1031];worker.clock=()=>ticks.shift();
 const state=await worker.execute('ingest_artifact',upload),event=latest(io);
 assert.equal(event.at,1029);assert.equal(event.data.artifact.at,1029);assert.equal(state.tasks[0].artifact.at,1029);
 assert.equal(state.tasks[0].lease,null);assert.equal(state.tasks[0].status,'produced');
});

test('fractional renewal uses decision time even when the return projection is already expired',async()=>{
 const {io,worker}=await fixture(),ticks=[1029.5,1060,1060];worker.clock=()=>ticks.shift();
 const state=await worker.execute('claim_task',claim),event=latest(io);
 assert.equal(event.at,1029.5);assert.equal(event.data.lease.expires_at,1059.5);
 assert.equal(state.tasks[0].lease,null);assert.equal(state.tasks[0].status,'unclaimed');
});

test('exact fractional expiry blocks uploads and permits another actor to reclaim',async()=>{
 const {io,time,worker}=await fixture(1000.5);
 const other=new Engine({...io,actor:'other',role:'worker',clock:()=>time.now});
 time.now=1030.499;await worker.execute('ingest_artifact',upload);assert.equal(latest(io).at,1030.499);
 await assert.rejects(other.execute('claim_task',claim),{code:'LEASE_CONFLICT'});
 const before=JSON.stringify(io.events);time.now=1030.5;
 await assert.rejects(worker.execute('ingest_artifact',upload),{code:'LEASE_REQUIRED'});assert.equal(JSON.stringify(io.events),before);
 const state=await other.execute('claim_task',claim);assert.equal(state.tasks[0].lease.actor,'other');assert.equal(latest(io).data.lease.expires_at,1060.5);
 await assert.rejects(worker.execute('ingest_artifact',upload),{code:'LEASE_REQUIRED'});
});

test('decision time is captured after asynchronous state read and replay',async()=>{
 for(const phase of ['read','replay']){
  const {io,time,worker}=await fixture();time.now=1029;
  if(phase==='read'){
   const read=io.store.read;worker.store={...io.store,async read(){const rows=await read();time.now=1030;return rows;}};
  }else{
   const replay=worker.replay.bind(worker);worker.replay=async rows=>{const state=await replay(rows);time.now=1030;return state;};
  }
  await assert.rejects(worker.execute('ingest_artifact',upload),{code:'LEASE_REQUIRED'},phase);
  assert.equal(io.events.length,2);assert.equal(io.blobs.size,0);
 }
});

test('failed CAS retries recapture time and cannot keep an expired lease',async()=>{
 const {io,time,worker,owner}=await fixture();time.now=1029;let attempts=0,reads=0;
 worker.store={async read(){reads++;return io.store.read();},async append(expected,event){
  attempts++;if(attempts===1){time.now=1030;await owner.execute('request_decision',{task_id:'one',question:'Concurrent event'});}
  return io.store.append(expected,event);
 }};
 await assert.rejects(worker.execute('ingest_artifact',upload),{code:'LEASE_REQUIRED'});
 assert.equal(attempts,1);assert.equal(reads,2);assert.equal(io.events.length,3);
 assert.equal(latest(io).action,'request_decision');assert.equal((await owner.snapshot()).tasks[0].artifact,null);
});

test('a still-eligible CAS retry records its own new fractional decision time',async()=>{
 const {io,time,worker,owner}=await fixture();time.now=1028;let attempts=0;
 worker.store={...io.store,async append(expected,event){
  attempts++;if(attempts===1){time.now=1029.5;await owner.execute('request_decision',{task_id:'one',question:'Concurrent event'});}
  return io.store.append(expected,event);
 }};
 await worker.execute('ingest_artifact',upload);
 assert.equal(attempts,2);assert.equal(io.events.length,4);assert.equal(latest(io).at,1029.5);assert.equal(latest(io).data.artifact.at,1029.5);
});

test('invalid clocks consistently fail closed with BAD_CLOCK before any mutation',async()=>{
 const {io,worker}=await fixture(),before=JSON.stringify(io.events);
 for(const now of [undefined,null,'1029',true,{},NaN,Infinity,-Infinity]){
  worker.clock=()=>now;
  await assert.rejects(worker.execute('ingest_artifact',upload),{code:'BAD_CLOCK'});
  await assert.rejects(worker.snapshot(),{code:'BAD_CLOCK'});
  assert.equal(JSON.stringify(io.events),before);assert.equal(io.blobs.size,0);
 }
});

test('invalid return clocks reject candidate events before CAS append',async()=>{
 for(const invalid of [undefined,null,'1031',true,NaN,Infinity]){
  const {io,worker,owner}=await fixture(),before=JSON.stringify(io.events),ticks=[1029,invalid];
  let appends=0;worker.clock=()=>ticks.shift();
  worker.store={...io.store,async append(expected,event){appends++;return io.store.append(expected,event);}};
  await assert.rejects(worker.execute('ingest_artifact',upload),{code:'BAD_CLOCK'});
  assert.equal(JSON.stringify(io.events),before);assert.equal(appends,0);
  assert.equal((await owner.snapshot()).tasks[0].artifact,null);
 }
});

test('delayed append keeps decision metadata and the already sampled return projection',async()=>{
 const {io,time,worker}=await fixture();time.now=1029;
 let release,entered;
 const gate=new Promise(resolve=>{release=resolve;}),waiting=new Promise(resolve=>{entered=resolve;});
 worker.store={...io.store,async append(expected,event){entered();await gate;return io.store.append(expected,event);}};
 const pending=worker.execute('ingest_artifact',upload);
 await waiting;time.now=1031;release();
 const state=await pending,event=latest(io);
 assert.equal(event.at,1029);assert.equal(event.data.artifact.at,1029);
 assert.equal(state.tasks[0].lease?.actor,'maker','Lease status was sampled before append waited');
 assert.equal((await worker.snapshot()).tasks[0].lease,null,'A later snapshot reflects elapsed append time');
});

test('each CAS retry rebuilds its return projection with a fresh second clock',async()=>{
 const {io,worker,owner}=await fixture(),ticks=[1028,1028.5,1029.5,1031];let attempts=0;
 worker.clock=()=>ticks.shift();
 worker.store={...io.store,async append(expected,event){
  attempts++;if(attempts===1)await owner.execute('request_decision',{task_id:'one',question:'Concurrent event'});
  return io.store.append(expected,event);
 }};
 const state=await worker.execute('ingest_artifact',upload);
 assert.equal(attempts,2);assert.equal(ticks.length,0);
 assert.equal(state.events_count,4);assert.equal(state.ledger_head,io.events.at(-1).digest);
 assert.equal(latest(io).at,1029.5);assert.equal(latest(io).data.artifact.at,1029.5);
 assert.equal(state.tasks[0].lease,null);
});
