import test from 'node:test';
import assert from 'node:assert/strict';
import {compare,step} from './semantic-stress-support.mjs';
const contract=()=>({project_id:'policy',goal:'Bounded work',original_request:'Check top-level ok',decision_owner:'owner',constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'json',kind:'json_equals',key:'ok',value:true}]}]});
const steps=(content,c=contract())=>[step('create_contract',c),step('claim_task',{task_id:'one',contract_revision:1,lease_seconds:300},'maker','worker'),step('ingest_artifact',{task_id:'one',contract_revision:1,filename:'out.json',content},'maker','worker'),step('run_checks',{task_id:'one',contract_revision:1,artifact_revision:1},'maker','worker')];
for(const depth of [65,511,512,513,990])test('shared artifact JSON policy at '+depth+' open containers',async()=>{
 const content='{"ok":true,"unused":'+'['.repeat(depth-1)+'0'+']'.repeat(depth-1)+'}',result=await compare(steps(content));
 assert.equal(result.results.at(-1).ok.tasks[0].evidence.at(-1).outcome,depth<=512?'pass':'fail');assert.equal(result.mismatch,-1);
});
for(const digits of [4299,4300,4301])test('shared artifact JSON integer digits '+digits,async()=>{
 for(const sign of ['','-']){const result=await compare(steps('{"ok":true,"unused":'+sign+'9'.repeat(digits)+'}'));assert.equal(result.results.at(-1).ok.tasks[0].evidence.at(-1).outcome,digits<=4300?'pass':'fail');assert.equal(result.mismatch,-1)}
});
for(const encoding of ['utf8','utf16le','utf16be','utf32le','utf32be'])test('artifact byte encoding '+encoding,async()=>{
 const text='{"ok":true}',content=[...text].map(ch=>encoding==='utf8'?ch:encoding==='utf16le'?ch+'\0':encoding==='utf16be'?'\0'+ch:encoding==='utf32le'?ch+'\0\0\0':'\0\0\0'+ch).join('');
 const result=await compare(steps(content));assert.equal(result.results.at(-1).ok.tasks[0].evidence.at(-1).outcome,'pass');assert.equal(result.mismatch,-1);
});
test('depth scan ignores bracket characters and escaped quotes within strings',async()=>{
 const content=JSON.stringify({ok:true,unused:'["\\'.repeat(1000)}),result=await compare(steps(content));assert.equal(result.mismatch,-1);assert.equal(result.results.at(-1).ok.tasks[0].evidence.at(-1).outcome,'pass');
});
for(const depth of [1,30,55,110])test('selected expected value retains its separate serialization policy at depth '+depth,async()=>{
 let value=true;for(let i=0;i<depth;i++)value=[value];const c=contract();c.tasks[0].acceptance[0].value=value;
 const result=await compare(steps(JSON.stringify({ok:value}),c));assert.equal(result.mismatch,-1);assert.equal(result.results.at(-1).ok.tasks[0].evidence.at(-1).outcome,'pass');
});

test('new artifact policy does not rewrite historical evidence; recheck records new result',async()=>{
 const {actual,hash}=await import('./semantic-stress-support.mjs');
 const {Engine}=await import('../worker/engine.js');const {canonical,parseJSON}=await import('../worker/codec.js');const {createHash}=await import('node:crypto');
 for(const content of ['{"ok":true,"unused":'+'['.repeat(512)+'0'+']'.repeat(512)+'}', '{"ok":true,"unused":"'+String.fromCharCode(92)+'ud800"}']){
 const result=await actual(steps(content)),io=result.io;
 const row=io.events.at(-1),event=parseJSON(row.payload);assert.equal(event.data.evidence[0].outcome,'fail');event.data.evidence[0].outcome='pass';row.payload=canonical(event);row.digest=createHash('sha256').update(row.previous+'\n'+row.payload).digest('hex');
 const owner=new Engine({...io,actor:'owner',role:'human',clock:()=>1000}),old=hash(io.events);assert.equal((await owner.snapshot()).tasks[0].status,'checks_passed');assert.equal(hash(io.events),old);
 assert.equal((await owner.execute('decide',{task_id:'one',contract_revision:1,artifact_revision:1,outcome:'accepted',reason:'Historical receipt'})).tasks[0].status,'accepted');
 const state=await owner.execute('run_checks',{task_id:'one',contract_revision:1,artifact_revision:1});assert.equal(state.tasks[0].evidence[0].outcome,'pass');assert.equal(state.tasks[0].evidence.at(-1).outcome,'fail');assert.equal(state.tasks[0].status,'produced');
 }
});

test('valid UTF-8 uploads cannot create UTF-16/32 surrogate key collisions',async()=>{
 const cases=[];
 const received=(text,width)=>{const bytes=Buffer.alloc(text.length*width);for(let i=0;i<text.length;i++)width===2?bytes.writeUInt16BE(text.charCodeAt(i),i*width):bytes.writeUInt32BE(text.charCodeAt(i),i*width);return new TextDecoder('utf-8',{fatal:true}).decode(bytes)};
 for(const [high,low] of [[0xd8a0,0xdc80],[0xd9bf,0xddbf],[0xdbbf,0xdfbf]])for(const literalHigh of [true,false])for(const first of [true,false]){
  const key=String.fromCodePoint(0x10000+((high-0xd800)<<10)+low-0xdc00),mixed=literalHigh?String.fromCharCode(high)+(String.fromCharCode(92)+'u')+low.toString(16):(String.fromCharCode(92)+'u')+high.toString(16)+String.fromCharCode(low),text='{"'+key+'":'+first+',"'+mixed+'":'+!first+'}';cases.push({key,content:received(text,2)});
 }
 for(const first of [true,false]){
  const high=0xd8b6,low=0xdca1,key=String.fromCodePoint(0x10000+((high-0xd800)<<10)+low-0xdc00),left=Buffer.from('{"'),right=Buffer.from('":'+first+',"'),end=Buffer.from('":'+!first+'}');
  const encodeASCII=b=>{const out=Buffer.alloc(b.length*4);for(let i=0;i<b.length;i++)out.writeUInt32BE(b[i],i*4);return out},scalar=Buffer.alloc(4),surrogates=Buffer.alloc(8);scalar.writeUInt32BE(key.codePointAt(0));surrogates.writeUInt32BE(high);surrogates.writeUInt32BE(low,4);cases.push({key,content:new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat([encodeASCII(left),scalar,encodeASCII(right),surrogates,encodeASCII(end)]))});
 }
 for(const item of cases){const c=contract();c.tasks[0].acceptance[0].key=item.key;const result=await compare(steps(item.content,c));assert.equal(result.results.at(-1).ok.tasks[0].evidence.at(-1).outcome,'fail');assert.equal(result.mismatch,-1)}
});
