/** Synthetic offline fixtures. No Worker/server/runtime imports. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {Engine,RumboError} from '../worker/engine.js';
import {canonical,clone,parseJSON,FloatValue} from '../worker/codec.js';
export const hash=value=>createHash('sha256').update(canonical(value)).digest('hex');
export const step=(action,args={},actor='owner',role='human',now=1000)=>({action,args,actor,role,now});
export function memory(){const events=[],blobs=new Map();return {events,blobs,
 store:{async read(){return events.map(clone)},async append(expected,event){if(expected.count!==events.length||expected.head!==(events.at(-1)?.digest??'0'.repeat(64)))return false;events.push(clone(event));return true}},
 artifacts:{async put(digest,bytes){if(blobs.has(digest)&&!Buffer.from(blobs.get(digest)).equals(Buffer.from(bytes)))throw new RumboError('ARTIFACT_CORRUPT');blobs.set(digest,bytes.slice())},async get(digest){if(!blobs.has(digest))throw new RumboError('PATH_UNSAFE');return blobs.get(digest)}}};}
export function assertState(state,now){
 const tasks=new Map(state.tasks.map(t=>[t.id,t]));assert.equal(tasks.size,state.tasks.length);
 for(const task of tasks.values()){
  assert.equal(task.contract_revision,state.contract_revision,'contract revision projected consistently');
  if(task.lease){const expiry=task.lease.expires_at;assert.ok((expiry instanceof FloatValue?expiry.value:expiry)>now,'expired leases absent');}
  const blocked=task.dependencies.filter(id=>tasks.get(id).status!=='accepted');assert.equal(task.status==='blocked',blocked.length>0,'dependencies govern blocking');
  if(task.status==='accepted'){
   assert.ok(task.artifact);assert.equal(task.artifact.contract_revision,state.contract_revision);
   const current=new Map();for(const e of task.evidence)if(e.contract_revision===state.contract_revision&&e.artifact_revision===task.artifact.revision&&e.artifact_sha256===task.artifact.sha256)current.set(e.check_id,e);
   for(const c of task.acceptance)assert.equal(current.get(c.id)?.outcome,'pass','accepted task has passing current evidence');
   const d=task.decisions.filter(d=>d.contract_revision===state.contract_revision&&d.artifact_revision===task.artifact.revision&&d.artifact_sha256===task.artifact.sha256).at(-1);
   assert.equal(d?.outcome,'accepted');assert.equal(d.actor,state.decision_owner);assert.equal(d.role,'human');assert.deepEqual(d.evidence_ids,[...current.values()].map(e=>e.id).sort());
   for(const id of task.dependencies)assert.equal(canonical(task.artifact.dependencies[id]),canonical({artifact:tasks.get(id).artifact.sha256,decision:tasks.get(id).decisions.at(-1).id}),'exact upstream acceptance');
  }
  for(const e of task.evidence)if(e.kind==='reviewer_assertion')assert.equal(e.role,'reviewer');
 }
}
export async function actual(steps,{invariants=true,io=memory()}={}){
 const results=[],counts={actions:{},errors:{},statuses:{}};
 for(const [index,op] of steps.entries()){
  const before=hash(io.events),size=io.events.length;
  const artifacts=op.fault?{...io.artifacts,async put(digest,bytes){if(op.fault==='upload_after_write')await io.artifacts.put(digest,bytes);throw new RumboError('PATH_UNSAFE','Synthetic interrupted upload')}}:io.artifacts;
  const e=new Engine({...io,artifacts,actor:op.actor,role:op.role,clock:()=>op.now});let result;
  try{result={ok:op.action==='snapshot'?await e.snapshot():op.action==='read'?await e.artifactView(op.args):await e.execute(op.action,op.args)}}catch(error){result=error.code?{error:error.code}:{exception:error.constructor.name,message:error.message}}
  results.push(result);counts.actions[op.action]=(counts.actions[op.action]??0)+1;if(result.error)counts.errors[result.error]=(counts.errors[result.error]??0)+1;
  if(invariants){assert.ok(!result.exception,`Unhandled JS exception at step ${index}: ${canonical(result)}`);if(result.error||op.action==='snapshot'||op.action==='read')assert.equal(hash(io.events),before,'failed/read-only operation leaves ledger unchanged');else{assert.equal(io.events.length,size+1);assert.equal(io.events.at(-1).seq,io.events.length)}
   if(result.ok&&op.action!=='read'){assertState(result.ok,op.now);assert.equal(result.ok.events_count,io.events.length);assert.equal(result.ok.ledger_head,io.events.at(-1)?.digest??'0'.repeat(64));for(const t of result.ok.tasks)counts.statuses[t.status]=(counts.statuses[t.status]??0)+1;}
  }
 }
 return {results,counts,io};
}
export function oracle(steps,full=false){const result=spawnSync('python3',[fileURLToPath(new URL('./semantic-stress-oracle.py',import.meta.url))],{input:canonical({steps,full}),encoding:'utf8',maxBuffer:64*1024*1024});assert.equal(result.status,0,result.stderr);return parseJSON(result.stdout,128);}
export async function compare(steps,{invariants=true}={}){const observed=await actual(steps,{invariants}),expected=oracle(steps);return {...observed,mismatch:observed.results.findIndex((v,i)=>hash(v)!==expected[i].digest),expected};}
export function random(seed){let state=seed>>>0;return()=>{state^=state<<13;state^=state>>>17;state^=state<<5;return (state>>>0)/4294967296}}
export function generate(seed,randomSteps=64){
 const rng=random(seed),pick=vs=>vs[Math.floor(rng()*vs.length)],integer=max=>Math.floor(rng()*max),unicode=['é','e\u0301','😀','\ufeff','漢字','\u2028','\u007f','\u0085'];
 const values=['1','1.0','-0.0','9007199254740993','-9007199254740993','1e-7','1e20','null','false','[1,1.0,"😀"]','{"__proto__":{"safe":true},"😀":2,"￿":3}'];
 const count=1+integer(5),tasks=[],content={};
 for(let i=0;i<count;i++){const id='t'+i,value=parseJSON(pick(values)),marker='m'+pick(unicode),raw='{"value":'+canonical(value)+',"marker":'+JSON.stringify(marker)+'}';content[id]=raw;
  const acceptance=[{id:'json',kind:'json_equals',key:'value',value},{id:'text',kind:'file_contains',value:marker}];if(rng()<.7)acceptance.push({id:'review',kind:'manual_review',prompt:'Inspect '+marker});if(rng()<.5)acceptance.push({id:'sha',kind:'sha256',value:createHash('sha256').update(raw).digest('hex')});
  tasks.push({id,title:'Task '+i+' '+marker,dependencies:tasks.filter(()=>rng()<.4).map(t=>t.id),acceptance});}
 const contract={project_id:'seed-'+seed.toString(16),goal:'Generated bounded work',original_request:'Verify exact received bytes',decision_owner:'owner',constraints:['Synthetic only'],tasks,demo:true};
 const steps=[step('snapshot',{},'viewer','viewer'),step('create_contract',contract),step('create_contract',contract)];
 for(const task of tasks){const id=task.id,worker='maker-'+id;steps.push(step('decide',{task_id:id,contract_revision:1,artifact_revision:1,outcome:'accepted',reason:'Not owner'},worker,'worker'),step('request_decision',{task_id:id,question:'Ready? '+pick(unicode)},worker,'worker'),step('claim_task',{task_id:id,contract_revision:1,lease_seconds:3600},worker,'worker'),step('claim_task',{task_id:id,contract_revision:1,lease_seconds:300},'competitor','worker'),step('ingest_artifact',{task_id:id,contract_revision:1,filename:'result.json',content:content[id]},worker,'worker'),step('run_checks',{task_id:id,contract_revision:1,artifact_revision:1},worker,'worker'));
  if(task.acceptance.some(c=>c.kind==='manual_review')){const args={task_id:id,contract_revision:1,artifact_revision:1,check_id:'review',outcome:'pass',detail:'Independent synthetic reviewer'};steps.push(step('submit_review',args,worker,'reviewer'),step('submit_review',args,'reviewer','reviewer'))}
  steps.push(step('decide',{task_id:id,contract_revision:1,artifact_revision:1,outcome:'accepted',reason:'Exact artifact inspected'}),step('read',{task_id:id,contract_revision:1,artifact_revision:1},'viewer','viewer'));}
 const acceptedAt=steps.length;steps.push(step('snapshot',{},'viewer','viewer'));
 let revision=1,now=1000;
 for(let n=0;n<randomSteps;n++){const task=pick(tasks),id=task.id,worker='maker-'+id,kind=integer(14),rev=rng()<.2?Math.max(1,revision-1):revision,artifact_revision=pick([1,1,1,2,3]),actor=pick([worker,worker,'other','reviewer','owner']),role=actor==='owner'?'human':actor==='reviewer'?'reviewer':'worker',args={task_id:id,contract_revision:rev};
  if(kind===0){now+=pick([0,0.25,29,30.5,300,3600.25]);steps.push(step('claim_task',{...args,lease_seconds:pick([29,30,31,300,3600,3601])},actor,role,now))}
  else if(kind===1)steps.push(step('ingest_artifact',{...args,filename:pick(['result.json','same.txt','result.json','bad/name','empty.txt']),content:pick([content[id],content[id],'','{"value":false}','null','\ufeff'+content[id],'bad\ud800'])},actor,role,now));
  else if(kind===2||kind===3)steps.push(step('run_checks',{...args,artifact_revision},actor,role,now));
  else if(kind===4)steps.push(step('submit_review',{...args,artifact_revision,check_id:pick(['review','json','missing']),outcome:pick(['pass','fail','uncertain']),detail:'Review '+n},pick(['reviewer',worker]),'reviewer',now));
  else if(kind===5||kind===6)steps.push(step('decide',{...args,artifact_revision,outcome:pick(['accepted','rejected']),reason:'Decision '+n},'owner','human',now));
  else if(kind===7)steps.push(step('request_decision',{task_id:pick([id,'missing']),question:'Question '+n+' '+pick(unicode)},actor,role,now));
  else if(kind===8)steps.push(step('read',{...args,artifact_revision},'viewer','viewer',now));
  else if(kind===9){const replacement=clone(contract);if(n%2)delete replacement.demo;steps.push(step('revise_contract',{contract:replacement,expected_revision:revision,reason:'Replacement '+n},'owner','human',now));revision++}
  else if(kind===10)steps.push(step('claim_task',{...args,lease_seconds:30,extra:true},actor,role,now));
  else if(kind===11)steps.push(step('claim_task',{...args,contract_revision:parseJSON('1.0'),lease_seconds:30},actor,role,now));
  else if(kind===12)steps.push(step('request_decision',{task_id:id,question:'Read-only attempt'},'viewer','viewer',now));
  else steps.push(step('snapshot',{},'viewer','viewer',now));}
 steps.push(step('snapshot',{},'viewer','viewer',now+3601));return {seed,steps,acceptedAt};
}
