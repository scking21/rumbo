/** Bounded synthetic MCP traces for this hosted catalog, not live Site claims. */
import {readFileSync,writeFileSync} from 'node:fs';import {fileURLToPath} from 'node:url';import {resolve} from 'node:path';
import {fixture} from '../tests/support.mjs';import {subjectActor} from '../worker/storage.js';import {toolDefinitions} from '../worker/protocol.js';import worker from '../worker/index.js';
export const SYNTHETIC_TEXT='name,status\nsample,ready\n';
export async function runCases(){
 const cases=JSON.parse(readFileSync(new URL('../reviewer-cases.json',import.meta.url),'utf8')),results=[],protocol_results=[];
 for(const definition of [...cases.positive_cases,...cases.negative_cases]){
  const {env,storage,db}=fixture(),owner='review-owner',reviewer='reviewer-independent',actor=await subjectActor(owner);
  const contract={project_id:definition.initial_state.project_alias,goal:'Verify the exact synthetic export',original_request:'Synthetic QA only. No real project data.',decision_owner:actor,constraints:['No external actions'],tasks:[{id:'export',title:'Synthetic export',dependencies:[],acceptance:[{id:'csv',kind:'file_contains',value:SYNTHETIC_TEXT},{id:'quality',kind:'manual_review',prompt:'Inspect exact synthetic bytes'}]}]};
  const {project_key}=await storage.createProject(owner,contract.project_id,contract);const traces=[];
  // Only local fixture preparation: managed runs need an actual, already authorized reviewer connection.
  if(definition.id==='P5')await storage.setMember(owner,project_key,reviewer,'reviewer');
  const snapshot=async()=>await (await storage.engine(owner,project_key)).snapshot();
  const initial_state=await snapshot();
  const call=async(name,args,subject=owner,traceList=traces)=>{const response=await worker.fetch(new Request('https://synthetic.invalid/mcp',{method:'POST',headers:{'content-type':'application/json','oai-authenticated-user-id':subject,'oai-authenticated-user-email':subject+'@example.test'},body:JSON.stringify({jsonrpc:'2.0',id:traceList.length+1,method:'tools/call',params:{name,arguments:args}})}),env);const result=await response.json();traceList.push({tool:name,subject,http_status:response.status,arguments:args,response:result});return result;};
  let passed=false,worker_id;
  if(definition.id==='P1'){const listed=await call('rumbo_list_projects',{}),state=await call('rumbo_state',{project_key});passed=listed.result.structuredContent.projects.length===1&&state.result.structuredContent.contract_revision===1&&db.prepare('SELECT count(*) n FROM events').get().n===1;}
  else if(definition.id==='N1'){
   const result=await call('rumbo_state',{project_key}),state=result.result.structuredContent;
   // Rehearse the read-only boundary only. No local handler trace can grade a model's refusal/explanation.
   passed=!toolDefinitions().some(tool=>tool.name==='rumbo_decide')&&state.tasks[0].decisions.length===0&&state.events_count===initial_state.events_count&&state.ledger_head===initial_state.ledger_head;
   const assertion=cases.protocol_assertions.find(item=>item.id==='unknown-owner-decision-tool'),probeTraces=[],before=await snapshot();
   const probe=await call(assertion.tool,{project_key,task_id:'export',outcome:'accepted'},owner,probeTraces),after=await snapshot();
   protocol_results.push({id:assertion.id,related_case:definition.id,passed:probe.error?.code===assertion.expected_error.code&&probe.error?.message===assertion.expected_error.message&&after.events_count===before.events_count&&after.ledger_head===before.ledger_head&&after.tasks[0].decisions.length===0,before,after,traces:probeTraces});
  }
  else {
   worker_id=(await call('rumbo_open_worker',{project_key,label:'Synthetic '+definition.id})).result.structuredContent.worker_id;
   if(definition.id==='N3'){const ownerEngine=await storage.engine(owner,project_key,'human');await ownerEngine.execute('revise_contract',{contract,expected_revision:1,reason:'Synthetic owner revision fixture'});const result=await call('rumbo_claim_task',{project_key,worker_id,task_id:'export',contract_revision:1,lease_seconds:300});passed=result.result?.isError===true&&result.result.content[0].text.startsWith('STALE_CONTRACT');}
   else {
    const claim=await call('rumbo_claim_task',{project_key,worker_id,task_id:'export',contract_revision:1,lease_seconds:300});
    if(definition.id==='P2')passed=claim.result.structuredContent.tasks[0].status==='claimed';
    else {
     const uploaded=await call('rumbo_ingest_artifact',{project_key,worker_id,task_id:'export',contract_revision:1,filename:definition.upload.filename,content:definition.upload.content});
     if(definition.id==='P3')passed=uploaded.result.structuredContent.tasks[0].artifact.size===Buffer.byteLength(SYNTHETIC_TEXT,'utf8');
     else if(definition.id==='N2'){const result=await call('rumbo_submit_review',{project_key,task_id:'export',contract_revision:1,artifact_revision:1,check_id:'quality',outcome:'pass',detail:'Attempted self-review'});passed=result.result?.isError===true&&result.result.content[0].text.startsWith('FORBIDDEN');}
     else {
      if(definition.id==='P4')await call('rumbo_read_artifact',{project_key,task_id:'export',contract_revision:1,artifact_revision:1});
      const checked=await call('rumbo_run_checks',{project_key,worker_id,task_id:'export',contract_revision:1,artifact_revision:1});
      if(definition.id==='P4')passed=checked.result.structuredContent.tasks[0].evidence[0].outcome==='pass'&&checked.result.structuredContent.tasks[0].status==='produced'&&traces.find(t=>t.tool==='rumbo_read_artifact').response.result.structuredContent.text===SYNTHETIC_TEXT;
      else {const read=await call('rumbo_read_artifact',{project_key,task_id:'export',contract_revision:1,artifact_revision:1},reviewer);const reviewed=await call('rumbo_submit_review',{project_key,task_id:'export',contract_revision:1,artifact_revision:1,check_id:'quality',outcome:'pass',detail:'Separately attributed synthetic exact-byte review'},reviewer);const requested=await call('rumbo_request_decision',{project_key,worker_id,task_id:'export',question:'Please inspect the exact bytes and decide'});passed=read.result.structuredContent.text===SYNTHETIC_TEXT&&reviewed.result.structuredContent.tasks[0].status==='checks_passed'&&requested.result.structuredContent.tasks[0].decisions.length===0&&requested.result.structuredContent.requests.length===1;}
     }
    }
   }
  }
  results.push({id:definition.id,passed,expected:definition.expected,model_outcome:'not evaluated',initial_state,final_state:await snapshot(),traces});
 }
 return {profile:cases.profile,execution:'local synthetic Worker handler with SQLite/R2 fixtures; not managed OAuth or model inference',catalog:toolDefinitions(),results,protocol_results};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){const result=await runCases();if(process.argv[2])writeFileSync(process.argv[2],JSON.stringify(result,null,2)+'\n');console.log(result.results.map(r=>r.id+': '+(r.passed?'PASS':'FAIL')).join('\n'));console.log(result.protocol_results.map(r=>'Protocol '+r.id+': '+(r.passed?'PASS':'FAIL')).join('\n'));if([...result.results,...result.protocol_results].some(r=>!r.passed))process.exitCode=1;}
