import test from 'node:test';import assert from 'node:assert/strict';import {JSDOM} from 'jsdom';import {readFileSync} from 'node:fs';
import {subjectActor} from '../worker/storage.js';
import worker from '../worker/index.js';import {fixture} from './support.mjs';
async function ownerDOM({browserFocus=false,retainDialogFocus=false,site=fixture(),subject='owner',projectKey='',tabStorage={}}={}){
 const {env,storage}=site,identity={'oai-authenticated-user-id':subject,'oai-authenticated-user-email':subject+'@example.test'};const page=await worker.fetch(new Request('https://rumbo.test/',{headers:{...identity,'sec-fetch-mode':'navigate','sec-fetch-dest':'document'}}),env);const cookie=page.headers.get('set-cookie').split(';')[0];
 const dom=new JSDOM(await page.text(),{url:'https://rumbo.test/'+(projectKey?'?project_key='+encodeURIComponent(projectKey):''),runScripts:'outside-only'}),w=dom.window;
 for(const [key,value] of Object.entries(tabStorage))w.sessionStorage.setItem(key,value);
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(v){if(v!==undefined)this.returnValue=v;this.open=false;this.dispatchEvent(new w.Event('close'));};w.HTMLElement.prototype.scrollIntoView=function(){};
 if(browserFocus){
  // jsdom does not implement native dialog focus or the disabled-control blur
  // observed in the Chromium keyboard regressions. Model those transitions only
  // for these deterministic tests; the browser suite verifies the native behavior.
  for(const prototype of [w.HTMLButtonElement.prototype,w.HTMLSelectElement.prototype]){
   const disabled=Object.getOwnPropertyDescriptor(prototype,'disabled');
   Object.defineProperty(prototype,'disabled',{...disabled,set(value){if(value&&w.document.activeElement===this)this.blur();disabled.set.call(this,value);}});
  }
  // Exercise both settlement states: body, or a control in a now-closed dialog.
  let previousFocus;
  w.HTMLDialogElement.prototype.showModal=function(){previousFocus=w.document.activeElement;this.open=true;this.querySelector('button').focus();};
  w.HTMLDialogElement.prototype.close=function(value){if(value!==undefined)this.returnValue=value;this.open=false;if(!retainDialogFocus&&this.contains(w.document.activeElement))w.document.activeElement.blur();previousFocus?.focus();this.dispatchEvent(new w.Event('close'));};
 }
 // The fixture uses Node Request/fetch, so use its matching AbortSignal brand.
 w.AbortController=AbortController;
 w.fetch=async(path,options={})=>worker.fetch(new Request(new URL(path,w.location.href),{...options,headers:{...identity,cookie,...(options.method==='POST'?{origin:'https://rumbo.test','sec-fetch-site':'same-origin','sec-fetch-mode':'cors'}:{}),...options.headers}}),env);
 await w.eval('(async()=>{'+readFileSync('web/owner.js','utf8')+'})()');return {w,storage,dom};
}
const tick=()=>new Promise(r=>setTimeout(r,5));
test('owner confirmation remains clickable while a write is pending; cancel preserves draft',async()=>{
 const {w,dom}=await ownerDOM(),d=w.document;const contract=JSON.parse(d.getElementById('contract').value);contract.goal='Synthetic';contract.original_request='Test only';contract.tasks[0].title='One';contract.tasks[0].acceptance[0].value='hello';const draft=JSON.stringify(contract);d.getElementById('contract').value=draft;
 d.getElementById('create').click();await tick();assert.equal(d.getElementById('confirmation').open,true);assert.equal(d.getElementById('confirm-submit').disabled,false);
 d.getElementById('confirmation').close('cancel');await tick();assert.equal(d.getElementById('contract').value,draft);assert.equal(d.getElementById('create').disabled,false);dom.window.close();
});
test('owner creates a contract once after explicit modal confirmation; errors preserve drafts',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document,c=JSON.parse(d.getElementById('contract').value);c.goal='<img src=x onerror=alert(1)>';c.original_request='Test';c.tasks[0].title='One';c.tasks[0].acceptance[0].value='hello';d.getElementById('contract').value=JSON.stringify(c);
 d.getElementById('create').click();await tick();d.getElementById('confirmation').close('confirm');for(let i=0;i<40&&d.getElementById('create').disabled;i++)await tick();assert.equal((await storage.listProjects('owner')).length,1);assert.equal(d.getElementById('goal').textContent,c.goal);assert.equal(d.querySelector('#goal img'),null);
 d.getElementById('contract').value='{invalid';d.getElementById('create').click();await tick();assert.equal(d.getElementById('contract').value,'{invalid');assert.match(d.getElementById('message').textContent,/draft has been kept/);dom.window.close();
});

async function idle(d){for(let i=0;i<200&&d.getElementById('create').disabled;i++)await tick();assert.equal(d.getElementById('create').disabled,false,'Owner operation should settle');}
test('dismissing a second confirmation never reuses the earlier confirmed result',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const c=JSON.parse(d.getElementById('contract').value);c.goal='Synthetic';c.original_request='Test only';c.tasks[0].title='One';c.tasks[0].acceptance[0].value='hello';d.getElementById('contract').value=JSON.stringify(c);
  d.getElementById('create').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  const project=(await storage.listProjects('owner'))[0];d.getElementById('change-reason').value='Canceled scope change';
  d.getElementById('revise').click();await tick();assert.equal(d.getElementById('confirmation').open,true);
  // Escape/native dismissal closes without setting a new returnValue.
  d.getElementById('confirmation').close();await idle(d);
  assert.equal((await (await storage.engine('owner',project.project_key,'human')).snapshot()).contract_revision,1);
  assert.equal(d.getElementById('change-reason').value,'Canceled scope change');
 }finally{dom.window.close();}
});

