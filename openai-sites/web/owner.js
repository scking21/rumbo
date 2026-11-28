const $=id=>document.getElementById(id),csrf=document.querySelector('meta[name="rumbo-csrf"]').content;
let projectKey='',state=null,selectedArtifact=null,decisionDraftKey=null,busy=false,projects=[],actor='',manualRecoveryKey='';
const decisionDrafts=new Map();
const attemptedDeletions=new Set();
function deletionMarker(key){return 'rumbo.deletion.'+actor+'.'+key;}
function deletionAttempted(key){
 if(attemptedDeletions.has(key))return true;
 try{return sessionStorage.getItem(deletionMarker(key))==='1';}catch{return false;}
}
function rememberDeletion(key){
 attemptedDeletions.add(key);
 try{sessionStorage.setItem(deletionMarker(key),'1');}catch{/* Same-page and manual recovery remain available. */}
}
function forgetDeletion(key){
 attemptedDeletions.delete(key);
 try{sessionStorage.removeItem(deletionMarker(key));}catch{/* Tab storage may be unavailable. */}
}
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function request(path,options,consume){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
 try{return await consume(await fetch(path,{...options,signal:controller.signal}));}
 catch(error){if(error.name==='AbortError')throw new Error('Request timed out. Refresh to check the latest saved state before retrying.');throw error;}
 finally{clearTimeout(timer);}
}
async function api(path,body){return request(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'content-type':'application/json','x-rumbo-csrf':csrf},...(body===undefined?{}:{body:typeof body==='string'?body:JSON.stringify(body)})},async response=>{const data=await response.json();if(!response.ok)throw new Error(data.error||'Request failed');return data;});}
async function run(action){
 if(busy)return;
 const previousFocus=document.activeElement;
 busy=true;document.querySelectorAll('button,#projects').forEach(b=>{if(!b.closest('dialog'))b.disabled=true;});
 try{await action();}catch(e){message(e.message+' Your draft has been kept.',true);}
 finally{
  busy=false;document.querySelectorAll('button,#projects').forEach(b=>b.disabled=false);
  const project=projects.find(p=>p.project_key===projectKey),ownerSelected=project?.role==='owner';
  for(const node of document.querySelectorAll('[data-project-admin]'))node.hidden=!ownerSelected;
  const canAdmin=ownerSelected && project.lifecycle!=='deleting' && !deletionAttempted(projectKey);
  for(const id of ['export','revise','grant'])$(id).disabled=!canAdmin;
  // Disabling the trigger blurs it before a dialog can remember its focus.
  // A just-closed dialog can still own focus when this action settles.
  // Restore only lost focus, never a newer focus choice or a hidden control.
  const active=document.activeElement,focusLost=active===document.body||active?.closest('dialog:not([open])');
  if(focusLost&&previousFocus&&previousFocus!==document.body){
   const target=previousFocus.isConnected&&!previousFocus.closest('[hidden]')?previousFocus:state&&!$('project-panel').hidden?$('goal'):previousFocus.id==='delete-project'&&!projectKey?$('projects'):null;
   target?.focus({preventScroll:true});
  }
 }
}
function confirmAction(title,text,detail){$('confirm-title').textContent=title;$('confirm-text').textContent=text;$('confirm-detail').textContent=detail;const dialog=$('confirmation');dialog.returnValue='';return new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();});}
function el(tag,text){const node=document.createElement(tag);node.textContent=text;return node;}
async function loadProjects(){const list=await api('/api/projects');projects=list.projects;const select=$('projects');select.replaceChildren(new Option('Choose a project',''));for(const p of list.projects)select.add(new Option(p.alias+' · '+p.role+(p.lifecycle==='deleting'?' · deletion pending':''),p.project_key));if(projectKey&&!projects.some(p=>p.project_key===projectKey))select.add(new Option('Unavailable project',projectKey));if([...select.options].some(o=>o.value===projectKey))select.value=projectKey;if(projects.some(p=>p.project_key===projectKey&&p.lifecycle!=='deleting'))forgetDeletion(projectKey);}
function saveDecisionDraft(){if(decisionDraftKey)decisionDrafts.set(decisionDraftKey,$('decision-reason').value);}
function clearInspection(){
 saveDecisionDraft();
 selectedArtifact=null;
 decisionDraftKey=null;
 $('artifact-panel').hidden=true;
 $('decision-controls').hidden=true;
 for(const id of ['artifact-text','artifact-meta','artifact-criteria','artifact-evidence','artifact-decision'])$(id).textContent='';
}
async function inspectArtifact(task,role){
 clearInspection();
 const params=new URLSearchParams({project_key:projectKey,task_id:task.id,contract_revision:state.contract_revision,artifact_revision:task.artifact.revision});
 let artifact;
 try{artifact=await api('/api/artifact?'+params);}
 catch(error){throw new Error(error.message+' Refresh and inspect this task again.');}
 const context=artifact.review_context;
 if(!context||typeof context.review_basis!=='string')throw new Error('Current owner review basis is unavailable');
 const draftKey=JSON.stringify([projectKey,task.id,artifact.contract_revision,artifact.artifact_revision,context.review_basis]);
 decisionDraftKey=draftKey;
 $('decision-reason').value=decisionDrafts.get(draftKey)??'';
 const canDecide=role==='owner';
 selectedArtifact=canDecide?{task_id:task.id,contract_revision:artifact.contract_revision,artifact_revision:artifact.artifact_revision,expected_review_basis:context.review_basis}:null;
 $('decision-controls').hidden=!canDecide;
 $('artifact-meta').textContent=artifact.filename+' · '+artifact.sha256;
 $('artifact-text').textContent=artifact.text;
 $('artifact-criteria').textContent=JSON.stringify(context.acceptance,null,2);
 $('artifact-evidence').textContent=JSON.stringify(context.evidence,null,2);
 $('artifact-decision').textContent=JSON.stringify(context.decision,null,2);
 $('artifact-panel').hidden=false;
 $('artifact-panel').scrollIntoView({behavior:'smooth',block:'start'});
 message(canDecide?'Exact received bytes and current review basis loaded. Inspect each section before deciding.':'Exact received bytes and current review basis loaded for inspection. The project owner can accept or reject this revision.');
}
function clearProjectContent(){state=null;clearInspection();$('project-panel').hidden=true;$('tasks').replaceChildren();$('goal').textContent='';$('revision').textContent='';$('constraints').textContent='';}
function showDeletion(project){$('privacy-panel').hidden=project?.role!=='owner'&&project?.lifecycle!=='unknown';const pending=project?.lifecycle==='deleting',unknown=project?.lifecycle==='unknown';$('delete-project').textContent=pending?'Continue deletion':unknown?'Retry deletion confirmation':'Delete project';$('delete-status').textContent=pending?'Deletion is pending. Project access is blocked. Continue to retry cleanup; do not assume all content is erased yet.':unknown?'Deletion outcome is unknown. Refresh to check current state, or enter the original project ID and retry the owner-confirmed deletion. Access removal and erasure are not yet confirmed.':'Project ID: '+(project?.alias??'');}
function showDeletionRecovery(){
 showDeletion({lifecycle:'unknown'});
 message('The deletion result has not been verified. Enter the original project ID to retry your request.');
}
async function loadState(){
 clearProjectContent();$('privacy-panel').hidden=true;
 const recovery=$('start-deletion-recovery');recovery.hidden=true;manualRecoveryKey='';
 if(!projectKey)return;
 const project=projects.find(p=>p.project_key===projectKey);
 if(!project){
  if(deletionAttempted(projectKey))showDeletionRecovery();
  else{
   recovery.hidden=false;
   message('Project unavailable. Refresh the project list or choose another project.');
  }
  return;
 }
 if(project?.lifecycle==='deleting'){showDeletion(project);message('Deletion pending. Continue deletion to retry cleanup.');return;}state=await api('/api/state?project_key='+encodeURIComponent(projectKey));showDeletion(project);$('project-panel').hidden=false;$('goal').textContent=state.goal;$('revision').textContent='Contract revision '+state.contract_revision+' · '+state.tasks.length+' tasks · Owner '+state.decision_owner;$('constraints').textContent=state.constraints.join(' · ');$('board-link').href='/board?project_key='+encodeURIComponent(projectKey);$('tasks').replaceChildren();for(const task of state.tasks){const card=el('div','');card.className='task';card.append(el('h3',task.title),el('p',task.status+(task.stale_reason?' · '+task.stale_reason:'')));if(task.artifact){card.append(el('p','Artifact revision '+task.artifact.revision+' · SHA-256 '+task.artifact.sha256));const inspect=el('button','Inspect exact bytes');inspect.onclick=()=>run(()=>inspectArtifact(task,project.role));card.append(inspect);}const evidence=el('details','');evidence.append(el('summary','Evidence and decision history'),el('pre',JSON.stringify({acceptance:task.acceptance,evidence:task.evidence,decisions:task.decisions},null,2)));card.append(evidence);$('tasks').append(card);}message('Project refreshed');}
