import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {Engine} from '../worker/engine.js';
import {canonical,parseJSON,clone} from '../worker/codec.js';
export function memoryStorage(){
 const events=[],blobs=new Map();return {
  events, blobs,
  store:{async read(){return events.map(clone);},async append(expected,event){if(events.length!==expected.count||(events.at(-1)?.digest??'0'.repeat(64))!==expected.head)return false;events.push(clone(event));return true;}},
  artifacts:{async put(digest,bytes){if(blobs.has(digest)&&Buffer.compare(Buffer.from(blobs.get(digest)),Buffer.from(bytes)))throw Object.assign(new Error(),{code:'ARTIFACT_CORRUPT'});blobs.set(digest,bytes.slice());},async get(digest){if(!blobs.has(digest))throw Object.assign(new Error(),{code:'PATH_UNSAFE'});return blobs.get(digest);}}
 };
}
export const contract=()=>({project_id:'example',goal:'Deliver bounded work',original_request:'Make it correct',decision_owner:'owner',constraints:['No external actions'],tasks:[{id:'one',title:'First artifact',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'hello'},{id:'review',kind:'manual_review',prompt:'Check details'}]},{id:'two',title:'Follow on',dependencies:['one'],acceptance:[{id:'json',kind:'json_equals',key:'ok',value:true}]}]});
const step=(action,args={},actor='owner',role='human',now=1000)=>({action,args,actor,role,now});
const claim=(actor='maker',task_id='one',now=1000)=>step('claim_task',{task_id,contract_revision:1,lease_seconds:300},actor,'worker',now);
const upload=(content='hello',revision=1)=>step('ingest_artifact',{task_id:'one',contract_revision:revision,filename:'output.txt',content},'maker','worker');
const checks=()=>step('run_checks',{task_id:'one',contract_revision:1,artifact_revision:1},'maker','worker');
const review=(actor='reviewer')=>step('submit_review',{task_id:'one',contract_revision:1,artifact_revision:1,check_id:'review',outcome:'pass',detail:'Synthetic review'},actor,'reviewer');
const decide=(outcome='accepted')=>step('decide',{task_id:'one',contract_revision:1,artifact_revision:1,outcome,reason:'Owner inspected bytes'});
async function actual(steps){const io=memoryStorage(),out=[];for(const op of steps){const e=new Engine({...io,actor:op.actor,role:op.role,clock:()=>op.now});try{out.push({ok:op.action==='snapshot'?await e.snapshot():op.action==='read'?await e.artifactView(op.args):await e.execute(op.action,op.args)});}catch(e){if(!e.code)throw e;out.push({error:e.code});}}return parseJSON(canonical(out));}
function oracle(steps){const r=spawnSync('python3',['tests/oracle.py'],{input:canonical({mode:'steps',steps}),encoding:'utf8'});assert.equal(r.status,0,r.stderr);return parseJSON(r.stdout);}
const scenarios={
 'complete owner/worker/reviewer workflow':[step('create_contract',contract()),claim(),upload(),checks(),review(),decide(),step('read',{task_id:'one',contract_revision:1,artifact_revision:1}),claim('next','two')],
 'role, claim and self-review failures':[step('create_contract',contract()),claim(),claim('other'),upload(),checks(),review('maker'),step('decide',decide().args,'maker','worker'),decide(),step('snapshot')],
 'leases expire and refresh':[step('create_contract',contract()),claim(),claim('other','one',1299),claim('other','one',1300),upload(),step('snapshot',{},'viewer','viewer',1601)],
 'revisions invalidate artifact and evidence':[step('create_contract',contract()),claim(),upload(),checks(),review(),decide(),step('revise_contract',{contract:contract(),expected_revision:1,reason:'Clarify contract'}),checks(),upload(),step('snapshot')],
 'replacement artifacts cannot inherit evidence':[step('create_contract',contract()),claim(),upload(),checks(),review(),decide(),upload('hello revised'),decide(),step('read',{task_id:'one',contract_revision:1,artifact_revision:1})],
 'request decisions has no approval power':[step('create_contract',contract()),step('request_decision',{task_id:'one',question:'Which output?'},'maker','worker'),claim('maker','two')],
};
for(const [name,steps] of Object.entries(scenarios))test('Python parity: '+name,async()=>assert.deepEqual(await actual(steps),oracle(steps)));
test('validation failures match canonical engine',async()=>{
 const mutations=[c=>c.tasks[0].dependencies.push('missing'),c=>c.tasks[0].dependencies.push('two'),c=>c.decision_owner='imposter',c=>c.extra='no',c=>c.tasks[0].acceptance[0].kind='shell',c=>c.tasks[0].acceptance[0].value='',c=>c.demo=1,c=>c.tasks[0].id='bad/id',c=>c.tasks[0].acceptance.push(c.tasks[0].acceptance[0])];
 for(const mutate of mutations){const c=contract();mutate(c);const steps=[step('create_contract',c)];assert.deepEqual(await actual(steps),oracle(steps));}
});
test('competing claims append only one winner; ledger replay detects corruption',async()=>{
 const io=memoryStorage();const owner=new Engine({...io,actor:'owner',role:'human',clock:()=>1000});await owner.execute('create_contract',contract());
 const results=await Promise.allSettled(['a','b','c','d'].map(actor=>new Engine({...io,actor,role:'worker',clock:()=>1000}).execute('claim_task',claim().args)));
 assert.equal(results.filter(r=>r.status==='fulfilled').length,1);assert.ok(results.filter(r=>r.status==='rejected').every(r=>r.reason.code==='LEASE_CONFLICT'));assert.equal(io.events.length,2);
 io.events[0].payload=io.events[0].payload.replace('Deliver bounded','Tampered bounded');await assert.rejects(()=>owner.snapshot(),e=>e.code==='LEDGER_CORRUPT');
});
test('immutable artifact corruption is stale and blocks checks',async()=>{
 const io=memoryStorage();let engine;for(const op of scenarios['complete owner/worker/reviewer workflow'].slice(0,3)){engine=new Engine({...io,actor:op.actor,role:op.role,clock:()=>1000});await engine.execute(op.action,op.args);}
 const s=await engine.snapshot();io.blobs.set(s.tasks[0].artifact.sha256,new TextEncoder().encode('changed'));
 assert.equal((await engine.snapshot()).tasks[0].status,'stale');await assert.rejects(()=>engine.execute('run_checks',checks().args),e=>e.code==='ARTIFACT_CHANGED');
});