async function createOwnerProject(w,storage){
 const d=w.document,c=JSON.parse(d.getElementById('contract').value);c.goal='Synthetic';c.original_request='Test only';c.tasks[0].title='One';c.tasks[0].acceptance[0].value='hello';d.getElementById('contract').value=JSON.stringify(c);
 d.getElementById('create').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
 return {contract:c,project:(await storage.listProjects('owner'))[0]};
}
test('project deletion requires typed alias and a fresh confirmation; Cancel preserves project',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const {project}=await createOwnerProject(w,storage),remove=d.getElementById('delete-project');assert.ok(remove,'Owner deletion control exists');
  assert.equal(d.getElementById('privacy-panel').hidden,false);
  d.getElementById('delete-confirmation').value='wrong';remove.click();await idle(d);assert.equal(d.getElementById('confirmation').open,false);assert.equal((await storage.listProjects('owner')).length,1);
  d.getElementById('delete-confirmation').value=project.alias;remove.click();await tick();assert.equal(d.getElementById('confirmation').open,true);assert.match(d.getElementById('confirm-text').textContent,/cannot be undone/i);assert.match(d.getElementById('confirm-detail').textContent,/provider|backup/i);
  d.getElementById('confirmation').close('cancel');await idle(d);assert.equal((await storage.listProjects('owner')).length,1);
  remove.click();await tick();d.getElementById('confirmation').close();await idle(d);assert.equal((await storage.listProjects('owner')).length,1);
  remove.click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.equal((await storage.listProjects('owner')).length,0);assert.equal(d.getElementById('projects').value,'');assert.equal(d.getElementById('project-panel').hidden,true);assert.equal(d.getElementById('privacy-panel').hidden,true);assert.equal(d.getElementById('contract').value,'');assert.equal(d.getElementById('artifact-text').textContent,'');assert.match(d.getElementById('message').textContent,/content deleted/i);
 }finally{dom.window.close();}
});
test('an interrupted deletion is visibly pending and resumes without re-enabling project actions',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const {project}=await createOwnerProject(w,storage),session=await storage.openWorker('owner',project.project_key,'Synthetic maker'),engine=await storage.workerEngine('owner',project.project_key,session.worker_id);
  await engine.execute('claim_task',{task_id:'first-task',contract_revision:1,lease_seconds:300});await engine.execute('ingest_artifact',{task_id:'first-task',contract_revision:1,filename:'test.txt',content:'hello'});
  const put=storage.bucket.put.bind(storage.bucket);let fail=true;storage.bucket.put=async(...args)=>{if(fail&&args[1].byteLength===0)throw new Error('Synthetic storage interruption');return put(...args);};
  assert.ok(d.getElementById('delete-project'),'Owner deletion control exists');d.getElementById('delete-confirmation').value=project.alias;d.getElementById('delete-project').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.equal(d.getElementById('project-panel').hidden,true);assert.equal(d.getElementById('privacy-panel').hidden,false);assert.match(d.getElementById('message').textContent,/pending/i);assert.match(d.getElementById('delete-project').textContent,/continue/i);
  d.getElementById('refresh').click();await idle(d);assert.equal(d.getElementById('project-panel').hidden,true);assert.equal(d.getElementById('privacy-panel').hidden,false);
  fail=false;d.getElementById('delete-project').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);assert.equal((await storage.listProjects('owner')).length,0);
 }finally{dom.window.close();}
});
test('a deletion request lost before delivery never claims project access is blocked',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const {project}=await createOwnerProject(w,storage),fetch=w.fetch;
  w.fetch=async(path,options)=>{if(path==='/owner/api/delete')throw new Error('Synthetic request not delivered');return fetch(path,options);};
  d.getElementById('delete-confirmation').value=project.alias;d.getElementById('delete-project').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.doesNotMatch(d.getElementById('delete-status').textContent,/access is blocked/);assert.match(d.getElementById('delete-status').textContent,/unknown|unconfirmed/i);assert.equal((await storage.listProjects('owner')).length,1);
  w.fetch=fetch;d.getElementById('refresh').click();await idle(d);assert.equal(d.getElementById('project-panel').hidden,false);
 }finally{dom.window.close();}
});
test('a committed deletion with a lost response remains confirmable after Refresh',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const {project}=await createOwnerProject(w,storage),fetch=w.fetch;let lose=true;
  w.fetch=async(path,options)=>{const response=await fetch(path,options);if(path==='/owner/api/delete'&&lose){lose=false;throw new Error('Synthetic completed response lost');}return response;};
  d.getElementById('delete-confirmation').value=project.alias;d.getElementById('delete-project').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);assert.equal((await storage.listProjects('owner')).length,0);
  d.getElementById('refresh').click();await idle(d);assert.equal(d.getElementById('privacy-panel').hidden,false);assert.equal(d.getElementById('delete-confirmation').value,project.alias);assert.match(d.getElementById('delete-status').textContent,/unknown|unconfirmed/i);
  d.getElementById('delete-project').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);assert.match(d.getElementById('message').textContent,/content deleted/i);assert.equal(d.getElementById('projects').value,'');
 }finally{dom.window.close();}
});
test('completed deletion moves lost focus to the project picker',async()=>{
 const {w,storage,dom}=await ownerDOM({browserFocus:true,retainDialogFocus:true}),d=w.document;try{
  const {project}=await createOwnerProject(w,storage);d.getElementById('delete-confirmation').value=project.alias;d.getElementById('delete-project').focus();d.getElementById('delete-project').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.equal(d.activeElement,d.getElementById('projects'));
 }finally{dom.window.close();}
});
test('confirmed deletion remains successful when refreshing the remaining project list fails',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const {project}=await createOwnerProject(w,storage),fetch=w.fetch;let deleted=false;
  w.fetch=async(path,options)=>{if(path==='/api/projects'&&deleted)return new Response(JSON.stringify({error:'Synthetic list interruption'}),{status:503,headers:{'content-type':'application/json'}});const response=await fetch(path,options);if(path==='/owner/api/delete'&&response.ok)deleted=true;return response;};
  d.getElementById('delete-confirmation').value=project.alias;d.getElementById('delete-project').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.equal((await storage.listProjects('owner')).length,0);assert.match(d.getElementById('message').textContent,/content deleted/i);assert.doesNotMatch(d.getElementById('message').textContent,/draft has been kept/);assert.equal(d.getElementById('projects').value,'');
 }finally{dom.window.close();}
});
test('creating a project records its selection in the reloadable URL',async()=>{
 const {w,storage,dom}=await ownerDOM();try{const {project}=await createOwnerProject(w,storage);assert.equal(new URLSearchParams(w.location.search).get('project_key'),project.project_key);}finally{dom.window.close();}
});
test('project selection cannot change while its state refresh is pending',async()=>{
 const {w,storage,dom}=await ownerDOM();let resume;try{
  await createOwnerProject(w,storage);let ready;const pending=new Promise(r=>ready=r),gate=new Promise(r=>resume=r),fetch=w.fetch;
  w.fetch=async(path,options)=>{if(path.startsWith('/api/state?')){ready();await gate;}return fetch(path,options);};
  w.document.getElementById('refresh').click();await pending;
  assert.equal(w.document.getElementById('projects').disabled,true,'A pending operation must keep the visible project and loaded context together');
  resume();await idle(w.document);assert.equal(w.document.getElementById('projects').disabled,false);
 }finally{resume?.();await idle(w.document);dom.window.close();}
});
test('failed project switching clears the earlier project context until retry succeeds',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const first=await createOwnerProject(w,storage),c={...first.contract,project_id:'second-project',goal:'Second synthetic project'};
  const second=await storage.createProject('owner',c.project_id,c);d.getElementById('refresh').click();await idle(d);
  const fetch=w.fetch;w.fetch=async(path,options)=>path==='/api/state?project_key='+second.project_key?new Response(JSON.stringify({error:'Synthetic offline read'}),{status:503}):fetch(path,options);
  const select=d.getElementById('projects');select.value=second.project_key;select.dispatchEvent(new w.Event('change'));await idle(d);
  assert.equal(d.getElementById('project-panel').hidden,true,'The previous project must not stay visible under the new selection');
  d.getElementById('change-reason').value='Retry after interruption';d.getElementById('revise').click();await tick();assert.equal(d.getElementById('confirmation').open,false,'No stale contract context may be confirmed');
  assert.match(d.getElementById('message').textContent,/Choose a project first/);
  w.fetch=fetch;d.getElementById('refresh').click();await idle(d);assert.equal(d.getElementById('goal').textContent,c.goal);assert.equal(d.getElementById('project-panel').hidden,false);
 }finally{dom.window.close();}
});

