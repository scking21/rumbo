import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createOfflineRuntime,denyExternalFetch} from './offline-runtime.mjs';

test('every synthetic runtime constructor goes through the offline configuration factory',()=>{
 const source=readFileSync('tests/runtime.test.mjs','utf8');
 assert.doesNotMatch(source,/new\s+Miniflare\s*\(/,'Raw Miniflare defaults may fetch Request.cf metadata');
 assert.match(source,/createOfflineRuntime\(Miniflare,/);
});
test('the synthetic browser fixture rejects global Worker fetch without introducing Miniflare',()=>{
 const source=readFileSync('scripts/browser-test-server.mjs','utf8');
 assert.match(source,/globalThis\.fetch\s*=\s*denyExternalFetch/);
 assert.doesNotMatch(source,/from ['"]miniflare['"]/);
});

test('offline runtime configuration overrides ambient metadata and outbound defaults before construction',()=>{
 class CaptureRuntime{constructor(options){this.options=options;}}
 const runtime=createOfflineRuntime(CaptureRuntime,{modules:true,script:'synthetic',cf:true,telemetry:{enabled:true},outboundService:()=>{throw new Error('Caller override must not run');}});
 assert.equal(runtime.options.cf,false);assert.deepEqual(runtime.options.telemetry,{enabled:false});assert.equal(runtime.options.outboundService,denyExternalFetch);
 assert.throws(()=>runtime.options.outboundService(new Request('https://synthetic.invalid/no-egress')),/External fetch is disabled/);
 assert.equal(runtime.options.script,'synthetic');assert.equal(runtime.options.modules,true);
});
test('offline runtime rejects alternative worker or fetch-mock configuration before constructing anything',()=>{
 let constructed=false;class CaptureRuntime{constructor(){constructed=true;}}
 for(const options of [{workers:[]},{fetchMock:{}}])assert.throws(()=>createOfflineRuntime(CaptureRuntime,options),/expects one worker/);
 assert.equal(constructed,false);
});
