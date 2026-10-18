import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM} from 'jsdom';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const snapshot=()=>({version:1,project_id:'focus-fixture',goal:'Predictable task navigation',contract_revision:1,decision_owner:'Owner',integrity:{valid:true},tasks:['one','two'].map(id=>({id,title:'Task '+id,status:'produced',acceptance:[],evidence:[],decisions:[]}))});
async function fixture(source){
 let state=snapshot(),denyCopy;
 const dom=new JSDOM(source,{url:'https://rumbo.test/board',runScripts:'dangerously',beforeParse(w){w.fetch=async()=>({ok:true,json:async()=>structuredClone(state)});Object.defineProperty(w.navigator,'clipboard',{value:{writeText:()=>new Promise((resolve,reject)=>{denyCopy=reject;})}});}});
 await tick();return {dom,d:dom.window.document,setState:value=>{state=value;},denyCopy:()=>denyCopy(new Error('Synthetic denial'))};
}
async function hostFixture(source){
 let send;const pendingCopy=[],calls=[];
 const dom=new JSDOM(source,{url:'https://rumbo.test/board',runScripts:'dangerously',beforeParse(w){
  const parent={postMessage(message){
   if(message.method==='tools/call')calls.push(message);
   if(message.method==='ui/initialize')queueMicrotask(()=>send({id:message.id,result:{protocolVersion:'2026-01-26',hostCapabilities:{serverTools:{}},hostContext:{}}}));
   if(message.method==='ui/notifications/initialized')queueMicrotask(()=>send({method:'ui/notifications/tool-result',params:{structuredContent:snapshot()}}));
  }};
  Object.defineProperty(w,'parent',{value:parent});
  Object.defineProperty(w.navigator,'clipboard',{value:{writeText:()=>new Promise((resolve,reject)=>pendingCopy.push({resolve,reject}))}});
  send=data=>w.dispatchEvent(new w.MessageEvent('message',{source:parent,origin:'https://host.test',data:{jsonrpc:'2.0',...data}}));
 }});
 await tick();
 return {dom,d:dom.window.document,pendingCopy,calls,respond:async (call,state)=>{send({id:call.id,result:{structuredContent:state}});await tick();},update:async state=>{send({method:'ui/notifications/tool-result',params:{structuredContent:state}});await tick();}};
}
const boards=[['hosted board',new URL('../web/board.html',import.meta.url)]];
const localBoard=new URL('../../rumbo/web/board.html',import.meta.url);
if(fs.existsSync(localBoard))boards.push(['local board',localBoard]);
for(const [name,url] of boards){
 const source=fs.readFileSync(url,'utf8');
 test(name+': focused task activation preserves keyboard focus on its replacement',async()=>{
  const {dom,d}=await fixture(source);try{
   const task=d.querySelectorAll('#task-list button')[1];task.focus();task.click();const selected=d.querySelector('#task-list [aria-pressed="true"]');
   assert.match(selected.textContent,/Task two/);assert.equal(d.activeElement,selected);assert.equal(selected.isConnected,true);
  }finally{dom.window.close();}
 });
 test(name+': pointer-style activation without task focus preserves another active control',async()=>{
  const {dom,d}=await fixture(source);try{
   const filter=d.getElementById('status-filter');filter.focus();d.querySelectorAll('#task-list button')[1].click();assert.equal(d.activeElement,filter);assert.match(d.querySelector('#task-detail h2').textContent,/Task two/);
  }finally{dom.window.close();}
 });
 test(name+': refresh retains an existing focused task without changing selection',async()=>{
  const {dom,d}=await fixture(source);try{
   d.querySelectorAll('#task-list button')[1].focus();d.getElementById('refresh').click();await tick();assert.equal(d.activeElement,d.querySelectorAll('#task-list button')[1]);assert.match(d.querySelector('#task-detail h2').textContent,/Task one/);
  }finally{dom.window.close();}
 });
 for(const empty of [false,true])test(name+': removal of focused task moves focus to filter; empty='+empty,async()=>{
  const {dom,d,setState}=await fixture(source);try{
   d.querySelectorAll('#task-list button')[1].focus();const next=snapshot();next.tasks=empty?[]:next.tasks.slice(0,1);setState(next);d.getElementById('refresh').click();await tick();assert.equal(d.activeElement,d.getElementById('status-filter'));assert.equal(d.querySelectorAll('#task-list button').length,empty?0:1);
  }finally{dom.window.close();}
 });
 test(name+': delayed copy failure cannot steal focus from a newly activated task',async()=>{
  const {dom,d,denyCopy}=await fixture(source);try{
   d.querySelector('#task-detail button').click();const task=d.querySelectorAll('#task-list button')[1];task.focus();task.click();denyCopy();await tick();assert.equal(d.activeElement,d.querySelector('#task-list [aria-pressed="true"]'));assert.equal(d.getElementById('handoff-text').hidden,true);
  }finally{dom.window.close();}
 });
 test(name+': asynchronous same-task snapshot retains focus on the replacement Copy handoff control',async()=>{
  const {dom,d,update}=await hostFixture(source);try{
   const previous=d.querySelector('#task-detail button');previous.focus();
   const next=snapshot();next.contract_revision=2;await update(next);
   assert.equal(previous.isConnected,false,'The original detail control was replaced');
   assert.equal(d.activeElement,d.querySelector('#task-detail button'),'Keyboard focus must not fall back to the document body');
   assert.equal(d.getElementById('contract-revision').textContent,'2');
  }finally{dom.window.close();}
 });
 test(name+': replacing a focused clipboard fallback returns to Copy without retaining stale summary bytes',async()=>{
  const {dom,d,update,pendingCopy}=await hostFixture(source);try{
   const copy=d.querySelector('#task-detail button');copy.focus();copy.click();
   pendingCopy[0].reject(new Error('Synthetic denial'));await tick();
   const previous=d.getElementById('handoff-text');assert.equal(d.activeElement,previous);assert.equal(previous.hidden,false);
   const next=snapshot();next.contract_revision=2;next.goal='Updated goal';await update(next);
   assert.equal(previous.isConnected,false);assert.equal(d.getElementById('handoff-text').hidden,true);assert.equal(d.getElementById('handoff-text').value,'');
   assert.equal(d.activeElement,d.querySelector('#task-detail button'));
   d.activeElement.click();pendingCopy[1].reject(new Error('Synthetic denial'));await tick();
   assert.match(d.getElementById('handoff-text').value,/Updated goal/);assert.match(d.getElementById('handoff-text').value,/Contract: r2/);
  }finally{dom.window.close();}
 });
 for(const change of ['remove-selected','empty','project','hosted-project-key'])test(name+': detail focus returns to task navigation when context changes: '+change,async()=>{
  const {dom,d,update}=await hostFixture(source);try{
   const initial=snapshot();initial.hosted_project_key='first-key';await update(initial);
   d.querySelector('#task-detail button').focus();const next=structuredClone(initial);
   if(change==='remove-selected')next.tasks=next.tasks.slice(1);
   if(change==='empty')next.tasks=[];
   if(change==='project')next.project_id='another-project';
   if(change==='hosted-project-key')next.hosted_project_key='different-key';
   await update(next);assert.equal(d.activeElement,d.getElementById('status-filter'));
  }finally{dom.window.close();}
 });
 for(const target of ['status-filter','task-detail'])test(name+': snapshot does not move a stable focused '+target,async()=>{
  const {dom,d,update}=await hostFixture(source);try{
   const control=d.getElementById(target);control.focus();await update(snapshot());assert.equal(d.activeElement,control);
  }finally{dom.window.close();}
 });
 for(const result of ['resolve','reject'])test(name+': obsolete clipboard '+result+' cannot affect the newly focused detail',async()=>{
  const {dom,d,update,pendingCopy}=await hostFixture(source);try{
   const copy=d.querySelector('#task-detail button');copy.focus();copy.click();await update(snapshot());
   const current=d.querySelector('#task-detail button');assert.equal(d.activeElement,current);
   pendingCopy[0][result](new Error('Synthetic old response'));await tick();
   assert.equal(d.activeElement,current);assert.equal(d.getElementById('message').textContent,'');assert.equal(d.getElementById('handoff-text').hidden,true);
  }finally{dom.window.close();}
 });
}