function controlTimeouts(w){
 const timers=new Map();let id=0;w.setTimeout=fn=>{timers.set(++id,fn);return id;};w.clearTimeout=key=>timers.delete(key);
 return ()=>{for(const fn of [...timers.values()])fn();};
}
test('an interrupted state request times out, unlocks controls and can be retried',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;let resume;try{
  await createOwnerProject(w,storage);const expire=controlTimeouts(w),fetch=w.fetch;let ready;const pending=new Promise(r=>ready=r);
  w.fetch=(path,options={})=>path.startsWith('/api/state?')?new Promise((resolve,reject)=>{resume=()=>fetch(path,options).then(resolve,reject);options.signal?.addEventListener('abort',()=>reject(new w.DOMException('Synthetic stalled request','AbortError')),{once:true});ready();}):fetch(path,options);
  d.getElementById('refresh').click();await pending;expire();await tick();
  assert.equal(d.getElementById('refresh').disabled,false,'A stalled network request must not lock the owner UI forever');assert.match(d.getElementById('message').textContent,/timed out/);assert.equal(d.getElementById('project-panel').hidden,true);
  w.fetch=fetch;d.getElementById('refresh').click();await idle(d);assert.equal(d.getElementById('project-panel').hidden,false);
 }finally{resume?.();await idle(d);dom.window.close();}
});
test('a stalled write response body times out with an honest unknown-outcome message',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;let resume;try{
  const {project}=await createOwnerProject(w,storage),expire=controlTimeouts(w),fetch=w.fetch;let ready;const pending=new Promise(r=>ready=r);
  w.fetch=async(path,options={})=>{const response=await fetch(path,options);if(path!=='/owner/api/revise')return response;return {ok:response.ok,json:()=>new Promise((resolve,reject)=>{resume=()=>response.json().then(resolve,reject);options.signal?.addEventListener('abort',()=>reject(new w.DOMException('Synthetic stalled body','AbortError')),{once:true});ready();})};};
  d.getElementById('change-reason').value='Keep this reason after uncertain response';d.getElementById('revise').click();await tick();d.getElementById('confirmation').close('confirm');await pending;expire();await tick();
  assert.equal(d.getElementById('revise').disabled,false,'A stalled response body must not lock the owner UI');assert.match(d.getElementById('message').textContent,/timed out/);assert.match(d.getElementById('message').textContent,/Refresh.*saved/);assert.equal(d.getElementById('change-reason').value,'Keep this reason after uncertain response');
  assert.equal((await (await storage.engine('owner',project.project_key,'human')).snapshot()).contract_revision,2,'The lost response must not be misreported as a failed write');
  w.fetch=fetch;d.getElementById('refresh').click();await idle(d);assert.match(d.getElementById('revision').textContent,/Contract revision 2/);
 }finally{resume?.();await idle(d);dom.window.close();}
});
test('a stalled export body times out without a partial download and a fresh retry succeeds',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;let resume;try{
  await createOwnerProject(w,storage);const expire=controlTimeouts(w),fetch=w.fetch,downloads=[];let ready;const pending=new Promise(r=>ready=r);
  w.URL.createObjectURL=()=> 'blob:synthetic-export';w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){downloads.push(this.download);};
  w.fetch=async(path,options={})=>{const response=await fetch(path,options);if(path!=='/owner/api/export')return response;return {ok:response.ok,blob:()=>new Promise((resolve,reject)=>{resume=()=>response.blob().then(resolve,reject);options.signal?.addEventListener('abort',()=>reject(new w.DOMException('Synthetic stalled export','AbortError')),{once:true});ready();})};};
  d.getElementById('export').click();await pending;expire();await tick();assert.equal(d.getElementById('export').disabled,false);assert.match(d.getElementById('message').textContent,/timed out/);assert.deepEqual(downloads,[]);
  w.fetch=fetch;d.getElementById('export').click();await idle(d);assert.deepEqual(downloads,['rumbo-my-project-export.ndjson']);
 }finally{resume?.();await idle(d);dom.window.close();}
});
test('a stale inspected revision is rejected and refreshed exact bytes can be accepted',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const {project}=await createOwnerProject(w,storage),session=await storage.openWorker('owner',project.project_key,'UI workflow worker'),engine=await storage.workerEngine('owner',project.project_key,session.worker_id);
  const task_id='first-task';await engine.execute('claim_task',{task_id,contract_revision:1,lease_seconds:300});
  const upload=content=>engine.execute('ingest_artifact',{task_id,contract_revision:1,filename:'ui.txt',content}),checks=artifact_revision=>engine.execute('run_checks',{task_id,contract_revision:1,artifact_revision});
  await upload('hello first');await checks(1);d.getElementById('refresh').click();await idle(d);d.querySelector('#tasks button').click();await idle(d);assert.equal(d.getElementById('artifact-text').textContent,'hello first');
  await upload('hello second');await checks(2);d.getElementById('decision-reason').value='Inspect exact replacement before acceptance';d.getElementById('accept').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.match(d.getElementById('message').textContent,/STALE_ARTIFACT/);assert.equal((await engine.snapshot()).tasks[0].decisions.length,0);assert.equal(d.getElementById('decision-reason').value,'Inspect exact replacement before acceptance');
  d.getElementById('refresh').click();await idle(d);assert.equal(d.getElementById('artifact-panel').hidden,true);d.querySelector('#tasks button').click();await idle(d);assert.equal(d.getElementById('artifact-text').textContent,'hello second');
  assert.equal(d.getElementById('decision-reason').value, '', 'Replacement bytes require their own decision reason');
  d.getElementById('decision-reason').value = 'Reviewed the replacement bytes';
  d.getElementById('accept').click();d.getElementById('accept').click();await tick();d.getElementById('confirmation').close('confirm');d.getElementById('confirmation').close('confirm');await idle(d);
  const task=(await engine.snapshot()).tasks[0];assert.equal(task.status,'accepted');assert.equal(task.decisions.length,1);assert.equal(task.decisions[0].artifact_revision,2);
 }finally{dom.window.close();}
});

