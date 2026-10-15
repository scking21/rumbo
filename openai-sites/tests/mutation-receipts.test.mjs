import test from 'node:test';
import assert from 'node:assert/strict';
import {dispatch,toolDefinitions} from '../worker/protocol.js';
import {Storage,subjectActor} from '../worker/storage.js';
import {fixture} from './support.mjs';
const origin='https://rumbo.test';
const contract=async()=>({project_id:'receipts',goal:'Exact synthetic workflow',original_request:'Keep all evidence and human decisions',decision_owner:await subjectActor('owner'),constraints:['No new permissions'],tasks:[
 {id:'one',title:'One',dependencies:[],acceptance:[{id:'contains',kind:'file_contains',value:'hello'},{id:'review',kind:'manual_review',prompt:'Inspect exact bytes'}]},
 {id:'two',title:'Two',dependencies:['one'],acceptance:[{id:'contains',kind:'file_contains',value:'hello'}]}
]});
const claim={task_id:'one',contract_revision:1,lease_seconds:300},exact={task_id:'one',contract_revision:1,artifact_revision:1};
const mutationNames=['rumbo_claim_task','rumbo_ingest_artifact','rumbo_run_checks','rumbo_submit_review','rumbo_request_decision'];
function timed(storage,clock){
 for(const method of ['engine','workerEngine','reviewerEngine']){
  const original=storage[method].bind(storage);storage[method]=async(...args)=>{const engine=await original(...args);engine.clock=clock;return engine;};
 }
 return storage;
}
async function setup(){
 const f=fixture(),c=await contract(),p=await f.storage.createProject('owner',c.project_id,c);
 await f.storage.setMember('owner',p.project_key,'reviewer','reviewer');
 const session=await f.storage.openWorker('owner',p.project_key,'Maker');
 let now=1000;timed(f.storage,()=>now);
 const owner=await f.storage.engine('owner',p.project_key,'human');
 return {...f,c,p,session,owner,setTime:value=>now=value};
}
async function call(f,name,args={},mode='receipt',subject='owner',id=1){
 const arguments_={...args,...(mode===null?{}:{response_mode:mode})},before=structuredClone(arguments_);
 const result=await dispatch({jsonrpc:'2.0',id,method:'tools/call',params:{name,arguments:arguments_}},{storage:f.storage,subject,origin});
 assert.deepEqual(arguments_,before,'Do not mutate client arguments');assert.equal(result.id,id);return result.result;
}
function receiptInvariant(receipt,state,name,project_key,task_id='one'){
 const task=state.tasks.find(t=>t.id===task_id),a=task.artifact;
 assert.equal(receipt.kind,'rumbo.mutation_receipt.v1');assert.equal(receipt.complete,false);assert.equal(receipt.observation,'operation_response_only');
 assert.equal(receipt.operation,name);assert.equal(receipt.project_id,state.project_id);assert.equal(receipt.contract_revision,state.contract_revision);
 assert.equal(receipt.task_id,task_id);assert.equal(receipt.task_status,task.status);assert.equal(receipt.human_decision_recorded,false);
 assert.deepEqual(receipt.artifact,a?{revision:a.revision,contract_revision:a.contract_revision,sha256:a.sha256}:null);
 assert.deepEqual(receipt.ledger,{events_count:state.events_count,head:state.ledger_head});
 assert.deepEqual(receipt.recovery,{tool:'rumbo_state',arguments:{project_key}});
 for(const marker of ['Incomplete','other tasks','evidence and human decisions','recorded identity, not fresh verification','earlier human decision','not cache validity','lost response','not idempotent','not authorization'])assert.ok(receipt.notice.includes(marker),marker);
 for(const key of ['goal','tasks','requests','evidence','decisions'])assert.equal(Object.hasOwn(receipt,key),false);
}
const scoped=(f,args,review=false)=>({project_key:f.p.project_key,...(review?{}:{worker_id:f.session.worker_id}),...args});