// Hosted selectors carry project keys/labels, not a version-1 task snapshot.
const selector=count=>({project_selection_required:true,projects:Array.from({length:count},(_,i)=>({project_key:'key-'+i,alias:'Project '+i,role:'owner'}))});
const hostedSource=fs.readFileSync(new URL('../web/board.html',import.meta.url),'utf8');
for(const count of [0,1,2])for(const control of ['copy','fallback'])test('hosted selector: replaced '+control+' focuses useful selector content; projects='+count,async()=>{
 const {dom,d,update,pendingCopy}=await hostFixture(hostedSource);try{
  const copy=d.querySelector('#task-detail button');copy.focus();
  if(control==='fallback'){copy.click();pendingCopy[0].reject(new Error('Synthetic denial'));await tick();}
  const previous=d.activeElement;await update(selector(count));
  assert.equal(previous.isConnected,false);assert.equal(d.activeElement,count?d.querySelector('#task-list button'):d.getElementById('task-detail'));
  assert.equal(d.querySelectorAll('#task-list button').length,count);assert.equal(d.getElementById('handoff-text'),null);
  assert.match(d.getElementById('task-detail').textContent,count?/Select an authorized project/:/No authorized projects yet/);
  assert.equal(d.getElementById('refresh').disabled,true,'Existing selector Refresh behavior is unchanged');
 }finally{dom.window.close();}
});
for(const count of [0,2])for(const target of ['status-filter','task-detail','skip','body'])test('hosted selector: preserves surviving '+target+' focus; projects='+count,async()=>{
 const {dom,d,update}=await hostFixture(hostedSource);try{
  const node=target==='skip'?d.querySelector('.skip'):target==='body'?d.body:d.getElementById(target);
  if(target!=='body')node.focus();assert.equal(d.activeElement,node);
  await update(selector(count));assert.equal(d.activeElement,node);
 }finally{dom.window.close();}
});
for(const count of [0,2])for(const completion of ['resolve','reject'])test('hosted selector: stale clipboard '+completion+' does not steal focus or feedback; projects='+count,async()=>{
 const {dom,d,update,pendingCopy}=await hostFixture(hostedSource);try{
  const copy=d.querySelector('#task-detail button');copy.focus();copy.click();await update(selector(count));
  const current=count?d.querySelector('#task-list button'):d.getElementById('task-detail');assert.equal(d.activeElement,current);
  pendingCopy[0][completion](new Error('Synthetic stale clipboard completion'));await tick();
  assert.equal(d.activeElement,current);assert.equal(d.getElementById('handoff-text'),null);assert.equal(d.getElementById('message'),null);
 }finally{dom.window.close();}
});
for(const mode of ['tasks','empty','filtered'])test('hosted selector: focused choice round trip lands on selected task or detail; '+mode,async()=>{
 const {dom,d,update,calls,respond}=await hostFixture(hostedSource);try{
  await update(selector(2));const choice=d.querySelectorAll('#task-list button')[1];choice.focus();choice.click();
  assert.equal(calls.length,1);assert.equal(calls[0].params.name,'rumbo_state');assert.equal(calls[0].params.arguments.project_key,'key-1');
  const next=snapshot();next.hosted_project_key='key-1';if(mode==='empty')next.tasks=[];
  if(mode==='filtered')d.getElementById('status-filter').value='accepted';
  await respond(calls[0],next);assert.equal(choice.isConnected,false);
  assert.equal(d.activeElement,mode==='tasks'?d.querySelector('#task-list [aria-pressed="true"]'):d.getElementById('task-detail'));
 }finally{dom.window.close();}
});
for(const target of ['status-filter','task-detail','skip'])test('hosted selector: pending selection response preserves moved '+target+' focus',async()=>{
 const {dom,d,update,calls,respond}=await hostFixture(hostedSource);try{
  await update(selector(2));const choice=d.querySelector('#task-list button');choice.focus();choice.click();
  const outside=target==='skip'?d.querySelector('.skip'):d.getElementById(target);outside.focus();
  await respond(calls[0],snapshot());assert.equal(d.activeElement,outside);
 }finally{dom.window.close();}
});
test('hosted selector: stale selection response cannot replace the latest project or focus',async()=>{
 const {dom,d,update,calls,respond}=await hostFixture(hostedSource);try{
  await update(selector(2));const choices=d.querySelectorAll('#task-list button');
  choices[0].focus();choices[0].click();choices[1].focus();choices[1].click();
  const latest=snapshot();latest.goal='Latest chosen project';latest.hosted_project_key='key-1';await respond(calls[1],latest);
  const current=d.querySelector('#task-list [aria-pressed="true"]');assert.equal(d.activeElement,current);
  const stale=snapshot();stale.goal='Stale project';await respond(calls[0],stale);
  assert.equal(d.getElementById('goal').textContent,'Latest chosen project');assert.equal(d.activeElement,current);
 }finally{dom.window.close();}
});