test('owner review shows the exact basis and refuses evidence refreshed after inspection',async()=>{
 const {w,storage,dom}=await ownerDOM(),d=w.document;try{
  const {project}=await createOwnerProject(w,storage),session=await storage.openWorker('owner',project.project_key,'Review basis worker'),maker=await storage.workerEngine('owner',project.project_key,session.worker_id),owner=await storage.engine('owner',project.project_key,'human');
  const task_id='first-task',check={task_id,contract_revision:1,artifact_revision:1};await maker.execute('claim_task',{task_id,contract_revision:1,lease_seconds:300});await maker.execute('ingest_artifact',{task_id,contract_revision:1,filename:'basis.txt',content:'hello basis'});await maker.execute('run_checks',check);
  d.getElementById('refresh').click();await idle(d);d.querySelector('#tasks button').click();await idle(d);
  assert.match(d.getElementById('artifact-criteria').textContent,/file_contains/);assert.match(d.getElementById('artifact-evidence').textContent,/e4-check/);assert.equal(d.getElementById('artifact-decision').textContent,'null');
  d.getElementById('decision-reason').value='First exact basis';d.getElementById('accept').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);assert.equal((await owner.snapshot()).tasks[0].decisions.length,1);
  await maker.execute('run_checks',check);d.getElementById('refresh').click();await idle(d);d.querySelector('#tasks button').click();await idle(d);
  assert.match(d.getElementById('artifact-evidence').textContent,/e6-check/);assert.match(d.getElementById('artifact-decision').textContent,/First exact basis/);
  await maker.execute('run_checks',check);d.getElementById('decision-reason').value='Must not absorb unseen evidence';d.getElementById('accept').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.match(d.getElementById('message').textContent,/STALE_REVIEW/);assert.equal((await owner.snapshot()).tasks[0].decisions.length,1);assert.equal(d.getElementById('decision-reason').value,'Must not absorb unseen evidence');
  d.getElementById('refresh').click();await idle(d);d.querySelector('#tasks button').click();await idle(d);
  assert.equal(d.getElementById('decision-reason').value, '', 'Changed evidence requires its own decision reason');
  d.getElementById('decision-reason').value = 'Reviewed the refreshed evidence';
  d.getElementById('accept').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);assert.equal((await owner.snapshot()).tasks[0].decisions.length,2);
 }finally{dom.window.close();}
});


