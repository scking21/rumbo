import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {JSDOM} from 'jsdom';
import {dispatch} from '../worker/protocol.js';
const version='0.1.2';
test('Sites package, lock root and actual MCP server report the prepared patch identity',async()=>{
 const pkg=JSON.parse(fs.readFileSync(new URL('../package.json',import.meta.url)));
 const lock=JSON.parse(fs.readFileSync(new URL('../package-lock.json',import.meta.url)));
 assert.equal(pkg.version,version);assert.equal(lock.version,version);assert.equal(lock.packages[''].version,version);
 const reply=await dispatch({jsonrpc:'2.0',id:1,method:'initialize',params:{protocolVersion:'2025-11-25'}},{});
 assert.equal(reply.result.serverInfo.version,version);assert.equal(reply.result.protocolVersion,'2025-11-25');
});
for(const [name,path] of [['hosted','../web/board.html'],['local','../../rumbo/web/board.html']]){
 const url=new URL(path,import.meta.url);if(!fs.existsSync(url))continue;
 test(name+' board announces the prepared app identity without changing its protocol',()=>{
  const sent=[];const dom=new JSDOM(fs.readFileSync(url,'utf8'),{url:'https://rumbo.test/board',runScripts:'dangerously',beforeParse(w){Object.defineProperty(w,'parent',{value:{postMessage:message=>sent.push(message)}});}});
  try{const init=sent.find(message=>message.method==='ui/initialize');assert.ok(init);assert.equal(init.params.appInfo.version,name==='hosted'?version:'0.1.1');assert.equal(init.params.protocolVersion,'2026-01-26');}finally{dom.window.close();}
 });
}