test('artifact JSON parsing and text bytes preserve Python semantics',async()=>{
 const cases=[['hello\ufeff','hello'],['\ufeffhello','\ufeff'],['😀','\ud83d']];
 for(const [content,needle] of cases){const c=contract();c.tasks[0].acceptance=[{id:'text',kind:'file_contains',value:needle}];const steps=[step('create_contract',c),claim(),upload(content),checks(),step('read',{task_id:'one',contract_revision:1,artifact_revision:1})];assert.deepEqual(await actual(steps),oracle(steps));}
 for(const content of ['{"ok":false,"ok":true}','{"ok":true,"unused":'+ '['.repeat(65)+'0'+']'.repeat(65)+'}','{"ok":true,"unused":NaN}','{"ok":true,"unused":1e999}','\ufeff{"ok":true}']){const c=contract();c.tasks[0].acceptance=[{id:'json',kind:'json_equals',key:'ok',value:true}];const steps=[step('create_contract',c),claim(),upload(content),checks()];assert.deepEqual(await actual(steps),oracle(steps));}
});

test('a top-level JSON float is never mistaken for an object with a value field',async()=>{const c=contract();c.tasks[0].acceptance=[{id:'json',kind:'json_equals',key:'value',value:1}];const steps=[step('create_contract',c),claim(),upload('1.0'),checks()];assert.deepEqual(await actual(steps),oracle(steps));});