test('hosted optional schema preserves required fields, authority and special tools',()=>{
 for(const tool of toolDefinitions()){
  assert.equal(tool.inputSchema.required.includes('response_mode'),false);
  assert.equal(Object.hasOwn(tool.inputSchema.properties,'response_mode'),mutationNames.includes(tool.name));
  if(mutationNames.includes(tool.name)){
   assert.deepEqual(tool.inputSchema.properties.response_mode.enum,['snapshot','receipt']);
   assert.equal(tool.annotations.idempotentHint,false);assert.ok(tool.inputSchema.required.includes('project_key'));
   assert.equal(tool.inputSchema.required.includes('worker_id'),tool.name!=='rumbo_submit_review');
  }
 }
 assert.deepEqual(toolDefinitions().find(t=>t.name==='open_project_board').inputSchema.required,[]);
});
test('invalid mode fails before storage access, upload or mutation for every hosted mutation',async()=>{
 const storage=new Proxy({},{get(){throw new Error('Storage must not be touched for invalid mode');}});
 for(const tool of toolDefinitions().filter(t=>mutationNames.includes(t.name))){
  const args=Object.fromEntries(tool.inputSchema.required.map(key=>[key,tool.inputSchema.properties[key].type==='integer'?1:'one']));
  for(const mode of [null,'','Receipt','compact',1,false,[],{},['receipt']]){
   const result=await dispatch({jsonrpc:'2.0',id:1,method:'tools/call',params:{name:tool.name,arguments:{...args,response_mode:mode}}},{storage,subject:'owner',origin});
   assert.equal(result.result.isError,true);assert.match(result.result.content[0].text,/BAD_INPUT: response_mode/);
  }
 }
});
test('read/board/list/open-worker tools reject irrelevant mode without minting a worker',async()=>{
 const f=await setup();try{
  const before=f.db.prepare('SELECT total_changes() AS n').get().n;
  for(const [name,args] of [['rumbo_state',{project_key:f.p.project_key}],['open_project_board',{}],['rumbo_list_projects',{}],['rumbo_read_artifact',{project_key:f.p.project_key,...exact}],['rumbo_open_worker',{project_key:f.p.project_key,label:'Do not create'}]]){
   const result=await call(f,name,args);assert.equal(result.isError,true);assert.match(result.content[0].text,/UNKNOWN_FIELD: response_mode/);
  }
  assert.equal(f.db.prepare('SELECT total_changes() AS n').get().n,before);
 }finally{f.db.close();}
});
async function workflow(mode){
 const f=await setup(),responses=[],states=[];
 try{
  const doAction=async(action,args,subject='owner')=>{
   const name='rumbo_'+action,result=await call(f,name,scoped(f,args,action==='submit_review'),mode,subject);
   assert.equal(result.isError,false,JSON.stringify(result));
   const state=await f.owner.snapshot();states.push(state);responses.push(result);
   if(mode==='receipt'){
    receiptInvariant(result.structuredContent,state,name,f.p.project_key,args.task_id);
    const recovery=result.structuredContent.recovery,read=await call(f,recovery.tool,recovery.arguments,null,subject);
    const {hosted_project_key,owner_review_url,hosted_notice,...raw}=read.structuredContent;
    assert.deepEqual(raw,state);assert.equal(hosted_project_key,f.p.project_key);
   }else{
    const expected={content:[{type:'text',text:'Rumbo returned the requested project record. Evidence is not authorization.'}],structuredContent:{...state,hosted_project_key:f.p.project_key,owner_review_url:origin+'/?project_key='+f.p.project_key,hosted_notice:'Uploaded bytes only. Local file changes are not observable by this service.'},isError:false};
    assert.equal(JSON.stringify(result),JSON.stringify(expected));
   }
   return result.structuredContent;
  };
  const human=async(action,args)=>states.push(await f.owner.execute(action,args));
  await doAction('claim_task',claim);
  await doAction('ingest_artifact',{task_id:'one',contract_revision:1,filename:'one.txt',content:'hello exact bytes'});
  await doAction('run_checks',exact);
  await doAction('submit_review',{...exact,check_id:'review',outcome:'pass',detail:'Exact synthetic bytes'},'reviewer');
  await doAction('request_decision',{task_id:'one',question:'Accept this exact revision?'});
  await human('decide',{...exact,outcome:'accepted',reason:'Owner inspected exact bytes'});
  const accepted=await doAction('request_decision',{task_id:'one',question:'Keep accepted work?'});
  if(mode==='receipt'){assert.equal(accepted.task_status,'accepted');assert.equal(accepted.human_decision_recorded,false);}
  await doAction('claim_task',{...claim,task_id:'two'});
  await doAction('ingest_artifact',{task_id:'two',contract_revision:1,filename:'two.txt',content:'hello dependent'});
  await doAction('run_checks',{...exact,task_id:'two'});
  await human('decide',{...exact,task_id:'two',outcome:'accepted',reason:'Owner inspected dependency'});
  await doAction('ingest_artifact',{task_id:'one',contract_revision:1,filename:'one.txt',content:'hello exact bytes'});
  assert.equal(states.at(-1).tasks[1].status,'blocked','Target receipt cannot represent downstream status');
  await doAction('run_checks',{...exact,artifact_revision:2});
  await doAction('submit_review',{...exact,artifact_revision:2,check_id:'review',outcome:'pass',detail:'Same bytes new revision'},'reviewer');
  await human('decide',{...exact,artifact_revision:2,outcome:'rejected',reason:'Owner rejected'});
  await human('decide',{...exact,artifact_revision:2,outcome:'accepted',reason:'Owner reconsidered'});
  await human('revise_contract',{contract:f.c,expected_revision:1,reason:'Owner changed scope'});
  await doAction('request_decision',{task_id:'one',question:'Review revised contract?'});
  await doAction('claim_task',{...claim,contract_revision:2});
  await doAction('ingest_artifact',{task_id:'one',contract_revision:2,filename:'one.txt',content:'hello new bytes'});
  await doAction('run_checks',{...exact,contract_revision:2,artifact_revision:3});
  await doAction('submit_review',{...exact,contract_revision:2,artifact_revision:3,check_id:'review',outcome:'pass',detail:'New exact bytes'},'reviewer');
  assert.equal(states.at(-1).tasks[0].decisions.length,3);
  const engine=await timed(new Storage(f.env),()=>1000).engine('owner',f.p.project_key);
  assert.deepEqual(await engine.snapshot(),states.at(-1));
  const view=await engine.artifactView({...exact,contract_revision:2,artifact_revision:3});assert.equal(view.text,'hello new bytes');
  return {responses,states,view,rows:f.db.prepare('SELECT seq,payload,previous,digest FROM events ORDER BY seq').all(),objects:[...f.objects].map(([key,value])=>[key,[...value]])};
 }finally{f.db.close();}
}
test('all hosted mutations preserve exact default bytes, poststate, history, dependencies, artifacts and restart',async t=>{
 const now=Date.now();t.mock.method(Date,'now',()=>now);t.mock.method(crypto,'randomUUID',()=> '00000000-0000-4000-8000-000000000001');
 const defaults=await workflow(null),explicit=await workflow('snapshot'),receipts=await workflow('receipt');
 assert.equal(JSON.stringify(defaults),JSON.stringify(explicit));
 const {responses:defaultResponses,...defaultState}=defaults,{responses:receiptResponses,...receiptState}=receipts;
 assert.deepEqual(defaultState,receiptState);assert.equal(defaultResponses.length,receiptResponses.length);
});
test('stale, corrupt, role and project failures are unchanged and do not write',async()=>{
 const f=await setup();try{
  await call(f,'rumbo_claim_task',scoped(f,claim));
  await call(f,'rumbo_ingest_artifact',scoped(f,{task_id:'one',contract_revision:1,filename:'one.txt',content:'hello exact bytes'}));
  const cases=[
   ['rumbo_claim_task',scoped(f,{...claim,contract_revision:2}),'owner','STALE_CONTRACT'],
   ['rumbo_run_checks',scoped(f,{...exact,artifact_revision:2}),'owner','STALE_ARTIFACT'],
   ['rumbo_submit_review',scoped(f,{...exact,check_id:'review',outcome:'pass',detail:'Unauthorized'},true),'owner','FORBIDDEN'],
   ['rumbo_request_decision',scoped(f,{task_id:'one',question:'No permission'}),'outsider','FORBIDDEN'],
   ['rumbo_claim_task',{...scoped(f,claim),role:'human'},'owner','UNKNOWN_FIELD'],
   ['rumbo_claim_task',{...scoped(f,claim),project_key:'alias'},'owner','BAD_INPUT']
  ];
  const state=await f.owner.snapshot();f.objects.set(f.p.project_key+'/'+state.tasks[0].artifact.sha256,new TextEncoder().encode('corrupt bytes'));
  cases.push(['rumbo_run_checks',scoped(f,exact),'owner','ARTIFACT_CORRUPT']);
  const before=f.db.prepare('SELECT total_changes() AS n').get().n,objects=[...f.objects];
  for(const [name,args,subject,code] of cases){
   const results=[];for(const mode of [null,'snapshot','receipt'])results.push(await call(f,name,args,mode,subject));
   assert.deepEqual(results[0],results[1]);assert.deepEqual(results[1],results[2]);assert.equal(results[0].isError,true);assert.ok(results[0].content[0].text.includes(code),JSON.stringify(results));
  }
  assert.equal(f.db.prepare('SELECT total_changes() AS n').get().n,before);assert.deepEqual([...f.objects],objects);
 }finally{f.db.close();}
});
test('lossy context/recovery mutants cannot satisfy receipt contract',async()=>{
 const f=await setup();try{
  const receipt=(await call(f,'rumbo_claim_task',scoped(f,claim))).structuredContent,state=await f.owner.snapshot();
  for(const [key,value] of [['complete',true],['notice',''],['recovery',{tool:'rumbo_state',arguments:{project_key:'wrong'}}],['recovery',{tool:'rumbo_open_worker',arguments:{project_key:f.p.project_key,label:'Replacement'}}],['human_decision_recorded',true],['observation','cache_valid']])assert.throws(()=>receiptInvariant({...receipt,[key]:value},state,'rumbo_claim_task',f.p.project_key));
  for(const key of ['kind','complete','recovery','notice','ledger','artifact']){const mutant={...receipt};delete mutant[key];assert.throws(()=>receiptInvariant(mutant,state,'rumbo_claim_task',f.p.project_key));}
 }finally{f.db.close();}
});
test('same ledger head does not validate cached lease projection',async()=>{
 const f=await setup();try{
  const receipt=(await call(f,'rumbo_claim_task',scoped(f,claim))).structuredContent;
  f.setTime(1300);const read=await call(f,receipt.recovery.tool,receipt.recovery.arguments,null);
  assert.equal(receipt.ledger.head,read.structuredContent.ledger_head);assert.equal(receipt.task_status,'claimed');assert.equal(read.structuredContent.tasks[0].status,'unclaimed');
 }finally{f.db.close();}
});
test('lost reply is read back in exact project before unsafe retry, without minting identity',async()=>{
 const f=await setup();try{
  const result=await call(f,'rumbo_request_decision',scoped(f,{task_id:'one',question:'One request only'}));
  const workers=f.db.prepare('SELECT count(*) AS n FROM workers').get().n;
  const read=await call(f,'rumbo_state',{project_key:f.p.project_key},null,'owner','x'.repeat(65536));
  assert.equal(read.structuredContent.requests.length,1);assert.equal(read.structuredContent.events_count,2);
  assert.equal(f.db.prepare('SELECT count(*) AS n FROM workers').get().n,workers);
  assert.deepEqual(result.structuredContent.recovery.arguments,{project_key:f.p.project_key});
 }finally{f.db.close();}
});
