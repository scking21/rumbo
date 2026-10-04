/** Synthetic valid history construction, real replay, real limit append checks. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {writeFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {Engine,MAX_EVENTS,MAX_LEDGER_BYTES} from '../worker/engine.js';
import {canonical,parseJSON} from '../worker/codec.js';
import {dispatch} from '../worker/protocol.js';
import {memory,hash} from '../tests/semantic-stress-support.mjs';
const contract={project_id:'size',goal:'Size characterization',original_request:'Preserve all evidence',decision_owner:'owner',constraints:[],tasks:[{id:'one',title:'One',dependencies:[],acceptance:[{id:'review',kind:'manual_review',prompt:'Inspect'}]}]};
function row(event,rows){const payload=canonical(event),previous=rows.at(-1)?.digest??'0'.repeat(64);return {seq:rows.length+1,payload,previous,digest:createHash('sha256').update(previous+'\n'+payload).digest('hex')}}
async function history({events,bytes,question='q'}){
 const io=memory(),engine=new Engine({...io,actor:'owner',role:'human',clock:()=>1000}),state=await engine.execute('create_contract',contract);let used=io.events[0].payload.length;
 const nextEvent=async text=>{state.events_count=io.events.length;return {action:'request_decision',data:await engine.prepare('request_decision',{task_id:'one',question:text},state,1000),actor:'owner',role:'human',at:1000}};
 const append=async text=>{const next=row(await nextEvent(text),io.events);io.events.push(next);used+=next.payload.length};
 if(events)while(io.events.length<events)await append(question);
 if(bytes){
  while(true){const overhead=canonical(await nextEvent('q')).length-1;if(bytes-used<=2*(overhead+4000)+2)break;await append('q'.repeat(4000))}
  const firstOverhead=canonical(await nextEvent('q')).length-1;const probe={...state,events_count:io.events.length+1};const nextData=await engine.prepare('request_decision',{task_id:'one',question:'q'},probe,1000);const secondOverhead=canonical({action:'request_decision',data:nextData,actor:'owner',role:'human',at:1000}).length-1;
  const remaining=bytes-used-firstOverhead-secondOverhead,q1=Math.min(4000,remaining-1),q2=remaining-q1;assert.ok(q1>=1&&q1<=4000&&q2>=1&&q2<=4000);await append('q'.repeat(q1));await append('q'.repeat(q2));assert.equal(used,bytes);
 }
 return {io,engine,payloadBytes:used};
}
const cases=[{name:'small',events:1},{name:'events_one_below_limit',events:MAX_EVENTS-1},{name:'events_at_limit',events:MAX_EVENTS},{name:'bytes_one_below_limit',bytes:MAX_LEDGER_BYTES-1},{name:'bytes_exact_append_fit',bytes:MAX_LEDGER_BYTES,fillWithNext:true},{name:'bytes_at_limit',bytes:MAX_LEDGER_BYTES}];
const report={scope:'Pure synthetic histories, actual engine replay/append and direct MCP dispatch; no server/runtime/browser/network',limits:{events:MAX_EVENTS,payload_bytes:MAX_LEDGER_BYTES},cases:[]};
for(const item of cases){const started=performance.now();let fixture=await history(item);
 if(item.fillWithNext){const before=await fixture.engine.snapshot(),data=await fixture.engine.prepare('request_decision',{task_id:'one',question:'q'},before,1000),payload=canonical({action:'request_decision',data,actor:'owner',role:'human',at:1000});fixture=await history({bytes:MAX_LEDGER_BYTES-payload.length})}
 const {io,engine,payloadBytes}=fixture,state=await engine.snapshot(),raw=canonical(state);
 const result={name:item.name,events:state.events_count,payload_bytes:payloadBytes,state_bytes:Buffer.byteLength(raw),state_digest:hash(state),requests:state.requests.length};
 assert.equal(result.requests,result.events-1,'full untruncated history');
 const mcp=await dispatch({jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'rumbo_state',arguments:{project_key:'a'.repeat(64)}}},{storage:{async engine(){return engine}},subject:'synthetic-owner',origin:'https://example.invalid'});
 assert.equal(mcp.result.structuredContent.requests.length,state.requests.length);result.mcp_response_bytes=Buffer.byteLength(canonical(mcp));
 const python=spawnSync('python3',[fileURLToPath(new URL('../tests/state-size-oracle.py',import.meta.url))],{input:canonical({rows:io.events}),encoding:'utf8',maxBuffer:64*1024*1024});assert.equal(python.status,0,python.stderr);const expected=parseJSON(python.stdout);assert.equal(expected.state_digest,result.state_digest);assert.equal(expected.state_bytes,result.state_bytes);
 const head=hash(io.events);try{const after=await engine.execute('request_decision',{task_id:'one',question:'q'});result.append={events:after.events_count,requests:after.requests.length}}catch(error){result.append={error:error.code};assert.equal(hash(io.events),head,'limit rejection preserves all history')}
 assert.equal(canonical(result.append),canonical(expected.append));if(item.fillWithNext)assert.equal(io.events.reduce((n,row)=>n+row.payload.length,0),MAX_LEDGER_BYTES,'real append fills exact payload budget');result.seconds=Number(((performance.now()-started)/1000).toFixed(3));report.cases.push(result);console.log(JSON.stringify(result));
}
const output=process.argv[2]??'evidence/state-size.json';mkdirSync(dirname(output),{recursive:true});writeFileSync(output,canonical(report)+'\n');
