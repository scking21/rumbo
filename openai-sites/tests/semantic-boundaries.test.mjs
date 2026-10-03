import test from 'node:test';
import assert from 'node:assert/strict';
import {parseJSON} from '../worker/codec.js';
import {compare,step} from './semantic-stress-support.mjs';
const base=()=>({project_id:'boundary',goal:'Bounded work',original_request:'Compare exact typed evidence',decision_owner:'owner',constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'text',kind:'file_contains',value:'x'}]}]});
const claim=()=>step('claim_task',{task_id:'one',contract_revision:1,lease_seconds:3600},'maker','worker');
const upload=(content,filename='out.json')=>step('ingest_artifact',{task_id:'one',contract_revision:1,filename,content},'maker','worker');
const checks=artifact_revision=>step('run_checks',{task_id:'one',contract_revision:1,artifact_revision},'maker','worker');
test('cross-product of JSON numeric/value kinds yields identical exact evidence',async()=>{
 const values=['0','0.0','-0.0','1','1.0','true','false','null','"1"','9007199254740993','-9007199254740993','1e-7','1e-4','1e15','1e16','1e20','1.7976931348623157e308','5e-324','[1,1.0]','{"__proto__":1,"😀":2,"￿":3}'];
 const c=base();c.tasks[0].acceptance=values.map((raw,i)=>({id:'v'+i,kind:'json_equals',key:'value',value:parseJSON(raw)}));const steps=[step('create_contract',c),claim()];
 for(const [i,raw] of values.entries())steps.push(upload('{"value":'+raw+'}'),checks(i+1));
 const result=await compare(steps);assert.equal(result.mismatch,-1);for(let i=0;i<values.length;i++){const latest=result.results[3+2*i].ok.tasks[0].evidence.slice(-values.length);assert.equal(latest[i].outcome,'pass');assert.equal(latest.filter(e=>e.outcome==='pass').length,1,'canonical comparison preserves numeric type and signed float zero')}
});
test('Unicode scalar, lone-surrogate needles, literal escapes and codepoint limits match Python',async()=>{
 const cases=[['😀','\ud83d','fail'],['😀','\ude00','fail'],['😀','😀','pass'],['e\u0301','é','fail'],['é','e\u0301','fail'],['\ufeffhello','\ufeff','pass'],['a\u0085','a\u0085','pass'],['hello.*[](){}?+^$|\\','.*[](){}?+^$|\\','pass'],['line\r\nnext','\r\n','invalid'],['x\ud800','x','invalid_upload']];
 for(const [content,needle,outcome] of cases){const c=base();c.tasks[0].acceptance[0].value=needle;const result=await compare([step('create_contract',c),claim(),upload(content),checks(1)]);assert.equal(result.mismatch,-1);if(outcome==='invalid')assert.equal(result.results[0].error,'BAD_INPUT');else if(outcome==='invalid_upload')assert.equal(result.results[2].error,'BAD_INPUT');else assert.equal(result.results[3].ok.tasks[0].evidence.at(-1).outcome,outcome)}
 for(const n of [3999,4000,4001]){const c=base();c.goal='😀'.repeat(n);const result=await compare([step('create_contract',c)]);assert.equal(result.mismatch,-1);assert.equal(Boolean(result.results[0].ok),n<=4000)}
});
test('all integer-field boundaries reject booleans/floats and preserve allowed endpoints',async()=>{
 for(const raw of ['true','false','null','"30"','29','30','3600','3601','30.0','1e2','-1','0','9007199254740993']){const c=base(),result=await compare([step('create_contract',c),step('claim_task',{task_id:'one',contract_revision:1,lease_seconds:parseJSON(raw)},'maker','worker')]);assert.equal(result.mismatch,-1,raw);assert.equal(Boolean(result.results[1].ok),['30','3600'].includes(raw))}
});
test('filename and upload UTF-8 byte boundaries match at exact limit and above',async()=>{
 for(const filename of ['x','a'.repeat(128),'a'.repeat(129),'x.json','x.JSON','x.pem','x.PEM','a/b','a\\b','x\n','é.txt']){const result=await compare([step('create_contract',base()),claim(),upload('x',filename)]);assert.equal(result.mismatch,-1,filename)}
 for(const content of ['', 'x'.repeat(131071),'x'.repeat(131072),'x'.repeat(131073),'😀'.repeat(32768),'😀'.repeat(32768)+'x']){const result=await compare([step('create_contract',base()),claim(),upload(content)]);assert.equal(result.mismatch,-1);assert.equal(Boolean(result.results[2].ok),Buffer.byteLength(content)<=131072)}
});
test('JSON Unicode keys and duplicate/nonfinite unused fields retain current outcomes',async()=>{
 for(const key of ['😀','\ud800','__proto__','constructor','e\u0301']){const c=base();c.tasks[0].acceptance=[{id:'json',kind:'json_equals',key,value:true}];const content='{'+JSON.stringify(key)+':true}';const result=await compare([step('create_contract',c),claim(),upload(content),checks(1)]);assert.equal(result.mismatch,-1);assert.equal(result.results[3].ok.tasks[0].evidence.at(-1).outcome,key.isWellFormed()?'pass':'fail')}
 const c=base();c.tasks[0].acceptance=[{id:'json',kind:'json_equals',key:'ok',value:true}];for(const [content,outcome] of [['{"ok":false,"ok":true}','pass'],['{"ok":true,"ok":false}','fail'],['{"ok":true,"unused":NaN}','pass'],['{"ok":true,"unused":Infinity}','pass'],['{"ok":true,"unused":-Infinity}','pass'],['{"ok":true,"unused":1e999}','pass'],['{"ok":NaN}','fail'],['\ufeff{"ok":true}','pass']]){const result=await compare([step('create_contract',c),claim(),upload(content),checks(1)]);assert.equal(result.mismatch,-1);assert.equal(result.results[3].ok.tasks[0].evidence.at(-1).outcome,outcome)}
});
