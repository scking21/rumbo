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
}