for(const retainDialogFocus of [false,true])test('canceling a confirmation restores focus from '+(retainDialogFocus?'the closed dialog':'body'),async()=>{
 const {w,dom}=await ownerDOM({browserFocus:true,retainDialogFocus}),d=w.document;try{
  assert.equal(d.activeElement,d.body,'Initial loading must not move focus');
  const trigger=d.getElementById('create');trigger.focus();trigger.click();await tick();
  assert.equal(d.activeElement,d.querySelector('#confirmation button'));
  d.getElementById('confirmation').close('cancel');await idle(d);
  assert.equal(d.activeElement,trigger);
 }finally{dom.window.close();}
});
test('failed asynchronous work and a successful retry restore keyboard focus',async()=>{
 const {w,storage,dom}=await ownerDOM({browserFocus:true}),d=w.document;try{
  await createOwnerProject(w,storage);const fetch=w.fetch,trigger=d.getElementById('refresh');
  w.fetch=async(path,options)=>path.startsWith('/api/state?')?new Response(JSON.stringify({error:'Synthetic focus failure'}),{status:503}):fetch(path,options);
  trigger.focus();trigger.click();await idle(d);assert.match(d.getElementById('message').textContent,/Synthetic focus failure/);assert.equal(d.activeElement,trigger);
  w.fetch=fetch;trigger.click();await idle(d);assert.equal(d.getElementById('project-panel').hidden,false);assert.equal(d.activeElement,trigger);
 }finally{dom.window.close();}
});
test('settling a pending request preserves focus the owner moved to another input',async()=>{
 const {w,storage,dom}=await ownerDOM({browserFocus:true}),d=w.document;let release;try{
  await createOwnerProject(w,storage);const fetch=w.fetch,gate=new Promise(resolve=>release=resolve);let entered;const pending=new Promise(resolve=>entered=resolve);
  w.fetch=async(path,options)=>{if(path.startsWith('/api/state?')){entered();await gate;}return fetch(path,options);};
  d.getElementById('refresh').focus();d.getElementById('refresh').click();await pending;
  d.getElementById('contract').focus();release();await idle(d);assert.equal(d.activeElement,d.getElementById('contract'));
 }finally{release?.();await idle(d);dom.window.close();}
});

async function inspectOwnerArtifact(w,storage){
 const {project}=await createOwnerProject(w,storage),session=await storage.openWorker('owner',project.project_key,'Keyboard test worker'),engine=await storage.workerEngine('owner',project.project_key,session.worker_id);
 await engine.execute('claim_task',{task_id:'first-task',contract_revision:1,lease_seconds:300});
 await engine.execute('ingest_artifact',{task_id:'first-task',contract_revision:1,filename:'keyboard.txt',content:'hello keyboard'});
 await engine.execute('run_checks',{task_id:'first-task',contract_revision:1,artifact_revision:1});
 w.document.getElementById('refresh').click();await idle(w.document);w.document.querySelector('#tasks button').click();await idle(w.document);
 w.document.getElementById('decision-reason').value='Keyboard-reviewed exact bytes';
}
for(const retainDialogFocus of [false,true])for(const outcome of ['accept','reject'])test('successful '+outcome+' moves '+(retainDialogFocus?'closed-dialog':'body')+' focus to the project heading',async()=>{
 const {w,storage,dom}=await ownerDOM({browserFocus:true,retainDialogFocus}),d=w.document;try{
  await inspectOwnerArtifact(w,storage);const trigger=d.getElementById(outcome);trigger.focus();trigger.click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.equal(d.getElementById('artifact-panel').hidden,true);assert.equal(d.getElementById('project-panel').hidden,false);
  assert.equal(d.activeElement,d.getElementById('goal'));assert.equal(d.getElementById('goal').getAttribute('tabindex'),'-1');
 }finally{dom.window.close();}
});
test('a completed decision keeps focus on another input the owner selected while waiting',async()=>{
 const {w,storage,dom}=await ownerDOM({browserFocus:true,retainDialogFocus:true}),d=w.document;let release;try{
  await inspectOwnerArtifact(w,storage);const fetch=w.fetch,gate=new Promise(resolve=>release=resolve);let entered;const pending=new Promise(resolve=>entered=resolve);
  w.fetch=async(path,options)=>{if(path==='/owner/api/decide'){entered();await gate;}return fetch(path,options);};
  d.getElementById('accept').focus();d.getElementById('accept').click();await tick();d.getElementById('confirmation').close('confirm');await pending;
  d.getElementById('contract').focus();release();await idle(d);assert.equal(d.getElementById('artifact-panel').hidden,true);assert.equal(d.activeElement,d.getElementById('contract'));
 }finally{release?.();await idle(d);dom.window.close();}
});
test('a failed reload after a decision does not focus the hidden project heading',async()=>{
 const {w,storage,dom}=await ownerDOM({browserFocus:true}),d=w.document;try{
  await inspectOwnerArtifact(w,storage);const fetch=w.fetch;
  w.fetch=async(path,options)=>path.startsWith('/api/state?')?new Response(JSON.stringify({error:'Synthetic decision refresh failure'}),{status:503}):fetch(path,options);
  d.getElementById('accept').focus();d.getElementById('accept').click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.equal(d.getElementById('project-panel').hidden,true);assert.match(d.getElementById('message').textContent,/Synthetic decision refresh failure/);assert.equal(d.activeElement,d.body);
 }finally{dom.window.close();}
});

