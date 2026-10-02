import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {canonical, parseJSON} from '../worker/codec.js';
const oracle=(raw)=>JSON.parse(spawnSync('python3',['tests/oracle.py'],{input:'{"mode":"canonical","values":'+raw+'}',encoding:'utf8'}).stdout);
test('canonical JSON preserves Python number types, Unicode order and escapes',()=>{
 const raw='[1,1.0,-0.0,1e-7,1e20,9007199254740993,0.00001,1.2345678901234567e30,{"😀":"é\\n","￿":"\\u007f"},[true,null,false]]';
 assert.deepEqual(parseJSON(raw).map(v=>canonical(v)),oracle(raw));
});
test('canonical codec rejects duplicate keys, excess nesting and non-finite numbers',()=>{
 for(const raw of ['{"a":1,"a":2}','1e999','NaN','['.repeat(65)+']'.repeat(65)])assert.throws(()=>parseJSON(raw));
});

test('Python float shortest decimal never rerounds with toFixed',()=>{const raw='[2.0174932121132912e+14,6.152744521759799e13,-9.000000000000002e14]';assert.deepEqual(parseJSON(raw).map(v=>canonical(v)),oracle(raw));});
test('twenty thousand seeded finite floats match the unchanged Python encoder',()=>{
 let seed=0x72ab90fe;const next=()=>{seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return seed>>>0;};const values=[];const bytes=new ArrayBuffer(8),view=new DataView(bytes);
 while(values.length<20000){view.setUint32(0,next());view.setUint32(4,next());const value=view.getFloat64(0);if(Number.isFinite(value))values.push(value.toExponential());}
 const raw='['+values.join(',')+']',expected=oracle(raw),actual=parseJSON(raw).map(v=>canonical(v));for(let i=0;i<actual.length;i++)assert.equal(actual[i],expected[i],values[i]);
});
