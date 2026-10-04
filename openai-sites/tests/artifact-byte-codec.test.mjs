import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {decodeJSONBytes,parseJSON,canonical} from '../worker/codec.js';
function encoded(text,encoding,bom){
 let bytes;
 if(encoding==='utf8')bytes=Buffer.from(text);
 else if(encoding.startsWith('utf16')){bytes=Buffer.alloc(text.length*2);for(let i=0;i<text.length;i++)encoding.endsWith('le')?bytes.writeUInt16LE(text.charCodeAt(i),i*2):bytes.writeUInt16BE(text.charCodeAt(i),i*2)}
 else{const points=[...text].map(x=>x.codePointAt(0));bytes=Buffer.alloc(points.length*4);for(let i=0;i<points.length;i++)encoding.endsWith('le')?bytes.writeUInt32LE(points[i],i*4):bytes.writeUInt32BE(points[i],i*4)}
 const marks={utf8:[239,187,191],utf16le:[255,254],utf16be:[254,255],utf32le:[255,254,0,0],utf32be:[0,0,254,255]};return bom?Buffer.concat([Buffer.from(marks[encoding]),bytes]):bytes;
}
test('artifact byte decoder matches canonical BOM/endian detection and malformed inputs',()=>{
 const cases=[];
 for(const encoding of ['utf8','utf16le','utf16be','utf32le','utf32be'])for(const bom of [false,true])for(const text of ['{"ok":true,"😀":"é"}','{"ok":false,"ok":true}','{"\\ud800":"\\udfff"}','{}','1','true','{"ok":"\\ufeff"}'])cases.push(encoded(text,encoding,bom));
 for(const encoding of ['utf16le','utf16be','utf32le','utf32be'])cases.push(encoded('{"ok":true}',encoding,false).subarray(0,-1));
 cases.push(Buffer.from([]),Buffer.from([239,187,191,239,187,191,123,125]),Buffer.from([0,0,0xff,0xff]),Buffer.from([0,0,254,255,0,17,0,0]));
 const result=spawnSync('python3',[fileURLToPath(new URL('./artifact-codec-oracle.py',import.meta.url))],{input:JSON.stringify(cases.map(b=>b.toString('base64'))),encoding:'utf8'});assert.equal(result.status,0,result.stderr);const expected=parseJSON(result.stdout);
 const actual=cases.map(bytes=>{try{return {ok:parseJSON(decodeJSONBytes(bytes),512,{duplicates:true,nonfinite:true,maxIntegerDigits:4300,scalarStrings:true})}}catch{return {error:'INVALID_ARTIFACT_JSON'}}});assert.equal(canonical(actual),canonical(expected));
});

test('artifact scalar policy rejects raw and escaped surrogates before duplicate collapse',()=>{
 const cases=[],expect=[];
 const add=(bytes,valid)=>{cases.push(bytes);expect.push(valid)};
 const surround=bytes=>Buffer.concat([Buffer.from('{"ok":true,"unused":"'),Buffer.from(bytes),Buffer.from('"}')]);
 for(const bytes of [[0xed,0xa0,0x80],[0xed,0xaf,0xbf],[0xed,0xb0,0x80],[0xed,0xbf,0xbf],[0xed,0xa0,0x80,0xed,0xb0,0x80],[...Buffer.from('é😀'),0xed,0xa0,0x80,...Buffer.from('漢字')],[0xed],[0xed,0xa0],[0xed,0xa0,0x7f],[0xc0,0x80],[0xe0,0x80,0x80],[0xf4,0x90,0x80,0x80]])add(surround(bytes),false);
 const everySurrogate=[];for(let second=0xa0;second<=0xbf;second++)for(let third=0x80;third<=0xbf;third++)everySurrogate.push(0xed,second,third);add(surround(everySurrogate),false);
 for(const content of ['{"ok":true,"unused":"\\ud800"}','{"ok":true,"unused":"\\udfff"}','{"ok":true,"\\ud800":0}','{"ok":true,"unused":"\\ud800","unused":0}','{"ok":true,"unused":["\\ud800"],"unused":0}','{"ok":true,"unused":{"\\ud800":0},"unused":0}'])add(Buffer.from(content),false);
 for(const encoding of ['utf8','utf16le','utf16be','utf32le','utf32be'])for(const bom of [false,true])for(const content of ['{"ok":true,"unused":"😀"}','{"ok":true,"unused":"\\ud83d\\ude00"}','{"😀":false,"\\ud83d\\ude00":true}','{"ok":true,"unused":"é漢字"}'])add(encoded(content,encoding,bom),true);
 for(const encoding of ['utf16le','utf16be','utf32le','utf32be'])for(const bom of [false,true])for(const surrogate of ['\ud800','\udfff'])add(encoded('{"ok":true,"unused":"'+surrogate+'"}',encoding,bom),false);
 for(const endian of ['LE','BE']){const data=Buffer.alloc(8);data['writeUInt32'+endian](0xd800,0);data['writeUInt32'+endian](0xdc00,4);const encoding='utf32'+endian.toLowerCase();add(Buffer.concat([encoded('{"ok":true,"unused":"',encoding,false),data,encoded('"}',encoding,false)]),false)}
 const result=spawnSync('python3',[fileURLToPath(new URL('./artifact-codec-oracle.py',import.meta.url))],{input:JSON.stringify(cases.map(b=>b.toString('base64'))),encoding:'utf8'});assert.equal(result.status,0,result.stderr);const expected=parseJSON(result.stdout);
 const actual=cases.map(bytes=>{try{return {ok:parseJSON(decodeJSONBytes(bytes),512,{duplicates:true,nonfinite:true,maxIntegerDigits:4300,scalarStrings:true})}}catch{return {error:'INVALID_ARTIFACT_JSON'}}});
 for(let i=0;i<cases.length;i++){assert.equal(Boolean(expected[i].ok),expect[i],'canonical scalar policy case '+i);assert.equal(Boolean(actual[i].ok),expect[i],'Sites scalar policy case '+i)}assert.equal(canonical(actual),canonical(expected));
});
