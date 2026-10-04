/** Count real artifact decoding without replacing the parser or adding test hooks. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {Engine} from '../worker/engine.js';
import {canonical} from '../worker/codec.js';
import {memory,oracle,step} from './semantic-stress-support.mjs';

const digest=content=>createHash('sha256').update(content).digest('hex');
const jsonChecks=()=>Array.from({length:3},(_,i)=>({id:'json'+i,kind:'json_equals',key:'ok',value:true}));
const contract=checks=>({project_id:'cache',goal:'Exact checks',original_request:'Check all criteria',decision_owner:'owner',constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:checks}]});
const upload=content=>step('ingest_artifact',{task_id:'one',contract_revision:1,filename:'out.json',content},'maker','worker');
const check=(artifact_revision=1)=>step('run_checks',{task_id:'one',contract_revision:1,artifact_revision},'maker','worker');
const setup=(content,checks)=>[step('create_contract',contract(checks)),step('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300},'maker','worker'),upload(content)];

async function run(steps){
 const io=memory(),engines=new Map(),results=[],decodes=[];
 for(const op of steps){
  const key=op.actor+'/'+op.role;
  if(!engines.has(key))engines.set(key,new Engine({...io,actor:op.actor,role:op.role,clock:()=>1000}));
  const engine=engines.get(key),OriginalTextDecoder=globalThis.TextDecoder;let count=0;
  // Both JSON and file_contains use the real fatal UTF-8 decoder. Expected
  // counts include the independent text checks; ledger replay never uses it.
  globalThis.TextDecoder=class extends OriginalTextDecoder {decode(...args){count++;return super.decode(...args)}};
  try{results.push({ok:await engine.execute(op.action,op.args)})}finally{globalThis.TextDecoder=OriginalTextDecoder}
  if(op.action==='run_checks')decodes.push(count);
 }
 assert.equal(canonical(results),canonical(oracle(steps,true)),'complete states, evidence and ledger heads match Python');
 return {results,decodes};
}
const outcomes=result=>result.ok.tasks[0].evidence.map(e=>e.outcome);

test('mixed checks decode JSON once and preserve every receipt after a selected-value failure',async()=>{
 const content='{"ok":false,"ok":true,"bad":NaN}';
 const checks=[{id:'bad',kind:'json_equals',key:'bad',value:0},{id:'text',kind:'file_contains',value:'"ok"'},{id:'good',kind:'json_equals',key:'ok',value:true},{id:'review',kind:'manual_review',prompt:'Inspect'},{id:'sha',kind:'sha256',value:digest(content)},{id:'missing',kind:'json_equals',key:'missing',value:null}];
 const result=await run([...setup(content,checks),check()]);
 assert.deepEqual(outcomes(result.results.at(-1)),['fail','pass','pass','pass','fail']);
 assert.deepEqual(result.decodes,[2],'one JSON decode and one independent file_contains decode');
});

test('failed JSON parsing is cached while other criteria still produce evidence',async()=>{
 for(const content of ['{"ok":true,}','{"ok":true,"unused":"\\ud800","unused":0}','{"ok":true,"unused":'+'['.repeat(512)+'0'+']'.repeat(512)+'}','{"ok":true,"unused":'+'9'.repeat(4301)+'}']){
  const checks=[{id:'first',kind:'json_equals',key:'ok',value:true},{id:'sha',kind:'sha256',value:digest(content)},{id:'last',kind:'json_equals',key:'ok',value:true}];
  const result=await run([...setup(content,checks),check()]);
  assert.deepEqual(outcomes(result.results.at(-1)),['fail','pass','fail']);assert.deepEqual(result.decodes,[1]);
 }
});

test('null and other non-object JSON results are cached',async()=>{
 for(const content of ['null','false','1.0','[]']){
  const result=await run([...setup(content,jsonChecks()),check()]);
  assert.deepEqual(outcomes(result.results.at(-1)),['fail','fail','fail']);assert.deepEqual(result.decodes,[1]);
 }
});

test('later actions and replacements parse fresh bytes on the same engine',async()=>{
 const result=await run([...setup('{"ok":true}',jsonChecks()),check(),check(),upload('{"ok":false}'),check(2),upload('{"ok":'),check(3),upload('{"ok":true}'),check(4)]);
 assert.deepEqual(outcomes(result.results.at(-1)),['pass','pass','pass','pass','pass','pass','fail','fail','fail','fail','fail','fail','pass','pass','pass']);
 assert.deepEqual(result.decodes,[1,1,1,1,1]);
});

test('non-JSON criteria do not decode JSON',async()=>{
 const content='not JSON',checks=[{id:'sha',kind:'sha256',value:digest(content)},{id:'review',kind:'manual_review',prompt:'Inspect'}];
 const result=await run([...setup(content,checks),check()]);
 assert.deepEqual(outcomes(result.results.at(-1)),['pass']);assert.deepEqual(result.decodes,[0]);
});