const keyedSelector=keys=>({project_selection_required:true,projects:keys.map(project_key=>({project_key,alias:'Shared alias',role:'owner'}))});
for(const keys of [['a','b','c'],['c','a','b'],['b','d'],['d'],[]])test('hosted selector navigation: exact focused key survives refresh or uses useful fallback; '+JSON.stringify(keys),async()=>{
 const {dom,d,update}=await hostFixture(hostedSource);try{
  await update(keyedSelector(['a','b','c']));const previous=d.querySelectorAll('#task-list button')[1];previous.focus();
  await update(keyedSelector(keys));assert.equal(previous.isConnected,false);
  const choices=d.querySelectorAll('#task-list button');const target=keys.length?choices[keys.includes('b')?keys.indexOf('b'):0]:d.getElementById('task-detail');
  assert.equal(d.activeElement,target,'Match the stable project key, never the alias or original list position');
  if(keys.length)assert.equal(target.dataset.projectKey,keys.includes('b')?'b':keys[0]);
 }finally{dom.window.close();}
});
for(const key of ['key["x"]#\\escape','__proto__'])test('hosted selector navigation: project key remains opaque data; '+key,async()=>{
 const {dom,d,update}=await hostFixture(hostedSource);try{
  await update(keyedSelector(['a',key,'c']));d.querySelectorAll('#task-list button')[1].focus();
  await update(keyedSelector([key,'a']));assert.equal(d.activeElement,d.querySelector('#task-list button'));assert.equal(d.activeElement.dataset.projectKey,key);
 }finally{dom.window.close();}
});
for(const count of [0,1,2])test('hosted selector navigation: focused task moves to first project or empty explanation; projects='+count,async()=>{
 const {dom,d,update}=await hostFixture(hostedSource);try{
  const previous=d.querySelectorAll('#task-list button')[1];previous.focus();await update(selector(count));
  assert.equal(previous.isConnected,false);assert.equal(d.activeElement,count?d.querySelector('#task-list button'):d.getElementById('task-detail'));
 }finally{dom.window.close();}
});
for(const target of ['status-filter','task-detail','skip','body'])for(const count of [0,2])test('hosted selector navigation: repeated selector preserves outside '+target+' focus; projects='+count,async()=>{
 const {dom,d,update}=await hostFixture(hostedSource);try{
  await update(selector(2));const outside=target==='skip'?d.querySelector('.skip'):target==='body'?d.body:d.getElementById(target);
  if(target!=='body')outside.focus();assert.equal(d.activeElement,outside);
  await update(selector(count));assert.equal(d.activeElement,outside);
 }finally{dom.window.close();}
});
test('hosted selector navigation: focus identity after reordering still sends that exact project key',async()=>{
 const {dom,d,update,calls,respond}=await hostFixture(hostedSource);try{
  await update(keyedSelector(['a','b','c']));d.querySelectorAll('#task-list button')[1].focus();await update(keyedSelector(['c','a','b']));
  assert.equal(d.activeElement,d.querySelectorAll('#task-list button')[2]);d.activeElement.click();assert.equal(calls[0].params.arguments.project_key,'b');
  const next=snapshot();next.hosted_project_key='b';await respond(calls[0],next);assert.equal(d.activeElement,d.querySelector('#task-list [aria-pressed="true"]'));
 }finally{dom.window.close();}
});
