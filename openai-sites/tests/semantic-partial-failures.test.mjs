import test from 'node:test';
import assert from 'node:assert/strict';
import {Engine} from '../worker/engine.js';
import {actual,compare,hash,memory,step} from './semantic-stress-support.mjs';
const contract={project_id:'retry',goal:'Bounded work',original_request:'Recover interrupted writes',decision_owner:'owner',constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'hello'}]}]};
const setup=[step('create_contract',contract),step('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300},'maker','worker')];
const upload=()=>step('ingest_artifact',{task_id:'one',contract_revision:1,filename:'out.txt',content:'hello'},'maker','worker');
for(const fault of ['upload_before_write','upload_after_write'])test('Python parity: retry '+fault,async()=>{
 const op={...upload(),fault},steps=[...setup,op,step('snapshot'),upload(),step('run_checks',{task_id:'one',contract_revision:1,artifact_revision:1},'maker','worker'),step('decide',{task_id:'one',contract_revision:1,artifact_revision:1,outcome:'accepted',reason:'Verified retry'})];
 const result=await compare(steps);assert.equal(result.mismatch,-1);assert.equal(result.results[2].error,'PATH_UNSAFE');assert.equal(result.results[3].ok.events_count,2);assert.equal(result.results[4].ok.tasks[0].artifact.revision,1);assert.equal(result.results.at(-1).ok.tasks[0].status,'accepted');assert.equal(result.io.blobs.size,1);
});
for(const conflicts of [0,1,7,8])test('compare-and-swap conflict budget '+conflicts,async()=>{
 const io=memory();await actual(setup,{io});const append=io.store.append;let calls=0;io.store.append=async(...args)=>{calls++;return calls<=conflicts?false:append(...args)};
 const op=upload(),engine=new Engine({...io,actor:op.actor,role:op.role,clock:()=>1000}),before=hash(io.events);
 if(conflicts<8){const state=await engine.execute(op.action,op.args);assert.equal(state.events_count,3);assert.equal(state.tasks[0].artifact.revision,1);assert.equal(calls,conflicts+1)}
 else{await assert.rejects(()=>engine.execute(op.action,op.args),e=>e.code==='CONCURRENT_MODIFICATION');assert.equal(hash(io.events),before);assert.equal(calls,8);assert.equal(io.blobs.size,1);io.store.append=append;const state=await engine.execute(op.action,op.args);assert.equal(state.tasks[0].artifact.revision,1);assert.equal(state.events_count,3)}
 assert.equal(io.blobs.size,1,'same digest is not multiplied by retries');
});
test('committed upload with lost response remains observable; repeated upload has new revision',async()=>{
 const io=memory();await actual(setup,{io});const op=upload(),engine=new Engine({...io,actor:op.actor,role:op.role,clock:()=>1000});
 await assert.rejects(async()=>{await engine.execute(op.action,op.args);throw Error('Synthetic response loss')},/response loss/);
 const observed=await engine.snapshot();assert.equal(observed.events_count,3);assert.equal(observed.tasks[0].artifact.revision,1);
 const repeated=await engine.execute(op.action,op.args);assert.equal(repeated.tasks[0].artifact.revision,2);assert.equal(repeated.tasks[0].status,'produced');assert.equal(io.blobs.size,1);
});