function selectProject(key){if(projectKey!==key){$('delete-confirmation').value='';manualRecoveryKey='';}projectKey=key;history.replaceState(null,'',projectKey?'/?project_key='+encodeURIComponent(projectKey):'/');}
$('projects').onchange=()=>run(async()=>{selectProject($('projects').value);await loadState();});
$('refresh').onclick=()=>run(async()=>{await loadProjects();await loadState();});
$('create').onclick=()=>run(async()=>{const raw=$('contract').value;JSON.parse(raw);if(!await confirmAction('Create contract','This records the entire contract as your owner-approved scope.',raw))return;const result=await api('/owner/api/create','{"contract":'+raw+'}');selectProject(result.project_key);await loadProjects();await loadState();});
$('revise').onclick=()=>run(async()=>{if(!state)throw new Error('Choose a project first');const raw=$('contract').value;JSON.parse(raw);const reason=$('change-reason').value;if(!reason.trim())throw new Error('Enter a revision reason');if(!await confirmAction('Revise contract','This changes the agreed scope and invalidates prior acceptance. Expected current revision: '+state.contract_revision,raw+'\nReason: '+reason))return;const prefix=JSON.stringify({project_key:projectKey,expected_revision:state.contract_revision,reason}).slice(0,-1);await api('/owner/api/revise',prefix+',"contract":'+raw+'}');await loadState();});
async function decide(outcome){if(!selectedArtifact)throw new Error('Inspect the exact artifact first');const reason=$('decision-reason').value;if(!reason.trim())throw new Error('Enter a decision reason');const payload={project_key:projectKey,...selectedArtifact,outcome,reason};if(!await confirmAction(outcome==='accepted'?'Accept exact revision':'Reject exact revision','Your decision applies only to the inspected contract/artifact revisions and current evidence.',JSON.stringify(payload,null,2)))return;await api('/owner/api/decide',payload);await loadState();}
$('accept').onclick=()=>run(()=>decide('accepted'));$('reject').onclick=()=>run(()=>decide('rejected'));
$('grant').onclick=()=>run(async()=>{if(!projectKey)throw new Error('Choose a project first');const payload={project_key:projectKey,subject:$('member-subject').value,role:$('member-role').value};if(!await confirmAction('Grant persistent project access','This person will be able to read project records and uploaded bytes. Worker/reviewer roles can also write their permitted records. Confirm the recipient and role.',JSON.stringify(payload,null,2)))return;await api('/owner/api/member',payload);message('Project access updated');});
$('start-deletion-recovery').onclick=()=>{
 if(!projectKey||$('start-deletion-recovery').hidden)return;
 manualRecoveryKey=projectKey;
 $('start-deletion-recovery').hidden=true;
 showDeletionRecovery();
 $('delete-confirmation').focus();
};
$('delete-project').onclick=()=>run(async()=>{
 const project=projects.find(p=>p.project_key===projectKey)??(projectKey&&(deletionAttempted(projectKey)||manualRecoveryKey===projectKey)?{lifecycle:'unknown'}:null);if(!project||(project.role!=='owner'&&project.lifecycle!=='unknown'))throw new Error('Choose a project you own');
 const confirmation=$('delete-confirmation').value;if(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(confirmation)||(project.alias&&confirmation!==project.alias))throw new Error('Type the exact project ID'+(project.alias?': '+project.alias:''));
 const payload={project_key:projectKey,confirmation};
 if(!await confirmAction(project.lifecycle==='deleting'?'Continue project deletion':'Permanently delete project','This cannot be undone. Export first if you need a copy. This removes all hosted project content and access for every member.',JSON.stringify({project_id:confirmation,project_key:projectKey},null,2)+'\nEmpty hash-derived technical guard keys remain to prevent delayed uploads restoring content. The project ID cannot be reused. Copies already downloaded or held by connected clients, provider backups and logs are not erased by this action.'))return;
 clearProjectContent();rememberDeletion(projectKey);showDeletion({role:project.role,lifecycle:'unknown'});message('Deletion outcome unconfirmed. Waiting for the server response.');
 const result=await api('/owner/api/delete',payload);
 if(result.status==='deleted'){
  forgetDeletion(payload.project_key);
  projects=projects.filter(p=>p.project_key!==payload.project_key);for(const option of [...$('projects').options])if(option.value===payload.project_key)option.remove();selectProject('');$('projects').value='';$('contract').value='';$('change-reason').value='';$('decision-reason').value='';$('privacy-panel').hidden=true;await loadState();
  const complete='Project content deleted. Empty technical guard keys remain; this project ID cannot be reused. Previously downloaded or provider-held copies are unaffected.';
  try{await loadProjects();message(complete);}catch{message(complete+' The remaining project list could not refresh. Use Refresh to retry.');}
 }else{await loadProjects();await loadState();message('Deletion pending. Project access is blocked. Continue deletion to retry cleanup.');}
});
$('export').onclick=()=>run(async()=>{if(!projectKey)throw new Error('Choose a project first');const blob=await request('/owner/api/export',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json','x-rumbo-csrf':csrf},body:JSON.stringify({project_key:projectKey})},async response=>{if(!response.ok)throw new Error((await response.json()).error);return response.blob();});const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='rumbo-'+state.project_id+'-export.ndjson';link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);message('Export downloaded. Verify it with the included verify-export.py script before relying on it as a backup.');});
await run(async()=>{const me=await api('/api/me');actor=me.actor;$('identity').textContent='Your Site user ID: '+me.subject+' · Owner ID: '+me.actor;$('contract').value=JSON.stringify({project_id:'my-project',goal:'',original_request:'',decision_owner:me.actor,constraints:[],tasks:[{id:'first-task',title:'',dependencies:[],acceptance:[{id:'check',kind:'file_contains',value:''}]}]},null,2);projectKey=new URLSearchParams(location.search).get('project_key')||'';await loadProjects();await loadState();});
