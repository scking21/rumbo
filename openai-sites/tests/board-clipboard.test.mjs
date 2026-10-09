import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM} from 'jsdom';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const snapshot=()=>({version:1,project_id:'copy-fixture',goal:'Keep handoffs in their original context',contract_revision:1,decision_owner:'Owner',integrity:{valid:true},tasks:['one','two'].map(id=>({id,title:'Task '+id,status:'produced',acceptance:[],evidence:[],decisions:[]}))});
async function fixture(source){
 let state=snapshot();const pending=[];
 const dom=new JSDOM(source,{url:'https://rumbo.test/board',runScripts:'dangerously',beforeParse(w){w.fetch=async()=>({ok:true,json:async()=>structuredClone(state)});Object.defineProperty(w.navigator,'clipboard',{value:{writeText:summary=>new Promise((resolve,reject)=>pending.push({resolve,reject,summary}))}});}});
 await tick();return {dom,d:dom.window.document,pending,setState:value=>{state=value;}};
}
const boards=[['hosted board',new URL('../web/board.html',import.meta.url)]];
const localBoard=new URL('../../rumbo/web/board.html',import.meta.url);
// A standalone Sites source package has no sibling Python distribution.
if(fs.existsSync(localBoard))boards.push(['local board',localBoard]);
for(const [path,url] of boards){
 const source=fs.readFileSync(url,'utf8');
 for(const outcome of ['resolve','reject'])test(path+': delayed '+outcome+' cannot change a newer selected task',async()=>{
  const {dom,d,pending}=await fixture(source);try{
   d.querySelector('#task-detail button').click();const next=d.querySelectorAll('#task-list button')[1];next.click();const focused=d.querySelectorAll('#task-list button')[1];focused.focus();const message=d.getElementById('message').textContent;
   pending[0][outcome](new Error('Synthetic clipboard denial'));await tick();
   assert.equal(d.querySelector('#task-detail h2').textContent,'Task two');assert.equal(d.getElementById('message').textContent,message);assert.equal(d.getElementById('handoff-text').hidden,true);assert.equal(d.getElementById('handoff-text').value,'');assert.equal(d.activeElement,focused);
  }finally{dom.window.close();}
 });
 test(path+': delayed failure cannot populate refreshed details of the same task',async()=>{
  const {dom,d,pending,setState}=await fixture(source);try{
   d.querySelector('#task-detail button').click();const next=snapshot();next.contract_revision=2;setState(next);d.getElementById('refresh').click();await tick();pending[0].reject(new Error('Synthetic clipboard denial'));await tick();assert.equal(d.getElementById('handoff-text').hidden,true);assert.equal(d.getElementById('handoff-text').value,'');
  }finally{dom.window.close();}
 });
 test(path+': current clipboard failure still provides selectable manual fallback',async()=>{
  const {dom,d,pending}=await fixture(source);try{
   const copy=d.querySelector('#task-detail button');copy.focus();copy.click();pending[0].reject(new Error('Synthetic clipboard denial'));await tick();const fallback=d.getElementById('handoff-text');assert.equal(fallback.hidden,false);assert.match(fallback.value,/Task: one/);assert.equal(d.activeElement,fallback);assert.equal(fallback.selectionStart,0);assert.equal(fallback.selectionEnd,fallback.value.length);
  }finally{dom.window.close();}
 });
 test(path+': latest copy result wins over an older failure',async()=>{
  const {dom,d,pending}=await fixture(source);try{
   const copy=d.querySelector('#task-detail button');copy.click();copy.click();pending[1].resolve();await tick();pending[0].reject(new Error('Older denial'));await tick();assert.equal(d.getElementById('message').textContent,'Copied handoff summary');assert.equal(d.getElementById('handoff-text').hidden,true);
  }finally{dom.window.close();}
 });
 test(path+': delayed failure does not steal a newer filter focus',async()=>{
  const {dom,d,pending}=await fixture(source);try{
   const copy=d.querySelector('#task-detail button');copy.focus();copy.click();const filter=d.getElementById('status-filter');filter.focus();pending[0].reject(new Error('Synthetic denial'));await tick();assert.equal(d.getElementById('handoff-text').hidden,false);assert.equal(d.activeElement,filter);
  }finally{dom.window.close();}
 });
 test(path+': missing Clipboard API keeps the manual fallback usable',async()=>{
  const {dom,d}=await fixture(source);try{
   delete dom.window.navigator.clipboard.writeText;
   const copy=d.querySelector('#task-detail button');copy.focus();copy.click();await tick();
   assert.equal(d.getElementById('handoff-text').hidden,false);assert.match(d.getElementById('handoff-text').value,/Task: one/);assert.equal(d.activeElement,d.getElementById('handoff-text'));
  }finally{dom.window.close();}
 });
 test(path+': older success cannot overwrite a newer copy failure',async()=>{
  const {dom,d,pending}=await fixture(source);try{
   const copy=d.querySelector('#task-detail button');copy.click();copy.click();pending[1].reject(new Error('Latest denial'));await tick();pending[0].resolve();await tick();
   assert.equal(d.getElementById('message').textContent,'Select and copy the handoff summary below');assert.equal(d.getElementById('handoff-text').hidden,false);assert.match(d.getElementById('handoff-text').value,/Task: one/);
  }finally{dom.window.close();}
 });
 test(path+': switching away and back does not revive an old copy result',async()=>{
  const {dom,d,pending}=await fixture(source);try{
   d.querySelector('#task-detail button').click();d.querySelectorAll('#task-list button')[1].click();d.querySelectorAll('#task-list button')[0].click();pending[0].reject(new Error('Old denial'));await tick();
   assert.equal(d.querySelector('#task-detail h2').textContent,'Task one');assert.equal(d.getElementById('handoff-text').hidden,true);assert.equal(d.getElementById('message').textContent,'');
  }finally{dom.window.close();}
 });
 test(path+': removing all tasks while a copy is pending leaves the empty state intact',async()=>{
  const {dom,d,pending,setState}=await fixture(source);try{
   d.querySelector('#task-detail button').click();const next=snapshot();next.tasks=[];setState(next);d.getElementById('refresh').click();await tick();const empty=d.getElementById('task-detail').textContent;pending[0].reject(new Error('Old denial'));await tick();
   assert.equal(d.getElementById('task-detail').textContent,empty);assert.equal(d.getElementById('handoff-text'),null);
  }finally{dom.window.close();}
 });

}
