/** Experimental hosted implementation. Python core.py remains the parity oracle.
 * Authority is supplied by the verified host, never by action arguments.
 */
import {canonical,parseJSON,clone,sha256,utf8,FloatValue} from './codec.js';
export const MAX_INGEST=128*1024, MAX_EVENTS=10000, MAX_LEDGER_BYTES=16*1024*1024;
export class RumboError extends Error { constructor(code,message=''){super(code+': '+(message||code.toLowerCase().replaceAll('_',' ')));this.code=code;} }
export function fail(code,message=''){throw new RumboError(code,message);}
export function fields(value,required,optional=[]){
 if(!value||typeof value!=='object'||Array.isArray(value)||value instanceof FloatValue)fail('BAD_INPUT','Expected an object');
 const unknown=Object.keys(value).filter(k=>!required.includes(k)&&!optional.includes(k));
 if(unknown.length)fail('UNKNOWN_FIELD',unknown.sort().join(', '));
 const missing=required.filter(k=>!Object.hasOwn(value,k));if(missing.length)fail('MISSING_FIELD',missing.sort().join(', '));
}
function string(value,name,limit=4000){if(typeof value!=='string'||!(/[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u).test(value)||[...value].length>limit||value.includes('\0'))fail('BAD_INPUT',`${name} must be nonempty text (max ${limit})`);return value;}
export function identifier(value,name='identifier'){if(typeof value!=='string'||!(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/).test(value))fail('BAD_INPUT','Invalid '+name);return value;}
function integer(value,name,min=1,max=1000000000){if(typeof value!=='number'||!Number.isInteger(value)||value<min||value>max)fail('BAD_INPUT',name+' is outside its integer range');return value;}
export const ACTION_FIELDS={
 create_contract:[['project_id','goal','original_request','decision_owner','constraints','tasks'],['demo']],
 revise_contract:[['contract','expected_revision','reason'],[]],claim_task:[['task_id','contract_revision','lease_seconds'],[]],
 ingest_artifact:[['task_id','contract_revision','filename','content'],[]],run_checks:[['task_id','contract_revision','artifact_revision'],[]],
 submit_review:[['task_id','contract_revision','artifact_revision','check_id','outcome','detail'],[]],request_decision:[['task_id','question'],[]],
 decide:[['task_id','contract_revision','artifact_revision','outcome','reason'],[]],
};
export function validateContract(data,actor){
 fields(data,...ACTION_FIELDS.create_contract);identifier(data.project_id,'project_id');string(data.goal,'goal');string(data.original_request,'original_request',16000);identifier(data.decision_owner,'decision_owner');
 if(data.decision_owner!==actor)fail('FORBIDDEN','The authenticated decision owner must own the contract');
 if(Object.hasOwn(data,'demo')&&typeof data.demo!=='boolean')fail('BAD_INPUT','demo must be boolean');
 if(!Array.isArray(data.constraints)||data.constraints.length>50)fail('BAD_INPUT','constraints must be an array of at most 50 strings');
 for(const v of data.constraints)string(v,'constraint');
 if(!Array.isArray(data.tasks)||data.tasks.length<1||data.tasks.length>100)fail('BAD_INPUT','Include 1 to 100 bounded tasks');
 const ids=new Set();
 for(const task of data.tasks){
  fields(task,['id','title','dependencies','acceptance']);identifier(task.id,'task id');string(task.title,'task title');if(ids.has(task.id))fail('BAD_INPUT','Duplicate task id');ids.add(task.id);
  if(!Array.isArray(task.dependencies)||task.dependencies.length>100)fail('BAD_INPUT','Invalid dependencies');for(const dep of task.dependencies)identifier(dep,'dependency');if(new Set(task.dependencies).size!==task.dependencies.length)fail('BAD_INPUT','Duplicate dependency');
  if(!Array.isArray(task.acceptance)||task.acceptance.length<1||task.acceptance.length>30)fail('BAD_INPUT','Include 1 to 30 acceptance checks');
  const seen=new Set();
  for(const check of task.acceptance){
   if(!check||typeof check!=='object'||Array.isArray(check))fail('BAD_INPUT','Acceptance must contain objects');
   const extras={file_contains:['value'],json_equals:['key','value'],sha256:['value'],manual_review:['prompt']};
   if(!Object.hasOwn(extras,check.kind))fail('BAD_INPUT','Unsupported check kind');
   fields(check,['id','kind',...extras[check.kind]]);identifier(check.id,'check id');if(seen.has(check.id))fail('BAD_INPUT','Duplicate check id');seen.add(check.id);
   if(['file_contains','sha256'].includes(check.kind))string(check.value,'check value',16000);
   if(check.kind==='sha256'&&!/^[a-f0-9]{64}$/.test(check.value))fail('BAD_INPUT','sha256 must be a lowercase digest');
   if(check.kind==='json_equals'){string(check.key,'JSON top-level key',256);if(canonical(check.value).length>16000)fail('BAD_INPUT','JSON expected value too large');}
   if(check.kind==='manual_review')string(check.prompt,'review prompt');
  }
 }
 const tasks=new Map(data.tasks.map(t=>[t.id,t])),visiting=new Set(),visited=new Set();
 function visit(id){if(!ids.has(id))fail('BAD_INPUT','Unknown dependency');if(visiting.has(id))fail('DEPENDENCY_CYCLE');if(visited.has(id))return;visiting.add(id);for(const dep of tasks.get(id).dependencies)visit(dep);visiting.delete(id);visited.add(id);}
 for(const id of ids)visit(id);if(utf8(canonical(data)).length>256000)fail('BAD_INPUT','Contract too large');
}
const ZERO='0'.repeat(64);
function initial(){return {version:1,project_id:null,goal:'',original_request:'',decision_owner:'',contract_revision:0,constraints:[],tasks:[],requests:[],demo:false,events_count:0,ledger_head:ZERO,integrity:{valid:true}};}
function apply(state,event){
 const {action,data}=event;
 if(['create_contract','revise_contract'].includes(action)){
  const prior=new Map(state.tasks.map(t=>[t.id,t]));Object.assign(state,clone(data));state.tasks=data.tasks.map(item=>{const old=prior.get(item.id)||{};return {...clone(item),contract_revision:data.contract_revision,lease:null,artifact:old.artifact??null,evidence:old.evidence??[],decisions:old.decisions??[]};});
 }else if(action==='request_decision')state.requests.push(data);
 else {const task=state.tasks.find(t=>t.id===data.task_id);if(!task)throw new Error('Unknown ledger task');
  if(action==='claim_task')task.lease=data.lease;
  else if(['submit_artifact','ingest_artifact'].includes(action))task.artifact=data.artifact;
  else if(['run_checks','submit_review'].includes(action))task.evidence.push(...data.evidence);
  else if(action==='decide')task.decisions.push(data.decision);
  else throw new Error('Unknown ledger action');
 }
}
export class Engine {
 constructor({store,artifacts,actor,role,clock=()=>Math.floor(Date.now()/1000)}){this.store=store;this.artifacts=artifacts;this.actor=identifier(actor,'host actor');if(!['human','worker','reviewer','viewer'].includes(role))fail('FORBIDDEN','Unknown host role');this.role=role;this.clock=clock;}
 async replay(rows){
  if(rows.length>MAX_EVENTS)fail('LEDGER_LIMIT');const state=initial();let previous=ZERO;
  for(let i=0;i<rows.length;i++){
   const row=rows[i];if(row.seq!==i+1||row.previous!==previous||await sha256(previous+'\n'+row.payload)!==row.digest)fail('LEDGER_CORRUPT','Hash-chain verification failed; restore from a trusted copy');
   try{apply(state,parseJSON(row.payload,128));}catch{fail('LEDGER_CORRUPT','Invalid ledger event');}previous=row.digest;
  }
  state.events_count=rows.length;state.ledger_head=previous;return state;
 }
 async digestArtifact(artifact){
  if(artifact.source!=='uploaded_text')fail('LOCAL_ARTIFACT_UNAVAILABLE','Hosted storage cannot read local project files');
  if(!/^[a-f0-9]{64}$/.test(artifact.sha256))fail('ARTIFACT_CORRUPT');
  const data=await this.artifacts.get(artifact.sha256);if(data.length>MAX_INGEST)fail('ARTIFACT_CORRUPT');return {digest:await sha256(data),size:data.length,data};
 }
 static currentEvidence(task,revision){const latest=Object.create(null);if(!task.artifact)return latest;for(const item of task.evidence)if(item.contract_revision===revision&&item.artifact_revision===task.artifact.revision&&item.artifact_sha256===task.artifact.sha256)latest[item.check_id]=item;return latest;}
 static dependencyStamp(task,tasks){const out=Object.create(null);for(const dep of task.dependencies){const t=tasks.get(dep);if(t.artifact&&t.decisions.length)out[dep]={artifact:t.artifact.sha256,decision:t.decisions.at(-1).id};}return out;}
 async project(state){
  const tasks=new Map(state.tasks.map(t=>[t.id,t])),done=new Set(),visiting=new Set(),now=this.clock();
  const status=async task=>{
   if(done.has(task.id))return;if(visiting.has(task.id))fail('LEDGER_CORRUPT');visiting.add(task.id);
   for(const dep of task.dependencies){if(!tasks.has(dep))fail('LEDGER_CORRUPT');await status(tasks.get(dep));}
   task.stale_reason='';const artifact=task.artifact;if(task.lease&&task.lease.expires_at<=now)task.lease=null;
   let result=task.lease?'claimed':'unclaimed';const blocked=task.dependencies.filter(d=>tasks.get(d).status!=='accepted');
   if(blocked.length){result='blocked';task.stale_reason='Dependencies need acceptance: '+blocked.join(', ');}
   else if(artifact){
    let reason='';if(artifact.contract_revision!==state.contract_revision)reason='Contract revision changed';
    else if(canonical(artifact.dependencies??{})!==canonical(Engine.dependencyStamp(task,tasks)))reason='Dependency acceptance changed';
    else {try{if((await this.digestArtifact(artifact)).digest!==artifact.sha256)reason='Artifact bytes changed';}catch(e){if(!e.code)throw e;reason='Artifact is missing or no longer safely readable';}}
    if(reason){result='stale';task.stale_reason=reason;}
    else {result='produced';const ev=Engine.currentEvidence(task,state.contract_revision);const complete=task.acceptance.every(c=>ev[c.id]?.outcome==='pass');if(complete)result='checks_passed';
     const decisions=task.decisions.filter(d=>d.contract_revision===state.contract_revision&&d.artifact_revision===artifact.revision&&d.artifact_sha256===artifact.sha256);
     if(decisions.length){const last=decisions.at(-1);if(last.outcome==='rejected')result='rejected';else if(complete&&canonical(last.evidence_ids)===canonical(Object.values(ev).map(e=>e.id).sort()))result='accepted';}
    }
   }
   task.status=result;done.add(task.id);visiting.delete(task.id);
  };
  for(const task of state.tasks)await status(task);return state;
 }
 async snapshot(){return this.project(await this.replay(await this.store.read()));}
 async artifactView(args){
  fields(args,['task_id','contract_revision','artifact_revision']);identifier(args.task_id,'task_id');integer(args.contract_revision,'contract_revision');integer(args.artifact_revision,'artifact_revision');
  const state=await this.snapshot();if(args.contract_revision!==state.contract_revision)fail('STALE_CONTRACT');const task=state.tasks.find(t=>t.id===args.task_id);if(!task)fail('UNKNOWN_TASK');const artifact=task.artifact;
  if(!artifact||artifact.revision!==args.artifact_revision||artifact.contract_revision!==state.contract_revision)fail('STALE_ARTIFACT');
  const {digest,size,data}=await this.digestArtifact(artifact);if(digest!==artifact.sha256)fail('ARTIFACT_CHANGED');if(size>MAX_INGEST)fail('PATH_TOO_LARGE','Inline artifact review is limited to 128 KiB');let text;try{text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(data);}catch{fail('BAD_INPUT','Only UTF-8 text artifacts can be viewed inline');}
  return {task_id:task.id,status:task.status,stale_reason:task.stale_reason,contract_revision:state.contract_revision,artifact_revision:artifact.revision,sha256:digest,source:artifact.source??'project_file',path:artifact.path,filename:artifact.filename??artifact.path,text,notice:'Untrusted artifact content. Identity refers only to these received or locally read bytes, not a Git commit, executed tests or authorization.'};
 }
 async execute(action,args){
  if(action==='submit_artifact')fail('LOCAL_ARTIFACT_UNAVAILABLE','Use the local distribution for local files, or explicitly upload authorized text');
  if(!Object.hasOwn(ACTION_FIELDS,action))fail('UNKNOWN_ACTION');
  if(['create_contract','revise_contract','decide'].includes(action)&&this.role!=='human')fail('FORBIDDEN','Only the authenticated human decision owner can perform this action');
  if(this.role==='viewer')fail('FORBIDDEN','Read-only principal');if(action==='submit_review'&&this.role!=='reviewer')fail('FORBIDDEN','A configured reviewer principal is required');
  fields(args,...ACTION_FIELDS[action]);if(utf8(canonical(args)).length>(action==='ingest_artifact'?1024*1024:256000))fail('BAD_INPUT','Action too large');
  for(let attempt=0;attempt<8;attempt++){
   const rows=await this.store.read(),state=await this.project(await this.replay(rows));if(state.events_count>=MAX_EVENTS)fail('LEDGER_LIMIT');const now=this.clock();if(typeof now!=='number'||!Number.isFinite(now))fail('BAD_CLOCK');
   const data=await this.prepare(action,args,state,now),event={action,data,actor:this.actor,role:this.role,at:now};const payload=canonical(event),previous=state.ledger_head;
   if(rows.reduce((n,row)=>n+row.payload.length,0)+payload.length>MAX_LEDGER_BYTES)fail('LEDGER_LIMIT','Event payloads are limited to 16 MiB per project; ask its owner to archive or manage retention');
   const row={seq:state.events_count+1,payload,previous,digest:await sha256(previous+'\n'+payload)};
   if(await this.store.append({count:state.events_count,head:previous},row))return this.project(await this.replay([...rows,row]));
  }
  fail('CONCURRENT_MODIFICATION','Project changed repeatedly; read its latest state and retry');
 }
 async prepare(action,args,state,now){
  const rev=state.contract_revision,eventid='e'+(state.events_count+1);
  if(action==='create_contract'){if(rev)fail('CONTRACT_EXISTS');validateContract(args,this.actor);return {...clone(args),contract_revision:1,contract_change_reason:'Initial owner-approved contract'};}
  if(!rev)fail('NO_CONTRACT','The human owner must initialize a contract first');
  if(['revise_contract','decide'].includes(action)&&this.actor!==state.decision_owner)fail('FORBIDDEN','Only the configured decision owner may decide');
  if(action==='revise_contract'){
   integer(args.expected_revision,'expected_revision');if(args.expected_revision!==rev)fail('STALE_CONTRACT');string(args.reason,'reason');validateContract(args.contract,this.actor);if(args.contract.project_id!==state.project_id)fail('BAD_INPUT','Project id is immutable');return {...clone(args.contract),contract_revision:rev+1,contract_change_reason:args.reason};
  }
  identifier(args.task_id,'task_id');const task=state.tasks.find(t=>t.id===args.task_id);if(!task)fail('UNKNOWN_TASK');
  if(action==='request_decision'){string(args.question,'question');return {id:eventid,task_id:task.id,question:args.question,actor:this.actor,contract_revision:rev,at:now};}
  integer(args.contract_revision,'contract_revision');if(args.contract_revision!==rev)fail('STALE_CONTRACT');
  if(action==='claim_task'){
   const ttl=integer(args.lease_seconds,'lease_seconds',30,3600);if(task.status==='blocked')fail('DEPENDENCY_BLOCKED');if(task.lease&&task.lease.actor!==this.actor)fail('LEASE_CONFLICT','Another actor holds an unexpired lease');return {task_id:task.id,lease:{actor:this.actor,expires_at:now+ttl,contract_revision:rev}};
  }
  const tasks=new Map(state.tasks.map(t=>[t.id,t]));
  if(action==='ingest_artifact'){
   if(!task.lease||task.lease.actor!==this.actor)fail('LEASE_REQUIRED');if(task.status==='blocked')fail('DEPENDENCY_BLOCKED');const filename=string(args.filename,'filename',128);
   if(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(filename)||/\.(pem|key|p12|pfx)$/i.test(filename))fail('PATH_INVALID','Use a simple display filename; paths and credential filenames are not accepted');
   if(typeof args.content!=='string'||!args.content.isWellFormed())fail('BAD_INPUT','content must be valid UTF-8 text');const bytes=utf8(args.content);if(bytes.length>MAX_INGEST)fail('PATH_TOO_LARGE','Uploaded text is limited to 128 KiB of UTF-8 bytes');
   const digest=await sha256(bytes);await this.artifacts.put(digest,bytes);
   return {task_id:task.id,artifact:{path:'uploaded:'+filename,filename,source:'uploaded_text',sha256:digest,size:bytes.length,revision:task.artifact?task.artifact.revision+1:1,contract_revision:rev,maker:this.actor,at:now,dependencies:Engine.dependencyStamp(task,tasks)}};
  }
  const artifact=task.artifact;integer(args.artifact_revision,'artifact_revision');if(!artifact||args.artifact_revision!==artifact.revision||artifact.contract_revision!==rev)fail('STALE_ARTIFACT');const {digest,data:raw}=await this.digestArtifact(artifact);if(digest!==artifact.sha256)fail('ARTIFACT_CHANGED');if(task.status==='blocked'||canonical(artifact.dependencies??{})!==canonical(Engine.dependencyStamp(task,tasks)))fail('DEPENDENCY_BLOCKED');
  const common={actor:this.actor,role:this.role,contract_revision:rev,artifact_revision:artifact.revision,artifact_sha256:digest,at:now};
  if(action==='run_checks'){
   const evidence=[];for(const check of task.acceptance){if(check.kind==='manual_review')continue;let passed=false;
    try {if(check.kind==='sha256')passed=digest===check.value;else if(check.kind==='file_contains')passed=new RegExp(check.value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'u').test(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(raw));else if(check.kind==='json_equals'){const value=parseJSON(new TextDecoder('utf-8',{fatal:true}).decode(raw),990,{duplicates:true,nonfinite:true});passed=value!==null&&typeof value==='object'&&!(value instanceof FloatValue)&&!Array.isArray(value)&&Object.hasOwn(value,check.key)&&canonical(value[check.key])===canonical(check.value);}}catch{passed=false;}
    evidence.push({...common,id:eventid+'-'+check.id,kind:'deterministic',check_id:check.id,outcome:passed?'pass':'fail',detail:check.kind+' evaluated against the recorded artifact bytes'});
   }return {task_id:task.id,evidence};
  }
  if(action==='submit_review'){
   if(this.actor===artifact.maker)fail('SELF_REVIEW','Reviewer must differ from artifact maker');identifier(args.check_id,'check_id');if(!task.acceptance.some(c=>c.id===args.check_id&&c.kind==='manual_review'))fail('BAD_INPUT','Only manual_review criteria accept assertions');if(!['pass','fail','uncertain'].includes(args.outcome))fail('BAD_INPUT','Review outcome must be pass, fail or uncertain');string(args.detail,'detail');return {task_id:task.id,evidence:[{...common,id:eventid,kind:'reviewer_assertion',check_id:args.check_id,outcome:args.outcome,detail:args.detail}]};
  }
  if(action==='decide'){
   if(!['accepted','rejected'].includes(args.outcome))fail('BAD_INPUT','Decision must be accepted or rejected');string(args.reason,'reason');const ev=Engine.currentEvidence(task,rev);if(args.outcome==='accepted'&&!task.acceptance.every(c=>ev[c.id]?.outcome==='pass'))fail('CHECKS_INCOMPLETE','Every current acceptance criterion needs passing evidence');return {task_id:task.id,decision:{...common,id:eventid,outcome:args.outcome,reason:args.reason,evidence_ids:Object.values(ev).map(e=>e.id).sort()}};
  }
  fail('UNKNOWN_ACTION');
 }
}