async function twoOwnerArtifacts(w, storage) {
 const d = w.document;
 const contract = JSON.parse(d.getElementById('contract').value);
 contract.goal = 'Review two reports';
 contract.original_request = 'Review each report separately';
 contract.tasks = ['trail', 'bridge'].map(id => ({
  id, title: id + ' report', dependencies: [],
  acceptance: [{id: 'present', kind: 'file_contains', value: 'report'}],
 }));
 d.getElementById('contract').value = JSON.stringify(contract);
 d.getElementById('create').click();
 await tick();
 d.getElementById('confirmation').close('confirm');
 await idle(d);
 const [project] = await storage.listProjects('owner');
 const session = await storage.openWorker('owner', project.project_key, 'Report writer');
 const engine = await storage.workerEngine('owner', project.project_key, session.worker_id);
 async function upload(id, revision) {
  const args = {task_id: id, contract_revision: 1};
  await engine.execute('ingest_artifact', {...args, filename: id + '.txt', content: id + ' report ' + revision});
  await engine.execute('run_checks', {...args, artifact_revision: revision});
 }
 for (const id of ['trail', 'bridge']) {
  await engine.execute('claim_task', {task_id: id, contract_revision: 1, lease_seconds: 300});
  await upload(id, 1);
 }
 async function refresh() {
  d.getElementById('refresh').click();
  await idle(d);
 }
 async function inspect(id) {
  const card = [...d.querySelectorAll('#tasks .task')].find(card => card.querySelector('h3').textContent === id + ' report');
  card.querySelector('button').click();
  await idle(d);
 }
 await refresh();
 return {engine, upload, refresh, inspect};
}

test('failed inspection of a second report cannot confirm the first report', async t => {
 const {w, storage, dom} = await ownerDOM();
 try {
  const d = w.document, {engine, upload, inspect} = await twoOwnerArtifacts(w, storage);
  await inspect('trail');
  d.getElementById('decision-reason').value = 'Trail report matches the survey';
  await upload('bridge', 2);
  await inspect('bridge');
  assert.match(d.getElementById('message').textContent, /STALE_ARTIFACT/);
  const panel = d.getElementById('artifact-panel'), dialog = d.getElementById('confirmation');
  let offered = null;
  if (!panel.hidden) {
   d.getElementById('accept').click();
   await tick();
   if (dialog.open) {
    offered = JSON.parse(d.getElementById('confirm-detail').textContent);
    dialog.close('confirm');
   }
   await idle(d);
  }
  const decisions = (await engine.snapshot()).tasks.map(task => [task.id, task.decisions.length]);
  t.diagnostic(JSON.stringify({requested: 'bridge', offered, decisions}));
  assert.equal(offered, null, 'A failed new inspection must retire the previous confirmation target');
  assert.deepEqual(decisions, [['trail', 0], ['bridge', 0]]);
  assert.equal(panel.hidden, true);
  assert.equal(d.getElementById('artifact-text').textContent, '');
 } finally { dom.window.close(); }
});

test('an owner can resume the original draft or decide the refreshed second report with its own reason', async () => {
 const {w, storage, dom} = await ownerDOM();
 try {
  const d = w.document, {engine, upload, refresh, inspect} = await twoOwnerArtifacts(w, storage);
  await inspect('trail');
  const reason = d.getElementById('decision-reason');
  reason.value = 'Only the trail report was reviewed';
  d.getElementById('reject').click();
  await tick();
  d.getElementById('confirmation').close('cancel');
  await idle(d);
  await upload('bridge', 2);
  await inspect('bridge');
  await inspect('trail');
  assert.equal(reason.value, 'Only the trail report was reviewed');
  await refresh();
  await inspect('bridge');
  assert.equal(d.getElementById('artifact-text').textContent, 'bridge report 2');
  assert.equal(reason.value, '', 'The previous task rationale must not be submitted for this task');
  reason.value = 'Reviewed the updated bridge report';
  d.getElementById('accept').click();
  await tick();
  const payload = JSON.parse(d.getElementById('confirm-detail').textContent);
  assert.equal(payload.task_id, 'bridge');
  assert.equal(payload.artifact_revision, 2);
  d.getElementById('confirmation').close('confirm');
  await idle(d);
  const [trail, bridge] = (await engine.snapshot()).tasks;
  assert.equal(trail.decisions.length, 0);
  assert.equal(bridge.decisions[0].reason, 'Reviewed the updated bridge report');
  assert.equal(bridge.decisions[0].artifact_revision, 2);
 } finally { dom.window.close(); }
});

for (const role of ['viewer', 'worker', 'reviewer']) {
 test('shared artifact inspection hands the decision to the owner for a ' + role, async t => {
  const {w, storage, dom} = await ownerDOM();
  try {
   const d = w.document;
   await inspectOwnerArtifact(w, storage);
   const [own] = await storage.listProjects('owner');
   const contract = JSON.parse(d.getElementById('contract').value);
   contract.project_id = 'shared-' + role;
   contract.decision_owner = await subjectActor('report-owner');
   const shared = await storage.createProject('report-owner', contract.project_id, contract);
   await storage.setMember('report-owner', shared.project_key, 'owner', role);
   const session = await storage.openWorker('report-owner', shared.project_key, 'Shared report writer');
   const engine = await storage.workerEngine('report-owner', shared.project_key, session.worker_id);
   const args = {task_id: 'first-task', contract_revision: 1};
   await engine.execute('claim_task', {...args, lease_seconds: 300});
   await engine.execute('ingest_artifact', {...args, filename: 'shared.txt', content: 'hello shared report'});
   await engine.execute('run_checks', {...args, artifact_revision: 1});
   d.getElementById('refresh').click();
   await idle(d);
   async function openArtifact(projectKey) {
    const picker = d.getElementById('projects');
    picker.value = projectKey;
    picker.dispatchEvent(new w.Event('change'));
    await idle(d);
    assert.equal(d.getElementById('artifact-panel').hidden, true);
    d.querySelector('#tasks button').click();
    await idle(d);
    assert.equal(d.getElementById('artifact-panel').hidden, false);
   }
   const offered = id => {
    const control = d.getElementById(id);
    return !control.closest('[hidden]') && !control.disabled;
   };
   await openArtifact(shared.project_key);
   const member = {
    role, bytes: d.getElementById('artifact-text').textContent, message: d.getElementById('message').textContent,
    reason: offered('decision-reason'), accept: offered('accept'), reject: offered('reject'), outcomes: [],
   };
   for (const id of ['accept', 'reject']) {
    if (!member.reason || !offered(id)) continue;
    d.getElementById('decision-reason').value = 'This shared report was inspected';
    d.getElementById(id).click();
    await tick();
    assert.equal(d.getElementById('confirmation').open, true);
    d.getElementById('confirmation').close('confirm');
    await idle(d);
    member.outcomes.push(d.getElementById('message').textContent);
   }
   member.decisions = (await engine.snapshot()).tasks[0].decisions.length;
   await openArtifact(own.project_key);
   assert.equal(d.getElementById('artifact-text').textContent, 'hello keyboard');
   assert.ok(offered('accept') && offered('reject') && offered('decision-reason'));
   d.getElementById('decision-reason').value = 'Inspected my own project';
   d.getElementById('accept').click();
   await tick();
   d.getElementById('confirmation').close('confirm');
   await idle(d);
   const ownEngine = await storage.engine('owner', own.project_key, 'human');
   const ownerDecisions = (await ownEngine.snapshot()).tasks[0].decisions;
   t.diagnostic(JSON.stringify({member, ownerDecisions: ownerDecisions.length}));
   assert.equal(ownerDecisions[0].reason, 'Inspected my own project');
   assert.equal(member.bytes, 'hello shared report');
   assert.equal(member.decisions, 0);
   assert.deepEqual([member.reason, member.accept, member.reject], [false, false, false]);
   assert.match(member.message, /project owner/i);
   assert.doesNotMatch(member.message, /record your decision/i);
  } finally { dom.window.close(); }
 });
}

