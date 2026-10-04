import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,copyFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
test('new Python fixtures use the vendored canonical oracle in standalone Sites packages',()=>{
 const root=mkdtempSync(join(tmpdir(),'rumbo-standalone-oracles-')),tests=join(root,'tests');mkdirSync(tests);
 try{
  for(const name of ['oracle_core.py','semantic-stress-oracle.py','artifact-codec-oracle.py','state-size-oracle.py'])copyFileSync(fileURLToPath(new URL(name,import.meta.url)),join(tests,name));
  for(const [name,input,check] of [
   ['semantic-stress-oracle.py',{steps:[{action:'snapshot',args:{},actor:'owner',role:'human',now:1000}],full:true},result=>assert.equal(result[0].ok.events_count,0)],
   ['artifact-codec-oracle.py',[Buffer.from('{"ok":true}').toString('base64')],result=>assert.equal(result[0].ok.ok,true)],
   ['state-size-oracle.py',{rows:[]},result=>assert.equal(result.append.error,'NO_CONTRACT')]
  ]){const child=spawnSync('python3',['-I',join(tests,name)],{input:JSON.stringify(input),encoding:'utf8',cwd:root});assert.equal(child.status,0,child.stderr);check(JSON.parse(child.stdout));}
 }finally{rmSync(root,{recursive:true,force:true})}
});
