import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM} from 'jsdom';
const source=fs.readFileSync(new URL('../web/board.html',import.meta.url),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const snapshot={version:1,project_id:'synthetic',goal:'Preserve known context',contract_revision:1,decision_owner:'Owner',integrity:{valid:true},tasks:[{id:'one',title:'Task one',status:'produced',acceptance:[],evidence:[],decisions:[]}]};
const selector=projects=>({project_selection_required:true,projects});
const good=(key='a',alias='Shared alias')=>({project_key:key,alias,role:'owner'});
async function fixture(initial=snapshot){
 let send;const calls=[];
 const dom=new JSDOM(source,{url:'https://rumbo.test/board',runScripts:'dangerously',beforeParse(w){const parent={postMessage(m){calls.push(m);if(m.method==='ui/initialize')queueMicrotask(()=>send({id:m.id,result:{protocolVersion:'2026-01-26',hostCapabilities:{serverTools:{}},hostContext:{}}}));if(m.method==='ui/notifications/initialized'&&initial!==null)queueMicrotask(()=>send({method:'ui/notifications/tool-result',params:{structuredContent:initial}}));}};Object.defineProperty(w,'parent',{value:parent});send=data=>w.dispatchEvent(new w.MessageEvent('message',{source:parent,origin:'https://host.test',data:{jsonrpc:'2.0',...data}}));}});await tick();
 return {dom,d:dom.window.document,calls,update:async value=>{send({method:'ui/notifications/tool-result',params:{structuredContent:value}});await tick();},reply:async(call,value)=>{send({id:call.id,result:{structuredContent:value}});await tick();}};
}
const invalids={sparseArray:selector(new Array(1)),nullEntry:selector([null]),missingKey:selector([{alias:'Bad',role:'owner'}]),duplicateKey:selector([good('a','First'),good('a','Second')]),partialValid:selector([good('a'),null]),nonArray:selector({}),nonBoolean:{project_selection_required:'true',projects:[good('a')]}};
for(const kind of ['task','selector','empty'])for(const [name,payload] of Object.entries(invalids))test(`reject ${name} while preserving prior ${kind}`,async()=>{
 const initial=kind==='task'?snapshot:selector(kind==='empty'?[]:[good('old-a'),good('old-b')]);const f=await fixture(initial);try{
  const focus=kind==='task'?f.d.querySelector('#task-detail button'):kind==='selector'?f.d.querySelectorAll('#task-list button')[1]:f.d.getElementById('task-detail');focus.focus();
  const before={goal:f.d.getElementById('goal').textContent,list:f.d.getElementById('task-list').innerHTML,detail:f.d.getElementById('task-detail').innerHTML};
  await f.update(payload);
  assert.equal(f.d.getElementById('error').hidden,false,'Malformed input must produce visible error');
  assert.equal(f.d.getElementById('goal').textContent,before.goal,'Goal/selection context preserved');
  assert.equal(f.d.getElementById('task-list').innerHTML,before.list,'No partial choices');
  assert.equal(f.d.getElementById('task-detail').innerHTML,before.detail,'Known detail preserved');
  assert.equal(f.d.activeElement,focus,'Focused control survives');assert.equal(focus.isConnected,true);
  assert.equal(f.calls.filter(c=>c.method==='tools/call').length,0,'Notification causes no calls');
 }finally{f.dom.window.close();}
});
for(const target of ['status-filter','skip'])test('invalid selector preserves outside focus '+target,async()=>{const f=await fixture();try{const node=target==='skip'?f.d.querySelector('.skip'):f.d.getElementById(target);node.focus();await f.update(invalids.nullEntry);assert.equal(f.d.activeElement,node);}finally{f.dom.window.close();}});
for(const projects of [[],[good('a')],[good('a'),good('b')],[good('key["x"]#\\escape'),good('__proto__')],[{...good('a'),lifecycle:'active',owner_actor:'synthetic'}]])test('valid selector control '+JSON.stringify(projects),async()=>{const f=await fixture();try{await f.update(selector(projects));assert.equal(f.d.getElementById('error').hidden,true);assert.equal(f.d.querySelectorAll('#task-list button').length,projects.length);assert.equal(f.d.getElementById('goal').textContent,'Choose your project');if(projects.length){const button=f.d.querySelectorAll('#task-list button').item(projects.length-1);button.click();assert.equal(f.calls.at(-1).params.arguments.project_key,projects.at(-1).project_key);}}finally{f.dom.window.close();}});
test('initial malformed selector has no fabricated context then valid update recovers',async()=>{const f=await fixture(null);try{await f.update(invalids.nullEntry);assert.equal(f.d.getElementById('error').hidden,false);assert.equal(f.d.querySelectorAll('#task-list button').length,0);await f.update(selector([good('recovery')]));assert.equal(f.d.getElementById('error').hidden,true);assert.equal(f.d.querySelector('#task-list button').dataset.projectKey,'recovery');}finally{f.dom.window.close();}});
test('stale malformed refresh cannot overwrite newer valid context',async()=>{const f=await fixture();try{f.d.getElementById('refresh').click();const request=f.calls.find(c=>c.method==='tools/call');await f.update({...snapshot,goal:'Newer',contract_revision:2});await f.reply(request,invalids.nullEntry);assert.equal(f.d.getElementById('goal').textContent,'Newer');assert.equal(f.d.getElementById('error').hidden,true);}finally{f.dom.window.close();}});

for(const field of ['project_key','alias','role'])for(const bad of [undefined,'','   ',42,{},[]])test('reject invalid '+field+' '+JSON.stringify(bad),async()=>{const f=await fixture();try{const focused=f.d.querySelector('#task-detail button');focused.focus();await f.update(selector([{...good(),[field]:bad}]));assert.equal(f.d.getElementById('error').hidden,false);assert.equal(f.d.activeElement,focused);assert.equal(f.d.getElementById('goal').textContent,snapshot.goal);}finally{f.dom.window.close();}});
test('future nonempty display role remains compatible and grants no authority',async()=>{const f=await fixture();try{await f.update(selector([{...good(),role:'future-display-role'}]));assert.equal(f.d.getElementById('error').hidden,true);assert.match(f.d.querySelector('#task-list button').textContent,/future-display-role/);assert.equal(f.calls.filter(c=>c.method==='tools\/call').length,0);}finally{f.dom.window.close();}});