test('an unavailable bookmark offers refresh and selection without implying a deletion', async t => {
 const site = fixture(), knownKey = 'a'.repeat(64);
 const {w, dom} = await ownerDOM({site, projectKey: knownKey});
 const d = w.document;
 try {
  async function refresh() {
   d.getElementById('refresh').click();
   await idle(d);
  }
  const picker = d.getElementById('projects');
  for (const pass of ['first load', 'refresh']) {
   if (pass === 'refresh') await refresh();
   const message = d.getElementById('message').textContent;
   const option = picker.selectedOptions[0].textContent;
   t.diagnostic(JSON.stringify({pass, message, option, deletePanel: !d.getElementById('privacy-panel').hidden}));
   assert.equal(d.getElementById('privacy-panel').hidden, true);
   assert.match(message, /unavailable|not in your project list/i);
   assert.doesNotMatch(message + option, /delet|eras/i);
   assert.match(message, /refresh/i);
   assert.equal(d.getElementById('revise').disabled, true);
   assert.equal(d.getElementById('grant').disabled, true);
   assert.equal(picker.disabled, false);
  }
  const contract = JSON.parse(d.getElementById('contract').value);
  Object.assign(contract, {goal: 'Survey', original_request: 'Survey this route'});
  Object.assign(contract.tasks[0], {title: 'Survey report'});
  contract.tasks[0].acceptance[0].value = 'report';
  const available = await site.storage.createProject('owner', contract.project_id, contract);
  await refresh();
  picker.value = available.project_key;
  picker.dispatchEvent(new w.Event('change'));
  await idle(d);
  assert.equal(d.getElementById('goal').textContent, 'Survey');
  assert.equal(d.getElementById('privacy-panel').hidden, false);
  assert.equal(d.getElementById('grant').disabled, false);
  assert.equal(d.getElementById('revise').disabled, false);
 } finally { dom.window.close(); }
});

test('reloading an uncertain deletion limits recovery to the initiating user and project until confirmed', async () => {
 const site = fixture(), first = await ownerDOM({site}), pages = [first];
 async function reopen(tab, key, subject='owner') {
  const page = await ownerDOM({site, subject, projectKey:key, tabStorage:{...tab.w.sessionStorage}});
  pages.push(page);
  return page;
 }
 async function confirmDeletion(page, alias) {
  const d = page.w.document;
  d.getElementById('delete-confirmation').value = alias;
  d.getElementById('delete-project').click();
  await tick();
  assert.equal(d.getElementById('confirmation').open, true);
  d.getElementById('confirmation').close('confirm');
  await idle(d);
 }
 try {
  const {project} = await createOwnerProject(first.w, site.storage);
  const fetch = first.w.fetch;
  first.w.fetch = async (path, options) => {
   const response = await fetch(path,options);
   if (path === '/owner/api/delete') throw new Error('Synthetic committed response lost');
   return response;
  };
  await confirmDeletion(first, project.alias);
  assert.equal((await site.storage.listProjects('owner')).length, 0);
  const reopened = await reopen(first, project.project_key);
  const d = reopened.w.document;
  assert.equal(d.getElementById('privacy-panel').hidden, false);
  assert.match(d.getElementById('delete-project').textContent, /retry/i);
  assert.equal(d.getElementById('delete-confirmation').value, '');
  for (const [key, subject] of [[project.project_key, 'other'], ['b'.repeat(64), 'owner']]) {
   const unrelated = await reopen(first, key, subject);
   assert.equal(unrelated.w.document.getElementById('privacy-panel').hidden, true);
  }
  await confirmDeletion(reopened, project.alias);
  assert.match(d.getElementById('message').textContent, /content deleted/i);
  const resolved = await reopen(reopened, project.project_key);
  assert.equal(resolved.w.document.getElementById('privacy-panel').hidden, true);
 } finally { for (const page of pages) page.dom.window.close(); }
});

