import test from 'node:test';
import assert from 'node:assert/strict';
import {compare,generate,step} from './semantic-stress-support.mjs';
const start=0x6d2b79f5;
test('independent invariants support replayed fractional lease timestamps',async()=>{
 const contract={project_id:'fractional-invariant',goal:'Check clocks',original_request:'Synthetic fixture',decision_owner:'owner',constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'x'}]}]};
 const result=await compare([step('create_contract',contract,'owner','human',1000.25),
  step('claim_task',{task_id:'one',contract_revision:1,lease_seconds:60},'maker','worker',1000.25),
  step('snapshot',{},'reader','viewer',1060.25)]);
 assert.equal(result.mismatch,-1);
});
for(let i=0;i<8;i++){
 const seed=(start+Math.imul(i,0x9e3779b9))>>>0;
 test('seeded owner/worker/reviewer parity seed '+seed,async()=>{
  const scenario=generate(seed,32),result=await compare(scenario.steps);
  assert.ok(result.results[scenario.acceptedAt].ok?.tasks.every(t=>t.status==='accepted'),'initial dependency workflow completed before disruption');
  assert.equal(result.mismatch,-1,'exact canonical result differs at step '+result.mismatch);
 });
}