test('fractional lease clocks expire at the exact boundary after canonical replay',async()=>{
 const args={task_id:'one',contract_revision:1,lease_seconds:60};
 const steps=[step('create_contract',contract(),'owner','human',1000.5),
  step('claim_task',args,'maker','worker',1000.5),
  step('snapshot',{},'reader','viewer',1060.49),
  step('claim_task',args,'other','worker',1060.49),
  step('claim_task',args,'other','worker',1060.5),
  step('snapshot',{},'reader','viewer',1120.5)];
 assert.deepEqual(await actual(steps),oracle(steps));
});
test('check-kind validation rejects non-string JSON values with canonical BAD_INPUT errors',async()=>{
 for(const kind of [[],['file_contains'],['sha256'],{}, {toString:null},null,0,true]){
  const c=contract();c.tasks[0].acceptance[0].kind=kind;const steps=[step('create_contract',c)];
  assert.deepEqual(await actual(steps),oracle(steps),'kind='+JSON.stringify(kind));
 }
});

const childUpload=()=>step('ingest_artifact',{task_id:'two',contract_revision:1,filename:'child.json',content:'{"ok":true}'},'next','worker');
const childChecks=artifact_revision=>step('run_checks',{task_id:'two',contract_revision:1,artifact_revision},'next','worker');
const childDecision=artifact_revision=>step('decide',{task_id:'two',contract_revision:1,artifact_revision,outcome:'accepted',reason:'Exact downstream revision inspected'});
const workflowScenarios={
 'rejecting and reaccepting a dependency requires downstream resubmission':[
  ...scenarios['complete owner/worker/reviewer workflow'],childUpload(),childChecks(1),childDecision(1),decide('rejected'),step('snapshot'),decide(),childChecks(1),childUpload(),childChecks(2),childDecision(2),step('snapshot')
 ],
 'rerunning checks invalidates the exact earlier acceptance and dependent work':[
  ...scenarios['complete owner/worker/reviewer workflow'],childUpload(),childChecks(1),childDecision(1),checks(),step('snapshot'),decide(),step('snapshot')
 ],
 'latest uncertain reviewer assertion supersedes an earlier passing review':[
  ...scenarios['complete owner/worker/reviewer workflow'],step('submit_review',{...review().args,outcome:'uncertain',detail:'A later review needs owner clarification'},'reviewer','reviewer'),decide(),step('snapshot'),review(),decide()
 ],
 'same-content upload replacement still requires fresh revision-bound evidence':[
  ...scenarios['complete owner/worker/reviewer workflow'].slice(0,6),upload(),decide(),step('read',{task_id:'one',contract_revision:1,artifact_revision:2}),step('run_checks',{...checks().args,artifact_revision:2},'maker','worker'),step('submit_review',{...review().args,artifact_revision:2},'reviewer','reviewer'),step('decide',{...decide().args,artifact_revision:2})
 ],
};
for(const [name,steps] of Object.entries(workflowScenarios))test('Python workflow parity: '+name,async()=>assert.deepEqual(await actual(steps),oracle(steps)));

test('UTF-8 upload limits use received bytes at the exact multibyte boundary',async()=>{
 for(const count of [32768,32769]){const c=contract();c.tasks[0].acceptance=[{id:'text',kind:'file_contains',value:'😀'}];const steps=[step('create_contract',c),claim(),upload('😀'.repeat(count)),checks(),step('snapshot')];assert.deepEqual(await actual(steps),oracle(steps));}
});

test('removing and later restoring a task does not revive its old acceptance',async()=>{
 const c=contract(),reduced={...c,tasks:[{...c.tasks[1],dependencies:[]}]};
 const steps=[...scenarios['complete owner/worker/reviewer workflow'].slice(0,6),step('revise_contract',{contract:reduced,expected_revision:1,reason:'Remove first task'}),step('revise_contract',{contract:c,expected_revision:2,reason:'Restore task as new work'}),step('snapshot')];assert.deepEqual(await actual(steps),oracle(steps));
});
test('complete contract replacement resets an omitted demo flag to the canonical default',async()=>{
 const synthetic={...contract(),demo:true};const steps=[step('create_contract',synthetic),step('revise_contract',{contract:contract(),expected_revision:1,reason:'Replace complete synthetic scope'}),step('snapshot')];
 assert.deepEqual(await actual(steps),oracle(steps));
});
