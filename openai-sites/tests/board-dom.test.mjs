import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {BOARD_HTML} from '../worker/assets.js';

const noticeText='This task is outside the current filter. Its details stay open.';
const snapshot=()=>({version:1,project_id:'filter-test',goal:'Keep selected evidence visible',contract_revision:1,decision_owner:'Synthetic owner',integrity:{valid:true},tasks:[
 {id:'accepted',title:'Accepted output',status:'accepted',acceptance:[],evidence:[],decisions:[]},
 {id:'active',title:'Active output',status:'produced',acceptance:[],evidence:[],decisions:[]}
]});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function boardDOM(){
 let state=snapshot();const requests=[];
 const dom=new JSDOM(BOARD_HTML,{url:'https://rumbo.test/board?project_key=synthetic',runScripts:'dangerously',beforeParse(w){
  w.fetch=async url=>{requests.push(url);return {ok:true,json:async()=>structuredClone(state)};};
 }});
 await tick();const d=dom.window.document;
 assert.equal(d.querySelector('#task-detail h2')?.textContent,'Accepted output');
 return {dom,d,requests,setState:value=>{state=value;},filter(value){const select=d.getElementById('status-filter');select.value=value;select.dispatchEvent(new dom.window.Event('change'));}};
}

test('board explains a retained selection outside empty and nonempty filters without losing detail state or focus',async()=>{
 const {dom,d,requests,filter}=await boardDOM();try{
  const notice=()=>d.getElementById('filter-notice');
  assert.ok(notice(),'The selected detail must have a filter notice');assert.equal(notice().hidden,true);
  d.querySelector('#task-detail button').click();await tick();
  const fallback=d.getElementById('handoff-text'),detailHeading=d.querySelector('#task-detail h2'),message=d.getElementById('message');
  assert.equal(fallback.hidden,false);assert.match(fallback.value,/Task: accepted/);
  const copyValue=fallback.value,copyMessage=message.textContent,filterControl=d.getElementById('status-filter');filterControl.focus();
  filter('attention');
  assert.equal(d.querySelectorAll('#task-list button').length,0);assert.equal(d.getElementById('list-empty').hidden,false);assert.equal(d.getElementById('list-empty').textContent,'No tasks match this filter');
  assert.equal(notice().hidden,false);assert.equal(notice().textContent,noticeText);
  filter('active');
  assert.equal(d.querySelectorAll('#task-list button').length,1);assert.match(d.getElementById('task-list').textContent,/Active output/);assert.equal(d.getElementById('list-empty').hidden,true);assert.equal(notice().hidden,false);
  assert.equal(d.querySelector('#task-detail h2'),detailHeading);assert.equal(d.getElementById('handoff-text'),fallback);assert.equal(fallback.hidden,false);assert.equal(fallback.value,copyValue);assert.equal(message.textContent,copyMessage);assert.equal(d.activeElement,filterControl);
  filter('accepted');assert.equal(notice().hidden,true);assert.equal(d.querySelector('#task-list button').getAttribute('aria-pressed'),'true');
  filter('all');assert.equal(notice().hidden,true);assert.equal(d.querySelectorAll('#task-list button').length,2);assert.equal(d.getElementById('handoff-text'),fallback);assert.equal(d.activeElement,filterControl);
  assert.deepEqual(requests,['/api/state?project_key=synthetic'],'Filtering must remain client-side');
 }finally{dom.window.close();}
});

test('board notice follows a new selection and refreshed status without changing filter or selection',async()=>{
 const {dom,d,filter,setState}=await boardDOM();try{
  filter('active');assert.equal(d.getElementById('filter-notice')?.hidden,false);
  d.querySelector('#task-list button').click();assert.equal(d.querySelector('#task-detail h2').textContent,'Active output');assert.equal(d.getElementById('filter-notice').hidden,true);assert.equal(d.querySelector('#task-list button').getAttribute('aria-pressed'),'true');
  const next=snapshot();next.tasks[1].status='accepted';setState(next);d.getElementById('refresh').click();await tick();
  assert.equal(d.getElementById('status-filter').value,'active');assert.equal(d.querySelector('#task-detail h2').textContent,'Active output');assert.equal(d.getElementById('list-empty').hidden,false);assert.equal(d.getElementById('filter-notice').hidden,false);
  setState(snapshot());d.getElementById('refresh').click();await tick();
  assert.equal(d.querySelector('#task-detail h2').textContent,'Active output');assert.equal(d.getElementById('filter-notice').hidden,true);assert.equal(d.querySelector('#task-list button').getAttribute('aria-pressed'),'true');
 }finally{dom.window.close();}
});
