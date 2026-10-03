import test from 'node:test';import assert from 'node:assert/strict';import {JSDOM} from 'jsdom';import {readFileSync} from 'node:fs';
import worker from '../worker/index.js';import {fixture} from './support.mjs';
async function ownerDOM({browserFocus=false}={}){
 const {env,storage}=fixture(),identity={'oai-authenticated-user-id':'owner','oai-authenticated-user-email':'owner@example.test'};const page=await worker.fetch(new Request('https://rumbo.test/',{headers:{...identity,'sec-fetch-mode':'navigate','sec-fetch-dest':'document'}}),env);const cookie=page.headers.get('set-cookie').split(';')[0];
 const dom=new JSDOM(await page.text(),{url:'https://rumbo.test/',runScripts:'outside-only'}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(v){if(v!==undefined)this.returnValue=v;this.open=false;this.dispatchEvent(new w.Event('close'));};w.HTMLElement.prototype.scrollIntoView=function(){};
 if(browserFocus){
  // jsdom does not implement native dialog focus or the disabled-control blur
  // observed in the Chromium keyboard regressions. Model those transitions only
  // for these deterministic tests; the browser suite verifies the native behavior.
  for(const prototype of [w.HTMLButtonElement.prototype,w.HTMLSelectElement.prototype]){
   const disabled=Object.getOwnPropertyDescriptor(prototype,'disabled');
   Object.defineProperty(prototype,'disabled',{...disabled,set(value){if(value&&w.document.activeElement===this)this.blur();disabled.set.call(this,value);}});
  }
  let previousFocus;
  w.HTMLDialogElement.prototype.showModal=function(){previousFocus=w.document.activeElement;this.open=true;this.querySelector('button').focus();};
  w.HTMLDialogElement.prototype.close=function(value){if(value!==undefined)this.returnValue=value;this.open=false;if(this.contains(w.document.activeElement))w.document.activeElement.blur();previousFocus?.focus();this.dispatchEvent(new w.Event('close'));};
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
  d.getElementById('accept').click();d.getElementById('accept').click();await tick();d.getElementById('confirmation').close('confirm');d.getElementById('confirmation').close('confirm');await idle(d);
  const task=(await engine.snapshot()).tasks[0];assert.equal(task.status,'accepted');assert.equal(task.decisions.length,1);assert.equal(task.decisions[0].artifact_revision,2);
 }finally{dom.window.close();}
});


test('canceling a confirmation restores focus after the initiating button was disabled',async()=>{
 const {w,dom}=await ownerDOM({browserFocus:true}),d=w.document;try{
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
for(const outcome of ['accept','reject'])test('successful '+outcome+' moves lost focus from the hidden decision panel to the project heading',async()=>{
 const {w,storage,dom}=await ownerDOM({browserFocus:true}),d=w.document;try{
  await inspectOwnerArtifact(w,storage);const trigger=d.getElementById(outcome);trigger.focus();trigger.click();await tick();d.getElementById('confirmation').close('confirm');await idle(d);
  assert.equal(d.getElementById('artifact-panel').hidden,true);assert.equal(d.getElementById('project-panel').hidden,false);
  assert.equal(d.activeElement,d.getElementById('goal'));assert.equal(d.getElementById('goal').getAttribute('tabindex'),'-1');
 }finally{dom.window.close();}
});
test('a completed decision keeps focus on another input the owner selected while waiting',async()=>{
 const {w,storage,dom}=await ownerDOM({browserFocus:true}),d=w.document;let release;try{
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