test('a returning owner can explicitly recover a lost deletion from a fresh tab', async () => {
 const site = fixture(), first = await ownerDOM({site});
 let second;
 try {
  const {project} = await createOwnerProject(first.w, site.storage);
  const fetch = first.w.fetch;
  first.w.fetch = async (path, options) => {
   const response = await fetch(path,options);
   if (path === '/owner/api/delete') throw new Error('Lost response on first tab');
   return response;
  };
  const initial = first.w.document;
  initial.getElementById('delete-confirmation').value = project.alias;
  initial.getElementById('delete-project').click();
  await tick();
  initial.getElementById('confirmation').close('confirm');
  await idle(initial);
  second = await ownerDOM({site, projectKey:project.project_key});
  const {w} = second, d = w.document, writes = [];
  const network = w.fetch;
  w.fetch = (path,options) => { writes.push(path); return network(path,options); };
  assert.equal(d.getElementById('privacy-panel').hidden, true);
  const entry = [...d.querySelectorAll('button,summary')].find(control =>
   !control.closest('[hidden]') && /verify a deletion I previously requested/i.test(control.textContent)
  );
  assert.ok(entry, 'Offer a secondary action for a previously requested deletion');
  entry.click();
  await idle(d);
  assert.deepEqual(writes, []);
  assert.equal(d.getElementById('privacy-panel').hidden, false, 'One explicit action opens recovery');
  assert.equal(d.activeElement, d.getElementById('delete-confirmation'));
  d.getElementById('delete-project').click();
  await idle(d);
  assert.equal(d.getElementById('confirmation').open, false);
  d.getElementById('delete-confirmation').value = project.alias;
  d.getElementById('delete-project').click();
  await tick();
  d.getElementById('confirmation').close('cancel');
  await idle(d);
  assert.deepEqual(writes, []);
  d.getElementById('delete-project').click();
  await tick();
  d.getElementById('confirmation').close('confirm');
  await idle(d);
  assert.match(d.getElementById('message').textContent, /content deleted/i);
  assert.equal(writes.filter(path=>path==='/owner/api/delete').length, 1);
 } finally { first.dom.window.close(); second?.dom.window.close(); }
});

for (const role of ['viewer', 'worker', 'reviewer']) {
 test('project administration follows the selected project for a shared ' + role, async t => {
  const {w, storage, dom} = await ownerDOM(), d = w.document;
  const byId = id => d.getElementById(id);
  const offered = id => !byId(id).closest('[hidden]') && !byId(id).disabled;
  const select = async key => {
   const picker = byId('projects');
   picker.value = key;
   picker.dispatchEvent(new w.Event('change'));
   await idle(d);
  };
  async function confirm(id) {
   byId(id).click();
   await tick();
   assert.equal(byId('confirmation').open, true);
   byId('confirmation').close('confirm');
   await idle(d);
  }
  try {
   const {contract, project} = await createOwnerProject(w, storage);
   const sharedContract = {...contract, project_id: 'survey', goal: 'Shared survey', decision_owner: await subjectActor('surveyor')};
   const shared = await storage.createProject('surveyor', sharedContract.project_id, sharedContract);
   await storage.setMember('surveyor', shared.project_key, 'owner', role);
   byId('refresh').click();
   await idle(d);
   await select(shared.project_key);
   assert.equal(byId('goal').textContent, 'Shared survey');
   assert.equal(new URL(byId('board-link').href).searchParams.get('project_key'), shared.project_key);
   // Open disclosures a member can use before evaluating their actions.
   for (const summary of d.querySelectorAll('details > summary')) {
    if (!summary.closest('[hidden]') && !summary.parentElement.open) summary.click();
   }
   const sharedOffers = ['export', 'revise', 'grant'].filter(offered);
   const actions = [];
   const fetch = w.fetch;
   w.fetch = async (path, options) => {
    try {
     const response = await fetch(path, options);
     if (options.method === 'POST') actions.push({path, status: response.status});
     return response;
    } catch (error) {
     actions.push({path, error: error.message});
     throw error;
    }
   };
   if (offered('revise')) byId('change-reason').value = 'Update the survey notes';
   if (offered('grant')) byId('member-subject').value = 'new-reader';
   for (const id of sharedOffers) {
    if (id === 'export') {
     byId(id).click();
     await idle(d);
    } else {
     await confirm(id);
    }
   }
   const sharedActions = actions.splice(0);
   t.diagnostic(JSON.stringify({role, sharedOffers, sharedActions}));
   assert.equal(offered('create'), true);
   byId('contract').value = JSON.stringify({...contract, project_id: 'new-survey', goal: 'My new survey'});
   await confirm('create');
   assert.equal(byId('goal').textContent, 'My new survey');
   await select(project.project_key);
   for (const id of ['export', 'revise', 'grant']) assert.equal(offered(id), true);
   byId('contract').value = JSON.stringify({...contract, goal: 'Revised survey'});
   byId('change-reason').value = 'Clarified the survey area';
   await confirm('revise');
   assert.equal(byId('goal').textContent, 'Revised survey');
   byId('member-subject').value = 'new-reader';
   await confirm('grant');
   assert.equal((await storage.listProjects('new-reader'))[0].project_key, project.project_key);
   const downloads = [];
   w.URL.createObjectURL = () => 'blob:synthetic-export';
   w.URL.revokeObjectURL = () => {};
   w.HTMLAnchorElement.prototype.click = function() {downloads.push(this.download);};
   byId('export').click();
   await idle(d);
   assert.deepEqual(downloads, ['rumbo-my-project-export.ndjson']);
   assert.deepEqual(actions.map(a => a.path), ['/owner/api/create', '/owner/api/revise', '/owner/api/member', '/owner/api/export']);
   assert.ok(actions.every(a => a.status >= 200 && a.status < 300));
   t.diagnostic(JSON.stringify({role, ownedActions: actions, downloads}));
   await select(shared.project_key);
   assert.equal(byId('goal').textContent, 'Shared survey');
   assert.deepEqual(sharedActions, []);
   assert.deepEqual(sharedOffers, []);
   assert.ok(['export', 'revise', 'grant', 'change-reason', 'member-subject'].every(id => !offered(id)));
  } finally {dom.window.close();}
 });
}
