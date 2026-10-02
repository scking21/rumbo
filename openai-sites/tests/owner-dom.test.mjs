import test from 'node:test';import assert from 'node:assert/strict';import {JSDOM} from 'jsdom';import {readFileSync} from 'node:fs';
import worker from '../worker/index.js';import {fixture} from './support.mjs';
async function ownerDOM(){
 const {env,storage}=fixture(),identity={'oai-authenticated-user-id':'owner','oai-authenticated-user-email':'owner@example.test'};const page=await worker.fetch(new Request('https://rumbo.test/',{headers:{...identity,'sec-fetch-mode':'navigate','sec-fetch-dest':'document'}}),env);const cookie=page.headers.get('set-cookie').split(';')[0];
 const dom=new JSDOM(await page.text(),{url:'https://rumbo.test/',runScripts:'outside-only'}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;this.returnValue='';};w.HTMLDialogElement.prototype.close=function(v=''){this.returnValue=v;this.open=false;this.dispatchEvent(new w.Event('close'));};w.HTMLElement.prototype.scrollIntoView=function(){};
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
